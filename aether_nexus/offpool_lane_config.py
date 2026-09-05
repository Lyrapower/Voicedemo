"""Off-pool lane registry — CC CLI (Sonnet 4.6) + Ollama cloud (DeepSeek V4)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ALLOWED_BACKENDS = frozenset({"cc_cli", "ollama_cloud"})
DEFAULT_CC_MODEL = "claude-sonnet-4-6"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash:cloud"


@dataclass(frozen=True)
class OffpoolLane:
    lane: str
    backend: str
    model: str
    label: str

    @property
    def cli_model(self) -> str:
        """Legacy field for CC CLI lanes."""
        return self.model if self.backend == "cc_cli" else ""


def _parse_lane_chunk(chunk: str) -> OffpoolLane | None:
    chunk = chunk.strip()
    if not chunk:
        return None
    if "|" in chunk:
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) != 4:
            logger.warning("skip bad OFFPOOL_LANES pipe entry: %s", chunk)
            return None
        lane, backend, model, label = parts
    else:
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) != 3:
            logger.warning("skip bad OFFPOOL_LANES colon entry: %s", chunk)
            return None
        lane, model, label = parts
        backend = "cc_cli"
    if backend not in ALLOWED_BACKENDS:
        logger.warning("skip unknown backend %r in %s", backend, chunk)
        return None
    return OffpoolLane(lane=lane, backend=backend, model=model, label=label)


def default_offpool_lanes() -> list[OffpoolLane]:
    raw = os.getenv("OFFPOOL_LANES", "").strip()
    if raw:
        lanes = [ln for ln in (_parse_lane_chunk(c) for c in raw.split(",")) if ln]
        if lanes:
            return lanes
    deepseek_model = os.getenv("OFFPOOL_DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL).strip()
    return [
        OffpoolLane("sonnet-4.6", "cc_cli", DEFAULT_CC_MODEL, "SONNET 4.6"),
        OffpoolLane("deepseek-v4", "ollama_cloud", deepseek_model, "DEEPSEEK V4"),
    ]
