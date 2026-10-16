#!/bin/sh
# flashinstall.cgi — "Install to flash" card (Settings → Update & backup),
# front end of scripts/flash-install.sh (README "Install to flash").
#   GET   ?cmd=status    {"ok":true,"state":…,"running":0|1,"log":…}
#         state: flash (already running from flash) | none (no tc100-flash/
#         folder) | empty | prepared | ready | installed
#   POST  ?cmd=prepare   step 1 now: copy the original /usr to the card
#                        (read-only for the flash, in the background)
#   POST  ?cmd=install   step 3: reboot; the install runs at boot, before any
#                        video service (only when usr.img is on the card)
# POSTs need the X-CSRF-Token header.

FI="${FI_SCRIPT:-/mnt/scripts/flash-install.sh}"
CARD="${FI_CARD:-/mnt}"
K="${FI_DIR:-$CARD/tc100-flash}"
RUN="${FI_RUNNING:-/tmp/flash-install.running}"

printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n'

_cmd=""
_qs="&${QUERY_STRING:-}&"
case "$_qs" in *"&cmd="*) _cmd="${_qs#*&cmd=}"; _cmd="${_cmd%%&*}" ;; esac
case "$_cmd" in *[!a-z]*) _cmd="" ;; esac

if [ "${REQUEST_METHOD:-GET}" = "POST" ]; then
  _csrf_stored=""
  if [ -r /tmp/csrf_token ]; then
    read -r _csrf_stored < /tmp/csrf_token
    _csrf_stored="$(printf '%s' "$_csrf_stored" | awk '{ gsub(/[^0-9a-fA-F]/, ""); print }')"
  fi
  _csrf_hdr="$(printf '%s' "${HTTP_X_CSRF_TOKEN:-}" | awk '{ gsub(/[^0-9a-fA-F]/, ""); print }')"
  if [ -z "$_csrf_stored" ] || [ "$_csrf_hdr" != "$_csrf_stored" ]; then
    echo '{"ok":false,"error":"csrf_invalid","message":"CSRF token invalid, reload the page."}'
    exit 0
  fi
fi

_state="$(FI_CARD="$CARD" FI_DIR="$K" sh "$FI" status 2>/dev/null)"
case "${REQUEST_METHOD:-GET}:$_cmd" in
  GET:status|GET:)
    _r=0; [ -e "$RUN" ] && _r=1
    _log="$(tail -n 8 "$K/STATUS.txt" 2>/dev/null | awk '{ gsub(/[\\"]/, ""); gsub(/\t/, " "); printf "%s\\n", $0 }')"
    printf '{"ok":true,"state":"%s","running":%s,"log":"%s"}\n' "${_state:-none}" "$_r" "$_log" ;;
  POST:prepare)
    case "$_state" in
      none|empty|prepared) ;;
      *) printf '{"ok":false,"error":"state","message":"Not possible now (%s)."}\n' "$_state"; exit 0 ;;
    esac
    [ -e "$RUN" ] && { echo '{"ok":false,"error":"busy","message":"Already running."}'; exit 0; }
    mkdir -p "$K" || { echo '{"ok":false,"error":"card","message":"Cannot write to the SD card."}'; exit 0; }
    : > "$RUN"
    ( trap '' HUP; FI_CARD="$CARD" FI_DIR="$K" sh "$FI" prepare; rm -f "$RUN" ) </dev/null >/dev/null 2>&1 &
    echo '{"ok":true,"started":"prepare"}' ;;
  POST:install)
    [ "$_state" = ready ] || { printf '{"ok":false,"error":"state","message":"No usr.img on the card yet (%s)."}\n' "$_state"; exit 0; }
    ( trap '' HUP; sleep 2; sync; reboot ) </dev/null >/dev/null 2>&1 &
    echo '{"ok":true,"started":"install"}' ;;
  *)
    echo '{"ok":false,"error":"unknown_command"}' ;;
esac
