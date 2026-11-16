#!/bin/sh
# install66.sh check|run   install the 3.0 firmware into the SPI flash, from the trial mode on the SD card.
#
# Runs on Linux 6.6 started from the card (U-Boot sdload/sdboot: tc100test/c66.img). Writes, with flashw (allow-list,
# partition saved to tc100-3/backup first when no verified full flash-stock.bin exists on the card, md5 of each image
# checked before and after):
#   vendor  a squashfs of this camera's sensor tuning file (isp.conf, ~12 KB; no vendor libraries since 3.0.1-rc35)
#   stack   tc100-3/stack.sqfs, the free user space
#   kernel  tc100test/c66.img
#   initrd  tc100test/c66rd.gz, last: U-Boot's flashcheck starts the flash system only once this area holds it
# then copies the settings of the card into the flash slots (cfg-persist) unless the flash already holds settings
# (a camera that ran 3.0 before keeps its own), renames tc100test/c66.img to
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
. "${INSTALL66_LIB:-$V/install}/imgcheck.sh"
has_part() { for d in /sys/class/mtd/mtd[0-9]*; do case $d in *ro) continue;; esac; [ "$(cat $d/name)" = "$1" ] && return 0; done; return 1; }

# a vendor image made off the camera (tc100-3/vendor.sqfs + .md5 and the marker vendor.sqfs.prebuilt): used when
# mksquashfs cannot run on the camera (squashfs-tools before the 32 MB patch refuse to start with 45 MB of RAM)
prebuilt() { [ -f "$K/vendor.sqfs.prebuilt" ] && [ -s "$K/vendor.sqfs" ] && [ "$(want_md5 "$K/vendor.sqfs")" = "$(md5 "$K/vendor.sqfs")" ]; }

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
	# the same image checks as the web update (v3/install/imgcheck.sh): a kernel that does not start cannot be put right from Linux
	r=$(kernel_img_check "$C/tc100test/c66.img") || { echo "$r"; return 1; }
	r=$(initrd_img_check "$C/tc100test/c66rd.gz") || { echo "$r"; return 1; }
	[ "$(head -c 4 "$K/stack.sqfs")" = hsqs ] || { echo "tc100-3/stack.sqfs is not a squashfs image"; return 1; }
	[ -x /mnt/ext/bin/mksquashfs ] || prebuilt || { echo "mksquashfs is missing (ext/ of the package)"; return 1; }
	# the hardware must be a known variant (board profile), the flash chip identified by the kernel: else nothing
	# is written (the inventory is made at each start, while the kernel log still has the sensor id)
	[ -s /tmp/inventory.txt ] || sh $V/install/inventory.sh --quick > /tmp/inventory.txt 2>/dev/null
	hw=$(HWCHECK_FLASH_ID=1 sh $V/install/hwcheck.sh /tmp/inventory.txt $V/board) || { echo "this camera is not a TC100 variant the firmware knows ($hw); nothing is written. Please send the page http://<camera>/cgi-bin/inventory.cgi in a GitHub issue (Hardware inventory)"; return 1; }
	isp_src >/dev/null || { echo "the sensor tuning file of the camera is missing (config/isp_f23_mipi_2lane.conf on the card)"; return 1; }
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

# the vendor partition image, built on the card (not in RAM): holds only this camera's sensor tuning (isp.conf, ~12 KB
# compressed; no vendor libraries are needed or packaged since 3.0.1-rc35)
W=$K/vendor-build; rm -rf "$W"; mkdir -p "$W/root"
cp "$(isp_src)" "$W/root/isp.conf" || fail "sensor tuning"
if /mnt/ext/bin/mksquashfs "$W/root" "$K/vendor.new" -comp xz -b 256K -noappend -all-root -quiet -processors 1 -mem 8M >> "$LOG" 2>&1; then
	mv -f "$K/vendor.new" "$K/vendor.sqfs"; rm -f "$K/vendor.sqfs.prebuilt"
elif prebuilt; then
	rm -f "$K/vendor.new"; say "mksquashfs cannot run here: using the prebuilt tc100-3/vendor.sqfs"
else
	fail "mksquashfs (and no prebuilt tc100-3/vendor.sqfs)"
fi
rm -rf "$W"
n=$(wc -c < "$K/vendor.sqfs"); [ "$n" -le $VENDOR_MAX ] || fail "vendor.sqfs is $n bytes, the partition has $VENDOR_MAX"
md5sum < "$K/vendor.sqfs" | sed 's/ .*/  vendor.sqfs/' > "$K/vendor.sqfs.md5"
say "vendor image: $n bytes"

# room on the card, checked before anything is stopped or written: the backups (-b, every partition, unless the stock copy
# covers them: counted anyway, conservative) and the read-back below, which writes one whole partition (the largest) to the
# card, plus 1 MiB. INSTALL66_SD_FREE_KB is a test hook.
sz_sum=0; sz_max=0
for _p in vendor stack kernel initrd; do
	for d in /sys/class/mtd/mtd[0-9]*; do case $d in *ro) continue;; esac; [ "$(cat $d/name)" = $_p ] && _s=$(cat $d/size); done
	sz_sum=$((sz_sum + _s / 1024)); [ $((_s / 1024)) -gt $sz_max ] && sz_max=$((_s / 1024))
done
need=$((sz_sum + sz_max + 1024))
free=${INSTALL66_SD_FREE_KB:-$(df -k $C 2>/dev/null | tail -n 1 | awk '{ print $(NF - 2) }')}
case "$free" in ''|*[!0-9]*) ;; *) [ "$free" -ge "$need" ] || fail "the SD card has $((free / 1024)) MiB free, the install needs $((need / 1024)) MiB (backups and the read-back check): free some space on the card" ;; esac

# stop what reads the card or the flash heavily while writing (the polled SPI flash is slow, about a minute per MiB)
# and what takes the most memory (the camera restarts at the end): the same list as the web update. With only the
# first two stopped, a camera in trial mode restarted in the middle of writing the stack (2026-10-29).
# halt, not stop, for the services whose stop is a setting (REC_LOCAL=0, mdenabled=0, daynight=3, kept for good: after the
# rc29 update both cameras came back without automatic day / night and the .24 without its recording)
for s in recording motion-detection auto-night-detection; do sh /mnt/controlscripts/$s halt >/dev/null 2>&1; done
for s in rtsp-h26x mqtt-bridge onvif; do sh /mnt/controlscripts/$s stop >/dev/null 2>&1; done
killall tc100_rtsp tc100-onvifd 2>/dev/null
# the scheduled-reboot entry of crond and the reset button (hold 8 s = reboot) would restart the camera in the middle of
# a flash write: both stop with the services (the camera restarts at the end of the run; a failed run puts them back
# (restore_guards, EXIT trap))
CROND_WAS=$(pidof crond)
GUARDS_OFF=1
# a failed install (fail(), any exit but the final restart) puts them back, best effort
restore_guards() {
	[ -n "$GUARDS_OFF" ] && [ -z "$INSTALL_DONE" ] || return 0
	[ -n "$CROND_WAS" ] && crond -c /mnt/config/cron/crontabs </dev/null >/dev/null 2>&1
	sh /mnt/controlscripts/button-actions start >/dev/null 2>&1
}
trap restore_guards EXIT
killall crond 2>/dev/null
sh /mnt/controlscripts/button-actions stop >/dev/null 2>&1
for p in $(ps 2>/dev/null | awk '/button-watch\.sh/ && !/awk/ { print $1 }'); do kill "$p" 2>/dev/null; done
sleep 2; sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
for p in $(pidof watchdog); do echo -1000 > /proc/$p/oom_score_adj 2>/dev/null; done
say "free memory before writing: $(awk '$1 == "MemAvailable:" { print $2 }' /proc/meminfo) KB"

# First install only: when the verified 8 MiB stock flash copy (tc100-3/backup/flash-stock.bin) is on the card and
# the flash still holds the stock firmware, every partition we write (vendor, stack, kernel, initrd) is already saved
# inside it: skip the redundant 5.7 MiB per-partition SPI read-back backup (-b), saving ~1.5 min. restore-stock.sh
# --check only compares the boot and mac areas, so a camera that already runs 3.0 from its flash (valid cfga/cfgb
# slot) keeps -b: its 3.0 partitions are not in the stock copy.
BK="-b $K/backup"
if [ -z "$INSTALL66_FORCE_PART_BACKUP" ] && ! sh $V/linux66-sd/cfg-persist saved >/dev/null 2>&1 &&
	sh $V/install/restore-stock.sh --check >/dev/null 2>&1; then
	say "stock flash backup verified (tc100-3/backup/flash-stock.bin): skipping redundant per-partition read-back"
	BK=
fi

w() {	# partition file
	say "writing $1 ($(wc -c < "$2") bytes)..."
	# the md5 PUBLISHED with the image (file.md5, checked against the file by check() above), not one computed from
	# the file itself (that comparison could never fail); vendor.sqfs.md5 is made above, from the image just built
	_wm=$(want_md5 "$2"); [ -n "$_wm" ] || fail "no md5 file for ${2#$C/}"
	FLASHW_ALLOW="vendor stack kernel initrd" sh $FLASHW -m "$_wm" $BK "$1" "$2" >> "$LOG" 2>&1 || fail "writing $1 (the card still starts the camera; see $LOG)"
}
w vendor "$K/vendor.sqfs"
w stack "$K/stack.sqfs"
w kernel "$C/tc100test/c66.img"
w initrd "$C/tc100test/c66rd.gz"

# R18: the restart below is deliberate; the intent lands in /mnt/config/log, which the first boot from the flash reads
# when the settings of the card are copied below (a camera that keeps its flash settings keeps its own history)
[ -f /mnt/scripts/reboot-tracker.sh ] && REBOOT_TRACKER_DIR=/mnt/config/log sh /mnt/scripts/reboot-tracker.sh intent "SD install of $(cat /mnt/VERSION 2>/dev/null || echo 3.0)" >/dev/null 2>&1
# A camera that already ran 3.0 from its flash keeps its own settings: the cfga/cfgb slots sit at the same place in
# every layout and this install does not write them. Only a first install (no valid slot) takes the card's settings,
# or a card with tc100-3/settings-from-card (the user asks for the card's settings).
if s=$(sh $V/linux66-sd/cfg-persist saved 2>/dev/null) && [ ! -f "$K/settings-from-card" ]; then
	say "the settings already in the flash are kept ($s)"
else
	say "copying the settings of the card into the flash slots..."
	CFG=/mnt/config sh $V/linux66-sd/cfg-persist save >> "$LOG" 2>&1 || say "WARNING: the settings were not saved to flash (they stay on the card; set them again after the restart)"
fi

# the card kernel is renamed (= the next start is from the flash) only once every partition reads back as written: a
# second, independent read of each (written to the card: a stack image would not fit the RAM disk) against its published md5 (flashw already did one), else the card keeps starting the camera
for _p in vendor:$K/vendor.sqfs stack:$K/stack.sqfs kernel:$C/tc100test/c66.img initrd:$C/tc100test/c66rd.gz; do
	_f=${_p#*:}; _sz=$(wc -c < "$_f")
	_got=$(sh $FLASHW -r "${_p%%:*}" "$K/rb66.bin" >/dev/null 2>&1 && head -c "$_sz" "$K/rb66.bin" | md5sum | cut -d' ' -f1); rm -f "$K/rb66.bin"
	[ -n "$_got" ] && [ "$_got" = "$(want_md5 "$_f")" ] || fail "read-back of ${_p%%:*} does not match (the card still starts the camera; see $LOG)"
done
mv -f "$C/tc100test/c66.img" "$C/tc100test/c66.img.installed" && sync
say "DONE: restarting from the flash. The card is now only video storage. Way back: rename tc100test/c66.img.installed to c66.img."
INSTALL_DONE=1
sleep 3
reboot
