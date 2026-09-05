#!/usr/bin/env bash
# Paper daily report @ 16:40 — emit aether_paper_daily + crypto A/B.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PAPER="${ROOT}/aether-paper"

export GRID_EVENTS="${GRID_EVENTS:-http://127.0.0.1:8501/store/events}"
export PAPER_DAILY_TIME="${PAPER_DAILY_TIME:-16:40}"

PY="${PY:-${ROOT}/aether_nexus/.venv/bin/python}"
cd "${PAPER}"
exec "${PY}" paper_daily_report_daemon.py "$@"
