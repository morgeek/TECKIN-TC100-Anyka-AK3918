#!/bin/sh
# wifi-aim.sh — aim the camera without a screen (item 32 of the implementer list).
#
# For WIFI_AIM_SECONDS (300) after boot (boot.conf WIFI_AIM=1, started by v3/autorun-linux66.sh), the blue front LED
# blinks once per period, the period following the Wi-Fi signal: about 4 blinks a second at -50 dBm or better, one
# every 2 s at -85 dBm or worse, steady off without a link. Turn the camera, the faster it blinks the better. The LED
# is left off at the end. The signal comes from scripts/wifi-signal.sh (the one reader of it).
#
#   wifi-aim.sh run          the loop above
#   wifi-aim.sh period DBM   the blink period for a level, in tenths of a second (tests)
SECONDS_MAX="${WIFI_AIM_SECONDS:-300}"
LED="${WA_LED:-/sys/class/leds/blue_led/brightness}"
[ -e "$LED" ] || LED=/sys/class/leds/blue/brightness

# -50 dBm or better -> 2 (0.2 s), -85 or worse -> 20 (2 s), linear in between; empty -> 0 (no link)
wa_period() {
  case "$1" in ''|*[!0-9-]*) echo 0; return ;; esac
  d=$1
  [ "$d" -ge -50 ] && { echo 2; return; }
  [ "$d" -le -85 ] && { echo 20; return; }
  echo $(( 2 + (-50 - d) * 18 / 35 ))
}

case "$1" in
  period) wa_period "$2"; exit 0 ;;
  run) ;;
  *) echo "usage: wifi-aim.sh run | period DBM" >&2; exit 2 ;;
esac

. "${WA_SIGNAL:-/mnt/scripts/wifi-signal.sh}" 2>/dev/null
logger -t tc100-event -p user.notice "wifi-aim: the front LED shows the Wi-Fi signal for ${SECONDS_MAX} s" 2>/dev/null
start=$(cut -d. -f1 /proc/uptime 2>/dev/null)
while :; do
  now=$(cut -d. -f1 /proc/uptime 2>/dev/null)
  [ $((now - start)) -ge "$SECONDS_MAX" ] && break
  WIFI_DBM=
  command -v wifi_signal_read >/dev/null 2>&1 && wifi_signal_read any
  p=$(wa_period "$WIFI_DBM")
  if [ "$p" = 0 ]; then
    echo 0 > "$LED" 2>/dev/null; sleep 1
  else
    echo 1 > "$LED" 2>/dev/null; usleep 100000 2>/dev/null || sleep 1
    echo 0 > "$LED" 2>/dev/null; usleep $((p * 100000 - 100000)) 2>/dev/null || sleep 1
  fi
done
echo 0 > "$LED" 2>/dev/null
exit 0
