#!/usr/bin/env bash
set -euo pipefail
GS="$(cd "$(dirname "$0")/../grid-sovereign-runtime" && pwd)"
cd "$GS"
export EGRESS_PORT=8502
export EGRESS_UPSTREAM="${EGRESS_UPSTREAM:-https://ark.cn-beijing.volces.com}"
export EGRESS_AUTH_STYLE=bearer
export EGRESS_AUDIT="${EGRESS_AUDIT:-$GS/traces/egress_ark_audit.jsonl}"
: "${ARK_API_KEY:?ARK_API_KEY required in egress process only}"
exec python3 egress.py
