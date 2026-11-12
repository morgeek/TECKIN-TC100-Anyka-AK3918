#!/bin/sh
# update.cgi: firmware update (Settings -> Update & backup -> Firmware update):
#   GET  ?cmd=status    {"ok":true,"current":…,"state":"idle|staged|installing","staged":…,"kind":"linux66","message":…}
#   POST ?cmd=upload    raw body = tc100-<version>-update.tar; unpacked as it arrives (card if present, else RAM) and checked
#   POST ?cmd=install   v3/install/update66.sh apply in the background (the camera restarts). Without an SD card there
#                       is no backup of the flash: refused (error "nobackup") until the page asks again with
#                       &nobackup=1 after the user confirmed (review 2026-11-06, owner's decision)
#   POST ?cmd=discard   drop the uploaded package
# POSTs need the X-CSRF-Token header.
U=/mnt/v3/install/update66.sh
if grep -q ' /mnt/sd vfat ' /proc/mounts; then WORK=/mnt/sd/tc100-3/update; else WORK=/tmp/update66; fi
MAX_BYTES=$((12 * 1024 * 1024))

printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n'
js() { printf '%s' "$1" | awk '{ gsub(/[\\"]/, ""); gsub(/[\001-\037]/, " "); printf "%s", $0 }'; }
_cmd=""
_qs="&${QUERY_STRING:-}&"
case "$_qs" in *"&cmd="*) _cmd="${_qs#*&cmd=}"; _cmd="${_cmd%%&*}" ;; esac
case "$_cmd" in *[!a-z]*) _cmd="" ;; esac
if [ "${REQUEST_METHOD:-GET}" = "POST" ]; then
	_csrf_stored=""
	[ -r /tmp/csrf_token ] && read -r _csrf_stored < /tmp/csrf_token
	_csrf_stored="$(printf '%s' "$_csrf_stored" | awk '{ gsub(/[^0-9a-fA-F]/, ""); print }')"
	_csrf_hdr="$(printf '%s' "${HTTP_X_CSRF_TOKEN:-}" | awk '{ gsub(/[^0-9a-fA-F]/, ""); print }')"
	if [ -z "$_csrf_stored" ] || [ "$_csrf_hdr" != "$_csrf_stored" ]; then
		echo '{"ok":false,"error":"csrf_invalid","message":"CSRF token invalid, reload the page."}'; exit 0
	fi
fi
cur=$(js "$(cat /mnt/VERSION 2>/dev/null)")
# R26 (IPCAM1, rc31): the work folder is on the card when there is one, and a package left there by an earlier session
# (an rc28 on a camera in rc31) was shown as staged and could be installed. A package is staged only when it was
# uploaded and checked since the camera started: the mark is in RAM (/tmp), gone at the next start.
STAGED_MARK=${UPDATE_STAGED_MARK:-/tmp/update66.staged}
staged_ok() { [ -f "$WORK/ok" ] && [ -f "$WORK/VERSION" ] && [ "$(cat "$STAGED_MARK" 2>/dev/null)" = "$WORK" ]; }
# ver_older A B: 0 when version A is older than B (3.0.1-rc28 < 3.0.1-rc31 < 3.0.1; a -dev suffix counts as its rc)
ver_older() {
	awk -v a="$1" -v b="$2" 'function key(v,   base, rc, n, p) {
		base = v; sub(/-.*/, "", base); n = split(base, p, ".")
		rc = 999999; if (match(v, /-rc[0-9]+/)) rc = substr(v, RSTART + 3, RLENGTH - 3) + 0
		return sprintf("%06d%06d%06d%06d", p[1], p[2], p[3], rc) }
		BEGIN { exit !(key(a) < key(b)) }'
}

# an install under way, or one that failed after touching the flash (update66.sh leaves /tmp/update66.failed): no other
# upload, discard or install until a restart (review 2026-11-12)
busy_or_failed() {
	[ -e /tmp/update66.failed ] && { echo '{"ok":false,"error":"failed","message":"The last install failed half way: start the camera from the 3.0 SD card (tc100test/c66.img), then Settings -> Install to flash."}'; exit 0; }
	[ -e /tmp/update66.running ] && { echo '{"ok":false,"error":"busy","message":"Already installing."}'; exit 0; }
}

case "${REQUEST_METHOD:-GET}:$_cmd" in
GET:status|GET:)
	st=idle; staged=""; msg=$(js "$(cat /tmp/update66.status 2>/dev/null)")
	if [ -e /tmp/update66.running ]; then st=installing
	elif staged_ok; then st=staged; staged=$(js "$(cat "$WORK/VERSION")"); fi
	printf '{"ok":true,"current":"%s","state":"%s","staged":"%s","kind":"linux66","message":"%s"}\n' "$cur" "$st" "$staged" "$msg" ;;
POST:upload)
	# never during an install: it would delete the package being written (review 2026-11-12)
	busy_or_failed
	[ -f /tmp/flashmode ] || { echo '{"ok":false,"error":"sd_mode","message":"Running from the SD card (trial): copy the new 3.0 package to the card and restart."}'; exit 0; }
	n=${CONTENT_LENGTH:-0}
	case "$n" in ''|*[!0-9]*) n=0 ;; esac
	[ "$n" -gt 0 ] && [ "$n" -le $MAX_BYTES ] || { echo '{"ok":false,"error":"size","message":"Not a 3.0 update package (size)."}'; exit 0; }
	rm -rf "$WORK"; mkdir -p "$WORK" || { echo '{"ok":false,"error":"space","message":"Cannot store the package."}'; exit 0; }
	# Without a card the package is kept in RAM, which holds about 6 MB next to the running services: it is unpacked
	# as it arrives (no copy of the tar), and when the free memory is still short the services that need the most
	# are stopped first (the camera restarts after the install, or after a discard). Without that the kernel ran
	# out of memory and restarted the camera half way through the upload.
	if [ "$WORK" = /tmp/update66 ]; then
		need=$(( n / 1024 + 3072 )); avail=$(awk '$1 == "MemAvailable:" { print $2 }' /proc/meminfo)
		if [ "${avail:-0}" -lt "$need" ]; then
			: > /tmp/update66.stopped
			for sv in recording motion-detection auto-night-detection; do	# halt: their stop writes a setting for good
				[ -x /mnt/controlscripts/$sv ] && sh /mnt/controlscripts/$sv halt >/dev/null 2>&1
			done
			for sv in rtsp-h26x mqtt-bridge onvif; do
				[ -x /mnt/controlscripts/$sv ] && sh /mnt/controlscripts/$sv stop >/dev/null 2>&1
			done
			killall tc100_rtsp tc100-onvifd 2>/dev/null; sleep 2; sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
			avail=$(awk '$1 == "MemAvailable:" { print $2 }' /proc/meminfo)
			[ "${avail:-0}" -ge "$need" ] || {
				rm -rf "$WORK"; head -c "$n" > /dev/null
				printf '{"ok":false,"error":"memory","message":"Not enough free memory for the package (%s KB free, %s KB needed): put a FAT32 card in the camera and upload again. The camera restarts now."}\n' "${avail:-0}" "$need"
				( sh /mnt/scripts/reboot-tracker.sh intent "web UI update: not enough memory for the package, services restarted" >/dev/null 2>&1; sleep 2; reboot ) </dev/null >/dev/null 2>&1 &
				exit 0
			}
		fi
	fi
	head -c "$n" | ( cd "$WORK" && tar xf - VERSION stack.sqfs c66.img c66rd.gz MD5SUMS 2>/dev/null )
	t=0; for f in VERSION stack.sqfs c66.img c66rd.gz MD5SUMS; do [ -f "$WORK/$f" ] && t=$((t + $(wc -c < "$WORK/$f"))); done
	[ "$t" -gt 0 ] || { rm -rf "$WORK"; echo '{"ok":false,"error":"upload","message":"Upload incomplete or not a 3.0 update package."}'; exit 0; }
	r=$(sh $U check "$WORK" 2>&1)
	if [ "$r" != ok ]; then rm -rf "$WORK"; printf '{"ok":false,"error":"invalid","message":"%s"}\n' "$(js "$r")"; exit 0; fi
	: > "$WORK/ok"; printf '%s' "$WORK" > "$STAGED_MARK"
	printf '{"ok":true,"kind":"linux66","version":"%s","current":"%s"}\n' "$(js "$(cat "$WORK/VERSION")")" "$cur" ;;
POST:install)
	staged_ok || { echo '{"ok":false,"error":"state","message":"Upload a package first."}'; exit 0; }
	new=$(js "$(cat "$WORK/VERSION")")
	case "$_qs" in *"&older=1&"*) ;; *)
		if [ -n "$cur" ] && ver_older "$new" "$cur"; then
			printf '{"ok":false,"error":"older","message":"This package is older than the firmware installed now (%s is older than %s). Install it anyway? Settings stay as they are; a setting the older version does not know is ignored by it."}\n' "$new" "$cur"; exit 0
		fi ;;
	esac
	busy_or_failed
	_nb=0; case "$_qs" in *"&nobackup=1&"*) _nb=1 ;; esac
	if ! grep -q ' /mnt/sd vfat ' /proc/mounts && [ "$_nb" != 1 ]; then
		echo '{"ok":false,"error":"nobackup","message":"No SD card: the firmware now in the flash cannot be saved before it is overwritten, so the only way back is the 3.0 SD card. Install without a backup? (Or cancel, put a FAT32 card in the camera and install again.)"}'; exit 0
	fi
	: > /tmp/update66.running
	( trap '' HUP; UPDATE66_NOBACKUP=$_nb sh $U apply "$WORK"; rm -f /tmp/update66.running ) </dev/null >/dev/null 2>&1 &
	echo '{"ok":true,"started":"install"}' ;;
POST:discard)
	# never during an install: it would delete the package being written, and the restart below would cut a flash erase
	busy_or_failed
	rm -rf "$WORK"; rm -f "$STAGED_MARK"; echo '{"ok":true}'
	# services stopped to make room for the package: back to normal with a restart
	[ -e /tmp/update66.stopped ] && ( sh /mnt/scripts/reboot-tracker.sh intent "web UI update discarded, services restarted" >/dev/null 2>&1; sleep 2; reboot ) </dev/null >/dev/null 2>&1 & ;;
POST:rollback)
	echo '{"ok":false,"error":"unsupported","message":"No rollback on 3.0: install the previous package."}' ;;
*)
	echo '{"ok":false,"error":"unknown_command"}' ;;
esac
