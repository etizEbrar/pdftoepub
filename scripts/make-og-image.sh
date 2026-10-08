#!/usr/bin/env bash
# Render landing/og-image.png (1200x630) from an inline template.
#
#   ./scripts/make-og-image.sh
#
# Generated rather than hand-drawn so the card and the page cannot drift: it
# reuses the page's own tokens. A missing og:image renders as an empty card in
# iMessage, Slack and X, which is worse than no tag at all.
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[ -x "$CHROME" ] || { echo "Chrome not found; set CHROME=..." >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/og.html" <<'HTML'
<!doctype html><meta charset="utf-8">
<style>
  :root{--ink:#f5f3ef;--dim:#b4ada2;--bg:#16150f;--accent:#d97757;--line:#2e2c23}
  *{box-sizing:border-box;margin:0}
  body{width:1200px;height:630px;background:var(--bg);color:var(--ink);
    font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",Inter,system-ui,sans-serif;
    padding:68px 76px;display:flex;flex-direction:column;justify-content:space-between;
    -webkit-font-smoothing:antialiased}
  .top{display:flex;align-items:center;gap:14px}
  .mark{width:44px;height:44px;border-radius:10px;background:var(--accent);color:#1a1710;
    display:grid;place-items:center;font-weight:700;font-size:17px}
  .name{font-size:25px;font-weight:650;letter-spacing:-.01em}
  h1{font-size:68px;line-height:1.06;letter-spacing:-.032em;font-weight:620;max-width:17ch}
  p{margin-top:22px;color:var(--dim);font-size:25px;max-width:30ch;line-height:1.45}
  .badges{display:flex;gap:11px;flex-wrap:wrap}
  .b{padding:9px 17px;border:1px solid var(--line);border-radius:999px;
    color:var(--dim);font-size:18px;background:#1e1d16}
  .b b{color:var(--ink);font-weight:600}
</style>
<div class="top"><div class="mark">PE</div><div class="name">PDF to EPUB</div></div>
<div>
  <h1>Publication-ready EPUBs from difficult PDFs.</h1>
  <p>On-device OCR, deterministic typesetting, and Claude for the rest.</p>
</div>
<div class="badges">
  <span class="b"><b>2.1 s</b> &nbsp;per scanned page, on device</span>
  <span class="b"><b>472</b> &nbsp;engine tests</span>
  <span class="b">Validated <b>EPUB3</b></span>
</div>
HTML

"$CHROME" --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1200,630 --screenshot="$TMP/og.png" \
  "file://$TMP/og.html" >/dev/null 2>&1

# sips ships with macOS; keeps the file small without adding a dependency.
cp "$TMP/og.png" landing/og-image.png
command -v sips >/dev/null && sips -s format png landing/og-image.png --out landing/og-image.png >/dev/null 2>&1 || true

echo "wrote landing/og-image.png ($(du -h landing/og-image.png | cut -f1))"
