"""Canonical pool symbol list — shared by scan universe and offpool exclusion."""
from __future__ import annotations

import os
from pathlib import Path

_BASE = Path(__file__).resolve().parent
DEFAULT_POOL = (
    "MU,MRVL,AMD,HOOD,DELL,APA,OXY,IONQ,NVDA,TSLA,COIN,IREN,CRDO,QCOM,"
    "GLW,BABA,SMCI,ANET"
)


def _pool_symbols_raw() -> str:
    """Prefer aether_nexus/.env over stale process env (load_dotenv does not override)."""
    env_path = _BASE / ".env"
    if env_path.is_file():
        try:
            text = env_path.read_text(encoding="utf-8")
        except OSError:
            return os.getenv("POOL_SYMBOLS", DEFAULT_POOL)
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("POOL_SYMBOLS="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("POOL_SYMBOLS", DEFAULT_POOL)


def pool_symbols() -> list[str]:
    raw = _pool_symbols_raw()
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def pool_symbols_set() -> set[str]:
    return set(pool_symbols())
