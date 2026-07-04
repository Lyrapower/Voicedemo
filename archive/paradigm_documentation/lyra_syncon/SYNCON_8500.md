# Entry A — Echo Gateway @ :8500

**Architecture lock:** Entry A only. **Compile + particle = Entry B @ 8787** (not proxied here).

Optional **`POST /api/route`** → LM Studio `qwen3-14b-mlx` (echo-side SynCon, not a unified Grid chain).

## Run

```bash
cd echo_nodes_interface/incoming/echo_nodes
./start.sh
```

## Endpoints

| Path | Role |
|------|------|
| `GET /health` | Gateway status |
| `POST /echo-node` | Echo frequency executor (protocol) |
| `GET /context` | `interface.echo-nodes.json` |
| `GET /descriptor` | `Config.toml` |
| `POST /api/route` | SynCon router → LM Studio 14B |
| *(none)* | Compile moved to **Entry B :8787** |

## SynCon route (local only)

```bash
curl -s http://127.0.0.1:8500/api/route \
  -H 'Content-Type: application/json' \
  -d '{
    "task":"auto",
    "messages":[{"role":"user","content":"Summarize compile layer in one line"}],
    "metadata":{"origin":"cli"}
  }'
```

Prerequisite: LM Studio server on `127.0.0.1:1234` with **qwen3-14b-mlx** loaded.

## Anchor

- `syncon/config/anchor.json` — Lyra core + banned phrases + `local`-only chain

## Not touched

- **9B** LM Studio chats
- **`gateway/`** token gateway (separate product; cloud providers optional there)
- **8787** Entry B: particle UI + `GET/POST /api/memory/*` (local compile, no proxy to 8500)
- **5173** dev: MEMORY calls `http://127.0.0.1:8787/api/memory/*`

Logs: `incoming/echo_nodes/logs/router.jsonl`
