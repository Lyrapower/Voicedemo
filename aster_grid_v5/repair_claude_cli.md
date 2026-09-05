#!/usr/bin/env bash
# Claude Code CLI stuck in UE state — cannot be killed; reboot clears kernel wait.
set -euo pipefail
echo "Stuck claude PIDs (UE = needs reboot):"
ps aux | awk '$8 ~ /UE/ && /claude/ {print $2, $8, $11, $12, $13}'
echo ""
echo "After reboot, run:"
echo "  source ~/Projects/demo/aster_grid_v5/env.sh"
echo "  ~/Projects/demo/aster_grid_v5/check_claude_link.sh"
echo ""
echo "V5 wiring is ready at ~/Projects/demo/aster_grid_v5/env.sh"
echo "  CLAUDE_BIN=$HOME/.local/bin/claude"
echo "  PATH includes ~/.local/bin"
