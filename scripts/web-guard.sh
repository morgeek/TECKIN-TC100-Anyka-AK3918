#!/bin/sh
# web-guard.sh — keeps a way into the camera when the web interface is down.
#
# Started by config/autostart/02_system-webserver (SD card and flash). Every
# minute it checks that a web port listens (443 or 80, or the ultra-lite
# port):
#   * the first time none does, it restarts the web server once;
#   * if that did not help, it opens a rescue telnet on port 23 (login as
#     usual) and logs it;
#   * as soon as the web interface has been back for two checks in a row, it
#     closes that rescue telnet again. A telnet the user started from
#     Services (telnet-server) is never touched.
# It also records whether HTTPS fell back to plain HTTP (/tmp/web-fallback),
# which the status line shows in the web page, and every 10 minutes checks
# the SD card (scripts/sd-health.sh; a write test after boot, then daily).
#
#   web-guard.sh run      the loop (backgrounded by 02_system-webserver)
#   web-guard.sh once     one check (tests)

. "${WG_COMMON:-/mnt/scripts/common_functions.sh}"
STATE="${WG_STATE:-/tmp/web-guard}"
PIDF="${WG_PIDFILE:-/var/run/rescue-telnetd.pid}"
INTERVAL="${WG_INTERVAL:-60}"
mkdir -p "$STATE" 2>/dev/null

_wg_ports()
{
    WEB_MODE=full; ULTRALITE_HTTP_PORT=80
    [ -f /mnt/config/boot.conf ] && . /mnt/config/boot.conf 2>/dev/null
    case "$WEB_MODE" in
        off) echo "" ;;
        ultra-lite|ultralite) echo "${ULTRALITE_HTTP_PORT:-80}" ;;
        *) echo "443 80" ;;
    esac
}

_wg_web_up()
{
    for _p in $(_wg_ports); do port_listening "$_p" && return 0; done
    return 1
}

_wg_rescue_running()
{
    [ -s "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null
}

_wg_rescue_start()
{
    _wg_rescue_running && return 0
    # Port 23 may already be the user's telnet-server: then nothing to do.
    port_listening 23 && return 0
    ${WG_TELNETD:-telnetd} -p 23 -F </dev/null >/dev/null 2>&1 &
    echo $! > "$PIDF"
    logger -t tc100-event -p user.err "web interface down: rescue telnet opened on port 23" 2>/dev/null
}

_wg_rescue_stop()
{
    _wg_rescue_running || { rm -f "$PIDF"; return 0; }
    kill "$(cat "$PIDF")" 2>/dev/null
    rm -f "$PIDF"
    logger -t tc100-event -p user.notice "web interface back: rescue telnet closed" 2>/dev/null
}

wg_once()
{
    [ -z "$(_wg_ports)" ] && return 0          # WEB_MODE=off: nothing to guard
    if _wg_web_up; then
        _n=$(cat "$STATE/up" 2>/dev/null); _n=$(( ${_n:-0} + 1 ))
        echo "$_n" > "$STATE/up"; rm -f "$STATE/restarted"
        [ "$_n" -ge 2 ] && _wg_rescue_stop
        if port_listening 443; then rm -f /tmp/web-fallback
        elif [ "$(cat /tmp/tc100-storage 2>/dev/null)" = flash ] && [ -s /mnt/config/lighttpd.pem ]; then
            echo http > /tmp/web-fallback
        fi
        return 0
    fi
    echo 0 > "$STATE/up"
    if [ ! -e "$STATE/restarted" ]; then
        : > "$STATE/restarted"
        logger -t tc100-event -p user.err "web interface down: restarting the web server" 2>/dev/null
        ${WG_RESTART:-http_server} on </dev/null >/dev/null 2>&1
        return 0
    fi
    _wg_rescue_start
}

case "${0##*/}" in
    web-guard.sh)
        case "$1" in
            once) wg_once ;;
            run) sleep "${WG_FIRST:-60}"; _i=0
                 while :; do
                     wg_once
                     # Network loss with the rest of the system running (net-guard.sh).
                     sh "${WG_NETGUARD:-/mnt/scripts/net-guard.sh}" once </dev/null >/dev/null 2>&1
                     if [ $((_i % 10)) -eq 0 ]; then
                         _last=$(sed -n 's/^test_ts=//p' /tmp/sd-health 2>/dev/null); _now=$(date +%s)
                         _up=$(cut -d. -f1 /proc/uptime)
                         _t=""; [ "$_up" -ge 300 ] && { [ -z "$_last" ] || [ $((_now - _last)) -ge 86400 ] || [ "$_last" -gt "$_now" ]; } && _t=--test
                         sh "${WG_SDH:-/mnt/scripts/sd-health.sh}" check $_t >/dev/null 2>&1
                     fi
                     _i=$((_i + 1)); sleep "$INTERVAL"
                 done ;;
            *) echo "usage: $0 run | once" >&2; exit 2 ;;
        esac ;;
esac
