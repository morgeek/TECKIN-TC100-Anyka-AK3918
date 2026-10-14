#!/bin/sh
# Build the read-only firmware image (see scripts/rofs.sh): the git-tracked
# code directories as one squashfs file, plus its md5.
#
# Usage: src/release/build-image.sh [output-dir]     (default: dist/)
# Writes <output-dir>/firmware.sqfs and <output-dir>/firmware.sqfs.md5.
#
# gzip with 32 KiB blocks: on the ARM926 reading every file of the image took
# 8.8 s against 14.5 s with xz/64 KiB and 6.4 s straight from exFAT (measured
# 2026-10-14); lzo is not built into the camera kernel. The output is
# reproducible (fixed timestamps, root ownership).
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=${1:-dist}
case "$out" in /*) ;; *) out="$root/$out" ;; esac
command -v mksquashfs >/dev/null || { echo "mksquashfs not found (apt install squashfs-tools)" >&2; exit 1; }
mkdir -p "$out"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git ls-files -- bin lib www scripts controlscripts > "$tmp/files"
mkdir -p "$tmp/img"
while IFS= read -r f; do
  mkdir -p "$tmp/img/$(dirname "$f")"
  cp -p "$f" "$tmp/img/$f"
done < "$tmp/files"
cp VERSION "$tmp/img/VERSION"
# The SD card is FAT/exFAT mounted with fmask=0022: every file there is
# rwxr-xr-x, and the firmware relies on it (git tracks most binaries and CGIs
# as 0644). Give the image the same modes, or nothing in bin/ can run.
find "$tmp/img" -type d -exec chmod 755 {} +
find "$tmp/img" -type f -exec chmod 755 {} +
# Files the camera creates at runtime inside these directories:
#  - libcurl's SONAME link (autorun.sh self_heal_runtime checks this target);
#  - the patched PTT player, built from the vendor binary into RAM when /mnt/bin
#    is read-only (scripts/prepare-ptt-player.sh).
[ -e "$tmp/img/lib/libcurl.so.4" ] || ln -s /mnt/lib/libcurl.so.4.8.0 "$tmp/img/lib/libcurl.so.4"
[ -e "$tmp/img/bin/ak_ao_ptt" ] || ln -s /tmp/bin/ak_ao_ptt "$tmp/img/bin/ak_ao_ptt"
rm -f "$out/firmware.sqfs"
mksquashfs "$tmp/img" "$out/firmware.sqfs" -comp gzip -b 32768 -all-root -noappend \
  -no-xattrs -mkfs-time 0 -all-time 0 -quiet >/dev/null
(cd "$out" && md5sum firmware.sqfs > firmware.sqfs.md5)
echo "$out/firmware.sqfs: version $(cat VERSION), $(wc -l < "$tmp/files") files, $(wc -c < "$out/firmware.sqfs") bytes"
