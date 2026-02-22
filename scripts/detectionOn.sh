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

# Save a snapshot
if [ "$save_snapshot" = true ] ; then
	pattern="${save_file_date_pattern:-+%d-%m-%Y_%H.%M.%S}"
	filename=$(date $pattern).jpg
	if [ ! -d "$save_dir" ]; then
		mkdir -p "$save_dir"
	fi
	{
		# Limit the number of snapshots
		if [ "$(ls "$save_dir" | wc -l)" -ge "$max_snapshots" ]; then
			rm -f "$save_dir/$(ls -ltr "$save_dir" | awk 'NR==2{print $9}')"
		fi
	} &
	snapshot_path="$save_dir/$filename"
	/mnt/bin/getimage > "$snapshot_path" &
fi

# Send emails ...
if [ "$sendemail" = true ] ; then
    /mnt/scripts/sendPictureMail.sh&
fi

# Send a telegram message
if [ "$send_telegram" = true ]; then
	if [ "$save_snapshot" = true ] ; then
		/mnt/bin/telegram p "$snapshot_path"
	else
		/mnt/bin/getimage > "/tmp/telegram_image.jpg"
 		/mnt/bin/telegram p "/tmp/telegram_image.jpg"
 		rm "/tmp/telegram_image.jpg"
	fi
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
