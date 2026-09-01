#!/usr/bin/env bash
# Capture App Store screenshots by driving the real UI in the simulator.
#
# The result and quality-report screens only exist after a genuine conversion,
# so this needs a backend running. Start one with:
#   cd backend && ./.venv/bin/python -m uvicorn app.main:app --port 8000
#
# Usage: ./scripts/capture_screenshots.sh [simulator-name] [output-dir]
set -euo pipefail

SIM="${1:-iPhone 17 Pro Max}"          # 6.9" — the size App Store Connect requires
OUT="${2:-build/screenshots}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

if ! curl -sf --max-time 3 http://localhost:8000/health >/dev/null; then
  echo "No backend on http://localhost:8000 — the result screens cannot be captured." >&2
  echo "Start one first; see the header of this script." >&2
  exit 1
fi

RESULTS="$(mktemp -d)/results.xcresult"
mkdir -p "$OUT"

echo "Driving the UI on '$SIM'…"
xcodebuild test \
  -project PDFtoEPUB.xcodeproj \
  -scheme PDFtoEPUB \
  -configuration Debug \
  -destination "platform=iOS Simulator,name=$SIM" \
  -only-testing:PDFtoEPUBUITests/ScreenshotCaptureTest \
  -resultBundlePath "$RESULTS" \
  >/dev/null

echo "Extracting attachments…"
xcrun xcresulttool export attachments \
  --path "$RESULTS" \
  --output-path "$OUT" \
  >/dev/null 2>&1 || {
    echo "Could not export attachments from $RESULTS" >&2
    exit 1
  }

COUNT=$(find "$OUT" -name "*.png" | wc -l | tr -d ' ')
echo "Wrote $COUNT screenshot(s) to $OUT"
[ "$COUNT" -gt 0 ] || { echo "No screenshots produced." >&2; exit 1; }
find "$OUT" -name "*.png" -exec sh -c 'printf "  %s  %s\n" "$(sips -g pixelWidth -g pixelHeight "$1" | awk "/pixel/{printf \$2\"x\"}" | sed "s/x$//")" "$(basename "$1")"' _ {} \;
