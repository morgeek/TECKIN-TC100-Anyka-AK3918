#!/bin/sh

# serve FILE: the picture with its header; no picture (video server restarting, no frame yet): 503, which the
# page retries, instead of an empty "image/jpeg" that shows a broken image.
serve() {
  if [ -s "$1" ]; then
    echo "Content-type: image/jpeg"
    echo "Cache-Control: no-store"
    echo ""
    exec cat "$1"
  else
    echo "Status: 503 Service Unavailable"
    echo "Content-type: text/plain"
    echo "Retry-After: 1"
    echo ""
    echo "no picture yet"
  fi
  exit 0
}

# timeout(1) shim. This CGI is standalone (it sources neither func.cgi nor
# common_functions.sh, deliberately — it is on the liveview hot path), so it
# carries its own. /bin/timeout is the old busybox variant wanting `-t SECS`;
# given `timeout SECS CMD` it tries to exec the duration and fails silently in a
# redirect. That is why this endpoint served a 0-byte JPEG — HTTP 200, correct
# Content-Type, no image — and the dashboard liveview stayed blank.
if ! timeout 1 true >/dev/null 2>&1; then
    timeout() { busybox timeout "$@"; }
fi

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
  serve "$CACHE_FILE"
fi

# tc100_rtsp owns the cache. It makes a new picture at once when /tmp/snapshot_request exists; wait ~1.5 s
# for it, then serve whatever picture is there.
read -r _old_ts 2>/dev/null < "$CACHE_META_FILE"
: > /tmp/snapshot_request 2>/dev/null
wait_count=0
while [ "$wait_count" -lt 15 ]; do
  _new_ts=""; read -r _new_ts 2>/dev/null < "$CACHE_META_FILE"
  [ -n "$_new_ts" ] && [ "$_new_ts" != "$_old_ts" ] && break
  sleep 0.1
  wait_count=$((wait_count + 1))
done
serve "$CACHE_FILE"
