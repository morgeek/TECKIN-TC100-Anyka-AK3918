#!/bin/sh

# A very light-weight interface just for responsive ui to get states

source ./func.cgi

# Set content type based on requested format
if wants_json_response; then
  echo "Content-type: application/json"
else
  echo "Content-type: text/plain"
fi
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

USAGE_CACHE_FILE="/tmp/state_usage.cache"
USAGE_CACHE_TTL_SECONDS=2
CPU_USAGE_STATE_FILE="/tmp/state_cpu_usage.state"
CPU_USAGE_MIN_DELTA_TICKS=20
PERFPROFILE_CACHE_FILE="/tmp/state_perfprofile.cache"
PERFPROFILE_CACHE_TTL_SECONDS=5
PWD_CACHE_FILE="/tmp/state_pwd.cache"
PWD_CACHE_TTL_SECONDS=120

_SCRIPT_BTIME=0
_read_script_btime() {
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _SCRIPT_BTIME="$_v" && break
  done < /proc/stat
}
_read_now_ts() {
  [ "$_SCRIPT_BTIME" -gt 0 ] || _read_script_btime
  read -r _rnt_up _ < /proc/uptime
  now_ts=$((_SCRIPT_BTIME + ${_rnt_up%.*}))
  [ "$now_ts" -gt 0 ] || now_ts=0
}
_format_iso8601_utc() {
  _ts="$1"
  _sec_in_day=$((_ts % 86400))
  _days=$((_ts / 86400))
  _hr=$((_sec_in_day / 3600))
  _min=$(((_sec_in_day % 3600) / 60))
  _sec=$((_sec_in_day % 60))
  _q=$((_days / 36524))
  _r=$((_days % 36524))
  _y=$((1970 + _q * 100))
  _q=$((_r / 1461))
  _r=$((_r % 1461))
  _y=$((_y + _q * 4))
  if [ "$_q" -lt 25 ]; then
    _q=$((_r / 365))
    [ "$_q" -gt 3 ] && _q=3
    _r=$((_r - _q * 365))
    _y=$((_y + _q))
  else
    _r=$((_r - 1461))
    _y=$((_y + 4))
  fi
  if [ $(((_y % 4 == 0 && _y % 100 != 0) || _y % 400 == 0)) -eq 1 ]; then
    _month_days="31 29 31 30 31 30 31 31 30 31 30 31"
  else
    _month_days="31 28 31 30 31 30 31 31 30 31 30 31"
  fi
  _m=0
  for _days_in_m in $_month_days; do
    _m=$((_m + 1))
    if [ "$_r" -lt "$_days_in_m" ]; then
      break
    fi
    _r=$((_r - _days_in_m))
  done
  _d=$((_r + 1))
  printf '%04d-%02d-%02dT%02d:%02d:%02dZ' "$_y" "$_m" "$_d" "$_hr" "$_min" "$_sec"
}

get_current_cpu_usage_fast() {
  cpu_active_prev=0
  cpu_total_prev=0
  cpu_util_prev=0
  case "$CPU_USAGE_MIN_DELTA_TICKS" in
    ''|*[!0-9]*) CPU_USAGE_MIN_DELTA_TICKS=20 ;;
  esac
  [ "$CPU_USAGE_MIN_DELTA_TICKS" -lt 1 ] && CPU_USAGE_MIN_DELTA_TICKS=1

  if [ -f "$CPU_USAGE_STATE_FILE" ]; then
    read -r cpu_active_prev cpu_total_prev cpu_util_prev < "$CPU_USAGE_STATE_FILE"
    case "$cpu_active_prev" in ''|*[!0-9]*) cpu_active_prev=0 ;; esac
    case "$cpu_total_prev" in ''|*[!0-9]*) cpu_total_prev=0 ;; esac
    case "$cpu_util_prev" in ''|*[!0-9]*) cpu_util_prev=0 ;; esac
  fi

  # /proc/stat layout:
  # cpu user nice system idle iowait irq softirq steal guest guest_nice
  read -r _ user nice system idle iowait irq softirq steal _ _ < /proc/stat
  cpu_active_cur=$((user + nice + system + irq + softirq + steal))
  cpu_total_cur=$((cpu_active_cur + idle + iowait))

  delta_total=$((cpu_total_cur - cpu_total_prev))
  delta_active=$((cpu_active_cur - cpu_active_prev))

  if [ "$cpu_total_prev" -le 0 ] || [ "$delta_total" -lt 0 ]; then
    printf '%s %s %s\n' "$cpu_active_cur" "$cpu_total_cur" 0 > "$CPU_USAGE_STATE_FILE"
    echo "0"
    return
  fi

  if [ "$delta_total" -lt "$CPU_USAGE_MIN_DELTA_TICKS" ]; then
    # Calls happened too close together; keep previous stable sample.
    echo "$cpu_util_prev"
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
  printf '%s %s %s\n' "$cpu_active_cur" "$cpu_total_cur" "$cpu_util" > "$CPU_USAGE_STATE_FILE"
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

  _read_now_ts
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
  _read_now_ts
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

# Load configs into shell variables in one pass per file to save IO/forks.
load_conf_file() {
  _lcf_path="$1"
  [ -f "$_lcf_path" ] || return 1
  while IFS='=' read -r _lcf_k _lcf_v; do
    case "$_lcf_k" in
      ''|'#'*) continue ;;
    esac
    _lcf_k_clean="$(printf '%s' "$_lcf_k" | tr -cd 'A-Za-z0-9_')"
    [ -n "$_lcf_k_clean" ] || continue
    eval "C_${_lcf_k_clean}=\"\$_lcf_v\""
  done < "$_lcf_path"
}

# Helper to get the loaded value or default
get_cfg() {
  eval "_gc_val=\"\$C_$1\""
  if [ -z "$_gc_val" ]; then
    echo "$2"
  else
    echo "$_gc_val"
  fi
}

normalize_web_mode_value() {
  case "$1" in
    ultra-lite|ultralite)
      echo "ultra-lite"
      ;;
    full|http|off)
      echo "$1"
      ;;
    *)
      echo "full"
      ;;
  esac
}

detect_primary_ip() {
  primary_ip=""
  if [ -r /tmp/camera_ip.txt ]; then
    read -r primary_ip < /tmp/camera_ip.txt
  fi
  if [ -z "$primary_ip" ]; then
    primary_ip="$(ifconfig 2>/dev/null | awk '
      /inet addr:[0-9]/ {
        split($2, a, ":")
        if (a[2] !~ /^127\./) {
          print a[2]
          exit
        }
      }
      /inet [0-9]/ {
        if ($2 !~ /^127\./) {
          print $2
          exit
        }
      }
    ')"
  fi
  [ -n "$primary_ip" ] || primary_ip="CAMERA-IP"
}

truthy_flag() {
  case "$1" in
    1|true|on|yes|enabled)
      echo "1"
      ;;
    *)
      echo "0"
      ;;
  esac
}

userinfo_safe() {
  case "$1" in
    ''|*[!A-Za-z0-9._~-]*)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

prepare_rtsp_auth_template() {
  url_user="$1"
  url_password="$2"
  rtsp_url_auth_embedded=0
  rtsp_url_auth_warning=""
  rtsp_url_auth_prefix=""

  if [ -n "$url_user" ] || [ -n "$url_password" ]; then
    if userinfo_safe "$url_user" && userinfo_safe "$url_password"; then
      rtsp_url_auth_prefix="${url_user}:${url_password}@"
      rtsp_url_auth_embedded=1
    else
      rtsp_url_auth_prefix="USERNAME:PASSWORD@"
      rtsp_url_auth_warning="RTSP credentials contain URL-sensitive characters; replace USERNAME/PASSWORD or percent-encode them in client configs."
    fi
  fi
}

build_rtsp_url_template() {
  url_host="$1"
  url_port="$2"
  url_path="$3"
  printf 'rtsp://%s%s:%s/%s' "$rtsp_url_auth_prefix" "$url_host" "$url_port" "$url_path"
}

build_web_base_url() {
  web_mode_value="$1"
  web_host="$2"
  ultralite_port_value="$3"

  web_enabled=1
  web_scheme="https"
  web_port=443
  web_base_url=""

  case "$web_mode_value" in
    full)
      web_scheme="https"
      web_port=443
      ;;
    http)
      web_scheme="http"
      web_port=80
      ;;
    ultra-lite)
      web_scheme="http"
      web_port="$ultralite_port_value"
      ;;
    off)
      web_enabled=0
      web_scheme=""
      web_port=0
      ;;
    *)
      web_scheme="https"
      web_port=443
      ;;
  esac

  if [ "$web_enabled" = "1" ]; then
    case "${web_scheme}:${web_port}" in
      https:443|http:80)
        web_base_url="${web_scheme}://${web_host}"
        ;;
      *)
        web_base_url="${web_scheme}://${web_host}:${web_port}"
        ;;
    esac
  fi
}

rtsp_describe_local_ok() {
  describe_path="$1"
  describe_port="$2"
  describe_user="$3"
  describe_password="$4"
  describe_timeout="$5"

  [ -x /mnt/bin/curl ] || return 1

  if [ -n "$describe_user" ]; then
    describe_sdp=$(/mnt/bin/curl -s -S -m "$describe_timeout" -X DESCRIBE -u "${describe_user}:${describe_password}" "rtsp://127.0.0.1:${describe_port}/${describe_path}" 2>/dev/null) || return 1
  else
    describe_sdp=$(/mnt/bin/curl -s -S -m "$describe_timeout" -X DESCRIBE "rtsp://127.0.0.1:${describe_port}/${describe_path}" 2>/dev/null) || return 1
  fi

  printf '%s' "$describe_sdp" | grep -q "m=video" || return 1
}

slugify_value() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g; s/__*/_/g; s/^_//; s/_$//'
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
    # Main Stream [0]
    codec0="$(sanitize_int "$(get_cfg 0_codec 2)" 2)"
    width0="$(sanitize_int "$(get_cfg 0_width 1280)" 1280)"
    height0="$(sanitize_int "$(get_cfg 0_height 720)" 720)"
    fps0="$(sanitize_int "$(get_cfg 0_fps 16)" 16)"
    bps0="$(sanitize_int "$(get_cfg 0_bps 1000)" 1000)"
    profile0="$(sanitize_int "$(get_cfg 0_profile 3)" 3)"
    goplen0="$(sanitize_int "$(get_cfg 0_goplen 50)" 50)"
    brmode0="$(sanitize_int "$(get_cfg 0_brmode 1)" 1)"
    minqp0="$(sanitize_int "$(get_cfg 0_minqp 20)" 20)"
    maxqp0="$(sanitize_int "$(get_cfg 0_maxqp 51)" 51)"
    smartmode0="$(sanitize_int "$(get_cfg 0_smartmode 1)" 1)"
    smartgoplen0="$(sanitize_int "$(get_cfg 0_smartgoplen 0)" 0)"
    smartquality0="$(sanitize_int "$(get_cfg 0_smartquality 100)" 100)"
    smartstatic0="$(sanitize_int "$(get_cfg 0_smartstatic 500)" 500)"
    maxkbps0="$(sanitize_int "$(get_cfg 0_maxkbps 1500)" 1500)"
    targetkbps0="$(sanitize_int "$(get_cfg 0_targetkbps 1200)" 1200)"

    # Sub Stream [1]
    codec1="$(sanitize_int "$(get_cfg 1_codec 0)" 0)"
    width1="$(sanitize_int "$(get_cfg 1_width 640)" 640)"
    height1="$(sanitize_int "$(get_cfg 1_height 360)" 360)"
    fps1="$(sanitize_int "$(get_cfg 1_fps 8)" 8)"
    bps1="$(sanitize_int "$(get_cfg 1_bps 250)" 250)"
    profile1="$(sanitize_int "$(get_cfg 1_profile 0)" 0)"
    goplen1="$(sanitize_int "$(get_cfg 1_goplen 32)" 32)"
    brmode1="$(sanitize_int "$(get_cfg 1_brmode 1)" 1)"
    minqp1="$(sanitize_int "$(get_cfg 1_minqp 20)" 20)"
    maxqp1="$(sanitize_int "$(get_cfg 1_maxqp 51)" 51)"
    smartmode1="$(sanitize_int "$(get_cfg 1_smartmode 1)" 1)"
    smartgoplen1="$(sanitize_int "$(get_cfg 1_smartgoplen 0)" 0)"
    smartquality1="$(sanitize_int "$(get_cfg 1_smartquality 50)" 50)"
    smartstatic1="$(sanitize_int "$(get_cfg 1_smartstatic 150)" 150)"
    maxkbps1="$(sanitize_int "$(get_cfg 1_maxkbps 450)" 450)"
    targetkbps1="$(sanitize_int "$(get_cfg 1_targetkbps 400)" 400)"

    rtsp_port="$(sanitize_int "$(get_cfg PORT 554)" 554)"
}

last_watchdog_event_json() {
  event=""
  if [ -r /tmp/log/service-watchdog.log ]; then
    event="$(tail -n 1 /tmp/log/service-watchdog.log 2>/dev/null)"
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
  mqtt_last_pub_ts=0
  mqtt_last_pub_ok=-1

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

  if [ -f /tmp/mqtt_last_pub.status ]; then
    read -r _mq_ts _mq_result < /tmp/mqtt_last_pub.status
    case "$_mq_ts" in ''|*[!0-9]*) _mq_ts=0 ;; esac
    case "$_mq_result" in
      ok)   mqtt_last_pub_ok=1 ;;
      fail) mqtt_last_pub_ok=0 ;;
    esac
    mqtt_last_pub_ts="$_mq_ts"
  fi
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

  _read_now_ts
  [ "$now_ts" -gt 0 ] || return 1
  [ "$cached_ts" -le "$now_ts" ] || return 1
  age=$((now_ts - cached_ts))
  [ "$age" -le "$PERFPROFILE_CACHE_TTL_SECONDS" ] || return 1

  profile="$cached_profile"
  return 0
}

save_cached_perf_profile() {
  _read_now_ts
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

get_sd_usage() {
  sd_used_kb=0
  sd_total_kb=0
  sd_percent=0

  # df output: Filesystem 1K-blocks Used Available Use% Mounted
  # BusyBox df may omit header or use slightly different columns; parse by mount point.
  while read -r _fs _total _used _avail _pct _mp _rest; do
    case "$_mp" in
      /mnt|/mnt/)
        case "$_total" in ''|*[!0-9]*) continue ;; esac
        case "$_used"  in ''|*[!0-9]*) continue ;; esac
        sd_total_kb="$_total"
        sd_used_kb="$_used"
        # _pct may be "72%" — strip trailing %
        _pct_num="${_pct%%%}"
        case "$_pct_num" in ''|*[!0-9]*) _pct_num=0 ;; esac
        sd_percent="$_pct_num"
        break
        ;;
    esac
  done <<EOF
$(df -k /mnt 2>/dev/null | tail -n +2)
EOF
}

read_reboot_epoch() {
  reboot_epoch=0

  [ "$_SCRIPT_BTIME" -gt 0 ] || _read_script_btime
  if [ "$_SCRIPT_BTIME" -gt 0 ]; then
    reboot_epoch="$_SCRIPT_BTIME"
  fi

  if [ "$reboot_epoch" -le 0 ] && [ -r /proc/uptime ]; then
    read -r uptime_raw _ < /proc/uptime
    uptime_seconds_fallback="${uptime_raw%.*}"
    uptime_seconds_fallback="$(sanitize_int "$uptime_seconds_fallback" 0)"
    _read_now_ts
    if [ "$now_ts" -gt 0 ] && [ "$uptime_seconds_fallback" -gt 0 ]; then
      reboot_epoch=$((now_ts - uptime_seconds_fallback))
    fi
  fi
}

default_password_active_flag() {
  # Caching to reduce IO/CPU on frequent statusline polls
  if [ -f "$PWD_CACHE_FILE" ]; then
    read -r cached_ts cached_val < "$PWD_CACHE_FILE"
    _read_now_ts
    if [ "$now_ts" -gt 0 ] && [ "$cached_ts" -le "$now_ts" ]; then
      age=$((now_ts - cached_ts))
      if [ "$age" -le "$PWD_CACHE_TTL_SECONDS" ]; then
        echo "$cached_val"
        return 0
      fi
    fi
  fi

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
    # Keep compatibility with minimal BusyBox builds where `tr` may be absent.
    http_hash="$(printf '%s' "$http_hash" | sed 's/\r//g')"
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
  _read_now_ts; printf '%s %s\n' "$now_ts" "$default_active" > "$PWD_CACHE_FILE"
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
    get_sd_usage
    default_password_active="$(default_password_active_flag)"
    default_password_active="$(sanitize_int "$default_password_active" 0)"
    profile_json="$(json_escape "$profile")"
    lum_json="$(json_escape "$lum_value")"
    awb_json="$(json_escape "$awb_value")"
    web_mode_json="$(json_escape "$WEB_MODE_VALUE")"
    csrf_token=""
    # Ensure a CSRF token exists so the client ALWAYS receives one on its first
    # statusline poll. Without this, if no CGI had called csrf_guard since boot
    # the token file would be absent, the client would hold no token, and the
    # first authenticated POST (now that action.cgi enforces CSRF) would 403 —
    # a bootstrap lock-out. Generating it here (once, when missing) closes that.
    if [ ! -s /tmp/csrf_token ]; then
        if [ -r /dev/urandom ]; then
            _stt="$(head -c 16 /dev/urandom | hexdump -e '16/1 "%02x"' 2>/dev/null)"
        fi
        [ -n "$_stt" ] || _stt="$(date +%s%N | md5sum | cut -c1-32)"
        printf '%s' "$_stt" > /tmp/csrf_token 2>/dev/null || true
    fi
    if [ -r /tmp/csrf_token ]; then
        read -r csrf_token < /tmp/csrf_token
        # Strip any non-hex characters for safety
        csrf_token="$(printf '%s' "$csrf_token" | tr -cd '0-9a-fA-F')"
    fi
    # Update notifier integration
    update_available=0
    update_latest="n/a"
    if [ -r /tmp/update_status.json ]; then
        update_available="$(/mnt/bin/jq -r '.update_available' /tmp/update_status.json 2>/dev/null)"
        update_latest="$(/mnt/bin/jq -r '.latest_version' /tmp/update_status.json 2>/dev/null)"
        [ "$update_available" = "1" ] || update_available=0
        [ -n "$update_latest" ] || update_latest="n/a"
    fi
    update_latest_json="$(json_escape "$update_latest")"

    # Firmware version for the UI topbar chip. Read with the `read` builtin
    # (no fork) since this runs on every hot statusline poll.
    current_version="n/a"
    if [ -r /mnt/VERSION ]; then
        read -r current_version < /mnt/VERSION
        [ -n "$current_version" ] || current_version="n/a"
    fi
    current_version_json="$(json_escape "$current_version")"

    echo "{\"sysusage\":\"CPU: $cpu% RAM: $mem_used/$mem_total kB\",\"cpu\":$cpu,\"ram_used_kb\":$mem_used,\"ram_total_kb\":$mem_total,\"ram_percent\":$ram_percent,\"sd_used_kb\":$sd_used_kb,\"sd_total_kb\":$sd_total_kb,\"sd_percent\":$sd_percent,\"perfprofile\":\"$profile_json\",\"lum\":\"$lum_json\",\"awb\":\"$awb_json\",\"ui_ultralite_mode\":$ui_mode,\"web_mode\":\"$web_mode_json\",\"security_hardening_mode\":$security_hardening_mode,\"mqtt_enabled\":$mqtt_enabled,\"mqtt_last_pub_ts\":$mqtt_last_pub_ts,\"mqtt_last_pub_ok\":$mqtt_last_pub_ok,\"default_password_active\":$default_password_active,\"csrf_token\":\"$csrf_token\",\"update_available\":$update_available,\"update_latest_version\":\"$update_latest_json\",\"current_version\":\"$current_version_json\"}"
    ;;

  integrationtest)
    detect_primary_ip
    if [ -r /proc/sys/kernel/hostname ]; then
      read -r test_hostname < /proc/sys/kernel/hostname
    else
      test_hostname="$(hostname 2>/dev/null)"
    fi
    [ -n "$test_hostname" ] || test_hostname="TC100 Camera"

    read_rtsp_stream_summary
    rtsp_username_test="$(read_conf_value /mnt/config/rtspserver.conf USERNAME root)"
    rtsp_password_test="$(read_conf_value /mnt/config/rtspserver.conf USERPASSWORD pass)"
    rtsp_substream_enabled_test="$(truthy_flag "$(read_conf_value /mnt/config/boot.conf RTSP_SUBSTREAM 1)")"
    rtsp_timeout_test="$(sanitize_int "$(read_conf_value /mnt/config/boot.conf RTSP_HEALTHCHECK_TIMEOUT_SECONDS 4)" 4)"
    if [ "$rtsp_timeout_test" -lt 2 ] || [ "$rtsp_timeout_test" -gt 30 ]; then
      rtsp_timeout_test=4
    fi
    onvif_port_test="$(sanitize_int "$(read_conf_value /mnt/config/onvif.conf ONVIF_PORT 8081)" 8081)"
    if [ "$onvif_port_test" -lt 1 ] || [ "$onvif_port_test" -gt 65535 ]; then
      onvif_port_test=8081
    fi
    mqtt_enabled_test="$(truthy_flag "$(read_conf_value /mnt/config/mqtt.conf MQTT_ENABLE 0)")"
    mqtt_topic_root_test="$(read_conf_value /mnt/config/mqtt.conf MQTT_TOPIC_ROOT tc100/camera)"
    mqtt_broker_host_test="$(read_conf_value /mnt/config/mqtt.conf MQTT_HOST 127.0.0.1)"
    mqtt_broker_port_test="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf MQTT_PORT 1883)" 1883)"
    if [ "$mqtt_broker_port_test" -lt 1 ] || [ "$mqtt_broker_port_test" -gt 65535 ]; then
      mqtt_broker_port_test=1883
    fi

    rtsp_main_status="fail"
    rtsp_main_detail="RTSP service is not running."
    if [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x status >/dev/null 2>&1; then
      if [ -x /mnt/bin/curl ]; then
        if rtsp_describe_local_ok "video0_unicast" "$rtsp_port" "$rtsp_username_test" "$rtsp_password_test" "$rtsp_timeout_test"; then
          rtsp_main_status="ok"
          rtsp_main_detail="DESCRIBE succeeded for video0_unicast."
        else
          rtsp_main_status="fail"
          rtsp_main_detail="DESCRIBE failed for video0_unicast."
        fi
      else
        rtsp_main_status="ok"
        rtsp_main_detail="RTSP service is running; DESCRIBE skipped because curl is unavailable."
      fi
    fi

    rtsp_sub_status="disabled"
    rtsp_sub_detail="Substream disabled by RTSP_SUBSTREAM=0."
    if [ "$rtsp_substream_enabled_test" = "1" ]; then
      rtsp_sub_status="fail"
      rtsp_sub_detail="RTSP substream check failed because RTSP service is not running."
      if [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x status >/dev/null 2>&1; then
        if [ -x /mnt/bin/curl ]; then
          if rtsp_describe_local_ok "video1_unicast" "$rtsp_port" "$rtsp_username_test" "$rtsp_password_test" "$rtsp_timeout_test"; then
            rtsp_sub_status="ok"
            rtsp_sub_detail="DESCRIBE succeeded for video1_unicast."
          else
            rtsp_sub_status="fail"
            rtsp_sub_detail="DESCRIBE failed for video1_unicast."
          fi
        else
          rtsp_sub_status="ok"
          rtsp_sub_detail="RTSP service is running; substream DESCRIBE skipped because curl is unavailable."
        fi
      fi
    fi

    onvif_status="disabled"
    onvif_detail="ONVIF service is not running."
    if [ -x /mnt/controlscripts/onvif ] && /mnt/controlscripts/onvif status >/dev/null 2>&1; then
      if /mnt/controlscripts/onvif health >/dev/null 2>&1; then
        onvif_status="ok"
        onvif_detail="ONVIF service is healthy on port ${onvif_port_test}."
      else
        onvif_status="fail"
        onvif_detail="ONVIF health check failed on port ${onvif_port_test}."
      fi
    fi

    mqtt_status="disabled"
    mqtt_detail="MQTT bridge disabled in config."
    if [ "$mqtt_enabled_test" = "1" ]; then
      if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
        _read_now_ts
        mqtt_selftest_payload="$(printf '{"ts":%s,"type":"integration_selftest","origin":"state.cgi"}' "$now_ts")"
        if /mnt/scripts/mqtt-bridge.sh publish selftest "$mqtt_selftest_payload" 0 >/dev/null 2>&1; then
          mqtt_status="ok"
          mqtt_detail="Published self-test payload to ${mqtt_topic_root_test}/selftest via ${mqtt_broker_host_test}:${mqtt_broker_port_test}."
        else
          mqtt_status="fail"
          mqtt_detail="MQTT publish failed to ${mqtt_broker_host_test}:${mqtt_broker_port_test}."
        fi
      else
        mqtt_status="fail"
        mqtt_detail="MQTT bridge helper script is missing."
      fi
    fi

    snapshot_status="fail"
    snapshot_detail="Snapshot capture failed."
    _read_now_ts
    snapshot_tmp="/tmp/integration-selftest.$$.$now_ts.jpg"
    if [ -x /mnt/bin/getimage ]; then
      if timeout 5 /mnt/bin/getimage > "$snapshot_tmp" 2>/dev/null && [ -s "$snapshot_tmp" ]; then
        snapshot_status="ok"
        snapshot_detail="Local snapshot capture succeeded."
      else
        snapshot_status="fail"
        snapshot_detail="getimage did not return a valid JPEG."
      fi
    else
      snapshot_status="fail"
      snapshot_detail="getimage binary is missing."
    fi
    rm -f "$snapshot_tmp" >/dev/null 2>&1 || true

    overall_status="ok"
    overall_ok=1
    for integration_test_status in "$rtsp_main_status" "$rtsp_sub_status" "$onvif_status" "$mqtt_status" "$snapshot_status"; do
      if [ "$integration_test_status" = "fail" ]; then
        overall_status="fail"
        overall_ok=0
        break
      fi
      if [ "$integration_test_status" = "disabled" ] && [ "$overall_status" = "ok" ]; then
        overall_status="warn"
      fi
    done

    _read_now_ts
    test_time_utc="$(_format_iso8601_utc "$now_ts")"
    test_time_utc_json="$(json_escape "$test_time_utc")"
    test_hostname_json="$(json_escape "$test_hostname")"
    primary_ip_json="$(json_escape "$primary_ip")"
    overall_status_json="$(json_escape "$overall_status")"
    rtsp_main_status_json="$(json_escape "$rtsp_main_status")"
    rtsp_main_detail_json="$(json_escape "$rtsp_main_detail")"
    rtsp_sub_status_json="$(json_escape "$rtsp_sub_status")"
    rtsp_sub_detail_json="$(json_escape "$rtsp_sub_detail")"
    onvif_status_json="$(json_escape "$onvif_status")"
    onvif_detail_json="$(json_escape "$onvif_detail")"
    mqtt_status_json="$(json_escape "$mqtt_status")"
    mqtt_detail_json="$(json_escape "$mqtt_detail")"
    snapshot_status_json="$(json_escape "$snapshot_status")"
    snapshot_detail_json="$(json_escape "$snapshot_detail")"

    printf '{"timestamp_utc":"%s","hostname":"%s","primary_ip":"%s","overall_status":"%s","overall_ok":%s,"tests":{"rtsp_main":{"status":"%s","detail":"%s"},"rtsp_sub":{"status":"%s","detail":"%s"},"onvif":{"status":"%s","detail":"%s"},"mqtt_publish":{"status":"%s","detail":"%s"},"snapshot":{"status":"%s","detail":"%s"}}}\n' \
      "$test_time_utc_json" "$test_hostname_json" "$primary_ip_json" "$overall_status_json" "$overall_ok" \
      "$rtsp_main_status_json" "$rtsp_main_detail_json" \
      "$rtsp_sub_status_json" "$rtsp_sub_detail_json" \
      "$onvif_status_json" "$onvif_detail_json" \
      "$mqtt_status_json" "$mqtt_detail_json" \
      "$snapshot_status_json" "$snapshot_detail_json"
    ;;

  integrationmanifest)
    if [ -r /proc/sys/kernel/hostname ]; then
      read -r manifest_hostname < /proc/sys/kernel/hostname
    else
      manifest_hostname="$(hostname 2>/dev/null)"
    fi
    [ -n "$manifest_hostname" ] || manifest_hostname="TC100 Camera"
    manifest_redact="$(truthy_flag "$F_redact")"

    detect_primary_ip

    manifest_camera_slug="$(slugify_value "$manifest_hostname")"
    [ -n "$manifest_camera_slug" ] || manifest_camera_slug="$(slugify_value "$(read_conf_value /mnt/config/mqtt.conf MQTT_CLIENT_ID tc100-camera)")"
    [ -n "$manifest_camera_slug" ] || manifest_camera_slug="tc100_camera"

    manifest_web_mode="$(normalize_web_mode_value "$(read_conf_value /mnt/config/boot.conf WEB_MODE full)")"
    manifest_ultralite_http_port="$(sanitize_int "$(read_conf_value /mnt/config/boot.conf ULTRALITE_HTTP_PORT 80)" 80)"
    if [ "$manifest_ultralite_http_port" -lt 1 ] || [ "$manifest_ultralite_http_port" -gt 65535 ]; then
      manifest_ultralite_http_port=80
    fi
    build_web_base_url "$manifest_web_mode" "$primary_ip" "$manifest_ultralite_http_port"

    web_snapshot_url=""
    web_healthsnapshot_url=""
    web_manifest_url=""
    web_motion_events_url=""
    web_motion_thumbnail_url=""
    if [ "$web_enabled" = "1" ]; then
      web_snapshot_url="${web_base_url}/cgi-bin/currentpic.cgi"
      web_healthsnapshot_url="${web_base_url}/cgi-bin/state.cgi?cmd=healthsnapshot"
      web_manifest_url="${web_base_url}/cgi-bin/state.cgi?cmd=integrationmanifest"
      web_motion_events_url="${web_base_url}/cgi-bin/motionevents.cgi?limit=20"
      web_motion_thumbnail_url="${web_base_url}/cgi-bin/motionthumb.cgi"
    fi

    read_rtsp_stream_summary
    rtsp_username="$(read_conf_value /mnt/config/rtspserver.conf USERNAME root)"
    rtsp_password="$(read_conf_value /mnt/config/rtspserver.conf USERPASSWORD pass)"
    rtsp_substream_enabled="$(truthy_flag "$(read_conf_value /mnt/config/boot.conf RTSP_SUBSTREAM 1)")"
    rtsp_audio_enabled="$(truthy_flag "$(read_conf_value /mnt/config/boot.conf RTSP_AUDIO 1)")"
    onvif_stream_policy_value="$(read_conf_value /mnt/config/boot.conf ONVIF_STREAM_POLICY main-primary)"
    rtsp_manifest_username="$rtsp_username"
    rtsp_manifest_password="$rtsp_password"
    if [ "$manifest_redact" = "1" ]; then
      rtsp_auth_embedded=0
      if [ -n "$rtsp_username" ] || [ -n "$rtsp_password" ]; then
        rtsp_manifest_username="USERNAME"
        rtsp_manifest_password=""
        rtsp_url_auth_prefix="USERNAME:PASSWORD@"
        rtsp_auth_warning="Credentials omitted from redacted manifest; replace USERNAME/PASSWORD in client configs."
      else
        rtsp_manifest_username=""
        rtsp_manifest_password=""
        rtsp_url_auth_prefix=""
        rtsp_auth_warning=""
      fi
    else
      prepare_rtsp_auth_template "$rtsp_username" "$rtsp_password"
      rtsp_auth_embedded="$rtsp_url_auth_embedded"
      rtsp_auth_warning="$rtsp_url_auth_warning"
    fi
    rtsp_main_url="$(build_rtsp_url_template "$primary_ip" "$rtsp_port" "video0_unicast")"
    rtsp_sub_url=""
    if [ "$rtsp_substream_enabled" = "1" ]; then
      rtsp_sub_url="$(build_rtsp_url_template "$primary_ip" "$rtsp_port" "video1_unicast")"
    fi

    frigate_record_url="$rtsp_main_url"
    frigate_detect_url="$rtsp_main_url"
    frigate_detect_source="main"
    if [ "$rtsp_substream_enabled" = "1" ] && [ -n "$rtsp_sub_url" ]; then
      frigate_detect_url="$rtsp_sub_url"
      frigate_detect_source="sub"
    fi

    onvif_port="$(sanitize_int "$(read_conf_value /mnt/config/onvif.conf ONVIF_PORT 8081)" 8081)"
    if [ "$onvif_port" -lt 1 ] || [ "$onvif_port" -gt 65535 ]; then
      onvif_port=8081
    fi
    onvif_device_service_url="http://${primary_ip}:${onvif_port}/onvif/device_service"

    mqtt_enabled_flag="$(truthy_flag "$(read_conf_value /mnt/config/mqtt.conf MQTT_ENABLE 0)")"
    mqtt_broker_host="$(read_conf_value /mnt/config/mqtt.conf MQTT_HOST 127.0.0.1)"
    mqtt_broker_port="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf MQTT_PORT 1883)" 1883)"
    if [ "$mqtt_broker_port" -lt 1 ] || [ "$mqtt_broker_port" -gt 65535 ]; then
      mqtt_broker_port=1883
    fi
    mqtt_username="$(read_conf_value /mnt/config/mqtt.conf MQTT_USER "")"
    mqtt_password="$(read_conf_value /mnt/config/mqtt.conf MQTT_PASSWORD "")"
    mqtt_manifest_username="$mqtt_username"
    mqtt_manifest_password="$mqtt_password"
    if [ "$manifest_redact" = "1" ]; then
      mqtt_manifest_username=""
      mqtt_manifest_password=""
    fi
    mqtt_client_id="$(read_conf_value /mnt/config/mqtt.conf MQTT_CLIENT_ID tc100-camera)"
    mqtt_topic_root="$(read_conf_value /mnt/config/mqtt.conf MQTT_TOPIC_ROOT tc100/camera)"
    mqtt_command_topic="$(read_conf_value /mnt/config/mqtt.conf MQTT_TOPIC_COMMAND "")"
    [ -n "$mqtt_command_topic" ] || mqtt_command_topic="${mqtt_topic_root}/command"
    mqtt_discovery_enabled="$(truthy_flag "$(read_conf_value /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_ENABLE 1)")"
    mqtt_discovery_prefix="$(read_conf_value /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_PREFIX homeassistant)"
    mqtt_availability_topic="${mqtt_topic_root}/availability"
    mqtt_health_topic="${mqtt_topic_root}/health"
    mqtt_motion_state_topic="${mqtt_topic_root}/motion/state"
    mqtt_event_topic="${mqtt_topic_root}/event"
    mqtt_snapshot_last_path_topic="${mqtt_topic_root}/snapshot/last_path"
    mqtt_integration_manifest_topic="${mqtt_topic_root}/integration/manifest"
    mqtt_integration_selftest_topic="${mqtt_topic_root}/integration/selftest"
    mqtt_command_result_topic="${mqtt_topic_root}/command/result"
    mqtt_command_last_result_topic="${mqtt_topic_root}/command/last_result"
    mqtt_repair_last_result_topic="${mqtt_topic_root}/repair/last_result"

    _read_now_ts
    manifest_time_utc="$(_format_iso8601_utc "$now_ts")"
    manifest_time_utc_json="$(json_escape "$manifest_time_utc")"
    manifest_hostname_json="$(json_escape "$manifest_hostname")"
    manifest_camera_slug_json="$(json_escape "$manifest_camera_slug")"
    primary_ip_json="$(json_escape "$primary_ip")"
    web_mode_json="$(json_escape "$manifest_web_mode")"
    web_base_url_json="$(json_escape "$web_base_url")"
    web_snapshot_url_json="$(json_escape "$web_snapshot_url")"
    web_healthsnapshot_url_json="$(json_escape "$web_healthsnapshot_url")"
    web_manifest_url_json="$(json_escape "$web_manifest_url")"
    web_motion_events_url_json="$(json_escape "$web_motion_events_url")"
    web_motion_thumbnail_url_json="$(json_escape "$web_motion_thumbnail_url")"
    rtsp_username_json="$(json_escape "$rtsp_manifest_username")"
    rtsp_password_json="$(json_escape "$rtsp_manifest_password")"
    rtsp_auth_warning_json="$(json_escape "$rtsp_auth_warning")"
    rtsp_main_url_json="$(json_escape "$rtsp_main_url")"
    rtsp_sub_url_json="$(json_escape "$rtsp_sub_url")"
    codec0_json="$(json_escape "$codec0_name")"
    codec1_json="$(json_escape "$codec1_name")"
    frigate_record_url_json="$(json_escape "$frigate_record_url")"
    frigate_detect_url_json="$(json_escape "$frigate_detect_url")"
    frigate_detect_source_json="$(json_escape "$frigate_detect_source")"
    onvif_device_service_url_json="$(json_escape "$onvif_device_service_url")"
    onvif_stream_policy_json="$(json_escape "$onvif_stream_policy_value")"
    mqtt_broker_host_json="$(json_escape "$mqtt_broker_host")"
    mqtt_username_json="$(json_escape "$mqtt_manifest_username")"
    mqtt_password_json="$(json_escape "$mqtt_manifest_password")"
    mqtt_client_id_json="$(json_escape "$mqtt_client_id")"
    mqtt_topic_root_json="$(json_escape "$mqtt_topic_root")"
    mqtt_command_topic_json="$(json_escape "$mqtt_command_topic")"
    mqtt_discovery_prefix_json="$(json_escape "$mqtt_discovery_prefix")"
    mqtt_availability_topic_json="$(json_escape "$mqtt_availability_topic")"
    mqtt_health_topic_json="$(json_escape "$mqtt_health_topic")"
    mqtt_motion_state_topic_json="$(json_escape "$mqtt_motion_state_topic")"
    mqtt_event_topic_json="$(json_escape "$mqtt_event_topic")"
    mqtt_snapshot_last_path_topic_json="$(json_escape "$mqtt_snapshot_last_path_topic")"
    mqtt_integration_manifest_topic_json="$(json_escape "$mqtt_integration_manifest_topic")"
    mqtt_integration_selftest_topic_json="$(json_escape "$mqtt_integration_selftest_topic")"
    mqtt_command_result_topic_json="$(json_escape "$mqtt_command_result_topic")"
    mqtt_command_last_result_topic_json="$(json_escape "$mqtt_command_last_result_topic")"
    mqtt_repair_last_result_topic_json="$(json_escape "$mqtt_repair_last_result_topic")"

    printf '{"generated_at_utc":"%s","hostname":"%s","camera_slug":"%s","primary_ip":"%s","web":{"mode":"%s","enabled":%s,"base_url":"%s","snapshot_url":"%s","healthsnapshot_url":"%s","integration_manifest_url":"%s","motion_events_url":"%s","motion_thumbnail_url":"%s"},"rtsp":{"username":"%s","password":"%s","port":%s,"auth_embedded":%s,"auth_warning":"%s","audio_enabled":%s,"substream_enabled":%s,"main":{"path":"video0_unicast","url":"%s","codec":"%s","width":%s,"height":%s,"fps":%s},"sub":{"path":"video1_unicast","url":"%s","codec":"%s","width":%s,"height":%s,"fps":%s},"frigate":{"record_url":"%s","detect_url":"%s","detect_source":"%s"}},"onvif":{"port":%s,"device_service_url":"%s","stream_policy":"%s"},"mqtt":{"enabled":%s,"broker_host":"%s","broker_port":%s,"username":"%s","password":"%s","client_id":"%s","discovery_enabled":%s,"discovery_prefix":"%s","topic_root":"%s","command_topic":"%s","availability_topic":"%s","health_topic":"%s","motion_state_topic":"%s","event_topic":"%s","snapshot_last_path_topic":"%s","integration_manifest_topic":"%s","integration_selftest_topic":"%s","command_result_topic":"%s","command_last_result_topic":"%s","repair_last_result_topic":"%s"}}\n' \
      "$manifest_time_utc_json" "$manifest_hostname_json" "$manifest_camera_slug_json" "$primary_ip_json" \
      "$web_mode_json" "$web_enabled" "$web_base_url_json" "$web_snapshot_url_json" "$web_healthsnapshot_url_json" "$web_manifest_url_json" "$web_motion_events_url_json" "$web_motion_thumbnail_url_json" \
      "$rtsp_username_json" "$rtsp_password_json" "$rtsp_port" "$rtsp_auth_embedded" "$rtsp_auth_warning_json" "$rtsp_audio_enabled" "$rtsp_substream_enabled" \
      "$rtsp_main_url_json" "$codec0_json" "$width0" "$height0" "$fps0" \
      "$rtsp_sub_url_json" "$codec1_json" "$width1" "$height1" "$fps1" \
      "$frigate_record_url_json" "$frigate_detect_url_json" "$frigate_detect_source_json" \
      "$onvif_port" "$onvif_device_service_url_json" "$onvif_stream_policy_json" \
      "$mqtt_enabled_flag" "$mqtt_broker_host_json" "$mqtt_broker_port" "$mqtt_username_json" "$mqtt_password_json" "$mqtt_client_id_json" "$mqtt_discovery_enabled" "$mqtt_discovery_prefix_json" "$mqtt_topic_root_json" "$mqtt_command_topic_json" "$mqtt_availability_topic_json" "$mqtt_health_topic_json" "$mqtt_motion_state_topic_json" "$mqtt_event_topic_json" "$mqtt_snapshot_last_path_topic_json" "$mqtt_integration_manifest_topic_json" "$mqtt_integration_selftest_topic_json" "$mqtt_command_result_topic_json" "$mqtt_command_last_result_topic_json" "$mqtt_repair_last_result_topic_json"
    ;;

  healthsnapshot)
    HEALTH_SNAP_CACHE="/tmp/health_snapshot.cache"
    HEALTH_SNAP_TTL=3
    _read_now_ts
    _hs_now="$now_ts"
    _hs_cached=""
    if [ -f "$HEALTH_SNAP_CACHE" ]; then
      { read -r _hs_snap_ts; read -r _hs_cached; } < "$HEALTH_SNAP_CACHE" 2>/dev/null || true
      case "$_hs_snap_ts" in ''|*[!0-9]*) _hs_snap_ts=0 ;; esac
      [ $((_hs_now - _hs_snap_ts)) -lt "$HEALTH_SNAP_TTL" ] && [ -n "$_hs_cached" ] || _hs_cached=""
    fi
    if [ -n "$_hs_cached" ]; then
      printf '%s\n' "$_hs_cached"
    else
    # Load all configs needed for a full state overview
    load_conf_file /mnt/config/boot.conf
    load_conf_file /mnt/config/service_trim.conf
    load_conf_file /mnt/config/rtspserver.conf
    load_conf_file /mnt/config/mqtt.conf
    load_conf_file /mnt/config/recording.conf
    load_conf_file /mnt/config/sound_detection.conf

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

    health_time_utc="$(_format_iso8601_utc "$_hs_now")"
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
    web_mode_json="$(json_escape "$(get_cfg WEB_MODE full)")"
    codec0_json="$(json_escape "$codec0_name")"
    codec1_json="$(json_escape "$codec1_name")"
    watchdog_json="$(last_watchdog_event_json)"

    rtsp_state_json="$(service_state_json /mnt/controlscripts/rtsp-h26x)"
    onvif_state_json="$(service_state_json /mnt/controlscripts/onvif)"

    # SD Card Read-Only check
    sd_readonly=1
    if mount | grep "/mmcblk" | grep -q "rw,"; then
      sd_readonly=0
    fi

    # CSRF Token
    csrf_token=""
    if [ -r /tmp/csrf_token ]; then
        read -r csrf_token < /tmp/csrf_token
        csrf_token="$(printf '%s' "$csrf_token" | tr -cd '0-9a-fA-F')"
    fi

    _hs_result="{\"timestamp_utc\":\"$health_time_utc_json\",\"hostname\":\"$health_hostname_json\",\"uptime_seconds\":$uptime_seconds,\"sysusage\":\"CPU: $cpu% RAM: $mem_used/$mem_total kB\",\"cpu\":$cpu,\"ram_used_kb\":$mem_used,\"ram_total_kb\":$mem_total,\"ram_percent\":$ram_percent,\"chip_temp_c\":$chip_temp_json,\"chip_temp_text\":\"$chip_temp_text_json\",\"perfprofile\":\"$profile_json\",\"lum\":\"$lum_json\",\"awb\":\"$awb_json\",\"ui_ultralite_mode\":$ui_mode,\"web_mode\":\"$web_mode_json\",\"security_hardening_mode\":$security_hardening_mode,\"mqtt_enabled\":$mqtt_enabled,\"mqtt_discovery_enabled\":$mqtt_discovery,\"reboot_epoch\":$reboot_epoch,\"default_password_active\":$default_password_active,\"sd_readonly\":$sd_readonly,\"csrf_token\":\"$csrf_token\",\"power_voltage_mv\":$power_voltage_mv_json,\"power_voltage_text\":\"$power_voltage_text_json\",\"power_sensor_raw\":$power_sensor_raw_json,\"power_sensor_path\":\"$power_sensor_path_json\",\"power_estimate_enabled\":$power_estimate_enabled,\"power_estimated_mw\":$power_estimated_mw_json,\"power_estimated_text\":\"$power_estimated_text_json\",\"power_estimated_current_ma\":$power_estimated_current_ma_json,\"rtsp\":{\"service\":$rtsp_state_json,\"port\":$rtsp_port,\"main\":{\"path\":\"video0_unicast\",\"codec\":\"$codec0_json\",\"width\":$width0,\"height\":$height0,\"fps\":$fps0},\"sub\":{\"path\":\"video1_unicast\",\"codec\":\"$codec1_json\",\"width\":$width1,\"height\":$height1,\"fps\":$fps1}},\"onvif\":{\"service\":$onvif_state_json},\"last_watchdog_event\":\"$watchdog_json\"}"
    { printf '%s\n' "$_hs_now"; printf '%s\n' "$_hs_result"; } > "$HEALTH_SNAP_CACHE" 2>/dev/null || true
    printf '%s\n' "$_hs_result"
    fi
    ;;

  fullconfig)
    # This command returns ALL configurable values for the UI to populate its tabs.
    # It avoids multiple requests and keeps everything in sync.
    load_conf_file /mnt/config/boot.conf
    _iprofile="$(get_cfg INTEGRATION_PROFILE default)"
    load_conf_file /mnt/config/rtspserver.conf
    load_conf_file /mnt/config/mqtt.conf
    load_conf_file /mnt/config/service_trim.conf
    load_conf_file /mnt/config/timezone.conf
    load_conf_file /mnt/config/ntp_srv.conf
    load_conf_file /mnt/config/motion.conf
    load_conf_file /mnt/config/telnetd.conf
    if [ "$_iprofile" != "frigate_ha" ]; then
      load_conf_file /mnt/config/recording.conf
      load_conf_file /mnt/config/sound_detection.conf
      load_conf_file /mnt/config/timelapse.conf
      load_conf_file /mnt/config/telegram.conf
    fi
    
    read_rtsp_stream_summary
    detect_primary_ip
    
    # ISP / OSD Specifics
    osdenabled="$(truthy_flag "$(get_cfg osdenabled 0)")"
    osdtext_raw="$(get_cfg osdtext "")"
    osdtext_json="$(json_escape "$osdtext_raw")"
    
    # Audio specifics
    samplerate="$(get_cfg samplerate 8000)"
    audio_vol="$(get_cfg volume 8)"
    
    # MQTT particulars
    mqtt_enabled="$(truthy_flag "$(get_cfg MQTT_ENABLE 0)")"
    mqtt_discovery="$(truthy_flag "$(get_cfg MQTT_HA_DISCOVERY_ENABLE 1)")"
    
    # Reboot epoch calculation (needed for uptime display)
    read_reboot_epoch
    
    # System info
    if [ -r /proc/sys/kernel/hostname ]; then
      read -r health_hostname < /proc/sys/kernel/hostname
    else
      health_hostname="$(hostname 2>/dev/null)"
    fi

    # Peripheral & Specialized status
    front_led_state="$(truthy_flag "$(get_cfg FRONT_LED 0)")"
    red_led_state="$(truthy_flag "$(get_cfg RED_LED 0)")"
    syslog_enabled="$(truthy_flag "$(get_cfg SYSLOG_ENABLE 0)")"
    telegram_enabled="$(truthy_flag "$(get_cfg TELEGRAM_ENABLE 0)")"
    privacy_enabled="$(truthy_flag "$(get_cfg PRIVACY_MODE 0)")"
    
    # Feature blocks
    printf '{"boot":{"web_mode":"%s","perf_profile":"%s","service_trim":%s,"topology":"%s","ultralite_port":%s,"lightweight_mode":%s,"security_hardening":%s},"video":{"rtsp_port":%s,"main":{"codec":%s,"profile":%s,"width":%s,"height":%s,"fps":%s,"bitrate":%s,"gop":%s,"format":"%s","minqp":%s,"maxqp":%s,"smartmode":%s,"smartgoplen":%s,"smartquality":%s,"smartstatic":%s,"maxkbps":%s,"targetkbps":%s},"sub":{"codec":%s,"profile":%s,"width":%s,"height":%s,"fps":%s,"bitrate":%s,"gop":%s,"format":"%s","minqp":%s,"maxqp":%s,"smartmode":%s,"smartgoplen":%s,"smartquality":%s,"smartstatic":%s,"maxkbps":%s,"targetkbps":%s},"flip":%s,"rtsp_log":%s},"audio":{"samplerate":%s,"volume":%s,"codec_main":%s,"codec_sub":%s,"mic_sens":%s},"isp":{"daynight_lum":%s,"daynight_awb":%s,"nightday_lum":%s,"nightday_awb":%s},"osd":{"enabled":%s,"text":"%s","alpha":%s,"fontsize0":%s,"frontcolor":%s,"backcolor":%s,"edgecolor":%s,"x0":%s,"y0":%s},"mqtt":{"enabled":%s,"host":"%s","port":%s,"user":"%s","topic_root":"%s","discovery":%s,"discovery_prefix":"%s"},"recording":{"postrec":%s,"maxduration":%s,"reserved_mb":%s,"motion_activated":%s},"system":{"hostname":"%s","timezone":"%s","ntp_server":"%s","setup_wizard_done":%s,"gateway":"%s","reboot_schedule":{"enable":%s,"hour":%s,"min":%s,"dow":"%s"},"mem_guard":{"enable":%s,"warn_kb":%s,"crit_kb":%s,"interval":%s,"hits_warn":%s,"hits_crit":%s,"cooldown":%s}},"timelapse":{"interval":%s,"duration":%s},"services":{"telnet_port":%s,"sound_det_enable":%s,"sound_det_threshold":%s,"sound_det_interval":%s,"motion_sens":%s,"motion_led":%s},"telegram":{"enabled":%s,"token":"%s","chat_id":"%s"},"syslog":{"enabled":%s,"host":"%s","port":%s},"peripherals":{"led_front":%s,"led_red":%s,"privacy":%s}}\n' \
      "$(json_escape "$(get_cfg WEB_MODE full)")" "$(get_perf_profile)" "$(truthy_flag "$(get_cfg SERVICE_TRIM 0)")" "$(json_escape "$(get_cfg STREAM_TOPOLOGY dual)")" "$(sanitize_int "$(get_cfg ULTRALITE_HTTP_PORT 80)" 80)" "$(truthy_flag "$(get_cfg LIGHTWEIGHT_MODE 0)")" "$(truthy_flag "$(get_cfg SECURITY_HARDENING_MODE 0)")" \
      "$rtsp_port" \
      "$codec0" "$profile0" "$width0" "$height0" "$fps0" "$bps0" "$goplen0" "$(codec_name "$codec0")" "$minqp0" "$maxqp0" "$smartmode0" "$smartgoplen0" "$smartquality0" "$smartstatic0" "$maxkbps0" "$targetkbps0" \
      "$codec1" "$profile1" "$width1" "$height1" "$fps1" "$bps1" "$goplen1" "$(codec_name "$codec1")" "$minqp1" "$maxqp1" "$smartmode1" "$smartgoplen1" "$smartquality1" "$smartstatic1" "$maxkbps1" "$targetkbps1" \
      "$(sanitize_int "$(get_cfg imageFlip 0)" 0)" "$(truthy_flag "$(get_cfg enable_rtsp_log 0)")" \
      "$samplerate" "$audio_vol" "$(sanitize_int "$(get_cfg audioCodec0 4)" 4)" "$(sanitize_int "$(get_cfg audioCodec1 4)" 4)" "$audio_vol" \
      "$(sanitize_int "$(get_cfg daynightlum 2000)" 2000)" "$(sanitize_int "$(get_cfg daynightawb 100000)" 100000)" "$(sanitize_int "$(get_cfg nightdaylum 6000)" 6000)" "$(sanitize_int "$(get_cfg nightdayawb 50000)" 50000)" \
      "$osdenabled" "$osdtext_json" "$(sanitize_int "$(get_cfg osdalpha 128)" 128)" "$(sanitize_int "$(get_cfg osdfontsize0 24)" 24)" "$(sanitize_int "$(get_cfg frontcolor 1)" 1)" "$(sanitize_int "$(get_cfg backcolor 0)" 0)" "$(sanitize_int "$(get_cfg edgecolor 2)" 2)" "$(sanitize_int "$(get_cfg osdx0 10)" 10)" "$(sanitize_int "$(get_cfg osdy0 10)" 10)" \
      "$mqtt_enabled" "$(json_escape "$(get_cfg MQTT_HOST 127.0.0.1)")" "$(sanitize_int "$(get_cfg MQTT_PORT 1883)" 1883)" "$(json_escape "$(get_cfg MQTT_USER "")")" "$(json_escape "$(get_cfg MQTT_TOPIC_ROOT tc100/camera)")" "$mqtt_discovery" "$(json_escape "$(get_cfg MQTT_HA_DISCOVERY_PREFIX homeassistant)")" \
      "$(sanitize_int "$(get_cfg postrec 10)" 10)" "$(sanitize_int "$(get_cfg maxduration 60)" 60)" "$(sanitize_int "$(get_cfg diskspace 1024)" 1024)" "$(truthy_flag "$(get_cfg motion_act 0)")" \
      "$(json_escape "$health_hostname")" "$(json_escape "$(get_cfg TIMEZONE UTC)")" "$(json_escape "$(get_cfg NTP_SERVER pool.ntp.org)")" "$(truthy_flag "$(get_cfg SETUP_WIZARD_DONE 0)")" "$(json_escape "$(get_cfg DEFAULT_GATEWAY "0.0.0.0")")" "$(truthy_flag "$(get_cfg REBOOT_SCHEDULE_ENABLE 0)")" "$(sanitize_int "$(get_cfg REBOOT_SCHEDULE_HOUR 4)" 4)" "$(sanitize_int "$(get_cfg REBOOT_SCHEDULE_MINUTE 0)" 0)" "$(json_escape "$(get_cfg REBOOT_SCHEDULE_WEEKDAY "*")")" \
      "$(truthy_flag "$(get_cfg MEM_GUARD_ENABLE 0)")" "$(sanitize_int "$(get_cfg MEM_GUARD_WARN_KB 8192)" 8192)" "$(sanitize_int "$(get_cfg MEM_GUARD_CRITICAL_KB 4096)" 4096)" "$(sanitize_int "$(get_cfg MEM_GUARD_INTERVAL_SECONDS 20)" 20)" "$(sanitize_int "$(get_cfg MEM_GUARD_WARN_HITS 2)" 2)" "$(sanitize_int "$(get_cfg MEM_GUARD_CRITICAL_HITS 1)" 1)" "$(sanitize_int "$(get_cfg MEM_GUARD_COOLDOWN_SECONDS 120)" 120)" \
      "$(sanitize_int "$(get_cfg tlinterval 10)" 10)" "$(sanitize_int "$(get_cfg tlduration 0)" 0)" \
      "$(sanitize_int "$(get_cfg TELNET_PORT 23)" 23)" "$(truthy_flag "$(get_cfg ENABLE 0)")" "$(sanitize_int "$(get_cfg THRESHOLD 1500)" 1500)" "$(sanitize_int "$(get_cfg INTERVAL 5)" 5)" "$(sanitize_int "$(get_cfg mdsens 50)" 50)" "$(truthy_flag "$(get_cfg motion_trigger_led 0)")" \
      "$telegram_enabled" "$(json_escape "$(get_cfg apiToken "")")" "$(json_escape "$(get_cfg userChatId "")")" \
      "$syslog_enabled" "$(json_escape "$(get_cfg SYSLOG_HOST "")")" "$(sanitize_int "$(get_cfg SYSLOG_PORT 514)" 514)" \
      "$front_led_state" "$red_led_state" "$privacy_enabled"
    ;;

  perfprofile)
    get_perf_profile
    ;;

  get_events)
    # Source event logger
    . /mnt/scripts/event-logger.sh

    since_param="${F_since:-0}"
    limit_param="${F_limit:-50}"

    # Validate parameters
    since_param="$(sanitize_int "$since_param" 0)"
    limit_param="$(sanitize_int "$limit_param" 50)"
    if [ "$limit_param" -gt 200 ]; then
      limit_param=200
    fi

    get_events_since "$since_param" "$limit_param"
    ;;

  list_presets)
    presets_dir="/mnt/config/presets"
    mkdir -p "$presets_dir"

    if wants_json_response; then
      printf '{"presets":['
      first=1
      for preset_file in "$presets_dir"/*.json; do
        [ -f "$preset_file" ] || continue
        if [ "$first" = "1" ]; then
          first=0
        else
          printf ','
        fi
        preset_name=$(basename "$preset_file" .json)
        printf '{"name":"'
        json_escape "$(basename "$preset_file" .json)"
        printf '"}'
      done
      printf ']}'
    else
      # busybox basename has no -s flag; iterate and strip the suffix per file.
      for _pf in "$presets_dir"/*.json; do
        [ -f "$_pf" ] || continue
        basename "$_pf" .json
      done
    fi
    ;;

  load_preset)
    preset_name="${F_name:-}"
    presets_dir="/mnt/config/presets"

    if [ -z "$preset_name" ]; then
      if wants_json_response; then
        json_error "INVALID_PRESET" "Preset name required"
      else
        echo "ERROR: Preset name required"
      fi
    # SECURITY: validate the name before building a path, exactly like
    # save_preset/delete_preset do. Without this, name=../../../tmp/update_status
    # reads /mnt/config/presets/../../../tmp/update_status.json — an arbitrary
    # file read outside the presets directory. Fork-free case idiom (busybox-safe,
    # no grep -E) — rejects empty and anything with a char outside [A-Za-z0-9_-],
    # which blocks '/' and '.'.
    else
      case "$preset_name" in
        ''|*[!A-Za-z0-9_-]*)
          if wants_json_response; then
            json_error "INVALID_NAME" "Invalid preset name"
          else
            echo "ERROR: Invalid preset name"
          fi
          preset_name="" ;;
      esac
    fi
    if [ -n "$preset_name" ]; then
      preset_file="$presets_dir/$preset_name.json"
      if [ -f "$preset_file" ]; then
        if wants_json_response; then
          printf '{"preset":'
          cat "$preset_file"
          printf '}'
        else
          cat "$preset_file"
        fi
      else
        if wants_json_response; then
          json_error "PRESET_NOT_FOUND" "Preset '$preset_name' not found"
        else
          echo "ERROR: Preset '$preset_name' not found"
        fi
      fi
    fi
    ;;

  *)
    echo "Unsupported command '$F_cmd'"
    ;;
  esac
  fi

exit 0
