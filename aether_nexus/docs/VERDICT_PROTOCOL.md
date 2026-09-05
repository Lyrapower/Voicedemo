# Verdict Protocol — Premarket A/B (E4-B + S1)

**Lock date:** metrics below are frozen before first scorable data on **2026-07-15**. No post-hoc redefinition.

## 1. Win-rate denominator (directional only)

| Rule | Detail |
|---|---|
| **Included** | Journal rows with `dir ≠ 0` (long/short directional signals) |
| **Excluded** | 观察 (`dir=0`), skip, flat — never enter wins/losses denominator |
| **Per-chain** | Grid and Sonnet win rates computed independently |
| **Display** | `rolling_win_rate` is **display-only**; does not drive verdict |

Code: `premarket_ab_pairing.is_directional_row()`, `premarket_ab_journal.reconcile_chain()`.

## 2. Verdict window vs rolling display

| Metric | Window | Authority |
|---|---|---|
| **Verdict** (bootstrap CI, dual leaderboard for S1) | Fixed **30 trading days** on or after **2026-07-15**, void-symmetric paired dates | **Authoritative** |
| **Rolling** (`grid_return_30d_pct`, `30d胜率` in UI) | Same paired void-symmetric dates, trailing ≤30 days | **Display only** |

Verdict bootstrap resamples **paired day difference** sequence `(sonnet_return − grid_return)` — not unpaired chain series.

Protocol id: `bootstrap_10000_ci90_paired_void_symmetric`.

## 3. Void symmetry (paired scorable set)

| Rule | Detail |
|---|---|
| Trigger | Either chain marks day `ab_void` or `context_asymmetric`, or warmup |
| Effect | Day **removed from both chains'** scorable set |
| Identity | `grid_n == sonnet_n == len(paired_scorable_dates)` — enforced by `assert_paired_symmetry()` |
| Bootstrap | Only paired dates with both returns present |

Code: `premarket_ab_pairing.is_either_side_void()`, `paired_scorable_dates()`, `paired_daily_diffs()`.

## 4. Verdict states

| Verdict | Condition |
|---|---|
| `INCONCLUSIVE` | CI90 crosses zero, or `< 2` paired scorable days |
| `SONNET` | mean diff > 0 and CI90 entirely > 0 |
| `GRID` | mean diff < 0 and CI90 entirely < 0 |

`inconclusive_triggers_extension`: true — evaluation period extends until conclusive or manual review.

## 5. adjusted board (verdict lane)

Same void/pairing rules as raw. Sonnet return recomputed excluding information bucket (see `E4-B_SCORING.md`).

## References

- `aether_nexus/premarket_ab_pairing.py` — pairing, void, bucket
- `aether_nexus/premarket_verdict_bootstrap.py` — bootstrap CI
- `aether_nexus/premarket_ab_scoring.py` — dual leaderboard
- `aether_nexus/premarket_ab_returns.py` — rolling display helpers
