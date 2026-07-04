#!/usr/bin/env bash
# Acceptance: exact xcodebuild used for validation (same as manual command).
# Tries iPhone 15 Pro first; if the simulator is not installed, falls back to iPhone 17 Pro.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -o pipefail
set +e
xcodebuild -project TripPackAI.xcodeproj -scheme TripPackAI -destination 'platform=iOS Simulator,name=iPhone 15 Pro' -configuration Debug clean build 2>&1 | tee LastBuildLog.txt
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  exit 0
fi
if [[ $rc -eq 70 ]] || grep -q "Unable to find a device" LastBuildLog.txt; then
  echo ""
  echo "iPhone 15 Pro simulator not installed; using iPhone 17 Pro (from xcodebuild -showdestinations)."
  set +e
  set -o pipefail
  xcodebuild -project TripPackAI.xcodeproj -scheme TripPackAI -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -configuration Debug clean build 2>&1 | tee LastBuildLog.txt
  rc2=$?
  set -e
  exit $rc2
fi
exit "$rc"
