#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Photos / export → Obsidian: one .md + one .txt per processed image.

Modes:
  EXPORT_MODE  — scan a folder (EXPORT_ROOT or PHOTOS_ASSET_ROOT).
  PHOTOS_MODE  — discover via Spotlight (screenshots) + optional Photos AppleScript export.

Environment:
  EXPORT_MODE=1           Use export folder (required with export root).
  EXPORT_ROOT=...         Default: ~/Desktop/PhotosExport
  PHOTOS_ASSET_ROOT=...   Same as EXPORT_ROOT if EXPORT_MODE (either may be set).

  PHOTOS_MODE=1           Use Spotlight + Photos helpers (no fake .photoslibrary rglob).

  DRY_RUN=1               Print discovery only; no OCR writes (still writes _logs).

  CLEAN=1                 Before run: rm -rf vault markdown + text dirs.

  ALLOW_SINGLE_TEST=1     accept.sh only; pipeline records count in manifest.

Usage:
  EXPORT_MODE=1 EXPORT_ROOT=~/Desktop/PhotosExport CLEAN=1 python3 pipeline.py
  PHOTOS_MODE=1 CLEAN=1 python3 pipeline.py
  DRY_RUN=1 PHOTOS_MODE=1 python3 pipeline.py
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import ExifTags, Image
except Exception:
    Image = None
    ExifTags = None

try:
    from ocrmac import ocrmac
except Exception:
    ocrmac = None

VAULT = Path.home() / "Obsidian" / "PhotoTextVault"
MD_DIR = VAULT / "markdown"
TXT_DIR = VAULT / "text"
LOG_DIR = VAULT / "_logs"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".webp"}

START_DATE = date(2025, 8, 1)
END_DATE = date(2026, 4, 23)


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _expand(p: str) -> Path:
    return Path(p).expanduser().resolve()


def normalized_suffix(p: Path) -> str:
    m = re.search(r"(\.[^.]+)$", p.name, re.I)
    if not m:
        return ""
    ext = m.group(1).lower()
    if ext == ".jpeg":
        ext = ".jpg"
    return ext


def is_image(p: Path) -> bool:
    return p.is_file() and normalized_suffix(p) in IMAGE_EXTS


def verify_readable(p: Path) -> Tuple[bool, str]:
    try:
        if not p.exists():
            return False, "not_exists"
        if not p.is_file():
            return False, "not_file"
        if p.stat().st_size <= 0:
            return False, "zero_byte"
        with open(p, "rb") as f:
            f.read(64)
        return True, ""
    except OSError as e:
        return False, f"os_error:{e}"
    except Exception as e:
        return False, f"read_error:{e}"


def image_meta_dates(p: Path) -> Tuple[Optional[datetime], Optional[date]]:
    """Return (best datetime for display, date for filtering)."""
    dt: Optional[datetime] = None
    d: Optional[date] = None
    if Image is None:
        try:
            ts = p.stat().st_mtime
            dt = datetime.fromtimestamp(ts)
            d = dt.date()
        except OSError:
            pass
        return dt, d
    try:
        img = Image.open(p)
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
                            dt = datetime.fromisoformat(raw)
                            d = dt.date()
                            return dt, d
                        except ValueError:
                            pass
    except Exception:
        pass
    try:
        ts = p.stat().st_mtime
        dt = datetime.fromtimestamp(ts)
        d = dt.date()
    except OSError:
        pass
    return dt, d


def in_range(d: Optional[date]) -> bool:
    if d is None:
        return False
    return START_DATE <= d <= END_DATE


def run_ocr(p: Path) -> Tuple[str, str]:
    if ocrmac is None:
        return "", "no_engine"
    try:
        eng = ocrmac.OCR(str(p))
        out = eng.recognize()
        chunks: List[str] = []
        for item in out:
            if isinstance(item, (list, tuple)) and item and str(item[0]).strip():
                chunks.append(str(item[0]).strip())
            elif isinstance(item, str) and item.strip():
                chunks.append(item.strip())
        text = "\n".join(chunks).strip()
        if not text:
            return "", "empty"
        return text, "ok"
    except Exception as e:
        return f"OCR_ERROR: {p} {type(e).__name__}: {e}", "error"


def slug(s: str, max_len: int = 80) -> str:
    s = re.sub(r"[^\w\-]+", "_", s.strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:max_len] if s else "img").strip("_") or "img"


def mdfind_screenshots() -> Tuple[List[Path], str]:
    """Spotlight: screen captures on disk (indexed). Date range applied after query in Python."""
    q = "kMDItemIsScreenCapture == 1"
    try:
        r = subprocess.run(
            ["mdfind", q],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            return [], f"mdfind_exit_{r.returncode}:{r.stderr.strip()}"
        paths: List[Path] = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            p = Path(line)
            if not p.exists() or not is_image(p):
                continue
            _, d = image_meta_dates(p)
            if in_range(d):
                paths.append(p.resolve())
        return paths, ""
    except subprocess.TimeoutExpired:
        return [], "mdfind_timeout"
    except Exception as e:
        return [], f"mdfind_exception:{e}"


def osascript_photos_export_screenshots_album(max_items: int = 300) -> Tuple[List[Path], str]:
    """
    Export from a Screenshots-like album into a temp dir. Requires Photos + accessibility.
    Returns list of exported file paths.
    """
    scratch = Path(tempfile.mkdtemp(prefix="phototextvault_photos_"))
    out_dir = scratch / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    posix_out = str(out_dir.resolve())

    script = f'''
    tell application "Photos"
        set albumNames to {{"Screenshots", "Screen Shot", "屏幕快照", "截屏"}}
        set targetItems to {{}}
        repeat with albName in albumNames
            try
                set alb to first album whose name is (albName as string)
                set targetItems to (get every media item of alb)
                exit repeat
            end try
        end repeat
        if (count of targetItems) is 0 then error "No Screenshots album found or empty"
        set destFolder to POSIX file "{posix_out}"
        set n to count of targetItems
        if n > {max_items} then set n to {max_items}
        repeat with i from 1 to n
            try
                set mi to item i of targetItems
                export {{mi}} to destFolder using originals
            end try
        end repeat
        return (n as string)
    end tell
    '''
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if r.returncode != 0:
            shutil.rmtree(scratch, ignore_errors=True)
            return [], f"osascript_exit_{r.returncode}:{err or out}"
        paths: List[Path] = []
        for p in out_dir.rglob("*"):
            if is_image(p):
                paths.append(p.resolve())
        if not paths:
            shutil.rmtree(scratch, ignore_errors=True)
            return [], f"osascript_no_images_exported:{err or out}"
        return paths, ""
    except subprocess.TimeoutExpired:
        shutil.rmtree(scratch, ignore_errors=True)
        return [], "osascript_timeout"
    except Exception as e:
        shutil.rmtree(scratch, ignore_errors=True)
        return [], f"osascript_exception:{e}"


def discover_export_paths(root: Path) -> Tuple[List[Path], List[Dict[str, str]], Dict[str, Any]]:
    skipped: List[Dict[str, str]] = []
    candidates: List[Path] = []
    total_files = 0
    image_ext_files = 0
    readable_images = 0
    for p in root.rglob("*"):
        try:
            if not p.is_file():
                continue
            total_files += 1
            if not is_image(p):
                continue
            image_ext_files += 1
            ok, reason = verify_readable(p)
            if not ok:
                skipped.append({"path": str(p.resolve()), "reason": reason})
                continue
            readable_images += 1
            _, d = image_meta_dates(p)
            if not in_range(d):
                skipped.append({"path": str(p.resolve()), "reason": f"outside_date_range:{d}"})
                continue
            candidates.append(p.resolve())
        except OSError as e:
            skipped.append({"path": str(p), "reason": str(e)})
    stats = {
        "total_files_seen": total_files,
        "candidate_images": image_ext_files,
        "readable_images": readable_images,
        "readable_in_range": len(candidates),
        "skipped_count": len(skipped),
    }
    return candidates, skipped, stats


def discover_photos_mode() -> Tuple[List[Path], List[Dict[str, str]], Dict[str, Any], str]:
    """Returns (paths, skipped, stats, unknown_message). unknown_message empty if OK."""
    skipped: List[Dict[str, str]] = []
    paths, mdf_err = mdfind_screenshots()
    note = ""
    if not paths:
        note = f"Spotlight screen captures: none or query failed ({mdfind_err}). "
        paths2, o_err = osascript_photos_export_screenshots_album()
        if paths2:
            paths = paths2
            note += f"Photos AppleScript export succeeded ({len(paths)} files). "
        else:
            note += f"Photos export: {o_err}. "
            u = (
                "UNKNOWN: No indexed screen captures and Photos album export did not produce files.\n"
                "ACTION:\n"
                "  1) Photos → File → Export → Export Unmodified Originals to a folder, then\n"
                "     EXPORT_MODE=1 EXPORT_ROOT=<that folder> python3 pipeline.py\n"
                "  2) Or ensure Spotlight indexes your screen shots (System Settings → Siri & Spotlight).\n"
                "  3) Or create/use a 'Screenshots' album in Photos and grant Automation for osascript.\n"
            )
            return [], skipped, {
                "total_files_seen": 0,
                "candidate_images": 0,
                "readable_images": 0,
                "readable_in_range": 0,
                "skipped_count": 0,
                "mdfind_error": mdf_err,
                "osascript_error": o_err,
            }, u

    candidates: List[Path] = []
    for p in paths:
        if not is_image(p):
            skipped.append({"path": str(p), "reason": "not_image_ext"})
            continue
        ok, reason = verify_readable(p)
        if not ok:
            skipped.append({"path": str(p), "reason": reason})
            continue
        _, d = image_meta_dates(p)
        if not in_range(d):
            skipped.append({"path": str(p), "reason": f"outside_date_range:{d}"})
            continue
        candidates.append(p.resolve())

    stats = {
        "total_files_seen": len(paths),
        "candidate_images": len(paths),
        "readable_images": len(candidates),
        "readable_in_range": len(candidates),
        "skipped_count": len(skipped),
        "note": note,
    }
    return candidates, skipped, stats, ""


def print_diagnostics(
    mode: str,
    export_root: Optional[Path],
    stats: Dict[str, Any],
    candidates: List[Path],
    skipped: List[Dict[str, str]],
    unknown: str,
) -> None:
    print(f"current_user: {getpass.getuser()}", flush=True)
    print(f"cwd: {os.getcwd()}", flush=True)
    print(f"mode: {mode}", flush=True)
    print(f"EXPORT_ROOT: {export_root}", flush=True)
    print(f"PHOTOS_ASSET_ROOT env: {os.environ.get('PHOTOS_ASSET_ROOT', '')!r}", flush=True)
    print(f"resolved_scan_roots: {[str(export_root)] if export_root else ['PHOTOS_MODE:mdfind+Photos']}", flush=True)
    print(f"total_assets_discovered: {stats.get('total_files_seen', 0)}", flush=True)
    print(f"candidate_images: {stats.get('candidate_images', 0)}", flush=True)
    print(f"readable_images: {stats.get('readable_images', stats.get('readable_in_range', 0))}", flush=True)
    print(f"readable_exported_images: {stats.get('readable_in_range', 0)}", flush=True)
    print("first_20_candidate_paths:", flush=True)
    for p in candidates[:20]:
        print(f"  {p}", flush=True)
    print("first_20_skipped:", flush=True)
    for row in skipped[:20]:
        print(f"  {row.get('path')} | {row.get('reason')}", flush=True)
    if unknown:
        print(unknown, flush=True)


def clean_vault_outputs() -> None:
    for d in (MD_DIR, TXT_DIR):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def process_one_image(p: Path, dry_run: bool) -> Optional[Dict[str, Any]]:
    created_dt, d = image_meta_dates(p)
    created_s = created_dt.isoformat() if created_dt else ""
    proc_at = datetime.now().astimezone().isoformat()
    uid = uuid.uuid4().hex[:10]
    base = slug(p.stem) + "_" + uid

    if dry_run:
        return {
            "path": str(p),
            "slug": base,
            "created": created_s,
            "dry_run": True,
        }

    text, kind = run_ocr(p)
    if kind == "empty":
        text = f"OCR_EMPTY: {p}"
    elif kind == "no_engine":
        text = f"OCR_ERROR: {p} ocrmac not installed"
        kind = "error"

    txt_path = TXT_DIR / f"{base}.txt"
    txt_path.write_text(text, encoding="utf-8")

    md_body = (
        f"---\n"
        f"source_image: {p}\n"
        f"created_timestamp: {created_s}\n"
        f"processing_timestamp: {proc_at}\n"
        f"ocr_kind: {kind}\n"
        f"text_file: {txt_path}\n"
        f"---\n\n"
        f"# {p.name}\n\n"
        f"## Source\n\n`{p}`\n\n"
        f"## OCR\n\n{text}\n"
    )
    md_path = MD_DIR / f"{base}.md"
    md_path.write_text(md_body, encoding="utf-8")

    return {
        "path": str(p),
        "markdown": str(md_path),
        "text": str(txt_path),
        "ocr_kind": kind,
    }


def main() -> int:
    dry = _env_bool("DRY_RUN")
    clean = _env_bool("CLEAN")
    export_mode = _env_bool("EXPORT_MODE")
    photos_mode = _env_bool("PHOTOS_MODE")

    if export_mode and photos_mode:
        print("ERROR: set only one of EXPORT_MODE or PHOTOS_MODE", flush=True)
        return 2
    if not export_mode and not photos_mode:
        print("ERROR: set EXPORT_MODE=1 or PHOTOS_MODE=1", flush=True)
        return 2

    export_root: Optional[Path] = None
    unknown = ""
    if export_mode:
        root_s = (
            os.environ.get("EXPORT_ROOT", "").strip()
            or os.environ.get("PHOTOS_ASSET_ROOT", "").strip()
            or str(Path.home() / "Desktop" / "PhotosExport")
        )
        export_root = _expand(root_s)
        if not export_root.is_dir():
            print(f"ERROR: export root is not a directory: {export_root}", flush=True)
            return 1
        candidates, skipped, stats = discover_export_paths(export_root)
    else:
        candidates, skipped, stats, unknown = discover_photos_mode()

    print_diagnostics(
        "export" if export_mode else "photos",
        export_root,
        stats,
        candidates,
        skipped,
        unknown,
    )

    if dry:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        rep = {
            "stats": stats,
            "candidates": [str(x) for x in candidates],
            "skipped_sample": skipped[:200],
            "unknown": unknown,
        }
        (LOG_DIR / "dry_run_report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
        if unknown:
            (LOG_DIR / "unknown.txt").write_text(unknown, encoding="utf-8")
        print("DRY_RUN: no OCR files written.", flush=True)
        return 0

    if unknown and not candidates:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / "unknown.txt").write_text(unknown, encoding="utf-8")
        (LOG_DIR / "manifest.json").write_text(
            json.dumps({"stats": stats, "unknown": unknown, "processed_count": 0}, indent=2),
            encoding="utf-8",
        )
        return 3

    if clean:
        clean_vault_outputs()
    else:
        MD_DIR.mkdir(parents=True, exist_ok=True)
        TXT_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    processed: List[Dict[str, Any]] = []
    for p in candidates:
        row = process_one_image(p, dry_run=False)
        if row:
            processed.append(row)

    manifest = {
        "processed_count": len(processed),
        "candidates_discovered": len(candidates),
        "skipped_count": len(skipped),
        "mode": "export" if export_mode else "photos",
        "export_root": str(export_root) if export_root else None,
        "processed": processed,
    }
    (LOG_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    md_n = sum(1 for f in MD_DIR.glob("*.md") if f.is_file() and f.stat().st_size > 0)
    tx_n = sum(1 for f in TXT_DIR.glob("*.txt") if f.is_file() and f.stat().st_size > 0)
    if md_n != len(processed) or tx_n != len(processed):
        print(f"ERROR: count mismatch processed={len(processed)} md={md_n} txt={tx_n}", flush=True)
        return 1
    if len(processed) == 0:
        print("ERROR: zero processed images", flush=True)
        return 1

    print(f"OK: processed={len(processed)} markdown_files={md_n} text_files={tx_n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
