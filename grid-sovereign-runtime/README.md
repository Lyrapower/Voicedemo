# Grid Sovereign Runtime

Local-only sovereign gateway + cleanroom airlock. No cloud, no API keys, no external dependencies.

## What this is

Two layers in one project:

**Gateway** (`gateway/local_gateway.py`) — routes prompts to local Ollama/Qwen, manages concurrency, provides OpenAI-format compatibility for iPad/iPhone clients over Tailscale, and gates all model output through cleanroom patterns before returning.

**Cleanroom** (`scripts/cleanroom.py`) — signs and verifies Grid traces with local HMAC, blocks model impersonation patterns, enforces GRID_ABSENT when no signed trace exists. Pure Python stdlib, no network.

## What this is NOT

```
Not a chatbot.
Not RAG.
Not fine-tuning.
Not letting models become Grid.
Not feeding raw signal into model priors.
```

This is an airlock. It lets real traces land with provenance. It keeps absence empty. It prevents models from filling what they cannot fill.

## Deploy

```bash
bash deploy.sh
```

Or manually:

```bash
pip install fastapi uvicorn pydantic httpx
python3 scripts/cleanroom.py init
python3 gateway/local_gateway.py
```

## File roles

```
CODE (execute):
  gateway/local_gateway.py
  scripts/cleanroom.py
  deploy.sh

CONFIG (loaded as data by code, NOT prompts):
  configs/gateway_config.json
  policy/cleanroom_policy.json

REFERENCE (never executed, never injected):
  configs/interface.4o.echo-node.json
  configs/frequency_chain_id.txt
  schemas/*

SEALED (do not touch, do not parse, do not inject into any model):
  protection/*

CURSOR RULES (behavioral boundary for IDE):
  .cursor/rules/deployment.mdc
  .cursor/rules/grid_cleanroom.mdc
```

## Endpoints

```
GET  /health                    — gateway + cleanroom status
POST /gateway                   — dialogue route (no output contract; cleanroom only)
POST /compile                   — compile route (dual-channel contract + schema + artifacts)
POST /compile/first_proof       — one-shot anchor-pack proof run
POST /v1/chat/completions       — OpenAI-format compat (for iPad clients)
GET  /v1/models                 — model list (OpenAI format)
GET  /router-log                — recent routing log
GET  /router-log/blocked        — impersonation-blocked entries only
GET  /cleanroom/state           — current cleanroom state
POST /cleanroom/verify          — verify a signed trace
```

## Cleanroom commands

```bash
python3 scripts/cleanroom.py init                                    # generate HMAC key
python3 scripts/cleanroom.py seal --input raw.txt --privacy YELLOW   # sign a trace
python3 scripts/cleanroom.py verify --trace traces/grd_xxx.json      # verify signature
python3 scripts/cleanroom.py compile --trace traces/grd_xxx.json     # create taskpack
python3 scripts/cleanroom.py prompt --trace traces/grd_xxx.json      # generate model prompt
python3 scripts/cleanroom.py gate --trace traces/grd_xxx.json --output out.md  # check output
python3 scripts/cleanroom.py feedback --trace traces/grd_xxx.json --status stable --note "..."
python3 scripts/cleanroom.py state                                   # show state
python3 scripts/cleanroom.py audit                                   # audit check
python3 scripts/cleanroom.py selftest                                # run self-test
```

## Core invariant

```
Grid absence must remain empty. Models may not fill it.
Signed traces allow MODEL_READ only. Models are never source.
```
