#!/bin/sh
# dash.cgi — raw counters for the dashboard graphs (src/webui/index/47-dashboard.js),
# polled every 5 s while the dashboard is on screen; the page turns them into
# rates (CPU %, Mbit/s). Kept apart from state.cgi on purpose: no func.cgi,
# no command substitution, no pipeline, so a poll starts no process besides
# this shell. Measured on a camera over a kept-alive HTTPS connection: no
# visible change in CPU use at one poll every 5 s (state.cgi: about +6 %).
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n'
_d_cpu="0,0,0,0,0,0,0"
while read -r _k _u _n _s _i _w _q _sq _rest; do
  [ "$_k" = cpu ] && { _d_cpu="$_u,$_n,$_s,$_i,${_w:-0},${_q:-0},${_sq:-0}"; break; }
done < /proc/stat
_d_mt=0; _d_mf=0; _d_mb=0; _d_mc=0
while read -r _k _v _rest; do
  case "$_k" in
    MemTotal:) _d_mt=$_v ;; MemFree:) _d_mf=$_v ;; Buffers:) _d_mb=$_v ;; Cached:) _d_mc=$_v; break ;;
  esac
done < /proc/meminfo
_d_rx=0; _d_tx=0; _d_if=""
while IFS= read -r _l; do
  case "$_l" in
    *wlan0:*|*eth0:*)
      _d_if="${_l%%:*}"; _d_if="${_d_if##* }"
      set -- ${_l#*:}
      _d_rx="${1:-0}"; _d_tx="${9:-0}"
      [ "$_d_if" = wlan0 ] && break ;;
  esac
done < /proc/net/dev
_d_wq=null; _d_wl=null
while read -r _k _st _lk _lv _rest; do
  [ "$_k" = "wlan0:" ] || continue
  _lk="${_lk%%.*}"; _lv="${_lv%%.*}"
  case "$_lk" in ''|*[!0-9]*) ;; *) _d_wq=$_lk ;; esac
  # Realtek drivers give the level either in dBm (negative) or as 0-100.
  case "$_lv" in -[0-9]*|[0-9]*) case "${_lv#-}" in *[!0-9]*) ;; *) _d_wl=$_lv ;; esac ;; esac
done 2>/dev/null < /proc/net/wireless
_d_up=0; read -r _d_up _rest < /proc/uptime; _d_up="${_d_up%%.*}"
_d_l1=0; read -r _d_l1 _d_l5 _d_l15 _rest < /proc/loadavg
# RTSP viewers: established TCP connections to the RTSP port (default 554).
_d_rp=554
while IFS='=' read -r _k _v; do [ "$_k" = PORT ] && { _v="${_v%\"}"; _d_rp="${_v#\"}"; }; done 2>/dev/null < /mnt/config/rtspserver.conf
case "$_d_rp" in ''|*[!0-9]*) _d_rp=554 ;; esac
_d_cl=0
while read -r _sl _loc _rem _st _rest; do
  [ "$_st" = 01 ] || continue
  _p="${_loc##*:}"
  case "$_p" in ''|*[!0-9A-Fa-f]*) continue ;; esac
  [ "$((0x$_p))" = "$_d_rp" ] && _d_cl=$((_d_cl + 1))
done < /proc/net/tcp
_d_sd=""
if [ -r /tmp/sd-health ]; then
  while IFS='=' read -r _k _v; do [ "$_k" = state ] && _d_sd="$_v"; done < /tmp/sd-health
fi
case "$_d_sd" in *[!a-z]*) _d_sd="" ;; esac
printf '{"up":%s,"load":"%s","cpu":[%s],"mem":[%s,%s,%s,%s],"iface":"%s","net":[%s,%s],"wifi":[%s,%s],"rtsp_clients":%s,"sd_health":"%s"}\n' \
  "$_d_up" "$_d_l1" "$_d_cpu" "$_d_mt" "$_d_mf" "$_d_mb" "$_d_mc" "$_d_if" "$_d_rx" "$_d_tx" "$_d_wq" "$_d_wl" "$_d_cl" "$_d_sd"
