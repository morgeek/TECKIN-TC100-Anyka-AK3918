#!/bin/sh
# audio_stream.cgi[?type=mic]   the camera microphone as a WAV stream (8 kHz mono 16-bit), for "Listen" on the
# main page (scripts/ptt-audio.bundle.min.js). Linux 6.6 (3.0) only: ALSA hw:0,0 through arecord, at most 60 s.
# The ALSA capture device takes one reader: while tc100_rtsp serves its audio track it holds the microphone
# (its own arecord) and this answers 503; listen to the RTSP stream instead (VLC, Frigate).
# A HEAD request (the page's probe) only tells whether the microphone is free: 200 or 503.
unavailable() {
  printf 'Status: 503 Service Unavailable\r\nContent-Type: text/plain\r\nCache-Control: no-store\r\n\r\n'
  [ "$REQUEST_METHOD" = HEAD ] || echo "$1"
  exit 0
}
[ -f /tmp/linux66 ] || unavailable "not available on this firmware"
command -v arecord >/dev/null 2>&1 || unavailable "arecord missing"
[ -c /dev/snd/pcmC0D0c ] || unavailable "no capture device"
pidof arecord >/dev/null 2>&1 && unavailable "the microphone is used by the RTSP stream (audio track): listen to the stream in VLC or Frigate"
if [ "$REQUEST_METHOD" = HEAD ]; then
  printf 'Content-Type: audio/wav\r\nCache-Control: no-store\r\n\r\n'
  exit 0
fi
printf 'Content-Type: audio/wav\r\nCache-Control: no-store\r\n\r\n'
# RIFF/WAVE header with "endless" sizes, PCM 1 channel 8000 Hz 16 bit
printf 'RIFF\377\377\377\177WAVEfmt \020\000\000\000\001\000\001\000\100\037\000\000\200\076\000\000\002\000\020\000data\333\377\377\177'
# The capture start is delayed in the driver; no -F/-B (fixed 512-byte period, other values give I/O errors)
exec arecord -q -D hw:0,0 -f S16_LE -r 8000 -c 1 -t raw -d 60 2>/dev/null
