# Mobile Agent Console

The PWA is under `mobile/`.

## Two connection modes

### Local/LAN

```text
By default the harness binds to `127.0.0.1`.

For direct phone access on a trusted LAN, set in `~/.config/grid/harness_resident.env`:

```bash
GRID_BIND_HOST=0.0.0.0
```

Then:

```text
iPhone -> http://MAC_LAN_IP:8787
```

Do not expose port 8787 directly to the public Internet.

### Remote Relay

```text
iPhone PWA
   |
 HTTPS/WSS
   v
Thin Relay
   ^
 outbound WSS
   |
Mac Harness
```

The Mac never needs an inbound public port.

## Reliability model

WebSocket is only the live transport.

Truth is:

```text
SQLite stream_events
+ monotonic seq
+ phone lastSeq
+ replay after reconnect
```

So Wi‑Fi/5G changes or iPhone lock do not define continuity.

On reconnect the phone requests all events after its last persisted sequence number.

## Agent views

Default control threads:

- Qwen Resident
- Claude Code
- GLM · on demand
- Kimi · on demand

Create more threads from the `+` button.

Each thread can:
- send messages
- create work
- pause
- resume
- cancel
- receive live response deltas
- survive reconnects

GLM/Kimi threads do not mean cloud workers stay alive 24/7. They are durable local control threads that spawn cloud inference only when messaged.


## Context button

V1.2 adds **Context** inside each agent thread.

It shows the server-side context receipt:

```text
worker
memory_domain
context_owner
context_hash
stable / active / recent / recall sizes
memory IDs
```

It does not guess from UI state.

By default the receipt does not expose full memory contents. The local API has
`include_content=true` for explicit debugging.
