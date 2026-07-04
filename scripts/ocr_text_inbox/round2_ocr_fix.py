#!/usr/bin/env python3
"""
Round 2: Re-OCR remaining garbled / legacy-engine notes (2025-08 .. 2026-05).

Targets any source .md that is NOT already good Chinese OCR:
  - ocr_engine != macos_vision_zh_en (e.g. macos_vision_local)
  - OR visible Latin garble with CJK < 8
  - OR classic mojibake pattern

Skips notes with >= 8 CJK chars and macos_vision_zh_en.
On failure keeps existing file; reverts if new OCR is worse than old.

Run from Terminal.app:
  cd ~/Desktop/demo && .venv_ocr_inbox/bin/python scripts/ocr_text_inbox/round2_ocr_fix.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from scripts.ocr_text_inbox import inbox_export as ie  # noqa: E402
from scripts.ocr_text_inbox.audit_garbage_restoration import (  # noqa: E402
    INBOX,
    is_mojibake_likely,
    ocr_body,
)
from scripts.ocr_text_inbox.date_scope import MONTHS  # noqa: E402

OUT_DIR = ie.OUT_DIR
LOG = OUT_DIR / "round2_ocr_fix_progress.txt"
_export_asset_to_temp_timed = ie._export_asset_to_temp_timed
_ensure_photos_authorized = ie._ensure_photos_authorized
_iso = ie._iso
_md_filename = ie._md_filename
_render_md = ie._render_md
_vision_ocr = ie._vision_ocr
_ocr_screenshot_image = ie._ocr_screenshot_image
SkipImageScreenshot = ie.SkipImageScreenshot

GARBLE_RE = re.compile(r"[\u00C0-\u024F\u1E00-\u1EFF]|ìŁ|Ñº|ÈE|Ł|Ã")
MIN_GOOD_CJK = 8


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    print(msg, flush=True)


def _parse_meta(raw: str) -> Dict[str, str]:
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    meta: Dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta


def _cjk_count(text: str) -> int:
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


def needs_round2(raw: str, body: str) -> bool:
    cjk = _cjk_count(body)
    engine = _parse_meta(raw).get("ocr_engine", "")
    if cjk >= MIN_GOOD_CJK and engine == "macos_vision_zh_en":
        return False
    if engine and engine != "macos_vision_zh_en":
        return True
    if is_mojibake_likely(body):
        return True
    if cjk < MIN_GOOD_CJK and len(GARBLE_RE.findall(body)) >= 3:
        return True
    return False


def _write_md(asset, md_path: Path, raw_backup: str) -> str:
    asset_id = str(asset.localIdentifier())
    dt = asset.creationDate()
    if hasattr(dt, "timeIntervalSince1970"):
        created_dt = datetime.fromtimestamp(float(dt.timeIntervalSince1970()), tz=timezone.utc)
    else:
        created_dt = datetime.now(timezone.utc)

    old_cjk = _cjk_count(ocr_body(raw_backup))
    tmp: Optional[Path] = None
    try:
        tmp = _export_asset_to_temp_timed(asset)
        text = _ocr_screenshot_image(tmp)
    except SkipImageScreenshot as e:
        _log(f"SKIP image {md_path.relative_to(OUT_DIR)} ({e})")
        return "skip_image"
    except Exception as e:
        _log(f"KEEP {md_path.relative_to(OUT_DIR)} ({e})")
        return "keep"
    finally:
        if tmp and tmp.is_file():
            tmp.unlink(missing_ok=True)

    new_cjk = _cjk_count(text)
    if new_cjk < old_cjk and old_cjk >= MIN_GOOD_CJK:
        _log(f"REVERT {md_path.name} (new cjk={new_cjk} < old={old_cjk})")
        return "revert"

    md_path.write_text(
        _render_md(created=_iso(created_dt), asset_id=asset_id, text=text),
        encoding="utf-8",
    )
    _log(f"OK {md_path.relative_to(OUT_DIR)} cjk={new_cjk}")
    return "ok"


def collect_targets() -> List[Tuple[str, Path, str]]:
    rows: List[Tuple[str, Path, str]] = []
    for month in MONTHS:
        folder = OUT_DIR / month
        if not folder.is_dir():
            continue
        for path in folder.glob("*.md"):
            if path.name.startswith("_"):
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            body = ocr_body(raw)
            if not needs_round2(raw, body):
                continue
            aid = _parse_meta(raw).get("asset_id", "")
            rows.append((aid, path, raw))
    return rows


def run_fix() -> Dict[str, int]:
    if sys.platform != "darwin":
        raise RuntimeError("macOS + Photos required")

    _ensure_photos_authorized()
    import Photos

    stats = {"ok": 0, "keep": 0, "revert": 0, "no_asset": 0, "skip_image": 0}
    targets = collect_targets()
    _log(f"Round 2 start: {len(targets)} files (2025-08 .. 2026-05)")

    for idx, (aid, path, raw) in enumerate(targets):
        if not aid:
            stats["no_asset"] += 1
            continue
        try:
            asset = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_([aid], None).firstObject()
        except Exception:
            asset = None
        if asset is None:
            stats["no_asset"] += 1
            if stats["no_asset"] <= 20:
                _log(f"NO_ASSET {path.name}")
            continue
        r = _write_md(asset, path, raw)
        stats[r] = stats.get(r, 0) + 1
        if (idx + 1) % 100 == 0:
            _log(f"Progress {idx+1}/{len(targets)} ok={stats['ok']} keep={stats['keep']}")

    _log(f"Round 2 done: {stats}")
    return stats


def rebuild() -> None:
    script = Path(__file__).resolve().parent / "build_monthly_auto.py"
    subprocess.run([sys.executable, str(script)], check=True)
    _log("Monthly reviews + ocr_index.json rebuilt")


def main() -> int:
    if "--count-only" in sys.argv:
        n = len(collect_targets())
        print(f"round2_targets={n}")
        return 0
    if "--rebuild-only" in sys.argv:
        rebuild()
        return 0
    run_fix()
    purge_script = Path(__file__).resolve().parent / "purge_pure_image_md.py"
    subprocess.run([sys.executable, str(purge_script)], check=False)
    _log("Purged pure-image .md notes (see purge_image_md_log.json)")
    rebuild()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
