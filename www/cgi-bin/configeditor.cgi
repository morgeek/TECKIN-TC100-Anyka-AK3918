#!/bin/sh
# configeditor.cgi — Read and write allowed /mnt/config/* files as plain text.
# GET  ?file=<name>         → JSON {"ok":true,"content":"...","file":"..."}
# POST ?cmd=save&file=<name> body: raw file content (text/plain)

FUNC_CGI_SKIP_BODY=1
if [ -r /mnt/www/cgi-bin/func.cgi ]; then
  . /mnt/www/cgi-bin/func.cgi
else
  . ./func.cgi
fi

CONFIG_ROOT="/mnt/config"
MAX_WRITE_BYTES=65536

# Whitelist of editable config files (base names only)
is_allowed_file() {
  case "$1" in
    boot.conf|mqtt.conf|rtspserver.conf|recording.conf|onvif.conf|\
    hostname.conf|ntp_srv.conf|timezone.conf|telegram.conf|\
    netmon.conf|dns.conf|motion.conf|timelapse.conf|pttvolume.conf)
      return 0 ;;
    *) return 1 ;;
  esac
}

sanitize_filename() {
  # Allow only basename, alphanumeric + dot + underscore + hyphen
  _fn="${1##*/}"
  case "$_fn" in
    ''|*[!A-Za-z0-9._-]*|..*|.) echo ""; return 1 ;;
  esac
  echo "$_fn"
}

emit_headers() {
  echo "Content-type: application/json"
  echo "Pragma: no-cache"
  echo "Cache-Control: no-store, no-cache"
  echo ""
}

json_str() {
  # Escape a string for JSON embedding
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}' | sed '$ s/\\n$//'
}

if [ "$F_cmd" = "save" ]; then
  rate_limit_check 5 60
  mutation_guard
fi

emit_headers

_file="$(sanitize_filename "${F_file:-}")"
if [ -z "$_file" ] || ! is_allowed_file "$_file"; then
  printf '{"ok":false,"error":"File not allowed or invalid name"}\n'
  exit 0
fi

_path="$CONFIG_ROOT/$_file"

case "${F_cmd:-read}" in
  read)
    if [ ! -f "$_path" ]; then
      # Try .dist template
      if [ -f "${_path}.dist" ]; then
        _content="$(cat "${_path}.dist" 2>/dev/null)"
        _source="dist"
      else
        printf '{"ok":false,"error":"File not found"}\n'
        exit 0
      fi
    else
      _content="$(cat "$_path" 2>/dev/null)"
      _source="config"
    fi
    # Emit JSON with content as escaped string
    printf '{"ok":true,"file":"%s","source":"%s","content":"%s"}\n' \
      "$_file" "$_source" "$(printf '%s' "$_content" | sed 's/\\/\\\\/g; s/"/\\"/g; s/$/\\n/' | tr -d '\n' | sed 's/\\n$//')"
    ;;

  save)
    _cl="${CONTENT_LENGTH:-0}"
    case "$_cl" in ''|*[!0-9]*) _cl=0 ;; esac
    if [ "$_cl" -le 0 ]; then
      printf '{"ok":false,"error":"No content received"}\n'
      exit 0
    fi
    if [ "$_cl" -gt "$MAX_WRITE_BYTES" ]; then
      printf '{"ok":false,"error":"Content too large (max 64 KB)"}\n'
      exit 0
    fi
    _tmp="${_path}.write.$$"
    _lock="/tmp/configeditor-${_file}.lock"
    if ! mkdir "$_lock" 2>/dev/null; then
      printf '{"ok":false,"error":"Configuration is busy; retry shortly"}\n'
      exit 0
    fi
    trap 'rm -f "$_tmp"; rmdir "$_lock" 2>/dev/null' EXIT
    trap 'exit 1' INT TERM
    if ! head -c "$_cl" > "$_tmp" || [ "$(wc -c < "$_tmp")" -ne "$_cl" ]; then
      printf '{"ok":false,"error":"Incomplete upload; original configuration preserved"}\n'
      exit 0
    fi
    # Only these files use shell assignments; RTSP/ONVIF and one-line files do not.
    case "$_file" in
      boot.conf|mqtt.conf|recording.conf|telegram.conf|netmon.conf|dns.conf|motion.conf|timelapse.conf)
        if ! sh -n "$_tmp" 2>/dev/null; then
          printf '{"ok":false,"error":"Invalid configuration syntax; original preserved"}\n'
          exit 0
        fi ;;
    esac
    if [ -f "$_path" ] && cmp -s "$_tmp" "$_path"; then
      printf '{"ok":true,"file":"%s","message":"Unchanged"}\n' "$_file"
      exit 0
    fi
    if [ -f "$_path" ] && ! cp "$_path" "/tmp/configeditor-backup-${_file}"; then
      printf '{"ok":false,"error":"Cannot create backup; original preserved"}\n'
      exit 0
    fi
    if mv "$_tmp" "$_path"; then
      sync
      audit_log_event "configeditor_save" "$_file"
      printf '{"ok":true,"file":"%s","message":"Saved successfully"}\n' "$_file"
    else
      printf '{"ok":false,"error":"Write failed; check SD card"}\n'
    fi
    ;;

  *)
    printf '{"ok":false,"error":"Unknown command"}\n'
    ;;
esac
