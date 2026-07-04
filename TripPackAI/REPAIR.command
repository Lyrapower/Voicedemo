#!/bin/bash
cd "$(dirname "$0")" || exit 1
set -u
./tools/xcodebuild_acceptance.sh
ec=$?
if [[ $ec -eq 0 ]]; then
  open -a Xcode "TripPackAI.xcodeproj"
fi
exit "$ec"
