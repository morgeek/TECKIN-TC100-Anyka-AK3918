#!/bin/sh
# audio_stream.cgi[?type=mic]   the camera microphone as a WAV stream (8 kHz mono 16-bit), for "Listen" on the
# main page (scripts/ptt-audio.bundle.min.js). at most 60 s.
# The ALSA capture device takes one reader and tc100_rtsp's arecord is it, so the sound comes from tc100_rtsp: this
# script makes a FIFO /tmp/tc100_listen/<pid>.fifo, tc100_rtsp (src/tc100rtsp/alisten.c) finds it within half a second and
# writes the raw PCM (S16_LE) into it for as long as it is read, at most 60 s; cat copies it to the browser after a WAV
# header. The microphone runs only while somebody listens, records or streams audio. When the browser goes away tc100_rtsp
# notices the unread FIFO within 2 s and closes it. Works whether or not the RTSP stream has its audio track.
# Without tc100_rtsp (not running) the microphone is read directly (arecord), when nothing else holds it.
# A HEAD request (the page's probe) only tells whether listening is possible: 200 or 503.
# (the two variables are overridden only by the host tests)
LISTEN_DIR=${TC100_LISTEN_DIR:-/tmp/tc100_listen}
SND_DEV=${TC100_SND_DEV:-/dev/snd/pcmC0D0c}
unavailable() {
  printf 'Status: 503 Service Unavailable\r\nContent-Type: text/plain\r\nCache-Control: no-store\r\n\r\n'
  [ "$REQUEST_METHOD" = HEAD ] || echo "$1"
  exit 0
}
wav_headers() {
  printf 'Content-Type: audio/wav\r\nCache-Control: no-store\r\n\r\n'
  [ "$REQUEST_METHOD" = HEAD ] && exit 0
  # RIFF/WAVE header with "endless" sizes, PCM 1 channel 8000 Hz 16 bit
  printf 'RIFF\377\377\377\177WAVEfmt \020\000\000\000\001\000\001\000\100\037\000\000\200\076\000\000\002\000\020\000data\333\377\377\177'
}
if [ -d "$LISTEN_DIR" ] && pidof tc100_rtsp >/dev/null 2>&1; then
  command -v mkfifo >/dev/null 2>&1 || unavailable "mkfifo missing"
  command -v arecord >/dev/null 2>&1 || unavailable "arecord missing"
  [ -c "$SND_DEV" ] || unavailable "no capture device"
  n=0; for f in "$LISTEN_DIR"/*.fifo; do [ -p "$f" ] && n=$((n + 1)); done
  [ "$n" -lt 3 ] || unavailable "too many listeners (3 at most)"
  [ "$REQUEST_METHOD" = HEAD ] && { wav_headers; exit 0; }
  F="$LISTEN_DIR/$$.fifo"
  mkfifo "$F" 2>/dev/null || unavailable "cannot create the audio pipe"
  trap 'rm -f "$F"' EXIT HUP INT TERM PIPE
  wav_headers
  # tc100_rtsp opens the FIFO within 0.5 s (the open of the read end waits for it); "timeout" bounds a wait that never ends
  if command -v timeout >/dev/null 2>&1; then timeout 70 cat "$F"; else cat "$F"; fi
  exit 0
fi
command -v arecord >/dev/null 2>&1 || unavailable "arecord missing"
[ -c "$SND_DEV" ] || unavailable "no capture device"
pidof arecord >/dev/null 2>&1 && unavailable "the microphone is in use"
wav_headers
[ "$REQUEST_METHOD" = HEAD ] && exit 0
# The capture start is delayed in the driver; no -F/-B (fixed 512-byte period, other values give I/O errors)
exec arecord -q -D hw:0,0 -f S16_LE -r 8000 -c 1 -t raw -d 60 2>/dev/null
