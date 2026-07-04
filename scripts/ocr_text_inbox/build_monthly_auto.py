#!/usr/bin/env python3
"""
Rebuild monthly reviews for every YYYY-MM folder under OCR_Text_Inbox.

Use this for 2026-06, 2026-07, … without changing build_monthly.py (fixed legacy months).
"""

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

INBOX = Path.home() / "Desktop" / "OCR_Text_Inbox"
REVIEW_NAME = "_monthly_review.md"
MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
SKIP_MD_PREFIXES = ("_monthly", "_weekly")


def discover_months() -> List[str]:
    if not INBOX.is_dir():
        return []
    return sorted(
        p.name for p in INBOX.iterdir() if p.is_dir() and MONTH_DIR_RE.match(p.name)
    )


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
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def is_source_note(path: Path) -> bool:
    if not path.name.endswith(".md"):
        return False
    return not any(path.name.startswith(p) for p in SKIP_MD_PREFIXES)


def is_garbage(body: str) -> bool:
    b = body.strip()
    return not b or b.lower() in {"no text recognized", "(no text recognized)"}


def build_month(month: str) -> Dict[str, Any]:
    folder = INBOX / month
    valid: List[Tuple[datetime, str, str]] = []
    for path in sorted(folder.glob("*.md"), key=lambda p: p.name):
        if not is_source_note(path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        body = ocr_body(text)
        if is_garbage(body):
            continue
        valid.append((resolve_datetime(path, text), path.name, body))
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


def main(months: List[str] | None = None) -> None:
    targets = months or discover_months()
    months_out = [build_month(m) for m in targets if (INBOX / m).is_dir()]
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
    for m in targets:
        src = INBOX / m / REVIEW_NAME
        if src.is_file():
            (INBOX / f"{m}_monthly_review.md").write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8"
            )


if __name__ == "__main__":
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    main(only if only else None)
