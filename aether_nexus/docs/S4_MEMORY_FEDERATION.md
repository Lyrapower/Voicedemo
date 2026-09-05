# S4 — Memory federation (12-week plan)

**Phase:** V-adjacent — **scheduled**, not implemented.

## Problem

Six storage layers (diary hash chain, diary replies, memory_context 7d, Obsidian vault, grid_store events, TRANSITION_LOG) accumulate history without cross-index.

## Design (read-only federation)

- Local embedding index (Qwen embeddings) spans all six layers.
- Lanes query «this symbol / concept appeared where» at prompt-build time.
- **No storage merge** — sovereign boundaries unchanged; shared library catalog only.

## Next artifact

Full index-layer spec when Phase V slot opens (~week 8–10 of 12-week plan).

**Owner confirmation:** 2026-07-14 — accepted into roadmap; implementation deferred.
