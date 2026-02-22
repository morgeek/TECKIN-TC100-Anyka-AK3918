#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_LOCK_FILE="$REPO_ROOT/config/packages.lock.dist"

usage() {
  cat <<'EOF'
Usage: tools/build_hash_locked_dropin_bundle.sh <source_dir> <out_bundle_dir> [lock_file]

Builds a SAFE drop-in bundle from a source tree by copying only files that
match the baseline lock hashes exactly.

Expected source layout:
  <source_dir>/bin/<files...>
  <source_dir>/lib/<files...>

Default lock file:
  config/packages.lock.dist

Output:
  <out_bundle_dir>/bin/... and/or <out_bundle_dir>/lib/...
  <out_bundle_dir>/manifest.lock
  <out_bundle_dir>/report.txt
EOF
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "ERROR: missing required command: $cmd" >&2
    exit 2
  }
}

require_hash_cmd() {
  if command -v sha256sum >/dev/null 2>&1; then
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    return 0
  fi
  echo "ERROR: missing required command: sha256sum or shasum" >&2
  exit 2
}

hash_file() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  else
    shasum -a 256 "$f" | awk '{print $1}'
  fi
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 1
fi

require_cmd awk
require_cmd cp
require_cmd mkdir
require_cmd dirname
require_hash_cmd

SOURCE_DIR="$1"
OUT_DIR="$2"
LOCK_FILE="${3:-$DEFAULT_LOCK_FILE}"

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "ERROR: source dir not found: $SOURCE_DIR" >&2
  exit 1
fi

if [[ ! -f "$LOCK_FILE" ]]; then
  echo "ERROR: lock file not found: $LOCK_FILE" >&2
  exit 1
fi

mkdir -p "$OUT_DIR/bin" "$OUT_DIR/lib"
MANIFEST="$OUT_DIR/manifest.lock"
REPORT="$OUT_DIR/report.txt"
: > "$MANIFEST"
: > "$REPORT"

total=0
copied=0
missing=0
mismatch=0

while IFS='|' read -r rel expected_hash; do
  [[ -n "$rel" ]] || continue
  [[ "$rel" == \#* ]] && continue

  total=$((total + 1))
  src="$SOURCE_DIR/$rel"

  if [[ ! -f "$src" ]]; then
    echo "MISSING|$rel" >> "$REPORT"
    missing=$((missing + 1))
    continue
  fi

  actual_hash="$(hash_file "$src")"
  if [[ "$actual_hash" != "$expected_hash" ]]; then
    echo "MISMATCH|$rel|expected=$expected_hash|actual=$actual_hash" >> "$REPORT"
    mismatch=$((mismatch + 1))
    continue
  fi

  dst="$OUT_DIR/$rel"
  mkdir -p "$(dirname "$dst")"
  cp -p "$src" "$dst"
  echo "$rel|$actual_hash" >> "$MANIFEST"
  copied=$((copied + 1))
done < "$LOCK_FILE"

if [[ "$copied" -eq 0 ]]; then
  echo "ERROR: no lock-matching files were found in source dir." >&2
  echo "See report: $REPORT" >&2
  exit 1
fi

"$REPO_ROOT/tools/check_bundle_compat.sh" "$OUT_DIR"

echo "SAFE drop-in bundle built:"
echo "  source:   $SOURCE_DIR"
echo "  bundle:   $OUT_DIR"
echo "  lock:     $LOCK_FILE"
echo "  total:    $total"
echo "  copied:   $copied"
echo "  missing:  $missing"
echo "  mismatch: $mismatch"
echo "  manifest: $MANIFEST"
echo "  report:   $REPORT"
