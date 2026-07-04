"""Backward-compatible re-export — Pack 2 canonical loader is models.llama_loader."""

from __future__ import annotations

from models.llama_loader import (
    CARRIER_PREFIX,
    SubstrateConfig,
    SubstrateLoader,
    get_loader,
)

__all__ = ["SubstrateLoader", "SubstrateConfig", "get_loader", "CARRIER_PREFIX"]
