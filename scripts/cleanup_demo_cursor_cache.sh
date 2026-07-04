#!/usr/bin/env bash
# Remove Cursor archived/demo cache + safe demo junk (does not delete main .venv or source).
#
# HARD RULE: never touch Garden stack:
#   repo/, scripts/garden/, scripts/sound_lab*, LaunchAgents 5173/8787/8788
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CURSOR_APP="${HOME}/Library/Application Support/Cursor"
CURSOR_HOME="${HOME}/.cursor"
WS="${CURSOR_APP}/User/workspaceStorage"

removed=0
note() { echo "[cleanup] $*"; }

rm_rf() {
  if [[ -e "$1" ]]; then
    note "remove $1"
    rm -rf "$1"
    removed=$((removed + 1))
  fi
}

# --- Cursor: stale / archived workspace slots (keep active demo root) ---
KEEP_WS="1511cfa78a70e03e77ab548a0462329b"
if [[ -d "${WS}" ]]; then
  for d in "${WS}"/*/; do
    [[ -d "$d" ]] || continue
    id="$(basename "$d")"
    [[ "$id" == "$KEEP_WS" ]] && continue
    rm_rf "$d"
  done
fi

rm_rf "${CURSOR_HOME}/projects/Users-ciciwang-Desktop-demo-uploads"
rm_rf "${CURSOR_HOME}/projects/var-folders-"*

# Agent session debris (safe to regenerate)
rm_rf "${CURSOR_HOME}/projects/Users-ciciwang-Desktop-demo/agent-tools"
rm_rf "${CURSOR_HOME}/projects/Users-ciciwang-Desktop-demo/terminals"
find "${CURSOR_HOME}/projects/Users-ciciwang-Desktop-demo/agent-transcripts" -type f -name '*.jsonl' -delete 2>/dev/null || true
find "${CURSOR_HOME}/projects/Users-ciciwang-Desktop-demo/agent-transcripts" -type d -empty -delete 2>/dev/null || true

# Cursor logs + browser partition cache
rm_rf "${CURSOR_APP}/logs"
rm_rf "${CURSOR_APP}/Partitions/cursor-browser"
rm_rf "${CURSOR_HOME}/ai-tracking"

# --- Demo repo: caches / accidental installs (gitignored or junk) ---
rm_rf "${ROOT}/.gemhome"
rm_rf "${ROOT}/.mplconfig"
rm_rf "${ROOT}/generated"
find "${ROOT}" \
  -path "${ROOT}/repo" -prune -o \
  -path "${ROOT}/scripts/garden" -prune -o \
  -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "${ROOT}" \
  -path "${ROOT}/repo" -prune -o \
  -path "${ROOT}/scripts/garden" -prune -o \
  -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true

# Optional subproject venvs (regeneratable; main .venv + .venv_ocr_inbox kept)
rm_rf "${ROOT}/travel_package_agent/venv"

note "done (${removed} top-level paths removed)"
