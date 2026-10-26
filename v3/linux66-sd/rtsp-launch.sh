#!/bin/sh
# (Re)start the free RTSP server tc100_rtsp with the settings of config/rtspserver.conf (what the web UI writes:
# codec, bit rate, port, microphone gain). Used by the boot script and by controlscripts/rtsp-h26x
# (Services page, "Apply" buttons).
TB=/mnt/tc100test; CONF=/mnt/config/rtspserver.conf; PWD_FILE=/mnt/config/user.pwd
[ -f $TB/tc100_rtsp ] || exit 1
# stop: SIGTERM first, so that the recorder closes its file (index, duration); SIGKILL after 5 s
stop_rtsp() { killall tc100_rtsp 2>/dev/null || return 0; i=0; while pidof tc100_rtsp >/dev/null && [ $i -lt 10 ]; do sleep 0.5; i=$((i+1)); done; killall -9 tc100_rtsp 2>/dev/null; return 0; }
cmp -s $TB/tc100_rtsp /tmp/tc100_rtsp 2>/dev/null || { stop_rtsp; cp $TB/tc100_rtsp /tmp/tc100_rtsp && chmod +x /tmp/tc100_rtsp; }
[ -f /tmp/libakuio.so ] || cp $TB/libakuio.so /tmp/libakuio.so
[ -e /lib/ld-uClibc.so.0 ] || ln -sf /mnt/lib/ld-uClibc-0.9.33.2.so /lib/ld-uClibc.so.0
CODEC=h265; KBPS=${RTSP_KBPS:-1500}; PORT=554; SUBCODEC=h264; SUBKBPS=400
# codec in rtspserver.conf (Video page): 0 = H.264, 2 = H.265 (1, written by older 6.6 boot scripts, = H.264)
if [ -f $CONF ]; then
  set -- $(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 0 codec 0 bps " " PORT 2>/dev/null)
  case "$1" in 0|1) CODEC=h264 ;; esac
  case "$2" in ''|*[!0-9]*) ;; *) KBPS=$2 ;; esac
  case "$3" in ''|*[!0-9]*) ;; *) PORT=$3 ;; esac
  set -- $(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 1 codec 1 bps 2>/dev/null)
  [ "$1" = 2 ] && SUBCODEC=h265
  case "$2" in ''|*[!0-9]*) ;; *) SUBKBPS=$2 ;; esac
fi
# boot.conf: RTSP_SUBSTREAM (640x360 second stream on /video1, /ch1, /sub; 0 = off) and RTSP_AUDIO (G.711 track).
# The recording (REC_*), the sound level (sound_detection.conf) and the motion zones are read by tc100_rtsp itself.
bc() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}\$/\1/p" /mnt/config/boot.conf 2>/dev/null | tail -n 1; }
SUB=$(bc RTSP_SUBSTREAM); case "$SUB" in 0|no|off|false) SUB=0 ;; *) SUB=1 ;; esac
AUD=${RTSP_AUDIO:-$(bc RTSP_AUDIO)}; case "$AUD" in 0|no|off|false) AUD=0 ;; *) AUD=1 ;; esac
# recordings: /mnt/DCIM (the card; in flash mode a link to /mnt/sd/DCIM), what the Recordings page lists
REC_DIR=/mnt/DCIM
# microphone gain (Audio page, 0-12) -> codec "LineIn Capture Volume" (0-15)
V=$(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r " " volume 2>/dev/null)
case "$V" in ''|*[!0-9]*) ;; *) amixer -c 0 cset name="LineIn Capture Volume" "$V" >/dev/null 2>&1 ;; esac
stop_rtsp
w=0; while netstat -tan 2>/dev/null | grep -q ":$PORT .*LISTEN" && [ $w -lt 8 ]; do sleep 1; w=$((w+1)); done
# time zone for the clock overlay (first non-comment line of config/timezone.conf, POSIX TZ string)
TZV=$(grep -v '^#' /mnt/config/timezone.conf 2>/dev/null | grep -v '^$' | head -n 1); [ -n "$TZV" ] && export TZ="$TZV"
RTSP_LOG=/tmp/logs/tc100_rtsp.log; mkdir -p /tmp/logs
[ -f /mnt/config/rtsp.debug ] && RTSP_LOG=/dev/console
( cd /tmp && { set -a; [ -f /mnt/config/rtsp.env ] && . /mnt/config/rtsp.env; set +a; }
  LD_LIBRARY_PATH=/mnt/lib exec /tmp/tc100_rtsp -c "$CODEC" -A /tmp/libakuio.so -p "$PORT" -b "$KBPS" \
    -u "${RTSP_USER:-root}" -w "$PWD_FILE" -a "$AUD" -s "$SUB" -C "$SUBCODEC" -B "$SUBKBPS" -R "$REC_DIR" \
    -S /var/run/sound_level >"$RTSP_LOG" 2>&1 ) &
sleep 2
for pid in $(pidof tc100_rtsp 2>/dev/null); do echo -900 > /proc/$pid/oom_score_adj 2>/dev/null; done
# the vendor scripts (health, MQTT bridge, capability check) use this pid file as "RTSP server is up"
pidof tc100_rtsp 2>/dev/null | awk '{print $1}' > /var/run/v4l2rtspserver.pid
exit 0
