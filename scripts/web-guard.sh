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
# Every minute it also runs the network guard (net-guard.sh) and refreshes the
# SD card panel (v3/linux66-sd/sdinfo-sd.sh). The loop is kept cheap (it lives as long as the camera, one core at
# 480 MHz, each fork+exec costs a few ms): the check of the web port reads /proc/net/tcp in the shell, the network
# guard runs every minute only while the gateway is out and every 3rd minute otherwise, the SD panel script runs when
# the card state changed (or every 10th minute) and common_functions.sh (31 KB) is sourced only on the failure paths.
#
#   web-guard.sh run      the loop (started by v3/autorun-linux66.sh)
#   web-guard.sh once     one check (tests)

# port_listening here (same as common_functions.sh): a TCP socket in LISTEN state on the port, from /proc/net/tcp[6]
port_listening() {
  case "$1" in ''|*[!0-9]*) return 1 ;; esac
  eval "_pl_hex=\$_plh_$1"   # the hex form of the port is computed once (one printf fork), not each minute
  [ -n "$_pl_hex" ] || { _pl_hex="$(printf '%04X' "$1")"; eval "_plh_$1=\$_pl_hex"; }
  for _pl_f in /proc/net/tcp /proc/net/tcp6; do
    [ -r "$_pl_f" ] || continue
    while read -r _pl_sl _pl_local _pl_rem _pl_st _pl_rest; do
      [ "$_pl_st" = 0A ] || continue
      case "$_pl_local" in *":$_pl_hex") return 0 ;; esac
    done < "$_pl_f"
  done
  return 1
}
# common_functions.sh (http_server, netacl_exec) only when something went wrong; WG_COMMON (tests) is loaded at once
_wg_common() { [ -n "$_wg_cf" ] && return 0; _wg_cf=1; . "${WG_COMMON:-/mnt/scripts/common_functions.sh}"; }
[ -n "${WG_COMMON:-}" ] && _wg_common
STATE="${WG_STATE:-/tmp/web-guard}"
PIDF="${WG_PIDFILE:-/var/run/rescue-telnetd.pid}"
INTERVAL="${WG_INTERVAL:-60}"
mkdir -p "$STATE" 2>/dev/null

# httpfront on port 80 only (no HTTPS); empty = WEB_MODE off, nothing to guard
WG_PORTS="80"

_wg_web_up()
{
    for _p in $WG_PORTS; do port_listening "$_p" && return 0; done
    return 1
}

_wg_rescue_running()
{
    _wg_pid=""; [ -s "$PIDF" ] && read -r _wg_pid < "$PIDF"
    [ -n "$_wg_pid" ] && kill -0 "$_wg_pid" 2>/dev/null
}

_wg_rescue_start()
{
    _wg_rescue_running && return 0
    _wg_common
    # Port 23 may already be the user's telnet-server: then nothing to do.
    port_listening 23 && return 0
    if [ -n "${WG_TELNETD:-}" ]; then "$WG_TELNETD" -p 23 -F </dev/null >/dev/null 2>&1 &
    else netacl_exec rescue-telnet telnetd -p 23 -F </dev/null >/dev/null 2>&1 &   # LAN only
    fi
    echo $! > "$PIDF"
    logger -t tc100-event -p user.err "web interface down: rescue telnet opened on port 23" 2>/dev/null
}

_wg_rescue_stop()
{
    _wg_rescue_running || { rm -f "$PIDF"; return 0; }
    kill "$_wg_pid" 2>/dev/null
    rm -f "$PIDF"
    logger -t tc100-event -p user.notice "web interface back: rescue telnet closed" 2>/dev/null
}

# state of the card in one word (no fork): block device size and what /proc/mounts says of /mnt and /mnt/sd
_wg_sdsig()
{
    _wg_sig=none
    [ -b /dev/mmcblk0 ] || return 0
    _sz=0; [ -r /sys/block/mmcblk0/size ] && read -r _sz < /sys/block/mmcblk0/size
    _wg_sig="$_sz"
    while read -r _d _mp _fs _opt _rest; do
        case "$_mp $_fs" in
            "/mnt/sd vfat"|"/mnt/sd exfat"|"/mnt vfat") _wg_sig="$_wg_sig:$_mp:$_fs:$_opt" ;;
        esac
    done < /proc/mounts
}

wg_once()
{
    [ -z "$WG_PORTS" ] && return 0          # WEB_MODE=off: nothing to guard
    if _wg_web_up; then
        _n=0; [ -r "$STATE/up" ] && read -r _n < "$STATE/up"
        case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
        _n=$(( _n + 1 ))
        echo "$_n" > "$STATE/up"; rm -f "$STATE/restarted"
        [ "$_n" -ge 2 ] && _wg_rescue_stop
        return 0
    fi
    echo 0 > "$STATE/up"
    if [ ! -e "$STATE/restarted" ]; then
        : > "$STATE/restarted"
        logger -t tc100-event -p user.err "web interface down: restarting the web server" 2>/dev/null
        _wg_common
        ${WG_RESTART:-http_server} on </dev/null >/dev/null 2>&1
        return 0
    fi
    _wg_rescue_start
}

case "${0##*/}" in
    web-guard.sh)
        case "$1" in
            once) wg_once ;;
            run) sleep "${WG_FIRST:-60}"; _i=0; _sd_prev=
                 while :; do
                     wg_once
                     # Network loss with the rest of the system running (net-guard.sh). While the gateway answers one
                     # ping every 3rd minute is enough; once a check failed (net-guard keeps down_since) every minute,
                     # so the limits of the guard (NET_GUARD_MIN, doubling, forced reboot) count as before.
                     if [ -e "${WG_NETSTATE:-/tmp/net-guard}/down_since" ] || [ $((_i % 3)) -eq 0 ]; then
                         sh "${WG_NETGUARD:-/mnt/scripts/net-guard.sh}" once </dev/null >/dev/null 2>&1
                     fi
                     # the SD panel (card put in or taken out): the script runs when the card state (size, mounted,
                     # read-only) is not the one of the last run, and every 10th minute for the free space
                     _wg_sdsig
                     if [ "$_wg_sig" != "$_sd_prev" ] || [ $((_i % 10)) -eq 0 ]; then
                         sh "${WG_SDINFO:-/mnt/v3/linux66-sd/sdinfo-sd.sh}" </dev/null >/dev/null 2>&1
                         _sd_prev=$_wg_sig
                     fi
                     _i=$((_i + 1)); sleep "$INTERVAL"
                 done ;;
            *) echo "usage: $0 run | once" >&2; exit 2 ;;
        esac ;;
esac
