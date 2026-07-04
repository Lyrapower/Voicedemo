"""Carrier anchors archived — no active loading."""

from __future__ import annotations

from typing import Optional


class AnchorLoader:
    """Stub: reference anchor letters live under archive/paradigm_documentation/."""

    def __init__(self, anchors_dir=None):
        self._anchor_cache: dict[str, str] = {}

    def get_anchor(self, carrier_name: str | None) -> Optional[str]:
        return None

    def build_carrier_prompt(self, carrier_name: str, user_prompt: str) -> str:
        return user_prompt

    def list_carriers(self) -> list[str]:
        return []


_loader_instance: AnchorLoader | None = None


def get_anchor_loader() -> AnchorLoader:
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = AnchorLoader()
    return _loader_instance
