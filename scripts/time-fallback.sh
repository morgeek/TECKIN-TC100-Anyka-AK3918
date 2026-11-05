#!/bin/sh
# time-fallback.sh — set the clock from an HTTP "Date:" header when NTP could not (item 24 of the implementer list).
#
# The SoC has no battery-backed clock: it starts in 1970 and ntpd (v3/autorun-linux66.sh) sets it once the Wi-Fi is
# up. Where UDP port 123 is blocked (guest networks, some routers and firewalls) the recordings, logs and MQTT stamps
# stayed in 1970. Started 2 minutes after boot: while the clock is not set (year before 2025), every 5 minutes, at most
# 12 times, a HEAD request to each address of the list; the first "Date:" header (RFC 7231, always GMT) sets the clock.
# NTP stays the reference: ntpd keeps running and corrects the time when it gets through.
#
# boot.conf: TIME_HTTP_FALLBACK=1 (default; 0 = off), TIME_HTTP_URLS (space-separated http:// addresses; default
# "gateway" = the router's own web page, on the local network: nothing leaves it). Add e.g. http://www.google.com to
# ask the Internet.
#
#   time-fallback.sh run     the loop above (autorun)
#   time-fallback.sh once    one round of the list now; exit 0 when the clock was set
#   time-fallback.sh parse "Thu, 05 Nov 2026 09:30:00 GMT"   seconds since 1970 (tests)
CONF="${TF_CONF:-/mnt/config/boot.conf}"
CURL="${TF_CURL:-curl}"
TRIES="${TF_TRIES:-12}"
GAP="${TF_GAP:-300}"

tf_log() { logger -t tc100-event -p user.notice "time-fallback: $*" 2>/dev/null; echo "[time-fallback] $*" > "${TF_CONSOLE:-/dev/console}" 2>/dev/null; }
tf_kv() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}\$/\1/p" "$CONF" 2>/dev/null | tail -n 1; }
tf_year() { if [ -n "$TF_YEAR" ]; then echo "$TF_YEAR"; else date +%Y; fi; }
tf_set() { [ "$(tf_year)" -ge 2025 ] 2>/dev/null; }

# "Thu, 05 Nov 2026 09:30:00 GMT" -> seconds since 1970, without date -D (busybox builds differ): days from the civil
# date (Howard Hinnant's algorithm), all integer shell arithmetic
tf_parse() {
  set -- $1
  [ $# -ge 5 ] || return 1
  d=$2; mon=$3; y=$4; t=$5
  case "$mon" in Jan) m=1 ;; Feb) m=2 ;; Mar) m=3 ;; Apr) m=4 ;; May) m=5 ;; Jun) m=6 ;; Jul) m=7 ;; Aug) m=8 ;;
    Sep) m=9 ;; Oct) m=10 ;; Nov) m=11 ;; Dec) m=12 ;; *) return 1 ;; esac
  case "$d$y" in *[!0-9]*|'') return 1 ;; esac
  case "$t" in [0-2][0-9]:[0-5][0-9]:[0-6][0-9]) ;; *) return 1 ;; esac
  d=${d#0}; hh=${t%%:*}; mm=${t#*:}; ss=${mm#*:}; mm=${mm%%:*}
  hh=${hh#0}; mm=${mm#0}; ss=${ss#0}
  [ "$y" -ge 2020 ] && [ "$y" -le 2100 ] && [ "$d" -ge 1 ] && [ "$d" -le 31 ] || return 1
  [ "$m" -le 2 ] && y=$((y - 1))
  era=$((y / 400)); yoe=$((y - era * 400))
  if [ "$m" -gt 2 ]; then mp=$((m - 3)); else mp=$((m + 9)); fi
  doy=$(( (153 * mp + 2) / 5 + d - 1 ))
  doe=$(( yoe * 365 + yoe / 4 - yoe / 100 + doy ))
  days=$(( era * 146097 + doe - 719468 ))
  echo $(( days * 86400 + ${hh:-0} * 3600 + ${mm:-0} * 60 + ${ss:-0} ))
}

tf_gateway() { ip route 2>/dev/null | sed -n 's/^default via \([0-9.]*\).*/\1/p' | head -n 1; }

tf_once() {
  urls=$(tf_kv TIME_HTTP_URLS); [ -n "$urls" ] || urls=gateway
  for u in $urls; do
    if [ "$u" = gateway ]; then g=${TF_GW:-$(tf_gateway)}; [ -n "$g" ] || continue; u="http://$g/"; fi
    case "$u" in http://*) ;; *) continue ;; esac
    hdr=$("$CURL" -s -I -m 5 "$u" 2>/dev/null | tr -d '\r' | sed -n 's/^[Dd]ate: *//p' | head -n 1)
    [ -n "$hdr" ] || continue
    s=$(tf_parse "$hdr") || continue
    if ${TF_DATE_SET:-date -u -s} "@$s" >/dev/null 2>&1; then
      tf_log "clock set from the Date header of $u ($hdr): NTP did not answer"
      return 0
    fi
  done
  return 1
}

case "${1:-run}" in
  parse) tf_parse "$2" ;;
  once) tf_once ;;
  run)
    case "$(tf_kv TIME_HTTP_FALLBACK)" in 0|no|off|false) exit 0 ;; esac
    i=0
    while [ "$i" -lt "$TRIES" ]; do
      tf_set && exit 0
      tf_once && exit 0
      i=$((i + 1)); sleep "$GAP"
    done ;;
  *) echo "usage: time-fallback.sh run|once|parse DATE" >&2; exit 2 ;;
esac
