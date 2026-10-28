#!/bin/sh
# Publish the map to GitHub Pages at https://neilk.github.io/mobi-density/
#
# Copies analysis/output/map.html to index.html on the gh-pages branch and
# pushes it. Build the map first (analysis/README.md); nothing here rebuilds.
# The branch holds only the published page, so it carries no history of the
# rest of the project.
set -eu
cd "$(dirname "$0")"
SRC=analysis/output/map.html
[ -f "$SRC" ] || { echo "$SRC is missing; build it first (see analysis/README.md)" >&2; exit 1; }

WT=$(mktemp -d)
trap 'git worktree remove --force "$WT" 2>/dev/null || true' EXIT
if git fetch -q origin gh-pages 2>/dev/null; then
  git branch -q -f gh-pages FETCH_HEAD             # the local branch follows what is published
  git worktree add -q "$WT" gh-pages
elif git show-ref -q --verify refs/heads/gh-pages; then
  git worktree add -q "$WT" gh-pages
else
  git worktree add -q --orphan -b gh-pages "$WT"   # first publish: a branch with no history
fi

cp "$SRC" "$WT/index.html"
touch "$WT/.nojekyll"                              # serve the file as is, no Jekyll pass
git -C "$WT" add -A
if git -C "$WT" diff --cached --quiet; then
  echo "index.html is unchanged; nothing to publish"
  exit 0
fi
git -C "$WT" commit -q -m "Publish map.html built $(date +%Y-%m-%d)"
git -C "$WT" push -q -u origin gh-pages
echo "Pushed gh-pages; https://neilk.github.io/mobi-density/ updates within a minute or two"
