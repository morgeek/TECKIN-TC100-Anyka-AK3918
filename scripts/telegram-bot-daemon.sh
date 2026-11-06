#!/bin/sh

CURL="/mnt/bin/curl"
LASTUPDATEFILE="/tmp/last_update_id"
TELEGRAM="/mnt/bin/telegram"
# the JSON answers are read with scripts/jsonflat.awk (audit 2026-11-06 S1: no jq in the flash image any more)
JSONFLAT="${JSONFLAT:-/mnt/scripts/jsonflat.awk}"

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
  # getimage (2.x) or the picture tc100_rtsp keeps (Linux 6.6)
  . /mnt/scripts/common_functions.sh
  take_snapshot "/tmp/telegram_image.jpg" &&\
  "$TELEGRAM" p "/tmp/telegram_image.jpg"
  rm -f "/tmp/telegram_image.jpg"
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

# tg_parse JSON: ok, chatId, cmd, updateId, username, firstName of the first update of a getUpdates answer, read from
# the lines of jsonflat.awk ("path TAB type TAB value"); no eval of anything from the network. 1 = not ok / not JSON.
tg_parse() {
  _tab=$(printf '\t')
  ok=; chatId=; cmd=; updateId=; username=; firstName=
  while IFS="$_tab" read -r _p _t _v; do
    case "$_p" in
      .ok) ok=$_v ;;
      '.result[0].update_id') updateId=$_v ;;
      '.result[0].message.chat.id') chatId=$_v ;;
      '.result[0].message.text') cmd=$_v ;;
      '.result[0].message.from.username') username=$_v ;;
      '.result[0].message.from.first_name') firstName=$_v ;;
    esac
  done <<EOF
$(printf '%s' "$1" | LC_ALL=C awk -f "$JSONFLAT" 2>/dev/null)
EOF
  [ "$ok" = true ]
}

main() {
  json="$(readNext)" || return 2

  tg_parse "$json" || return 1
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
