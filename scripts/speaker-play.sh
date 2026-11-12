#!/bin/sh
# speaker-play.sh FILE [VOLUME]   play a clip on the camera speaker (Linux 6.6 / 3.0, ALSA).
#   FILE    *.pcm = raw 8 kHz mono signed 16-bit little endian (push-to-talk uploads, custom sounds),
#           *.alaw = raw 8 kHz mono G.711 A-law (the built-in clips of the flash image, converted at build time),
#           *.wav = any WAV aplay reads,
#           -     = raw PCM as above from standard input (tc100_rtsp's two-way audio: the sound a client sends over
#                   RTSP; the clip ends when the input does),
#           -hold = no sound from this script: tc100_rtsp writes the sound itself to the playback device (RTSP_AUDIO_AEC=1,
#                   echo cancellation needs to know what was written). The script only does what surrounds the sound:
#                   the lock, the volume, the amplifier; it creates /tmp/speaker-hold.ready once the amplifier is on and
#                   waits until its standard input is closed (then the amplifier goes off and the lock is released).
#   VOLUME  0-100 (default: config/pttvolume.conf, else 90), set on the codec's "Headphone Playback Volume".
# One player at a time, the web push-to-talk and tc100_rtsp's two-way audio alike: the lock below (mkdir) makes the second
# one exit with status 3 ("busy"); upload_audio.cgi looks at it too.
# The codec takes stereo only on playback: "plughw" lets ALSA duplicate the mono samples. The capture side
# (tc100_rtsp's arecord) is a separate substream: the RTSP stream keeps running.
# Amplifier: GPIO 14 (526 on 6.6). The codec driver drives it itself when the device tree hands it the pin
# (speak-gpios); when the pin is free, it is driven here around the clip, active level from boot.conf
# SPEAKER_AMP_ACTIVE (0 = active low, the TC100 board as seen on 2.x; 1 = active high).
F=$1; V=$2
[ "$F" = - ] || [ "$F" = -hold ] || [ -r "$F" ] || { echo "no file: $F" >&2; exit 1; }
case "$V" in ''|*[!0-9]*) V=$(head -n 1 /mnt/config/pttvolume.conf 2>/dev/null) ;; esac
case "$V" in ''|*[!0-9]*) V=90 ;; esac
[ "$V" -gt 100 ] && V=100
[ "$F" = -hold ] || command -v aplay >/dev/null 2>&1 || { echo "no aplay" >&2; exit 2; }

LOCK=/tmp/speaker-play.lock
mkdir "$LOCK" 2>/dev/null || { echo "busy" >&2; exit 3; }
# INT / TERM end the script (the EXIT trap removes the lock): a trap that only removed the lock let the script go on
# and start aplay without it (review 2026-11-11, C5)
trap 'amp 0; rm -f /tmp/speaker-hold.ready; rmdir "$LOCK" 2>/dev/null' EXIT
trap 'exit 143' INT TERM

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

amixer -q -D hw:0 cset name='Headphone Playback Volume' "${V}%" >/dev/null 2>&1
amp 1
case "$F" in
  -hold) : > /tmp/speaker-hold.ready; cat >/dev/null ;;
  *.wav|*.WAV) aplay -q -D plughw:0,0 "$F" ;;
  *.alaw) aplay -q -D plughw:0,0 -t raw -f A_LAW -r 8000 -c 1 "$F" ;;
  *) aplay -q -D plughw:0,0 -t raw -f S16_LE -r 8000 -c 1 "$F" ;;
esac
rc=$?
exit $rc
