#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/trippack_api"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -q -r requirements.txt
export TRIPPACK_BACKEND_MODE="${TRIPPACK_BACKEND_MODE:-RELEASE}"
echo "TRIPPACK_BACKEND_MODE=$TRIPPACK_BACKEND_MODE"
echo "TripPackAI backend: http://127.0.0.1:8810"
exec uvicorn app.main:app --host 127.0.0.1 --port 8810
