#!/usr/bin/env bash
# Publish site/ to the gh-pages branch, which GitHub Pages serves.
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
cp site/*.html "$TMP/"
touch "$TMP/.nojekyll"

git fetch -q origin "$BRANCH" 2>/dev/null || true
WORK="$(mktemp -d)"
git worktree add -q --detach "$WORK"
pushd "$WORK" >/dev/null
  git checkout -q --orphan "$BRANCH"
  git rm -rq --cached . 2>/dev/null || true
  find . -maxdepth 1 ! -name . ! -name .git -exec rm -rf {} +
  cp "$TMP"/*.html "$TMP/.nojekyll" .
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
echo "  https://$(echo "$USER_" | tr '[:upper:]' '[:lower:]').github.io/$NAME/"
