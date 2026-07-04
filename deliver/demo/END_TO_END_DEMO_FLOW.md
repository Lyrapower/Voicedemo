# End-to-End Demo Flow

## Demo Goal

Prove Crypto V1 artifacts, deploy path, and acceptance path without using live external systems.

## Flow

1. Open `deliver/sow/CLIENT_SOW_TEMPLATE.md`.
2. Open `deliver/deploy/DEPLOY_CHECKLIST.md`.
3. Run `bash scripts/deploy_to_client_aws.sh --dry-run`.
4. Open `deliver/deploy/FICTIONAL_CLIENT_WALKTHROUGH.md`.
5. Run `./scripts/accept_crypto_v1.sh`.
6. Review `deliver/proof/crypto/ACCEPTANCE_REPORT.md`.

## Expected Result

- Dry-run deploy prints planned targets only.
- Acceptance report returns `PASS`.
