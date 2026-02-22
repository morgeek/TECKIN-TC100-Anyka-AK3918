#!/bin/sh

source ./func.cgi
. /mnt/scripts/common_functions.sh

MOTION_CONFIG="/mnt/config/motion.conf"
EVENT_LOG="/mnt/log/motion-events.log"
LATEST_SNAPSHOT_FILE="/tmp/motion-last-snapshot.path"

install_config "$MOTION_CONFIG"

motion_save_dir="/mnt/motion/stills"
if [ -f "$MOTION_CONFIG" ]; then
  # shellcheck disable=SC1090
  . "$MOTION_CONFIG"
  motion_save_dir="${save_dir:-$motion_save_dir}"
fi

find_latest_from_log()
{
  if [ ! -f "$EVENT_LOG" ]; then
    return 1
  fi

  tmp_log="/tmp/motionthumb.$$.tmp"
  tail -n 120 "$EVENT_LOG" > "$tmp_log" 2>/dev/null || true

  latest=""
  while IFS='|' read -r _ _ _ snapshot_path _ _; do
    if [ -n "$snapshot_path" ] && [ -f "$snapshot_path" ]; then
      latest="$snapshot_path"
    fi
  done < "$tmp_log"
  rm -f "$tmp_log"

  if [ -n "$latest" ] && [ -f "$latest" ]; then
    printf '%s\n' "$latest"
    return 0
  fi
  return 1
}

resolve_snapshot_path()
{
  if [ -n "$F_file" ]; then
    filename="${F_file##*/}"
    candidate="${motion_save_dir%/}/$filename"
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  if [ -f "$LATEST_SNAPSHOT_FILE" ]; then
    read -r latest_path < "$LATEST_SNAPSHOT_FILE"
    if [ -n "$latest_path" ] && [ -f "$latest_path" ]; then
      printf '%s\n' "$latest_path"
      return 0
    fi
  fi

  if find_latest_from_log; then
    return 0
  fi

  latest_fs="$(ls -1t "${motion_save_dir%/}"/*.jpg 2>/dev/null | head -n 1)"
  if [ -n "$latest_fs" ] && [ -f "$latest_fs" ]; then
    printf '%s\n' "$latest_fs"
    return 0
  fi

  return 1
}

snapshot_path="$(resolve_snapshot_path)"
if [ -z "$snapshot_path" ] || [ ! -f "$snapshot_path" ]; then
  echo "Status: 404 Not Found"
  echo "Content-type: text/plain"
  echo "Pragma: no-cache"
  echo "Cache-Control: max-age=0, no-store, no-cache"
  echo ""
  echo "No motion thumbnail available"
  exit 0
fi

echo "Content-type: image/jpeg"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""
cat "$snapshot_path"
