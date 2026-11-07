#!/bin/sh
# h265-step2.sh capture | run   — step 2 of the free H.265 encoder, on a TEST camera (2026-11-07; the owner's choice:
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
case "${1:-}" in
capture)
	OUT=${H265_CAP:-/tmp/h265cap}
	[ -x "$NEW/tc100_rtsp" ] && [ -f "$NEW/libakuio.so" ] || { echo "put tc100_rtsp and libakuio.so of this build in $NEW"; exit 1; }
	[ -r /proc/$(cat /var/run/v4l2rtspserver.pid 2>/dev/null)/cmdline ] || { echo "the video server is not running"; exit 1; }
	ARGS=$(tr '\0' ' ' < /proc/$(cat /var/run/v4l2rtspserver.pid)/cmdline | sed 's|^[^ ]*||; s|-A [^ ]*|-A '"$NEW"'/libakuio.so|')
	ENVS=$(tr '\0' '\n' < /proc/$(cat /var/run/v4l2rtspserver.pid)/environ | grep -E '^(LD_LIBRARY_PATH|RTSP_|TC100_)' | tr '\n' ' ')
	rm -rf "$OUT"; mkdir -p "$OUT"
	$CTL stop; sleep 2
	echo "tc100_rtsp $ARGS"
	( cd /tmp && env $ENVS AKUIO_CAPTURE="$OUT/c" AKUIO_CAPTURE_N=${H265_N:-6} RTSP_SAVE_FRAMES="$OUT/f" RTSP_SAVE_FRAMES_N=${H265_N:-6} "$NEW/tc100_rtsp" $ARGS > "$OUT/rtsp.log" 2>&1 ) &
	sleep 20
	kill $! 2>/dev/null; sleep 2; pkill -f "$NEW/tc100_rtsp" 2>/dev/null; sleep 1
	$CTL start
	ls -l "$OUT"; du -sh "$OUT"
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
*)
	echo "usage: $0 capture | run"; exit 2 ;;
esac
