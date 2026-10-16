#!/usr/bin/env bash
# Build a server release: release/arynwood-grove-<version>.tar.gz (+ .sha256), plus copies named
# arynwood-grove.tar.gz for the "latest" download link the installer uses.
# The members' page is built here, so servers never need Node.js.
set -euo pipefail
cd "$(dirname "$0")/.."
version=$(sed -n "s/^VERSION = '\(.*\)'/\1/p" backend/community/store.py)
[[ -n $version ]] || { echo "No VERSION in backend/community/store.py" >&2; exit 1; }
[[ $(node -p "require('./frontend/package.json').version") == "$version" ]] || { echo "frontend/package.json version differs from $version" >&2; exit 1; }

# Only tracked files are packed, so a new file git does not know about would silently be missing.
untracked=$(git ls-files --others --exclude-standard -- backend deploy docs frontend nkn tests scripts)
[[ -z $untracked ]] || { printf 'Not tracked by git, so it would be left out of the release:\n%s\n' "$untracked" >&2; exit 1; }

npm --prefix frontend ci --no-audit --no-fund >/dev/null
npm --prefix frontend run build >/dev/null

name=arynwood-grove-$version
stage=$(mktemp -d); trap 'rm -rf "$stage"' EXIT
mkdir "$stage/$name"
# Tracked files only (no .env, data, wallets or node_modules), plus the built page.
git ls-files -z -- backend deploy docs frontend nkn tests scripts LICENSE README.md requirements.txt requirements-dev.txt .env.example setup.sh start.sh \
  | tar --null -T - -cf - | tar -xf - -C "$stage/$name"
cp -r frontend/dist "$stage/$name/frontend/dist"
echo "$version" >"$stage/$name/VERSION"

mkdir -p release
tar --owner=0 --group=0 --sort=name -czf "release/$name.tar.gz" -C "$stage" "$name"
(cd release && sha256sum "$name.tar.gz" >"$name.tar.gz.sha256" \
  && cp "$name.tar.gz" arynwood-grove.tar.gz && sha256sum arynwood-grove.tar.gz >arynwood-grove.tar.gz.sha256)
# The one-line install command fetches this from the latest release, not from the main branch.
cp deploy/install.sh release/install.sh
echo "release/$name.tar.gz"
