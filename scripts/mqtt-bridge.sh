#!/bin/sh

CONFIG_FILE="/mnt/config/mqtt.conf"
LOGPATH="/mnt/log/mqtt-bridge.log"
STATE_FILE="/tmp/mqtt-bridge.state"
HEALTH_SLOW_CACHE_FILE="/tmp/mqtt-bridge.health-slow.cache"
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
  MQTT_HEALTH_INTERVAL_SECONDS="$(sanitize_int_range "${MQTT_HEALTH_INTERVAL_SECONDS:-120}" 10 86400 120)"
  MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS="$(sanitize_int_range "${MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS:-180}" 10 86400 180)"
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

read_kv_config_value()
{
  conf_path="$1"
  conf_key="$2"
  conf_default="$3"
  conf_value="$conf_default"

  if [ -r "$conf_path" ]; then
    conf_value="$(awk -F= -v key="$conf_key" '
      $0 !~ /^[[:space:]]*#/ && $1 == key {print $2; exit}
    ' "$conf_path" 2>/dev/null)"
  fi
  [ -n "$conf_value" ] || conf_value="$conf_default"
  printf '%s' "$conf_value"
}

security_hardening_enabled_runtime()
{
  value="$(read_kv_config_value /mnt/config/boot.conf SECURITY_HARDENING_MODE 0)"
  is_truthy_local "$value"
}

service_script_running_int()
{
  script_path="$1"
  pidfile_path="$2"

  if [ -n "$pidfile_path" ] && [ -r "$pidfile_path" ]; then
    read -r pid < "$pidfile_path"
    case "$pid" in
      ''|*[!0-9]*) pid=0 ;;
    esac
    if [ "$pid" -gt 0 ] && kill -0 "$pid" >/dev/null 2>&1; then
      echo "1"
      return
    fi
  fi

  if [ ! -x "$script_path" ]; then
    echo "0"
    return
  fi
  script_status="$("$script_path" status 2>/dev/null)"
  if [ -n "$script_status" ]; then
    echo "1"
  else
    echo "0"
  fi
}

normalize_toggle_value()
{
  value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  case "$value" in
    on|1|true|start|enable|enabled)
      echo "on"
      ;;
    off|0|false|stop|disable|disabled)
      echo "off"
      ;;
    toggle)
      echo "toggle"
      ;;
    *)
      echo ""
      ;;
  esac
}

read_int_file_value()
{
  file_path="$1"
  default_value="$2"
  result="$default_value"
  if [ -r "$file_path" ]; then
    read -r raw_value < "$file_path"
    case "$raw_value" in
      ''|*[!0-9]*) raw_value="$default_value" ;;
    esac
    result="$raw_value"
  fi
  printf '%s' "$result"
}

port_open_from_list_int()
{
  listen_data="$1"
  port="$2"
  if printf '%s\n' "$listen_data" | awk -v port="$port" '
    $1 ~ /^tcp/ {
      local_addr=$4
      split(local_addr, parts, ":")
      if (parts[length(parts)] == port) {
        found=1
        exit
      }
    }
    END { exit(found ? 0 : 1) }
  '; then
    echo "1"
  else
    echo "0"
  fi
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

publish_discovery_config()
{
  cfg_topic="$1"
  cfg_payload="$2"
  mqtt_publish_raw "$cfg_topic" "$cfg_payload" 1 >/dev/null 2>&1 || true
  # Smear the discovery load to prevent CPU spikes from 20+ concurrent curls
  sleep 0.1
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
  health_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/health")"
  motion_state_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/motion/state")"
  avail_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/availability")"
  device_name_json="$(json_escape "$hostname_value")"
  device_id_json="$(json_escape "$node_id")"
  cmd_profile_tpl_json="$(json_escape "{\"cmd\":\"profile\",\"value\":\"{{ value }}\"}")"
  cmd_motion_on_json="$(json_escape "{\"cmd\":\"motion\",\"value\":\"on\"}")"
  cmd_motion_off_json="$(json_escape "{\"cmd\":\"motion\",\"value\":\"off\"}")"
  cmd_ir_on_json="$(json_escape "{\"cmd\":\"ir_led\",\"value\":\"on\"}")"
  cmd_ir_off_json="$(json_escape "{\"cmd\":\"ir_led\",\"value\":\"off\"}")"
  cmd_front_on_json="$(json_escape "{\"cmd\":\"front_led\",\"value\":\"on\"}")"
  cmd_front_off_json="$(json_escape "{\"cmd\":\"front_led\",\"value\":\"off\"}")"
  cmd_red_on_json="$(json_escape "{\"cmd\":\"red_led\",\"value\":\"on\"}")"
  cmd_red_off_json="$(json_escape "{\"cmd\":\"red_led\",\"value\":\"off\"}")"
  cmd_ftp_on_json="$(json_escape "{\"cmd\":\"ftp\",\"value\":\"on\"}")"
  cmd_ftp_off_json="$(json_escape "{\"cmd\":\"ftp\",\"value\":\"off\"}")"
  cmd_telnet_on_json="$(json_escape "{\"cmd\":\"telnet\",\"value\":\"on\"}")"
  cmd_telnet_off_json="$(json_escape "{\"cmd\":\"telnet\",\"value\":\"off\"}")"

  cpu_cfg_topic="${discovery_prefix}/sensor/${node_id}/cpu/config"
  cpu_cfg_payload="$(printf '{"name":"%s CPU","uniq_id":"%s_cpu","stat_t":"%s","unit_of_meas":"%%","stat_cla":"measurement","val_tpl":"{{ value_json.cpu }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:chip","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$cpu_cfg_topic" "$cpu_cfg_payload"

  ram_cfg_topic="${discovery_prefix}/sensor/${node_id}/ram/config"
  ram_cfg_payload="$(printf '{"name":"%s RAM","uniq_id":"%s_ram","stat_t":"%s","unit_of_meas":"%%","stat_cla":"measurement","val_tpl":"{{ value_json.ram_percent }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:memory","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$ram_cfg_topic" "$ram_cfg_payload"

  temp_cfg_topic="${discovery_prefix}/sensor/${node_id}/chip_temp/config"
  temp_cfg_payload="$(printf '{"name":"%s Chip Temp","uniq_id":"%s_chip_temp","stat_t":"%s","unit_of_meas":"C","dev_cla":"temperature","stat_cla":"measurement","val_tpl":"{{ value_json.chip_temp_c if value_json.chip_temp_c is number else none }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:thermometer","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$temp_cfg_topic" "$temp_cfg_payload"

  power_cfg_topic="${discovery_prefix}/sensor/${node_id}/power_draw/config"
  power_cfg_payload="$(printf '{"name":"%s Power","uniq_id":"%s_power","stat_t":"%s","unit_of_meas":"W","dev_cla":"power","stat_cla":"measurement","val_tpl":"{{ (value_json.power_estimated_mw | float(0) / 1000) | round(2) if value_json.power_estimated_mw is number else none }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:flash","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$power_cfg_topic" "$power_cfg_payload"

  vin_cfg_topic="${discovery_prefix}/sensor/${node_id}/input_voltage/config"
  vin_cfg_payload="$(printf '{"name":"%s Input Voltage","uniq_id":"%s_vin","stat_t":"%s","unit_of_meas":"V","dev_cla":"voltage","stat_cla":"measurement","val_tpl":"{{ (value_json.power_voltage_mv | float(0) / 1000) | round(3) if value_json.power_voltage_mv is number else none }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:power-plug","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$vin_cfg_topic" "$vin_cfg_payload"

  uptime_cfg_topic="${discovery_prefix}/sensor/${node_id}/uptime/config"
  uptime_cfg_payload="$(printf '{"name":"%s Uptime","uniq_id":"%s_uptime","stat_t":"%s","unit_of_meas":"s","dev_cla":"duration","stat_cla":"measurement","val_tpl":"{{ value_json.uptime_seconds }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:clock-outline","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$uptime_cfg_topic" "$uptime_cfg_payload"

  profile_state_cfg_topic="${discovery_prefix}/sensor/${node_id}/profile_state/config"
  profile_state_cfg_payload="$(printf '{"name":"%s Profile","uniq_id":"%s_profile_state","stat_t":"%s","val_tpl":"{{ value_json.perfprofile }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:tune","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$profile_state_cfg_topic" "$profile_state_cfg_payload"

  web_mode_cfg_topic="${discovery_prefix}/sensor/${node_id}/web_mode/config"
  web_mode_cfg_payload="$(printf '{"name":"%s Web Mode","uniq_id":"%s_web_mode","stat_t":"%s","val_tpl":"{{ value_json.web_mode }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:web","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$web_mode_cfg_topic" "$web_mode_cfg_payload"

  ip_cfg_topic="${discovery_prefix}/sensor/${node_id}/primary_ip/config"
  ip_cfg_payload="$(printf '{"name":"%s IP","uniq_id":"%s_primary_ip","stat_t":"%s","val_tpl":"{{ value_json.primary_ip }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:ip-network","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$ip_cfg_topic" "$ip_cfg_payload"

  storage_used_cfg_topic="${discovery_prefix}/sensor/${node_id}/storage_used_percent/config"
  storage_used_cfg_payload="$(printf '{"name":"%s Storage Used","uniq_id":"%s_storage_used","stat_t":"%s","unit_of_meas":"%%","stat_cla":"measurement","val_tpl":"{{ value_json.storage_used_percent }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:database","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$storage_used_cfg_topic" "$storage_used_cfg_payload"

  storage_free_cfg_topic="${discovery_prefix}/sensor/${node_id}/storage_free_mb/config"
  storage_free_cfg_payload="$(printf '{"name":"%s Storage Free","uniq_id":"%s_storage_free_mb","stat_t":"%s","unit_of_meas":"MB","stat_cla":"measurement","val_tpl":"{{ value_json.storage_avail_mb }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:database-outline","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$storage_free_cfg_topic" "$storage_free_cfg_payload"

  security_cfg_topic="${discovery_prefix}/binary_sensor/${node_id}/security_hardening/config"
  security_cfg_payload="$(printf '{"name":"%s Security Hardening","uniq_id":"%s_security_hardening","stat_t":"%s","pl_on":"ON","pl_off":"OFF","val_tpl":"{{ \"ON\" if value_json.security_hardening_mode == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:shield-lock","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$security_cfg_topic" "$security_cfg_payload"

  motion_cfg_topic="${discovery_prefix}/binary_sensor/${node_id}/motion_active/config"
  motion_cfg_payload="$(printf '{"name":"%s Motion Active","uniq_id":"%s_motion_active","stat_t":"%s","pl_on":"ON","pl_off":"OFF","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:motion-sensor","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$motion_state_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$motion_cfg_topic" "$motion_cfg_payload"

  ftp_port_cfg_topic="${discovery_prefix}/binary_sensor/${node_id}/ftp_port/config"
  ftp_port_cfg_payload="$(printf '{"name":"%s FTP Port","uniq_id":"%s_ftp_port","stat_t":"%s","pl_on":"ON","pl_off":"OFF","val_tpl":"{{ \"ON\" if value_json.port_ftp_open == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:folder-network","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$ftp_port_cfg_topic" "$ftp_port_cfg_payload"

  telnet_port_cfg_topic="${discovery_prefix}/binary_sensor/${node_id}/telnet_port/config"
  telnet_port_cfg_payload="$(printf '{"name":"%s Telnet Port","uniq_id":"%s_telnet_port","stat_t":"%s","pl_on":"ON","pl_off":"OFF","val_tpl":"{{ \"ON\" if value_json.port_telnet_open == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:console-network","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$telnet_port_cfg_topic" "$telnet_port_cfg_payload"

  reboot_cfg_topic="${discovery_prefix}/button/${node_id}/reboot/config"
  reboot_cfg_payload="$(printf '{"name":"%s Reboot","uniq_id":"%s_reboot","cmd_t":"%s","pl_prs":"reboot","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:restart","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$reboot_cfg_topic" "$reboot_cfg_payload"

  snapshot_cfg_topic="${discovery_prefix}/button/${node_id}/snapshot/config"
  snapshot_cfg_payload="$(printf '{"name":"%s Snapshot","uniq_id":"%s_snapshot","cmd_t":"%s","pl_prs":"snapshot","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:camera","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$snapshot_cfg_topic" "$snapshot_cfg_payload"

  profile_select_cfg_topic="${discovery_prefix}/select/${node_id}/profile/config"
  profile_select_cfg_payload="$(printf '{"name":"%s Profile Preset","uniq_id":"%s_profile_select","cmd_t":"%s","stat_t":"%s","options":["balanced","low-cpu","rtsp-only"],"val_tpl":"{{ value_json.perfprofile }}","cmd_tpl":"%s","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:tune-variant","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$health_topic_json" "$cmd_profile_tpl_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$profile_select_cfg_topic" "$profile_select_cfg_payload"

  motion_switch_cfg_topic="${discovery_prefix}/switch/${node_id}/motion_detection/config"
  motion_switch_cfg_payload="$(printf '{"name":"%s Motion Detection","uniq_id":"%s_motion_detection","cmd_t":"%s","stat_t":"%s","pl_on":"%s","pl_off":"%s","stat_on":"ON","stat_off":"OFF","val_tpl":"{{ \"ON\" if value_json.motion_enabled == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:motion-sensor","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$health_topic_json" "$cmd_motion_on_json" "$cmd_motion_off_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$motion_switch_cfg_topic" "$motion_switch_cfg_payload"

  ir_switch_cfg_topic="${discovery_prefix}/switch/${node_id}/ir_led/config"
  ir_switch_cfg_payload="$(printf '{"name":"%s IR LED","uniq_id":"%s_ir_led","cmd_t":"%s","stat_t":"%s","pl_on":"%s","pl_off":"%s","stat_on":"ON","stat_off":"OFF","val_tpl":"{{ \"ON\" if value_json.ir_led_on == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:lightbulb-night","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$health_topic_json" "$cmd_ir_on_json" "$cmd_ir_off_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$ir_switch_cfg_topic" "$ir_switch_cfg_payload"

  front_switch_cfg_topic="${discovery_prefix}/switch/${node_id}/front_led/config"
  front_switch_cfg_payload="$(printf '{"name":"%s Front LED","uniq_id":"%s_front_led","cmd_t":"%s","stat_t":"%s","pl_on":"%s","pl_off":"%s","stat_on":"ON","stat_off":"OFF","val_tpl":"{{ \"ON\" if value_json.front_led_on == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:led-on","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$health_topic_json" "$cmd_front_on_json" "$cmd_front_off_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$front_switch_cfg_topic" "$front_switch_cfg_payload"

  red_switch_cfg_topic="${discovery_prefix}/switch/${node_id}/red_led/config"
  red_switch_cfg_payload="$(printf '{"name":"%s Red LED","uniq_id":"%s_red_led","cmd_t":"%s","stat_t":"%s","pl_on":"%s","pl_off":"%s","stat_on":"ON","stat_off":"OFF","val_tpl":"{{ \"ON\" if value_json.red_led_on == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:led-on","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$health_topic_json" "$cmd_red_on_json" "$cmd_red_off_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$red_switch_cfg_topic" "$red_switch_cfg_payload"

  ftp_switch_cfg_topic="${discovery_prefix}/switch/${node_id}/ftp_service/config"
  ftp_switch_cfg_payload="$(printf '{"name":"%s FTP Service","uniq_id":"%s_ftp_service","cmd_t":"%s","stat_t":"%s","pl_on":"%s","pl_off":"%s","stat_on":"ON","stat_off":"OFF","val_tpl":"{{ \"ON\" if value_json.ftp_enabled == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:folder-network","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$health_topic_json" "$cmd_ftp_on_json" "$cmd_ftp_off_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$ftp_switch_cfg_topic" "$ftp_switch_cfg_payload"

  telnet_switch_cfg_topic="${discovery_prefix}/switch/${node_id}/telnet_service/config"
  telnet_switch_cfg_payload="$(printf '{"name":"%s Telnet Service","uniq_id":"%s_telnet_service","cmd_t":"%s","stat_t":"%s","pl_on":"%s","pl_off":"%s","stat_on":"ON","stat_off":"OFF","val_tpl":"{{ \"ON\" if value_json.telnet_enabled == 1 else \"OFF\" }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:console-network","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$health_topic_json" "$cmd_telnet_on_json" "$cmd_telnet_off_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$telnet_switch_cfg_topic" "$telnet_switch_cfg_payload"
}

init_slow_health_defaults()
{
  slow_web_mode="full"
  slow_profile="balanced"
  slow_security_hardening_mode=0
  slow_motion_enabled=0
  slow_ftp_enabled=0
  slow_telnet_enabled=0
  slow_rtsp_enabled=0
  slow_onvif_enabled=0
  slow_storage_total_mb=0
  slow_storage_used_mb=0
  slow_storage_avail_mb=0
  slow_storage_used_percent=0
  slow_primary_ip="n/a"
  slow_dns_server_count=0
  slow_port_https_open=0
  slow_port_http_open=0
  slow_port_rtsp_open=0
  slow_port_onvif_open=0
  slow_port_ftp_open=0
  slow_port_telnet_open=0
}

collect_slow_health_metrics()
{
  init_slow_health_defaults

  ultralite_http_port="$(sanitize_int_range "$(read_kv_config_value /mnt/config/boot.conf ULTRALITE_HTTP_PORT 80)" 1 65535 80)"
  slow_web_mode="full"
  slow_profile="balanced"
  slow_security_hardening_mode=0
  if [ -f /mnt/config/boot.conf ]; then
    # shellcheck disable=SC1090
    . /mnt/config/boot.conf
    slow_web_mode="${WEB_MODE:-full}"
    if [ "${LOW_CPU_PROFILE:-0}" = "1" ]; then
      slow_profile="low-cpu"
    fi
    if is_truthy_local "${SECURITY_HARDENING_MODE:-0}"; then
      slow_security_hardening_mode=1
    fi
  fi
  if [ -f /mnt/config/service_trim.conf ]; then
    # shellcheck disable=SC1090
    . /mnt/config/service_trim.conf
    if [ "${SERVICE_TRIM:-0}" = "1" ]; then
      slow_profile="rtsp-only"
    fi
  fi

  ftp_port="$(sanitize_int_range "$(read_kv_config_value /mnt/config/ftp.conf PORT 21)" 1 65535 21)"
  telnet_port="$(sanitize_int_range "$(read_kv_config_value /mnt/config/telnetd.conf TELNET_PORT 23)" 1 65535 23)"
  rtsp_port="$(sanitize_int_range "$(read_kv_config_value /mnt/config/rtspserver.conf PORT 554)" 1 65535 554)"
  onvif_port="$(sanitize_int_range "$(read_kv_config_value /mnt/config/onvif.conf ONVIF_PORT 8081)" 1 65535 8081)"

  http_port=80
  case "$slow_web_mode" in
    ultra-lite|ultralite)
      http_port="$ultralite_http_port"
      ;;
  esac

  slow_motion_enabled="$(service_script_running_int /mnt/controlscripts/motion-detection /var/run/detection-monitor.pid)"
  slow_ftp_enabled="$(service_script_running_int /mnt/controlscripts/ftp-server /var/run/ftp-server.pid)"
  slow_telnet_enabled="$(service_script_running_int /mnt/controlscripts/telnet-server /var/run/telnet-server.pid)"
  slow_rtsp_enabled="$(service_script_running_int /mnt/controlscripts/rtsp-h26x /var/run/v4l2rtspserver.pid)"
  slow_onvif_enabled="$(service_script_running_int /mnt/controlscripts/onvif /var/run/onvif.pid)"

  slow_primary_ip="$(ifconfig 2>/dev/null | sed -n -e 's/.*inet addr:\([0-9.]*\).*/\1/p' -e 's/^[[:space:]]*inet \([0-9.]*\).*/\1/p' | grep -v '^127\.' | head -n 1)"
  [ -n "$slow_primary_ip" ] || slow_primary_ip="n/a"
  slow_dns_server_count="$(awk '/^nameserver[[:space:]]+/{count++} END{print count+0}' /etc/resolv.conf 2>/dev/null)"
  case "$slow_dns_server_count" in
    ''|*[!0-9]*) slow_dns_server_count=0 ;;
  esac

  storage_total_kb=0
  storage_used_kb=0
  storage_avail_kb=0
  storage_used_percent=0
  df_line="$(df -k /mnt 2>/dev/null | awk 'NR==2{print $2 " " $3 " " $4 " " $5}')"
  if [ -z "$df_line" ]; then
    df_line="$(df -k / 2>/dev/null | awk 'NR==2{print $2 " " $3 " " $4 " " $5}')"
  fi
  set -- $df_line
  storage_total_kb="$1"
  storage_used_kb="$2"
  storage_avail_kb="$3"
  storage_used_text="$4"
  case "$storage_total_kb" in ''|*[!0-9]*) storage_total_kb=0 ;; esac
  case "$storage_used_kb" in ''|*[!0-9]*) storage_used_kb=0 ;; esac
  case "$storage_avail_kb" in ''|*[!0-9]*) storage_avail_kb=0 ;; esac
  storage_used_percent="$(printf '%s' "$storage_used_text" | tr -cd '0-9')"
  case "$storage_used_percent" in ''|*[!0-9]*) storage_used_percent=0 ;; esac
  if [ "$storage_used_percent" -le 0 ] && [ "$storage_total_kb" -gt 0 ]; then
    storage_used_percent=$((100 * storage_used_kb / storage_total_kb))
  fi
  slow_storage_total_mb=$((storage_total_kb / 1024))
  slow_storage_used_mb=$((storage_used_kb / 1024))
  slow_storage_avail_mb=$((storage_avail_kb / 1024))
  slow_storage_used_percent="$storage_used_percent"

  listen_tcp="$(netstat -lnt 2>/dev/null)"
  if [ -z "$listen_tcp" ]; then
    listen_tcp="$(netstat -ln 2>/dev/null)"
  fi
  slow_port_https_open="$(port_open_from_list_int "$listen_tcp" 443)"
  slow_port_http_open="$(port_open_from_list_int "$listen_tcp" "$http_port")"
  slow_port_rtsp_open="$(port_open_from_list_int "$listen_tcp" "$rtsp_port")"
  slow_port_onvif_open="$(port_open_from_list_int "$listen_tcp" "$onvif_port")"
  slow_port_ftp_open="$(port_open_from_list_int "$listen_tcp" "$ftp_port")"
  slow_port_telnet_open="$(port_open_from_list_int "$listen_tcp" "$telnet_port")"
}

save_slow_health_cache()
{
  now_ts="$(date +%s 2>/dev/null)"
  case "$now_ts" in
    ''|*[!0-9]*) now_ts=0 ;;
  esac
  [ "$now_ts" -gt 0 ] || return 0
  {
    printf 'ts=%s\n' "$now_ts"
    printf 'web_mode=%s\n' "$slow_web_mode"
    printf 'profile=%s\n' "$slow_profile"
    printf 'security_hardening_mode=%s\n' "$slow_security_hardening_mode"
    printf 'motion_enabled=%s\n' "$slow_motion_enabled"
    printf 'ftp_enabled=%s\n' "$slow_ftp_enabled"
    printf 'telnet_enabled=%s\n' "$slow_telnet_enabled"
    printf 'rtsp_enabled=%s\n' "$slow_rtsp_enabled"
    printf 'onvif_enabled=%s\n' "$slow_onvif_enabled"
    printf 'storage_total_mb=%s\n' "$slow_storage_total_mb"
    printf 'storage_used_mb=%s\n' "$slow_storage_used_mb"
    printf 'storage_avail_mb=%s\n' "$slow_storage_avail_mb"
    printf 'storage_used_percent=%s\n' "$slow_storage_used_percent"
    printf 'primary_ip=%s\n' "$slow_primary_ip"
    printf 'dns_server_count=%s\n' "$slow_dns_server_count"
    printf 'port_https_open=%s\n' "$slow_port_https_open"
    printf 'port_http_open=%s\n' "$slow_port_http_open"
    printf 'port_rtsp_open=%s\n' "$slow_port_rtsp_open"
    printf 'port_onvif_open=%s\n' "$slow_port_onvif_open"
    printf 'port_ftp_open=%s\n' "$slow_port_ftp_open"
    printf 'port_telnet_open=%s\n' "$slow_port_telnet_open"
  } > "$HEALTH_SLOW_CACHE_FILE"
}

load_slow_health_cache()
{
  [ -f "$HEALTH_SLOW_CACHE_FILE" ] || return 1
  init_slow_health_defaults
  cache_ts=0

  while IFS='=' read -r key value; do
    case "$key" in
      ts) cache_ts="$value" ;;
      web_mode) slow_web_mode="$value" ;;
      profile) slow_profile="$value" ;;
      security_hardening_mode) slow_security_hardening_mode="$value" ;;
      motion_enabled) slow_motion_enabled="$value" ;;
      ftp_enabled) slow_ftp_enabled="$value" ;;
      telnet_enabled) slow_telnet_enabled="$value" ;;
      rtsp_enabled) slow_rtsp_enabled="$value" ;;
      onvif_enabled) slow_onvif_enabled="$value" ;;
      storage_total_mb) slow_storage_total_mb="$value" ;;
      storage_used_mb) slow_storage_used_mb="$value" ;;
      storage_avail_mb) slow_storage_avail_mb="$value" ;;
      storage_used_percent) slow_storage_used_percent="$value" ;;
      primary_ip) slow_primary_ip="$value" ;;
      dns_server_count) slow_dns_server_count="$value" ;;
      port_https_open) slow_port_https_open="$value" ;;
      port_http_open) slow_port_http_open="$value" ;;
      port_rtsp_open) slow_port_rtsp_open="$value" ;;
      port_onvif_open) slow_port_onvif_open="$value" ;;
      port_ftp_open) slow_port_ftp_open="$value" ;;
      port_telnet_open) slow_port_telnet_open="$value" ;;
    esac
  done < "$HEALTH_SLOW_CACHE_FILE"

  case "$cache_ts" in
    ''|*[!0-9]*) return 1 ;;
  esac

  now_ts="$(date +%s 2>/dev/null)"
  case "$now_ts" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ "$cache_ts" -le "$now_ts" ] || return 1
  age=$((now_ts - cache_ts))
  [ "$age" -le "$MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS" ] || return 1

  case "$slow_security_hardening_mode" in ''|*[!0-9]*) slow_security_hardening_mode=0 ;; esac
  case "$slow_motion_enabled" in ''|*[!0-9]*) slow_motion_enabled=0 ;; esac
  case "$slow_ftp_enabled" in ''|*[!0-9]*) slow_ftp_enabled=0 ;; esac
  case "$slow_telnet_enabled" in ''|*[!0-9]*) slow_telnet_enabled=0 ;; esac
  case "$slow_rtsp_enabled" in ''|*[!0-9]*) slow_rtsp_enabled=0 ;; esac
  case "$slow_onvif_enabled" in ''|*[!0-9]*) slow_onvif_enabled=0 ;; esac
  case "$slow_storage_total_mb" in ''|*[!0-9]*) slow_storage_total_mb=0 ;; esac
  case "$slow_storage_used_mb" in ''|*[!0-9]*) slow_storage_used_mb=0 ;; esac
  case "$slow_storage_avail_mb" in ''|*[!0-9]*) slow_storage_avail_mb=0 ;; esac
  case "$slow_storage_used_percent" in ''|*[!0-9]*) slow_storage_used_percent=0 ;; esac
  case "$slow_dns_server_count" in ''|*[!0-9]*) slow_dns_server_count=0 ;; esac
  case "$slow_port_https_open" in ''|*[!0-9]*) slow_port_https_open=0 ;; esac
  case "$slow_port_http_open" in ''|*[!0-9]*) slow_port_http_open=0 ;; esac
  case "$slow_port_rtsp_open" in ''|*[!0-9]*) slow_port_rtsp_open=0 ;; esac
  case "$slow_port_onvif_open" in ''|*[!0-9]*) slow_port_onvif_open=0 ;; esac
  case "$slow_port_ftp_open" in ''|*[!0-9]*) slow_port_ftp_open=0 ;; esac
  case "$slow_port_telnet_open" in ''|*[!0-9]*) slow_port_telnet_open=0 ;; esac
  [ -n "$slow_primary_ip" ] || slow_primary_ip="n/a"
  case "$slow_web_mode" in full|http|off|ultra-lite|ultralite) ;; *) slow_web_mode="full" ;; esac
  case "$slow_profile" in balanced|low-cpu|rtsp-only) ;; *) slow_profile="balanced" ;; esac

  return 0
}

load_or_collect_slow_health_metrics()
{
  if load_slow_health_cache; then
    return 0
  fi
  collect_slow_health_metrics
  save_slow_health_cache
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

  reboot_epoch=0
  if [ -r /proc/stat ]; then
    reboot_epoch="$(awk '/^btime / {print $2; exit}' /proc/stat 2>/dev/null)"
    case "$reboot_epoch" in
      ''|*[!0-9]*) reboot_epoch=0 ;;
    esac
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

  load_or_collect_slow_health_metrics
  web_mode="$slow_web_mode"
  profile="$slow_profile"
  security_hardening_mode="$slow_security_hardening_mode"
  motion_enabled="$slow_motion_enabled"
  ftp_enabled="$slow_ftp_enabled"
  telnet_enabled="$slow_telnet_enabled"
  rtsp_enabled="$slow_rtsp_enabled"
  onvif_enabled="$slow_onvif_enabled"

  front_led_on="$(read_int_file_value /sys/class/leds/blue_led/brightness 0)"
  red_led_on="$(read_int_file_value /sys/class/leds/red_led/brightness 0)"
  ir_led_on="$(read_int_file_value /sys/user-gpio/ir-led 0)"

  motion_active=0
  if [ -x /mnt/bin/getflag ] && [ -f /tmp/rec_control ]; then
    motion_active="$(/mnt/bin/getflag /tmp/rec_control 2>/dev/null)"
    case "$motion_active" in
      ''|*[!0-9]*) motion_active=0 ;;
    esac
  fi
  case "$motion_active" in
    1) motion_state_payload="ON" ;;
    *) motion_state_payload="OFF" ;;
  esac

  primary_ip="$slow_primary_ip"
  dns_server_count="$slow_dns_server_count"
  storage_total_mb="$slow_storage_total_mb"
  storage_used_mb="$slow_storage_used_mb"
  storage_avail_mb="$slow_storage_avail_mb"
  storage_used_percent="$slow_storage_used_percent"
  port_https_open="$slow_port_https_open"
  port_http_open="$slow_port_http_open"
  port_rtsp_open="$slow_port_rtsp_open"
  port_onvif_open="$slow_port_onvif_open"
  port_ftp_open="$slow_port_ftp_open"
  port_telnet_open="$slow_port_telnet_open"

  hostname_value="$(hostname 2>/dev/null)"
  hostname_json="$(json_escape "$hostname_value")"
  web_mode_json="$(json_escape "$web_mode")"
  profile_json="$(json_escape "$profile")"
  power_sensor_path_json="$(json_escape "$power_sensor_path")"
  primary_ip_json="$(json_escape "$primary_ip")"

  printf '{"ts":%s,"hostname":"%s","uptime_seconds":%s,"reboot_epoch":%s,"cpu":%s,"ram_used_kb":%s,"ram_total_kb":%s,"ram_percent":%s,"chip_temp_c":%s,"power_estimate_enabled":%s,"power_estimated_mw":%s,"power_estimated_current_ma":%s,"power_voltage_mv":%s,"power_sensor_path":"%s","web_mode":"%s","perfprofile":"%s","security_hardening_mode":%s,"motion_active":%s,"motion_enabled":%s,"ftp_enabled":%s,"telnet_enabled":%s,"rtsp_enabled":%s,"onvif_enabled":%s,"front_led_on":%s,"red_led_on":%s,"ir_led_on":%s,"storage_total_mb":%s,"storage_used_mb":%s,"storage_avail_mb":%s,"storage_used_percent":%s,"primary_ip":"%s","dns_server_count":%s,"port_https_open":%s,"port_http_open":%s,"port_rtsp_open":%s,"port_onvif_open":%s,"port_ftp_open":%s,"port_telnet_open":%s}' \
    "$now_ts" "$hostname_json" "$uptime_seconds" "$reboot_epoch" "$cpu" "$mem_used" "$mem_total" "$ram_percent" "$chip_temp_json" "$power_estimated_enabled_json" "$power_estimated_mw_json" "$power_estimated_current_ma_json" "$power_voltage_mv_json" "$power_sensor_path_json" "$web_mode_json" "$profile_json" "$security_hardening_mode" "$motion_active" "$motion_enabled" "$ftp_enabled" "$telnet_enabled" "$rtsp_enabled" "$onvif_enabled" "$front_led_on" "$red_led_on" "$ir_led_on" "$storage_total_mb" "$storage_used_mb" "$storage_avail_mb" "$storage_used_percent" "$primary_ip_json" "$dns_server_count" "$port_https_open" "$port_http_open" "$port_rtsp_open" "$port_onvif_open" "$port_ftp_open" "$port_telnet_open"
}

publish_health()
{
  payload="$(build_health_payload)"
  mqtt_publish_topic_suffix "health" "$payload" 0
  mqtt_publish_topic_suffix "motion/state" "$motion_state_payload" 1 >/dev/null 2>&1 || true
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

ensure_low_cpu_runtime_tuning()
{
  install_config /mnt/config/mqtt.conf

  mqtt_health_interval_current="$(sanitize_int_range "$(read_kv_config_value /mnt/config/mqtt.conf MQTT_HEALTH_INTERVAL_SECONDS 120)" 10 86400 120)"
  if [ "$mqtt_health_interval_current" -lt 120 ]; then
    rewrite_config /mnt/config/mqtt.conf MQTT_HEALTH_INTERVAL_SECONDS 120
    MQTT_HEALTH_INTERVAL_SECONDS=120
  fi

  mqtt_slow_ttl_current="$(sanitize_int_range "$(read_kv_config_value /mnt/config/mqtt.conf MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS 180)" 10 86400 180)"
  if [ "$mqtt_slow_ttl_current" -lt 180 ]; then
    rewrite_config /mnt/config/mqtt.conf MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS 180
    MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS=180
  fi

  if [ ! -f /mnt/config/sound_detection.conf ]; then
    {
      echo "ENABLE=0"
      echo "THRESHOLD=1500"
      echo "INTERVAL=10"
    } > /mnt/config/sound_detection.conf
  fi
  sound_interval_current="$(sanitize_int_range "$(read_kv_config_value /mnt/config/sound_detection.conf INTERVAL 10)" 1 300 10)"
  if [ "$sound_interval_current" -lt 10 ]; then
    rewrite_config /mnt/config/sound_detection.conf INTERVAL 10
  fi
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
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO 1
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION 1
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_OSD 1
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG 1
      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 1
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO 0
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-only
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0
      ensure_low_cpu_runtime_tuning
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
      ensure_low_cpu_runtime_tuning
      for svc in ftp-server telnet-server motion-detection recording timelapse auto-night-detection front-led night-mode network-monitor; do
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

  rm -f "$HEALTH_SLOW_CACHE_FILE" >/dev/null 2>&1 || true
  restart_service_if_need /mnt/controlscripts/rtsp-h26x
  restart_service_if_need /mnt/controlscripts/onvif
  return 0
}

apply_toggle_command()
{
  cmd="$1"
  requested_value="$(normalize_toggle_value "$2")"
  if [ -z "$requested_value" ]; then
    return 2
  fi

  case "$cmd" in
    motion|motion_detection)
      script="/mnt/controlscripts/motion-detection"
      ;;
    ir_led)
      script="/mnt/controlscripts/ir-led"
      ;;
    front_led)
      script="/mnt/controlscripts/front-led"
      ;;
    red_led)
      script="/mnt/controlscripts/red-led"
      ;;
    ftp)
      if security_hardening_enabled_runtime; then
        return 3
      fi
      script="/mnt/controlscripts/ftp-server"
      ;;
    telnet)
      if security_hardening_enabled_runtime; then
        return 3
      fi
      script="/mnt/controlscripts/telnet-server"
      ;;
    rtsp)
      script="/mnt/controlscripts/rtsp-h26x"
      ;;
    onvif)
      script="/mnt/controlscripts/onvif"
      ;;
    *)
      return 1
      ;;
  esac

  [ -x "$script" ] || return 1

  action="$requested_value"
  if [ "$requested_value" = "toggle" ]; then
    if [ "$(service_script_running_int "$script")" = "1" ]; then
      action="off"
    else
      action="on"
    fi
  fi

  case "$action" in
    on)
      "$script" start >/dev/null 2>&1 || return 1
      ;;
    off)
      "$script" stop >/dev/null 2>&1 || return 1
      ;;
    *)
      return 2
      ;;
  esac

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
      *:*)
        cmd="${payload_trimmed%%:*}"
        value="${payload_trimmed#*:}"
        ;;
      *=*)
        cmd="${payload_trimmed%%=*}"
        value="${payload_trimmed#*=}"
        ;;
      *_on)
        cmd="${payload_trimmed%_on}"
        value="on"
        ;;
      *_off)
        cmd="${payload_trimmed%_off}"
        value="off"
        ;;
      *)
        cmd="$payload_trimmed"
        ;;
    esac
  fi

  cmd="$(printf '%s' "$cmd" | tr '[:upper:]' '[:lower:]' | tr '-' '_' | sed 's/[[:space:]]\+/_/g')"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  refresh_state=0

  case "$cmd" in
    reboot)
      publish_event_simple "command.reboot" "accepted"
      /sbin/reboot
      ;;
    snapshot)
      # Use a fixed path instead of timestamped to prevent /tmp RAM exhaustion
      shot_path="/tmp/mqtt-last-snapshot.jpg"
      if /mnt/bin/getimage > "$shot_path" 2>/dev/null; then
        shot_json="$(json_escape "$shot_path")"
        now_ts="$(date +%s 2>/dev/null)"
        [ -n "$now_ts" ] || now_ts=0
        payload=$(printf '{"ts":%s,"type":"snapshot.manual","snapshot":"%s"}' "$now_ts" "$shot_json")
        mqtt_publish_topic_suffix "event" "$payload" 0
        mqtt_publish_topic_suffix "snapshot/last_path" "$shot_path" 1 >/dev/null 2>&1 || true
      else
        publish_event_simple "command.snapshot" "failed"
      fi
      refresh_state=1
      ;;
    profile)
      if apply_profile_command "$value"; then
        publish_event_simple "command.profile" "$value"
        refresh_state=1
      else
        publish_event_simple "command.profile" "invalid:$value"
      fi
      ;;
    motion|motion_detection|ir_led|front_led|red_led|ftp|telnet|rtsp|onvif)
      if apply_toggle_command "$cmd" "$value"; then
        publish_event_simple "command.${cmd}" "${value:-toggle}"
        refresh_state=1
      else
        toggle_rc=$?
        case "$toggle_rc" in
          3)
            publish_event_simple "command.${cmd}" "blocked:security_hardening"
            ;;
          2)
            publish_event_simple "command.${cmd}" "invalid-value:${value}"
            ;;
          *)
            publish_event_simple "command.${cmd}" "failed:${value}"
            ;;
        esac
      fi
      ;;
    discovery|ha_discovery|discovery_refresh)
      publish_homeassistant_discovery
      publish_event_simple "command.discovery" "published"
      ;;
    health|health_now)
      publish_health >/dev/null 2>&1 || true
      publish_event_simple "command.health" "published"
      ;;
    *)
      publish_event_simple "command.unknown" "$payload_trimmed"
      ;;
  esac

  if [ "$refresh_state" -eq 1 ]; then
    rm -f "$HEALTH_SLOW_CACHE_FILE" >/dev/null 2>&1 || true
    publish_health >/dev/null 2>&1 || true
  fi
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
