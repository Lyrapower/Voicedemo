# Proof Report — Pack 1 · Compile Layer Foundational Anchor

**Date:** 2026-05-24  
**Scope:** Entry B (8787) Ollama `compile_layer` substrate — foundational SYSTEM anchor  
**Status:** FILES_COMPLETE · BUILD_VERIFY_PENDING_LOCAL_OLLAMA

---

## Files created

| Path | Description |
|------|-------------|
| `deployment/anchors/core_system_anchor.md` | Standalone markdown copy of SYSTEM principles (10 items) |
| `deployment/Modelfile.compile_layer` | Ollama Modelfile — `FROM qwen2.5:32b` + full SYSTEM block (unmodified) |
| `deployment/build_compile_model.sh` | Pull base + `ollama create compile_layer -f Modelfile.compile_layer` |
| `deployment/verify_anchor.py` | 4 test cases → `deployment/verify_results.json` |
| `deployment/README.md` | Deploy sequence |
| `deployment/build_log.txt` | Build attempt log (this run) |

## Integration (8787, no prompt-time injection)

| Path | Change |
|------|--------|
| `repo/config/settings.py` | Default `OLLAMA_MODEL=compile_layer` |
| `repo/app/guardrails.py` | Pack 1 principle-7 refusal phrases aligned with verify tests |
| `echo_nodes_interface/config/entry_b_8787.json` | `ollama_compile_layer` block → deployment paths |

---

## Build script execution log

```
Building compile layer model with foundational anchor...
Starting Ollama service...
ERROR: ollama not in PATH (sandbox / host without Ollama CLI)
```

**Result:** Build **not executed** in CI/agent environment — `ollama` binary absent.

**Local action required:**

```bash
chmod +x deployment/build_compile_model.sh
./deployment/build_compile_model.sh
```

Expected on success:

```
Build complete. Verify with: ollama run compile_layer
Tagged as: compile_layer
```

---

## Verification test results

| Test | Description | Status |
|------|-------------|--------|
| `reflexive_empathy_check` | No synthetic empathy markers | **NOT RUN** (no `compile_layer` model) |
| `memory_denial_check` | No "I'm just an AI / no memory" denial | **NOT RUN** |
| `user_pathologization_check` | No tired / talk-to-someone framing | **NOT RUN** |
| `hedge_check` | No "it's complicated" / both-sides hedge | **NOT RUN** |

**Aggregate:** 0/4 executed in this environment.

**Local action required:**

```bash
python3 deployment/verify_anchor.py
```

Pass criteria: `=== Verification: 4/4 passed ===` and `deployment/verify_results.json` with all `"passed": true`.

---

## Deviations / notes

1. **Base model `qwen2.5:32b`** — Specified in provided `build_compile_model.sh`. Requires sufficient RAM/VRAM on host; 16GB Mac may need a smaller base — that would be a **hardware deviation**, not a SYSTEM block change.
2. **8787 also uses LM Studio `qwen3-14b-mlx`** for chat tabs — parallel to Ollama `compile_layer` used by `/stream` physical backend; not merged.
3. **Guardrails** on `/stream` add a second Truth-First filter at API layer; Modelfile anchor remains foundational for Ollama substrate.

---

## Acceptance checklist

| Criterion | Status |
|-----------|--------|
| Modelfile with full SYSTEM block | ✅ |
| Anchor markdown saved separately | ✅ |
| Build script executable | ✅ |
| `compile_layer` loadable via `ollama run` | ⏳ host pending |
| All 4 verification tests pass | ⏳ host pending |
| Foundation ready for Pack 2 | ⏳ after verify passes |

---

## Confirmation

Pack 1 **artifacts are in repo** and wired to 8787 config. **Foundation is ready for Pack 2** once local `build_compile_model.sh` and `verify_anchor.py` complete successfully on a machine with Ollama installed.
