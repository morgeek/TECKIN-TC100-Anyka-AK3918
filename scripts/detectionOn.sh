#!/bin/sh

# Source your custom motion configurations
. /mnt/scripts/common_functions.sh

CONFIGPATH=/mnt/config/motion.conf
install_config $CONFIGPATH

. $CONFIGPATH

snapshot_path=""


# Led
if [ "$motion_trigger_led" = true ] ; then
    red_led_blink 4 &
fi

# Send a telegram message
if [ "$send_telegram" = true ]; then
	tg_tmp="/tmp/telegram_image.$$.jpg"
	/mnt/bin/getimage > "$tg_tmp"
	/mnt/bin/telegram p "$tg_tmp"
	rm -f "$tg_tmp"
fi

# Persist motion event for local API + optional MQTT publish.
/mnt/scripts/motion-event.sh motion_on "$snapshot_path" "" "trigger=motion" >/dev/null 2>&1 &

# Run any user scripts.
for i in /mnt/config/userscripts/motiondetection/*; do
    if [ -x "$i" ]; then
        echo "Running: $i on $snapshot_path"
        $i on "$snapshot_path" &
    fi
done
