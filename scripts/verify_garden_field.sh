#!/usr/bin/env bash
# Garden field — runtime verification (must pass before claiming the page works).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/scripts/sound_lab_fallback.py"
FAIL=0

die() { echo "FAIL: $*"; FAIL=1; }
ok() { echo "OK: $*"; }

python3 -m py_compile "$PY" || die "python syntax"
ok "python compile"

HTML="$(python3 <<'PY'
import re
text=open("/Users/ciciwang/Desktop/demo/scripts/sound_lab_fallback.py").read()
print(text)
PY
)"
JS="$(python3 <<'PY'
import re
text=open("/Users/ciciwang/Desktop/demo/scripts/sound_lab_fallback.py").read()
print(re.search(r'<script type="module">\n(.*)\n  </script>', text, re.S).group(1))
PY
)"
TMP="$(mktemp /tmp/garden.XXXXXX.js)"
printf '%s' "$JS" > "$TMP"
node --check "$TMP" || die "javascript syntax (node --check)"
ok "javascript syntax"

echo "$JS" | grep -q 'const mx = mouseX' || die "missing camera mx"
MX_COUNT="$(echo "$JS" | grep -c 'const mx = mouseX' || true)"
[[ "$MX_COUNT" -eq 1 ]] || die "duplicate const mx ($MX_COUNT)"
ok "single mx declaration"

for needle in startMic applyPresenceUi pushVoice createSoftSpriteTexture animateLayer; do
  echo "$JS" | grep -q "$needle" || die "missing JS: $needle"
done
for needle in 'id="micBtn"' 'id="speakBtn"' 'id="saveMemory"'; do
  echo "$HTML" | grep -q "$needle" || die "missing HTML: $needle"
done
ok "mic/presence/render hooks present"

HTML5173="$(curl -sf http://127.0.0.1:5173/)" || die "5173 unreachable"
HTML8787="$(curl -sf http://127.0.0.1:8787/)" || die "8787 unreachable"
echo "$HTML5173" | grep -q 'ROLLBACK v3.4' || die "5173 missing ROLLBACK watermark"
echo "$HTML8787" | grep -q 'ROLLBACK v3.4' || die "8787 missing ROLLBACK watermark"
ok "ROLLBACK v3.4 on 5173 + 8787"

curl -sf http://127.0.0.1:8787/api/telemetry >/dev/null || die "8787 telemetry"
curl -sf -X POST http://127.0.0.1:8787/api/presence -H 'Content-Type: application/json' -d '{"enabled":true}' >/dev/null || die "8787 presence POST"
ok "8787 API telemetry + presence"

rm -f "$TMP"
if [[ "$FAIL" -ne 0 ]]; then exit 1; fi
echo ""
echo "ALL RUNTIME CHECKS PASSED"
echo "Browser still required: HUD fps must tick, MIC/Presence click test."
