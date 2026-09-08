#!/bin/sh
# rebuild grid-cc:2.1.201 from this directory; no secrets.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
docker build -t grid-cc:2.1.201-py3 "$ROOT"
docker image inspect grid-cc:2.1.201-py3 --format '{{.Id}}'
docker run --rm --entrypoint python3 grid-cc:2.1.201-py3 --version
