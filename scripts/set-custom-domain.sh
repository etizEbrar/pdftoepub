#!/usr/bin/env bash
# Point the published site at a custom domain.
#
#   ./scripts/set-custom-domain.sh pdftoepub.tech
#   ./scripts/set-custom-domain.sh --off        # back to the github.io URL
#
# Run this only once the DNS records resolve. A CNAME file makes GitHub
# redirect the github.io address to the custom domain, so publishing it ahead
# of DNS takes the site down rather than moving it -- which is why it is a
# separate step from publishing.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${1:-}" = "--off" ]; then
  rm -f CNAME
  echo "custom domain cleared; publishing will serve the github.io URL"
  ./scripts/publish-site.sh
  exit 0
fi

DOMAIN="${1:-}"
[ -n "$DOMAIN" ] || { echo "usage: $0 <domain> | --off" >&2; exit 1; }

# Refuse to cut over to a domain that is not pointing here yet: the failure
# mode is a site that looks deployed and serves nothing.
EXPECTED="185.199.108.153 185.199.109.153 185.199.110.153 185.199.111.153"
RESOLVED="$(dig +short A "$DOMAIN" | sort | tr '\n' ' ')"
MATCHED=0
for ip in $RESOLVED; do
  case " $EXPECTED " in *" $ip "*) MATCHED=1 ;; esac
done

if [ "$MATCHED" -eq 0 ]; then
  echo "refusing: $DOMAIN does not resolve to GitHub Pages yet." >&2
  echo "  resolves to: ${RESOLVED:-nothing}" >&2
  echo "  expected one of: $EXPECTED" >&2
  echo "Add the A records at your DNS host, wait for them to propagate, retry." >&2
  exit 1
fi

echo "$DOMAIN" > CNAME
echo "CNAME -> $DOMAIN  (resolves to: $RESOLVED)"
./scripts/publish-site.sh

cat <<NOTE

Last step, once: GitHub repo -> Settings -> Pages
  Custom domain:  $DOMAIN
  Enforce HTTPS:  tick it after the certificate is issued (a few minutes).
NOTE
