#!/bin/sh
# upload_backup.cgi — Accepts a raw binary POST of a config backup tar.gz,
# saves it to /tmp, validates it, and restores it.
# The backup.html frontend sends the file as application/octet-stream.

if [ -r /mnt/www/cgi-bin/func.cgi ]; then
  . /mnt/www/cgi-bin/func.cgi
else
  . ./func.cgi
fi

MAX_UPLOAD_BYTES=16777216
TMP_ROOT="/tmp"

html_header() {
  echo "Content-type: text/html"
  echo "Pragma: no-cache"
  echo "Cache-Control: no-store, no-cache"
  echo ""
}

sanitize_int() {
  value="$1"; fallback="$2"
  case "$value" in
    ''|*[!0-9]*) echo "$fallback" ;;
    *) echo "$value" ;;
  esac
}

rate_limit_check 2 300
csrf_guard

if [ "$REQUEST_METHOD" != "POST" ]; then
  html_header
  echo "Method not allowed."
  exit 0
fi

content_length="$(sanitize_int "${CONTENT_LENGTH:-0}" 0)"
if [ "$content_length" -le 0 ]; then
  html_header
  echo "No file data received."
  exit 0
fi

if [ "$content_length" -gt "$MAX_UPLOAD_BYTES" ]; then
  html_header
  echo "Upload too large (max 16 MB)."
  exit 0
fi

restart_services="${F_restart_services:-0}"
case "$restart_services" in
  1|true|on|yes) restart_services=1 ;;
  *) restart_services=0 ;;
esac

_ub_btime=0
while read -r _k _v _; do [ "$_k" = "btime" ] && _ub_btime="$_v" && break; done < /proc/stat
read -r _ub_up _ < /proc/uptime
_ub_ts=$((_ub_btime + ${_ub_up%.*}))

archive_path="$TMP_ROOT/config-upload-${_ub_ts}-$$.tar.gz"

if ! head -c "$content_length" > "$archive_path" 2>/dev/null; then
  html_header
  echo "Failed to write uploaded file."
  rm -f "$archive_path"
  exit 0
fi

# Validate: must be a non-empty file
if [ ! -s "$archive_path" ]; then
  html_header
  echo "Uploaded file is empty."
  rm -f "$archive_path"
  exit 0
fi

# Delegate to configbackup.cgi restore logic via sourcing its functions.
# We reconstruct the env vars configbackup.cgi expects.
F_archive_path="$archive_path"
F_restart_services="$restart_services"
F_cmd="restore"

# Source configbackup.cgi logic by re-executing it with the right env.
# Simpler: just call it as a subprocess with the right query string.
# Note: configbackup.cgi expects F_* vars from func.cgi; we already sourced it.
# Since validate_archive_path and restore_backup are defined in configbackup.cgi
# and not available here, we exec configbackup.cgi with QUERY_STRING set.

QUERY_STRING="cmd=restore&archive_path=${archive_path}&restart_services=${restart_services}"
REQUEST_METHOD="GET"
export QUERY_STRING REQUEST_METHOD F_cmd F_archive_path F_restart_services

exec /mnt/www/cgi-bin/configbackup.cgi
