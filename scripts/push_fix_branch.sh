#!/usr/bin/env bash
# One-shot push: reads GITHUB_TOKEN from repo-root .env.gitpush.local (gitignored).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -f "$ROOT/.env.gitpush.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env.gitpush.local"
  set +a
fi
if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "missing GITHUB_TOKEN in .env.gitpush.local" >&2
  exit 1
fi
export GIT_TERMINAL_PROMPT=0
export GIT_ASKPASS="$ROOT/git-askpass-voicedemo.sh"
chmod +x "$GIT_ASKPASS"
git push -u origin fix/alpha-factory-evolution
