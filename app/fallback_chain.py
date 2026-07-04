from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FallbackChain:
    """
    Substrate fallback chain within layer.
    If primary substrate fails: try secondary, tertiary.
    All local — no cloud fallback per sovereignty requirements.
    """

    def __init__(self, lyra_anchor: Any, loader: Any):
        self.lyra = lyra_anchor
        self.loader = loader
        self.max_attempts_per_chain = 3

    def generate_with_fallback(
        self,
        *,
        layer: str,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        carrier: str | None = None,
    ) -> dict[str, Any]:
        chain = self.lyra.get_substrate_fallback(layer)
        attempts: list[dict[str, Any]] = []

        for i, substrate_name in enumerate(chain[: self.max_attempts_per_chain]):
            try:
                attempt_result = self.loader.generate(
                    substrate_name=substrate_name,
                    prompt=prompt,
                    temperature_override=temperature,
                    max_tokens_override=max_tokens,
                    carrier=carrier,
                )
                if "error" not in attempt_result:
                    attempt_result["fallback_used"] = i > 0
                    attempt_result["fallback_chain_position"] = i
                    attempt_result["fallback_attempts"] = attempts
                    return attempt_result
                attempts.append(
                    {
                        "substrate": substrate_name,
                        "error": attempt_result["error"],
                        "position": i,
                    }
                )
                logger.warning(
                    "Substrate %s failed: %s", substrate_name, attempt_result["error"]
                )
            except Exception as e:
                attempts.append(
                    {"substrate": substrate_name, "error": str(e), "position": i}
                )
                logger.error("Substrate %s exception: %s", substrate_name, e)

        return {
            "error": "All substrates in fallback chain failed",
            "attempts": attempts,
            "chain": chain,
        }


_chain_instance: FallbackChain | None = None


def get_fallback_chain() -> FallbackChain:
    global _chain_instance
    if _chain_instance is None:
        from app.lyra_verification import get_lyra
        from models.llama_loader import get_loader

        _chain_instance = FallbackChain(get_lyra(), get_loader())
    return _chain_instance
