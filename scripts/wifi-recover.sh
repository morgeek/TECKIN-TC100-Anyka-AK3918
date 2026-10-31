#!/bin/sh
# wifi-recover.sh [check|run]   bring back a Wi-Fi chip the driver could not power on (test queue W-NET)
#
# W-NET (IPCAM2, 2026-10-31): after warm reboots the RTL8188FU answered on USB but "rtl8xxxu_init_device: Failed power
# on", probe error -16, no wlan0, five boots in a row; a warm reboot (net-guard's remedy) did not help, a power cut
# did. This script acts only when wlan0 is missing, step by step, each step waiting up to WR_WAIT seconds for wlan0:
#   1. the USB device is probed again (authorized 0 -> 1: the driver's probe runs again);
#   2. the chip's power is cut and restored through GPIO 11, then probed again: the stock firmware's board data names
#      GPIO 11 as the Wi-Fi power / reset pin, high = on (sdio_wifi.ko: on, then 2 s before the USB and Wi-Fi drivers;
#      docs/linux-port/vendor-re-findings.md). WIFI_POWER_GPIO=0 in boot.conf leaves the pin alone.
# Then the Wi-Fi settings are applied again (wifi-apply: wpa_supplicant, DHCP). Every step goes to syslog and the
# console. check: exit 0 when wlan0 exists. Paths can be overridden (WR_*) for the tests.
WR_SYS=${WR_SYS:-/sys}
WR_DEV=${WR_DEV:-$WR_SYS/bus/usb/devices/1-1}
WR_WAIT=${WR_WAIT:-20}
WR_APPLY=${WR_APPLY:-/mnt/v3/linux66-sd/wifi-apply}
WR_BOOTCONF=${WR_BOOTCONF:-/mnt/config/boot.conf}
WR_CONSOLE=${WR_CONSOLE:-/dev/console}
WR_LOCK=${WR_LOCK:-/tmp/.wifi-recover.lock}
WR_LAST=${WR_LAST:-/tmp/.wifi-recover.last}
WR_MARK=${WR_MARK:-/mnt/config/.wifi-recover-restarts}
WR_GAP=${WR_GAP:-300}     # seconds between two tries (net-guard calls it every minute while wlan0 is missing)

wr_log() { echo "[wifi-recover] $*" >> "$WR_CONSOLE" 2>/dev/null; logger -t tc100-event -p user.warn "wifi-recover: $*" 2>/dev/null; }
wr_have() { [ -e "$WR_SYS/class/net/wlan0" ]; }
wr_wait() { _i=0; while [ "$_i" -lt "$WR_WAIT" ]; do wr_have && return 0; sleep 1; _i=$((_i + 1)); done; wr_have; }
wr_gpio() {   # the Wi-Fi power pin, sysfs number (GPIO 11 of the first bank, chips at 512); empty = leave it alone
  _g=$(sed -n 's/^WIFI_POWER_GPIO="\{0,1\}\([0-9]*\)"\{0,1\}$/\1/p' "$WR_BOOTCONF" 2>/dev/null | tail -n 1)
  case "$_g" in 0) echo "" ;; '') echo 523 ;; *) echo "$_g" ;; esac
}
wr_set() {    # wr_set N VALUE: N as an output at VALUE
  _p=$WR_SYS/class/gpio/gpio$1
  [ -d "$_p" ] || echo "$1" > "$WR_SYS/class/gpio/export" 2>/dev/null
  echo out > "$_p/direction" 2>/dev/null
  echo "$2" > "$_p/value" 2>/dev/null
}
wr_reprobe() {
  [ -w "$WR_DEV/authorized" ] || return 1
  echo 0 > "$WR_DEV/authorized" 2>/dev/null; sleep 1; echo 1 > "$WR_DEV/authorized" 2>/dev/null
}

case "${1:-run}" in
  check) wr_have; exit $? ;;
  run) ;;
  *) echo "usage: wifi-recover.sh [check|run]" >&2; exit 2 ;;
esac
wr_have && exit 0
read -r _up _ < /proc/uptime; _now=${_up%.*}
if [ -r "$WR_LAST" ]; then read -r _last < "$WR_LAST"; case "$_last" in ""|*[!0-9]*) ;; *) [ $((_now - _last)) -ge "$WR_GAP" ] || exit 0 ;; esac; fi
mkdir "$WR_LOCK" 2>/dev/null || exit 0      # one recovery at a time (boot and net-guard)
echo "$_now" > "$WR_LAST" 2>/dev/null
trap 'rmdir "$WR_LOCK" 2>/dev/null' EXIT
wr_log "no wlan0: probing the Wi-Fi chip again"
ok=
if wr_reprobe && wr_wait; then ok="USB probe"
else
  G=$(wr_gpio)
  if [ -n "$G" ]; then
    wr_log "still no wlan0: power cycle of the Wi-Fi chip (GPIO $G)"
    wr_set "$G" 0; sleep 1; wr_set "$G" 1; sleep 2
    wr_reprobe
    wr_wait && ok="power cycle (GPIO $G)"
  fi
fi
if [ -z "$ok" ]; then wr_log "Wi-Fi chip not recovered (a power cut is needed)"; exit 1; fi
wr_log "wlan0 back after the $ok (USB speed $(cat "$WR_DEV/speed" 2>/dev/null || echo ?) Mbit/s): Wi-Fi settings applied again"
[ -f "$WR_APPLY" ] && sh "$WR_APPLY" >/dev/null 2>&1
# R14-01: after a power cycle by hand the chip came back but the link stayed bad (pings of 1-3 s, RX drops) until a
# warm reboot, which then started from the freshly powered chip. So after a power cycle the gateway is pinged; a lost or
# slow link (average above WR_SLOW_MS) restarts the camera, once: the count in WR_MARK (kept in the flash settings)
# stops a second restart until the net-guard has seen the network fine for 10 minutes.
case "$ok" in "power cycle"*) ;; *) exit 0 ;; esac
sleep "${WR_SETTLE:-25}"
gw=$(ip route 2>/dev/null | sed -n 's/^default via \([0-9.]*\).*/\1/p' | head -n 1)
avg=$( [ -n "$gw" ] && ping -c 4 -W 2 "$gw" 2>/dev/null | sed -n 's|.*min/avg/max[^=]*= *[0-9.]*/\([0-9]*\).*|\1|p')
case "$avg" in ''|*[!0-9]*) avg=99999 ;; esac
[ "$avg" -le "${WR_SLOW_MS:-500}" ] && { wr_log "link fine after the power cycle (gateway $avg ms)"; exit 0; }
n=0; [ -r "$WR_MARK" ] && read -r n < "$WR_MARK"; case "$n" in ''|*[!0-9]*) n=0 ;; esac
if [ "$n" -ge 1 ]; then wr_log "link still slow (gateway ${avg} ms) after a restart for it: left as it is"; exit 0; fi
echo $((n + 1)) > "$WR_MARK" 2>/dev/null
wr_log "link slow after the power cycle (gateway ${avg} ms): restart from the freshly powered chip"
sh "${WR_TRACKER:-/mnt/scripts/reboot-tracker.sh}" intent "wifi-recover: link slow after a Wi-Fi power cycle, clean restart" >/dev/null 2>&1
sync
${WR_REBOOT:-reboot}
exit 0
