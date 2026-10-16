#!/bin/sh
# Sourced: sets and exports TZ from /mnt/config/timezone.conf (a POSIX TZ
# string such as "UTC0" or "CET-1CEST,M3.5.0,M10.5.0/3"). Only the first line
# that is not a comment counts: the whole file used to be taken, comments
# included, so a camera left on the template got a garbage TZ.
TIME_ZONE_CONFIG_FILE="${TIME_ZONE_CONFIG_FILE:-/mnt/config/timezone.conf}"

if [ ! -f "$TIME_ZONE_CONFIG_FILE" ] && [ -f "$TIME_ZONE_CONFIG_FILE.dist" ]; then
    cp "$TIME_ZONE_CONFIG_FILE.dist" "$TIME_ZONE_CONFIG_FILE"
fi

time_zone=""
if [ -r "$TIME_ZONE_CONFIG_FILE" ]; then
    while IFS= read -r _tz_l || [ -n "$_tz_l" ]; do
        case "$_tz_l" in ''|'#'*) continue ;; esac
        time_zone="$_tz_l"; break
    done < "$TIME_ZONE_CONFIG_FILE"
fi
time_zone="${time_zone%% *}"
case "$time_zone" in
    ''|*[!A-Za-z0-9,.:+/\<\>-]*) time_zone="UTC0" ;;
esac
export TZ="$time_zone"
