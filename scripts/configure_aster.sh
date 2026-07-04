#!/usr/bin/env bash
# One-shot: aster.toml → local_router.db + LM Studio Aster tab JSON
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/init_local_router_db.sh"
"$ROOT/scripts/deploy_lmstudio_aster.sh"
