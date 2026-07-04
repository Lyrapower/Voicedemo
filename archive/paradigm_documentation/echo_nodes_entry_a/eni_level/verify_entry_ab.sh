#!/usr/bin/env bash
# Verify Entry A (8500) and Entry B (8787) are fully separated in config + LM Studio.
set -euo pipefail
ENI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ENI_ROOT/setup/verify_entry_ab.py"
