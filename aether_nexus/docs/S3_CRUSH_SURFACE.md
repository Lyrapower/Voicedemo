# S3 — Local crush surface (trigger spec)

## Auto-trigger

When **≥ 30** earnings trades accumulate IV triple-readings (`IV_e`, entry, exit) in `sonnet_earnings` lane.

## Surface

Aggregate by **sector × market_cap_bucket × pre-earnings IV percentile** → mean crush + variance.

## Filter hook (E-line)

After trigger:

```
if expected_crush > bucket_historical_runup_mean → skip (unverified_catalyst path)
```

## Deliverables at trigger

- Crush surface table JSON under `aether-paper/state/crush_surface.json`
- Diff wiring `earnings_integrity.py` / filter pipeline

**Status (2026-07-14):** trigger condition locked; surface not yet populated.
