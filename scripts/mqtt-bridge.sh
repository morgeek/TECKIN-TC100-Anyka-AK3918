#!/bin/sh

. /mnt/scripts/event-logger.sh

CONFIG_FILE="/mnt/config/mqtt.conf"
LOGPATH="/tmp/log/mqtt-bridge.log"
STATE_FILE="/tmp/mqtt-bridge.state"
HEALTH_SLOW_CACHE_FILE="/tmp/mqtt-bridge.health-slow.cache"
NETWORK_STATE_FILE="/tmp/network-monitor.state"
NETWORK_STATE_MAX_AGE_SECONDS=900
CURL_BIN="/mnt/bin/curl"
JQ_BIN="/mnt/bin/jq"
LOCAL_STATE_CGI="/mnt/www/cgi-bin/state.cgi"
INTEGRATION_MANIFEST_STATE_FILE="/tmp/mqtt-bridge.integration-manifest.state"
STREAM_FIFO="/tmp/mqtt-bridge-sub.fifo"
stream_pid=""

. /mnt/scripts/common_functions.sh

# Cached boot-time epoch from /proc/stat — read once, zero forks on every subsequent call.
BTIME=0
_load_btime()
{
  while read -r _key _val _; do
    [ "$_key" = "btime" ] && BTIME="$_val" && break
  done < /proc/stat
}

json_escape()
{
  # Fast path: most values (hostnames, paths, profile names) have no special chars.
  _je_nl='
'
  _je_tab='	'
  case "$1" in
    *\\*|*'"'*|*"$_je_nl"*|*"$_je_tab"*) ;;
    *) printf '%s' "$1"; return ;;
  esac
  # Slow path: escape backslash, double-quote, newline, tab (no forks).
  _je="$1"
  _je_out=""
  while [ -n "$_je" ]; do
    case "$_je" in
      *\\*)
        _je_out="${_je_out}${_je%%\\*}\\\\"
        _je="${_je#*\\}"
        ;;
      *'"'*)
        _je_out="${_je_out}${_je%%\"*}\\\""
        _je="${_je#*\"}"
        ;;
      *"$_je_nl"*)
        _je_out="${_je_out}${_je%%"$_je_nl"*}\\n"
        _je="${_je#*"$_je_nl"}"
        ;;
      *"$_je_tab"*)
        _je_out="${_je_out}${_je%%"$_je_tab"*}\\t"
        _je="${_je#*"$_je_tab"}"
        ;;
      *)
        _je_out="${_je_out}${_je}"
        _je=""
        ;;
    esac
  done
  printf '%s' "$_je_out"
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
  if [ ! -d /tmp/log ]; then
    mkdir -p /tmp/log >/dev/null 2>&1 || true
  fi
  [ "$BTIME" -gt 0 ] || _load_btime
  read -r _up _ < /proc/uptime
  printf '%s %s\n' "$((BTIME + ${_up%.*}))" "$1" >> "$LOGPATH"
}

load_config()
{
  install_config "$CONFIG_FILE"
  # shellcheck disable=SC1090
  if [ -f "$CONFIG_FILE" ]; then
    . "$CONFIG_FILE"
  fi

  MQTT_ENABLE="${MQTT_ENABLE:-0}"
  MQTT_HOST="${MQTT_HOST:-}"
  
  # Plug & Play: Auto-detect MQTT broker if not configured
  if [ -z "$MQTT_HOST" ] || [ "$MQTT_HOST" = "127.0.0.1" ] || [ "$MQTT_HOST" = "192.168.1.10" ]; then
    # Try common Home Assistant broker names
    for host in "homeassistant" "hassio" "home-assistant"; do
      if ping -c 1 -W 2 "$host" >/dev/null 2>&1; then
        MQTT_HOST="$host"
        log_msg "Auto-detected MQTT broker at: $MQTT_HOST"
        break
      fi
    done
    # Fallback to Gateway if still not found
    if [ -z "$MQTT_HOST" ] || [ "$MQTT_HOST" = "127.0.0.1" ]; then
      gw_ip="$(get_default_gateway)"
      if [ "$gw_ip" != "n/a" ] && [ "$gw_ip" != "0.0.0.0" ]; then
        if ping -c 1 -W 1 "$gw_ip" >/dev/null 2>&1; then
          # We don't assume the gateway IS the broker, but it's a better default than loopback in many IoT networks
          # However, let's stick to the config default if auto-detect fails
          [ -n "$MQTT_HOST" ] || MQTT_HOST="$(read_kv_config_value "$CONFIG_FILE" MQTT_HOST "127.0.0.1")"
        fi
      fi
    fi
  fi
  [ -n "$MQTT_HOST" ] || MQTT_HOST="127.0.0.1"
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
  MQTT_STREAM_ENABLE="${MQTT_STREAM_ENABLE:-1}"
  MQTT_STREAM_MAX_SECONDS="$(sanitize_int_range "${MQTT_STREAM_MAX_SECONDS:-300}" 30 3600 300)"
  MQTT_COMMAND_REPEAT_WINDOW_SECONDS="$(sanitize_int_range "${MQTT_COMMAND_REPEAT_WINDOW_SECONDS:-20}" 0 600 20)"
  MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS="$(sanitize_int_range "${MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS:-2}" 1 60 2)"
  MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS="$(sanitize_int_range "${MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS:-20}" 1 600 20)"
  MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER="$(sanitize_int_range "${MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER:-2}" 1 5 2)"
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

  if [ "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" -lt "$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS" ]; then
    MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS"
  fi
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

detect_primary_ip_current()
{
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
  printf '%s\n' "$primary_ip"
}

integration_manifest_fingerprint()
{
  current_primary_ip="$(detect_primary_ip_current)"
  current_hostname=""
  read -r current_hostname < /proc/sys/kernel/hostname 2>/dev/null || current_hostname=""

  {
    printf 'hostname=%s\n' "$current_hostname"
    printf 'primary_ip=%s\n' "$current_primary_ip"
    for cfg_path in /mnt/config/boot.conf /mnt/config/rtspserver.conf /mnt/config/onvif.conf /mnt/config/mqtt.conf; do
      printf '[%s]\n' "$cfg_path"
      [ -r "$cfg_path" ] && cat "$cfg_path"
    done
  } | md5sum | awk '{print $1}'
}

run_local_state_cgi_query()
{
  state_query="$1"
  [ -n "$state_query" ] || return 1
  [ -x "$LOCAL_STATE_CGI" ] || return 1

  (
    cd "${LOCAL_STATE_CGI%/*}" || exit 1
    REQUEST_METHOD=GET QUERY_STRING="$state_query" ./state.cgi 2>/dev/null
  ) | awk 'BEGIN{body=0} body{print} /^$/{body=1}'
}

publish_integration_manifest()
{
  publish_mode="${1:-}"
  manifest_fp="$(integration_manifest_fingerprint)"
  [ -n "$manifest_fp" ] || return 1

  last_manifest_fp=""
  if [ -r "$INTEGRATION_MANIFEST_STATE_FILE" ]; then
    read -r last_manifest_fp < "$INTEGRATION_MANIFEST_STATE_FILE"
  fi
  if [ "$publish_mode" != "force" ] && [ "$manifest_fp" = "$last_manifest_fp" ]; then
    return 0
  fi

  manifest_payload="$(run_local_state_cgi_query 'cmd=integrationmanifest&redact=1')" || return 1
  [ -n "$manifest_payload" ] || return 1
  mqtt_publish_topic_suffix "integration/manifest" "$manifest_payload" 1 >/dev/null 2>&1 || return 1
  printf '%s\n' "$manifest_fp" > "$INTEGRATION_MANIFEST_STATE_FILE" 2>/dev/null || true
}

publish_integration_selftest()
{
  selftest_payload="$(run_local_state_cgi_query 'cmd=integrationtest')" || return 1
  [ -n "$selftest_payload" ] || return 1
  mqtt_publish_topic_suffix "integration/selftest" "$selftest_payload" 1 >/dev/null 2>&1 || return 1
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

init_network_state_defaults()
{
  network_state_ts=0
  network_state_fresh=0
  network_wifi_iface="wlan0"
  network_wifi_connected=0
  network_gateway_address=""
  network_gateway_reachable=0
  network_broker_monitor_enabled=0
  network_broker_host=""
  network_broker_port=1883
  network_broker_state="disabled"
  network_broker_reachable=0
  network_current_problem="disabled"
  network_reconnect_count=0
  network_broker_restart_count=0
  network_last_recovery_reason="none"
  network_last_recovery_action="none"
  network_last_recovery_ts=0
}

load_network_monitor_state()
{
  init_network_state_defaults

  if [ "$network_monitor_enabled" != "1" ]; then
    return 1
  fi

  network_current_problem="state_missing"
  [ -r "$NETWORK_STATE_FILE" ] || return 1

  while IFS='=' read -r key value; do
    case "$key" in
      ts) network_state_ts="$value" ;;
      wifi_iface) network_wifi_iface="$value" ;;
      wifi_connected) network_wifi_connected="$value" ;;
      gateway_address) network_gateway_address="$value" ;;
      gateway_reachable) network_gateway_reachable="$value" ;;
      broker_monitor_enabled) network_broker_monitor_enabled="$value" ;;
      broker_host) network_broker_host="$value" ;;
      broker_port) network_broker_port="$value" ;;
      broker_state) network_broker_state="$value" ;;
      broker_reachable) network_broker_reachable="$value" ;;
      current_problem) network_current_problem="$value" ;;
      reconnect_count) network_reconnect_count="$value" ;;
      broker_restart_count) network_broker_restart_count="$value" ;;
      last_recovery_reason) network_last_recovery_reason="$value" ;;
      last_recovery_action) network_last_recovery_action="$value" ;;
      last_recovery_ts) network_last_recovery_ts="$value" ;;
    esac
  done < "$NETWORK_STATE_FILE"

  case "$network_state_ts" in ''|*[!0-9]*) network_state_ts=0 ;; esac
  case "$network_wifi_connected" in ''|*[!0-9]*) network_wifi_connected=0 ;; esac
  case "$network_gateway_reachable" in ''|*[!0-9]*) network_gateway_reachable=0 ;; esac
  case "$network_broker_monitor_enabled" in ''|*[!0-9]*) network_broker_monitor_enabled=0 ;; esac
  case "$network_broker_port" in ''|*[!0-9]*) network_broker_port=1883 ;; esac
  case "$network_broker_reachable" in ''|*[!0-9]*) network_broker_reachable=0 ;; esac
  case "$network_reconnect_count" in ''|*[!0-9]*) network_reconnect_count=0 ;; esac
  case "$network_broker_restart_count" in ''|*[!0-9]*) network_broker_restart_count=0 ;; esac
  case "$network_last_recovery_ts" in ''|*[!0-9]*) network_last_recovery_ts=0 ;; esac
  [ -n "$network_wifi_iface" ] || network_wifi_iface="wlan0"
  [ -n "$network_current_problem" ] || network_current_problem="unknown"
  [ -n "$network_broker_state" ] || network_broker_state="unknown"
  [ -n "$network_last_recovery_reason" ] || network_last_recovery_reason="none"
  [ -n "$network_last_recovery_action" ] || network_last_recovery_action="none"

  [ "$BTIME" -gt 0 ] || _load_btime
  read -r _up _ < /proc/uptime
  now_ts=$((BTIME + ${_up%.*}))
  if [ "$network_state_ts" -le 0 ] || [ "$network_state_ts" -gt "$now_ts" ]; then
    network_current_problem="stale"
    return 1
  fi

  if [ $((now_ts - network_state_ts)) -gt "$NETWORK_STATE_MAX_AGE_SECONDS" ]; then
    network_current_problem="stale"
    return 1
  fi

  network_state_fresh=1
  return 0
}

normalize_toggle_value()
{
  # Pure-shell case-insensitive match — avoids tr/sed forks.
  case "$1" in
    [Oo][Nn]|1|[Tt][Rr][Uu][Ee]|[Ss][Tt][Aa][Rr][Tt]|[Ee][Nn][Aa][Bb][Ll][Ee]|[Ee][Nn][Aa][Bb][Ll][Ee][Dd])
      printf 'on\n' ;;
    [Oo][Ff][Ff]|0|[Ff][Aa][Ll][Ss][Ee]|[Ss][Tt][Oo][Pp]|[Dd][Ii][Ss][Aa][Bb][Ll][Ee]|[Dd][Ii][Ss][Aa][Bb][Ll][Ee][Dd])
      printf 'off\n' ;;
    [Tt][Oo][Gg][Gg][Ll][Ee])
      printf 'toggle\n' ;;
    *)
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

# Single-pass variant: checks all 6 ports in one awk+printf instead of 6 separate calls.
# Sets slow_port_* variables directly in the caller's scope.
# Args: listen_data http_port rtsp_port onvif_port ftp_port telnet_port
collect_port_states_from_netstat()
{
  eval "$(printf '%s\n' "$1" | awk \
    -v p_https=443 \
    -v p_http="$2" \
    -v p_rtsp="$3" \
    -v p_onvif="$4" \
    -v p_ftp="$5" \
    -v p_telnet="$6" \
    '$1 ~ /^tcp/ {
      n = split($4, a, ":")
      p = a[n]
      if (p == p_https)  https  = 1
      if (p == p_http)   http   = 1
      if (p == p_rtsp)   rtsp   = 1
      if (p == p_onvif)  onvif  = 1
      if (p == p_ftp)    ftp    = 1
      if (p == p_telnet) telnet = 1
    }
    END {
      print "slow_port_https_open="  (https  + 0)
      print "slow_port_http_open="   (http   + 0)
      print "slow_port_rtsp_open="   (rtsp   + 0)
      print "slow_port_onvif_open="  (onvif  + 0)
      print "slow_port_ftp_open="    (ftp    + 0)
      print "slow_port_telnet_open=" (telnet + 0)
    }')"
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

  # Build URL inline — eliminates mqtt_url subshell fork.
  if [ -n "$retain" ]; then
    _url="mqtt://${MQTT_HOST}:${MQTT_PORT}/${topic}?clientid=${MQTT_CLIENT_ID}-pub&qos=${MQTT_QOS}&retain=${retain}"
  else
    _url="mqtt://${MQTT_HOST}:${MQTT_PORT}/${topic}?clientid=${MQTT_CLIENT_ID}-pub&qos=${MQTT_QOS}"
  fi

  # Pipe payload via stdin — eliminates curl_auth_args subshell and temp file write/unlink.
  if [ -n "$MQTT_USER" ]; then
    printf '%s' "$payload" | "$CURL_BIN" --silent --show-error --max-time 10 \
      -u "${MQTT_USER}:${MQTT_PASSWORD}" --upload-file - "$_url" >/dev/null 2>&1
  else
    printf '%s' "$payload" | "$CURL_BIN" --silent --show-error --max-time 10 \
      --upload-file - "$_url" >/dev/null 2>&1
  fi
  _pub_rc=$?
  # Record result for MQTT health indicator in web UI (/tmp/mqtt_last_pub.status).
  [ "$BTIME" -gt 0 ] || _load_btime
  read -r _pub_up _ < /proc/uptime
  _pub_ts=$(( BTIME + ${_pub_up%.*} ))
  if [ "$_pub_rc" -eq 0 ]; then
    printf '%s ok\n' "$_pub_ts" > /tmp/mqtt_last_pub.status 2>/dev/null || true
  else
    printf '%s fail\n' "$_pub_ts" > /tmp/mqtt_last_pub.status 2>/dev/null || true
  fi
  return "$_pub_rc"
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

  read -r hostname_value < /proc/sys/kernel/hostname 2>/dev/null || hostname_value=""
  [ -n "$hostname_value" ] || hostname_value="TC100 Camera"

  discovery_prefix="$MQTT_HA_DISCOVERY_PREFIX"
  root_json="$(json_escape "$MQTT_TOPIC_ROOT")"
  cmd_json="$(json_escape "$MQTT_TOPIC_COMMAND")"
  health_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/health")"
  motion_state_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/motion/state")"
  network_state_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/network/state")"
  integration_manifest_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/integration/manifest")"
  avail_topic_json="$(json_escape "${MQTT_TOPIC_ROOT}/availability")"
  device_name_json="$(json_escape "$hostname_value")"
  device_id_json="$(json_escape "$node_id")"
  
  # Command templates for interactive entities
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

  # --- Sensors (CPU, RAM, Temp, Power) ---
  
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
  power_cfg_payload="$(printf '{"name":"%s Power Draw","uniq_id":"%s_power","stat_t":"%s","unit_of_meas":"W","dev_cla":"power","stat_cla":"measurement","val_tpl":"{{ (value_json.power_estimated_mw | float(0) / 1000) | round(2) if value_json.power_estimated_mw is number else none }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:flash","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$power_cfg_topic" "$power_cfg_payload"

  uptime_cfg_topic="${discovery_prefix}/sensor/${node_id}/uptime/config"
  uptime_cfg_payload="$(printf '{"name":"%s Uptime","uniq_id":"%s_uptime","stat_t":"%s","unit_of_meas":"s","dev_cla":"duration","stat_cla":"measurement","val_tpl":"{{ value_json.uptime_seconds }}","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:clock-outline","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$health_topic_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$uptime_cfg_topic" "$uptime_cfg_payload"

  # --- Elite Integration Entities ---

  # Camera (RTSP Stream)
  rtsp_port="$(read_kv_config_value /mnt/config/rtspserver.conf PORT 554)"
  rtsp_user="$(read_kv_config_value /mnt/config/rtspserver.conf USERNAME "")"
  rtsp_pass="$(read_kv_config_value /mnt/config/rtspserver.conf USERPASSWORD "")"
  rtsp_url_json="$(json_escape "rtsp://${rtsp_user:+$rtsp_user:$rtsp_pass@}$(detect_primary_ip_current):$rtsp_port/video0_unicast")"
  
  camera_cfg_topic="${discovery_prefix}/camera/${node_id}/live/config"
  camera_cfg_payload="$(printf '{"name":"%s Live","uniq_id":"%s_camera","topic":"%s","stream_source":"%s","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "${MQTT_TOPIC_ROOT}/snapshot/last_path" "$rtsp_url_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$camera_cfg_topic" "$camera_cfg_payload"

  # Switches (Interactive Toggles)
  for cmd in ir_led front_led red_led motion_detection privacy_shield; do
    uniq_id="${node_id}_${cmd}"
    name_suffix="$(echo "$cmd" | tr '_' ' ' | sed 's/led/LED/g' | sed 's/\b./\u&/g')"
    ic="mdi:toggle-switch"
    [ "$cmd" = "ir_led" ] && ic="mdi:eye-outline"
    [ "$cmd" = "front_led" ] && ic="mdi:led-on"
    [ "$cmd" = "red_led" ] && ic="mdi:led-variant-on"
    [ "$cmd" = "motion_detection" ] && ic="mdi:motion-sensor"
    [ "$cmd" = "privacy_shield" ] && ic="mdi:shield-account"

    stat_field="${cmd}_on"
    [ "$cmd" = "motion_detection" ] && stat_field="motion_enabled"
    [ "$cmd" = "privacy_shield" ] && stat_field="privacy_mode"

    switch_cfg_topic="${discovery_prefix}/switch/${node_id}/${cmd}/config"
    switch_cfg_payload="$(printf '{"name":"%s %s","uniq_id":"%s","stat_t":"%s","val_tpl":"{{ \"ON\" if value_json.%s == 1 else \"OFF\" }}","cmd_t":"%s","pl_on":"{\"cmd\":\"%s\",\"value\":\"on\"}","pl_off":"{\"cmd\":\"%s\",\"value\":\"off\"}","avty_t":"%s","ic":"%s","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$name_suffix" "$uniq_id" "$health_topic_json" "$stat_field" "$cmd_json" "$cmd" "$cmd" "$avail_topic_json" "$ic" "$device_id_json" "$device_name_json")"
    publish_discovery_config "$switch_cfg_topic" "$switch_cfg_payload"
  done

  # Maintenance Entities (Buttons/Select)
  reboot_btn_topic="${discovery_prefix}/button/${node_id}/reboot/config"
  reboot_btn_payload="$(printf '{"name":"%s Reboot","uniq_id":"%s_reboot","cmd_t":"%s","payload_press":"{\"cmd\":\"reboot\"}","avty_t":"%s","ic":"mdi:restart","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$reboot_btn_topic" "$reboot_btn_payload"

  snapshot_btn_topic="${discovery_prefix}/button/${node_id}/snapshot/config"
  snapshot_btn_payload="$(printf '{"name":"%s Take Snapshot","uniq_id":"%s_snapshot","cmd_t":"%s","payload_press":"{\"cmd\":\"snapshot\"}","avty_t":"%s","ic":"mdi:camera","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$snapshot_btn_topic" "$snapshot_btn_payload"

  update_cfg_topic="${discovery_prefix}/update/${node_id}/firmware/config"
  update_cfg_payload="$(printf '{"name":"%s Firmware","uniq_id":"%s_update","stat_t":"%s","val_tpl":"{{ value_json.update_status if value_json.update_status is defined else \"none\" }}","cmd_t":"%s","pl_inst":"{\"cmd\":\"update_install\"}","avty_t":"%s","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "${MQTT_TOPIC_ROOT}/update/state" "$cmd_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$update_cfg_topic" "$update_cfg_payload"

  profile_select_cfg_topic="${discovery_prefix}/select/${node_id}/profile/config"
  profile_select_cfg_payload="$(printf '{"name":"%s Profile Preset","uniq_id":"%s_profile_select","cmd_t":"%s","stat_t":"%s","options":["balanced","low-cpu","rtsp-only"],"val_tpl":"{{ value_json.perfprofile }}","cmd_tpl":"%s","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:tune-variant","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}' "$device_name_json" "$device_id_json" "$cmd_json" "$health_topic_json" "$cmd_profile_tpl_json" "$avail_topic_json" "$device_id_json" "$device_name_json")"
  publish_discovery_config "$profile_select_cfg_topic" "$profile_select_cfg_payload"
}

init_slow_health_defaults()
{
  slow_web_mode="full"
  slow_profile="balanced"
  slow_security_hardening_mode=0
  slow_network_monitor_enabled=0
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
  slow_network_monitor_enabled="$(service_script_running_int /mnt/controlscripts/network-monitor /var/run/network-monitor.pid)"
  slow_ftp_enabled="$(service_script_running_int /mnt/controlscripts/ftp-server /var/run/ftp-server.pid)"
  slow_telnet_enabled="$(service_script_running_int /mnt/controlscripts/telnet-server /var/run/telnet-server.pid)"
  slow_rtsp_enabled="$(service_script_running_int /mnt/controlscripts/rtsp-h26x /var/run/v4l2rtspserver.pid)"
  slow_onvif_enabled="$(service_script_running_int /mnt/controlscripts/onvif /var/run/onvif.pid)"

  slow_primary_ip="$(ifconfig 2>/dev/null | awk '
    /inet addr:[0-9]/{split($2,a,":");if(a[2]!~/^127\./){print a[2];exit}}
    /inet [0-9]/{if($2!~/^127\./){print $2;exit}}')"
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
  storage_used_percent="${storage_used_text%\%}"
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
  collect_port_states_from_netstat "$listen_tcp" "$http_port" "$rtsp_port" "$onvif_port" "$ftp_port" "$telnet_port"
}

save_slow_health_cache()
{
  [ "$BTIME" -gt 0 ] || _load_btime
  read -r _up _ < /proc/uptime
  now_ts=$((BTIME + ${_up%.*}))
  [ "$now_ts" -gt 0 ] || return 0
  {
    printf 'ts=%s\n' "$now_ts"
    printf 'web_mode=%s\n' "$slow_web_mode"
    printf 'profile=%s\n' "$slow_profile"
    printf 'security_hardening_mode=%s\n' "$slow_security_hardening_mode"
    printf 'network_monitor_enabled=%s\n' "$slow_network_monitor_enabled"
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
      network_monitor_enabled) slow_network_monitor_enabled="$value" ;;
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

  [ "$BTIME" -gt 0 ] || _load_btime
  read -r _up _ < /proc/uptime
  now_ts=$((BTIME + ${_up%.*}))
  [ "$cache_ts" -le "$now_ts" ] || return 1
  age=$((now_ts - cache_ts))
  [ "$age" -le "$MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS" ] || return 1

  case "$slow_security_hardening_mode" in ''|*[!0-9]*) slow_security_hardening_mode=0 ;; esac
  case "$slow_network_monitor_enabled" in ''|*[!0-9]*) slow_network_monitor_enabled=0 ;; esac
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

build_network_state_payload()
{
  network_wifi_iface_json="$(json_escape "$network_wifi_iface")"
  network_gateway_address_json="$(json_escape "$network_gateway_address")"
  network_broker_host_json="$(json_escape "$network_broker_host")"
  network_broker_state_json="$(json_escape "$network_broker_state")"
  network_current_problem_json="$(json_escape "$network_current_problem")"
  network_last_recovery_reason_json="$(json_escape "$network_last_recovery_reason")"
  network_last_recovery_action_json="$(json_escape "$network_last_recovery_action")"

  network_state_payload="$(printf '{"ts":%s,"hostname":"%s","monitor_enabled":%s,"state_fresh":%s,"wifi_iface":"%s","wifi_connected":%s,"gateway_address":"%s","gateway_reachable":%s,"broker_monitor_enabled":%s,"broker_host":"%s","broker_port":%s,"broker_state":"%s","broker_reachable":%s,"current_problem":"%s","reconnect_count":%s,"broker_restart_count":%s,"last_recovery_reason":"%s","last_recovery_action":"%s","last_recovery_ts":%s}' \
    "$now_ts" "$hostname_json" "$network_monitor_enabled" "$network_state_fresh" "$network_wifi_iface_json" "$network_wifi_connected" "$network_gateway_address_json" "$network_gateway_reachable" "$network_broker_monitor_enabled" "$network_broker_host_json" "$network_broker_port" "$network_broker_state_json" "$network_broker_reachable" "$network_current_problem_json" "$network_reconnect_count" "$network_broker_restart_count" "$network_last_recovery_reason_json" "$network_last_recovery_action_json" "$network_last_recovery_ts")"
}

build_health_payload()
{
  [ "$BTIME" -gt 0 ] || _load_btime
  read -r uptime_raw _ < /proc/uptime
  uptime_seconds="${uptime_raw%.*}"
  case "$uptime_seconds" in
    ''|*[!0-9]*) uptime_seconds=0 ;;
  esac
  now_ts=$((BTIME + uptime_seconds))
  [ "$now_ts" -gt 0 ] || now_ts=0
  reboot_epoch="$BTIME"

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
  network_monitor_enabled="$slow_network_monitor_enabled"
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

  read -r hostname_value < /proc/sys/kernel/hostname 2>/dev/null || hostname_value=""
  [ -n "$hostname_value" ] || hostname_value="TC100 Camera"
  hostname_json="$(json_escape "$hostname_value")"
  web_mode_json="$(json_escape "$web_mode")"
  profile_json="$(json_escape "$profile")"
  power_sensor_path_json="$(json_escape "$power_sensor_path")"
  primary_ip_json="$(json_escape "$primary_ip")"
  load_network_monitor_state >/dev/null 2>&1 || true
  build_network_state_payload

  printf '{"ts":%s,"hostname":"%s","uptime_seconds":%s,"reboot_epoch":%s,"cpu":%s,"ram_used_kb":%s,"ram_total_kb":%s,"ram_percent":%s,"chip_temp_c":%s,"power_estimate_enabled":%s,"power_estimated_mw":%s,"power_estimated_current_ma":%s,"power_voltage_mv":%s,"power_sensor_path":"%s","web_mode":"%s","perfprofile":"%s","security_hardening_mode":%s,"motion_active":%s,"motion_enabled":%s,"ftp_enabled":%s,"telnet_enabled":%s,"rtsp_enabled":%s,"onvif_enabled":%s,"front_led_on":%s,"red_led_on":%s,"ir_led_on":%s,"storage_total_mb":%s,"storage_used_mb":%s,"storage_avail_mb":%s,"storage_used_percent":%s,"primary_ip":"%s","dns_server_count":%s,"port_https_open":%s,"port_http_open":%s,"port_rtsp_open":%s,"port_onvif_open":%s,"port_ftp_open":%s,"port_telnet_open":%s,"network":%s}' \
    "$now_ts" "$hostname_json" "$uptime_seconds" "$reboot_epoch" "$cpu" "$mem_used" "$mem_total" "$ram_percent" "$chip_temp_json" "$power_estimated_enabled_json" "$power_estimated_mw_json" "$power_estimated_current_ma_json" "$power_voltage_mv_json" "$power_sensor_path_json" "$web_mode_json" "$profile_json" "$security_hardening_mode" "$motion_active" "$motion_enabled" "$ftp_enabled" "$telnet_enabled" "$rtsp_enabled" "$onvif_enabled" "$front_led_on" "$red_led_on" "$ir_led_on" "$storage_total_mb" "$storage_used_mb" "$storage_avail_mb" "$storage_used_percent" "$primary_ip_json" "$dns_server_count" "$port_https_open" "$port_http_open" "$port_rtsp_open" "$port_onvif_open" "$port_ftp_open" "$port_telnet_open" "$network_state_payload"
}

publish_health()
{
  payload="$(build_health_payload)"
  mqtt_publish_topic_suffix "health" "$payload" 0
  mqtt_publish_topic_suffix "motion/state" "$motion_state_payload" 1 >/dev/null 2>&1 || true
  mqtt_publish_topic_suffix "network/state" "$network_state_payload" 1 >/dev/null 2>&1 || true
}

publish_event_simple()
{
  event_type="$1"
  detail="$2"
  [ "$BTIME" -gt 0 ] || _load_btime
  read -r _up _ < /proc/uptime
  now_ts=$((BTIME + ${_up%.*}))
  event_json="$(json_escape "$event_type")"
  detail_json="$(json_escape "$detail")"
  payload=$(printf '{"ts":%s,"type":"%s","detail":"%s"}' "$now_ts" "$event_json" "$detail_json")
  mqtt_publish_topic_suffix "event" "$payload" 0
}

publish_command_result()
{
  result_command="$1"
  result_status="$2"
  result_detail="$3"
  result_ok="${4:-0}"
  result_source="${5:-mqtt}"
  result_class="${6:-command}"

  [ "$BTIME" -gt 0 ] || _load_btime
  read -r _up _ < /proc/uptime
  now_ts=$((BTIME + ${_up%.*}))

  result_command_json="$(json_escape "$result_command")"
  result_status_json="$(json_escape "$result_status")"
  result_detail_json="$(json_escape "$result_detail")"
  result_source_json="$(json_escape "$result_source")"
  result_class_json="$(json_escape "$result_class")"
  payload="$(printf '{"ts":%s,"command":"%s","status":"%s","detail":"%s","ok":%s,"source":"%s","class":"%s"}' \
    "$now_ts" "$result_command_json" "$result_status_json" "$result_detail_json" "$result_ok" "$result_source_json" "$result_class_json")"

  mqtt_publish_topic_suffix "command/result" "$payload" 0 >/dev/null 2>&1 || true
  mqtt_publish_topic_suffix "command/last_result" "$payload" 1 >/dev/null 2>&1 || true
  case "$result_class" in
    repair|recovery)
      mqtt_publish_topic_suffix "repair/last_result" "$payload" 1 >/dev/null 2>&1 || true
      ;;
  esac
}

dedupe_command()
{
  cmd_payload="$1"
  [ "$BTIME" -gt 0 ] || _load_btime
  read -r _up _ < /proc/uptime
  now_ts=$((BTIME + ${_up%.*}))
  _raw_hash="$(printf '%s' "$cmd_payload" | md5sum)"
  cmd_hash="${_raw_hash%% *}"

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

restart_service_script()
{
  script_path="$1"
  [ -x "$script_path" ] || return 1

  if "$script_path" restart >/dev/null 2>&1; then
    return 0
  fi

  "$script_path" stop >/dev/null 2>&1 || true
  sleep 1
  "$script_path" start >/dev/null 2>&1 || return 1
  return 0
}

queue_mqtt_bridge_restart()
{
  [ -x /mnt/controlscripts/mqtt-bridge ] || return 1
  (
    sleep 1
    /mnt/controlscripts/mqtt-bridge stop >/dev/null 2>&1 || true
    sleep 1
    /mnt/controlscripts/mqtt-bridge start >/dev/null 2>&1 || true
  ) >/dev/null 2>&1 &
  return 0
}

restart_named_service()
{
  service_name="$1"
  case "$service_name" in
    rtsp|rtsp_h26x|rtsp_server)
      service_script="/mnt/controlscripts/rtsp-h26x"
      ;;
    onvif)
      service_script="/mnt/controlscripts/onvif"
      ;;
    network_monitor|network)
      service_script="/mnt/controlscripts/network-monitor"
      ;;
    mqtt_bridge|mqtt)
      queue_mqtt_bridge_restart
      return $?
      ;;
    *)
      return 1
      ;;
  esac

  restart_service_script "$service_script"
}

REPAIR_INTEGRATION_SUMMARY=""

repair_integration_services()
{
  rtsp_ok=0
  onvif_expected=0
  onvif_ok=1
  manifest_ok=1
  selftest_ok=1

  if [ -x /mnt/controlscripts/rtsp-h26x ]; then
    if ! /mnt/controlscripts/rtsp-h26x health >/dev/null 2>&1; then
      restart_service_script /mnt/controlscripts/rtsp-h26x >/dev/null 2>&1 || true
      sleep 2
    fi
    if /mnt/controlscripts/rtsp-h26x health >/dev/null 2>&1; then
      rtsp_ok=1
    fi
  fi

  if [ -x /mnt/controlscripts/onvif ] && { [ -f /mnt/config/autostart/onvif ] || /mnt/controlscripts/onvif status >/dev/null 2>&1; }; then
    onvif_expected=1
    onvif_ok=0
    if ! /mnt/controlscripts/onvif health >/dev/null 2>&1; then
      restart_service_script /mnt/controlscripts/onvif >/dev/null 2>&1 || true
      sleep 2
    fi
    if /mnt/controlscripts/onvif health >/dev/null 2>&1; then
      onvif_ok=1
    fi
  fi

  publish_integration_manifest force >/dev/null 2>&1 || manifest_ok=0
  publish_integration_selftest >/dev/null 2>&1 || selftest_ok=0
  publish_homeassistant_discovery >/dev/null 2>&1 || true
  rm -f "$HEALTH_SLOW_CACHE_FILE" >/dev/null 2>&1 || true
  publish_health >/dev/null 2>&1 || true

  rtsp_result="fail"
  onvif_result="skipped"
  manifest_result="fail"
  selftest_result="fail"
  [ "$rtsp_ok" = "1" ] && rtsp_result="ok"
  [ "$manifest_ok" = "1" ] && manifest_result="ok"
  [ "$selftest_ok" = "1" ] && selftest_result="ok"
  if [ "$onvif_expected" = "1" ]; then
    [ "$onvif_ok" = "1" ] && onvif_result="ok" || onvif_result="fail"
  fi

  REPAIR_INTEGRATION_SUMMARY="rtsp=${rtsp_result},onvif=${onvif_result},manifest=${manifest_result},selftest=${selftest_result}"

  if [ "$rtsp_ok" = "1" ] && [ "$manifest_ok" = "1" ] && { [ "$onvif_expected" != "1" ] || [ "$onvif_ok" = "1" ]; }; then
    return 0
  fi
  return 1
}

handle_command_payload()
{
  command_source="${2:-mqtt}"
  payload_raw="$(printf '%s' "$1" | tr -d '\r')"
  payload_trimmed="$(printf '%s' "$payload_raw" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  [ -n "$payload_trimmed" ] || return 0

  if [ "$command_source" = "mqtt" ]; then
    if ! dedupe_command "$payload_trimmed"; then
      return 0
    fi
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
  command_rc=0

  case "$cmd" in
    reboot)
      publish_event_simple "command.reboot" "accepted"
      publish_command_result "reboot" "accepted" "Reboot requested." 1 "$command_source" command
      /sbin/reboot
      ;;
    snapshot)
      # Use a fixed path instead of timestamped to prevent /tmp RAM exhaustion
      shot_path="/tmp/mqtt-last-snapshot.jpg"
      if /mnt/bin/getimage > "$shot_path" 2>/dev/null; then
        shot_json="$(json_escape "$shot_path")"
        read -r _up _ < /proc/uptime
        now_ts=$((BTIME + ${_up%.*}))
        payload=$(printf '{"ts":%s,"type":"snapshot.manual","snapshot":"%s"}' "$now_ts" "$shot_json")
        mqtt_publish_topic_suffix "event" "$payload" 0
        mqtt_publish_topic_suffix "snapshot/last_path" "$shot_path" 1 >/dev/null 2>&1 || true
        publish_command_result "snapshot" "captured" "Captured a fresh snapshot to /tmp/mqtt-last-snapshot.jpg." 1 "$command_source" command
      else
        publish_event_simple "command.snapshot" "failed"
        publish_command_result "snapshot" "failed" "Snapshot capture failed." 0 "$command_source" command
        command_rc=1
      fi
      refresh_state=1
      ;;
    profile)
      if apply_profile_command "$value"; then
        publish_event_simple "command.profile" "$value"
        publish_command_result "profile" "applied" "Applied profile ${value}." 1 "$command_source" command
        refresh_state=1
      else
        publish_event_simple "command.profile" "invalid:$value"
        publish_command_result "profile" "invalid" "Unknown profile ${value}." 0 "$command_source" command
        command_rc=1
      fi
      ;;
    motion|motion_detection|ir_led|front_led|red_led|ftp|telnet|rtsp|onvif)
      if apply_toggle_command "$cmd" "$value"; then
        publish_event_simple "command.${cmd}" "${value:-toggle}"
        publish_command_result "$cmd" "applied" "Applied ${cmd}=${value:-toggle}." 1 "$command_source" command
        refresh_state=1
      else
        toggle_rc=$?
        case "$toggle_rc" in
          3)
            publish_event_simple "command.${cmd}" "blocked:security_hardening"
            publish_command_result "$cmd" "blocked" "Blocked by security hardening." 0 "$command_source" command
            ;;
          2)
            publish_event_simple "command.${cmd}" "invalid-value:${value}"
            publish_command_result "$cmd" "invalid_value" "Invalid value ${value}." 0 "$command_source" command
            ;;
          *)
            publish_event_simple "command.${cmd}" "failed:${value}"
            publish_command_result "$cmd" "failed" "Failed to apply ${cmd}=${value}." 0 "$command_source" command
            ;;
        esac
        command_rc=1
      fi
      ;;
    restart_rtsp|restart_onvif|restart_network_monitor|restart_mqtt_bridge)
      restart_target="${cmd#restart_}"
      if restart_named_service "$restart_target"; then
        case "$restart_target" in
          mqtt_bridge)
            publish_event_simple "command.${cmd}" "scheduled"
            publish_command_result "$cmd" "scheduled" "Scheduled MQTT bridge restart." 1 "$command_source" repair
            ;;
          *)
            publish_event_simple "command.${cmd}" "restarted"
            publish_command_result "$cmd" "restarted" "Restarted ${restart_target}." 1 "$command_source" repair
            refresh_state=1
            ;;
        esac
      else
        publish_event_simple "command.${cmd}" "failed"
        publish_command_result "$cmd" "failed" "Failed to restart ${restart_target}." 0 "$command_source" repair
        command_rc=1
      fi
      ;;
    repair_integration|integration_repair)
      if repair_integration_services; then
        publish_event_simple "command.repair_integration" "$REPAIR_INTEGRATION_SUMMARY"
        publish_command_result "repair_integration" "ok" "$REPAIR_INTEGRATION_SUMMARY" 1 "$command_source" repair
        refresh_state=1
      else
        publish_event_simple "command.repair_integration" "failed:${REPAIR_INTEGRATION_SUMMARY}"
        publish_command_result "repair_integration" "failed" "$REPAIR_INTEGRATION_SUMMARY" 0 "$command_source" repair
        command_rc=1
      fi
      ;;
    integration_selftest|selftest|integrationtest)
      if publish_integration_selftest; then
        publish_event_simple "command.integration_selftest" "published"
        publish_command_result "integration_selftest" "published" "Published the live integration self-test payload." 1 "$command_source" integration
      else
        publish_event_simple "command.integration_selftest" "failed"
        publish_command_result "integration_selftest" "failed" "Failed to publish the integration self-test payload." 0 "$command_source" integration
        command_rc=1
      fi
      ;;
    integration_manifest|manifest|manifest_refresh)
      if publish_integration_manifest force; then
        publish_event_simple "command.integration_manifest" "published"
        publish_command_result "integration_manifest" "published" "Published the redacted integration manifest." 1 "$command_source" integration
      else
        publish_event_simple "command.integration_manifest" "failed"
        publish_command_result "integration_manifest" "failed" "Failed to publish the integration manifest." 0 "$command_source" integration
        command_rc=1
      fi
      ;;
    discovery|ha_discovery|discovery_refresh)
      publish_integration_manifest force >/dev/null 2>&1 || true
      publish_homeassistant_discovery
      publish_event_simple "command.discovery" "published"
      publish_command_result "discovery" "published" "Published Home Assistant discovery payloads." 1 "$command_source" integration
      ;;
    health|health_now)
      publish_health >/dev/null 2>&1 || true
      publish_integration_manifest >/dev/null 2>&1 || true
      publish_event_simple "command.health" "published"
      publish_command_result "health" "published" "Published health and integration state." 1 "$command_source" integration
      ;;
    *)
      publish_event_simple "command.unknown" "$payload_trimmed"
      publish_command_result "unknown" "rejected" "Unsupported command payload: ${payload_trimmed}" 0 "$command_source" command
      command_rc=1
      ;;
  esac

  if [ "$refresh_state" -eq 1 ]; then
    rm -f "$HEALTH_SLOW_CACHE_FILE" >/dev/null 2>&1 || true
    publish_integration_manifest >/dev/null 2>&1 || true
    publish_health >/dev/null 2>&1 || true
  fi

  return "$command_rc"
}

subscribe_once_command()
{
  # Build URL inline — eliminates mqtt_url and curl_auth_args subshell forks.
  _sub_url="mqtt://${MQTT_HOST}:${MQTT_PORT}/${MQTT_TOPIC_COMMAND}?clientid=${MQTT_CLIENT_ID}-sub&qos=${MQTT_QOS}"
  if [ -n "$MQTT_USER" ]; then
    "$CURL_BIN" --silent --show-error --max-time "$MQTT_COMMAND_WAIT_SECONDS" \
      -u "${MQTT_USER}:${MQTT_PASSWORD}" "$_sub_url" 2>/dev/null
  else
    "$CURL_BIN" --silent --show-error --max-time "$MQTT_COMMAND_WAIT_SECONDS" \
      "$_sub_url" 2>/dev/null
  fi
}

stream_mode_enabled()
{
  is_truthy_local "$MQTT_STREAM_ENABLE"
}

stream_read_supported()
{
  # Stream mode needs a `read -t` that returns partial input on timeout, so a
  # payload published without a trailing newline is still delivered promptly.
  # Probe at runtime: the writer holds the pipe open past the timeout so the
  # read genuinely times out instead of seeing EOF. Costs ~2s once at startup.
  _srs_out="$( { printf 'PROBE'; sleep 2; } | { _srs_p=""; read -r -t 1 _srs_p 2>/dev/null; printf '%s' "$_srs_p"; } )"
  [ "$_srs_out" = "PROBE" ]
}

subscribe_stream_start()
{
  # Long-lived subscription: one connection per MQTT_STREAM_MAX_SECONDS instead
  # of one per MQTT_COMMAND_WAIT_SECONDS. --no-buffer makes curl flush each
  # PUBLISH payload to the FIFO as it arrives; --connect-timeout keeps failure
  # detection fast now that --max-time no longer bounds the connect phase.
  _ss_url="mqtt://${MQTT_HOST}:${MQTT_PORT}/${MQTT_TOPIC_COMMAND}?clientid=${MQTT_CLIENT_ID}-sub&qos=${MQTT_QOS}"
  if [ -n "$MQTT_USER" ]; then
    "$CURL_BIN" --silent --no-buffer --connect-timeout 10 \
      --max-time "$MQTT_STREAM_MAX_SECONDS" \
      -u "${MQTT_USER}:${MQTT_PASSWORD}" "$_ss_url" >"$STREAM_FIFO" 2>/dev/null &
  else
    "$CURL_BIN" --silent --no-buffer --connect-timeout 10 \
      --max-time "$MQTT_STREAM_MAX_SECONDS" "$_ss_url" >"$STREAM_FIFO" 2>/dev/null &
  fi
  stream_pid=$!
}

run_stream_loop()
{
  rm -f "$STREAM_FIFO" 2>/dev/null
  if ! mkfifo "$STREAM_FIFO" 2>/dev/null; then
    log_msg "mkfifo failed; staying on one-shot polling"
    return 1
  fi
  # Open read-write so the open never blocks and the fd never reports EOF;
  # curl death is detected with kill -0 on an idle tick instead.
  exec 3<>"$STREAM_FIFO"

  stream_failures=0
  stream_backoff_seconds="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS"
  last_health_ts=0

  while :; do
    read -r _up _ < /proc/uptime
    _sl_session_start_ts=$((BTIME + ${_up%.*}))

    subscribe_stream_start

    _sl_pending=""
    _sl_pending_ts=0
    while :; do
      read -r _up _ < /proc/uptime
      now_ts=$((BTIME + ${_up%.*}))

      if [ "$last_health_ts" -le 0 ] || [ $((now_ts - last_health_ts)) -ge "$MQTT_HEALTH_INTERVAL_SECONDS" ]; then
        publish_health >/dev/null 2>&1 || true
        publish_integration_manifest >/dev/null 2>&1 || true
        last_health_ts="$now_ts"
      fi

      _sl_line=""
      if read -r -t 1 _sl_line <&3; then
        _sl_got_eol=1
      else
        _sl_got_eol=0
      fi

      if [ -n "$_sl_line" ]; then
        if [ -n "$_sl_pending" ]; then
          _sl_pending="${_sl_pending} ${_sl_line}"
        else
          _sl_pending="$_sl_line"
          _sl_pending_ts="$now_ts"
        fi
      fi

      if [ -n "$_sl_pending" ]; then
        case "$_sl_pending" in
          '{'*'}'*)
            handle_command_payload "$_sl_pending" mqtt
            _sl_pending=""
            ;;
          '{'*)
            # JSON payload still open (pretty-printed, multi-line) — keep
            # accumulating, but never hold a torn payload longer than 5s.
            if [ $((now_ts - _sl_pending_ts)) -ge 5 ]; then
              handle_command_payload "$_sl_pending" mqtt
              _sl_pending=""
            fi
            ;;
          *)
            handle_command_payload "$_sl_pending" mqtt
            _sl_pending=""
            ;;
        esac
      fi

      if [ "$_sl_got_eol" -eq 0 ] && [ -z "$_sl_line" ]; then
        if ! kill -0 "$stream_pid" 2>/dev/null; then
          if [ -n "$_sl_pending" ]; then
            handle_command_payload "$_sl_pending" mqtt
            _sl_pending=""
          fi
          break
        fi
      fi
    done

    wait "$stream_pid" 2>/dev/null
    stream_pid=""

    read -r _up _ < /proc/uptime
    now_ts=$((BTIME + ${_up%.*}))
    _sl_lifetime=$((now_ts - _sl_session_start_ts))

    # A session that survived past the one-shot wait window counts as a healthy
    # connection (max-time expiry is the normal end of life); reconnect at once.
    if [ "$_sl_lifetime" -ge "$MQTT_COMMAND_WAIT_SECONDS" ]; then
      if [ "$stream_failures" -gt 0 ]; then
        log_msg "MQTT stream recovered after ${stream_failures} error(s)"
      fi
      stream_failures=0
      stream_backoff_seconds="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS"
      continue
    fi

    stream_failures=$((stream_failures + 1))
    if [ "$stream_failures" -eq 1 ] || [ $((stream_failures % 5)) -eq 0 ]; then
      log_msg "MQTT stream died after ${_sl_lifetime}s failures=${stream_failures} backoff=${stream_backoff_seconds}s"
      log_event "error" "mqtt" "MQTT stream failed (attempt ${stream_failures}, backoff ${stream_backoff_seconds}s)"
    fi

    _cb_thresh="${MQTT_CIRCUIT_BREAKER_THRESHOLD:-50}"
    case "$_cb_thresh" in ''|*[!0-9]*) _cb_thresh=50 ;; esac
    if [ "$stream_failures" -ge "$_cb_thresh" ]; then
      _cb_cooldown="${MQTT_CIRCUIT_BREAKER_COOLDOWN_SECONDS:-300}"
      case "$_cb_cooldown" in ''|*[!0-9]*) _cb_cooldown=300 ;; esac
      log_msg "MQTT circuit breaker tripped (${stream_failures} consecutive failures) — pausing ${_cb_cooldown}s"
      log_event "critical" "mqtt" "MQTT circuit breaker tripped after ${stream_failures} failures; cooling down ${_cb_cooldown}s"
      sleep "$_cb_cooldown"
      stream_failures=0
      stream_backoff_seconds="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS"
      continue
    fi

    sleep "$stream_backoff_seconds"
    if [ "$stream_backoff_seconds" -lt "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" ]; then
      stream_backoff_seconds=$((stream_backoff_seconds * MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER))
      if [ "$stream_backoff_seconds" -gt "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" ]; then
        stream_backoff_seconds="$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS"
      fi
    fi
  done
}

shutdown_bridge()
{
  if [ -n "$stream_pid" ] && kill -0 "$stream_pid" 2>/dev/null; then
    kill "$stream_pid" 2>/dev/null
  fi
  rm -f "$STREAM_FIFO" 2>/dev/null
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
  log_event "info" "mqtt" "MQTT bridge started"
  publish_availability online
  publish_integration_manifest force >/dev/null 2>&1 || true
  publish_homeassistant_discovery
  publish_event_simple "bridge.start" "online"

  if stream_mode_enabled; then
    if stream_read_supported; then
      log_msg "Persistent subscription enabled (one connection per ${MQTT_STREAM_MAX_SECONDS}s instead of per ${MQTT_COMMAND_WAIT_SECONDS}s poll)"
      run_stream_loop
      # run_stream_loop only returns if the FIFO could not be created —
      # fall through to the legacy one-shot polling loop.
    else
      log_msg "Shell read -t does not preserve partial input; using legacy one-shot polling"
    fi
  fi

  last_health_ts=0
  subscribe_failures=0
  subscribe_backoff_seconds="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS"
  while :; do
    read -r _up _ < /proc/uptime
    now_ts=$((BTIME + ${_up%.*}))

    if [ "$last_health_ts" -le 0 ] || [ $((now_ts - last_health_ts)) -ge "$MQTT_HEALTH_INTERVAL_SECONDS" ]; then
      publish_health >/dev/null 2>&1 || true
      publish_integration_manifest >/dev/null 2>&1 || true
      last_health_ts="$now_ts"
    fi

    cmd_payload="$(subscribe_once_command)"
    subscribe_rc=$?
    if [ "$subscribe_rc" -eq 0 ]; then
      if [ "$subscribe_failures" -gt 0 ]; then
        log_msg "MQTT subscribe recovered after ${subscribe_failures} error(s)"
      fi
      subscribe_failures=0
      subscribe_backoff_seconds="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS"
      if [ -n "$cmd_payload" ]; then
        handle_command_payload "$cmd_payload" mqtt
      fi
      sleep 1
      continue
    fi

    subscribe_failures=$((subscribe_failures + 1))
    if [ "$subscribe_failures" -eq 1 ] || [ $((subscribe_failures % 5)) -eq 0 ]; then
      log_msg "MQTT subscribe failed rc=${subscribe_rc} failures=${subscribe_failures} backoff=${subscribe_backoff_seconds}s"
      log_event "error" "mqtt" "MQTT subscribe failed (attempt ${subscribe_failures}, backoff ${subscribe_backoff_seconds}s)"
    fi

    # Circuit breaker: after too many consecutive failures, pause for an extended
    # cooldown before retrying.  This prevents hot-looping against a permanently
    # dead broker and gives the network/broker time to recover.
    _cb_thresh="${MQTT_CIRCUIT_BREAKER_THRESHOLD:-50}"
    case "$_cb_thresh" in ''|*[!0-9]*) _cb_thresh=50 ;; esac
    if [ "$subscribe_failures" -ge "$_cb_thresh" ]; then
      _cb_cooldown="${MQTT_CIRCUIT_BREAKER_COOLDOWN_SECONDS:-300}"
      case "$_cb_cooldown" in ''|*[!0-9]*) _cb_cooldown=300 ;; esac
      log_msg "MQTT circuit breaker tripped (${subscribe_failures} consecutive failures) — pausing ${_cb_cooldown}s"
      log_event "critical" "mqtt" "MQTT circuit breaker tripped after ${subscribe_failures} failures; cooling down ${_cb_cooldown}s"
      sleep "$_cb_cooldown"
      subscribe_failures=0
      subscribe_backoff_seconds="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS"
      continue
    fi

    sleep "$subscribe_backoff_seconds"
    if [ "$subscribe_backoff_seconds" -lt "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" ]; then
      subscribe_backoff_seconds=$((subscribe_backoff_seconds * MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER))
      if [ "$subscribe_backoff_seconds" -gt "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" ]; then
        subscribe_backoff_seconds="$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS"
      fi
    fi
  done
}

publish_mode()
{
  load_config
  if ! mqtt_enabled; then exit 0; fi
  while [ $# -ge 2 ]; do
    _pm_suffix="$1"; _pm_payload="$2"; _pm_retain="${3:-0}"
    mqtt_publish_topic_suffix "$_pm_suffix" "$_pm_payload" "$_pm_retain"
    shift 3 2>/dev/null || break
  done
}

command_mode()
{
  load_config
  [ "$BTIME" -gt 0 ] || _load_btime
  cmd_payload="$1"
  cmd_source="${2:-local}"
  [ -n "$cmd_payload" ] || exit 1
  handle_command_payload "$cmd_payload" "$cmd_source"
}

case "$1" in
  run|daemon|"")
    run_loop
    ;;
  publish)
    publish_mode "$2" "$3" "$4"
    ;;
  command)
    command_mode "$2" "$3"
    ;;
  *)
    echo "Usage: $0 [run|publish <topic_suffix> <payload> [retain]|command <payload> [source]]"
    exit 1
    ;;
esac
