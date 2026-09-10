#!/bin/sh
# conf-import.cgi — validate and apply a tc100-boot-mqtt-export v1 file.
# POST: raw text body (Content-Type: text/plain), X-CSRF-Token header required.
# Returns JSON: {"ok":true,"applied":N,"skipped":N} or {"ok":false,"error":"..."}

CONFIG_ROOT="${TC_CONFIG_ROOT:-/mnt/config}"
if [ -r "${CONFIG_TX_LIB:-/mnt/scripts/config-transaction.sh}" ]; then
    . "${CONFIG_TX_LIB:-/mnt/scripts/config-transaction.sh}"
elif [ -r ../../scripts/config-transaction.sh ]; then
    . ../../scripts/config-transaction.sh
else
    printf 'Content-Type: application/json\r\n\r\n'
    printf '{"ok":false,"error":"validator_unavailable"}\n'
    exit 0
fi
BOOT_SOURCE="$CONFIG_ROOT/boot.conf"
MQTT_SOURCE="$CONFIG_ROOT/mqtt.conf"
BOOT_CONF_DIST="$CONFIG_ROOT/boot.conf.dist"
MQTT_CONF_DIST="$CONFIG_ROOT/mqtt.conf.dist"

printf 'Content-Type: application/json\r\n'
printf '\r\n'

# ── CSRF check ────────────────────────────────────────────────────────────────
# awk, not tr: this CGI sources neither func.cgi nor common_functions.sh, so it
# has no tr() shim. A bare `tr` exits 127 on the camera and yields "" — which
# here would collapse both sides of the comparison and BYPASS the CSRF check.
_csrf_stored=""
if [ -r /tmp/csrf_token ]; then
    read -r _csrf_stored < /tmp/csrf_token
    _csrf_stored="$(printf '%s' "$_csrf_stored" | awk '{ gsub(/[^0-9a-fA-F]/, ""); print }')"
fi
if [ -n "$_csrf_stored" ]; then
    _csrf_hdr="$(printf '%s' "${HTTP_X_CSRF_TOKEN:-}" | awk '{ gsub(/[^0-9a-fA-F]/, ""); print }')"
    if [ "$_csrf_hdr" != "$_csrf_stored" ]; then
        printf '{"ok":false,"error":"csrf_invalid","message":"CSRF token invalid — reload the page."}\n'
        exit 0
    fi
fi

if [ "${REQUEST_METHOD:-GET}" != "POST" ]; then
    printf '{"ok":false,"error":"post_required"}\n'
    exit 0
fi

# ── Read raw POST body (max 128 KB) ─────────────────────────────────────────
_cl="${CONTENT_LENGTH:-0}"
case "$_cl" in ''|*[!0-9]*) _cl=0 ;; esac
if [ "$_cl" -le 0 ] || [ "$_cl" -gt 131072 ]; then
    printf '{"ok":false,"error":"invalid_size","message":"Import must be between 1 byte and 128 KB."}\n'
    exit 0
fi

_tmp="/tmp/conf_import_$$.txt"
_raw="/tmp/conf_import_$$.raw"
head -c "$_cl" > "$_raw" 2>/dev/null
_got="$(wc -c < "$_raw" 2>/dev/null)"
set -- $_got; _got="${1:-0}"
if [ "$_got" != "$_cl" ]; then
    rm -f "$_tmp" "$_raw"
    printf '{"ok":false,"error":"incomplete_payload"}\n'
    exit 0
fi
awk '{ gsub(/\r/, ""); print }' "$_raw" > "$_tmp"
rm -f "$_raw"

# ── Validate magic header ────────────────────────────────────────────────────
if ! grep -q '^## tc100-boot-mqtt-export v1' "$_tmp" 2>/dev/null; then
    rm -f "$_tmp"
    printf '{"ok":false,"error":"invalid_format","message":"Not a valid TC100 config export file. Export from this camera first."}\n'
    exit 0
fi

# ── Prepare isolated copies; active files remain untouched until commit ───────
_stage="/tmp/conf-import-stage.$$"
_backup="/tmp/conf-import-rollback.$$"
rm -rf "$_stage" "$_backup"
mkdir -p "$_stage" || { rm -f "$_tmp"; printf '{"ok":false,"error":"staging_failed"}\n'; exit 0; }
if [ -f "$BOOT_SOURCE" ]; then cp "$BOOT_SOURCE" "$_stage/boot.conf"; else cp "$BOOT_CONF_DIST" "$_stage/boot.conf" 2>/dev/null; fi
if [ -f "$MQTT_SOURCE" ]; then cp "$MQTT_SOURCE" "$_stage/mqtt.conf"; else cp "$MQTT_CONF_DIST" "$_stage/mqtt.conf" 2>/dev/null; fi
BOOT_CONF="$_stage/boot.conf"
MQTT_CONF="$_stage/mqtt.conf"
if [ ! -f "$BOOT_CONF" ] || [ ! -f "$MQTT_CONF" ]; then
    rm -rf "$_tmp" "$_stage" "$_backup"
    printf '{"ok":false,"error":"config_not_found","message":"Cannot locate boot.conf or mqtt.conf on SD card."}\n'
    exit 0
fi

set_conf() { tc_set_flat "$3" "$1" "$2"; }

validate_legacy_value() {
    _vl_key="$1"; _vl_raw="$2"
    case "$_vl_raw" in *'\'*|*'`'*|*'$'*|*';'*|*'&'*|*'|'*|*'<'*|*'>'*) return 1 ;; esac
    case "$_vl_raw" in
      \"*\") ;;
      \'*\') ;;
      *' '*) return 1 ;;
    esac
    tc_strip_quotes "$_vl_raw"
    _vl_value="$TC_UNQUOTED_VALUE"
    case "$_vl_key" in
      WEB_MODE) _vl_type=web_mode ;;
      ONVIF_STREAM_POLICY) _vl_type=onvif_policy ;;
      MQTT_PORT|ULTRALITE_HTTP_PORT|SYSLOG_PORT) _vl_type=port ;;
      MQTT_QOS) _vl_type=qos ;;
      REBOOT_SCHEDULE_HOUR|MOTION_ARM_HOUR|MOTION_DISARM_HOUR) _vl_type=hour ;;
      REBOOT_SCHEDULE_MINUTE|MOTION_ARM_MINUTE|MOTION_DISARM_MINUTE) _vl_type=minute ;;
      REBOOT_SCHEDULE_WEEKDAY|MOTION_SCHEDULE_WEEKDAY) _vl_type=weekday ;;
      LOW_CPU_MAIN_WIDTH|LOW_CPU_SUB_WIDTH|CPU_SCALER_D1_WIDTH) _vl_type=width ;;
      LOW_CPU_MAIN_HEIGHT|LOW_CPU_SUB_HEIGHT|CPU_SCALER_D1_HEIGHT) _vl_type=height ;;
      LOW_CPU_MAIN_FPS|LOW_CPU_SUB_FPS|CPU_SCALER_FPS_TARGET) _vl_type=fps ;;
      LOW_CPU_MAIN_BPS|LOW_CPU_SUB_BPS|LOW_CPU_MAIN_MAXKBPS|LOW_CPU_SUB_MAXKBPS|LOW_CPU_MAIN_TARGETKBPS|LOW_CPU_SUB_TARGETKBPS) _vl_type=bitrate ;;
      LOW_CPU_MAIN_GOPLEN|LOW_CPU_SUB_GOPLEN) _vl_type=gop ;;
      MQTT_HOST|SYSLOG_HOST) _vl_type=host ;;
      MQTT_TOPIC_ROOT|MQTT_TOPIC_COMMAND|MQTT_HA_DISCOVERY_PREFIX) _vl_type=topic ;;
      MQTT_CLIENT_ID) _vl_type=identifier ;;
      ENABLE_*|*_ENABLE|LOW_CPU_DISABLE_*|RTSP_SUBSTREAM|RTSP_AUDIO|MEM_GUARD_DROP_CACHES|RTSP_DEEP_HEALTH_CHECK|NTP_ONE_SHOT|LIGHTWEIGHT_MODE|UI_ULTRALITE_MODE|SECURITY_HARDENING_MODE|LOW_CPU_PROFILE) _vl_type=bool ;;
      *) _vl_type=safe_text_optional ;;
    esac
    tc_normalize_and_validate "$_vl_type" "$_vl_value"
}

# ── Allowlists ────────────────────────────────────────────────────────────────
BOOT_KEYS=" LIGHTWEIGHT_MODE ENABLE_WATCHDOG ENABLE_NTP NTP_ONE_SHOT \
ENABLE_CROND ENABLE_AUTOSTART \
REBOOT_SCHEDULE_ENABLE REBOOT_SCHEDULE_MINUTE REBOOT_SCHEDULE_HOUR REBOOT_SCHEDULE_WEEKDAY \
MOTION_SCHEDULE_ENABLE MOTION_ARM_MINUTE MOTION_ARM_HOUR MOTION_DISARM_MINUTE \
MOTION_DISARM_HOUR MOTION_SCHEDULE_WEEKDAY \
WEB_MODE ULTRALITE_HTTP_PORT UI_ULTRALITE_MODE SECURITY_HARDENING_MODE \
LOW_CPU_PROFILE LOW_CPU_DISABLE_SUBSTREAM LOW_CPU_DISABLE_AUDIO \
LOW_CPU_DISABLE_MOTION LOW_CPU_DISABLE_OSD LOW_CPU_DISABLE_JPEG \
LOW_CPU_MAIN_WIDTH LOW_CPU_MAIN_HEIGHT LOW_CPU_MAIN_FPS LOW_CPU_MAIN_BPS \
LOW_CPU_MAIN_GOPLEN LOW_CPU_MAIN_MAXKBPS LOW_CPU_MAIN_TARGETKBPS \
LOW_CPU_SUB_WIDTH LOW_CPU_SUB_HEIGHT LOW_CPU_SUB_FPS LOW_CPU_SUB_BPS \
LOW_CPU_SUB_GOPLEN LOW_CPU_SUB_MAXKBPS LOW_CPU_SUB_TARGETKBPS \
MEM_GUARD_ENABLE MEM_GUARD_INTERVAL_SECONDS MEM_GUARD_WARN_KB \
MEM_GUARD_CRITICAL_KB MEM_GUARD_EMERGENCY_KB MEM_GUARD_COOLDOWN_SECONDS \
MEM_GUARD_DROP_CACHES MEM_GUARD_SOFT_SERVICES MEM_GUARD_CRITICAL_SERVICES \
MEM_GUARD_EMERGENCY_SERVICES MEM_WATCHDOG_ENABLE MEM_WATCHDOG_INTERVAL_SECONDS \
MEM_WATCHDOG_MAX_RETRIES MEM_WATCHDOG_SERVICES \
CPU_SCALER_ENABLE CPU_SCALER_INTERVAL_SECONDS CPU_SCALER_THRESHOLD_PERCENT \
CPU_SCALER_HOLD_TIME_SECONDS CPU_SCALER_FPS_TARGET CPU_SCALER_D1_WIDTH CPU_SCALER_D1_HEIGHT \
AUTOSTART_ALLOWLIST AUTOSTART_DENYLIST RTSP_SUBSTREAM RTSP_AUDIO ONVIF_STREAM_POLICY \
RTSP_HEALTHCHECK_TIMEOUT_SECONDS ONVIF_HEALTHCHECK_TIMEOUT_SECONDS \
ONVIF_STARTUP_GRACE_SECONDS ONVIF_HEALTHCHECK_RETRIES ONVIF_RTSP_DEPENDENCY_MODE \
CHECK_TIMEOUT_SECONDS RTSP_WATCHDOG_MODE ONVIF_WATCHDOG_MODE \
RTSP_DEEP_HEALTH_CHECK RTSP_GOP_STALL_THRESHOLD_SECONDS \
WATCHDOG_LOG_MAX_BYTES WATCHDOG_LOG_BACKUPS \
WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS \
WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS CHIP_TEMP_SOURCE_PATH CHIP_TEMP_RAW_DIVISOR \
STORAGE_CLEANUP_ENABLE STORAGE_CLEANUP_THRESHOLD STORAGE_CLEANUP_TARGET \
STORAGE_CLEANUP_DCIM_PATH HEALTH_SNAPSHOT_INTERVAL_SECONDS \
SYSLOG_ENABLE SYSLOG_HOST SYSLOG_PORT INTEGRATION_PROFILE "

MQTT_KEYS=" MQTT_ENABLE MQTT_HOST MQTT_PORT MQTT_USER MQTT_PASSWORD \
MQTT_CLIENT_ID MQTT_TOPIC_ROOT MQTT_TOPIC_COMMAND MQTT_QOS \
MQTT_HEALTH_INTERVAL_SECONDS MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS \
MQTT_COMMAND_WAIT_SECONDS MQTT_COMMAND_REPEAT_WINDOW_SECONDS \
MQTT_STREAM_ENABLE MQTT_STREAM_MAX_SECONDS \
MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS \
MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER \
MQTT_CIRCUIT_BREAKER_THRESHOLD MQTT_CIRCUIT_BREAKER_COOLDOWN_SECONDS \
MQTT_HA_DISCOVERY_ENABLE MQTT_HA_DISCOVERY_PREFIX \
POWER_ESTIMATE_ENABLE POWER_ESTIMATE_BASE_MW POWER_ESTIMATE_CPU_SCALE_MW \
POWER_ESTIMATE_IR_LED_MW POWER_SENSOR_PATH "

in_list() {  # in_list KEY LIST — returns 0 if KEY is in the space-delimited LIST
    case "$2" in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# ── Parse and apply ───────────────────────────────────────────────────────────
_section=""
_applied=0
_skipped=0

while IFS= read -r _line; do
    case "$_line" in
        '##[SECTION:boot.conf]##') _section="boot"; continue ;;
        '##[SECTION:mqtt.conf]##') _section="mqtt"; continue ;;
        '##'*|'#'*|'')            continue ;;
    esac

    # Must contain at least one = and key must be pure uppercase + digits + underscore
    case "$_line" in *'='*) ;; *) continue ;; esac
    _key="${_line%%=*}"
    _val="${_line#*=}"
    case "$_key" in ''|*[!A-Z_0-9]*) continue ;; esac

    # Value: strip inline comments and leading/trailing whitespace is preserved
    # (boot.conf values may be quoted: KEY="val with spaces" — keep as-is)
    # Block only values containing newlines (CRs already stripped by awk above)
    # and null bytes. Values with = in them are handled by ${_line#*=} above.

    if { [ "$_section" = "boot" ] && in_list "$_key" "$BOOT_KEYS"; } || { [ "$_section" = "mqtt" ] && in_list "$_key" "$MQTT_KEYS"; }; then
        if ! validate_legacy_value "$_key" "$_val"; then
            _invalid_key="$_key"
            break
        fi
    fi

    if [ "$_section" = "boot" ] && in_list "$_key" "$BOOT_KEYS"; then
        if set_conf "$_key" "$_val" "$BOOT_CONF"; then
            _applied=$((_applied + 1))
        else
            _skipped=$((_skipped + 1))
        fi
    elif [ "$_section" = "mqtt" ] && in_list "$_key" "$MQTT_KEYS"; then
        if set_conf "$_key" "$_val" "$MQTT_CONF"; then
            _applied=$((_applied + 1))
        else
            _skipped=$((_skipped + 1))
        fi
    else
        _skipped=$((_skipped + 1))
    fi
done < "$_tmp"

rm -f "$_tmp"
if [ -n "${_invalid_key:-}" ]; then
    rm -rf "$_stage" "$_backup"
    printf '{"ok":false,"error":"validation_failed","message":"Invalid value for %s; active configuration was preserved."}\n' "$_invalid_key"
    exit 0
fi
if [ "$_applied" -le 0 ]; then
    rm -rf "$_stage" "$_backup"
    printf '{"ok":false,"error":"empty_config","message":"No known configuration values found."}\n'
    exit 0
fi
if ! tc_commit_config_files "$_stage" "$CONFIG_ROOT" "$_backup" "boot.conf mqtt.conf"; then
    _error="${TC_CONFIG_ERROR:-transaction_failed}"
    rm -rf "$_stage" "$_backup"
    printf '{"ok":false,"error":"transaction_failed","message":"%s; active configuration was preserved."}\n' "$_error"
    exit 0
fi
_changed="$TC_COMMIT_COUNT"
rm -rf "$_stage" "$_backup"
printf '{"ok":true,"applied":%d,"changed_files":%d,"skipped":%d,"transactional":true}\n' "$_applied" "$_changed" "$_skipped"
