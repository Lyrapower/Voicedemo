# Aether Nexus R5.4.x — Filter Diagnostics & Liquidity Fix

See `aether_filter_patch.py` and integration in `aether_dryrun.py`.

## Task 1 — Shipped

- `RejectionLogger` writes `logs/rejections/{date}_{scan_id}.jsonl`
- Telegram digest appends kill counts + near-miss top 10
- **No filter behavior change** (Task 2/3 gated until 3-day review)

## Policy V2 Shadow — Shipped 2026-07-06 (logging-only)

- `PolicyV2Audit` + `policy_v2_shadow()` in `aether_filter_patch.py`
- Theta band ±0.03 and indicative greek soft — **shadow only**, live kills unchanged
- JSONL fields: `policy_v2_flags`, `policy_v2_would_kill`, `policy_v2_rescued`
- Env: `POLICY_V2_SHADOW=true`, `THETA_RATIO_BAND=0.03`
- Activate rules after 3 trading days of shadow review

## Task 2–4 — Queued

Do not activate indicative fallback or percentile caps until Task 1 has run 3 trading days.
