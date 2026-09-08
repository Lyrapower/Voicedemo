#!/bin/sh
# Prepare /work, start model+egress relays, run claude, then supervisor in-job diag.
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
if [ -S /bridge/egress.sock ]; then
  MODEL_SOCK=/bridge/egress.sock MODEL_RELAY_PORT=3128 node /opt/grid/model_relay.js &
fi
if [ -S /bridge/dev.sock ]; then
  MODEL_SOCK=/bridge/dev.sock MODEL_RELAY_PORT=3129 node /opt/grid/model_relay.js &
  export HTTPS_PROXY=http://127.0.0.1:3129
  export HTTP_PROXY=http://127.0.0.1:3129
  export NO_PROXY=127.0.0.1,localhost
fi
n=0
while [ "$n" -lt 50 ]; do
  if node -e "const n=require('net');const s=n.connect(11434,'127.0.0.1');s.on('connect',()=>{s.end();process.exit(0)});s.on('error',()=>process.exit(1))"; then
    break
  fi
  n=$((n+1))
  sleep 0.1
done
cd /work
set +e
"$@"
cc_rc=$?
set -e
if [ -f /opt/grid/in_job_diag.py ]; then
  python3 /opt/grid/in_job_diag.py || true
fi
exit "$cc_rc"
