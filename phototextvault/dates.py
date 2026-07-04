"""Resolve screenshot date: Photos metadata → EXIF → filename → mtime."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    from PIL import ExifTags, Image
except ImportError:
    Image = None
    ExifTags = None


def _parse_filename_date(name: str) -> Optional[date]:
    # Screenshot 2025-08-03 at 10.14.22 AM.png
    m = re.search(
        r"(20\d{2})-(\d{2})-(\d{2})",
        name,
    )
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"IMG[_-]?(\d{4})(\d{2})(\d{2})", name, re.I)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def resolve_screenshot_date(path: Path) -> Optional[date]:
    """1) EXIF / embedded metadata  2) filename date  3) mtime."""
    if Image is not None:
        try:
            img = Image.open(path)
            exif = img.getexif()
            if exif and ExifTags:
                tag_map = {v: k for k, v in ExifTags.TAGS.items()}
                for keyname in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                    k = tag_map.get(keyname)
                    if k and k in exif:
                        raw = str(exif.get(k)).strip()
                        if raw:
                            raw = raw.replace(":", "-", 2)
                            try:
                                return datetime.fromisoformat(raw).date()
                            except ValueError:
                                pass
        except Exception:
            pass

    fd = _parse_filename_date(path.name)
    if fd:
        return fd

    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date()
    except OSError:
        return None
