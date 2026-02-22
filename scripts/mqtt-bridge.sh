#!/bin/sh

CONFIG_FILE="/mnt/config/mqtt.conf"
LOGPATH="/mnt/log/mqtt-bridge.log"
STATE_FILE="/tmp/mqtt-bridge.state"
CURL_BIN="/mnt/bin/curl"
JQ_BIN="/mnt/bin/jq"

. /mnt/scripts/common_functions.sh

json_escape()
{
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

sanitize_int_range()
{
  value="$1"
  min="$2"
  max="$3"
  fallback="$4"

  case "$value" in
    ''|*[!0-9]*) value="$fallback" ;;
  esac
  if [ "$value" -lt "$min" ]; then
    value="$min"
  fi
  if [ "$value" -gt "$max" ]; then
    value="$max"
  fi
  echo "$value"
}

is_truthy_local()
{
  case "$1" in
    1|true|on|yes|enabled) return 0 ;;
    *) return 1 ;;
  esac
}

log_msg()
{
  if [ ! -d /mnt/log ]; then
    mkdir -p /mnt/log >/dev/null 2>&1 || true
  fi
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)" "$1" >> "$LOGPATH"
}

load_config()
{
  install_config "$CONFIG_FILE"
  # shellcheck disable=SC1090
  if [ -f "$CONFIG_FILE" ]; then
    . "$CONFIG_FILE"
  fi

  MQTT_ENABLE="${MQTT_ENABLE:-0}"
  MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
  MQTT_PORT="$(sanitize_int_range "${MQTT_PORT:-1883}" 1 65535 1883)"
  MQTT_USER="${MQTT_USER:-}"
  MQTT_PASSWORD="${MQTT_PASSWORD:-}"
  MQTT_CLIENT_ID="${MQTT_CLIENT_ID:-tc100-camera}"
  MQTT_TOPIC_ROOT="${MQTT_TOPIC_ROOT:-tc100/camera}"
  MQTT_TOPIC_COMMAND="${MQTT_TOPIC_COMMAND:-}"
  MQTT_QOS="$(sanitize_int_range "${MQTT_QOS:-0}" 0 2 0)"
  MQTT_HEALTH_INTERVAL_SECONDS="$(sanitize_int_range "${MQTT_HEALTH_INTERVAL_SECONDS:-60}" 10 86400 60)"
  MQTT_COMMAND_WAIT_SECONDS="$(sanitize_int_range "${MQTT_COMMAND_WAIT_SECONDS:-12}" 3 120 12)"
  MQTT_COMMAND_REPEAT_WINDOW_SECONDS="$(sanitize_int_range "${MQTT_COMMAND_REPEAT_WINDOW_SECONDS:-20}" 0 600 20)"
  MQTT_HA_DISCOVERY_ENABLE="${MQTT_HA_DISCOVERY_ENABLE:-1}"
  MQTT_HA_DISCOVERY_PREFIX="${MQTT_HA_DISCOVERY_PREFIX:-homeassistant}"
  POWER_ESTIMATE_ENABLE="${POWER_ESTIMATE_ENABLE:-0}"
  POWER_ESTIMATE_BASE_MW="$(sanitize_int_range "${POWER_ESTIMATE_BASE_MW:-1700}" 500 10000 1700)"
  POWER_ESTIMATE_CPU_SCALE_MW="$(sanitize_int_range "${POWER_ESTIMATE_CPU_SCALE_MW:-500}" 0 5000 500)"
  POWER_ESTIMATE_IR_LED_MW="$(sanitize_int_range "${POWER_ESTIMATE_IR_LED_MW:-700}" 0 5000 700)"
  POWER_SENSOR_PATH="${POWER_SENSOR_PATH:-auto}"

  if [ -z "$MQTT_TOPIC_COMMAND" ]; then
    MQTT_TOPIC_COMMAND="${MQTT_TOPIC_ROOT}/command"
  fi

  MQTT_HA_DISCOVERY_PREFIX="$(printf '%s' "$MQTT_HA_DISCOVERY_PREFIX" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
  [ -n "$MQTT_HA_DISCOVERY_PREFIX" ] || MQTT_HA_DISCOVERY_PREFIX="homeassistant"

  case "$POWER_SENSOR_PATH" in
    ''|auto)
      POWER_SENSOR_PATH="auto"
      ;;
    /*)
      POWER_SENSOR_PATH="$(printf '%s' "$POWER_SENSOR_PATH" | sed 's#[^A-Za-z0-9._/-]##g')"
      [ -n "$POWER_SENSOR_PATH" ] || POWER_SENSOR_PATH="auto"
      ;;
    *)
      POWER_SENSOR_PATH="auto"
      ;;
  esac
}

mqtt_enabled()
{
  is_truthy_local "$MQTT_ENABLE"
}

ha_discovery_enabled()
{
  is_truthy_local "$MQTT_HA_DISCOVERY_ENABLE"
}

power_estimate_enabled()
{
  is_truthy_local "$POWER_ESTIMATE_ENABLE"
}

mqtt_url()
{
  topic="$1"
  client_id="$2"
  retain="$3"
  if [ -z "$topic" ]; then
    echo ""
    return
  fi

  if [ -n "$retain" ]; then
    echo "mqtt://${MQTT_HOST}:${MQTT_PORT}/${topic}?clientid=${client_id}&qos=${MQTT_QOS}&retain=${retain}"
  else
    echo "mqtt://${MQTT_HOST}:${MQTT_PORT}/${topic}?clientid=${client_id}&qos=${MQTT_QOS}"
  fi
}

curl_auth_args()
{
  if [ -n "$MQTT_USER" ]; then
    printf -- '-u%s:%s' "$MQTT_USER" "$MQTT_PASSWORD"
  fi
}

mqtt_publish_raw()
{
  topic="$1"
  payload="$2"
  retain="${3:-0}"
  [ -n "$topic" ] || return 1

  tmp_payload="/tmp/mqtt-publish.$$.tmp"
  url="$(mqtt_url "$topic" "$MQTT_CLIENT_ID-pub" "$retain")"
  auth_arg="$(curl_auth_args)"

  printf '%s' "$payload" > "$tmp_payload"
  if [ -n "$auth_arg" ]; then
    "$CURL_BIN" --silent --show-error --max-time 10 "$auth_arg" --upload-file "$tmp_payload" "$url" >/dev/null 2>&1
  else
    "$CURL_BIN" --silent --show-error --max-time 10 --upload-file "$tmp_payload" "$url" >/dev/null 2>&1
  fi
  rc=$?
  rm -f "$tmp_payload"
  return "$rc"
}

mqtt_publish_topic_suffix()
{
  suffix="$1"
  payload="$2"
  retain="${3:-0}"
  if ! mqtt_enabled; then
    return 0
  fi
  mqtt_publish_raw "${MQTT_TOPIC_ROOT}/${suffix}" "$payload" "$retain"
}

read_power_telemetry()
{
  power_sensor_candidates=""
  case "$POWER_SENSOR_PATH" in
    ''|auto)
      power_sensor_candidates="/sys/kernel/ain/bat /sys/kernel/ain/ain0 /sys/kernel/ain/ain1"
      ;;
    *)
      power_sensor_candidates="$POWER_SENSOR_PATH"
      ;;
  esac

  power_sensor_raw=0
  power_sensor_path=""
  power_voltage_mv=0

  for candidate in $power_sensor_candidates; do
    [ -r "$candidate" ] || continue
    read -r raw_value < "$candidate"
    case "$raw_value" in
      ''|*[!0-9]*) raw_value=0 ;;
    esac
    if [ "$raw_value" -le 0 ]; then
      continue
    fi
    power_sensor_raw="$raw_value"
    power_sensor_path="$candidate"
    break
  done

  if [ "$power_sensor_raw" -ge 2500 ] && [ "$power_sensor_raw" -le 20000 ]; then
    power_voltage_mv="$power_sensor_raw"
  elif [ "$power_sensor_raw" -ge 2500000 ] && [ "$power_sensor_raw" -le 20000000 ]; then
    power_voltage_mv=$((power_sensor_raw / 1000))
  fi

  power_estimated_mw=0
  power_estimated_current_ma=0
  power_estimated_enabled_json=0
  if power_estimate_enabled; then
    power_estimated_enabled_json=1
    power_estimated_mw=$((POWER_ESTIMATE_BASE_MW + (cpu * POWER_ESTIMATE_CPU_SCALE_MW / 100)))

    ir_led_state=0
    if [ -r /sys/user-gpio/ir-led ]; then
      read -r ir_led_raw < /sys/user-gpio/ir-led
      case "$ir_led_raw" in
        ''|*[!0-9]*) ir_led_raw=0 ;;
      esac
      ir_led_state="$ir_led_raw"
    fi
    if [ "$ir_led_state" -eq 1 ]; then
      power_estimated_mw=$((power_estimated_mw + POWER_ESTIMATE_IR_LED_MW))
    fi
    if [ "$power_estimated_mw" -lt 0 ]; then
      power_estimated_mw=0
    fi
    if [ "$power_voltage_mv" -gt 0 ]; then
      power_estimated_current_ma=$((power_estimated_mw * 1000 / power_voltage_mv))
    fi
  fi
}

read_chip_temperature()
{
  chip_temp_c=""
  temp_candidates="/sys/class/thermal/thermal_zone0/temp /sys/class/thermal/thermal_zone1/temp /sys/devices/virtual/thermal/thermal_zone0/temp /proc/temperature /tmp/chip_temp"
  for candidate in $temp_candidates; do
    [ -r "$candidate" ] || continue
    read -r raw_value < "$candidate"
    case "$raw_value" in
      ''|*[!0-9]*) raw_value=0 ;;
    esac
    if [ "$raw_value" -le 0 ]; then
      continue
    fi
    if [ "$raw_value" -ge 10000 ]; then
      chip_temp_c=$((raw_value / 1000))
    elif [ "$raw_value" -le 125 ]; then
      chip_temp_c="$raw_value"
    else
      chip_temp_c=""
    fi
    if [ -n "$chip_temp_c" ]; then
      break
    fi
  done
}

publish_availability()
{
  state="$1"
  [ -n "$state" ] || state="online"
  mqtt_publish_topic_suffix "availability" "$state" 1 >/dev/null 2>&1 || true
}

publish_homeassistant_discovery()
{
  if ! ha_discovery_enabled; then
    return 0
  fi

  node_id="$(printf '%s' "$MQTT_CLIENT_ID" | tr -c 'A-Za-z0-9_-' '_' | sed 's/^_//; s/_$//')"
  [ -n "$node_id" ] || node_id="tc100_camera"

  hostname_value="$(hostname 2>/dev/null)"
  [ -n "$hostname_value" ] || hostname_value="TC100 Camera"

  discovery_prefix="$MQTT_HA_DISCOVERY_PREFIX"
  root_json="$(json_escape "$MQTT_TOPIC_ROOT")"
  cmd_json="$(json_escape "$MQTT_TOPIC_COMMAND")"
  avail_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/availability")"
  device_name_json="$(json_escape "$hostname_value")"
  device_id_json="$(json_escape "$node_id")"

  cpu_cfg_topic="${discovery_prefix}/sensor/${node_id}/cpu/config"
  cpu_cfg_payload="$(printf '{"name":"%s CPU","uniq_id":"%s_cpu","stat_t":"%s/health","unit_of_meas":"%%","dev_cla":null,"stat_cla":"measurement","val_tpl":"{{ value_json.cpu }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:chip","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$root_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  mqtt_publish_raw "$cpu_cfg_topic" "$cpu_cfg_payload" 1 >/dev/null 2>&1 || true

  ram_cfg_topic="${discovery_prefix}/sensor/${node_id}/ram/config"
  ram_cfg_payload="$(printf '{"name":"%s RAM","uniq_id":"%s_ram","stat_t":"%s/health","unit_of_meas":"%%","stat_cla":"measurement","val_tpl":"{{ value_json.ram_percent }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:memory","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$root_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  mqtt_publish_raw "$ram_cfg_topic" "$ram_cfg_payload" 1 >/dev/null 2>&1 || true

  temp_cfg_topic="${discovery_prefix}/sensor/${node_id}/chip_temp/config"
  temp_cfg_payload="$(printf '{"name":"%s Chip Temp","uniq_id":"%s_chip_temp","stat_t":"%s/health","unit_of_meas":"C","dev_cla":"temperature","stat_cla":"measurement","val_tpl":"{{ value_json.chip_temp_c if value_json.chip_temp_c is number else none }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:thermometer","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$root_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  mqtt_publish_raw "$temp_cfg_topic" "$temp_cfg_payload" 1 >/dev/null 2>&1 || true

  power_cfg_topic="${discovery_prefix}/sensor/${node_id}/power_draw/config"
  power_cfg_payload="$(printf '{"name":"%s Power","uniq_id":"%s_power","stat_t":"%s/health","unit_of_meas":"W","dev_cla":"power","stat_cla":"measurement","val_tpl":"{{ (value_json.power_estimated_mw | float(0) / 1000) | round(2) if value_json.power_estimated_mw is number else none }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:flash","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$root_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  mqtt_publish_raw "$power_cfg_topic" "$power_cfg_payload" 1 >/dev/null 2>&1 || true

  vin_cfg_topic="${discovery_prefix}/sensor/${node_id}/input_voltage/config"
  vin_cfg_payload="$(printf '{"name":"%s Input Voltage","uniq_id":"%s_vin","stat_t":"%s/health","unit_of_meas":"V","dev_cla":"voltage","stat_cla":"measurement","val_tpl":"{{ (value_json.power_voltage_mv | float(0) / 1000) | round(3) if value_json.power_voltage_mv is number else none }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:power-plug","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$root_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  mqtt_publish_raw "$vin_cfg_topic" "$vin_cfg_payload" 1 >/dev/null 2>&1 || true

  reboot_cfg_topic="${discovery_prefix}/button/${node_id}/reboot/config"
  reboot_cfg_payload="$(printf '{"name":"%s Reboot","uniq_id":"%s_reboot","cmd_t":"%s","pl_prs":"reboot","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:restart","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  mqtt_publish_raw "$reboot_cfg_topic" "$reboot_cfg_payload" 1 >/dev/null 2>&1 || true

  snapshot_cfg_topic="${discovery_prefix}/button/${node_id}/snapshot/config"
  snapshot_cfg_payload="$(printf '{"name":"%s Snapshot","uniq_id":"%s_snapshot","cmd_t":"%s","pl_prs":"snapshot","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:camera","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  mqtt_publish_raw "$snapshot_cfg_topic" "$snapshot_cfg_payload" 1 >/dev/null 2>&1 || true
}

build_health_payload()
{
  now_ts="$(date +%s 2>/dev/null)"
  if [ -z "$now_ts" ] || [ "$now_ts" -le 0 ] 2>/dev/null; then
    now_ts=0
  fi

  if [ -r /proc/uptime ]; then
    read -r uptime_raw _ < /proc/uptime
    uptime_seconds="${uptime_raw%.*}"
    case "$uptime_seconds" in
      ''|*[!0-9]*) uptime_seconds=0 ;;
    esac
  else
    uptime_seconds=0
  fi

  cpu="$(get_current_cpu_usage 2>/dev/null)"
  case "$cpu" in
    ''|*[!0-9]*) cpu=0 ;;
  esac

  mem_used="$(get_current_memory_usage 2>/dev/null)"
  mem_total="$(get_all_memory 2>/dev/null)"
  case "$mem_used" in
    ''|*[!0-9]*) mem_used=0 ;;
  esac
  case "$mem_total" in
    ''|*[!0-9]*) mem_total=0 ;;
  esac

  if [ "$mem_total" -gt 0 ]; then
    ram_percent=$((100 * mem_used / mem_total))
  else
    ram_percent=0
  fi

  read_chip_temperature
  read_power_telemetry

  chip_temp_json="null"
  if [ -n "$chip_temp_c" ]; then
    chip_temp_json="$chip_temp_c"
  fi

  power_voltage_mv_json="null"
  if [ "$power_voltage_mv" -gt 0 ]; then
    power_voltage_mv_json="$power_voltage_mv"
  fi
  power_estimated_mw_json="null"
  if [ "$power_estimated_mw" -gt 0 ] || [ "$power_estimated_enabled_json" -eq 1 ]; then
    power_estimated_mw_json="$power_estimated_mw"
  fi
  power_estimated_current_ma_json="null"
  if [ "$power_estimated_current_ma" -gt 0 ] && [ "$power_estimated_enabled_json" -eq 1 ]; then
    power_estimated_current_ma_json="$power_estimated_current_ma"
  fi

  web_mode="full"
  profile="balanced"
  if [ -f /mnt/config/boot.conf ]; then
    # shellcheck disable=SC1090
    . /mnt/config/boot.conf
    web_mode="${WEB_MODE:-full}"
    if [ "${LOW_CPU_PROFILE:-0}" = "1" ]; then
      profile="low-cpu"
    fi
  fi
  if [ -f /mnt/config/service_trim.conf ]; then
    # shellcheck disable=SC1090
    . /mnt/config/service_trim.conf
    if [ "${SERVICE_TRIM:-0}" = "1" ]; then
      profile="rtsp-only"
    fi
  fi

  hostname_value="$(hostname 2>/dev/null)"
  hostname_json="$(json_escape "$hostname_value")"
  web_mode_json="$(json_escape "$web_mode")"
  profile_json="$(json_escape "$profile")"
  power_sensor_path_json="$(json_escape "$power_sensor_path")"

  printf '{"ts":%s,"hostname":"%s","uptime_seconds":%s,"cpu":%s,"ram_used_kb":%s,"ram_total_kb":%s,"ram_percent":%s,"chip_temp_c":%s,"power_estimate_enabled":%s,"power_estimated_mw":%s,"power_estimated_current_ma":%s,"power_voltage_mv":%s,"power_sensor_path":"%s","web_mode":"%s","perfprofile":"%s"}' \
    "$now_ts" "$hostname_json" "$uptime_seconds" "$cpu" "$mem_used" "$mem_total" "$ram_percent" "$chip_temp_json" "$power_estimated_enabled_json" "$power_estimated_mw_json" "$power_estimated_current_ma_json" "$power_voltage_mv_json" "$power_sensor_path_json" "$web_mode_json" "$profile_json"
}

publish_health()
{
  payload="$(build_health_payload)"
  mqtt_publish_topic_suffix "health" "$payload" 0
}

publish_event_simple()
{
  event_type="$1"
  detail="$2"
  now_ts="$(date +%s 2>/dev/null)"
  [ -n "$now_ts" ] || now_ts=0
  event_json="$(json_escape "$event_type")"
  detail_json="$(json_escape "$detail")"
  payload=$(printf '{"ts":%s,"type":"%s","detail":"%s"}' "$now_ts" "$event_json" "$detail_json")
  mqtt_publish_topic_suffix "event" "$payload" 0
}

dedupe_command()
{
  cmd_payload="$1"
  now_ts="$(date +%s 2>/dev/null)"
  [ -n "$now_ts" ] || now_ts=0
  cmd_hash="$(printf '%s' "$cmd_payload" | md5sum | awk '{print $1}')"

  last_hash=""
  last_ts=0
  if [ -f "$STATE_FILE" ]; then
    read -r last_hash last_ts < "$STATE_FILE"
    case "$last_ts" in
      ''|*[!0-9]*) last_ts=0 ;;
    esac
  fi

  if [ "$cmd_hash" = "$last_hash" ] && [ "$MQTT_COMMAND_REPEAT_WINDOW_SECONDS" -gt 0 ]; then
    age=$((now_ts - last_ts))
    if [ "$age" -ge 0 ] && [ "$age" -lt "$MQTT_COMMAND_REPEAT_WINDOW_SECONDS" ]; then
      return 1
    fi
  fi

  printf '%s %s\n' "$cmd_hash" "$now_ts" > "$STATE_FILE"
  return 0
}

apply_profile_command()
{
  profile_raw="$1"
  profile="$(printf '%s' "$profile_raw" | tr '[:upper:]' '[:lower:]')"

  install_config /mnt/config/boot.conf
  install_config /mnt/config/service_trim.conf

  case "$profile" in
    balanced)
      rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 0
      rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE 0
      rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE 0
      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 1
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO 1
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-primary
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0
      if [ -x /mnt/controlscripts/memory-guard ]; then
        /mnt/controlscripts/memory-guard stop >/dev/null 2>&1 || true
      fi
      ;;
    low-cpu)
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
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0
      if [ -x /mnt/controlscripts/memory-guard ]; then
        /mnt/controlscripts/memory-guard start >/dev/null 2>&1 || true
      fi
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
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 1
      for svc in ftp-server telnet-server motion-detection recording timelapse auto-night-detection blue-led night-mode network-monitor; do
        if [ -x "/mnt/controlscripts/$svc" ]; then
          /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
        fi
      done
      if [ -x /mnt/controlscripts/memory-guard ]; then
        /mnt/controlscripts/memory-guard start >/dev/null 2>&1 || true
      fi
      ;;
    *)
      return 1
      ;;
  esac

  restart_service_if_need /mnt/controlscripts/rtsp-h26x
  restart_service_if_need /mnt/controlscripts/onvif
  return 0
}

handle_command_payload()
{
  payload_raw="$(printf '%s' "$1" | tr -d '\r')"
  payload_trimmed="$(printf '%s' "$payload_raw" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  [ -n "$payload_trimmed" ] || return 0

  if ! dedupe_command "$payload_trimmed"; then
    return 0
  fi

  cmd=""
  value=""
  if printf '%s' "$payload_trimmed" | grep -q '^{'; then
    if [ -x "$JQ_BIN" ]; then
      cmd="$(printf '%s' "$payload_trimmed" | "$JQ_BIN" -r '.cmd // .command // empty' 2>/dev/null)"
      value="$(printf '%s' "$payload_trimmed" | "$JQ_BIN" -r '.value // .profile // empty' 2>/dev/null)"
    fi
  fi

  if [ -z "$cmd" ]; then
    case "$payload_trimmed" in
      profile:*|profile=*|profile\ *)
        cmd="profile"
        value="${payload_trimmed#profile}"
        value="${value#:}"
        value="${value#=}"
        value="${value# }"
        ;;
      *)
        cmd="$payload_trimmed"
        ;;
    esac
  fi

  cmd="$(printf '%s' "$cmd" | tr '[:upper:]' '[:lower:]')"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"

  case "$cmd" in
    reboot)
      publish_event_simple "command.reboot" "accepted"
      /sbin/reboot
      ;;
    snapshot)
      shot_path="/tmp/mqtt-snapshot-$(date +%Y%m%d-%H%M%S 2>/dev/null).jpg"
      if /mnt/bin/getimage > "$shot_path" 2>/dev/null; then
        shot_json="$(json_escape "$shot_path")"
        now_ts="$(date +%s 2>/dev/null)"
        [ -n "$now_ts" ] || now_ts=0
        payload=$(printf '{"ts":%s,"type":"snapshot.manual","snapshot":"%s"}' "$now_ts" "$shot_json")
        mqtt_publish_topic_suffix "event" "$payload" 0
      else
        publish_event_simple "command.snapshot" "failed"
      fi
      ;;
    profile)
      if apply_profile_command "$value"; then
        publish_event_simple "command.profile" "$value"
      else
        publish_event_simple "command.profile" "invalid:$value"
      fi
      ;;
    *)
      publish_event_simple "command.unknown" "$payload_trimmed"
      ;;
  esac
}

subscribe_once_command()
{
  sub_client_id="${MQTT_CLIENT_ID}-sub"
  url="$(mqtt_url "$MQTT_TOPIC_COMMAND" "$sub_client_id" "")"
  auth_arg="$(curl_auth_args)"
  if [ -n "$auth_arg" ]; then
    "$CURL_BIN" --silent --show-error --max-time "$MQTT_COMMAND_WAIT_SECONDS" "$auth_arg" "$url" 2>/dev/null
  else
    "$CURL_BIN" --silent --show-error --max-time "$MQTT_COMMAND_WAIT_SECONDS" "$url" 2>/dev/null
  fi
}

shutdown_bridge()
{
  publish_availability offline
  log_msg "MQTT bridge stopping"
}

run_loop()
{
  load_config
  if ! mqtt_enabled; then
    log_msg "MQTT bridge disabled in config"
    exit 0
  fi

  trap 'shutdown_bridge; trap - INT TERM EXIT; exit 0' INT TERM
  trap 'shutdown_bridge' EXIT
  log_msg "MQTT bridge started host=${MQTT_HOST}:${MQTT_PORT} root=${MQTT_TOPIC_ROOT}"
  publish_availability online
  publish_homeassistant_discovery
  publish_event_simple "bridge.start" "online"

  last_health_ts=0
  while :; do
    now_ts="$(date +%s 2>/dev/null)"
    [ -n "$now_ts" ] || now_ts=0

    if [ "$last_health_ts" -le 0 ] || [ $((now_ts - last_health_ts)) -ge "$MQTT_HEALTH_INTERVAL_SECONDS" ]; then
      publish_health >/dev/null 2>&1 || true
      last_health_ts="$now_ts"
    fi

    cmd_payload="$(subscribe_once_command)"
    subscribe_rc=$?
    if [ "$subscribe_rc" -eq 0 ] && [ -n "$cmd_payload" ]; then
      handle_command_payload "$cmd_payload"
    fi

    sleep 1
  done
}

publish_mode()
{
  suffix="$1"
  payload="$2"
  retain="${3:-0}"

  load_config
  mqtt_publish_topic_suffix "$suffix" "$payload" "$retain"
  exit $?
}

case "$1" in
  run|daemon|"")
    run_loop
    ;;
  publish)
    publish_mode "$2" "$3" "$4"
    ;;
  *)
    echo "Usage: $0 [run|publish <topic_suffix> <payload> [retain]]"
    exit 1
    ;;
esac
