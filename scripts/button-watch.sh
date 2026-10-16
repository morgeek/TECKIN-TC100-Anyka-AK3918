#!/bin/sh
# button-watch.sh — actions on the camera's reset button while it runs.
#
# The button is the kernel's "akgpio-keys" input device (/dev/input/event0).
# Each event is a 16-byte struct input_event (seconds, microseconds, type,
# code, value; little endian). This loop blocks in dd until the button moves:
# no process at all while nobody touches it.
#
#   held  3–7 s    open the rescue Wi-Fi access point (scripts/wifi-rescue.sh)
#   held  8–19 s   reboot
#   held 20 s +    firmware from flash: back to the code built into /usr
#                  (clears the code zone, scripts/flash-code.sh), then reboot —
#                  the way out of a bad code update without a computer;
#                  from the SD card: reboot
#
# (Holding the button while powering the camera on is U-Boot's SD recovery,
# unrelated to this script.)

DEV="${BUTTON_DEV:-/dev/input/event0}"
REBOOT_SECONDS="${BUTTON_REBOOT_SECONDS:-8}"
RESTORE_SECONDS="${BUTTON_RESTORE_SECONDS:-20}"
FC="${BUTTON_FLASH_CODE:-/usr/tc100/scripts/flash-code.sh}"
REBOOT="${BUTTON_REBOOT_CMD:-/sbin/reboot}"
RESCUE_SECONDS="${BUTTON_RESCUE_SECONDS:-3}"
RESCUE="${BUTTON_RESCUE:-/mnt/scripts/wifi-rescue.sh}"

_bw_log() { logger -t tc100-event -p user.err "button: $*" 2>/dev/null; }

# _bw_event -> sets ev_sec ev_type ev_value; 1 at end of input
_bw_event()
{
    set -- $(dd if="$DEV" bs=16 count=1 2>/dev/null | od -An -v -tu1)
    [ $# -eq 16 ] || return 1
    ev_sec=$(( $1 + $2 * 256 + $3 * 65536 + $4 * 16777216 ))
    ev_type=$(( $9 + ${10} * 256 ))
    ev_value=$(( ${13} + ${14} * 256 ))
}

[ -r "$DEV" ] || { echo "no $DEV" >&2; exit 1; }
pressed=""
while _bw_event; do
    [ "$ev_type" = 1 ] || continue          # EV_KEY only
    if [ "$ev_value" != 0 ]; then
        [ -n "$pressed" ] || pressed="$ev_sec"
        continue
    fi
    [ -n "$pressed" ] || continue
    held=$(( ev_sec - pressed )); pressed=""
    if [ "$held" -ge "$RESTORE_SECONDS" ]; then
        if [ "$(cat "${TC100_STORAGE_FILE:-/tmp/tc100-storage}" 2>/dev/null)" = flash ] && [ -x "$FC" ]; then
            _bw_log "held ${held}s: back to the built-in code, reboot"
            sh "$FC" clear >/dev/null 2>&1
        else
            _bw_log "held ${held}s: reboot"
        fi
        sh /mnt/scripts/reboot-tracker.sh intent "reset button held ${held}s" >/dev/null 2>&1
        sync; $REBOOT
    elif [ "$held" -ge "$REBOOT_SECONDS" ]; then
        _bw_log "held ${held}s: reboot"
        sh /mnt/scripts/reboot-tracker.sh intent "reset button held ${held}s" >/dev/null 2>&1
        sync; $REBOOT
    elif [ "$held" -ge "$RESCUE_SECONDS" ]; then
        _bw_log "held ${held}s: rescue access point"
        sh "$RESCUE" start-ap "reset button" </dev/null >/dev/null 2>&1 &
    fi
done
