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
# sensor tuning (the camera's own isp.conf): without it the ISP runs untuned (colour cast, which the software white
# balance then has to correct on every frame). Checked before every start, not only at boot; in flash mode the copy
# the install hook made may only be on the card (/mnt/sd/config).
if [ ! -s /lib/firmware/anyka/isp.conf ]; then
  mkdir -p /lib/firmware/anyka
  ISPN=$(sed -n 's/^ISP_CONF=//p' /tmp/board.conf 2>/dev/null | head -n 1)
  for f in /vendor/isp.conf ${ISPN:+/mnt/config/$ISPN /mnt/sd/config/$ISPN} /mnt/config/isp_f23_mipi_2lane.conf \
      $TB/isp_f23_mipi_2lane.conf $TB/isp_f23_mipi2lane.conf /mnt/config/isp.conf /mnt/sd/config/isp_f23_mipi_2lane.conf; do
    [ -s "$f" ] && { cp "$f" /lib/firmware/anyka/isp.conf; break; }
  done
  [ -s /lib/firmware/anyka/isp.conf ] || echo "rtsp-launch: no sensor tuning file (isp.conf): the colours will be off" > /dev/console
fi
# Frame rate (Settings -> Streams & audio, rtspserver.conf [0] fps): one rate for both streams (they share the capture
# loop). Only 10, 12, 15, 20 and 25 are passed as -f; anything else (the 16 of older config files, an empty value)
# leaves tc100_rtsp at its default of 15.
fps_opt() { case "$1" in 10|12|15|20|25) echo "-f $1" ;; esac; }
CODEC=h265; KBPS=${RTSP_KBPS:-1500}; PORT=554; SUBCODEC=h264; SUBKBPS=400; ENCOPT=
# codec in rtspserver.conf (Video page): 0 = H.264, 2 = H.265 (1, written by older 6.6 boot scripts, = H.264)
if [ -f $CONF ]; then
  set -- $(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 0 codec 0 bps " " PORT 2>/dev/null)
  case "$1" in 0|1) CODEC=h264 ;; esac
  case "$2" in ''|*[!0-9]*) ;; *) KBPS=$2 ;; esac
  case "$3" in ''|*[!0-9]*) ;; *) PORT=$3 ;; esac
  set -- $(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 1 codec 1 bps 2>/dev/null)
  [ "$1" = 2 ] && SUBCODEC=h265
  case "$2" in ''|*[!0-9]*) ;; *) SUBKBPS=$2 ;; esac
  # Video page, advanced encoding: QP range (main stream values, both streams) and keyframe interval per stream.
  # Only valid values are passed (QP 10..51 with min <= max, GOP 1..300 frames); otherwise tc100_rtsp keeps its defaults.
  set -- $(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 0 minqp 0 maxqp 0 goplen 1 goplen 2>/dev/null)
  [ $# -eq 4 ] || set -- "" "" "" ""	# a missing key would shift the values
  # The values shipped before 3.0.1 (QP 20..51, GOP 64 / 32) were never applied: a camera still holding them keeps
  # the tested behaviour (QP 25..48, GOP 2 s) until someone sets other values on the Video page.
  [ "$1 $2" = "20 51" ] && set -- "" "" "$3" "$4"
  [ "$3" = 64 ] && [ "$4" = 32 ] && set -- "$1" "$2" "" ""
  case "$1$2" in *[!0-9]*|'') ;; *) [ "$1" -ge 10 ] && [ "$2" -le 51 ] && [ "$1" -le "$2" ] && ENCOPT="-q $1 -Q $2" ;; esac
  ENCOPT="$ENCOPT $(fps_opt "$(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 0 fps 2>/dev/null)")"
  case "$3" in ''|*[!0-9]*) ;; *) [ "$3" -ge 1 ] && [ "$3" -le 300 ] && ENCOPT="$ENCOPT -g $3" ;; esac
  case "$4" in ''|*[!0-9]*) ;; *) [ "$4" -ge 1 ] && [ "$4" -le 300 ] && ENCOPT="$ENCOPT -G $4" ;; esac
fi
# Settings: bit rate mode and smart encoding (Streams & audio, rtspserver.conf [0] vbr / smart: R11-01), the night
# parameter set and the low-light frame rate (Day/night, daynight.conf NIGHT_STYLE / LOWLIGHT_FPS: R12-01, R12-02).
# The older brmode / smartmode keys were never applied and are not read. config/rtsp.env, sourced later, overrides.
if [ -f $CONF ]; then
  set -- $(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 0 vbr 0 smart 2>/dev/null)
  [ $# -eq 2 ] || set -- "" ""
  case "$1" in 1) export RTSP_VBR=1 ;; esac
  case "$2" in 1|2) export RTSP_SMART=$2 ;; esac
fi
dnc() { sed -n "s/^$1=//p" /mnt/config/daynight.conf 2>/dev/null | tail -n 1; }
# the night parameter set is on unless switched off (rc15: R14-02 passed, the stock firmware always uses it)
[ "$(dnc NIGHT_STYLE)" = 0 ] || export RTSP_NIGHTSTYLE=1
[ "$(dnc LOWLIGHT_FPS)" = 1 ] && export RTSP_LOWLIGHT_FPS=1
# boot.conf: RTSP_SUBSTREAM (640x360 second stream on /video1, /ch1, /sub; 0 = off) and RTSP_AUDIO (G.711 track).
# The recording (REC_*), the sound level (sound_detection.conf) and the motion zones are read by tc100_rtsp itself.
bc() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}\$/\1/p" /mnt/config/boot.conf 2>/dev/null | tail -n 1; }
SUB=$(bc RTSP_SUBSTREAM); case "$SUB" in 0|no|off|false) SUB=0 ;; *) SUB=1 ;; esac
AUD=${RTSP_AUDIO:-$(bc RTSP_AUDIO)}; case "$AUD" in 0|no|off|false) AUD=0 ;; *) AUD=1 ;; esac
# recordings: /mnt/DCIM (the card; in flash mode a link to /mnt/sd/DCIM), what the Recordings page lists
REC_DIR=/mnt/DCIM
# microphone gain (Audio page, 0-15, passed as it is) -> codec "LineIn Capture Volume" (0-15)
V=$(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r " " volume 2>/dev/null)
case "$V" in ''|*[!0-9]*) ;; *) amixer -c 0 cset name="LineIn Capture Volume" "$V" >/dev/null 2>&1 ;; esac
stop_rtsp
w=0; while netstat -tan 2>/dev/null | grep -q ":$PORT .*LISTEN" && [ $w -lt 8 ]; do sleep 1; w=$((w+1)); done
# time zone for the clock overlay (first non-comment line of config/timezone.conf, POSIX TZ string)
TZV=$(grep -v '^#' /mnt/config/timezone.conf 2>/dev/null | grep -v '^$' | head -n 1); [ -n "$TZV" ] && export TZ="$TZV"
RTSP_LOG=/tmp/logs/tc100_rtsp.log; mkdir -p /tmp/logs
[ -f /mnt/config/rtsp.debug ] && RTSP_LOG=/dev/console
# the log in /tmp is capped by the server itself (RTSP_LOGFILE: above RTSP_LOGMAX, 256 KB, it is renamed to .1 and
# reopened): the file is emptied once here and opened for appending
if [ "$RTSP_LOG" != /dev/console ]; then export RTSP_LOGFILE="$RTSP_LOG"; : > "$RTSP_LOG"; fi
( cd /tmp && { set -a; [ -f /mnt/config/rtsp.env ] && . /mnt/config/rtsp.env; set +a; }
  LD_LIBRARY_PATH=/mnt/lib exec /tmp/tc100_rtsp -L /mnt/lib -c "$CODEC" -A /tmp/libakuio.so -p "$PORT" -b "$KBPS" \
    -u "${RTSP_USER:-root}" -w "$PWD_FILE" -a "$AUD" -s "$SUB" -C "$SUBCODEC" -B "$SUBKBPS" -R "$REC_DIR" \
    -S /var/run/sound_level $ENCOPT >>"$RTSP_LOG" 2>&1 ) &
# the subshell exec's tc100_rtsp: $! is the server's pid (no sleep and pidof needed to find it); pidof stays as a fallback
RPID=$!
[ -d /proc/$RPID ] || { sleep 1; RPID=$(pidof tc100_rtsp 2>/dev/null); RPID=${RPID%% *}; }
[ -n "$RPID" ] && echo -900 > /proc/$RPID/oom_score_adj 2>/dev/null
FLIP=$(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r " " imageflip 2>/dev/null)
/mnt/bin/setconf -k f -v ${FLIP:-0} 2>/dev/null || true
( sleep 3; /mnt/bin/setconf -k f -v ${FLIP:-0} 2>/dev/null ) &
# the vendor scripts (health, MQTT bridge, capability check) use this pid file as "RTSP server is up"
echo "$RPID" > /var/run/v4l2rtspserver.pid
exit 0
