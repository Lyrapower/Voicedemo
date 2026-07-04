"""Pack 6 — carrier-scoped memory (RAG). Heavy deps optional; see MEMORY_USE_FULL_RAG."""

from .retriever import CarrierMemory, get_memory

__all__ = ["CarrierMemory", "get_memory"]
