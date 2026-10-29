#!/bin/sh
# update.cgi: firmware update (Settings -> Update & backup -> Firmware update):
#   GET  ?cmd=status    {"ok":true,"current":…,"state":"idle|staged|installing","staged":…,"kind":"linux66","message":…}
#   POST ?cmd=upload    raw body = tc100-<version>-update.tar; unpacked as it arrives (card if present, else RAM) and checked
#   POST ?cmd=install   v3/install/update66.sh apply in the background (the camera restarts)
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

case "${REQUEST_METHOD:-GET}:$_cmd" in
GET:status|GET:)
	st=idle; staged=""; msg=$(js "$(cat /tmp/update66.status 2>/dev/null)")
	if [ -e /tmp/update66.running ]; then st=installing
	elif [ -f "$WORK/VERSION" ] && [ -f "$WORK/ok" ]; then st=staged; staged=$(js "$(cat "$WORK/VERSION")"); fi
	printf '{"ok":true,"current":"%s","state":"%s","staged":"%s","kind":"linux66","message":"%s"}\n' "$cur" "$st" "$staged" "$msg" ;;
POST:upload)
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
			for sv in rtsp-h26x recording motion-detection mqtt-bridge onvif auto-night-detection; do
				[ -x /mnt/controlscripts/$sv ] && sh /mnt/controlscripts/$sv stop >/dev/null 2>&1
			done
			killall tc100_rtsp monvifd 2>/dev/null; sleep 2; sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
			avail=$(awk '$1 == "MemAvailable:" { print $2 }' /proc/meminfo)
			[ "${avail:-0}" -ge "$need" ] || {
				rm -rf "$WORK"; head -c "$n" > /dev/null
				printf '{"ok":false,"error":"memory","message":"Not enough free memory for the package (%s KB free, %s KB needed): put a FAT32 card in the camera and upload again. The camera restarts now."}\n' "${avail:-0}" "$need"
				( sleep 2; reboot ) </dev/null >/dev/null 2>&1 &
				exit 0
			}
		fi
	fi
	head -c "$n" | ( cd "$WORK" && tar xf - VERSION stack.sqfs c66.img c66rd.gz MD5SUMS 2>/dev/null )
	t=0; for f in VERSION stack.sqfs c66.img c66rd.gz MD5SUMS; do [ -f "$WORK/$f" ] && t=$((t + $(wc -c < "$WORK/$f"))); done
	[ "$t" -gt 0 ] || { rm -rf "$WORK"; echo '{"ok":false,"error":"upload","message":"Upload incomplete or not a 3.0 update package."}'; exit 0; }
	r=$(sh $U check "$WORK" 2>&1)
	if [ "$r" != ok ]; then rm -rf "$WORK"; printf '{"ok":false,"error":"invalid","message":"%s"}\n' "$(js "$r")"; exit 0; fi
	: > "$WORK/ok"
	printf '{"ok":true,"kind":"linux66","version":"%s","current":"%s"}\n' "$(js "$(cat "$WORK/VERSION")")" "$cur" ;;
POST:install)
	[ -f "$WORK/ok" ] || { echo '{"ok":false,"error":"state","message":"Upload a package first."}'; exit 0; }
	[ -e /tmp/update66.running ] && { echo '{"ok":false,"error":"busy","message":"Already installing."}'; exit 0; }
	: > /tmp/update66.running
	( trap '' HUP; sh $U apply "$WORK"; rm -f /tmp/update66.running ) </dev/null >/dev/null 2>&1 &
	echo '{"ok":true,"started":"install"}' ;;
POST:discard)
	rm -rf "$WORK"; echo '{"ok":true}'
	# services stopped to make room for the package: back to normal with a restart
	[ -e /tmp/update66.stopped ] && ( sleep 2; reboot ) </dev/null >/dev/null 2>&1 & ;;
POST:rollback)
	echo '{"ok":false,"error":"unsupported","message":"No rollback on 3.0: install the previous package."}' ;;
*)
	echo '{"ok":false,"error":"unknown_command"}' ;;
esac
