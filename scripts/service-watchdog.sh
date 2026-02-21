#!/bin/sh

LOGPATH="${LOGPATH:-/var/log/service-watchdog.log}"
WATCHDOG_LOG_MAX_BYTES="${WATCHDOG_LOG_MAX_BYTES:-262144}"
WATCHDOG_LOG_BACKUPS="${WATCHDOG_LOG_BACKUPS:-2}"
WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS="${WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS:-20}"
WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS="${WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS:-15}"
WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS="${WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS:-180}"
MAX_ERRORS_TO_REBOOT=5
MAX_ERRORS_TO_ALTERNATIVE_REBOOT=10 # If normal reboot not work
MIN_SUCCES_TO_RESET_REBOOT=30
# Increase default check interval to reduce CPU usage (can be overridden)
CHECK_TIMEOUT_SECONDS="${CHECK_TIMEOUT_SECONDS:-60}"

case "$CHECK_TIMEOUT_SECONDS" in
    ''|*[!0-9]*) CHECK_TIMEOUT_SECONDS=60 ;;
esac
[ "$CHECK_TIMEOUT_SECONDS" -lt 5 ] && CHECK_TIMEOUT_SECONDS=5

case "$WATCHDOG_LOG_MAX_BYTES" in
    ''|*[!0-9]*) WATCHDOG_LOG_MAX_BYTES=262144 ;;
esac
[ "$WATCHDOG_LOG_MAX_BYTES" -lt 32768 ] && WATCHDOG_LOG_MAX_BYTES=32768
[ "$WATCHDOG_LOG_MAX_BYTES" -gt 2097152 ] && WATCHDOG_LOG_MAX_BYTES=2097152

case "$WATCHDOG_LOG_BACKUPS" in
    ''|*[!0-9]*) WATCHDOG_LOG_BACKUPS=2 ;;
esac
[ "$WATCHDOG_LOG_BACKUPS" -lt 0 ] && WATCHDOG_LOG_BACKUPS=0
[ "$WATCHDOG_LOG_BACKUPS" -gt 5 ] && WATCHDOG_LOG_BACKUPS=5

case "$WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS" in
    ''|*[!0-9]*) WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS=20 ;;
esac
[ "$WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS" -lt 0 ] && WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS=0
[ "$WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS" -gt 300 ] && WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS=300

case "$WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS" in
    ''|*[!0-9]*) WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS=15 ;;
esac
[ "$WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS" -lt 0 ] && WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS=0
[ "$WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS" -gt 120 ] && WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS=120

case "$WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS" in
    ''|*[!0-9]*) WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS=180 ;;
esac
[ "$WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS" -lt 0 ] && WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS=0
[ "$WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS" -gt 600 ] && WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS=600
[ "$WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS" -lt "$WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS" ] && WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS="$WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS"

append_log()
{
    line="$1"

    case "$LOGPATH" in
        /dev/null)
            return 0
            ;;
    esac

    log_dir=$(dirname "$LOGPATH")
    if [ ! -d "$log_dir" ]; then
        mkdir -p "$log_dir" >/dev/null 2>&1 || true
    fi

    if [ -f "$LOGPATH" ]; then
        log_size="$(wc -c < "$LOGPATH" 2>/dev/null)"
        case "$log_size" in
            ''|*[!0-9]*) log_size=0 ;;
        esac

        if [ "$log_size" -gt "$WATCHDOG_LOG_MAX_BYTES" ]; then
            if [ "$WATCHDOG_LOG_BACKUPS" -gt 0 ]; then
                idx="$WATCHDOG_LOG_BACKUPS"
                while [ "$idx" -gt 1 ]; do
                    prev=$((idx - 1))
                    if [ -f "${LOGPATH}.${prev}" ]; then
                        mv "${LOGPATH}.${prev}" "${LOGPATH}.${idx}" 2>/dev/null || true
                    fi
                    idx=$((idx - 1))
                done
                mv "$LOGPATH" "${LOGPATH}.1" 2>/dev/null || : > "$LOGPATH"
            else
                : > "$LOGPATH"
            fi
        fi
    fi

    printf '%s\n' "$line" >> "$LOGPATH" 2>/dev/null || true
}

service_is_healthy()
{
    SERVICE_TO_MONITOR=$1
    CHECK_MODE=$2

    service_status="$("$SERVICE_TO_MONITOR" status 2>/dev/null)"
    if [ -z "$service_status" ]; then
        return 1
    fi

    if [ "$CHECK_MODE" = "health" ]; then
        "$SERVICE_TO_MONITOR" health >/dev/null 2>&1 || return 1
    fi

    return 0
}

recover_service()
{
    SERVICE_TO_MONITOR=$1
    CHECK_MODE=$2

    if [ "$CHECK_MODE" = "health" ]; then
        # Prefer a service-level restart so watchdog process itself is not killed.
        "$SERVICE_TO_MONITOR" restart >/dev/null 2>&1 || "$SERVICE_TO_MONITOR" start >/dev/null 2>&1
    else
        "$SERVICE_TO_MONITOR" start >/dev/null 2>&1
    fi
}

monitor_service()
{
    SERVICE_TO_MONITOR=$1
    NEED_REBOOT_ON_ERROR=$2
    CHECK_MODE=$3
    CURRENT_ERRORS=0
    CURRENT_SUCCESS=0
    no_reboot_delay_seconds="$WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS"
    last_no_reboot_restart_ts=0

    case "$CHECK_MODE" in
        status|health) ;;
        *) CHECK_MODE="status" ;;
    esac

    while :
    do
        sleep $CHECK_TIMEOUT_SECONDS

        if service_is_healthy "$SERVICE_TO_MONITOR" "$CHECK_MODE"; then
            CURRENT_SUCCESS=$((CURRENT_SUCCESS+1))
            if [ "$CURRENT_SUCCESS" -gt 10 ]; then
                no_reboot_delay_seconds="$WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS"
            fi
            if [ "$CURRENT_SUCCESS" -gt "$MIN_SUCCES_TO_RESET_REBOOT" ]; then
                CURRENT_SUCCESS=0
                CURRENT_ERRORS=0
            fi
        elif [ $NEED_REBOOT_ON_ERROR -eq 0 ]; then
            now_ts="$(date +%s 2>/dev/null)"
            case "$now_ts" in
                ''|*[!0-9]*) now_ts=0 ;;
            esac
            if [ "$no_reboot_delay_seconds" -gt 0 ] && [ "$last_no_reboot_restart_ts" -gt 0 ] && [ "$now_ts" -gt "$last_no_reboot_restart_ts" ]; then
                elapsed=$((now_ts - last_no_reboot_restart_ts))
                if [ "$elapsed" -lt "$no_reboot_delay_seconds" ]; then
                    append_log "$(date) $SERVICE_TO_MONITOR - unhealthy, restart deferred ${elapsed}s/${no_reboot_delay_seconds}s (no reboot mode, check=$CHECK_MODE)"
                    continue
                fi
            fi
            append_log "$(date) $SERVICE_TO_MONITOR - unhealthy, perform restart (no reboot mode, check=$CHECK_MODE, backoff=${no_reboot_delay_seconds}s)"
            recover_service "$SERVICE_TO_MONITOR" "$CHECK_MODE"
            last_no_reboot_restart_ts="$now_ts"
            if [ "$no_reboot_delay_seconds" -lt "$WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS" ]; then
                no_reboot_delay_seconds=$((no_reboot_delay_seconds + WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS))
                if [ "$no_reboot_delay_seconds" -gt "$WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS" ]; then
                    no_reboot_delay_seconds="$WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS"
                fi
            fi
        else
            CURRENT_SUCCESS=0
            CURRENT_ERRORS=$((CURRENT_ERRORS+1))
            append_log "$(date) Service $SERVICE_TO_MONITOR unhealthy, error count: $CURRENT_ERRORS (check=$CHECK_MODE)"
            if [ "$CURRENT_ERRORS" -gt "$MAX_ERRORS_TO_ALTERNATIVE_REBOOT" ]; then # If we can't reboot by normal call to 'reboot'
                append_log "$SERVICE_TO_MONITOR - perform alternative reboot"
                echo b >/proc/sysrq-trigger
                CURRENT_ERRORS=0
            elif [ "$CURRENT_ERRORS" -gt "$MAX_ERRORS_TO_REBOOT" ]; then
                append_log "$SERVICE_TO_MONITOR - perform reboot"
                /sbin/reboot -f
            else
                append_log "$SERVICE_TO_MONITOR - perform restart"
                recover_service "$SERVICE_TO_MONITOR" "$CHECK_MODE"
            fi
        fi
    done
}

if [ $# -eq 0 ]; then
    append_log "No service to monitor! First param - full patch to service control script."
else
    monitor_service "$1" "${2:-1}" "${3:-status}"
fi
