# Pack 1 — Compile Layer Foundational Anchor (8787 / Ollama)

## Files

| Path | Role |
|------|------|
| `anchors/core_system_anchor.md` | Standalone anchor (version control) |
| `Modelfile.compile_layer` | Ollama SYSTEM block (foundational, not runtime injection) |
| `build_compile_model.sh` | `ollama create compile_layer` |
| `verify_anchor.py` | 4 baseline refusal tests |

## Deploy

```bash
chmod +x deployment/build_compile_model.sh
./deployment/build_compile_model.sh
python3 deployment/verify_anchor.py
```

8787 Grid `/stream` uses `OLLAMA_MODEL=compile_layer` by default (`repo/config/settings.py`).

## Constraints (Pack 1)

- SYSTEM block is not modified at prompt time.
- No patch-time anchor injection — anchor lives in Modelfile only.
- Verification must pass before Pack 2.
