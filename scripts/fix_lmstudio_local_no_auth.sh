#!/usr/bin/env bash
# Turn off mandatory LM Studio Local Server API auth (tokenMode: optional) and restart :1234.
set -euo pipefail
PERMS="$HOME/.lmstudio/.internal/permissions-store.json"
if [[ ! -f "$PERMS" ]]; then
  echo "LM Studio permissions file not found: $PERMS"
  exit 1
fi
cp "$PERMS" "${PERMS}.bak.$(date +%Y%m%d%H%M%S)"
python3 - "$PERMS" <<'PY'
import json, sys
path = sys.argv[1]
data = json.loads(open(path, encoding="utf-8").read())
data.setdefault("json", {})["tokenMode"] = "optional"
open(path, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))
print("Set tokenMode=optional in", path)
PY
if command -v lms >/dev/null 2>&1; then
  lms server stop 2>/dev/null || true
  sleep 1
  lms server start
  echo "LM Studio server restarted on :1234 (no Bearer token required)."
else
  echo "Install lms CLI or restart Local Server from LM Studio Developer tab."
fi
