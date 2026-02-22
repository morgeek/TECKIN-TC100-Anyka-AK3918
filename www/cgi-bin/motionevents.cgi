#!/bin/sh

source ./func.cgi

echo "Content-type: application/json"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

EVENT_LOG="/mnt/log/motion-events.log"

json_escape()
{
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

sanitize_int_range()
{
  value="$1"
  min="$2"
  max="$3"
  fallback="$4"
  case "$value" in
    ''|*[!0-9]*) value="$fallback" ;;
  esac
  if [ "$value" -lt "$min" ]; then
    value="$min"
  fi
  if [ "$value" -gt "$max" ]; then
    value="$max"
  fi
  echo "$value"
}

limit="$(sanitize_int_range "${F_limit:-20}" 1 200 20)"
type_filter="${F_type:-}"
case "$type_filter" in
  motion_on|motion_off)
    ;;
  *)
    type_filter=""
    ;;
esac

if [ ! -f "$EVENT_LOG" ]; then
  echo '{"items":[],"count":0,"latest_thumbnail":"cgi-bin/motionthumb.cgi"}'
  exit 0
fi

tmp_events="/tmp/motionevents.$$.tmp"
tail -n "$limit" "$EVENT_LOG" > "$tmp_events" 2>/dev/null || true

printf '{"items":['
sep=""
count=0

while IFS='|' read -r epoch ts_utc event_type snapshot_path clip_path detail; do
  [ -n "$epoch" ] || continue
  if [ -n "$type_filter" ] && [ "$event_type" != "$type_filter" ]; then
    continue
  fi

  epoch_sanitized="$(sanitize_int_range "$epoch" 0 4294967295 0)"
  ts_json="$(json_escape "$ts_utc")"
  type_json="$(json_escape "$event_type")"
  snapshot_json="$(json_escape "$snapshot_path")"
  clip_json="$(json_escape "$clip_path")"
  detail_json="$(json_escape "$detail")"

  printf '%s{"ts":%s,"time_utc":"%s","type":"%s","snapshot":"%s","clip":"%s","detail":"%s"}' \
    "$sep" "$epoch_sanitized" "$ts_json" "$type_json" "$snapshot_json" "$clip_json" "$detail_json"
  sep=","
  count=$((count + 1))
done < "$tmp_events"

rm -f "$tmp_events"
printf '],"count":%s,"latest_thumbnail":"cgi-bin/motionthumb.cgi"}\n' "$count"
