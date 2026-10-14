#!/bin/sh
# isp-tune.sh — shared helpers for live image tuning (ISP_TUNE).
# Sourced by www/cgi-bin/action.cgi, www/cgi-bin/state.cgi and
# scripts/mqtt-bridge.sh. The values are applied by the libtc100fix.so thread
# inside v4l2rtspserver (src/tc100fix/isp_tune.c), which polls the file.
# Camera-side shell: no tr(1), no bashisms.

ISP_TUNE_CONF="${ISP_TUNE_CONF:-/mnt/config/isp_tune.conf}"
ISP_TUNE_STATUS="${ISP_TUNE_STATUS:-/var/run/isp_tune.status}"
ISP_TUNE_BOOT="${ISP_TUNE_BOOT:-/mnt/config/boot.conf}"
ISP_TUNE_KEYS="BRIGHTNESS CONTRAST SATURATION SHARPNESS HUE POWER_HZ EXPOSURE_MAX_PCT"

# isp_tune_norm KEY VALUE -> prints the normalized value, returns 1 if invalid.
isp_tune_norm()
{
  _itn_v="$2"
  case "$1" in
    BRIGHTNESS|CONTRAST|SATURATION|SHARPNESS|HUE)
      [ -z "$_itn_v" ] && { echo 0; return 0; }
      case "$_itn_v" in -*) _itn_n="${_itn_v#-}" ;; *) _itn_n="$_itn_v" ;; esac
      case "$_itn_n" in ''|*[!0-9]*) return 1 ;; esac
      [ ${#_itn_n} -le 2 ] || return 1
      [ "$_itn_n" -le 50 ] || return 1
      [ "$_itn_n" = "0" ] && { echo 0; return 0; }
      case "$_itn_v" in -*) echo "-$((_itn_n + 0))" ;; *) echo "$((_itn_n + 0))" ;; esac
      ;;
    POWER_HZ)
      case "$_itn_v" in ''|50|60) echo "$_itn_v" ;; *) return 1 ;; esac
      ;;
    EXPOSURE_MAX_PCT)
      case "$_itn_v" in ''|0) echo ""; return 0 ;; *[!0-9]*) return 1 ;; esac
      [ ${#_itn_v} -le 3 ] || return 1
      [ "$_itn_v" -ge 10 ] && [ "$_itn_v" -le 100 ] || return 1
      echo "$((_itn_v + 0))"
      ;;
    *) return 1 ;;
  esac
}

# isp_tune_get KEY [FILE] -> value from the tuning file (empty if absent).
isp_tune_get()
{
  _itg_f="${2:-$ISP_TUNE_CONF}"
  [ -r "$_itg_f" ] || return 0
  while IFS= read -r _itg_l || [ -n "$_itg_l" ]; do
    case "$_itg_l" in "$1"=*) echo "${_itg_l#*=}"; return 0 ;; esac
  done < "$_itg_f"
}

# isp_tune_set KEY VALUE -> validate and write; returns 1 if invalid.
isp_tune_set()
{
  _its_v="$(isp_tune_norm "$1" "$2")" || return 1
  [ -f "$ISP_TUNE_CONF" ] || cp "${ISP_TUNE_CONF}.dist" "$ISP_TUNE_CONF" 2>/dev/null || : > "$ISP_TUNE_CONF"
  rewrite_config "$ISP_TUNE_CONF" "$1" "$_its_v"
}

isp_tune_enabled()
{
  case "$(isp_tune_get ISP_TUNE "$ISP_TUNE_BOOT")" in 1|true|yes|on|enabled) echo 1 ;; *) echo 0 ;; esac
}

# JSON number or null for a possibly-empty value.
_isp_num() { case "$1" in ''|*[!0-9-]*) printf 'null' ;; *) printf '%s' "$1" ;; esac; }

# isp_tune_json -> {"enabled":0|1,"conf":{...},"applied":{...}|null}
isp_tune_json()
{
  printf '{"enabled":%s,"conf":{' "$(isp_tune_enabled)"
  _itj_sep=""
  for _itj_k in $ISP_TUNE_KEYS; do
    printf '%s"%s":%s' "$_itj_sep" "$_itj_k" "$(_isp_num "$(isp_tune_get "$_itj_k")")"
    _itj_sep=","
  done
  printf '},"applied":'
  if [ -r "$ISP_TUNE_STATUS" ]; then
    printf '{'
    _itj_sep=""
    for _itj_k in $ISP_TUNE_KEYS EXPOSURE_NOW EXPOSURE_ORIG; do
      _itj_v="$(isp_tune_get "$_itj_k" "$ISP_TUNE_STATUS")"
      [ -n "$_itj_v" ] || continue
      printf '%s"%s":%s' "$_itj_sep" "$_itj_k" "$(_isp_num "$_itj_v")"
      _itj_sep=","
    done
    printf '}'
  else
    printf 'null'
  fi
  printf '}\n'
}
