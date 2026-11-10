#!/bin/sh
# scripts/notify.sh — Multi-channel notification dispatcher (Webhook, Ntfy, Telegram)
# Usage: notify.sh <event_type> <message> [snapshot_path] [detail]
#
# Item 34 of the implementer list (pictures out of the camera on a serious alert, so that they survive a camera torn
# down or a card taken out):
#   - an event that brings no picture (tamper) gets a fresh one when NOTIFY_ATTACH_SNAPSHOT=1;
#   - NOTIFY_BURST=N (0-5, default 0): for the events of NOTIFY_BURST_EVENTS (default "tamper"), N more fresh pictures,
#     one a second, to the picture channels (Ntfy, Telegram);
#   - NOTIFY_UPLOAD_URL (http(s)://, a WebDAV folder or a pre-signed upload address; empty = off): every picture of
#     the alert is also sent there with an HTTP PUT, as <host>_<date>_<n>.jpg (NOTIFY_UPLOAD_AUTH = "user:password"
#     for curl -u, optional).

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
NOTIFY_BURST=0
NOTIFY_BURST_EVENTS="tamper"
NOTIFY_UPLOAD_URL=""
NOTIFY_UPLOAD_AUTH=""

# shellcheck disable=SC1090
. "$NOTIFY_CONF" 2>/dev/null || exit 0

# Presence profiles can suppress outbound notifications without rewriting
# their channel settings or event filters. MQTT telemetry and event topics stay
# available to Home Assistant.
_presence_script="$PRESENCE_MODE_SCRIPT"
[ -n "$_presence_script" ] || _presence_script=/mnt/scripts/presence-mode.sh
if [ -r "$_presence_script" ]; then
  _presence_allowed="$(sh "$_presence_script" notifications 2>/dev/null)"
  [ "$_presence_allowed" = 0 ] && exit 0
fi

# Fast check: any channel enabled?
if [ "${WEBHOOK_ENABLE:-0}" != "1" ] && [ "${NTFY_ENABLE:-0}" != "1" ] && [ "${TELEGRAM_NOTIFY_ENABLE:-0}" != "1" ] && \
   [ -z "$NOTIFY_UPLOAD_URL" ]; then
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
cooldown_file="${NOTIFY_STATE_DIR:-/tmp}/.notify_${event_type}.last"
if [ "$NOTIFY_COOLDOWN_SECONDS" -gt 0 ] 2>/dev/null && [ -r "$cooldown_file" ]; then
  read -r last_s < "$cooldown_file" 2>/dev/null
  case "$last_s" in ''|*[!0-9]*) last_s=0 ;; esac
  if [ $((now_s - last_s)) -lt "$NOTIFY_COOLDOWN_SECONDS" ]; then
    exit 0
  fi
fi
echo "$now_s" > "$cooldown_file" 2>/dev/null || true

# Determine curl binary
CURL_BIN="${NOTIFY_CURL:-/mnt/bin/curl}"
[ -x "$CURL_BIN" ] || CURL_BIN="$(command -v curl 2>/dev/null)"
TELEGRAM_BIN="${NOTIFY_TELEGRAM:-/mnt/bin/telegram}"
TMPD="${NOTIFY_STATE_DIR:-/tmp}"

# a fresh picture (tc100_rtsp's snapshot cache): $1 = file; NOTIFY_SNAPSHOT_CMD replaces it in the tests
_snap() {
  if [ -n "$NOTIFY_SNAPSHOT_CMD" ]; then $NOTIFY_SNAPSHOT_CMD "$1"; return; fi
  [ -r /mnt/scripts/common_functions.sh ] || return 1
  ( . /mnt/scripts/common_functions.sh && take_snapshot "$1" ) >/dev/null 2>&1
}

# Check snapshot availability; an event without one (tamper) gets a fresh one
has_snap=0
if [ "${NOTIFY_ATTACH_SNAPSHOT:-1}" = "1" ]; then
  if [ -n "$snapshot_path" ] && [ -f "$snapshot_path" ]; then
    has_snap=1
  elif _snap "$TMPD/.notify-$event_type.jpg" && [ -s "$TMPD/.notify-$event_type.jpg" ]; then
    snapshot_path="$TMPD/.notify-$event_type.jpg"; has_snap=1
  fi
fi

# Hostname for messages
cam_name="tc100"
[ -r /proc/sys/kernel/hostname ] && read -r cam_name < /proc/sys/kernel/hostname
[ -n "$cam_name" ] || cam_name="tc100"

_ntfy_tags="camera"
case "$event_type" in
  motion) _ntfy_tags="camera,warning" ;;
  tamper) _ntfy_tags="camera,rotating_light" ;;
  sound)  _ntfy_tags="camera,loudspeaker" ;;
esac

# Ntfy: $1 = picture file or "", $2 = message (no eval: the message is passed as one argument)
_ntfy() {
  [ "${NTFY_ENABLE:-0}" = "1" ] && [ -n "$NTFY_TOPIC" ] && [ -n "$CURL_BIN" ] || return 0
  _nu="${NTFY_URL%/}/${NTFY_TOPIC}"
  if [ -n "$1" ]; then
    "$CURL_BIN" -s -m 10 ${NTFY_AUTH:+-H "Authorization: $NTFY_AUTH"} -H "Title: [${cam_name}] ${event_type}" \
      -H "Priority: ${NTFY_PRIORITY:-default}" -H "Tags: $_ntfy_tags" -H "Filename: snapshot.jpg" -H "X-Message: $2" \
      -T "$1" "$_nu" >/dev/null 2>&1
  else
    "$CURL_BIN" -s -m 10 ${NTFY_AUTH:+-H "Authorization: $NTFY_AUTH"} -H "Title: [${cam_name}] ${event_type}" \
      -H "Priority: ${NTFY_PRIORITY:-default}" -H "Tags: $_ntfy_tags" -d "$2" "$_nu" >/dev/null 2>&1
  fi
}

# Telegram: $1 = picture file or "", $2 = message
_telegram() {
  [ "${TELEGRAM_NOTIFY_ENABLE:-0}" = "1" ] && [ -x "$TELEGRAM_BIN" ] || return 0
  if [ -n "$1" ]; then "$TELEGRAM_BIN" p "$1" >/dev/null 2>&1
  else "$TELEGRAM_BIN" m "[$cam_name] $event_type: $2" >/dev/null 2>&1; fi
}

# off-site copy (item 34): $1 = picture, $2 = its number in the alert
_stamp="$(date +%Y%m%d-%H%M%S 2>/dev/null || echo "$now_s")"
_upload() {
  case "$NOTIFY_UPLOAD_URL" in http://*|https://*) ;; *) return 0 ;; esac
  [ -n "$CURL_BIN" ] && [ -s "$1" ] || return 0
  "$CURL_BIN" -s -m 30 ${NOTIFY_UPLOAD_AUTH:+-u "$NOTIFY_UPLOAD_AUTH"} -T "$1" \
    "${NOTIFY_UPLOAD_URL%/}/${cam_name}_${_stamp}_${event_type}_$2.jpg" >/dev/null 2>&1
}

# 1. Ntfy, 2. Telegram (the picture when there is one)
if [ "$has_snap" -eq 1 ]; then
  _ntfy "$snapshot_path" "$message" &
  _telegram "$snapshot_path" "$message" &
  _upload "$snapshot_path" 0 &
else
  _ntfy "" "$message" &
  _telegram "" "$message" &
fi

# 3. Webhook Dispatch (Generic HTTP POST JSON)
if [ "${WEBHOOK_ENABLE:-0}" = "1" ] && [ -n "$WEBHOOK_URL" ] && [ -n "$CURL_BIN" ]; then
  _json_msg="$(printf '%s' "$message" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  _json_payload="{\"hostname\":\"$cam_name\",\"event\":\"$event_type\",\"message\":\"$_json_msg\",\"timestamp\":$now_s}"
  "$CURL_BIN" -s -m 10 -X "${WEBHOOK_METHOD:-POST}" -H "Content-Type: application/json" \
    -d "$_json_payload" "$WEBHOOK_URL" >/dev/null 2>&1 &
fi

# 4. Burst (item 34): more fresh pictures, one a second, for the serious events
_burst=0
case " $NOTIFY_BURST_EVENTS " in *" $event_type "*) _burst="${NOTIFY_BURST:-0}" ;; esac
case "$_burst" in ''|*[!0-9]*) _burst=0 ;; esac
[ "$_burst" -gt 5 ] && _burst=5
_i=1
while [ "$_i" -le "$_burst" ]; do
  sleep 1
  _f="$TMPD/.notify-burst-$event_type-$_i.jpg"
  if _snap "$_f" && [ -s "$_f" ]; then
    _ntfy "$_f" "$message ($_i/$_burst)"
    _telegram "$_f" "$message ($_i/$_burst)"
    _upload "$_f" "$_i"
  fi
  rm -f "$_f"
  _i=$((_i + 1))
done
wait
exit 0
