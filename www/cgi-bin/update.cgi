#!/bin/sh
# update.cgi — firmware update from the web UI (Settings → Firmware update).
#   GET               ?cmd=status              JSON state (scripts/fw-update.sh status)
#   POST (raw body)   ?cmd=upload              save the package to the SD card and verify it
#   POST              ?cmd=install|rollback    run in the background, then the camera reboots
#   POST              ?cmd=discard             drop the staged package
# POSTs need the X-CSRF-Token header. The request body is streamed by lighttpd
# (server.stream-request-body for this URL) straight to the SD card: a package
# is several MB and RAM is ~33 MB in total.

FWU="${FWU_SCRIPT:-/mnt/scripts/fw-update.sh}"
WORK="${FWU_WORK:-/mnt/update}"
MAX_BYTES=$((48 * 1024 * 1024))

printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n'

_cmd=""
_qs="&${QUERY_STRING:-}&"
case "$_qs" in *"&cmd="*) _cmd="${_qs#*&cmd=}"; _cmd="${_cmd%%&*}" ;; esac
case "$_cmd" in *[!a-z]*) _cmd="" ;; esac

if [ "${REQUEST_METHOD:-GET}" = "POST" ]; then
  # Same CSRF check as conf-import.cgi (awk: no tr on the camera).
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

# Running from flash (scripts/flashboot.sh): /mnt is a small RAM disk and the
# code is in the flash /usr image, which this updater does not write.
if [ "${REQUEST_METHOD:-GET}" = "POST" ] && [ "$(cat "${TC100_STORAGE_FILE:-/tmp/tc100-storage}" 2>/dev/null)" = flash ]; then
  echo '{"ok":false,"error":"flash_mode","message":"The camera runs from its flash memory: updates are written with src/flash/flash-usr.sh, not from this page."}'
  exit 0
fi

case "${REQUEST_METHOD:-GET}:$_cmd" in
  GET:status|GET:)
    sh "$FWU" status ;;
  POST:upload)
    _cl="${CONTENT_LENGTH:-0}"
    case "$_cl" in ''|*[!0-9]*) _cl=0 ;; esac
    if [ "$_cl" -le 0 ] || [ "$_cl" -gt "$MAX_BYTES" ]; then
      echo '{"ok":false,"error":"invalid_size","message":"Package must be between 1 byte and 48 MB."}'
      exit 0
    fi
    mkdir -p "$WORK"
    rm -rf "$WORK/stage" "$WORK/package.tar"
    head -c "$_cl" > "$WORK/package.tar" 2>/dev/null
    set -- $(wc -c < "$WORK/package.tar" 2>/dev/null)
    if [ "${1:-0}" != "$_cl" ]; then
      rm -f "$WORK/package.tar"
      echo '{"ok":false,"error":"upload_incomplete"}'
      exit 0
    fi
    sh "$FWU" verify "$WORK/package.tar" ;;
  POST:install|POST:rollback)
    # Detached: the install outlives this request and ends with a reboot.
    ( trap '' HUP; sh "$FWU" "$_cmd" </dev/null >>"$WORK/update.log" 2>&1 ) &
    printf '{"ok":true,"started":"%s"}\n' "$_cmd" ;;
  POST:discard)
    sh "$FWU" discard ;;
  *)
    echo '{"ok":false,"error":"unknown_command"}' ;;
esac
