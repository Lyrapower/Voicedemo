#!/usr/bin/env bash
# Rebuild React /app bundle into docker volume webdist (required after frontend edits).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
docker compose up web --force-recreate
echo "OK — open http://localhost:8600/app#/field (hard refresh if cached)"
echo "nav should show: ui 2026-07-24f"
