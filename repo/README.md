# Aster Router (Lean)

Local-first FastAPI router with streaming to local LLM backends.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
./scripts/run.sh
```

Server: `127.0.0.1:8787`

## Endpoints

### GET /health

Returns:

```json
{
  "status": "ok",
  "primary_backend": "ollama",
  "fallback_backend": "llama.cpp"
}
```

### POST /stream

Input:

```json
{
  "message": "string",
  "session_id": "default",
  "mode": "flow",
  "context_map": {}
}
```

Output is Server-Sent Events (SSE):

- `event: token` with raw text chunks
- `event: final` with a JSON object:

```json
{
  "raw_text": "string",
  "backend_used": "ollama",
  "coherence_score": 0.0,
  "audit_id": "string"
}
```

Example request:

```bash
curl -N http://127.0.0.1:8787/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","session_id":"default","mode":"flow","context_map":{}}'
```

## Backend config

Environment variables (optional):

- `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`)
- `OLLAMA_MODEL` (default `qwen3:8b`)
- `LLAMA_CPP_BASE_URL` (default `http://127.0.0.1:8080`)

## State

Per-session JSON files are stored under `data/sessions/`.
