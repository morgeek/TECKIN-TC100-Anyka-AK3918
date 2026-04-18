#!/bin/sh

CURL="/mnt/bin/curl"
LASTUPDATEFILE="/tmp/last_update_id"
TELEGRAM="/mnt/bin/telegram"
JQ="/mnt/bin/jq"

. /mnt/config/telegram.conf
[ -z "$apiToken" ] && echo "api token not configured yet" && exit 1
[ -z "$userChatId" ] && echo "chat id not configured yet" && exit 1

# Performance tuning:
# - Use Telegram long polling to avoid tight request loops.
# - Add configurable sleep/backoff to keep CPU usage predictable.
TELEGRAM_LONG_POLL_TIMEOUT_SECONDS="${TELEGRAM_LONG_POLL_TIMEOUT_SECONDS:-25}"
TELEGRAM_IDLE_SLEEP_SECONDS="${TELEGRAM_IDLE_SLEEP_SECONDS:-5}"
TELEGRAM_ERROR_BACKOFF_SECONDS="${TELEGRAM_ERROR_BACKOFF_SECONDS:-5}"

sendShot() {
  /mnt/bin/getimage > "/tmp/telegram_image.jpg" &&\
  "$TELEGRAM" p "/tmp/telegram_image.jpg"
  rm "/tmp/telegram_image.jpg"
}

sendMem() {
  "$TELEGRAM" m "$(free -k | awk '/^Mem/ {print "Mem: used "$3" free "$4} /^Swap/ {print "Swap: used "$3}')"
}

detectionOn() {
  . /mnt/scripts/common_functions.sh
  motion_detection on && "$TELEGRAM" m "Motion detection started"
}

detectionOff() {
  . /mnt/scripts/common_functions.sh
  motion_detection off && "$TELEGRAM" m "Motion detection stopped"
}

respond() {
  case $1 in
    /mem) sendMem;;
    /shot) sendShot;;
    /on) detectionOn;;
    /off) detectionOff;;
    *) "$TELEGRAM" m "I can't respond to '$1' command"
  esac
}

readNext() {
  lastUpdateId="$(cat "$LASTUPDATEFILE" 2>/dev/null || echo "0")"
  maxTime=$((TELEGRAM_LONG_POLL_TIMEOUT_SECONDS + 10))
  "$CURL" -s --connect-timeout 5 --max-time "$maxTime" -X GET \
    "https://api.telegram.org/bot$apiToken/getUpdates?offset=$lastUpdateId&limit=1&timeout=$TELEGRAM_LONG_POLL_TIMEOUT_SECONDS&allowed_updates=message"
}

markAsRead() {
  nextId=$(($1 + 1))
  echo "$nextId" > "$LASTUPDATEFILE"
}

main() {
  json="$(readNext)" || return 2

  # Check for error or empty result in one pass
  p="$(echo "$json" | "$JQ" -r 'if .ok == true then .result[0] | @sh "chatId=\(.message.chat.id // \"\") cmd=\(.message.text // \"\") updateId=\(.update_id // \"\") username=\(.message.from.username // \"\") firstName=\(.message.from.first_name // \"\")" else "error" end' 2>/dev/null)"
  [ -z "$p" ] || [ "$p" = "error" ] && return 1

  # Safely evaluate variables (chatId, cmd, updateId, username, firstName)
  eval "$p"
  [ -z "$chatId" ] && return 0 # no new updates

  if [ "$chatId" != "$userChatId" ]; then
    "$TELEGRAM" m "Unauthorized chat: $chatId\nUser: $username($firstName)\nMsg: $cmd"
  else
    respond "$cmd"
  fi

  markAsRead "$updateId"
}

while true; do
  main >/dev/null 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    sleep "$TELEGRAM_IDLE_SLEEP_SECONDS"
  else
    sleep "$TELEGRAM_ERROR_BACKOFF_SECONDS"
  fi
done;
