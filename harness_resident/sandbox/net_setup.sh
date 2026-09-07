#!/bin/sh
# grid-cc-net (internal) + grid-cc-fwd. No host port bind. Idempotent.
set -e
HR="$(cd "$(dirname "$0")/.." && pwd)"
DEMO="$(cd "$HR/.." && pwd)"
STATE="$HR/state"
DENIED="$STATE/egress_denied.jsonl"
mkdir -p "$STATE"
touch "$DENIED"
docker network inspect grid-cc-net >/dev/null 2>&1 || docker network create --internal grid-cc-net
docker build -t grid-cc-fwd:local "$HR/sandbox/forwarder"
docker rm -f grid-cc-fwd >/dev/null 2>&1 || true
docker run -d --name grid-cc-fwd --restart always \
  --network grid-cc-net \
  --add-host=host.docker.internal:host-gateway \
  -v "$DEMO/EGRESS.md:/etc/egress/EGRESS.md:ro" \
  -v "$DENIED:/var/log/egress_denied.jsonl" \
  grid-cc-fwd:local
docker network connect bridge grid-cc-fwd >/dev/null 2>&1 || true
echo "grid-cc-fwd up (no host ports)"
