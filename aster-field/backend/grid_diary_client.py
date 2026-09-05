"""8790 → 8501 /store/diary/* 桥接（Grid 读回信 + 7 天记忆口径）。"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

_DEMO_ROOT = Path(__file__).resolve().parents[2]
_BASE = os.environ.get("GRID_STORE_BASE", "http://127.0.0.1:8501").rstrip("/")
_TOKEN_PATH = _DEMO_ROOT / "grid-sovereign-runtime" / "config" / "grid_store.token"


def _token() -> str:
    env = (os.environ.get("GRID_STORE_TOKEN") or "").strip()
    if env:
        return env
    if _TOKEN_PATH.is_file():
        return _TOKEN_PATH.read_text(encoding="utf-8").strip()
    return ""


def _headers() -> dict[str, str]:
    hdr = {"Content-Type": "application/json"}
    tok = _token()
    if tok:
        hdr["X-Grid-Token"] = tok
    return hdr


def _entry_date(ts: str) -> str:
    return (ts or "")[:10]


def _grid_diary_event_id_for_exact_date(date: str) -> int | None:
    with httpx.Client(timeout=8.0) as client:
        r = client.get(
            f"{_BASE}/store/diary/thread",
            params={"date": date},
            headers=_headers(),
        )
        r.raise_for_status()
        thread = r.json()
    grid = [e for e in thread if e.get("kind") == "grid_diary"]
    if not grid:
        return None
    return int(grid[-1]["id"])


def grid_diary_event_id(date: str) -> int | None:
    """当日 grid_diary 优先; 否则向前最多 7 天找最近一篇(与 7 天记忆口径一致)。"""
    import datetime as dt

    try:
        start = dt.date.fromisoformat(date)
    except ValueError:
        return None
    for i in range(8):
        d = (start - dt.timedelta(days=i)).isoformat()
        eid = _grid_diary_event_id_for_exact_date(d)
        if eid is not None:
            return eid
    return None


def reply_target_entry_id(entries: list[dict]) -> int | None:
    for e in reversed(entries):
        if grid_diary_event_id(_entry_date(e.get("ts", ""))):
            return int(e["id"])
    return None


def post_reply_for_entry(entry: dict, text: str) -> dict:
    date = _entry_date(entry["ts"])
    event_id = grid_diary_event_id(date)
    if event_id is None:
        raise KeyError(f"no grid_diary for {date}")
    with httpx.Client(timeout=12.0) as client:
        r = client.post(
            f"{_BASE}/store/diary/reply",
            headers=_headers(),
            json={"diary_event_id": event_id, "text": text},
        )
        if r.status_code >= 400:
            detail = r.json().get("detail", r.text) if r.content else r.text
            raise KeyError(str(detail))
        return r.json()


def replies_for_date(date: str) -> list[dict]:
    with httpx.Client(timeout=8.0) as client:
        r = client.get(
            f"{_BASE}/store/diary/thread",
            params={"date": date},
            headers=_headers(),
        )
        r.raise_for_status()
        thread = r.json()
    out: list[dict] = []
    reply_ids: set[int] = set()
    for ev in thread:
        kind = ev.get("kind")
        p = ev.get("payload") or {}
        if kind == "diary_reply":
            reply_ids.add(int(ev["id"]))
            out.append({
                "id": ev["id"],
                "author": "lyra",
                "text": p.get("text", ""),
                "ts": _fmt_ts(ev.get("ts")),
            })
        elif kind == "diary_reply_ack" and p.get("reply_event_id") in reply_ids:
            out.append({
                "id": ev["id"],
                "author": "grid",
                "text": p.get("text", ""),
                "ts": _fmt_ts(ev.get("ts")),
            })
    return out


def _fmt_ts(ts: float | int | str | None) -> str:
    if ts is None:
        return ""
    if isinstance(ts, (int, float)):
        import datetime as dt
        return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    return str(ts)
