# Crypto V1 Security Baseline (Supply Chain + Key Safety)
Owner: Lyra (final authority)

## What we defend against
- Malicious dependency / transitive dependency compromise
- Install-time execution (e.g., .pth) style attacks
- Secret exfiltration via env vars, configs, shell history, repo notes
- Prompt injection attempts to trigger asset-moving actions

## Core promise (V1)
We do not claim "no compromise possible".
We claim: compromise does not reach assets.
All asset-moving actions require a local Signing Gate with:
- human confirmation
- action allowlist
- address allowlist
- per-tx USD cap + daily USD cap
- explicit logs

## Non-negotiable Laws
1) No secrets in import world: Python-importable code must not hold long-lived secrets.
2) Router/LLM is mouth, not hands. It cannot sign or withdraw.
3) All asset-moving actions go through Signing Gate (no bypass).
4) Proof over claims: acceptance must produce SECURITY_ACCEPTANCE.md.

## Forbidden in repo (FAIL acceptance if found)
- private keys / seed phrases / mnemonics
- any "BEGIN PRIVATE KEY" blocks
- API keys committed in markdown/scripts
- .env containing real secrets

## Allowed secret storage (V1)
- OS keychain / password manager (manual)
- env vars injected at runtime only (not committed)
- optional data/secrets/ exists but gitignored and placeholder-only by default

## Incident response (client)
If compromise suspected:
1) Freeze withdrawals / disable keys (exchange)
2) Revoke/rotate all API keys
3) Rotate wallet keys (move funds to new wallet if needed)
4) Rebuild environment from scratch
5) Re-run acceptance scripts
