#!/bin/sh
# build-release.sh STACKOUT KERNEL INITRD ENVTOOL OUT
#   STACKOUT  output folder of v3/build-stack.sh (tree/, stack.sqfs)
#   KERNEL    uImage (zImage + DTB) of the 6.6 kernel        -> tc100test/c66.img
#   INITRD    initramfs from v3/build-rootfs66.sh (xz, padded) -> tc100test/c66rd.gz
#   ENVTOOL   v3/install/envtool.c built static for ARM
#   OUT       gets tc100-<version>-sd.zip (everything for the SD card) and tc100-<version>-update.tar (the web update)
# Only free files: the camera's sensor tuning (isp.conf) comes from each camera at install (v3/install; no vendor libraries since 3.0.1-rc34).
set -eu
S=${1:?usage: build-release.sh STACKOUT KERNEL INITRD ENVTOOL OUT}; K=${2:?kernel}; I=${3:?initrd}; E=${4:?envtool}; OUT=${5:?out}
REPO=$(cd "$(dirname "$0")/.." && pwd)
KERNEL_MAX=2097152 INITRD_SIZE=2012654
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
VER=$(head -n 1 "$S/tree/VERSION")
[ "$(wc -c < "$K")" -le $KERNEL_MAX ] || { echo "kernel does not fit the kernel partition" >&2; exit 1; }
[ "$(wc -c < "$I")" -eq $INITRD_SIZE ] || { echo "initramfs is not $INITRD_SIZE bytes (v3/build-rootfs66.sh pads it)" >&2; exit 1; }

# Reproducible packages (item CI-PIN): with SOURCE_DATE_EPOCH (the CI sets it to the commit time) the zip and tar entries
# are in a fixed order, owned by root, and carry that time, so two builds of one commit give the same files. Without it: as before.
# mkzip DIR ZIP: everything in DIR. mktar TAR FILE...: the files of the current directory, in that order.
mkzip() {
	if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then ( cd "$1" && zip -qr -X "$2" . ); return; fi
	( cd "$1" && find . -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} + && find . -mindepth 1 | LC_ALL=C sort | TZ=UTC zip -qX "$2" -@ )
}
mktar() {
	t=$1; shift
	if [ -n "${SOURCE_DATE_EPOCH:-}" ] && tar --version 2>/dev/null | grep -q GNU; then
		tar --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner -cf "$t" "$@"
	else
		tar cf "$t" "$@"
	fi
}

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
rm -f "$OUT/tc100-$VER-sd.zip"; mkzip "$C" "$OUT/tc100-$VER-sd.zip"

# inventory package: only the read-only hardware inventory (the same hook stops after it: INVENTORY-ONLY), for owners
# of a TC100 that may differ from the tested one. Nothing of the firmware, nothing written to the camera.
N=$OUT/inventory; rm -rf "$N"; mkdir -p "$N/wifitest" "$N/v3/install" "$N/bin" "$N/tc100-3"
cp "$REPO/v3/install/stock-hook.sh" "$N/wifitest/wifi_test.sh"
cp "$REPO/v3/install/inventory.sh" "$REPO/v3/install/hwcheck.sh" "$N/v3/install/"
cp -r "$REPO/v3/board" "$N/v3/"; cp "$S/tree/bin/busybox" "$N/bin/"; cp "$S/tree/VERSION" "$N/"
cp "$REPO/v3/install/LISEZ-MOI-INVENTAIRE.txt" "$N/00-LISEZ-MOI-READ-ME.txt"
: > "$N/INVENTORY-ONLY"; chmod 755 "$N/wifitest/wifi_test.sh"
rm -f "$OUT/tc100-$VER-inventory.zip"; mkzip "$N" "$OUT/tc100-$VER-inventory.zip"

# web update: what the flash partitions stack, kernel and initrd receive
U=$OUT/update; rm -rf "$U"; mkdir -p "$U"
cp "$S/stack.sqfs" "$U/"; cp "$K" "$U/c66.img"; cp "$I" "$U/c66rd.gz"; cp "$S/tree/VERSION" "$U/"
# MD5SUMS stays for flashw (it compares the file with the md5 of the package). SHA256SUMS lists every file of the package,
# MD5SUMS included: it is the file the owner signs (docs/linux-port/upgrade-3.2/sign.md). The CI never holds a private key:
# SHA256SUMS.sig is NOT made here, an unsigned package is the normal CI output (scripts/sign_update.py adds the signature).
sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
( cd "$U" && md5sum stack.sqfs c66.img c66rd.gz VERSION > MD5SUMS && sha256_of VERSION stack.sqfs c66.img c66rd.gz MD5SUMS > SHA256SUMS && mktar "$OUT/tc100-$VER-update.tar" VERSION stack.sqfs c66.img c66rd.gz MD5SUMS SHA256SUMS )
ls -l "$OUT"/*.zip "$OUT"/*.tar
