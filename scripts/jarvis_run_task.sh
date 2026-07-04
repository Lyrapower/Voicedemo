#!/usr/bin/env bash
# Jarvis task runner — delegates to app.jarvis.run_task (same registry as platform_main).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec python3 -m app.jarvis.run_task "$@"
