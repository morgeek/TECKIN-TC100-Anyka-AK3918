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

wq_rssi() {
  _r=null
  while read -r _i _s _q _l _rest; do
    [ "${_i%:}" = "$IFACE" ] || continue
    _l=${_l%.}
    case "$_l" in -[0-9]*) _r=$_l ;; [0-9]*) [ "$_l" -gt 0 ] && [ "$_l" -le 256 ] && _r=$((_l - 256)) ;; esac
    break
  done < "${WQ_WIRELESS:-/proc/net/wireless}" 2>/dev/null
  echo "$_r"
}

# totals of "tx retries" and "tx failed" over the stations (the access point)
wq_station() {
  if [ -n "$WQ_STATION" ]; then cat "$WQ_STATION" 2>/dev/null
  else "$(command -v iw || echo /mnt/ext/bin/iw)" dev "$IFACE" station dump 2>/dev/null; fi | {
    _rt=0; _fl=0
    while read -r _a _b _v _rest; do
      case "$_a $_b" in
        "tx retries:") case "$_v" in ''|*[!0-9]*) ;; *) _rt=$((_rt + _v)) ;; esac ;;
        "tx failed:") case "$_v" in ''|*[!0-9]*) ;; *) _fl=$((_fl + _v)) ;; esac ;;
      esac
    done
    echo "$_rt $_fl"
  }
}

wq_gateway() {
  while read -r _if _dst _gw _rest; do
    [ "$_dst" = 00000000 ] || continue
    case "$_gw" in ????????) ;; *) continue ;; esac
    printf '%d.%d.%d.%d\n' "0x${_gw#??????}" "0x$(echo "$_gw" | cut -c5-6)" "0x$(echo "$_gw" | cut -c3-4)" "0x${_gw%??????}"
    return 0
  done < /proc/net/route 2>/dev/null
  return 1
}

# packet loss in % over 3 pings to the router (null without a router)
wq_loss() {
  if [ -n "$WQ_PING" ]; then _out=$(cat "$WQ_PING" 2>/dev/null)
  else _gw=$(wq_gateway) || { echo null; return; }; _out=$(ping -c 3 -W 1 -w 4 -q "$_gw" 2>/dev/null); fi
  _p=$(printf '%s\n' "$_out" | sed -n 's/.* \([0-9][0-9]*\)% packet loss.*/\1/p' | head -n 1)
  case "$_p" in ''|*[!0-9]*) echo null ;; *) echo "$_p" ;; esac
}

wq_sample() {
  _now=${WQ_NOW:-$(date +%s)}
  _rssi=$(wq_rssi)
  set -- $(wq_station); _rt=${1:-0}; _fl=${2:-0}
  _prt=""; _pfl=""; [ -r "$STATE" ] && read -r _prt _pfl < "$STATE"
  echo "$_rt $_fl" > "$STATE"
  _drt=0; _dfl=0
  case "$_prt" in ''|*[!0-9]*) ;; *) [ "$_rt" -ge "$_prt" ] && _drt=$((_rt - _prt)) ;; esac
  case "$_pfl" in ''|*[!0-9]*) ;; *) [ "$_fl" -ge "$_pfl" ] && _dfl=$((_fl - _pfl)) ;; esac
  _loss=$(wq_loss)
  echo "$_now $_rssi $_drt $_dfl $_loss" >> "$LOG"
  _n=$(wc -l < "$LOG")
  if [ "$_n" -gt $((MAXLINES + 60)) ]; then tail -n "$MAXLINES" "$LOG" > "$LOG.tmp" && mv -f "$LOG.tmp" "$LOG"; fi
  wq_summary "$_now"
}

wq_summary() {
  _now=${1:-${WQ_NOW:-$(date +%s)}}
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
