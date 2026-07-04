# Deploy Checklist

## Preconditions

- Keep `external_enabled: false` unless explicitly enabled later.
- Confirm `data/execution/KILL_EXTERNAL` is absent before any future real external run.
- Keep deploy script in `dry_run` mode for this step.

## Steps

1. Review client SOW.
2. Run `bash scripts/deploy_to_client_aws.sh --dry-run`.
3. Review fictional client walkthrough.
4. Review demo flow.
5. Run `./scripts/accept_crypto_v1.sh`.

## Evidence

- `deliver/proof/crypto/ACCEPTANCE_REPORT.md`
