#!/usr/bin/env bash
# Rollback deploy check only — confirms ROLLBACK v3.4 HTML is on wire.
set -euo pipefail
HTML="$(curl -sf http://127.0.0.1:5173/)" || { echo "5173 unreachable"; exit 1; }
HTML8787="$(curl -sf http://127.0.0.1:8787/)" || { echo "8787 unreachable"; exit 1; }
grep -q 'ROLLBACK v3.4 · soft round · 165000' <<<"$HTML" || { echo "missing rollback watermark on 5173"; exit 1; }
grep -q 'createSoftSpriteTexture' <<<"$HTML" || { echo "missing v3.4 PointsMaterial on 5173"; exit 1; }
grep -q 'makeLayer(42000' <<<"$HTML" || { echo "missing 165k layers on 5173"; exit 1; }
grep -q 'id="micBtn"' <<<"$HTML" || { echo "missing micBtn"; exit 1; }
grep -q 'applyPresenceUi' <<<"$HTML" || { echo "missing presence UI"; exit 1; }
grep -q 'ROLLBACK v3.4 · soft round · 165000' <<<"$HTML8787" || { echo "missing rollback watermark on 8787"; exit 1; }
echo "ROLLBACK v3.4 deployed on 5173 + 8787 (HTML only — not a visual test)"
