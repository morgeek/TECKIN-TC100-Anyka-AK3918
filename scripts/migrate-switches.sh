#!/bin/sh
# migrate-switches.sh — once per camera (config/.migrated-switches), when a camera moves to "one switch per service"
# (scripts/service-switch.sh). Keeps what the camera did at its last start, so that an update changes nothing visible:
#   - Telegram on motion had three paths (motion.conf send_telegram, telegram.conf TELEGRAM_MOTION_SNAPSHOT, notify.conf
#     TELEGRAM_NOTIFY_ENABLE): any of them on -> TELEGRAM_NOTIFY_ENABLE=1, the only one left (scripts/notify.sh).
#   - Tamper detection needed TAMPER_DETECT=1 in boot.conf AND ENABLE=1 in tamper.conf: tamper.conf alone now, set to
#     what both gave; the TAMPER_* lines leave boot.conf (TAMPER_HOLD_SEC/TAMPER_LUMA_MIN of tamper.conf won already).
#   - Recording: config/autostart/recording forced REC_LOCAL=1 at every start; REC_LOCAL alone now (kept on), file removed.
# MS_CONF_DIR changes /mnt/config (tests).
C=${MS_CONF_DIR:-/mnt/config}
[ -d "$C" ] || exit 0
[ -f "$C/.migrated-switches" ] && exit 0
SW_CONF_DIR=$C
. "${MS_SWITCH:-/mnt/scripts/service-switch.sh}"

# set KEY=VALUE in FILE (FILE created from its .dist, or empty, when missing)
ms_set() {
  [ -f "$1" ] || { [ -f "$1.dist" ] && cp "$1.dist" "$1"; } || : > "$1"
  if grep -q "^$2=" "$1"; then
    sed "s|^$2=.*|$2=$3|" "$1" > "$1.tmp.$$" && mv -f "$1.tmp.$$" "$1"
  else
    printf '%s=%s\n' "$2" "$3" >> "$1"
  fi
}
on() { case "$1" in 1|true|yes|on|enabled) return 0 ;; esac; return 1; }

# Telegram
if on "$(svc_kv "$C/motion.conf" send_telegram 0)" || on "$(svc_kv "$C/telegram.conf" TELEGRAM_MOTION_SNAPSHOT 0)"; then
  ms_set "$C/notify.conf" TELEGRAM_NOTIFY_ENABLE 1
fi
[ -f "$C/motion.conf" ] && sed -i '/^send_telegram=/d' "$C/motion.conf"
[ -f "$C/telegram.conf" ] && sed -i '/^TELEGRAM_MOTION_SNAPSHOT=/d' "$C/telegram.conf"

# Tamper
if grep -q '^TAMPER_' "$C/boot.conf" 2>/dev/null; then
  if on "$(svc_kv "$C/boot.conf" TAMPER_DETECT 0)" && on "$(svc_kv "$C/tamper.conf" ENABLE 0)"; then t=1; else t=0; fi
  ms_set "$C/tamper.conf" ENABLE "$t"
  sed -i '/^TAMPER_DETECT=/d; /^TAMPER_HOLD_SEC=/d; /^TAMPER_LUMA_MIN=/d' "$C/boot.conf"
fi

# Recording
if [ -e "$C/autostart/recording" ]; then
  svc_set recording 1
  rm -f "$C/autostart/recording"
fi

: > "$C/.migrated-switches"
exit 0
