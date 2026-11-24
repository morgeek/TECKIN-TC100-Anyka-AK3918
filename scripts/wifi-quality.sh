#!/bin/sh
# Wi-Fi quality over time: one sample a minute (signal, transmit retries and failures, packet loss to the router),
# kept in RAM for 24 h, so that bursts of loss (the .24) can be seen and timed instead of guessed.
#   /tmp/wifi-quality.log   "epoch rssi_dbm retries failed loss_pct" (deltas since the previous sample), <= 1440 lines
#   /tmp/wifi-quality       last hour: rssi, rssi_min_1h, rssi_avg_1h, loss_pct_1h, retries_1h, failed_1h, samples_1h
# Read by mqtt-bridge.sh (diag: wifi_loss_pct, wifi_tx_retries, wifi_rssi_min).
# Nothing is written to flash or card. WIFI_QUALITY=1 in boot.conf switches it on (off by default); the housekeeper
# runs "wifi-quality.sh hk" (autorun-linux66.sh) and "wifi-quality.sh run" is the loop of its own without it.
#   wifi-quality.sh sample | summary | hk | run
# Forks a sample: timeout + iw, timeout + ping, two mv = 8 pids with busybox timeout (3 each; 13 with the $(...) subshells, the pipe and awk
# before [wifiq]). The last hour is kept in "$STATE.win" (the lines of the hour only), so the 1440-line log is not
# scanned each minute (`summary` alone still reads the whole log). iw and ping write to "$STATE.iw" / "$STATE.ping",
# read back with `read`: no $(...), no pipe. The sums are shell arithmetic, the same integers the awk gave.
# Test hooks: WQ_LOG, WQ_SUM, WQ_STATE, WQ_WIRELESS, WQ_STATION (a file instead of `iw station dump`), WQ_PING
# (a file instead of ping's output), WQ_ROUTE (a file instead of /proc/net/route), WQ_NOW.
LOG=${WQ_LOG:-/tmp/wifi-quality.log}
SUM=${WQ_SUM:-/tmp/wifi-quality}
STATE=${WQ_STATE:-/tmp/.wifi-quality.prev}
WIN="$STATE.win"
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

# totals of "tx retries" and "tx failed" over the stations (the access point), and the averaged signal of the access
# point's beacons ("beacon signal avg", dBm; "-" when there is none). Not "signal avg": with rtl8xxxu it read -13 dBm on
# the .24 while beacons, /proc and the MCS 2 rate all said about -50 (tester, 2026-11-04). iw and ping run under
# timeout: a sample stuck in the Wi-Fi driver kept the housekeeper job "running" for hours (.11, 2026-11-03).
# Sets _rt _fl _sg (no subshell). iw's path is searched in PATH by hand (was $(command -v iw)).
wq_station() {
  _rt=0; _fl=0; _sg=-
  _wq_f="${WQ_STATION:-}"
  if [ -z "$_wq_f" ]; then
    _wq_f="$STATE.iw"
    _wq_iw=/mnt/ext/bin/iw
    if [ ! -x "$_wq_iw" ]; then
      _wq_ifs=$IFS; IFS=:
      for _wq_d in $PATH; do
        [ -x "$_wq_d/iw" ] && { _wq_iw="$_wq_d/iw"; break; }
      done
      IFS=$_wq_ifs
    fi
    timeout 5 "$_wq_iw" dev "$IFACE" station dump > "$_wq_f" 2>/dev/null
  fi
  [ -r "$_wq_f" ] || return 0
  while read -r _a _b _v _rest; do
    case "$_a $_b" in
      "tx retries:") case "$_v" in ''|*[!0-9]*) ;; *) _rt=$((_rt + _v)) ;; esac ;;
      "tx failed:") case "$_v" in ''|*[!0-9]*) ;; *) _fl=$((_fl + _v)) ;; esac ;;
      "beacon signal") [ "$_v" = "avg:" ] && case "${_rest%% *}" in
          -[0-9]|-[0-9][0-9]|-10[0-9]|-110) [ "$_sg" = - ] && _sg=${_rest%% *} ;; esac ;;
    esac
  done < "$_wq_f"
  return 0
}

# the default gateway as a dotted quad: printed, or with "var" left in _wq_gw (no subshell)
wq_gateway() {
  while read -r _if _dst _gw _rest; do
    [ "$_dst" = 00000000 ] || continue
    case "$_gw" in ????????) ;; *) continue ;; esac
    # bytes 3-4 and 5-6 by expansion, not two $(echo | cut): six forks a minute less
    _g3=${_gw#????}; _g3=${_g3%??}; _g2=${_gw#??}; _g2=${_g2%????}
    _wq_gw="$((0x${_gw#??????})).$((0x$_g3)).$((0x$_g2)).$((0x${_gw%??????}))"
    [ "${1:-}" = var ] || echo "$_wq_gw"
    return 0
  done < "${WQ_ROUTE:-/proc/net/route}" 2>/dev/null
  return 1
}

# packet loss in % over 3 pings to the router (null without a router)
wq_loss() {
  if [ -n "$WQ_PING" ]; then _wq_pf="$WQ_PING"
  else
    wq_gateway var || { _wq_loss_val=null; [ "${1:-}" = var ] || echo null; return; }
    _wq_pf="$STATE.ping"
    timeout 8 ping -c 3 -W 1 -w 4 -q "$_wq_gw" > "$_wq_pf" 2>/dev/null
  fi
  # the digits just before the first "% packet loss", line by line (was a subshell with cat / ping)
  _p=
  if [ -r "$_wq_pf" ]; then
    while IFS= read -r _l || [ -n "$_l" ]; do
      case "$_l" in *"% packet loss"*) _p=${_l%%"% packet loss"*}; _p=${_p##*[!0-9]}; break ;; esac
    done < "$_wq_pf"
  fi
  case "$_p" in ''|*[!0-9]*) _wq_loss_val=null ;; *) _wq_loss_val="$_p" ;; esac
  [ "${1:-}" = var ] || echo "$_wq_loss_val"
}

# _d = $1 as a decimal integer: no leading zeros ($(( )) would read 08 as an invalid octal), the sign kept
_wq_dec() {
  _d="$1"; _dn=
  case "$_d" in -*) _dn=-; _d=${_d#-} ;; esac
  while :; do
    case "$_d" in 0?*) _d=${_d#0} ;; *) break ;; esac
  done
  _d="$_dn$_d"
}

# one log line "epoch rssi retries failed loss" into the sums of the hour (awk of the old wq_summary, no fork);
# the lines of the hour are collected in _wq_kept (the next window file)
_wq_acc() {
  _wq_last="$2"
  case "$1" in ''|*[!0-9]*) return 0 ;; esac
  [ "$1" -ge "$_wq_since" ] || return 0
  _wq_n=$((_wq_n + 1))
  _wq_kept="$_wq_kept$1 $2 $3 $4 $5
"
  if [ "$2" != null ]; then
    case "$2" in ''|*[!0-9-]*) _d=0 ;; *) _wq_dec "$2" ;; esac
    _wq_s=$((_wq_s + _d)); _wq_nr=$((_wq_nr + 1))
    if [ -z "$_wq_min" ] || [ "$_d" -lt "$_wq_min" ]; then _wq_min="$_d"; fi
  fi
  case "$3" in ''|*[!0-9]*) ;; *) _wq_dec "$3"; _wq_rt=$((_wq_rt + _d)) ;; esac
  case "$4" in ''|*[!0-9]*) ;; *) _wq_dec "$4"; _wq_fl=$((_wq_fl + _d)) ;; esac
  if [ "$5" != null ]; then
    case "$5" in ''|*[!0-9]*) ;; *) _wq_dec "$5"; _wq_ls=$((_wq_ls + _d)) ;; esac
    _wq_nl=$((_wq_nl + 1))
  fi
}

_wq_reset() {
  _wq_last=; _wq_n=0; _wq_s=0; _wq_nr=0; _wq_min=; _wq_rt=0; _wq_fl=0; _wq_ls=0; _wq_nl=0; _wq_kept=
  _wq_since=$((_now - 3600))
}

# the whole log through _wq_acc (the standalone `summary`, the first sample after an upgrade or a lost window)
_wq_fold_log() {
  [ -r "$LOG" ] || return 0
  while read -r _e _r _t _f _l _x || [ -n "$_e" ]; do
    _wq_acc "$_e" "$_r" "$_t" "$_f" "$_l"
  done < "$LOG"
}

# the output file, from the sums of _wq_acc: one write, then mv (a reader never sees half of it)
_wq_emit() {
  _lo=null; [ "$_wq_nl" -gt 0 ] && _lo=$(( (2 * _wq_ls + _wq_nl) / (2 * _wq_nl) ))
  _av=null; [ "$_wq_nr" -gt 0 ] && _av=$((_wq_s / _wq_nr))
  printf 'rssi=%s\nrssi_min_1h=%s\nrssi_avg_1h=%s\nloss_pct_1h=%s\nretries_1h=%d\nfailed_1h=%d\nsamples_1h=%d\n' \
    "${_wq_last:-null}" "${_wq_min:-null}" "$_av" "$_lo" "$_wq_rt" "$_wq_fl" "$_wq_n" > "$SUM.tmp" && mv -f "$SUM.tmp" "$SUM"
}

wq_sample() {
  _wq_now
  wq_station; _rt=${_rt:-0}; _fl=${_fl:-0}; _sg=${_sg:--}
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
  # the window of the last hour is only good with the log it was made with
  _wq_win=0; [ -r "$WIN" ] && [ -r "$LOG" ] && _wq_win=1
  echo "$_now $_rssi $_drt $_dfl $_loss" >> "$LOG"
  case "$_pln" in
    ''|*[!0-9]*)
      _n=0; _wq_win=0
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
  _wq_reset
  if [ "$_wq_win" = 1 ]; then
    while read -r _e _r _t _f _l _x || [ -n "$_e" ]; do
      _wq_acc "$_e" "$_r" "$_t" "$_f" "$_l"
    done < "$WIN"
    _wq_acc "$_now" "$_rssi" "$_drt" "$_dfl" "$_loss"
  else
    _wq_fold_log
  fi
  printf '%s' "$_wq_kept" > "$WIN"
  _wq_emit
}

wq_summary() {
  if [ -n "${1:-}" ]; then _now="$1"; else _wq_now; fi
  [ -r "$LOG" ] || return 0
  _wq_reset
  _wq_fold_log
  _wq_emit
}

case "$1" in
  sample) wq_sample ;;
  summary) wq_summary ;;
  hk) wq_sample ;;
  run) while :; do wq_sample; sleep 60; done ;;
  *) echo "usage: $0 sample|summary|hk|run" >&2; exit 2 ;;
esac
