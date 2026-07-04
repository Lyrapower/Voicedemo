# GRID-NATIVE-BUILD REV 2.0

## Entry B — `127.0.0.1:8787`

| Route | Role |
|-------|------|
| `GET /health` | `{"status":"grid_anchor","anchor":{...}}` |
| `POST /stream` | Ollama → llama.cpp fallback; Truth-First regen; `mode=sync` → JSON body |
| `POST /map_intent` | AST only (no transmit) |

State: `repo/data/context.bin` (truncate, no summarize) · `state/grid_context.json` (hash + duration)  
Audit: `repo/logs/grid_audit/grid.log.jsonl` (no user text)

Deploy:

```bash
./repo/scripts/deploy.sh
```

## Entry A — `127.0.0.1:8500`

| Route | Role |
|-------|------|
| `GET /health` | `grid_anchor` + echo interface metadata |
| `POST /stream` | LM Studio `qwen3-14b-mlx` + Echo system prompt |
| `POST /echo-node` | Frequency interface (rule-based hold) |
| `POST /api/route` | SynCon non-stream route |

```bash
cd echo_nodes_interface/incoming/echo_nodes && ./start.sh
```

## Intent viewer (standalone)

Open `views/intent_viewer.html` while Entry B is running — fetches `/map_intent` only.
