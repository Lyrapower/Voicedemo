"""Screenshot filtering: PNG default; JPG only with flag."""

from __future__ import annotations

import re
from pathlib import Path


def is_screenshotish_name(name: str) -> bool:
    n = name.lower()
    if "screenshot" in n or "screen shot" in n or "screen_shot" in n:
        return True
    if n.startswith("img_") or n.startswith("img-"):
        return True
    if re.search(r"20\d{2}-\d{2}-\d{2}", n):
        return True
    return False


def should_process(path: Path, *, include_jpg: bool, include_all_png: bool) -> tuple[bool, str]:
    if not path.is_file():
        return False, "not_file"
    suf = path.suffix.lower()
    if suf == ".png":
        if include_all_png or is_screenshotish_name(path.name):
            return True, "png"
        return False, "png_not_screenshotish_name"
    if include_jpg and suf in (".jpg", ".jpeg"):
        if include_all_png or is_screenshotish_name(path.name):
            return True, "jpeg"
        return False, "jpeg_not_screenshotish_name"
    return False, f"extension_skipped:{suf}"
