#!/bin/sh
# update.cgi — firmware update from the web UI (Settings → Firmware update).
#   GET               ?cmd=status              JSON state (scripts/fw-update.sh status)
#   POST (raw body)   ?cmd=upload              save the package to the SD card and verify it
#   POST              ?cmd=install|rollback    run in the background, then the camera reboots
#   POST              ?cmd=discard             drop the staged package
# From flash, two kinds of package: a code package (tc100-code-VERSION.bin,
# the scripts and web pages: code zone) and a system package
# (tc100-system-VERSION.tar from src/flash/build-flash-kit.sh: /usr and code,
# scripts/usr-update.sh).
# POSTs need the X-CSRF-Token header. The request body is streamed by lighttpd
# (server.stream-request-body for this URL) straight to the SD card: a package
# is several MB and RAM is ~33 MB in total.

FWU="${FWU_SCRIPT:-/mnt/scripts/fw-update.sh}"
WORK="${FWU_WORK:-/mnt/tc100-update}"
MAX_BYTES=$((48 * 1024 * 1024))

# Record why the camera is about to restart (scripts/reboot-tracker.sh reads
# it at the next boot), written directly: the code zone holding the tracker
# script may just have been rewritten.
fl_reboot_intent() {
  mkdir -p "${FWU_JFFS_LOG:-/etc/jffs2/tc100/log}" 2>/dev/null
  printf '%s|%s\n' "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)" "$1" > "${FWU_JFFS_LOG:-/etc/jffs2/tc100/log}/.reboot-intent" 2>/dev/null
}

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

# Never restart in the middle of an SD card format (scripts/sd-card.sh):
# the card would be left without a file system.
case "${REQUEST_METHOD:-GET}:$_cmd" in
  POST:install|POST:rollback)
    if [ "$(sed -n 's/^state=//p' "${SDC_FMT:-/tmp/sd-format}" 2>/dev/null)" = running ]; then
      echo '{"ok":false,"error":"sd_format","message":"An SD card is being formatted: wait until it is done."}'
      exit 0
    fi ;;
esac

# Running from flash (scripts/flashboot.sh): updates are code packages
# (src/flash/build-code.sh) written to the code zone of the flash by
# scripts/flash-code.sh — staged in RAM (/tmp), never on /mnt. The binaries in
# /usr are not updated from here. "rollback" clears the zone: the camera then
# runs the code built into /usr.
if [ "$(cat "${TC100_STORAGE_FILE:-/tmp/tc100-storage}" 2>/dev/null)" = flash ]; then
  FC="${FC_SCRIPT:-/usr/tc100/scripts/flash-code.sh}"
  FW="${FC_WORK:-/tmp/update}"
  SW="${UU_WORK:-/tmp/sysupd}"
  UU="${UU_SCRIPT:-/mnt/scripts/usr-update.sh}"
  _fz="$(sh "$FC" status 2>/dev/null)"
  case "$_fz" in "valid "*) _cur="${_fz#valid }" ;; *) _cur="$(cat /usr/tc100/VERSION 2>/dev/null) (built in)" ;; esac
  # Build identity (flash-code.sh info, code zone copy: the one in /usr may
  # predate it). Values are checked by the header parser: no quoting needed.
  FCI="${FC_INFO_SCRIPT:-/mnt/scripts/flash-code.sh}"
  _fi() { sh "$FCI" info $1 2>/dev/null | sed -n "s/^$2=//p"; }
  _cur_md5=""; _cur_built=""; _cur_commit=""
  case "$_fz" in "valid "*) _cur_md5="$(_fi "" md5)"; _cur_built="$(_fi "" built)"; _cur_commit="$(_fi "" commit)" ;; esac
  case "${REQUEST_METHOD:-GET}:$_cmd" in
    GET:status|GET:)
      _st=idle; _staged=""; _kind=""
      if [ -f "$FW/installing" ]; then _st=installing
      elif [ -f "$SW/ready" ]; then
        _st=staged; _kind=system; read -r _staged _r < "$SW/VERSION"
      elif [ -f "$FW/code.bin" ] && _chk="$(sh "$FC" check "$FW/code.bin")"; then
        _st=staged; _kind=code; set -- $_chk; _staged="$2"
        _s_md5="$(_fi "$FW/code.bin" md5)"; _s_built="$(_fi "$FW/code.bin" built)"; _s_commit="$(_fi "$FW/code.bin" commit)"
      fi
      _rb=""; case "$_fz" in "valid "*) _rb="built-in code" ;; esac
      # Update history (installs, confirmations, automatic rollbacks), JSON-escaped.
      _log="$(tail -n 6 "${FC_HISTORY:-/etc/jffs2/tc100/log/code-updates.log}" 2>/dev/null | awk '{ gsub(/[\\"]/, ""); printf "%s\\n", $0 }')"
      printf '{"ok":true,"storage":"flash","state":"%s","kind":"%s","current":"%s","current_md5":"%s","current_built":"%s","current_commit":"%s","staged":"%s","staged_md5":"%s","staged_built":"%s","staged_commit":"%s","rollback_to":"%s","log":"%s"}\n' \
        "$_st" "$_kind" "$_cur" "$_cur_md5" "$_cur_built" "$_cur_commit" "$_staged" "${_s_md5:-}" "${_s_built:-}" "${_s_commit:-}" "$_rb" "$_log" ;;
    POST:upload)
      _cl="${CONTENT_LENGTH:-0}"
      case "$_cl" in ''|*[!0-9]*) _cl=0 ;; esac
      if [ "$_cl" -gt 655360 ] && [ "$_cl" -le 6291456 ]; then
        # System package (/usr + code), unpacked in RAM. The video server is
        # stopped first: it holds most of the 33 MB.
        rm -rf "$SW" "$FW/code.bin"
        sh /mnt/controlscripts/rtsp-h26x stop </dev/null >/dev/null 2>&1
        sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
        _avail=$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo 2>/dev/null)
        [ -n "$_avail" ] || _avail=$(awk '/^(MemFree|Cached):/ { s += $2 } END { print s + 0 }' /proc/meminfo)
        if [ "$_avail" -lt $(( _cl / 1024 + 6144 )) ]; then
          head -c "$_cl" > /dev/null
          sh /mnt/controlscripts/rtsp-h26x start </dev/null >/dev/null 2>&1 &
          printf '{"ok":false,"error":"no_memory","message":"Not enough free memory (%s KB) to receive the system package."}\n' "$_avail"
          exit 0
        fi
        mkdir -p "$SW"
        head -c "$_cl" | tar -xf - -C "$SW" 2>/dev/null
        if _chk="$(sh "$UU" check "$SW" 2>&1)"; then
          set -- $_chk
          printf '{"ok":true,"kind":"system","version":"%s","current":"%s","changed":1,"files":1}\n' "$2" "$_cur"
        else
          rm -rf "$SW"
          sh /mnt/controlscripts/rtsp-h26x start </dev/null >/dev/null 2>&1 &
          _chk="$(printf '%s' "${_chk#refused }" | awk '{ gsub(/[\\"]/, ""); printf "%s", $0 }')"
          printf '{"ok":false,"error":"invalid_package","message":"Not a valid system package: %s."}\n' "$_chk"
        fi
        exit 0
      fi
      if [ "$_cl" -le 4096 ] || [ "$_cl" -gt 655360 ]; then
        echo '{"ok":false,"error":"invalid_size","message":"From flash, upload a code package (tc100-code-VERSION.bin, at most 640 KB) or a system package (tc100-system-VERSION.tar)."}'
        exit 0
      fi
      mkdir -p "$FW"; rm -f "$FW/code.bin"
      head -c "$_cl" > "$FW/code.bin" 2>/dev/null
      if _chk="$(sh "$FC" check "$FW/code.bin")"; then
        set -- $_chk
        _p_md5="$(_fi "$FW/code.bin" md5)"
        # Same version as the running code but another build: worth a look
        # before installing (an older file with the same name, 2026-10-18).
        _same=0; [ "$2" = "$_cur" ] && [ -n "$_cur_md5" ] && [ "$_p_md5" != "$_cur_md5" ] && _same=1
        [ "$2" = "$_cur" ] && [ "$_p_md5" = "$_cur_md5" ] && _same=2
        printf '{"ok":true,"kind":"code","version":"%s","current":"%s","md5":"%s","built":"%s","commit":"%s","current_md5":"%s","current_built":"%s","current_commit":"%s","same_version":%s,"changed":1,"files":1}\n' \
          "$2" "$_cur" "$_p_md5" "$(_fi "$FW/code.bin" built)" "$(_fi "$FW/code.bin" commit)" "$_cur_md5" "$_cur_built" "$_cur_commit" "$_same"
      else
        rm -f "$FW/code.bin"
        printf '{"ok":false,"error":"invalid_package","message":"Not a valid code package: %s."}\n' "$_chk"
      fi ;;
    POST:install)
      if [ -f "$SW/ready" ]; then
        # The installer stops everything that runs from /usr, this web server
        # included: it runs from RAM with the rootfs shell (usr-update.sh).
        cp "$UU" "$SW/usr-update.sh" && cp "$FC" "$SW/flash-code.sh" &&
          cp "${FM:-/mnt/scripts/flashmode-once.sh}" "$SW/flashmode-once.sh" || {
          echo '{"ok":false,"error":"copy","message":"Could not prepare the installer."}'; exit 0; }
        # (not ": > file || ...": a failed redirection of a special builtin
        # ends a non-interactive ash, and this request answered nothing)
        mkdir -p "$FW"; touch "$FW/installing"
        ( trap '' HUP TERM; exec /bin/sh "$SW/usr-update.sh" install "$SW" ) </dev/null >/dev/null 2>&1 &
        echo '{"ok":true,"started":"install","kind":"system"}'
        exit 0
      fi
      if ! sh "$FC" check "$FW/code.bin" >/dev/null 2>&1; then
        echo '{"ok":false,"error":"nothing_staged","message":"Upload a code package first."}'; exit 0
      fi
      mkdir -p "$FW"; touch "$FW/installing"
      # An SD card with the firmware hook would start instead of the new code:
      # one boot from flash (usr-update.sh oneshot). Both scripts are copied to
      # RAM first: /mnt/scripts is the code zone being rewritten.
      cp "$UU" /tmp/usr-update.sh 2>/dev/null; cp "${FM:-/mnt/scripts/flashmode-once.sh}" /tmp/flashmode-once.sh 2>/dev/null
      ( trap '' HUP
        if sh "$FC" write "$FW/code.bin" >/dev/null 2>&1; then rm -f "$FW/code.bin"
          [ -s /tmp/usr-update.sh ] && sh /tmp/usr-update.sh oneshot /tmp/flashmode-once.sh >/dev/null 2>&1
          fl_reboot_intent "web: code update"; sync; reboot
        else rm -f "$FW/installing"; fi ) </dev/null >/dev/null 2>&1 &
      echo '{"ok":true,"started":"install"}' ;;
    POST:rollback)
      mkdir -p "$FW"; touch "$FW/installing"
      cp "$UU" /tmp/usr-update.sh 2>/dev/null; cp "${FM:-/mnt/scripts/flashmode-once.sh}" /tmp/flashmode-once.sh 2>/dev/null
      ( trap '' HUP
        if sh "$FC" clear >/dev/null 2>&1; then
          [ -s /tmp/usr-update.sh ] && sh /tmp/usr-update.sh oneshot /tmp/flashmode-once.sh >/dev/null 2>&1
          fl_reboot_intent "web: code rollback"; sync; reboot
        else rm -f "$FW/installing"; fi ) </dev/null >/dev/null 2>&1 &
      echo '{"ok":true,"started":"rollback"}' ;;
    POST:discard)
      rm -f "$FW/code.bin"
      if [ -d "$SW" ]; then rm -rf "$SW"; sh /mnt/controlscripts/rtsp-h26x start </dev/null >/dev/null 2>&1 & fi
      echo '{"ok":true}' ;;
    *)
      echo '{"ok":false,"error":"unknown_command"}' ;;
  esac
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
