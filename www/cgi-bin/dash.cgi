#!/bin/sh
# dash.cgi — raw counters for the dashboard graphs (src/webui/index/47-dashboard.js),
# polled every 5 s while the dashboard is on screen; the page turns them into
# rates (CPU %, Mbit/s). Kept apart from state.cgi on purpose: no func.cgi,
# no command substitution, no pipeline, so a poll starts no process besides
# this shell. Measured on a camera over a kept-alive connection: no
# visible change in CPU use at one poll every 5 s (state.cgi: about +6 %).
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n'
_d_cpu="0,0,0,0,0,0,0"
while read -r _k _u _n _s _i _w _q _sq _rest; do
  [ "$_k" = cpu ] && { _d_cpu="$_u,$_n,$_s,$_i,${_w:-0},${_q:-0},${_sq:-0}"; break; }
done < /proc/stat
# RAM: one definition everywhere, available = MemAvailable, used = MemTotal - MemAvailable
_d_mt=0; _d_ma=0
while read -r _k _v _rest; do
  case "$_k" in
    MemTotal:) _d_mt=$_v ;; MemAvailable:) _d_ma=$_v; break ;;
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
if [ -r /mnt/scripts/wifi-signal.sh ]; then
  . /mnt/scripts/wifi-signal.sh
  wifi_signal_read && { _d_wq="${WIFI_QUAL:-null}"; _d_wl="${WIFI_DBM:-null}"; }
fi
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
# Frame rate the video server really encodes (both streams, tc100_rtsp -f), in tenths of fps over its last 5 s:
# /var/run/tc100_rtsp.stat ("captured" frames in "interval_s"), only while tc100_rtsp runs (its pid alive). The low-light
# rate, the idle rate and the night switch change it without touching the settings (owner 2026-11-06: the dashboard
# showed 25 fps while the stream was at 10).
_d_vf=null; _d_vi=0; _d_vc=""; _d_vp=""
read -r _d_vp _rest 2>/dev/null < /var/run/v4l2rtspserver.pid
case "$_d_vp" in ''|*[!0-9]*) ;; *)
  if [ -d "/proc/$_d_vp" ] && [ -r /var/run/tc100_rtsp.stat ]; then
    while read -r _k _v; do
      case "$_k" in interval_s) _d_vi=$_v ;; captured) _d_vc=$_v ;; esac
    done < /var/run/tc100_rtsp.stat
    case "$_d_vi" in ''|*[!0-9]*) ;; *)
      case "$_d_vc" in ''|*[!0-9]*) ;; *) [ "$_d_vi" -gt 0 ] && _d_vf=$((_d_vc * 10 / _d_vi)) ;; esac ;;
    esac
  fi ;;
esac
printf '{"up":%s,"load":"%s","cpu":[%s],"mem":[%s,%s],"iface":"%s","net":[%s,%s],"wifi":[%s,%s],"rtsp_clients":%s,"sd_health":"%s","vfps":%s}\n' \
  "$_d_up" "$_d_l1" "$_d_cpu" "$_d_mt" "$_d_ma" "$_d_if" "$_d_rx" "$_d_tx" "$_d_wq" "$_d_wl" "$_d_cl" "$_d_sd" "$_d_vf"
