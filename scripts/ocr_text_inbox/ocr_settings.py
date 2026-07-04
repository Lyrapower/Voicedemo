"""OCR pipeline toggles (override via environment variables)."""

from __future__ import annotations

import os

# Skip screenshots that are mostly photos/images with little readable text.
# Set OCR_SKIP_IMAGE_SCREENSHOTS=0 to disable.
SKIP_IMAGE_SCREENSHOTS = os.environ.get("OCR_SKIP_IMAGE_SCREENSHOTS", "1") != "0"

# Minimum total characters from Vision fast text pass to treat as text screenshot.
MIN_TEXT_CHARS = int(os.environ.get("OCR_MIN_TEXT_CHARS", "18"))

# Minimum number of text regions (lines/blocks) to treat as text screenshot.
MIN_TEXT_BOXES = int(os.environ.get("OCR_MIN_TEXT_BOXES", "2"))
