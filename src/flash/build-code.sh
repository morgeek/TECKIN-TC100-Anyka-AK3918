#!/bin/sh
# Build a code package for the code zone of the flash firmware
# (scripts/flash-code.sh): a 4 KB text header + a squashfs (xz) of the code
# taken from a /usr/tc100 staging directory (src/flash/stage-tc100.sh).
#
# Usage: src/flash/build-code.sh <tc100-dir> <out.bin>
set -eu
src=$(cd "$1" && pwd); out=$2
max=$(( 159 * 4096 ))
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
mkdir "$w/code"
for d in autorun.sh VERSION scripts controlscripts www sounds config; do
  [ -e "$src/$d" ] && cp -a "$src/$d" "$w/code/"
done
# The RTSP server fixes, so that a code package can update them without a
# system package (controlscripts/rtsp-h26x prefers this copy).
if [ -f "$src/lib/libtc100fix.so" ]; then
  mkdir -p "$w/code/lib" && cp -a "$src/lib/libtc100fix.so" "$w/code/lib/"
fi
# The filtered syslog forwarder (scripts/common_functions.sh syslogd_start
# prefers /tmp/tc100code/bin): new in 2.1.5, so not in older /usr images.
for b in tc100-logfwd hostapd-rtw; do
  # hostapd-rtw: the Wi-Fi rescue access point (scripts/wifi-rescue.sh) on
  # the flash /usr, which has no vendor hostapd.
  if [ -f "$src/bin/$b" ]; then
    mkdir -p "$w/code/bin" && cp -a "$src/bin/$b" "$w/code/bin/"
  fi
done
mksquashfs "$w/code" "$w/code.sqsh" -comp xz -b 131072 -all-root -noappend -no-xattrs -quiet >/dev/null
size=$(wc -c < "$w/code.sqsh" | tr -d ' ')
[ "$size" -le "$max" ] || { echo "error: code image $size bytes, the zone holds $max" >&2; exit 1; }
md5=$( (md5sum "$w/code.sqsh" 2>/dev/null || md5 -r "$w/code.sqsh") | cut -d' ' -f1)
ver=$(head -n 1 "$src/VERSION" 2>/dev/null || true)
# Build identity, shown by the web page before installing: two packages with
# the same version can then be told apart (BUILD_COMMIT / BUILD_DATE override).
built=${BUILD_DATE:-$(date -u +%Y-%m-%dT%H:%MZ)}
commit=${BUILD_COMMIT:-}
if [ -z "$commit" ]; then
  repo=$(cd "$(dirname "$0")/../.." && pwd)
  commit=$(git -C "$repo" rev-parse --short=10 HEAD 2>/dev/null || true)
  [ -n "$commit" ] && [ -n "$(git -C "$repo" status --porcelain --untracked-files=no 2>/dev/null)" ] && commit="$commit+dirty"
fi
printf 'TC100CODE 1\nsize %s\nmd5 %s\nversion %s\nbuilt %s\n' "$size" "$md5" "${ver:-unknown}" "$built" > "$w/hdr"
[ -n "$commit" ] && printf 'commit %s\n' "$commit" >> "$w/hdr"
dd if="$w/hdr" of="$w/hdr4k" bs=4096 count=1 conv=sync 2>/dev/null
cat "$w/hdr4k" "$w/code.sqsh" > "$out"
echo "$out: code ${ver:-unknown}, $size bytes (zone: $max), md5 $md5, built $built${commit:+, commit $commit}"
