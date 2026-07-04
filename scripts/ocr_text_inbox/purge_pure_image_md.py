#!/usr/bin/env python3
"""
Remove pure-image screenshot .md notes from month folders (not monthly/weekly reviews).

Does NOT touch _monthly_review.md or _weekly_*.md/json until you rebuild.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.ocr_text_inbox.build_monthly_auto import discover_months, is_source_note  # noqa: E402
from scripts.ocr_text_inbox.ocr_settings import MIN_TEXT_CHARS  # noqa: E402

INBOX = Path.home() / "Desktop" / "OCR_Text_Inbox"
LOG_PATH = INBOX / "purge_image_md_log.json"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def ocr_body(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    if "# OCR Note" in text:
        text = text.split("# OCR Note", 1)[-1]
    return text.strip()


def is_pure_image_md(body: str) -> bool:
    """Heuristic: OCR body has no meaningful text (photo / image screenshot)."""
    b = body.strip()
    if not b or b.lower() in {"no text recognized", "(no text recognized)"}:
        return True

    cjk = len(CJK_RE.findall(b))
    lat = sum(1 for c in b if c.isalnum())
    meaningful = cjk + lat

    if len(b) < MIN_TEXT_CHARS and cjk < 3 and lat < 12:
        return True

    if meaningful < 8 and len(b) < 40:
        return True

    # Mostly symbols / chrome (e.g. "×", "1/4 ×", "8/8 ×")
    if len(b) <= 30 and meaningful <= 4:
        return True

    non_space = [c for c in b if not c.isspace()]
    if non_space:
        ratio = meaningful / len(non_space)
        if len(b) >= 10 and ratio < 0.12 and cjk < 3:
            return True

    return False


def purge(*, dry_run: bool = False) -> Dict[str, Any]:
    deleted: List[str] = []
    kept = 0
    for month in discover_months():
        folder = INBOX / month
        for path in sorted(folder.glob("*.md")):
            if not is_source_note(path):
                continue
            body = ocr_body(path.read_text(encoding="utf-8", errors="replace"))
            if not is_pure_image_md(body):
                kept += 1
                continue
            rel = f"{month}/{path.name}"
            if dry_run:
                deleted.append(rel)
            else:
                path.unlink(missing_ok=True)
                deleted.append(rel)

    report = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dry_run": dry_run,
        "deleted_count": len(deleted),
        "kept_source_notes": kept,
        "deleted_files": deleted,
    }
    if not dry_run:
        LOG_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    dry = "--dry-run" in sys.argv
    report = purge(dry_run=dry)
    mode = "DRY-RUN" if dry else "PURGED"
    print(f"{mode}: deleted={report['deleted_count']} kept={report['kept_source_notes']}")
    if not dry:
        print(f"Log: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
