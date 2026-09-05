#!/usr/bin/env bash
# Weekly off-pool A/B report (Sonnet 4.6 vs Opus 4.8).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
exec "${PY}" "${ROOT}/aether_nexus/offpool_ab_weekly.py" "$@"
