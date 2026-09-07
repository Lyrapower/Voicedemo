#!/bin/sh
set -e
if [ -d /ws/job ]; then
  cp -a /ws/job/. /work/ 2>/dev/null || true
fi
printf '%s\n' '{"hasCompletedOnboarding":true}' > /work/.claude.json
cd /work
exec "$@"
