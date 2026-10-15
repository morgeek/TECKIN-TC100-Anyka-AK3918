#!/bin/sh
# /usr/bin/wpa_supplicant of the flash /usr image: the vendor 0.8 client is
# replaced by wpa_supplicant 2.11 (/usr/tc100/bin) to make room. The vendor
# scripts (wifi_station.sh) call it with the vendor configuration, whose WPS
# keys 2.11 (built without WPS) refuses: the -c file is passed filtered.
NEW="${WPA_NEW:-/usr/tc100/bin/wpa_supplicant}"
TMPCONF="${WPA_TMPCONF:-/tmp/wpa_supplicant-vendor.conf}"
filter()
{
    grep -v -E '^[[:space:]]*(device_name|manufacturer|model_name|model_number|serial_number|device_type|os_version|config_methods|wps_[a-z_]*)=' \
        "$1" > "$TMPCONF"
}
next=0
for a; do
    shift
    if [ "$next" = 1 ]; then filter "$a"; set -- "$@" "$TMPCONF"; next=0; continue; fi
    case "$a" in
        -c) next=1; set -- "$@" -c ;;
        -c?*) filter "${a#-c}"; set -- "$@" "-c$TMPCONF" ;;
        *) set -- "$@" "$a" ;;
    esac
done
exec "$NEW" "$@"
