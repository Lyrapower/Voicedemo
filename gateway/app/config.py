"""Configuration from environment. No secrets in repo; use .env (gitignored)."""
import os
from pathlib import Path

# Bind: must be 127.0.0.1 (no 0.0.0.0)
HOST = os.environ.get("GATEWAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("GATEWAY_PORT", "8000"))

# Kill-switch: GATEWAY_KILL=1 => all endpoints return 503
GATEWAY_KILL = os.environ.get("GATEWAY_KILL", "0").strip() in ("1", "true", "yes")

# DB path (relative to project root or absolute)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.environ.get("GATEWAY_DB_PATH", str(DATA_DIR / "gateway.db")))

# Provider defaults (env)
DEFAULT_CHAT_PROVIDER = os.environ.get("DEFAULT_CHAT_PROVIDER", "claude").lower()
DEFAULT_VISION_PROVIDER = os.environ.get("DEFAULT_VISION_PROVIDER", "gemini").lower()
DEFAULT_TTS_PROVIDER = os.environ.get("DEFAULT_TTS_PROVIDER", "mock").lower()

# Timeouts (seconds)
PROVIDER_TIMEOUT = int(os.environ.get("PROVIDER_TIMEOUT", "20"))

# Allowed provider names
ALLOWED_PROVIDERS = {"claude", "openai", "gemini", "mock"}
