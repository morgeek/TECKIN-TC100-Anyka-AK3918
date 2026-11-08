#!/bin/sh
# log-cap.sh — safety net for the logs kept in RAM (item 28 of the implementer list).
#
# Every log the firmware writes caps itself (tc100_rtsp 128 KB, audit / MQTT / night mode / sound / motion 32-64 KB,
# wifi-quality 1440 lines, daynight 2 x 400 lines, syslog -s 200). This catches the ones that do not, or a new one:
# every 10 minutes (housekeeper job "log-cap", registered by v3/autorun-linux66.sh) each regular file of /tmp/log and
# /tmp/logs above LOG_CAP_KB (boot.conf, default 64) keeps its last LOG_CAP_LINES (200) lines. The file is rewritten in
# place (same inode): a program that holds it open with O_APPEND (">>", syslogd) keeps writing into it, where a
# "tail > tmp; mv" would leave it writing into a deleted file that still takes RAM. Rotated copies (*.0, *.1) and
# tc100_rtsp.log (it rotates itself, and does not open it in append mode) are left alone.
#
#   log-cap.sh [DIR...]   one pass (default: /tmp/log /tmp/logs)
CONF="${LC_CONF:-/mnt/config/boot.conf}"
kb=$(sed -n 's/^LOG_CAP_KB="\{0,1\}\([0-9]*\)"\{0,1\}$/\1/p' "$CONF" 2>/dev/null | tail -n 1)
case "$kb" in ''|*[!0-9]*) kb=64 ;; esac
[ "$kb" -ge 8 ] || kb=8
lines="${LOG_CAP_LINES:-200}"
max=$((kb * 1024))
[ $# -gt 0 ] || set -- /tmp/log /tmp/logs
for d in "$@"; do
  [ -d "$d" ] || continue
  for f in "$d"/*; do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    case "${f##*/}" in *.0|*.1|*.tmp|tc100_rtsp.log) continue ;; esac
    sz=$(wc -c < "$f" 2>/dev/null); sz=${sz##* }; sz=${sz%%[!0-9]*}
    case "$sz" in ''|*[!0-9]*) continue ;; esac
    [ "$sz" -gt "$max" ] || continue
    if tail -n "$lines" "$f" > "$f.tmp" 2>/dev/null; then
      cat "$f.tmp" > "$f" 2>/dev/null
      logger -t tc100-event -p user.notice "log-cap: ${f} was ${sz} bytes, last ${lines} lines kept" 2>/dev/null
    fi
    rm -f "$f.tmp"
  done
done
exit 0
