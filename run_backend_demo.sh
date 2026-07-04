#!/usr/bin/env bash
set -euo pipefail
export TRIPPACK_BACKEND_MODE=DEBUG_DEMO
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/run_backend.sh"
