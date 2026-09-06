#!/usr/bin/env bash
# Point the iOS Release build at a verified backend, and prove it landed in the
# built binary rather than only in the project file.
set -euo pipefail
URL="${1:-}"
[ -n "$URL" ] || { echo "usage: $0 https://your-service.onrender.com" >&2; exit 2; }
case "$URL" in https://*) ;; *) echo "refusing: must be https://" >&2; exit 2;; esac
case "$URL" in *localhost*|*127.0.0.1*|*192.168.*|*10.*|*.local*)
  echo "refusing: that is a private address, which a Release build must never ship" >&2; exit 2;; esac

cd "$(dirname "$0")/.."
python3 - "$URL" <<'PY'
import re, sys
from pathlib import Path
url = sys.argv[1].rstrip("/")
p = Path("ios/project.yml")
s = p.read_text(encoding="utf-8")
s2 = re.sub(r'(\n    PRODUCTION_BACKEND_URL: ).*', lambda m: m.group(1) + f'"{url}"', s, count=1)
if s2 == s:
    sys.exit("could not find PRODUCTION_BACKEND_URL in ios/project.yml")
p.write_text(s2, encoding="utf-8")
print(f"ios/project.yml -> PRODUCTION_BACKEND_URL={url}")
PY

cd ios && xcodegen generate >/dev/null && echo "regenerated the Xcode project"
echo "Now rebuild and confirm it is really in the binary:"
echo "  cd ios && xcodebuild archive -scheme PDFtoEPUB -configuration Release \\"
echo "      -destination 'generic/platform=iOS' -archivePath build/PDFtoEPUB.xcarchive -allowProvisioningUpdates"
