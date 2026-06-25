#!/bin/sh

# Audio streaming CGI — microphone → browser (listen direction).
#
# STATUS: Non-functional on AK3918 hardware.
#
# The AK3918 uses a proprietary Anyka audio framework. There is no ALSA
# userspace (no arecord, no /dev/snd/) and no ak_ai_demo binary in this
# firmware distribution. All find_audio_capture_bin() calls will fail and
# this endpoint will always return 503 AUDIO_CAPTURE_UNAVAILABLE.
#
# To enable listen support in the future, either:
#   a) obtain the Anyka audio input binary (ak_ai_demo or equivalent), or
#   b) build ffmpeg with AK3918 audio capture support and pipe its output.
#
# The frontend (ptt-audio.js) detects the 503 and disables the Listen button.

. /mnt/www/cgi-bin/func.cgi
. /mnt/scripts/common_functions.sh
. /mnt/scripts/event-logger.sh

export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'

# Timeouts and limits
AUDIO_STREAM_TIMEOUT_SECONDS=300
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
AUDIO_BIT_DEPTH=16
AUDIO_BUFFER_SIZE=2048
MAX_STREAM_CLIENTS=2

AUDIO_STREAM_LOCK_DIR="/tmp/audio-stream.lock"
AUDIO_STREAM_PID_FILE="/tmp/audio-stream.pid"
AUDIO_STREAM_FIFO="/tmp/audio-stream.fifo"

# Audio capturing binary - attempt to find available one
find_audio_capture_bin() {
  # Try different possible audio capture tools
  for bin in /mnt/bin/arecord /usr/bin/arecord /mnt/bin/rec /usr/bin/rec; do
    [ -x "$bin" ] && { echo "$bin"; return 0; }
  done
  return 1
}

AUDIO_CAPTURE_BIN="$(find_audio_capture_bin || echo "")"

respond() {
  status_code="$1"
  content_type="${2:-audio/wav}"
  
  echo "Status: $status_code"
  echo "Content-Type: $content_type"
  echo "Cache-Control: no-cache, no-store"
  echo "Pragma: no-cache"
  echo "Connection: close"
  echo ""
}

cleanup() {
  if [ -p "$AUDIO_STREAM_FIFO" ]; then
    rm -f "$AUDIO_STREAM_FIFO" 2>/dev/null || true
  fi
  if [ -f "$AUDIO_STREAM_PID_FILE" ]; then
    stream_pid="$(cat "$AUDIO_STREAM_PID_FILE" 2>/dev/null)"
    if [ -n "$stream_pid" ] && kill -0 "$stream_pid" 2>/dev/null; then
      kill "$stream_pid" 2>/dev/null || true
    fi
    rm -f "$AUDIO_STREAM_PID_FILE" 2>/dev/null || true
  fi
  if [ -d "$AUDIO_STREAM_LOCK_DIR" ]; then
    rmdir "$AUDIO_STREAM_LOCK_DIR" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

# Validate request
if [ "$REQUEST_METHOD" != "GET" ]; then
  respond "405 Method Not Allowed" "text/plain"
  echo "METHOD_NOT_ALLOWED"
  exit 0
fi

# Check if audio capture is available
if [ -z "$AUDIO_CAPTURE_BIN" ] || [ ! -x "$AUDIO_CAPTURE_BIN" ]; then
  log_event "error" "audio" "Audio capture unavailable: binary not found or not executable"
  respond "503 Service Unavailable" "text/plain"
  echo "AUDIO_CAPTURE_UNAVAILABLE"
  exit 0
fi

# Enforce max concurrent streams
client_count="$(ls -d "$AUDIO_STREAM_LOCK_DIR."* 2>/dev/null | wc -l)"
if [ "$client_count" -ge "$MAX_STREAM_CLIENTS" ]; then
  respond "429 Too Many Requests" "text/plain"
  echo "TOO_MANY_CLIENTS"
  exit 0
fi

# Create unique stream session
unique_id="$$_$(date +%s%3N 2>/dev/null || date +%s)"
session_lock_dir="${AUDIO_STREAM_LOCK_DIR}.${unique_id}"

if ! mkdir "$session_lock_dir" 2>/dev/null; then
  respond "503 Service Unavailable" "text/plain"
  echo "UNABLE_TO_CREATE_SESSION"
  exit 0
fi

session_pid_file="${session_lock_dir}/pid"
session_fifo="${session_lock_dir}/fifo"

# Create named pipe for audio streaming
if ! mkfifo "$session_fifo" 2>/dev/null; then
  rmdir "$session_lock_dir" 2>/dev/null || true
  respond "500 Internal Server Error" "text/plain"
  echo "FIFO_CREATION_FAILED"
  exit 0
fi

# Start audio capture in background
# Using WAV format with appropriate headers for HTTP streaming
(
  delay=0
  while [ $delay -lt 60 ] && kill -0 $$ 2>/dev/null; do
    # Generate minimal WAV header for PCM audio
    # RIFF header
    printf 'RIFF'
    # File size placeholder (will be invalid for streaming, but browsers tolerate it)
    printf '\xff\xff\xff\x7f'
    # WAVE format
    printf 'WAVE'
    
    # fmt subchunk
    printf 'fmt '
    printf '\x10\x00\x00\x00'  # Subchunk1Size (16 for PCM)
    printf '\x01\x00'           # AudioFormat (1 = PCM)
    printf '\x01\x00'           # NumChannels (1 = mono)
    # Sample rate (16000 Hz, little endian)
    printf '\x80\x3e\x00\x00'
    # Byte rate = sample_rate * num_channels * bytes_per_sample
    # 16000 * 1 * 2 = 32000 = 0x7d00
    printf '\x00\x7d\x00\x00'
    printf '\x02\x00'           # BlockAlign (1 channel * 2 bytes)
    printf '\x10\x00'           # BitsPerSample (16)
    
    # data subchunk
    printf 'data'
    printf '\xff\xff\xff\x7f'   # Subchunk2Size placeholder
    
    # Start capturing audio and stream to FIFO
    "$AUDIO_CAPTURE_BIN" -q -t raw -r "$AUDIO_SAMPLE_RATE" -c "$AUDIO_CHANNELS" -b "$AUDIO_BIT_DEPTH" 2>/dev/null > "$session_fifo" &
    capture_pid=$!
    
    echo "$capture_pid" > "$session_pid_file"
    
    # Wait for capture process (with timeout)
    wait_count=0
    while kill -0 "$capture_pid" 2>/dev/null && [ $wait_count -lt "$AUDIO_STREAM_TIMEOUT_SECONDS" ]; do
      sleep 1
      wait_count=$((wait_count + 1))
    done
    
    kill "$capture_pid" 2>/dev/null || true
    delay=$((delay + 1))
  done
) > "$session_fifo" 2>/dev/null &

stream_start_pid=$!
echo "$stream_start_pid" > "$session_pid_file"

# Send WAV stream headers and content to client
respond "200 OK" "audio/wav"

# Stream audio data from FIFO to client with timeout
timeout "$AUDIO_STREAM_TIMEOUT_SECONDS" cat "$session_fifo" 2>/dev/null || true

exit 0
