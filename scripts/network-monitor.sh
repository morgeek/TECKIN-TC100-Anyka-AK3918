#!/bin/sh
[ -f /mnt/config/netmon.conf ] && . /mnt/config/netmon.conf

LOGPATH="/tmp/log/network_reboot.log"
STATE_FILE="/tmp/network-monitor.state"
MQTT_STATUS_FILE="/tmp/mqtt_last_pub.status"
MQTT_CONFIG_FILE="/mnt/config/mqtt.conf"

_NM_BTIME=0
_nm_now() {
  if [ "$_NM_BTIME" -le 0 ]; then
    while read -r _k _v _; do
      [ "$_k" = "btime" ] && _NM_BTIME="$_v" && break
    done < /proc/stat
  fi
  read -r _nm_up _ < /proc/uptime
  _nm_ts=$((_NM_BTIME + ${_nm_up%.*}))
  [ "$_nm_ts" -gt 0 ] || _nm_ts=0
}

ensure_log_dir() {
  [ -d /tmp/log ] || mkdir -p /tmp/log >/dev/null 2>&1 || true
}

sanitize_int_local() {
  value="$1"
  fallback="$2"
  case "$value" in
    ''|*[!0-9]*) value="$fallback" ;;
  esac
  printf '%s\n' "$value"
}

read_conf_value() {
  conf_file="$1"
  conf_key="$2"
  conf_default="$3"
  conf_value="$conf_default"

  if [ -r "$conf_file" ]; then
    while IFS= read -r line; do
      case "$line" in
        ''|'#'*) continue ;;
        "$conf_key"=*)
          conf_value="${line#*=}"
          break
          ;;
      esac
    done < "$conf_file"
  fi

  printf '%s\n' "$conf_value"
}

log_line() {
  _nm_now
  ensure_log_dir
  printf '@%s %s\n' "$_nm_ts" "$1" >> "$LOGPATH"
}

write_state() {
  _nm_now
  tmp_state="${STATE_FILE}.$$"
  {
    printf 'ts=%s\n' "$_nm_ts"
    printf 'wifi_iface=%s\n' "$WIFI_IFACE"
    printf 'wifi_connected=%s\n' "$wifi_connected"
    printf 'gateway_address=%s\n' "$PINGADDRESS"
    printf 'gateway_reachable=%s\n' "$gateway_reachable"
    printf 'broker_monitor_enabled=%s\n' "$broker_monitor_enabled"
    printf 'broker_host=%s\n' "$broker_host"
    printf 'broker_port=%s\n' "$broker_port"
    printf 'broker_state=%s\n' "$broker_state"
    printf 'broker_reachable=%s\n' "$broker_reachable"
    printf 'current_problem=%s\n' "$current_problem"
    printf 'reconnect_count=%s\n' "$reconnect_count"
    printf 'broker_restart_count=%s\n' "$broker_restart_count"
    printf 'last_recovery_reason=%s\n' "$last_recovery_reason"
    printf 'last_recovery_action=%s\n' "$last_recovery_action"
    printf 'last_recovery_ts=%s\n' "$last_recovery_ts"
    printf 'last_broker_restart_ts=%s\n' "$last_broker_restart_ts"
  } > "$tmp_state"
  mv "$tmp_state" "$STATE_FILE" 2>/dev/null || true
}

load_previous_state() {
  reconnect_count=0
  broker_restart_count=0
  last_recovery_reason="none"
  last_recovery_action="none"
  last_recovery_ts=0
  last_broker_restart_ts=0

  [ -r "$STATE_FILE" ] || return 0

  while IFS='=' read -r key value; do
    case "$key" in
      reconnect_count) reconnect_count="$(sanitize_int_local "$value" 0)" ;;
      broker_restart_count) broker_restart_count="$(sanitize_int_local "$value" 0)" ;;
      last_recovery_reason) [ -n "$value" ] && last_recovery_reason="$value" ;;
      last_recovery_action) [ -n "$value" ] && last_recovery_action="$value" ;;
      last_recovery_ts) last_recovery_ts="$(sanitize_int_local "$value" 0)" ;;
      last_broker_restart_ts) last_broker_restart_ts="$(sanitize_int_local "$value" 0)" ;;
    esac
  done < "$STATE_FILE"
}

record_recovery() {
  _nm_now
  last_recovery_reason="$1"
  last_recovery_action="$2"
  last_recovery_ts="$_nm_ts"
}

detect_wifi_connected() {
  ifconfig_data="$(/sbin/ifconfig "$WIFI_IFACE" 2>/dev/null)" || {
    printf '0\n'
    return
  }

  if [ -r "/sys/class/net/${WIFI_IFACE}/carrier" ]; then
    read -r wifi_carrier < "/sys/class/net/${WIFI_IFACE}/carrier"
    case "$wifi_carrier" in
      1)
        printf '1\n'
        return
        ;;
    esac
  fi

  case "$ifconfig_data" in
    *"inet addr:"*|*"inet "*|*RUNNING*)
      printf '1\n'
      ;;
    *)
      printf '0\n'
      ;;
  esac
}

check_gateway_connectivity() {
  ping -q -c "$PING_ATTEMPTS" -W "$PING_TIMEOUT_SECONDS" "$PINGADDRESS" >/dev/null 2>&1
}

check_gateway_reconnect() {
  ping -q -c "$RECHECK_ATTEMPTS" -W "$PING_TIMEOUT_SECONDS" "$PINGADDRESS" >/dev/null 2>&1
}

load_mqtt_runtime() {
  broker_monitor_enabled=0
  broker_host=""
  broker_port=1883

  mqtt_enable_value="$(read_conf_value "$MQTT_CONFIG_FILE" MQTT_ENABLE 0)"
  case "$mqtt_enable_value" in
    1|true|on|yes|enabled)
      broker_monitor_enabled=1
      ;;
  esac

  broker_host="$(read_conf_value "$MQTT_CONFIG_FILE" MQTT_HOST 127.0.0.1)"
  broker_port="$(sanitize_int_local "$(read_conf_value "$MQTT_CONFIG_FILE" MQTT_PORT 1883)" 1883)"
  if [ "$broker_port" -lt 1 ] || [ "$broker_port" -gt 65535 ]; then
    broker_port=1883
  fi
}

read_broker_status() {
  broker_state="disabled"
  broker_reachable=0

  if [ "$broker_monitor_enabled" != "1" ]; then
    return 0
  fi

  broker_state="unknown"
  [ -r "$MQTT_STATUS_FILE" ] || return 0

  read -r broker_status_ts broker_status_result < "$MQTT_STATUS_FILE"
  broker_status_ts="$(sanitize_int_local "$broker_status_ts" 0)"
  _nm_now
  if [ "$broker_status_ts" -gt 0 ]; then
    broker_status_age=$((_nm_ts - broker_status_ts))
  else
    broker_status_age=-1
  fi

  if [ "$broker_status_age" -lt 0 ] || [ "$broker_status_age" -gt "$BROKER_CHECK_MAX_AGE_SECONDS" ]; then
    broker_state="stale"
    broker_reachable=0
    return 0
  fi

  case "$broker_status_result" in
    ok)
      broker_state="ok"
      broker_reachable=1
      ;;
    fail)
      broker_state="fail"
      broker_reachable=0
      ;;
    *)
      broker_state="unknown"
      broker_reachable=0
      ;;
  esac
}

assess_current_state() {
  load_mqtt_runtime
  wifi_connected="$(detect_wifi_connected)"

  gateway_reachable=0
  if [ "$wifi_connected" = "1" ] && check_gateway_connectivity; then
    gateway_reachable=1
  fi

  read_broker_status

  current_problem="ok"
  if [ "$wifi_connected" != "1" ]; then
    current_problem="wifi_disconnected"
  elif [ "$gateway_reachable" != "1" ]; then
    current_problem="gateway_unreachable"
  elif [ "$broker_monitor_enabled" = "1" ] && [ "$broker_state" = "fail" ]; then
    current_problem="broker_unreachable"
  fi
}

bounce_wifi_interface() {
  /sbin/ifconfig "$WIFI_IFACE" down >/dev/null 2>&1 || true
  sleep "$RECONNECT_WAIT_SECONDS"
  /sbin/ifconfig "$WIFI_IFACE" up >/dev/null 2>&1 || true
  sleep "$RECHECK_WAIT_SECONDS"
}

restart_mqtt_bridge_recovery() {
  [ "$broker_monitor_enabled" = "1" ] || return 1
  [ "$BROKER_RECOVERY_RESTART_MQTT" = "1" ] || return 1
  [ -x /mnt/controlscripts/mqtt-bridge ] || return 1

  _nm_now
  broker_restart_age=$((_nm_ts - last_broker_restart_ts))
  if [ "$last_broker_restart_ts" -gt 0 ] && [ "$broker_restart_age" -ge 0 ] && [ "$broker_restart_age" -lt "$BROKER_RECOVERY_COOLDOWN_SECONDS" ]; then
    return 1
  fi

  record_recovery "broker_unreachable" "restart_mqtt_bridge"
  last_broker_restart_ts="$last_recovery_ts"
  broker_restart_count=$((broker_restart_count + 1))
  log_line "Broker appears unreachable, restarting MQTT bridge..."
  write_state
  /mnt/controlscripts/mqtt-bridge stop >/dev/null 2>&1 || true
  sleep 1
  /mnt/controlscripts/mqtt-bridge start >/dev/null 2>&1 || true
  return 0
}

recovery_validation_ready() {
  [ "$current_problem" = "ok" ] || return 1
  if [ "$broker_monitor_enabled" = "1" ] && [ "$broker_reachable" != "1" ]; then
    return 1
  fi
  return 0
}

run_post_recovery_validation() {
  validation_reason="$1"
  [ -n "$validation_reason" ] || return 1

  if [ ! -x /mnt/scripts/mqtt-bridge.sh ]; then
    log_line "Post-recovery integration validation skipped after ${validation_reason}: mqtt-bridge.sh missing."
    return 1
  fi

  if [ "$POST_RECOVERY_VALIDATE_DELAY_SECONDS" -gt 0 ]; then
    sleep "$POST_RECOVERY_VALIDATE_DELAY_SECONDS"
  fi

  log_line "Network recovered after ${validation_reason}; running integration repair validation..."
  if /mnt/scripts/mqtt-bridge.sh command repair_integration network_recovery >/dev/null 2>&1; then
    log_line "Post-recovery integration validation succeeded after ${validation_reason}."
    return 0
  fi

  log_line "Post-recovery integration validation failed after ${validation_reason}."
  return 1
}

: "${WIFI_IFACE:=wlan0}"
: "${PINGADDRESS:=192.168.0.1}"
: "${PINGINTERVAL:=120}"
: "${PING_ATTEMPTS:=1}"
: "${PING_TIMEOUT_SECONDS:=1}"
: "${RECONNECT_WAIT_SECONDS:=10}"
: "${RECHECK_WAIT_SECONDS:=20}"
: "${RECHECK_ATTEMPTS:=1}"
: "${REBOOT_DELAY_SECONDS:=3}"
: "${BROKER_CHECK_MAX_AGE_SECONDS:=300}"
: "${BROKER_RECOVERY_RESTART_MQTT:=1}"
: "${BROKER_RECOVERY_COOLDOWN_SECONDS:=180}"
: "${POST_RECOVERY_VALIDATE_DELAY_SECONDS:=5}"

PINGINTERVAL="$(sanitize_int_local "$PINGINTERVAL" 120)"
PING_ATTEMPTS="$(sanitize_int_local "$PING_ATTEMPTS" 1)"
PING_TIMEOUT_SECONDS="$(sanitize_int_local "$PING_TIMEOUT_SECONDS" 1)"
RECONNECT_WAIT_SECONDS="$(sanitize_int_local "$RECONNECT_WAIT_SECONDS" 10)"
RECHECK_WAIT_SECONDS="$(sanitize_int_local "$RECHECK_WAIT_SECONDS" 20)"
RECHECK_ATTEMPTS="$(sanitize_int_local "$RECHECK_ATTEMPTS" 1)"
REBOOT_DELAY_SECONDS="$(sanitize_int_local "$REBOOT_DELAY_SECONDS" 3)"
BROKER_CHECK_MAX_AGE_SECONDS="$(sanitize_int_local "$BROKER_CHECK_MAX_AGE_SECONDS" 300)"
BROKER_RECOVERY_COOLDOWN_SECONDS="$(sanitize_int_local "$BROKER_RECOVERY_COOLDOWN_SECONDS" 180)"
POST_RECOVERY_VALIDATE_DELAY_SECONDS="$(sanitize_int_local "$POST_RECOVERY_VALIDATE_DELAY_SECONDS" 5)"

[ "$PINGINTERVAL" -lt 5 ] && PINGINTERVAL=5
[ "$PING_ATTEMPTS" -lt 1 ] && PING_ATTEMPTS=1
[ "$PING_TIMEOUT_SECONDS" -lt 1 ] && PING_TIMEOUT_SECONDS=1
[ "$RECONNECT_WAIT_SECONDS" -lt 1 ] && RECONNECT_WAIT_SECONDS=1
[ "$RECHECK_WAIT_SECONDS" -lt 1 ] && RECHECK_WAIT_SECONDS=1
[ "$RECHECK_ATTEMPTS" -lt 1 ] && RECHECK_ATTEMPTS=1
[ "$REBOOT_DELAY_SECONDS" -lt 1 ] && REBOOT_DELAY_SECONDS=1
[ "$BROKER_CHECK_MAX_AGE_SECONDS" -lt 10 ] && BROKER_CHECK_MAX_AGE_SECONDS=10
[ "$BROKER_RECOVERY_COOLDOWN_SECONDS" -lt 10 ] && BROKER_RECOVERY_COOLDOWN_SECONDS=10

case "$BROKER_RECOVERY_RESTART_MQTT" in
  1|true|on|yes|enabled)
    BROKER_RECOVERY_RESTART_MQTT=1
    ;;
  *)
    BROKER_RECOVERY_RESTART_MQTT=0
    ;;
esac

load_previous_state
pending_validation_reason=""

while true
do
  assess_current_state
  write_state

  case "$current_problem" in
    ok)
      ;;
    broker_unreachable)
      if restart_mqtt_bridge_recovery; then
        pending_validation_reason="broker_unreachable"
      fi
      ;;
    wifi_disconnected|gateway_unreachable)
      recovery_reason="$current_problem"
      reconnect_count=$((reconnect_count + 1))
      record_recovery "$current_problem" "bounce_wifi"
      log_line "Network issue (${current_problem}), trying to reconnect..."
      write_state
      bounce_wifi_interface
      assess_current_state
      write_state

      case "$current_problem" in
        ok)
          log_line "Network connectivity recovered after ${WIFI_IFACE} reset."
          pending_validation_reason="$recovery_reason"
          ;;
        broker_unreachable)
          log_line "Gateway recovered after ${WIFI_IFACE} reset; broker still unreachable."
          if restart_mqtt_bridge_recovery; then
            pending_validation_reason="broker_unreachable"
          fi
          ;;
        *)
          record_recovery "$current_problem" "reboot"
          log_line "Network reconnection failed (${current_problem}), reboot..."
          write_state
          sleep "$REBOOT_DELAY_SECONDS"
          /sbin/reboot
          ;;
      esac
      ;;
  esac

  if [ -n "$pending_validation_reason" ] && recovery_validation_ready; then
    validation_reason="$pending_validation_reason"
    pending_validation_reason=""
    run_post_recovery_validation "$validation_reason" || true
    assess_current_state
    write_state
  fi

  sleep "$PINGINTERVAL"
done
