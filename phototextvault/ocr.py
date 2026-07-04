"""Local OCR: ocrmac (Vision) on macOS, else pytesseract."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

try:
    from ocrmac import ocrmac as _ocrmac_mod
except ImportError:
    _ocrmac_mod = None


def _ocr_score(text: str) -> int:
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    lat = sum(1 for c in text if c.isalnum())
    return cjk * 3 + lat


def _text_from_ocrmac(path: Path) -> str:
    if _ocrmac_mod is None:
        raise RuntimeError("ocrmac not importable")
    langs = ["zh-Hans", "zh-Hant", "en-US"]
    eng = _ocrmac_mod.OCR(str(path), language_preference=langs)
    out = eng.recognize()
    chunks: list[str] = []
    for item in out:
        if isinstance(item, (list, tuple)) and item and str(item[0]).strip():
            chunks.append(str(item[0]).strip())
        elif isinstance(item, str) and item.strip():
            chunks.append(item.strip())
    return "\n".join(chunks).strip()


def _text_from_tesseract_zh(path: Path) -> str:
    import pytesseract
    from PIL import Image

    img = Image.open(path)
    return pytesseract.image_to_string(img, lang="chi_sim+chi_tra+eng").strip()


def _text_from_pytesseract(path: Path) -> str:
    import pytesseract
    from PIL import Image

    img = Image.open(path)
    return pytesseract.image_to_string(img).strip()


def ocr_image(path: Path) -> Tuple[str, str]:
    """
    Returns (text, engine_name).
    Raises RuntimeError if no engine available or all engines fail.
    """
    last_err: Exception | None = None
    ocrmac_empty = False

    candidates: list[tuple[int, str, str]] = []

    if _ocrmac_mod is not None:
        try:
            text = _text_from_ocrmac(path)
            if text:
                candidates.append((_ocr_score(text), text, "ocrmac_vision_zh"))
            else:
                ocrmac_empty = True
        except Exception as e:
            last_err = e

    try:
        text = _text_from_tesseract_zh(path)
        if text:
            candidates.append((_ocr_score(text), text, "pytesseract_zh_en"))
    except Exception:
        pass

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], candidates[0][2]

    try:
        text = _text_from_pytesseract(path)
        return text, "pytesseract"
    except ImportError as e:
        msg = (
            "No OCR engine available. On macOS: pip install ocrmac pillow. "
            "Or: pip install pytesseract pillow and install Tesseract (brew install tesseract)."
        )
        if last_err is not None:
            msg += f" ocrmac failed: {last_err}"
        elif ocrmac_empty:
            msg += " ocrmac returned no text."
        raise RuntimeError(msg) from e
    except Exception as e:
        if last_err is not None:
            raise RuntimeError(
                f"OCR failed. ocrmac error: {last_err}; pytesseract error: {e}"
            ) from e
        if ocrmac_empty:
            raise RuntimeError(f"OCR failed: ocrmac returned no text; pytesseract: {e}") from e
        raise RuntimeError(f"pytesseract OCR failed: {e}") from e
