Cursor, deploy V5.2 hardened pack.

Goal:
Local-first Aster/Grid/Jarvis stack with hardened cloud boundary, training gates, and CC CLI containment.

Use these files only:
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
- V5_HARDENED_MANIFEST.md
- referee_selftest.sh
- accept_v5_install.sh
- accept_cc_cli.sh
- CC_CLI_CONTAINMENT.md
- daemon_charter.md
- V5_ACCEPTANCE_AND_DEPLOY.md

V4 was not deployed. Treat V5.2 as the first production runtime. Do not give CC CLI write/exec autonomy until V5.2 acceptance passes.

Run:
```bash
cd /workspace
python3 -m py_compile aether_sentinel_v1.py cloud_boundary.py provenance_registry.py sentinel_ledger_v5.py cc_cli_guard.py aster_fable_bridge_v5.py telegram_aster_fable_bot_v5.py aether_router_v5.py jarvis_backend_runtime_v5.py frontend_multimodal_v5.py
./referee_selftest.sh
./accept_v5_install.sh
```

Verify:
- `aster_fable_bridge_v5.py coach --help` has no `--reviewed`.
- `token = sk-abc12345` routes local_only.
- clean user + secret Qwen draft is blocked before Claude Code.
- Telegram ignores non-private chats.
- `python3 aster_fable_bridge_v5.py selftest` passes without ASTER_ALLOW_FALLBACK_VERIFIER.
- `./accept_cc_cli.sh` passes.
- unsigned CC CLI action blocks.
- signed CC CLI action touching DENY_ALWAYS rejects with `guard_immutable`.
- signed scoped CC CLI action writes ledger before execution.

Report:
One-line verdict, then selftest outputs, then any changed launchd/service commands.
