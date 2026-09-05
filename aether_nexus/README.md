# Aether Nexus R5.4.1

IB Paper daemon + **Data-Hardened Dry Run** (Alpaca/Stooq/yfinance + Gemini) + Streamlit dashboard.

## Architecture

| Component | Role |
|-----------|------|
| `aether_daemon.py` | Exclusive IB connection, auto buy/monitor from Dry Run candidates |
| `aether_dryrun.py` | Dry Run scanner — **pool** (做T池) + **sp500** (BFS 漏斗) dual lines |
| `aether_dashboard.py` | Streamlit UI — IB + Dry Run tabs |
| `post_market_summary_daemon.py` | Post-close scan log → `:8501` Aster JSON summary → Telegram + `traces/daemon/` |
| `watchlist.json` | 紫苏叶 watchlist + catalyst metadata |
| `state/` | IB daemon writes, dashboard reads |
| `dryrun_state/` | Dry run signals, iv_history, data_health, filtered logs |
| `commands/` | Dashboard → daemon command files |

Daemon and dashboard communicate via files only — no shared IB connection in Dry Run.

## Quick Start

```bash
cd /Users/ciciwang/Projects/demo/aether_nexus
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Start IB Gateway (paper **7497**), configure `.env` (Alpaca keys recommended, Telegram, Gemini), then:

```bash
./run_all.sh
```

Dashboard: **http://localhost:8510** (binds `127.0.0.1` only)

## Scan architecture (R5.4.1)

| Layer | Component | Data source | Role |
|-------|-----------|-------------|------|
| **Scan** | `aether_dryrun.py` | **Alpaca → Stooq → yfinance** | BFS sp500 + pool lines; trading-day gate |
| **Buy** | `aether_daemon.py` | Reads `dryrun_state/signals.json` | IB paper execution only — **no IB universe scan** |

Set `IB_SCAN_SOURCE=dryrun` (default). Legacy IB scan: `IB_SCAN_SOURCE=ib`.

Dry Run writes `state/candidates.json` after each BFS scan so the IB tab and daemon share the same picks.

### R5.4.1 data layer

- **Stocks/history:** `DATA_PROVIDER_ORDER=alpaca,stooq,yfinance`
- **Options:** `OPTION_PROVIDER_ORDER=alpaca,yfinance` (Alpaca free = indicative feed)
- **Health log:** `dryrun_state/data_health.json`
- **Trading-day gate:** skips weekends/holidays via Alpaca `/v2/calendar` when keys present
- Gemini key in header (not URL); Telegram via plain HTTP

## Dry Run — Scan Lines

| Line | Schedule (EST) | Output |
|------|----------------|--------|
| **紫苏叶** | 08:30 (+ 08:25 reminder) | `perilla_signals.json` |
| **股票池** | 09:35, 15:20 | `pool_signals.json` |
| **BFS sp500** | 09:40, 15:30 | `signals.json` + **`state/candidates.json` → IB** |

Pool symbols skip price-range filters. Set `POOL_SCAN_ENABLED=false` to disable pool line.

Default pool: `MU,MRVL,AMD,HOOD,DELL,APA,OXY,IONQ,NVDA,TSLA,PLTR,COIN`

### Scoring (R5.4.1)

- **Theta filter by DTE:** short ≤0.12, mid ≤0.08, long ≤0.055
- **IV value factor:** up to 10 pts; `hv_rank` proxy until ~60 rounds in `iv_history.json`
- Sentiment stub removed; OI relaxed when Alpaca snapshot omits open interest

## Scheduled Tasks (EST)

### IB Daemon

| Time | Action |
|------|--------|
| Every 10s loop | Sync candidates from Dry Run (`IB_SCAN_SOURCE=dryrun`) |
| Every 60s | Position monitor |
| Every 120s (10:00–15:00) | Buy using Dry Run strike/expiry via IB |

### Dry Run

| Time | Action |
|------|--------|
| **08:25** | 紫苏叶 scan reminder |
| **08:30** | 紫苏叶 watchlist scan (+ buy signal if score ≥ 35) |
| **09:35** | 股票池 scan |
| **09:40** | BFS sp500 → **IB 买入候选** + 买入提醒 |
| **15:20** | 股票池 scan |
| **15:25** | 下午买入提醒 |
| **15:30** | BFS sp500 → IB |

Set `DRYRUN_SCAN_ON_START=false` (default) to skip scan on restart.

## Dashboard Tabs

1. **IB Paper Trading** — positions, IB scan candidates, audit log
2. **Dry Run** — 做T股票池, pool/BFS results, 紫苏叶 watchlist, data health

## Key `.env` Variables

```env
# Alpaca (recommended)
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
DATA_PROVIDER_ORDER=alpaca,stooq,yfinance
OPTION_PROVIDER_ORDER=alpaca,yfinance

# Dry Run
IB_SCAN_SOURCE=dryrun
DRYRUN_SCAN_MODE=sp500
POOL_SCAN_ENABLED=true
DRYRUN_SCAN_ON_START=false
SCAN_PRE_MARKET=09:40
SCAN_POST_MARKET=15:30
```

See `.env.example` for full list.

## State Files

| File | Content |
|------|---------|
| `state/candidates.json` | Latest BFS picks for IB |
| `dryrun_state/signals.json` | BFS scan history |
| `dryrun_state/pool_signals.json` | Pool scan history |
| `dryrun_state/perilla_signals.json` | 紫苏叶 scan + buy_signals |
| `dryrun_state/data_health.json` | Provider fetch health |
| `dryrun_state/iv_history.json` | ATM IV history for IV rank |

## Operational Notes

- Without Alpaca keys, scanner falls back to Stooq/yfinance (slower; yfinance may rate-limit)
- Increase `STOOQ_SLEEP` / `YF_SLEEP` if Stage 2 returns empty
- Pool mode ~12 symbols (~2–3 min); sp500 BFS full run ~15–25 min
- IB disconnect affects auto-buy only — Dry Run Telegram reports are independent

## Post-Market Summary daemon v1

After each trading day (default **16:35 EST**), reads same-day `dryrun.log`, calls **`:8501` / `demo/aster`**, triple-votes `candidate_count` / `top_symbol` / `top_score`, pushes Telegram, writes `grid-sovereign-runtime/traces/daemon/`.

```bash
# One-shot (today or --date YYYY-MM-DD)
/Users/ciciwang/Projects/demo/scripts/start_post_market_summary.sh --once --dry-run

# 5-day acceptance dry-run loop (title prefix [DRY-RUN])
/Users/ciciwang/Projects/demo/scripts/start_post_market_summary.sh --loop --dry-run
```

Requires `:8501` gateway up and `TELEGRAM_*` in `.env`. `contract_gate` quarantines outputs containing 建仓/做多/做空/买入/卖出/加仓 (no Telegram dispatch).

## Sync topology (Aether ↔ Alpha · 只读可见性 · TICK_SECONDS=300 不动)

| Writer | What | Cadence | Reader | Face period |
|--------|------|---------|--------|-------------|
| `aether_dryrun` / scan daemons | `grid_store` events (`aether_scan`, brief, …) | trading windows (09:40/15:30 ET etc.) | Aether UI `:8501/app/aether.html` | poll **30s** |
| Alpha worker `:8600` | `platform.db` ticks/bars/factors/heat nominations | **TICK_SECONDS=300** | Alpha Console `/app` | WS ~2s / HTTP poll |
| Alpha worker | heat = WATCHLIST + scan 提名≤8 | same tick | `/api/pulse` equity | tick-bound |
| BFS raw rows | store `aether_scan` | scan windows | Console BFS 区 | **即时**(不经 tick) |
| Factory propose | `8600 → 8501 /factory/task`（**factory 分类器**，≠ `:8500` Router） | on demand | `factor_drafts` | — |

共享事实源只有 `grid_store.db`；**无 live bus**。UI 数据龄徽章：store 最后写入 ts vs 本面最后读取 ts；超本面周期×2 → 琥珀。

## Legacy

`aether_nexus.py` (R3.4 monolith) retained for reference.
