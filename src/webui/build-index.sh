#!/bin/sh
# Build www/scripts/index.bundle.min.js (the web UI main script, served as is)
# from src/webui/index/*.js, concatenated in name order. The parts share one
# function scope (00-state.js opens it, 99-api.js closes it), so they are not
# standalone scripts. The regression tests fail when the bundle and the parts
# differ: edit the parts, run this, commit both.
#   src/webui/build-index.sh [--check]
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
out="$root/www/scripts/index.bundle.min.js"
tmp=$(mktemp -d)/index.js; trap 'rm -rf "${tmp%/*}"' EXIT
cat "$root"/src/webui/index/[0-9][0-9]-*.js > "$tmp"
if [ "${1:-}" = --check ]; then
  cmp -s "$tmp" "$out" || { echo "www/scripts/index.bundle.min.js is not built from src/webui/index (run src/webui/build-index.sh)" >&2; exit 1; }
  exit 0
fi
command -v node >/dev/null 2>&1 && node --check "$tmp"
cp "$tmp" "$out"
echo "$out: $(wc -l < "$out") lines"
