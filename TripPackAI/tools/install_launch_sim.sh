#!/usr/bin/env bash
# Build, install, and launch TripPackAI on iPhone 17 Pro. Home screen label: "TripPack AI".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SIM_NAME="iPhone 17 Pro"

xcodebuild -project TripPackAI.xcodeproj -scheme TripPackAI \
  -destination "platform=iOS Simulator,name=${SIM_NAME}" -configuration Debug \
  clean build 2>&1 | tee LastBuildLog.txt

APP_PATH=$(find "$HOME/Library/Developer/Xcode/DerivedData" -path "*TripPackAI*/Build/Products/Debug-iphonesimulator/TripPackAI.app" -type d 2>/dev/null | head -1)
test -d "$APP_PATH"

xcrun simctl shutdown all 2>/dev/null || true
xcrun simctl boot "$SIM_NAME"
open -a Simulator
# Let SpringBoard finish booting so install targets the right UI.
sleep 4

xcrun simctl install booted "$APP_PATH"
BUNDLE_ID=$(/usr/libexec/PlistBuddy -c "Print CFBundleIdentifier" "$APP_PATH/Info.plist")
xcrun simctl launch booted "$BUNDLE_ID"
open -a Simulator
echo "Done. Look for the app named \"TripPack AI\" (teal icon) on the simulator home screen."
