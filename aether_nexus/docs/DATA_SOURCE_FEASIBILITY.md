# Indicative → Real-Time Trade Data — Feasibility Assessment

**Date:** 2026-07-06  
**Context:** Pool scan greek/spread kills on `alpaca_indicative` are largely data-quality
artifacts. Hard greek gates must sit on **trade-derived** quotes, not indicative snapshots.

## Current state (R5.4.1)

| Layer | Setting | Source |
|-------|---------|--------|
| Equities | `ALPACA_DATA_FEED=iex` | Alpaca free IEX trades/bars |
| Options | `ALPACA_OPTION_FEED=indicative` | Alpaca indicative snapshots |
| OI | missing in free snapshot | `oi_source=missing_in_snapshot` |
| Greeks | bundled in indicative snap | not OPRA-consolidated |

Observed on 2026-07-06 pool scan (15 symbols): **spread kill #3**, all rejects on
`quote_source=indicative`. Policy V2 shadow (indicative greek soft + theta band) would
**rescue ~40–60%** of hard kills without changing live rules yet.

## Option A — Alpaca OPRA feed (`ALPACA_OPTION_FEED=opra`)

| Item | Assessment |
|------|------------|
| **What you get** | Consolidated NBBO-style option quotes, tighter spreads, OI in snapshots (paid tier) |
| **Greeks** | Still model-derived from quote; better bid/ask → more stable delta/iv |
| **Cost** | Alpaca **Algo Trader Plus** or equivalent options data subscription (check current pricing) |
| **Switch** | `.env`: `ALPACA_OPTION_FEED=opra` — no code change |
| **Verdict** | **Recommended first step** if budget allows; lowest integration cost |

**Hard-greek readiness:** OPRA + real bid/ask → spread filter meaningful; iv/delta still
indicative-model but **much** closer to tradable. Mark greek hard gates `realtime` only
when `feed=opra` and `quote_stale=false`.

## Option B — Alpaca latest trade / quote endpoints (equity + per-contract)

| Item | Assessment |
|------|------------|
| **What you get** | Last trade price for underlying; option **trades** stream on paid plans |
| **Greeks** | Must compute locally (already have `bs_greeks`) from trade-implied vol |
| **Cost** | Same paid tier; more API calls per scan |
| **Verdict** | Good **sanity cross-check**; heavy for full pool scan (15× chains) |

## Option C — CBOE LiveVol / direct exchange

| Item | Assessment |
|------|------------|
| **What you get** | Exchange-grade options tape, institutional OI |
| **Greeks** | Vendor or self-compute |
| **Cost** | $$$$; legal/compliance review |
| **Verdict** | **Overkill for dry-run**; revisit if live execution on IB with CBOE entitlement |

## Option D — IB Gateway (already in stack for live path)

| Item | Assessment |
|------|------------|
| **What you get** | Real-time if market data subs active (Error 10089 without subs) |
| **Dry-run** | Currently Alpaca-first; IB export exists but scan uses Alpaca |
| **Verdict** | **Best for live** once subs enabled; keep Alpaca for unattended dry-run until OPRA |

## Recommendation (phased)

1. **Now (logging-first):** Policy V2 shadow on indicative — record kills vs rescued; **3 trading days** before activating soft rules.
2. **Week 1:** Trial `ALPACA_OPTION_FEED=opra` on **pool only**; compare spread kill rate + JSONL `quote_source=realtime`.
3. **Gate rule:** Enable **hard** delta/iv/gamma/theta only when `quote_source != indicative` AND `quote_stale=false`.
4. **Do not** build greek hard gates on indicative long-term — use vol/OI fallback (Task 2) until OPRA live.

## Acceptance checklist (when upgrading feed)

- [ ] `spread` kill count drops >50% vs indicative baseline (same rally day replay)
- [ ] `quote_stale` <5% of contracts in pool scan
- [ ] Theta unit sanity ratio ≈1.0 (already passing on indicative)
- [ ] JSONL shows `quote_source=realtime` for >90% of scored candidates
