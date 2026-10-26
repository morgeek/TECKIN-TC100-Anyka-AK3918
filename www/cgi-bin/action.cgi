#!/bin/sh

. /mnt/www/cgi-bin/func.cgi
. /mnt/scripts/common_functions.sh
. /mnt/scripts/event-logger.sh

export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'

# Must stay in sync with WIFI_CONFIG in autorun.sh — that is the file passed to
# `wpa_supplicant -c`, so anything written elsewhere is ignored at boot and by
# `wpa_cli reconfigure`.
WIFI_CONFIG_PATH="/mnt/wpa_supplicant.conf"


# Rate limit: commands that change something (POST). The pages poll read commands (sd_card_info, wifi_get_ssid,
# local_rec_status...) with GET; counting them made the settings and dashboard pages hit 429.
case "${REQUEST_METHOD:-GET}:$F_cmd" in
  *:reboot|*:shutdown) rate_limit_check 3 300 ;;
  POST:*) rate_limit_check 20 60 ;;
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

# sound_threshold_db VALUE FALLBACK -> integer dBFS in -90..0
sound_threshold_db() {
  case "$1" in
    -[0-9]|-[0-9][0-9]|0) _std="$1" ;;
    *) _std="$2" ;;
  esac
  [ "$_std" -lt -90 ] && _std=-90
  echo "$_std"
}

# apply_sound_detection ENABLE THRESHOLD_DB [INTERVAL] — persist, (re)start the
# daemon and restart RTSP when ENABLE changed (the microphone capture and the
# level meter are set up when v4l2rtspserver starts).
apply_sound_detection() {
  install_config /mnt/config/sound_detection.conf
  _asd_old="$(read_kv_or_default /mnt/config/sound_detection.conf ENABLE 0)"
  rewrite_config /mnt/config/sound_detection.conf ENABLE "$1"
  rewrite_config /mnt/config/sound_detection.conf THRESHOLD_DB "$2"
  [ -n "$3" ] && rewrite_config /mnt/config/sound_detection.conf INTERVAL "$3"
  if [ "$1" = "1" ]; then
    /mnt/controlscripts/sound-detection start >/dev/null 2>&1
  else
    /mnt/controlscripts/sound-detection stop >/dev/null 2>&1
  fi
  [ "$_asd_old" != "$1" ] && schedule_rtsp_restart
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
PTT_PCM_PLAYBACK_BIN="/mnt/bin/ak_ao_ptt"
PTT_WAV_PLAYBACK_BIN="/mnt/bin/audioplay"

# Linux 6.6 (3.0): ALSA playback through scripts/speaker-play.sh FILE VOLUME(0-100), no vendor binary
PTT_SPEAKER_PLAY="/mnt/scripts/speaker-play.sh"
ptt_l66() { [ -f /tmp/linux66 ] && [ -r "$PTT_SPEAKER_PLAY" ] && command -v aplay >/dev/null 2>&1; }

ptt_backend_status() {
  if [ -x "$PTT_PCM_PLAYBACK_BIN" ] || ptt_l66; then
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
  for candidate in /mnt/config/audio-test.wav /mnt/config/ptt-test.wav "$PTT_LAST_PCM_FILE" /mnt/sounds/alert.pcm; do
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

  if ptt_l66; then
    case "$audio_source" in
      *.pcm|*.wav)
        ( sh "$PTT_SPEAKER_PLAY" "$audio_source" "$audio_volume" ) </dev/null >/dev/null 2>&1 &
        if wants_json_response; then
          json_body_ok "Playing $audio_source at volume $audio_volume"
        else
          echo "Play $audio_source at volume $audio_volume"
        fi
        return 0 ;;
    esac
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
      echo "${schedule_minute} ${schedule_hour} * * ${schedule_weekday} /bin/sh /mnt/scripts/reboot-tracker.sh intent 'scheduled reboot (REBOOT_SCHEDULE)'; /sbin/reboot >/dev/null 2>&1"
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
      echo "THRESHOLD_DB=-24"
      echo "INTERVAL=2"
    } > /mnt/config/sound_detection.conf
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
  for svc in ftp-server telnet-server motion-detection auto-night-detection front-led night-mode network-monitor; do
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
  if ! command -v nc >/dev/null 2>&1; then
    return 2
  fi

  rtsp_timeout="$(sanitize_int_range "$(read_kv_or_default /mnt/config/boot.conf RTSP_HEALTHCHECK_TIMEOUT_SECONDS 4)" 2 30 4)"
  rtsp_port="$(read_config rtspserver.conf PORT)"
  [ -n "$rtsp_port" ] || rtsp_port=554
  describe_uri="rtsp://127.0.0.1:${rtsp_port}/${health_stream}"

  # The bundled curl sends OPTIONS even with -X DESCRIBE. Use the same raw
  # probe as state.cgi and allow the encoder a short warm-up period.
  describe_attempt=1
  while [ "$describe_attempt" -le 5 ]; do
    describe_reply="$(printf 'DESCRIBE %s RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\n\r\n' "$describe_uri"       | nc -w "$rtsp_timeout" 127.0.0.1 "$rtsp_port" 2>/dev/null)" || true
    case "$describe_reply" in
      *'RTSP/1.0 401 Unauthorized'*) return 0 ;;
      *'RTSP/1.0 200 OK'*'m=video'*) return 0 ;;
    esac
    [ "$describe_attempt" -lt 5 ] && sleep 1
    describe_attempt=$((describe_attempt + 1))
  done
  return 1
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
  if [ -x /mnt/bin/getimage ] || [ -f /tmp/linux66 ]; then
    # take_snapshot: getimage (2.x) or the picture tc100_rtsp keeps (Linux 6.6)
    if take_snapshot "$snapshot_tmp"; then
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

# Preserve the existing restart/rollback checks and expose their actual result
# to the settings UI. Legacy HTML callers retain their original diagnostics.
ui_finalize_stream_apply() {
  if ! wants_json_response; then
    finalize_stream_apply "$1"
    return $?
  fi
  _ui_apply_report="$(finalize_stream_apply "$1")"
  _ui_apply_rc=$?
  if [ "$_ui_apply_rc" -ne 0 ]; then
    json_body_err "STREAM_APPLY_FAILED" "The video check failed. The camera attempted rollback; check playback before retrying."
    return 1
  fi
  case "$_ui_apply_report" in
    *[Ww]arning*) _ui_apply_message="Saved. Video health check passed with warnings; review diagnostics." ;;
    *) _ui_apply_message="Saved. Video restart and health check passed." ;;
  esac
  printf '{"ok":true,"message":"%s","restart":"verified"}\n' "$_ui_apply_message"
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
    frigate-light-ak3918)
      profile_label="Frigate Light AK3918"
      width0=1280; height0=720;  fps0=12; bps0=1000; gop0=12; maxkbps0=1300; targetkbps0=1000; smartq0=72; smartstatic0=360
      width1=640;  height1=360;  fps1=8;  bps1=320;  gop1=8;  maxkbps1=420;  targetkbps1=320;  smartq1=65; smartstatic1=150
      codec0=2; profile0=3
      # Real TC100 hardware rejects mixed H.265-main/H.264-sub encoding.
      # Keep both hardware channels on H.265 and save resources via fps/bitrate.
      codec1=2; profile1=3
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
    showlog|get_ptt_vol|get_ptt_status|wifi_scan|wifi_get_ssid|wifi_rescue_info|local_rec_status|sd_card_info|md_zones_info|rtsp_server_info) ;;
    *) csrf_check ;;
  esac
  # Each command lives in scripts/action.d/<group>.sh: only that file is
  # parsed (the whole list took ~0.3 s per request on the camera).
  case "$F_cmd" in
    showlog|clearlog)
      _action_group=logs ;;
    set_video_params|isp_pro|isp_tune|set_advanced_tuning|osd|image-flip|toggle-rtsp-nightvision-on|toggle-rtsp-nightvision-off|rtsp-log-on|rtsp-log-off|enable_privacy_shield|set_video_size)
      _action_group=video ;;
    rtsp_server_info|set_rtsp_server|set_stream_topology|set_onvif_stream_policy|set_rtsp_preset|set_rtsp_quality_profile|set_client_profile|save_known_good_profile|restore_known_good_profile|set_frigate_live)
      _action_group=stream ;;
    conf_audioin|audio_test|set_sound_detection|get_ptt_vol|get_ptt_status|conf_ptt)
      _action_group=audio ;;
    set_local_recording|local_rec_status|sd_card_info|sd_card_format|sd_card_mount|sd_card_ack|local_rec_eject|local_rec_resume)
      _action_group=storage ;;
    md_zones_info|motion_detection_on|motion_detection_off|conf_motiondetect)
      _action_group=detection ;;
    front_led_on|front_led_off|red_led_on|red_led_off|ir_led_on|ir_led_off|ir_cut_on|ir_cut_off|auto_night_mode_start|auto_night_mode_stop|night-mode-on|night-mode-off|conf_autodaynight|set_led_config)
      _action_group=hardware ;;
    reboot|shutdown|clear_mem|set_telnet|set_ftp|settz|set_http_password|set_all_password|service_trim_on|service_trim_off|set_performance_profile|set_web_mode|set_reboot_schedule|set_telegram_config|set_syslog_config|save_preset|delete_preset)
      _action_group=system ;;
    set_network|conf_dns|conf_static_ip|wifi_scan|wifi_get_ssid|wifi_rescue_info|wifi_set_config)
      _action_group=network ;;
    refresh_ha_discovery|set_mqtt_config|pair_home_assistant)
      _action_group=integrations ;;
    complete_setup_wizard|wizard_reset)
      _action_group=setup ;;
    *) _action_group= ;;
  esac
  if [ -n "$_action_group" ] && [ -f "/mnt/scripts/action.d/$_action_group.sh" ]; then
    . "/mnt/scripts/action.d/$_action_group.sh"
  else
          if wants_json_response; then
            json_body_err "UNSUPPORTED_COMMAND" "Unsupported command '$F_cmd'"
          else
            echo "Unsupported command '$F_cmd'"
          fi
  fi
fi

if ! wants_json_response; then
  echo "<hr/>"
fi
