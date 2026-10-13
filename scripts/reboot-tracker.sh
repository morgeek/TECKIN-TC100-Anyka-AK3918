#!/bin/sh
# reboot-tracker.sh — record why the camera restarted.
#
#   intent "<who>: <why>"  called right before a deliberate reboot
#   heartbeat              called every minute by cron: last time seen alive
#   boot                   called early by autorun.sh: classifies the previous
#                          shutdown and appends one line to the history
#
# A boot with no recorded intent means the previous run ended without anyone
# asking for it: hardware watchdog, power loss or kernel crash. The last
# heartbeat then dates it to within a minute.
# Files live on the SD card (survive reboots); writes are tiny and at most one
# per minute. Camera-side shell: busybox ash.

LOGDIR="${REBOOT_TRACKER_DIR:-/mnt/log}"
INTENT="$LOGDIR/.reboot-intent"
HEARTBEAT="$LOGDIR/.heartbeat"
HISTORY="$LOGDIR/reboot-history.log"
LAST="${REBOOT_TRACKER_LAST:-/tmp/last-reboot-reason}"
KEEP=50

_rt_ts() { date '+%Y-%m-%d %H:%M:%S' 2>/dev/null; }

rt_intent()
{
  mkdir -p "$LOGDIR" 2>/dev/null
  printf '%s|%s\n' "$(_rt_ts)" "${1:-unspecified}" > "$INTENT" 2>/dev/null
  sync
}

rt_heartbeat()
{
  _hb_up=""; read -r _hb_up _hb_rest < /proc/uptime 2>/dev/null
  _hb_load=""; read -r _hb_load _hb_rest < /proc/loadavg 2>/dev/null
  _hb_free="$(sed -n 's/^MemFree: *\([0-9]*\).*/\1/p' /proc/meminfo 2>/dev/null)"
  mkdir -p "$LOGDIR" 2>/dev/null
  printf '%s|%s|%s|%s\n' "$(_rt_ts)" "${_hb_up%.*}" "$_hb_load" "$_hb_free" > "$HEARTBEAT.tmp" 2>/dev/null &&
    mv -f "$HEARTBEAT.tmp" "$HEARTBEAT" 2>/dev/null
}

rt_boot()
{
  mkdir -p "$LOGDIR" 2>/dev/null
  _bt_hb=""
  [ -r "$HEARTBEAT" ] && read -r _bt_hb < "$HEARTBEAT"
  if [ -r "$INTENT" ]; then
    read -r _bt_in < "$INTENT"
    _bt_line="requested at ${_bt_in%%|*}: ${_bt_in#*|}"
  elif [ -n "$_bt_hb" ]; then
    _bt_rest="${_bt_hb#*|}"
    _bt_line="UNEXPECTED (hardware watchdog, power loss or crash); last alive ${_bt_hb%%|*}, uptime ${_bt_rest%%|*}s"
    _bt_rest="${_bt_rest#*|}"
    _bt_line="$_bt_line, load ${_bt_rest%%|*}, MemFree ${_bt_rest#*|} kB"
  else
    _bt_line="unknown (no heartbeat recorded yet)"
  fi
  echo "$_bt_line" > "$LAST" 2>/dev/null
  # Clock may not be set yet (NTP runs later): the line is dated by its content.
  echo "boot after: $_bt_line" >> "$HISTORY" 2>/dev/null
  if [ "$(wc -l < "$HISTORY" 2>/dev/null)" -gt "$KEEP" ] 2>/dev/null; then
    tail -n "$KEEP" "$HISTORY" > "$HISTORY.tmp" 2>/dev/null && mv -f "$HISTORY.tmp" "$HISTORY"
  fi
  rm -f "$INTENT" "$HEARTBEAT" 2>/dev/null
  sync
}

case "${0##*/}" in
  reboot-tracker.sh)
    case "$1" in
      intent) shift; rt_intent "$*" ;;
      heartbeat) rt_heartbeat ;;
      boot) rt_boot ;;
      *) echo "usage: $0 intent <reason> | heartbeat | boot" >&2; exit 2 ;;
    esac ;;
esac
