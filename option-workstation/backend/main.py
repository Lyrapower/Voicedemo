"""Option Workstation · :8620 · v1.2 desk(Scout tab + workstation)
宪法:数字全出确定性引擎;七问=脊柱;仪表带来源+时间戳;模型类读数带假设。
desk UI: / → Scout+8620 双 Tab(sample 卡片风); /workstation → 原七问驾驶舱。
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import cleaning, datastore, gex, strategy

_ET = ZoneInfo("America/New_York")  # trading-date logic uses ET (DST-aware)

app = FastAPI(title="option-workstation", version="1.3-scout-wiring")
STATIC = Path(os.getenv("STATIC_DIR", "/app/static"))
# SCOUT_DIR/briefs — env only, 禁写死绝对路径(CURSOR SCOUT UI WIRING v1 · T1)
SCOUT_BRIEFS = Path(os.getenv("SCOUT_BRIEFS", os.getenv("SCOUT_DIR", "/data/scout_briefs")))
if (SCOUT_BRIEFS / "briefs").is_dir() and not list(SCOUT_BRIEFS.glob("*-morning.html")):
    SCOUT_BRIEFS = SCOUT_BRIEFS / "briefs"
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:8501").rstrip("/")
_CACHE: dict = {}
_ATM_IV: dict = {}

# aether OPTION(:8501) 同源读 /api/scout/entry — 本机跨端口需 CORS；ts.net /ows 同 origin 不依赖此
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$|^https://[\w.-]+\.ts\.net$",
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# T1 · 静态服务 briefs/(同一渲染器落盘;页面链接按 hostname 动态拼)
if SCOUT_BRIEFS.is_dir():
    app.mount("/briefs", StaticFiles(directory=str(SCOUT_BRIEFS)), name="briefs")


def _nocache_html(text: str) -> HTMLResponse:
    return HTMLResponse(
        text,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.on_event("startup")
def _boot():
    if not datastore.list_dates():
        # O1: previously auto-generated 120 days of synthetic (source=synthetic-v1) on
        # every boot when data was empty — consumers that don't filter `source` then
        # rendered fake GEX/IVP as if live. Now require explicit opt-in via
        # OWS_ALLOW_SYNTHETIC=1; otherwise leave empty and surface a no-data state.
        if os.getenv("OWS_ALLOW_SYNTHETIC", "").strip() in ("1", "true", "True"):
            n = datastore.gen_synthetic(days=120)
            print(
                "[ows] 无数据 → 生成合成快照 %d 日(source=synthetic-v1 · 显式 opt-in);"
                "买断数据到位后按 README loader 替换" % n,
                flush=True,
            )
        else:
            print("[ows] 无数据且 OWS_ALLOW_SYNTHETIC 未设 → 不生成合成链（避免假 GEX 渲染）", flush=True)
    print("[ows] desk UI · SCOUT_BRIEFS=%s · GW=%s" % (SCOUT_BRIEFS, GATEWAY_URL), flush=True)


def _cleaned(date, root=datastore.DEFAULT_ROOT):
    key = (root, date)
    if key not in _CACHE:
        snap = datastore.load_raw(date, root=root)
        _CACHE[key] = (snap, cleaning.clean_snapshot(snap))
        if len(_CACHE) > 40:
            _CACHE.pop(next(iter(_CACHE)))
    return _CACHE[key]


def _atm_hist(upto, root=datastore.DEFAULT_ROOT, dte=30, lookback=252):
    ivs = []
    for d in datastore.list_dates(root):
        if d > upto:
            break
        key = (root, d)
        if key not in _ATM_IV:
            snap, cl = _cleaned(d, root)
            rows = [r for r in cl["clean"] if r["dte"] == dte]
            _ATM_IV[key] = (
                min(rows, key=lambda x: abs(x["m"]))["iv"] if rows else None
            )
        if _ATM_IV[key] is not None:
            ivs.append(_ATM_IV[key])
    return ivs[-lookback:]


@app.get("/api/health")
def health():
    roots = datastore.list_roots()
    return {
        "ok": True,
        "version": "1.3-scout-wiring",
        "roots": roots,
        "dates": {r: len(datastore.list_dates(r)) for r in roots},
        "scout_briefs": str(SCOUT_BRIEFS),
        "scout_briefs_ok": SCOUT_BRIEFS.is_dir(),
        "briefs_mount": "/briefs",
    }


@app.get("/api/scout/entry")
def scout_entry(date: str | None = None):
    """8620 Scout tab 入口卡读数——只读 briefs JSON,不重算判断。

    取最新班次(morning/midday/earnings/evening)按文件 mtime;指定 date 时取该日最新班次。
    """
    import datetime as _dt

    day = (date or _dt.datetime.now(_ET).date().isoformat()).strip()[:10]
    # 该日所有班次 json
    cands = [p for p in SCOUT_BRIEFS.glob(f"{day}-*.json") if _shift_from_name(p.name)]
    # 未显式传 date 且今日无文件 → 最新班次(跨日回退)
    if not date and not cands and SCOUT_BRIEFS.is_dir():
        cands = [p for p in SCOUT_BRIEFS.glob("*.json") if _shift_from_name(p.name)]
    if not cands:
        return {
            "date": day,
            "mode": None,
            "morning_json": False,
            "morning_html": False,
            "evening_html": False,
            "liquidation_watch": None,
            "distribution_risk": None,
            "regime": None,
            "gray": True,
        }
    jp = max(cands, key=lambda x: x.stat().st_mtime)
    shift = _shift_from_name(jp.name)
    day = jp.name[:10]
    hp = SCOUT_BRIEFS / f"{day}-{shift}.html"
    ep = SCOUT_BRIEFS / f"{day}-evening.html"
    out = {
        "date": day,
        "mode": shift,
        "morning_json": False,
        "morning_html": hp.is_file(),
        "evening_html": ep.is_file(),
        "liquidation_watch": None,
        "distribution_risk": None,
        "regime": None,
        "gray": True,
    }
    if jp.is_file():
        try:
            j = json.loads(jp.read_text(encoding="utf-8"))
            # v3.6: {_engine, ds}; 旧落盘: {data, indices, review}
            eng = j.get("_engine") or {}
            ds = j.get("ds") if isinstance(j.get("ds"), dict) else (j.get("data") or {})
            hd = (ds.get("hedge") if isinstance(ds, dict) else None) or {}
            rev = j.get("review") if isinstance(j.get("review"), dict) else {}
            origin = rev.get("review_origin") or (
                (rev.get("expanded_meta") or {}).get("review_origin")
            )
            out.update(
                {
                    "morning_json": True,
                    "gray": False,
                    "liquidation_watch": bool(eng.get("liquidation_watch")),
                    "distribution_risk": hd.get("distribution_risk"),
                    "regime": hd.get("regime"),
                    "review_origin": origin,
                }
            )
        except Exception as e:
            out["error"] = str(e)[:200]
    return out


@app.get("/api/dates")
def dates(root: str | None = None):
    return datastore.list_dates(root)


@app.get("/api/day/{date}")
def day(date: str, root: str | None = None):
    try:
        snap, cl = _cleaned(date, root=root or datastore.DEFAULT_ROOT)
    except FileNotFoundError:
        raise HTTPException(404, "no snapshot")
    feats = cleaning.features(snap, cl, _atm_hist(date, root=root or datastore.DEFAULT_ROOT))
    gx = gex.net_gex(snap, cl)
    return {
        "snap": {k: snap[k] for k in ("date", "underlying", "spot", "ts", "source")},
        "gauges": cl["gauges"],
        "smiles": cl["smiles"],
        "features": feats,
        "chain": cl["clean"],
        "quarantine_sample": cl["quarantine"][:20],
        "gex": gx,
    }


@app.post("/api/strategy/{date}")
async def strat(date: str, req: Request, root: str | None = None):
    body = await req.json()
    snap, cl = _cleaned(date, root=root or datastore.DEFAULT_ROOT)
    rows = [r for r in cl["clean"] if r["dte"] == 30]
    if not rows:
        return JSONResponse(
            {"error": "无 30d 清洗后数据,ATM IV 不可得——POP/评估拒算(不硬编)"},
            status_code=400,
        )
    atm_iv = min(rows, key=lambda x: abs(x["m"]))["iv"]
    card = strategy.evaluate(snap, cl, body.get("legs", []), atm_iv)
    return JSONResponse(card, status_code=(400 if "error" in card else 200))


_SHIFT_SUFFIXES = ("morning", "midday", "earnings", "evening")


def _shift_from_name(name: str) -> str | None:
    for s in _SHIFT_SUFFIXES:
        if f"-{s}." in name:
            return s
    return None


def _scout_from_briefs() -> dict | None:
    if not SCOUT_BRIEFS.is_dir():
        return None
    cands = [p for p in SCOUT_BRIEFS.glob("*.json") if _shift_from_name(p.name)]
    if not cands:
        return None
    p = max(cands, key=lambda x: x.stat().st_mtime)
    shift = _shift_from_name(p.name)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    # scout write: {"data": ..., "indices": ...} or bare schema
    data = doc.get("data") if isinstance(doc, dict) and "data" in doc else doc
    indices = doc.get("indices") if isinstance(doc, dict) else {}
    date = p.name.replace(f"-{shift}.json", "")
    final_md = SCOUT_BRIEFS / f"{date}-{shift}-final.md"
    glm = final_md.read_text(encoding="utf-8") if final_md.is_file() else ""
    return {
        "date": date,
        "mode": shift,
        "data": data if isinstance(data, dict) else None,
        "indices": indices or {},
        "glm_final": glm,
        "via": "scout_briefs:" + p.name,
        "brief_path": str(p),
    }


def _scout_from_gateway() -> dict | None:
    url = (
        GATEWAY_URL
        + "/store/events/recent?source=aether&kinds=aether_scout_brief&per_kind=4"
    )
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            events = json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(events, list) or not events:
        return None
    # prefer morning
    pick = None
    for ev in events:
        p = (ev or {}).get("payload") or {}
        if p.get("mode") == "morning":
            pick = ev
            break
    pick = pick or events[0]
    p = pick.get("payload") or {}
    structured = p.get("structured")
    if isinstance(structured, dict) and "data" in structured and "macro" not in structured:
        structured = structured.get("data")
    return {
        "date": p.get("date"),
        "mode": p.get("mode") or "morning",
        "data": structured,
        "indices": p.get("indices") or {},
        "vix": p.get("vix"),
        "glm_final": p.get("glm_final") or p.get("body") or "",
        "ds_draft": p.get("ds_draft") or "",
        "via": p.get("via") or "aether_store",
        "console_ds_task": p.get("console_ds_task"),
        "console_glm_task": p.get("console_glm_task"),
        "brief_path": p.get("brief_path"),
        "event_id": pick.get("id"),
    }


@app.get("/api/scout/latest")
def scout_latest():
    """Scout Agent 晨会结构化简报 → desk Tab1。优先本地 briefs,其次 8501 store。"""
    out = _scout_from_briefs() or _scout_from_gateway()
    if not out:
        # sample fallback for empty UI shape
        sample = STATIC / "brief_sample.html"
        return {
            "date": None,
            "mode": "morning",
            "data": None,
            "indices": {},
            "glm_final": "",
            "via": "empty",
            "sample_hint": sample.exists(),
            "error": "no scout brief yet",
        }
    return out


def _latest_brief_html() -> Path | None:
    if not SCOUT_BRIEFS.is_dir():
        return None
    cands = [p for p in SCOUT_BRIEFS.glob("*.html") if _shift_from_name(p.name)]
    # prefer live over .sample.html
    cands = [p for p in cands if not p.name.endswith(".sample.html")]
    if not cands:
        return None
    return max(cands, key=lambda x: x.stat().st_mtime)


@app.get("/brief")
def brief_view(sample: int = 0):
    """Scout Tab iframe 目标。

    默认 = 最新实跑 *-morning.html(无假卡)。
    ?sample=1 = brief sample 作业 UI(含 PLTR 假卡,仅对照样式)。
    """
    sample_p = STATIC / "brief_sample.html"
    if sample:
        if sample_p.is_file():
            return _nocache_html(sample_p.read_text(encoding="utf-8"))
        return JSONResponse({"error": "brief sample missing"}, status_code=404)
    live_p = _latest_brief_html()
    if live_p and live_p.is_file():
        return _nocache_html(live_p.read_text(encoding="utf-8"))
    if sample_p.is_file():
        return _nocache_html(sample_p.read_text(encoding="utf-8"))
    return JSONResponse({"error": "no scout brief html"}, status_code=404)


@app.get("/brief_sample.html")
def brief_sample_static():
    f = STATIC / "brief_sample.html"
    if not f.exists():
        return JSONResponse({"error": "brief_sample.html missing"}, status_code=404)
    return _nocache_html(f.read_text(encoding="utf-8"))


@app.get("/")
def desk():
    f = STATIC / "desk.html"
    if not f.exists():
        return JSONResponse({"error": "desk.html missing"}, status_code=500)
    return _nocache_html(f.read_text(encoding="utf-8"))


@app.get("/workstation")
def workstation():
    f = STATIC / "index.html"
    if not f.exists():
        return JSONResponse({"error": "static missing"}, status_code=500)
    return _nocache_html(f.read_text(encoding="utf-8"))


@app.get("/desk")
def desk_alias():
    return desk()
