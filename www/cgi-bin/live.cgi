#!/bin/sh
# live.cgi              the camera's H.264 live video as fragmented MP4 (video/mp4), for the "Video" mode of the live view
#                       (scripts/index.bundle.min.js: fetch + Media Source Extensions). At most 2 viewers, 10 minutes each.
# live.cgi?info=1       JSON for the page: {"ok":1,"stream":"sub","codec":"avc1.42c01e","width":640,"height":360}
# Same transport as Listen (audio_stream.cgi): this script makes a FIFO /tmp/tc100_live/<pid>.fifo, tc100_rtsp
# (src/tc100rtsp/livemp4.c) finds it within half a second and writes an initialisation segment and then one moof+mdat per
# frame into it, starting at the next keyframe; cat copies it to the browser. tc100_rtsp encodes the stream while a viewer
# exists (the 640x360 sub-stream when it is H.264, else the main stream when it is H.264) and tells in
# /tmp/tc100_live/status what it can serve. When the browser goes away, or does not read for 1.5 s, tc100_rtsp closes
# and removes the FIFO.
# 415: neither stream is H.264 (the page keeps the JPEG view); 503: tc100_rtsp not running or starting, or 2 viewers already.
# A HEAD request only tells whether the video is possible. (TC100_LIVE_DIR is overridden by the host tests only.)
LIVE_DIR=${TC100_LIVE_DIR:-/tmp/tc100_live}
fail() {	# status text message
  printf 'Status: %s\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n' "$1"
  [ "$REQUEST_METHOD" = HEAD ] || printf '{"ok":0,"error":"%s"}\n' "$2"
  exit 0
}
pidof tc100_rtsp >/dev/null 2>&1 || fail "503 Service Unavailable" "tc100_rtsp is not running"
line=
[ -r "$LIVE_DIR/status" ] && read -r line < "$LIVE_DIR/status"
stream=; codec=; width=; height=
for kv in $line; do
  case "$kv" in
    stream=*) stream=${kv#stream=} ;;
    codec=*) codec=${kv#codec=} ;;
    width=*) width=${kv#width=} ;;
    height=*) height=${kv#height=} ;;
  esac
done
case "$stream" in
  main|sub) ;;
  none) fail "415 Unsupported Media Type" "no H.264 stream (both streams are H.265)" ;;
  *) fail "503 Service Unavailable" "the video is starting" ;;
esac
case "$codec" in avc1.[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;; *) fail "503 Service Unavailable" "the video is starting" ;; esac
case "$width$height" in *[!0-9]*|"") fail "503 Service Unavailable" "the video is starting" ;; esac
case "$QUERY_STRING" in
  *info=1*)
    printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n'
    [ "$REQUEST_METHOD" = HEAD ] || printf '{"ok":1,"stream":"%s","codec":"%s","width":%s,"height":%s}\n' "$stream" "$codec" "$width" "$height"
    exit 0 ;;
esac
command -v mkfifo >/dev/null 2>&1 || fail "503 Service Unavailable" "mkfifo missing"
n=0; for f in "$LIVE_DIR"/*.fifo; do [ -p "$f" ] && n=$((n + 1)); done
[ "$n" -lt 2 ] || fail "503 Service Unavailable" "too many viewers (2 at most)"
if [ "$REQUEST_METHOD" = HEAD ]; then
  printf 'Content-Type: video/mp4\r\nCache-Control: no-store\r\n\r\n'
  exit 0
fi
F="$LIVE_DIR/$$.fifo"
mkfifo "$F" 2>/dev/null || fail "503 Service Unavailable" "cannot create the video pipe"
trap 'rm -f "$F"' EXIT HUP INT TERM PIPE
printf 'Content-Type: video/mp4\r\nCache-Control: no-store, no-cache, must-revalidate\r\nPragma: no-cache\r\n\r\n'
# tc100_rtsp opens the FIFO within 0.5 s (the open of the read end waits for it) and ends the stream after 10 minutes;
# "timeout" bounds a wait that never ends
if command -v timeout >/dev/null 2>&1; then timeout 630 cat "$F"; else cat "$F"; fi
exit 0
