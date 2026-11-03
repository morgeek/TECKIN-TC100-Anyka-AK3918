#!/bin/sh
# scripts/notify.sh — Multi-channel notification dispatcher (Webhook, Ntfy, Telegram)
# Usage: notify.sh <event_type> <message> [snapshot_path] [detail]

NOTIFY_CONF="${NOTIFY_CONF:-/mnt/config/notify.conf}"
[ -f "$NOTIFY_CONF" ] || exit 0

# Defaults
WEBHOOK_ENABLE=0
WEBHOOK_URL=""
WEBHOOK_METHOD="POST"
NTFY_ENABLE=0
NTFY_URL="https://ntfy.sh"
NTFY_TOPIC=""
NTFY_PRIORITY="default"
NTFY_AUTH=""
TELEGRAM_NOTIFY_ENABLE=0
NOTIFY_ATTACH_SNAPSHOT=1
NOTIFY_COOLDOWN_SECONDS=15
NOTIFY_EVENTS="motion sound tamper"

# shellcheck disable=SC1090
. "$NOTIFY_CONF" 2>/dev/null || exit 0

# Fast check: any provider enabled?
if [ "${WEBHOOK_ENABLE:-0}" != "1" ] && [ "${NTFY_ENABLE:-0}" != "1" ] && [ "${TELEGRAM_NOTIFY_ENABLE:-0}" != "1" ]; then
  exit 0
fi

event_type="${1:-alert}"
message="${2:-TC100 Camera Alert}"
snapshot_path="$3"
detail="$4"

# Check event filter
case " $NOTIFY_EVENTS " in
  *" $event_type "*) ;;
  *) exit 0 ;;
esac

# Read current uptime for cooldown check
_up=0
[ -r /proc/uptime ] && read -r _up _ < /proc/uptime
now_s="${_up%.*}"
case "$now_s" in ''|*[!0-9]*) now_s=0 ;; esac

# Cooldown per event type
cooldown_file="/tmp/.notify_${event_type}.last"
if [ "$NOTIFY_COOLDOWN_SECONDS" -gt 0 ] 2>/dev/null && [ -r "$cooldown_file" ]; then
  read -r last_s < "$cooldown_file" 2>/dev/null
  case "$last_s" in ''|*[!0-9]*) last_s=0 ;; esac
  if [ $((now_s - last_s)) -lt "$NOTIFY_COOLDOWN_SECONDS" ]; then
    exit 0
  fi
fi
echo "$now_s" > "$cooldown_file" 2>/dev/null || true

# Determine curl / wget binary
CURL_BIN="/mnt/bin/curl"
[ -x "$CURL_BIN" ] || CURL_BIN="$(command -v curl 2>/dev/null)"

# Check snapshot availability
has_snap=0
if [ "${NOTIFY_ATTACH_SNAPSHOT:-1}" = "1" ] && [ -n "$snapshot_path" ] && [ -f "$snapshot_path" ]; then
  has_snap=1
fi

# Hostname for messages
cam_name="tc100"
[ -r /proc/sys/kernel/hostname ] && read -r cam_name < /proc/sys/kernel/hostname
[ -n "$cam_name" ] || cam_name="tc100"

# 1. Ntfy Dispatch
if [ "${NTFY_ENABLE:-0}" = "1" ] && [ -n "$NTFY_TOPIC" ] && [ -n "$CURL_BIN" ]; then
  _ntfy_url="${NTFY_URL%/}/${NTFY_TOPIC}"
  _ntfy_title="[${cam_name}] ${event_type}"
  _ntfy_tags="camera"
  case "$event_type" in
    motion) _ntfy_tags="camera,warning" ;;
    tamper) _ntfy_tags="camera,rotating_light" ;;
    sound)  _ntfy_tags="camera,loudspeaker" ;;
  esac

  _ntfy_args="-s -m 10"
  [ -n "$NTFY_AUTH" ] && _ntfy_args="$_ntfy_args -H 'Authorization: $NTFY_AUTH'"
  _ntfy_args="$_ntfy_args -H 'Title: $_ntfy_title' -H 'Priority: ${NTFY_PRIORITY:-default}' -H 'Tags: $_ntfy_tags'"

  if [ "$has_snap" -eq 1 ]; then
    # Upload snapshot directly with message in Header X-Message
    eval "$CURL_BIN $_ntfy_args -H 'Filename: snapshot.jpg' -H 'X-Message: $message' -T \"$snapshot_path\" \"$_ntfy_url\"" >/dev/null 2>&1 &
  else
    eval "$CURL_BIN $_ntfy_args -d \"$message\" \"$_ntfy_url\"" >/dev/null 2>&1 &
  fi
fi

# 2. Webhook Dispatch (Generic HTTP POST JSON)
if [ "${WEBHOOK_ENABLE:-0}" = "1" ] && [ -n "$WEBHOOK_URL" ] && [ -n "$CURL_BIN" ]; then
  _json_msg="$(printf '%s' "$message" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  _json_payload="{\"hostname\":\"$cam_name\",\"event\":\"$event_type\",\"message\":\"$_json_msg\",\"timestamp\":$now_s}"
  
  $CURL_BIN -s -m 10 -X "${WEBHOOK_METHOD:-POST}" \
    -H "Content-Type: application/json" \
    -d "$_json_payload" \
    "$WEBHOOK_URL" >/dev/null 2>&1 &
fi

# 3. Telegram Dispatch (Delegates to /mnt/bin/telegram)
if [ "${TELEGRAM_NOTIFY_ENABLE:-0}" = "1" ] && [ -x /mnt/bin/telegram ]; then
  if [ "$has_snap" -eq 1 ]; then
    /mnt/bin/telegram p "$snapshot_path" >/dev/null 2>&1 &
  else
    /mnt/bin/telegram m "[$cam_name] $event_type: $message" >/dev/null 2>&1 &
  fi
fi

exit 0
