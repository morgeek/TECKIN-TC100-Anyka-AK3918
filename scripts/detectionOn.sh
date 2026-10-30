#!/bin/sh

# Source your custom motion configurations
. /mnt/scripts/common_functions.sh

CONFIGPATH=/mnt/config/motion.conf
install_config $CONFIGPATH

. $CONFIGPATH

snapshot_path=""

# Led (the web UI writes 1/0; older files hold true/false)
case "$motion_trigger_led" in
  1|true|yes|on) red_led_blink 4 & ;;
esac

# A picture of the event: the hardware JPEG tc100_rtsp keeps (take_snapshot), a few kept in RAM for the events list
snap="/tmp/motion_snap_$(date +%s).jpg"
if take_snapshot "$snap"; then
    snapshot_path="$snap"
    # keep the newest 5
    ls -1t /tmp/motion_snap_*.jpg 2>/dev/null | tail -n +6 | while read -r old; do rm -f "$old"; done
else
    rm -f "$snap"
fi

# Send a telegram message
case "$send_telegram" in
  1|true|yes|on)
    if [ -n "$snapshot_path" ]; then
        /mnt/bin/telegram p "$snapshot_path"
    else
        tg_tmp="/tmp/telegram_image.$$.jpg"
        take_snapshot "$tg_tmp" && /mnt/bin/telegram p "$tg_tmp"
        rm -f "$tg_tmp"
    fi ;;
esac

# Persist motion event for local API + optional MQTT publish.
/mnt/scripts/motion-event.sh motion_on "$snapshot_path" "" "trigger=motion" >/dev/null 2>&1 &

# Run any user scripts.
for i in /mnt/config/userscripts/motiondetection/*; do
    if [ -x "$i" ]; then
        echo "Running: $i on $snapshot_path"
        $i on "$snapshot_path" &
    fi
done
