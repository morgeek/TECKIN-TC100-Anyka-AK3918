#!/bin/sh
# nightmode.sh — Switches night/day mode and publishes the state change.
# Usage: nightmode.sh {on|off|status}

. /mnt/scripts/common_functions.sh

NIGHTMODE_LOG="/tmp/log/nightmode.log"
NIGHTMODE_MAX_LOG_BYTES=32768

log_nightmode() {
  [ -d /tmp/log ] || mkdir -p /tmp/log >/dev/null 2>&1 || true
  # Rotate log if too large
  if [ -f "$NIGHTMODE_LOG" ]; then
    _sz="$(wc -c < "$NIGHTMODE_LOG" 2>/dev/null)"
    case "$_sz" in ''|*[!0-9]*) _sz=0 ;; esac
    if [ "$_sz" -gt "$NIGHTMODE_MAX_LOG_BYTES" ]; then
      tail -n 50 "$NIGHTMODE_LOG" > "${NIGHTMODE_LOG}.tmp" 2>/dev/null && \
        mv "${NIGHTMODE_LOG}.tmp" "$NIGHTMODE_LOG" 2>/dev/null || true
    fi
  fi
  # Get epoch without fork
  _nm_btime=0
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _nm_btime="$_v" && break
  done < /proc/stat
  read -r _nm_up _ < /proc/uptime
  _nm_ts=$((_nm_btime + ${_nm_up%.*}))
  printf '%s %s\n' "$_nm_ts" "$1" >> "$NIGHTMODE_LOG"
}

publish_nightmode_mqtt() {
  _state="$1"
  if [ ! -x /mnt/scripts/mqtt-bridge.sh ]; then
    return 0
  fi
  _nm_btime=0
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _nm_btime="$_v" && break
  done < /proc/stat
  read -r _nm_up _ < /proc/uptime
  _nm_ts=$((_nm_btime + ${_nm_up%.*}))
  _payload="$(printf '{"ts":%s,"type":"night_mode","state":"%s"}' "$_nm_ts" "$_state")"
  /mnt/scripts/mqtt-bridge.sh publish event "$_payload" 0 \
    night_mode/state "$_state" 1 >/dev/null 2>&1 || true
}

case "$1" in
  on)
    night_mode on
    log_nightmode "on"
    publish_nightmode_mqtt "on"
    ;;
  off)
    night_mode off
    log_nightmode "off"
    publish_nightmode_mqtt "off"
    ;;
  status)
    night_mode status
    ;;
  *)
    night_mode "$1"
    ;;
esac
