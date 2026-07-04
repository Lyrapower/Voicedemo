#!/usr/bin/env bash
set -euo pipefail

MODE="dry-run"
if [[ "${1:-}" == "--live" ]]; then
  echo "LIVE_DEPLOY_BLOCKED: external deployment is disabled in this step."
  exit 1
fi

echo "DEPLOY_MODE=$MODE"
echo "TARGET=fictional-client-aws"
echo "ACTION=plan only"
echo "RESULT=no external calls executed"
