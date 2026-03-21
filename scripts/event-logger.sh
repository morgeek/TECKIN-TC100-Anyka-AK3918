#!/bin/sh

# Event Logging Framework for TECKIN TC100
# Lightweight JSON-based event logging system
# Usage: source this file and call log_event <level> <category> <message> [extra_json]

EVENT_LOG_FILE="/tmp/events.jsonl"
EVENT_LOG_MAX_SIZE_KB=256
EVENT_LOG_BACKUP_COUNT=2

# Check if event logging is enabled (default: enabled)
event_logging_enabled() {
    [ "${EVENT_LOG_ENABLE:-1}" = "1" ]
}

# Rotate log file if it exceeds max size
rotate_event_log() {
    if [ ! -f "$EVENT_LOG_FILE" ]; then
        return
    fi

    local size_kb=$(du -k "$EVENT_LOG_FILE" 2>/dev/null | awk '{print $1}')
    if [ "$size_kb" -gt "$EVENT_LOG_MAX_SIZE_KB" ]; then
        # Rotate backups
        for i in $(seq $((EVENT_LOG_BACKUP_COUNT - 1)) -1 0); do
            if [ -f "${EVENT_LOG_FILE}.$i" ]; then
                mv "${EVENT_LOG_FILE}.$i" "${EVENT_LOG_FILE}.$((i + 1))"
            fi
        done

        # Move current to .0
        if [ -f "$EVENT_LOG_FILE" ]; then
            mv "$EVENT_LOG_FILE" "${EVENT_LOG_FILE}.0"
        fi
    fi
}

# Log an event
# Usage: log_event <level> <category> <message> [extra_json]
# Levels: debug, info, warn, error, critical
# Categories: system, network, audio, video, mqtt, onvif, api, service
log_event() {
    if ! event_logging_enabled; then
        return
    fi

    local level="$1"
    local category="$2"
    local message="$3"
    local extra_json="$4"

    # Validate level
    case "$level" in
        debug|info|warn|error|critical) ;;
        *) level="info" ;;
    esac

    # Get timestamp
    local timestamp=$(date +%s)

    # Build JSON
    local json="{\"timestamp\":$timestamp,\"level\":\"$level\",\"category\":\"$category\",\"message\":\"$message\""

    # Add extra JSON if provided
    if [ -n "$extra_json" ]; then
        # Remove leading/trailing braces if present
        extra_json=$(echo "$extra_json" | sed 's/^{//' | sed 's/}$//')
        if [ -n "$extra_json" ]; then
            json="$json,$extra_json"
        fi
    fi

    json="$json}"

    # Rotate if needed
    rotate_event_log

    # Append to log
    echo "$json" >> "$EVENT_LOG_FILE" 2>/dev/null || true
}

# Get events since timestamp
# Usage: get_events_since <timestamp> [limit]
get_events_since() {
    local since="$1"
    local limit="${2:-100}"

    if [ ! -f "$EVENT_LOG_FILE" ]; then
        echo "[]"
        return
    fi

    # Use jq if available, otherwise basic filtering
    if command -v jq >/dev/null 2>&1; then
        jq -s "map(select(.timestamp >= $since)) | .[-$limit:]" "$EVENT_LOG_FILE" 2>/dev/null || echo "[]"
    else
        # Basic filtering without jq
        awk -v since="$since" -v limit="$limit" '
        BEGIN { count = 0; print "[" }
        {
            if (count > 0) print ","
            # Extract timestamp from JSON (basic parsing)
            if (match($0, /"timestamp":([0-9]+)/, arr)) {
                if (arr[1] >= since) {
                    print $0
                    count++
                }
            }
        }
        END { print "]" }
        ' "$EVENT_LOG_FILE" | head -n $((limit * 2 + 2)) || echo "[]"
    fi
}

# Get recent events
# Usage: get_recent_events [limit]
get_recent_events() {
    local limit="${1:-50}"

    if [ ! -f "$EVENT_LOG_FILE" ]; then
        echo "[]"
        return
    fi

    # Get last N lines and format as JSON array
    if command -v jq >/dev/null 2>&1; then
        tail -n "$limit" "$EVENT_LOG_FILE" 2>/dev/null | jq -s '.' 2>/dev/null || echo "[]"
    else
        # Basic formatting without jq
        echo "["
        tail -n "$limit" "$EVENT_LOG_FILE" 2>/dev/null | awk '
        NR > 1 { print "," }
        { print $0 }
        '
        echo "]"
    fi
}

# Get error events only
# Usage: get_error_events [since_timestamp] [limit]
get_error_events() {
    local since="${1:-0}"
    local limit="${2:-20}"

    if [ ! -f "$EVENT_LOG_FILE" ]; then
        echo "[]"
        return
    fi

    if command -v jq >/dev/null 2>&1; then
        jq -s "map(select(.timestamp >= $since and (.level == \"error\" or .level == \"critical\"))) | .[-$limit:]" "$EVENT_LOG_FILE" 2>/dev/null || echo "[]"
    else
        # Basic filtering without jq
        awk -v since="$since" -v limit="$limit" '
        BEGIN { count = 0; print "[" }
        /"level":"error"/ || /"level":"critical"/ {
            if (count > 0) print ","
            # Check timestamp
            if (match($0, /"timestamp":([0-9]+)/, arr)) {
                if (arr[1] >= since) {
                    print $0
                    count++
                }
            }
        }
        END { print "]" }
        ' "$EVENT_LOG_FILE" | head -n $((limit * 2 + 2)) || echo "[]"
    fi
}

# Clean up old log files
cleanup_event_logs() {
    # Remove excess backup files
    ls -t "${EVENT_LOG_FILE}."* 2>/dev/null | tail -n +$((EVENT_LOG_BACKUP_COUNT + 1)) | xargs rm -f 2>/dev/null || true
}