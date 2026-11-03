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
if [ "${motion_best_shot:-0}" = "1" ] || [ "${motion_best_shot:-0}" = "true" ]; then
    # Best-shot mode: take up to 3 quick shots and pick the one with highest byte size (detail / sharpness)
    _best_snap="$snap"
    _best_size=0
    for _i in 1 2 3; do
        _candidate="/tmp/.motion_snap_cand_${_i}_$$.jpg"
        if take_snapshot "$_candidate"; then
            _cand_size=$(wc -c < "$_candidate" 2>/dev/null)
            case "$_cand_size" in ''|*[!0-9]*) _cand_size=0 ;; esac
            if [ "$_cand_size" -gt "$_best_size" ]; then
                _best_size="$_cand_size"
                cp "$_candidate" "$_best_snap" 2>/dev/null || true
            fi
            rm -f "$_candidate" 2>/dev/null || true
        fi
        sleep 0.2 2>/dev/null || true
    done
    if [ -s "$_best_snap" ]; then
        snapshot_path="$_best_snap"
        ls -1t /tmp/motion_snap_*.jpg 2>/dev/null | tail -n +6 | while read -r old; do rm -f "$old"; done
    else
        rm -f "$_best_snap"
    fi
elif take_snapshot "$snap"; then
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
