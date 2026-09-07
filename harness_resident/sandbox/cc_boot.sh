#!/bin/sh
# Prepare /work and start localhost:11434 -> model.sock. Then exec claude.
set -e
if [ -d /ws/job ]; then
  cp -a /ws/job/. /work/ 2>/dev/null || true
fi
printf '%s\n' '{"hasCompletedOnboarding":true}' > /work/.claude.json
if [ ! -S /bridge/model.sock ]; then
  echo "BLOCKED_SANDBOX_MISSING model.sock" >&2
  exit 78
fi
node /opt/grid/model_relay.js &
n=0
while [ "$n" -lt 50 ]; do
  if node -e "const n=require('net');const s=n.connect(11434,'127.0.0.1');s.on('connect',()=>{s.end();process.exit(0)});s.on('error',()=>process.exit(1))"; then
    break
  fi
  n=$((n+1))
  sleep 0.1
done
cd /work
exec "$@"
