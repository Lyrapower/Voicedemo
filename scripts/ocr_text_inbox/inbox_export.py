#!/usr/bin/env python3
"""
Mac Photos screenshots → ~/Desktop/OCR_Text_Inbox/*.md + ocr_index.json
Vision OCR only. No image files kept in the output folder.
Run from Terminal.app (not inside a sandboxed IDE) after granting Photos access.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

OUT_DIR = Path.home() / "Desktop" / "OCR_Text_Inbox"
INDEX_PATH = OUT_DIR / "ocr_index.json"
PROGRESS_PATH = OUT_DIR / "export_progress.txt"
TARGET_FOLDER = "~/Desktop/OCR_Text_Inbox"
EXPORT_TIMEOUT_SEC = 120


class SkipImageScreenshot(Exception):
    """Screenshot is mostly image/photo — no OCR scan needed."""


def _ocr_screenshot_image(image_path: Path) -> str:
    from scripts.ocr_text_inbox.image_screenshot_filter import should_skip_image_screenshot

    skip, reason = should_skip_image_screenshot(image_path)
    if skip:
        raise SkipImageScreenshot(reason)
    return _vision_ocr(image_path)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_index() -> Dict[str, Any]:
    if INDEX_PATH.is_file():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {
        "created_at": _iso(datetime.now(timezone.utc)),
        "source": "Mac Photos screenshots",
        "target_folder": TARGET_FOLDER,
        "items": [],
    }


def _save_index(index: Dict[str, Any]) -> None:
    INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _sync_index_from_markdown(index: Dict[str, Any], known: Set[str]) -> int:
    """Add index rows for .md files that exist but are missing from ocr_index.json."""
    added = 0
    items = index.setdefault("items", [])
    indexed_files = {str(i.get("markdown_file")) for i in items if i.get("markdown_file")}
    for md_path in sorted(OUT_DIR.glob("*.md")):
        if md_path.name in indexed_files:
            continue
        text = md_path.read_text(encoding="utf-8")
        asset_id = ""
        created = _iso(datetime.now(timezone.utc))
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                front = parts[1]
                body = parts[2].strip()
                for line in front.splitlines():
                    if line.startswith("asset_id:"):
                        asset_id = line.split(":", 1)[1].strip()
                    elif line.startswith("created:"):
                        created = line.split(":", 1)[1].strip()
        if not asset_id:
            asset_id = md_path.stem
        ocr_body = body
        if ocr_body.startswith("# OCR Note"):
            ocr_body = ocr_body.split("\n", 1)[1].strip() if "\n" in ocr_body else ""
        preview = ocr_body[:120].replace("\n", " ")
        item = {
            "asset_id": asset_id,
            "created": created,
            "markdown_file": md_path.name,
            "text_preview": preview,
            "text_hash": hashlib.sha256(ocr_body.encode("utf-8")).hexdigest(),
        }
        items.append(item)
        known.add(asset_id)
        indexed_files.add(md_path.name)
        added += 1
    if added:
        _save_index(index)
    return added


def _md_filename(asset_id: str) -> str:
    stem = asset_id.split("/")[0]
    stem = re.sub(r"[^\w\-]", "_", stem)
    return f"{stem}.md"


def _ocr_score(text: str) -> int:
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    lat = sum(1 for c in text if c.isalnum())
    return cjk * 3 + lat


def _vision_ocr(image_path: Path) -> str:
    if not image_path.is_file():
        raise RuntimeError(f"image missing: {image_path}")
    if image_path.stat().st_size < 400:
        raise RuntimeError(f"image too small ({image_path.stat().st_size} bytes)")

    candidates: List[tuple[int, str]] = []

    try:
        from ocrmac import ocrmac

        langs = ["zh-Hans", "zh-Hant", "en-US"]
        eng = ocrmac.OCR(str(image_path), language_preference=langs)
        out = eng.recognize()
        chunks: List[str] = []
        for item in out:
            if isinstance(item, (list, tuple)) and item and str(item[0]).strip():
                chunks.append(str(item[0]).strip())
            elif isinstance(item, str) and item.strip():
                chunks.append(item.strip())
        text = "\n".join(chunks).strip()
        if text:
            candidates.append((_ocr_score(text), text))
    except Exception:
        pass

    try:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="chi_sim+chi_tra+eng").strip()
        if text:
            candidates.append((_ocr_score(text), text))
    except Exception:
        pass

    if not candidates:
        raise RuntimeError(
            "OCR returned no text (Vision + Tesseract). "
            "Install: pip install ocrmac pillow pytesseract && brew install tesseract tesseract-lang"
        )

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _render_md(*, created: str, asset_id: str, text: str) -> str:
    return (
        "---\n"
        "type: ocr_note\n"
        f"created: {created}\n"
        "source: screenshot\n"
        "ocr_engine: macos_vision_zh_en\n"
        f"asset_id: {asset_id}\n"
        "tags:\n"
        "  - ocr\n"
        "  - screenshot\n"
        "---\n"
        "\n"
        "# OCR Note\n"
        "\n"
        f"{text}\n"
    )


def _ensure_photos_authorized() -> None:
    import Photos

    status = Photos.PHPhotoLibrary.authorizationStatus()
    if status == Photos.PHAuthorizationStatusAuthorized:
        return
    if status == Photos.PHAuthorizationStatusNotDetermined:
        import threading

        done = threading.Event()
        state: Dict[str, int] = {}

        def _cb(new_status: int) -> None:
            state["status"] = new_status
            done.set()

        Photos.PHPhotoLibrary.requestAuthorization_(_cb)
        done.wait(timeout=120)
        status = state.get("status", Photos.PHPhotoLibrary.authorizationStatus())
    if status != Photos.PHAuthorizationStatusAuthorized:
        raise RuntimeError(
            "Photos access denied. System Settings → Privacy & Security → Photos → "
            "allow Terminal (or Python)."
        )


def _fetch_screenshot_assets():
    import Photos

    subtype = Photos.PHAssetMediaSubtypePhotoScreenshot
    pred = Photos.NSPredicate.predicateWithFormat_("(mediaSubtype & %d) != 0", subtype)
    opts = Photos.PHFetchOptions.alloc().init()
    opts.setPredicate_(pred)
    opts.setIncludeHiddenAssets_(False)
    opts.setIncludeAllBurstAssets_(False)
    return Photos.PHAsset.fetchAssetsWithOptions_(opts)


def _log_progress(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
    print(msg, flush=True)


def _export_asset_to_temp(asset) -> Path:
    import Photos
    from Foundation import NSData

    mgr = Photos.PHImageManager.defaultManager()
    opts = Photos.PHImageRequestOptions.alloc().init()
    opts.setSynchronous_(True)
    opts.setDeliveryMode_(Photos.PHImageRequestOptionsDeliveryModeHighQualityFormat)
    opts.setVersion_(Photos.PHImageRequestOptionsVersionCurrent)
    opts.setNetworkAccessAllowed_(True)

    holder: Dict[str, Any] = {}

    def _handler(data: NSData, _uti: str, _orient: int, info: dict) -> None:
        holder["data"] = data
        holder["info"] = info

    mgr.requestImageDataAndOrientationForAsset_options_resultHandler_(asset, opts, _handler)
    data = holder.get("data")
    if data is None:
        raise RuntimeError("could not read screenshot bytes from Photos (iCloud item?)")

    suffix = ".png"
    uti = str(holder.get("info", {}).get("PHImageFileUTIKey", "") or "")
    if "jpeg" in uti.lower():
        suffix = ".jpg"

    fd, tmp_name = tempfile.mkstemp(suffix=suffix, prefix="ocr_inbox_")
    os.close(fd)
    tmp = Path(tmp_name)
    data.writeToFile_atomically_(str(tmp), True)
    return tmp


def _export_asset_to_temp_timed(asset, timeout_sec: int = EXPORT_TIMEOUT_SEC) -> Path:
    result: Dict[str, Any] = {}
    err: List[BaseException] = []

    def _worker() -> None:
        try:
            result["path"] = _export_asset_to_temp(asset)
        except BaseException as e:  # noqa: BLE001
            err.append(e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        raise TimeoutError(f"Photos export timed out after {timeout_sec}s (iCloud download?)")
    if err:
        raise err[0]
    path = result.get("path")
    if path is None:
        raise RuntimeError("Photos export returned no image data")
    return path


def _process_photo_kit(known: Set[str], index: Dict[str, Any]) -> List[Dict[str, Any]]:
    import Photos
    from Foundation import NSDate

    _ensure_photos_authorized()
    assets = _fetch_screenshot_assets()
    count = int(assets.count())
    already = len(list(OUT_DIR.glob("*.md")))
    _log_progress(f"Found {count} screenshots in Photos. Already in inbox: {already}. Starting export…")

    new_items: List[Dict[str, Any]] = []
    skipped = 0
    done = 0

    for i in range(count):
        asset = assets.objectAtIndex_(i)
        asset_id = str(asset.localIdentifier())
        md_name = _md_filename(asset_id)
        md_path = OUT_DIR / md_name

        if asset_id in known or md_path.is_file():
            continue

        created_dt = asset.creationDate()
        if isinstance(created_dt, NSDate):
            ts = float(created_dt.timeIntervalSince1970())
            created = _iso(datetime.fromtimestamp(ts, tz=timezone.utc))
        elif isinstance(created_dt, datetime):
            created = _iso(created_dt)
        else:
            created = _iso(datetime.now(timezone.utc))

        tmp_path: Path | None = None
        try:
            tmp_path = _export_asset_to_temp_timed(asset)
            text = _ocr_screenshot_image(tmp_path)
        except SkipImageScreenshot as e:
            skipped += 1
            _log_progress(f"SKIP image [{i + 1}/{count}] {asset_id}: {e}")
            continue
        except Exception as e:
            skipped += 1
            _log_progress(f"SKIP [{i + 1}/{count}] {asset_id}: {e}")
            continue
        finally:
            if tmp_path and tmp_path.is_file():
                tmp_path.unlink(missing_ok=True)

        md_path.write_text(
            _render_md(created=created, asset_id=asset_id, text=text),
            encoding="utf-8",
        )
        preview = text[:120].replace("\n", " ")
        item = {
            "asset_id": asset_id,
            "created": created,
            "markdown_file": md_name,
            "text_preview": preview,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        new_items.append(item)
        known.add(asset_id)
        done += 1
        if done % 10 == 0 or done == 1:
            _log_progress(f"OK [{i + 1}/{count}] wrote {md_name} ({done} new, {skipped} skipped)")
        if len(new_items) % 25 == 0:
            index.setdefault("items", []).extend(new_items)
            _save_index(index)
            new_items.clear()

    _log_progress(f"Finished pass: {done} new markdown files, {skipped} skipped.")
    return new_items


def _process_osxphotos(known: Set[str], index: Dict[str, Any]) -> List[Dict[str, Any]]:
    import osxphotos

    db = osxphotos.PhotosDB()
    new_items: List[Dict[str, Any]] = []

    for photo in db.query(osxphotos.QueryOptions(screenshot=True)):
        asset_id = str(photo.uuid)
        md_name = _md_filename(asset_id)
        md_path = OUT_DIR / md_name
        if asset_id in known or md_path.is_file():
            continue

        created_dt = photo.date or datetime.now(timezone.utc)
        created = _iso(created_dt if isinstance(created_dt, datetime) else datetime.now(timezone.utc))

        with tempfile.TemporaryDirectory(prefix="ocr_inbox_") as td:
            exported = photo.export(td)
            if not exported:
                continue
            image_path = Path(exported[0] if isinstance(exported, list) else exported)
            try:
                text = _ocr_screenshot_image(image_path)
            except SkipImageScreenshot:
                continue

        md_path.write_text(
            _render_md(created=created, asset_id=asset_id, text=text),
            encoding="utf-8",
        )
        preview = text[:120].replace("\n", " ")
        new_items.append(
            {
                "asset_id": asset_id,
                "created": created,
                "markdown_file": md_name,
                "text_preview": preview,
                "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        known.add(asset_id)

    return new_items


def _current_screenshot_ids() -> Set[str]:
    _ensure_photos_authorized()
    assets = _fetch_screenshot_assets()
    return {str(assets.objectAtIndex_(i).localIdentifier()) for i in range(int(assets.count()))}


def prune_deleted_from_inbox() -> int:
    """Remove .md and index rows for screenshots no longer in Photos."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    live = _current_screenshot_ids()
    live_stems = {aid.split("/")[0] for aid in live}
    removed = 0
    for md_path in list(OUT_DIR.glob("*.md")):
        stem = md_path.stem
        if stem not in live_stems and not any(aid.startswith(stem) for aid in live):
            md_path.unlink(missing_ok=True)
            removed += 1
    index = _load_index()
    kept = []
    for item in index.get("items", []):
        aid = str(item.get("asset_id", ""))
        if aid in live or aid.split("/")[0] in live_stems:
            kept.append(item)
    index["items"] = kept
    _save_index(index)
    _log_progress(f"Pruned {removed} markdown file(s) no longer in Photos ({len(live)} screenshots remain).")
    return removed


def main() -> int:
    if sys.platform != "darwin":
        print("ERROR: macOS only.", file=sys.stderr)
        return 1

    if len(sys.argv) > 1 and sys.argv[1] == "--prune":
        prune_deleted_from_inbox()
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = _load_index()
    known: Set[str] = {str(i.get("asset_id")) for i in index.get("items", []) if i.get("asset_id")}
    _sync_index_from_markdown(index, known)

    new_items: List[Dict[str, Any]] = []
    blocker: str | None = None

    try:
        new_items = _process_photo_kit(known, index)
    except Exception as e:
        blocker = f"PhotoKit: {e}"

    if not new_items:
        try:
            new_items = _process_osxphotos(known, index)
            blocker = None
        except Exception as e2:
            if blocker:
                blocker = f"{blocker}; osxphotos: {e2}"
            else:
                blocker = f"osxphotos: {e2}"

    if new_items:
        index.setdefault("items", []).extend(new_items)
    _save_index(index)

    md_count = len(list(OUT_DIR.glob("*.md")))
    if md_count == 0 and blocker:
        print(f"ERROR: {blocker}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
