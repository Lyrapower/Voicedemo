# R1 — Post-market fact pack

Schema: `postmarket_fact_pack/v1` (`aether_nexus/postmarket_fact_pack.py`)

## Fields

| Field | Type | Purpose |
|---|---|---|
| `trade_date` | ISO date | Session anchor |
| `zero_realized_close` | bool | Always true for report-only mock |
| `zero_close_statement` | str | Explicit «今日零平仓» fed to compile |
| `win_rate_available` | bool | false → review guard drops win-rate sentences |
| `signals` | list | Per-chain premarket journal rows |
| `open_positions` | list | Mock wallet open legs |
| `closed_today_count` | int | 0 until IB closes exist |
| `filter_kill_counts` | map | Kill rule tallies |
| `premarket_ab` | object | grid_n, sonnet_n, warmup, ab_ledger_start |

## Invariants

1. Grid and Sonnet review receive **identical** fact pack envelope.
2. Unsourced win-rate / close stats → `postmarket_review_guard.audit_review_text` tags `fact_gap` (supply gap), not confabulation.
3. Fact pack is built **before** compile; journal includes `format_fact_pack_for_journal()` block.

## Sample trace

See `aether_nexus/traces/post_market/*/trace.json` field `fact_pack` after live post-market run.
