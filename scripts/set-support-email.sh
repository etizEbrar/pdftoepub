#!/usr/bin/env bash
# Fill in the support address the privacy policy and support page publish.
#
#   ./scripts/set-support-email.sh support@example.com
#
# Deliberately a separate step. This address goes onto a public page that search
# engines will index and that the App Store listing points at, so it is worth
# choosing on purpose rather than inheriting whatever address happened to be to
# hand. A dedicated alias tends to age better than a personal mailbox.
set -euo pipefail
EMAIL="${1:-}"
[ -n "$EMAIL" ] || { echo "usage: $0 you@example.com" >&2; exit 2; }
case "$EMAIL" in *@*.*) ;; *) echo "that does not look like an email address" >&2; exit 2;; esac

cd "$(dirname "$0")/.."
for f in docs/privacy-policy.md docs/support.md docs/app-store-metadata.md; do
  [ -f "$f" ] || continue
  python3 - "$f" "$EMAIL" <<'PY'
import sys
from pathlib import Path
p, email = Path(sys.argv[1]), sys.argv[2]
s = p.read_text(encoding="utf-8")
if "[SUPPORT EMAIL]" in s:
    p.write_text(s.replace("[SUPPORT EMAIL]", email), encoding="utf-8")
    print(f"  {p}")
PY
done
python3 scripts/build-site.py >/dev/null
echo "site/ regenerated with $EMAIL"
if grep -rqn "\[[A-Z][A-Z ]*\]" site/*.html; then
  echo "WARNING: other placeholders remain:" >&2
  grep -rn "\[[A-Z][A-Z ]*\]" site/*.html >&2
else
  echo "no placeholders remain — the Pages workflow will publish"
fi
