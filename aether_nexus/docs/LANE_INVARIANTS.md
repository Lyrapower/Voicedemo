# Lane Invariants (ONEPACK D)

## Rule

**`lane = owner × asset_class`** — any aggregate row must declare `aggregation_scope`.

## Physical storage

| Lane | Owner | Asset class | Account file |
|------|-------|-------------|--------------|
| `equity` | grid | equity_underlying | `aether-paper/state/account.json` |
| `crypto_rules` | grid | crypto_spot | `aether-paper/state/account_crypto_rules.json` |
| `crypto_cli` | sonnet | crypto_spot | `aether-paper/state/account_crypto_cli.json` |
| `sonnet_earnings` | sonnet | equity_options | `aether-paper/state/account_sonnet_earnings.json` |

## Invariants

1. Ledgers are physically separate JSON/JSONL files — never merge accounts.
2. Premarket A/B (`premarket_grid` / `premarket_sonnet`) are report-only — never merge 30d stats.
3. `sonnet_earnings` never merges with premarket A/B or equity scan path.
4. UI TRADING tab renders equity + premarket only; CRYPTO tab renders crypto lanes only.
5. Paper daily summary must label each row with `owner` and `asset_class`.
6. New lanes must register in `LANE_REGISTRY` before first write.

## Dump

```bash
cd /Users/ciciwang/Projects/demo/aether-paper
python3 -c "from paper.store import dump_lane_registry; import json; print(json.dumps(dump_lane_registry(), indent=2, ensure_ascii=False))"
```
