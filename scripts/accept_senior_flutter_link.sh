#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLIENT="$ROOT/clients/openclaw_senior_flutter"
REPORT_DIR="$ROOT/deliver/proof/openclaw_v1"
REPORT="$REPORT_DIR/SENIOR_FLUTTER_LINK_REPORT.md"
FAIL=0

mkdir -p "$REPORT_DIR"

# ── File existence checks ──────────────────────────────────────────────────
FILE_LINES=""
check_file() {
  local rel="$1" label="$2"
  if [ -f "$CLIENT/$rel" ]; then
    FILE_LINES="${FILE_LINES}- PRESENT  | $rel ($label)\n"
  else
    FILE_LINES="${FILE_LINES}- MISSING  | $rel ($label)\n"
    FAIL=1
  fi
}

check_file "lib/main.dart"                                         "main entry"
check_file "lib/features/home/home_page.dart"                     "home UI"
check_file "lib/features/home/home_controller.dart"               "home controller"
check_file "lib/features/safety/safety_screen.dart"               "safety screen"
check_file "lib/core/services/tts_service.dart"                   "TTS service"
check_file "lib/core/services/log_service.dart"                   "log service"
check_file "lib/core/services/presence_echo_service.dart"         "presence echo"
check_file "lib/core/services/safety_chain_service.dart"          "safety chain"
check_file "lib/core/services/verified_mode_service.dart"         "verified mode"
check_file "pubspec.yaml"                                         "pubspec"

# ── V1 hard-gate keyword checks ────────────────────────────────────────────
GATE_LINES=""
check_gate() {
  local rel="$1" token="$2"
  if [ -f "$CLIENT/$rel" ] && grep -q "$token" "$CLIENT/$rel" 2>/dev/null; then
    GATE_LINES="${GATE_LINES}- PASS  | $rel → $token\n"
  else
    GATE_LINES="${GATE_LINES}- FAIL  | $rel → $token\n"
    FAIL=1
  fi
}

check_gate "lib/core/services/safety_chain_service.dart" "ESCALATE_72H"
check_gate "lib/core/services/tts_service.dart"          "TTS_SPOKEN"
check_gate "lib/core/services/verified_mode_service.dart" "medication"
check_gate "lib/features/home/home_page.dart"            "我在"
check_gate "lib/features/home/home_controller.dart"      "你在吗"

# ── Flutter SDK runtime status ─────────────────────────────────────────────
if command -v flutter &>/dev/null; then
  FLUTTER_RUNTIME="$(flutter --version 2>/dev/null | head -1)"
else
  FLUTTER_RUNTIME="UNKNOWN (Flutter SDK not installed — file checks only)"
fi

# ── Verdict ────────────────────────────────────────────────────────────────
if [ "$FAIL" -eq 0 ]; then
  VERDICT="PASS"
else
  VERDICT="FAIL"
fi

# ── Write report ───────────────────────────────────────────────────────────
{
  echo "# Senior Flutter Link Report"
  echo "Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "Client path: clients/openclaw_senior_flutter"
  echo ""
  echo "## File Existence"
  echo -e "$FILE_LINES" | sort
  echo ""
  echo "## V1 Hard-Gate Keywords"
  echo -e "$GATE_LINES" | sort
  echo ""
  echo "## Flutter SDK Runtime"
  echo "$FLUTTER_RUNTIME"
  echo ""
  echo "## Notes"
  echo "- File checks are local-only reads; no Flutter build or run was performed."
  echo "- Runtime marked UNKNOWN if Flutter SDK absent (does not affect PASS/FAIL)."
  echo ""
  echo "FINAL VERDICT: $VERDICT"
} > "$REPORT"

echo ""
echo "Senior Flutter Link: $VERDICT"
echo "Report: $REPORT"
