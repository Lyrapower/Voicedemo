#!/bin/sh
# rebuild grid-cc:2.1.201 from this directory; no secrets.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
docker build -t grid-cc:2.1.201 "$ROOT"
