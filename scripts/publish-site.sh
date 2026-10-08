#!/usr/bin/env bash
# Publish the landing page and the legal pages to gh-pages, which GitHub
# Pages serves.
#
# Two sources, deliberately:
#   landing/   hand-written marketing page -> /index.html, /style.css, /main.js
#   site/      generated from docs/        -> /privacy.html, /support.html
#
# privacy.html and support.html keep their exact paths because those URLs are
# registered with Apple in App Store Connect. Moving them breaks a compliance
# link, so the landing page takes the index and nothing else is renamed.
#
# The generated site/index.html is not published: the landing page is the
# index now. It is still built, because build-site.py is how the legal pages
# stay in step with docs/.
#
#   ./scripts/publish-site.sh
#
# A branch deploy rather than an Actions workflow, because creating
# .github/workflows/ needs a token with the `workflow` scope and this needs
# none. Enable it once under Settings → Pages → Deploy from a branch →
# gh-pages → / (root).
set -euo pipefail
cd "$(dirname "$0")/.."

python3 scripts/build-site.py >/dev/null
echo "site/ regenerated from docs/"

# A privacy policy with an unfilled placeholder is worse than an unpublished
# one: it is a public statement with a hole in it, and search engines will index
# it before anyone notices.
if grep -rn "\[[A-Z][A-Z ]*\]" site/*.html; then
  echo >&2
  echo "refusing to publish: the pages above still contain placeholders." >&2
  echo "run ./scripts/set-support-email.sh you@example.com first." >&2
  exit 1
fi

BRANCH="${1:-gh-pages}"
TMP="$(mktemp -d)"
cp site/privacy.html site/support.html "$TMP/"

# The landing page, its assets, and the card that social previews fetch.
cp landing/index.html landing/style.css landing/main.js "$TMP/"
[ -f landing/og-image.png ] && cp landing/og-image.png "$TMP/"

touch "$TMP/.nojekyll"

# A CNAME file is what tells GitHub Pages to serve a custom domain. Written
# only when one is configured, because the moment it exists GitHub redirects
# the github.io address to that domain -- so publishing it before the DNS
# records resolve takes the site down rather than moving it.
if [ -f CNAME ]; then
  cp CNAME "$TMP/"
  echo "custom domain: $(cat CNAME)"
fi

git fetch -q origin "$BRANCH" 2>/dev/null || true
WORK="$(mktemp -d)"
git worktree add -q --detach "$WORK"
pushd "$WORK" >/dev/null
  # A unique orphan name: checking out "$BRANCH" directly fails once a local
  # branch of that name exists, and the push below targets the branch by
  # refspec anyway, so the working name never matters.
  git checkout -q --orphan "publish-$$"
  git rm -rq --cached . 2>/dev/null || true
  find . -maxdepth 1 ! -name . ! -name .git -exec rm -rf {} +
  cp "$TMP"/* "$TMP/.nojekyll" .
  git add -A
  git -c user.name="$(git config user.name)" -c user.email="$(git config user.email)" \
      commit -qm "Publish site $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  git push -q -f origin "HEAD:$BRANCH"
popd >/dev/null
git worktree remove --force "$WORK"
rm -rf "$TMP"

REPO="$(git remote get-url origin | sed -E 's#.*github\.com[:/]([^/]+)/([^/.]+)(\.git)?#\1 \2#')"
USER_="$(echo "$REPO" | cut -d' ' -f1)"; NAME="$(echo "$REPO" | cut -d' ' -f2)"
echo "pushed to $BRANCH"
if [ -f CNAME ]; then
  echo "  https://$(cat CNAME)/"
else
  echo "  https://$(echo "$USER_" | tr '[:upper:]' '[:lower:]').github.io/$NAME/"
fi
