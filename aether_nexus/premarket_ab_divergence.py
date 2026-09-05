"""Premarket A/B divergence — push only symbols where chains disagree."""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any

from aether_shared import send_notification

logger = logging.getLogger(__name__)

_CONF_RANK = {"观察": 0, "试探性": 1, "高置信": 2}


def _parse_conf(value: str) -> str:
    m = re.search(r"\[(高置信|试探性|观察)\]", value or "")
    return m.group(1) if m else "观察"


def _parse_dir(value: str, fallback: int = 0) -> int:
    v = value or ""
    if "多" in v or "long" in v.lower():
        return 1
    if "空" in v or "short" in v.lower() or "bear" in v.lower():
        return -1
    return fallback


def items_by_sym(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for it in items or []:
        sym = str(it.get("sym") or "").upper()
        if sym:
            out[sym] = it
    return out


def is_divergent(grid_it: dict[str, Any] | None, sonnet_it: dict[str, Any] | None) -> bool:
    if not grid_it or not sonnet_it:
        return bool(grid_it) ^ bool(sonnet_it)
    gv = str(grid_it.get("value") or "")
    sv = str(sonnet_it.get("value") or "")
    gd = int(grid_it.get("dir") if grid_it.get("dir") is not None else _parse_dir(gv))
    sd = int(sonnet_it.get("dir") if sonnet_it.get("dir") is not None else _parse_dir(sv))
    if gd != sd:
        return True
    gc = _parse_conf(gv)
    sc = _parse_conf(sv)
    return abs(_CONF_RANK.get(gc, 0) - _CONF_RANK.get(sc, 0)) >= 2


def find_divergences(
    grid_items: list[dict[str, Any]],
    sonnet_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gmap = items_by_sym(grid_items)
    smap = items_by_sym(sonnet_items)
    syms = sorted(set(gmap) | set(smap))
    out: list[dict[str, Any]] = []
    for sym in syms:
        g = gmap.get(sym)
        s = smap.get(sym)
        if is_divergent(g, s):
            out.append({"sym": sym, "grid": g, "sonnet": s})
    return out


def format_divergence_push(trade_date: str, divergences: list[dict[str, Any]]) -> str:
    if not divergences:
        return ""
    lines = [f"盘前 A/B 分歧 · {trade_date}", f"共 {len(divergences)} 标的（非全量）", ""]
    for d in divergences[:12]:
        sym = d["sym"]
        gv = (d.get("grid") or {}).get("value") or "—"
        sv = (d.get("sonnet") or {}).get("value") or "—"
        lines.append(f"{sym}: GRID {gv} | SONNET {sv}")
    return "\n".join(lines)


def fetch_premarket_from_store(*, kind: str, trade_date: str) -> list[dict[str, Any]]:
    """Read compiled items from store — used post-compile only, never in Grid prompt."""
    base = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events").rsplit("/", 1)[0]
    url = f"{base}/events/recent?source=aether&kinds={kind}&per_kind=15"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            events = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("fetch premarket %s failed: %s", kind, exc)
        return []
    for ev in events:
        p = ev.get("payload") or {}
        if p.get("date") == trade_date and p.get("items"):
            return list(p["items"])
    for ev in events:
        p = ev.get("payload") or {}
        if p.get("items"):
            return list(p["items"])
    return []


def maybe_push_after_grid(trade_date: str, grid_items: list[dict[str, Any]]) -> dict[str, Any]:
    """After Grid @06:45 — compare with Sonnet store snapshot; push divergences only."""
    sonnet_items = fetch_premarket_from_store(kind="aether_premarket_sonnet", trade_date=trade_date)
    if not sonnet_items:
        logger.info("premarket A/B push skipped: no sonnet items for %s", trade_date)
        return {"pushed": False, "count": 0, "reason": "no_sonnet"}
    return push_divergences_only(
        trade_date=trade_date,
        grid_items=grid_items,
        sonnet_items=sonnet_items,
    )


def push_divergences_only(
    *,
    trade_date: str,
    grid_items: list[dict[str, Any]],
    sonnet_items: list[dict[str, Any]],
) -> dict[str, Any]:
    divs = find_divergences(grid_items, sonnet_items)
    msg = format_divergence_push(trade_date, divs)
    pushed = False
    if msg:
        send_notification(msg)
        pushed = True
        logger.info("premarket A/B divergence push: %d symbols", len(divs))
    else:
        logger.info("premarket A/B: no divergence — skip push")
    return {"divergences": divs, "pushed": pushed, "count": len(divs)}
