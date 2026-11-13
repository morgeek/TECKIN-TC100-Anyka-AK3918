#!/bin/sh
# boot-milestones.sh — records startup timings (audit 2026-11-06, H11).
# Usage: boot-milestones.sh <milestone_name> [details]
# Reads /proc/uptime to log exact elapsed seconds since kernel boot.
# Stored in /tmp/boot-milestones.txt and persisted in /mnt/config/log/boot-milestones.log.

FILE="/tmp/boot-milestones.txt"
PERSIST="/mnt/config/log/boot-milestones.log"

record() {
  _m="$1"
  [ -z "$_m" ] && return 0
  shift
  _details="$*"
  _up=0
  if [ -r /proc/uptime ]; then
    read -r _up _ < /proc/uptime 2>/dev/null
  fi
  if [ "$_m" = "autorun_start" ] && [ -d /tmp ]; then
    : > "$FILE"
  fi
  [ -d /tmp ] && printf '%-20s %8s s  %s\n' "$_m" "${_up}" "$_details" >> "$FILE"
  if [ -d /mnt/config/log ]; then
    printf '%-20s %8s s  %s\n' "$_m" "${_up}" "$_details" >> "$PERSIST"
    if [ "$_m" = "boot_complete" ] && [ -f "$PERSIST" ]; then
      tail -n 40 "$PERSIST" > "$PERSIST.tmp" 2>/dev/null && mv -f "$PERSIST.tmp" "$PERSIST" 2>/dev/null || rm -f "$PERSIST.tmp"
    fi
  fi
}

case "$1" in
  show)
    if [ -f "$FILE" ]; then
      cat "$FILE"
    elif [ -f "$PERSIST" ]; then
      cat "$PERSIST"
    else
      echo "No boot milestones recorded yet."
    fi
    ;;
  clear)
    rm -f "$FILE"
    ;;
  *)
    record "$@"
    ;;
esac
