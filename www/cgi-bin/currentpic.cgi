#!/bin/sh

# serve FILE: the picture with its header; no picture (video server restarting, no frame yet): 503, which the
# page retries, instead of an empty "image/jpeg" that shows a broken image.
serve() {
  if [ -s "$1" ]; then
    echo "Content-type: image/jpeg"
    echo "Cache-Control: no-store"
    echo ""
    cat "$1"
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
CACHE_LOCK_DIR="/tmp/currentpic.cache.lock"
CACHE_TTL_SECONDS="${CURRENTPIC_CACHE_TTL_SECONDS:-2}"

case "$CACHE_TTL_SECONDS" in
  ''|*[!0-9]*) CACHE_TTL_SECONDS=2 ;;
esac
[ "$CACHE_TTL_SECONDS" -lt 0 ] && CACHE_TTL_SECONDS=0
[ "$CACHE_TTL_SECONDS" -gt 10 ] && CACHE_TTL_SECONDS=10

_read_ts

# The video server writes the still-picture encoder's last JPEG (one a
# second) to /tmp/snapshot.jpg (libtc100fix, TC100FIX_SNAPSHOT): when it is
# recent, serve it as it is, without starting getimage.
SNAP_FILE="${CURRENTPIC_SNAPSHOT:-/tmp/snapshot.jpg}"
if [ -s "$SNAP_FILE" ] && [ "$now_ts" -gt 0 ]; then
  snap_ts="$(date -r "$SNAP_FILE" +%s 2>/dev/null)"
  case "$snap_ts" in ''|*[!0-9]*) snap_ts=0 ;; esac
  if [ "$snap_ts" -gt 0 ] && [ $((now_ts - snap_ts)) -le 3 ] && [ $((now_ts - snap_ts)) -ge -3 ]; then
    serve "$SNAP_FILE"
  fi
fi

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

# Linux 6.6: tc100_rtsp owns the cache (no getimage). It makes a new picture at once when
# /tmp/snapshot_request exists; wait ~1.5 s for it, then serve whatever picture is there.
if [ -f /tmp/linux66 ]; then
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
fi

if mkdir "$CACHE_LOCK_DIR" 2>/dev/null; then
  _read_ts
  tmp_img="/tmp/currentpic.cache.$$.$now_ts.jpg"
  if timeout 5 /mnt/bin/getimage > "$tmp_img" 2>/dev/null; then
    mv "$tmp_img" "$CACHE_FILE" 2>/dev/null || cat "$tmp_img" > "$CACHE_FILE"
    rm -f "$tmp_img" >/dev/null 2>&1 || true
    _read_ts
    [ "$now_ts" -gt 0 ] && printf '%s\n' "$now_ts" > "$CACHE_META_FILE"
    rmdir "$CACHE_LOCK_DIR" >/dev/null 2>&1 || true
    serve "$CACHE_FILE"
  fi
  rm -f "$tmp_img" >/dev/null 2>&1 || true
  rmdir "$CACHE_LOCK_DIR" >/dev/null 2>&1 || true
fi

wait_count=0
while [ "$wait_count" -lt 4 ]; do
  sleep 0.1
  [ -s "$CACHE_FILE" ] && serve "$CACHE_FILE"
  wait_count=$((wait_count + 1))
done

tmp_img="/tmp/currentpic.last.$$.jpg"
timeout 5 /mnt/bin/getimage > "$tmp_img" 2>/dev/null
( serve "$tmp_img" ); rm -f "$tmp_img"

