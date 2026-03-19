#!/bin/sh
. /mnt/config/netmon.conf
LOGPATH="/tmp/log/network_reboot.log"

_NM_BTIME=0
_nm_now() {
  if [ "$_NM_BTIME" -le 0 ]; then
    while read -r _k _v _; do [ "$_k" = "btime" ] && _NM_BTIME="$_v" && break; done < /proc/stat
  fi
  read -r _nm_up _ < /proc/uptime
  _nm_ts=$((_NM_BTIME + ${_nm_up%.*}))
  [ "$_nm_ts" -gt 0 ] || _nm_ts=0
}

: "${PINGADDRESS:=192.168.0.1}"
: "${PINGINTERVAL:=120}"
: "${PING_ATTEMPTS:=1}"
: "${PING_TIMEOUT_SECONDS:=1}"
: "${RECONNECT_WAIT_SECONDS:=10}"
: "${RECHECK_WAIT_SECONDS:=20}"
: "${RECHECK_ATTEMPTS:=1}"
: "${REBOOT_DELAY_SECONDS:=3}"

case "$PINGINTERVAL" in
    ''|*[!0-9]*) PINGINTERVAL=120 ;;
esac
case "$PING_ATTEMPTS" in
    ''|*[!0-9]*) PING_ATTEMPTS=1 ;;
esac
case "$PING_TIMEOUT_SECONDS" in
    ''|*[!0-9]*) PING_TIMEOUT_SECONDS=1 ;;
esac
case "$RECONNECT_WAIT_SECONDS" in
    ''|*[!0-9]*) RECONNECT_WAIT_SECONDS=10 ;;
esac
case "$RECHECK_WAIT_SECONDS" in
    ''|*[!0-9]*) RECHECK_WAIT_SECONDS=20 ;;
esac
case "$RECHECK_ATTEMPTS" in
    ''|*[!0-9]*) RECHECK_ATTEMPTS=1 ;;
esac
case "$REBOOT_DELAY_SECONDS" in
    ''|*[!0-9]*) REBOOT_DELAY_SECONDS=3 ;;
esac

[ "$PINGINTERVAL" -lt 5 ] && PINGINTERVAL=5
[ "$PING_ATTEMPTS" -lt 1 ] && PING_ATTEMPTS=1
[ "$PING_TIMEOUT_SECONDS" -lt 1 ] && PING_TIMEOUT_SECONDS=1
[ "$RECONNECT_WAIT_SECONDS" -lt 1 ] && RECONNECT_WAIT_SECONDS=1
[ "$RECHECK_WAIT_SECONDS" -lt 1 ] && RECHECK_WAIT_SECONDS=1
[ "$RECHECK_ATTEMPTS" -lt 1 ] && RECHECK_ATTEMPTS=1
[ "$REBOOT_DELAY_SECONDS" -lt 1 ] && REBOOT_DELAY_SECONDS=1

check_connectivity()
{
  ping -q -c "$PING_ATTEMPTS" -W "$PING_TIMEOUT_SECONDS" "$PINGADDRESS" >/dev/null 2>&1
}

while true
do
  check_connectivity || {
    _nm_now; echo "@${_nm_ts} Network is down, trying to reconnect..." >> "$LOGPATH"
    /sbin/ifconfig wlan0 down && sleep "$RECONNECT_WAIT_SECONDS" && /sbin/ifconfig wlan0 up && sleep "$RECHECK_WAIT_SECONDS"
    ping -q -c "$RECHECK_ATTEMPTS" -W "$PING_TIMEOUT_SECONDS" "$PINGADDRESS" >/dev/null 2>&1 || {
      _nm_now; echo "@${_nm_ts} Network reconnection failed, reboot..." >> "$LOGPATH"
      sleep "$REBOOT_DELAY_SECONDS" && /sbin/reboot
    }
  }
  sleep "$PINGINTERVAL"
done
