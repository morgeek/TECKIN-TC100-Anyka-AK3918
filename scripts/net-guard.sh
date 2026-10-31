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

# No forks in the helpers below: the check runs every minute (3 minutes while the network is fine, see web-guard.sh).
# _ng_kv KEY: value of KEY in boot.conf (last line wins, one pair of double quotes removed, a value with another quote
# is ignored: what the former sed|tail gave), into $_kv
_ng_kv()
{
    _kv=
    [ -r "$CONF" ] || return 0
    while IFS= read -r _kl || [ -n "$_kl" ]; do
        case "$_kl" in "$1="*) ;; *) continue ;; esac
        _kx=${_kl#*=}; _kx=${_kx#\"}; _kx=${_kx%\"}
        case "$_kx" in *\"*) continue ;; esac
        _kv=$_kx
    done < "$CONF"
}
# uptime in seconds into $_now
_ng_up() { if [ -n "$NG_UPTIME" ]; then _now="$NG_UPTIME"; else read -r _u _ < /proc/uptime; _now="${_u%.*}"; fi; }
# first line of FILE into $_f1 (empty when unreadable)
_ng_first() { _f1=; [ -r "$1" ] && read -r _f1 < "$1"; return 0; }

# the default gateway into $_gw: first line with destination 0.0.0.0 of "route -n" text (NG_ROUTE_FILE: tests), or of
# /proc/net/route (hex, little endian: C0A80101 is written 0101A8C0)
_ng_gateway()
{
    _gw=
    if [ -n "$NG_ROUTE_FILE" ]; then
        [ -r "$NG_ROUTE_FILE" ] || return 0
        while read -r _rd _rg _; do
            [ "$_rd" = 0.0.0.0 ] && { _gw=$_rg; break; }
        done < "$NG_ROUTE_FILE"
        return 0
    fi
    [ -r /proc/net/route ] || return 0
    while read -r _ri _rd _rg _; do
        [ "$_rd" = 00000000 ] || continue
        case "$_rg" in [0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]) ;; *) continue ;; esac
        _o3=${_rg#??}; _o3=${_o3%????}; _o2=${_rg#????}; _o2=${_o2%??}
        _gw="$((0x${_rg#??????})).$((0x$_o2)).$((0x$_o3)).$((0x${_rg%??????}))"
        break
    done < /proc/net/route
}

_ng_ok()
{
    _ng_gateway
    [ -n "$_gw" ] || return 1
    ${NG_PING:-ping} -c 1 -W 3 "$_gw" >/dev/null 2>&1 && return 0
    sleep "${NG_RETRY_S:-2}"
    ${NG_PING:-ping} -c 1 -W 3 "$_gw" >/dev/null 2>&1
}

_ng_rescue_ap() { _ng_first "$WR_RUN/hostapd.pid"; [ -n "$_f1" ] && kill -0 "$_f1" 2>/dev/null; }

_ng_count() { _ng_first "$PERSIST"; _c=$_f1; case "$_c" in ''|*[!0-9]*) _c=0 ;; esac; echo "$_c"; }

_ng_limit()
{
    _ng_kv NET_GUARD_MIN; _min=$_kv
    case "$_min" in ''|*[!0-9]*|0) _min=15 ;; esac
    _n=$(_ng_count); [ "$_n" -gt 3 ] && _n=3
    _b=$((_min * 60)); _l=$_b
    while [ "$_n" -gt 0 ]; do _l=$((_l * 2)); _n=$((_n - 1)); done
    # Doubling stops at 2 h (or at the base itself when it is set above 2 h).
    _cap=7200; [ "$_b" -gt "$_cap" ] && _cap=$_b
    [ "$_l" -gt "$_cap" ] && _l=$_cap
    echo "$_l"
}

# network-monitor (Services, opt-in) does the same job with Wi-Fi bounces first: one network-loss rebooter at a time.
_ng_netmon() { _ng_first "${NG_NETMON_PID:-/var/run/network-monitor.pid}"; [ -n "$_f1" ] && kill -0 "$_f1" 2>/dev/null; }

ng_once()
{
    _ng_kv NET_GUARD
    case "$_kv" in 0|no|off|false) rm -f "$STATE/down_since"; return 0 ;; esac
    if _ng_netmon; then rm -f "$STATE/down_since"; return 0; fi
    _ng_up
    if _ng_ok; then
        if [ -f "$STATE/down_since" ]; then
            _ng_first "$STATE/down_since"; _ds=$_f1; rm -f "$STATE/down_since"
            logger -t tc100-event -p user.notice "net-guard: network back after $((_now - _ds)) s" 2>/dev/null
        fi
        [ -f "$STATE/up_since" ] || echo "$_now" > "$STATE/up_since"
        if [ -f "$PERSIST" ]; then
            _ng_first "$STATE/up_since"
            [ $((_now - _f1)) -ge 600 ] && { rm -f "$PERSIST"; sync; }
        fi
        return 0
    fi
    rm -f "$STATE/up_since"
    if [ ! -f "$STATE/down_since" ]; then
        echo "$_now" > "$STATE/down_since"
        logger -t tc100-event -p user.warn "net-guard: gateway unreachable, reboot in $(( $(_ng_limit) / 60 )) min if it stays so" 2>/dev/null
        return 0
    fi
    _ng_first "$STATE/down_since"; _ds=$_f1
    # W-NET: no wlan0 at all (the Wi-Fi chip failed to power on after a warm reboot): bring the chip back first, a warm
    # reboot did not (scripts/wifi-recover.sh: probe again, then a power cycle; it spaces its own tries by 5 min)
    [ -e "${NG_SYS:-/sys}/class/net/wlan0" ] || { sh "${NG_WIFI_RECOVER:-/mnt/scripts/wifi-recover.sh}" run </dev/null >/dev/null 2>&1 & }
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
                _ng_up; _d=0
                [ -f "$STATE/down_since" ] && { _ng_first "$STATE/down_since"; _d=$((_now - _f1)); }
                echo "down_s=$_d limit_s=$(_ng_limit) reboots=$(_ng_count)" ;;
            *) echo "usage: $0 once | status" >&2; exit 2 ;;
        esac ;;
esac
