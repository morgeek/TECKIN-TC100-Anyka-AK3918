#!/bin/sh

LOGPATH="${LOGPATH:-/var/log/service-watchdog.log}"
MAX_ERRORS_TO_REBOOT=5
MAX_ERRORS_TO_ALTERNATIVE_REBOOT=10 # If normal reboot not work
MIN_SUCCES_TO_RESET_REBOOT=30
# Increase default check interval to reduce CPU usage (can be overridden)
CHECK_TIMEOUT_SECONDS="${CHECK_TIMEOUT_SECONDS:-60}"

case "$CHECK_TIMEOUT_SECONDS" in
    ''|*[!0-9]*) CHECK_TIMEOUT_SECONDS=60 ;;
esac
[ "$CHECK_TIMEOUT_SECONDS" -lt 5 ] && CHECK_TIMEOUT_SECONDS=5

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

    case "$CHECK_MODE" in
        status|health) ;;
        *) CHECK_MODE="status" ;;
    esac

    while :
    do
        sleep $CHECK_TIMEOUT_SECONDS

        if service_is_healthy "$SERVICE_TO_MONITOR" "$CHECK_MODE"; then
            CURRENT_SUCCESS=$((CURRENT_SUCCESS+1))
            if [ "$CURRENT_SUCCESS" -gt "$MIN_SUCCES_TO_RESET_REBOOT" ]; then
                CURRENT_SUCCESS=0
                CURRENT_ERRORS=0
            fi
        elif [ $NEED_REBOOT_ON_ERROR -eq 0 ]; then
            echo "$(date) $SERVICE_TO_MONITOR - unhealthy, perform restart (no reboot mode, check=$CHECK_MODE)" >> "$LOGPATH"
            recover_service "$SERVICE_TO_MONITOR" "$CHECK_MODE"
        else
            CURRENT_SUCCESS=0
            CURRENT_ERRORS=$((CURRENT_ERRORS+1))
            echo "$(date) Service $SERVICE_TO_MONITOR unhealthy, error count: $CURRENT_ERRORS (check=$CHECK_MODE)" >> "$LOGPATH"
            if [ "$CURRENT_ERRORS" -gt "$MAX_ERRORS_TO_ALTERNATIVE_REBOOT" ]; then # If we can't reboot by normal call to 'reboot'
                echo "$SERVICE_TO_MONITOR - perform alternative reboot" >> "$LOGPATH"
                echo b >/proc/sysrq-trigger
                CURRENT_ERRORS=0
            elif [ "$CURRENT_ERRORS" -gt "$MAX_ERRORS_TO_REBOOT" ]; then
                echo "$SERVICE_TO_MONITOR - perform reboot" >> "$LOGPATH"
                /sbin/reboot -f
            else
                echo "$SERVICE_TO_MONITOR - perform restart" >> "$LOGPATH"
                recover_service "$SERVICE_TO_MONITOR" "$CHECK_MODE"
            fi
        fi
    done
}

if [ $# -eq 0 ]; then
    echo "No service to monitor! First param - full patch to service control script." >> "$LOGPATH"
else
    monitor_service "$1" "${2:-1}" "${3:-status}"
fi
