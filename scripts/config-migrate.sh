#!/bin/sh
# config-migrate.sh — bring existing configs up to date with their .dist
# templates without touching the user's settings.
#
# install_config only copies a .dist when the config is absent, so a camera
# set up with an older release never receives new settings or new web-server
# directives (measured on a 1.8.3 camera: lighttpd.conf had no mod_deflate,
# so the 677 KB stylesheet was sent uncompressed; boot.conf lacked 34 keys).
#
# What it does (append-only, idempotent):
#   * shell-style KEY=VALUE configs: keys present in the .dist but missing from
#     the config are appended with their default. A key the user commented out
#     (#KEY=) counts as present. Existing lines are never modified.
#   * lighttpd configs: blocks marked "# @migrate <name> <probe>" ... "# @end"
#     in the .dist are appended when <probe> is absent from the config (blocks
#     must only use modules already loaded by the stock config). The result is
#     checked with `lighttpd -tt` before it replaces the file. A config the
#     bundled lighttpd rejects because it names mod_setenv (not built in) is
#     repaired first.
#
# Runs at boot from autorun.sh. A stamp of the .dist checksums makes it a
# no-op (one md5sum) until a release ships different templates.
# Camera-side shell: busybox ash, no tr(1), no bashisms.

CONFIGPATH="${CONFIGPATH:-/mnt/config}"
MIGRATE_STAMP="${MIGRATE_STAMP:-$CONFIGPATH/.migrate-stamp}"
MIGRATE_LOG="${MIGRATE_LOG:-/tmp/log/config-migrate.log}"
LIGHTTPD_BIN="${LIGHTTPD_BIN:-/mnt/bin/lighttpd}"

# Shell-style configs (sourced by scripts). INI-style files with [sections]
# (rtspserver.conf) are not handled: appending would land in the last section.
# Left out on purpose: sendmail.conf / telegram.conf (their defaults are
# credential placeholders) and webcontrols.conf (an absent key means "show
# every switch"; the default list would hide some).
MIGRATE_KV_CONFIGS="boot.conf mqtt.conf netmon.conf motion.conf recording.conf onvif.conf onvif_events.conf sound_detection.conf timelapse.conf service_trim.conf ftp.conf telnetd.conf dns.conf network.conf isp_tune.conf"
MIGRATE_HTTPD_CONFIGS="lighttpd.conf lighttpd.http.conf"

# Keys whose .dist default differs from what the code does when the key is
# absent. A camera that never had the key keeps its current behaviour, so the
# appended value is the code default, not the .dist one.
# Format: file:KEY=value (one per line). tests/test_regressions.py checks that
# every divergence between a .dist and the code defaults is listed here.
MIGRATE_KEEP_BEHAVIOUR='boot.conf:MEM_WATCHDOG_ENABLE=0
boot.conf:MEM_WATCHDOG_SERVICES="web-server rtsp-h26x recording onvif"
boot.conf:MEM_GUARD_DROP_CACHES=1
mqtt.conf:MQTT_HOST=
mqtt.conf:MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS=180
service_trim.conf:SERVICE_TRIM_ALLOWLIST="00_system-config 02_system-webserver rtsp-h26x onvif memory-guard"'

_mg_log() { echo "[config-migrate] $*" >> "$MIGRATE_LOG" 2>/dev/null; }

# _mg_keep FILE KEY -> prints the override line and returns 0 if one exists.
_mg_keep()
{
  _mk_rest="$MIGRATE_KEEP_BEHAVIOUR"
  while [ -n "$_mk_rest" ]; do
    case "$_mk_rest" in
      *"
"*) _mk_line="${_mk_rest%%
*}"; _mk_rest="${_mk_rest#*
}" ;;
      *) _mk_line="$_mk_rest"; _mk_rest="" ;;
    esac
    case "$_mk_line" in "$1:$2="*) echo "${_mk_line#*:}"; return 0 ;; esac
  done
  return 1
}

# _mg_replace TMP DEST — atomic replace, keeping one pre-migration backup.
_mg_replace()
{
  [ -f "$2.pre-migrate" ] || cp "$2" "$2.pre-migrate" 2>/dev/null
  mv "$1" "$2" && sync
}

# migrate_kv NAME — append keys missing from CONFIGPATH/NAME.
migrate_kv()
{
  _kv_cfg="$CONFIGPATH/$1"
  _kv_dist="$_kv_cfg.dist"
  [ -f "$_kv_cfg" ] && [ -f "$_kv_dist" ] || return 0

  # Keys already present (also commented out) — one pass, no forks.
  _kv_have="|"
  while IFS= read -r _kv_l || [ -n "$_kv_l" ]; do
    _kv_l="${_kv_l#"${_kv_l%%[! ]*}"}"
    _kv_l="${_kv_l#\#}"
    _kv_l="${_kv_l#"${_kv_l%%[! ]*}"}"
    case "$_kv_l" in
      [A-Za-z_]*=*) _kv_k="${_kv_l%%=*}"
        case "$_kv_k" in *[!A-Za-z0-9_]*) ;; *) _kv_have="$_kv_have$_kv_k|" ;; esac ;;
    esac
  done < "$_kv_cfg"

  _kv_add=""
  _kv_names=""
  while IFS= read -r _kv_l || [ -n "$_kv_l" ]; do
    case "$_kv_l" in [A-Za-z_]*=*) ;; *) continue ;; esac
    _kv_k="${_kv_l%%=*}"
    case "$_kv_k" in *[!A-Za-z0-9_]*) continue ;; esac
    case "$_kv_have" in *"|$_kv_k|"*) continue ;; esac
    _kv_have="$_kv_have$_kv_k|"
    _kv_keep="$(_mg_keep "$1" "$_kv_k")" && _kv_l="$_kv_keep"
    _kv_add="$_kv_add$_kv_l
"
    _kv_names="$_kv_names $_kv_k"
  done < "$_kv_dist"
  [ -n "$_kv_add" ] || return 0

  _kv_tmp="$_kv_cfg.migrate.tmp"
  cp "$_kv_cfg" "$_kv_tmp" || return 1
  # Make sure the existing last line is terminated before appending.
  [ -n "$(tail -c 1 "$_kv_tmp" 2>/dev/null)" ] && echo >> "$_kv_tmp"
  {
    echo "# --- added by config-migrate: new settings, default values ---"
    printf '%s' "$_kv_add"
  } >> "$_kv_tmp"
  if ! sh -n "$_kv_tmp" 2>/dev/null; then
    rm -f "$_kv_tmp"
    _mg_log "$1: result does not parse, left unchanged"
    return 1
  fi
  _mg_replace "$_kv_tmp" "$_kv_cfg"
  _mg_log "$1: added$_kv_names"
}

# _mg_httpd_ok FILE — 0 if lighttpd accepts FILE (or cannot be run here).
_mg_httpd_ok()
{
  [ -x "$LIGHTTPD_BIN" ] || return 0
  mkdir -p /tmp/lighttpd-deflate 2>/dev/null
  LD_LIBRARY_PATH="/mnt/lib:/lib:/usr/lib" "$LIGHTTPD_BIN" -tt -f "$1" >/dev/null 2>&1
}

# _mg_strip_setenv IN OUT — drop mod_setenv and comment out setenv.* directives.
# The bundled lighttpd is built without mod_setenv; a config naming it (the
# .dist of 1.8.3-rc20 and earlier did) stops the web server from starting.
_mg_strip_setenv()
{
  : > "$2" || return 1
  _ss_in=0
  while IFS= read -r _ss_l || [ -n "$_ss_l" ]; do
    _ss_t="${_ss_l#"${_ss_l%%[! ]*}"}"
    case "$_ss_t" in '"mod_setenv",'*) continue ;; esac
    if [ "$_ss_in" = 1 ]; then
      echo "#$_ss_l" >> "$2"
      case "$_ss_t" in ')'*) _ss_in=0 ;; esac
      continue
    fi
    case "$_ss_t" in
      setenv.*)
        echo "#$_ss_l" >> "$2"
        case "$_ss_t" in *'('*')'*) ;; *'('*) _ss_in=1 ;; esac
        continue ;;
    esac
    echo "$_ss_l" >> "$2"
  done < "$1"
}

# migrate_httpd NAME — repair a config the bundled lighttpd rejects, then
# append missing @migrate blocks from the .dist.
migrate_httpd()
{
  _hd_cfg="$CONFIGPATH/$1"
  _hd_dist="$_hd_cfg.dist"
  [ -f "$_hd_cfg" ] && [ -f "$_hd_dist" ] || return 0
  _hd_cur="$(cat "$_hd_cfg")"

  case "$_hd_cur" in
    *'"mod_setenv"'*)
      if ! _mg_httpd_ok "$_hd_cfg"; then
        _hd_tmp="$_hd_cfg.migrate.tmp"
        _mg_strip_setenv "$_hd_cfg" "$_hd_tmp" || return 1
        if _mg_httpd_ok "$_hd_tmp"; then
          _mg_replace "$_hd_tmp" "$_hd_cfg"
          _mg_log "$1: removed mod_setenv (not built into lighttpd)"
          _hd_cur="$(cat "$_hd_cfg")"
        else
          rm -f "$_hd_tmp"
          _mg_log "$1: rejected by lighttpd, not repairable automatically"
          return 1
        fi
      fi ;;
  esac

  _hd_add=""
  _hd_names=""
  _hd_in=0
  while IFS= read -r _hd_l || [ -n "$_hd_l" ]; do
    case "$_hd_l" in
      "# @migrate "*)
        _hd_spec="${_hd_l#\# @migrate }"
        _hd_name="${_hd_spec%% *}"
        _hd_probe="${_hd_spec#* }"
        case "$_hd_cur" in
          *"$_hd_probe"*) _hd_in=0 ;;
          *) _hd_in=1; _hd_names="$_hd_names $_hd_name"; _hd_add="$_hd_add
$_hd_l
" ;;
        esac
        continue ;;
      "# @end")
        [ "$_hd_in" = 1 ] && _hd_add="$_hd_add$_hd_l
"
        _hd_in=0
        continue ;;
    esac
    [ "$_hd_in" = 1 ] && _hd_add="$_hd_add$_hd_l
"
  done < "$_hd_dist"
  [ -n "$_hd_add" ] || return 0

  _hd_tmp="$_hd_cfg.migrate.tmp"
  cp "$_hd_cfg" "$_hd_tmp" || return 1
  printf '%s' "$_hd_add" >> "$_hd_tmp"

  if ! _mg_httpd_ok "$_hd_tmp"; then
    rm -f "$_hd_tmp"
    _mg_log "$1: lighttpd rejected the migrated config, left unchanged"
    return 1
  fi
  _mg_replace "$_hd_tmp" "$_hd_cfg"
  _mg_log "$1: added$_hd_names"
}

config_migrate_main()
{
  mkdir -p "${MIGRATE_LOG%/*}" 2>/dev/null
  _cm_list=""
  for _cm_n in $MIGRATE_KV_CONFIGS $MIGRATE_HTTPD_CONFIGS; do
    [ -f "$CONFIGPATH/$_cm_n.dist" ] && _cm_list="$_cm_list $CONFIGPATH/$_cm_n.dist"
  done
  [ -n "$_cm_list" ] || return 0
  # shellcheck disable=SC2086
  _cm_sum="$(cat $_cm_list | md5sum)"
  _cm_sum="${_cm_sum%% *}"
  if [ "$1" != "--force" ] && [ -r "$MIGRATE_STAMP" ]; then
    read -r _cm_old < "$MIGRATE_STAMP"
    [ "$_cm_old" = "$_cm_sum" ] && return 0
  fi

  _cm_fail=0
  for _cm_n in $MIGRATE_KV_CONFIGS; do migrate_kv "$_cm_n" || _cm_fail=1; done
  for _cm_n in $MIGRATE_HTTPD_CONFIGS; do migrate_httpd "$_cm_n" || _cm_fail=1; done
  # Stamp only a clean run, so a failure is retried on the next boot.
  if [ "$_cm_fail" = 0 ]; then
    echo "$_cm_sum" > "$MIGRATE_STAMP"
    _mg_log "done"
  fi
  return 0
}

# Run when executed, not when sourced by the tests.
case "${0##*/}" in
  config-migrate.sh) config_migrate_main "$@" ;;
esac
