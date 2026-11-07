#!/bin/sh
# h265-step2.sh capture | trace | free | restore | run | live | live264   — steps 2 and 3 of the free H.265 encoder, on a TEST camera (2026-11-07; the owner's choice:
# IPCAM2, after the 7-day watch). Video stops for about a minute; nothing is written to flash or to /mnt/config.
#
#   capture  stop the video service (rtsp-h26x stop: no setting changes), start tc100_rtsp by hand for 20 s with
#            AKUIO_CAPTURE (libakuio) and RTSP_SAVE_FRAMES (tc100_rtsp): /tmp/h265cap/c.<n>.cap, f.<n>.h26x, f.log;
#            then the video service again. Needs the libakuio.so and tc100_rtsp of this build in /tmp/h265new/.
#            Then, on a computer: python3 src/h265enc/capture.py DIR --out DIR/in
#   run      stop the video service, h265enc --run on the inputs (/tmp/h265in: list.bin, tables.bin, work.bin,
#            small.bin, params.bin, in.nv12): /tmp/h265out/o.h265 (+ .raw, .list), then the video service again.
#            Then: ffprobe o.h265; ffmpeg -i o.h265 o.png; compare with the vendor's f.0.h26x.
# The captures are data read from the camera's vendor encoder: they stay on the test machine, never in git.
set -u
NEW=${H265_NEW:-/tmp/h265new}
CTL=/mnt/controlscripts/rtsp-h26x
# stop the copies of a program started from $NEW (busybox has no pkill)
# and wait until they are gone (up to 15 s): the video service started too early finds the camera busy and exits
stopnew() {
	for p in $(pidof "$1"); do [ "$(readlink /proc/$p/exe)" = "$NEW/$1" ] && kill "$p"; done
	i=0; while [ $i -lt 15 ]; do
		left=0; for p in $(pidof "$1"); do [ "$(readlink /proc/$p/exe)" = "$NEW/$1" ] && left=1; done
		[ $left = 0 ] && break; sleep 1; i=$((i + 1))
	done
	sleep 1
}
case "${1:-}" in
capture)
	OUT=${H265_CAP:-/tmp/h265cap}
	[ -x "$NEW/tc100_rtsp" ] && [ -f "$NEW/libakuio.so" ] || { echo "put tc100_rtsp and libakuio.so of this build in $NEW"; exit 1; }
	VP=$(cat /var/run/v4l2rtspserver.pid 2>/dev/null); [ -r "/proc/$VP/cmdline" ] || VP=$(pidof tc100_rtsp | cut -d' ' -f1)
	[ -n "$VP" ] && [ -r "/proc/$VP/cmdline" ] || { echo "the video server is not running"; exit 1; }
	ARGS=$(tr '\0' ' ' < "/proc/$VP/cmdline" | sed 's|^[^ ]*||; s|-A [^ ]*|-A '"$NEW"'/libakuio.so|')
	ENVS=$(tr '\0' '\n' < "/proc/$VP/environ" | grep -E '^(LD_LIBRARY_PATH|RTSP_)[A-Za-z0-9_]*=[^ ]*$' | tr '\n' ' ')	# no value with a space (word splitting)
	rm -rf "$OUT"; mkdir -p "$OUT"
	$CTL stop; sleep 2
	echo "tc100_rtsp $ARGS"
	( cd /tmp && env $ENVS AKUIO_CAPTURE="$OUT/c" AKUIO_CAPTURE_N=${H265_N:-6} AKUIO_CAPTURE_STREAM=${H265_STREAM:-262144} AKUIO_CAPTURE_WIDTH=${H265_WIDTH:-0} RTSP_SAVE_FRAMES="$OUT/f" RTSP_SAVE_FRAMES_N=${H265_N:-6} "$NEW/tc100_rtsp" $ARGS > "$OUT/rtsp.log" 2>&1 ) &
	sleep "${H265_SECS:-20}"
	kill $! 2>/dev/null; sleep 2; stopnew tc100_rtsp
	$CTL start
	ls -l "$OUT"; du -sh "$OUT"
	;;
trace)
	# the vendor library's hardware accesses: tc100_rtsp with venctrace.so preloaded (src/h265enc/venctrace), for
	# H265_SECS seconds: /tmp/venc.trc (python3 src/h265enc/hwseq.py reads it)
	[ -f "$NEW/venctrace.so" ] || { echo "put venctrace.so of this build in $NEW"; exit 1; }
	VP=$(cat /var/run/v4l2rtspserver.pid 2>/dev/null); [ -r "/proc/$VP/cmdline" ] || VP=$(pidof tc100_rtsp | cut -d' ' -f1)
	[ -n "$VP" ] && [ -r "/proc/$VP/cmdline" ] || { echo "the video server is not running"; exit 1; }
	BIN=$(readlink "/proc/$VP/exe"); ARGS=$(tr '\0' ' ' < "/proc/$VP/cmdline" | sed 's|^[^ ]*||')
	ENVS=$(tr '\0' '\n' < "/proc/$VP/environ" | grep -E '^(LD_LIBRARY_PATH|RTSP_)[A-Za-z0-9_]*=[^ ]*$' | tr '\n' ' ')
	rm -f /tmp/venc.trc
	$CTL stop; sleep 2
	( cd /tmp && env $ENVS LD_PRELOAD="$NEW/venctrace.so" VENC_TRACE=/tmp/venc VENC_TRACE_KB=${H265_KB:-1024} "$BIN" $ARGS > /tmp/venctrace.log 2>&1 ) &
	sleep "${H265_SECS:-20}"
	kill $! 2>/dev/null; sleep 2; for p in $(pidof tc100_rtsp); do kill "$p"; done; sleep 2
	$CTL start
	ls -l /tmp/venc.trc; tail -3 /tmp/venctrace.log
	;;
free)
	# tc100_rtsp of this build with RTSP_FREE_ENC=1 (the free encoders), the video service's arguments and settings,
	# left running in the background (log /tmp/free.log) until "restore"
	[ -x "$NEW/tc100_rtsp" ] && [ -f "$NEW/libakuio.so" ] || { echo "put tc100_rtsp and libakuio.so of this build in $NEW"; exit 1; }
	VP=$(cat /var/run/v4l2rtspserver.pid 2>/dev/null); [ -r "/proc/$VP/cmdline" ] || VP=$(pidof tc100_rtsp | cut -d' ' -f1)
	[ -n "$VP" ] && [ -r "/proc/$VP/cmdline" ] || { echo "the video server is not running"; exit 1; }
	ARGS=$(tr '\0' ' ' < "/proc/$VP/cmdline" | sed 's|^[^ ]*||; s|-A [^ ]*|-A '"$NEW"'/libakuio.so|')
	ENVS=$(tr '\0' '\n' < "/proc/$VP/environ" | grep -E '^(LD_LIBRARY_PATH|RTSP_)[A-Za-z0-9_]*=[^ ]*$' | grep -v '^RTSP_LOGFILE=' | tr '\n' ' ')
	$CTL stop; sleep 2; stopnew tc100_rtsp
	echo "tc100_rtsp $ARGS"
	[ "${H265_NOSUB:-0}" = 1 ] && ARGS=$(echo "$ARGS" | sed 's/ -s 1 / -s 0 /')
	( cd /tmp && env $ENVS RTSP_FREE_ENC=1 ${H265_FREE_ENV:-} "$NEW/tc100_rtsp" $ARGS > /tmp/free.log 2>&1 ) &
	sleep 8; grep -E "encoder|free" /tmp/free.log | head -8
	;;
restore)
	stopnew tc100_rtsp
	$CTL start; sleep 5
	pidof tc100_rtsp >/dev/null || { sleep 3; $CTL start; sleep 5; }
	pidof tc100_rtsp
	;;
run)
	IN=${H265_IN:-/tmp/h265in}; OUT=${H265_OUT:-/tmp/h265out}
	[ -x "$NEW/h265enc" ] || { echo "put h265enc of this build in $NEW"; exit 1; }
	rm -rf "$OUT"; mkdir -p "$OUT"
	$CTL stop; sleep 2
	QP=$(od -An -tu1 -j14 -N1 "$IN/list.bin" | tr -d ' ')	# the vendor's own QP of that IDR (word 3 bits 16-23)
	"$NEW/h265enc" --run -q "${H265_QP:-$QP}" --params "$IN/params.bin" "$IN" "$IN/in.nv12" "$OUT/o.h265" 2>&1 | tee "$OUT/run.log"
	$CTL start
	ls -l "$OUT"
	;;
live)
	# step 3: h265live encodes N pictures (IDR then P) straight from the ISP, without the vendor libraries
	IN=${H265_IN:-/tmp/h265in}; OUT=${H265_OUT:-/tmp/h265out}
	[ -x "$NEW/h265live" ] || { echo "put h265live of this build in $NEW"; exit 1; }
	mkdir -p "$OUT"
	$CTL stop; sleep 2
	timeout 60 "$NEW/h265live" -n "${H265_FRAMES:-50}" -q "${H265_QP:-32}" ${H265_KBPS:+-b $H265_KBPS} -s 15 "$IN" "$OUT/live.h265" 2>&1 | tee "$OUT/live.log" | tail -3
	$CTL start
	ls -l "$OUT/live.h265"
	;;
live264)
	# the H.264 640x360 sub stream: h264live, from the ISP sub channel, without the vendor libraries
	OUT=${H265_OUT:-/tmp/h265out}
	[ -x "$NEW/h264live" ] || { echo "put h264live of this build in $NEW"; exit 1; }
	mkdir -p "$OUT"
	$CTL stop; sleep 2
	timeout 60 "$NEW/h264live" -n "${H265_FRAMES:-50}" -q "${H265_QP:-32}" ${H265_KBPS:+-b $H265_KBPS} -s 15 "$OUT/live.h264" 2>&1 | tee "$OUT/live264.log" | tail -3
	$CTL start
	ls -l "$OUT/live.h264"
	;;
*)
	echo "usage: $0 capture | trace | free | restore | run | live | live264"; exit 2 ;;
esac
