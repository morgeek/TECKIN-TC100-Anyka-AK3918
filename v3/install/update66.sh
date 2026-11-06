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
# smallest number of bytes of the kernel partition that this camera's U-Boot reads ("sf read 0x82000000 0x39000 SIZE" in
# its environment, read-only here): 0x200000 for the card install, 0x1ce000 for the hand-made commands of 2026-10-24
kernel_load_max() {
	for d in /sys/class/mtd/mtd[0-9]*; do
		case $d in *ro) continue;; esac
		[ "$(cat $d/name)" = env ] || continue
		tr '\000' '\n' < /dev/${d##*/}ro 2>/dev/null | sed -n 's/.*sf read 0x82000000 0x39000 \(0x[0-9a-fA-F]*\).*/\1/p' |
			while read h; do echo $((h)); done | sort -n | head -n 1 | grep .
		return
	done
	return 1
}
say() { echo "$*" > $ST; echo "update66: $*" > /dev/console; [ -n "$LOG" ] && echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
# the md5 published in the package for a file (B3: flashw compares the file with THIS sum, not with itself)
sum_of() { awk -v f="$2" '$2 == f || $2 == "*" f { print $1; exit }' "$1/MD5SUMS" | grep -E '^[0-9a-fA-F]{32}$'; }
LOG=; grep -q ' /mnt/sd vfat ' /proc/mounts && mkdir -p /mnt/sd/tc100-3 2>/dev/null && LOG=/mnt/sd/tc100-3/update66.log

check() {
	D=$1
	[ -f /tmp/flashmode ] || { echo "the camera is not running from its flash (trial mode: copy the new package to the card instead)"; return 1; }
	# the first, hand-made flash layout (2026-10-24) has the vendor libraries inside a 3.7 MiB "stack" and no "vendor"
	# partition: the packaged stack.sqfs has no vendor files, so writing it there would leave the camera without video
	part_size vendor >/dev/null || { echo "this camera has the first flash layout (no vendor partition): a web update would remove its vendor libraries. Copy the new SD package to the card (keep its lib/ folder), start the camera from it, then Settings -> Update & backup -> Install to flash"; return 1; }
	for f in VERSION stack.sqfs c66.img c66rd.gz MD5SUMS; do [ -f "$D/$f" ] || { echo "$f is missing from the package"; return 1; }; done
	( cd "$D" && md5sum -c MD5SUMS >/dev/null 2>&1 ) || { echo "the package is damaged (md5)"; return 1; }
	for f in stack.sqfs c66.img c66rd.gz; do sum_of "$D" $f >/dev/null || { echo "MD5SUMS has no sum for $f"; return 1; }; done
	for p in stack:stack.sqfs kernel:c66.img initrd:c66rd.gz; do
		s=$(part_size ${p%%:*}) || { echo "no ${p%%:*} partition"; return 1; }
		[ "$(wc -c < "$D/${p#*:}")" -le "$s" ] || { echo "${p#*:} does not fit the ${p%%:*} partition"; return 1; }
	done
	[ "$(wc -c < "$D/c66rd.gz")" -eq 2012654 ] || { echo "c66rd.gz has not the size the boot commands load"; return 1; }
	head -c 6 "$D/c66rd.gz" | od -An -tx1 | grep -q 'fd 37 7a 58 5a 00' || { echo "c66rd.gz is not an xz image"; return 1; }
	# A kernel that does not start cannot be put right from Linux (U-Boot always loads the kernel partition, the
	# initramfs never runs): it is checked before anything is written. A uImage (bootm), complete (the data size of its
	# header), and not larger than what this camera's U-Boot reads from the flash.
	ks=$(wc -c < "$D/c66.img")
	head -c 4 "$D/c66.img" | od -An -tx1 | grep -q '27 05 19 56' || { echo "c66.img is not a U-Boot kernel image (uImage)"; return 1; }
	kd=$(dd if="$D/c66.img" bs=1 skip=12 count=4 2>/dev/null | od -An -tu1 | awk '{ print (($1 * 256 + $2) * 256 + $3) * 256 + $4 }')
	case "$kd" in ''|*[!0-9]*) echo "c66.img: unreadable uImage header"; return 1 ;; esac
	[ $((kd + 64)) -le "$ks" ] || { echo "c66.img is cut short ($ks bytes, its header announces $((kd + 64)))"; return 1; }
	kl=$(kernel_load_max) && [ "$ks" -gt "$kl" ] && { echo "c66.img ($ks bytes) is larger than the $kl bytes this camera's start commands read from the flash: it would not start. Install it from the SD card instead"; return 1; }
	[ "$(head -c 4 "$D/stack.sqfs")" = hsqs ] || { echo "stack.sqfs is not a squashfs image"; return 1; }
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
	# no SD card = no backup of what the flash holds now (flashw -b): only with an explicit confirmation (the web page
	# asks for it, update.cgi then sets UPDATE66_NOBACKUP=1), checked before anything is stopped (review 2026-11-06)
	if [ -z "$LOG" ] && [ "${UPDATE66_NOBACKUP:-0}" != 1 ]; then
		say "FAILED: no SD card for the backup of the flash; confirm the install without a backup (web page) or put a FAT32 card in the camera"
		exit 1
	fi
	# run from RAM: the squashfs under /mnt is about to be rewritten
	R=/tmp/upd66; rm -rf $R; mkdir -p $R
	cp "$0" $R/update66.sh && cp /mnt/v3/linux66-sd/flashw $R/flashw || { say "FAILED: copy to RAM"; exit 1; }
	exec /bin/sh $R/update66.sh apply-ram "$D"
fi

export PATH=/bin:/sbin:/usr/bin:/usr/sbin
say "installing $(cat "$D/VERSION"): stopping the services"
# the same list as install66.sh, and what restarts services (audit 2026-11-04 B4: the housekeeper brought tc100_rtsp
# back from the stack partition being erased, 2026-10-29; net-guard, one of its jobs, may reboot in the middle)
sh /mnt/scripts/housekeeper.sh stop >/dev/null 2>&1
for p in $(ps 2>/dev/null | awk '/web-guard\.sh run/ && !/awk/ { print $1 }'); do kill "$p" 2>/dev/null; done
# halt, not stop, for the services whose stop is a setting (REC_LOCAL=0, mdenabled=0, daynight=3, kept for good: after the
# rc29 update both cameras came back without automatic day / night and the .24 without its recording)
for s in recording motion-detection auto-night-detection; do sh /mnt/controlscripts/$s halt >/dev/null 2>&1; done
for s in rtsp-h26x mqtt-bridge onvif; do sh /mnt/controlscripts/$s stop >/dev/null 2>&1; done
killall tc100_rtsp tc100-onvifd 2>/dev/null
# R18: the reboot at the end is deliberate: the intent goes to /mnt/config/log before the flush below writes it to the
# flash slots (rc29: the next boot said "unknown (no heartbeat recorded yet)"). KEEP_CARD: the backups below still go
# to the card, which is remounted read-only right before the reboot.
REBOOT_TRACKER_KEEP_CARD=1 sh /mnt/scripts/reboot-tracker.sh intent "web update to $(cat "$D/VERSION")" >/dev/null 2>&1
# B6: the settings of the last 30 s and a zero boot counter to the flash slots (cfga/cfgb, not rewritten here), then the
# settings daemon stops: the lock (cfg-persist save) is taken and kept, so a save under way ends first
sh /mnt/v3/linux66-sd/cfg-persist flush >/dev/null 2>&1
sh /mnt/v3/linux66-sd/boot-guard clear >/dev/null 2>&1
n=0; while ! mkdir /tmp/cfg-persist.lock 2>/dev/null && [ $n -lt 60 ]; do sleep 1; n=$((n + 1)); done
for p in $(ps 2>/dev/null | awk '/cfg-persist daemon/ && !/awk/ { print $1 }'); do kill "$p" 2>/dev/null; done
sleep 2; sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
for p in $(pidof watchdog); do echo -1000 > /proc/$p/oom_score_adj 2>/dev/null; done	# its keeper must outlive a memory shortage
BK=; [ -n "$LOG" ] && BK="-b /mnt/sd/tc100-3/backup"
if [ -n "$BK" ]; then
	# B6: the backups of the previous update stay (with this one: two), older ones go (about 7 MB each)
	for p in stack kernel initrd; do
		ls -1 /mnt/sd/tc100-3/backup/$p-*.bin 2>/dev/null | sort -r | sed 1d | while read -r f; do rm -f "$f"; done
	done
else
	say "no SD card: the firmware now in the flash is not saved before writing (confirmed by the user)"
fi
# BEGIN write_part (tests extract this block)
# write_part PARTITION FILE MD5: up to 3 attempts (flashw erases, writes and reads back each time); 0 = written and
# verified, 1 = failed three times. Test switch (audit B1): a file /tmp/update66.simfail holding "PARTITION [N]" makes the
# first N attempts (default all) on that partition fail by passing flashw a wrong md5, which it refuses before touching the flash.
write_part() {
	wp=$1; wf=$2; wm=$3; try=1
	FLASHW=${FLASHW:-/tmp/upd66/flashw}; FWLOG=${FWLOG:-/tmp/upd66/flashw.log}; RETRY_SLEEP=${RETRY_SLEEP:-3}; SIMFAIL=${SIMFAIL:-/tmp/update66.simfail}
	while [ $try -le 3 ]; do
		am=$wm
		if [ -f "$SIMFAIL" ]; then
			set -- $(cat "$SIMFAIL")
			[ "$1" = "$wp" ] && [ "$try" -le "${2:-99}" ] && am=00000000000000000000000000000000
		fi
		[ $try -gt 1 ] && say "retrying $wp (attempt $try of 3)"
		FLASHW_ALLOW="stack kernel initrd" sh $FLASHW -m "$am" $BK $wp "$wf" > $FWLOG 2>&1 && rc=0 || rc=$?
		[ -n "$LOG" ] && { echo "attempt $try on $wp: flashw exit $rc" >> "$LOG"; cat $FWLOG >> "$LOG"; }
		[ $rc -eq 0 ] && return 0
		try=$((try + 1)); [ $try -le 3 ] && sleep $RETRY_SLEEP
	done
	return 1
}
# END write_part
for p in stack:stack.sqfs kernel:c66.img initrd:c66rd.gz; do
	f=$D/${p#*:}
	m=$(sum_of "$D" "${p#*:}") || { say "FAILED: no md5 for ${p#*:} in MD5SUMS, nothing written for it. Web and ssh stay available: run the update again with a good package, or use the SD card. Do not cut the power"; exit 1; }
	say "writing ${p%%:*} ($(wc -c < "$f") bytes), do not unplug the camera"
	write_part ${p%%:*} "$f" "$m" || {
		# B1: no automatic reboot: the session in RAM (web, ssh) is the way to try again
		say "FAILED writing ${p%%:*} after 3 attempts. Web and ssh stay available: run the update again, or use the SD card (tc100test/c66.img). Do not cut the power. The camera services stay stopped until then"
		exit 1; }
done
say "DONE: $(cat "$D/VERSION") written, restarting"
sync; sleep 2
# the card (video storage, the recorder is stopped above) leaves clean: no "not properly unmounted" at the next boot
grep -qE ' /mnt/sd (vfat|exfat) rw' /proc/mounts && mount -o remount,ro /mnt/sd 2>/dev/null
reboot
