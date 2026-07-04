"""Local embeddings — full BGE optional (skipped by default to save disk)."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from typing import List, Protocol

logger = logging.getLogger(__name__)

_DIM = 384
_USE_FULL = os.environ.get("MEMORY_USE_FULL_RAG", "").lower() in ("1", "true", "yes")
_MODEL = os.environ.get("MEMORY_EMBED_MODEL", "BAAI/bge-large-zh-v1.5")


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class LightweightEmbedder:
    """Deterministic local vectors — no downloads, sovereignty-friendly."""

    def __init__(self, dim: int = _DIM) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        return self._vector(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        if not tokens:
            tokens = ["_"]
        vec = [0.0] * self.dim
        for tok in tokens:
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            for i in range(self.dim):
                vec[i] += ((h[i % len(h)] / 255.0) - 0.5) / len(tokens)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = _MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", model_name)
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


_embedding_service: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedding_service
    if _embedding_service is not None:
        return _embedding_service
    if _USE_FULL:
        try:
            _embedding_service = SentenceTransformerEmbedder()
            logger.info("Embedding dimension: %s", _embedding_service.dim)
            return _embedding_service
        except ImportError:
            logger.warning("sentence-transformers not installed; using lightweight embedder")
    _embedding_service = LightweightEmbedder()
    logger.info("Using lightweight embedder (dim=%s). Set MEMORY_USE_FULL_RAG=1 for BGE.", _DIM)
    return _embedding_service
