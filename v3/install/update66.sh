#!/bin/sh
# update66.sh check DIR | apply DIR   update the 3.0 firmware in the flash from an update package.
#
# Package (tc100-<version>-update.tar, made by v3/build-release.sh): VERSION, stack.sqfs, c66.img, c66rd.gz, MD5SUMS
# and SHA256SUMS; the owner adds SHA256SUMS.sig (Ed25519, scripts/sign_update.py; docs/linux-port/upgrade-3.2/sign.md).
# "check" verifies it: the signature (policy UPDATE_REQUIRE_SIG of /mnt/config/boot.conf), then SHA256SUMS, then md5, sizes,
# partitions. The result of the signature check is the line of /tmp/update66.sig ("signed ID", "unsigned WHY", "refused WHY").
# "apply" runs from a copy in RAM (the user space it replaces
# is the squashfs being rewritten): it stops the services, writes stack, kernel and initrd with flashw (md5 checked
# before and after each write), and restarts. The settings (cfga/cfgb) and the vendor libraries (vendor) are kept.
# If something goes wrong half way, the flash system may not start: an SD card with the 3.0 package
# (tc100test/c66.img) starts the camera, and Settings -> Install to flash writes everything again.
# Status: /tmp/update66.status (one line) and, with a card, tc100-3/update66.log.
ST=/tmp/update66.status
part_size() { for d in /sys/class/mtd/mtd[0-9]*; do case $d in *ro) continue;; esac; [ "$(cat $d/name)" = "$1" ] && { cat $d/size; return 0; }; done; return 1; }
# kernel_load_max, kernel_img_check, initrd_img_check: shared with the SD install (install66.sh), so that both refuse the
# same bad images before anything is erased
. "${UPDATE66_LIB:-/mnt/v3/install}/imgcheck.sh"
say() { echo "$*" > $ST; echo "update66: $*" > /dev/console; [ -n "$LOG" ] && echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
# the md5 published in the package for a file (B3: flashw compares the file with THIS sum, not with itself)
sum_of() { awk -v f="$2" '$2 == f || $2 == "*" f { print $1; exit }' "$1/MD5SUMS" | grep -E '^[0-9a-fA-F]{32}$'; }
# signature check (test hooks: the UPDATE66_* variables). Keys: the public keys of the running image, then the owner's own folder.
SIGCHECK=${UPDATE66_SIGCHECK:-/mnt/bin/tc100-sigcheck}
KEYDIRS=${UPDATE66_KEYDIRS:-/mnt/v3/install/update-keys /mnt/config/update-keys}
SIGST=${UPDATE66_SIGST:-/tmp/update66.sig}
SHA256SUM=${UPDATE66_SHA256SUM:-sha256sum}
BOOTCONF=${UPDATE66_BOOTCONF:-/mnt/config/boot.conf}
LOG=; grep -q ' /mnt/sd vfat ' /proc/mounts && mkdir -p /mnt/sd/tc100-3 2>/dev/null && LOG=/mnt/sd/tc100-3/update66.log

# UPDATE_REQUIRE_SIG (boot.conf, single source; the environment wins, for tests): 0 or unset = 0, anything else = 1
require_sig() {
	v=${UPDATE_REQUIRE_SIG:-}
	[ -z "$v" ] && [ -f "$BOOTCONF" ] && v=$(grep -E '^[[:space:]]*UPDATE_REQUIRE_SIG=' "$BOOTCONF" | tail -n 1 | sed -e 's/^[^=]*=//' -e 's/[[:space:]#].*$//' -e "s/[\"']//g")
	case "$v" in ''|0) echo 0 ;; *) echo 1 ;; esac
}
sig_set() { echo "$*" > "$SIGST"; [ -n "$LOG" ] && echo "$(date '+%Y-%m-%d %H:%M:%S') update signature: $*" >> "$LOG"; return 0; }
# verify_sig DIR: 0 = go on, 1 = refuse (the reason on stdout). Reads only. A signature that is present and BAD is always
# refused; unsigned or unknown-key packages are accepted with a warning unless UPDATE_REQUIRE_SIG=1 and a key is installed
# (with no key installed the switch cannot lock the owner out: warning, behaves as 0).
# key_count: the usable public keys, as the verifier itself counts them (a .pub that does not parse is no key); the number
# of .pub files when the verifier cannot run (then a present signature cannot be checked either, see below)
key_count() {
	nk=$("$SIGCHECK" keys $KEYDIRS 2>/dev/null)
	case "$nk" in ''|*[!0-9]*) nk=0; for kd in $KEYDIRS; do for kf in "$kd"/*.pub; do [ -f "$kf" ] && nk=$((nk + 1)); done; done ;; esac
	echo "$nk"
}
verify_sig() {
	verify_sig_core "$1" || return 1
	# no sha256sum applet: the files cannot be checked against SHA256SUMS. Policy 0 falls back to the md5 checks with a warning
	# (it must not block every package); policy 1 with a key installed refuses
	if ! command -v "$SHA256SUM" >/dev/null 2>&1 && [ -f "$1/SHA256SUMS" ]; then
		if [ "$(require_sig)" = 1 ] && [ "$(key_count)" != 0 ]; then
			sig_set "refused sha256sum is not available"; echo "sha256sum is not available: the package cannot be checked (UPDATE_REQUIRE_SIG=1)"; return 1
		fi
		sig_set "unsigned sha256sum is not available on this camera: SHA256SUMS not checked, md5 only"
	fi
	return 0
}
verify_sig_core() {
	d=$1; req=$(require_sig); rm -f "$SIGST"; note=; nk=$(key_count)
	if [ "$req" = 1 ] && [ "$nk" = 0 ]; then req=0; note=" (UPDATE_REQUIRE_SIG=1 but no public key is installed on this camera: treated as 0)"; fi
	if [ ! -f "$d/SHA256SUMS.sig" ]; then
		if [ "$req" = 1 ]; then sig_set "refused the package is not signed and UPDATE_REQUIRE_SIG=1"; echo "the package is not signed and this camera accepts only signed packages (UPDATE_REQUIRE_SIG=1)"; return 1; fi
		sig_set "unsigned no signature (SHA256SUMS.sig) in the package$note"; return 0
	fi
	[ -f "$d/SHA256SUMS" ] || { sig_set "refused the package has a signature but no SHA256SUMS"; echo "the package has a signature but no SHA256SUMS"; return 1; }
	r=$("$SIGCHECK" verify "$d/SHA256SUMS" "$d/SHA256SUMS.sig" $KEYDIRS 2>/dev/null); rc=$?
	case $rc in
	0) sig_set "signed ${r#signed }"; return 0 ;;
	1) sig_set "refused the signature of the package is not valid"; echo "the signature of the package is not valid (changed or damaged after signing): refused"; return 1 ;;
	3) if [ "$req" = 1 ]; then sig_set "refused signed by a key not installed on this camera (${r#unknown })"; echo "the package is signed by key ${r#unknown }, which is not installed on this camera (UPDATE_REQUIRE_SIG=1)"; return 1; fi
	   sig_set "unsigned signed by an unknown key (${r#unknown }), accepted because UPDATE_REQUIRE_SIG=0"; return 0 ;;
	4) sig_set "unsigned no usable public key on this camera$note"; return 0 ;;
	*) if [ "$req" = 1 ]; then sig_set "refused the signature could not be checked"; echo "the signature could not be checked (tc100-sigcheck missing or failing): refused (UPDATE_REQUIRE_SIG=1)"; return 1; fi
	   sig_set "unsigned the signature could not be checked (tc100-sigcheck missing or failing)"; return 0 ;;
	esac
}

# pkg_auth DIR: the read-only authenticity checks of "check" (links, signature, SHA256SUMS); also "update66.sh sigcheck DIR"
# for a test on a camera started from the SD card (no flash mode needed): prints ok or the reason
pkg_auth() {
	D=$1
	for f in VERSION stack.sqfs c66.img c66rd.gz MD5SUMS SHA256SUMS SHA256SUMS.sig; do [ -L "$D/$f" ] && { echo "$f is a link: not a valid firmware update package"; return 1; }; done
	# authenticity first, then the sums it covers, then the md5 of flashw; nothing is written to the flash by any of them
	r=$(verify_sig "$D") || { echo "$r"; return 1; }
	if [ -f "$D/SHA256SUMS" ]; then
		# whole lines as sha256sum writes them, each package file exactly once, MD5SUMS included (it must not be swappable)
		awk 'BEGIN { nf = split("VERSION stack.sqfs c66.img c66rd.gz MD5SUMS", f, " ") } NF == 0 { next }
			{ ok = 0; for (i = 1; i <= 5; i++) if ($0 == $1 "  " f[i] || $0 == $1 " *" f[i]) { ok = 1; n[f[i]]++ }
			  if (!ok || length($1) != 64 || $1 !~ /^[0-9a-fA-F]+$/) bad = 1 }
			END { for (i = 1; i <= 5; i++) if (n[f[i]] != 1) bad = 1; exit bad }' "$D/SHA256SUMS" ||
			{ sig_set "refused SHA256SUMS does not list the files of the package"; echo "SHA256SUMS does not list exactly the files of a valid firmware update package"; return 1; }
		# (without the applet verify_sig has already decided: warning at policy 0, refused at policy 1)
		if command -v "$SHA256SUM" >/dev/null 2>&1; then
		( cd "$D" && "$SHA256SUM" -c SHA256SUMS >/dev/null 2>&1 ) || { sig_set "refused the package is damaged or changed (sha256)"; echo "the package is damaged or changed (sha256)"; return 1; }
		fi
	fi
	echo ok
}

check() {
	D=$1
	[ -f /tmp/flashmode ] || { echo "the camera is not running from its flash (trial mode: copy the new package to the card instead)"; return 1; }
	# the first, hand-made flash layout (2026-10-24) has the vendor libraries inside a 3.7 MiB "stack" and no "vendor"
	# partition: the packaged stack.sqfs has no vendor files, so writing it there would leave the camera without video
	part_size vendor >/dev/null || { echo "this camera has the first flash layout (no vendor partition): a web update would remove its vendor libraries. Copy the new SD package to the card (keep its lib/ folder), start the camera from it, then Settings -> Update & backup -> Install to flash"; return 1; }
	for f in VERSION stack.sqfs c66.img c66rd.gz MD5SUMS; do [ -f "$D/$f" ] || { echo "$f is missing from the package"; return 1; }; done
	# plain files only, and MD5SUMS names only these files: a link (VERSION -> any file, shown by the web page) or an
	# entry such as /dev/zero (md5sum -c would never end) is refused (review 2026-11-12)
	r=$(pkg_auth "$D") || { echo "$r"; return 1; }
	# whole lines as md5sum writes them ("md5  name" or "md5 *name"): awk's own field split would let "x<TAB>VERSION  /dev/zero" by
	awk 'BEGIN { split("VERSION stack.sqfs c66.img c66rd.gz", f, " ") } NF == 0 { next }
		{ ok = 0; for (i = 1; i <= 4; i++) if ($0 == $1 "  " f[i] || $0 == $1 " *" f[i]) ok = 1 }
		!ok || length($1) != 32 { bad = 1 } END { exit bad }' "$D/MD5SUMS" ||
		{ echo "MD5SUMS names other files: not a valid firmware update package"; return 1; }
	( cd "$D" && md5sum -c MD5SUMS >/dev/null 2>&1 ) || { echo "the package is damaged (md5)"; return 1; }
	for f in stack.sqfs c66.img c66rd.gz; do sum_of "$D" $f >/dev/null || { echo "MD5SUMS has no sum for $f"; return 1; }; done
	for p in stack:stack.sqfs kernel:c66.img initrd:c66rd.gz; do
		s=$(part_size ${p%%:*}) || { echo "no ${p%%:*} partition"; return 1; }
		[ "$(wc -c < "$D/${p#*:}")" -le "$s" ] || { echo "${p#*:} does not fit the ${p%%:*} partition"; return 1; }
	done
	r=$(initrd_img_check "$D/c66rd.gz") || { echo "$r"; return 1; }
	r=$(kernel_img_check "$D/c66.img") || { echo "$r (install it from the SD card instead)"; return 1; }
	[ "$(head -c 4 "$D/stack.sqfs")" = hsqs ] || { echo "stack.sqfs is not a squashfs image"; return 1; }
	echo ok
}

case "$1" in
check) check "$2"; exit $? ;;
sigcheck) pkg_auth "$2"; exit $? ;;
apply) ;;
apply-ram) ;;
*) echo "usage: update66.sh check|sigcheck|apply DIR"; exit 2 ;;
esac
D=$2
if [ "$1" = apply ]; then
	r=$(check "$D") || { say "FAILED: $r"; exit 1; }
	case "$(cat "$SIGST" 2>/dev/null)" in unsigned*) [ -n "$LOG" ] && echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING: installing a package that is not authenticated: $(cat "$SIGST")" >> "$LOG" ;; esac
	# no SD card = no backup of what the flash holds now (flashw -b): only with an explicit confirmation (the web page
	# asks for it, update.cgi then sets UPDATE66_NOBACKUP=1), checked before anything is stopped (review 2026-11-06)
	if [ -z "$LOG" ] && [ "${UPDATE66_NOBACKUP:-0}" != 1 ]; then
		say "FAILED: no SD card for the backup of the flash; confirm the install without a backup (web page) or put a FAT32 card in the camera"
		exit 1
	fi
	# room for the backups on the card (flashw -b writes each whole partition, ~7 MB in all, and refuses without room, but
	# only after the services are stopped): checked now, before anything is stopped. Margin 1 MiB. UPDATE66_SD_FREE_KB
	# is a test hook.
	if [ -n "$LOG" ]; then
		need=1024; for p in stack kernel initrd; do need=$((need + $(part_size $p) / 1024)); done
		free=${UPDATE66_SD_FREE_KB:-$(df -k /mnt/sd 2>/dev/null | tail -n 1 | awk '{ print $(NF - 2) }')}
		# the prune below deletes the older backups (all but the newest of each partition) before this run writes its own:
		# what it will free counts as free; the newest of each stay, so the set a failed run may need is never touched
		case "$free" in ''|*[!0-9]*) ;; *)
			for p in stack kernel initrd; do
				for f in $(ls -1 /mnt/sd/tc100-3/backup/$p-*.bin 2>/dev/null | sort -r | sed 1d); do
					free=$((free + $(wc -c < "$f") / 1024))
				done
			done ;;
		esac
		case "$free" in ''|*[!0-9]*) ;; *)
			[ "$free" -ge "$need" ] || { say "FAILED: the SD card has $((free / 1024)) MiB free, the backup of the flash needs $((need / 1024)) MiB: free some space on the card (tc100-3/backup holds the old backups) and try again"; exit 1; } ;;
		esac
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
# the scheduled-reboot entry of crond and the reset button (hold 8 s = reboot) would restart the camera in the middle of
# a flash write: both stop with the services (the camera restarts at the end of the run; a failed run puts them back
# (restore_guards, EXIT trap); /tmp/update66.running also refuses a restart from the web page while the run lives)
CROND_WAS=$(pidof crond)
GUARDS_OFF=1
# a failed run (any exit but the final restart) puts them back, best effort: the reset button (rescue Wi-Fi, 8 s restart)
# is then the way out without a power cut
restore_guards() {
	[ -n "$GUARDS_OFF" ] && [ -z "$UPDATE_DONE" ] || return 0
	[ -n "$CROND_WAS" ] && crond -c /mnt/config/cron/crontabs </dev/null >/dev/null 2>&1
	sh /mnt/controlscripts/button-actions start >/dev/null 2>&1
}
trap restore_guards EXIT
killall crond 2>/dev/null
sh /mnt/controlscripts/button-actions stop >/dev/null 2>&1
for p in $(ps 2>/dev/null | awk '/button-watch\.sh/ && !/awk/ { print $1 }'); do kill "$p" 2>/dev/null; done
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
	wp=$1; wf=$2; wm=$3; try=1; wtouched=0; wbk=$BK	# wtouched: flashw got as far as flashcp (exit 0, 5, 6) at least once
	FLASHW=${FLASHW:-/tmp/upd66/flashw}; FWLOG=${FWLOG:-/tmp/upd66/flashw.log}; RETRY_SLEEP=${RETRY_SLEEP:-3}; SIMFAIL=${SIMFAIL:-/tmp/update66.simfail}
	while [ $try -le 3 ]; do
		am=$wm
		if [ -f "$SIMFAIL" ]; then
			set -- $(cat "$SIMFAIL")
			[ "$1" = "$wp" ] && [ "$try" -le "${2:-99}" ] && am=00000000000000000000000000000000
		fi
		[ $try -gt 1 ] && say "retrying $wp (attempt $try of 3)"
		FLASHW_ALLOW="stack kernel initrd" sh $FLASHW -m "$am" $wbk $wp "$wf" > $FWLOG 2>&1 && rc=0 || rc=$?
		[ -n "$LOG" ] && { echo "attempt $try on $wp: flashw exit $rc" >> "$LOG"; cat $FWLOG >> "$LOG"; }
		case $rc in 0|5|6) wtouched=1 ;; esac	# 1-4, 7: refused or backup failed before any erase
		# the backup is made once, by the first attempt that got as far as flashcp: a later attempt would "back up" the
		# half-written partition, and the prune above (newest kept) would then keep that copy instead of the good one.
		# An attempt refused or failed before the erase (rc 1-4, 7) made no good backup: it keeps -b.
		[ $wtouched = 1 ] && wbk=
		[ $rc -eq 0 ] && return 0
		try=$((try + 1)); [ $try -le 3 ] && sleep $RETRY_SLEEP
	done
	return 1
}
# END write_part
for p in stack:stack.sqfs kernel:c66.img initrd:c66rd.gz; do
	f=$D/${p#*:}
	# B1: no automatic reboot after a failure. The web pages live in the stack partition, written first: once it is
	# touched they are not usable any more, so the way back is the SD card. /tmp/update66.failed makes update.cgi refuse
	# any other upload / discard / install until a restart (review 2026-11-12: a discard deleted the package, a new
	# install recopied the tools from the rewritten /mnt)
	m=$(sum_of "$D" "${p#*:}") || { : > /tmp/update66.failed; say "FAILED: no md5 for ${p#*:} in MD5SUMS. Do not cut the power. Start the camera from the 3.0 SD card (tc100test/c66.img), then Settings -> Install to flash"; exit 1; }
	say "writing ${p%%:*} ($(wc -c < "$f") bytes), do not unplug the camera"
	write_part ${p%%:*} "$f" "$m" || {
		: > /tmp/update66.failed
		# the first partition refused before any erase (no room for the backup on the card, md5 or size): nothing changed
		[ "${p%%:*}" = stack ] && [ "$wtouched" = 0 ] && {
			say "FAILED before writing (flashw exit $rc: backup on the card, md5 or size, see the log): the flash is unchanged. Restart the camera: it starts the firmware it had"
			exit 1; }
		say "FAILED writing ${p%%:*} after 3 attempts. Do not cut the power. The web page is no longer usable (it lives in the stack partition being rewritten): start the camera from the 3.0 SD card (tc100test/c66.img), then Settings -> Install to flash. The camera services stay stopped until then"
		exit 1; }
done
UPDATE_DONE=1
say "DONE: $(cat "$D/VERSION") written, restarting"
sync; sleep 2
# the card (video storage, the recorder is stopped above) leaves clean: no "not properly unmounted" at the next boot
grep -qE ' /mnt/sd (vfat|exfat) rw' /proc/mounts && mount -o remount,ro /mnt/sd 2>/dev/null
reboot
