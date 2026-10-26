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

EVENT_LOG_FILE="${EVENT_LOG_FILE:-/tmp/events.jsonl}"
EVENT_LOG_MAX_SIZE_KB=256
EVENT_LOG_BACKUP_COUNT=2

# Log Level mapping (numeric for comparison)
# debug: 10, info: 20, warn: 30, error: 40, critical: 50
get_level_val() {
    case "$1" in
        debug) echo 10 ;;
        info)  echo 20 ;;
        warn)  echo 30 ;;
        error) echo 40 ;;
        critical) echo 50 ;;
        *) echo 20 ;;
    esac
}

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

    # Filter by threshold (Default to INFO)
    _threshold_val=$(get_level_val "${EVENT_LOG_THRESHOLD:-info}")
    _current_val=$(get_level_val "$level")
    
    if [ "$_current_val" -lt "$_threshold_val" ]; then
        return
    fi

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

# The event log is JSONL: one object per line, as log_event() writes it.
# Queries are done in awk (BusyBox: no 3-argument match(), and no jq on the
# flash firmware); the result is a JSON array of the last <limit> matches.
#   _el_query <since> <limit> <errors-only 0|1>
_el_query() {
    if [ ! -f "$EVENT_LOG_FILE" ]; then
        echo "[]"
        return
    fi
    awk -v since="$1" -v limit="$2" -v errors="$3" '
    BEGIN { n = 0; if (limit + 0 < 1) limit = 1 }
    NF == 0 { next }
    {
        if (!match($0, /"timestamp":[0-9]+/)) next
        if (substr($0, RSTART + 12, RLENGTH - 12) + 0 < since + 0) next
        if (errors == 1 && $0 !~ /"level":"(error|critical)"/) next
        buf[n % limit] = $0; n++
    }
    END {
        printf "["
        first = (n > limit) ? n - limit : 0
        for (i = first; i < n; i++) printf "%s%s", (i > first ? "," : ""), buf[i % limit]
        print "]"
    }' "$EVENT_LOG_FILE" 2>/dev/null || echo "[]"
}

# Get events since timestamp
# Usage: get_events_since <timestamp> [limit]
get_events_since() {
    _el_query "${1:-0}" "${2:-100}" 0
}

# Get recent events
# Usage: get_recent_events [limit]
get_recent_events() {
    _el_query 0 "${1:-50}" 0
}

# Get error events only
# Usage: get_error_events [since_timestamp] [limit]
get_error_events() {
    _el_query "${1:-0}" "${2:-20}" 1
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