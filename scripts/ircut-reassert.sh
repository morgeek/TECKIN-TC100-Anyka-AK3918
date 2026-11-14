#!/bin/sh
# ircut-reassert.sh: pulse the IR-cut coil again to the position the state file says (/var/run/ircut: 1 = day, 0 = night).
# The coil is latching: nothing holds it but its last pulse. On 2026-11-14 the .11's filter was found out of the day
# position while the state file said day (picture magenta, RGB 125/81/109 against 91/91/94 on the .24, the ISP's white
# balance jumping between illuminants); one day pulse put it right (93/99/103). Re-pulsing the same position is harmless
# (setconf: one pulse, both pins low after, a lock against a concurrent switch). Run by the housekeeper every
# IRCUT_REASSERT_MIN minutes (boot.conf, default 30, 0 = off; v3/autorun-linux66.sh).
s=1
[ -r "${IRCUT_STATE:-/var/run/ircut}" ] && read -r s < "${IRCUT_STATE:-/var/run/ircut}" 2>/dev/null
[ "$s" = 0 ] || s=1
exec sh "${SETCONF:-/mnt/bin/setconf}" -k e -v "$s"
