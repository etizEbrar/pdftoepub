#!/usr/bin/env bash
# Capture App Store screenshots by driving the real UI in the simulator.
#
#   ./scripts/capture_screenshots.sh ["iPhone 17 Pro Max"] [output-dir]
#
# Needs a backend, because the progress, result and preview screens only exist
# after a genuine conversion:
#   cd backend && ./.venv/bin/python -m uvicorn app.main:app --port 8000
set -euo pipefail

SIM_NAME="${1:-iPhone 17 Pro Max}"          # 6.9" — the size App Store Connect wants
OUT="${2:-build/screenshots}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # the ios/ directory
REPO="$(cd "$HERE/.." && pwd)"             # the repository root
cd "$HERE"

if ! curl -sf --max-time 3 http://localhost:8000/health >/dev/null; then
  echo "No backend on http://localhost:8000 — the result screens cannot be captured." >&2
  exit 1
fi

SIM_ID="$(xcrun simctl list devices available \
          | grep -F "$SIM_NAME (" | head -1 | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')"
[ -n "$SIM_ID" ] || { echo "no available simulator named '$SIM_NAME'" >&2; exit 1; }
xcrun simctl boot "$SIM_ID" 2>/dev/null || true
until xcrun simctl list devices | grep -q "$SIM_ID) (Booted)"; do sleep 2; done

# Build and install first, *then* place the fixture. A plain `xcodebuild test`
# reinstalls the app, which wipes its container and takes the fixture with it —
# the test then could not find a PDF and used to skip, reporting success while
# producing a single screenshot.
echo "Building for testing…"
xcodebuild build-for-testing -project PDFtoEPUB.xcodeproj -scheme PDFtoEPUB \
  -configuration Debug -destination "platform=iOS Simulator,id=$SIM_ID" >/dev/null

APP="$(find ~/Library/Developer/Xcode/DerivedData/PDFtoEPUB-*/Build/Products/Debug-iphonesimulator \
       -name "PDFtoEPUB.app" -maxdepth 2 2>/dev/null | head -1)"
[ -n "$APP" ] || { echo "could not locate the built app" >&2; exit 1; }
xcrun simctl install "$SIM_ID" "$APP"
CONT="$(xcrun simctl get_app_container "$SIM_ID" com.pdftoepub.app data)"
mkdir -p "$CONT/Documents"
cp "$REPO/backend/tests/fixtures/simple_book.pdf" "$CONT/Documents/"
# Launch once and stop. The Files provider indexes a container lazily, so a
# freshly copied PDF is not yet visible to the document picker; without this the
# picker comes up empty and the run fails looking for a file that is on disk.
xcrun simctl launch "$SIM_ID" com.pdftoepub.app >/dev/null 2>&1 || true
sleep 5
xcrun simctl terminate "$SIM_ID" com.pdftoepub.app >/dev/null 2>&1 || true
echo "Placed the fixture in the app container and warmed the file provider."

RESULTS="$(mktemp -d)/results.xcresult"
# Start from an empty directory: xcresulttool refuses to overwrite an existing
# manifest.json, so a previous run would otherwise block this one.
rm -rf "$OUT"
mkdir -p "$OUT"

echo "Driving the UI on '$SIM_NAME'…"
xcodebuild test-without-building \
  -project PDFtoEPUB.xcodeproj -scheme PDFtoEPUB -configuration Debug \
  -destination "platform=iOS Simulator,id=$SIM_ID" \
  -only-testing:PDFtoEPUBUITests/ScreenshotCaptureTest \
  -resultBundlePath "$RESULTS" >/dev/null

echo "Extracting attachments…"
# Not silenced: when this fails the reason matters, and swallowing it once made
# a working export look like a broken one.
xcrun xcresulttool export attachments --path "$RESULTS" --output-path "$OUT"

# Attachments come out named by UUID; the manifest carries the readable name.
python3 "$HERE/scripts/_name_screenshots.py" "$OUT"

COUNT=$(find "$OUT" -name "*.png" | wc -l | tr -d " ")
echo "Wrote $COUNT screenshot(s) to $OUT"
[ "$COUNT" -ge 5 ] || { echo "expected 5 (home, settings, progress, result, preview)" >&2; exit 1; }
for f in "$OUT"/*.png; do
  printf "  %-28s %s\n" "$(basename "$f")" \
    "$(sips -g pixelWidth -g pixelHeight "$f" | awk "/pixelWidth/{w=\$2} /pixelHeight/{h=\$2} END{print w\"x\"h}")"
done
