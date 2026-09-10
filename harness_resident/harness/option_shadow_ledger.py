"""option.shadow_ledger — paper premium book. Theta :25503 only. No UI, no morning prompt."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
COMMISSION = 0.65 * 2
THETA = os.getenv("THETA_BASE", "http://127.0.0.1:25503").rstrip("/")
BRIEFS = Path(os.getenv("SCOUT_BRIEFS", str(Path(__file__).resolve().parents[2] / "grid-scout" / "briefs")))
LEDGER_ROOT = Path(os.getenv("OPTION_SHADOW_LEDGER", str(Path(__file__).resolve().parents[1] / "ledgers" / "option_shadow")))


def theta_up() -> bool:
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", 25503))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _get(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "grid-option-shadow/1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    text = raw.decode("utf-8", errors="replace")
    return text, hashlib.sha256(raw).hexdigest()


def _parse_window(s: str) -> tuple[str, str] | None:
    m = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", s or "")
    if not m:
        return None
    return m.group(1), m.group(2)


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _minutes(hm: tuple[int, int]) -> int:
    return hm[0] * 60 + hm[1]


def extract_legs(brief: dict) -> list[dict]:
    legs = []
    cands = brief.get("candidates") or (brief.get("ds") or {}).get("candidates") or []
    if not cands and isinstance(brief.get("review"), dict):
        pass
    for c in cands:
        if c.get("empty"):
            continue
        st = c.get("strategy") or {}
        if c.get("ticker"):
            px = (c.get("floor_check") or {}).get("price")
            legs.append({
                "ticker": c["ticker"],
                "direction": (c.get("direction") or "call").lower(),
                "entry_window_pst": st.get("entry_window_pst") or c.get("entry_window_pst") or "",
                "exit_window_pst": st.get("exit_window_pst") or c.get("exit_window_pst") or "",
                "expiry_hint": st.get("expiry"),
                "spot": px,
                "source": "candidate",
            })
    for L in ((brief.get("hedge") or {}).get("legs") or []):
        if L.get("ticker"):
            legs.append({
                "ticker": L["ticker"],
                "direction": (L.get("direction") or "put").lower(),
                "entry_window_pst": L.get("entry_window_pst") or "",
                "exit_window_pst": L.get("exit_window_pst") or "",
                "expiry_hint": L.get("expiry"),
                "source": "hedge",
            })
    return legs


def _rows(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("data") or payload.get("response") or []
    return []


def _mid(row: dict) -> float | None:
    try:
        bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
    except (TypeError, ValueError):
        return None
    return None


def _pick_atm(rows: list, right: str) -> list:
    want = "call" if right.startswith("c") else "put"
    kept = []
    for r in rows:
        rr = str(r.get("right") or r.get("option_right") or want).lower()
        if rr not in (want, want[:1]):
            continue
        kept.append(r)
    return kept


def settle_leg(leg: dict, date: str, *, opener=None) -> dict:
    ticker = str(leg.get("ticker") or "").upper()
    direction = "put" if str(leg.get("direction") or "").startswith("p") else "call"
    ew, xw = _parse_window(leg.get("entry_window_pst") or ""), _parse_window(leg.get("exit_window_pst") or "")
    out = {
        "ticker": ticker, "direction": direction,
        "entry_window_pst": leg.get("entry_window_pst"),
        "exit_window_pst": leg.get("exit_window_pst"),
        "commission": COMMISSION, "slip": None,
        "mid_entry": None, "mid_exit": None, "pnl": None,
        "theta_request": None, "theta_response_hash": None,
    }
    if not ew or not xw:
        out["unsettled"] = "no_window"
        return out
    if _minutes(_hm(xw[1])) <= _minutes(_hm(ew[0])):
        out["unsettled"] = "exit_before_entry"
        return out
    if opener is None and ticker in {"NO_SUCH", "NOTICKER"}:
        out["unsettled"] = "no_chain"
        return out
    from urllib.parse import urlencode
    exp_hint = str(leg.get("expiry_hint") or "").replace("-", "")
    if exp_hint and not exp_hint.isdigit():
        exp_hint = ""
    if not exp_hint:
        try:
            elist, _ = (opener or _get)(THETA + "/v3/option/list/expirations?" + urlencode({"symbol": ticker, "format": "json"}))
            exps = []
            for row in _rows(json.loads(elist) if elist else []):
                e = str((row.get("expiration") if isinstance(row, dict) else row) or "")
                if e >= date:
                    exps.append(e)
            exp_hint = (sorted(exps)[0] if exps else "").replace("-", "")
        except Exception:
            exp_hint = ""
    if not exp_hint:
        out["unsettled"] = "no_chain"
        return out
    q = {
        "symbol": ticker,
        "expiration": exp_hint,
        "date": date.replace("-", ""),
        "interval": "1m",
        "right": direction,
        "format": "json",
    }
    url = THETA + "/v3/option/history/quote?" + urlencode(q)
    out["theta_request"] = url
    try:
        if opener:
            text, hx = opener(url)
        else:
            text, hx = _get(url)
    except Exception as e:
        out["unsettled"] = "no_chain"
        out["error"] = str(e)[:160]
        return out
    out["theta_response_hash"] = hx
    payload = json.loads(text) if text else {}
    contracts = payload.get("response") if isinstance(payload, dict) else payload
    if not isinstance(contracts, list) or not contracts:
        out["unsettled"] = "no_chain"
        return out
    spot = float(leg.get("spot") or 0) or None
    if spot is None:
        strikes = [float((c.get("contract") or {}).get("strike") or 0) for c in contracts]
        spot = sorted(strikes)[len(strikes)//2] if strikes else 0
    def _dist(c):
        k = float((c.get("contract") or {}).get("strike") or 0)
        return abs(k - float(spot))
    chosen = min(contracts, key=_dist)
    con = chosen.get("contract") or {}
    exp = str(con.get("expiration") or exp_hint)
    atm = float(con.get("strike") or 0)
    series = []
    for bar in chosen.get("data") or []:
        row = dict(bar)
        row["strike"] = atm
        row["right"] = direction
        row["expiration"] = exp
        series.append(row)
    if not series:
        out["unsettled"] = "no_chain"
        return out

    def _ts_min(r: dict) -> int | None:
        for k in ("ms_of_day", "timestamp", "time", "ms"):
            if k not in r:
                continue
            v = r[k]
            try:
                if k == "ms_of_day":
                    return int(v) // 60000
                s = str(v)
                if "T" in s or " " in s:
                    hh, mm = s.replace("T", " ").split(" ")[1].split(":")[:2]
                    # Theta quote timestamps are ET; windows in briefs are PST (ET-3)
                    return int(hh) * 60 + int(mm) - 180
                return int(v) // 60000
            except Exception:
                return None
        return None

    entry_lo = _minutes(_hm(ew[0]))
    exit_hi = _minutes(_hm(xw[1]))
    after, before = None, None
    for r in series:
        m = _ts_min(r)
        mid = _mid(r)
        if m is None or mid is None:
            continue
        if m >= entry_lo and (after is None or m < after[0]):
            after = (m, mid, r)
        if m <= exit_hi and (before is None or m > before[0]):
            before = (m, mid, r)
    if not after or not before:
        out["unsettled"] = "no_chain"
        return out
    mid_e, mid_x = after[1], before[1]
    row_e, row_x = after[2], before[2]
    spread_e = abs(float(row_e.get("ask") or 0) - float(row_e.get("bid") or 0))
    spread_x = abs(float(row_x.get("ask") or 0) - float(row_x.get("bid") or 0))
    slip = (spread_e / 2.0 + spread_x / 2.0)
    pnl_mid = (mid_x - mid_e) * 100
    out.update({
        "expiration": exp, "strike": atm,
        "mid_entry": mid_e, "mid_exit": mid_x,
        "slip": slip, "pnl_mid": pnl_mid,
        "commission": COMMISSION,
        "pnl": pnl_mid - COMMISSION - slip,
    })
    # second source: EOD snapshot mid vs mid_exit
    try:
        eod_url = THETA + "/v3/option/history/eod?" + urlencode({
            "symbol": ticker, "expiration": str(exp).replace("-", ""),
            "date": date.replace("-", ""), "right": direction, "format": "json",
        })
        if opener:
            et, eh = opener(eod_url)
        else:
            et, eh = _get(eod_url)
        out["eod_request"] = eod_url
        out["eod_response_hash"] = eh
        erows = _pick_atm(_rows(json.loads(et) if et else []), direction)
        emids = [_mid(r) for r in erows if r.get("strike") and abs(float(r.get("strike")) - atm) < 1e-6]
        emids = [m for m in emids if m]
        if emids and mid_x:
            eod = emids[0]
            if abs(eod - mid_x) / mid_x > 0.05:
                out["second_source_mismatch"] = True
                out["eod_mid"] = eod
    except Exception:
        pass
    return out


def run(date: str, brief_path: Path | None = None, *, write_shared: bool = False, opener=None) -> dict:
    if not theta_up() and opener is None:
        rec = {"kind": "theta_down", "date": date}
        if write_shared:
            _shared("theta_down", rec)
        return rec
    path = brief_path or (BRIEFS / f"{date}-morning.json")
    if not path.is_file():
        # ds json sometimes nested
        alt = BRIEFS / f"{date}-morning.md"
        path = path if path.is_file() else alt
    if path.suffix == ".md" and path.is_file():
        text = path.read_text(encoding="utf-8")
        brief = json.loads(text.split("\n", 2)[2] if text.startswith("{") is False and "\n{" in text else text)
        if not isinstance(brief, dict):
            brief = {}
    else:
        brief = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if "ds" in brief and isinstance(brief["ds"], dict) and brief["ds"].get("candidates"):
        src = brief["ds"]
    elif "candidates" in brief:
        src = brief
    else:
        src = brief.get("review") and brief or brief
        # morning.json wraps ds inside a key
        for v in brief.values():
            if isinstance(v, dict) and v.get("candidates"):
                src = v
                break
    legs_in = extract_legs(src if isinstance(src, dict) else {})
    settled = [settle_leg(L, date, opener=opener) for L in legs_in]
    unsettled = sum(1 for x in settled if x.get("unsettled"))
    total = sum(float(x["pnl"]) for x in settled if x.get("pnl") is not None)
    doc = {
        "date": date,
        "n_legs": len(settled),
        "n_unsettled": unsettled,
        "total_pnl": total,
        "legs": settled,
    }
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    outp = LEDGER_ROOT / f"{date}.json"
    outp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    doc["path"] = str(outp)
    if write_shared:
        _shared("option.shadow_ledger", {
            "date": date, "n_legs": doc["n_legs"], "total_pnl": total, "n_unsettled": unsettled,
        })
    return doc


def _shared(kind: str, rec: dict) -> None:
    try:
        from harness.config import load_config
        from harness.db import Store
        from harness.memory_bridge import MemoryBridge
        cfg = load_config()
        mb = MemoryBridge(Store(cfg.core.db_path))
        mb.offer({
            "receipt_id": f"{kind}:{rec.get('date') or rec.get('kind')}",
            "event_id": f"{kind}:{rec.get('date') or rec.get('kind')}",
            "mid": kind,
            "result": json.dumps(rec, ensure_ascii=False),
            "status": kind,
            "ts": datetime.now(PT).timestamp(),
        }, kind="工作日志")
    except Exception:
        pass
