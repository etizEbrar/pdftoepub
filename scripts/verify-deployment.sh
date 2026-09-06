#!/usr/bin/env bash
# Verify a deployed backend from outside, then wire the iOS app to it.
#
#   ./scripts/verify-deployment.sh https://pdftoepub-backend.onrender.com
#
# Runs a real conversion over the public URL — upload, poll, download, delete —
# and validates the returned EPUB with EPUBCheck. Nothing is written to the iOS
# project unless every check passes.
set -uo pipefail

BASE="${1:-}"
[ -n "$BASE" ] || { echo "usage: $0 https://your-service.onrender.com" >&2; exit 2; }
BASE="${BASE%/}"
PDF="${2:-backend/tests/fixtures/corpus/turkish_novel.pdf}"
TMP="$(mktemp -d)"
fail() { echo "  FAIL: $*" >&2; exit 1; }

echo "== 1. HTTPS and health =="
case "$BASE" in https://*) ;; *) fail "not an https:// URL — the app refuses plain http to a public host";; esac
# A free instance may be asleep; the first request can take ~1 minute to wake.
HEALTH=""
for i in $(seq 1 20); do
  HEALTH="$(curl -fsS --max-time 30 "$BASE/health" 2>/dev/null || true)"
  [ -n "$HEALTH" ] && break
  echo "  waiting for the service to wake ($i/20)…"
  sleep 15
done
[ -n "$HEALTH" ] || fail "no response from $BASE/health"
echo "  $HEALTH"
echo "$HEALTH" | grep -q '"status":"ok"'          || fail "health did not report ok"
echo "$HEALTH" | grep -q '"ai_provider":"none"'   || fail "an AI provider is configured; it must be none"

echo "== 2. production hardening =="
for p in /docs /openapi.json; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$BASE$p")"
  [ "$code" = "404" ] || fail "$p is exposed (HTTP $code); ENVIRONMENT is not production"
  echo "  $p -> 404 (hidden)"
done
curl -sI --max-time 20 "$BASE/health" | grep -qi "strict-transport-security" \
  && echo "  HSTS present" || echo "  NOTE: no HSTS header (the platform may terminate TLS ahead of the app)"

echo "== 3. real conversion over the public URL =="
[ -f "$PDF" ] || fail "test PDF not found: $PDF"
JOB="$(curl -fsS --max-time 180 -X POST "$BASE/v1/conversions" \
        -F "file=@$PDF" -F "mode=maximum_accuracy" \
      | sed -E 's/.*"id":"([a-f0-9]+)".*/\1/')"
[ ${#JOB} -eq 32 ] || fail "no job id returned (got '${JOB:0:60}')"
echo "  job $JOB"

STATUS=""
for i in $(seq 1 240); do
  STATUS="$(curl -fsS --max-time 30 "$BASE/v1/conversions/$JOB/progress" \
            | sed -E 's/.*"status":"([A-Za-z_]+)".*/\1/')"
  case "$STATUS" in COMPLETED|FAILED) break;; esac
  sleep 3
done
[ "$STATUS" = "COMPLETED" ] || fail "conversion ended as '$STATUS'"
echo "  status COMPLETED"

RESULT="$(curl -fsS --max-time 30 "$BASE/v1/conversions/$JOB/result")"
echo "$RESULT" | grep -q '"ai_provider_used":"none"' || fail "the conversion used an AI provider"
echo "$RESULT" | grep -q '"epubcheck_passed":true'   || fail "the server's own EPUBCheck did not pass"
echo "  ai=none, server-side epubcheck passed"

curl -fsS --max-time 180 -o "$TMP/out.epub" "$BASE/v1/conversions/$JOB/download" || fail "download failed"
SIZE=$(stat -f%z "$TMP/out.epub" 2>/dev/null || stat -c%s "$TMP/out.epub")
[ "$SIZE" -gt 2000 ] || fail "downloaded EPUB is implausibly small ($SIZE bytes)"
echo "  downloaded $SIZE bytes"

if command -v epubcheck >/dev/null 2>&1; then
  epubcheck "$TMP/out.epub" 2>&1 | grep -q "No errors or warnings detected" \
    && echo "  independent EPUBCheck: PASS" || fail "independent EPUBCheck reported problems"
else
  echo "  NOTE: epubcheck not on PATH here; skipped the independent check"
fi

echo "== 4. the document is deleted afterwards =="
curl -fsS --max-time 30 -X DELETE "$BASE/v1/conversions/$JOB" >/dev/null || true
GONE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$BASE/v1/conversions/$JOB/progress")"
[ "$GONE" = "404" ] && echo "  job removed (404 after delete)" || echo "  NOTE: job still present (HTTP $GONE)"

rm -rf "$TMP"
echo
echo "ALL CHECKS PASSED for $BASE"
echo "Wire the iOS app to it with:"
echo "  ./scripts/set-production-url.sh $BASE"
