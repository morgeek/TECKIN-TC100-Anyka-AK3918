#!/bin/sh
# motion-heatmap.sh: Record & query 24-hour activity distribution and motion zone events
# Usage:
#   motion-heatmap.sh record [zone]   -> record a motion trigger in current hour bucket (0..23)
#   motion-heatmap.sh get             -> dump JSON { "ok": true, "hourly": [c0..c23], "total_24h": N, "current_hour": H }

DATA_FILE="/tmp/motion_heatmap.data"

init_data() {
  if [ ! -f "$DATA_FILE" ]; then
    # 24 zero counts separated by space, followed by last reset day/hour
    echo "0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 $(date +%d 2>/dev/null || echo 0)" > "$DATA_FILE"
  fi
}

record_event() {
  init_data
  _hr=$(date +%H 2>/dev/null || echo 0)
  _day=$(date +%d 2>/dev/null || echo 0)
  _hr=$((_hr + 0)) # strip leading zero

  read -r c0 c1 c2 c3 c4 c5 c6 c7 c8 c9 c10 c11 c12 c13 c14 c15 c16 c17 c18 c19 c20 c21 c22 c23 lday < "$DATA_FILE"

  # If day changed, clear bucket for current hour to keep rolling 24h window
  if [ "$lday" != "$day" ]; then
    # day rollover: reset current hour counter
    eval "c${_hr}=0"
  fi

  eval "_cur=\$c${_hr}"
  _cur=$((_cur + 1))
  eval "c${_hr}=\$_cur"

  echo "$c0 $c1 $c2 $c3 $c4 $c5 $c6 $c7 $c8 $c9 $c10 $c11 $c12 $c13 $c14 $c15 $c16 $c17 $c18 $c19 $c20 $c21 $c22 $c23 $_day" > "$DATA_FILE.tmp" && mv -f "$DATA_FILE.tmp" "$DATA_FILE"
}

get_json() {
  init_data
  read -r c0 c1 c2 c3 c4 c5 c6 c7 c8 c9 c10 c11 c12 c13 c14 c15 c16 c17 c18 c19 c20 c21 c22 c23 _ < "$DATA_FILE"
  _hr=$(date +%H 2>/dev/null || echo 0)
  _hr=$((_hr + 0))
  _tot=0
  for _cnt in $c0 $c1 $c2 $c3 $c4 $c5 $c6 $c7 $c8 $c9 $c10 $c11 $c12 $c13 $c14 $c15 $c16 $c17 $c18 $c19 $c20 $c21 $c22 $c23; do
    _tot=$((_tot + _cnt))
  done

  printf '{"ok":true,"current_hour":%d,"total_24h":%d,"hourly":[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d]}\n' \
    "$_hr" "$_tot" \
    "${c0:-0}" "${c1:-0}" "${c2:-0}" "${c3:-0}" "${c4:-0}" "${c5:-0}" \
    "${c6:-0}" "${c7:-0}" "${c8:-0}" "${c9:-0}" "${c10:-0}" "${c11:-0}" \
    "${c12:-0}" "${c13:-0}" "${c14:-0}" "${c15:-0}" "${c16:-0}" "${c17:-0}" \
    "${c18:-0}" "${c19:-0}" "${c20:-0}" "${c21:-0}" "${c22:-0}" "${c23:-0}"
}

case "$1" in
  record) record_event "$2" ;;
  get) get_json ;;
  *) echo "Usage: $0 {record|get}" >&2; exit 1 ;;
esac
