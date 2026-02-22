#!/bin/sh
set -eu

PKG_ROOT="${PKG_ROOT:-/mnt}"
BIN_DIR="$PKG_ROOT/bin"
LIB_DIR="$PKG_ROOT/lib"
BACKUP_ROOT="$PKG_ROOT/backup/package-upgrades"
LOG_FILE="$PKG_ROOT/log/pkg-upgrade.log"
LOCK_FILE="$PKG_ROOT/config/packages.lock"

timestamp()
{
  date +"%Y%m%d-%H%M%S"
}

log_msg()
{
  msg="$1"
  mkdir -p "$(dirname "$LOG_FILE")" >/dev/null 2>&1 || true
  printf '%s %s\n' "$(date +"%Y-%m-%d %H:%M:%S")" "$msg" >> "$LOG_FILE"
  printf '%s\n' "$msg"
}

usage()
{
  cat <<EOF
Usage:
  /mnt/scripts/pkg-upgrade-safe.sh backup
  /mnt/scripts/pkg-upgrade-safe.sh apply <bundle_dir>
  /mnt/scripts/pkg-upgrade-safe.sh rollback <backup_id>
  /mnt/scripts/pkg-upgrade-safe.sh status

Bundle layout:
  <bundle_dir>/bin/<files...> and/or <bundle_dir>/lib/<files...>
EOF
}

hash_file()
{
  f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  elif command -v md5sum >/dev/null 2>&1; then
    md5sum "$f" | awk '{print $1}'
  else
    cksum "$f" | awk '{print $1 ":" $2}'
  fi
}

generate_lock()
{
  out="$1"
  tmp="$out.tmp.$$"
  mkdir -p "$(dirname "$out")"
  {
    echo "# package lock generated $(date +"%Y-%m-%d %H:%M:%S")"
    for dir in "$BIN_DIR" "$LIB_DIR"; do
      [ -d "$dir" ] || continue
      for f in "$dir"/*; do
        [ -f "$f" ] || continue
        rel="${f#$PKG_ROOT/}"
        printf '%s|%s\n' "$rel" "$(hash_file "$f")"
      done
    done
  } > "$tmp"
  mv "$tmp" "$out"
}

list_bundle_files()
{
  bundle="$1"
  if [ -d "$bundle/bin" ]; then
    find "$bundle/bin" -maxdepth 1 -type f | sort
  fi
  if [ -d "$bundle/lib" ]; then
    find "$bundle/lib" -maxdepth 1 -type f | sort
  fi
}

bundle_rel_path()
{
  bundle="$1"
  f="$2"
  printf '%s\n' "${f#$bundle/}"
}

backup_file()
{
  src="$1"
  dest="$2"
  mkdir -p "$(dirname "$dest")"
  cp -Pp "$src" "$dest"
}

restore_manifest()
{
  backup_dir="$1"
  manifest="$backup_dir/manifest.txt"

  if [ ! -f "$manifest" ]; then
    log_msg "Rollback failed: missing manifest in $backup_dir"
    return 1
  fi

  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    src="$backup_dir/current/$rel"
    dst="$PKG_ROOT/$rel"
    if [ -f "$src" ] || [ -L "$src" ]; then
      mkdir -p "$(dirname "$dst")"
      cp -Pp "$src" "$dst"
    fi
  done < "$manifest"

  # Keep SONAME self-heal consistent with autorun fallback behavior.
  if [ -e "$LIB_DIR/libcurl.so.4.8.0" ] && [ ! -e "$LIB_DIR/libcurl.so.4" ]; then
    ln -s "$LIB_DIR/libcurl.so.4.8.0" "$LIB_DIR/libcurl.so.4" >/dev/null 2>&1 || true
  fi
}

do_backup()
{
  id="$(timestamp)"
  backup_dir="$BACKUP_ROOT/$id"
  mkdir -p "$backup_dir/current/bin" "$backup_dir/current/lib"

  for f in "$BIN_DIR"/*; do
    [ -f "$f" ] || continue
    backup_file "$f" "$backup_dir/current/bin/$(basename "$f")"
  done

  for f in "$LIB_DIR"/*; do
    [ -f "$f" ] || [ -L "$f" ] || continue
    backup_file "$f" "$backup_dir/current/lib/$(basename "$f")"
  done

  generate_lock "$backup_dir/packages.lock"
  log_msg "Backup created: $id"
}

do_apply()
{
  bundle="${1:-}"
  if [ -z "$bundle" ] || [ ! -d "$bundle" ]; then
    log_msg "Apply failed: bundle directory missing"
    return 1
  fi

  has_bin=0
  has_lib=0
  [ -d "$bundle/bin" ] && [ "$(find "$bundle/bin" -maxdepth 1 -type f | wc -l | tr -d ' ')" -gt 0 ] && has_bin=1
  [ -d "$bundle/lib" ] && [ "$(find "$bundle/lib" -maxdepth 1 -type f | wc -l | tr -d ' ')" -gt 0 ] && has_lib=1
  if [ "$has_bin" -eq 0 ] && [ "$has_lib" -eq 0 ]; then
    log_msg "Apply failed: bundle has no files in bin/ or lib/"
    return 1
  fi

  id="$(timestamp)"
  backup_dir="$BACKUP_ROOT/$id"
  mkdir -p "$backup_dir/current"
  manifest="$backup_dir/manifest.txt"
  : > "$manifest"

  rollback_needed=0
  for src in $(list_bundle_files "$bundle"); do
    rel="$(bundle_rel_path "$bundle" "$src")"
    dst="$PKG_ROOT/$rel"
    tmp="$dst.new.$$"

    if [ ! -e "$dst" ] && [ ! -L "$dst" ]; then
      log_msg "Apply blocked: target does not exist in baseline: $rel"
      rollback_needed=1
      break
    fi

    backup_file "$dst" "$backup_dir/current/$rel"
    printf '%s\n' "$rel" >> "$manifest"

    cp "$src" "$tmp"
    case "$rel" in
      bin/*) chmod 0755 "$tmp" ;;
      lib/*) chmod 0644 "$tmp" ;;
    esac

    if ! mv "$tmp" "$dst"; then
      rm -f "$tmp" >/dev/null 2>&1 || true
      log_msg "Apply failed while replacing $rel"
      rollback_needed=1
      break
    fi
  done

  if [ "$rollback_needed" -eq 1 ]; then
    log_msg "Apply failed. Rolling back from $id"
    restore_manifest "$backup_dir" || true
    return 1
  fi

  if [ -e "$LIB_DIR/libcurl.so.4.8.0" ] && [ ! -e "$LIB_DIR/libcurl.so.4" ]; then
    ln -s "$LIB_DIR/libcurl.so.4.8.0" "$LIB_DIR/libcurl.so.4" >/dev/null 2>&1 || true
  fi

  generate_lock "$LOCK_FILE"
  sync >/dev/null 2>&1 || true
  log_msg "Apply succeeded. Backup id: $id"
}

do_rollback()
{
  id="${1:-}"
  if [ -z "$id" ]; then
    log_msg "Rollback failed: missing backup id"
    return 1
  fi

  backup_dir="$BACKUP_ROOT/$id"
  if [ ! -d "$backup_dir" ]; then
    log_msg "Rollback failed: backup not found: $id"
    return 1
  fi

  restore_manifest "$backup_dir"
  generate_lock "$LOCK_FILE"
  sync >/dev/null 2>&1 || true
  log_msg "Rollback completed from backup: $id"
}

do_status()
{
  echo "Package root: $PKG_ROOT"
  echo "Backup root:  $BACKUP_ROOT"
  echo "Log file:     $LOG_FILE"
  if [ -d "$BACKUP_ROOT" ]; then
    echo "Backups:"
    ls -1 "$BACKUP_ROOT" | tail -n 10
  else
    echo "Backups: none"
  fi
}

cmd="${1:-}"
case "$cmd" in
  backup)
    do_backup
    ;;
  apply)
    do_apply "${2:-}"
    ;;
  rollback)
    do_rollback "${2:-}"
    ;;
  status)
    do_status
    ;;
  *)
    usage
    exit 1
    ;;
esac
