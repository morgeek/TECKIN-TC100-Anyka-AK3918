#!/bin/sh

# Source common functions only — do NOT source action.cgi (it emits Content-Type headers on load)
# FUNC_CGI_SKIP_BODY: the body of this request is raw PCM, and func.cgi's form
# parser would otherwise slurp stdin dry before we read it (every upload then
# fails with EMPTY_INPUT).
FUNC_CGI_SKIP_BODY=1
. /mnt/www/cgi-bin/func.cgi
. /mnt/scripts/common_functions.sh

MAX_UPLOAD_BYTES=524288
PTT_VOLUME_FILE="/mnt/config/pttvolume.conf"
PTT_PLAYBACK_PID_FILE="/tmp/ptt-audioplay.pid"
PTT_LOCK_DIR="/tmp/ptt-upload.lock"
PTT_LAST_PCM_FILE="/tmp/ptt-last.pcm"
PLAYBACK_CLEANUP_DELAY_SECONDS=2
RTSP_SERVICE="/mnt/controlscripts/rtsp-h26x"

# Anyka native audio output binary: ak_ao_demo <rate> <channels> <pcm_file> <volume 0-6>
AUDIOPLAY_BIN="/mnt/bin/ak_ao_ptt"

# Map UI volume (0-100) to ak_ao_demo scale (0-6).
# Caller guarantees $1 is already clamped to 0-100.
ptt_volume_to_ak() {
    _num=$(expr "$1" \* 6 + 50)
    expr "$_num" / 100
}

pcm_file=""
lock_acquired=0
playback_started=0
playback_pid=""
rtsp_was_running=0

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
    if [ "$playback_started" != "1" ] && [ -n "$pcm_file" ]; then
        rm -f "$pcm_file" >/dev/null 2>&1
    fi
    if [ "$lock_acquired" = "1" ]; then
        rmdir "$PTT_LOCK_DIR" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT INT TERM

mutation_guard
rate_limit_check 5 60

if [ "$REQUEST_METHOD" != "POST" ]; then
    respond_plain "405 Method Not Allowed" "METHOD_NOT_ALLOWED"
    exit 0
fi

if [ ! -x "$AUDIOPLAY_BIN" ] && [ -r /mnt/scripts/prepare-ptt-player.sh ]; then
    sh /mnt/scripts/prepare-ptt-player.sh >/dev/null 2>&1 || true
fi

if [ ! -x "$AUDIOPLAY_BIN" ]; then
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

if [ "$(expr "$CONTENT_LENGTH" % 2)" -ne 0 ]; then
    respond_plain "400 Bad Request" "INVALID_PCM"
    exit 0
fi

if [ "$CONTENT_LENGTH" -gt "$MAX_UPLOAD_BYTES" ]; then
    respond_plain "413 Payload Too Large" "TOO_LARGE"
    exit 0
fi

if ! mkdir "$PTT_LOCK_DIR" 2>/dev/null; then
    # Recover a lock orphaned by an interrupted/older CGI only when no tracked
    # playback process is still alive.
    active_playback=0
    if [ -f "$PTT_PLAYBACK_PID_FILE" ]; then
        active_pid="$(head -n 1 "$PTT_PLAYBACK_PID_FILE" 2>/dev/null)"
        case "$active_pid" in
            ''|*[!0-9]*) ;;
            *)
                if kill -0 "$active_pid" >/dev/null 2>&1; then
                    active_playback=1
                fi
                ;;
        esac
    fi
    if [ "$active_playback" = "0" ]; then
        rmdir "$PTT_LOCK_DIR" >/dev/null 2>&1 || true
    fi
    if ! mkdir "$PTT_LOCK_DIR" 2>/dev/null; then
        respond_plain "429 Too Many Requests" "BUSY"
        exit 0
    fi
fi
lock_acquired=1

_wd_btime=0
while read -r _k _v _; do [ "$_k" = "btime" ] && _wd_btime="$_v" && break; done < /proc/stat
read -r _wd_up _ < /proc/uptime
tmp_tag=$(expr "$_wd_btime" + "${_wd_up%.*}")
pcm_file="/tmp/pttaudio_${tmp_tag}_$$.pcm"

# Read raw PCM body efficiently (Int16 LE at 8kHz mono from browser)
if ! head -c "$CONTENT_LENGTH" > "$pcm_file" 2>/dev/null; then
    respond_plain "400 Bad Request" "READ_FAILED"
    exit 0
fi

if [ ! -s "$pcm_file" ]; then
    respond_plain "400 Bad Request" "EMPTY_INPUT"
    exit 0
fi

cp "$pcm_file" "$PTT_LAST_PCM_FILE" >/dev/null 2>&1 || true

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

# Map 0-100 to 0-6 for ak_ao_demo
vol_ak="$(ptt_volume_to_ak "$ptt_volume")"

if [ -f "$PTT_PLAYBACK_PID_FILE" ]; then
    last_pid="$(head -n 1 "$PTT_PLAYBACK_PID_FILE" 2>/dev/null)"
    case "$last_pid" in
        ''|*[!0-9]*) ;;
        *)
            if kill -0 "$last_pid" >/dev/null 2>&1; then
                respond_plain "429 Too Many Requests" "BUSY"
                exit 0
            fi
            ;;
    esac
    rm -f "$PTT_PLAYBACK_PID_FILE" >/dev/null 2>&1 || true
fi

# The AK3918 exposes capture and playback through one exclusive codec device.
# Stop RTSP only when it currently owns that device, then restore it from the
# detached cleanup worker after the short PTT clip has completed.
if [ -x "$RTSP_SERVICE" ] && "$RTSP_SERVICE" status >/dev/null 2>&1; then
    rtsp_was_running=1
    "$RTSP_SERVICE" stop >/dev/null 2>&1 || {
        respond_plain "503 Service Unavailable" "AUDIO_DEVICE_BUSY"
        exit 0
    }
    sleep 1
fi

"$AUDIOPLAY_BIN" 8000 1 "$pcm_file" "$vol_ak" >/dev/null 2>&1 &
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
    _cl_loops=0
    while kill -0 "$playback_pid" >/dev/null 2>&1 && [ "$_cl_loops" -lt 120 ]; do
        sleep 1
        _cl_loops=$(expr "$_cl_loops" + 1)
    done
    sleep "$PLAYBACK_CLEANUP_DELAY_SECONDS"
    if [ "$rtsp_was_running" = "1" ] && [ -x "$RTSP_SERVICE" ]; then
        "$RTSP_SERVICE" start >/dev/null 2>&1 || true
    fi
    rm -f "$pcm_file" >/dev/null 2>&1 || true
    if [ -f "$PTT_PLAYBACK_PID_FILE" ]; then
        _cur_pid="$(head -n 1 "$PTT_PLAYBACK_PID_FILE" 2>/dev/null)"
        if [ "$_cur_pid" = "$playback_pid" ]; then
            rm -f "$PTT_PLAYBACK_PID_FILE" >/dev/null 2>&1 || true
        fi
    fi
    rmdir "$PTT_LOCK_DIR" >/dev/null 2>&1 || true
) >/dev/null 2>&1 &
# Transfer lock ownership to the detached worker so another upload cannot
# interrupt playback or race the RTSP restart.
lock_acquired=0
respond_plain "200 OK" "OK"
