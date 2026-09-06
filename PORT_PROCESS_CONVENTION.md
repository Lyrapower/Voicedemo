# Port & process convention (repo root)

Effective: 2026-07-04

## Sovereign ports

- **8501** — Grid Sovereign Gateway (`demo/aster` substrate door, LM Mini Tailscale Serve target)
- **8504** — Grid Voice daemon (ASR/TTS; `com.demo.grid.voice8504`)
- **8787** — Aster / Entry B telemetry & particles orchestration
- **8790** — ASTER FIELD bridge (read-only sidecar; forwards to :8501, serves particle UI)

These ports are **not** script-managed. Do not `kill`, `lsof -t … | kill`, or `pkill` listeners on **8501**, **8787**, or **8790** from repo scripts.

**8790 bridge code** must never kill any port (including 8501/8787).

## Model transport / provider ports

- **1234** — LM Studio model API (`LM Studio` process; local OpenAI-compatible inference endpoint)
  - `process` = LM Studio app (`lms server start --port 1234`)
  - `port` = 1234
  - `role` = local model inference surface (OpenAI-compatible `/v1`)
  - `exclusive_listener` = true
  - `execution locality` = **local model dependent** — endpoint is a local process; models loaded by LM Studio execute locally. Default model is **config-derived** (`config/aster.toml` `api_model_id`), not a hardcoded port identity.
  - `protocols` = OpenAI-compatible (`/v1/chat/completions`, `/v1/models`)
  - `authority` = local inference surface — this port is **not** "Aster proxy". `demo/aster` is one model served here (specialized explicit resource, gated by :8501 five-layer contract); the port itself is a generic local model endpoint. Sanitizer/gate run **inline in :8501** (`substrate_sanitizer` / `substrate_gate` / `airlock_bridge` imported as modules), not as a separate proxy process on this port.

- **11434** — Ollama API (`ollama` process; model transport / provider endpoint)
  - `process` = ollama
  - `port` = 11434
  - `role` = model transport / provider endpoint
  - `exclusive_listener` = true
  - `execution locality` = **derived from selected model, not port locality** — `127.0.0.1:11434` endpoint is a local process, but a `:cloud` model (e.g. `glm-5.3:cloud`) executes remotely via Ollama Cloud; a non-`:cloud` model executes locally. Provenance must record `transport_locality` and `model_execution_locality` separately (do **not** collapse into one local/cloud Boolean).
  - `protocols` = native Ollama API + OpenAI-compatible (`/v1/chat/completions`) + Anthropic Messages (`/v1/messages`)
  - `authority` = transport only — this port is **not** a claim of local inference.

## Process management

Start, stop, and restart **only** via **launchctl** and installed LaunchAgents:

```bash
# Gateway :8501
launchctl kickstart -k "gui/$(id -u)/com.demo.grid.gateway8501"

# Voice daemon :8504 — see GRID_VOICE_SPEC §2.3 before any restart
#   initializing / asr_download<1.0 → NO restart (no -k, no kill -9)
#   graceful (preferred):
launchctl kill SIGTERM "gui/$(id -u)/com.demo.grid.voice8504"
#   hard (-k) ONLY when curl :8504/health shows status=ok:
# launchctl kickstart -k "gui/$(id -u)/com.demo.grid.voice8504"

# Aster :8787
launchctl kickstart -k "gui/$(id -u)/com.demo.garden.aster8787"

# ASTER FIELD bridge :8790
launchctl kickstart -k "gui/$(id -u)/com.demo.field.bridge8790"

# Install / reload plists (one-time or after plist edits)
bash scripts/garden/install_launchagents.sh
bash scripts/install_aster_field_launchagent.sh
```

Do **not** use `scripts/start_grid_gateway.sh` for manual restarts unless you are debugging launchd itself.

## Repair / verify scripts

Scripts named `repair_*`, `verify_*`, or `setup_*` that touch phone or tailnet connectivity:

- **May**: curl health, DNS, Tailscale Serve status, print LM Mini URL hints, write reports under `grid-sovereign-runtime/traces/proof/`
- **Must not**: kill processes, rewrite gateway logic, sync model IDs into config, or restart `:8501` / `:8787`

Examples (check-only):

- `scripts/verify_scheme2_dns.sh`
- `scripts/setup_tailscale_gateway.sh` — Serve config only; if gateway health fails, **report** and tell user to `launchctl kickstart`, do not start/kill gateway inline

## Regression gate (Aster tab)

After any change that might affect `:8501` routing or Aster identity:

```bash
python3 scripts/aster_tab_fingerprint_probe.py
```

Rollback is not complete until `grid-sovereign-runtime/traces/proof/aster_tab_fingerprint.json` shows `served_by: gateway-v4.11` on gateway non-stream and stream probes.

## Harness GOLIVE exceptions (2026-09-05)

- **L5 kimi alias:** `kimi_k3` is silently aliased to `glm53` on gateway. Harness never sends `kimi_k3`. Do not add a kimi route. Do not change gateway to "fix" the alias.
- **L7 cc lane :11434:** claude CLI talks to Ollama `:11434` directly and does **not** go through `:8501`. This is a registered 8501 exception. Model names still follow the 8501 route table. Adding Anthropic Messages passthrough on 8501 is a Lyra unlock, not this package. Do not build an 8503 bridge.

## Deferred work (queued)

See `work_orders/WO-2026-07-04-gateway-dynamic-models.md` — dynamic `/v1/models` and `/health` `substrate_models` are **out of scope** until post–dry-run review.

## Market data sources (Alpha / TRADE_EXEC · Lyra 2026-09-03)

**原则：付费源为主；券商免费 IEX 只做交叉核对，不作主表。Theta 仅期权，不调用股票端点。**

| 层 | 主源 | 交叉核对 | 禁止 |
|----|------|----------|------|
| **热力 60s · 价量** | **FMP** `/stable/batch-quote`（1 req；402 时 fallback `stable/quote×N` 同 Scout 档）→ `bars.src=fmp_quote` | Alpaca IEX `trades/latest` + `snapshots` bid/ask → `heat_crosscheck` | Alpaca 写主表 · Theta 股票端点 |
| **日线 / ret_1d / movers** | **FMP** EOD + quote | Alpaca 备份缺票 | — |
| **期权 GEX/IV/工作站** | **Theta** EOD normalized（`:25503` 期权链） | — | Theta 股票 snapshot/stream |
| **Lane B 滑点参照** | **`ref_px`** = FMP quote `price` @ `signal_ts`（`ref_src=fmp_quote`；无 bid/ask 故无中价） | Alpaca IEX bid/ask 对照列 | Theta 股票端点 |
| **Lane B 成交** | Alpaca paper/live `fill_px` | — | — |

- **数据龄** = `now − FMP quote.timestamp`（页面「数据龄」按 worst-case equity 行）。
- **交叉核对处决**：`|FMP−Alpaca|/price > 0.5%` 或 FMP 滞后 **>60s** → 该只 `stale=1`，WARNING 日志，pulse 暴露，不静默。
- **环境变量**：`HEAT_TICK_SECONDS=60` · `SCAN_TICK_SECONDS=300` · `HEAT_CROSSCHECK_LAG_S=60` · `HEAT_CROSSCHECK_DELTA_PCT=0.005`。
