#!/bin/sh

if [ -r /mnt/www/cgi-bin/func.cgi ]; then
  . /mnt/www/cgi-bin/func.cgi
else
  . ./func.cgi
fi

TMP_ROOT="/tmp"
MAX_ARCHIVE_BYTES=16777216

html_header() {
  echo "Content-type: text/html"
  echo "Pragma: no-cache"
  echo "Cache-Control: max-age=0, no-store, no-cache"
  echo ""
}

is_truthy() {
  case "$1" in
    1|true|on|yes|enabled)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

sanitize_int() {
  value="$1"
  fallback="$2"
  case "$value" in
    ''|*[!0-9]*)
      echo "$fallback"
      ;;
    *)
      echo "$value"
      ;;
  esac
}

create_archive() {
  archive_path="$1"
  source_root="$2"
  source_name="$3"
  tmp_plain="$archive_path.raw"

  rm -f "$archive_path" "$tmp_plain"

  if tar -czf "$archive_path" -C "$source_root" "$source_name" >/dev/null 2>&1; then
    return 0
  fi
  if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox tar -czf "$archive_path" -C "$source_root" "$source_name" >/dev/null 2>&1; then
    return 0
  fi

  if tar -cf "$tmp_plain" -C "$source_root" "$source_name" >/dev/null 2>&1; then
    if gzip -c "$tmp_plain" > "$archive_path" 2>/dev/null; then
      rm -f "$tmp_plain"
      return 0
    fi
    if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox gzip -c "$tmp_plain" > "$archive_path" 2>/dev/null; then
      rm -f "$tmp_plain"
      return 0
    fi
  fi
  if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox tar -cf "$tmp_plain" -C "$source_root" "$source_name" >/dev/null 2>&1; then
    if gzip -c "$tmp_plain" > "$archive_path" 2>/dev/null; then
      rm -f "$tmp_plain"
      return 0
    fi
    if /mnt/bin/busybox gzip -c "$tmp_plain" > "$archive_path" 2>/dev/null; then
      rm -f "$tmp_plain"
      return 0
    fi
  fi

  rm -f "$archive_path" "$tmp_plain"
  return 1
}

list_archive_entries() {
  archive_path="$1"
  if tar -tzf "$archive_path" 2>/dev/null; then
    return 0
  fi
  if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox tar -tzf "$archive_path" 2>/dev/null; then
    return 0
  fi
  if tar -tf "$archive_path" 2>/dev/null; then
    return 0
  fi
  if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox tar -tf "$archive_path" 2>/dev/null; then
    return 0
  fi
  return 1
}

extract_archive() {
  archive_path="$1"
  dest_root="$2"
  if tar -xzf "$archive_path" -C "$dest_root" >/dev/null 2>&1; then
    return 0
  fi
  if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox tar -xzf "$archive_path" -C "$dest_root" >/dev/null 2>&1; then
    return 0
  fi
  if tar -xf "$archive_path" -C "$dest_root" >/dev/null 2>&1; then
    return 0
  fi
  if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox tar -xf "$archive_path" -C "$dest_root" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

download_backup() {
  now_tag="$(date -u +%Y%m%d-%H%M%S 2>/dev/null)"
  case "$now_tag" in
    ''|*[!0-9-]*)
      now_tag="unknown"
      ;;
  esac

  archive_path="$TMP_ROOT/config-backup-$now_tag.tar.gz"
  file_name="camera-config-$now_tag.tar.gz"

  if ! create_archive "$archive_path" /mnt config; then
    html_header
    echo "Failed to build backup archive."
    return 1
  fi

  archive_size="$(wc -c < "$archive_path" 2>/dev/null)"
  archive_size="$(sanitize_int "$archive_size" 0)"

  echo "Content-type: application/gzip"
  echo "Content-Disposition: attachment; filename=\"$file_name\""
  echo "Content-Length: $archive_size"
  echo "Cache-Control: no-store"
  echo ""
  cat "$archive_path"
  rm -f "$archive_path"
  return 0
}

validate_archive_path() {
  archive_path="$1"
  case "$archive_path" in
    /tmp/*) ;;
    *)
      return 1
      ;;
  esac
  case "$archive_path" in
    *".."*)
      return 1
      ;;
  esac
  return 0
}

validate_archive_entries() {
  archive_path="$1"
  entry_list="$(list_archive_entries "$archive_path")" || return 1
  [ -n "$entry_list" ] || return 1

  invalid=0
  while IFS= read -r entry; do
    [ -n "$entry" ] || continue
    case "$entry" in
      config|config/*) ;;
      *)
        invalid=1
        ;;
    esac
    case "$entry" in
      /?*|../*|*/../*|*/..|..)
        invalid=1
        ;;
    esac
  done <<EOF
$entry_list
EOF

  [ "$invalid" -eq 0 ]
}

restore_backup() {
  archive_path="$1"
  restart_services="$2"
  now_tag="$(date -u +%Y%m%d-%H%M%S 2>/dev/null)"
  case "$now_tag" in
    ''|*[!0-9-]*)
      now_tag="unknown"
      ;;
  esac
  rollback_archive="$TMP_ROOT/config-rollback-$now_tag.tar.gz"

  if ! create_archive "$rollback_archive" /mnt config; then
    html_header
    echo "Restore aborted: failed to create rollback archive."
    return 1
  fi

  if ! extract_archive "$archive_path" /mnt; then
    html_header
    echo "Restore failed while extracting archive."
    echo "<br/>Rollback archive: $rollback_archive"
    return 1
  fi

  html_header
  echo "Config restore completed from: $archive_path"
  echo "<br/>Rollback archive: $rollback_archive"
  echo "<br/>"

  if is_truthy "$restart_services"; then
    /mnt/controlscripts/rtsp-h26x restart >/dev/null 2>&1 || true
    /mnt/controlscripts/onvif restart >/dev/null 2>&1 || true
    echo "<br/>RTSP/ONVIF restart requested."
  fi

  echo "<br/>Reboot is recommended if boot-level settings were restored."
  return 0
}

case "$F_cmd" in
  download)
    download_backup
    ;;
  restore)
    csrf_guard
    archive_path="${F_archive_path}"
    restart_services="${F_restart_services}"

    if ! validate_archive_path "$archive_path"; then
      html_header
      echo "Invalid archive path. Only /tmp/*.tar.gz is allowed."
      exit 0
    fi
    if [ ! -f "$archive_path" ]; then
      html_header
      echo "Archive file not found: $archive_path"
      exit 0
    fi

    archive_size="$(wc -c < "$archive_path" 2>/dev/null)"
    archive_size="$(sanitize_int "$archive_size" 0)"
    if [ "$archive_size" -le 0 ] || [ "$archive_size" -gt "$MAX_ARCHIVE_BYTES" ]; then
      html_header
      echo "Archive size is invalid or too large (max ${MAX_ARCHIVE_BYTES} bytes)."
      exit 0
    fi

    if ! validate_archive_entries "$archive_path"; then
      html_header
      echo "Archive validation failed. Expected entries under config/ only."
      exit 0
    fi

    # restore_backup prints its own response headers/body.
    restore_backup "$archive_path" "$restart_services"
    ;;
  *)
    html_header
    echo "Usage:"
    echo "<br/>cgi-bin/configbackup.cgi?cmd=download"
    echo "<br/>cgi-bin/configbackup.cgi?cmd=restore (POST: archive_path=/tmp/..tar.gz)"
    ;;
esac

exit 0
