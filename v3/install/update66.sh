#!/bin/sh
# update66.sh check DIR | apply DIR   update the 3.0 firmware in the flash from an update package.
#
# Package (tc100-<version>-update.tar, made by v3/build-release.sh): VERSION, stack.sqfs, c66.img, c66rd.gz and
# MD5SUMS. "check" verifies it (md5, sizes, partitions). "apply" runs from a copy in RAM (the user space it replaces
# is the squashfs being rewritten): it stops the services, writes stack, kernel and initrd with flashw (md5 checked
# before and after each write), and restarts. The settings (cfga/cfgb) and the vendor libraries (vendor) are kept.
# If something goes wrong half way, the flash system may not start: an SD card with the 3.0 package
# (tc100test/c66.img) starts the camera, and Settings -> Install to flash writes everything again.
# Status: /tmp/update66.status (one line) and, with a card, tc100-3/update66.log.
ST=/tmp/update66.status
part_size() { for d in /sys/class/mtd/mtd[0-9]*; do case $d in *ro) continue;; esac; [ "$(cat $d/name)" = "$1" ] && { cat $d/size; return 0; }; done; return 1; }
say() { echo "$*" > $ST; echo "update66: $*" > /dev/console; [ -n "$LOG" ] && echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
LOG=; grep -q ' /mnt/sd vfat ' /proc/mounts && mkdir -p /mnt/sd/tc100-3 2>/dev/null && LOG=/mnt/sd/tc100-3/update66.log

check() {
	D=$1
	[ -f /tmp/flashmode ] || { echo "the camera is not running from its flash (trial mode: copy the new package to the card instead)"; return 1; }
	# the first, hand-made flash layout (2026-10-24) has the vendor libraries inside a 3.7 MiB "stack" and no "vendor"
	# partition: the packaged stack.sqfs has no vendor files, so writing it there would leave the camera without video
	part_size vendor >/dev/null || { echo "this camera has the first flash layout (no vendor partition): a web update would remove its vendor libraries. Copy the new SD package to the card (keep its lib/ folder), start the camera from it, then Settings -> Update & backup -> Install to flash"; return 1; }
	for f in VERSION stack.sqfs c66.img c66rd.gz MD5SUMS; do [ -f "$D/$f" ] || { echo "$f is missing from the package"; return 1; }; done
	( cd "$D" && md5sum -c MD5SUMS >/dev/null 2>&1 ) || { echo "the package is damaged (md5)"; return 1; }
	for p in stack:stack.sqfs kernel:c66.img initrd:c66rd.gz; do
		s=$(part_size ${p%%:*}) || { echo "no ${p%%:*} partition"; return 1; }
		[ "$(wc -c < "$D/${p#*:}")" -le "$s" ] || { echo "${p#*:} does not fit the ${p%%:*} partition"; return 1; }
	done
	[ "$(wc -c < "$D/c66rd.gz")" -eq 2012654 ] || { echo "c66rd.gz has not the size the boot commands load"; return 1; }
	head -c 6 "$D/c66rd.gz" | od -An -tx1 | grep -q 'fd 37 7a 58 5a 00' || { echo "c66rd.gz is not an xz image"; return 1; }
	echo ok
}

case "$1" in
check) check "$2"; exit $? ;;
apply) ;;
apply-ram) ;;
*) echo "usage: update66.sh check|apply DIR"; exit 2 ;;
esac
D=$2
if [ "$1" = apply ]; then
	r=$(check "$D") || { say "FAILED: $r"; exit 1; }
	# run from RAM: the squashfs under /mnt is about to be rewritten
	R=/tmp/upd66; rm -rf $R; mkdir -p $R
	cp "$0" $R/update66.sh && cp /mnt/v3/linux66-sd/flashw $R/flashw || { say "FAILED: copy to RAM"; exit 1; }
	exec /bin/sh $R/update66.sh apply-ram "$D"
fi

export PATH=/bin:/sbin:/usr/bin:/usr/sbin
say "installing $(cat "$D/VERSION"): stopping the services"
for s in recording motion-detection mqtt-bridge onvif auto-night-detection; do sh /mnt/controlscripts/$s stop >/dev/null 2>&1; done
killall tc100_rtsp monvifd 2>/dev/null
sleep 2; sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
BK=; [ -n "$LOG" ] && BK="-b /mnt/sd/tc100-3/backup"
for p in stack:stack.sqfs kernel:c66.img initrd:c66rd.gz; do
	f=$D/${p#*:}
	say "writing ${p%%:*} ($(wc -c < "$f") bytes), do not unplug the camera"
	m=$(md5sum < "$f" | cut -d' ' -f1)
	FLASHW_ALLOW="stack kernel initrd" sh /tmp/upd66/flashw -m "$m" $BK ${p%%:*} "$f" > /tmp/upd66/flashw.log 2>&1 || {
		[ -n "$LOG" ] && cat /tmp/upd66/flashw.log >> "$LOG"
		say "FAILED writing ${p%%:*}: the camera restarts; if it does not come back, start it with the 3.0 SD card and install again"
		sleep 5; reboot; exit 1; }
	[ -n "$LOG" ] && cat /tmp/upd66/flashw.log >> "$LOG"
done
say "DONE: $(cat "$D/VERSION") written, restarting"
sync; sleep 2
reboot
