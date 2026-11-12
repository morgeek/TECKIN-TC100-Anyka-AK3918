#!/bin/sh
# v3/dev/aec-measure.sh [PROBE]   ON THE CAMERA: play the probe on the speaker while the microphone records, at volumes 50, 90
# and 100 (docs/linux-port/audio-aec-measure.md). Nothing is written to the flash: everything goes to /tmp (RAM).
# The RTSP server is stopped for the measurement (it holds the microphone) and started again at the end, by the same control
# script as the web UI and the boot (controlscripts/rtsp-h26x start -> rtsp-launch.sh, same arguments and rtsp.env).
# Needs the probe on the camera (made on the computer with v3/dev/aec-probe.py make): default /tmp/aec-probe.pcm.
# Results: /tmp/aec-mic-50.raw, -90, -100 (S16_LE, 8 kHz, mono) and /tmp/aec-measure.txt (dmesg rates, volumes, sizes).
PROBE=${1:-/tmp/aec-probe.pcm}
[ -r "$PROBE" ] || { echo "no probe: $PROBE" >&2; exit 1; }
command -v arecord >/dev/null 2>&1 && command -v aplay >/dev/null 2>&1 || { echo "arecord and aplay are needed" >&2; exit 1; }
OUT=/tmp/aec-measure.txt
SECS=$(( $(wc -c < "$PROBE") / 16000 + 3 ))
restart() { sh /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1; echo "rtsp server: $(sh /mnt/controlscripts/rtsp-h26x status 2>&1 | head -n 1)" | tee -a "$OUT"; }
trap restart EXIT
{
  echo "== $(date) $(head -n 1 /mnt/VERSION 2>/dev/null) probe $PROBE (${SECS}s of recording)"
  echo "== kernel rates (the ADC and the DAC both divide the PLL; an adaptive filter cannot follow their difference)"
  dmesg | grep -i "actual sample rate"
  echo "== pttvolume.conf: $(head -n 1 /mnt/config/pttvolume.conf 2>/dev/null)"
} | tee "$OUT"
sh /mnt/controlscripts/rtsp-h26x stop >/dev/null 2>&1
sleep 1
for V in 50 90 100; do
  rm -f /tmp/aec-mic-$V.raw
  arecord -q -D hw:0,0 -f S16_LE -r 8000 -c 1 -t raw -d "$SECS" /tmp/aec-mic-$V.raw &
  sleep 1
  sh /mnt/scripts/speaker-play.sh "$PROBE" "$V"
  rc=$?
  wait
  echo "volume $V: $(wc -c < /tmp/aec-mic-$V.raw) bytes, speaker-play.sh status $rc" | tee -a "$OUT"
  sleep 1
done
dmesg | grep -i "actual sample rate" | tail -n 4 | tee -a "$OUT"
echo "copy back: scp root@CAMERA:/tmp/aec-mic-*.raw root@CAMERA:/tmp/aec-measure.txt ."
