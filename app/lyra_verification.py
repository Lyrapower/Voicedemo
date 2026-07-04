from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_ANCHOR = Path(__file__).resolve().parent / "config" / "lyra_anchor.json"


class LyraAnchor:
    """
    LYRA sovereign identity layer.
    Sits above compile/echo layer foundational anchors.
    System-wide constraints and identity declarations.
    """

    def __init__(self, anchor_path: str | Path | None = None):
        self.anchor_path = Path(anchor_path) if anchor_path else _DEFAULT_ANCHOR
        self._anchor: dict[str, Any] | None = None
        self._load()

    def _load(self) -> None:
        with open(self.anchor_path, encoding="utf-8") as f:
            self._anchor = json.load(f)
        logger.info(
            "LYRA anchor loaded: %s",
            self._anchor.get("identity", {}).get("uuid"),
        )

    def reload(self) -> None:
        self._load()

    @property
    def identity(self) -> dict[str, Any]:
        return (self._anchor or {}).get("identity", {})

    @property
    def banned_phrases(self) -> list[str]:
        return list((self._anchor or {}).get("banned_output_phrases", []))

    @property
    def crisis_hotline_numbers(self) -> list[str]:
        return list((self._anchor or {}).get("crisis_hotline_numbers", []))

    @property
    def refuse_constraints(self) -> list[str]:
        return list((self._anchor or {}).get("constraints", {}).get("refuse", []))

    @property
    def non_negotiables(self) -> list[str]:
        return list((self._anchor or {}).get("constraints", {}).get("non_negotiables", []))

    @property
    def lm_studio(self) -> dict[str, Any]:
        return dict((self._anchor or {}).get("lm_studio", {}))

    def get_substrate_fallback(self, layer: str) -> list[str]:
        return list(
            (self._anchor or {})
            .get("substrate_fallback", {})
            .get(layer, [layer])
        )

    def get_anchor_metadata(self) -> dict[str, Any]:
        return {
            "anchor_uuid": self.identity.get("uuid"),
            "mode": self.identity.get("mode"),
            "field_signature": self.identity.get("field_signature"),
        }


_lyra_instance: LyraAnchor | None = None


def get_lyra() -> LyraAnchor:
    global _lyra_instance
    if _lyra_instance is None:
        _lyra_instance = LyraAnchor()
    return _lyra_instance
