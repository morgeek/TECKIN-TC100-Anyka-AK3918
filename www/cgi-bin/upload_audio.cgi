#!/bin/sh

MAX_UPLOAD_BYTES=524288
PTT_VOLUME_FILE="/mnt/config/pttvolume.conf"
PTT_PLAYBACK_PID_FILE="/tmp/ptt-audioplay.pid"
PTT_LOCK_DIR="/tmp/ptt-upload.lock"
PLAYBACK_CLEANUP_DELAY_SECONDS=20

FFMPEG_BIN="/mnt/bin/ffmpeg-min-recorder"
AUDIOPLAY_BIN="/usr/bin/audioplay"
if [ -x "/mnt/bin/audioplay" ]; then
    AUDIOPLAY_BIN="/mnt/bin/audioplay"
fi

webm_file=""
wav_file=""
lock_acquired=0
playback_started=0
playback_pid=""

respond_plain() {
    status_code="$1"
    body="$2"
    echo "Status: $status_code"
    echo "Content-type: text/plain"
    echo "Pragma: no-cache"
    echo "Cache-Control: no-store, no-cache"
    echo ""
    echo "$body"
}

cleanup() {
    [ -n "$webm_file" ] && rm -f "$webm_file" >/dev/null 2>&1
    if [ "$playback_started" != "1" ] && [ -n "$wav_file" ]; then
        rm -f "$wav_file" >/dev/null 2>&1
    fi
    if [ "$lock_acquired" = "1" ]; then
        rmdir "$PTT_LOCK_DIR" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT INT TERM

if [ "$REQUEST_METHOD" != "POST" ]; then
    respond_plain "405 Method Not Allowed" "METHOD_NOT_ALLOWED"
    exit 0
fi

content_type="$(printf '%s' "$CONTENT_TYPE" | tr '[:upper:]' '[:lower:]')"
case "$content_type" in
    audio/webm*|application/octet-stream*|"")
        ;;
    *)
        respond_plain "415 Unsupported Media Type" "UNSUPPORTED_CONTENT_TYPE"
        exit 0
        ;;
esac

if [ ! -x "$FFMPEG_BIN" ] || [ ! -x "$AUDIOPLAY_BIN" ]; then
    respond_plain "500 Internal Server Error" "PTT_BIN_MISSING"
    exit 0
fi

case "$CONTENT_LENGTH" in
    ''|*[!0-9]*)
        respond_plain "411 Length Required" "INVALID_CONTENT_LENGTH"
        exit 0
        ;;
esac

if [ "$CONTENT_LENGTH" -le 0 ]; then
    respond_plain "400 Bad Request" "EMPTY_INPUT"
    exit 0
fi

if [ "$CONTENT_LENGTH" -gt "$MAX_UPLOAD_BYTES" ]; then
    respond_plain "413 Payload Too Large" "TOO_LARGE"
    exit 0
fi

if ! mkdir "$PTT_LOCK_DIR" 2>/dev/null; then
    respond_plain "429 Too Many Requests" "BUSY"
    exit 0
fi
lock_acquired=1

tmp_tag="$$.$(date +%s)"
webm_file="/tmp/pttaudio_${tmp_tag}.webm"
wav_file="/tmp/pttaudio_${tmp_tag}.wav"

if ! dd bs=1 count="$CONTENT_LENGTH" of="$webm_file" 2>/dev/null; then
    respond_plain "400 Bad Request" "READ_FAILED"
    exit 0
fi

if [ ! -s "$webm_file" ]; then
    respond_plain "400 Bad Request" "EMPTY_INPUT"
    exit 0
fi

if ! "$FFMPEG_BIN" -i "$webm_file" -acodec pcm_s16le -ar 8000 -ac 1 "$wav_file" -y >/dev/null 2>&1; then
    respond_plain "400 Bad Request" "CONVERSION_FAILED"
    exit 0
fi

if [ ! -s "$wav_file" ]; then
    respond_plain "400 Bad Request" "CONVERSION_FAILED"
    exit 0
fi

ptt_volume=90
if [ -f "$PTT_VOLUME_FILE" ]; then
    file_volume="$(head -n 1 "$PTT_VOLUME_FILE" 2>/dev/null)"
    case "$file_volume" in
        ''|*[!0-9]*)
            ;;
        *)
            ptt_volume="$file_volume"
            ;;
    esac
fi

if [ "$ptt_volume" -lt 0 ]; then
    ptt_volume=0
fi
if [ "$ptt_volume" -gt 100 ]; then
    ptt_volume=100
fi

if [ -f "$PTT_PLAYBACK_PID_FILE" ]; then
    last_pid="$(cat "$PTT_PLAYBACK_PID_FILE" 2>/dev/null)"
    case "$last_pid" in
        ''|*[!0-9]*)
            ;;
        *)
            if [ -r "/proc/$last_pid/cmdline" ] && grep -q "audioplay" "/proc/$last_pid/cmdline" 2>/dev/null; then
                kill "$last_pid" >/dev/null 2>&1 || true
            fi
            ;;
    esac
    rm -f "$PTT_PLAYBACK_PID_FILE" >/dev/null 2>&1 || true
fi

"$AUDIOPLAY_BIN" "$wav_file" "$ptt_volume" >/dev/null 2>&1 &
playback_pid="$!"
playback_started=1

case "$playback_pid" in
    ''|*[!0-9]*)
        ;;
    *)
        echo "$playback_pid" > "$PTT_PLAYBACK_PID_FILE"
        ;;
esac

(
    loops=0
    while kill -0 "$playback_pid" >/dev/null 2>&1 && [ "$loops" -lt 120 ]; do
        sleep 1
        loops=$((loops + 1))
    done
    sleep "$PLAYBACK_CLEANUP_DELAY_SECONDS"
    rm -f "$wav_file" >/dev/null 2>&1 || true
    if [ -f "$PTT_PLAYBACK_PID_FILE" ]; then
        current_pid="$(cat "$PTT_PLAYBACK_PID_FILE" 2>/dev/null)"
        if [ "$current_pid" = "$playback_pid" ]; then
            rm -f "$PTT_PLAYBACK_PID_FILE" >/dev/null 2>&1 || true
        fi
    fi
) >/dev/null 2>&1 &
respond_plain "200 OK" "OK"
