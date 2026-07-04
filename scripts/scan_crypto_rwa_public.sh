#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec python3 "$ROOT/scripts/scan_crypto_rwa_public.py" "$@"
