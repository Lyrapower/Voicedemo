# PORTS.md — bind-before-register

Port is registered here **before** bind or launchd. Duplicate bind = refuse.

| Port | Bind | Service | launchd | Notes |
|------|------|---------|---------|-------|
| 8500 | 127.0.0.1 | Entry A / Echo | — | Do not merge with 8787 |
| 8501 | 127.0.0.1 | Grid Sovereign Gateway | `com.demo.grid.gateway8501` | Frozen inference chain |
| 8504 | 127.0.0.1 | Grid Voice | `com.demo.grid.voice8504` | |
| 8515 | 127.0.0.1 | b11 workbench UI | — | API is 8501, not this port |
| 8520 | 127.0.0.1 | Aether watcher | — | |
| 8600 | 127.0.0.1 | Alpha platform | — | |
| 8630 | 127.0.0.1 | Grid Harness (`app.harness.server`) `/health` `/api/capabilities` | **no** | Session uvicorn only. Do not install LaunchAgent until this row says yes. |
| 8631 | 127.0.0.1 | PersonaPlex / Kokoro voice | — | Harness stays on 8630 |
| 8787 | 127.0.0.1 | Entry B / Aster particles | `com.demo.garden.aster8787` | Not harness |
| 8790 | 127.0.0.1 | ASTER FIELD bridge | `com.demo.field.bridge8790` | |

**8630:** registered 2026-08-26. Not in launchd. Cross-ref `PORT_PROCESS_CONVENTION.md`.
