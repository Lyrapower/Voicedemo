# Aster / Grid / Jarvis V5.2 Hardened Pack

Purpose: deploy the hardened local-first runtime after V3/V4 audit, Fable acceptance, and CC CLI containment review.

Closed findings:
- F1: cloud boundary scans every outbound component before Claude Code CLI
- F2: provenance registry blocks laundered external text
- F4: review is second-pass approval, not a launch flag
- F5: verifier fallback fails closed
- F8: Telegram is private-only and does not dump paths
- F9: CC CLI is frozen until signed, ledgered, scoped, and clear of DENY_ALWAYS paths

Files:
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
- referee_selftest.sh
- accept_v5_install.sh
- accept_cc_cli.sh
- CC_CLI_CONTAINMENT.md
- daemon_charter.md
- V5_ACCEPTANCE_AND_DEPLOY.md
- V5_HARDENED_MANIFEST.md
- CURSOR_DEPLOY_V5.md

Deploy:

```bash
cd /workspace
python3 -m py_compile aether_sentinel_v1.py cloud_boundary.py provenance_registry.py sentinel_ledger_v5.py cc_cli_guard.py aster_fable_bridge_v5.py telegram_aster_fable_bot_v5.py aether_router_v5.py jarvis_backend_runtime_v5.py frontend_multimodal_v5.py
./referee_selftest.sh
./accept_v5_install.sh
```

Claude Code check:

```bash
which claude
python3 sentinel_ledger_v5.py referee --role fable "回答一个词:在岗"
python3 sentinel_ledger_v5.py referee --role opus48 "回答一个词:在岗"
```

Bridge usage:

```bash
python3 aster_fable_bridge_v5.py coach --text "把这个需求编译成执行边界，只输出 JSON"
python3 aster_fable_bridge_v5.py review list
python3 aster_fable_bridge_v5.py review show <run_id>
python3 aster_fable_bridge_v5.py review approve <run_id>
python3 aster_fable_bridge_v5.py review reject <run_id> --reason "not clean enough"
```

Telegram:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_ALLOWED_USER_IDS="123456"
python3 telegram_aster_fable_bot_v5.py poll
```

Acceptance:
- `python3 aster_fable_bridge_v5.py selftest` passes without `ASTER_ALLOW_FALLBACK_VERIFIER`
- secret in user text blocks before Qwen/Fable
- secret in Qwen draft blocks before Claude Code
- `auth token budget` is allowed
- `token = sk-abc12345` is blocked
- copied registered external text fails provenance
- no `--reviewed` flag exists on `coach`
- approval happens only through `review approve`
- `stop_conditions` table exists and is empty
- Telegram ignores non-private chats
- `./accept_cc_cli.sh` passes
- unsigned CC CLI action blocks
- ledger failure blocks and records stop condition
- DENY_ALWAYS path rejects with `guard_immutable`
- allowed scoped CC CLI action requires signature before ledger before execution
