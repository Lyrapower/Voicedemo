# CC sandbox v3.2 phase 1 · 2026-09-07

`--network none`. Model path is per-job Linux volume Unix socket, not socat and not host ports.

| 项 | 值 |
|---|---|
| cc image | `grid-cc:2.1.201` (`72575045ec3c`) — not upgraded |
| broker image | `python:3.13-slim` (already local) |
| cc network | `none` |
| broker net | `grid-cc-broker-net` (no publish; host-gateway to Ollama only) |
| /bridge | per-job volume `grid-cc-bridge-<job>` · broker rw · cc ro |
| /work | per-job volume `grid-cc-work-<job>` |
| model | `127.0.0.1:11434` (cc netns relay) → `/bridge/model.sock` → broker → host Ollama |
| tools (phase 1) | existing Write/Edit deny kept; Bash policy unchanged |
| old fwd | `grid-cc-fwd` left running, unused; not deleted |

Missing broker/image → `BLOCKED_SANDBOX_MISSING`. No host claude fallback.
Phase 2: safe exporter + /work Write/Edit/Bash. Phase 3+ (egress.sock, dev.sock) not enabled.
