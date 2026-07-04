# WORKSPACE Infra

## Active Constraints
- external_enabled remains false by default.
- KILL_EXTERNAL blocks all external calls.
- Only knowledge/compiled/*.md feeds the local router context.

## Active Module State
- Jarvis routing layer stays local-first with compiled-memory-only read path.

## Latest Proof / Acceptance Status
- Top-level proof: PASS

## Blockers
- missing: knowledge/source/ASTER.md

## Current Next Actions
- Compile memory on start.
- Block external adapters when disabled or kill-switched.
- Keep raw chat and raw logs out of router context.
