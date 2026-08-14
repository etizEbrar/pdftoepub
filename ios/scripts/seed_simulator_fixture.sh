#!/usr/bin/env bash
# Copies the test PDF into the booted simulator's "On My iPhone" storage so the
# end-to-end UI tests can pick it through the real system document picker.
# That storage lives outside the app container, so it survives app reinstalls
# between test runs (the app's own Documents folder does not).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIXTURE="$REPO_ROOT/backend/tests/fixtures/simple_book.pdf"

if [ ! -f "$FIXTURE" ]; then
  echo "Generating test fixture..."
  (cd "$REPO_ROOT/backend" && ./.venv/bin/python tests/fixtures/make_test_pdf.py)
fi

DEVICE_ID=$(xcrun simctl list devices booted -j \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["devices"]; print(next(x["udid"] for v in d.values() for x in v if x["state"]=="Booted"))')

DEVICE_ROOT="$HOME/Library/Developer/CoreSimulator/Devices/$DEVICE_ID/data/Containers/Shared/AppGroup"

STORAGE=""
for dir in "$DEVICE_ROOT"/*/; do
  plist="$dir/.com.apple.mobile_container_manager.metadata.plist"
  [ -f "$plist" ] || continue
  id=$(plutil -extract MCMMetadataIdentifier raw "$plist" 2>/dev/null || true)
  if [ "$id" = "group.com.apple.FileProvider.LocalStorage" ]; then
    STORAGE="$dir/File Provider Storage"
    break
  fi
done

if [ -z "$STORAGE" ]; then
  echo "Could not find the simulator's local file-provider storage." >&2
  exit 1
fi

mkdir -p "$STORAGE"
cp "$FIXTURE" "$STORAGE/"
echo "Seeded $(basename "$FIXTURE") into the booted simulator's On My iPhone storage."
