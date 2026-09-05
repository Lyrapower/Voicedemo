# WORKSPACE Trading

## Active Constraints
- Core: NVDA, TSLA
- Satellite: PLTR, COIN, CORZ, BE
- Hedge: SQQQ, GLD
- Backups: AMD, MU, XLE
- No setup means PASS.
- Bottleneck ledger: L0 BE/XLE, L1 CORZ, L2 PLTR; trading_permission hook at file end.

## Active Module State
- Trading shell stays deterministic and PASS-first.

## Latest Proof / Acceptance Status
- Trading acceptance: PASS

## Blockers
- none

## Current Next Actions
- Keep weekly cap at 3 including hedges.
- Keep satellite separate from fallback logic.
- Keep output human-readable and deterministic.

## Bottleneck Ledger (Top 3)

- constraint_id: POWER_DC
- constraint_layer: L0
- state: dormant
- confidence: low
- proxies: BE, XLE
- why_inevitable: Scaling AI compute tightens power, grid, and permitting before GPU supply becomes the only binding constraint.
- activation_signals:
  - type_news: no_multi_source_headline_cluster_in_local_ingest
  - type_capex_flow: no_datacenter_power_capex_shift_signal_in_ingest
- last_update_utc: 2026-09-04T05:47:10Z
- notes:
  - Compile defaults only; warming needs cross-type confirmation per transition rules.

- constraint_id: DC_CAPACITY
- constraint_layer: L1
- state: dormant
- confidence: low
- proxies: CORZ
- why_inevitable: Capacity and site timelines for compute real estate lag demand once power and interconnect bind.
- activation_signals:
  - type_news: no_project_delay_attributed_to_power_or_permit_in_ingest
  - type_rs: no_proxy_relative_strength_series_evaluated
- last_update_utc: 2026-09-04T05:47:10Z
- notes:
  - No RS feed in this build; active requires strong signal or RS per rules.

- constraint_id: GOV_AI_INFRA
- constraint_layer: L2
- state: dormant
- confidence: low
- proxies: PLTR
- why_inevitable: Defense and government AI procurement paths gate durable infra spend separate from consumer tech cycles.
- activation_signals:
  - type_policy: no_program_award_or_budget_line_cluster_in_ingest
  - type_flow: no_PLTR_relative_strength_vs_basket_evaluated
- last_update_utc: 2026-09-04T05:47:10Z

- trading_permission: allowed_only_if_active_constraint=yes
