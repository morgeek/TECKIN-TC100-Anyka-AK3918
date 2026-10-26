#!/bin/sh
# motion-schedule.sh arm|disarm
# Called by crond to enable or disable motion detection on a schedule.
# Configured via MOTION_SCHEDULE_* in boot.conf.

. /mnt/scripts/common_functions.sh

case "$1" in
    arm)    motion_detection on  ;;
    disarm) motion_detection off ;;
    *)      echo "Usage: $0 arm|disarm" >&2; exit 1 ;;
esac
