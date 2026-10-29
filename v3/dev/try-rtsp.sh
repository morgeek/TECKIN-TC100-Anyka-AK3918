#!/bin/sh
# v3/dev/try-rtsp.sh CAMERA BINARY [VAR=value ...]   measure a test build of tc100_rtsp on a 3.0 camera.
#
# From a computer on the camera's network. Asks the camera password itself (ssh, once: connection sharing); nothing
# is stored. Nothing is written to the flash: the test binary and the profiler go to /tmp (RAM), and the stock server
# is started again at the end (rtsp-launch.sh). The RTSP stream stops for about 40 s.
#   1. per-thread CPU for 10 s with the running server (scripts/cpu-profile.sh), and its last STAT lines;
#   2. the test binary with the same arguments, plus the VAR=value given (e.g. RTSP_ZEROCOPY=1): its first log lines
#      (capture mode), its STAT lines (pp_ms = main picture post-processing, sub_ms = sub picture, per 5 s) and a
#      second CPU profile;
#   3. the stock server again.
# Output on the terminal and in try-rtsp-<camera>-<time>.txt in the current folder.
#   make -C src/tc100rtsp && sh v3/dev/try-rtsp.sh 192.168.1.11 src/tc100rtsp/tc100_rtsp
#   sh v3/dev/try-rtsp.sh 192.168.1.11 src/tc100rtsp/tc100_rtsp RTSP_ZEROCOPY=1
CAM=${1:?usage: try-rtsp.sh CAMERA BINARY [VAR=value ...]}; BIN=${2:?binary}; shift 2
HERE=$(cd "$(dirname "$0")/../.." && pwd)
[ -f "$BIN" ] || { echo "$BIN: no such file" >&2; exit 1; }
EXTRA="$*"
OUT=try-rtsp-$CAM-$(date +%Y%m%d-%H%M%S).txt
CP=/tmp/tc100-cm-$$
SSH="ssh -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o ControlPath=$CP -o ControlPersist=120 root@$CAM"
{
echo "== $(date) camera $CAM, binary $BIN ($(md5sum < "$BIN" | cut -d' ' -f1)) ${EXTRA:+with $EXTRA}"
$SSH 'cat > /tmp/cpu-profile.sh' < "$HERE/scripts/cpu-profile.sh" || exit 1
$SSH 'cat > /tmp/tc100_rtsp.test && chmod +x /tmp/tc100_rtsp.test' < "$BIN" || exit 1
$SSH "EXTRA='$EXTRA' sh -s" <<'EOF'
echo "== version: $(head -n 1 /mnt/VERSION 2>/dev/null), board $(cat /tmp/board 2>/dev/null), uptime $(cut -d' ' -f1 /proc/uptime) s"
echo "== BASELINE STAT (running server)"; grep STAT /tmp/logs/tc100_rtsp.log 2>/dev/null | tail -n 2
echo "== BASELINE per-thread CPU, 10 s"; sh /tmp/cpu-profile.sh 10 threads
OLD=$(pidof tc100_rtsp | awk '{ print $1 }')
[ -n "$OLD" ] || { echo "no tc100_rtsp running"; exit 1; }
ARGS=$(tr '\0' '\n' < /proc/$OLD/cmdline | tail -n +2 | tr '\n' ' ')
echo "== args: $ARGS"
killall tc100_rtsp; i=0; while pidof tc100_rtsp >/dev/null && [ $i -lt 10 ]; do sleep 1; i=$((i + 1)); done
killall -9 tc100_rtsp 2>/dev/null
mkdir -p /tmp/logs
( cd /tmp && env $EXTRA LD_LIBRARY_PATH=/mnt/lib /tmp/tc100_rtsp.test $ARGS > /tmp/logs/tc100_rtsp.test.log 2>&1 ) &
sleep 25
echo "== TEST: first log lines"; head -n 8 /tmp/logs/tc100_rtsp.test.log
echo "== TEST: STAT"; grep STAT /tmp/logs/tc100_rtsp.test.log | tail -n 3
echo "== TEST per-thread CPU, 10 s"; sh /tmp/cpu-profile.sh 10 threads
echo "== free memory"; grep -E 'MemFree|MemAvailable|CmaFree' /proc/meminfo
echo "== restoring the running server"
killall tc100_rtsp.test 2>/dev/null; sleep 2; killall -9 tc100_rtsp.test 2>/dev/null
sh /mnt/tc100test/rtsp-launch.sh > /dev/null 2>&1
sleep 5; echo "tc100_rtsp: $(pidof tc100_rtsp)"; rm -f /tmp/tc100_rtsp.test
EOF
echo "== done"
} 2>&1 | tee "$OUT"
ssh -O exit -o ControlPath=$CP root@$CAM 2>/dev/null
echo "saved: $OUT"
