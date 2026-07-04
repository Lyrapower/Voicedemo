#!/usr/bin/env bash
set -euo pipefail
echo "Aster deploy — config/aster.toml + local_router.db"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$PROJECT_ROOT/scripts/init_local_router_db.sh" 2>/dev/null || true
echo "Start: $PROJECT_ROOT/scripts/start_aster.sh"
