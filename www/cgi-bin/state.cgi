#!/bin/sh

# A very light-weight interface just for responsive ui to get states

source ./func.cgi

echo "Content-type: text"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

USAGE_CACHE_FILE="/tmp/state_usage.cache"
USAGE_CACHE_TTL_SECONDS=2
PERFPROFILE_CACHE_FILE="/tmp/state_perfprofile.cache"
PERFPROFILE_CACHE_TTL_SECONDS=5

now_epoch() {
  now_ts="$(date +%s 2>/dev/null)"
  case "$now_ts" in
    ''|*[!0-9]*)
      echo "0"
      ;;
    *)
      echo "$now_ts"
      ;;
  esac
}

get_current_cpu_usage_fast() {
  cpu_active_prev=0
  cpu_total_prev=0
  if [ -f /tmp/cpuact ]; then
    read -r cpu_active_prev < /tmp/cpuact
  fi
  if [ -f /tmp/cputot ]; then
    read -r cpu_total_prev < /tmp/cputot
  fi

  # /proc/stat layout:
  # cpu user nice system idle iowait irq softirq steal guest guest_nice
  read -r _ user nice system idle iowait irq softirq steal _ _ < /proc/stat
  cpu_active_cur=$((user + nice + system + irq + softirq + steal))
  cpu_total_cur=$((cpu_active_cur + idle + iowait))

  echo "$cpu_active_cur" > /tmp/cpuact
  echo "$cpu_total_cur" > /tmp/cputot

  delta_total=$((cpu_total_cur - cpu_total_prev))
  delta_active=$((cpu_active_cur - cpu_active_prev))
  if [ "$delta_total" -le 0 ]; then
    echo "0"
    return
  fi
  if [ "$delta_active" -lt 0 ]; then
    delta_active=0
  fi

  cpu_util=$((100 * delta_active / delta_total))
  if [ "$cpu_util" -lt 0 ]; then
    cpu_util=0
  elif [ "$cpu_util" -gt 100 ]; then
    cpu_util=100
  fi
  echo "$cpu_util"
}

get_memory_usage_fast() {
  mem_total=0
  mem_available=0
  mem_free=0
  mem_buffers=0
  mem_cached=0
  mem_sreclaimable=0
  mem_shmem=0

  while IFS=' ' read -r key value _; do
    case "$key" in
      MemTotal:)
        mem_total="$value"
        ;;
      MemAvailable:)
        mem_available="$value"
        ;;
      MemFree:)
        mem_free="$value"
        ;;
      Buffers:)
        mem_buffers="$value"
        ;;
      Cached:)
        mem_cached="$value"
        ;;
      SReclaimable:)
        mem_sreclaimable="$value"
        ;;
      Shmem:)
        mem_shmem="$value"
        ;;
    esac
    if [ "$mem_total" -gt 0 ] && [ "$mem_available" -gt 0 ]; then
      break
    fi
  done < /proc/meminfo

  if [ "$mem_available" -le 0 ]; then
    mem_available=$((mem_free + mem_buffers + mem_cached + mem_sreclaimable - mem_shmem))
    if [ "$mem_available" -lt 0 ]; then
      mem_available=0
    fi
  fi
  if [ "$mem_available" -gt "$mem_total" ]; then
    mem_available="$mem_total"
  fi

  mem_used=$((mem_total - mem_available))
}

compute_usage_metrics() {
  cpu="$(get_current_cpu_usage_fast)"
  get_memory_usage_fast
  ram_percent=0
  if [ "$mem_total" -gt 0 ]; then
    ram_percent=$((100 * mem_used / mem_total))
    if [ "$ram_percent" -lt 0 ]; then
      ram_percent=0
    elif [ "$ram_percent" -gt 100 ]; then
      ram_percent=100
    fi
  fi
}

load_cached_usage_metrics() {
  [ -f "$USAGE_CACHE_FILE" ] || return 1

  cached_ts=0
  cached_cpu=0
  cached_mem_used=0
  cached_mem_total=0
  cached_ram_percent=0

  read -r cached_ts cached_cpu cached_mem_used cached_mem_total cached_ram_percent < "$USAGE_CACHE_FILE" || return 1

  for value in "$cached_ts" "$cached_cpu" "$cached_mem_used" "$cached_mem_total" "$cached_ram_percent"; do
    case "$value" in
      ''|*[!0-9]*)
        return 1
        ;;
    esac
  done

  now_ts="$(now_epoch)"
  [ "$now_ts" -gt 0 ] || return 1
  [ "$cached_ts" -le "$now_ts" ] || return 1

  age=$((now_ts - cached_ts))
  [ "$age" -le "$USAGE_CACHE_TTL_SECONDS" ] || return 1

  cpu="$cached_cpu"
  mem_used="$cached_mem_used"
  mem_total="$cached_mem_total"
  ram_percent="$cached_ram_percent"
  return 0
}

save_cached_usage_metrics() {
  now_ts="$(now_epoch)"
  [ "$now_ts" -gt 0 ] || return 0
  printf '%s %s %s %s %s\n' "$now_ts" "$cpu" "$mem_used" "$mem_total" "$ram_percent" > "$USAGE_CACHE_FILE"
}

load_or_compute_usage_metrics() {
  if load_cached_usage_metrics; then
    return 0
  fi
  compute_usage_metrics
  save_cached_usage_metrics
}

read_conf_value() {
  conf_file="$1"
  conf_key="$2"
  conf_default="$3"
  conf_value="$conf_default"

  if [ -f "$conf_file" ]; then
    while IFS= read -r line; do
      case "$line" in
        ''|'#'*)
          continue
          ;;
      esac
      case "$line" in
        "$conf_key"=*)
          conf_value="${line#*=}"
          break
          ;;
      esac
    done < "$conf_file"
  fi

  echo "$conf_value"
}

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

sanitize_int() {
  raw="$1"
  fallback="$2"
  case "$raw" in
    ''|*[!0-9]*)
      echo "$fallback"
      ;;
    *)
      echo "$raw"
      ;;
  esac
}

codec_name() {
  case "$1" in
    2)
      echo "H265"
      ;;
    0)
      echo "H264"
      ;;
    *)
      echo "unknown"
      ;;
  esac
}

service_state_json() {
  service_script="$1"
  service_state="stopped"
  service_pid=0
  service_status="$("$service_script" status 2>/dev/null)"
  if [ -n "$service_status" ]; then
    service_state="running"
    service_pid="$(printf '%s' "$service_status" | sed -n 's/.*PID:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -n 1)"
    service_pid="$(sanitize_int "$service_pid" 0)"
  fi
  service_state_escaped="$(json_escape "$service_state")"
  printf '{"state":"%s","pid":%s}' "$service_state_escaped" "$service_pid"
}

read_rtsp_stream_summary() {
  if [ -x /mnt/bin/rwconf ]; then
    set -- $(/mnt/bin/rwconf /mnt/config/rtspserver.conf r \
      " " PORT \
      0 codec 0 width 0 height 0 fps \
      1 codec 1 width 1 height 1 fps)
  else
    set -- 554 0 0 0 0 0 0 0 0
  fi

  rtsp_port="$(sanitize_int "$1" 554)"
  codec0="$(sanitize_int "$2" 0)"
  width0="$(sanitize_int "$3" 0)"
  height0="$(sanitize_int "$4" 0)"
  fps0="$(sanitize_int "$5" 0)"
  codec1="$(sanitize_int "$6" 0)"
  width1="$(sanitize_int "$7" 0)"
  height1="$(sanitize_int "$8" 0)"
  fps1="$(sanitize_int "$9" 0)"

  codec0_name="$(codec_name "$codec0")"
  codec1_name="$(codec_name "$codec1")"
}

last_watchdog_event_json() {
  event=""
  if [ -r /var/log/service-watchdog.log ]; then
    event="$(tail -n 1 /var/log/service-watchdog.log 2>/dev/null)"
  fi
  event_escaped="$(json_escape "$event")"
  printf '%s' "$event_escaped"
}

load_lum_awb() {
  lum_value=""
  awb_value=""

  if [ -r /var/run/lum ]; then
    read -r lum_value < /var/run/lum
  fi
  if [ -r /var/run/awb ]; then
    read -r awb_value < /var/run/awb
  fi
}

get_ui_ultralite_mode() {
  ui_mode=0
  WEB_MODE_VALUE="$(read_conf_value /mnt/config/boot.conf WEB_MODE full)"
  UI_ULTRALITE_MODE_VALUE="$(read_conf_value /mnt/config/boot.conf UI_ULTRALITE_MODE 0)"

  case "$WEB_MODE_VALUE" in
    ultra-lite|ultralite)
      ui_mode=1
      ;;
  esac

  case "$UI_ULTRALITE_MODE_VALUE" in
    1|true|on|yes|enabled)
      ui_mode=1
      ;;
  esac
}

get_security_and_mqtt_flags() {
  security_hardening_mode=0
  mqtt_enabled=0

  security_raw="$(read_conf_value /mnt/config/boot.conf SECURITY_HARDENING_MODE 0)"
  case "$security_raw" in
    1|true|on|yes|enabled)
      security_hardening_mode=1
      ;;
  esac

  mqtt_raw="$(read_conf_value /mnt/config/mqtt.conf MQTT_ENABLE 0)"
  case "$mqtt_raw" in
    1|true|on|yes|enabled)
      mqtt_enabled=1
      ;;
  esac
}

read_chip_temperature() {
  chip_temp_raw=""
  chip_temp_c=""
  chip_temp_json="null"
  chip_temp_text="n/a"

  temp_source_path="$(read_conf_value /mnt/config/boot.conf CHIP_TEMP_SOURCE_PATH auto)"
  temp_raw_divisor="$(read_conf_value /mnt/config/boot.conf CHIP_TEMP_RAW_DIVISOR auto)"

  temp_candidates=""
  case "$temp_source_path" in
    ''|auto)
      temp_candidates="/sys/class/thermal/thermal_zone0/temp /sys/class/thermal/thermal_zone1/temp /sys/devices/virtual/thermal/thermal_zone0/temp /proc/temperature /tmp/chip_temp"
      ;;
    *)
      temp_candidates="$temp_source_path"
      ;;
  esac

  for candidate in $temp_candidates; do
    [ -r "$candidate" ] || continue
    read -r raw_value < "$candidate"
    raw_value="$(sanitize_int "$raw_value" 0)"
    if [ "$raw_value" -gt 0 ]; then
      chip_temp_raw="$raw_value"
      break
    fi
  done

  if [ -n "$chip_temp_raw" ]; then
    case "$temp_raw_divisor" in
      ''|auto)
        if [ "$chip_temp_raw" -ge 10000 ]; then
          temp_raw_divisor=1000
        elif [ "$chip_temp_raw" -le 125 ]; then
          temp_raw_divisor=1
        else
          temp_raw_divisor=0
        fi
        ;;
      *)
        temp_raw_divisor="$(sanitize_int "$temp_raw_divisor" 0)"
        ;;
    esac

    if [ "$temp_raw_divisor" -gt 0 ]; then
      chip_temp_c=$((chip_temp_raw / temp_raw_divisor))
    fi
  fi

  if [ -n "$chip_temp_c" ] && [ "$chip_temp_c" -ge 0 ] && [ "$chip_temp_c" -le 125 ]; then
    chip_temp_text="${chip_temp_c}C"
    chip_temp_json="$chip_temp_c"
  fi
}

read_power_telemetry() {
  power_sensor_path_cfg="$(read_conf_value /mnt/config/mqtt.conf POWER_SENSOR_PATH auto)"
  power_estimate_enable_raw="$(read_conf_value /mnt/config/mqtt.conf POWER_ESTIMATE_ENABLE 0)"
  power_estimate_base_mw="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf POWER_ESTIMATE_BASE_MW 1700)" 1700)"
  power_estimate_cpu_scale_mw="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf POWER_ESTIMATE_CPU_SCALE_MW 500)" 500)"
  power_estimate_ir_led_mw="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf POWER_ESTIMATE_IR_LED_MW 700)" 700)"

  if [ "$power_estimate_base_mw" -lt 0 ]; then
    power_estimate_base_mw=0
  fi
  if [ "$power_estimate_cpu_scale_mw" -lt 0 ]; then
    power_estimate_cpu_scale_mw=0
  fi
  if [ "$power_estimate_ir_led_mw" -lt 0 ]; then
    power_estimate_ir_led_mw=0
  fi

  case "$power_estimate_enable_raw" in
    1|true|on|yes|enabled)
      power_estimate_enabled=1
      ;;
    *)
      power_estimate_enabled=0
      ;;
  esac

  case "$power_sensor_path_cfg" in
    ''|auto)
      power_sensor_candidates="/sys/kernel/ain/bat /sys/kernel/ain/ain0 /sys/kernel/ain/ain1"
      ;;
    /*)
      power_sensor_candidates="$power_sensor_path_cfg"
      ;;
    *)
      power_sensor_candidates="/sys/kernel/ain/bat /sys/kernel/ain/ain0 /sys/kernel/ain/ain1"
      ;;
  esac

  power_sensor_raw=""
  power_sensor_path=""
  power_voltage_mv=0

  for candidate in $power_sensor_candidates; do
    [ -r "$candidate" ] || continue
    read -r raw_value < "$candidate"
    raw_value="$(sanitize_int "$raw_value" 0)"
    if [ "$raw_value" -le 0 ]; then
      continue
    fi
    power_sensor_raw="$raw_value"
    power_sensor_path="$candidate"
    break
  done

  if [ -n "$power_sensor_raw" ]; then
    if [ "$power_sensor_raw" -ge 2500 ] && [ "$power_sensor_raw" -le 20000 ]; then
      power_voltage_mv="$power_sensor_raw"
    elif [ "$power_sensor_raw" -ge 2500000 ] && [ "$power_sensor_raw" -le 20000000 ]; then
      power_voltage_mv=$((power_sensor_raw / 1000))
    fi
  fi

  power_voltage_mv_json="null"
  power_voltage_text="n/a"
  if [ "$power_voltage_mv" -gt 0 ]; then
    power_voltage_mv_json="$power_voltage_mv"
    volts_centiv=$(((power_voltage_mv + 5) / 10))
    volts_whole=$((volts_centiv / 100))
    volts_frac=$((volts_centiv % 100))
    power_voltage_text="$(printf '%s.%02sV' "$volts_whole" "$volts_frac")"
  fi

  power_sensor_raw_json="null"
  if [ -n "$power_sensor_raw" ]; then
    power_sensor_raw_json="$power_sensor_raw"
  fi
  if [ -n "$power_sensor_path" ]; then
    power_sensor_path_json="$(json_escape "$power_sensor_path")"
  else
    power_sensor_path_json="n/a"
  fi

  power_estimated_mw_json="null"
  power_estimated_text="n/a"
  power_estimated_current_ma_json="null"

  if [ "$power_estimate_enabled" -eq 1 ]; then
    cpu_for_power="$(sanitize_int "$cpu" 0)"
    if [ "$cpu_for_power" -lt 0 ]; then
      cpu_for_power=0
    elif [ "$cpu_for_power" -gt 100 ]; then
      cpu_for_power=100
    fi

    power_estimated_mw=$((power_estimate_base_mw + (cpu_for_power * power_estimate_cpu_scale_mw / 100)))
    ir_led_state=0
    if [ -r /sys/user-gpio/ir-led ]; then
      read -r ir_led_raw < /sys/user-gpio/ir-led
      ir_led_state="$(sanitize_int "$ir_led_raw" 0)"
    fi
    if [ "$ir_led_state" -eq 1 ]; then
      power_estimated_mw=$((power_estimated_mw + power_estimate_ir_led_mw))
    fi
    if [ "$power_estimated_mw" -lt 0 ]; then
      power_estimated_mw=0
    fi

    power_estimated_mw_json="$power_estimated_mw"
    est_tenths_w=$(((power_estimated_mw + 50) / 100))
    est_w_whole=$((est_tenths_w / 10))
    est_w_frac=$((est_tenths_w % 10))
    power_estimated_text="$(printf '%s.%sW est' "$est_w_whole" "$est_w_frac")"

    if [ "$power_voltage_mv" -gt 0 ]; then
      power_estimated_current_ma=$((power_estimated_mw * 1000 / power_voltage_mv))
      power_estimated_current_ma_json="$power_estimated_current_ma"
    fi
  fi
}

compute_perf_profile() {
  LOW_CPU_PROFILE="$(read_conf_value /mnt/config/boot.conf LOW_CPU_PROFILE 0)"
  SERVICE_TRIM="$(read_conf_value /mnt/config/service_trim.conf SERVICE_TRIM 0)"

  if [ "${SERVICE_TRIM:-0}" = "1" ]; then
    profile="rtsp-only"
  elif [ "${LOW_CPU_PROFILE:-0}" = "1" ]; then
    profile="low-cpu"
  else
    profile="balanced"
  fi
}

load_cached_perf_profile() {
  [ -f "$PERFPROFILE_CACHE_FILE" ] || return 1

  cached_ts=0
  cached_profile=""
  read -r cached_ts cached_profile < "$PERFPROFILE_CACHE_FILE" || return 1
  case "$cached_ts" in
    ''|*[!0-9]*)
      return 1
      ;;
  esac
  case "$cached_profile" in
    balanced|low-cpu|rtsp-only) ;;
    *)
      return 1
      ;;
  esac

  now_ts="$(now_epoch)"
  [ "$now_ts" -gt 0 ] || return 1
  [ "$cached_ts" -le "$now_ts" ] || return 1
  age=$((now_ts - cached_ts))
  [ "$age" -le "$PERFPROFILE_CACHE_TTL_SECONDS" ] || return 1

  profile="$cached_profile"
  return 0
}

save_cached_perf_profile() {
  now_ts="$(now_epoch)"
  [ "$now_ts" -gt 0 ] || return 0
  printf '%s %s\n' "$now_ts" "$profile" > "$PERFPROFILE_CACHE_FILE"
}

get_perf_profile() {
  if load_cached_perf_profile; then
    echo "$profile"
    return 0
  fi
  compute_perf_profile
  save_cached_perf_profile
  echo "$profile"
}

read_reboot_epoch() {
  reboot_epoch=0

  if [ -r /proc/stat ]; then
    reboot_epoch="$(awk '/^btime / {print $2; exit}' /proc/stat 2>/dev/null)"
    reboot_epoch="$(sanitize_int "$reboot_epoch" 0)"
  fi

  if [ "$reboot_epoch" -le 0 ] && [ -r /proc/uptime ]; then
    read -r uptime_raw _ < /proc/uptime
    uptime_seconds_fallback="${uptime_raw%.*}"
    uptime_seconds_fallback="$(sanitize_int "$uptime_seconds_fallback" 0)"
    now_ts="$(now_epoch)"
    if [ "$now_ts" -gt 0 ] && [ "$uptime_seconds_fallback" -gt 0 ]; then
      reboot_epoch=$((now_ts - uptime_seconds_fallback))
    fi
  fi
}

default_password_active_flag() {
  default_active=0
  default_hash="1d06b7785388de1501e8d57847540f6d"

  rtsp_username="$(read_conf_value /mnt/config/rtspserver.conf USERNAME root)"
  rtsp_password="$(read_conf_value /mnt/config/rtspserver.conf USERPASSWORD pass)"
  if [ "$rtsp_username" = "root" ] && [ "$rtsp_password" = "pass" ]; then
    default_active=1
  fi

  http_hash=""
  if [ -r /mnt/config/lighttpd.user ]; then
    IFS=: read -r _ _ http_hash < /mnt/config/lighttpd.user
    http_hash="$(printf '%s' "$http_hash" | tr -d '\r\n')"
    if [ "$http_hash" = "$default_hash" ]; then
      default_active=1
    fi
  fi

  if [ -r /mnt/config/user.pwd ]; then
    read -r all_services_password < /mnt/config/user.pwd
    if [ "$all_services_password" = "pass" ]; then
      default_active=1
    fi
  fi

  echo "$default_active"
}

if [ -n "$F_cmd" ]; then
  case "$F_cmd" in
  hostname)
    if [ -r /proc/sys/kernel/hostname ]; then
      cat /proc/sys/kernel/hostname
    else
      hostname
    fi
    ;;

  lumawb)
    load_lum_awb
    echo "$lum_value"
    echo "$awb_value"
    ;;

  sysusage)
    load_or_compute_usage_metrics
    echo "CPU: $cpu% RAM: $mem_used/$mem_total kB"
    ;;

  statusline)
    load_or_compute_usage_metrics
    profile="$(get_perf_profile)"
    load_lum_awb
    get_ui_ultralite_mode
    get_security_and_mqtt_flags
    read_chip_temperature
    read_power_telemetry
    read_reboot_epoch
    default_password_active="$(default_password_active_flag)"
    default_password_active="$(sanitize_int "$default_password_active" 0)"
    profile_json="$(json_escape "$profile")"
    lum_json="$(json_escape "$lum_value")"
    awb_json="$(json_escape "$awb_value")"
    chip_temp_text_json="$(json_escape "$chip_temp_text")"
    web_mode_json="$(json_escape "$WEB_MODE_VALUE")"
    power_voltage_text_json="$(json_escape "$power_voltage_text")"
    power_estimated_text_json="$(json_escape "$power_estimated_text")"
    echo "{\"sysusage\":\"CPU: $cpu% RAM: $mem_used/$mem_total kB\",\"cpu\":$cpu,\"ram_used_kb\":$mem_used,\"ram_total_kb\":$mem_total,\"ram_percent\":$ram_percent,\"chip_temp_c\":$chip_temp_json,\"chip_temp_text\":\"$chip_temp_text_json\",\"perfprofile\":\"$profile_json\",\"lum\":\"$lum_json\",\"awb\":\"$awb_json\",\"ui_ultralite_mode\":$ui_mode,\"web_mode\":\"$web_mode_json\",\"security_hardening_mode\":$security_hardening_mode,\"mqtt_enabled\":$mqtt_enabled,\"reboot_epoch\":$reboot_epoch,\"default_password_active\":$default_password_active,\"power_voltage_mv\":$power_voltage_mv_json,\"power_voltage_text\":\"$power_voltage_text_json\",\"power_sensor_raw\":$power_sensor_raw_json,\"power_sensor_path\":\"$power_sensor_path_json\",\"power_estimate_enabled\":$power_estimate_enabled,\"power_estimated_mw\":$power_estimated_mw_json,\"power_estimated_text\":\"$power_estimated_text_json\",\"power_estimated_current_ma\":$power_estimated_current_ma_json}"
    ;;

  healthsnapshot)
    load_or_compute_usage_metrics
    profile="$(get_perf_profile)"
    load_lum_awb
    get_ui_ultralite_mode
    get_security_and_mqtt_flags
    read_chip_temperature
    read_power_telemetry
    read_reboot_epoch
    default_password_active="$(default_password_active_flag)"
    default_password_active="$(sanitize_int "$default_password_active" 0)"
    read_rtsp_stream_summary

    if [ -r /proc/sys/kernel/hostname ]; then
      read -r health_hostname < /proc/sys/kernel/hostname
    else
      health_hostname="$(hostname 2>/dev/null)"
    fi
    health_hostname_json="$(json_escape "$health_hostname")"

    health_time_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)"
    health_time_utc_json="$(json_escape "$health_time_utc")"

    uptime_seconds=0
    if [ -r /proc/uptime ]; then
      read -r uptime_raw _ < /proc/uptime
      uptime_seconds="${uptime_raw%.*}"
      uptime_seconds="$(sanitize_int "$uptime_seconds" 0)"
    fi

    profile_json="$(json_escape "$profile")"
    lum_json="$(json_escape "$lum_value")"
    awb_json="$(json_escape "$awb_value")"
    chip_temp_text_json="$(json_escape "$chip_temp_text")"
    power_voltage_text_json="$(json_escape "$power_voltage_text")"
    power_estimated_text_json="$(json_escape "$power_estimated_text")"
    web_mode_json="$(json_escape "$WEB_MODE_VALUE")"
    codec0_json="$(json_escape "$codec0_name")"
    codec1_json="$(json_escape "$codec1_name")"
    watchdog_json="$(last_watchdog_event_json)"

    rtsp_state_json="$(service_state_json /mnt/controlscripts/rtsp-h26x)"
    onvif_state_json="$(service_state_json /mnt/controlscripts/onvif)"

    echo "{\"timestamp_utc\":\"$health_time_utc_json\",\"hostname\":\"$health_hostname_json\",\"uptime_seconds\":$uptime_seconds,\"sysusage\":\"CPU: $cpu% RAM: $mem_used/$mem_total kB\",\"cpu\":$cpu,\"ram_used_kb\":$mem_used,\"ram_total_kb\":$mem_total,\"ram_percent\":$ram_percent,\"chip_temp_c\":$chip_temp_json,\"chip_temp_text\":\"$chip_temp_text_json\",\"perfprofile\":\"$profile_json\",\"lum\":\"$lum_json\",\"awb\":\"$awb_json\",\"ui_ultralite_mode\":$ui_mode,\"web_mode\":\"$web_mode_json\",\"security_hardening_mode\":$security_hardening_mode,\"mqtt_enabled\":$mqtt_enabled,\"reboot_epoch\":$reboot_epoch,\"default_password_active\":$default_password_active,\"power_voltage_mv\":$power_voltage_mv_json,\"power_voltage_text\":\"$power_voltage_text_json\",\"power_sensor_raw\":$power_sensor_raw_json,\"power_sensor_path\":\"$power_sensor_path_json\",\"power_estimate_enabled\":$power_estimate_enabled,\"power_estimated_mw\":$power_estimated_mw_json,\"power_estimated_text\":\"$power_estimated_text_json\",\"power_estimated_current_ma\":$power_estimated_current_ma_json,\"rtsp\":{\"service\":$rtsp_state_json,\"port\":$rtsp_port,\"main\":{\"path\":\"video0_unicast\",\"codec\":\"$codec0_json\",\"width\":$width0,\"height\":$height0,\"fps\":$fps0},\"sub\":{\"path\":\"video1_unicast\",\"codec\":\"$codec1_json\",\"width\":$width1,\"height\":$height1,\"fps\":$fps1}},\"onvif\":{\"service\":$onvif_state_json},\"last_watchdog_event\":\"$watchdog_json\"}"
    ;;

  perfprofile)
    get_perf_profile
    ;;
  *)
    echo "Unsupported command '$F_cmd'"
    ;;
  esac
  fi

exit 0
