# E4-B — Dual leaderboard & info_basis

## Dual boards

| Board | Answers | Formula |
|---|---|---|
| **raw** | 实战谁强 | Σ paired-day (Sonnet return − Grid return), verdict window |
| **adjusted** | 同信息谁强 | raw minus Sonnet-only world-knowledge information bucket |

Verdict applies **separately** to each board — see `VERDICT_PROTOCOL.md`.

## adjusted — information bucket (locked)

**Not** runtime delta / data latency. Recompute Sonnet daily return excluding:

```
Sonnet独有 ∩ info_basis=world-knowledge ∩ attribution=information
```

- **Sonnet独有**: symbol has directional signal on Sonnet (`dir≠0`) but not on Grid (`dir≠0`) that day
- **info_basis**: journal field, tagged at append (`tag_info_basis`)
- **attribution**: spot-check field on journal row; must be exactly `information`

Implementation: `premarket_ab_pairing.is_information_bucket_row()` → `daily_returns_for_date(adjusted=True)` → `reconcile_chain` stores `adjusted_return_pct`.

## info_gap_cost — 信息差成本(世界知识优势)

```
info_gap_cost_bps = (raw_Δ − adj_Δ) × 100
```

UI label **must** match: `信息差成本(世界知识优势)` — same meaning as formula (world-knowledge edge removed in adjusted board).

Appended to `docs/TRANSITION_LOG.md` on each post-market run.

## Consensus bucket

Symbols selected by **both** chains — confidence calibration sub-leaderboard (no adjustment).

Implementation: `premarket_ab_scoring.compute_dual_leaderboard()`.
