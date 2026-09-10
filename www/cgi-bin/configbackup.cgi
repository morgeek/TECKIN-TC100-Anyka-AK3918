#!/bin/sh

if [ -r /mnt/www/cgi-bin/func.cgi ]; then
  . /mnt/www/cgi-bin/func.cgi
else
  . ./func.cgi
fi

if [ -r "${CONFIG_TX_LIB:-/mnt/scripts/config-transaction.sh}" ]; then
  . "${CONFIG_TX_LIB:-/mnt/scripts/config-transaction.sh}"
elif [ -r ../../scripts/config-transaction.sh ]; then
  . ../../scripts/config-transaction.sh
fi

TMP_ROOT="${TMP_ROOT:-/tmp}"
MNT_ROOT="${TC_MNT_ROOT:-/mnt}"
CONFIG_ROOT="${TC_CONFIG_ROOT:-$MNT_ROOT/config}"
MAX_ARCHIVE_BYTES=1048576

_BTIME=0
_read_btime() {
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _BTIME="$_v" && break
  done < /proc/stat
}
_read_ts() {
  [ "$_BTIME" -gt 0 ] || _read_btime
  read -r _up _ < /proc/uptime
  now_ts=$((_BTIME + ${_up%.*}))
  [ "$now_ts" -gt 0 ] || now_ts=0
}
_format_backup_tag() {
  date '+%Y%m%d-%H%M%S'
}

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
  set -- $value; value="${1:-}"
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

download_backup() {
  _read_ts
  now_tag="$(_format_backup_tag "$now_ts")-$$"
  case "$now_tag" in
    ''|*[!0-9-]*)
      now_tag="unknown"
      ;;
  esac

  archive_path="$TMP_ROOT/config-backup-$now_tag.tar.gz"
  file_name="camera-config-$now_tag.tar.gz"

  if ! create_archive "$archive_path" "$MNT_ROOT" config; then
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
    *".."*|*[!A-Za-z0-9_./-]*)
      return 1
      ;;
  esac
  return 0
}

archive_to_plain() {
  archive_path="$1"; plain_path="$2"
  rm -f "$plain_path"
  if gzip -dc "$archive_path" 2>/dev/null | head -c 2097153 > "$plain_path"; then
    [ -s "$plain_path" ] && return 0
  fi
  rm -f "$plain_path"
  if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox gzip -dc "$archive_path" 2>/dev/null | head -c 2097153 > "$plain_path"; then
    [ -s "$plain_path" ] && return 0
  fi
  rm -f "$plain_path"
  return 1
}

list_plain_entries() {
  plain_path="$1"
  if tar -tf "$plain_path" 2>/dev/null; then return 0; fi
  if [ -x /mnt/bin/busybox ]; then /mnt/bin/busybox tar -tf "$plain_path" 2>/dev/null; return $?; fi
  return 1
}

list_plain_verbose() {
  plain_path="$1"
  if tar -tvf "$plain_path" 2>/dev/null; then return 0; fi
  if [ -x /mnt/bin/busybox ]; then /mnt/bin/busybox tar -tvf "$plain_path" 2>/dev/null; return $?; fi
  return 1
}

extract_plain_archive() {
  plain_path="$1"; dest_root="$2"
  if tar -xf "$plain_path" -C "$dest_root" >/dev/null 2>&1; then return 0; fi
  if [ -x /mnt/bin/busybox ]; then /mnt/bin/busybox tar -xf "$plain_path" -C "$dest_root" >/dev/null 2>&1; return $?; fi
  return 1
}

validate_archive_entries() {
  archive_path="$1"
  plain_path="$TMP_ROOT/config-validate.$$.tar"
  if ! archive_to_plain "$archive_path" "$plain_path"; then return 1; fi
  _expanded="$(wc -c < "$plain_path" 2>/dev/null)"
  case "$_expanded" in ''|*[!0-9[:space:]]*) rm -f "$plain_path"; return 1 ;; esac
  if [ "$_expanded" -le 0 ] || [ "$_expanded" -gt 2097152 ]; then rm -f "$plain_path"; return 1; fi

  _types="$TMP_ROOT/config-types.$$.txt"
  if ! list_plain_verbose "$plain_path" > "$_types"; then rm -f "$plain_path" "$_types"; return 1; fi
  if ! awk 'substr($0,1,1) != "-" && substr($0,1,1) != "d" {bad=1} END {exit (bad || NR > 512)}' "$_types"; then
    rm -f "$plain_path" "$_types"; return 1
  fi
  entry_file="$TMP_ROOT/config-entries.$$.txt"
  if ! list_plain_entries "$plain_path" > "$entry_file"; then rm -f "$plain_path" "$_types" "$entry_file"; return 1; fi
  rm -f "$plain_path" "$_types"

  invalid=0; count=0
  while IFS= read -r entry; do
    [ -n "$entry" ] || continue
    count=$((count + 1))
    case "$entry" in config|config/*) ;; *) invalid=1 ;; esac
    case "$entry" in /?*|../*|*/../*|*/..|..|*[!A-Za-z0-9_./-]*) invalid=1 ;; esac
  done < "$entry_file"
  rm -f "$entry_file"
  [ "$count" -gt 0 ] && [ "$invalid" -eq 0 ]
}

restore_backup() {
  restore_input="$1"
  restart_services="$2"
  _read_ts
  now_tag="$(_format_backup_tag "$now_ts")-$$"
  case "$now_tag" in ''|*[!0-9-]*) now_tag="unknown" ;; esac
  rollback_archive="$TMP_ROOT/config-rollback-$now_tag.tar.gz"
  stage_root="$TMP_ROOT/config-restore-stage.$$"
  transaction_backup="$TMP_ROOT/config-restore-transaction.$$"
  plain_archive="$TMP_ROOT/config-restore.$$.tar"

  if ! command -v tc_commit_config_files >/dev/null 2>&1; then
    html_header; echo "Restore aborted: configuration validator is unavailable."; return 1
  fi
  if ! create_archive "$rollback_archive" "$MNT_ROOT" config; then
    html_header; echo "Restore aborted: failed to create rollback archive."; return 1
  fi
  rm -rf "$stage_root" "$transaction_backup"
  mkdir -p "$stage_root" || { html_header; echo "Restore aborted: staging area unavailable."; return 1; }
  if ! archive_to_plain "$restore_input" "$plain_archive" || ! extract_plain_archive "$plain_archive" "$stage_root"; then
    rm -rf "$stage_root" "$transaction_backup"; rm -f "$plain_archive"
    html_header; echo "Restore failed while staging archive. Active configuration was preserved."; return 1
  fi
  rm -f "$plain_archive"
  if [ ! -d "$stage_root/config" ]; then
    rm -rf "$stage_root" "$transaction_backup"
    html_header; echo "Restore rejected: config directory missing. Active configuration was preserved."; return 1
  fi

  restore_files=""
  find "$stage_root/config" -type f 2>/dev/null | while IFS= read -r staged_file; do
    printf '%s\n' "${staged_file#"$stage_root/config/"}"
  done > "$stage_root/file-list"
  while IFS= read -r restore_rel; do
    [ -n "$restore_rel" ] || continue
    case "$restore_rel" in *[!A-Za-z0-9_./-]*|*/../*|../*)
      rm -rf "$stage_root" "$transaction_backup"
      html_header; echo "Restore rejected: unsafe file name. Active configuration was preserved."; return 1 ;;
    esac
    restore_files="$restore_files $restore_rel"
  done < "$stage_root/file-list"
  [ -n "$restore_files" ] || {
    rm -rf "$stage_root" "$transaction_backup"
    html_header; echo "Restore rejected: archive contains no configuration files."; return 1
  }

  if ! tc_commit_config_files "$stage_root/config" "$CONFIG_ROOT" "$transaction_backup" "$restore_files"; then
    restore_error="${TC_CONFIG_ERROR:-transaction failed}"
    rm -rf "$stage_root" "$transaction_backup"
    html_header
    echo "Restore rejected ($restore_error). Active configuration was preserved or rolled back."
    echo "<br/>Rollback archive: $rollback_archive"
    return 1
  fi
  restored_count="$TC_COMMIT_COUNT"
  rm -rf "$stage_root" "$transaction_backup"

  html_header
  echo "Config restore completed transactionally ($restored_count changed file(s))."
  echo "<br/>Rollback archive: $rollback_archive"
  if is_truthy "$restart_services"; then
    "$MNT_ROOT/controlscripts/rtsp-h26x" restart >/dev/null 2>&1 || true
    "$MNT_ROOT/controlscripts/onvif" restart >/dev/null 2>&1 || true
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
    mutation_guard
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
