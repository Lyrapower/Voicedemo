"""ex-post S&P 500 PIT reconstruction. 402 / missing evidence → blocked. No adv500 auto-switch."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def reconstruct(
    snapshot: dict[str, Any],
    events: list[dict[str, Any]],
    rename_map: dict[str, str] | None = None,
) -> dict[str, set[str]]:
    """Forward/back from a dated full snapshot using add/remove/rename events (effective date).

    snapshot: {date: 'YYYY-MM-DD', members: [symbols]}
    events: {date, action: add|remove|rename, symbol, new_symbol?}
    rename_map: old → stable id (applied to every date).
    Returns members_on[date] for every event/snapshot date plus a contiguous fill is
    the caller's calendar job — this function returns change-point sets.
    """
    rename_map = {k.upper(): v.upper() for k, v in (rename_map or {}).items()}

    def sid(sym: str) -> str:
        s = str(sym).upper()
        return rename_map.get(s, s)

    snap_d = str(snapshot["date"])[:10]
    members = {sid(s) for s in snapshot.get("members") or snapshot.get("symbols") or []}
    dated: dict[str, set[str]] = {snap_d: set(members)}
    evs = sorted(events, key=lambda e: str(e.get("date") or e.get("effectiveDate") or ""))
    # forward from snapshot
    cur = set(members)
    for e in evs:
        d = str(e.get("date") or e.get("effectiveDate") or "")[:10]
        if not d or d < snap_d:
            continue
        act = str(e.get("action") or e.get("type") or "").lower()
        sym = sid(str(e.get("symbol") or e.get("addedTicker") or e.get("removedTicker") or ""))
        if act in ("add", "added"):
            cur.add(sym)
        elif act in ("remove", "removed", "delete"):
            cur.discard(sym)
        elif act == "rename":
            new = sid(str(e.get("new_symbol") or e.get("newTicker") or ""))
            cur.discard(sym)
            if new:
                cur.add(new)
        dated[d] = set(cur)
    # backward from snapshot
    cur = set(members)
    for e in reversed(evs):
        d = str(e.get("date") or e.get("effectiveDate") or "")[:10]
        if not d or d >= snap_d:
            continue
        act = str(e.get("action") or e.get("type") or "").lower()
        sym = sid(str(e.get("symbol") or e.get("addedTicker") or e.get("removedTicker") or ""))
        # invert
        if act in ("add", "added"):
            cur.discard(sym)
        elif act in ("remove", "removed", "delete"):
            cur.add(sym)
        elif act == "rename":
            new = sid(str(e.get("new_symbol") or e.get("newTicker") or ""))
            cur.discard(new)
            if sym:
                cur.add(sym)
        dated[d] = set(cur)
    return dated


def members_on_calendar(dated: dict[str, set[str]], calendar: list[str]) -> dict[str, set[str]]:
    """Step function: last known change-point on or before t."""
    keys = sorted(dated)
    out: dict[str, set[str]] = {}
    i = -1
    for t in calendar:
        while i + 1 < len(keys) and keys[i + 1] <= t:
            i += 1
        if i >= 0:
            out[t] = set(dated[keys[i]])
    return out


def fetch_fmp_json(url: str, timeout: int = 20) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": "regime-ic-v4"})
    try:
        with urlopen(req, timeout=timeout) as r:
            body = r.read()
            return {"ok": True, "status": getattr(r, "status", 200), "data": json.loads(body.decode())}
    except HTTPError as e:
        return {"ok": False, "status": e.code, "blocked": e.code == 402, "reason": f"HTTP {e.code}"}
    except URLError as e:
        return {"ok": False, "status": None, "blocked": False, "reason": str(e.reason)}
    except Exception as e:
        return {"ok": False, "status": None, "blocked": False, "reason": type(e).__name__}


def pit_status(constituent_fetch: dict[str, Any], rename_fetch: dict[str, Any] | None) -> dict[str, Any]:
    """R9: 402 or thin coverage → blocked. Never auto-switch adv500."""
    if constituent_fetch.get("blocked") or constituent_fetch.get("status") == 402:
        return {
            "universe": "sp500_pit",
            "verdict": "blocked",
            "reason": "historical-sp500-constituent 402 or blocked",
            "tag": "ex-post PIT reconstruction",
            "adv500_auto": False,
        }
    data = constituent_fetch.get("data")
    n = len(data) if isinstance(data, list) else 0
    if not constituent_fetch.get("ok") or n == 0:
        return {
            "universe": "sp500_pit",
            "verdict": "blocked",
            "reason": constituent_fetch.get("reason") or "no constituent events",
            "tag": "ex-post PIT reconstruction",
            "adv500_auto": False,
        }
    rename_ok = True
    if rename_fetch is not None and not rename_fetch.get("ok"):
        rename_ok = False
    return {
        "universe": "sp500_pit",
        "verdict": "ok" if rename_ok else "blocked_renames",
        "n_events": n,
        "tag": "ex-post PIT reconstruction",
        "adv500_auto": False,
        "rename_ok": rename_ok,
    }


def adv500_feasibility(*, has_full_investable: bool, has_adv20: bool, has_list_delist: bool, has_stable_id: bool) -> dict[str, Any]:
    """R9: only Lyra may select adv500_pit. Current-library subset is not adv500_pit."""
    ready = has_full_investable and has_adv20 and has_list_delist and has_stable_id
    return {
        "option": "adv500_pit",
        "ready": ready,
        "has_full_investable_tminus1": has_full_investable,
        "has_adv20_px_vol": has_adv20,
        "has_list_delist_stable_id": has_list_delist and has_stable_id,
        "note": "current daily_bars subset must not be named adv500_pit",
        "blocked_unless_lyra": True,
    }
