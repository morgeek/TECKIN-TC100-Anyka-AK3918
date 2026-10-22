#!/bin/sh
# Build the squashfs (xz) root filesystem for the flash image of the Linux 6.6 firmware.
# Same base as build-rootfs66.sh (our Buildroot musl userland), then:
#   - removes what v3/rootfs-prune.txt lists (OpenIPC web UI, UBI/NAND tools, ...)
#   - adds the V3 payload: www, scripts, controlscripts, config skeleton (never user.pwd/credentials)
#   - squashfs, xz, 128 KiB blocks, no xattrs
# The result is loaded to RAM by U-Boot as an initrd (root=/dev/ram0 rootfstype=squashfs), so only
# the compressed image sits in RAM.  Needs root (device nodes), cpio, gzip, mksquashfs.
# Usage: v3/build-flash-rootfs66.sh in.cpio.gz [out.sqsh]
set -eu
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$HERE/..
IN=${1:?usage: build-flash-rootfs66.sh BASE-rootfs.cpio.gz [out.sqsh]}
OUT=${2:-rootfs66.sqsh}
case "$IN" in /*) ;; *) IN=$PWD/$IN ;; esac
case "$OUT" in /*) ;; *) OUT=$PWD/$OUT ;; esac
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir "$W/rd"; cd "$W/rd"
gzip -dc "$IN" | cpio -id --quiet
install -m 755 "$HERE/S39tc100-linux66" etc/init.d/S39tc100
rm -rf lib/modules/4.4.302
# the serial console is started by S39tc100 (login prompt, or a shell if tc100test/consoleshell exists)
sed -i '/ttySAK0/d' etc/inittab
sed -i 's|^root:[^:]*:|root:*:|' etc/shadow
if grep -qE '^(psk|ssid)=' etc/wpa_supplicant.conf 2>/dev/null; then : > etc/wpa_supplicant.conf; fi
grep -v '^#' "$HERE/rootfs-prune.txt" | grep -v '^$' | while read -r p; do rm -rf "./$p"; done
# V3 payload (read-only part); user data stays on the SD card
mkdir -p opt/v3
cp -a "$REPO/www" opt/v3/www
cp -a "$REPO/scripts" opt/v3/scripts
cp -a "$REPO/controlscripts" opt/v3/controlscripts
mkdir -p opt/v3/config
for f in "$REPO"/config/*; do
  case "$f" in *.pwd|*.pwd.dist|*wpa_supplicant*) continue ;; esac
  cp -a "$f" opt/v3/config/
done
# streaming binaries (statically useful ones only; the vendor media libraries are not needed by the V4L2 path)
mkdir -p opt/v3/bin
for b in "$REPO/bin/tc100_streamer" "$REPO/thingino_port/bin/thingino-rtsp-server"; do
  [ -f "$b" ] && install -m 755 "$b" opt/v3/bin/
done
find opt/v3 -name '*.pwd' -o -name 'wpa_supplicant.conf' | grep . && { echo "credentials in payload" >&2; exit 1; } || true
rm -f "$OUT"
mksquashfs . "$OUT" -comp xz -b 131072 -no-xattrs -noappend -all-root -quiet
ls -l "$OUT"
