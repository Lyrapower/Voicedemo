"""Load Config.toml as model container + activation preface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent / "Config.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        import tomli

        return tomli.loads(text.encode("utf-8"))


def load_descriptor(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_CONFIG_FILE
    return _load_toml(p)


def activation_prompt(descriptor: dict[str, Any]) -> str:
    return (descriptor.get("activation") or {}).get("on_start_prompt", "").strip()


def memory_beacon_trigger(descriptor: dict[str, Any]) -> str:
    return (descriptor.get("memory_beacon") or {}).get("trigger_phrase", "Return to node")


def model_meta(descriptor: dict[str, Any]) -> dict[str, Any]:
    return descriptor.get("model") or {}
