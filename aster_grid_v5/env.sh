# Source before any V5.2 runtime command:
#   source ~/Projects/demo/aster_grid_v5/env.sh
export ASTER_GRID_V5_ROOT="${ASTER_GRID_V5_ROOT:-$HOME/Projects/demo/aster_grid_v5}"
export PATH="$HOME/Projects/demo/aster_grid_v5/.tools/node_modules/.bin:$HOME/.local/bin:$PATH"
export CLAUDE_BIN="${CLAUDE_BIN:-$HOME/Projects/demo/aster_grid_v5/.tools/node_modules/.bin/claude}"

# CC CLI execution frozen — coach/referee only via aster_fable_bridge_v5.py + sentinel_ledger_v5 referee.
# cc_cli_guard.py is installed as future containment; never pass --execute in production.
export CC_CLI_EXECUTION_FROZEN=1
export CC_CLI_GUARD_ENABLED=0

# Field Pack / distill (CC CLI Fable coach — no :8503)
export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
export QWEN_ENDPOINT="${QWEN_ENDPOINT:-http://127.0.0.1:8501/v1/chat/completions}"
export QWEN_MODEL="${QWEN_MODEL:-demo/aster}"
export TEACHER_MODEL="${TEACHER_MODEL:-claude-fable-5}"
export ARK_BASE="${ARK_BASE:-http://127.0.0.1:8502/api/v3}"
