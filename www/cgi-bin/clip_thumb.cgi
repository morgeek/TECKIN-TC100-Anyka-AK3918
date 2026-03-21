#!/bin/sh
# clip_thumb.cgi — Serve a JPEG thumbnail for a recording file.
#
# Query parameters:
#   path=<relative path under /mnt/DCIM>   (required)
#   size=<width>                            (optional, default 320)
#
# Response:
#   200 image/jpeg  — thumbnail extracted from the first keyframe of the clip
#   400             — missing or unsafe path
#   404             — file not found
#   503             — no ffmpeg available

. /mnt/www/cgi-bin/func.cgi
. /mnt/scripts/common_functions.sh

export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'

DCIM_ROOT="/mnt/DCIM"
THUMB_CACHE_DIR="/tmp/clip_thumbs"
THUMB_TTL_SECONDS=300
FFMPEG_BIN="/mnt/bin/ffmpeg-min"
FALLBACK_FFMPEG="/mnt/bin/ffmpeg"

respond_error() {
  echo "Status: $1"
  echo "Content-Type: text/plain"
  echo "Cache-Control: no-cache"
  echo ""
  echo "$2"
}

# Only allow GET
if [ "$REQUEST_METHOD" != "GET" ] && [ "$REQUEST_METHOD" != "HEAD" ]; then
  respond_error "405 Method Not Allowed" "METHOD_NOT_ALLOWED"
  exit 0
fi

# Find a usable ffmpeg
FFMPEG=""
for _bin in "$FFMPEG_BIN" "$FALLBACK_FFMPEG" /usr/bin/ffmpeg; do
  if [ -x "$_bin" ]; then
    FFMPEG="$_bin"
    break
  fi
done

if [ -z "$FFMPEG" ]; then
  respond_error "503 Service Unavailable" "NO_FFMPEG"
  exit 0
fi

# Parse and sanitize the path parameter
clip_path="${F_path:-}"
# Strip leading slashes and any .. components for safety
clip_path="$(printf '%s' "$clip_path" | sed 's|^\/*||; s|/\.\./|/|g; s|\.\.$||; s|^\.\./||')"

if [ -z "$clip_path" ]; then
  respond_error "400 Bad Request" "MISSING_PATH"
  exit 0
fi

# Reject any remaining .. to prevent path traversal
case "$clip_path" in
  *..*)
    respond_error "400 Bad Request" "INVALID_PATH"
    exit 0
    ;;
esac

full_path="$DCIM_ROOT/$clip_path"

if [ ! -f "$full_path" ]; then
  respond_error "404 Not Found" "NOT_FOUND"
  exit 0
fi

# Validate file extension (only video files)
case "$full_path" in
  *.mp4|*.mkv|*.avi|*.ts|*.mov|*.h264|*.h265)
    ;;
  *)
    respond_error "400 Bad Request" "UNSUPPORTED_FORMAT"
    exit 0
    ;;
esac

# Thumbnail size
thumb_w="${F_size:-320}"
case "$thumb_w" in
  ''|*[!0-9]*) thumb_w=320 ;;
esac
if [ "$thumb_w" -lt 64 ]; then thumb_w=64; fi
if [ "$thumb_w" -gt 1920 ]; then thumb_w=1920; fi

# Cache key: sha of path + size (no sha256sum needed — use cksum which is always available)
cache_key="$(printf '%s_%s' "$clip_path" "$thumb_w" | cksum | awk '{print $1}')"
cache_file="$THUMB_CACHE_DIR/${cache_key}.jpg"

# Check cache freshness
serve_cached=0
if [ -f "$cache_file" ]; then
  # Check age via /proc/uptime and file mtime (use ls -l and compare)
  # On busybox, check if file is newer than TTL seconds
  cache_age="$(find "$THUMB_CACHE_DIR" -name "${cache_key}.jpg" -newer /proc/uptime 2>/dev/null | wc -l)"
  # Simpler approach: just always regenerate if full_path is newer than cache
  if [ "$full_path" -ot "$cache_file" ]; then
    serve_cached=1
  fi
fi

if [ "$serve_cached" = "0" ]; then
  mkdir -p "$THUMB_CACHE_DIR" 2>/dev/null || true
  tmp_thumb="${cache_file}.tmp.$$"

  # Extract first keyframe, scale to requested width
  "$FFMPEG" -y -loglevel error \
    -ss 0 \
    -i "$full_path" \
    -vframes 1 \
    -vf "scale=${thumb_w}:-2" \
    -f image2 \
    "$tmp_thumb" 2>/dev/null

  if [ -s "$tmp_thumb" ]; then
    mv "$tmp_thumb" "$cache_file" 2>/dev/null || true
  else
    rm -f "$tmp_thumb" 2>/dev/null || true
    respond_error "500 Internal Server Error" "THUMB_FAILED"
    exit 0
  fi
fi

if [ ! -s "$cache_file" ]; then
  respond_error "500 Internal Server Error" "CACHE_MISSING"
  exit 0
fi

echo "Status: 200 OK"
echo "Content-Type: image/jpeg"
echo "Cache-Control: max-age=$THUMB_TTL_SECONDS"
echo ""
cat "$cache_file"
