"""Load plugins from plugins/*/manifest.yaml per config/aster.toml."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

import yaml

from .aster_config import repo_root, section


def _required_manifest_fields() -> list[str]:
    fields = section("plugins").get("manifest_required_fields", {}).get("fields", [])
    return list(fields) if fields else ["name", "allow_gpu", "outbound_net"]


def discover_plugins() -> dict[str, dict[str, Any]]:
    root = repo_root()
    plugins_root = root / "plugins"
    manifest_name = str(section("plugins").get("manifest_filename", "manifest.yaml"))
    required = _required_manifest_fields()
    loaded: dict[str, dict[str, Any]] = {}

    if not plugins_root.is_dir():
        return loaded

    for plugin_dir in sorted(plugins_root.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest_path = plugin_dir / manifest_name
        handler_path = plugin_dir / "handler.py"
        if not manifest_path.is_file() or not handler_path.is_file():
            continue

        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        missing = [f for f in required if f not in manifest]
        if missing:
            continue

        name = str(manifest["name"])
        spec = importlib.util.spec_from_file_location(f"plugin_{name}", handler_path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        handle_fn = getattr(mod, "handle", None)
        if not callable(handle_fn):
            continue

        loaded[name] = {
            "manifest": manifest,
            "handle": handle_fn,
            "path": str(plugin_dir),
        }
    return loaded


_plugins: dict[str, dict[str, Any]] | None = None


def get_plugins() -> dict[str, dict[str, Any]]:
    global _plugins
    if _plugins is None:
        _plugins = discover_plugins()
    return _plugins
