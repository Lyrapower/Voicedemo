"""Per-carrier memory — Chroma optional; JSON store fallback (no large deps)."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.embeddings import get_embedder

logger = logging.getLogger(__name__)

_CARRIERS = ("aster", "shouheng", "che", "cheng", "shuo")
_MAX_RESULTS = 3
_MEMORY_ROOT = Path(__file__).resolve().parent


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class _JsonCarrierStore:
    """Per-carrier chunk files under memory/{carrier}/chunks.jsonl."""

    def __init__(self, memory_base: Path) -> None:
        self.memory_base = memory_base
        for c in _CARRIERS:
            (memory_base / c).mkdir(parents=True, exist_ok=True)

    def _path(self, carrier: str) -> Path:
        return self.memory_base / carrier / "chunks.jsonl"

    def count(self, carrier: str) -> int:
        p = self._path(carrier)
        if not p.exists():
            return 0
        return sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())

    def add(self, carrier: str, chunk_id: str, content: str, embedding: list[float], metadata: Dict) -> None:
        row = {
            "id": chunk_id,
            "content": content,
            "embedding": embedding,
            "metadata": metadata,
        }
        with open(self._path(carrier), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def load(self, carrier: str) -> list[Dict[str, Any]]:
        p = self._path(carrier)
        if not p.exists():
            return []
        out: list[Dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out


class CarrierMemory:
    """
    Per-carrier vector memory. Collections isolated per carrier.
    hop memory < 3: retrieve at most 3 chunks.
    """

    def __init__(self, memory_base: str | Path | None = None, *, use_chroma: bool | None = None) -> None:
        self.memory_base = Path(memory_base) if memory_base else _MEMORY_ROOT
        self.memory_base.mkdir(exist_ok=True)
        for c in _CARRIERS:
            (self.memory_base / c).mkdir(exist_ok=True)

        self.embedder = get_embedder()
        self._json = _JsonCarrierStore(self.memory_base)
        self._chroma_collections: dict[str, Any] = {}
        self._use_chroma = use_chroma

        if self._use_chroma is None:
            import os

            self._use_chroma = os.environ.get("MEMORY_USE_FULL_RAG", "").lower() in ("1", "true", "yes")

        if self._use_chroma:
            self._init_chroma()
        else:
            for c in _CARRIERS:
                logger.info("Carrier %s memory: %s chunks (json)", c, self._json.count(c))

    def _init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            logger.warning("chromadb not installed; using JSON store")
            self._use_chroma = False
            return

        self.client = chromadb.PersistentClient(
            path=str(self.memory_base / "chroma_db"),
            settings=Settings(anonymized_telemetry=False),
        )
        for carrier in _CARRIERS:
            self._chroma_collections[carrier] = self.client.get_or_create_collection(
                name=f"carrier_{carrier}",
                metadata={"carrier": carrier},
            )
            logger.info(
                "Carrier %s memory: %s chunks (chroma)",
                carrier,
                self._chroma_collections[carrier].count(),
            )

    def add_memory(
        self,
        carrier: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> str:
        if carrier not in _CARRIERS:
            raise ValueError(f"Unknown carrier: {carrier}")

        chunk_id = str(uuid.uuid4())
        embedding = self.embedder.embed(content)
        full_metadata = dict(metadata or {})
        full_metadata["carrier"] = carrier

        if self._use_chroma and carrier in self._chroma_collections:
            self._chroma_collections[carrier].add(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[full_metadata],
            )
        else:
            self._json.add(carrier, chunk_id, content, embedding, full_metadata)

        return chunk_id

    def retrieve(self, carrier: str, query: str, n_results: int = 3) -> List[Dict]:
        n_results = min(max(1, n_results), _MAX_RESULTS)

        if carrier not in _CARRIERS:
            return []

        if self._use_chroma and carrier in self._chroma_collections:
            coll = self._chroma_collections[carrier]
            if coll.count() == 0:
                return []
            qe = self.embedder.embed(query)
            results = coll.query(
                query_embeddings=[qe],
                n_results=min(n_results, coll.count()),
            )
            chunks: List[Dict] = []
            for i, doc in enumerate(results["documents"][0]):
                chunks.append(
                    {
                        "content": doc,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else None,
                    }
                )
            return chunks

        rows = self._json.load(carrier)
        if not rows:
            return []
        qe = self.embedder.embed(query)
        scored = [
            (
                1.0 - _cosine(qe, r["embedding"]),
                r,
            )
            for r in rows
        ]
        scored.sort(key=lambda x: x[0])
        out: List[Dict] = []
        for dist, r in scored[:n_results]:
            out.append(
                {
                    "content": r["content"],
                    "metadata": r.get("metadata", {}),
                    "distance": dist,
                }
            )
        return out

    def get_stats(self) -> Dict[str, int]:
        if self._use_chroma and self._chroma_collections:
            return {c: self._chroma_collections[c].count() for c in _CARRIERS}
        return {c: self._json.count(c) for c in _CARRIERS}


_memory_instance: CarrierMemory | None = None


def get_memory() -> CarrierMemory:
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = CarrierMemory()
    return _memory_instance


def format_memory_context(chunks: List[Dict]) -> str:
    if not chunks:
        return ""
    parts = ["\n\n## Relevant prior context:\n\n"]
    for i, chunk in enumerate(chunks, 1):
        parts.append(f"### Context {i}:\n{chunk['content']}\n\n")
    return "".join(parts)
