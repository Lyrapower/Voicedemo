"""Write clean monthly Markdown and side-channel raw_text + logs."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Each: window_start inclusive, window_end exclusive (except last uses inclusive end in contains()), filename, title_start, title_end inclusive for heading
MONTHLY_WINDOWS: List[Tuple[date, date, str, date, date, bool]] = [
    (date(2025, 8, 1), date(2025, 9, 1), "2025-08_to_2025-09.md", date(2025, 8, 1), date(2025, 8, 31), False),
    (date(2025, 9, 1), date(2025, 10, 1), "2025-09_to_2025-10.md", date(2025, 9, 1), date(2025, 9, 30), False),
    (date(2025, 10, 1), date(2025, 11, 1), "2025-10_to_2025-11.md", date(2025, 10, 1), date(2025, 10, 31), False),
    (date(2025, 11, 1), date(2025, 12, 1), "2025-11_to_2025-12.md", date(2025, 11, 1), date(2025, 11, 30), False),
    (date(2025, 12, 1), date(2026, 1, 1), "2025-12_to_2026-01.md", date(2025, 12, 1), date(2025, 12, 31), False),
    (date(2026, 1, 1), date(2026, 2, 1), "2026-01_to_2026-02.md", date(2026, 1, 1), date(2026, 1, 31), False),
    (date(2026, 2, 1), date(2026, 3, 1), "2026-02_to_2026-03.md", date(2026, 2, 1), date(2026, 2, 28), False),
    (date(2026, 3, 1), date(2026, 4, 1), "2026-03_to_2026-04.md", date(2026, 3, 1), date(2026, 3, 31), False),
    (date(2026, 4, 1), date(2026, 4, 24), "2026-04-01_to_2026-04-23.md", date(2026, 4, 1), date(2026, 4, 23), True),
]


def window_for_date(d: date) -> Optional[Tuple[date, date, str, date, date, bool]]:
    for ws, we, fn, ts, te, is_last in MONTHLY_WINDOWS:
        if is_last:
            if ws <= d <= te:
                return (ws, we, fn, ts, te, is_last)
        else:
            if ws <= d < we:
                return (ws, we, fn, ts, te, is_last)
    return None


def _group_by_day(entries: List[Dict[str, Any]]) -> Dict[date, List[Dict[str, Any]]]:
    by_day: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
    for e in sorted(entries, key=lambda x: (x["shot_date"], x["filename"])):
        by_day[e["shot_date"]].append(e)
    return by_day


def render_monthly_markdown(
    title_start: date,
    title_end: date,
    grouped: Dict[date, List[Dict[str, Any]]],
    source_label: str,
) -> str:
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# iCloud Screenshot OCR: {title_start.isoformat()} to {title_end.isoformat()}",
        "",
        f"Generated: {gen}",
        "",
        f"Source: {source_label}",
        "",
    ]
    if not grouped:
        lines.append("No screenshots found for this date range.")
        lines.append("")
        return "\n".join(lines)

    for day in sorted(grouped.keys()):
        lines.append(f"## {day.isoformat()}")
        lines.append("")
        for i, e in enumerate(grouped[day], 1):
            lines.append(f"### Screenshot {i}")
            lines.append("")
            lines.append(f"Source: {e['filename']}")
            lines.append("")
            body = (e.get("ocr") or "").strip()
            if body:
                lines.append(body)
            else:
                lines.append("(no text recognized)")
            lines.append("")
            lines.append("---")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_raw_sidecar(raw_dir: Path, window_fn: str, payload: Dict[str, Any]) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    safe = window_fn.replace(".md", "")
    (raw_dir / f"{safe}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_monthly_bundle(
    out_dir: Path,
    raw_dir: Path,
    log_dir: Path,
    *,
    entries: List[Dict[str, Any]],
    source_label: str,
    log_lines: List[str],
) -> None:
    """Partition entries into monthly files; write md, raw_text json per month, append logs."""
    log_dir.mkdir(parents=True, exist_ok=True)
    buckets: Dict[str, List[Dict[str, Any]]] = {w[2]: [] for w in MONTHLY_WINDOWS}

    for e in entries:
        w = window_for_date(e["shot_date"])
        if not w:
            log_lines.append(f"skip_out_of_window_assignment: {e['path']} date={e['shot_date']}")
            continue
        buckets[w[2]].append(e)

    for ws, we, fn, ts, te, is_last in MONTHLY_WINDOWS:
        group = buckets[fn]
        by_day = _group_by_day(group)
        md = render_monthly_markdown(ts, te, by_day, source_label)
        (out_dir / fn).write_text(md, encoding="utf-8")

        raw_payload = {
            "window_file": fn,
            "window_start": ws.isoformat(),
            "window_end_exclusive": we.isoformat(),
            "entries": [
                {
                    "filename": e["filename"],
                    "shot_date": e["shot_date"].isoformat(),
                    "ocr": e.get("ocr") or "",
                    "ocr_sha256": hashlib.sha256((e.get("ocr") or "").encode()).hexdigest(),
                    "internal_path": e["path"],
                    "engine": e.get("engine"),
                }
                for e in sorted(group, key=lambda x: (x["shot_date"], x["filename"]))
            ],
        }
        write_raw_sidecar(raw_dir, fn, raw_payload)

    (log_dir / "export.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


def write_single_range(
    out_path: Path,
    raw_dir: Path,
    log_dir: Path,
    *,
    range_start: date,
    range_end_exclusive: date,
    entries: List[Dict[str, Any]],
    source_label: str,
    log_lines: List[str],
) -> None:
    """Single file for [range_start, range_end_exclusive)."""
    title_end = range_end_exclusive - timedelta(days=1)
    by_day = _group_by_day(entries)
    md = render_monthly_markdown(range_start, title_end, by_day, source_label)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_entries = [
        {
            "filename": e["filename"],
            "shot_date": e["shot_date"].isoformat(),
            "ocr": e.get("ocr") or "",
            "ocr_sha256": hashlib.sha256((e.get("ocr") or "").encode()).hexdigest(),
            "internal_path": e["path"],
            "engine": e.get("engine"),
        }
        for e in sorted(entries, key=lambda x: (x["shot_date"], x["filename"]))
    ]
    write_raw_sidecar(
        raw_dir,
        out_path.name,
        {"single_out": str(out_path), "range_start": range_start.isoformat(), "entries": raw_entries},
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "export_single.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
