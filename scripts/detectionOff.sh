#!/bin/sh

# Source your custom motion configurations
. /mnt/scripts/common_functions.sh

latest_clip="$(ls -1t /mnt/DCIM/*.mp4 /mnt/DCIM/*.h264 /mnt/DCIM/*.ts 2>/dev/null | head -n 1)"

# Persist motion stop event for local API + optional MQTT publish.
/mnt/scripts/motion-event.sh motion_off "" "$latest_clip" "trigger=motion_end" >/dev/null 2>&1 &

# Run any user scripts.
for i in /mnt/config/userscripts/motiondetection/*; do
    if [ -x $i ]; then
        echo "Running: $i off"
        $i off
    fi
done
