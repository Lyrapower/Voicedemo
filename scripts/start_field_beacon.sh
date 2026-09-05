#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export FIELD_DIR="${FIELD_DIR:-$ROOT/data/grid_field}"
export BEACON_INTERVAL="${BEACON_INTERVAL:-60}"
exec /usr/bin/python3 "$ROOT/scripts/field_beacon_writer.py"
