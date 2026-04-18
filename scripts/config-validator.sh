#!/bin/sh
# config-validator.sh — Validate key config values at boot time.
# Called from autorun.sh after configs are installed.
# Logs errors to /tmp/log/config-validator.log; exits 0 always (non-fatal).

LOGPATH="/tmp/log/config-validator.log"
CONFIGPATH="/mnt/config"
_errors=0

_log() {
  [ -d /tmp/log ] || mkdir -p /tmp/log 2>/dev/null || true
  printf '%s\n' "$1" >> "$LOGPATH"
  printf '%s\n' "$1" >&2
}

_err() {
  _log "CONFIG ERROR: $1"
  _errors=$((_errors + 1))
}

_warn() {
  _log "CONFIG WARN:  $1"
}

# Check that a variable is a non-empty integer in [min, max].
check_int() {
  _ci_name="$1"; _ci_val="$2"; _ci_min="$3"; _ci_max="$4"
  case "$_ci_val" in
    ''|*[!0-9]*)
      _err "$_ci_name='${_ci_val}' is not a valid integer (expected ${_ci_min}–${_ci_max})"
      return 1 ;;
  esac
  if [ "$_ci_val" -lt "$_ci_min" ] || [ "$_ci_val" -gt "$_ci_max" ]; then
    _err "$_ci_name=${_ci_val} out of range (expected ${_ci_min}–${_ci_max})"
    return 1
  fi
  return 0
}

# Check that a variable is one of a set of allowed values.
check_enum() {
  _ce_name="$1"; _ce_val="$2"; shift 2
  for _ce_allowed in "$@"; do
    [ "$_ce_val" = "$_ce_allowed" ] && return 0
  done
  _err "$_ce_name='${_ce_val}' is not valid (allowed: $*)"
}

_log "=== config-validator start ==="

# ── boot.conf ──────────────────────────────────────────────────────────────
if [ -f "$CONFIGPATH/boot.conf" ]; then
  # shellcheck disable=SC1090
  . "$CONFIGPATH/boot.conf"

  check_enum  "WEB_MODE"                    "${WEB_MODE:-full}"         full http ultra-lite
  check_int   "REBOOT_SCHEDULE_HOUR"        "${REBOOT_SCHEDULE_HOUR:-3}"        0  23
  check_int   "STORAGE_CLEANUP_THRESHOLD"   "${STORAGE_CLEANUP_THRESHOLD:-90}"  1  99
  check_int   "STORAGE_CLEANUP_TARGET"      "${STORAGE_CLEANUP_TARGET:-85}"     1  99
  check_int   "MEM_GUARD_WARN_KB"           "${MEM_GUARD_WARN_KB:-8192}"        512 131072
  check_int   "MEM_GUARD_CRITICAL_KB"       "${MEM_GUARD_CRITICAL_KB:-4096}"    256 131072
  check_int   "MEM_GUARD_EMERGENCY_KB"      "${MEM_GUARD_EMERGENCY_KB:-2048}"   128 131072
  check_int   "MEM_GUARD_INTERVAL_SECONDS"  "${MEM_GUARD_INTERVAL_SECONDS:-20}" 5   3600
  check_int   "CHECK_TIMEOUT_SECONDS"       "${CHECK_TIMEOUT_SECONDS:-60}"      5   600

  # Threshold ordering sanity
  _warn_kb="${MEM_GUARD_WARN_KB:-8192}"; _crit_kb="${MEM_GUARD_CRITICAL_KB:-4096}"
  _emrg_kb="${MEM_GUARD_EMERGENCY_KB:-2048}"
  case "$_warn_kb$_crit_kb$_emrg_kb" in *[!0-9]*) : ;; *)
    [ "$_warn_kb" -gt "$_crit_kb" ] || _warn "MEM_GUARD_WARN_KB (${_warn_kb}) should be > MEM_GUARD_CRITICAL_KB (${_crit_kb})"
    [ "$_crit_kb" -gt "$_emrg_kb" ] || _warn "MEM_GUARD_CRITICAL_KB (${_crit_kb}) should be > MEM_GUARD_EMERGENCY_KB (${_emrg_kb})"
  esac

  _sc_thr="${STORAGE_CLEANUP_THRESHOLD:-90}"; _sc_tgt="${STORAGE_CLEANUP_TARGET:-85}"
  case "$_sc_thr$_sc_tgt" in *[!0-9]*) : ;; *)
    [ "$_sc_thr" -gt "$_sc_tgt" ] || _warn "STORAGE_CLEANUP_THRESHOLD (${_sc_thr}) should be > STORAGE_CLEANUP_TARGET (${_sc_tgt})"
  esac
else
  _warn "boot.conf not found — using defaults"
fi

# ── mqtt.conf ───────────────────────────────────────────────────────────────
if [ -f "$CONFIGPATH/mqtt.conf" ]; then
  . "$CONFIGPATH/mqtt.conf"
  check_int "MQTT_PORT"                        "${MQTT_PORT:-1883}"                    1  65535
  check_int "MQTT_QOS"                         "${MQTT_QOS:-0}"                        0  2
  check_int "MQTT_HEALTH_INTERVAL_SECONDS"     "${MQTT_HEALTH_INTERVAL_SECONDS:-120}"  10 86400
  check_int "MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" "${MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS:-20}" 1 3600
fi

# ── netmon.conf ─────────────────────────────────────────────────────────────
if [ -f "$CONFIGPATH/netmon.conf" ]; then
  . "$CONFIGPATH/netmon.conf"
  check_int "PINGINTERVAL"           "${PINGINTERVAL:-120}"    5  86400
  check_int "PING_TIMEOUT_SECONDS"   "${PING_TIMEOUT_SECONDS:-1}" 1 30
  check_int "RECONNECT_WAIT_SECONDS" "${RECONNECT_WAIT_SECONDS:-10}" 1 300
fi

# ── rtspserver.conf (basic numeric check via rwconf) ────────────────────────
if [ -x /mnt/bin/rwconf ] && [ -f "$CONFIGPATH/rtspserver.conf" ]; then
  _rtsp_port="$(/mnt/bin/rwconf "$CONFIGPATH/rtspserver.conf" r " " PORT 2>/dev/null)"
  case "$_rtsp_port" in
    ''|*[!0-9]*) _warn "rtspserver.conf: PORT='${_rtsp_port}' is not numeric" ;;
    *) [ "$_rtsp_port" -ge 1 ] && [ "$_rtsp_port" -le 65535 ] || \
       _err "rtspserver.conf: PORT=${_rtsp_port} out of range (1–65535)" ;;
  esac
fi

_log "=== config-validator done: ${_errors} error(s) ==="
# Always exit 0 — validation is advisory, not fatal.
exit 0
