# Aster / Grid V5 Hardened Manifest

Status: deployable V5.2 hardening pack for Cursor.

Based on:
- V3 Fable review
- V4 cross-review
- V4 Hardening Instructions

Closed findings:
- F1: component-level cloud boundary scan before Claude Code CLI
- F2: structural provenance registry with full-hash and 5-gram shingle overlap
- F4: second-pass review; no `--reviewed` launch flag
- F5: verifier fallback fail-closed unless explicitly degraded
- F8: Telegram private-only and no path dump
- F9: CC CLI containment with signature, ledger, scope, and immutable guard gates

Included:
- aether_sentinel_v1.py
- cloud_boundary.py
- provenance_registry.py
- sentinel_ledger_v5.py
- cc_cli_guard.py
- aster_fable_bridge_v5.py
- telegram_aster_fable_bot_v5.py
- aether_router_v5.py
- jarvis_backend_runtime_v5.py
- frontend_multimodal_v5.py
- ASTER_GRID_V5_DEPLOY.md
- CURSOR_DEPLOY_V5.md
- referee_selftest.sh
- accept_v5_install.sh
- accept_cc_cli.sh
- CC_CLI_CONTAINMENT.md
- daemon_charter.md
- V5_ACCEPTANCE_AND_DEPLOY.md

Non-goals:
- no DeepSeek runtime
- no direct Anthropic API
- no training export without second-pass approval
- no cloud node receives RED payload components

Acceptance already run locally:
- py_compile all V5 files
- cloud_boundary selftest
- provenance_registry selftest
- sentinel_ledger_v5 selftest
- cc_cli_guard selftest
- aster_fable_bridge_v5 selftest
- telegram_aster_fable_bot_v5 selftest
- aether_router_v5 selftest
- jarvis_backend_runtime_v5 selftest
- frontend_multimodal_v5 selftest
- clean user + secret Qwen draft blocked before Claude Code
- bridge selftest passes undegraded with aether_sentinel_v1 present
- stop_conditions table exists and is empty
- CC CLI unsigned actions block
- CC CLI ledger failure blocks
- CC CLI DENY_ALWAYS paths reject with guard_immutable
- CC CLI allowed scoped write can pass only after signature and ledger
