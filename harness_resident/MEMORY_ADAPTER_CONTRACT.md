# Existing Memory Adapter Contract

V1.2 deliberately leaves the existing memory databases/services in place.

Only this boundary must be mapped:

```text
harness/memory_adapter.py
```

## Local domain

Used by:

```text
Qwen
Claude Code
```

Config:

```toml
[memory.local]
base_url = "http://127.0.0.1:8501"
stable_core_path = "/memory/local/stable_core"
active_state_path = "/memory/local/active_state"
recall_path = "/memory/local/recall"
```

## Cloud domain

Used by:

```text
GLM
Kimi
```

Config:

```toml
[memory.cloud]
base_url = "http://127.0.0.1:8501"
stable_core_path = "/memory/cloud/stable_core"
active_state_path = "/memory/cloud/active_state"
recall_path = "/memory/cloud/recall"
```

The paths above are integration placeholders. Replace them with the actual
existing endpoints; do not create duplicate storage just to satisfy these names.

## Required invariants

- Qwen/CC context receipt must say `memory_domain=local`.
- GLM/Kimi context receipt must say `memory_domain=cloud`.
- Local memory IDs must never appear in a cloud receipt through union logic.
- Cloud memory IDs must never appear in a local receipt through union logic.
- `STABLE_CORE` and `ACTIVE_STATE` cannot silently truncate.
- `RECALL` may truncate explicitly.
- `CURRENT_TURN` is appended once.
- `context_hash` changes when an injected layer changes.

## If your endpoint returns a different schema

Change only:

```text
MemoryDomain._single_record()
MemoryDomain._records()
```

Do not fork the entire adapter per model.
