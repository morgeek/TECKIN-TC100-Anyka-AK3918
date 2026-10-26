#!/bin/sh
# TC100 Intelligent Auto Day/Night Detection Daemon for Linux 6.6 LTS
PIDFILE="/var/run/auto-night-detection.pid"
echo "$$" > "$PIDFILE"

. /mnt/scripts/common_functions.sh

LOW_LIGHT_COUNT=0
BRIGHT_LIGHT_COUNT=0
# Thresholds on the mean picture luminance (0-255): night below luma_night, day again above luma_day
# (rtspserver.conf, Settings -> Day/night on 3.0; the gap stops the flapping at dusk).
THRESHOLD_NIGHT=40
THRESHOLD_DAY=100

echo "[auto-night] Daemon started" > /dev/console

# The daemon itself must stay in auto mode (daynight=2) while it switches: nightmode.sh -> night-mode normally
# means "manual override" and writes daynight=3, which silently froze the daemon in NIGHT mode all day.
export NIGHT_KEEP_AUTO=1

# daynight value and the thresholds of the config without any fork (the loop runs every 4 s)
read_daynight() {
  DN_MODE=2
  [ -r /mnt/config/rtspserver.conf ] || return 0
  while IFS='= ' read -r _k _v _; do
    case "$_k" in
      daynight) DN_MODE="$_v" ;;
      luma_night) case "$_v" in [0-9]|[0-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5]) THRESHOLD_NIGHT="$_v" ;; esac ;;
      luma_day) case "$_v" in [0-9]|[0-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5]) THRESHOLD_DAY="$_v" ;; esac ;;
      '[0]') break ;;
    esac
  done < /mnt/config/rtspserver.conf
}

while true; do
  sleep 4

  # Check if auto detection is enabled in config (manual day/night = 3 pauses the daemon)
  read_daynight
  [ "$DN_MODE" != "2" ] && continue

  # Read luminance directly from real-time streamer or cache
  LUMA=50
  if [ -f /tmp/cam_luma ]; then
    read -r LUMA < /tmp/cam_luma
  elif [ -f /tmp/currentpic.cache.jpg ]; then
    LUMA=$(hexdump -n 512 -v -e '1/1 "%d\n"' /tmp/currentpic.cache.jpg 2>/dev/null | awk '{s+=$1} END {if (NR>0) print int(s/NR); else print 50}')
  fi

  # IR-cut state straight from its state file (same as `ir_cut status`, no fork); 1 = ON = day
  CUR_CUT=ON
  [ -r /var/run/ircut ] && { read -r _ic < /var/run/ircut; [ "$_ic" = 0 ] && CUR_CUT=OFF; }

  if [ "$CUR_CUT" = "ON" ]; then
    # Currently DAY mode
    if [ "$LUMA" -lt "$THRESHOLD_NIGHT" ]; then
      LOW_LIGHT_COUNT=$((LOW_LIGHT_COUNT + 1))
      if [ "$LOW_LIGHT_COUNT" -ge 2 ]; then
        echo "[auto-night] Low light detected (luma=$LUMA): Switching to NIGHT mode" > /dev/console
        /mnt/scripts/nightmode.sh on
        LOW_LIGHT_COUNT=0
        BRIGHT_LIGHT_COUNT=0
      fi
    else
      LOW_LIGHT_COUNT=0
    fi
  else
    # Currently NIGHT mode
    if [ "$LUMA" -gt "$THRESHOLD_DAY" ]; then
      BRIGHT_LIGHT_COUNT=$((BRIGHT_LIGHT_COUNT + 1))
      if [ "$BRIGHT_LIGHT_COUNT" -ge 2 ]; then
        echo "[auto-night] Bright light detected (luma=$LUMA): Switching to DAY mode" > /dev/console
        /mnt/scripts/nightmode.sh off
        LOW_LIGHT_COUNT=0
        BRIGHT_LIGHT_COUNT=0
      fi
    else
      BRIGHT_LIGHT_COUNT=0
    fi
  fi
done
