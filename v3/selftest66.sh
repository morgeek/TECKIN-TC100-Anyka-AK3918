#!/bin/sh
# One-shot hardware self-test of the TC100 on Linux 6.6. Started by S39tc100-linux66 when the file
# tc100test/selftest exists on the SD card; writes everything to tc100test/selftest-<n>.log.
# Safe: reads, a few seconds of capture, and (only if tc100test/selftest-jpeg exists) one hardware
# JPEG encode through jpegenc. Nothing is written to flash.
SD=/mnt/sd
T=$SD/tc100test
n=1; while [ -e "$T/selftest-$n.log" ]; do n=$((n + 1)); done
LOG=$T/selftest-$n.log
exec > "$LOG" 2>&1

sec() { echo; echo "##### $*"; }
run() { echo "\$ $*"; sh -c "$*" 2>&1; echo "[exit $?]"; }
res() { echo "RESULT $1: $2"; }

echo "TC100 6.6 self-test $n"; date; uname -a
sec cmdline;     run 'cat /proc/cmdline'
sec memory;      run 'free; grep -iE "^(Cma|MemTotal|MemFree|SwapTotal)" /proc/meminfo; cat /proc/swaps'
sec devices;     run 'ls -l /dev/video* /dev/uio* /dev/snd/* /dev/watchdog* /dev/mmcblk* 2>&1'
sec platform;    run 'for d in /sys/bus/platform/devices/*; do [ -e $d/driver ] && echo "$(basename $d) -> $(basename $(readlink $d/driver))" || echo "$(basename $d) -> (none)"; done'
sec interrupts;  run 'cat /proc/interrupts'
sec dmesg;       run 'dmesg | grep -iE "ak39|venc|isp|vi |camera|sensor|f23|akmci|otg|rtl8|wlan|snd|codec|pcm|cma|zram|error|fail|warn" | tail -80'

# --- Wi-Fi
sec wifi; run 'ip addr show wlan0; ip route'
if ip route 2>/dev/null | grep -q default; then
  GW=$(ip route | awk '/default/ {print $3; exit}')
  if ping -c 3 -W 2 "$GW" >/dev/null 2>&1; then res wifi "ok (gateway answers)"; else res wifi "FAILED (no answer from gateway)"; fi
else res wifi "FAILED (no default route)"; fi

# --- video: V4L2 capture through the V3 streamer (software JPEG)
sec video
if [ -c /dev/video0 ]; then
  rm -f /tmp/stream.jpg
  S=$SD/bin/tc100_streamer; [ -x "$S" ] || S=$T/tc100_streamer
  if [ -x "$S" ]; then
    "$S" -d; sleep 6
    if [ -s /tmp/stream.jpg ]; then
      cp /tmp/stream.jpg "$T/selftest-$n-frame.jpg"
      res video "ok ($(wc -c < /tmp/stream.jpg) bytes, saved as selftest-$n-frame.jpg)"
    else res video "FAILED (streamer produced no picture)"; fi
    killall tc100_streamer 2>/dev/null
  else res video "SKIPPED (no tc100_streamer)"; fi
else res video "FAILED (no /dev/video0)"; fi

# --- audio
sec audio; run 'cat /proc/asound/cards; aplay -l; arecord -l'
if [ -e /proc/asound/cards ] && grep -q '[0-9]' /proc/asound/cards 2>/dev/null; then res audio "card present"; else res audio "FAILED (no sound card)"; fi

# --- encoder access
sec encoder
if [ -c /dev/uio0 ]; then
  res uio0 "device present"
  run 'cat /proc/interrupts | grep -iE "venc|encoder|uio"'
  J=$T/jpegenc; [ -x "$J" ] || J=$SD/bin/jpegenc
  if [ -f "$T/selftest-jpeg" ] && [ -x "$J" ]; then
    echo "hardware JPEG encode of a black 1920x1080 frame (the watchdog restarts the camera if the block hangs)"
    dd if=/dev/zero of=/tmp/black.nv12 bs=3110400 count=1 2>/dev/null
    sync
    timeout 15 "$J" --run -q 35 /tmp/black.nv12 1920 1080 /tmp/hw.jpg; rc=$?
    echo "[jpegenc exit $rc]"
    if [ -s /tmp/hw.jpg ]; then
      cp /tmp/hw.jpg "$T/selftest-$n-hw.jpg"; cp /tmp/hw.jpg.hw "$T/selftest-$n-hw.raw" 2>/dev/null
      head -c 4 /tmp/hw.jpg | od -An -tx1
      res jpeg "output $(wc -c < /tmp/hw.jpg) bytes (check the file selftest-$n-hw.jpg)"
    else res jpeg "FAILED (no output, exit $rc)"; fi
  else res jpeg "SKIPPED (create tc100test/selftest-jpeg to run it)"; fi
else res uio0 "FAILED (no /dev/uio0: ak39_venc missing from the kernel or the device tree)"; fi

# --- SD card, watchdog, load
sec misc; run 'mount | grep -E "mmc|sd"; uptime; cat /sys/class/watchdog/watchdog0/state 2>/dev/null'
sec dmesg_tail; run 'dmesg | tail -30'
echo; echo "self-test finished"; sync
