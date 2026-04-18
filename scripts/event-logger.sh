#!/bin/sh

# Event Logging Framework for TECKIN TC100
# Lightweight JSON-based event logging system
# Usage: source this file and call log_event <level> <category> <message> [extra_json]

_EL_BTIME=0
_el_read_btime() {
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _EL_BTIME="$_v" && break
  done < /proc/stat
}
_el_read_ts() {
  [ "$_EL_BTIME" -gt 0 ] || _el_read_btime
  read -r _up _ < /proc/uptime
  _EL_TS=$((_EL_BTIME + ${_up%.*}))
}

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

    _el_sz="$(wc -c < "$EVENT_LOG_FILE" 2>/dev/null)"
    case "$_el_sz" in ''|*[!0-9]*) _el_sz=0 ;; esac
    _el_max_bytes=$(( EVENT_LOG_MAX_SIZE_KB * 1024 ))
    if [ "$_el_sz" -gt "$_el_max_bytes" ]; then
        # Rotate backups without seq (arithmetic loop, BusyBox-safe).
        _el_i=$((EVENT_LOG_BACKUP_COUNT - 1))
        while [ "$_el_i" -ge 0 ]; do
            if [ -f "${EVENT_LOG_FILE}.${_el_i}.gz" ]; then
                mv "${EVENT_LOG_FILE}.${_el_i}.gz" "${EVENT_LOG_FILE}.$((_el_i + 1)).gz" 2>/dev/null || true
            elif [ -f "${EVENT_LOG_FILE}.${_el_i}" ]; then
                mv "${EVENT_LOG_FILE}.${_el_i}" "${EVENT_LOG_FILE}.$((_el_i + 1))" 2>/dev/null || true
            fi
            _el_i=$((_el_i - 1))
        done

        # Compress the current log into .0.gz, fall back to plain .0 if gzip unavailable.
        if command -v gzip >/dev/null 2>&1; then
            gzip -c "$EVENT_LOG_FILE" > "${EVENT_LOG_FILE}.0.gz" 2>/dev/null \
                && rm -f "$EVENT_LOG_FILE" 2>/dev/null || true
        else
            mv "$EVENT_LOG_FILE" "${EVENT_LOG_FILE}.0" 2>/dev/null || true
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
    _el_read_ts
    local timestamp=$_EL_TS

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
        # Basic filtering without jq.
        # Assumes one complete JSON object per line (JSONL/ndjson format) with
        # "timestamp":<epoch> as the first numeric field — the format log_event() writes.
        # head -n guard: each event is one line + one comma = 2 lines; cap output size.
        awk -v since="$since" -v limit="$limit" '
        BEGIN { count = 0; print "[" }
        NF == 0 { next }
        {
            if (count > 0) print ","
            # Extract timestamp from JSON (expects "timestamp":<number> anywhere in line)
            if (match($0, /"timestamp":([0-9]+)/, arr)) {
                if (arr[1] >= since && count < limit) {
                    print $0
                    count++
                }
            }
        }
        END { print "]" }
        ' "$EVENT_LOG_FILE" | head -n $((limit * 2 + 4)) || echo "[]"
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
        # Basic filtering without jq (same JSONL format assumption as get_events_since).
        awk -v since="$since" -v limit="$limit" '
        BEGIN { count = 0; print "[" }
        NF == 0 { next }
        /"level":"error"/ || /"level":"critical"/ {
            if (count > 0) print ","
            if (match($0, /"timestamp":([0-9]+)/, arr)) {
                if (arr[1] >= since && count < limit) {
                    print $0
                    count++
                }
            }
        }
        END { print "]" }
        ' "$EVENT_LOG_FILE" | head -n $((limit * 2 + 4)) || echo "[]"
    fi
}

# Clean up old log files beyond EVENT_LOG_BACKUP_COUNT
cleanup_event_logs() {
    _cl_keep=$((EVENT_LOG_BACKUP_COUNT + 1))
    _cl_idx=0
    # List all backups (plain and gzipped), newest first, remove extras.
    for _cl_f in $(ls -t "${EVENT_LOG_FILE}."* 2>/dev/null); do
        _cl_idx=$((_cl_idx + 1))
        if [ "$_cl_idx" -gt "$EVENT_LOG_BACKUP_COUNT" ]; then
            rm -f "$_cl_f" 2>/dev/null || true
        fi
    done
}