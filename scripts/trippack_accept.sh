#!/usr/bin/env bash
# Legacy name; delegates to scripts/accept_trippack.sh (SQLite, no Docker).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/scripts/accept_trippack.sh"
