# Architecture v1.2

```text
Phone / Grid / Cursor IDE
          |
      Grid API 8787
          |
   Durable Job Store
          |
      Supervisor
      /   |    \
   Qwen GLM/Kimi Claude Code
      \   |    /
          8501
 authoritative gateway
```

## Durable job thread

Statuses:

```text
queued
running
waiting_approval
blocked
done
failed
interrupted
```

A job has:
- job_id
- channel
- goal
- worker
- allowed_tools
- allowed_paths
- cloud_allowed
- approval_mode
- checkpoint state

## Slack-like model

```text
# grid
  J184 [running] qwen  inspect gateway
  J185 [waiting] cc    wants approval
  J186 [done]    kimi  image analysis
```

Events are append-only and attached to the job/thread.

## Escalation

Qwen may emit exactly:

```json
{"action":"escalate","target":"glm","reason":"deeper reasoning required"}
```

or:

```json
{"action":"escalate","target":"kimi","reason":"multimodal input required"}
```

Supervisor accepts it only when `cloud_allowed=true`.

Cloud output returns as a candidate to the local harness. It never gets DB/filesystem authority.

## Recovery

On boot:

```text
running -> interrupted
```

Then, if policy allows:

```text
interrupted -> queued
```

up to retry limits.

Recovery comes from durable state, not model memory.


## V1.1 Control plane

```text
                    Mobile PWA / Existing Grid
                         | REST + WSS
                         v
                  Grid Harness :8787
          +-----------+--------+-----------+
          |           |                    |
       sessions      jobs              stream_events
          |           |                    |
          +-----------+---------+----------+
                                |
                           Supervisor
                    max_concurrency = N
                       /       |       \
                  Qwen        CC      GLM/Kimi
                    \          |          /
                              8501
```

## Continuity

A WebSocket is not continuity.

```text
stream_events.seq
      +
phone lastSeq
      +
GET /events?after_seq=N
```

is continuity.

## Session vs job

A session is a durable conversation/control thread.

A job is one execution spawned from that thread.

```text
session
  message
  job 1
  message
  job 2
  message
```

This is intentionally closer to Slack threads than one-shot CLI tasks.


## V1.2 memory/context plane

```text
                  one Context Assembler
                         |
        +----------------+----------------+
        |                                 |
   LOCAL DOMAIN                      CLOUD DOMAIN
   existing memory                   existing memory
        |                                 |
     Qwen / CC                        GLM / Kimi
```

For every worker:

```text
STABLE_CORE
    +
ACTIVE_STATE
    +
RECENT_CONTIGUOUS_TURNS
    +
RELEVANT_RECALL
    +
CURRENT_TURN
```

`memory_domain` is a worker property.

It is not a tab, surface, or personality.

The operational job/session database remains separate from long-term semantic
memory. It contributes deterministic ACTIVE_STATE and recent thread continuity;
it does not become a third long-term memory system.
