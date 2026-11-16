#!/bin/sh
# update-locked.sh: exit 0 when a firmware write is really under way (the lock dir /tmp/update66.running made by
# www/cgi-bin/update.cgi), 1 when there is none or it is STALE. Used by the web reboot / shutdown, the scheduled-reboot
# cron line and the reset button so that a hung update (stuck SD I/O, flashcp) or a final reboot that returned cannot make
# them refuse for ever. update.cgi writes the pid of the apply run to <lock>/pid and the uptime in seconds to <lock>/ts:
# the lock counts only while that pid is alive and for at most UPDATE_LOCK_MAX_S (1800) seconds. A lock without pid or
# ts yet (the few ms between mkdir and the writes) counts as live. /tmp is the RAM disk of the initramfs: a lock never
# survives a restart.
L=${UPDATE_LOCK:-/tmp/update66.running}
[ -e "$L" ] || exit 1
p=; [ -r "$L/pid" ] && read -r p < "$L/pid"
case "$p" in ''|*[!0-9]*) ;; *) kill -0 "$p" 2>/dev/null || exit 1 ;; esac
t=; [ -r "$L/ts" ] && read -r t < "$L/ts"
case "$t" in ''|*[!0-9]*) exit 0 ;; esac
u=0; read -r u _r < "${UPDATE_LOCK_UPTIME:-/proc/uptime}" 2>/dev/null; u=${u%.*}
case "$u" in ''|*[!0-9]*) exit 0 ;; esac
[ $((u - t)) -le "${UPDATE_LOCK_MAX_S:-1800}" ] || exit 1
exit 0
