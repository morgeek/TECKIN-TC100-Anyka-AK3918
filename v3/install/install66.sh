#!/bin/sh
# install66.sh check|run   install the 3.0 firmware into the SPI flash, from the trial mode on the SD card.
#
# Runs on Linux 6.6 started from the card (U-Boot sdload/sdboot: tc100test/c66.img). Writes, with flashw (allow-list,
# partition saved to tc100-3/backup first, md5 of each image checked before and after):
#   vendor  a squashfs of this camera's own vendor libraries (made here from lib/ of the card)
#   stack   tc100-3/stack.sqfs, the free user space
#   kernel  tc100test/c66.img
#   initrd  tc100test/c66rd.gz, last: U-Boot's flashcheck starts the flash system only once this area holds it
# then copies the settings of the card into the flash slots (cfg-persist), renames tc100test/c66.img to
# c66.img.installed (so that the next start is from the flash) and restarts.
# The way back at every step: rename tc100test/c66.img.installed to c66.img on the card, and the camera starts from
# the card again. U-Boot, its environment, "boot" and "mac" are never written here.
# Progress: tc100-3/install66.log on the card and /tmp/install66.status (one line, for the web page).
C=/mnt/sd
K=$C/tc100-3
LOG=$K/install66.log
ST=/tmp/install66.status
V=/mnt/v3
FLASHW=$V/linux66-sd/flashw
VENDOR_MAX=1048576

say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; echo "$*" > "$ST"; echo "install66: $*" > /dev/console; }
fail() { say "FAILED: $*"; exit 1; }
md5() { md5sum < "$1" | cut -d' ' -f1; }
want_md5() { cut -d' ' -f1 "$1.md5" 2>/dev/null; }
has_part() { for d in /sys/class/mtd/mtd[0-9]*; do case $d in *ro) continue;; esac; [ "$(cat $d/name)" = "$1" ] && return 0; done; return 1; }

# the sensor tuning in use (copied at boot from the card), else the card's copy
isp_src() { for f in /lib/firmware/anyka/isp.conf /mnt/config/isp_f23_mipi_2lane.conf; do [ -s $f ] && { echo $f; return 0; }; done; return 1; }

check() {
	[ -f /tmp/linux66 ] || { echo "not the 3.0 firmware"; return 1; }
	[ -f /tmp/flashmode ] && { echo "already running from the flash (use the update instead)"; return 1; }
	grep -q " $C vfat " /proc/mounts || { echo "no SD card"; return 1; }
	for p in kernel initrd stack vendor cfga cfgb; do has_part $p || { echo "the running kernel has no '$p' flash partition (start the kernel of this package)"; return 1; }; done
	for f in "$K/stack.sqfs" "$C/tc100test/c66.img" "$C/tc100test/c66rd.gz"; do
		[ -f "$f" ] || { echo "${f#$C/} is missing on the card"; return 1; }
		[ "$(want_md5 "$f")" = "$(md5 "$f")" ] || { echo "${f#$C/} does not match its md5"; return 1; }
	done
	[ -x /mnt/ext/bin/mksquashfs ] || { echo "mksquashfs is missing (ext/ of the package)"; return 1; }
	isp_src >/dev/null || { echo "the sensor tuning file of the camera is missing (config/isp_f23_mipi_2lane.conf on the card)"; return 1; }
	sh $V/install/collect-vendor.sh -c /mnt/lib >/dev/null || { echo "the camera's vendor libraries are not all in lib/ of the card (step 1 not done?)"; return 1; }
	echo ok
}

case "$1" in
check) check; exit $? ;;
run) ;;
*) echo "usage: install66.sh check|run"; exit 2 ;;
esac

mkdir -p "$K/backup"
r=$(check) || fail "$r"
say "install to flash: start ($(cat /mnt/VERSION 2>/dev/null))"

# the vendor partition image, built on the card (not in RAM)
W=$K/vendor-build; rm -rf "$W"; mkdir -p "$W/root/lib"
sh $V/install/collect-vendor.sh /mnt/lib "$W/root/lib" >> "$LOG" 2>&1 || fail "vendor libraries"
cp "$(isp_src)" "$W/root/isp.conf" || fail "sensor tuning"
mksquashfs "$W/root" "$K/vendor.sqfs" -comp xz -b 256K -noappend -all-root -quiet >> "$LOG" 2>&1 || fail "mksquashfs"
rm -rf "$W"
n=$(wc -c < "$K/vendor.sqfs"); [ "$n" -le $VENDOR_MAX ] || fail "vendor.sqfs is $n bytes, the partition has $VENDOR_MAX"
md5sum < "$K/vendor.sqfs" | sed 's/ .*/  vendor.sqfs/' > "$K/vendor.sqfs.md5"
say "vendor image: $n bytes"

# stop what reads the card or the flash heavily while writing (the polled SPI flash is slow, about a minute per MiB)
for s in recording motion-detection; do sh /mnt/controlscripts/$s stop >/dev/null 2>&1; done

w() {	# partition file
	say "writing $1 ($(wc -c < "$2") bytes)..."
	FLASHW_ALLOW="vendor stack kernel initrd" sh $FLASHW -m "$(md5 "$2")" -b "$K/backup" "$1" "$2" >> "$LOG" 2>&1 || fail "writing $1 (the card still starts the camera; see $LOG)"
}
w vendor "$K/vendor.sqfs"
w stack "$K/stack.sqfs"
w kernel "$C/tc100test/c66.img"
w initrd "$C/tc100test/c66rd.gz"

say "copying the settings of the card into the flash slots..."
CFG=/mnt/config sh $V/linux66-sd/cfg-persist save >> "$LOG" 2>&1 || say "WARNING: the settings were not saved to flash (they stay on the card; set them again after the restart)"

mv -f "$C/tc100test/c66.img" "$C/tc100test/c66.img.installed" && sync
say "DONE: restarting from the flash. The card is now only video storage. Way back: rename tc100test/c66.img.installed to c66.img."
sleep 3
reboot
