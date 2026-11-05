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
# scripts/wifi-signal.sh is the one reader; an unknown value has no sample (no fake 0)
_wq=""; _wl=""
if [ -r /mnt/scripts/wifi-signal.sh ]; then
  . /mnt/scripts/wifi-signal.sh
  wifi_signal_read && { _wq="$WIFI_QUAL"; _wl="$WIFI_DBM"; }
fi

printf '# HELP tc100_wifi_link_quality Wi-Fi link quality score (0-100), no sample when unknown\n# TYPE tc100_wifi_link_quality gauge\n'
[ -n "$_wq" ] && printf 'tc100_wifi_link_quality %s\n' "$_wq"
printf '# HELP tc100_wifi_signal_dbm Wi-Fi signal level in dBm, no sample when unknown\n# TYPE tc100_wifi_signal_dbm gauge\n'
[ -n "$_wl" ] && printf 'tc100_wifi_signal_dbm %s\n' "$_wl"

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

# 10. Video server (tc100_rtsp writes /var/run/tc100_rtsp.stat every 5 s: counts over that interval). No sample when
#     the file is missing or older than 30 s (server stopped).
_st=/var/run/tc100_rtsp.stat
if [ -r "$_st" ] && [ -n "$(find "$_st" -mmin -1 2>/dev/null)" ]; then
  _iv=0; _cap=0; _mb=0; _sb=0; _cl=0; _dr=0
  while read -r _k _v; do
    case "$_v" in ''|*[!0-9]*) continue ;; esac
    case "$_k" in
      interval_s) _iv=$_v ;; captured) _cap=$_v ;; main_bytes) _mb=$_v ;; sub_bytes) _sb=$_v ;;
      clients) _cl=$_v ;; dropped) _dr=$_v ;;
    esac
  done < "$_st"
  [ "$_iv" -gt 0 ] || _iv=5
  printf '# HELP tc100_rtsp_capture_fps Frames captured per second by the video server\n# TYPE tc100_rtsp_capture_fps gauge\ntc100_rtsp_capture_fps %s\n' "$((_cap / _iv))"
  printf '# HELP tc100_rtsp_main_kbps Bit rate of the main stream in kbit/s\n# TYPE tc100_rtsp_main_kbps gauge\ntc100_rtsp_main_kbps %s\n' "$((_mb * 8 / 1000 / _iv))"
  printf '# HELP tc100_rtsp_sub_kbps Bit rate of the sub-stream in kbit/s\n# TYPE tc100_rtsp_sub_kbps gauge\ntc100_rtsp_sub_kbps %s\n' "$((_sb * 8 / 1000 / _iv))"
  printf '# HELP tc100_rtsp_clients_playing RTSP clients receiving a stream\n# TYPE tc100_rtsp_clients_playing gauge\ntc100_rtsp_clients_playing %s\n' "$_cl"
  printf '# HELP tc100_rtsp_dropped_frames Frames skipped for the connected clients since they connected (slow network)\n# TYPE tc100_rtsp_dropped_frames gauge\ntc100_rtsp_dropped_frames %s\n' "$_dr"
fi

# 11. microSD card (scripts read it from /tmp/sd-card, written by v3/linux66-sd/sdinfo-sd.sh)
_sdp=0; _sds=""; _sdf=""
if [ -r /tmp/sd-card ]; then
  while IFS='=' read -r _k _v; do
    case "$_k" in present) _sdp=$_v ;; size_mb) _sds=$_v ;; free_mb) _sdf=$_v ;; esac
  done < /tmp/sd-card
fi
case "$_sdp" in 1) ;; *) _sdp=0 ;; esac
printf '# HELP tc100_sdcard_present 1 when a microSD card is in the slot\n# TYPE tc100_sdcard_present gauge\ntc100_sdcard_present %s\n' "$_sdp"
case "$_sds" in ''|*[!0-9]*) ;; *) [ "$_sdp" = 1 ] && printf '# HELP tc100_sdcard_size_bytes Size of the microSD card\n# TYPE tc100_sdcard_size_bytes gauge\ntc100_sdcard_size_bytes %s\n' "$((_sds * 1048576))" ;; esac
case "$_sdf" in ''|*[!0-9]*) ;; *) [ "$_sdp" = 1 ] && printf '# HELP tc100_sdcard_free_bytes Free space on the microSD card\n# TYPE tc100_sdcard_free_bytes gauge\ntc100_sdcard_free_bytes %s\n' "$((_sdf * 1048576))" ;; esac

# 12. Firmware version (constant 1, the version as a label). No chip temperature: the 6.6 kernel of this firmware
#     has no thermal sensor driver for the AK3918.
_ver=""; [ -r /mnt/VERSION ] && read -r _ver < /mnt/VERSION
_ver=$(printf '%s' "$_ver" | tr -cd 'A-Za-z0-9._-')
printf '# HELP tc100_info Firmware of the camera\n# TYPE tc100_info gauge\ntc100_info{version="%s"} 1\n' "${_ver:-unknown}"
