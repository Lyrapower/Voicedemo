# Proof Report — Pack 6 · Memory Context Layer (RAG)

**Date:** 2026-05-24  
**Depends on:** Packs 1–5  
**Status:** COMPLETE (lightweight mode — heavy deps **skipped** per user request)

---

## Space-saving decision

**Not installed** (saves several GB disk):

- `chromadb`
- `sentence-transformers`
- `BAAI/bge-large-zh-v1.5` model weights

**Default runtime:**

| Component | Implementation |
|-----------|----------------|
| Embeddings | `LightweightEmbedder` — local SHA256 token vectors, dim 384 |
| Storage | Per-carrier `memory/{carrier}/chunks.jsonl` |
| Retrieval | Cosine similarity, **max 3 chunks** (`hop memory < 3`) |

**Optional full RAG** (when disk allows):

```bash
pip install chromadb sentence-transformers
export MEMORY_USE_FULL_RAG=1
```

---

## Files created

| Path | Role |
|------|------|
| `memory/__init__.py` | Exports |
| `memory/embeddings.py` | Lightweight + optional BGE |
| `memory/retriever.py` | `CarrierMemory`, `format_memory_context` |
| `memory/ingest.py` | CLI paragraph ingest |
| `memory/{aster,shouheng,che,cheng,shuo}/` | Per-carrier dirs |
| `memory/test_memory.py` | Unit tests |
| `carriers/route_core.py` | `build_carrier_final_prompt` + memory in `/route` |
| `app/main.py` | `app.state.memory` |
| `repo/app/main.py` | `app.state.memory` (8787) |
| `app/routes.py`, `repo/app/grid_route.py` | Pass `memory_service` |

---

## Memory test output

```bash
python3 memory/test_memory.py
# Ran 4 tests — OK
```

| Test | Result |
|------|--------|
| add + retrieve (cheng) | ✅ |
| max 3 results | ✅ |
| carrier isolation | ✅ |
| format_memory_context | ✅ |

---

## Sample ingest

```bash
python3 memory/ingest.py cheng carriers/anchors/cheng.md
# Writes chunks to memory/cheng/chunks.jsonl
```

---

## Routing integration

When carrier invoked, prompt shape:

```
{anchor letter}
{## Relevant prior context: ... up to 3 chunks}
---
User request:
{user text}
```

Metadata on `/route` response:

- `memory_chunks_used`
- `memory_chunk_previews` (audit-friendly)

8787 TestClient: `@澄` with seeded cheng memory → `memory_chunks_used >= 1`.

8792: `app/test_router.py` — 6 tests OK with temp memory dir.

---

## Constraints verified

| Constraint | Status |
|------------|--------|
| `n_results` ≤ 3 | ✅ enforced in `retrieve` |
| Per-carrier isolation | ✅ separate collections / jsonl |
| No cloud embeddings | ✅ local only |
| No auto-ingest conversations | ✅ ingest CLI only |

---

## Ready for Pack 7

Pack 6 complete in lightweight mode. Enable `MEMORY_USE_FULL_RAG=1` later if you want Chroma + BGE without code changes.

**8500** unchanged. **8787** particle API still only on 8787.
