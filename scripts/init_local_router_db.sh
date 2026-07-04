#!/usr/bin/env bash
# Initialize local_router.db schema per config/aster.toml [state_persistence]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -c "from models.local_router_store import get_local_router_store; get_local_router_store().ensure_schema(); print('local_router.db schema OK')"
