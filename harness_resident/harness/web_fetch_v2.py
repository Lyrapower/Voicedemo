"""Broker-facing import name. Implementation lives in web_fetch_v3.py."""
from __future__ import annotations
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "web_fetch_v3", Path(__file__).with_name("web_fetch_v3.py")
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
globals().update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith("__")})
