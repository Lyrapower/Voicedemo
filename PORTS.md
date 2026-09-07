# PORTS.md — bind-before-register

Port is registered here **before** bind or launchd. Duplicate bind = refuse.

| Port | Bind | Service | launchd | Notes |
|------|------|---------|---------|-------|
| 8500 | 127.0.0.1 | Entry A / Echo | — | Do not merge with 8787 |
| 8501 | 127.0.0.1 | Grid Sovereign Gateway | `com.demo.grid.gateway8501` | Frozen inference chain |
| 8504 | 127.0.0.1 | Grid Voice | `com.demo.grid.voice8504` | Voice daemon (ASR/TTS), **NOT** local LLM proxy |
| 8515 | 127.0.0.1 | b11 workbench UI | — | API is 8501, not this port |
| 8520 | 127.0.0.1 | Aether watcher | — | |
| 8600 | 127.0.0.1 | Alpha platform | — | |
| 8630 | 127.0.0.1 | Grid Harness api (`harness_resident`) `/health` `/api/jobs` `/api/capabilities` `/api/receipts` `WS /ws/events` | `com.grid.harness-api` | owner=`harness_resident`; local; token from env not plist |
| — | — | H1 carrier (no bind; reads 8501 store `field-particle` ro, POSTs 8630) | `com.grid.h1-carrier` | not a port; KeepAlive; plist only |
| 8631 | 127.0.0.1 | kokoro-tts (PersonaPlex / Kokoro) | `com.grid.kokoro-tts-8631` | in register; voice package later; harness stays on 8630 |
| 8787 | 127.0.0.1 | Entry B / Aster particles | `com.demo.garden.aster8787` | Not harness; do not confuse with 8788 |
| 8788 | — | closed | — | telemetry stub; default off (D8) |
| 8790 | 127.0.0.1 | ASTER FIELD bridge | `com.demo.field.bridge8790` | |
| 1234 | 127.0.0.1 | LM Studio model API | — | local OpenAI-compatible endpoint; owner=LM Studio process; execution=local model inference; default model **config-derived** (`config/aster.toml` `api_model_id`); NOT "Aster proxy" — Aster is a model served here, not the port's identity |
| 11434 | 127.0.0.1 | Ollama API | — | transport only; native Ollama API + OpenAI-compat + Anthropic Messages; execution=local_or_cloud_by_selected_model; **NOT "local inference"** (`:cloud` model = remote execution) |

**8630:** GOLIVE v1.3 owner=`harness_resident`. launchd `com.grid.harness-api`. Cross-ref `PORT_PROCESS_CONVENTION.md`.
