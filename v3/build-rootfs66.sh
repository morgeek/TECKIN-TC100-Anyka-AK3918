#!/bin/sh
# Build the Linux 6.6 test initramfs of the V3 firmware from our Buildroot base
# (v3/buildroot: musl, busybox, dropbear, wpa_supplicant), cpio.gz as built by CI:
#   - replaces the boot script with v3/S39tc100-linux66 (SD card, Wi-Fi, password, V3 services)
#   - drops the Linux 4.4 kernel modules (the 6.6 kernel has Wi-Fi, SD and USB built in)
#   - locks the default root password of the OpenIPC image (set from config/user.pwd at boot)
# Needs root (device nodes in the archive) and cpio, gzip, xz.
# Usage: v3/build-rootfs66.sh in.cpio.gz [out.gz]
#   Output: xz with a 2 MiB dictionary (a bigger one makes the kernel run out of memory while unpacking), zero-padded
#   to INITRD_SIZE bytes (default 2012654): the U-Boot boot commands (SD and flash) pass this fixed size, and the
#   flash initrd partition holds it. Fails if the image is bigger.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
IN=${1:?usage: build-rootfs66.sh BASE-rootfs.cpio.gz [out.gz]}
OUT=${2:-oipcrd66.gz}
case "$IN" in /*) ;; *) IN=$PWD/$IN ;; esac
case "$OUT" in /*) ;; *) OUT=$PWD/$OUT ;; esac
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir "$W/rd"; cd "$W/rd"
gzip -dc "$IN" | cpio -id --quiet
install -m 755 "$HERE/S39tc100-linux66" etc/init.d/S39tc100
rm -rf lib/modules/4.4.302
# RAM-only: drop what the self-test does not need (see initramfs-prune.txt)
grep -vE '^(#|$)' "$HERE/initramfs-prune.txt" | while read -r f; do rm -rf "./$f"; done
# What the prune list moved to ext/ of the user space (build-stack.sh puts it there): links into /mnt/ext, which is the
# user space in both modes (flash: link to /rom/ext; SD: the card, mounted at /mnt by autorun-linux66.sh). A link costs no
# RAM and is dangling until then, as the program would be missing. dropbear has its own start script.
for b in aplay arecord amixer; do ln -sf /mnt/ext/bin/$b usr/bin/$b; done
ln -sfn /mnt/ext/share/alsa usr/share/alsa	# the ALSA configuration directory compiled into libasound
install -m 755 "$HERE/S50dropbear-linux66" etc/init.d/S50dropbear
# musl library search path, same content as autorun-linux66.sh writes: the moved libraries (ext/lib) are found by a
# rescue shell too, before autorun runs
for l in lib/ld-musl-*.so.1; do
  n=${l##*/ld-musl-}; printf '/lib\n/usr/lib\n/mnt/ext/lib\n' > "etc/ld-musl-${n%.so.1}.path"
done
# login shells (ssh, telnet, console): the tools of ext/ (curl, jq, iw, ...) on the PATH, and the CA bundle of curl
# (as autorun gives the services; without it curl over TLS exits 60)
printf 'export PATH="$PATH:/mnt/ext/bin"\nexport CURL_CA_BUNDLE=/mnt/ext/etc/ssl/certs/ca-certificates.crt\n' \
  > etc/profile.d/tc100-ext.sh
# the serial console is started by S39tc100 (login prompt, or a shell if tc100test/consoleshell exists)
sed -i '/ttySAK0/d' etc/inittab
# default password of the OpenIPC image: lock it, S39tc100 sets the real one
sed -i 's|^root:[^:]*:|root:*:|' etc/shadow
# no credentials of any kind may be baked in
if grep -qE '^(psk|ssid)=' etc/wpa_supplicant.conf 2>/dev/null; then
  : > etc/wpa_supplicant.conf
fi
INITRD_SIZE=${INITRD_SIZE:-2012654}
find . | cpio -o -H newc --quiet | xz -9 --check=crc32 --lzma2=dict=2MiB > "$OUT.tmp"
n=$(wc -c < "$OUT.tmp")
[ "$n" -le "$INITRD_SIZE" ] || { echo "initramfs is $n bytes, more than $INITRD_SIZE" >&2; rm -f "$OUT.tmp"; exit 1; }
head -c $((INITRD_SIZE - n)) /dev/zero >> "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
echo "initramfs: $n bytes of xz, padded to $(wc -c < "$OUT") (initrd=0x81000000,$INITRD_SIZE)"
