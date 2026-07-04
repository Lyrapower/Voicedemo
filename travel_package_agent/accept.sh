#!/usr/bin/env bash
# TripPack AI — Acceptance script (App Store Readiness V1)
# Verifies: install → tests → solver logic → HTTP endpoints → UI content → App Store guards

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT=8765
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo ""
echo "═══════════════════════════════════════════════════"
echo "  TripPack AI — Acceptance Check"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. Virtual environment ─────────────────────────────────────────────────
echo "▸ Setting up environment..."
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt -q
echo "  ✓ Dependencies installed"
echo ""

# ── 2. Pytest ──────────────────────────────────────────────────────────────
echo "▸ Running tests..."
python -m pytest tests/ -q --tb=short
echo "  ✓ Tests passed"
echo ""

# ── 3. Import check ────────────────────────────────────────────────────────
echo "▸ Checking app import..."
python -c "from app.main import app; print('  ✓ App imports OK')"
echo ""

# ── 4. Deterministic solver check ─────────────────────────────────────────
echo "▸ Running solver acceptance check..."
python - <<'PYEOF'
from datetime import date
from app.models import TripRequest
from app.solver import solve

req = TripRequest(
    origin="San Diego",
    budget=5000,
    earliest_departure=date(2026, 5, 8),
    latest_return=date(2026, 5, 22),
    travelers=1,
    style="Best Value",
    rental_car_required=True,
    destination_preference="Any",
)
result = solve(req)

assert len(result.top_packages) >= 3, \
    f"FAIL: Expected >= 3 PASS packages, got {len(result.top_packages)}"

for pkg in result.top_packages:
    assert pkg.total_cost <= 5000, \
        f"FAIL: {pkg.destination} total_cost {pkg.total_cost} exceeds budget"
    assert pkg.flight is not None, f"FAIL: {pkg.destination} missing flight"
    assert pkg.hotel is not None,  f"FAIL: {pkg.destination} missing hotel"
    assert pkg.car is not None,    f"FAIL: {pkg.destination} missing car"
    assert pkg.taxes_fees > 0,     f"FAIL: {pkg.destination} missing taxes_fees"
    assert pkg.buffer > 0,         f"FAIL: {pkg.destination} missing buffer"

assert len(result.rejected_packages) >= 2, \
    f"FAIL: Expected >= 2 rejected packages, got {len(result.rejected_packages)}"

print("  ✓ Solver works without LLM or external API")
print(f"  ✓ Top packages: {len(result.top_packages)}")
print(f"  ✓ Rejected packages: {len(result.rejected_packages)}")
for i, pkg in enumerate(result.top_packages):
    remaining = f"+${pkg.budget_remaining:,.0f} remaining"
    print(f"    #{i+1} {pkg.destination}: ${pkg.total_cost:,.2f} — {pkg.rank_label} — {remaining}")
PYEOF
echo ""

# ── 5. Start server ────────────────────────────────────────────────────────
echo "▸ Starting server on port $PORT..."
uvicorn app.main:app --host 127.0.0.1 --port $PORT --log-level error &
SERVER_PID=$!

# Wait for server ready (up to 8s)
READY=0
for i in $(seq 1 16); do
  if curl -s "http://127.0.0.1:$PORT/" > /dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.5
done

if [ "$READY" -eq 0 ]; then
  echo "  ✗ Server did not start in time"
  exit 1
fi
echo "  ✓ Server running at http://127.0.0.1:$PORT"
echo ""

# ── 6. GET / ─────────────────────────────────────────────────────────────
echo "▸ Checking GET / ..."
HOME_HTML=$(curl -s "http://127.0.0.1:$PORT/")

chk_home() {
  if echo "$HOME_HTML" | grep -q "$1"; then
    echo "  ✓ Found: $2"
  else
    echo "  ✗ MISSING in /: $2"
    exit 1
  fi
}

chk_home "Three trips you can actually afford"   "Hero title"
chk_home "BUDGET-LOCKED"                          "Product identity pill"
chk_home "Tell us the trip"                       "Composer title"
chk_home "Build my three packages"                "Build CTA"
chk_home "Generate packages"                      "Sticky CTA"
chk_home "Speak trip"                            "Voice affordance"
chk_home "Privacy"                                "Privacy link in footer"
chk_home "Demo data"                              "Demo honesty copy"
echo ""

# ── 7. POST /search ────────────────────────────────────────────────────────
echo "▸ Checking POST /search ..."
SEARCH_HTML=$(curl -s -X POST "http://127.0.0.1:$PORT/search" \
  -F "origin=San Diego" \
  -F "budget=5000" \
  -F "earliest_departure=2026-05-08" \
  -F "latest_return=2026-05-22" \
  -F "travelers=1" \
  -F "style=Best Value" \
  -F "rental_car_required=on" \
  -F "destination_preference=Any")

chk_search() {
  if echo "$SEARCH_HTML" | grep -q "$1"; then
    echo "  ✓ Found: $2"
  else
    echo "  ✗ MISSING in /search: $2"
    exit 1
  fi
}

chk_search "3 packages under"                    "Results headline"
chk_search "BUDGET PASS"                         "BUDGET PASS badge"
chk_search "View package"                        "View package CTA"
chk_search "Rejected options"                    "Rejected options section"
chk_search "not just ChatGPT"                    "Differentiation copy"
chk_search "Privacy"                             "Privacy link"
chk_search "Mock"                                "Mock booking label"
chk_search "Demo data"                            "Results demo disclaimer"
chk_search "Save"                                "Save control"

# Verify mock links are NOT presented as real booking buttons
if echo "$SEARCH_HTML" | grep -qi "Book Now" ; then
  echo "  ✗ FAIL: Found 'Book Now' — do not present mock links as real booking"
  exit 1
fi
if echo "$SEARCH_HTML" | grep -qi "Confirm booking" ; then
  echo "  ✗ FAIL: Found 'Confirm booking' — do not present mock links as real booking"
  exit 1
fi
echo "  ✓ No fake real-booking language detected"
echo ""

# ── 8. GET /privacy ────────────────────────────────────────────────────────
echo "▸ Checking GET /privacy ..."
PRIVACY_HTML=$(curl -s "http://127.0.0.1:$PORT/privacy")
if echo "$PRIVACY_HTML" | grep -q "Privacy"; then
  echo "  ✓ /privacy loads"
else
  echo "  ✗ /privacy failed"
  exit 1
fi
if echo "$PRIVACY_HTML" | grep -q "demo data\|Demo Data"; then
  echo "  ✓ Privacy page includes data honesty disclosure"
else
  echo "  ✗ Privacy page missing data honesty"
  exit 1
fi
echo ""

# ── 9. GET /review-notes ──────────────────────────────────────────────────
echo "▸ Checking GET /review-notes ..."
REVIEW_HTML=$(curl -s "http://127.0.0.1:$PORT/review-notes")
if echo "$REVIEW_HTML" | grep -q "Review Notes\|review-notes\|App Review"; then
  echo "  ✓ /review-notes loads"
else
  echo "  ✗ /review-notes failed"
  exit 1
fi
if echo "$REVIEW_HTML" | grep -q "deterministic\|DETERMINISTIC"; then
  echo "  ✓ Review notes explains deterministic code"
else
  echo "  ✗ Review notes missing deterministic explanation"
  exit 1
fi
echo ""

# ── 10. POST /parse-request ────────────────────────────────────────────────
echo "▸ Checking POST /parse-request ..."
PARSE_RESP=$(curl -s -X POST "http://127.0.0.1:$PORT/parse-request" \
  -F "text=I have 5000 and want to travel from San Diego in the second week of May near the beach and need a rental car")
if echo "$PARSE_RESP" | grep -q "budget"; then
  echo "  ✓ /parse-request returns structured fields (no LLM)"
else
  echo "  ✗ /parse-request missing budget"
  exit 1
fi
echo ""

# ── Final output ────────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════"
echo ""
echo "ACCEPTANCE PASS"
echo "Top packages: 3"
echo "Budget respected: YES"
echo "Rejected packages visible: YES"
echo "Mock booking links labeled: YES"
echo "Pricing honesty copy present: YES"
echo "Privacy page: YES"
echo "Review notes page: YES"
echo "No fake booking language: YES"
echo ""
echo "═══════════════════════════════════════════════════"
echo ""
echo "To run the app:"
echo "  source venv/bin/activate"
echo "  uvicorn app.main:app --port 8765 --reload"
echo "  Open: http://127.0.0.1:8765"
echo ""
