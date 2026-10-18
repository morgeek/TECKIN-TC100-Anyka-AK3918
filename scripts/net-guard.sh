#!/bin/sh
# net-guard.sh — reboots the camera when it has been off the network for a
# long time while the rest of the system keeps running.
#
# The hardware watchdog only resets a camera whose userspace has stopped.
# A Wi-Fi driver or network stack stuck while the watchdog feeder still runs
# leaves the camera unreachable until someone pulls the plug (seen on a test
# camera, 2026-10-18: 20+ min off the network after a code upload).
#
# Called once a minute by scripts/web-guard.sh (always started at boot by
# config/autostart/02_system-webserver). A check pings the default gateway;
# with no default route the check fails too.
#   * NET_GUARD_MIN minutes in a row without the gateway (default 15) →
#     reboot, recorded by reboot-tracker.sh;
#   * if the reboot itself does not happen within NET_GUARD_FORCE_S (120 s),
#     the watchdog feeder is stopped so the hardware watchdog resets the
#     camera (8 s later);
#   * after such a reboot the next limit doubles (15, 30, 60, then 120 min at
#     most), so a router that is off for a night costs a few reboots, not one
#     every 15 min. The count is kept in the persistent config (one small
#     write per reboot) and cleared once the network has been back 10 min;
#   * never while the Wi-Fi rescue access point is up (scripts/wifi-rescue.sh):
#     someone may be connected to it to fix the Wi-Fi settings.
# boot.conf: NET_GUARD=1 (0 = off), NET_GUARD_MIN=15.
#
#   net-guard.sh once     one check
#   net-guard.sh status   down_s=<seconds without network> limit_s=<...> reboots=<n>

CONF="${NG_BOOT_CONF:-/mnt/config/boot.conf}"
STATE="${NG_STATE:-/tmp/net-guard}"
PERSIST="${NG_PERSIST:-/mnt/config/.net-guard-reboots}"
WR_RUN="${NG_WR_RUN:-/tmp/wifi-rescue}"
mkdir -p "$STATE" 2>/dev/null

_ng_kv() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" "$CONF" 2>/dev/null | tail -n 1; }
_ng_up() { if [ -n "$NG_UPTIME" ]; then echo "$NG_UPTIME"; else cut -d. -f1 /proc/uptime; fi; }

_ng_gateway()
{
    if [ -n "$NG_ROUTE_FILE" ]; then cat "$NG_ROUTE_FILE"; else route -n 2>/dev/null; fi |
        awk '$1 == "0.0.0.0" { print $2; exit }'
}

_ng_ok()
{
    _gw="$(_ng_gateway)"
    [ -n "$_gw" ] || return 1
    ${NG_PING:-ping} -c 1 -W 3 "$_gw" >/dev/null 2>&1 && return 0
    sleep "${NG_RETRY_S:-2}"
    ${NG_PING:-ping} -c 1 -W 3 "$_gw" >/dev/null 2>&1
}

_ng_rescue_ap() { [ -f "$WR_RUN/hostapd.pid" ] && kill -0 "$(cat "$WR_RUN/hostapd.pid" 2>/dev/null)" 2>/dev/null; }

_ng_count() { _c=$(cat "$PERSIST" 2>/dev/null); case "$_c" in ''|*[!0-9]*) _c=0 ;; esac; echo "$_c"; }

_ng_limit()
{
    _min="$(_ng_kv NET_GUARD_MIN)"
    case "$_min" in ''|*[!0-9]*|0) _min=15 ;; esac
    _n=$(_ng_count); [ "$_n" -gt 3 ] && _n=3
    _b=$((_min * 60)); _l=$_b
    while [ "$_n" -gt 0 ]; do _l=$((_l * 2)); _n=$((_n - 1)); done
    # Doubling stops at 2 h (or at the base itself when it is set above 2 h).
    _cap=7200; [ "$_b" -gt "$_cap" ] && _cap=$_b
    [ "$_l" -gt "$_cap" ] && _l=$_cap
    echo "$_l"
}

ng_once()
{
    case "$(_ng_kv NET_GUARD)" in 0|no|off|false) rm -f "$STATE/down_since"; return 0 ;; esac
    _now=$(_ng_up)
    if _ng_ok; then
        if [ -f "$STATE/down_since" ]; then
            _ds=$(cat "$STATE/down_since"); rm -f "$STATE/down_since"
            logger -t tc100-event -p user.notice "net-guard: network back after $((_now - _ds)) s" 2>/dev/null
        fi
        [ -f "$STATE/up_since" ] || echo "$_now" > "$STATE/up_since"
        if [ -f "$PERSIST" ] && [ $((_now - $(cat "$STATE/up_since"))) -ge 600 ]; then
            rm -f "$PERSIST"; sync
        fi
        return 0
    fi
    rm -f "$STATE/up_since"
    if [ ! -f "$STATE/down_since" ]; then
        echo "$_now" > "$STATE/down_since"
        logger -t tc100-event -p user.warn "net-guard: gateway unreachable, reboot in $(( $(_ng_limit) / 60 )) min if it stays so" 2>/dev/null
        return 0
    fi
    _ds=$(cat "$STATE/down_since")
    _lim=$(_ng_limit)
    [ $((_now - _ds)) -ge "$_lim" ] || return 0
    if _ng_rescue_ap; then return 0; fi
    _n=$(( $(_ng_count) + 1 ))
    echo "$_n" > "$PERSIST"
    _msg="net-guard: no network for $((_now - _ds)) s, reboot (#$_n)"
    logger -t tc100-event -p user.err "$_msg" 2>/dev/null
    sh "${NG_TRACKER:-/mnt/scripts/reboot-tracker.sh}" intent "$_msg" >/dev/null 2>&1
    sync
    # A reboot stuck in a driver (Wi-Fi, SD card) would leave the camera as it
    # is: stop feeding the hardware watchdog, which then resets it.
    ( sleep "${NG_FORCE_S:-120}"; ${NG_KILLWD:-killall -9 watchdog} ) </dev/null >/dev/null 2>&1 &
    ${NG_REBOOT:-reboot}
}

case "${0##*/}" in
    net-guard.sh)
        case "$1" in
            once) ng_once ;;
            status)
                _now=$(_ng_up); _d=0
                [ -f "$STATE/down_since" ] && _d=$((_now - $(cat "$STATE/down_since")))
                echo "down_s=$_d limit_s=$(_ng_limit) reboots=$(_ng_count)" ;;
            *) echo "usage: $0 once | status" >&2; exit 2 ;;
        esac ;;
esac
