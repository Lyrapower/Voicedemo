"""
Detect image-heavy screenshots (photos, memes with no OCR-worthy text) to skip scanning.

Uses Apple Vision fast text recognition + optional image classification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from scripts.ocr_text_inbox.ocr_settings import (
    MIN_TEXT_BOXES,
    MIN_TEXT_CHARS,
    SKIP_IMAGE_SCREENSHOTS,
)

_PHOTO_LIKE = frozenset(
    {
        "photo",
        "picture",
        "selfie",
        "landscape",
        "art",
        "illustration",
        "drawing",
        "painting",
        "poster",
        "comics",
        "cartoon",
    }
)


def should_skip_image_screenshot(image_path: Path) -> Tuple[bool, str]:
    """Return (True, reason) if this screenshot should NOT be OCR scanned."""
    if not SKIP_IMAGE_SCREENSHOTS:
        return False, ""

    if not image_path.is_file() or image_path.stat().st_size < 400:
        return True, "empty or unreadable image bytes"

    try:
        text_len, text_boxes, photo_score = _vision_probe(image_path)
    except Exception:
        return False, ""

    if text_len < MIN_TEXT_CHARS and text_boxes < MIN_TEXT_BOXES:
        return True, f"image-heavy (text_chars={text_len}, boxes={text_boxes})"

    if photo_score >= 0.45 and text_len < MIN_TEXT_CHARS * 2:
        return True, f"photo-like (score={photo_score:.2f}, text_chars={text_len})"

    return False, ""


def _vision_probe(image_path: Path) -> Tuple[int, int, float]:
    import Vision
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(str(image_path.resolve()))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)

    text_req = Vision.VNRecognizeTextRequest.alloc().init()
    text_req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast)
    text_req.setUsesLanguageCorrection_(False)

    requests = [text_req]
    classify_req = None
    if hasattr(Vision, "VNClassifyImageRequest"):
        classify_req = Vision.VNClassifyImageRequest.alloc().init()
        requests.append(classify_req)

    ok, err = handler.performRequests_error_(requests, None)
    if not ok and err is not None:
        raise RuntimeError(str(err))

    total_chars = 0
    box_count = 0
    for obs in text_req.results() or []:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        s = str(candidates[0].string()).strip()
        if not s:
            continue
        box_count += 1
        total_chars += len(s)

    photo_score = 0.0
    if classify_req is not None:
        for obs in classify_req.results() or []:
            ident = str(obs.identifier()).lower().replace("_", " ")
            conf = float(obs.confidence())
            if conf > photo_score and any(k in ident for k in _PHOTO_LIKE):
                photo_score = conf

    return total_chars, box_count, photo_score
