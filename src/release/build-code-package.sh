#!/bin/sh
# Build the code package for cameras running from flash (Settings → Firmware
# update, a .bin): the git-tracked code — autorun.sh VERSION scripts
# controlscripts www sounds config (without config/ssl) — in the format of
# src/flash/build-code.sh. Needs no cross toolchain (no binaries inside).
#
# Usage: src/release/build-code-package.sh [out.bin]
# Default: dist/tc100-code-<VERSION>.bin
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
ver=$(head -n 1 VERSION)
out=${1:-dist/tc100-code-$ver.bin}
case "$out" in /*) ;; *) out="$root/$out" ;; esac
mkdir -p "$(dirname "$out")"
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
git ls-files -- autorun.sh VERSION scripts controlscripts www sounds config | grep -v '^config/ssl/' |
while IFS= read -r f; do
  mkdir -p "$w/code/$(dirname "$f")"; cp -p "$f" "$w/code/$f"
done
# autorun.sh runs these directly (a squashfs keeps the modes).
chmod -R 755 "$w/code/scripts" "$w/code/controlscripts" "$w/code/autorun.sh" "$w/code/config/autostart"
sh src/flash/build-code.sh "$w/code" "$out"
