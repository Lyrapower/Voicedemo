# Fictional Client Walkthrough

Client: `NorthBridge Digital Treasury`

## Goal

Show how Crypto V1 would be handed off without activating external services.

## Walkthrough

1. Share `deliver/sow/CLIENT_SOW_TEMPLATE.md`.
2. Review `deliver/deploy/DEPLOY_CHECKLIST.md`.
3. Run `bash scripts/deploy_to_client_aws.sh --dry-run`.
4. Show the planned target names and disabled external posture.
5. Run `./scripts/accept_crypto_v1.sh`.
6. Deliver `deliver/proof/crypto/ACCEPTANCE_REPORT.md`.

## Client-Safe Notes

- No live external API calls occur in this step.
- No client credentials are required.
- No autonomous execution is enabled.
