#!/bin/sh
# www/cgi-bin/metrics.cgi — Lightweight Prometheus metrics exporter for TECKIN TC100
# Answers GET /cgi-bin/metrics.cgi with Prometheus text format (version 0.0.4).
# Fast path: ash builtins and /proc reading only, minimal subshells and forks.

printf 'Content-Type: text/plain; version=0.0.4; charset=utf-8\r\nCache-Control: no-store\r\n\r\n'

# 1. System uptime
_up=0
[ -r /proc/uptime ] && read -r _up _ < /proc/uptime 2>/dev/null
_up="${_up%%.*}"
case "$_up" in ''|*[!0-9]*) _up=0 ;; esac
printf '# HELP tc100_uptime_seconds Total system uptime in seconds\n# TYPE tc100_uptime_seconds counter\ntc100_uptime_seconds %s\n' "$_up"

# 2. Memory metrics (kB -> bytes)
_mt=0; _mf=0; _ma=0; _mb=0; _mc=0
if [ -r /proc/meminfo ]; then
  while read -r _k _v _rest; do
    case "$_k" in
      MemTotal:)     _mt=$_v ;;
      MemFree:)      _mf=$_v ;;
      MemAvailable:) _ma=$_v ;;
      Buffers:)      _mb=$_v ;;
      Cached:)       _mc=$_v ;;
    esac
  done < /proc/meminfo 2>/dev/null
fi

[ "$_ma" -gt 0 ] 2>/dev/null || _ma=$(( _mf + _mb + _mc ))
printf '# HELP tc100_memory_total_bytes Total system memory\n# TYPE tc100_memory_total_bytes gauge\ntc100_memory_total_bytes %s\n' "$((_mt * 1024))"
printf '# HELP tc100_memory_free_bytes Free system memory\n# TYPE tc100_memory_free_bytes gauge\ntc100_memory_free_bytes %s\n' "$((_mf * 1024))"
printf '# HELP tc100_memory_available_bytes Estimated memory available for starting new applications\n# TYPE tc100_memory_available_bytes gauge\ntc100_memory_available_bytes %s\n' "$((_ma * 1024))"

# 3. CPU Load average
_l1=0; _l5=0; _l15=0
[ -r /proc/loadavg ] && read -r _l1 _l5 _l15 _rest < /proc/loadavg 2>/dev/null
printf '# HELP tc100_load1 1-minute load average\n# TYPE tc100_load1 gauge\ntc100_load1 %s\n' "${_l1:-0}"
printf '# HELP tc100_load5 5-minute load average\n# TYPE tc100_load5 gauge\ntc100_load5 %s\n' "${_l5:-0}"
printf '# HELP tc100_load15 15-minute load average\n# TYPE tc100_load15 gauge\ntc100_load15 %s\n' "${_l15:-0}"

# 4. Network interface stats (wlan0)
_rx_b=0; _tx_b=0; _rx_err=0; _tx_err=0; _rx_drop=0; _tx_drop=0
if [ -r /proc/net/dev ]; then
  while IFS= read -r _l; do
    case "$_l" in
      *wlan0:*|*eth0:*)
        set -- ${_l#*:}
        _rx_b="${1:-0}"; _rx_err="${3:-0}"; _rx_drop="${4:-0}"
        _tx_b="${9:-0}"; _tx_err="${11:-0}"; _tx_drop="${12:-0}"
        break
        ;;
    esac
  done < /proc/net/dev 2>/dev/null
fi

printf '# HELP tc100_network_receive_bytes_total Total received bytes on Wi-Fi\n# TYPE tc100_network_receive_bytes_total counter\ntc100_network_receive_bytes_total %s\n' "$_rx_b"
printf '# HELP tc100_network_transmit_bytes_total Total transmitted bytes on Wi-Fi\n# TYPE tc100_network_transmit_bytes_total counter\ntc100_network_transmit_bytes_total %s\n' "$_tx_b"
printf '# HELP tc100_network_receive_drops_total Total received packets dropped\n# TYPE tc100_network_receive_drops_total counter\ntc100_network_receive_drops_total %s\n' "$_rx_drop"
printf '# HELP tc100_network_transmit_drops_total Total transmitted packets dropped\n# TYPE tc100_network_transmit_drops_total counter\ntc100_network_transmit_drops_total %s\n' "$_tx_drop"

# 5. Wi-Fi Link Quality & Signal
_wq=0; _wl=0
if [ -r /proc/net/wireless ]; then
  while read -r _k _st _lk _lv _rest; do
    [ "$_k" = "wlan0:" ] || continue
    _lk="${_lk%%.*}"; _lv="${_lv%%.*}"
    case "$_lk" in ''|*[!0-9]*) ;; *) _wq=$_lk ;; esac
    case "$_lv" in -[0-9]*|[0-9]*) case "${_lv#-}" in *[!0-9]*) ;; *) _wl=$_lv ;; esac ;; esac
    break
  done < /proc/net/wireless 2>/dev/null
fi

printf '# HELP tc100_wifi_link_quality Wi-Fi link quality score (0-100)\n# TYPE tc100_wifi_link_quality gauge\ntc100_wifi_link_quality %s\n' "$_wq"
printf '# HELP tc100_wifi_signal_dbm Wi-Fi signal level in dBm\n# TYPE tc100_wifi_signal_dbm gauge\ntc100_wifi_signal_dbm %s\n' "$_wl"

# 6. RTSP Viewers (active TCP connections on port 554)
_rtsp_clients=0
if [ -r /proc/net/tcp ]; then
  while read -r _sl _loc _rem _st _rest; do
    [ "$_st" = 01 ] || continue
    _p="${_loc##*:}"
    [ "$_p" = "022A" ] && _rtsp_clients=$((_rtsp_clients + 1))
  done < /proc/net/tcp 2>/dev/null
fi
printf '# HELP tc100_rtsp_viewers_active Current active RTSP clients\n# TYPE tc100_rtsp_viewers_active gauge\ntc100_rtsp_viewers_active %s\n' "$_rtsp_clients"

# 7. Detection States (Motion, Sound, Tamper)
_motion=0; [ -f /tmp/motion_detected ] && _motion=1
_tamper=0; [ -f /tmp/cam_tamper ] && _tamper=1
_vox=0;    [ -f /tmp/vox_state ] && [ "$(cat /tmp/vox_state 2>/dev/null)" = "ON" ] && _vox=1

printf '# HELP tc100_motion_active Binary state of motion detection (1=active)\n# TYPE tc100_motion_active gauge\ntc100_motion_active %s\n' "$_motion"
printf '# HELP tc100_tamper_active Binary state of camera tamper / occlusion detection (1=active)\n# TYPE tc100_tamper_active gauge\ntc100_tamper_active %s\n' "$_tamper"
printf '# HELP tc100_vox_active Binary state of VOX / babyphone detection (1=active)\n# TYPE tc100_vox_active gauge\ntc100_vox_active %s\n' "$_vox"

# 8. Sensor Luminance
_lum=0
if [ -r /tmp/cam_luma ]; then
  read -r _lum < /tmp/cam_luma 2>/dev/null
  case "$_lum" in ''|*[!0-9]*) _lum=0 ;; esac
fi
printf '# HELP tc100_sensor_luma Current ISP scene luminance (0-255)\n# TYPE tc100_sensor_luma gauge\ntc100_sensor_luma %s\n' "$_lum"

# 9. Audio Sound Level (dBFS)
_sound_db=-96
if [ -r /var/run/sound_level ]; then
  _sl_ts=""; _sl_rms=""
  read -r _sl_ts _sl_rms _rest < /var/run/sound_level 2>/dev/null
  case "$_sl_rms" in -[0-9]*|0) _sound_db="$_sl_rms" ;; esac
fi
printf '# HELP tc100_audio_level_dbfs Current microphone audio level in dBFS\n# TYPE tc100_audio_level_dbfs gauge\ntc100_audio_level_dbfs %s\n' "$_sound_db"
