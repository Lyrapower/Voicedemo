#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)/aether_nexus"
cd "$ROOT"
# shellcheck source=ensure_venv.sh
source "$(dirname "$0")/ensure_venv.sh"
ensure_venv "$ROOT"
# shellcheck source=export_ssl_certs.sh
source "$(dirname "$0")/export_ssl_certs.sh"
export_ssl_certs "${ROOT}/.venv/bin/python"
exec "${ROOT}/.venv/bin/python" aether_dryrun.py
