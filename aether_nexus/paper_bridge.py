"""Bridge Grid/Aster scan → aether-paper signal inbox (mock only, no broker)."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

NEXUS_DIR = Path(__file__).resolve().parent
PAPER_ROOT = NEXUS_DIR.parent / "aether-paper"
if str(PAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(PAPER_ROOT))

from paper.signals import candidates_to_signals  # noqa: E402
from paper.store import INBOX_PATH, append_jsonl, ensure_state_dir  # noqa: E402
from scan_quarantine import is_quarantined, skip_log  # noqa: E402

SKIP_LOG_PATH = NEXUS_DIR / "logs" / "quarantine_skip.jsonl"


def _record_quarantine_skip(
    *,
    scan_event_id: int | None,
    trade_date: str,
    window: str,
    scan_mode: str,
) -> None:
    SKIP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "consumer": "paper_bridge",
        "reason": "quarantine",
        "scan_event_id": scan_event_id,
        "date": trade_date,
        "window": window,
        "scan_mode": scan_mode,
    }
    with open(SKIP_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def paper_loop_enabled() -> bool:
    return os.getenv("PAPER_LOOP_ENABLED", "true").lower() in ("1", "true", "yes")


def enqueue_scan_candidates(
    candidates: list[dict],
    scan_time: str,
    scan_mode: str,
    *,
    label: str = "",
    scan_event_id: int | None = None,
    trade_date: str = "",
    window: str = "",
) -> int:
    """Append scan-derived paper signals to inbox; returns count enqueued."""
    if not paper_loop_enabled():
        return 0
    if is_quarantined(event_id=scan_event_id, date=trade_date or None, window=window or None):
        skip_log(scan_event_id, consumer="paper_bridge", date=trade_date, window=window)
        _record_quarantine_skip(
            scan_event_id=scan_event_id,
            trade_date=trade_date,
            window=window,
            scan_mode=scan_mode,
        )
        return 0
    if not candidates:
        return 0
    ensure_state_dir()
    signals = candidates_to_signals(
        candidates,
        scan_time=scan_time,
        scan_mode=scan_mode,
        label=label or scan_mode,
    )
    n = 0
    for sig in signals:
        append_jsonl(INBOX_PATH, sig)
        n += 1
    if n:
        logger.info(
            "paper_bridge: enqueued %d signals scan_mode=%s label=%s",
            n,
            scan_mode,
            label,
        )
    return n


def enqueue_from_candidates_file(path: Path | None = None) -> int:
    """Manual replay: read state/candidates.json and enqueue."""
    p = path or (NEXUS_DIR / "state" / "candidates.json")
    if not p.exists():
        return 0
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return enqueue_scan_candidates(
        data.get("rows") or [],
        str(data.get("scan_timestamp") or ""),
        str(data.get("scan_mode") or "dryrun"),
        label="replay",
    )
