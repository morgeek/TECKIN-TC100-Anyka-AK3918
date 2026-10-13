#!/bin/sh
# fw-update.sh — install a firmware update package on the SD card, safely.
#
#   verify <package.tar>   unpack to the staging area and check it (MANIFEST
#                          md5 of every file, shell syntax, no path escapes);
#                          prints a JSON summary
#   install [--no-reboot]  install the staged package (see below), then reboot
#   rollback [--no-reboot] restore the files the last install replaced
#   discard                drop the staged package
#   status                 JSON: current/staged version, state, last backup
#
# A package is a plain tar built by src/release/build-update.sh: the SD-card
# payload (bin/ lib/ www/ scripts/ ...) plus MANIFEST ("md5  path" per file)
# and its VERSION file.
#
# install, file by file:
#   * unchanged files (same md5) are skipped;
#   * user-owned files are left alone: config/autostart/<service> toggles
#     (except the 0?_system-* boot hooks) are never added or replaced — their
#     presence is the user's "start at boot" choice — and
#     wpa_supplicant.conf.dist (holds the Wi-Fi credentials) is only added
#     when missing;
#   * a replaced file is copied to the backup first, then the new one is
#     written next to it and renamed over it. Renaming (never rewriting in
#     place) is what makes this safe for running binaries ("Text file busy")
#     and for shell scripts being executed.
# Then config-migrate.sh adds new settings, and the web server config is
# checked with the new lighttpd (-tt). If that check fails the install is
# rolled back automatically, so the web UI stays reachable.
# Camera-side shell: busybox ash.

ROOT="${FWU_ROOT:-/mnt}"
WORK="${FWU_WORK:-$ROOT/update}"
STAGE="$WORK/stage"
BACKUPS="${FWU_BACKUPS:-$ROOT/backup}"
LOG="$WORK/update.log"
STATE="$WORK/state"
LAST_BACKUP="$WORK/last-backup"
LOCK="${FWU_LOCK:-/tmp/fw-update.lock}"
MIGRATE="${FWU_MIGRATE:-$ROOT/scripts/config-migrate.sh}"
LIGHTTPD="${FWU_LIGHTTPD:-$ROOT/bin/lighttpd}"
TRACKER="${FWU_TRACKER:-$ROOT/scripts/reboot-tracker.sh}"

_fwu_log() { mkdir -p "$WORK" 2>/dev/null; echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$LOG"; }
_fwu_state() { mkdir -p "$WORK" 2>/dev/null; echo "$1" > "$STATE"; }
_fwu_json_str() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
_fwu_first() { _ff=""; [ -r "$1" ] && read -r _ff _ffr < "$1"; printf '%s' "$_ff"; }

# _fwu_md5 FILE -> md5 hex of FILE ("" if unreadable)
_fwu_md5() { _fm="$(md5sum "$1" 2>/dev/null)"; printf '%s' "${_fm%% *}"; }

# Writes on the camera's SD card can come out with a zeroed run of pages
# under memory pressure (seen on hardware 2026-10-13: 8.7 KB of zeros at
# offset 128 KiB in a 428 KB file extracted from a 16 MB package with ~2 MB
# of RAM free; not reproducible on retry). Every write below is therefore
# checked against the MANIFEST md5 and retried.

_fwu_lock()
{
  if ! mkdir "$LOCK" 2>/dev/null; then
    echo "another update operation is running" >&2
    return 1
  fi
  trap 'rmdir "$LOCK" 2>/dev/null' EXIT
}

# _fwu_skip PATH -> 0 if the package must not touch PATH on this camera.
_fwu_skip()
{
  case "$1" in
    config/autostart/0?_system-*) return 1 ;;
    config/autostart/*) return 0 ;;                       # boot choice
    wpa_supplicant.conf.dist) [ -e "$ROOT/$1" ] && return 0 ;;   # credentials
  esac
  return 1
}

# _fwu_dir PATH -> directory part of a relative PATH ("." at top level).
_fwu_dir() { case "$1" in */*) printf '%s' "${1%/*}" ;; *) printf '.' ;; esac; }

fwu_verify()
{
  _pkg="$1"
  [ -r "$_pkg" ] || { echo '{"ok":false,"error":"package_missing"}'; return 1; }
  rm -rf "$STAGE"; mkdir -p "$STAGE"
  _list="$WORK/package.list"
  if ! tar -tf "$_pkg" > "$_list" 2>/dev/null; then
    echo '{"ok":false,"error":"not_a_tar"}'; return 1
  fi
  # No absolute paths, no "..": everything must land under the staging area.
  if grep -qE '^/|(^|/)\.\.(/|$)' "$_list"; then
    echo '{"ok":false,"error":"unsafe_path"}'; return 1
  fi
  grep -qx 'MANIFEST' "$_list" || grep -qx './MANIFEST' "$_list" || {
    echo '{"ok":false,"error":"no_manifest"}'; return 1; }
  if ! tar -xf "$_pkg" -C "$STAGE" 2>/dev/null; then
    rm -rf "$STAGE"; echo '{"ok":false,"error":"extract_failed"}'; return 1
  fi
  [ -r "$STAGE/VERSION" ] || { echo '{"ok":false,"error":"no_version"}'; return 1; }
  _bad=0; _total=0; _changed=0; _syntax=""
  while read -r _sum _path; do
    [ -n "$_path" ] || continue
    _total=$((_total + 1))
    case "$_path" in /*|*..*) _bad=$((_bad + 1)); continue ;; esac
    _try=0
    while [ "$(_fwu_md5 "$STAGE/$_path")" != "$_sum" ] && [ $_try -lt 2 ]; do
      _try=$((_try + 1))
      _fwu_log "verify: $_path damaged after extraction, extracting it again ($_try)"
      rm -f "$STAGE/$_path"
      (cd "$STAGE" && tar -xf "$_pkg" "$_path") 2>/dev/null
    done
    if [ "$(_fwu_md5 "$STAGE/$_path")" != "$_sum" ]; then _bad=$((_bad + 1)); continue; fi
    case "$_path" in
      *.sh|*.cgi|autorun.sh|controlscripts/*|scripts/*|config/autostart/*)
        case "$_path" in *.py|*.md) ;; *) sh -n "$STAGE/$_path" 2>/dev/null || _syntax="$_syntax $_path" ;; esac ;;
    esac
    _fwu_skip "$_path" && continue
    _cur="$(md5sum "$ROOT/$_path" 2>/dev/null)"; _cur="${_cur%% *}"
    [ "$_cur" = "$_sum" ] || _changed=$((_changed + 1))
  done < "$STAGE/MANIFEST"
  _ver="$(_fwu_first "$STAGE/VERSION")"
  if [ "$_bad" -gt 0 ] || [ -n "$_syntax" ] || [ "$_total" = 0 ]; then
    _fwu_state failed
    _fwu_log "verify failed: version=$_ver bad_md5=$_bad syntax=$_syntax"
    printf '{"ok":false,"error":"verify_failed","version":"%s","bad_md5":%d,"syntax_errors":"%s"}\n' \
      "$(_fwu_json_str "$_ver")" "$_bad" "$(_fwu_json_str "${_syntax# }")"
    return 1
  fi
  echo "$_ver" > "$WORK/staged-version"
  _fwu_state staged
  _fwu_log "verified $_ver: $_total files, $_changed to install"
  printf '{"ok":true,"version":"%s","current":"%s","files":%d,"changed":%d}\n' \
    "$(_fwu_json_str "$_ver")" "$(_fwu_json_str "$(_fwu_first "$ROOT/VERSION")")" "$_total" "$_changed"
}

_fwu_restore()   # _fwu_restore BACKUP_DIR
{
  _rb="$1"
  [ -r "$_rb/changes" ] || return 1
  while read -r _act _path; do
    case "$_act" in
      replaced) cp -f "$_rb/files/$_path" "$ROOT/$_path.fwu" 2>/dev/null &&
                  mv -f "$ROOT/$_path.fwu" "$ROOT/$_path" ;;
      added) rm -f "$ROOT/$_path" ;;
    esac
  done < "$_rb/changes"
  sync
}

fwu_install()
{
  _reboot=1; [ "$1" = "--no-reboot" ] && _reboot=0
  [ "$(_fwu_first "$STATE")" = staged ] && [ -r "$STAGE/MANIFEST" ] || {
    echo "nothing staged (upload and verify a package first)" >&2; return 1; }
  _fwu_lock || return 1
  _from="$(_fwu_first "$ROOT/VERSION")"; _to="$(_fwu_first "$WORK/staged-version")"
  _b="$BACKUPS/update-$(date +%Y%m%d-%H%M%S 2>/dev/null || echo now)"
  mkdir -p "$_b/files"; : > "$_b/changes"
  _fwu_state installing
  _fwu_log "install $_from -> $_to (backup $_b)"
  _n=0; _fail=0
  while read -r _sum _path; do
    [ -n "$_path" ] || continue
    _dst="$ROOT/$_path"
    _fwu_skip "$_path" && continue
    _cur="$(md5sum "$_dst" 2>/dev/null)"; _cur="${_cur%% *}"
    [ "$_cur" = "$_sum" ] && continue
    mkdir -p "$ROOT/$(_fwu_dir "$_path")" 2>/dev/null
    if [ -e "$_dst" ]; then
      mkdir -p "$_b/files/$(_fwu_dir "$_path")" 2>/dev/null
      cp -f "$_dst" "$_b/files/$_path" || { _fail=1; break; }
      echo "replaced $_path" >> "$_b/changes"
    else
      echo "added $_path" >> "$_b/changes"
    fi
    _try=0; _ok=0
    while [ $_try -lt 3 ]; do
      _try=$((_try + 1))
      cp -f "$STAGE/$_path" "$_dst.fwu" 2>/dev/null || continue
      if [ "$(_fwu_md5 "$_dst.fwu")" = "$_sum" ]; then _ok=1; break; fi
      _fwu_log "install: $_path damaged on write, retrying ($_try)"
      rm -f "$_dst.fwu"
    done
    if [ "$_ok" = 1 ] && mv -f "$_dst.fwu" "$_dst"; then
      _n=$((_n + 1))
    else
      rm -f "$_dst.fwu"; _fwu_log "FAILED $_path"; _fail=1; break
    fi
  done < "$STAGE/MANIFEST"
  sync
  echo "$_b" > "$LAST_BACKUP"
  echo "$_from" > "$_b/from-version"
  if [ "$_fail" = 0 ]; then
    [ -r "$MIGRATE" ] && sh "$MIGRATE" --force >/dev/null 2>&1
    _cfg="$ROOT/config/lighttpd.conf"
    if [ -f "$LIGHTTPD" ] && [ -r "$_cfg" ] &&
       ! LD_LIBRARY_PATH="$ROOT/lib:/lib:/usr/lib" "$LIGHTTPD" -tt -f "$_cfg" >/dev/null 2>&1; then
      _fwu_log "lighttpd rejects the config after the update"; _fail=1
    fi
  fi
  if [ "$_fail" != 0 ]; then
    _fwu_log "install failed, rolling back $_n file(s)"
    _fwu_restore "$_b"
    _fwu_state failed
    echo "install failed, rolled back" >&2
    return 1
  fi
  rm -rf "$STAGE" "$WORK/package.tar" "$WORK/staged-version"
  _fwu_state installed
  _fwu_log "installed $_to: $_n file(s)"
  echo "installed $_to: $_n file(s), backup $_b"
  if [ "$_reboot" = 1 ]; then
    sh "$TRACKER" intent "firmware update $_from -> $_to" >/dev/null 2>&1
    sync; sleep 1; /sbin/reboot
  fi
}

fwu_rollback()
{
  _reboot=1; [ "$1" = "--no-reboot" ] && _reboot=0
  _b="$(_fwu_first "$LAST_BACKUP")"
  [ -n "$_b" ] && [ -r "$_b/changes" ] || { echo "no backup to roll back to" >&2; return 1; }
  _fwu_lock || return 1
  _now="$(_fwu_first "$ROOT/VERSION")"
  _fwu_log "rollback from $_now using $_b"
  _fwu_restore "$_b"
  rm -f "$LAST_BACKUP"
  _fwu_state rolledback
  echo "rolled back to $(_fwu_first "$ROOT/VERSION")"
  if [ "$_reboot" = 1 ]; then
    sh "$TRACKER" intent "firmware rollback $_now -> $(_fwu_first "$ROOT/VERSION")" >/dev/null 2>&1
    sync; sleep 1; /sbin/reboot
  fi
}

fwu_status()
{
  _st="$(_fwu_first "$STATE")"; [ -n "$_st" ] || _st=idle
  _b="$(_fwu_first "$LAST_BACKUP")"; _bv=""
  [ -n "$_b" ] && _bv="$(_fwu_first "$_b/from-version")"
  _tail="$(tail -n 5 "$LOG" 2>/dev/null | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk '{printf "%s\\n", $0}')"
  printf '{"ok":true,"state":"%s","current":"%s","staged":"%s","rollback_to":"%s","log":"%s"}\n' \
    "$_st" "$(_fwu_json_str "$(_fwu_first "$ROOT/VERSION")")" \
    "$(_fwu_json_str "$(_fwu_first "$WORK/staged-version")")" "$(_fwu_json_str "$_bv")" "$_tail"
}

case "${0##*/}" in
  fw-update.sh)
    mkdir -p "$WORK" 2>/dev/null
    case "$1" in
      verify) fwu_verify "$2" ;;
      install) fwu_install "$2" ;;
      rollback) fwu_rollback "$2" ;;
      discard) rm -rf "$STAGE" "$WORK/package.tar" "$WORK/staged-version"; _fwu_state idle; echo '{"ok":true}' ;;
      status) fwu_status ;;
      *) echo "usage: $0 verify <tar> | install [--no-reboot] | rollback [--no-reboot] | discard | status" >&2; exit 2 ;;
    esac ;;
esac
