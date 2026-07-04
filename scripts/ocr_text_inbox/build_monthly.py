#!/usr/bin/env python3
"""Rebuild _monthly_review.md and ocr_index.json from current source .md files."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.ocr_text_inbox.date_scope import MONTHS, in_range_dt  # noqa: E402

INBOX = Path.home() / "Desktop" / "OCR_Text_Inbox"
REVIEW_NAME = "_monthly_review.md"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z0-9]")


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: Dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, parts[2]


def ocr_body(text: str) -> str:
    _, body = parse_frontmatter(text)
    if "# OCR Note" in body:
        body = body.split("# OCR Note", 1)[-1].strip()
    return body.strip()


def parse_date_string(s: str):
    s = s.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", s)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    return None


def resolve_datetime(path: Path, text: str) -> datetime:
    meta, _ = parse_frontmatter(text)
    for key in ("created", "date"):
        if key in meta:
            dt = parse_date_string(meta[key])
            if dt:
                return dt
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", path.name)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def is_garbage(body: str) -> bool:
    """Only skip empty OCR from monthly stitch — never delete files on disk.

    Earlier rules (cjk<8 and latin<20) wrongly removed Chinese screenshots whose
    Vision OCR came out as Latin extended mojibake (乱码).
    """
    b = body.strip()
    if not b or b.lower() in {"no text recognized", "(no text recognized)"}:
        return True
    return False


def build_month(month: str) -> Dict[str, Any]:
    folder = INBOX / month
    valid: List[Tuple[datetime, str, str]] = []
    for path in sorted(folder.glob("*.md"), key=lambda p: p.name):
        if path.name == REVIEW_NAME or path.name.endswith("_monthly_review.md"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        body = ocr_body(text)
        if is_garbage(body):
            continue
        dt = resolve_datetime(path, text)
        if not in_range_dt(dt):
            continue
        valid.append((dt, path.name, body))
    valid.sort(key=lambda x: (x[0], x[1]))
    lines = [f"# OCR Monthly Review — {month}", "", "## Index", ""]
    for _, name, _ in valid:
        lines.append(f"- [[{name}]]")
    lines.extend(["", "---", ""])
    files_meta: List[Dict[str, Any]] = []
    for dt, name, body in valid:
        lines.extend(
            [
                f"## {dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                "",
                f"Source file: {name}",
                "",
                body,
                "",
                "---",
                "",
            ]
        )
        files_meta.append(
            {
                "file": f"{month}/{name}",
                "created": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "text_preview": body[:120].replace("\n", " "),
                "text_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            }
        )
    (folder / REVIEW_NAME).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "month": month,
        "monthly_review": f"{month}/{REVIEW_NAME}",
        "file_count": len(files_meta),
        "files": files_meta,
    }


def main() -> None:
    months_out = [build_month(m) for m in MONTHS if (INBOX / m).is_dir()]
    (INBOX / "ocr_index.json").write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "source_folder": "~/Desktop/OCR_Text_Inbox",
                "ocr_engine": "macos_vision_zh_en",
                "months": months_out,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # root convenience copies
    for m in MONTHS:
        src = INBOX / m / REVIEW_NAME
        if src.is_file():
            (INBOX / f"{m}_monthly_review.md").write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8"
            )


if __name__ == "__main__":
    main()
