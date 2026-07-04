#!/usr/bin/env bash
# TripPackAI — show why the simulator list may look "empty" and try to open one.
set -euo pipefail

echo "=== Active developer directory ==="
xcode-select -p 2>&1 || true

echo ""
echo "=== xcodebuild version ==="
xcodebuild -version 2>&1 | head -3 || { echo "No xcodebuild. Install full Xcode from the App Store (not just Command Line Tools)."; exit 1; }

echo ""
echo "=== iOS runtimes (need at least one for iPhone simulators) ==="
xcrun simctl list runtimes 2>&1 | grep -E 'iOS|com.apple' | head -20 || true

echo ""
echo "=== Available iPhone simulators (first 20 lines with iPhone) ==="
xcrun simctl list devices available 2>&1 | grep -i "iphone" || echo "(no lines matching 'iPhone' — list may be empty)"

echo ""
if xcrun simctl list devices available 2>&1 | grep -qi "iphone"; then
  # First UUID in the line: device id (not the second "(Shutdown)" paren)
  FIRST=$(xcrun simctl list devices available 2>&1 | grep -E 'iPhone' | head -1 | grep -oE '\([0-9A-F]{8}-[0-9A-F-]+\)' | tr -d '()' | head -1)
  if [[ -n "$FIRST" ]]; then
    echo "Booting first available iPhone simulator (id $FIRST)…"
    xcrun simctl boot "$FIRST" 2>/dev/null || true
    open -a Simulator 2>/dev/null || true
    echo "Simulator app should open. In Xcode, pick a destination with the same iPhone name."
  fi
else
  echo "EMPTY LIST FIX:"
  echo "  1) Open Xcode → Settings (⌘,) → Platforms (or Components)."
  echo "  2) Download/install the iOS simulator runtime (wait until it finishes)."
  echo "  3) Quit Xcode, reopen, open TripPackAI.xcodeproj from:"
  echo "     $(cd "$(dirname "$0")/.." && pwd)/TripPackAI.xcodeproj"
  echo "  4) Product menu → Destination → pick any 'iPhone …' (Pro is optional; any iPhone works)."
  echo ""
  echo "If you only installed Command Line Tools, full Xcode is required for the Simulator app."
  exit 1
fi
