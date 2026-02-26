import json
import csv
import os
import re
import ssl
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
import hashlib

import librosa
import librosa.display
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import certifi
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
try:
    import edge_tts
except Exception:  # pragma: no cover - optional dependency at runtime
    edge_tts = None

matplotlib.use("Agg")

USER_ID = "demo_user"
MAX_DURATION_SECONDS = 30
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
PREDICT_MIN_SAMPLES = 3
FEATURE_VERSION = "v1.1"
FEATURE_SCHEMA = {
    "version": FEATURE_VERSION,
    "fields": [
        "duration_sec",
        "sample_rate",
        "rms",
        "spectral_centroid",
        "spectral_rolloff",
        "spectral_bandwidth",
        "zero_crossing_rate",
        "mfcc_mean[13]",
        "mfcc_var[13]",
        "top_peaks[{hz,magnitude}]",
        "harmonicity",
        "energy_distribution{low,mid,high}",
    ],
    "compatibility": "Older rows without feature_version are treated as pre-versioned and still readable.",
}

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
GENERATED_DIR = BASE_DIR / "generated"
DATA_DIR = BASE_DIR / "data"
HISTORY_PATH = DATA_DIR / "history.jsonl"
AUDIT_LOG_PATH = DATA_DIR / "audit_log.jsonl"
RADAR_SETTINGS_PATH = DATA_DIR / "radar_settings.json"
QUICK_RECAP_LOG_PATH = DATA_DIR / "quick_recap_log.json"
RADAR_DB_PATH = DATA_DIR / "radarbrief_v1.sqlite3"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    recording_id: str | None = None


class OutcomeRequest(BaseModel):
    recording_id: str | None = None
    happened: bool


class RadarSettingsRequest(BaseModel):
    watchlist: list[str]
    crypto_toggle: bool
    language: str


class BriefRequest(BaseModel):
    mode: str = "Preview"
    language: str = "Chinese"
    duration_min: int = 5
    quick_recap: bool = False
    brief_type: str = "premarket"


class TtsRequest(BaseModel):
    text: str
    language: str = "Chinese"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(RADAR_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_radar_db() -> None:
    with _db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS radar_events (
                event_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT,
                source TEXT NOT NULL,
                url TEXT,
                publisher TEXT,
                published TEXT,
                category TEXT,
                direction TEXT,
                strength INTEGER,
                confidence INTEGER,
                why_you TEXT,
                trigger TEXT,
                meta_line TEXT,
                details_json TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS brief_usage (
                day TEXT PRIMARY KEY,
                quick_count INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS options_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                contract_key TEXT NOT NULL,
                call_put TEXT NOT NULL,
                strike REAL NOT NULL,
                expiry TEXT NOT NULL,
                volume REAL NOT NULL,
                open_interest REAL NOT NULL,
                premium_estimate REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_options_contract_time ON options_observations(contract_key, observed_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_options_symbol_time ON options_observations(symbol, observed_at)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO app_meta(key, value) VALUES('schema_version', '1')"
        )
        conn.commit()


def _upsert_radar_events(events: list[dict]) -> None:
    if not events:
        return
    now = _now_iso()
    with _db_conn() as conn:
        for e in events:
            conn.execute(
                """
                INSERT INTO radar_events(
                    event_key, title, summary, source, url, publisher, published, category,
                    direction, strength, confidence, why_you, trigger, meta_line, details_json, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(event_key) DO UPDATE SET
                    title=excluded.title,
                    summary=excluded.summary,
                    source=excluded.source,
                    url=excluded.url,
                    publisher=excluded.publisher,
                    published=excluded.published,
                    category=excluded.category,
                    direction=excluded.direction,
                    strength=excluded.strength,
                    confidence=excluded.confidence,
                    why_you=excluded.why_you,
                    trigger=excluded.trigger,
                    meta_line=excluded.meta_line,
                    details_json=excluded.details_json,
                    updated_at=excluded.updated_at
                """,
                (
                    e.get("event_key"),
                    e.get("title"),
                    e.get("summary"),
                    e.get("source"),
                    e.get("url"),
                    e.get("publisher"),
                    e.get("published"),
                    e.get("category"),
                    e.get("direction"),
                    e.get("strength"),
                    e.get("confidence"),
                    e.get("why_you"),
                    e.get("trigger"),
                    e.get("meta_line"),
                    json.dumps(e.get("details", {}), ensure_ascii=False),
                    now,
                ),
            )
        conn.commit()


def _load_recent_radar_events(limit: int = 20) -> list[dict]:
    with _db_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM radar_events
            ORDER BY COALESCE(published, updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "event_key": r["event_key"],
                "title": r["title"],
                "summary": r["summary"],
                "source": r["source"],
                "url": r["url"],
                "publisher": r["publisher"] or r["source"],
                "published": r["published"],
                "category": r["category"] or "macro",
                "direction": r["direction"] or "uncertain",
                "strength": int(r["strength"] or 30),
                "confidence": int(r["confidence"] or 35),
                "why_you": r["why_you"] or "",
                "trigger": r["trigger"] or "",
                "meta_line": r["meta_line"] or "",
                "details": json.loads(r["details_json"] or "{}"),
            }
        )
    return out


def _load_radar_settings() -> dict:
    default_settings = {
        "watchlist": ["SPY", "QQQ", "BTC", "ETH"],
        "crypto_priority": True,
        "language": "Chinese",
    }
    if not RADAR_SETTINGS_PATH.exists():
        RADAR_SETTINGS_PATH.write_text(json.dumps(default_settings, ensure_ascii=False, indent=2), encoding="utf-8")
        return default_settings
    try:
        payload = json.loads(RADAR_SETTINGS_PATH.read_text(encoding="utf-8"))
        watchlist = payload.get("watchlist", default_settings["watchlist"])
        watchlist = [str(x).strip().upper() for x in watchlist if str(x).strip()][:6]
        if not watchlist:
            watchlist = default_settings["watchlist"]
        language = payload.get("language", default_settings["language"])
        if language not in ("Chinese", "English"):
            language = default_settings["language"]
        crypto_priority = bool(payload.get("crypto_priority", default_settings["crypto_priority"]))
        cleaned = {"watchlist": watchlist, "crypto_priority": crypto_priority, "language": language}
        RADAR_SETTINGS_PATH.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        return cleaned
    except Exception:
        RADAR_SETTINGS_PATH.write_text(json.dumps(default_settings, ensure_ascii=False, indent=2), encoding="utf-8")
        return default_settings


def _save_radar_settings(settings: dict) -> dict:
    watchlist = settings.get("watchlist", ["SPY", "QQQ", "BTC", "ETH"])
    watchlist = [str(x).strip().upper() for x in watchlist if str(x).strip()][:6]
    if not watchlist:
        watchlist = ["SPY", "QQQ", "BTC", "ETH"]
    cleaned = {
        "watchlist": watchlist,
        "crypto_priority": bool(settings.get("crypto_priority", True)),
        "language": "Chinese" if settings.get("language") == "Chinese" else "English",
    }
    RADAR_SETTINGS_PATH.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    return cleaned


def _fetch_text(url: str, timeout: float = 8.0) -> str:
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    req = UrlRequest(
        url,
        headers={
            "User-Agent": "RadarBrief/1.0 (demo contact: radarbrief@example.com)",
            "Accept": "application/xml,application/rss+xml,text/xml,text/html,application/json",
        },
    )
    with urlopen(req, timeout=timeout, context=ssl_ctx) as res:
        return res.read().decode("utf-8", errors="ignore")


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc) - timedelta(days=3650)
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc)
    except Exception:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return datetime.now(timezone.utc) - timedelta(days=3650)


def _fetch_rss_items(url: str, source_name: str, limit: int = 6) -> tuple[list[dict], str | None]:
    try:
        xml_text = _fetch_text(url)
        root = ET.fromstring(xml_text)
        items: list[dict] = []
        for node in root.findall(".//item"):
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            desc = _strip_html(node.findtext("description") or node.findtext("content:encoded") or "")
            pub = node.findtext("pubDate") or node.findtext("published") or node.findtext("updated")
            if title and link:
                items.append(
                    {
                        "title": title,
                        "link": link,
                        "summary": desc[:220],
                        "published": _parse_dt(pub).isoformat(),
                        "source": source_name,
                    }
                )
            if len(items) >= limit:
                break
        if not items:
            for node in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title = (node.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link = ""
                for ln in node.findall("{http://www.w3.org/2005/Atom}link"):
                    href = ln.attrib.get("href")
                    if href:
                        link = href
                        break
                summary = _strip_html(
                    node.findtext("{http://www.w3.org/2005/Atom}summary")
                    or node.findtext("{http://www.w3.org/2005/Atom}content")
                    or ""
                )
                pub = node.findtext("{http://www.w3.org/2005/Atom}updated") or node.findtext(
                    "{http://www.w3.org/2005/Atom}published"
                )
                if title and link:
                    items.append(
                        {
                            "title": title,
                            "link": link,
                            "summary": summary[:220],
                            "published": _parse_dt(pub).isoformat(),
                            "source": source_name,
                        }
                    )
                if len(items) >= limit:
                    break
        return items, None
    except (ET.ParseError, URLError, TimeoutError, ValueError, OSError) as exc:
        return [], f"Source not connected: {source_name} ({exc.__class__.__name__})"


def _fetch_json(url: str, timeout: float = 12.0, headers: dict | None = None) -> dict:
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    req_headers = {
        "User-Agent": "RadarBrief/1.0 (demo contact: radarbrief@example.com)",
        "Accept": "application/json,text/json,*/*",
    }
    if headers:
        req_headers.update(headers)
    req = UrlRequest(url, headers=req_headers)
    with urlopen(req, timeout=timeout, context=ssl_ctx) as res:
        return json.loads(res.read().decode("utf-8", errors="ignore"))


def _fetch_text_with_headers(url: str, timeout: float = 12.0, headers: dict | None = None) -> str:
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    req_headers = {"User-Agent": "RadarBrief/1.0 (demo contact: radarbrief@example.com)"}
    if headers:
        req_headers.update(headers)
    req = UrlRequest(url, headers=req_headers)
    with urlopen(req, timeout=timeout, context=ssl_ctx) as res:
        return res.read().decode("utf-8", errors="ignore")


def _tradier_expirations(symbol: str, token: str) -> list[str]:
    q = urlencode({"symbol": symbol, "includeAllRoots": "true", "strikes": "false"})
    url = f"https://api.tradier.com/v1/markets/options/expirations?{q}"
    obj = _fetch_json(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    dates = (((obj.get("expirations") or {}).get("date")) or [])
    if isinstance(dates, str):
        return [dates]
    return [d for d in dates if isinstance(d, str)]


def _tradier_chain(symbol: str, expiry: str, token: str) -> list[dict]:
    q = urlencode({"symbol": symbol, "expiration": expiry, "greeks": "false"})
    url = f"https://api.tradier.com/v1/markets/options/chains?{q}"
    obj = _fetch_json(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    options = (((obj.get("options") or {}).get("option")) or [])
    if isinstance(options, dict):
        options = [options]
    out: list[dict] = []
    for o in options:
        try:
            cp = "C" if str(o.get("option_type", "")).lower().startswith("c") else "P"
            strike = float(o.get("strike") or 0.0)
            vol = float(o.get("volume") or 0.0)
            oi = float(o.get("open_interest") or 0.0)
            bid = float(o.get("bid") or 0.0)
            ask = float(o.get("ask") or 0.0)
            last = float(o.get("last") or 0.0)
            mid = ((bid + ask) / 2.0) if (bid > 0 and ask > 0) else last
            premium = max(0.0, mid * 100.0 * max(0.0, vol))
            contract_key = f"{symbol}-{expiry}-{cp}-{strike:.2f}"
            out.append(
                {
                    "symbol": symbol,
                    "expiry": expiry,
                    "call_put": cp,
                    "strike": strike,
                    "volume": vol,
                    "open_interest": oi,
                    "premium_estimate": premium,
                    "contract_key": contract_key,
                }
            )
        except Exception:
            continue
    return out


def _store_options_observations(rows: list[dict]) -> None:
    if not rows:
        return
    now = _now_iso()
    with _db_conn() as conn:
        conn.executemany(
            """
            INSERT INTO options_observations(
                observed_at, symbol, contract_key, call_put, strike, expiry, volume, open_interest, premium_estimate
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    now,
                    r["symbol"],
                    r["contract_key"],
                    r["call_put"],
                    r["strike"],
                    r["expiry"],
                    r["volume"],
                    r["open_interest"],
                    r["premium_estimate"],
                )
                for r in rows
            ],
        )
        conn.commit()


def _option_baselines(symbol: str, contract_key: str) -> dict:
    with _db_conn() as conn:
        c_rows = conn.execute(
            """
            SELECT volume, open_interest FROM options_observations
            WHERE contract_key = ?
            ORDER BY observed_at DESC LIMIT 60
            """,
            (contract_key,),
        ).fetchall()
        s_rows = conn.execute(
            """
            SELECT volume FROM options_observations
            WHERE symbol = ?
            ORDER BY observed_at DESC LIMIT 60
            """,
            (symbol,),
        ).fetchall()
    c_vol = np.array([float(r["volume"]) for r in c_rows], dtype=np.float64)
    s_vol = np.array([float(r["volume"]) for r in s_rows], dtype=np.float64)
    return {
        "contract_n": int(len(c_vol)),
        "contract_mean": float(c_vol.mean()) if len(c_vol) else 0.0,
        "contract_std": float(c_vol.std()) if len(c_vol) else 0.0,
        "symbol_mean": float(s_vol.mean()) if len(s_vol) else 0.0,
    }


def _cboe_market_baseline() -> tuple[dict, str | None]:
    url = "https://cdn.cboe.com/api/global/us_options/market_statistics/daily_volume.csv"
    try:
        txt = _fetch_text_with_headers(url)
        reader = csv.DictReader(txt.splitlines())
        values = []
        for row in reader:
            for key in ("total_volume", "equity_options", "equity_option_volume", "equity"):
                if key in row and row.get(key):
                    try:
                        values.append(float(str(row[key]).replace(",", "")))
                        break
                    except Exception:
                        continue
        arr = np.array(values[-60:], dtype=np.float64) if values else np.array([], dtype=np.float64)
        if len(arr) < 5:
            return {"mean": 0.0, "std": 0.0, "n": int(len(arr))}, "Source not connected: Cboe baseline"
        return {"mean": float(arr.mean()), "std": float(arr.std()), "n": int(len(arr))}, None
    except Exception:
        return {"mean": 0.0, "std": 0.0, "n": 0}, "Source not connected: Cboe baseline"


def _sec_direction_and_magnitude(text: str) -> tuple[str, str]:
    t = (text or "").lower()
    if any(k in t for k in ["new position", "initiated", "acquired", "purchase", "bought"]):
        direction = "new" if "new" in t or "initiated" in t else "increase"
    elif any(k in t for k in ["reduced", "decrease", "sold", "disposed", "exit", "terminated"]):
        direction = "exit" if "exit" in t or "terminated" in t else "decrease"
    else:
        direction = "uncertain"
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", text or "")
    if pct:
        return direction, f"{pct.group(1)}%"
    shares = re.search(r"([\d,]+)\s+shares", (text or "").lower())
    if shares:
        return direction, f"{shares.group(1)} shares"
    value = re.search(r"\$([\d,]+(?:\.\d+)?[mb]?)", (text or "").lower())
    if value:
        return direction, f"${value.group(1)}"
    return direction, "not disclosed"

def _classify_sentiment(text: str) -> str:
    t = text.lower()
    bear_keys = ["cut outlook", "downgrade", "miss", "layoff", "probe", "war", "tariff", "fall", "drop", "lawsuit"]
    bull_keys = ["beat", "raise outlook", "approval", "deal", "buyback", "growth", "gain", "surge", "record high"]
    if any(k in t for k in bear_keys):
        return "Bear"
    if any(k in t for k in bull_keys):
        return "Bull"
    return "Uncertain"


def _direction_value(sentiment: str) -> str:
    s = (sentiment or "").lower()
    if s == "bull":
        return "bull"
    if s == "bear":
        return "bear"
    return "uncertain"


def _hours_ago(iso_ts: str | None) -> str:
    if not iso_ts:
        return "time unknown"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        h = max(0, int(delta.total_seconds() // 3600))
        return f"{h}h ago"
    except Exception:
        return "time unknown"


def _category_from_text(text: str, source: str) -> str:
    t = f"{text} {source}".lower()
    if any(k in t for k in ["tariff", "sanction", "war", "policy", "white house", "ministry"]):
        return "politics-policy"
    if any(k in t for k in ["cpi", "pce", "gdp", "nfp", "unemployment", "pmi", "housing"]):
        return "macro"
    if any(k in t for k in ["fed", "ecb", "rate", "yield", "qt", "qe"]):
        return "rates-liquidity"
    if any(k in t for k in ["opec", "oil", "gas", "gold", "silver", "dxy"]):
        return "commodities"
    if any(k in t for k in ["earnings", "guidance", "merger", "acquisition", "lawsuit", "ceo", "ipo", "offering"]):
        return "company"
    if any(k in t for k in ["fda", "trial", "phase", "drug"]):
        return "health-biotech"
    if any(k in t for k in ["index", "rebalance", "option", "upgrade", "downgrade"]):
        return "capital-markets"
    if any(k in t for k in ["bitcoin", "crypto", "ethereum", "exchange hack"]):
        return "crypto"
    return "macro"


def _impact_line(category: str, direction: str, targets: list[str]) -> str:
    lead = "support" if direction == "bull" else "pressure" if direction == "bear" else "uncertain"
    mapping = {
        "rates-liquidity": "rates -> bonds / growth / gold",
        "commodities": "oil -> energy / airlines / inflation",
        "politics-policy": "policy -> supply chain / industry / risk appetite",
        "macro": "macro -> index mood / yield direction",
        "company": "company event -> single name / peers",
        "health-biotech": "FDA/trial -> biotech risk/reward",
        "capital-markets": "market structure -> index and sector flows",
        "crypto": "crypto macro link -> BTC / ETH / risk mood",
    }
    return f"{lead} on {', '.join(targets)} · {mapping.get(category, 'market impact map')}"


def _targets_for_event(text: str, watchlist: list[str]) -> list[str]:
    t = text.lower()
    targets: list[str] = []
    key_map = {
        "inflation": ["SPY", "QQQ", "TLT", "DXY"],
        "fed": ["SPY", "QQQ", "TLT", "DXY"],
        "rate": ["SPY", "TLT", "DXY"],
        "oil": ["XLE", "USO"],
        "crypto": ["BTC", "ETH", "COIN"],
        "bitcoin": ["BTC", "COIN"],
        "ethereum": ["ETH"],
        "nvidia": ["NVDA", "SMH"],
        "apple": ["AAPL", "QQQ"],
        "tesla": ["TSLA"],
        "sec": ["SPY", "QQQ"],
    }
    for k, vs in key_map.items():
        if k in t:
            for v in vs:
                if v not in targets:
                    targets.append(v)
    for w in watchlist:
        if w.lower() in t and w not in targets:
            targets.append(w)
    if not targets:
        targets = watchlist[:2] if watchlist else ["SPY", "QQQ"]
    return targets[:3]


def _build_event_card(event: dict, watchlist: list[str], tier: str) -> dict:
    title = event.get("title", "No headline")
    summary = event.get("summary", "")
    merged = f"{title}. {summary}".strip()
    sentiment = _classify_sentiment(merged)
    direction = _direction_value(sentiment)
    targets = _targets_for_event(merged, watchlist)
    category = _category_from_text(merged, event.get("source", ""))
    wl_hit = next((w for w in watchlist if w.lower() in merged.lower()), watchlist[0] if watchlist else "SPY")
    trigger_target = targets[0] if targets else wl_hit
    source_weight = 30 if "SEC" in event.get("source", "") or "Fed" in event.get("source", "") or "BLS" in event.get("source", "") else 20
    confidence = max(20, min(95, source_weight + (10 if event.get("summary") else 0)))
    strength = max(20, min(95, 40 + (15 if direction != "uncertain" else 0) + (10 if len(targets) > 1 else 0)))
    meta_line = f"1 source • {_hours_ago(event.get('published'))}"
    evidence = [f"{event.get('source', 'News')} headline: {title}"]
    if summary:
        evidence.append(summary[:140])
    evidence.append(f"Linked market focus: {', '.join(targets)}")
    if confidence < 45:
        evidence.append("Low confidence: waiting for more independent confirmation.")
    card = {
        "event_key": event.get("event_key") or hashlib.sha1(f"{title}|{event.get('link','')}".encode("utf-8")).hexdigest()[:16],
        "source": event.get("source", "Unknown"),
        "title": title[:120],
        "direction": direction,
        "strength": strength,
        "confidence": confidence,
        "why_you": f"Because you watch or hold {wl_hit}",
        "next_step": f"If {trigger_target} breaks its recent range, then reassess exposure.",
        "meta_line": meta_line,
        "category": category,
        "impact_line": _impact_line(category, direction, targets),
        "published": event.get("published"),
        "url": event.get("link", ""),
        "publisher": event.get("source", "Unknown"),
        "details": {
            "evidence_bullets": evidence[:3],
            "chain_3_nodes": [
                "News lands",
                f"People react ({direction})",
                f"Price focus moves to {targets[0] if targets else wl_hit}",
            ],
            "trust_reason": "Confidence uses source quality, source count, and conflict checks.",
            "source_links": [
                {
                    "label": event.get("source", "Source"),
                    "url": event.get("link", ""),
                    "publisher": event.get("source", "Source"),
                    "published": event.get("published"),
                    "title": title[:120],
                }
            ],
        },
    }
    return card


def _connected_source_count(payload: dict) -> int:
    return sum(1 for s in payload.get("source_status", []) if s.get("ok"))


def _trust_level(connected_count: int) -> str:
    if connected_count >= 6:
        return "High"
    if connected_count >= 4:
        return "Med"
    return "Low"


def _load_quick_recap_log() -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    default_obj = {"date": today, "count": 0}
    if not QUICK_RECAP_LOG_PATH.exists():
        QUICK_RECAP_LOG_PATH.write_text(json.dumps(default_obj), encoding="utf-8")
        return default_obj
    try:
        data = json.loads(QUICK_RECAP_LOG_PATH.read_text(encoding="utf-8"))
        if data.get("date") != today:
            data = default_obj
            QUICK_RECAP_LOG_PATH.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception:
        QUICK_RECAP_LOG_PATH.write_text(json.dumps(default_obj), encoding="utf-8")
        return default_obj


def _save_quick_recap_log(log_obj: dict) -> None:
    QUICK_RECAP_LOG_PATH.write_text(json.dumps(log_obj), encoding="utf-8")


def _brief_disclaimer(language: str) -> str:
    if language == "Chinese":
        return "提醒：这只是公开信息整理，不是投资建议。请按自己的计划和风险承受能力做决定。"
    return "Reminder: this is a public-information summary, not investment advice. Make decisions with your own plan and risk tolerance."


def _collect_public_sources(settings: dict) -> dict:
    _init_radar_db()
    macro_sources = [
        ("Fed Monetary Releases", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
        ("BLS Latest Releases", "https://www.bls.gov/feed/bls_latest.rss"),
        ("BEA News", "https://www.bea.gov/news/rss.xml"),
    ]
    sec_sources = [
        ("SEC EDGAR 8-K", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-k&count=20&output=atom"),
        ("SEC EDGAR 13D/13G", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC%2013&count=20&output=atom"),
        ("SEC EDGAR Form 4", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&count=20&output=atom"),
    ]
    rss_sources = [
        ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
        ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("MarketWatch Top Stories", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
        ("Yahoo Finance News", "https://finance.yahoo.com/news/rssindex"),
        ("Investing.com News", "https://www.investing.com/rss/news.rss"),
    ]
    source_status: list[dict] = []
    connection_notes: list[str] = []
    fetched: list[dict] = []

    for name, url in (macro_sources + sec_sources + rss_sources):
        items, err = _fetch_rss_items(url, name, limit=5)
        source_status.append({"name": name, "ok": not err, "message": err or "Connected", "url": url})
        if err:
            connection_notes.append("Source not connected")
        fetched.extend(items)

    # Verified options proxy sources: Tradier chain + Cboe baseline.
    tradier_token = os.getenv("TRADIER_TOKEN", "").strip()
    cboe_base, cboe_err = _cboe_market_baseline()
    source_status.append(
        {
            "name": "Tradier Options Chains API",
            "ok": bool(tradier_token),
            "message": "Connected" if tradier_token else "Source not connected",
            "url": "https://documentation.tradier.com/brokerage-api/markets/get-options-chains",
        }
    )
    source_status.append(
        {
            "name": "Cboe Historical Options Volume",
            "ok": not cboe_err,
            "message": cboe_err or "Connected",
            "url": "https://cdn.cboe.com/api/global/us_options/market_statistics/daily_volume.csv",
        }
    )

    cards = [_build_event_card(e, settings.get("watchlist", []), "Tier2") for e in fetched]
    cards.sort(key=lambda x: x.get("published") or "", reverse=True)

    if cards:
        _upsert_radar_events(cards[:30])
    db_cards = _load_recent_radar_events(limit=30)
    cards = db_cards or cards

    watchlist = settings.get("watchlist", ["SPY", "QQQ", "BTC", "ETH"])
    if settings.get("crypto_priority"):
        watchlist = [x for x in watchlist if x in ("BTC", "ETH")] + [x for x in watchlist if x not in ("BTC", "ETH")]
    watchlist_view = watchlist[:4]
    top3 = cards[:3]
    while len(top3) < 3:
        top3.append(
            {
                "title": "Data source not connected",
                "direction": "uncertain",
                "strength": 20,
                "confidence": 20,
                "why_you": f"Because you watch or hold {watchlist_view[0] if watchlist_view else 'SPY'}",
                "next_step": "If sources reconnect, then review this again.",
                "meta_line": "0 sources • time unknown",
                "details": {"evidence_bullets": ["Data source not connected"], "chain_3_nodes": ["No data", "No signal", "Wait"]},
            }
        )

    bull = sum(1 for c in top3 if c.get("direction") == "bull")
    bear = sum(1 for c in top3 if c.get("direction") == "bear")
    mood = "Risk-on, but stay selective." if bull > bear else "Risk-off tone, keep size light." if bear > bull else "Event-driven and mixed."
    triggers = [c.get("next_step") for c in top3 if c.get("next_step")][:3]
    connected_count = _connected_source_count({"source_status": source_status})
    trust = _trust_level(connected_count)

    option_rows: list[dict] = []
    if tradier_token:
        for symbol in watchlist_view[:3]:
            try:
                exps = _tradier_expirations(symbol, tradier_token)[:1]
                if not exps:
                    continue
                chain = _tradier_chain(symbol, exps[0], tradier_token)
                option_rows.extend(chain)
            except Exception:
                continue
    _store_options_observations(option_rows)
    option_cards = []
    for row in option_rows[:120]:
        b = _option_baselines(row["symbol"], row["contract_key"])
        c_mean = b["contract_mean"] if b["contract_n"] >= 5 else max(1.0, b["symbol_mean"])
        c_std = b["contract_std"] if b["contract_n"] >= 8 else max(1.0, c_mean * 0.5)
        vol = float(row["volume"])
        oi = float(row["open_interest"])
        oi_ratio = vol / max(1.0, oi)
        z = (vol - c_mean) / max(1.0, c_std)
        cboe_boost = 0.0 if cboe_base["n"] < 5 else min(2.0, (cboe_base["mean"] / max(1.0, cboe_base["std"] + 1.0)) / 100000.0)
        unusual = max(0.0, min(100.0, 45.0 + 10.0 * z + 15.0 * min(3.0, oi_ratio) + 10.0 * cboe_boost))
        conf = max(25, min(90, 35 + min(30, b["contract_n"]) + (10 if cboe_base["n"] >= 20 else 0)))
        direction = "bull" if row["call_put"] == "C" else "bear"
        option_cards.append(
            {
                "title": f"{row['symbol']} {row['call_put']} {row['strike']:.1f} {row['expiry']} options activity",
                "direction": direction,
                "strength": int(round(unusual)),
                "confidence": int(round(conf)),
                "why_you": f"Because you watch or hold {row['symbol']}.",
                "next_step": f"If spot confirms with volume, then watch {row['symbol']} continuation.",
                "meta_line": f"Tradier + Cboe • V {int(vol)} • OI {int(oi)}",
                "details": {
                    "evidence_bullets": [
                        f"volume={int(vol)}, open_interest={int(oi)}, oi_ratio={oi_ratio:.2f}",
                        f"premium_estimate={row['premium_estimate']:.0f}, volume_zscore={z:.2f}",
                        "Verified unusual activity proxy only (no sweep/aggressor claims).",
                    ],
                    "source_links": [
                        {"label": "Tradier", "url": "https://documentation.tradier.com/brokerage-api/markets/get-options-chains"},
                        {"label": "Cboe", "url": "https://cdn.cboe.com/api/global/us_options/market_statistics/daily_volume.csv"},
                    ],
                },
                "raw": {
                    "ticker": row["symbol"],
                    "call_put": row["call_put"],
                    "strike": row["strike"],
                    "expiry": row["expiry"],
                    "volume": int(vol),
                    "open_interest": int(oi),
                    "premium_estimate": float(row["premium_estimate"]),
                    "unusual_score": float(unusual),
                    "confidence": int(round(conf)),
                },
            }
        )
    option_cards.sort(key=lambda x: x["strength"], reverse=True)
    options_proxy = {
        "title": "Unusual Options Activity (Verified Proxy)",
        "status": "Connected" if option_cards else "Source not connected",
        "cards": option_cards[:4] if option_cards else [
            {
                "title": "Options data source not connected",
                "direction": "uncertain",
                "strength": 20,
                "confidence": 25,
                "why_you": "Because options often lead short-term risk mood.",
                "next_step": "If source reconnects, then reassess options heat.",
                "meta_line": "Tradier/Cboe source required",
                "details": {
                    "evidence_bullets": ["Need Tradier token and Cboe baseline for verified proxy."],
                    "source_links": [
                        {"label": "Tradier", "url": "https://documentation.tradier.com/brokerage-api/markets/get-options-chains"},
                        {"label": "Cboe", "url": "https://cdn.cboe.com/api/global/us_options/market_statistics/daily_volume.csv"},
                    ],
                },
            }
        ],
    }

    sec_items = [e for e in fetched if "SEC EDGAR" in (e.get("source") or "")]
    sec_radar_cards = []
    for e in sec_items[:12]:
        txt = f"{e.get('title','')}. {e.get('summary','')}"
        filing_type = "13F" if "13f" in txt.lower() else "13D/13G" if "13d" in txt.lower() or "13g" in txt.lower() else "Form 4" if "form 4" in txt.lower() or " type 4" in txt.lower() else "8-K"
        filing_dir, magnitude = _sec_direction_and_magnitude(txt)
        tickers = re.findall(r"\b[A-Z]{1,5}\b", e.get("title", ""))
        impacts = [t for t in tickers if t in watchlist][:3] or watchlist_view[:1]
        direction = "bull" if filing_dir in ("new", "increase") else "bear" if filing_dir in ("decrease", "exit") else "uncertain"
        sec_radar_cards.append(
            {
                "title": f"{filing_type}: {e.get('title','')[:86]}",
                "direction": direction,
                "strength": 52 if direction != "uncertain" else 35,
                "confidence": 78 if filing_type != "13F" else 62,
                "why_you": f"Because this filing can affect {', '.join(impacts)}.",
                "next_step": f"If price reacts with follow-through, then watch {impacts[0] if impacts else 'your watchlist'}.",
                "meta_line": f"SEC source • {_hours_ago(e.get('published'))}",
                "details": {
                    "evidence_bullets": [
                        f"filing_type={filing_type}, direction={filing_dir}, magnitude={magnitude}",
                        "SEC public filing is verifiable, but 13F is quarterly lagged.",
                        "Low-confidence or unclear filing text stays uncertain.",
                    ],
                    "source_links": [
                        {"label": "SEC", "url": e.get("link", "")},
                        {"label": "SEC EDGAR", "url": "https://www.sec.gov/edgar/searchedgar/companysearch"},
                    ],
                },
                "raw": {
                    "timestamp": e.get("published"),
                    "filer": e.get("source", "SEC"),
                    "filing_type": filing_type,
                    "impacted_tickers": impacts,
                    "direction": filing_dir,
                    "magnitude": magnitude,
                    "confidence": 78 if filing_type != "13F" else 62,
                },
            }
        )
    sec_radar = {
        "title": "SEC Filings Radar",
        "cards": sec_radar_cards[:4],
        "links": [s for s in source_status if "SEC" in s.get("name", "")],
        "note": "13F filings are quarterly and lagged.",
    }

    tomorrow_setup = {
        "mood": "Risk-on" if bull > bear else "Risk-off" if bear > bull else "Event-driven",
        "base_case": [
            "Macro headlines drive the first direction move.",
            "Large-cap reaction sets broad risk tone.",
            "Crypto-beta can lead intraday appetite.",
        ],
        "alt_case": [
            "If rates reverse hard, primary case weakens.",
            "If policy headlines conflict, wait for clarity.",
        ],
        "triggers": triggers[:3],
        "watchlist": watchlist_view,
        "confidence": trust,
        "why": "Source mix + cross-check rules",
        "guardrail": "Data insufficient, no setup." if connected_count < 2 else "No strong conclusion when confidence is low.",
    }

    return {
        "today_snapshot": {
            "mood_sentence": mood,
            "top3": [
                {
                    "what_happened": c.get("title", ""),
                    "why_you": c.get("why_you", ""),
                }
                for c in top3[:3]
            ],
            "watchlist": watchlist_view[:4],
            "triggers": triggers[:3],
            "trust_level": trust,
            "source_count": connected_count,
            "more_count": max(0, len(cards) - 3),
        },
        "event_cards": cards[:8],
        "source_status": source_status,
        "connection_plain_notes": connection_notes[:8],
        "pro_strip": {
            "label": "Tomorrow Setup · Unusual Options Activity · SEC Filings Radar",
            "tomorrow_setup": tomorrow_setup,
            "options_activity": options_proxy,
            "sec_radar": sec_radar,
        },
    }


def _build_brief_script(state_payload: dict, language: str, duration_min: int, quick: bool, brief_type: str = "premarket") -> str:
    snap = state_payload.get("today_snapshot", {})
    top3 = snap.get("top3", [])[:3]
    watchlist = snap.get("watchlist", [])
    triggers = snap.get("triggers", [])
    mood = snap.get("mood_sentence", "")
    disclaimer = _brief_disclaimer(language)
    if language == "Chinese":
        lines = [f"先说今天的感觉：{mood}", "", "我给你三个重点："]
        if brief_type == "overnight":
            lines.insert(0, "这是夜市/盘后简报。")
        elif brief_type == "quick":
            lines.insert(0, "这是当日快报。")
        for i, item in enumerate(top3, start=1):
            lines.append(f"{i}）{item.get('what_happened', '')}")
            lines.append(f"   why you：{item.get('why_you', '')}")
        lines += ["", "再看观察名单和触发条件：", f"观察名单：{', '.join(watchlist)}"]
        for t in triggers[:3]:
            lines.append(f"- {t}")
        if duration_min >= 3:
            lines += [
                "",
                "节奏建议：先看方向，再动手，不急着追价。",
                "如果你看到冲高回落，先等第二次确认再决定。",
            ]
        if duration_min >= 5:
            lines += [
                "今天更适合小步试探，留一点余地给后面的变化。",
                "你可以先盯住最熟的两个标的，其他先不分散注意力。",
            ]
        if duration_min >= 7:
            lines += [
                "如果盘中消息变多，先回到你的触发条件，不要被情绪带走。",
                "稳住节奏，比追求每一段波动更重要。",
            ]
        lines += ["", f"最后提醒：{disclaimer}"]
    else:
        lines = [f"First, the tone today: {mood}", "", "Here are your three key moves:"]
        if brief_type == "overnight":
            lines.insert(0, "This is your overnight / after-hours brief.")
        elif brief_type == "quick":
            lines.insert(0, "This is your quick recap alert.")
        for i, item in enumerate(top3, start=1):
            lines.append(f"{i}) {item.get('what_happened', '')}")
            lines.append(f"   why you: {item.get('why_you', '')}")
        lines += ["", "Now watchlist and triggers:", f"Watchlist: {', '.join(watchlist)}"]
        for t in triggers[:3]:
            lines.append(f"- {t}")
        if duration_min >= 3:
            lines += [
                "",
                "Pacing tip: read direction first, then size in slowly.",
                "If a move pops and fades fast, wait for a second confirmation.",
            ]
        if duration_min >= 5:
            lines += [
                "Today is better for calm, smaller decisions than big swings.",
                "Focus on your two most familiar names before widening attention.",
            ]
        if duration_min >= 7:
            lines += [
                "If headlines get noisy, go back to your trigger rules.",
                "Steady execution matters more than catching every move.",
            ]
        lines += ["", f"Final note: {disclaimer}"]
    if quick:
        if language == "Chinese":
            return "\n".join(lines[:8] + [f"快速回顾到这里。{disclaimer}"])
        return "\n".join(lines[:8] + [f"Quick recap ends here. {disclaimer}"])
    return "\n".join(lines)


def _tts_voice_candidates(language: str) -> list[str]:
    if language == "Chinese":
        return ["zh-CN-XiaoyiNeural", "zh-CN-XiaoxiaoNeural", "zh-CN-YunjianNeural"]
    return ["en-US-AvaMultilingualNeural", "en-US-EmmaMultilingualNeural", "en-US-JennyNeural"]


def _tts_rate(language: str) -> str:
    # Keep it calm, but not too slow.
    return "-4%" if language == "Chinese" else "-5%"


def _tts_pitch(language: str) -> str:
    return "-2Hz" if language == "Chinese" else "-1Hz"


def _clean_tts_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\n+", ". ", text)
    text = re.sub(r"[•*-]\s*", "", text)
    text = re.sub(r"\b\d+[）\).:]\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("：", "，").replace(":", ",")
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text[:4500]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _audit(route: str, input_summary: dict, result_summary: dict, error: str | None = None) -> None:
    _append_jsonl(
        AUDIT_LOG_PATH,
        {
            "timestamp": _now_iso(),
            "route": route,
            "user_id": USER_ID,
            "input_summary": input_summary,
            "result_summary": result_summary,
            "error": error,
        },
    )


def _history_rows() -> list[dict]:
    return _read_jsonl(HISTORY_PATH)


def _save_history(rows: list[dict]) -> None:
    _write_jsonl(HISTORY_PATH, rows)


def _find_row(rows: list[dict], recording_id: str) -> dict | None:
    for row in reversed(rows):
        if row.get("recording_id") == recording_id:
            return row
    return None


def _latest_row(rows: list[dict]) -> dict | None:
    return rows[-1] if rows else None


def _latest_analyzed_row(rows: list[dict]) -> dict | None:
    for row in reversed(rows):
        if row.get("features"):
            return row
    return None


def _feature_vector(features: dict) -> np.ndarray:
    mfcc_mean = features.get("mfcc_mean", [0.0] * 13)
    mfcc_var = features.get("mfcc_var", [0.0] * 13)
    vec = [
        float(features.get("duration_sec", 0.0)),
        float(features.get("rms", 0.0)),
        float(features.get("spectral_centroid", 0.0)),
        float(features.get("spectral_rolloff", 0.0)),
        float(features.get("spectral_bandwidth", 0.0)),
        float(features.get("zero_crossing_rate", 0.0)),
        *[float(x) for x in mfcc_mean[:13]],
        *[float(x) for x in mfcc_var[:13]],
    ]
    return np.array(vec, dtype=np.float64)


def _confidence_bucket(raw_conf: float) -> str:
    if raw_conf < 0.35:
        return "low"
    if raw_conf < 0.7:
        return "med"
    return "high"


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom <= 1e-9:
        return 0.0
    return float(np.clip(np.dot(a, b) / denom, -1.0, 1.0))


def _hit_rate(rows: list[dict]) -> float:
    labeled = [r for r in rows if r.get("outcome") in ("happened", "not_happened")]
    if not labeled:
        return 0.0
    hits = sum(1 for r in labeled if r.get("outcome") == "happened")
    return hits / len(labeled)


def _labeled_analyzed(rows: list[dict], exclude_id: str | None = None) -> list[dict]:
    out = []
    for r in rows:
        if exclude_id and r.get("recording_id") == exclude_id:
            continue
        if r.get("features") and r.get("outcome") in ("happened", "not_happened"):
            out.append(r)
    return out


def _neighbors(recording_id: str, k: int) -> dict:
    rows = _history_rows()
    target = _find_row(rows, recording_id)
    if not target or not target.get("features"):
        raise HTTPException(status_code=404, detail="recording not found or not analyzed")
    candidates = _labeled_analyzed(rows, exclude_id=recording_id)
    if not candidates:
        return {"ok": True, "recording_id": recording_id, "neighbors": [], "message": "no labeled neighbors yet"}

    target_vec = _feature_vector(target["features"])
    cand_vecs = np.array([_feature_vector(c["features"]) for c in candidates], dtype=np.float64)
    if len(candidates) >= 2:
        mu = cand_vecs.mean(axis=0)
        sigma = cand_vecs.std(axis=0)
        sigma[sigma < 1e-9] = 1.0
        target_cmp = (target_vec - mu) / sigma
        cmp_vecs = [(v - mu) / sigma for v in cand_vecs]
    else:
        target_cmp = target_vec
        cmp_vecs = [v for v in cand_vecs]

    scored: list[dict] = []
    for row, vec in zip(candidates, cmp_vecs):
        sim = _cosine_similarity(target_cmp, vec)
        scored.append(
            {
                "recording_id": row["recording_id"],
                "similarity": sim,
                "outcome": row["outcome"],
                "intent_tag": row.get("intent_tag"),
                "timestamp": row["timestamp"],
            }
        )
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    top = scored[: max(1, min(k, 20))]
    return {"ok": True, "recording_id": recording_id, "neighbors": top}


def _neighbors_from_rows(rows: list[dict], target_row: dict, k: int) -> list[dict]:
    candidates = []
    for row in rows:
        if row.get("recording_id") == target_row.get("recording_id"):
            continue
        if row.get("features") and row.get("outcome") in ("happened", "not_happened"):
            candidates.append(row)
    if not candidates:
        return []

    target_vec = _feature_vector(target_row["features"])
    cand_vecs = np.array([_feature_vector(c["features"]) for c in candidates], dtype=np.float64)
    if len(candidates) >= 2:
        mu = cand_vecs.mean(axis=0)
        sigma = cand_vecs.std(axis=0)
        sigma[sigma < 1e-9] = 1.0
        target_cmp = (target_vec - mu) / sigma
        cmp_vecs = [(v - mu) / sigma for v in cand_vecs]
    else:
        target_cmp = target_vec
        cmp_vecs = [v for v in cand_vecs]

    scored = []
    for row, vec in zip(candidates, cmp_vecs):
        scored.append(
            {
                "recording_id": row["recording_id"],
                "similarity": _cosine_similarity(target_cmp, vec),
                "outcome": row["outcome"],
                "intent_tag": row.get("intent_tag"),
                "timestamp": row["timestamp"],
            }
        )
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[: max(1, min(k, 20))]


def _loo_validation(rows: list[dict], k: int) -> dict:
    labeled = [r for r in rows if r.get("features") and r.get("outcome") in ("happened", "not_happened")]
    if len(labeled) < 3:
        return {"available": False, "reason": "Need at least 3 labeled samples for LOO validation."}

    correct = 0
    evaluated = 0
    for row in labeled:
        neigh = _neighbors_from_rows(labeled, row, k)
        if not neigh:
            continue
        neigh_success = sum(1 for n in neigh if n["outcome"] == "happened")
        p = (neigh_success + 1.0) / (len(neigh) + 2.0)
        pred = "happened" if p >= 0.5 else "not_happened"
        if pred == row["outcome"]:
            correct += 1
        evaluated += 1
    if evaluated == 0:
        return {"available": False, "reason": "No valid folds for LOO validation."}
    return {"available": True, "loo_accuracy": correct / evaluated, "evaluated_folds": evaluated}


def _bootstrap_ci(neighbors: list[dict], rounds: int = 200) -> dict:
    if not neighbors:
        return {"available": False, "reason": "No neighbors for bootstrap."}
    outcomes = np.array([1.0 if n["outcome"] == "happened" else 0.0 for n in neighbors], dtype=np.float64)
    n = len(outcomes)
    means = []
    for _ in range(rounds):
        sample = np.random.choice(outcomes, size=n, replace=True)
        p = float((np.sum(sample) + 1.0) / (n + 2.0))
        means.append(p)
    means = np.array(means, dtype=np.float64)
    return {
        "available": True,
        "p_success_ci_90": [float(np.percentile(means, 5)), float(np.percentile(means, 95))],
        "rounds": rounds,
    }


@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/dashboard")
def dashboard():
    html = (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/hello")
def hello():
    return {"ok": True, "msg": "hello"}


@app.get("/healthz")
def healthz():
    return {"ok": True, "status": "healthy"}


@app.get("/healthz.txt", response_class=PlainTextResponse)
def healthz_text():
    return "ok"


@app.get("/healthz.html", response_class=HTMLResponse)
def healthz_html():
    return """
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Health Check</title></head>
  <body style="font-family:sans-serif;padding:24px;">
    <h1 style="margin:0;color:#0a7f2e;">Service Healthy</h1>
    <p style="margin-top:8px;">status: ok</p>
  </body>
</html>
"""


@app.get("/recordings/latest")
def recordings_latest():
    rows = _history_rows()
    row = _latest_row(rows)
    if not row:
        raise HTTPException(status_code=404, detail="no recordings yet")
    return {"ok": True, "recording_id": row["recording_id"]}


@app.get("/features/schema")
def features_schema():
    return {"ok": True, "feature_schema": FEATURE_SCHEMA}


@app.post("/upload")
async def upload(request: Request):
    body = await request.body()
    if not body:
        _audit("/upload", {"bytes": 0}, {"ok": False}, "empty audio body")
        raise HTTPException(status_code=400, detail="Empty audio body")
    if len(body) > MAX_UPLOAD_BYTES:
        _audit("/upload", {"bytes": len(body)}, {"ok": False}, "audio too large")
        raise HTTPException(status_code=400, detail="Audio too large")

    recording_id = str(uuid.uuid4())
    intent_tag = request.headers.get("x-intent-tag")
    content_type = (request.headers.get("content-type") or "").lower()
    suffix = ".wav" if "wav" in content_type else ".webm"
    audio_path = UPLOAD_DIR / f"{recording_id}{suffix}"
    with audio_path.open("wb") as f:
        f.write(body)

    row = {
        "recording_id": recording_id,
        "user_id": USER_ID,
        "timestamp": _now_iso(),
        "intent_tag": intent_tag,
        "audio_path": str(audio_path),
        "png_path": None,
        "features": None,
        "outcome": None,
        "expected_by": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }
    _append_jsonl(HISTORY_PATH, row)
    _audit("/upload", {"recording_id": recording_id, "bytes": len(body)}, {"ok": True})
    return {"ok": True, "recording_id": recording_id}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    rows = _history_rows()
    target = _find_row(rows, req.recording_id) if req.recording_id else _latest_row(rows)
    if not target:
        _audit("/analyze", req.model_dump(), {"ok": False}, "recording not found")
        raise HTTPException(status_code=404, detail="recording not found")

    audio_path = Path(target["audio_path"])
    if not audio_path.exists():
        _audit("/analyze", req.model_dump(), {"ok": False}, "audio file missing")
        raise HTTPException(status_code=404, detail="audio file missing")

    try:
        y, sr = librosa.load(audio_path, sr=None, mono=True)
    except Exception as exc:
        _audit("/analyze", req.model_dump(), {"ok": False}, f"decode failed: {exc}")
        raise HTTPException(status_code=400, detail="audio decode failed") from exc

    duration_sec = float(librosa.get_duration(y=y, sr=sr)) if len(y) else 0.0
    if duration_sec > MAX_DURATION_SECONDS:
        _audit("/analyze", {"recording_id": target["recording_id"]}, {"ok": False}, "duration > 30s")
        raise HTTPException(status_code=400, detail="Audio must be <= 30s")

    spec = np.abs(librosa.stft(y, n_fft=1024, hop_length=256))
    spec_db = librosa.amplitude_to_db(spec, ref=np.max)
    png_path = GENERATED_DIR / f"{target['recording_id']}.png"
    plt.figure(figsize=(8, 3))
    librosa.display.specshow(spec_db, sr=sr, x_axis="time", y_axis="hz")
    plt.colorbar(format="%+2.0f dB")
    plt.tight_layout()
    plt.savefig(png_path)
    plt.close()
    (GENERATED_DIR / "latest.png").write_bytes(png_path.read_bytes())

    rms = float(np.mean(librosa.feature.rms(y=y))) if len(y) else 0.0
    spectral_centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))) if len(y) else 0.0
    spectral_rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr))) if len(y) else 0.0
    spectral_bandwidth = float(np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr))) if len(y) else 0.0
    zero_crossing_rate = float(np.mean(librosa.feature.zero_crossing_rate(y))) if len(y) else 0.0
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_mean = [float(v) for v in np.mean(mfcc, axis=1)]
    mfcc_var = [float(v) for v in np.var(mfcc, axis=1)]
    fft_mag = np.abs(np.fft.rfft(y))
    fft_freq = np.fft.rfftfreq(len(y), d=1.0 / sr) if len(y) else np.array([])
    top_peaks = []
    if len(fft_mag) and len(fft_freq):
        top_idx = np.argsort(fft_mag)[-5:][::-1]
        top_peaks = [
            {"hz": float(fft_freq[i]), "magnitude": float(fft_mag[i])}
            for i in top_idx
        ]

    harmonic = librosa.effects.harmonic(y) if len(y) else np.array([0.0])
    harmonicity = float(np.mean(np.abs(harmonic)) / (np.mean(np.abs(y)) + 1e-9)) if len(y) else 0.0
    stft_freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    power = np.mean(spec, axis=1) if spec.size else np.zeros_like(stft_freqs)
    low = float(np.sum(power[(stft_freqs >= 20) & (stft_freqs < 500)]))
    mid = float(np.sum(power[(stft_freqs >= 500) & (stft_freqs < 2000)]))
    high = float(np.sum(power[(stft_freqs >= 2000) & (stft_freqs < 8000)]))
    energy_total = low + mid + high + 1e-9
    energy_distribution = {
        "low": low / energy_total,
        "mid": mid / energy_total,
        "high": high / energy_total,
    }

    features = {
        "feature_version": FEATURE_VERSION,
        "duration_sec": duration_sec,
        "sample_rate": int(sr),
        "rms": rms,
        "spectral_centroid": spectral_centroid,
        "spectral_rolloff": spectral_rolloff,
        "spectral_bandwidth": spectral_bandwidth,
        "zero_crossing_rate": zero_crossing_rate,
        "mfcc_mean": mfcc_mean,
        "mfcc_var": mfcc_var,
        "top_peaks": top_peaks,
        "harmonicity": harmonicity,
        "energy_distribution": energy_distribution,
    }

    target["features"] = features
    target["png_path"] = str(png_path)
    target["png_url"] = f"/generated/{target['recording_id']}.png"
    _save_history(rows)
    result = {
        "ok": True,
        "recording_id": target["recording_id"],
        "png_url": target["png_url"],
        "features": features,
    }
    _audit("/analyze", {"recording_id": target["recording_id"]}, {"ok": True, "png_url": target["png_url"]})
    return result


@app.post("/outcome")
def outcome(req: OutcomeRequest):
    rows = _history_rows()
    target = _find_row(rows, req.recording_id) if req.recording_id else _latest_analyzed_row(rows)
    if not target:
        _audit("/outcome", req.model_dump(), {"ok": False}, "no analyzed recordings")
        raise HTTPException(status_code=404, detail="no analyzed recordings yet")

    target["outcome"] = "happened" if req.happened else "not_happened"
    _save_history(rows)
    _audit("/outcome", {"recording_id": target["recording_id"], "happened": req.happened}, {"ok": True})
    return {"ok": True, "recording_id": target["recording_id"], "outcome": target["outcome"]}


@app.get("/history")
def history(limit: int = 20):
    rows = [r for r in _history_rows() if r.get("features")]
    rows = sorted(rows, key=lambda r: r.get("timestamp", ""), reverse=True)[: max(1, min(limit, 200))]
    return {
        "ok": True,
        "history": rows,
        "hit_rate": _hit_rate(rows),
    }


@app.get("/baseline")
def baseline():
    rows = [r for r in _history_rows() if r.get("features") and r.get("outcome") in ("happened", "not_happened")]
    now = datetime.now(timezone.utc)
    rows_7d = [r for r in rows if datetime.fromisoformat(r["timestamp"]) >= now - timedelta(days=7)]
    return {
        "ok": True,
        "all_time_baseline": _hit_rate(rows),
        "last_7d_baseline": _hit_rate(rows_7d),
        "labeled_count": len(rows),
    }


@app.get("/neighbors")
def neighbors(recording_id: str, k: int = 5):
    payload = _neighbors(recording_id, k)
    _audit("/neighbors", {"recording_id": recording_id, "k": k}, {"ok": True, "count": len(payload["neighbors"])})
    return payload


@app.get("/predict")
def predict(recording_id: str, k: int = 5, min_samples: int = PREDICT_MIN_SAMPLES):
    rows = _history_rows()
    target = _find_row(rows, recording_id)
    if not target or not target.get("features"):
        raise HTTPException(status_code=404, detail="recording not found or not analyzed")

    candidates = _labeled_analyzed(rows, exclude_id=recording_id)
    if len(candidates) < min_samples:
        return {
            "ok": True,
            "recording_id": recording_id,
            "status": "insufficient data",
            "required_samples": min_samples,
            "available_samples": len(candidates),
            "score": None,
            "p_success": None,
            "top_features": [],
            "why": "Not enough labeled sessions to produce a reliable estimate yet.",
            "confidence": "low",
            "needs_more_data": {
                "required_samples": min_samples,
                "available_samples": len(candidates),
                "condition": f"Need at least {min_samples} labeled analyzed sessions.",
            },
            "guardrails": {
                "min_samples_gate": True,
                "loo_validation": {"available": False, "reason": "Insufficient samples"},
                "bootstrap": {"available": False, "reason": "Insufficient samples"},
            },
        }

    neigh = _neighbors(recording_id, k)
    top = neigh["neighbors"]
    success = sum(1 for n in top if n["outcome"] == "happened")
    p_success = (success + 1.0) / (len(top) + 2.0)
    avg_similarity = float(np.mean([n["similarity"] for n in top])) if top else 0.0
    conf_raw = min(1.0, len(top) / max(1, k)) * max(0.0, avg_similarity)
    features = target["features"]
    first_peak = (features.get("top_peaks") or [{}])[0]
    top_features = [
        {"name": "primary_peak_hz", "value": first_peak.get("hz", 0.0)},
        {"name": "rms", "value": features.get("rms", 0.0)},
        {"name": "spectral_centroid", "value": features.get("spectral_centroid", 0.0)},
        {"name": "spectral_bandwidth", "value": features.get("spectral_bandwidth", 0.0)},
        {"name": "harmonicity", "value": features.get("harmonicity", 0.0)},
    ]
    why = (
        f"Estimate is based on {len(top)} nearest labeled sessions with average similarity "
        f"{avg_similarity:.2f}. Current signal shows primary peak around "
        f"{top_features[0]['value']:.1f}Hz and RMS {top_features[1]['value']:.4f}."
    )
    loo = _loo_validation(rows, k)
    boot = _bootstrap_ci(top, rounds=200)
    return {
        "ok": True,
        "recording_id": recording_id,
        "status": "experimental",
        "method": "knn_laplace_smoothed",
        "score": p_success,
        "p_success": p_success,
        "top_features": top_features,
        "why": why,
        "confidence": _confidence_bucket(conf_raw),
        "needs_more_data": {
            "required_samples": min_samples,
            "available_samples": len(candidates),
            "condition": "Model confidence improves when more labeled sessions are added.",
        },
        "neighbors_used": len(top),
        "guardrails": {
            "min_samples_gate": True,
            "loo_validation": loo,
            "bootstrap": boot,
        },
    }


@app.get("/predict/latest")
def predict_latest(k: int = 5, min_samples: int = PREDICT_MIN_SAMPLES):
    rows = _history_rows()
    latest = _latest_analyzed_row(rows)
    if not latest:
        return {
            "ok": True,
            "status": "insufficient data",
            "why": "No analyzed recording yet.",
            "needs_more_data": {"condition": "Upload and analyze at least one recording first."},
        }
    return predict(latest["recording_id"], k=k, min_samples=min_samples)


@app.get("/dashboard/state")
def dashboard_state():
    settings = _load_radar_settings()
    state = _collect_public_sources(settings)
    return {"ok": True, "mode": "Preview", "settings": settings, **state}


def _browser_language(req: Request | None) -> str:
    if req is None:
        return "English"
    header = (req.headers.get("accept-language") or "").lower()
    return "Chinese" if header.startswith("zh") or "zh" in header else "English"


@app.get("/radarbrief/state")
def radarbrief_state(request: Request, mode: str = "Preview"):
    mode = mode if mode in ("Preview", "Tier1", "Tier2") else "Preview"
    settings = _load_radar_settings()
    if not settings.get("language"):
        settings["language"] = _browser_language(request)
        settings = _save_radar_settings(settings)
    state = _collect_public_sources(settings)
    cards = state.get("event_cards", [])
    if mode == "Preview":
        cards = cards[:4]
    elif mode == "Tier1":
        cards = (cards[:6] + state.get("sec_cards", [])[:3])[:8]
    else:
        cards = cards[:8]
    return {
        "ok": True,
        "mode": mode,
        "language": settings.get("language", _browser_language(request)),
        "settings": settings,
        "today_snapshot": state.get("today_snapshot", {}),
        "event_cards": cards,
        "source_status": state.get("source_status", []),
        "connection_plain_notes": state.get("connection_plain_notes", []),
        "pro_strip": state.get("pro_strip", {}),
    }


@app.get("/radarbrief/settings")
def radarbrief_get_settings(request: Request):
    settings = _load_radar_settings()
    if not settings.get("language"):
        settings["language"] = _browser_language(request)
        settings = _save_radar_settings(settings)
    return {
        "ok": True,
        "watchlist": settings["watchlist"],
        "crypto_toggle": settings["crypto_priority"],
        "language": settings["language"],
    }


@app.post("/radarbrief/settings")
def radarbrief_save_settings(req: RadarSettingsRequest):
    cleaned = _save_radar_settings(
        {"watchlist": req.watchlist, "crypto_priority": req.crypto_toggle, "language": req.language}
    )
    return {
        "ok": True,
        "watchlist": cleaned["watchlist"],
        "crypto_toggle": cleaned["crypto_priority"],
        "language": cleaned["language"],
    }


@app.post("/radarbrief/brief")
def radarbrief_brief(req: BriefRequest):
    mode = req.mode if req.mode in ("Preview", "Tier1", "Tier2") else "Preview"
    language = req.language if req.language in ("Chinese", "English") else "Chinese"
    duration = req.duration_min if req.duration_min in (1, 3, 5, 7) else 5
    brief_type = req.brief_type if req.brief_type in ("premarket", "overnight", "quick", "setup") else "premarket"
    quick = bool(req.quick_recap or brief_type == "quick")
    if quick:
        log_obj = _load_quick_recap_log()
        if int(log_obj.get("count", 0)) >= 3:
            return {
                "ok": False,
                "message": "Quick recap limit reached for today (max 3).",
                "remaining_today": 0,
            }
        log_obj["count"] = int(log_obj.get("count", 0)) + 1
        _save_quick_recap_log(log_obj)

    settings = _load_radar_settings()
    if settings.get("language") != language:
        settings["language"] = language
        settings = _save_radar_settings(settings)
    state = _collect_public_sources(settings)
    if brief_type == "setup":
        setup = state.get("pro_strip", {}).get("tomorrow_setup", {})
        if language == "Chinese":
            script = (
                f"Tomorrow Setup。情绪：{setup.get('mood','Event-driven')}。"
                f"基础情景：{'；'.join(setup.get('base_case',[])[:3])}。"
                f"备选情景：{'；'.join(setup.get('alt_case',[])[:2])}。"
                f"触发条件：{'；'.join(setup.get('triggers',[])[:3])}。"
                f"观察名单：{', '.join(setup.get('watchlist',[])[:4])}。"
                f"可信度：{setup.get('confidence','Low')}。"
                f"护栏：{setup.get('guardrail','Data insufficient, no setup.')}。"
            )
        else:
            script = (
                f"Tomorrow setup. Mood: {setup.get('mood','Event-driven')}. "
                f"Base case: {'; '.join(setup.get('base_case',[])[:3])}. "
                f"Alt case: {'; '.join(setup.get('alt_case',[])[:2])}. "
                f"Triggers: {'; '.join(setup.get('triggers',[])[:3])}. "
                f"Watchlist: {', '.join(setup.get('watchlist',[])[:4])}. "
                f"Confidence: {setup.get('confidence','Low')}. "
                f"Guardrail: {setup.get('guardrail','Data insufficient, no setup.')}. "
            )
    else:
        script = _build_brief_script(state, language=language, duration_min=duration, quick=quick, brief_type=brief_type)
    return {
        "ok": True,
        "mode": mode,
        "language": language,
        "duration_min": duration,
        "quick_recap": quick,
        "brief_type": brief_type,
        "script": script,
        "voice_ready": True,
    }


@app.post("/radarbrief/tts")
async def radarbrief_tts(req: TtsRequest):
    language = req.language if req.language in ("Chinese", "English") else "Chinese"
    text = _clean_tts_text(req.text)
    if not text:
        raise HTTPException(status_code=400, detail="Text is empty")
    if edge_tts is None:
        return {"ok": False, "message": "Voice not connected"}
    voice_file = GENERATED_DIR / f"brief-{uuid.uuid4().hex}.mp3"
    last_error = None
    for voice in _tts_voice_candidates(language):
        try:
            comm = edge_tts.Communicate(text=text, voice=voice, rate=_tts_rate(language), pitch=_tts_pitch(language))
            await comm.save(str(voice_file))
            return {"ok": True, "audio_url": f"/generated/{voice_file.name}", "voice": voice}
        except Exception as exc:
            last_error = exc
            continue
    return {"ok": False, "message": "Voice not connected", "error": str(last_error)[:120] if last_error else None}
