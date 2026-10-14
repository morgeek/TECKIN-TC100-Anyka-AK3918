#!/bin/sh
# Build a firmware update package for Settings → Firmware update (update.cgi /
# scripts/fw-update.sh): the SD-card payload tracked by git, plus MANIFEST.
#
# Usage: src/release/build-update.sh [output.tar]
# Default output: dist/tc100-update-<VERSION>.tar
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
ver=$(cat VERSION)
out=${1:-dist/tc100-update-$ver.tar}
case "$out" in /*) ;; *) out="$root/$out" ;; esac
mkdir -p "$(dirname "$out")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# Payload = what goes on the SD card root (see README "Repository Structure").
git ls-files -- autorun.sh VERSION README.md wpa_supplicant.conf.dist \
    bin lib www scripts controlscripts config sounds > "$tmp/files"
while IFS= read -r f; do
  mkdir -p "$tmp/pkg/$(dirname "$f")"
  cp -p "$f" "$tmp/pkg/$f"
done < "$tmp/files"
# Read-only firmware image (scripts/rofs.sh) when squashfs-tools is installed;
# without it the package still works, the camera keeps running from FAT.
if [ "${NO_IMAGE:-0}" != 1 ] && command -v mksquashfs >/dev/null 2>&1; then
  sh src/release/build-image.sh "$tmp/pkg" >/dev/null
  printf '%s\n' firmware.sqfs firmware.sqfs.md5 >> "$tmp/files"
else
  echo "note: no firmware.sqfs in the package (mksquashfs missing or NO_IMAGE=1)" >&2
fi
(cd "$tmp/pkg" && while IFS= read -r f; do md5sum "$f"; done < "$tmp/files" > MANIFEST)
(cd "$tmp/pkg" && tar -cf "$out" MANIFEST $(cat "$tmp/files"))
n=$(wc -l < "$tmp/files")
echo "$out: version $ver, $n files, $(wc -c < "$out") bytes"
