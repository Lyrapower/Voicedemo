#!/usr/bin/env bash
# 8790 FIELD chat UI/backend acceptance
set -euo pipefail
fail=0
pass() { echo "  PASS  $*"; }
bad() { echo "  FAIL  $*"; fail=1; }

echo "=== 8790 FIELD chat ==="
health="$(curl -sf --max-time 8 http://127.0.0.1:8790/health 2>/dev/null || echo '{}')"
echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" && pass "/health" || bad "/health"

html="$(curl -sf --max-time 8 http://127.0.0.1:8790/ 2>/dev/null || true)"
if [[ "$html" == *'id="ask-send"'* ]]; then
  pass "UI send button present"
else
  bad "UI missing #ask-send (rebuild dist or patch index.html)"
fi

chat_out="$(curl -sf --max-time 90 -N -X POST http://127.0.0.1:8790/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"只回复:收到"}' 2>&1)" || chat_out=""

verdict="$(CHAT_OUT="$chat_out" python3 - <<'PY'
import json, os, sys
text = os.environ.get("CHAT_OUT", "")
done = None
for line in text.splitlines():
    if not line.startswith("data:"):
        continue
    try:
        d = json.loads(line[5:].strip())
    except Exception:
        continue
    if d.get("done"):
        done = d
        break
if not done:
    print("FAIL|no done event")
    sys.exit(0)
t = (done.get("text") or "").strip()
s = done.get("served_by") or ""
if not t:
    print(f"FAIL|empty text served_by={s}")
elif not str(s).startswith("gateway-"):
    print(f"FAIL|bad served_by={s}")
else:
    print(f"PASS|text={t[:40]!r}")
PY
)"
case "${verdict%%|*}" in
  PASS) pass "/chat ${verdict#*|}" ;;
  *) bad "/chat ${verdict#*|}" ;;
esac

if command -v python3 >/dev/null 2>&1 && python3 -c "import playwright" 2>/dev/null; then
  if FIELD8790_URL=http://127.0.0.1:8790/ python3 - <<'PY'
import asyncio, os, sys
from playwright.async_api import async_playwright

URL = os.environ.get("FIELD8790_URL", "http://127.0.0.1:8790/")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width":390,"height":844}, is_mobile=True, has_touch=True)
        page = await ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=20000)
        await page.fill("#ask", "只回复:收到")
        await page.tap("#ask-send")
        await page.wait_for_timeout(22000)
        reply = await page.inner_text("#reply")
        await browser.close()
    if errs:
        print("FAIL|js:" + errs[0][:80])
        sys.exit(1)
    if "收到" in reply and "⏸" not in reply:
        print("PASS|mobile send btn")
    else:
        print(f"FAIL|reply={reply[:60]!r}")
        sys.exit(1)

asyncio.run(main())
PY
  then
    pass "mobile send button chat"
  else
    bad "mobile send button chat"
  fi
else
  echo "  SKIP  playwright not installed"
fi

echo ""
[[ "$fail" -eq 0 ]] && echo "8790 CHAT PASS" && exit 0
echo "8790 CHAT FAIL"
exit 1
