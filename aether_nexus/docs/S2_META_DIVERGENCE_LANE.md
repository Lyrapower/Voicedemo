# S2 — meta-divergence lane (spec)

**Schedule:** open **2026-07-29** (AB ledger start + 14 calendar days).

**Prerequisite:** E4-B three-bucket `info_basis` data ≥ 10 scorable trading days.

## Lane id

`meta-divergence` — paper only, broker=false.

## Signal states

| State | Definition | Risk premium |
|---|---|---|
| Grid-only | Grid high-conf ∩ Sonnet absent | Structural, low crowding |
| Sonnet-only | Sonnet high-conf ∩ Grid absent | Narrative early, structure unconfirmed |
| Dual-high | Both high-conf | Consensus — options often priced in |

## Weights

Calibrated from first 30d bucket returns after lane open. No auto parameter changes — owner ticket only.

## Deliverables (week 1)

- [ ] Lane registry entry in `aether-paper/paper/store.py`
- [ ] Signal inbox + first-week JSONL under `state/signal_inbox_meta_divergence.jsonl`
