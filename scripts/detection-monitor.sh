#!/bin/sh
# Tuneable performance parameters: allow overrides via environment to reduce CPU usage
MONITOR_TIMEOUT_SECONDS="${MONITOR_TIMEOUT_SECONDS:-6}"
MONITOR_TIMEOUT_SECONDS_ON_DETECTION="${MONITOR_TIMEOUT_SECONDS_ON_DETECTION:-8}"

case "$MONITOR_TIMEOUT_SECONDS" in
    ''|*[!0-9]*) MONITOR_TIMEOUT_SECONDS=6 ;;
esac
case "$MONITOR_TIMEOUT_SECONDS_ON_DETECTION" in
    ''|*[!0-9]*) MONITOR_TIMEOUT_SECONDS_ON_DETECTION=8 ;;
esac
[ "$MONITOR_TIMEOUT_SECONDS" -lt 1 ] && MONITOR_TIMEOUT_SECONDS=1
[ "$MONITOR_TIMEOUT_SECONDS_ON_DETECTION" -lt 1 ] && MONITOR_TIMEOUT_SECONDS_ON_DETECTION=1

monitor_motion_detection()
{
    LAST_MOTION_FLAG=0
    NEW_MOTION_FLAG=0

    while :
    do
        sleep $MONITOR_TIMEOUT_SECONDS
        NEW_MOTION_FLAG="$(/mnt/bin/getflag /tmp/rec_control 2>/dev/null)"
        case "$NEW_MOTION_FLAG" in
            0|1) ;;
            *) NEW_MOTION_FLAG=$LAST_MOTION_FLAG ;;
        esac

        if [ $NEW_MOTION_FLAG -ne $LAST_MOTION_FLAG ]; then
            if [ $NEW_MOTION_FLAG -eq 1 ]; then
                /mnt/scripts/detectionOn.sh
                sleep $MONITOR_TIMEOUT_SECONDS_ON_DETECTION
            else
                /mnt/scripts/detectionOff.sh
            fi

            LAST_MOTION_FLAG=$NEW_MOTION_FLAG
        fi

    done
}

monitor_motion_detection
