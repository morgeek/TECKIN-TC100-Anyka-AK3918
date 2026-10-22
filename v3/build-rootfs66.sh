#!/bin/sh
# Build the Linux 6.6 test initramfs of the V3 firmware from the OpenIPC one
# shipped in openipc_sd_kit/ (musl userland, busybox, dropbear, wpa_supplicant):
#   - replaces the boot script with v3/S39tc100-linux66 (SD card, Wi-Fi, password, V3 services)
#   - drops the Linux 4.4 kernel modules (the 6.6 kernel has Wi-Fi, SD and USB built in)
#   - locks the default root password of the OpenIPC image (set from config/user.pwd at boot)
# Needs root (device nodes in the archive) and cpio, gzip.
# Usage: v3/build-rootfs66.sh [in.gz] [out.gz]
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
IN=${1:-$HERE/../openipc_sd_kit/tc100test/oipcrd.gz}
OUT=${2:-oipcrd66.gz}
case "$IN" in /*) ;; *) IN=$PWD/$IN ;; esac
case "$OUT" in /*) ;; *) OUT=$PWD/$OUT ;; esac
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir "$W/rd"; cd "$W/rd"
gzip -dc "$IN" | cpio -id --quiet
install -m 755 "$HERE/S39tc100-linux66" etc/init.d/S39tc100
rm -rf lib/modules/4.4.302
# default password of the OpenIPC image: lock it, S39tc100 sets the real one
sed -i 's|^root:[^:]*:|root:*:|' etc/shadow
# no credentials of any kind may be baked in
if grep -qE '^(psk|ssid)=' etc/wpa_supplicant.conf 2>/dev/null; then
  : > etc/wpa_supplicant.conf
fi
find . | cpio -o -H newc --quiet | gzip -9 > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
ls -l "$OUT"
echo "initrd size for bootargs: $(wc -c < "$OUT")"
