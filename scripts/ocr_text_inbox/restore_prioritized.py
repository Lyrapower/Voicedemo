#!/usr/bin/env python3
"""
Restore deleted OCR notes (Chinese content) for 2025-08-01 .. 2026-05-20 only.

Default (--missing-rebuild):
  Phase 1: Re-OCR from Photos only when .md is missing (wrongly deleted as garbage).
           Writes file only if Chinese OCR finds CJK (>=3 chars).
  Phase 2: Rebuild _monthly_review.md + ocr_index.json.

Does NOT touch screenshots before Aug 2025 (stay excluded).
Does NOT re-OCR existing on-disk notes unless you pass --mojibake explicitly.

Run from Terminal.app:
  cd ~/Desktop/demo && .venv_ocr_inbox/bin/python scripts/ocr_text_inbox/restore_prioritized.py
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from scripts.ocr_text_inbox import inbox_export as ie  # noqa: E402
from scripts.ocr_text_inbox.audit_garbage_restoration import (  # noqa: E402
    INBOX,
    is_mojibake_likely,
    ocr_body,
)
from scripts.ocr_text_inbox.date_scope import (  # noqa: E402
    MOJIBAKE_MONTH_SET,
    MONTH_SET,
    RANGE_END,
    RANGE_START,
    in_range,
    range_end_exclusive_utc,
    range_start_utc,
)

MIN_CJK_FOR_CHINESE_RESTORE = 3

OUT_DIR = ie.OUT_DIR
_export_asset_to_temp_timed = ie._export_asset_to_temp_timed
_iso = ie._iso
_md_filename = ie._md_filename
_render_md = ie._render_md
_vision_ocr = ie._vision_ocr
_ocr_screenshot_image = ie._ocr_screenshot_image
SkipImageScreenshot = ie.SkipImageScreenshot
LOG = OUT_DIR / "restore_prioritized_progress.txt"


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
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
    t0 = range_start_utc().timestamp()
    t1 = range_end_exclusive_utc().timestamp()
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
    dt = asset.creationDate()
    if hasattr(dt, "timeIntervalSince1970"):
        return datetime.fromtimestamp(float(dt.timeIntervalSince1970()), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _write_md(asset, *, force: bool, require_chinese: bool = False) -> str:
    asset_id = str(asset.localIdentifier())
    created_dt = _asset_created(asset)
    shot_date = created_dt.date()
    if not in_range(shot_date):
        return "skip"
    folder = _month_folder(shot_date)
    if not folder:
        return "skip"
    md_path = folder / _md_filename(asset_id)
    if md_path.is_file() and not force:
        return "skip"

    tmp: Optional[Path] = None
    try:
        tmp = _export_asset_to_temp_timed(asset)
        text = _ocr_screenshot_image(tmp)
    except SkipImageScreenshot as e:
        _log(f"SKIP image {md_path.relative_to(OUT_DIR)} ({e})")
        return "skip_image"
    except Exception as e:
        if md_path.is_file():
            _log(f"KEEP {md_path.relative_to(OUT_DIR)} (re-OCR failed): {e}")
            return "keep"
        _log(f"FAIL {asset_id}: {e}")
        return "fail"
    finally:
        if tmp and tmp.is_file():
            tmp.unlink(missing_ok=True)

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(
        _render_md(created=_iso(created_dt), asset_id=asset_id, text=text),
        encoding="utf-8",
    )
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    if require_chinese and cjk < MIN_CJK_FOR_CHINESE_RESTORE:
        _log(f"SKIP {md_path.relative_to(OUT_DIR)} (no Chinese in OCR, cjk={cjk})")
        return "skip_not_chinese"
    _log(f"OK {md_path.relative_to(OUT_DIR)} cjk={cjk}")
    return "ok"


def restore_missing_from_photos() -> Dict[str, int]:
    import Photos

    stats = {"ok": 0, "skip": 0, "fail": 0}
    assets = _fetch_screenshots()
    total = int(assets.count())
    _log(
        f"Phase 1 — restore missing .md only, "
        f"{RANGE_START} .. {RANGE_END} ({total} Photos in range)"
    )

    for i in range(total):
        asset = assets.objectAtIndex_(i)
        asset_id = str(asset.localIdentifier())
        shot = _asset_created(asset).date()
        if not in_range(shot):
            stats["skip"] += 1
            continue
        folder = _month_folder(shot)
        if not folder:
            stats["skip"] += 1
            continue
        md_path = folder / _md_filename(asset_id)
        if md_path.is_file():
            stats["skip"] += 1
            continue
        r = _write_md(asset, force=True, require_chinese=True)
        stats[r] = stats.get(r, 0) + 1
    _log(f"Phase 1 done: {stats}")
    return stats


def _needs_chinese_fix(raw: str, body: str) -> bool:
    if "ocr_engine: macos_vision_zh_en" not in raw:
        return True
    cjk = sum(1 for c in body if "\u4e00" <= c <= "\u9fff")
    if cjk >= 8:
        return False
    if is_mojibake_likely(body):
        return True
    # Long text but almost no Chinese — likely bad first-pass OCR
    return len(body) >= 40 and cjk < 3


def fix_mojibake_on_disk() -> Dict[str, int]:
    import Photos

    stats = {"ok": 0, "skip": 0, "fail": 0, "keep": 0, "no_asset": 0}
    _log("Phase 2 — re-OCR notes that need Chinese-capable OCR")

    to_fix: List[tuple[str, Path]] = []
    for month in sorted(MONTH_SET):
        folder = OUT_DIR / month
        if not folder.is_dir():
            continue
        for path in folder.glob("*.md"):
            if path.name.startswith("_"):
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            body = ocr_body(raw)
            if _needs_chinese_fix(raw, body):
                aid = ""
                if raw.startswith("---"):
                    for line in raw.split("---", 2)[1].splitlines():
                        if line.strip().lower().startswith("asset_id:"):
                            aid = line.split(":", 1)[1].strip()
                            break
                to_fix.append((aid, path))

    _log(f"Phase 2 targets: {len(to_fix)} files (all months)")
    for idx, (aid, path) in enumerate(to_fix):
        raw = path.read_text(encoding="utf-8", errors="replace")
        old_cjk = sum(1 for c in ocr_body(raw) if "\u4e00" <= c <= "\u9fff")
        if not aid:
            stats["no_asset"] += 1
            continue
        try:
            asset = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_([aid], None).firstObject()
        except Exception:
            asset = None
        if asset is None:
            stats["no_asset"] += 1
            continue
        r = _write_md(asset, force=True)
        if r == "ok":
            new_body = ocr_body(path.read_text(encoding="utf-8", errors="replace"))
            new_cjk = sum(1 for c in new_body if "\u4e00" <= c <= "\u9fff")
            if new_cjk < 3 and old_cjk >= 3:
                path.write_text(raw, encoding="utf-8")
                stats["skip_ok"] += 1
                _log(f"REVERT {path.relative_to(OUT_DIR)} (new OCR worse, cjk={new_cjk})")
                continue
        stats[r] = stats.get(r, 0) + 1
        if (idx + 1) % 50 == 0:
            _log(f"Phase 2 progress {idx+1}/{len(to_fix)} ok={stats['ok']} keep={stats['keep']}")
    _log(f"Phase 2 done: {stats}")
    return stats


def _needs_mojibake_fix(raw: str, body: str) -> bool:
    """Garbled Latin OCR only — skip good Chinese and plain English notes."""
    cjk = sum(1 for c in body if "\u4e00" <= c <= "\u9fff")
    if cjk >= 8:
        return False
    return is_mojibake_likely(body)


def fix_mojibake_sept_to_may() -> Dict[str, int]:
    """Re-OCR garbled on-disk notes for 2025-09 .. 2026-05 only."""
    import Photos

    stats = {"ok": 0, "skip": 0, "fail": 0, "keep": 0, "no_asset": 0, "skip_ok": 0}
    _log("Phase 2 — mojibake re-OCR for 2025-09 .. 2026-05 (2025-08 untouched)")

    to_fix: List[tuple[str, Path, str]] = []
    for month in sorted(MOJIBAKE_MONTH_SET):
        folder = OUT_DIR / month
        if not folder.is_dir():
            continue
        for path in folder.glob("*.md"):
            if path.name.startswith("_"):
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            body = ocr_body(raw)
            if not _needs_mojibake_fix(raw, body):
                continue
            aid = ""
            if raw.startswith("---"):
                for line in raw.split("---", 2)[1].splitlines():
                    if line.strip().lower().startswith("asset_id:"):
                        aid = line.split(":", 1)[1].strip()
                        break
            to_fix.append((aid, path, raw))

    _log(f"Phase 2 targets: {len(to_fix)} mojibake-likely files")
    for idx, (aid, path, raw) in enumerate(to_fix):
        old_body = ocr_body(raw)
        old_cjk = sum(1 for c in old_body if "\u4e00" <= c <= "\u9fff")
        if not aid:
            stats["no_asset"] += 1
            continue
        try:
            asset = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_([aid], None).firstObject()
        except Exception:
            asset = None
        if asset is None:
            stats["no_asset"] += 1
            continue
        r = _write_md(asset, force=True)
        if r == "ok":
            new_body = ocr_body(path.read_text(encoding="utf-8", errors="replace"))
            new_cjk = sum(1 for c in new_body if "\u4e00" <= c <= "\u9fff")
            if new_cjk < 3 and old_cjk >= 3:
                path.write_text(raw, encoding="utf-8")
                stats["skip_ok"] += 1
                _log(f"REVERT {path.relative_to(OUT_DIR)} (new OCR worse, cjk={new_cjk})")
                continue
        stats[r] = stats.get(r, 0) + 1
        if (idx + 1) % 50 == 0:
            _log(f"Phase 2 progress {idx+1}/{len(to_fix)} ok={stats['ok']} keep={stats['keep']}")
    _log(f"Phase 2 done: {stats}")
    return stats


def rebuild() -> None:
    build_script = Path(__file__).resolve().parent / "build_monthly.py"
    subprocess.run([sys.executable, str(build_script)], check=True)
    _log("Phase 3 — monthly reviews + ocr_index.json rebuilt")


def main() -> int:
    if sys.platform != "darwin":
        print("macOS only", file=sys.stderr)
        return 1

    # Default: missing deleted Chinese only + rebuild (no full re-OCR, no mojibake pass)
    mode = "missing-rebuild"
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            mode = arg.lstrip("-")

    if mode in ("audit", "missing-rebuild"):
        subprocess.run([sys.executable, str(Path(__file__).parent / "audit_garbage_restoration.py")], check=False)

    if mode in ("missing", "missing-rebuild", "all"):
        restore_missing_from_photos()
    if mode == "mojibake":
        fix_mojibake_on_disk()
    if mode == "mojibake-rebuild":
        fix_mojibake_sept_to_may()
        rebuild()
    if mode in ("rebuild", "missing-rebuild", "all"):
        rebuild()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
