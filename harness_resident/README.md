# Grid Resident Harness v1.3.1

A small 24/7 agent harness built around one authority plane.

## Roles

- **8501** — authority / model routing / context injection
- **Qwen coder** — default resident worker
- **GLM** — explicit deep-reasoning escalation
- **Kimi** — explicit multimodal escalation
- **Claude Code** — bounded coding executor
- **Grid API (8787)** — control surface
- **SQLite** — durable sessions, jobs, messages, replayable events, checkpoints
- **Outbound relay** — optional mobile path without making Tailscale the only lifeline

Slack is borrowed only as an interaction pattern:

- `channel` = logical workspace
- `thread` = one durable job
- `event` = immutable activity log
- `waiting_approval` = thread waiting on a human

No Slack account/API is required.

## v1.3.1 (SOL closeout)

- Tool fence is deny-by-default over the known CC built-in universe: declared tools → `--allowedTools`, everything else → `--disallowedTools` (deny wins in CC's model). Snapshot constant `CC_TOOL_UNIVERSE` must track CC upgrades.
- Non-loopback bind without `GRID_HARNESS_TOKEN` refuses to boot (`validate_bind`, fail-closed before uvicorn starts).
- `test_security_v131.py`: S1-S10 regressions; offline tier runs anywhere, `--onsite` tier exercises real HTTP/WS enforcement (needs fastapi) and documents the live CC fence check.
- Release archive ships no `__pycache__`/`*.pyc`.

## v1.3 (gates)

- cc jobs and direct GLM/Kimi jobs are born `blocked` and require approval (approve/resume button or `POST /jobs/{id}/requeue`); `approval_mode="auto"` on an authenticated call bypasses for cc.
- The three silent `cloud_allowed=True` overrides are removed; invariant #7 now holds on every path.
- `allowed_tools`/`allowed_paths` are enforced via CC flags (`--allowedTools`, `--add-dir`), not prompt text; unknown-flag CC versions fail loudly instead of running unfenced.
- Set `GRID_HARNESS_TOKEN` to require `Authorization: Bearer` on every :8787 endpoint and `?token=` on `/ws/events` (mobile Settings token field covers both). Unset = v1.2 behavior with a loud startup warning.

## Hard invariants

1. 8501 is the only model-routing authority.
2. Cloud models do not receive direct DB/filesystem access.
3. Claude Code does not own memory or routing.
4. Grid is a control surface, not a second execution core.
5. Jobs survive restarts.
6. Each job declares allowed tools/paths.
7. Cloud escalation is off by default.
8. Relay transports envelopes only; it is not memory.
9. WebSocket may disconnect; continuity comes from durable event replay.
10. GLM/Kimi are on-demand cloud workers, not 24/7 memory owners.

## Install

```bash
bash install.sh
source .venv/bin/activate
cp .env.example .env
```

Edit `config.toml` so the route names match your actual 8501 routes.

## Run

```bash
bash run_local.sh
```

In another terminal:

```bash
source .venv/bin/activate
python smoke_test.py
```

Open:

```text
http://127.0.0.1:8787/docs
```

## Minimal job

```bash
curl -s http://127.0.0.1:8787/jobs \
  -H 'content-type: application/json' \
  -d '{
    "channel":"grid",
    "goal":"Inspect the repository and summarize failing tests.",
    "worker":"qwen",
    "allowed_tools":["read","test"],
    "allowed_paths":["."],
    "cloud_allowed":false
  }'
```

Worker choices:

- `qwen`
- `glm`
- `kimi`
- `cc`

Cloud routes require `cloud_allowed=true`.

## Mobile without Tailscale dependency

Deploy `relay_server.py` on a small HTTPS/WSS host. The Mac makes an outbound persistent WebSocket to it. No inbound port to the Mac is required.

For production:
- TLS only
- strong bearer token
- rate limit
- no plaintext persistence

## Voice

See `VOICE_BRIDGE.md`.

Voice is transport, not a new agent brain.


## V1.1 Mobile Agent Console

Open locally:

```text
http://127.0.0.1:8787/
```

or from another device on the LAN using the Mac LAN IP.

The PWA shows:
- Qwen Resident
- Claude Code
- GLM · on demand
- Kimi · on demand
- additional agent threads created with `+`

Each thread supports:
- separate conversation history
- durable session state
- current job
- live model deltas
- pause / resume / cancel
- waiting approval state
- reconnect + event replay

See `MOBILE_CONSOLE.md`.

## 24/7 Mac service

After normal install:

```bash
bash install_launchd.sh
```

The LaunchAgent uses `KeepAlive` and restarts the harness after crashes/login.

Remove it with:

```bash
bash uninstall_launchd.sh
```

## Important pause semantics

Pause is not fake token-level suspension.

For an active job it cancels the live runtime request/process, records the job as `interrupted`, and preserves the durable thread/job state. Resume requeues from that durable state.

## Concurrent agents

`core.max_concurrency` controls how many jobs may run simultaneously.

Default:

```toml
max_concurrency = 4
```

Jobs are atomically claimed from SQLite so the same queued job cannot be dispatched twice.

## Existing Grid

Do not create another Grid state machine.

Wire existing Grid UI to the same sessions/jobs/events endpoints described in `GRID_INTEGRATION.md`.


## V1.2 — Continuous memory + context windows

V1.2 keeps the existing memory split:

```text
Qwen / CC  -> local memory domain
GLM / Kimi -> cloud memory domain
```

It does **not** merge local and cloud memory.

Every worker now receives one canonical context assembled from:

```text
STABLE_CORE
ACTIVE_STATE
RECENT_CONTIGUOUS_TURNS
RELEVANT_RECALL
CURRENT_TURN
```

The four memory layers are built by:

```text
harness/context.py
```

The two existing memory domains are adapted by:

```text
harness/memory_adapter.py
```

Do not create model-specific memory clients.

### First deployment: shadow mode

The package intentionally ships with:

```toml
[memory]
context_owner = "shadow"
```

Why: your 8501 already has local/cloud memory behavior. Shadow mode lets you
verify the four-layer mapping without accidentally double-injecting legacy
memory.

Probe it:

```bash
source .venv/bin/activate
python context_probe.py --worker qwen
python context_probe.py --worker glm
```

Then map the real existing memory endpoints in `config.toml`.

When the receipts are correct and the legacy duplicate injector is disabled for
this chat route, cut over:

```toml
context_owner = "harness"
```

### Context receipt

Every model job emits a `context_receipt` event with:

- worker
- memory domain
- context hash
- estimated input size
- stable-core memory IDs
- active-state memory IDs
- recent-turn count
- recall memory IDs
- injected/shadow state

The phone thread has a **Context** button to inspect it.

### Hard behavior

- STABLE_CORE never silently truncates.
- ACTIVE_STATE never silently truncates.
- RECENT_TURNS keeps newest contiguous history.
- RECALL is supplemental and may explicitly truncate.
- CURRENT_TURN is appended exactly once.
- A current turn written to memory is filtered out of same-turn recall.
- Qwen/CC never union-query cloud memory.
- GLM/Kimi never union-query local memory.
- Local→cloud escalation does not export the local thread's recent transcript.
- Cloud ACTIVE_STATE redacts local filesystem paths by default.

Read:

- `MEMORY_CONTEXT_V1.2.md`
- `MEMORY_ADAPTER_CONTRACT.md`
