# MEMORY

## Active Constraints
- Local-first behavior only.
- External adapters remain OFF by default.
- Router/Qwen may read only compiled memory artifacts.
- No raw transcript dumping.

## Active Module States
- OpenClaw Senior: PASS
- Trading: PASS
- Crypto: UNKNOWN

## Latest Proof / Acceptance Status
- Top-level acceptance: PASS

## Blockers
- none

## Current Next Actions
- Keep Step 3 acceptance green.
- Keep routing layer external-off and dry-run only.
- Keep compiled memory synced through scripts/compile_memory.sh.

## Locked Rules
- Do not feed raw logs to the router context.
- Do not feed raw chat transcripts to the router context.
- Keep next actions capped at 3 in compiled memory artifacts.
