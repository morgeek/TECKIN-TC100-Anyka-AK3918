#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN_DIR="$REPO_ROOT/bin"
LIB_DIR="$REPO_ROOT/lib"

extract_version() {
  local f="$1"
  strings "$f" | grep -E -m1 \
    'BusyBox v[0-9]+\.[0-9]+\.[0-9]+|curl [0-9]+\.[0-9]+\.[0-9]+|OpenSSL [0-9]+\.[0-9]+\.[0-9]+|lighttpd/[0-9]+\.[0-9]+\.[0-9]+|FFmpeg version [0-9]+\.[0-9]+\.[0-9]+|libcurl/[0-9]+\.[0-9]+\.[0-9]+|[0-9]{4}\.[0-9]{2}\.[0-9]{2}|10\.[0-9]+ [0-9]{4}-[0-9]{2}-[0-9]{2}' \
    || true
}

echo "## bin/"
for f in "$BIN_DIR"/*; do
  [[ -f "$f" ]] || continue
  b="$(basename "$f")"
  v="$(extract_version "$f")"
  if [[ -n "$v" ]]; then
    printf '%-24s %s\n' "$b" "$v"
  else
    printf '%-24s %s\n' "$b" "-"
  fi
done

echo
echo "## lib/"
for f in "$LIB_DIR"/*; do
  [[ -f "$f" ]] || continue
  b="$(basename "$f")"
  v="$(extract_version "$f")"
  if [[ -n "$v" ]]; then
    printf '%-24s %s\n' "$b" "$v"
  else
    printf '%-24s %s\n' "$b" "-"
  fi
done
