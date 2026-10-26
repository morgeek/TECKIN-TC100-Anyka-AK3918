#!/bin/sh
# Linux 6.6 side of www/cgi-bin/update.cgi (Settings -> Update & backup -> Firmware update), same JSON protocol:
#   GET  ?cmd=status    {"ok":true,"current":…,"state":"idle|staged|installing","staged":…,"kind":"linux66","message":…}
#   POST ?cmd=upload    raw body = tc100-<version>-update.tar; saved (card if present, else RAM) and checked
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
	head -c "$n" > "$WORK/pkg.tar"
	[ "$(wc -c < "$WORK/pkg.tar")" -eq "$n" ] || { rm -rf "$WORK"; echo '{"ok":false,"error":"upload","message":"Upload incomplete."}'; exit 0; }
	( cd "$WORK" && tar xf pkg.tar VERSION stack.sqfs c66.img c66rd.gz MD5SUMS 2>/dev/null ); rm -f "$WORK/pkg.tar"
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
	rm -rf "$WORK"; echo '{"ok":true}' ;;
POST:rollback)
	echo '{"ok":false,"error":"unsupported","message":"No rollback on 3.0: install the previous package."}' ;;
*)
	echo '{"ok":false,"error":"unknown_command"}' ;;
esac
