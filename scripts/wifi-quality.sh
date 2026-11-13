#!/bin/sh
# Wi-Fi quality over time: one sample a minute (signal, transmit retries and failures, packet loss to the router),
# kept in RAM for 24 h, so that bursts of loss (the .24) can be seen and timed instead of guessed.
#   /tmp/wifi-quality.log   "epoch rssi_dbm retries failed loss_pct" (deltas since the previous sample), <= 1440 lines
#   /tmp/wifi-quality       last hour: rssi, rssi_min_1h, rssi_avg_1h, loss_pct_1h, retries_1h, failed_1h, samples_1h
# Read by mqtt-bridge.sh (diag: wifi_loss_pct, wifi_tx_retries, wifi_rssi_min).
# Nothing is written to flash or card. WIFI_QUALITY=1 in boot.conf switches it on (off by default); the housekeeper
# runs "wifi-quality.sh hk" (autorun-linux66.sh) and "wifi-quality.sh run" is the loop of its own without it.
#   wifi-quality.sh sample | summary | hk | run
# Test hooks: WQ_LOG, WQ_SUM, WQ_STATE, WQ_WIRELESS, WQ_STATION (a file instead of `iw station dump`), WQ_PING
# (a file instead of ping's output), WQ_NOW.
LOG=${WQ_LOG:-/tmp/wifi-quality.log}
SUM=${WQ_SUM:-/tmp/wifi-quality}
STATE=${WQ_STATE:-/tmp/.wifi-quality.prev}
IFACE=wlan0
MAXLINES=1440
. "${0%/*}/wifi-signal.sh"

_wq_btime=0
_wq_now() {
  if [ -n "${WQ_NOW:-}" ]; then
    _now="$WQ_NOW"
    return
  fi
  if [ "$_wq_btime" -le 0 ] 2>/dev/null && [ -r /proc/stat ]; then
    while read -r _k _v _; do
      [ "$_k" = btime ] && { _wq_btime="$_v"; break; }
    done < /proc/stat
  fi
  if [ "$_wq_btime" -gt 0 ] 2>/dev/null && [ -r "${WQ_UPTIME:-/proc/uptime}" ]; then
    read -r _up _ < "${WQ_UPTIME:-/proc/uptime}"
    _now=$((_wq_btime + ${_up%%.*}))
  else
    _now=$(date +%s)
  fi
}

wq_rssi() {
  WIFI_PROC_FILE="${WQ_WIRELESS:-}"
  wifi_signal_read
  echo "${WIFI_DBM:-null}"
}

# totals of "tx retries" and "tx failed" over the stations (the access point), and the averaged signal of the access
# point's beacons ("beacon signal avg", dBm; "-" when there is none). Not "signal avg": with rtl8xxxu it read -13 dBm on
# the .24 while beacons, /proc and the MCS 2 rate all said about -50 (tester, 2026-11-04). iw and ping run under
# timeout: a sample stuck in the Wi-Fi driver kept the housekeeper job "running" for hours (.11, 2026-11-03).
wq_station() {
  if [ -n "$WQ_STATION" ]; then cat "$WQ_STATION" 2>/dev/null
  elif [ -x /mnt/ext/bin/iw ]; then timeout 5 /mnt/ext/bin/iw dev "$IFACE" station dump 2>/dev/null
  else timeout 5 "$(command -v iw || echo /mnt/ext/bin/iw)" dev "$IFACE" station dump 2>/dev/null; fi | {
    _rt=0; _fl=0; _sg=-
    while read -r _a _b _v _rest; do
      case "$_a $_b" in
        "tx retries:") case "$_v" in ''|*[!0-9]*) ;; *) _rt=$((_rt + _v)) ;; esac ;;
        "tx failed:") case "$_v" in ''|*[!0-9]*) ;; *) _fl=$((_fl + _v)) ;; esac ;;
        "beacon signal") [ "$_v" = "avg:" ] && case "${_rest%% *}" in
            -[0-9]|-[0-9][0-9]|-10[0-9]|-110) [ "$_sg" = - ] && _sg=${_rest%% *} ;; esac ;;
      esac
    done
    echo "$_rt $_fl $_sg"
  }
}

wq_gateway() {
  while read -r _if _dst _gw _rest; do
    [ "$_dst" = 00000000 ] || continue
    case "$_gw" in ????????) ;; *) continue ;; esac
    # bytes 3-4 and 5-6 by expansion, not two $(echo | cut): six forks a minute less
    _g3=${_gw#????}; _g3=${_g3%??}; _g2=${_gw#??}; _g2=${_g2%????}
    printf '%d.%d.%d.%d\n' "0x${_gw#??????}" "0x$_g3" "0x$_g2" "0x${_gw%??????}"
    return 0
  done < /proc/net/route 2>/dev/null
  return 1
}

# packet loss in % over 3 pings to the router (null without a router)
wq_loss() {
  if [ -n "$WQ_PING" ]; then _out=$(cat "$WQ_PING" 2>/dev/null)
  else _gw=$(wq_gateway) || { _wq_loss_val=null; [ "${1:-}" = var ] || echo null; return; }; _out=$(timeout 8 ping -c 3 -W 1 -w 4 -q "$_gw" 2>/dev/null); fi
  # the digits just before the first "% packet loss" (was printf | sed | head: four forks)
  _p=; case "$_out" in *"% packet loss"*) _p=${_out%%"% packet loss"*}; _p=${_p##*[!0-9]} ;; esac
  case "$_p" in ''|*[!0-9]*) _wq_loss_val=null ;; *) _wq_loss_val="$_p" ;; esac
  [ "${1:-}" = var ] || echo "$_wq_loss_val"
}

wq_sample() {
  _wq_now
  set -- $(wq_station); _rt=${1:-0}; _fl=${2:-0}; _sg=${3:--}
  # the averaged signal of iw is the one value of the signal while this runs: kept for every reader
  # (scripts/wifi-signal.sh reads $WIFI_AVG_FILE while it is fresh), else the driver's /proc level
  if [ "$_sg" != - ]; then
    _rssi=$_sg; _u=0; read -r _u _r < "${WQ_UPTIME:-/proc/uptime}" 2>/dev/null
    echo "${_u%.*} $_sg" > "${WIFI_AVG_FILE:-/tmp/wifi-signal.avg}.tmp" && mv -f "${WIFI_AVG_FILE:-/tmp/wifi-signal.avg}.tmp" "${WIFI_AVG_FILE:-/tmp/wifi-signal.avg}"
  else
    WIFI_PROC_FILE="${WQ_WIRELESS:-}"
    wifi_signal_read
    _rssi="${WIFI_DBM:-null}"
  fi
  _prt=""; _pfl=""; _pln=""; [ -r "$STATE" ] && read -r _prt _pfl _pln < "$STATE"
  _drt=0; _dfl=0
  case "$_prt" in ''|*[!0-9]*) ;; *) [ "$_rt" -ge "$_prt" ] && _drt=$((_rt - _prt)) ;; esac
  case "$_pfl" in ''|*[!0-9]*) ;; *) [ "$_fl" -ge "$_pfl" ] && _dfl=$((_fl - _pfl)) ;; esac
  wq_loss var; _loss="$_wq_loss_val"
  echo "$_now $_rssi $_drt $_dfl $_loss" >> "$LOG"
  case "$_pln" in
    ''|*[!0-9]*)
      _n=0
      if [ -r "$LOG" ]; then
        while IFS= read -r _wq_l || [ -n "$_wq_l" ]; do _n=$((_n + 1)); done < "$LOG"
      fi
      ;;
    *) _n=$((_pln + 1)) ;;
  esac
  if [ "$_n" -gt $((MAXLINES + 60)) ]; then
    tail -n "$MAXLINES" "$LOG" > "$LOG.tmp" && mv -f "$LOG.tmp" "$LOG"
    _n="$MAXLINES"
  fi
  echo "$_rt $_fl $_n" > "$STATE"
  wq_summary "$_now"
}

wq_summary() {
  if [ -n "${1:-}" ]; then _now="$1"; else _wq_now; fi
  [ -r "$LOG" ] || return 0
  awk -v since=$((_now - 3600)) '
    { last_rssi = $2 }
    $1 >= since {
      n++
      if ($2 != "null") { r = $2 + 0; s += r; nr++; if (min == "" || r < min) min = r }
      rt += $3; fl += $4
      if ($5 != "null") { ls += $5; nl++ }
    }
    END {
      printf "rssi=%s\nrssi_min_1h=%s\nrssi_avg_1h=%s\nloss_pct_1h=%s\nretries_1h=%d\nfailed_1h=%d\nsamples_1h=%d\n",
        (last_rssi == "" ? "null" : last_rssi), (min == "" ? "null" : min), (nr ? int(s / nr) : "null"),
        (nl ? int(ls / nl + 0.5) : "null"), rt, fl, n
    }' "$LOG" > "$SUM.tmp" && mv -f "$SUM.tmp" "$SUM"
}

case "$1" in
  sample) wq_sample ;;
  summary) wq_summary ;;
  hk) wq_sample ;;
  run) while :; do wq_sample; sleep 60; done ;;
  *) echo "usage: $0 sample|summary|hk|run" >&2; exit 2 ;;
esac
