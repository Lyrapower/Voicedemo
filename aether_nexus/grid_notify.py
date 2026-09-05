"""Grid store + ntfy bridge for intraday momentum (report-only)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from aether_grid_emit import emit_momentum

logger = logging.getLogger(__name__)

NTFY_URL = os.getenv("NTFY_URL", "").strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
NTFY_TOKEN = os.getenv("NTFY_TOKEN", "").strip()
CRITICAL_SCORE_MIN = float(os.getenv("MOMENTUM_CRITICAL_SCORE", "60"))


def momentum_score(hit: dict[str, Any]) -> float:
    vol = float(hit.get("vol_ratio") or 0)
    brk = float(hit.get("breakout") or 0)
    opt = float(hit.get("opt_ratio") or 0)
    return min(100.0, vol * 18.0 + brk * 500.0 + opt * 12.0)


def has_breakout_confirmation(hit: dict[str, Any]) -> bool:
    return any("突破" in str(h) for h in (hit.get("hits") or []))


def notify(message: str, priority: str = "normal") -> bool:
    """Push to ntfy. Only critical priority rings on phone."""
    if priority != "critical":
        return False
    url = NTFY_URL or (f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else "")
    if not url:
        logger.debug("ntfy skipped: NTFY_URL/NTFY_TOPIC unset")
        return False
    headers: dict[str, str] = {"Title": "Aether Alert", "Content-Type": "text/plain; charset=utf-8"}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    headers["Priority"] = "5"
    headers["Tags"] = "rotating_light"
    try:
        resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
        ok = resp.status_code in (200, 201)
        if not ok:
            logger.warning("ntfy failed HTTP %s %s", resp.status_code, resp.text[:120])
        return ok
    except Exception as exc:
        logger.warning("ntfy error: %s", exc)
        return False


def publish_momentum_hit(
    *,
    sym: str,
    note: str,
    hit: dict[str, Any],
    label: str = "MomentumSticker",
) -> dict[str, Any]:
    """Always store; ntfy critical only for score≥60 + breakout confirmation."""
    score = round(momentum_score(hit), 1)
    direction = 1 if float(hit.get("breakout") or 0) >= 0 else -1
    row = {"sym": sym.upper(), "note": note, "dir": direction, "score": score}
    emit_momentum([row], label=label)
    critical = score >= CRITICAL_SCORE_MIN and has_breakout_confirmation(hit)
    pushed = False
    if critical:
        pushed = notify(f"🔔 {sym} score={score:.0f} · {note}", priority="critical")
    return {"row": row, "score": score, "critical": critical, "ntfy": pushed, "store": True}
