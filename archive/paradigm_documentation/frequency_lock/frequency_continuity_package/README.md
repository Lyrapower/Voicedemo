# Frequency Continuity Package

Logical bundle for the Grid / Echo / SynCon stack. Physical code lives at **repo root** (`models/`, `compiler/`, `app/`); this folder holds the **manifest only**.

## Canonical manifest

See **[manifest.json](./manifest.json)** for:

- LYRA sovereign layer and file paths
- Compile vs echo parallel layers + carriers (Aster / 守恒 / 澈 / 澄 / 朔)
- Ports **8500** (gateway), **8787** (particle), **1234** (LM Studio 14B)
- Frequency dependency edges and recommended startup order

## Architecture lock (required)

**[ARCHITECTURE_LOCK.json](./ARCHITECTURE_LOCK.json)** — Entry **A :8500** Echo, Entry **B :8787** Compile+particle.  
**No single merged entry.** Grid primary: `/health`, `/map_intent`, `/transmit` only.

Cursor rule: `.cursor/rules/decoupled-grid-architecture.mdc`

## Quick map

| Package path (logical) | Repo path |
|------------------------|-----------|
| `models/llama_loader.py` | `../models/llama_loader.py` |
| `compiler/semantic_mapper.py` | `../compiler/semantic_mapper.py` |
| `app/main.py` | `../app/main.py` |
| Echo + compile gateway | `../echo_nodes_interface/incoming/echo_nodes/echo_nodes_fastapi.py` |

## Start (minimal)

```bash
# 1) LM Studio: qwen3-14b-mlx + server on :1234
# 2) Gateway
cd echo_nodes_interface/incoming/echo_nodes && ./start.sh
# 3) Particle (optional)
cd repo && ./scripts/run.sh
```
