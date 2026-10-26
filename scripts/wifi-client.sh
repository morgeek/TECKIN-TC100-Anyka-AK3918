#!/bin/sh
# wifi-client.sh — run the bundled wpa_supplicant 2.11 (bin/wpa_supplicant)
# instead of the vendor one (Realtek-patched 0.8.x from 2013, which predates
# the KRACK fixes), with an automatic fallback to the vendor client.
#
# Opt-in: boot.conf WIFI_CLIENT=new. autorun.sh calls
#   wifi-client.sh start anyka            vendor setup (/usr/sbin/wifi_station.sh)
#   wifi-client.sh start <wpa.conf>       manual setup (/mnt/wpa_supplicant.conf)
# and falls back to the vendor client itself when this returns non-zero.
#
# 2.11 is built for the Realtek driver's wireless-extensions interface only
# (-Dwext, internal crypto, no WPS/EAP: src/wpa_supplicant/build.sh). The
# vendor configuration carries WPS device keys that such a build rejects, so
# a copy without them is used. The vendor wifi_station.sh then adds the
# network through wpa_cli, exactly as at a normal boot.
#
#   wifi-client.sh status   one line: client=new|vendor state=<wpa_state>
# Exit codes of start: 0 associated with 2.11; 1 not associated in time or
# not startable (2.11 stopped, the caller starts the vendor client).

NEW_BIN="${WIFI_NEW_BIN:-/mnt/bin/wpa_supplicant}"
CONF_TMP=/tmp/wpa_supplicant-new.conf
PIDFILE=/var/run/wpa_supplicant-new.pid
TIMEOUT="${WIFI_NEW_TIMEOUT:-60}"
LOG="${WIFI_CLIENT_LOG:-/tmp/log/wifi-client.log}"

_wc_log() { mkdir -p "${LOG%/*}" 2>/dev/null; echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$LOG"; }

_wc_stop_all()
{
    for _p in $(ps | awk '/[w]pa_supplicant/ && !/wifi-client/ {print $1}'); do kill "$_p" 2>/dev/null; done
    sleep 1
    rm -f /var/run/wpa_supplicant/wlan0 "$PIDFILE"
}

_wc_state() { wpa_cli -i wlan0 status 2>/dev/null | awk -F= '/^wpa_state=/ {print $2; exit}'; }

wc_start()
{
    _mode="$1"
    [ -x "$NEW_BIN" ] || { _wc_log "no $NEW_BIN"; return 1; }
    "$NEW_BIN" -v >/dev/null 2>&1 || { _wc_log "$NEW_BIN does not run"; return 1; }
    case "$_mode" in
        anyka) _src=/etc/jffs2/wpa_supplicant.conf ;;
        *) _src="$_mode" ;;
    esac
    [ -r "$_src" ] || { _wc_log "no $_src"; return 1; }
    # Drop the WPS device keys (vendor template); keep everything else.
    grep -v -E '^[[:space:]]*(device_name|manufacturer|model_name|model_number|serial_number|device_type|os_version|config_methods|wps_[a-z_]*)=' \
        "$_src" > "$CONF_TMP" 2>/dev/null || return 1
    # In manual mode the UI rewrites $_src and runs "wpa_cli reconfigure";
    # point 2.11 at the file itself when it needs no filtering.
    _conf="$CONF_TMP"
    [ "$_mode" != anyka ] && cmp -s "$_src" "$CONF_TMP" && _conf="$_src"

    _wc_stop_all
    if ! "$NEW_BIN" -B -i wlan0 -Dwext -c "$_conf" -P "$PIDFILE" >>"$LOG" 2>&1; then
        _wc_log "2.11 did not start (config: $_conf)"
        _wc_stop_all; return 1
    fi
    _connect_pid=""
    if [ "$_mode" = anyka ]; then
        /usr/sbin/wifi_station.sh connect >/dev/null 2>&1 &
        _connect_pid=$!
    fi
    _i=0
    while [ "$_i" -lt "$TIMEOUT" ]; do
        sleep 2; _i=$((_i + 2))
        if [ "$(_wc_state)" = COMPLETED ]; then
            _wc_log "2.11 associated after ${_i}s ($_mode)"
            echo new > /var/run/wifi-client
            # The vendor connect script goes on with DHCP; the boot expects an
            # address afterwards, as with the vendor client (bounded wait).
            _j=0
            while [ -n "$_connect_pid" ] && kill -0 "$_connect_pid" 2>/dev/null && [ "$_j" -lt 45 ]; do
                sleep 1; _j=$((_j + 1))
            done
            return 0
        fi
    done
    _wc_log "2.11 not associated after ${TIMEOUT}s (state $(_wc_state)), back to the vendor client"
    [ -n "$_connect_pid" ] && kill "$_connect_pid" 2>/dev/null
    logger -t tc100-event -p user.err "wpa_supplicant 2.11 did not associate in ${TIMEOUT}s; vendor Wi-Fi client used" 2>/dev/null
    _wc_stop_all
    return 1
}

case "${0##*/}" in
    wifi-client.sh)
        case "$1" in
            start) wc_start "${2:-anyka}" ;;
            status) _c=vendor; [ -r /var/run/wifi-client ] && read -r _c < /var/run/wifi-client
                    echo "client=$_c state=$(_wc_state)" ;;
            *) echo "usage: $0 start anyka|<wpa.conf> | status" >&2; exit 2 ;;
        esac ;;
esac
