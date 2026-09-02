# Memory + Context V1.2

## Purpose

V1.2 does **not** merge the existing local and cloud memories.

It introduces one context contract over the two existing domains:

```text
LOCAL MEMORY DOMAIN
  -> Qwen
  -> Claude Code

CLOUD MEMORY DOMAIN
  -> GLM
  -> Kimi
```

Each domain is assembled into the same four memory layers:

```text
1. STABLE_CORE
2. ACTIVE_STATE
3. RECENT_CONTIGUOUS_TURNS
4. RELEVANT_RECALL
+ CURRENT_TURN
```

The uniformity is the layer contract, not the storage ownership.

## Why two domains remain separate

`memory_domain` is selected by worker profile:

```toml
[context.qwen]
memory_domain = "local"

[context.cc]
memory_domain = "local"

[context.glm]
memory_domain = "cloud"

[context.kimi]
memory_domain = "cloud"
```

There is no local→cloud union query and no cloud→local union query.

If a Qwen job escalates to GLM, the GLM call is rebuilt against the **cloud**
memory domain. The two calls may belong to the same durable agent thread, but
their long-term memory sources remain separated.

## Four layers

### 1. STABLE_CORE

Existing stable identity/rules/core.

Properties:

- external source
- hard layer
- never silently truncated
- if it exceeds its configured budget, the call fails loudly

### 2. ACTIVE_STATE

V1.2 combines:

```text
existing domain active-state memory
+
structured operational state from the harness
```

The operational state is not an LLM summary. It is deterministic data:

```text
current_goal
job_id
job_status
worker
allowed_tools
allowed_paths
approval_mode
cloud_allowed
session_state
waiting_for
active_job_id
last_verified_state
```

ACTIVE_STATE is also protected from silent truncation.

### 3. RECENT_CONTIGUOUS_TURNS

The durable thread's most recent contiguous user/assistant turns.

This layer is not semantic retrieval.

Its job is to preserve "what we were just saying" even when no recall query
would retrieve it.

Newest turns win when the recent-turn budget is full.

### 4. RELEVANT_RECALL

Top-K recall from the selected existing memory domain.

This is supplemental. It may be reduced or explicitly truncated to fit the
worker context budget.

Every included record retains its `memory_id`.

## CURRENT_TURN

The current user turn is appended exactly once after the four memory layers.

It is not counted as a memory layer.

## Context ownership modes

`config.toml`:

```toml
[memory]
context_owner = "shadow"
```

### shadow

Recommended first deployment.

- Builds all four layers.
- Produces a context receipt.
- Does **not** inject external STABLE_CORE / ACTIVE_STATE / RECALL.
- Keeps V1.1 recent-thread behavior.
- Lets you prove the adapter mapping before touching live prompt semantics.

### harness

Final V1.2 mode.

- Harness injects all four layers.
- Disable any legacy duplicate context injection on the same 8501 chat route.
- One assembler owns the model context.

### gateway

Migration fallback.

- Harness sends only the current turn.
- Existing 8501 gateway remains the context owner.

Do not run `harness` plus a second legacy memory injector and call that
"more memory." That is duplicate context and creates contradictions.

## Existing-memory adapter

All external memory integration lives in:

```text
harness/memory_adapter.py
```

Default expected contract:

```text
GET  stable_core_path?subject_id=aster
GET  active_state_path?subject_id=aster
POST recall_path
```

Recall request:

```json
{
  "subject_id": "aster",
  "query": "current user turn",
  "top_k": 12
}
```

The adapter accepts common response shapes such as:

```json
{"content":"..."}
```

or:

```json
{"items":[
  {"memory_id":"m1","content":"...","source":"local"}
]}
```

If your existing endpoints use different field names, modify the normalizer in
`memory_adapter.py` **once**. Do not add QwenMemoryClient, GLMMemoryClient,
KimiMemoryClient, etc.

## Writes: avoid duplicates

Each memory domain has:

```toml
write_mode = "gateway_owned"
```

Options:

- `gateway_owned` — existing 8501 path already writes memory; harness does not duplicate it.
- `external` — harness posts turns to `write_path`.
- `none` — only the operational thread store is written.

Do not enable `external` if the same turn is already persisted by 8501.


## Cross-domain escalation isolation

A local Qwen/CC thread may explicitly escalate a job to GLM/Kimi.

That does **not** mean the cloud call inherits the local thread transcript.

With:

```toml
strict_domain_isolation = true
```

a local-session -> cloud-worker handoff gets:

```text
CLOUD STABLE_CORE
CLOUD ACTIVE_STATE
0 local RECENT_TURNS
CLOUD RELEVANT_RECALL
CURRENT_TURN
```

The deterministic operational state sent to cloud also redacts local
filesystem topology such as `allowed_paths`.

The context receipt makes this visible:

```json
{
  "memory_domain":"cloud",
  "session_domain":"local",
  "cross_domain_handoff":true,
  "layers":{
    "recent_turns":{"turns":0}
  }
}
```

A direct GLM/Kimi cloud thread is different: its own cloud-thread
RECENT_CONTIGUOUS_TURNS remain available.

This is the chain-isolation boundary. Cloud escalation is not permission to
export the local conversation history.

## Context budgets

Each worker owns a budget profile, not a memory store.

Example:

```toml
[context.qwen]
max_context_tokens = 32768
reserve_output_tokens = 8192
stable_core_tokens = 3500
active_state_tokens = 3500
recent_turns_tokens = 10000
recall_tokens = 6500
recall_top_k = 12
```

The current estimator is intentionally conservative:

```text
UTF-8 byte count
```

V1.2 also reserves `context.framing_reserve_tokens` for system prompts,
role framing, and layer labels so the configured layer payload does not consume
the entire nominal context window.

It is not advertised as an exact model tokenizer.

Why:
- exact tokenization differs by Qwen / GLM / Kimi / Claude backend
- underestimating causes context overflow
- overestimating only uses less of the window

A route-specific tokenizer can replace the estimator later without changing
the four-layer architecture.

## Context receipt

Every model/CC job emits a `context_receipt` event:

```json
{
  "worker":"qwen",
  "memory_domain":"local",
  "context_owner":"shadow",
  "context_hash":"...",
  "estimated_input_tokens":1234,
  "layers":{
    "stable_core":{"tokens":200,"memory_ids":["..."]},
    "active_state":{"tokens":500,"memory_ids":["..."]},
    "recent_turns":{"tokens":300,"turns":8},
    "recall":{"tokens":234,"memory_ids":["..."]}
  },
  "external_memory_injected":false,
  "shadow_only":true
}
```

The phone PWA has a **Context** button in every thread to view this receipt.

## Safe cutover

1. Map the actual local/cloud memory endpoints in `config.toml`.
2. Keep `context_owner="shadow"`.
3. Run `python context_probe.py`.
4. Verify:
   - Qwen/CC -> local
   - GLM/Kimi -> cloud
   - stable core is correct
   - active state is correct
   - memory IDs are real
   - no cross-domain IDs appear
5. Disable the legacy duplicate context injection for the harness chat route.
6. Change:
   ```toml
   context_owner = "harness"
   ```
7. Run the probe again and live E2E.

No memory migration is required merely to introduce the four layers.
