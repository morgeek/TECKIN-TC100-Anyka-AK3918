#!/bin/sh
# isp-tune.sh — shared helpers for live image tuning (ISP_TUNE).
# Sourced by www/cgi-bin/action.cgi, www/cgi-bin/state.cgi and
# scripts/mqtt-bridge.sh. The values are applied by tc100_rtsp through the ISP
# (/dev/isp_char), which checks the file every 2 s; POWER_HZ (anti-flicker) and the masks apply whatever ISP_TUNE is.
# Camera-side shell: no tr(1), no bashisms.

ISP_TUNE_CONF="${ISP_TUNE_CONF:-/mnt/config/isp_tune.conf}"
ISP_TUNE_STATUS="${ISP_TUNE_STATUS:-/var/run/isp_tune.status}"
ISP_TUNE_BOOT="${ISP_TUNE_BOOT:-/mnt/config/boot.conf}"
ISP_TUNE_KEYS="BRIGHTNESS CONTRAST SATURATION SHARPNESS DENOISE HUE POWER_HZ EXPOSURE_MAX_PCT"
# Hardware privacy masks: MASK1..MASK4 = x1,y1,x2,y2 in percent, MASK_COLOR.
ISP_MASK_KEYS="MASK1 MASK2 MASK3 MASK4 MASK_COLOR"

# isp_tune_norm KEY VALUE [var] -> prints (or stores in _it_norm) the normalized value, returns 1 if invalid.
isp_tune_norm()
{
  _itn_v="$2"
  _itn_q="${3:-}"
  case "$1" in
    BRIGHTNESS|CONTRAST|SATURATION|SHARPNESS|DENOISE|HUE)
      if [ -z "$_itn_v" ]; then
        _it_norm=0
        [ "$_itn_q" = var ] || echo "$_it_norm"
        return 0
      fi
      case "$_itn_v" in -*) _itn_n="${_itn_v#-}" ;; *) _itn_n="$_itn_v" ;; esac
      case "$_itn_n" in ''|*[!0-9]*) return 1 ;; esac
      [ ${#_itn_n} -le 2 ] || return 1
      [ "$_itn_n" -le 50 ] || return 1
      if [ "$_itn_n" = "0" ]; then
        _it_norm=0
        [ "$_itn_q" = var ] || echo "$_it_norm"
        return 0
      fi
      case "$_itn_v" in -*) _it_norm="-$((_itn_n + 0))" ;; *) _it_norm="$((_itn_n + 0))" ;; esac
      ;;
    POWER_HZ)
      case "$_itn_v" in ''|50|60|auto) _it_norm="$_itn_v" ;; *) return 1 ;; esac
      ;;
    EXPOSURE_MAX_PCT)
      case "$_itn_v" in
        ''|0) _it_norm=""; [ "$_itn_q" = var ] || echo "$_it_norm"; return 0 ;;
        *[!0-9]*) return 1 ;;
      esac
      [ ${#_itn_v} -le 3 ] || return 1
      [ "$_itn_v" -ge 10 ] && [ "$_itn_v" -le 100 ] || return 1
      _it_norm="$((_itn_v + 0))"
      ;;
    MASK1|MASK2|MASK3|MASK4)
      if [ -z "$_itn_v" ]; then
        _it_norm=""
        [ "$_itn_q" = var ] || echo "$_it_norm"
        return 0
      fi
      case "$_itn_v" in *[!0-9,]*) return 1 ;; esac
      _itn_old_ifs="$IFS"; IFS=,
      # shellcheck disable=SC2086
      set -- $_itn_v
      IFS="$_itn_old_ifs"
      [ $# -eq 4 ] || return 1
      for _itn_n in "$@"; do
        [ -n "$_itn_n" ] && [ ${#_itn_n} -le 3 ] && [ "$_itn_n" -le 100 ] || return 1
      done
      [ "$(($3 + 0))" -gt "$(($1 + 0))" ] && [ "$(($4 + 0))" -gt "$(($2 + 0))" ] || return 1
      _it_norm="$(($1 + 0)),$(($2 + 0)),$(($3 + 0)),$(($4 + 0))"
      ;;
    MASK_COLOR)
      case "$_itn_v" in ''|black|gray|white) _it_norm="$_itn_v" ;; *) return 1 ;; esac
      ;;
    *) return 1 ;;
  esac
  [ "$_itn_q" = var ] || echo "$_it_norm"
}

# isp_tune_get KEY [FILE] [var] -> value from the tuning file (empty if absent).
isp_tune_get()
{
  _itg_f="${2:-$ISP_TUNE_CONF}"
  _itg_q="${3:-}"
  _it_val=""
  if [ -r "$_itg_f" ]; then
    while IFS= read -r _itg_l || [ -n "$_itg_l" ]; do
      case "$_itg_l" in "$1"=*) _it_val="${_itg_l#*=}"; break ;; esac
    done < "$_itg_f"
  fi
  [ "$_itg_q" = var ] || { [ -n "$_it_val" ] && echo "$_it_val" || true; }
}

# isp_tune_set KEY VALUE -> validate and write; returns 1 if invalid.
isp_tune_set()
{
  isp_tune_norm "$1" "$2" var || return 1
  _its_v="$_it_norm"
  [ -f "$ISP_TUNE_CONF" ] || cp "${ISP_TUNE_CONF}.dist" "$ISP_TUNE_CONF" 2>/dev/null || : > "$ISP_TUNE_CONF"
  rewrite_config "$ISP_TUNE_CONF" "$1" "$_its_v"
}

isp_tune_enabled()
{
  isp_tune_get ISP_TUNE "$ISP_TUNE_BOOT" var
  case "$_it_val" in 1|true|yes|on|enabled) _it_en=1 ;; *) _it_en=0 ;; esac
  [ "${1:-}" = var ] || echo "$_it_en"
}

# JSON number or null for a possibly-empty value.
_isp_num() { case "$1" in auto) _it_num='"auto"' ;; ''|*[!0-9-]*) _it_num='null' ;; *) _it_num="$1" ;; esac; [ "${2:-}" = var ] || printf '%s' "$_it_num"; }   # auto: POWER_HZ only

# isp_tune_json -> {"enabled":0|1,"conf":{...},"applied":{...}|null}
isp_tune_json()
{
  isp_tune_enabled var
  printf '{"enabled":%s,"conf":{' "$_it_en"
  _itj_sep=""
  for _itj_k in $ISP_TUNE_KEYS; do
    isp_tune_get "$_itj_k" "$ISP_TUNE_CONF" var
    _isp_num "$_it_val" var
    printf '%s"%s":%s' "$_itj_sep" "$_itj_k" "$_it_num"
    _itj_sep=","
  done
  for _itj_k in $ISP_MASK_KEYS; do
    isp_tune_get "$_itj_k" "$ISP_TUNE_CONF" var
    _it_norm=""
    isp_tune_norm "$_itj_k" "$_it_val" var 2>/dev/null || _it_norm=""
    printf ',"%s":"%s"' "$_itj_k" "$_it_norm"
  done
  printf '},"applied":'
  if [ -r "$ISP_TUNE_STATUS" ]; then
    printf '{'
    _itj_sep=""
    for _itj_k in $ISP_TUNE_KEYS EXPOSURE_NOW EXPOSURE_ORIG POWER_HZ_BASE MASKS MASK_RC; do
      isp_tune_get "$_itj_k" "$ISP_TUNE_STATUS" var
      [ -n "$_it_val" ] || continue
      _isp_num "$_it_val" var
      printf '%s"%s":%s' "$_itj_sep" "$_itj_k" "$_it_num"
      _itj_sep=","
    done
    printf '}'
  else
    printf 'null'
  fi
  printf '}\n'
}
