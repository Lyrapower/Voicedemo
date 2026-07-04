#!/usr/bin/env python3
"""
Audit OCR_Text_Inbox for files wrongly treated as garbage (Chinese → 乱码).

Writes ~/Desktop/OCR_Text_Inbox/garbage_restore_audit.json with:
- per-month counts: on_disk, missing_vs_photos, mojibake_likely, has_cjk
- lists of missing asset ids (deleted .md) when Photos is available
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path as _Path

_REPO = _Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

INBOX = Path.home() / "Desktop" / "OCR_Text_Inbox"
AUDIT_PATH = INBOX / "garbage_restore_audit.json"
from scripts.ocr_text_inbox.date_scope import (  # noqa: E402
    MONTHS,
    MONTH_SET,
    range_end_exclusive_utc,
    range_start_utc,
)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
MOJI_RE = re.compile(r"[\u00C0-\u024F\u1E00-\u1EFF]")


def ocr_body(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    if "# OCR Note" in text:
        text = text.split("# OCR Note", 1)[-1]
    return text.strip()


def is_mojibake_likely(body: str) -> bool:
    """Garbled Chinese OCR: lots of Latin-1/extended, almost no CJK."""
    b = body.strip()
    if len(b) < 20:
        return False
    cjk = len(CJK_RE.findall(b))
    if cjk >= 8:
        return False
    moji = len(MOJI_RE.findall(b))
    lat = sum(1 for c in b if c.isalnum())
    return moji >= 5 and lat >= 20


def scan_disk() -> Dict[str, Any]:
    per_month: Dict[str, Any] = {}
    mojibake_samples: List[str] = []
    for month in MONTHS:
        folder = INBOX / month
        if not folder.is_dir():
            continue
        on_disk = 0
        has_cjk = 0
        mojibake = 0
        empty = 0
        for path in folder.glob("*.md"):
            if path.name.startswith("_"):
                continue
            on_disk += 1
            body = ocr_body(path.read_text(encoding="utf-8", errors="replace"))
            if not body or body.lower() in {"no text recognized", "(no text recognized)"}:
                empty += 1
                continue
            if len(CJK_RE.findall(body)) >= 3:
                has_cjk += 1
            if is_mojibake_likely(body):
                mojibake += 1
                if len(mojibake_samples) < 30:
                    mojibake_samples.append(f"{month}/{path.name}")
        per_month[month] = {
            "on_disk_md": on_disk,
            "with_cjk_ge3": has_cjk,
            "mojibake_likely": mojibake,
            "empty_ocr": empty,
        }
    return {"per_month": per_month, "mojibake_sample_files": mojibake_samples}


def scan_photos_missing() -> Optional[Dict[str, Any]]:
    if sys.platform != "darwin":
        return None
    try:
        import Photos
        from Foundation import NSDate, NSPredicate
    except ImportError:
        return {"error": "Photos framework unavailable"}

    from scripts.ocr_text_inbox.inbox_export import _md_filename  # noqa: E402

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
    assets = Photos.PHAsset.fetchAssetsWithOptions_(opts)
    total = int(assets.count())

    missing_by_month: Dict[str, List[str]] = {m: [] for m in MONTHS}
    present = 0
    for i in range(total):
        asset = assets.objectAtIndex_(i)
        asset_id = str(asset.localIdentifier())
        dt = asset.creationDate()
        if hasattr(dt, "timeIntervalSince1970"):
            shot = datetime.fromtimestamp(float(dt.timeIntervalSince1970()), tz=timezone.utc).date()
        else:
            continue
        month = f"{shot.year}-{shot.month:02d}"
        if month not in MONTH_SET:
            continue
        md_path = INBOX / month / _md_filename(asset_id)
        if md_path.is_file():
            present += 1
        else:
            missing_by_month[month].append(asset_id)

    missing_total = sum(len(v) for v in missing_by_month.values())
    return {
        "photos_screenshots_in_range": total,
        "md_present": present,
        "md_missing_deleted_or_never_written": missing_total,
        "missing_by_month_counts": {m: len(missing_by_month[m]) for m in MONTHS},
        "missing_asset_ids_sample": {
            m: missing_by_month[m][:5] for m in MONTHS if missing_by_month[m]
        },
    }


def main() -> int:
    INBOX.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "note": (
            "Deleted garbage .md files cannot be read from disk; restore by re-OCR "
            "from Mac Photos (same asset_id → {uuid}.md)."
        ),
        "disk_scan": scan_disk(),
    }
    photos = scan_photos_missing()
    if photos:
        report["photos_missing_scan"] = photos

    AUDIT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {AUDIT_PATH}")
    if photos and "md_missing_deleted_or_never_written" in photos:
        print(f"Missing .md vs Photos: {photos['md_missing_deleted_or_never_written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
