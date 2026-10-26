#!/bin/sh
# speaker-play.sh FILE [VOLUME]   play a clip on the camera speaker (Linux 6.6 / 3.0, ALSA).
#   FILE    *.pcm = raw 8 kHz mono signed 16-bit little endian (push-to-talk uploads, sounds/*.pcm),
#           *.wav = any WAV aplay reads.
#   VOLUME  0-100 (default: config/pttvolume.conf, else 90), set on the codec's "Headphone Playback Volume".
# The codec takes stereo only on playback: "plughw" lets ALSA duplicate the mono samples. The capture side
# (tc100_rtsp's arecord) is a separate substream: the RTSP stream keeps running.
# Amplifier: GPIO 14 (526 on 6.6). The codec driver drives it itself when the device tree hands it the pin
# (speak-gpios); when the pin is free, it is driven here around the clip, active level from boot.conf
# SPEAKER_AMP_ACTIVE (0 = active low, the TC100 board as seen on 2.x; 1 = active high).
F=$1; V=$2
[ -r "$F" ] || { echo "no file: $F" >&2; exit 1; }
case "$V" in ''|*[!0-9]*) V=$(head -n 1 /mnt/config/pttvolume.conf 2>/dev/null) ;; esac
case "$V" in ''|*[!0-9]*) V=90 ;; esac
[ "$V" -gt 100 ] && V=100
command -v aplay >/dev/null 2>&1 || { echo "no aplay" >&2; exit 2; }

LOCK=/tmp/speaker-play.lock
mkdir "$LOCK" 2>/dev/null || { echo "busy" >&2; exit 3; }
trap 'amp 0; rmdir "$LOCK" 2>/dev/null' EXIT INT TERM

ACT=$(sed -n 's/^SPEAKER_AMP_ACTIVE="\{0,1\}\([01]\)"\{0,1\}$/\1/p' /mnt/config/boot.conf 2>/dev/null | tail -n 1)
ACT=${ACT:-0}
G=/sys/class/gpio/gpio526
OWN=0
if [ ! -d $G ] && echo 526 > /sys/class/gpio/export 2>/dev/null; then OWN=1; fi
[ -d $G ] && [ -f /tmp/speaker-amp.gpio ] && OWN=1     # exported by an earlier run
[ "$OWN" = 1 ] && { : > /tmp/speaker-amp.gpio; echo out > $G/direction 2>/dev/null; }
amp() {  # amp 1|0
  [ "$OWN" = 1 ] || return 0
  if [ "$1" = 1 ]; then echo "$ACT" > $G/value; else echo $((1 - ACT)) > $G/value; fi 2>/dev/null
}

amixer -q -c 0 cset name='Headphone Playback Volume' "${V}%" >/dev/null 2>&1
amp 1
case "$F" in
  *.wav|*.WAV) aplay -q -D plughw:0,0 "$F" ;;
  *) aplay -q -D plughw:0,0 -t raw -f S16_LE -r 8000 -c 1 "$F" ;;
esac
rc=$?
exit $rc
