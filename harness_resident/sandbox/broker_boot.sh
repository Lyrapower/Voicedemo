#!/bin/sh
set -e
if [ "${DEV_FAKE_UPSTREAM:-}" = "1" ]; then
  echo "BLOCKED_TEST_OVERRIDE DEV_FAKE_UPSTREAM" >&2
  exit 78
fi
python3 /opt/grid/model_broker.py --sock /bridge/model.sock --upstream host.docker.internal:11434 --model "${BOUND_MODEL:-}" --token "${BROKER_JOB_TOKEN:-}" &
python3 /opt/grid/egress_broker.py &
if [ "${DEV_ENABLED:-}" = "1" ]; then
  python3 /opt/grid/dev_broker.py &
fi
wait
