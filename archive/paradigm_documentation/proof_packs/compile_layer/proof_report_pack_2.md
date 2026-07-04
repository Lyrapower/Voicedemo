# Proof Report — Pack 2 · Models Loader (Sovereignty Configuration)

**Date:** 2026-05-24  
**Depends on:** Pack 1 (`compile_layer` Ollama model)  
**Status:** FILES_COMPLETE · UNIT_TESTS_PASS · LIVE_OLLAMA_PENDING

---

## Files created / updated

| Path | Role |
|------|------|
| `models/llama_loader.py` | `SubstrateLoader`, `SubstrateConfig`, `get_loader()` + preserved `GridOllamaClient` |
| `models/__init__.py` | Public exports |
| `models/substrate_config.yaml` | `compile_layer` / `echo_layer` + LYRA fallback chain aliases |
| `models/test_loader.py` | Unittest (mocked) + `--manual` integration |
| `models/substrate_loader.py` | Re-export shim → `llama_loader` (fallback chain compat) |
| `app/fallback_chain.py` | Imports `get_loader` from `models.llama_loader` |
| `repo/app/router.py` | Optional `POST /stream` with `mode: "substrate"` → `SubstrateLoader` |

---

## substrate_config.yaml

Loads without error. Distinct parameters:

| Substrate | ollama_tag | carrier_capable | echo_mode | temperature | num_ctx |
|-----------|------------|-----------------|-----------|-------------|---------|
| compile_layer | compile_layer | true | false | 0.5 | 32768 |
| echo_layer | echo_layer | false | true | 0.7 | 16384 |

Fallback entries (`compile_layer_backup`, `qwen_dense_14b_emergency`, etc.) map to same tags for LYRA chain in `app/config/lyra_anchor.json`.

---

## Test loader execution

### Unit tests (mocked — no Ollama required)

```
python3 models/test_loader.py
```

```
Ran 5 tests in 0.015s — OK
```

- YAML load
- compile vs echo parameter distinction
- `verify_substrate_available` for `compile_layer`
- `generate("compile_layer", ...)` returns response payload
- carrier rejected on non-carrier-capable `echo_layer`

### Manual integration (`--manual`)

```
python3 models/test_loader.py --manual
```

On host **without Ollama**: all substrates show `Available: False`; message to run Pack 1 first.

On host **with Pack 1 built**: expect `compile_layer` available and sample generation output.

---

## Substrate availability verification

| Substrate | Expected when Pack 1 done | Method |
|-----------|---------------------------|--------|
| compile_layer | `verify_substrate_available` → true | `GET /api/tags` contains `compile_layer` |
| echo_layer | false until `echo_layer` model deployed | separate Modelfile / tag |

---

## Sample generation (mocked acceptance)

```json
{
  "substrate": "compile_layer",
  "response": "Substrate function. Carrier-capable compile layer.",
  "eval_count": 42,
  "ollama_tag": "compile_layer",
  "carrier_capable": true,
  "echo_mode": false
}
```

Live sample: run manual test after `./deployment/build_compile_model.sh`.

---

## Constraints verified

| Constraint | Status |
|------------|--------|
| All generation via `SubstrateLoader` | ✅ |
| Parameters from YAML only | ✅ |
| No auth (Pack 6) | ✅ |
| Foundational anchor not overridden unless `system_override` | ✅ |

---

## Acceptance checklist

| Criterion | Status |
|-----------|--------|
| models/ directory with 4 files | ✅ |
| YAML loads | ✅ |
| SubstrateLoader instantiates | ✅ |
| verify true for compile_layer (when Ollama + Pack 1) | ⏳ local |
| Test generation returns substrate response | ✅ mocked |
| compile vs echo config distinct | ✅ |

---

## Ready for Pack 3

Pack 2 loader is in place. Next pack can wire semantic mapper / router orchestration on top of `get_loader()` and `substrate_config.yaml`.

**Local verify:**

```bash
./deployment/build_compile_model.sh
python3 models/test_loader.py --manual
```
