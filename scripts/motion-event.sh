#!/bin/sh

EVENT_LOG="/mnt/log/motion-events.log"
LATEST_SNAPSHOT_FILE="/tmp/motion-last-snapshot.path"
MAX_EVENTS=400

json_escape()
{
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

sanitize_field()
{
  printf '%s' "$1" | tr '\r\n' '  ' | sed 's/|/%7C/g'
}

trim_event_log()
{
  if [ ! -f "$EVENT_LOG" ]; then
    return 0
  fi
  line_count="$(wc -l < "$EVENT_LOG" 2>/dev/null)"
  case "$line_count" in
    ''|*[!0-9]*) line_count=0 ;;
  esac
  if [ "$line_count" -le "$MAX_EVENTS" ]; then
    return 0
  fi
  tmp_log="/tmp/motion-events.$$.tmp"
  tail -n "$MAX_EVENTS" "$EVENT_LOG" > "$tmp_log" 2>/dev/null || true
  mv "$tmp_log" "$EVENT_LOG" 2>/dev/null || true
}

event_type="$(sanitize_field "$1")"
snapshot_path="$(sanitize_field "$2")"
clip_path="$(sanitize_field "$3")"
detail="$(sanitize_field "$4")"

if [ -z "$event_type" ]; then
  event_type="motion"
fi

if [ ! -d /mnt/log ]; then
  mkdir -p /mnt/log >/dev/null 2>&1 || true
fi

epoch="$(date +%s 2>/dev/null)"
[ -n "$epoch" ] || epoch=0
ts_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)"
[ -n "$ts_utc" ] || ts_utc="1970-01-01T00:00:00Z"

printf '%s|%s|%s|%s|%s|%s\n' "$epoch" "$ts_utc" "$event_type" "$snapshot_path" "$clip_path" "$detail" >> "$EVENT_LOG"
trim_event_log

if [ -n "$snapshot_path" ] && [ -f "$snapshot_path" ]; then
  printf '%s\n' "$snapshot_path" > "$LATEST_SNAPSHOT_FILE"
fi

if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
  event_json="$(json_escape "$event_type")"
  snapshot_json="$(json_escape "$snapshot_path")"
  clip_json="$(json_escape "$clip_path")"
  detail_json="$(json_escape "$detail")"
  payload=$(printf '{"ts":%s,"time_utc":"%s","type":"%s","snapshot":"%s","clip":"%s","detail":"%s"}' "$epoch" "$ts_utc" "$event_json" "$snapshot_json" "$clip_json" "$detail_json")
  /mnt/scripts/mqtt-bridge.sh publish event "$payload" 0 >/dev/null 2>&1 || true
fi
