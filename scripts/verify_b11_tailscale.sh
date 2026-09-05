#!/usr/bin/env bash
# b11 workbench via Tailscale — read-only acceptance (no store writes).
# Chat smoke is OPT-IN only: B11_CHAT_SMOKE=1 (writes to workbench-b11 — RED LINE for agents).
set -euo pipefail
HOST="${B11_TS_HOST:-cicimacbook-air.tail76db5b.ts.net}"
BASE="https://${HOST}/workbench"
URL="${BASE}/grid_workbench_b11.html"
fail=0

note() { echo "$*"; }
pass() { echo "  PASS  $*"; }
bad() { echo "  FAIL  $*"; fail=1; }

echo "=== b11 Tailscale acceptance (${HOST}) ==="

if curl -sf "${BASE}/health" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('ok') else 1)" 2>/dev/null; then
  pass "${BASE}/health"
else
  bad "${BASE}/health"
fi

if curl -sf "${BASE}/field_now/now.json" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if 'garden' in d else 1)" 2>/dev/null; then
  pass "${BASE}/field_now/now.json"
else
  bad "${BASE}/field_now/now.json (8515 proxy → 8795)"
fi

cc="$(curl -sI "${URL}" 2>/dev/null | awk 'tolower($0) ~ /^cache-control:/ {print $0; exit}')"
if [[ "$cc" == *"no-store"* ]]; then
  pass "b11 Cache-Control no-store"
else
  bad "b11 missing no-store (${cc:-none})"
fi

html="$(curl -sf "${URL}" 2>/dev/null || true)"
if [[ -n "$html" ]]; then
  ver="$(printf '%s' "$html" | rg -o 'PAGE_VER="[^"]+"' | head -1 || true)"
  if [[ -n "$ver" ]]; then
    pass "b11 ${ver} served"
  else
    bad "b11 missing PAGE_VER"
  fi
  if printf '%s' "$html" | rg -q 'runCcTask'; then
    pass "b11 CC CLI tab wired"
  else
    bad "b11 missing runCcTask (CC tab)"
  fi
  if printf '%s' "$html" | rg -q 'Cloud 旁路' && \
     printf '%s' "$html" | rg -q 'cloud/memory' && \
     printf '%s' "$html" | rg -q 'cloudMemHud' && \
     printf '%s' "$html" | rg -q 'sendCloud' && \
     printf '%s' "$html" | rg -q 'cloudBillHud'; then
    pass "b11 Cloud tab synced (8515 memory layer · billing · no 8501 store)"
  else
    bad "b11 missing Cloud tab (8515 isolated lane)"
  fi
  if printf '%s' "$html" | rg -q 'GLM 5\.2 · Ollama' && \
     printf '%s' "$html" | rg -q 'glm-5\.2:cloud' && \
     printf '%s' "$html" | rg -q 'VL 旁路:K2\.5'; then
    pass "b11 CC GLM52 + VL note synced"
  else
    bad "b11 missing GLM52 CC CLI copy (glm52-base-swap v2)"
  fi
else
  bad "b11 html fetch failed"
fi

final="$(curl -sfL -o /dev/null -w '%{url_effective}' "${BASE}/")"
if [[ "$final" == "${URL}" ]]; then
  pass "redirect ${BASE}/ → b11"
else
  bad "redirect got ${final} want ${URL}"
fi

cors="$(curl -sI -X OPTIONS "https://${HOST}/v1/chat/completions" \
  -H "Origin: https://${HOST}" \
  -H "Access-Control-Request-Method: POST" 2>/dev/null | awk 'tolower($0) ~ /^access-control-allow-origin:/ {print $2; exit}' | tr -d '\r')"
if [[ "$cors" == "https://${HOST}" ]]; then
  pass "CORS origin https://${HOST}"
else
  bad "CORS origin (${cors:-missing})"
fi

if command -v python3 >/dev/null 2>&1 && python3 -c "import playwright" 2>/dev/null; then
  B11_TS_URL="$URL" B11_TS_HOST="$HOST" python3 <<'PY'
import asyncio, os, sys
from playwright.async_api import async_playwright

URL = os.environ["B11_TS_URL"]
HOST = os.environ["B11_TS_HOST"]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        )
        page = await ctx.new_page()
        errs = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        gw = await page.input_value("#cGw")
        if gw != f"https://{HOST}":
            print(f"  FAIL  gw={gw!r}")
            await browser.close()
            sys.exit(1)
        cc_tab = await page.query_selector("#tabCC")
        cc_run = await page.query_selector("#ccRun")
        if not cc_tab or not cc_run:
            print("  FAIL  CC CLI tab controls missing")
            await browser.close()
            sys.exit(1)
        await browser.close()
    print("  PASS  iPhone UA read-only (gw + CC tab, no send)")

asyncio.run(main())
PY
else
  note "  SKIP  playwright not installed (optional: pip install playwright && playwright install chromium)"
fi

if [[ "${B11_CHAT_SMOKE:-}" == "1" ]]; then
  note "  WARN  B11_CHAT_SMOKE=1 — will WRITE to workbench-b11 store (user opt-in only)"
  if command -v python3 >/dev/null 2>&1 && python3 -c "import playwright" 2>/dev/null; then
    B11_TS_URL="$URL" B11_TS_HOST="$HOST" python3 <<'PY'
import asyncio, os, sys
from playwright.async_api import async_playwright

URL = os.environ["B11_TS_URL"]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 390, "height": 844})
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        await page.fill("#box", "只回复:收到")
        await page.click("#send")
        await page.wait_for_timeout(20000)
        chat = await page.inner_text("#chat")
        await browser.close()
    if "收到" in chat and "失败" not in chat:
        print("  PASS  iPhone UA chat HOME (store write — user opted in)")
    else:
        print(f"  FAIL  chat={chat[:120]!r}")
        sys.exit(1)

asyncio.run(main())
PY
  else
    bad "B11_CHAT_SMOKE=1 but playwright missing"
  fi
else
  note "  SKIP  chat smoke (set B11_CHAT_SMOKE=1 to opt in — writes store)"
fi

echo ""
if [[ "$fail" -ne 0 ]]; then
  echo "B11 TAILSCALE FAIL"
  exit 1
fi
echo "B11 TAILSCALE PASS (read-only)"
echo "Phone: ${URL}"
