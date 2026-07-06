#!/bin/sh
# conf-import.cgi — validate and apply a tc100-boot-mqtt-export v1 file.
# POST: raw text body (Content-Type: text/plain), X-CSRF-Token header required.
# Returns JSON: {"ok":true,"applied":N,"skipped":N} or {"ok":false,"error":"..."}

BOOT_CONF="/mnt/config/boot.conf"
MQTT_CONF="/mnt/config/mqtt.conf"
BOOT_CONF_DIST="/mnt/config/boot.conf.dist"
MQTT_CONF_DIST="/mnt/config/mqtt.conf.dist"

printf 'Content-Type: application/json\r\n'
printf '\r\n'

# ── CSRF check ────────────────────────────────────────────────────────────────
_csrf_stored=""
if [ -r /tmp/csrf_token ]; then
    read -r _csrf_stored < /tmp/csrf_token
    _csrf_stored="$(printf '%s' "$_csrf_stored" | tr -cd '0-9a-fA-F')"
fi
if [ -n "$_csrf_stored" ]; then
    _csrf_hdr="$(printf '%s' "${HTTP_X_CSRF_TOKEN:-}" | tr -cd '0-9a-fA-F')"
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
[ "$_cl" -gt 131072 ] && _cl=131072

_tmp="/tmp/conf_import_$$.txt"
head -c "$_cl" 2>/dev/null | tr -d '\r' > "$_tmp"

# ── Validate magic header ────────────────────────────────────────────────────
if ! grep -q '^## tc100-boot-mqtt-export v1' "$_tmp" 2>/dev/null; then
    rm -f "$_tmp"
    printf '{"ok":false,"error":"invalid_format","message":"Not a valid TC100 config export file. Export from this camera first."}\n'
    exit 0
fi

# ── Ensure target files exist (copy from .dist if needed) ────────────────────
[ -f "$BOOT_CONF" ] || { [ -f "$BOOT_CONF_DIST" ] && cp "$BOOT_CONF_DIST" "$BOOT_CONF" 2>/dev/null; }
[ -f "$MQTT_CONF" ] || { [ -f "$MQTT_CONF_DIST" ] && cp "$MQTT_CONF_DIST" "$MQTT_CONF" 2>/dev/null; }

if [ ! -f "$BOOT_CONF" ] || [ ! -f "$MQTT_CONF" ]; then
    rm -f "$_tmp"
    printf '{"ok":false,"error":"config_not_found","message":"Cannot locate boot.conf or mqtt.conf on SD card."}\n'
    exit 0
fi

# ── set_conf KEY VALUE FILE — atomic awk rewrite ────────────────────────────
set_conf() {
    _k="$1" _v="$2" _f="$3"
    [ -f "$_f" ] || return 1
    _t="${_f}.ictmp.$$"
    # Escape backslashes before awk -v to prevent awk from interpreting \n, \t, etc.
    _ve="$(printf '%s' "$_v" | sed 's/\\/\\\\/g')"
    awk -v k="$_k" -v v="$_ve" '
        BEGIN { FS="="; found=0 }
        $1==k  { print k"="v; found=1; next }
        { print }
        END { if (!found) print k"="v }
    ' "$_f" > "$_t" && mv "$_t" "$_f" || { rm -f "$_t"; return 1; }
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
    # Block only values containing newlines (already stripped by tr -d '\r' above)
    # and null bytes. Values with = in them are handled by ${_line#*=} above.

    if [ "$_section" = "boot" ] && in_list "$_key" "$BOOT_KEYS"; then
        if set_conf "$_key" "$_val" "$BOOT_CONF"; then
            _applied=$(expr "$_applied" + 1)
        else
            _skipped=$(expr "$_skipped" + 1)
        fi
    elif [ "$_section" = "mqtt" ] && in_list "$_key" "$MQTT_KEYS"; then
        if set_conf "$_key" "$_val" "$MQTT_CONF"; then
            _applied=$(expr "$_applied" + 1)
        else
            _skipped=$(expr "$_skipped" + 1)
        fi
    else
        _skipped=$(expr "$_skipped" + 1)
    fi
done < "$_tmp"

rm -f "$_tmp"

printf '{"ok":true,"applied":%d,"skipped":%d}\n' "$_applied" "$_skipped"
