#!/usr/bin/env python
"""Launch Telegram bot (polling mode)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_framework.bot.handlers import build_application


def main() -> None:
    app = build_application()
    app.run_polling()


if __name__ == "__main__":
    main()
