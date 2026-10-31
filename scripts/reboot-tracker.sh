#!/bin/sh
# reboot-tracker.sh — record why the camera restarted.
#
#   intent "<who>: <why>"  called right before a deliberate reboot
#   tick                   called every 5 min by cron: copies new critical
#                          syslog lines to important.log; every 15 min also
#                          runs heartbeat
#   heartbeat              last time seen alive (rewritten in place)
#   boot                   called early by autorun.sh: classifies the previous
#                          shutdown and appends one line to the history
#
# A boot with no recorded intent means the previous run ended without anyone
# asking for it: hardware watchdog, power loss or kernel crash. The last
# heartbeat then dates it to within 5 minutes (flash) or 15 (SD card), and
# says whether the SD card was failing at that time.
# Files live on the SD card, or in jffs2 when the firmware runs from flash
# (survive reboots). SD writes are kept rare: the
# heartbeat is overwritten in place (same 64 bytes, no new cluster or directory
# entry, unlike a temp file + rename), 4 times an hour; important.log is only
# appended to when a critical line actually appeared.
# Camera-side shell: busybox ash.

LOGDIR="${REBOOT_TRACKER_DIR:-/mnt/log}"
# Firmware run from flash: /mnt/log is a RAM disk; keep these few files in the
# jffs2 flash partition instead (small, and written as rarely as on the card).
if [ -z "${REBOOT_TRACKER_DIR:-}" ] && [ "$(cat "${TC100_STORAGE_FILE:-/tmp/tc100-storage}" 2>/dev/null)" = flash ]; then
  LOGDIR=/etc/jffs2/tc100/log
fi
INTENT="$LOGDIR/.reboot-intent"
HEARTBEAT="$LOGDIR/.heartbeat"
HISTORY="$LOGDIR/reboot-history.log"
LAST="${REBOOT_TRACKER_LAST:-/tmp/last-reboot-reason}"
KEEP=50
IMPORTANT="$LOGDIR/important.log"
IMPORTANT_MAX_BYTES=65536
case "$LOGDIR" in /etc/jffs2/*) IMPORTANT_MAX_BYTES=16384 ;; esac
IMPORTANT_KEEP=400
IMPORTANT_MARK="${REBOOT_TRACKER_MARK:-/tmp/log/important.last}"
SYSLOG_FILES="${REBOOT_TRACKER_SYSLOG:-/var/log/messages.0 /var/log/messages}"
# What deserves to survive a reboot: storage, memory and kernel failures, and
# our own tc100_log_event lines. Everything else stays in the RAM syslog.
# IMPORTANT_IGNORE: harmless warnings printed at every boot.
IMPORTANT_IGNORE='does not support reading read-only switch'
IMPORTANT_PATTERN='FAT-fs|mmc[0-9]|mmcblk|get_card_status|I/O error|Out of memory|oom-killer|Killed process|page allocation failure|segfault|Unable to handle|Internal error|Oops|BUG:|Kernel panic|soft lockup|blocked for more than|tc100-event'

_rt_ts() { date '+%Y-%m-%d %H:%M:%S' 2>/dev/null; }

rt_intent()
{
  rt_flush_important
  mkdir -p "$LOGDIR" 2>/dev/null
  printf '%s|%s\n' "$(_rt_ts)" "${1:-unspecified}" > "$INTENT" 2>/dev/null
  sync
  # settings changed in the last minute are saved to the flash first (cfg-persist saves a change once it has been
  # stable for 30 s: a reboot sooner lost it, R10-01). Only in flash mode, only when something changed; waited for up
  # to 20 s and never interrupted (the two slots keep the previous settings if the power goes during a write).
  _cp="${CFG_PERSIST_SH:-/mnt/v3/linux66-sd/cfg-persist}"
  if [ -f "$_cp" ] && [ -f "${CFG_PERSIST_SIG:-/tmp/cfg-persist.sig}" ]; then
    CFG=/mnt/config sh "$_cp" flush >/dev/null 2>&1 &
    _cpp=$!; _cpi=0
    while kill -0 "$_cpp" 2>/dev/null && [ "$_cpi" -lt 40 ]; do sleep 0.5; _cpi=$((_cpi + 1)); done
  fi
  # the RAM logs go to the SD card before the restart (scripts/log-persist.sh; LOG_PERSIST=0 turns it off);
  # every deliberate reboot (web UI, MQTT, net-guard, the reset button) announces itself here. Bounded at 8 s.
  _lp="${LOG_PERSIST_SH:-/mnt/scripts/log-persist.sh}"
  if [ -f "$_lp" ]; then
    sh "$_lp" shutdown "${1:-reboot}" >/dev/null 2>&1 &
    _lpp=$!; _lpi=0
    while kill -0 "$_lpp" 2>/dev/null && [ "$_lpi" -lt 16 ]; do sleep 0.5; _lpi=$((_lpi + 1)); done
  fi
}

rt_heartbeat()
{
  _hb_up=""; read -r _hb_up _hb_rest < /proc/uptime 2>/dev/null
  _hb_load=""; read -r _hb_load _hb_rest < /proc/loadavg 2>/dev/null
  _hb_free="$(sed -n 's/^MemFree: *\([0-9]*\).*/\1/p' /proc/meminfo 2>/dev/null)"
  # SD card state (v3/linux66-sd/sdinfo-sd.sh): a failing card blocks the kernel in
  # its driver until the hardware watchdog resets the camera, so the boot line
  # can then name the likely cause (seen on a test camera, 2026-10-16).
  _hb_sd=""; _hb_err=0
  if [ -r "${SDH_OUT:-/tmp/sd-health}" ]; then
    while IFS='=' read -r _hb_k _hb_v; do
      case "$_hb_k" in state) _hb_sd="$_hb_v" ;; errors) _hb_err="$_hb_v" ;; esac
    done < "${SDH_OUT:-/tmp/sd-health}"
  fi
  case "$_hb_sd" in *[!a-z]*) _hb_sd="" ;; esac
  case "$_hb_err" in ''|*[!0-9]*) _hb_err=0 ;; esac
  mkdir -p "$LOGDIR" 2>/dev/null
  # Fixed 64-byte record written over the previous one (read -r trims the
  # padding back off).
  printf '%-63s\n' "$(_rt_ts)|${_hb_up%.*}|$_hb_load|$_hb_free|${_hb_sd}:$_hb_err" |
    dd of="$HEARTBEAT" bs=64 count=1 conv=notrunc 2>/dev/null
}

# Copy the critical lines logged since the last call to important.log. The
# last copied line is remembered in RAM; when it has rotated out of the RAM
# log (or after a boot) every matching line still there is new.
rt_flush_important()
{
  mkdir -p "${IMPORTANT_MARK%/*}" 2>/dev/null
  # shellcheck disable=SC2086
  _fi_new="$(cat $SYSLOG_FILES 2>/dev/null | grep -E "$IMPORTANT_PATTERN" |
    grep -E '\.(emerg|alert|crit|err|warn|warning) |tc100-event' | grep -vE "$IMPORTANT_IGNORE" |
    awk -v markfile="$IMPORTANT_MARK" '
      BEGIN { if ((getline last < markfile) <= 0) last = "\001" }
      { a[++n] = $0; if ($0 == last) m = n }
      END { for (i = m + 1; i <= n; i++) print a[i] }')"
  [ -n "$_fi_new" ] || return 0
  mkdir -p "$LOGDIR" 2>/dev/null
  printf '%s\n' "$_fi_new" >> "$IMPORTANT" 2>/dev/null || return 0
  printf '%s\n' "$_fi_new" | tail -n 1 > "$IMPORTANT_MARK" 2>/dev/null
  _fi_size="$(wc -c < "$IMPORTANT" 2>/dev/null)"
  if [ "${_fi_size:-0}" -gt "$IMPORTANT_MAX_BYTES" ] 2>/dev/null; then
    tail -n "$IMPORTANT_KEEP" "$IMPORTANT" > "$IMPORTANT.tmp" 2>/dev/null && mv -f "$IMPORTANT.tmp" "$IMPORTANT"
  fi
}

rt_tick()
{
  rt_flush_important
  # In flash (jffs2, log-structured) every tick: dates a sudden reset to
  # within 5 minutes. On an SD card, every 15 minutes (fewer writes).
  case "$LOGDIR" in
    /etc/jffs2/*) rt_heartbeat ;;
    *) case "$(date +%M 2>/dev/null)" in
         00|15|30|45) rt_heartbeat ;;
       esac ;;
  esac
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
    _bt_line="$_bt_line, load ${_bt_rest%%|*}"
    _bt_rest="${_bt_rest#*|}"
    _bt_line="$_bt_line, MemFree ${_bt_rest%%|*} kB"
    case "$_bt_rest" in
      *'|'*) _bt_sd="${_bt_rest#*|}"; _bt_n="${_bt_sd#*:}"
             case "${_bt_sd%%:*}" in
               errors|failing|readonly) _bt_line="$_bt_line; SD card ${_bt_sd%%:*} ($_bt_n kernel errors): likely cause" ;;
               *) case "$_bt_n" in ''|0|*[!0-9]*) ;; *) _bt_line="$_bt_line; $_bt_n SD card errors in the kernel log" ;; esac ;;
             esac ;;
    esac
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
      tick) rt_tick ;;
      flush) rt_flush_important ;;
      boot) rt_boot ;;
      *) echo "usage: $0 intent <reason> | tick | heartbeat | flush | boot" >&2; exit 2 ;;
    esac ;;
esac
