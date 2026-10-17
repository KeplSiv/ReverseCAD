#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
mkdir -p reports
# This script creates/reuses only our dedicated simulator; it never resets others.
sim_id=$(xcrun simctl list devices available -j | .venv/bin/python -c 'import sys,json; d=json.load(sys.stdin); print(next((x["udid"] for a in d["devices"].values() for x in a if x["name"]=="ReverseCAD Trial"), ""))')
if [[ -z "$sim_id" ]]; then
  sim_id=$(xcrun simctl create 'ReverseCAD Trial' com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro com.apple.CoreSimulator.SimRuntime.iOS-26-5)
fi
xcrun simctl boot "$sim_id" 2>/dev/null || true
xcrun simctl bootstatus "$sim_id" -b
xcodegen generate --spec ios/project.yml
xcodebuild -project ios/ReverseCAD.xcodeproj -scheme ReverseCAD -configuration Debug -sdk iphonesimulator -destination "id=$sim_id" -derivedDataPath var/DerivedData CODE_SIGNING_ALLOWED=NO build > reports/simulator-launch-build.log 2>&1
xcrun simctl install "$sim_id" var/DerivedData/Build/Products/Debug-iphonesimulator/ReverseCAD.app
xcrun simctl launch "$sim_id" com.pranav.ReverseCAD
open -a Simulator --args -CurrentDeviceUDID "$sim_id"
