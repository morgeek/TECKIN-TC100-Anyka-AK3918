#!/bin/sh
# wifi-country.sh — the Wi-Fi rules of a country (channels, transmit power), from WIFI_COUNTRY of boot.conf, its one
# source (ISO 3166 code such as FR, BE, CH, US; empty = the "world" rules, the most restrictive, as before 3.0.2).
#
#   wifi-country.sh get             the configured code, empty when none
#   wifi-country.sh status          configured=, effective= (what the kernel applies now), regdb=0|1
#   wifi-country.sh conf IN OUT     OUT = IN with country=<code> as its first line (any country= of IN dropped): the
#                                   copy wpa_supplicant runs on (/etc/wpa_supplicant.conf, v3/linux66-sd/wifi-apply)
#   wifi-country.sh boot            autorun-linux66.sh: the database read again if the kernel missed it, then the code
#   wifi-country.sh apply           after a change in Settings: the copy, wpa_supplicant and the kernel, without
#                                   reconnecting (the rescue access point takes it at its next start)
#
# The kernel reads its database (/lib/firmware/regulatory.db, wireless-regdb of the Buildroot base, in the initramfs)
# once at boot; without it every code falls back to the world rules. The boot script v3/S39tc100-linux66 reads
# WIFI_COUNTRY itself (the user space is not there yet) with the same pattern, so that wpa_supplicant starts with it.
# Test hooks: WC_CONF (boot.conf), WC_FW (the database file), WC_RUNCONF (the copy), WC_MARK, WC_IW, WC_WPA_CLI,
# WC_DMESG, WC_PIDOF.

CONF="${WC_CONF:-/mnt/config/boot.conf}"
FW="${WC_FW:-/lib/firmware/regulatory.db}"
RUNCONF="${WC_RUNCONF:-/etc/wpa_supplicant.conf}"
MARK="${WC_MARK:-/tmp/wifi-regdb.reloaded}"
PATH="$PATH:/mnt/ext/bin"	# iw and wpa_cli come with the user space
IW="${WC_IW:-iw}"
WPA_CLI="${WC_WPA_CLI:-wpa_cli}"
DMESG="${WC_DMESG:-dmesg}"
PIDOF="${WC_PIDOF:-pidof}"

wc_get() { sed -n 's/^WIFI_COUNTRY="\{0,1\}\([A-Z][A-Z]\)"\{0,1\}$/\1/p' "$CONF" 2>/dev/null | tail -n 1; }

# the country the kernel applies now ("00" = world), from the global section of `iw reg get`
wc_effective() { $IW reg get 2>/dev/null | sed -n 's/^country \([0-9A-Z][0-9A-Z]\):.*/\1/p' | head -n 1; }

wc_conf()
{
    _wc_c="$(wc_get)"
    { [ -n "$_wc_c" ] && echo "country=$_wc_c"; grep -v '^[[:space:]]*country=' "$1"; } > "$2"
}

# The kernel tries the database once, early at boot; when that failed ("failed to load regulatory.db") and the file
# is there now, read it again (once per boot).
wc_regdb()
{
    [ -f "$FW" ] || return 1
    [ -f "$MARK" ] && return 0
    $DMESG 2>/dev/null | grep -q 'failed to load regulatory.db' || return 0
    $IW reg reload 2>/dev/null && : > "$MARK"
}

case "$1" in
    get) wc_get ;;
    status)
        _r=0; [ -f "$FW" ] && _r=1
        printf 'configured=%s\neffective=%s\nregdb=%s\n' "$(wc_get)" "$(wc_effective)" "$_r" ;;
    conf)
        [ -f "$2" ] && [ -n "$3" ] || { echo "usage: $0 conf IN OUT" >&2; exit 2; }
        wc_conf "$2" "$3" ;;
    boot)
        wc_regdb
        _c="$(wc_get)"
        [ -n "$_c" ] || exit 0
        [ "$(wc_effective)" = "$_c" ] || $IW reg set "$_c" 2>/dev/null ;;
    apply)
        wc_regdb
        _c="$(wc_get)"
        if [ -f "$RUNCONF" ]; then
            ( umask 077; wc_conf "$RUNCONF" "$RUNCONF.new" ) && mv -f "$RUNCONF.new" "$RUNCONF"
        fi
        # wpa_supplicant keeps it for its next connections; the kernel takes it now ("00": back to the world rules)
        $PIDOF wpa_supplicant >/dev/null 2>&1 && $WPA_CLI -i wlan0 set country "${_c:-00}" >/dev/null 2>&1
        $IW reg set "${_c:-00}" 2>/dev/null
        logger -t tc100-event "Wi-Fi country: ${_c:-world}" 2>/dev/null
        exit 0 ;;
    *) echo "usage: $0 get|status|conf IN OUT|boot|apply" >&2; exit 2 ;;
esac
