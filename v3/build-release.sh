#!/bin/sh
# build-release.sh STACKOUT KERNEL INITRD ENVTOOL OUT
#   STACKOUT  output folder of v3/build-stack.sh (tree/, stack.sqfs)
#   KERNEL    uImage (zImage + DTB) of the 6.6 kernel        -> tc100test/c66.img
#   INITRD    initramfs from v3/build-rootfs66.sh (xz, padded) -> tc100test/c66rd.gz
#   ENVTOOL   v3/install/envtool.c built static for ARM
#   OUT       gets tc100-<version>-sd.zip (everything for the SD card) and tc100-<version>-update.tar (the web update)
# Only free files: the vendor libraries come from each camera at install (v3/install).
set -eu
S=${1:?usage: build-release.sh STACKOUT KERNEL INITRD ENVTOOL OUT}; K=${2:?kernel}; I=${3:?initrd}; E=${4:?envtool}; OUT=${5:?out}
REPO=$(cd "$(dirname "$0")/.." && pwd)
KERNEL_MAX=2097152 INITRD_SIZE=2012654
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
VER=$(head -n 1 "$S/tree/VERSION")
[ "$(wc -c < "$K")" -le $KERNEL_MAX ] || { echo "kernel does not fit the kernel partition" >&2; exit 1; }
[ "$(wc -c < "$I")" -eq $INITRD_SIZE ] || { echo "initramfs is not $INITRD_SIZE bytes (v3/build-rootfs66.sh pads it)" >&2; exit 1; }

# SD card: the user space as plain files (trial mode runs it from the card), the boot images, the stock-firmware hook
C=$OUT/sd; rm -rf "$C"; mkdir -p "$C"
cp -r "$S/tree/." "$C/"
cp "$K" "$C/tc100test/c66.img"; cp "$I" "$C/tc100test/c66rd.gz"
( cd "$C/tc100test" && md5sum c66.img > c66.img.md5 && md5sum c66rd.gz > c66rd.gz.md5 )
mkdir -p "$C/wifitest" "$C/tc100-3"
cp "$REPO/v3/install/stock-hook.sh" "$C/wifitest/wifi_test.sh"
cp "$E" "$C/tc100-3/envtool"; cp "$REPO/v3/install/known-stock.txt" "$C/tc100-3/"
cp "$S/stack.sqfs" "$S/stack.sqfs.md5" "$C/tc100-3/"
cp "$REPO/v3/install/README-SD.txt" "$C/README-3.0.txt"
cp "$REPO/v3/install/LISEZ-MOI.txt" "$C/00-LISEZ-MOI-READ-ME.txt"	# first in the listing: card layout, LEDs, address
chmod 755 "$C/wifitest/wifi_test.sh" "$C/tc100-3/envtool"
rm -f "$OUT/tc100-$VER-sd.zip"; ( cd "$C" && zip -qr -X "$OUT/tc100-$VER-sd.zip" . )

# web update: what the flash partitions stack, kernel and initrd receive
U=$OUT/update; rm -rf "$U"; mkdir -p "$U"
cp "$S/stack.sqfs" "$U/"; cp "$K" "$U/c66.img"; cp "$I" "$U/c66rd.gz"; cp "$S/tree/VERSION" "$U/"
( cd "$U" && md5sum stack.sqfs c66.img c66rd.gz VERSION > MD5SUMS && tar cf "$OUT/tc100-$VER-update.tar" VERSION stack.sqfs c66.img c66rd.gz MD5SUMS )
ls -l "$OUT"/*.zip "$OUT"/*.tar
