# Grid Integration

Do not create a second Grid backend. Existing Grid should call the harness.

## Local/LAN

- Dashboard: `GET http://127.0.0.1:8787/sessions`
- Thread: `GET /sessions/{session_id}`
- Message agent: `POST /sessions/{session_id}/message`
- Live events: `WS /ws/events?after_seq=<cursor>`
- Replay after disconnect: `GET /events?after_seq=<cursor>`

## Existing Grid UI

Map existing Grid controls to the same endpoints:

```text
Grid card          -> session
Grid conversation  -> thread_messages
Grid activity      -> stream_events
Grid task          -> job
```

Do not create:
- another Grid memory DB
- another router
- another job state machine

The existing 8501 memory/context layer remains authoritative for long-term context. This harness stores operational session/job continuity.

## Suggested surfaces

```text
Grid
  Agents
    Qwen Resident
    Claude Code
    GLM · on demand
    Kimi · on demand
  Active
  Waiting for you
  Watchers
  Recent
```
