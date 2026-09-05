#!/usr/bin/env bash
# Sync Tree of Life artifacts → ~/2td/tree-of-life (separate from grid-stack-backup).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/tree-of-life/output"
DEST_ROOT="${BACKUP_2TD_ROOT:-$HOME/2td}/tree-of-life"
STAMP="$(date +%Y-%m-%dT%H%M%S)"
DEST="${DEST_ROOT}/${STAMP}"

python3 "${ROOT}/tree-of-life/generate.py" >/dev/null
mkdir -p "${DEST}"
rsync -a "${SRC}/" "${DEST}/"
cp -p "${ROOT}/tree-of-life/generate.py" "${ROOT}/tree-of-life/sync_to_2td.sh" "${ROOT}/tree-of-life/README.md" "${DEST}/_generator/" 2>/dev/null || {
  mkdir -p "${DEST}/_generator"
  cp -p "${ROOT}/tree-of-life/generate.py" "${ROOT}/tree-of-life/sync_to_2td.sh" "${ROOT}/tree-of-life/README.md" "${DEST}/_generator/"
}
ln -sfn "${STAMP}" "${DEST_ROOT}/latest"
echo "tree-of-life → ${DEST}"
du -sh "${DEST}" "${DEST_ROOT}/latest"
