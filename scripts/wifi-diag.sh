#!/bin/sh
# wifi-diag.sh: find WHERE the Wi-Fi ping losses come from (audit 2026-11-06, docs/linux-port/audit-2026-11-06.md, W1).
# READ ONLY: it never touches wlan0, wpa_supplicant, the driver or a setting; it writes to RAM only (/tmp), and stops by
# itself. Safe to run over ssh on a camera without a serial console.
# Field data (rc27, rc28): ~9 % of samples lose every ping to the router, 0.3-1.9 s latency spikes, no disassociation,
# power saving off, no CONFIG_PM (no USB autosuspend), and losses with 0 tx retries / 0 tx failures: the receive path
# (rtl8xxxu over the vendor USB host driver) or a stall of the camera itself, not the radio. One line a second tells them
# apart:
#   up_ms gap_ms rx_pkts tx_pkts rx_drop usb_irq beacons ping_ms
#   gap_ms   time lost by this loop beyond its 1 s sleep (> 300: the camera itself stalled: CPU, scheduler)
#   rx_pkts  wlan0 received packets (no change for several seconds while the router beacons: receive path stalled)
#   usb_irq  interrupts of the USB host since boot (no change: the USB host stopped interrupting)
#   beacons  "beacon rx" of the access point (iw, every 5 s; "-" in between)
#   ping_ms  one ping to the router (timeout 1 s; "-" = lost) when started with "ping"
# Usage (as root, over ssh):
#   sh /mnt/scripts/wifi-diag.sh run [SECONDS] [ping]   default 3600 s, at most 86400; in the background: add " &"
#   sh /mnt/scripts/wifi-diag.sh summary                 stalls, frozen receive, frozen USB, lost pings, with times
#   sh /mnt/scripts/wifi-diag.sh stop
# /tmp/wifi-diag.log keeps the last 21600 lines (6 h, ~0.4 MB of RAM). Test hooks: WD_LOG, WD_PID, WD_SYS (folder
# instead of /sys/class/net/wlan0/statistics), WD_INTR, WD_UPTIME, WD_STATION, WD_PING, WD_SLEEP, WD_GW.
LOG=${WD_LOG:-/tmp/wifi-diag.log}
PIDF=${WD_PID:-/tmp/wifi-diag.pid}
SYS=${WD_SYS:-/sys/class/net/wlan0/statistics}
INTR=${WD_INTR:-/proc/interrupts}
UPT=${WD_UPTIME:-/proc/uptime}
MAXLINES=21600

wd_up_ms() { read -r _u _r < "$UPT" 2>/dev/null; _s=${_u%.*}; _f=${_u#*.}; _f=${_f}00; echo $((_s * 1000 + ${_f%"${_f#???}"} )); }
wd_stat() { _v=0; read -r _v < "$SYS/$1" 2>/dev/null; case "$_v" in ''|*[!0-9]*) _v=0 ;; esac; echo "$_v"; }
# total of the interrupt lines of the USB host (name contains usb, otg or hcd)
wd_usb_irq() {
  _t=0
  while read -r _n _c _rest; do
    case "$_rest" in *[Uu][Ss][Bb]*|*otg*|*hcd*) case "$_c" in ''|*[!0-9]*) ;; *) _t=$((_t + _c)) ;; esac ;; esac
  done < "$INTR" 2>/dev/null
  echo "$_t"
}
wd_beacons() {
  if [ -n "$WD_STATION" ]; then cat "$WD_STATION" 2>/dev/null
  else timeout 3 "$(command -v iw || echo /mnt/ext/bin/iw)" dev wlan0 station dump 2>/dev/null; fi |
    sed -n 's/^[[:space:]]*beacon rx:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -n 1
}
wd_gateway() {
  [ -n "$WD_GW" ] && { echo "$WD_GW"; return 0; }
  while read -r _if _dst _gw _rest; do
    [ "$_dst" = 00000000 ] || continue
    case "$_gw" in ????????) ;; *) continue ;; esac
    printf '%d.%d.%d.%d\n' "0x${_gw#??????}" "0x$(echo "$_gw" | cut -c5-6)" "0x$(echo "$_gw" | cut -c3-4)" "0x${_gw%??????}"
    return 0
  done < /proc/net/route 2>/dev/null
  return 1
}
wd_ping() {
  if [ -n "$WD_PING" ]; then _o=$(cat "$WD_PING" 2>/dev/null)
  else _o=$(timeout 2 ping -c 1 -W 1 "$1" 2>/dev/null); fi
  _t=$(printf '%s\n' "$_o" | sed -n 's/.*time=\([0-9][0-9]*\).*/\1/p' | head -n 1)
  echo "${_t:--}"
}

run() {
  _secs=${1:-3600}; case "$_secs" in ''|*[!0-9]*) _secs=3600 ;; esac
  [ "$_secs" -gt 86400 ] && _secs=86400
  _ping=$2; _gw=
  if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; then echo "already running" >&2; return 1; fi
  echo $$ > "$PIDF"
  trap 'rm -f "$PIDF"' EXIT INT TERM
  [ "$_ping" = ping ] && _gw=$(wd_gateway)
  echo "# wifi-diag start $(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) secs=$_secs gw=${_gw:-none}" >> "$LOG"
  echo "# up_ms gap_ms rx_pkts tx_pkts rx_drop usb_irq beacons ping_ms" >> "$LOG"
  _prev=$(wd_up_ms); _i=0; _n=0
  while [ "$_i" -lt "$_secs" ]; do
    sleep "${WD_SLEEP:-1}"
    _now=$(wd_up_ms); _gap=$((_now - _prev - 1000)); [ "$_gap" -lt 0 ] && _gap=0; _prev=$_now
    _b=-; [ $((_i % 5)) = 0 ] && { _b=$(wd_beacons); _b=${_b:--}; }
    _p=-; [ -n "$_gw" ] && _p=$(wd_ping "$_gw")
    echo "$_now $_gap $(wd_stat rx_packets) $(wd_stat tx_packets) $(wd_stat rx_dropped) $(wd_usb_irq) $_b $_p" >> "$LOG"
    _i=$((_i + 1)); _n=$((_n + 1))
    # keep the log bounded (RAM): trim once it is 10 % over
    if [ "$_n" -ge $((MAXLINES / 10)) ]; then
      _n=0
      if [ "$(wc -l < "$LOG")" -gt $((MAXLINES + MAXLINES / 10)) ]; then
        tail -n "$MAXLINES" "$LOG" > "$LOG.tmp" && mv -f "$LOG.tmp" "$LOG"
      fi
    fi
  done
  echo "# wifi-diag end" >> "$LOG"
}

# events worth looking at, with the uptime in seconds: a stall of the loop, receive or USB counters frozen for 3 s or
# more, and every lost ping; then the totals
summary() {
  [ -r "$LOG" ] || { echo "no $LOG"; return 1; }
  awk '
    /^# wifi-diag start/ { ping = ($0 !~ /gw=none/); next }
    /^#/ { next }
    NF >= 8 {
      n++; t = int($1 / 1000)
      if ($2 > 300) { stalls++; printf "%d s: camera stalled %d ms\n", t, $2 }
      if (n > 1 && $3 == rx) { rxf++ } else { if (rxf >= 3) { rxs++; printf "%d s: receive frozen %d s\n", t, rxf }; rxf = 0 }
      if (n > 1 && $6 == usb) { usbf++ } else { if (usbf >= 3) { usbs++; printf "%d s: USB interrupts frozen %d s\n", t, usbf }; usbf = 0 }
      if (ping && $8 == "-") { lost++; printf "%d s: ping lost (rx frozen %d s, usb frozen %d s, gap %d ms)\n", t, rxf, usbf, $2 }
      if ($8 != "-") pings++
      rx = $3; usb = $6
    }
    END {
      printf "samples %d, camera stalls > 300 ms %d, receive frozen >= 3 s %d, USB frozen >= 3 s %d, pings %d, lost %d\n",
        n, stalls, rxs, usbs, pings + lost, lost
    }' "$LOG"
}

stop() {
  _p=$(cat "$PIDF" 2>/dev/null)
  [ -n "$_p" ] && kill "$_p" 2>/dev/null
  rm -f "$PIDF"
  echo "stopped"
}

case "$1" in
  run) shift; run "$@" ;;
  summary) summary ;;
  stop) stop ;;
  *) echo "usage: $0 run [SECONDS] [ping] | summary | stop" >&2; exit 2 ;;
esac
