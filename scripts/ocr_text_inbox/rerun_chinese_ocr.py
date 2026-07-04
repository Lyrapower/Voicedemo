#!/usr/bin/env python3
"""
Re-OCR all Mac Photos screenshots with Chinese + English Vision languages.
Overwrites monthly .md files, then rebuilds _monthly_review.md and ocr_index.json.

Run from Terminal.app:
  cd ~/Desktop/demo && .venv_ocr_inbox/bin/python scripts/ocr_text_inbox/rerun_chinese_ocr.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Reuse inbox helpers
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))
from scripts.ocr_text_inbox import inbox_export as ie  # noqa: E402

OUT_DIR = ie.OUT_DIR
_export_asset_to_temp_timed = ie._export_asset_to_temp_timed
_iso = ie._iso
_md_filename = ie._md_filename
_render_md = ie._render_md
_vision_ocr = ie._vision_ocr
_ocr_screenshot_image = ie._ocr_screenshot_image
SkipImageScreenshot = ie.SkipImageScreenshot

MONTHS = [f"2025-{m:02d}" for m in range(8, 13)] + [f"2026-{m:02d}" for m in range(1, 6)]
MONTH_SET = set(MONTHS)
RERUN_LOG = OUT_DIR / "rerun_chinese_progress.txt"
# Opt-in full re-OCR only; default pipeline uses restore_prioritized --missing-rebuild
CUTOFF_START = date(2025, 8, 1)
CUTOFF_END = date(2026, 5, 20)


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    RERUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RERUN_LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    print(msg, flush=True)


def _month_folder(d: date) -> Optional[Path]:
    k = f"{d.year}-{d.month:02d}"
    if k not in MONTH_SET:
        return None
    return OUT_DIR / k


def _fetch_screenshots():
    import Photos
    from Foundation import NSDate, NSPredicate

    sub = Photos.PHAssetMediaSubtypePhotoScreenshot
    t0 = datetime(2025, 8, 1, tzinfo=timezone.utc).timestamp()
    t1 = datetime(2026, 5, 21, tzinfo=timezone.utc).timestamp()
    d0 = NSDate.dateWithTimeIntervalSince1970_(t0)
    d1 = NSDate.dateWithTimeIntervalSince1970_(t1)
    pred = NSPredicate.predicateWithFormat_(
        "(mediaSubtype & %d) != 0 AND creationDate >= %@ AND creationDate < %@",
        sub,
        d0,
        d1,
    )
    opts = Photos.PHFetchOptions.alloc().init()
    opts.setPredicate_(pred)
    return Photos.PHAsset.fetchAssetsWithOptions_(opts)


def _asset_created(asset) -> datetime:
    from Foundation import NSDate

    dt = asset.creationDate()
    if isinstance(dt, NSDate):
        return datetime.fromtimestamp(float(dt.timeIntervalSince1970()), tz=timezone.utc)
    return datetime.now(timezone.utc)


def rerun_all(*, limit: Optional[int] = None) -> Dict[str, int]:
    import Photos

    stats = {"ok": 0, "skip": 0, "fail": 0}
    assets = _fetch_screenshots()
    total = int(assets.count())
    _log(f"Re-OCR start: {total} screenshots (zh-Hans + zh-Hant + en-US)")

    for i in range(total):
        if limit is not None and stats["ok"] >= limit:
            break
        asset = assets.objectAtIndex_(i)
        asset_id = str(asset.localIdentifier())
        created_dt = _asset_created(asset)
        shot_date = created_dt.date()

        folder = _month_folder(shot_date)
        if not folder:
            stats["skip"] += 1
            continue

        folder.mkdir(parents=True, exist_ok=True)
        md_path = folder / _md_filename(asset_id)
        created = _iso(created_dt)

        tmp: Optional[Path] = None
        try:
            tmp = _export_asset_to_temp_timed(asset)
            text = _ocr_screenshot_image(tmp)
        except SkipImageScreenshot as e:
            stats["skip"] += 1
            if stats["skip"] % 100 == 1:
                _log(f"SKIP image [{i+1}/{total}] {asset_id}: {e}")
            continue
        except Exception as e:
            stats["fail"] += 1
            if md_path.is_file():
                stats["skip"] += 1
                if stats["fail"] % 100 == 1:
                    _log(f"KEEP [{i+1}/{total}] {md_path.name} (re-OCR failed, kept existing): {e}")
            elif stats["fail"] <= 30 or stats["fail"] % 200 == 0:
                _log(f"FAIL [{i+1}/{total}] {asset_id}: {e}")
            continue
        finally:
            if tmp and tmp.is_file():
                tmp.unlink(missing_ok=True)

        md_path.write_text(
            _render_md(created=created, asset_id=asset_id, text=text),
            encoding="utf-8",
        )
        stats["ok"] += 1
        if stats["ok"] % 50 == 0 or stats["ok"] == 1:
            cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
            _log(f"OK [{i+1}/{total}] {md_path.name} cjk_chars={cjk} ({stats['ok']} done)")

    _log(f"Re-OCR done: ok={stats['ok']} skip={stats['skip']} fail={stats['fail']}")
    return stats


def rebuild_monthly_and_index() -> None:
    build_script = Path(__file__).resolve().parent / "build_monthly.py"
    subprocess.run([sys.executable, str(build_script)], check=True)
    _log("Monthly reviews and ocr_index.json rebuilt.")


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 1

    limit = None
    if "--test" in sys.argv:
        limit = 5
    if "--rebuild-only" in sys.argv:
        rebuild_monthly_and_index()
        return 0

    rerun_all(limit=limit)
    rebuild_monthly_and_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
