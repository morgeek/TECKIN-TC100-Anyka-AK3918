#!/bin/sh
# flashinstall.cgi: install the card system to the flash (Settings -> Update & backup -> Install to flash):
#   GET  ?cmd=status   {"ok":true,"linux66":1,"state":"flash|ready66|blocked|running|installed","running":0|1,"log":…}
#   POST ?cmd=install  v3/install/install66.sh run in the background (the camera restarts from its flash at the end)
# POSTs need the X-CSRF-Token header.
I=/mnt/v3/install/install66.sh
LOGF=/mnt/sd/tc100-3/install66.log
RUN=/tmp/install66.running

printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n'
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
log() { tail -n "${1:-8}" "$LOGF" 2>/dev/null | awk '{ gsub(/[\\"]/, ""); gsub(/\t/, " "); printf "%s\\n", $0 }'; }

case "${REQUEST_METHOD:-GET}:$_cmd" in
GET:status|GET:)
	if [ -f /tmp/flashmode ]; then printf '{"ok":true,"linux66":1,"state":"flash","running":0,"log":""}\n'; exit 0; fi
	if [ -e $RUN ]; then printf '{"ok":true,"linux66":1,"state":"running","running":1,"log":"%s"}\n' "$(log)"; exit 0; fi
	r=$(sh $I check 2>&1)
	if [ "$r" = ok ]; then st=ready66; l=$(log 4); else st=blocked; l=$(printf '%s' "$r" | awk '{ gsub(/[\\"]/, ""); printf "%s", $0 }'); fi
	printf '{"ok":true,"linux66":1,"state":"%s","running":0,"log":"%s"}\n' "$st" "$l" ;;
POST:install)
	[ -e $RUN ] && { echo '{"ok":false,"error":"busy","message":"Already installing."}'; exit 0; }
	r=$(sh $I check 2>&1)
	[ "$r" = ok ] || { printf '{"ok":false,"error":"state","message":"%s"}\n' "$(printf '%s' "$r" | awk '{ gsub(/[\\"]/, ""); printf "%s", $0 }')"; exit 0; }
	: > $RUN
	( trap '' HUP; sh $I run; rm -f $RUN ) </dev/null >/dev/null 2>&1 &
	echo '{"ok":true,"started":"install"}' ;;
*)
	echo '{"ok":false,"error":"unknown_command"}' ;;
esac
