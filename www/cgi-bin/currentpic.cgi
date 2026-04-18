#!/bin/sh

echo "Content-type: image/jpeg"
echo ""

_BTIME=0
_read_btime() {
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _BTIME="$_v" && break
  done < /proc/stat
}
_read_ts() {
  [ "$_BTIME" -gt 0 ] || _read_btime
  read -r _up _ < /proc/uptime
  now_ts=$((_BTIME + ${_up%.*}))
  [ "$now_ts" -gt 0 ] || now_ts=0
}

CACHE_FILE="/tmp/currentpic.cache.jpg"
CACHE_META_FILE="/tmp/currentpic.cache.ts"
CACHE_LOCK_DIR="/tmp/currentpic.cache.lock"
CACHE_TTL_SECONDS="${CURRENTPIC_CACHE_TTL_SECONDS:-2}"

case "$CACHE_TTL_SECONDS" in
  ''|*[!0-9]*) CACHE_TTL_SECONDS=2 ;;
esac
[ "$CACHE_TTL_SECONDS" -lt 0 ] && CACHE_TTL_SECONDS=0
[ "$CACHE_TTL_SECONDS" -gt 10 ] && CACHE_TTL_SECONDS=10

_read_ts

cache_fresh=0
if [ -f "$CACHE_FILE" ] && [ -f "$CACHE_META_FILE" ] && [ "$CACHE_TTL_SECONDS" -gt 0 ] && [ "$now_ts" -gt 0 ]; then
  read -r cache_ts < "$CACHE_META_FILE"
  case "$cache_ts" in
    ''|*[!0-9]*) cache_ts=0 ;;
  esac
  if [ "$cache_ts" -gt 0 ] && [ "$cache_ts" -le "$now_ts" ]; then
    cache_age=$((now_ts - cache_ts))
    if [ "$cache_age" -le "$CACHE_TTL_SECONDS" ]; then
      cache_fresh=1
    fi
  fi
fi

if [ "$cache_fresh" -eq 1 ]; then
  cat "$CACHE_FILE"
  exit 0
fi

if mkdir "$CACHE_LOCK_DIR" 2>/dev/null; then
  _read_ts
  tmp_img="/tmp/currentpic.cache.$$.$now_ts.jpg"
  if /mnt/bin/getimage > "$tmp_img" 2>/dev/null; then
    mv "$tmp_img" "$CACHE_FILE" 2>/dev/null || cat "$tmp_img" > "$CACHE_FILE"
    rm -f "$tmp_img" >/dev/null 2>&1 || true
    _read_ts
    [ "$now_ts" -gt 0 ] && printf '%s\n' "$now_ts" > "$CACHE_META_FILE"
    cat "$CACHE_FILE"
    rmdir "$CACHE_LOCK_DIR" >/dev/null 2>&1 || true
    exit 0
  fi
  rm -f "$tmp_img" >/dev/null 2>&1 || true
  rmdir "$CACHE_LOCK_DIR" >/dev/null 2>&1 || true
fi

wait_count=0
while [ "$wait_count" -lt 4 ]; do
  sleep 0.1
  if [ -f "$CACHE_FILE" ]; then
    cat "$CACHE_FILE"
    exit 0
  fi
  wait_count=$((wait_count + 1))
done

/mnt/bin/getimage
