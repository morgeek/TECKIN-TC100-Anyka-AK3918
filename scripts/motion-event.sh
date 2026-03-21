#!/bin/sh

EVENT_LOG="/tmp/log/motion-events.log"
LATEST_SNAPSHOT_FILE="/tmp/motion-last-snapshot.path"
MAX_EVENTS=400
LOCK_DIR="/tmp/motion_event.lock"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

json_escape()
{
  # Fast path: motion values (event types, paths) almost never contain special chars.
  case "$1" in
    *\\*|*'"'*) ;;
    *) printf '%s' "$1"; return ;;
  esac
  # Slow path: escape backslashes then double-quotes via parameter expansion (no forks).
  _je="$1"
  _je_out=""
  while [ -n "$_je" ]; do
    case "$_je" in
      *\\*)
        _je_out="${_je_out}${_je%%\\*}\\\\"
        _je="${_je#*\\}"
        ;;
      *'"'*)
        _je_out="${_je_out}${_je%%\"*}\\\""
        _je="${_je#*\"}"
        ;;
      *)
        _je_out="${_je_out}${_je}"
        _je=""
        ;;
    esac
  done
  printf '%s' "$_je_out"
}

sanitize_field()
{
  # Fast path: event types and file paths never contain |, CR, or LF.
  case "$1" in
    *'|'*|*'
'*)
      printf '%s' "$1" | tr '\r\n' '  ' | sed 's/|/%7C/g'
      ;;
    *)
      printf '%s' "$1"
      ;;
  esac
}

trim_event_log()
{
  if [ ! -f "$EVENT_LOG" ]; then
    return 0
  fi
  line_count="$(wc -l < "$EVENT_LOG" 2>/dev/null)"
  case "$line_count" in
    ''|*[!0-9]*) line_count=0 ;;
  esac
  if [ "$line_count" -le "$MAX_EVENTS" ]; then
    return 0
  fi
  tmp_log="/tmp/motion-events.$$.tmp"
  tail -n "$MAX_EVENTS" "$EVENT_LOG" > "$tmp_log" 2>/dev/null || true
  mv "$tmp_log" "$EVENT_LOG" 2>/dev/null || true
}

event_type="$(sanitize_field "$1")"
snapshot_path="$(sanitize_field "$2")"
clip_path="$(sanitize_field "$3")"
detail="$(sanitize_field "$4")"

if [ -z "$event_type" ]; then
  event_type="motion"
fi

if [ ! -d /tmp/log ]; then
  mkdir -p /tmp/log >/dev/null 2>&1 || true
fi

_btime=0
while read -r _key _val _; do
  [ "$_key" = "btime" ] && _btime="$_val" && break
done < /proc/stat
read -r _up _ < /proc/uptime
epoch=$((_btime + ${_up%.*}))
[ "$epoch" -gt 0 ] || epoch=0
# Convert epoch to ISO 8601 UTC using Hinnant's civil_from_days — no date fork
_sec=$(( epoch % 86400 )); _days=$(( epoch / 86400 ))
_H=$(( _sec / 3600 )); _M=$(( (_sec % 3600) / 60 )); _S=$(( _sec % 60 ))
_z=$(( _days + 719468 ))
_era=$(( _z / 146097 ))
_doe=$(( _z - _era * 146097 ))
_yoe=$(( (_doe - _doe / 1460 + _doe / 36524 - _doe / 146096) / 365 ))
_y=$(( _yoe + _era * 400 ))
_doy=$(( _doe - 365 * _yoe - _yoe / 4 + _yoe / 100 ))
_mp=$(( (5 * _doy + 2) / 153 ))
_day=$(( _doy - (153 * _mp + 2) / 5 + 1 ))
if [ "$_mp" -lt 10 ]; then _mon=$(( _mp + 3 )); else _mon=$(( _mp - 9 )); fi
[ "$_mon" -le 2 ] && _y=$(( _y + 1 ))
ts_utc="$(printf '%04d-%02d-%02dT%02d:%02d:%02dZ' "$_y" "$_mon" "$_day" "$_H" "$_M" "$_S")"
[ -n "$ts_utc" ] || ts_utc="1970-01-01T00:00:00Z"

printf '%s|%s|%s|%s|%s|%s\n' "$epoch" "$ts_utc" "$event_type" "$snapshot_path" "$clip_path" "$detail" >> "$EVENT_LOG"
trim_event_log

if [ -n "$snapshot_path" ] && [ -f "$snapshot_path" ]; then
  printf '%s\n' "$snapshot_path" > "$LATEST_SNAPSHOT_FILE"
fi

if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
  event_json="$(json_escape "$event_type")"
  snapshot_json="$(json_escape "$snapshot_path")"
  clip_json="$(json_escape "$clip_path")"
  detail_json="$(json_escape "$detail")"
  payload=$(printf '{"ts":%s,"time_utc":"%s","type":"%s","snapshot":"%s","clip":"%s","detail":"%s"}' "$epoch" "$ts_utc" "$event_json" "$snapshot_json" "$clip_json" "$detail_json")

  set -- event "$payload" 0
  case "$event_type" in
    motion_on)  set -- "$@" motion/state "ON" 1 ;;
    motion_off) set -- "$@" motion/state "OFF" 1 ;;
  esac
  if [ -n "$snapshot_path" ] && [ -f "$snapshot_path" ]; then
    set -- "$@" snapshot/last_path "$snapshot_path" 1
  fi
  /mnt/scripts/mqtt-bridge.sh publish "$@" >/dev/null 2>&1 || true
fi

if [ -x /mnt/scripts/onvif-notify.sh ]; then
  case "$event_type" in
    motion_on|motion_off)
      /mnt/scripts/onvif-notify.sh "$event_type" "$ts_utc" >/dev/null 2>&1 || true
      ;;
  esac
fi

# Telegram snapshot on motion_on — opt-in via TELEGRAM_MOTION_SNAPSHOT=1 in telegram.conf
if [ "$event_type" = "motion_on" ] && \
   [ -f /mnt/config/telegram.conf ] && \
   [ -x /mnt/bin/telegram ]; then
  TELEGRAM_MOTION_SNAPSHOT=0
  # shellcheck disable=SC1091
  . /mnt/config/telegram.conf 2>/dev/null || true
  if [ "${TELEGRAM_MOTION_SNAPSHOT:-0}" = "1" ] && [ -n "${apiToken:-}" ]; then
    if [ -n "$snapshot_path" ] && [ -f "$snapshot_path" ]; then
      /mnt/bin/telegram p "$snapshot_path" >/dev/null 2>&1 || true
    else
      # Take a fresh snapshot if no snapshot was passed with the event
      if [ -x /mnt/bin/getimage ]; then
        _tg_snap="/tmp/telegram_motion_snap_$$.jpg"
        /mnt/bin/getimage > "$_tg_snap" 2>/dev/null && \
          /mnt/bin/telegram p "$_tg_snap" >/dev/null 2>&1 || true
        rm -f "$_tg_snap" 2>/dev/null || true
      else
        /mnt/bin/telegram m "Motion detected at $ts_utc" >/dev/null 2>&1 || true
      fi
    fi
  fi
fi
