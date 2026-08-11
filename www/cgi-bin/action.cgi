#!/bin/sh

. /mnt/www/cgi-bin/func.cgi
. /mnt/scripts/common_functions.sh
. /mnt/scripts/event-logger.sh

export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'

# Must stay in sync with WIFI_CONFIG in autorun.sh — that is the file passed to
# `wpa_supplicant -c`, so anything written elsewhere is ignored at boot and by
# `wpa_cli reconfigure`.
WIFI_CONFIG_PATH="/mnt/wpa_supplicant.conf"

# Override install_config to use caching (skips .dist→.conf copy when .conf is fresh)
install_config() {
  install_config_cached "$@"
}

case "$F_cmd" in
  reboot|shutdown) rate_limit_check 3 300 ;;
  *) rate_limit_check 20 60 ;;
esac

# CSRF: enforce the per-boot token on state-changing (POST) requests, matching
# scripts.cgi / configeditor.cgi / config_exchange.cgi. Safe methods (GET/HEAD)
# pass through untouched, so read-style action.cgi calls still work. state.cgi
# guarantees the token is delivered to the client, so this cannot lock the UI
# out. Must run BEFORE any header output.
csrf_guard

# Set content type based on requested format
if wants_json_response; then
  echo "Content-type: application/json"
else
  echo "Content-type: text/html"
fi
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

# Debounce expensive service restarts to avoid restart storms when multiple
# settings are applied in quick succession from the web UI.
schedule_service_restart() {
  service_script="$1"
  delay_seconds="${2:-2}"
  lock_dir="/tmp/$(basename "$service_script").restart.pending"

  if [ ! -x "$service_script" ]; then
    return 0
  fi
  if ! mkdir "$lock_dir" 2>/dev/null; then
    # Clear stale lock if older than 3× the expected delay (restart hung or crashed).
    _lock_stale_threshold=$(( delay_seconds * 3 ))
    if [ -n "$(find "$lock_dir" -maxdepth 0 -mmin +"$(( _lock_stale_threshold / 60 + 1 ))" 2>/dev/null)" ]; then
      rmdir "$lock_dir" 2>/dev/null || true
      mkdir "$lock_dir" 2>/dev/null || return 0
    else
      return 0
    fi
  fi

  (
    sleep "$delay_seconds"
    rmdir "$lock_dir" >/dev/null 2>&1 || true
    restart_service_if_need "$service_script"
  ) >/dev/null 2>&1 &
}

schedule_rtsp_restart() {
  schedule_service_restart /mnt/controlscripts/rtsp-h26x 2
}

schedule_onvif_restart() {
  schedule_service_restart /mnt/controlscripts/onvif 2
}

normalize_bool() {
  case "$1" in
    1|true|on|yes|enabled)
      echo 1
      ;;
    *)
      echo 0
      ;;
  esac
}

sanitize_int_range() {
  value="$1"
  min="$2"
  max="$3"
  fallback="$4"

  case "$value" in
    ''|*[!0-9]*)
      value="$fallback"
      ;;
  esac

  if [ "$value" -lt "$min" ]; then
    value="$min"
  fi
  if [ "$value" -gt "$max" ]; then
    value="$max"
  fi
  echo "$value"
}

# Fork-free epoch — sets now_ts via /proc/stat btime + /proc/uptime.
# btime is cached after first call.
_AC_BTIME=0
_ac_now() {
  if [ "$_AC_BTIME" -le 0 ]; then
    while read -r _k _v _; do
      [ "$_k" = "btime" ] && _AC_BTIME="$_v" && break
    done < /proc/stat
  fi
  read -r _ac_up _ < /proc/uptime
  now_ts=$((_AC_BTIME + ${_ac_up%.*}))
  [ "$now_ts" -gt 0 ] || now_ts=0
}

align_up_to_multiple() {
  value="$1"
  multiple="$2"
  fallback="$3"

  case "$value" in
    ''|*[!0-9]*) value="$fallback" ;;
  esac
  case "$multiple" in
    ''|*[!0-9]*|0) multiple=1 ;;
  esac

  if [ $((value % multiple)) -ne 0 ]; then
    value=$(( ((value + multiple - 1) / multiple) * multiple ))
  fi
  echo "$value"
}

sanitize_video_codec() {
  case "$1" in
    0|2) echo "$1" ;;
    *) echo "0" ;;
  esac
}

sanitize_video_brmode() {
  case "$1" in
    0|1) echo "$1" ;;
    *) echo "1" ;;
  esac
}

sanitize_video_smartmode() {
  case "$1" in
    0|1|2) echo "$1" ;;
    *) echo "1" ;;
  esac
}

sanitize_weekday_expr() {
  case "$1" in
    '*'|0|1|2|3|4|5|6|1-5|0,6)
      echo "$1"
      ;;
    *)
      echo "*"
      ;;
  esac
}

sanitize_codec_profile_for_codec() {
  codec="$1"
  profile="$2"
  stream_index="$3"

  case "$codec" in
    0)
      case "$profile" in
        0|1|2) echo "$profile" ;;
        *)
          if [ "$stream_index" = "0" ]; then
            echo "1"
          else
            echo "0"
          fi
          ;;
      esac
      ;;
    2)
      case "$profile" in
        3|4) echo "$profile" ;;
        *) echo "3" ;;
      esac
      ;;
    *)
      if [ "$stream_index" = "0" ]; then
        echo "1"
      else
        echo "0"
      fi
      ;;
  esac
}

normalize_stream_geometry() {
  raw_width="$1"
  raw_height="$2"
  raw_codec="$3"
  fallback_width="$4"
  fallback_height="$5"

  width="$(sanitize_int_range "$raw_width" 160 1920 "$fallback_width")"
  height="$(sanitize_int_range "$raw_height" 120 1080 "$fallback_height")"
  codec="$(sanitize_video_codec "$raw_codec")"

  # H265 on this platform is unstable with odd/un-aligned dimensions.
  if [ "$codec" = "2" ]; then
    width="$(align_up_to_multiple "$width" 16 "$fallback_width")"
    height="$(align_up_to_multiple "$height" 8 "$fallback_height")"
  fi

  NORMALIZED_STREAM_WIDTH="$width"
  NORMALIZED_STREAM_HEIGHT="$height"
  NORMALIZED_STREAM_CODEC="$codec"
}

apply_web_mode_async() {
  mode="$1"
  (
    sleep 1
    killall lighttpd >/dev/null 2>&1 || true
    killall httpd >/dev/null 2>&1 || true
    if [ "$mode" != "off" ]; then
      if [ -x /mnt/config/autostart/02_system-webserver ]; then
        /mnt/config/autostart/02_system-webserver >/dev/null 2>&1 || true
      else
        http_server on >/dev/null 2>&1 || true
      fi
    fi
  ) >/dev/null 2>&1 &
}

security_hardening_enabled() {
  hardening=0
  if [ -f /mnt/config/boot.conf ]; then
    hardening="$(awk -F= '/^SECURITY_HARDENING_MODE=/{print $2; exit}' /mnt/config/boot.conf 2>/dev/null)"
  fi
  case "$hardening" in
    1|true|on|yes|enabled) return 0 ;;
    *) return 1 ;;
  esac
}

PTT_VOLUME_FILE="/mnt/config/pttvolume.conf"
PTT_LAST_PCM_FILE="/tmp/ptt-last.pcm"
PTT_PCM_PLAYBACK_BIN="/usr/bin/ak_ao_demo"
PTT_WAV_PLAYBACK_BIN="/mnt/bin/audioplay"

ptt_backend_status() {
  if [ -x "$PTT_PCM_PLAYBACK_BIN" ]; then
    if wants_json_response; then
      json_body_ok "OK"
    else
      echo "OK"
    fi
  else
    if wants_json_response; then
      json_body_err "PTT_BIN_MISSING" "PTT_BIN_MISSING"
    else
      echo "PTT_BIN_MISSING"
    fi
  fi
}

read_ptt_volume() {
  ptt_vol_val="$(head -n1 "$PTT_VOLUME_FILE" 2>/dev/null | tr -d '[:space:]')"
  volume="$(sanitize_int_range "$ptt_vol_val" 0 100 90)"
  if wants_json_response; then
    json_body_ok "$volume"
  else
    echo "$volume"
  fi
}

ptt_volume_to_ak() {
  ptt_ui_volume="$(sanitize_int_range "$1" 0 100 90)"
  echo $(( (ptt_ui_volume * 6 + 50) / 100 ))
}

resolve_audio_test_source() {
  for candidate in /mnt/config/audio-test.wav /mnt/config/ptt-test.wav "$PTT_LAST_PCM_FILE"; do
    [ -r "$candidate" ] || continue
    echo "$candidate"
    return 0
  done

  latest_candidate=""
  for candidate in /tmp/pttaudio_*.pcm /tmp/pttaudio_*.wav; do
    [ -r "$candidate" ] || continue
    latest_candidate="$candidate"
  done

  if [ -n "$latest_candidate" ]; then
    echo "$latest_candidate"
    return 0
  fi

  return 1
}

play_audio_test_source() {
  audio_source="$1"
  audio_volume="$(sanitize_int_range "$2" 0 100 90)"

  if [ -z "$audio_source" ] || [ ! -r "$audio_source" ]; then
    if wants_json_response; then
      json_body_err "AUDIO_TEST_FAILED" "no readable source file. Upload audio first (PTT) or provide a valid path."
    else
      echo "Audio test failed: no readable source file. Upload audio first (PTT) or provide a valid path."
    fi
    return 1
  fi

  case "$audio_source" in
    *.pcm)
      if [ ! -x "$PTT_PCM_PLAYBACK_BIN" ]; then
        if wants_json_response; then
          json_body_err "AUDIO_TEST_FAILED" "PCM playback backend is missing on the camera."
        else
          echo "Audio test failed: PCM playback backend is missing on the camera."
        fi
        return 1
      fi
      ak_volume="$(ptt_volume_to_ak "$audio_volume")"
      /mnt/bin/busybox nohup "$PTT_PCM_PLAYBACK_BIN" 8000 1 "$audio_source" "$ak_volume" > /dev/null 2>&1 &
      if wants_json_response; then
        json_body_ok "Playing $audio_source at volume $audio_volume (PCM)"
      else
        echo "Play $audio_source at volume $audio_volume (PCM)"
      fi
      return 0
      ;;
    *.wav)
      if [ ! -x "$PTT_WAV_PLAYBACK_BIN" ]; then
        if wants_json_response; then
          json_body_err "AUDIO_TEST_FAILED" "WAV playback backend is missing on the camera."
        else
          echo "Audio test failed: WAV playback backend is missing on the camera."
        fi
        return 1
      fi
      /mnt/bin/busybox nohup "$PTT_WAV_PLAYBACK_BIN" "$audio_source" "$audio_volume" > /dev/null 2>&1 &
      if wants_json_response; then
        json_body_ok "Playing $audio_source at volume $audio_volume (WAV)"
      else
        echo "Play $audio_source at volume $audio_volume (WAV)"
      fi
      return 0
      ;;
    *)
      if wants_json_response; then
        json_body_err "AUDIO_TEST_FAILED" "unsupported source format: $audio_source"
      else
        echo "Audio test failed: unsupported source format: $audio_source"
      fi
      return 1
      ;;
  esac
}


cron_busybox_bin() {
  if [ -x /mnt/bin/busybox ]; then
    echo /mnt/bin/busybox
    return 0
  fi
  if [ -x /bin/busybox ]; then
    echo /bin/busybox
    return 0
  fi
  echo busybox
}

ensure_cron_root_template() {
  cron_root="/mnt/config/cron/crontabs/root"
  cron_periodic="/mnt/config/cron/periodic"
  cron_bb="$(cron_busybox_bin)"

  mkdir -p /mnt/config/cron/crontabs >/dev/null 2>&1 || true
  mkdir -p "${cron_periodic}/15min" \
           "${cron_periodic}/hourly" \
           "${cron_periodic}/daily" \
           "${cron_periodic}/weekly" \
           "${cron_periodic}/monthly" >/dev/null 2>&1 || true

  if [ ! -f "$cron_root" ]; then
    cat > "$cron_root" <<EOF
# min   hour    day     month   weekday command
*/15    *       *       *       *       ${cron_bb} run-parts ${cron_periodic}/15min
0       *       *       *       *       ${cron_bb} run-parts ${cron_periodic}/hourly
0       2       *       *       *       ${cron_bb} run-parts ${cron_periodic}/daily
0       3       *       *       6       ${cron_bb} run-parts ${cron_periodic}/weekly
0       5       1       *       *       ${cron_bb} run-parts ${cron_periodic}/monthly
EOF
  fi
}

sync_managed_reboot_cron() {
  schedule_enable="$1"
  schedule_minute="$2"
  schedule_hour="$3"
  schedule_weekday="$4"
  cron_root="/mnt/config/cron/crontabs/root"
  _ac_now; tmp_file="/tmp/root.crontab.$$.$now_ts"

  ensure_cron_root_template

  awk '
    BEGIN { skip=0 }
    /^# BEGIN TC100 MANAGED REBOOT$/ { skip=1; next }
    /^# END TC100 MANAGED REBOOT$/ { skip=0; next }
    skip==0 { print }
  ' "$cron_root" > "$tmp_file" 2>/dev/null || cp "$cron_root" "$tmp_file"

  {
    echo "# BEGIN TC100 MANAGED REBOOT"
    if [ "$schedule_enable" = "1" ]; then
      echo "${schedule_minute} ${schedule_hour} * * ${schedule_weekday} /sbin/reboot >/dev/null 2>&1"
    else
      echo "# disabled"
    fi
    echo "# END TC100 MANAGED REBOOT"
  } >> "$tmp_file"

  mv "$tmp_file" "$cron_root"
}

restart_crond_if_enabled() {
  crond_enable="$1"
  cron_bb="$(cron_busybox_bin)"

  if [ "$crond_enable" = "1" ]; then
    killall crond >/dev/null 2>&1 || true
    "$cron_bb" crond -c /mnt/config/cron/crontabs >/dev/null 2>&1 || true
  fi
}

ensure_autostart_script() {
  script_name="$1"
  script_path="/mnt/controlscripts/$script_name"
  autostart_dir="/mnt/config/autostart"
  autostart_file="$autostart_dir/$script_name"

  case "$script_name" in
    ''|*[!A-Za-z0-9._-]*)
      return 1
      ;;
  esac

  if [ ! -x "$script_path" ]; then
    return 1
  fi

  mkdir -p "$autostart_dir" >/dev/null 2>&1 || true
  printf "#!/bin/sh\nsh \"%s\"\n" "$script_path" > "$autostart_file" || return 1
  chmod +x "$autostart_file" >/dev/null 2>&1 || true
  return 0
}

LOG_SUMMARY_TAIL_LINES=40
LOG_DMESG_TAIL_LINES=200
LOG_VIDEO_TAIL_LINES=256

emit_log_tail_dir() {
  log_dir="$1"
  heading="$2"
  tail_lines="$3"
  found=0

  for log_file in "$log_dir"/*; do
    [ -f "$log_file" ] || continue
    if [ "$found" -eq 0 ]; then
      echo "$heading<br/>"
      found=1
    fi
    echo "--- $(basename "$log_file") ---<br/>"
    tail -n "$tail_lines" "$log_file" 2>/dev/null || true
    echo "<br/>"
  done

  if [ "$found" -eq 0 ]; then
    echo "$heading<br/>No log files found.<br/>"
  fi
}

clear_log_dir_files() {
  log_dir="$1"
  cleared=0

  for log_file in "$log_dir"/*; do
    [ -f "$log_file" ] || continue
    : > "$log_file" 2>/dev/null || true
    cleared=$((cleared + 1))
  done

  echo "$cleared"
}

SNAPSHOT_DIR="/mnt/config/snapshots"
KNOWN_GOOD_RTSP_CONF="${SNAPSHOT_DIR}/rtspserver.known-good.conf"
KNOWN_GOOD_STREAM_CONF="${SNAPSHOT_DIR}/stream.known-good.conf"
PRECHANGE_RTSP_CONF=""
PRECHANGE_STREAM_CONF=""
PRECHANGE_RTSP_WAS_RUNNING=0
PRECHANGE_ONVIF_WAS_RUNNING=0

read_kv_or_default() {
  file_path="$1"
  key="$2"
  default_value="$3"
  value="$(awk -F= -v k="$key" '$1 == k { print substr($0, index($0, "=") + 1); found=1; exit } END { if (!found) exit 1 }' "$file_path" 2>/dev/null)"
  if [ $? -eq 0 ]; then
    echo "$value"
  else
    echo "$default_value"
  fi
}

apply_low_cpu_background_defaults() {
  install_config /mnt/config/mqtt.conf

  mqtt_health_interval="$(sanitize_int_range "$(read_kv_or_default /mnt/config/mqtt.conf MQTT_HEALTH_INTERVAL_SECONDS 120)" 10 86400 120)"
  if [ "$mqtt_health_interval" -lt 120 ]; then
    rewrite_config /mnt/config/mqtt.conf MQTT_HEALTH_INTERVAL_SECONDS 120
  fi

  mqtt_slow_ttl="$(sanitize_int_range "$(read_kv_or_default /mnt/config/mqtt.conf MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS 180)" 10 86400 180)"
  if [ "$mqtt_slow_ttl" -lt 180 ]; then
    rewrite_config /mnt/config/mqtt.conf MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS 180
  fi

  if [ ! -f /mnt/config/sound_detection.conf ]; then
    {
      echo "ENABLE=0"
      echo "THRESHOLD=1500"
      echo "INTERVAL=10"
    } > /mnt/config/sound_detection.conf
  fi

  sound_interval="$(sanitize_int_range "$(read_kv_or_default /mnt/config/sound_detection.conf INTERVAL 10)" 1 300 10)"
  if [ "$sound_interval" -lt 10 ]; then
    rewrite_config /mnt/config/sound_detection.conf INTERVAL 10
  fi
}

write_stream_state_snapshot() {
  output_file="$1"
  reason="$2"
  install_config /mnt/config/boot.conf
  install_config /mnt/config/service_trim.conf
  _ac_now

  rtsp_substream="$(read_kv_or_default /mnt/config/boot.conf RTSP_SUBSTREAM 1)"
  rtsp_audio="$(read_kv_or_default /mnt/config/boot.conf RTSP_AUDIO 1)"
  onvif_policy="$(read_kv_or_default /mnt/config/boot.conf ONVIF_STREAM_POLICY main-primary)"
  low_cpu_profile="$(read_kv_or_default /mnt/config/boot.conf LOW_CPU_PROFILE 0)"
  low_ram_profile="$(read_kv_or_default /mnt/config/boot.conf LOW_RAM_PROFILE 0)"
  mem_guard_enable="$(read_kv_or_default /mnt/config/boot.conf MEM_GUARD_ENABLE 0)"
  low_cpu_disable_substream="$(read_kv_or_default /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0)"
  low_cpu_disable_audio="$(read_kv_or_default /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO 0)"
  low_cpu_disable_motion="$(read_kv_or_default /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION 0)"
  low_cpu_disable_osd="$(read_kv_or_default /mnt/config/boot.conf LOW_CPU_DISABLE_OSD 0)"
  low_cpu_disable_jpeg="$(read_kv_or_default /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG 0)"
  service_trim="$(read_kv_or_default /mnt/config/service_trim.conf SERVICE_TRIM "$(read_kv_or_default /mnt/config/boot.conf SERVICE_TRIM 0)")"

  {
    echo "TS=$now_ts"
    echo "REASON=$reason"
    echo "RTSP_SUBSTREAM=$rtsp_substream"
    echo "RTSP_AUDIO=$rtsp_audio"
    echo "ONVIF_STREAM_POLICY=$onvif_policy"
    echo "LOW_CPU_PROFILE=$low_cpu_profile"
    echo "LOW_RAM_PROFILE=$low_ram_profile"
    echo "MEM_GUARD_ENABLE=$mem_guard_enable"
    echo "LOW_CPU_DISABLE_SUBSTREAM=$low_cpu_disable_substream"
    echo "LOW_CPU_DISABLE_AUDIO=$low_cpu_disable_audio"
    echo "LOW_CPU_DISABLE_MOTION=$low_cpu_disable_motion"
    echo "LOW_CPU_DISABLE_OSD=$low_cpu_disable_osd"
    echo "LOW_CPU_DISABLE_JPEG=$low_cpu_disable_jpeg"
    echo "SERVICE_TRIM=$service_trim"
  } > "$output_file"
}

apply_stream_state_snapshot() {
  state_file="$1"
  [ -f "$state_file" ] || return 1
  install_config /mnt/config/boot.conf
  install_config /mnt/config/service_trim.conf

  rtsp_substream="$(read_kv_or_default "$state_file" RTSP_SUBSTREAM 1)"
  rtsp_audio="$(read_kv_or_default "$state_file" RTSP_AUDIO 1)"
  onvif_policy="$(read_kv_or_default "$state_file" ONVIF_STREAM_POLICY main-primary)"
  low_cpu_profile="$(read_kv_or_default "$state_file" LOW_CPU_PROFILE 0)"
  low_ram_profile="$(read_kv_or_default "$state_file" LOW_RAM_PROFILE 0)"
  mem_guard_enable="$(read_kv_or_default "$state_file" MEM_GUARD_ENABLE 0)"
  low_cpu_disable_substream="$(read_kv_or_default "$state_file" LOW_CPU_DISABLE_SUBSTREAM 0)"
  low_cpu_disable_audio="$(read_kv_or_default "$state_file" LOW_CPU_DISABLE_AUDIO 0)"
  low_cpu_disable_motion="$(read_kv_or_default "$state_file" LOW_CPU_DISABLE_MOTION 0)"
  low_cpu_disable_osd="$(read_kv_or_default "$state_file" LOW_CPU_DISABLE_OSD 0)"
  low_cpu_disable_jpeg="$(read_kv_or_default "$state_file" LOW_CPU_DISABLE_JPEG 0)"
  service_trim="$(read_kv_or_default "$state_file" SERVICE_TRIM 0)"

  rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
  rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
  rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$onvif_policy"
  rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE "$low_cpu_profile"
  rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE "$low_ram_profile"
  rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE "$mem_guard_enable"
  rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM "$low_cpu_disable_substream"
  rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO "$low_cpu_disable_audio"
  rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION "$low_cpu_disable_motion"
  rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_OSD "$low_cpu_disable_osd"
  rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG "$low_cpu_disable_jpeg"
  rewrite_config /mnt/config/boot.conf SERVICE_TRIM "$service_trim"
  rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM "$service_trim"
  if [ "$low_cpu_profile" = "1" ]; then
    apply_low_cpu_background_defaults
  fi
}

capture_prechange_stream_snapshot() {
  _ac_now
  PRECHANGE_RTSP_CONF="/tmp/rtspserver.pre.$$.${now_ts}.conf"
  PRECHANGE_STREAM_CONF="/tmp/stream.pre.$$.${now_ts}.conf"
  PRECHANGE_RTSP_WAS_RUNNING=0
  PRECHANGE_ONVIF_WAS_RUNNING=0

  cp /mnt/config/rtspserver.conf "$PRECHANGE_RTSP_CONF" >/dev/null 2>&1 || true
  write_stream_state_snapshot "$PRECHANGE_STREAM_CONF" "prechange"

  if [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x status >/dev/null 2>&1; then
    PRECHANGE_RTSP_WAS_RUNNING=1
  fi
  if [ -x /mnt/controlscripts/onvif ] && /mnt/controlscripts/onvif status >/dev/null 2>&1; then
    PRECHANGE_ONVIF_WAS_RUNNING=1
  fi
}

restart_stream_services_for_validation() {
  if [ "$PRECHANGE_RTSP_WAS_RUNNING" = "1" ]; then
    restart_service_if_need /mnt/controlscripts/rtsp-h26x
  fi
  if [ "$PRECHANGE_ONVIF_WAS_RUNNING" = "1" ]; then
    restart_service_if_need /mnt/controlscripts/onvif
  fi
}

sync_memory_guard_service_with_config() {
  if [ ! -x /mnt/controlscripts/memory-guard ]; then
    return 0
  fi

  mem_guard_enable="$(read_kv_or_default /mnt/config/boot.conf MEM_GUARD_ENABLE 0)"
  if [ "$mem_guard_enable" = "1" ]; then
    /mnt/controlscripts/memory-guard start >/dev/null 2>&1 || true
  else
    /mnt/controlscripts/memory-guard stop >/dev/null 2>&1 || true
  fi
}

stop_trimmed_runtime_services() {
  for svc in ftp-server telnet-server motion-detection recording timelapse auto-night-detection front-led night-mode network-monitor; do
    if [ -x "/mnt/controlscripts/$svc" ]; then
      /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
    fi
  done
}

rtsp_quick_health_check() {
  if [ ! -x /mnt/controlscripts/rtsp-h26x ] || ! /mnt/controlscripts/rtsp-h26x status >/dev/null 2>&1; then
    return 1
  fi
  if [ ! -x /mnt/bin/curl ]; then
    return 0
  fi

  rtsp_port="$(read_config rtspserver.conf PORT)"
  [ -n "$rtsp_port" ] || rtsp_port=554
  rtsp_user="$(read_config rtspserver.conf USERNAME)"
  rtsp_pass="$(read_config rtspserver.conf USERPASSWORD)"
  rtsp_substream="$(read_kv_or_default /mnt/config/boot.conf RTSP_SUBSTREAM 1)"
  onvif_policy="$(read_kv_or_default /mnt/config/boot.conf ONVIF_STREAM_POLICY main-primary)"
  health_stream="video0_unicast"
  case "$onvif_policy" in
    sub-primary|sub-only)
      if [ "$rtsp_substream" = "1" ]; then
        health_stream="video1_unicast"
      fi
      ;;
  esac

  # Process-level status is authoritative for rollback.
  # DESCRIBE probe is best-effort and should not force rollback on flaky stacks.
  if [ -n "$rtsp_user" ]; then
    sdp="$(/mnt/bin/curl -s -S -m 2 -X DESCRIBE -u "${rtsp_user}:${rtsp_pass}" "rtsp://127.0.0.1:${rtsp_port}/${health_stream}" 2>/dev/null)" || return 0
  else
    sdp="$(/mnt/bin/curl -s -S -m 2 -X DESCRIBE "rtsp://127.0.0.1:${rtsp_port}/${health_stream}" 2>/dev/null)" || return 0
  fi
  echo "$sdp" | grep -q "m=video" || return 0
  return 0
}

wait_for_rtsp_health() {
  attempts="$1"
  [ -n "$attempts" ] || attempts=6
  if [ "$PRECHANGE_RTSP_WAS_RUNNING" != "1" ]; then
    return 0
  fi

  i=0
  while [ "$i" -lt "$attempts" ]; do
    if rtsp_quick_health_check; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

rtsp_strict_describe_check() {
  health_stream="$1"
  if [ ! -x /mnt/controlscripts/rtsp-h26x ] || ! /mnt/controlscripts/rtsp-h26x status >/dev/null 2>&1; then
    return 1
  fi
  if [ ! -x /mnt/bin/curl ]; then
    return 2
  fi

  rtsp_timeout="$(sanitize_int_range "$(read_kv_or_default /mnt/config/boot.conf RTSP_HEALTHCHECK_TIMEOUT_SECONDS 4)" 2 30 4)"
  rtsp_port="$(read_config rtspserver.conf PORT)"
  [ -n "$rtsp_port" ] || rtsp_port=554
  rtsp_user="$(read_config rtspserver.conf USERNAME)"
  rtsp_pass="$(read_config rtspserver.conf USERPASSWORD)"

  if [ -n "$rtsp_user" ]; then
    sdp="$(/mnt/bin/curl -s -S -m "$rtsp_timeout" -X DESCRIBE -u "${rtsp_user}:${rtsp_pass}" "rtsp://127.0.0.1:${rtsp_port}/${health_stream}" 2>/dev/null)" || return 1
  else
    sdp="$(/mnt/bin/curl -s -S -m "$rtsp_timeout" -X DESCRIBE "rtsp://127.0.0.1:${rtsp_port}/${health_stream}" 2>/dev/null)" || return 1
  fi

  printf '%s' "$sdp" | grep -q "m=video" || return 1
  return 0
}

AUTO_STREAM_SELFTEST_BLOCKING_FAIL=0
AUTO_STREAM_SELFTEST_WARN=0

record_auto_stream_selftest_result() {
  test_label="$1"
  test_status="$2"
  test_detail="$3"
  test_severity="${4:-nonblocking}"

  echo "Automatic integration self-test: ${test_label}: ${test_status}. ${test_detail}<br/>"

  case "$test_status" in
    FAIL)
      if [ "$test_severity" = "blocking" ]; then
        AUTO_STREAM_SELFTEST_BLOCKING_FAIL=1
      else
        AUTO_STREAM_SELFTEST_WARN=1
      fi
      ;;
    WARN)
      AUTO_STREAM_SELFTEST_WARN=1
      ;;
  esac
}

run_postchange_integration_selftest() {
  AUTO_STREAM_SELFTEST_BLOCKING_FAIL=0
  AUTO_STREAM_SELFTEST_WARN=0

  rtsp_expected=0
  onvif_expected=0
  current_rtsp_substream="$(normalize_bool "$(read_kv_or_default /mnt/config/boot.conf RTSP_SUBSTREAM 1)")"
  mqtt_enable="$(normalize_bool "$(read_kv_or_default /mnt/config/mqtt.conf MQTT_ENABLE 0)")"
  mqtt_topic_root="$(read_kv_or_default /mnt/config/mqtt.conf MQTT_TOPIC_ROOT tc100/camera)"
  mqtt_host="$(read_kv_or_default /mnt/config/mqtt.conf MQTT_HOST 127.0.0.1)"
  mqtt_port="$(sanitize_int_range "$(read_kv_or_default /mnt/config/mqtt.conf MQTT_PORT 1883)" 1 65535 1883)"

  if [ "$PRECHANGE_RTSP_WAS_RUNNING" = "1" ] || { [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x status >/dev/null 2>&1; }; then
    rtsp_expected=1
  fi
  if [ "$PRECHANGE_ONVIF_WAS_RUNNING" = "1" ] || { [ -x /mnt/controlscripts/onvif ] && /mnt/controlscripts/onvif status >/dev/null 2>&1; }; then
    onvif_expected=1
  fi

  if [ "$rtsp_expected" = "1" ]; then
    rtsp_strict_describe_check video0_unicast
    rtsp_main_rc=$?
    case "$rtsp_main_rc" in
      0)
        record_auto_stream_selftest_result "RTSP main" "OK" "DESCRIBE succeeded for video0_unicast." blocking
        ;;
      2)
        record_auto_stream_selftest_result "RTSP main" "WARN" "curl is unavailable, so DESCRIBE validation was skipped." nonblocking
        ;;
      *)
        record_auto_stream_selftest_result "RTSP main" "FAIL" "DESCRIBE failed for video0_unicast." blocking
        ;;
    esac
  else
    record_auto_stream_selftest_result "RTSP main" "SKIP" "RTSP service is not running, so validation was skipped." nonblocking
  fi

  if [ "$rtsp_expected" != "1" ]; then
    record_auto_stream_selftest_result "RTSP sub" "SKIP" "RTSP service is not running, so substream validation was skipped." nonblocking
  elif [ "$current_rtsp_substream" != "1" ]; then
    record_auto_stream_selftest_result "RTSP sub" "SKIP" "Substream disabled by RTSP_SUBSTREAM=0." nonblocking
  else
    rtsp_strict_describe_check video1_unicast
    rtsp_sub_rc=$?
    case "$rtsp_sub_rc" in
      0)
        record_auto_stream_selftest_result "RTSP sub" "OK" "DESCRIBE succeeded for video1_unicast." blocking
        ;;
      2)
        record_auto_stream_selftest_result "RTSP sub" "WARN" "curl is unavailable, so substream DESCRIBE validation was skipped." nonblocking
        ;;
      *)
        record_auto_stream_selftest_result "RTSP sub" "FAIL" "DESCRIBE failed for video1_unicast." blocking
        ;;
    esac
  fi

  if [ "$onvif_expected" = "1" ]; then
    if [ -x /mnt/controlscripts/onvif ] && /mnt/controlscripts/onvif health >/dev/null 2>&1; then
      record_auto_stream_selftest_result "ONVIF" "OK" "ONVIF health check succeeded." blocking
    else
      record_auto_stream_selftest_result "ONVIF" "FAIL" "ONVIF health check failed." blocking
    fi
  else
    record_auto_stream_selftest_result "ONVIF" "SKIP" "ONVIF service is not running, so validation was skipped." nonblocking
  fi

  if [ "$mqtt_enable" = "1" ]; then
    if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
      _ac_now
      [ -n "$now_ts" ] || now_ts=0
      mqtt_selftest_payload="$(printf '{"ts":%s,"type":"auto_stream_selftest","origin":"action.cgi"}' "$now_ts")"
      if /mnt/scripts/mqtt-bridge.sh publish selftest "$mqtt_selftest_payload" 0 >/dev/null 2>&1; then
        record_auto_stream_selftest_result "MQTT publish" "OK" "Published self-test payload to ${mqtt_topic_root}/selftest via ${mqtt_host}:${mqtt_port}." nonblocking
      else
        record_auto_stream_selftest_result "MQTT publish" "WARN" "Publish failed to ${mqtt_host}:${mqtt_port}; keeping stream changes because broker reachability is non-blocking." nonblocking
      fi
    else
      record_auto_stream_selftest_result "MQTT publish" "WARN" "mqtt-bridge.sh is missing, so MQTT publish validation was skipped." nonblocking
    fi
  else
    record_auto_stream_selftest_result "MQTT publish" "SKIP" "MQTT bridge disabled in config." nonblocking
  fi

  _ac_now; snapshot_tmp="/tmp/action-selftest.$$.$now_ts.jpg"
  if [ -x /mnt/bin/getimage ]; then
    if timeout 5 /mnt/bin/getimage > "$snapshot_tmp" 2>/dev/null && [ -s "$snapshot_tmp" ]; then
      record_auto_stream_selftest_result "Snapshot" "OK" "Local snapshot capture succeeded." nonblocking
    else
      record_auto_stream_selftest_result "Snapshot" "WARN" "Snapshot capture failed; keeping stream changes because this check is non-blocking." nonblocking
    fi
  else
    record_auto_stream_selftest_result "Snapshot" "WARN" "getimage is unavailable, so snapshot validation was skipped." nonblocking
  fi
  rm -f "$snapshot_tmp" >/dev/null 2>&1 || true
}

save_known_good_snapshot() {
  reason="$1"
  mkdir -p "$SNAPSHOT_DIR" >/dev/null 2>&1 || return 1
  cp /mnt/config/rtspserver.conf "$KNOWN_GOOD_RTSP_CONF" >/dev/null 2>&1 || return 1
  write_stream_state_snapshot "$KNOWN_GOOD_STREAM_CONF" "$reason"
}

restore_stream_from_snapshot() {
  rtsp_file="$1"
  state_file="$2"
  [ -f "$rtsp_file" ] || return 1
  [ -f "$state_file" ] || return 1
  cp "$rtsp_file" /mnt/config/rtspserver.conf >/dev/null 2>&1 || return 1
  apply_stream_state_snapshot "$state_file" || return 1
  restart_stream_services_for_validation
  wait_for_rtsp_health 4
}

rollback_stream_change() {
  failure_reason="$1"

  echo "${failure_reason}<br/>"
  if restore_stream_from_snapshot "$PRECHANGE_RTSP_CONF" "$PRECHANGE_STREAM_CONF"; then
    echo "Rollback completed using pre-change snapshot.<br/>"
    return 0
  fi

  if restore_stream_from_snapshot "$KNOWN_GOOD_RTSP_CONF" "$KNOWN_GOOD_STREAM_CONF"; then
    echo "Rollback completed using known-good snapshot.<br/>"
    return 0
  fi

  echo "Rollback failed: no recoverable snapshot available.<br/>"
  return 1
}

finalize_stream_apply() {
  change_label="$1"

  restart_stream_services_for_validation
  if ! wait_for_rtsp_health 4; then
    rollback_stream_change "Stream restart safety check failed after applying ${change_label}. Rolling back..."
    return 1
  fi

  echo "Stream restart safety check: OK.<br/>"
  run_postchange_integration_selftest

  if [ "$AUTO_STREAM_SELFTEST_BLOCKING_FAIL" = "1" ]; then
    rollback_stream_change "Automatic integration self-test failed after applying ${change_label}. Rolling back..."
    return 1
  fi

  if [ "$AUTO_STREAM_SELFTEST_WARN" = "1" ]; then
    echo "Automatic integration self-test completed with warnings, but no blocking stream regressions were detected.<br/>"
  else
    echo "Automatic integration self-test: OK.<br/>"
  fi

  if save_known_good_snapshot "auto:${change_label}"; then
    echo "Known-good snapshot updated.<br/>"
  else
    echo "Warning: could not update known-good snapshot.<br/>"
  fi
  return 0
}

credentials_default_active() {
  default_http_hash="1d06b7785388de1501e8d57847540f6d"
  rtsp_username="$(read_config rtspserver.conf USERNAME)"
  rtsp_password="$(read_config rtspserver.conf USERPASSWORD)"
  if [ "$rtsp_username" = "root" ] && [ "$rtsp_password" = "pass" ]; then
    return 0
  fi

  http_hash="$(awk -F: 'NR==1{print $3; exit}' /mnt/config/lighttpd.user 2>/dev/null | sed 's/\r//g')"
  if [ "$http_hash" = "$default_http_hash" ]; then
    return 0
  fi

  if [ -r /mnt/config/user.pwd ]; then
    read -r all_services_password < /mnt/config/user.pwd
    if [ "$all_services_password" = "pass" ]; then
      return 0
    fi
  fi
  return 1
}

select_compat_profile_values() {
  profile="$1"
  case "$profile" in
    universal-h264|high-quality)
      profile_label="Universal H264 (recommended)"
      width0=1920; height0=1080; fps0=20; bps0=2800; gop0=40; maxkbps0=3600; targetkbps0=2800; smartq0=90; smartstatic0=560
      width1=640;  height1=360;  fps1=12; bps1=550;  gop1=24; maxkbps1=760;  targetkbps1=550;  smartq1=75; smartstatic1=210
      codec0=0; profile0=1
      codec1=0; profile1=0
      rtsp_substream=1
      rtsp_audio=1
      onvif_policy="main-primary"
      low_cpu_profile=0
      ;;
    ha-frigate|frigate-balanced)
      profile_label="Frigate balanced"
      width0=1920; height0=1080; fps0=15; bps0=1800; gop0=15; maxkbps0=2400; targetkbps0=1800; smartq0=85; smartstatic0=480
      width1=640;  height1=360;  fps1=8;  bps1=260;  gop1=8;  maxkbps1=360;  targetkbps1=260;  smartq1=65; smartstatic1=150
      codec0=0; profile0=1
      codec1=0; profile1=0
      rtsp_substream=1
      rtsp_audio=0
      onvif_policy="sub-primary"
      low_cpu_profile=0
      ;;
    frigate-low-bandwidth)
      profile_label="Frigate low-bandwidth"
      width0=1280; height0=720;  fps0=10; bps0=1000; gop0=10; maxkbps0=1300; targetkbps0=1000; smartq0=72; smartstatic0=360
      width1=640;  height1=360;  fps1=5;  bps1=180;  gop1=5;  maxkbps1=240;  targetkbps1=180;  smartq1=60; smartstatic1=120
      codec0=0; profile0=1
      codec1=0; profile1=0
      rtsp_substream=1
      rtsp_audio=0
      onvif_policy="sub-primary"
      low_cpu_profile=0
      ;;
    frigate-quality)
      profile_label="Frigate quality"
      width0=1920; height0=1080; fps0=20; bps0=2600; gop0=20; maxkbps0=3200; targetkbps0=2600; smartq0=90; smartstatic0=520
      width1=640;  height1=360;  fps1=10; bps1=350;  gop1=10; maxkbps1=480;  targetkbps1=350;  smartq1=70; smartstatic1=180
      codec0=0; profile0=1
      codec1=0; profile1=0
      rtsp_substream=1
      rtsp_audio=0
      onvif_policy="sub-primary"
      low_cpu_profile=0
      ;;
    hybrid-hevc-main)
      profile_label="Hybrid HEVC main + H264 sub"
      width0=1920; height0=1080; fps0=20; bps0=2600; gop0=40; maxkbps0=3400; targetkbps0=2600; smartq0=90; smartstatic0=540
      width1=640;  height1=360;  fps1=10; bps1=450;  gop1=20; maxkbps1=650;  targetkbps1=450;  smartq1=72; smartstatic1=190
      codec0=2; profile0=3
      codec1=0; profile1=0
      rtsp_substream=1
      rtsp_audio=0
      onvif_policy="main-primary"
      low_cpu_profile=0
      ;;
    legacy-main-only)
      profile_label="Legacy main-only H264"
      width0=1280; height0=720;  fps0=15; bps0=1500; gop0=30; maxkbps0=2000; targetkbps0=1500; smartq0=75; smartstatic0=420
      width1=352;  height1=200;  fps1=5;  bps1=120;  gop1=10; maxkbps1=180;  targetkbps1=120;  smartq1=50; smartstatic1=100
      codec0=0; profile0=1
      codec1=0; profile1=0
      rtsp_substream=0
      rtsp_audio=1
      onvif_policy="main-only"
      low_cpu_profile=0
      ;;
    nvr-low-cpu)
      profile_label="NVR low-CPU (compat alias)"
      width0=1280; height0=720;  fps0=10; bps0=900;  gop0=20; maxkbps0=1200; targetkbps0=900;  smartq0=65; smartstatic0=360
      width1=352;  height1=200;  fps1=5;  bps1=120;  gop1=10; maxkbps1=180;  targetkbps1=120;  smartq1=50; smartstatic1=100
      codec0=0; profile0=1
      codec1=0; profile1=0
      rtsp_substream=1
      rtsp_audio=0
      onvif_policy="main-only"
      low_cpu_profile=1
      ;;
    *)
      return 1
      ;;
  esac
  return 0
}

# csrf_check — called AFTER response headers have already been emitted (inside cmd handlers).
# Validates the X-CSRF-Token header against the per-boot token.
# Outputs an error body and exits on mismatch; silently passes on early boot.
csrf_check() {
  _csrf_stored=""
  if [ -r /tmp/csrf_token ]; then
    read -r _csrf_stored < /tmp/csrf_token
    _csrf_stored="$(printf '%s' "$_csrf_stored" | tr -cd '0-9a-fA-F')"
  fi
  [ -z "$_csrf_stored" ] && return 0  # no token yet, skip enforcement
  _csrf_header="$(printf '%s' "${HTTP_X_CSRF_TOKEN:-}" | tr -cd '0-9a-fA-F')"
  if [ "$_csrf_header" != "$_csrf_stored" ]; then
    # Headers already sent — output body only (HTTP status will be 200 but action won't run)
    if wants_json_response; then
      printf '{"ok":false,"error":"CSRF token missing or invalid. Reload the page.","code":"permission_denied"}\n'
    else
      echo "<p>Error: CSRF token missing or invalid. Please reload the page.</p>"
    fi
    exit 0
  fi
}

audit_log() {
  _al_cmd="$1"
  _al_dir="/tmp/log"
  _al_file="$_al_dir/audit.log"
  _al_max_bytes=65536
  [ -d "$_al_dir" ] || mkdir -p "$_al_dir" 2>/dev/null || return 0
  # Rotate if too large
  if [ -f "$_al_file" ]; then
    _al_sz="$(wc -c < "$_al_file" 2>/dev/null)"; case "$_al_sz" in ''|*[!0-9]*) _al_sz=0 ;; esac
    if [ "$_al_sz" -gt "$_al_max_bytes" ]; then
      tail -n 100 "$_al_file" > "${_al_file}.tmp" 2>/dev/null && mv "${_al_file}.tmp" "$_al_file" 2>/dev/null || true
    fi
  fi
  _al_btime=0
  while read -r _k _v _; do [ "$_k" = "btime" ] && _al_btime="$_v" && break; done < /proc/stat
  read -r _al_up _ < /proc/uptime
  _al_ts=$((_al_btime + ${_al_up%.*}))
  _al_ip="${REMOTE_ADDR:-unknown}"
  printf '%s cmd=%s ip=%s\n' "$_al_ts" "$_al_cmd" "$_al_ip" >> "$_al_file" 2>/dev/null || true
}

if [ -n "$F_cmd" ]; then
  if [ -z "$F_val" ]; then
    F_val=100
  fi
  audit_log "$F_cmd"
  # Enforce CSRF for all state-changing commands. Read-only queries are whitelisted.
  case "$F_cmd" in
    showlog|get_ptt_vol|get_ptt_status|wifi_scan|wifi_get_ssid) ;;
    *) csrf_check ;;
  esac
  case "$F_cmd" in
    showlog)
      if wants_json_response; then
        json_body_err "FORMAT_NOT_SUPPORTED" "showlog command does not support JSON format"
      else
        echo "<pre>"
        case "${F_logname}" in
          "" | 1)
            emit_log_tail_dir "/var/log" "Summary of /var/log (tail -n ${LOG_SUMMARY_TAIL_LINES})" "$LOG_SUMMARY_TAIL_LINES"
            emit_log_tail_dir "/mnt/log" "=== /mnt/log (tail -n ${LOG_SUMMARY_TAIL_LINES}) ===" "$LOG_SUMMARY_TAIL_LINES"
            ;;

          2)
            echo "Content of dmesg (tail -n ${LOG_DMESG_TAIL_LINES})<br/>"
            /bin/dmesg 2>/dev/null | tail -n "$LOG_DMESG_TAIL_LINES"
            ;;

          3)
            echo "Content of v4l2rtspserver.log (tail -n ${LOG_VIDEO_TAIL_LINES})<br/>"
            if [ -f /mnt/log/v4l2rtspserver.log ]; then
              tail -n "$LOG_VIDEO_TAIL_LINES" /mnt/log/v4l2rtspserver.log
            else
              echo "Log file not found: /mnt/log/v4l2rtspserver.log"
            fi
            ;;

        esac
        echo "</pre>"
      fi
    ;;
    clearlog)
      if wants_json_response; then
        json_body_err "FORMAT_NOT_SUPPORTED" "clearlog command does not support JSON format"
      else
        echo "<pre>"
        case "${F_logname}" in
          "" | 1)
            cleared_var="$(clear_log_dir_files /var/log)"
            cleared_mnt="$(clear_log_dir_files /mnt/log)"
            echo "Summary logs cleared<br/>"
            echo "/var/log files cleared: $cleared_var<br/>"
            echo "/mnt/log files cleared: $cleared_mnt<br/>"
            ;;
          2)
            echo "Content of dmesg cleared<br/>"
            /bin/dmesg -c > /dev/null
            ;;
          3)
            echo "Content of v4l2rtspserver.log cleared<br/>"
            : > /mnt/log/v4l2rtspserver.log 2>/dev/null || true
            ;;
        esac
        echo "</pre>"
      fi
    ;;

    set_video_params)
      # Supports both stream 0 and 1, plus all advanced SmartVBR/QP tuning
      stream_idx="$(sanitize_int_range "${F_stream}" 0 1 0)"
      
      # Determine which inputs to use based on stream index
      if [ "$stream_idx" = "1" ]; then
          raw_size=$(printf '%s' "${F_video_size1}")
          fps=$(sanitize_int_range "${F_fps1}" 1 30 25)
          bitrate=$(sanitize_int_range "${F_brbitrate1}" 32 8000 300)
          codec=$(sanitize_int_range "${F_video_codec1}" 0 2 0)
          gop=$(sanitize_int_range "${F_goplen1}" 1 300 50)
          format=$(sanitize_int_range "${F_video_format1}" 0 1 1)
          minqp=$(sanitize_int_range "${F_minqp1}" 1 51 20)
          maxqp=$(sanitize_int_range "${F_maxqp1}" 1 51 45)
          smartmode=$(sanitize_int_range "${F_smartmode1}" 0 2 0)
      else
          raw_size=$(printf '%s' "${F_video_size0}")
          fps=$(sanitize_int_range "${F_fps0}" 1 30 25)
          bitrate=$(sanitize_int_range "${F_brbitrate0}" 32 8000 1000)
          codec=$(sanitize_int_range "${F_video_codec0}" 0 2 0)
          gop=$(sanitize_int_range "${F_goplen0}" 1 300 50)
          format=$(sanitize_int_range "${F_video_format0}" 0 1 1)
          minqp=$(sanitize_int_range "${F_minqp0}" 1 51 20)
          maxqp=$(sanitize_int_range "${F_maxqp0}" 1 51 45)
          smartmode=$(sanitize_int_range "${F_smartmode0}" 0 2 0)
      fi
      
      width=$(echo "$raw_size" | cut -d'x' -f1)
      height=$(echo "$raw_size" | cut -d'x' -f2)

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          "$stream_idx" width "$width" \
          "$stream_idx" height "$height" \
          "$stream_idx" codec "$codec" \
          "$stream_idx" fps "$fps" \
          "$stream_idx" bps "$bitrate" \
          "$stream_idx" goplen "$gop" \
          "$stream_idx" brmode "$format" \
          "$stream_idx" minqp "$minqp" \
          "$stream_idx" maxqp "$maxqp" \
          "$stream_idx" smartmode "$smartmode"
      
      schedule_rtsp_restart
      if wants_json_response; then
        json_body_ok "Video settings for stream $stream_idx updated."
      else
        echo "Video settings for stream $stream_idx updated. RTSP restarting...<br/>"
      fi
    ;;

    conf_audioin)
      samplerate=$(sanitize_int_range "${F_samplerate}" 8000 48000 8000)
      volume=$(sanitize_int_range "${F_audioinVol}" 0 12 10)
      codec_main=$(sanitize_int_range "${F_audioCodec0}" 0 18 4)
      
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " samplerate "$samplerate" \
          " " audioinVol "$volume" \
          0 codec "$codec_main"
          
      schedule_rtsp_restart
      if wants_json_response; then
        json_body_ok "Audio settings updated."
      else
        echo "Audio settings updated. RTSP restarting...<br/>"
      fi
    ;;

    isp_pro)
      daynightlum=$(sanitize_int_range "${F_daynightlum}" 0 20000 6000)
      daynightawb=$(sanitize_int_range "${F_daynightawb}" 0 500000 160000)
      nightdaylum=$(sanitize_int_range "${F_nightdaylum}" 0 20000 1500)
      nightdayawb=$(sanitize_int_range "${F_nightdayawb}" 0 500000 10000)
      
      osdenabled=$(normalize_bool "${F_osdenabled}")
      osdtext=$(printf '%s' "${F_osdtext:-%H:%M:%S %d.%m.%Y}")
      osdfontsize0=$(sanitize_int_range "${F_osdfontsize0}" 8 128 32)
      osdx0=$(sanitize_int_range "${F_osdx0}" 0 2000 20)
      osdy0=$(sanitize_int_range "${F_osdy0}" 0 2000 24)
      osdalpha=$(sanitize_int_range "${F_osdalpha}" 0 255 0)
      frontcolor=$(sanitize_int_range "${F_frontcolor}" 0 7 1)
      backcolor=$(sanitize_int_range "${F_backcolor}" 0 2 0)
      edgecolor=$(sanitize_int_range "${F_edgecolor}" 0 2 2)
      imageflip=$(sanitize_int_range "${F_imageFlip}" 0 3 0)

      # Persist
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " daynightlum "$daynightlum" \
          " " daynightawb "$daynightawb" \
          " " nightdaylum "$nightdaylum" \
          " " nightdayawb "$nightdayawb" \
          " " osdenabled "$osdenabled" \
          " " osdtext "$osdtext" \
          " " osdalpha "$osdalpha" \
          " " osdfrontcolor "$frontcolor" \
          " " osdbackcolor "$backcolor" \
          " " osdedgecolor "$edgecolor" \
          0 osdfontsize "$osdfontsize0" \
          0 osdx "$osdx0" \
          0 osdy "$osdy0" \
          " " imageflip "$imageflip"

      # Apply immediately (best effort via setconf)
      /mnt/bin/setconf -k a -v "$daynightlum"
      /mnt/bin/setconf -k r -v "$daynightawb"
      /mnt/bin/setconf -k d -v "$nightdaylum"
      /mnt/bin/setconf -k b -v "$nightdayawb"
      /mnt/bin/setconf -k l -v "$osdenabled"
      /mnt/bin/setconf -k o -v "$osdtext"
      /mnt/bin/setconf -k h -v "$osdalpha"
      /mnt/bin/setconf -k c -v "$frontcolor"
      /mnt/bin/setconf -k i -v "$backcolor"
      /mnt/bin/setconf -k j -v "$edgecolor"
      /mnt/bin/setconf -k s -v "$osdfontsize0"
      /mnt/bin/setconf -k x -v "$osdx0"
      /mnt/bin/setconf -k y -v "$osdy0"
      /mnt/bin/setconf -k f -v "$imageflip"

      if wants_json_response; then
        json_body_ok "ISP and OSD settings updated."
      else
        echo "ISP and OSD settings updated.<br/>"
      fi
    ;;

    set_advanced_tuning)
      install_config /mnt/config/boot.conf
      lightweight=$(normalize_bool "${F_lightweight_mode}")
      hardening=$(normalize_bool "${F_security_hardening}")

      # Mem Guard settings
      mg_enable=$(normalize_bool "${F_mem_guard_enable}")
      mg_warn=$(sanitize_int_range "${F_mem_guard_warn}" 1024 32768 8192)
      mg_crit=$(sanitize_int_range "${F_mem_guard_crit}" 512 16384 4096)
      mg_interval=$(sanitize_int_range "${F_mem_guard_interval}" 5 600 20)

      # Persist to boot.conf
      rewrite_config /mnt/config/boot.conf LIGHTWEIGHT_MODE "$lightweight"
      rewrite_config /mnt/config/boot.conf SECURITY_HARDENING_MODE "$hardening"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE "$mg_enable"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_WARN_KB "$mg_warn"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_CRITICAL_KB "$mg_crit"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_INTERVAL_SECONDS "$mg_interval"

      if wants_json_response; then
        json_body_ok "Advanced tuning updated. Reboot may be required."
      else
        echo "Advanced tuning updated.<br/>"
      fi
    ;;

    set_network)
      hostname=$(printf '%s' "${F_hostname}" | sed 's/[^a-zA-Z0-9-]//g')
      rtsp_port=$(sanitize_int_range "${F_rtsp_port}" 1 65535 554)
      telnet_port=$(sanitize_int_range "${F_telnet_port}" 1 65535 23)
      
      [ -n "$hostname" ] && hostname "$hostname" && echo "$hostname" > /mnt/config/hostname.conf
      
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " PORT "$rtsp_port"
      /mnt/bin/rwconf /mnt/config/telnetd.conf w " " TELNET_PORT "$telnet_port"
      
      if wants_json_response; then
        json_body_ok "Network settings updated. RTSP/Telnet restart scheduled."
      else
        echo "Network settings updated.<br/>"
      fi
    ;;

    reboot)
      csrf_check
      if wants_json_response; then
        json_body_ok "Rebooting device..."
      else
        echo "Rebooting device..."
      fi
      _ac_now
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"reboot","source":"action.cgi"}' "$now_ts")"
      /sbin/reboot
    ;;

    shutdown)
      csrf_check
      if wants_json_response; then
        json_body_ok "Shutting down device.."
      else
        echo "Shutting down device.."
      fi
      /sbin/halt
    ;;

    clear_mem)
      sync
      echo 3 > /proc/sys/vm/drop_caches
      if wants_json_response; then
        json_body_ok "System caches cleared. Memory freed."
      else
        echo "System caches cleared. Memory freed.<br/>"
      fi
    ;;

    set_sound_detection)
      enable=$(normalize_bool "${F_sound_det_enable}")
      threshold=$(sanitize_int_range "${F_sound_det_threshold}" 100 10000 1500)
      interval=$(sanitize_int_range "${F_sound_det_interval}" 1 300 5)

      # Persist
      install_config /mnt/config/sound_detection.conf
      /mnt/bin/rwconf /mnt/config/sound_detection.conf w \
          " " ENABLE "$enable" \
          " " THRESHOLD "$threshold" \
          " " INTERVAL "$interval"

      if [ "$enable" = "1" ]; then
        /mnt/controlscripts/sound-detection start
      else
        /mnt/controlscripts/sound-detection stop
      fi
      if wants_json_response; then
        json_body_ok "Sound detection settings updated."
      else
        echo "Sound detection settings updated.<br/>"
      fi
    ;;

    front_led_on)
      front_led on
      if wants_json_response; then
        json_body_ok "Front LED turned on"
      fi
    ;;

    front_led_off)
      front_led off
      if wants_json_response; then
        json_body_ok "Front LED turned off"
      fi
    ;;

    red_led_on)
      red_led on
      if wants_json_response; then
        json_body_ok "Red LED turned on"
      fi
    ;;

    red_led_off)
      red_led off
      if wants_json_response; then
        json_body_ok "Red LED turned off"
      fi
    ;;

    ir_led_on)
      ir_led on
      if wants_json_response; then
        json_body_ok "IR LED turned on"
      fi
    ;;

    ir_led_off)
      ir_led off
      if wants_json_response; then
        json_body_ok "IR LED turned off"
      fi
    ;;

    ir_cut_on)
      ir_cut on
      if wants_json_response; then
        json_body_ok "IR cut filter enabled"
      fi
    ;;

    ir_cut_off)
      ir_cut off
      if wants_json_response; then
        json_body_ok "IR cut filter disabled"
      fi
    ;;

    audio_test)
      F_audioSource=$(printf '%b' "${F_audioSource//%/\\x}")
      F_audiotestVol=$(sanitize_int_range "${F_audiotestVol}" 0 100 90)
      if [ -z "$F_audioSource" ]; then
        F_audioSource="$(resolve_audio_test_source || true)"
      fi
      play_audio_test_source "$F_audioSource" "$F_audiotestVol"
    ;;


    set_telnet)
      if security_hardening_enabled; then
        if wants_json_response; then
          json_body_err "SECURITY_HARDENING_ENABLED" "Telnet changes are blocked."
        else
          echo "<p>Security hardening is enabled. Telnet changes are blocked.</p>"
        fi
        exit 0
      fi
      telnetport=$(printf '%s' "${F_telnetport}")
      case "$telnetport" in
        ''|*[!0-9]*)
          if wants_json_response; then
            json_body_err "INVALID_PORT" "Invalid telnet port. Allowed range is 1-65535."
          else
            echo "<p>Invalid telnet port. Allowed range is 1-65535.</p>"
          fi
          ;;
        *)
          if [ "$telnetport" -lt 1 ] || [ "$telnetport" -gt 65535 ]; then
            if wants_json_response; then
              json_body_err "INVALID_PORT" "Invalid telnet port. Allowed range is 1-65535."
            else
              echo "<p>Invalid telnet port. Allowed range is 1-65535.</p>"
            fi
          else
            echo "TELNET_PORT=$telnetport" > /mnt/config/telnetd.conf
            restart_service_if_need /mnt/controlscripts/telnet-server
            if wants_json_response; then
              json_body_ok "Setting telnet service port to: $telnetport"
            else
              echo "<p>Setting telnet service port to : $telnetport</p>"
            fi
          fi
          ;;
      esac
    ;;

    set_ftp)
      if security_hardening_enabled; then
        if wants_json_response; then
          json_body_err "SECURITY_HARDENING_ENABLED" "FTP changes are blocked."
        else
          echo "<p>Security hardening is enabled. FTP changes are blocked.</p>"
        fi
        exit 0
      fi
      ftpport=$(printf '%s' "${F_ftpport}")
      case "$ftpport" in
        ''|*[!0-9]*)
          if wants_json_response; then
            json_body_err "INVALID_PORT" "Invalid ftp port. Allowed range is 1-65535."
          else
            echo "<p>Invalid ftp port. Allowed range is 1-65535.</p>"
          fi
          ;;
        *)
          if [ "$ftpport" -lt 1 ] || [ "$ftpport" -gt 65535 ]; then
            if wants_json_response; then
              json_body_err "INVALID_PORT" "Invalid ftp port. Allowed range is 1-65535."
            else
              echo "<p>Invalid ftp port. Allowed range is 1-65535.</p>"
            fi
          else
            if wants_json_response; then
              json_body_ok "Setting ftp service port to: $ftpport"
            else
              echo "<p>Setting ftp service port to: $ftpport</p>"
            fi
            echo "PORT=$ftpport" > /mnt/config/ftp.conf
            start_service_if_need /mnt/controlscripts/ftp-server
          fi
          ;;
      esac
    ;;

    settz)
       ntp_srv=$(printf '%s' "${F_ntp_srv}")

      #read ntp_serv.conf
      conf_ntp_srv=$(cat /mnt/config/ntp_srv.conf)

      if [ "$conf_ntp_srv" != "$ntp_srv" ]; then
        echo "<p>Setting NTP Server to '$ntp_srv'...</p>"
        echo "$ntp_srv" > /mnt/config/ntp_srv.conf
        echo "<p>Syncing time on '$ntp_srv'...</p>"
        if /mnt/bin/busybox ntpd -q -n -p "$ntp_srv" > /dev/null 2>&1; then
          echo "<p>Success</p>"
        else
          echo "<p>Failed</p>"
        fi
      fi

      tz=$(printf '%b' "${F_tz//%/\\x}")
      if [ "$(cat /mnt/config/timezone.conf)" != "$tz" ]; then
        echo "<p>Setting TZ to '$tz'...</p>"
        echo "$tz" > /mnt/config/timezone.conf
        echo "<p>Syncing time...</p>"
        if /mnt/bin/busybox ntpd -q -n -p "$ntp_srv" > /dev/null 2>&1; then
          echo "<p>Success</p>"
        else echo "<p>Failed</p>"
        fi
        schedule_rtsp_restart
      fi
      hst=$(printf '%s' "${F_hostname}")
      if [ "$(cat /mnt/config/hostname.conf)" != "$hst" ]; then
        echo "<p>Setting hostname to '$hst'...</p>"
        echo "$hst" > /mnt/config/hostname.conf
        if hostname "$hst"; then
          echo "<p>Success</p>"
        else echo "<p>Failed</p>"
        fi
      fi
    ;;

    set_http_password)
      password_raw="${F_password}"
      [ -n "$password_raw" ] || password_raw="${F_httppassword}"
      password=$(printf '%b' "${password_raw//%/\\x}")
      if [ -z "$password" ] || [ "$password" = "*****" ]; then
        echo "<p>Refusing empty/placeholder HTTP password.</p>"
        exit 0
      fi
      echo "<p>Setting http password to : $password</p>"
      http_password "$password"
    ;;

    set_all_password)
      password_raw="${F_password}"
      [ -n "$password_raw" ] || password_raw="${F_allpassword}"
      password=$(printf '%b' "${password_raw//%/\\x}")
      if [ -z "$password" ] || [ "$password" = "*****" ]; then
        echo "<p>Refusing empty/placeholder all-services password.</p>"
        exit 0
      fi
      echo "<p>Setting all services password to : $password</p>"
      all_password "$password"
      restart_service_if_need /mnt/controlscripts/ftp-server
      restart_service_if_need /mnt/controlscripts/telnet-server
      schedule_rtsp_restart
    ;;

    osd)
      osd_enabled="${F_OSDenable}"
      case "$osd_enabled" in
        1|enabled|true|on|yes)
          osd_enabled=1
          ;;
        *)
          osd_enabled=0
          ;;
      esac

      # F_osdtext is already URL-decoded in func.cgi; do not decode '%' again.
      osdtext="$F_osdtext"
      # Recover from legacy invalid escaped values like '\xH' -> '%H'.
      osdtext=$(printf '%s' "$osdtext" | sed 's/\\x/%/g')
      if [ -z "$osdtext" ]; then
        osdtext="%H:%M:%S %d.%m.%Y"
      fi

      frontcolor="${F_frontcolor:-1}"
      backcolor="${F_backcolor:-0}"
      edgecolor="${F_edgecolor:-2}"
      alpha="${F_alpha:-0}"
      osdsize0="${F_OSDSize0:-16}"
      posx0="${F_posx0:-0}"
      posy0="${F_posy0:-0}"
      osdsize1="${F_OSDSize1:-16}"
      posx1="${F_posx1:-0}"
      posy1="${F_posy1:-0}"

      if [ "$osd_enabled" = "1" ]; then
        /mnt/bin/setconf -k o -v "$osdtext"
      fi
      /mnt/bin/setconf -k c -v "$frontcolor"
      /mnt/bin/setconf -k i -v "$backcolor"
      /mnt/bin/setconf -k j -v "$edgecolor"
      /mnt/bin/setconf -k h -v "$alpha"
      /mnt/bin/setconf -k l -v "$osd_enabled"
      /mnt/bin/setconf -k s -v "$osdsize0"
      /mnt/bin/setconf -k x -v "$posx0"
      /mnt/bin/setconf -k y -v "$posy0"
      /mnt/bin/setconf -k z -v "$osdsize1"
      /mnt/bin/setconf -k w -v "$posx1"
      /mnt/bin/setconf -k t -v "$posy1"

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " osdtext "$osdtext" \
          " " osdfrontcolor "$frontcolor" \
          " " osdbackcolor "$backcolor" \
          " " osdalpha "$alpha" \
          " " osdedgecolor "$edgecolor" \
          " " osdenabled "$osd_enabled" \
          0  osdfontsize "$osdsize0" \
          0  osdx "$posx0" \
          0  osdy "$posy0" \
          1  osdfontsize "$osdsize1" \
          1  osdx "$posx1" \
          1  osdy "$posy1"

      schedule_rtsp_restart

      echo "OSD set to \"$osdtext\" and enabled: $osd_enabled<br/>"
    ;;

    auto_night_mode_start)
      /mnt/controlscripts/auto-night-detection start
    ;;

    auto_night_mode_stop)
      /mnt/controlscripts/auto-night-detection stop
    ;;

    toggle-rtsp-nightvision-on)
      /mnt/bin/setconf -k n -v 1
    ;;

    toggle-rtsp-nightvision-off)
      /mnt/bin/setconf -k n -v 0
    ;;

    night-mode-on)
      /mnt/controlscripts/night-mode start
    ;;

    night-mode-off)
      /mnt/controlscripts/night-mode stop
    ;;

    image-flip)
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " imageflip ${F_flipValue}
      /mnt/bin/setconf -k f -v ${F_flipValue}
    ;;

    rtsp-log-on)
      rewrite_config /mnt/config/rtspserver.conf RTSPLOGENABLED 1
      schedule_rtsp_restart
    ;;

    rtsp-log-off)
      rewrite_config /mnt/config/rtspserver.conf RTSPLOGENABLED 0
      schedule_rtsp_restart
    ;;

    motion_detection_on)
        mdsens=$(read_config rtspserver.conf mdsens)

        /mnt/bin/setconf -k m -v $mdsens
        /mnt/bin/setconf -k p -v 1
        rewrite_config /mnt/config/rtspserver.conf mdenabled 1
    ;;

    motion_detection_off)
      /mnt/bin/setconf -k p -v 0
      rewrite_config /mnt/config/rtspserver.conf mdenabled 0
    ;;

    service_trim_on)
      install_config /mnt/config/service_trim.conf
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 1
      echo "Service trimming enabled. Non-essential services will stop; reboot for full effect.<br/>"

      for svc in ftp-server telnet-server motion-detection recording timelapse auto-night-detection front-led night-mode network-monitor; do
        if [ -x "/mnt/controlscripts/$svc" ]; then
          /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
        fi
      done
      rm -f /tmp/health_snapshot.cache 2>/dev/null || true
    ;;

    service_trim_off)
      install_config /mnt/config/service_trim.conf
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0
      echo "Service trimming disabled. Reboot to restore autostart services.<br/>"
      rm -f /tmp/health_snapshot.cache 2>/dev/null || true
    ;;

    set_performance_profile)
      install_config /mnt/config/boot.conf
      install_config /mnt/config/service_trim.conf
      capture_prechange_stream_snapshot
      profile=$(printf '%s' "${F_performance_profile}")
      profile_summary_line=""
      profile_detail_line=""
      profile_detail_line2=""
      apply_low_cpu_defaults_after_finalize=0
      stop_trimmed_services_after_finalize=0

      case "$profile" in
        balanced)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 0
          rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE 0
          rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE 0
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 1
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-primary
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 0
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0

          profile_summary_line="Performance profile set to Balanced."
          profile_detail_line="Dual stream + audio defaults enabled; reboot to restore all background services if they were trimmed."
          ;;
        low-cpu)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 1
          rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE 1
          rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_OSD 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG 1
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 0
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-only
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 0
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0

          # Apply conservative stream settings immediately.
          /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
              0 width 640 0 height 360 0 fps 10 0 bps 600 0 goplen 20 0 brmode 1 0 codec 0 0 profile 1 \
              0 smartmode 1 0 smartgoplen 20 0 smartquality 60 0 smartstatic 350 0 maxkbps 800 0 targetkbps 600 \
              1 width 352 1 height 200 1 fps 5 1 bps 120 1 goplen 10 1 brmode 1 1 codec 0 1 profile 0 \
              1 smartmode 1 1 smartgoplen 10 1 smartquality 50 1 smartstatic 100 1 maxkbps 160 1 targetkbps 120
          apply_low_cpu_defaults_after_finalize=1
          profile_summary_line="Performance profile set to Low CPU."
          profile_detail_line="Applied conservative dual-stream RTSP settings now (safe geometry, H264) and enabled memory guard."
          profile_detail_line2="Reboot recommended for full low-CPU service profile."
          ;;
        rtsp-only)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 1
          rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE 1
          rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_OSD 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG 1
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 0
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 0
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-only
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 1
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 1

          apply_low_cpu_defaults_after_finalize=1
          stop_trimmed_services_after_finalize=1
          profile_summary_line="Performance profile set to RTSP + ONVIF only."
          profile_detail_line="Stopped non-essential services now; reboot to enforce trimmed autostart persistently."
          ;;
        *)
          echo "Unknown performance profile '$profile'<br/>"
          exit 0
          ;;
      esac

      if finalize_stream_apply "performance-profile:${profile}"; then
        if [ "$apply_low_cpu_defaults_after_finalize" = "1" ]; then
          apply_low_cpu_background_defaults
        fi
        if [ "$stop_trimmed_services_after_finalize" = "1" ]; then
          stop_trimmed_runtime_services
        fi
        sync_memory_guard_service_with_config
        echo "${profile_summary_line}<br/>"
        [ -n "$profile_detail_line" ] && echo "${profile_detail_line}<br/>"
        [ -n "$profile_detail_line2" ] && echo "${profile_detail_line2}<br/>"
        _ac_now
        publish_mqtt_event "$(printf '{"ts":%s,"type":"profile","value":"%s"}' "$now_ts" "$profile")"
      fi
      rm -f /tmp/health_snapshot.cache 2>/dev/null || true
    ;;

    set_web_mode)
      if wants_json_response; then
        json_body_err "FORMAT_NOT_SUPPORTED" "set_web_mode command does not support JSON format"
      else
        install_config /mnt/config/boot.conf
        web_mode=$(printf '%s' "${F_web_mode}")
        ultralite_http_port=$(printf '%s' "${F_ultralite_http_port}")

        if security_hardening_enabled; then
          if [ "$web_mode" != "full" ]; then
            echo "Security hardening is enabled. WEB_MODE is locked to full (HTTPS).<br/>"
            exit 0
          fi
        fi

        case "$web_mode" in
          full|http|ultra-lite|ultralite|off) ;;
          *)
            echo "Unknown web mode '$web_mode'<br/>"
            exit 0
            ;;
        esac

        if [ "$web_mode" = "ultralite" ]; then
          web_mode="ultra-lite"
        fi

        case "$ultralite_http_port" in
          ''|*[!0-9]*) ultralite_http_port=80 ;;
        esac
        if [ "$ultralite_http_port" -lt 1 ] || [ "$ultralite_http_port" -gt 65535 ]; then
          ultralite_http_port=80
        fi

        rewrite_config /mnt/config/boot.conf WEB_MODE "$web_mode"
        rewrite_config /mnt/config/boot.conf ULTRALITE_HTTP_PORT "$ultralite_http_port"

        apply_web_mode_async "$web_mode"
        schedule_onvif_restart

        echo "Web mode set to: $web_mode<br/>"
        if [ "$web_mode" = "ultra-lite" ]; then
          echo "Ultra-lite HTTP port set to: $ultralite_http_port<br/>"
        fi
        echo "If the web UI disconnects, reconnect using the updated protocol/port.<br/>"
        _ac_now
        publish_mqtt_event "$(printf '{"ts":%s,"type":"web_mode","mode":"%s"}' "$now_ts" "$web_mode")"
        rm -f /tmp/health_snapshot.cache 2>/dev/null || true
      fi
    ;;

    set_reboot_schedule)
      install_config /mnt/config/boot.conf

      reboot_schedule_enable="$(normalize_bool "${F_reboot_enable}")"
      reboot_schedule_minute="$(sanitize_int_range "${F_reboot_min}" 0 59 0)"
      reboot_schedule_hour="$(sanitize_int_range "${F_reboot_hour}" 0 23 4)"
      reboot_schedule_weekday="$(sanitize_weekday_expr "${F_reboot_dow}")"

      # shellcheck disable=SC1090
      if [ -f /mnt/config/boot.conf ]; then
        . /mnt/config/boot.conf
      fi
      current_enable_crond="$(normalize_bool "${ENABLE_CROND}")"

      if [ "$reboot_schedule_enable" = "1" ] && [ "$current_enable_crond" != "1" ]; then
        current_enable_crond=1
        rewrite_config /mnt/config/boot.conf ENABLE_CROND 1
      fi

      rewrite_config /mnt/config/boot.conf REBOOT_SCHEDULE_ENABLE "$reboot_schedule_enable"
      rewrite_config /mnt/config/boot.conf REBOOT_SCHEDULE_MINUTE "$reboot_schedule_minute"
      rewrite_config /mnt/config/boot.conf REBOOT_SCHEDULE_HOUR "$reboot_schedule_hour"
      rewrite_config /mnt/config/boot.conf REBOOT_SCHEDULE_WEEKDAY "$reboot_schedule_weekday"

      sync_managed_reboot_cron "$reboot_schedule_enable" "$reboot_schedule_minute" "$reboot_schedule_hour" "$reboot_schedule_weekday"
      restart_crond_if_enabled "$current_enable_crond"

      if [ "$reboot_schedule_enable" = "1" ]; then
        echo "Scheduled reboot enabled via cron: ${reboot_schedule_minute} ${reboot_schedule_hour} * * ${reboot_schedule_weekday}<br/>"
        if [ "$reboot_schedule_weekday" = "*" ]; then
          echo "Reboot will run daily at $(printf '%02d:%02d' "$reboot_schedule_hour" "$reboot_schedule_minute").<br/>"
        else
          echo "Reboot will run weekly pattern '$reboot_schedule_weekday' at $(printf '%02d:%02d' "$reboot_schedule_hour" "$reboot_schedule_minute").<br/>"
        fi
      else
        echo "Scheduled reboot disabled. Managed cron entry removed.<br/>"
      fi

      if [ "$current_enable_crond" = "1" ]; then
        echo "Crond is enabled and cron schedule has been reloaded.<br/>"
      else
        echo "Warning: crond is disabled in boot config. Enable ENABLE_CROND=1 for schedules to run.<br/>"
      fi

      _ac_now
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"reboot_schedule","enabled":%s,"minute":%s,"hour":%s,"weekday":"%s"}' "$now_ts" "$reboot_schedule_enable" "$reboot_schedule_minute" "$reboot_schedule_hour" "$reboot_schedule_weekday")"
    ;;

    set_stream_topology)
      install_config /mnt/config/boot.conf
      capture_prechange_stream_snapshot
      topology=$(printf '%s' "${F_stream_topology}")
      case "$topology" in
        dual-audio)
          rtsp_substream=1
          rtsp_audio=1
          topology_label="Dual stream + audio"
          ;;
        dual-no-audio)
          rtsp_substream=1
          rtsp_audio=0
          topology_label="Dual stream, audio disabled"
          ;;
        main-audio)
          rtsp_substream=0
          rtsp_audio=1
          topology_label="Main stream + audio"
          ;;
        main-only)
          rtsp_substream=0
          rtsp_audio=0
          topology_label="Main stream only (lowest CPU)"
          ;;
        *)
          echo "Unknown stream topology '$topology'<br/>"
          exit 0
          ;;
      esac

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      if finalize_stream_apply "stream-topology:${topology}"; then
        echo "Stream topology set to: $topology_label<br/>"
      fi
    ;;

    set_onvif_stream_policy)
      install_config /mnt/config/boot.conf
      capture_prechange_stream_snapshot
      # shellcheck disable=SC1090
      if [ -f /mnt/config/boot.conf ]; then
        . /mnt/config/boot.conf
      fi

      policy=$(printf '%s' "${F_onvif_stream_policy}")
      case "$policy" in
        main-primary)
          policy_label="Main primary (default)"
          ;;
        sub-primary)
          policy_label="Substream primary"
          ;;
        sub-only)
          policy_label="Substream only"
          ;;
        main-only)
          policy_label="Main only"
          ;;
        *)
          echo "Unknown ONVIF stream policy '$policy'<br/>"
          exit 0
          ;;
      esac

      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$policy"
      if finalize_stream_apply "onvif-policy:${policy}"; then
        echo "ONVIF stream policy set to: $policy_label<br/>"
        if [ "$RTSP_SUBSTREAM" != "1" ] && [ "$policy" != "main-primary" ] && [ "$policy" != "main-only" ]; then
          echo "Note: RTSP substream is disabled, ONVIF will fall back to main stream.<br/>"
        fi
      fi
    ;;

    refresh_ha_discovery)
      csrf_check
      if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
        /mnt/scripts/mqtt-bridge.sh discovery > /dev/null 2>&1
        if wants_json_response; then
          json_body_ok "Home Assistant Discovery refresh triggered."
        else
          echo "Home Assistant Discovery refresh triggered.<br/>"
        fi
      else
        if wants_json_response; then
          json_body_err "BRIDGE_MISSING" "MQTT bridge script missing."
        else
          echo "Error: MQTT bridge script missing.<br/>"
        fi
      fi
    ;;

    set_mqtt_config)
      csrf_check
      install_config /mnt/config/mqtt.conf

      mqtt_enable=$(normalize_bool "${F_mqtt_enable}")
      mqtt_host=$(printf '%s' "${F_mqtt_host}")
      mqtt_port=$(sanitize_int_range "${F_mqtt_port}" 1 65535 1883)
      mqtt_user=$(printf '%s' "${F_mqtt_user}")
      mqtt_password=$(printf '%s' "${F_mqtt_password}")
      mqtt_client_id=$(printf '%s' "${F_mqtt_client_id}")
      mqtt_topic_root=$(printf '%s' "${F_mqtt_topic_root}")
      mqtt_topic_command=$(printf '%s' "${F_mqtt_topic_command}")
      mqtt_qos=$(sanitize_int_range "${F_mqtt_qos}" 0 2 0)
      mqtt_health_interval_seconds=$(sanitize_int_range "${F_mqtt_health_interval_seconds}" 10 86400 120)
      mqtt_health_slow_cache_ttl_seconds=$(sanitize_int_range "$(read_kv_or_default /mnt/config/mqtt.conf MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS 180)" 10 86400 180)
      mqtt_command_wait_seconds=$(sanitize_int_range "${F_mqtt_command_wait_seconds}" 3 120 12)
      mqtt_command_repeat_window_seconds=$(sanitize_int_range "${F_mqtt_command_repeat_window_seconds}" 0 600 20)
      mqtt_subscribe_backoff_initial_seconds=$(sanitize_int_range "${F_mqtt_subscribe_backoff_initial_seconds:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS 2)}" 1 60 2)
      mqtt_subscribe_backoff_max_seconds=$(sanitize_int_range "${F_mqtt_subscribe_backoff_max_seconds:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS 20)}" 1 600 20)
      mqtt_subscribe_backoff_multiplier=$(sanitize_int_range "${F_mqtt_subscribe_backoff_multiplier:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER 2)}" 1 5 2)
      mqtt_ha_discovery_enable=$(normalize_bool "${F_mqtt_ha_discovery_enable}")
      mqtt_ha_discovery_prefix=$(printf '%s' "${F_mqtt_ha_discovery_prefix}")
      power_estimate_enable=$(normalize_bool "${F_power_estimate_enable}")
      power_estimate_base_mw=$(sanitize_int_range "${F_power_estimate_base_mw}" 500 10000 1700)
      power_estimate_cpu_scale_mw=$(sanitize_int_range "${F_power_estimate_cpu_scale_mw}" 0 5000 500)
      power_estimate_ir_led_mw=$(sanitize_int_range "${F_power_estimate_ir_led_mw}" 0 5000 700)
      power_sensor_path=$(printf '%s' "${F_power_sensor_path}")

      case "$mqtt_host" in
        ''|*[!A-Za-z0-9._:-]*)
          echo "Invalid broker host. Allowed characters: letters, numbers, dot, dash, underscore, colon.<br/>"
          exit 0
          ;;
      esac

      mqtt_client_id="$(printf '%s' "$mqtt_client_id" | sed 's/[^A-Za-z0-9._-]/-/g')"
      [ -n "$mqtt_client_id" ] || mqtt_client_id="tc100-camera"

      mqtt_topic_root="$(printf '%s' "$mqtt_topic_root" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      [ -n "$mqtt_topic_root" ] || mqtt_topic_root="tc100/camera"

      mqtt_topic_command="$(printf '%s' "$mqtt_topic_command" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      if [ -z "$mqtt_topic_command" ]; then
        mqtt_topic_command="${mqtt_topic_root}/command"
      fi

      mqtt_ha_discovery_prefix="$(printf '%s' "$mqtt_ha_discovery_prefix" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      [ -n "$mqtt_ha_discovery_prefix" ] || mqtt_ha_discovery_prefix="homeassistant"

      case "$power_sensor_path" in
        ''|auto)
          power_sensor_path="auto"
          ;;
        /*)
          power_sensor_path="$(printf '%s' "$power_sensor_path" | sed 's#[^A-Za-z0-9._/-]##g')"
          [ -n "$power_sensor_path" ] || power_sensor_path="auto"
          ;;
        *)
          power_sensor_path="auto"
          ;;
      esac

      rewrite_config /mnt/config/mqtt.conf MQTT_ENABLE "$mqtt_enable"
      rewrite_config /mnt/config/mqtt.conf MQTT_HOST "$mqtt_host"
      rewrite_config /mnt/config/mqtt.conf MQTT_PORT "$mqtt_port"
      rewrite_config /mnt/config/mqtt.conf MQTT_USER "$mqtt_user"
      rewrite_config /mnt/config/mqtt.conf MQTT_PASSWORD "$mqtt_password"
      rewrite_config /mnt/config/mqtt.conf MQTT_CLIENT_ID "$mqtt_client_id"
      rewrite_config /mnt/config/mqtt.conf MQTT_TOPIC_ROOT "$mqtt_topic_root"
      rewrite_config /mnt/config/mqtt.conf MQTT_TOPIC_COMMAND "$mqtt_topic_command"
      rewrite_config /mnt/config/mqtt.conf MQTT_QOS "$mqtt_qos"
      rewrite_config /mnt/config/mqtt.conf MQTT_HEALTH_INTERVAL_SECONDS "$mqtt_health_interval_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS "$mqtt_health_slow_cache_ttl_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_COMMAND_WAIT_SECONDS "$mqtt_command_wait_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_COMMAND_REPEAT_WINDOW_SECONDS "$mqtt_command_repeat_window_seconds"
      if [ "$mqtt_subscribe_backoff_max_seconds" -lt "$mqtt_subscribe_backoff_initial_seconds" ]; then
        mqtt_subscribe_backoff_max_seconds="$mqtt_subscribe_backoff_initial_seconds"
      fi
      rewrite_config /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS "$mqtt_subscribe_backoff_initial_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS "$mqtt_subscribe_backoff_max_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER "$mqtt_subscribe_backoff_multiplier"
      rewrite_config /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_ENABLE "$mqtt_ha_discovery_enable"
      rewrite_config /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_PREFIX "$mqtt_ha_discovery_prefix"
      rewrite_config /mnt/config/mqtt.conf POWER_ESTIMATE_ENABLE "$power_estimate_enable"
      rewrite_config /mnt/config/mqtt.conf POWER_ESTIMATE_BASE_MW "$power_estimate_base_mw"
      rewrite_config /mnt/config/mqtt.conf POWER_ESTIMATE_CPU_SCALE_MW "$power_estimate_cpu_scale_mw"
      rewrite_config /mnt/config/mqtt.conf POWER_ESTIMATE_IR_LED_MW "$power_estimate_ir_led_mw"
      rewrite_config /mnt/config/mqtt.conf POWER_SENSOR_PATH "$power_sensor_path"

      if [ -x /mnt/controlscripts/mqtt-bridge ]; then
        if [ "$mqtt_enable" = "1" ]; then
          /mnt/controlscripts/mqtt-bridge stop >/dev/null 2>&1 || true
          /mnt/controlscripts/mqtt-bridge start >/dev/null 2>&1 || true
        else
          /mnt/controlscripts/mqtt-bridge stop >/dev/null 2>&1 || true
        fi
      fi

      echo "MQTT bridge configuration saved.<br/>"
      echo "Enabled=$mqtt_enable, broker=${mqtt_host}:${mqtt_port}, topic_root=${mqtt_topic_root}, command_topic=${mqtt_topic_command}, qos=${mqtt_qos}, dedupe_window=${mqtt_command_repeat_window_seconds}s<br/>"
      echo "Retry backoff: initial=${mqtt_subscribe_backoff_initial_seconds}s, max=${mqtt_subscribe_backoff_max_seconds}s, multiplier=x${mqtt_subscribe_backoff_multiplier}<br/>"
      echo "HA discovery=${mqtt_ha_discovery_enable} (prefix=${mqtt_ha_discovery_prefix}), power_estimate=${power_estimate_enable}, base=${power_estimate_base_mw}mW, cpu_scale=${power_estimate_cpu_scale_mw}mW, ir_led=${power_estimate_ir_led_mw}mW<br/>"
      rm -f /tmp/health_snapshot.cache 2>/dev/null || true
    ;;

    pair_home_assistant)
      install_config /mnt/config/boot.conf
      install_config /mnt/config/mqtt.conf

      ha_broker_host="$(printf '%s' "${F_ha_broker_host}")"
      ha_broker_port="$(sanitize_int_range "${F_ha_broker_port}" 1 65535 1883)"
      ha_user="$(printf '%s' "${F_ha_user}")"
      ha_password="$(printf '%s' "${F_ha_password}")"
      ha_client_id="$(printf '%s' "${F_ha_client_id}")"
      ha_topic_root="$(printf '%s' "${F_ha_topic_root}")"
      ha_discovery_prefix="$(printf '%s' "${F_ha_discovery_prefix}")"
      ha_profile="$(printf '%s' "${F_ha_profile}")"
      ha_enable_onvif="$(normalize_bool "${F_ha_enable_onvif}")"
      ha_enable_mqtt_autostart="$(normalize_bool "${F_ha_enable_mqtt_autostart}")"

      case "$ha_broker_host" in
        ''|*[!A-Za-z0-9._:-]*)
          echo "Invalid broker host. Allowed characters: letters, numbers, dot, dash, underscore, colon.<br/>"
          exit 0
          ;;
      esac

      ha_client_id="$(printf '%s' "$ha_client_id" | sed 's/[^A-Za-z0-9._-]/-/g')"
      [ -n "$ha_client_id" ] || ha_client_id="tc100-camera"

      ha_topic_root="$(printf '%s' "$ha_topic_root" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      [ -n "$ha_topic_root" ] || ha_topic_root="tc100/camera"

      ha_discovery_prefix="$(printf '%s' "$ha_discovery_prefix" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      [ -n "$ha_discovery_prefix" ] || ha_discovery_prefix="homeassistant"

      [ -n "$ha_profile" ] || ha_profile="frigate-balanced"
      if ! select_compat_profile_values "$ha_profile"; then
        echo "Unknown compatibility preset '$ha_profile'<br/>"
        exit 0
      fi

      ha_topic_command="${ha_topic_root}/command"

      rewrite_config /mnt/config/mqtt.conf MQTT_ENABLE 1
      rewrite_config /mnt/config/mqtt.conf MQTT_HOST "$ha_broker_host"
      rewrite_config /mnt/config/mqtt.conf MQTT_PORT "$ha_broker_port"
      rewrite_config /mnt/config/mqtt.conf MQTT_USER "$ha_user"
      rewrite_config /mnt/config/mqtt.conf MQTT_PASSWORD "$ha_password"
      rewrite_config /mnt/config/mqtt.conf MQTT_CLIENT_ID "$ha_client_id"
      rewrite_config /mnt/config/mqtt.conf MQTT_TOPIC_ROOT "$ha_topic_root"
      rewrite_config /mnt/config/mqtt.conf MQTT_TOPIC_COMMAND "$ha_topic_command"
      rewrite_config /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_ENABLE 1
      rewrite_config /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_PREFIX "$ha_discovery_prefix"

      capture_prechange_stream_snapshot
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          0 width        "$width0" \
          0 height       "$height0" \
          0 fps          "$fps0" \
          0 bps          "$bps0" \
          0 goplen       "$gop0" \
          0 brmode       1 \
          0 codec        "$codec0" \
          0 profile      "$profile0" \
          0 smartmode    1 \
          0 smartgoplen  "$gop0" \
          0 smartquality "$smartq0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 width        "$width1" \
          1 height       "$height1" \
          1 fps          "$fps1" \
          1 bps          "$bps1" \
          1 goplen       "$gop1" \
          1 brmode       1 \
          1 codec        "$codec1" \
          1 profile      "$profile1" \
          1 smartmode    1 \
          1 smartgoplen  "$gop1" \
          1 smartquality "$smartq1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      if [ "$rtsp_audio" = "0" ]; then
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w 2 codec 0 3 codec 0
      fi

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$onvif_policy"
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0
      rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE "$low_cpu_profile"
      if finalize_stream_apply "ha-pair:${ha_profile}"; then
        if [ "$low_cpu_profile" = "1" ]; then
          apply_low_cpu_background_defaults
        fi

        ensure_autostart_script rtsp-h26x >/dev/null 2>&1 || true
        /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1 || true

        if [ "$ha_enable_onvif" = "1" ]; then
          ensure_autostart_script onvif >/dev/null 2>&1 || true
          /mnt/controlscripts/onvif start >/dev/null 2>&1 || true
        else
          rm -f /mnt/config/autostart/onvif >/dev/null 2>&1 || true
          /mnt/controlscripts/onvif stop >/dev/null 2>&1 || true
        fi

        if [ "$ha_enable_mqtt_autostart" = "1" ]; then
          ensure_autostart_script mqtt-bridge >/dev/null 2>&1 || true
        else
          rm -f /mnt/config/autostart/mqtt-bridge >/dev/null 2>&1 || true
        fi
        if [ -x /mnt/controlscripts/mqtt-bridge ]; then
          /mnt/controlscripts/mqtt-bridge stop >/dev/null 2>&1 || true
          /mnt/controlscripts/mqtt-bridge start >/dev/null 2>&1 || true
        fi

        rtsp_health_ok=0
        onvif_health_ok=0
        mqtt_publish_ok=0

        if [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x health >/dev/null 2>&1; then
          rtsp_health_ok=1
        fi
        if [ "$ha_enable_onvif" = "1" ] && [ -x /mnt/controlscripts/onvif ] && /mnt/controlscripts/onvif health >/dev/null 2>&1; then
          onvif_health_ok=1
        fi

        _ac_now
        [ -n "$now_ts" ] || now_ts=0
        mqtt_test_payload="$(printf '{"ts":%s,"type":"ha_pair_test","profile":"%s"}' "$now_ts" "$ha_profile")"
        if [ -x /mnt/scripts/mqtt-bridge.sh ] && /mnt/scripts/mqtt-bridge.sh publish event "$mqtt_test_payload" 0 >/dev/null 2>&1; then
          mqtt_publish_ok=1
        fi

        echo "Home Assistant pairing applied.<br/>"
        echo "Compatibility preset: $profile_label<br/>"
        echo "Broker: ${ha_broker_host}:${ha_broker_port}, discovery prefix: ${ha_discovery_prefix}<br/>"
        echo "Topics: root=${ha_topic_root}, command=${ha_topic_command}<br/>"
        echo "Autostart: RTSP=on, ONVIF=${ha_enable_onvif}, MQTT=${ha_enable_mqtt_autostart}<br/>"
        if [ "$rtsp_health_ok" = "1" ]; then
          echo "RTSP health check: OK<br/>"
        else
          echo "RTSP health check: FAILED (check video profile/network)<br/>"
        fi
        if [ "$ha_enable_onvif" = "1" ]; then
          if [ "$onvif_health_ok" = "1" ]; then
            echo "ONVIF health check: OK<br/>"
          else
            echo "ONVIF health check: FAILED (check ONVIF service/network)<br/>"
          fi
        else
          echo "ONVIF health check: skipped (disabled)<br/>"
        fi
        if [ "$mqtt_publish_ok" = "1" ]; then
          echo "MQTT publish test: OK (discovery should republish at MQTT bridge start)<br/>"
        else
          echo "MQTT publish test: FAILED (check broker credentials/reachability)<br/>"
        fi
        echo "Quick links: /onvif/device_service, rtsp://CAMERA-IP:554/video0_unicast, rtsp://CAMERA-IP:554/video1_unicast<br/>"
        echo "Integration manifest: /cgi-bin/state.cgi?cmd=integrationmanifest<br/>"

        publish_mqtt_event "$(printf '{"ts":%s,"type":"ha_pair","profile":"%s","rtsp_ok":%s,"onvif_ok":%s,"mqtt_ok":%s}' "$now_ts" "$ha_profile" "$rtsp_health_ok" "$onvif_health_ok" "$mqtt_publish_ok")"
      fi
    ;;

    set_rtsp_preset)
      capture_prechange_stream_snapshot
      preset=$(printf '%s' "${F_preset}")
      case "$preset" in
        full)
          width0=1280; height0=720; fps0=25; bps0=2000; gop0=50; maxkbps0=2500; targetkbps0=2000; smartq0=100; smartstatic0=550
          width1=640;  height1=360; fps1=10; bps1=300;  gop1=20; maxkbps1=400;  targetkbps1=300;  smartq1=70;  smartstatic1=150
          ;;
        medium)
          width0=1280; height0=720; fps0=20; bps0=1200; gop0=40; maxkbps0=1500; targetkbps0=1200; smartq0=80; smartstatic0=450
          width1=352;  height1=200; fps1=8;  bps1=200;  gop1=16; maxkbps1=250;  targetkbps1=200;  smartq1=60; smartstatic1=120
          ;;
        low)
          width0=640;  height0=360; fps0=10; bps0=600;  gop0=20; maxkbps0=800;  targetkbps0=600;  smartq0=60; smartstatic0=350
          width1=352;  height1=200; fps1=5;  bps1=120;  gop1=10; maxkbps1=160;  targetkbps1=120;  smartq1=50; smartstatic1=100
          ;;
        *)
          echo "Unknown preset '$preset'<br/>"
          exit 0
          ;;
      esac

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          0 width        "$width0" \
          0 height       "$height0" \
          0 fps          "$fps0" \
          0 bps          "$bps0" \
          0 goplen       "$gop0" \
          0 brmode       1 \
          0 smartmode    1 \
          0 smartgoplen  "$gop0" \
          0 smartquality "$smartq0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 width        "$width1" \
          1 height       "$height1" \
          1 fps          "$fps1" \
          1 bps          "$bps1" \
          1 goplen       "$gop1" \
          1 brmode       1 \
          1 smartmode    1 \
          1 smartgoplen  "$gop1" \
          1 smartquality "$smartq1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      if finalize_stream_apply "rtsp-preset:${preset}"; then
        echo "RTSP preset applied: $preset (fps max 25)<br/>"
      fi
    ;;

    set_rtsp_quality_profile)
      install_config /mnt/config/boot.conf
      capture_prechange_stream_snapshot
      quality_profile=$(printf '%s' "${F_rtsp_quality_profile}")

      case "$quality_profile" in
        max-quality-h264)
          profile_label="Max quality 1080p H264 (recommended)"
          width0=1920; height0=1080; fps0=25; bps0=3600; gop0=50; maxkbps0=4500; targetkbps0=3600; smartq0=100; smartstatic0=620
          width1=640;  height1=360;  fps1=15; bps1=700;  gop1=30; maxkbps1=900;  targetkbps1=700;  smartq1=80; smartstatic1=240
          codec0=0; profile0=1
          codec1=0; profile1=0
          rtsp_substream=1
          rtsp_audio=1
          onvif_policy="main-primary"
          ;;
        max-quality-hevc)
          profile_label="Max quality 1080p H265/HEVC"
          width0=1920; height0=1080; fps0=25; bps0=3000; gop0=50; maxkbps0=3800; targetkbps0=3000; smartq0=100; smartstatic0=600
          width1=640;  height1=360;  fps1=12; bps1=550;  gop1=24; maxkbps1=760;  targetkbps1=550;  smartq1=78; smartstatic1=220
          codec0=2; profile0=3
          codec1=2; profile1=3
          rtsp_substream=1
          rtsp_audio=1
          onvif_policy="main-primary"
          ;;
        max-main-h264)
          profile_label="Max quality main-only H264"
          width0=1920; height0=1080; fps0=25; bps0=4200; gop0=50; maxkbps0=5200; targetkbps0=4200; smartq0=100; smartstatic0=650
          width1=352;  height1=200;  fps1=5;  bps1=120;  gop1=10; maxkbps1=180;  targetkbps1=120;  smartq1=50; smartstatic1=100
          codec0=0; profile0=1
          codec1=0; profile1=0
          rtsp_substream=0
          rtsp_audio=1
          onvif_policy="main-only"
          ;;
        *)
          echo "Unknown RTSP quality profile '$quality_profile'<br/>"
          exit 0
          ;;
      esac

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          0 width        "$width0" \
          0 height       "$height0" \
          0 fps          "$fps0" \
          0 bps          "$bps0" \
          0 goplen       "$gop0" \
          0 brmode       1 \
          0 codec        "$codec0" \
          0 profile      "$profile0" \
          0 smartmode    1 \
          0 smartgoplen  "$gop0" \
          0 smartquality "$smartq0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 width        "$width1" \
          1 height       "$height1" \
          1 fps          "$fps1" \
          1 bps          "$bps1" \
          1 goplen       "$gop1" \
          1 brmode       1 \
          1 codec        "$codec1" \
          1 profile      "$profile1" \
          1 smartmode    1 \
          1 smartgoplen  "$gop1" \
          1 smartquality "$smartq1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$onvif_policy"
      rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 0
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0

      if finalize_stream_apply "rtsp-quality:${quality_profile}"; then
        echo "RTSP quality profile applied: $profile_label<br/>"
        echo "Main=${width0}x${height0}@${fps0}fps codec=${codec0}, Sub=${width1}x${height1}@${fps1}fps codec=${codec1}<br/>"
        echo "RTSP_SUBSTREAM=$rtsp_substream, RTSP_AUDIO=$rtsp_audio, ONVIF_STREAM_POLICY=$onvif_policy<br/>"
      fi
    ;;

    set_client_profile)
      client_profile=$(printf '%s' "${F_client_profile}")
      install_config /mnt/config/boot.conf
      capture_prechange_stream_snapshot
      if ! select_compat_profile_values "$client_profile"; then
        echo "Unknown client profile '$client_profile'<br/>"
        exit 0
      fi

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          0 width        "$width0" \
          0 height       "$height0" \
          0 fps          "$fps0" \
          0 bps          "$bps0" \
          0 goplen       "$gop0" \
          0 brmode       1 \
          0 codec        "$codec0" \
          0 profile      "$profile0" \
          0 smartmode    1 \
          0 smartgoplen  "$gop0" \
          0 smartquality "$smartq0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 width        "$width1" \
          1 height       "$height1" \
          1 fps          "$fps1" \
          1 bps          "$bps1" \
          1 goplen       "$gop1" \
          1 brmode       1 \
          1 codec        "$codec1" \
          1 profile      "$profile1" \
          1 smartmode    1 \
          1 smartgoplen  "$gop1" \
          1 smartquality "$smartq1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      if [ "$rtsp_audio" = "0" ]; then
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w 2 codec 0 3 codec 0
      fi

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$onvif_policy"
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0
      rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE "$low_cpu_profile"

      if finalize_stream_apply "compat-profile:${client_profile}"; then
        if [ "$low_cpu_profile" = "1" ]; then
          apply_low_cpu_background_defaults
        fi
        echo "Compatibility preset applied: $profile_label<br/>"
        echo "RTSP_SUBSTREAM=$rtsp_substream, RTSP_AUDIO=$rtsp_audio, ONVIF_STREAM_POLICY=$onvif_policy<br/>"
        echo "Main=${width0}x${height0}@${fps0}fps, Sub=${width1}x${height1}@${fps1}fps<br/>"
        _ac_now
        [ -n "$now_ts" ] || now_ts=0
        publish_mqtt_event "$(printf '{"ts":%s,"type":"client_profile","value":"%s"}' "$now_ts" "$client_profile")"
      fi
    ;;

    save_known_good_profile)
      if save_known_good_snapshot "manual:web-ui"; then
        saved_ts="$(read_kv_or_default "$KNOWN_GOOD_STREAM_CONF" TS 0)"
        echo "Known-good snapshot saved.<br/>"
        echo "Timestamp (epoch): ${saved_ts}<br/>"
      else
        echo "Failed to save known-good snapshot.<br/>"
      fi
    ;;

    restore_known_good_profile)
      capture_prechange_stream_snapshot
      if restore_stream_from_snapshot "$KNOWN_GOOD_RTSP_CONF" "$KNOWN_GOOD_STREAM_CONF"; then
        restore_reason="$(read_kv_or_default "$KNOWN_GOOD_STREAM_CONF" REASON unknown)"
        restore_ts="$(read_kv_or_default "$KNOWN_GOOD_STREAM_CONF" TS 0)"
        echo "Known-good snapshot restored.<br/>"
        echo "Source: ${restore_reason} (ts=${restore_ts})<br/>"
      else
        echo "Known-good restore failed.<br/>"
        if restore_stream_from_snapshot "$PRECHANGE_RTSP_CONF" "$PRECHANGE_STREAM_CONF"; then
          echo "Reverted to pre-restore snapshot.<br/>"
        fi
      fi
    ;;
    
    set_led_config)
      install_config /mnt/config/boot.conf
      led_front=$(normalize_bool "${F_led_front}")
      led_red=$(normalize_bool "${F_led_red}")
      
      rewrite_config /mnt/config/boot.conf FRONT_LED "$led_front"
      rewrite_config /mnt/config/boot.conf RED_LED "$led_red"
      
      [ "$led_front" = "1" ] && /mnt/controlscripts/front-led start || /mnt/controlscripts/front-led stop
      [ "$led_red" = "1" ] && /mnt/controlscripts/red-led start || /mnt/controlscripts/red-led stop
      
      echo "LED configuration updated.<br/>"
    ;;

    set_telegram_config)
      install_config /mnt/config/telegram.conf
      telegram_enable=$(normalize_bool "${F_telegram_enable}")
      telegram_token=$(printf '%s' "${F_telegram_token}")
      telegram_chat_id=$(printf '%s' "${F_telegram_chat_id}")
      
      rewrite_config /mnt/config/telegram.conf TELEGRAM_ENABLE "$telegram_enable"
      rewrite_config /mnt/config/telegram.conf apiToken "$telegram_token"
      rewrite_config /mnt/config/telegram.conf userChatId "$telegram_chat_id"
      
      if [ -x /mnt/controlscripts/telegram-bot ]; then
        if [ "$telegram_enable" = "1" ]; then
          /mnt/controlscripts/telegram-bot restart >/dev/null 2>&1 || true
        else
          /mnt/controlscripts/telegram-bot stop >/dev/null 2>&1 || true
        fi
      fi
      echo "Telegram configuration updated.<br/>"
    ;;

    set_syslog_config)
      install_config /mnt/config/boot.conf
      syslog_enable=$(normalize_bool "${F_syslog_enable}")
      syslog_host=$(printf '%s' "${F_syslog_host}")
      syslog_port=$(sanitize_int_range "${F_syslog_port}" 1 65535 514)
      
      rewrite_config /mnt/config/boot.conf SYSLOG_ENABLE "$syslog_enable"
      rewrite_config /mnt/config/boot.conf SYSLOG_HOST "$syslog_host"
      rewrite_config /mnt/config/boot.conf SYSLOG_PORT "$syslog_port"
      
      if [ -x /mnt/controlscripts/syslog-forward ]; then
        if [ "$syslog_enable" = "1" ]; then
          /mnt/controlscripts/syslog-forward restart >/dev/null 2>&1 || true
        else
          /mnt/controlscripts/syslog-forward stop >/dev/null 2>&1 || true
        fi
      fi
      echo "Syslog configuration updated.<br/>"
    ;;

    enable_privacy_shield)
      install_config /mnt/config/boot.conf
      # Privacy Shield: Stop all non-essential outbound/inbound services.
      for svc in telegram-bot syslog-forward mqtt-bridge ftp-server telnet-server; do
        if [ -x "/mnt/controlscripts/$svc" ]; then
          "/mnt/controlscripts/$svc" stop >/dev/null 2>&1 || true
        fi
      done
      rewrite_config /mnt/config/boot.conf PRIVACY_MODE 1
      echo "Privacy Shield activated: Cloud & outbound services disabled.<br/>"
      _ac_now
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"privacy_shield","enabled":1}' "$now_ts")"
    ;;

    complete_setup_wizard)
      csrf_check
      if wants_json_response; then
        json_body_err "FORMAT_NOT_SUPPORTED" "complete_setup_wizard command does not support JSON format"
      else
        install_config /mnt/config/boot.conf
      install_config /mnt/config/service_trim.conf
      wizard_password=$(printf '%b' "${F_wizard_password//%/\\x}")
      wizard_profile=$(printf '%s' "${F_wizard_profile}")
      wizard_tz=$(printf '%b' "${F_wizard_tz//%/\\x}")
      wizard_ntp_srv=$(printf '%b' "${F_wizard_ntp_srv//%/\\x}")
      wizard_hostname=$(printf '%b' "${F_wizard_hostname//%/\\x}")
      wizard_enable_ntp=$(normalize_bool "${F_wizard_enable_ntp}")

      [ -n "$wizard_profile" ] || wizard_profile="universal-h264"

      case "$wizard_password" in
        ''|'*****')
          wizard_password=""
          ;;
      esac

      if credentials_default_active; then
        if [ -z "$wizard_password" ] || [ "$wizard_password" = "pass" ]; then
          echo "Setup wizard requires changing default credentials before completion.<br/>"
          exit 0
        fi
      fi

      if [ -n "$wizard_password" ] && [ "${#wizard_password}" -lt 4 ]; then
        echo "Password too short. Use at least 4 characters.<br/>"
        exit 0
      fi

      capture_prechange_stream_snapshot
      if ! select_compat_profile_values "$wizard_profile"; then
        echo "Unknown compatibility preset '$wizard_profile'<br/>"
        exit 0
      fi

      if [ -n "$wizard_password" ]; then
        all_password "$wizard_password"
        restart_service_if_need /mnt/controlscripts/ftp-server
        restart_service_if_need /mnt/controlscripts/telnet-server
        echo "All service passwords updated.<br/>"
      fi

      if [ -z "$wizard_tz" ]; then
        wizard_tz="$(cat /mnt/config/timezone.conf 2>/dev/null)"
      fi
      [ -n "$wizard_tz" ] || wizard_tz="UTC0"
      echo "$wizard_tz" > /mnt/config/timezone.conf

      wizard_ntp_srv="$(printf '%s' "$wizard_ntp_srv" | sed 's/[^A-Za-z0-9._:-]//g')"
      if [ -z "$wizard_ntp_srv" ]; then
        wizard_ntp_srv="$(cat /mnt/config/ntp_srv.conf 2>/dev/null)"
      fi
      [ -n "$wizard_ntp_srv" ] || wizard_ntp_srv="pool.ntp.org"
      echo "$wizard_ntp_srv" > /mnt/config/ntp_srv.conf

      wizard_hostname="$(printf '%s' "$wizard_hostname" | sed 's/[^A-Za-z0-9._-]//g')"
      if [ -n "$wizard_hostname" ]; then
        echo "$wizard_hostname" > /mnt/config/hostname.conf
        hostname "$wizard_hostname" >/dev/null 2>&1 || true
      fi

      rewrite_config /mnt/config/boot.conf ENABLE_NTP "$wizard_enable_ntp"
      if [ "$wizard_enable_ntp" = "1" ]; then
        if /mnt/bin/busybox ntpd -q -n -p "$wizard_ntp_srv" >/dev/null 2>&1; then
          echo "NTP sync successful.<br/>"
        else
          echo "NTP sync failed (check server/network).<br/>"
        fi
      fi

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          0 width        "$width0" \
          0 height       "$height0" \
          0 fps          "$fps0" \
          0 bps          "$bps0" \
          0 goplen       "$gop0" \
          0 brmode       1 \
          0 codec        "$codec0" \
          0 profile      "$profile0" \
          0 smartmode    1 \
          0 smartgoplen  "$gop0" \
          0 smartquality "$smartq0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 width        "$width1" \
          1 height       "$height1" \
          1 fps          "$fps1" \
          1 bps          "$bps1" \
          1 goplen       "$gop1" \
          1 brmode       1 \
          1 codec        "$codec1" \
          1 profile      "$profile1" \
          1 smartmode    1 \
          1 smartgoplen  "$gop1" \
          1 smartquality "$smartq1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      if [ "$rtsp_audio" = "0" ]; then
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w 2 codec 0 3 codec 0
      fi

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$onvif_policy"
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0
      rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE "$low_cpu_profile"

      if finalize_stream_apply "setup-wizard:${wizard_profile}"; then
        _ac_now
        [ -n "$now_ts" ] || now_ts=0
        rewrite_config /mnt/config/boot.conf SETUP_WIZARD_DONE 1
        rewrite_config /mnt/config/boot.conf SETUP_WIZARD_EPOCH "$now_ts"
        if [ "$low_cpu_profile" = "1" ]; then
          apply_low_cpu_background_defaults
        fi
        echo "Setup wizard completed.<br/>"
        echo "Compatibility preset: $profile_label<br/>"
        echo "Timezone: $wizard_tz, NTP: $wizard_ntp_srv (ENABLE_NTP=$wizard_enable_ntp)<br/>"
        publish_mqtt_event "$(printf '{"ts":%s,"type":"setup_wizard","profile":"%s"}' "$now_ts" "$wizard_profile")"
      fi
      fi
    ;;

    set_video_size)
      capture_prechange_stream_snapshot
      safe_values_changed=0
      wh0=${F_video_size0}
      width0="${wh0%x*}"
      height0="${wh0#*x}"
      req_width0="$width0"
      req_height0="$height0"

      wh1=${F_video_size1}
      width1="${wh1%x*}"
      height1="${wh1#*x}"
      req_width1="$width1"
      req_height1="$height1"

      codec0="$(sanitize_video_codec "${F_video_codec0}")"
      codec1="$(sanitize_video_codec "${F_video_codec1}")"

      normalize_stream_geometry "$width0" "$height0" "$codec0" 1280 720
      width0="$NORMALIZED_STREAM_WIDTH"
      height0="$NORMALIZED_STREAM_HEIGHT"
      codec0="$NORMALIZED_STREAM_CODEC"

      normalize_stream_geometry "$width1" "$height1" "$codec1" 352 200
      width1="$NORMALIZED_STREAM_WIDTH"
      height1="$NORMALIZED_STREAM_HEIGHT"
      codec1="$NORMALIZED_STREAM_CODEC"

      username=$(printf '%b' "${F_videouser//%/\\x}")
      userpassword=$(printf '%b' "${F_videopassword//%/\\x}")
      videoport="$(sanitize_int_range "${F_videoport}" 1 65535 554)"

      bps0="$(sanitize_int_range "${F_brbitrate0}" 64 12000 2000)"
      bps1="$(sanitize_int_range "${F_brbitrate1}" 64 4000 300)"
      brmode0="$(sanitize_video_brmode "${F_video_format0}")"
      brmode1="$(sanitize_video_brmode "${F_video_format1}")"
      fps0="$(sanitize_int_range "${F_fps0}" 1 25 20)"
      fps1="$(sanitize_int_range "${F_fps1}" 1 25 10)"
      goplen0="$(sanitize_int_range "${F_goplen0}" 1 120 50)"
      goplen1="$(sanitize_int_range "${F_goplen1}" 1 120 20)"
      minqp0="$(sanitize_int_range "${F_minqp0}" 1 51 20)"
      minqp1="$(sanitize_int_range "${F_minqp1}" 1 51 20)"
      maxqp0="$(sanitize_int_range "${F_maxqp0}" 1 51 51)"
      maxqp1="$(sanitize_int_range "${F_maxqp1}" 1 51 51)"
      if [ "$minqp0" -gt "$maxqp0" ]; then
        minqp0="$maxqp0"
      fi
      if [ "$minqp1" -gt "$maxqp1" ]; then
        minqp1="$maxqp1"
      fi
      profile0="$(sanitize_codec_profile_for_codec "$codec0" "${F_codec_profile0}" 0)"
      profile1="$(sanitize_codec_profile_for_codec "$codec1" "${F_codec_profile1}" 1)"
      smartmode0="$(sanitize_video_smartmode "${F_smartmode0}")"
      smartmode1="$(sanitize_video_smartmode "${F_smartmode1}")"
      smartgoplen0="$(sanitize_int_range "${F_smartgoplen0}" 1 600 "$goplen0")"
      smartgoplen1="$(sanitize_int_range "${F_smartgoplen1}" 1 600 "$goplen1")"
      smartquality0="$(sanitize_int_range "${F_smartquality0}" 1 100 80)"
      smartquality1="$(sanitize_int_range "${F_smartquality1}" 1 100 65)"
      smartstatic0="$(sanitize_int_range "${F_smartstatic0}" 0 1000 550)"
      smartstatic1="$(sanitize_int_range "${F_smartstatic1}" 0 1000 150)"
      maxkbps0="$(sanitize_int_range "${F_maxkbps0}" 64 12000 "$bps0")"
      maxkbps1="$(sanitize_int_range "${F_maxkbps1}" 64 4000 "$bps1")"
      targetkbps0="$(sanitize_int_range "${F_targetkbps0}" 64 12000 "$bps0")"
      targetkbps1="$(sanitize_int_range "${F_targetkbps1}" 64 4000 "$bps1")"
      if [ "$targetkbps0" -gt "$maxkbps0" ]; then
        targetkbps0="$maxkbps0"
      fi
      if [ "$targetkbps1" -gt "$maxkbps1" ]; then
        targetkbps1="$maxkbps1"
      fi

      echo "Video resolution set to $wh0 and $wh1<br/>"
      if [ "$req_width0" != "$width0" ] || [ "$req_height0" != "$height0" ] || [ "${F_video_codec0}" != "$codec0" ]; then
        echo "Main stream normalized to ${width0}x${height0} (codec=${codec0}) for encoder safety.<br/>"
      fi
      if [ "$req_width1" != "$width1" ] || [ "$req_height1" != "$height1" ] || [ "${F_video_codec1}" != "$codec1" ]; then
        echo "Sub stream normalized to ${width1}x${height1} (codec=${codec1}) for encoder safety.<br/>"
      fi
      if [ "${F_videoport}" != "$videoport" ] || [ "${F_brbitrate0}" != "$bps0" ] || [ "${F_brbitrate1}" != "$bps1" ] || [ "${F_video_format0}" != "$brmode0" ] || [ "${F_video_format1}" != "$brmode1" ] || [ "${F_fps0}" != "$fps0" ] || [ "${F_fps1}" != "$fps1" ] || [ "${F_goplen0}" != "$goplen0" ] || [ "${F_goplen1}" != "$goplen1" ] || [ "${F_minqp0}" != "$minqp0" ] || [ "${F_minqp1}" != "$minqp1" ] || [ "${F_maxqp0}" != "$maxqp0" ] || [ "${F_maxqp1}" != "$maxqp1" ] || [ "${F_codec_profile0}" != "$profile0" ] || [ "${F_codec_profile1}" != "$profile1" ] || [ "${F_smartmode0}" != "$smartmode0" ] || [ "${F_smartmode1}" != "$smartmode1" ] || [ "${F_smartgoplen0}" != "$smartgoplen0" ] || [ "${F_smartgoplen1}" != "$smartgoplen1" ] || [ "${F_smartquality0}" != "$smartquality0" ] || [ "${F_smartquality1}" != "$smartquality1" ] || [ "${F_smartstatic0}" != "$smartstatic0" ] || [ "${F_smartstatic1}" != "$smartstatic1" ] || [ "${F_maxkbps0}" != "$maxkbps0" ] || [ "${F_maxkbps1}" != "$maxkbps1" ] || [ "${F_targetkbps0}" != "$targetkbps0" ] || [ "${F_targetkbps1}" != "$targetkbps1" ]; then
        safe_values_changed=1
      fi
      if [ "$safe_values_changed" = "1" ]; then
        echo "One or more advanced fields were sanitized to safe ranges/profile combinations.<br/>"
      fi

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " USERNAME "${username}" \
          " " USERPASSWORD "${userpassword}" \
          " " PORT "$videoport" \
          0 bps          "$bps0" \
          0 brmode       "$brmode0" \
          0 codec        "$codec0" \
          0 fps          "$fps0" \
          0 goplen       "$goplen0" \
          0 height       "$height0" \
          0 maxqp        "$maxqp0" \
          0 minqp        "$minqp0" \
          0 profile      "$profile0" \
          0 width        "$width0" \
          0 smartmode    "$smartmode0" \
          0 smartgoplen  "$smartgoplen0" \
          0 smartquality "$smartquality0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 bps          "$bps1" \
          1 brmode       "$brmode1" \
          1 codec        "$codec1" \
          1 fps          "$fps1" \
          1 goplen       "$goplen1" \
          1 height       "$height1" \
          1 maxqp        "$maxqp1" \
          1 minqp        "$minqp1" \
          1 profile      "$profile1" \
          1 width        "$width1" \
          1 smartmode    "$smartmode1" \
          1 smartgoplen  "$smartgoplen1" \
          1 smartquality "$smartquality1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      if ! finalize_stream_apply "manual-video-settings"; then
        echo "Manual video settings were rolled back.<br/>"
      fi
    ;;


    conf_timelapse)
      tlinterval=$(printf '%s' "${F_tlinterval}")
      tlinterval=$(echo "$tlinterval" | sed "s/[^0-9\.]//g")
      if [ "$tlinterval" ]; then
        rewrite_config /mnt/config/timelapse.conf TIMELAPSE_INTERVAL "$tlinterval"
        echo "Timelapse interval set to $tlinterval seconds."
      else
        echo "Invalid timelapse interval"
      fi
      tlduration=$(printf '%s' "${F_tlduration}")
      tlduration=$(echo "$tlduration" | sed "s/[^0-9\.]//g")
      if [ "$tlduration" ]; then
        rewrite_config /mnt/config/timelapse.conf TIMELAPSE_DURATION "$tlduration"
        echo "Timelapse duration set to $tlduration minutes."
      else
        echo "Invalid timelapse duration"
      fi
    ;;

    conf_recording)
      # SECURITY: recording.conf is sourced as root by controlscripts/recording
      # (`. $CONFIGPATH/recording.conf`). These four values MUST be validated to
      # bare bool/integers before being written, otherwise a newline or backtick
      # in the POST body lands in the sourced file and executes as root. The
      # sibling conf_dns/conf_static_ip handlers already validate; this one did
      # not. normalize_bool/sanitize_int_range strip anything non-numeric.
      motion_act="$(normalize_bool "${F_motion_act}")"
      postrec="$(sanitize_int_range "${F_postrec}" 0 3600 8)"
      maxduration="$(sanitize_int_range "${F_maxduration}" 1 3600 60)"
      diskspace="$(sanitize_int_range "${F_diskspace}" 0 1000000 512)"

      echo "Motion activated recording set to $motion_act.<BR>"
      echo "Postrecord set to $postrec seconds.<BR>"
      echo "Max file duration set to $maxduration seconds.<BR>"
      echo "Reserved free disk space set to $diskspace Megabytes.<BR>"

      echo "rec_motion_activated=$motion_act" > /mnt/config/recording.conf
      echo "rec_postrecord_sec=$postrec" >> /mnt/config/recording.conf
      echo "rec_file_duration_sec=$maxduration" >> /mnt/config/recording.conf
      echo "rec_reserverd_disk_mb=$diskspace" >> /mnt/config/recording.conf

      restart_service_if_need /mnt/controlscripts/recording
    ;;

    conf_motiondetect)
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " mdsens ${F_mdsens} 
      /mnt/bin/setconf -k m -v "${F_mdsens}"
      rewrite_config /mnt/config/motion.conf motion_trigger_led "${F_motionBlink}"

      echo "Motion red led blink set to ${F_motionBlink}<BR>"
      echo "Motion sensitivity set to ${F_mdsens}<BR>"
    ;;

    conf_autodaynight)
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
            " " daynightawb "${F_dnawb}" \
            " " daynightlum "${F_dnlum}" \
            " " nightdayawb "${F_ndawb}" \
            " " nightdaylum "${F_ndlum}"

        /mnt/bin/setconf -k r -v "${F_dnawb}"
        /mnt/bin/setconf -k a -v "${F_dnlum}"
        /mnt/bin/setconf -k b -v "${F_ndawb}"
        /mnt/bin/setconf -k d -v "${F_ndlum}"

        echo "daynightawb ${F_dnawb} <BR>"
        echo "daynightlum ${F_dnlum} <BR>"
        echo "nightdayawb ${F_ndawb} <BR>"
        echo "nightdaylum ${F_ndlum} <BR>"
     ;;


    get_ptt_vol)
        read_ptt_volume
    ;;

    get_ptt_status)
        ptt_backend_status
    ;;

    conf_ptt)
        safe_ptt_vol="$(sanitize_int_range "$F_audiooutVol" 0 100 90)"
        echo "$safe_ptt_vol" > "$PTT_VOLUME_FILE"
        if wants_json_response; then
          json_body_ok "Push-to-talk volume set to $safe_ptt_vol"
        else
          echo "Push-to-talk volume set to $safe_ptt_vol"
        fi
    ;;

     motion_detection_mail_on)
         rewrite_config /mnt/config/motion.conf sendemail "true"
         ;;

     motion_detection_mail_off)
          rewrite_config /mnt/config/motion.conf sendemail "false"
          ;;

     motion_detection_snapshot_on)
          rewrite_config /mnt/config/motion.conf save_snapshot "true"
          ;;

     motion_detection_snapshot_off)
          rewrite_config /mnt/config/motion.conf save_snapshot "false"
          ;;

    conf_dns)
        # Validate: must be empty or a dotted-quad IPv4 address
        validate_ip_or_empty() {
            addr="$1"
            [ -z "$addr" ] && return 0
            printf '%s' "$addr" | awk -F. 'NF==4 && $1+0==$1 && $2+0==$2 && $3+0==$3 && $4+0==$4 &&
                $1>=0 && $1<=255 && $2>=0 && $2<=255 && $3>=0 && $3<=255 && $4>=0 && $4<=255
                {exit 0} {exit 1}'
        }
        dns_primary="$F_dns_primary"
        dns_secondary="$F_dns_secondary"
        if ! validate_ip_or_empty "$dns_primary"; then
            if wants_json_response; then
              json_body_err "INVALID_DNS" "Invalid primary DNS address: $dns_primary"
            else
              log_event "error" "network" "Invalid primary DNS address: $dns_primary"
              echo "ERROR: invalid primary DNS address '$dns_primary'"
            fi
        elif ! validate_ip_or_empty "$dns_secondary"; then
            if wants_json_response; then
              json_body_err "INVALID_DNS" "Invalid secondary DNS address: $dns_secondary"
            else
              log_event "error" "network" "Invalid secondary DNS address: $dns_secondary"
              echo "ERROR: invalid secondary DNS address '$dns_secondary'"
            fi
        else
            rewrite_config /mnt/config/dns.conf DNS_PRIMARY "$dns_primary"
            rewrite_config /mnt/config/dns.conf DNS_SECONDARY "$dns_secondary"
            # Apply immediately to /etc/resolv.conf
            {
                [ -n "$dns_primary" ] && echo "nameserver $dns_primary"
                [ -n "$dns_secondary" ] && echo "nameserver $dns_secondary"
            } > /etc/resolv.conf
            if wants_json_response; then
              json_body_ok "DNS updated. Primary: ${dns_primary:-none} Secondary: ${dns_secondary:-none}. Reboot to make permanent."
            else
              echo "DNS updated. Primary: ${dns_primary:-none} Secondary: ${dns_secondary:-none}. Reboot to make permanent."
            fi
        fi
    ;;

    conf_static_ip)
        validate_ip_or_empty() {
            addr="$1"
            [ -z "$addr" ] && return 0
            printf '%s' "$addr" | awk -F. 'NF==4 && $1+0==$1 && $2+0==$2 && $3+0==$3 && $4+0==$4 &&
                $1>=0 && $1<=255 && $2>=0 && $2<=255 && $3>=0 && $3<=255 && $4>=0 && $4<=255
                {exit 0} {exit 1}'
        }
        ip_mode="$F_ip_mode"
        static_ip="$F_static_ip"
        static_netmask="$F_static_netmask"
        static_gateway="$F_static_gateway"
        case "$ip_mode" in
            static|dhcp) ;;
            *) ip_mode="dhcp" ;;
        esac
        if [ "$ip_mode" = "static" ]; then
            if [ -z "$static_ip" ] || ! validate_ip_or_empty "$static_ip"; then
                log_event "error" "network" "Invalid static IP address: $static_ip"
                echo "ERROR: invalid static IP '$static_ip'"
            elif ! validate_ip_or_empty "$static_netmask"; then
                log_event "error" "network" "Invalid netmask: $static_netmask"
                echo "ERROR: invalid netmask '$static_netmask'"
            elif ! validate_ip_or_empty "$static_gateway"; then
                log_event "error" "network" "Invalid gateway: $static_gateway"
                echo "ERROR: invalid gateway '$static_gateway'"
            else
                install_config /mnt/config/network.conf
                rewrite_config /mnt/config/network.conf IP_MODE "static"
                rewrite_config /mnt/config/network.conf STATIC_IP "$static_ip"
                rewrite_config /mnt/config/network.conf STATIC_NETMASK "${static_netmask:-255.255.255.0}"
                rewrite_config /mnt/config/network.conf STATIC_GATEWAY "$static_gateway"
                echo "Static IP saved: $static_ip / ${static_netmask:-255.255.255.0} gateway ${static_gateway:-none}. Reboot to apply."
            fi
        else
            install_config /mnt/config/network.conf
            rewrite_config /mnt/config/network.conf IP_MODE "dhcp"
            echo "DHCP mode saved. Reboot to apply."
        fi
    ;;

    wifi_scan)
        if wants_json_response; then
          json_body_err "FORMAT_NOT_SUPPORTED" "wifi_scan command does not support JSON format"
        else
          scan_out="$(iwlist wlan0 scan 2>/dev/null)"
          if [ -z "$scan_out" ]; then
              echo "<p class='help'>Scan failed or no results. Ensure WiFi is up.</p>"
          else
              rows="$(printf '%s\n' "$scan_out" | awk '
                  /Cell [0-9]+ - Address:/ {
                      if (ssid != "" || rssi != "") {
                          name = (ssid == "") ? "(hidden)" : ssid
                          printf "<tr><td>%s</td><td>%s</td><td>%s</td></tr>\n", name, (rssi != "" ? rssi : "n/a"), enc
                      }
                      ssid = ""; rssi = ""; enc = "No"
                  }
                  /ESSID:/ {
                      n = split($0, a, "\""); ssid = (n >= 2) ? a[2] : ""
                  }
                  /Encryption key:on/  { enc = "Yes" }
                  /Encryption key:off/ { enc = "No"  }
                  /Signal level=/ {
                      sub(/.*Signal level=/, ""); sub(/[[:space:]].*/, ""); rssi = $0
                  }
                  /Extra:rssi=/ {
                      sub(/.*Extra:rssi=/, ""); sub(/[[:space:]].*/, ""); rssi = $0
                  }
                  END {
                      name = (ssid == "") ? "(hidden)" : ssid
                      if (rssi != "" || ssid != "")
                          printf "<tr><td>%s</td><td>%s</td><td>%s</td></tr>\n", name, (rssi != "" ? rssi : "n/a"), enc
                  }
              ')"
              if [ -z "$rows" ]; then
                  echo "<p class='help'>No networks found.</p>"
              else
                  printf "<table class='table is-fullwidth is-hoverable is-size-7'><thead><tr><th>SSID</th><th>Quality</th><th>Encrypted</th></tr></thead><tbody>%s</tbody></table>\n" "$rows"
              fi
          fi
        fi
    ;;

    save_preset)
        preset_name="${F_name:-}"
        preset_data="${F_data:-}"
        presets_dir="/mnt/config/presets"

        mkdir -p "$presets_dir"

        if [ -z "$preset_name" ] || [ -z "$preset_data" ]; then
            if wants_json_response; then
              json_body_err "INVALID_PRESET" "Preset name and data required"
            else
              echo "ERROR: Preset name and data required"
            fi
        else
            # Validate preset name (alphanumeric, underscore, hyphen only).
            # Fork-free case idiom — busybox grep may lack -E (CLAUDE.md), in
            # which case `grep -qE` errored and rejected EVERY name.
            case "$preset_name" in ''|*[!a-zA-Z0-9_-]*) _preset_name_bad=1 ;; *) _preset_name_bad=0 ;; esac
            if [ "$_preset_name_bad" = "1" ]; then
                if wants_json_response; then
                  json_body_err "INVALID_NAME" "Preset name must be alphanumeric with underscore/hyphen only"
                else
                  echo "ERROR: Invalid preset name"
                fi
            else
                # Limit to 10 presets
                preset_count=$(find "$presets_dir" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l)
                preset_file="$presets_dir/$preset_name.json"

                if [ -f "$preset_file" ]; then
                    # Update existing preset
                    printf '%s' "$preset_data" > "$preset_file"
                    if wants_json_response; then
                      json_body_ok "Preset '$preset_name' updated"
                    else
                      echo "Preset '$preset_name' updated"
                    fi
                elif [ "$preset_count" -lt 10 ]; then
                    # Create new preset
                    printf '%s' "$preset_data" > "$preset_file"
                    if wants_json_response; then
                      json_body_ok "Preset '$preset_name' created"
                    else
                      echo "Preset '$preset_name' created"
                    fi
                else
                    if wants_json_response; then
                      json_body_err "PRESET_LIMIT" "Maximum 10 presets allowed"
                    else
                      echo "ERROR: Maximum 10 presets allowed"
                    fi
                fi
            fi
        fi
    ;;

    delete_preset)
        preset_name="${F_name:-}"
        presets_dir="/mnt/config/presets"

        if [ -z "$preset_name" ]; then
            if wants_json_response; then
              json_body_err "INVALID_PRESET" "Preset name required"
            else
              echo "ERROR: Preset name required"
            fi
        else
            # Validate preset name (busybox-safe, no grep -E — see save_preset)
            case "$preset_name" in ''|*[!a-zA-Z0-9_-]*) _preset_name_bad=1 ;; *) _preset_name_bad=0 ;; esac
            if [ "$_preset_name_bad" = "1" ]; then
                if wants_json_response; then
                  json_body_err "INVALID_NAME" "Invalid preset name"
                else
                  echo "ERROR: Invalid preset name"
                fi
            else
                preset_file="$presets_dir/$preset_name.json"
                if [ -f "$preset_file" ]; then
                    rm -f "$preset_file"
                    if wants_json_response; then
                      json_body_ok "Preset '$preset_name' deleted"
                    else
                      echo "Preset '$preset_name' deleted"
                    fi
                else
                    if wants_json_response; then
                      json_body_err "PRESET_NOT_FOUND" "Preset '$preset_name' not found"
                    else
                      echo "ERROR: Preset '$preset_name' not found"
                    fi
                fi
            fi
        fi
    ;;

    wifi_get_ssid)
        # Ask the interface, not a file. The camera often carries no
        # wpa_supplicant.conf at all (the firmware holds credentials in flash),
        # and after a wpa_cli reconfigure the file can disagree with the network
        # actually joined. Files are only a last resort.
        _ssid=""
        if command -v wpa_cli >/dev/null 2>&1; then
            # Take the ssid line only — `wpa_cli status` also prints `passphrase=`.
            _ssid="$(wpa_cli -i wlan0 status 2>/dev/null | awk '/^ssid=/ { print substr($0, 6); exit }')"
        fi
        if [ -z "$_ssid" ] && command -v iwconfig >/dev/null 2>&1; then
            _ssid="$(iwconfig wlan0 2>/dev/null | awk -F'"' '/ESSID:"/ { print $2; exit }')"
        fi
        if [ -z "$_ssid" ]; then
            for _wpa_conf in "$WIFI_CONFIG_PATH" /mnt/config/wpa_supplicant.conf; do
                [ -f "$_wpa_conf" ] || continue
                _ssid="$(awk -F'"' '/^[ \t]*ssid=/ { print $2; exit }' "$_wpa_conf")"
                [ -n "$_ssid" ] && break
            done
        fi
        _ssid_safe="$(printf '%s' "$_ssid" | sed 's/\\/\\\\/g; s/"/\\"/g')"
        printf '{"status":"success","ssid":"%s"}\n' "$_ssid_safe"
    ;;

    wifi_set_config)
        # Must be the very path autorun.sh passes to `wpa_supplicant -c`, or
        # `wpa_cli reconfigure` below re-reads the old file and the change is
        # silently discarded — and the new one is never used at boot either.
        _wpa_conf="$WIFI_CONFIG_PATH"
        _ssid="$(printf '%s' "${F_ssid:-}" | awk '{ gsub(/["\\]/, ""); print }' | cut -c1-32)"
        _psk="$(printf '%s' "${F_psk:-}" | awk '{ gsub(/["\\]/, ""); print }' | cut -c1-63)"
        _ssid_len="$(printf '%s' "$_ssid" | wc -c)"
        _psk_len="$(printf '%s' "$_psk" | wc -c)"
        if [ "$_ssid_len" -lt 1 ]; then
            json_body_err "INVALID_SSID" "SSID must be 1-32 characters"
        elif [ "$_psk_len" -lt 8 ]; then
            json_body_err "INVALID_PSK" "PSK must be at least 8 characters"
        else
            _wpa_tmp="${_wpa_conf}.tmp.$$"
            {
                printf 'ctrl_interface=/var/run/wpa_supplicant\n'
                printf 'ctrl_interface_group=0\n'
                printf 'ap_scan=1\n'
                printf 'network={\n'
                printf '\tssid="%s"\n'   "$_ssid"
                printf '\tkey_mgmt=WPA-PSK\n'
                printf '\tpsk="%s"\n'    "$_psk"
                printf '\tpriority=2\n'
                printf '}\n'
            } > "$_wpa_tmp" && mv "$_wpa_tmp" "$_wpa_conf" || {
                rm -f "$_wpa_tmp" 2>/dev/null
                json_body_err "WRITE_ERROR" "Failed to write WiFi configuration"
                exit 0
            }
            command -v wpa_cli >/dev/null 2>&1 && wpa_cli -i wlan0 reconfigure >/dev/null 2>&1 || true
            json_body_ok "WiFi configuration updated for SSID: $_ssid. Reconnecting..."
        fi
    ;;

    wizard_reset)
        rm -f /mnt/config/.wizard_done 2>/dev/null || true
        touch /tmp/.first_boot 2>/dev/null || true
        json_body_ok "Wizard reset. Redirecting to setup wizard."
    ;;

     *)
        if wants_json_response; then
          json_body_err "UNSUPPORTED_COMMAND" "Unsupported command '$F_cmd'"
        else
          echo "Unsupported command '$F_cmd'"
        fi
        ;;

  esac
fi

if ! wants_json_response; then
  echo "<hr/>"
fi
