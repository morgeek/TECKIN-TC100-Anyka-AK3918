#!/bin/sh
# log-persist.sh: keep the camera's logs across a reboot or a panic. The logs live in RAM (/tmp/logs, /tmp/log,
# the syslog in /var/log, dmesg) and are gone after a restart. Every 10 minutes and before a deliberate reboot, they
# are copied to the SD card, one folder per boot, so the cause of a crash can be read afterwards:
#
#   /mnt/sd/logs/boot-0007/{dmesg.log,syslog.log,tc100_rtsp.log,other.log,meta.txt}
#
# The boot number is a counter kept on the card (/mnt/sd/logs/.bootcount). The last 5 boots are kept (LOG_KEEP),
# each at most about 2 MB (every file is the tail of its source; a file is only rewritten when its content changed).
# Nothing is written when there is no card mounted read-write on /mnt/sd, when the recording is paused or the card
# is being ejected (/var/run/tc100rec.pause, scripts/rec-storage.sh), when the card is not healthy (/tmp/sd-health)
# or when it has less than 64 MB free. LOG_PERSIST=0 in config/boot.conf turns it off (read at every cycle).
#
#   log-persist.sh run              loop: first save after 2 minutes, then every LOG_PERSIST_MIN minutes (10)
#   log-persist.sh hk               one cycle for the housekeeper (scripts/housekeeper.sh runs this instead of "run")
#   log-persist.sh save [why]       one save now
#   log-persist.sh shutdown [why]   one save, before a reboot (called by scripts/reboot-tracker.sh intent)
#   log-persist.sh list             saved boots as JSON, newest first (www/cgi-bin/savedlogs.cgi)
#   log-persist.sh cat BOOT FILE    one saved file (names are checked)
# The paths and limits can be changed through LP_* variables (the tests do). Camera-side shell: busybox ash.

LP_SD=${LP_SD:-/mnt/sd}
LP_ROOT=${LP_ROOT:-$LP_SD/logs}
LP_MOUNTS=${LP_MOUNTS:-/proc/mounts}
LP_PAUSE=${LP_PAUSE:-/var/run/tc100rec.pause}
LP_HEALTH=${LP_HEALTH:-/tmp/sd-health}
LP_BOOTCONF=${LP_BOOTCONF:-/mnt/config/boot.conf}
LP_STATE=${LP_STATE:-/tmp/log-persist.dir}
LP_LOCK=${LP_LOCK:-/tmp/log-persist.lock}
LP_PIDFILE=${LP_PIDFILE:-/var/run/log-persist.pid}
LP_KEEP=${LP_KEEP:-5}
LP_FILECAP=${LP_FILECAP:-400000}      # bytes per file: 3 files + other.log (half) stay below the 2 MB of a boot
LP_OTHERCAP=${LP_OTHERCAP:-200000}
LP_BOOTCAP=${LP_BOOTCAP:-2097152}
LP_MIN_FREE_KB=${LP_MIN_FREE_KB:-65536}
LP_FIRST=${LP_FIRST:-120}
LP_SYSLOG=${LP_SYSLOG:-/var/log/messages.0 /var/log/messages}
LP_RTSPLOG=${LP_RTSPLOG:-/tmp/logs/tc100_rtsp.log}
LP_OTHER_DIRS=${LP_OTHER_DIRS:-/tmp/logs /tmp/log}
LP_DMESG_FILE=${LP_DMESG_FILE:-}      # tests: read this file instead of running dmesg

lp_conf() {   # KEY DEFAULT -> value of boot.conf (last line, quotes removed)
  _v=$(sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}\$/\1/p" "$LP_BOOTCONF" 2>/dev/null | tail -n 1)
  echo "${_v:-$2}"
}

lp_enabled() {
  case "$(lp_conf LOG_PERSIST 1)" in 0|no|off|false) return 1 ;; esac
  return 0
}

# the card is there, writable and healthy, and nobody is ejecting it
lp_card_ok() {
  grep -qE " $LP_SD (vfat|exfat) " "$LP_MOUNTS" 2>/dev/null || return 1
  [ -e "$LP_PAUSE" ] && return 1
  if [ -r "$LP_HEALTH" ]; then
    while IFS='=' read -r _k _v; do
      [ "$_k" = state ] && [ "$_v" != ok ] && return 1
    done < "$LP_HEALTH"
  fi
  if [ "$LP_MIN_FREE_KB" -gt 0 ]; then
    _free=$(df -k "$LP_SD" 2>/dev/null | awk 'NR>1{print $4; exit}')
    case "$_free" in ''|*[!0-9]*) return 1 ;; esac
    [ "$_free" -ge "$LP_MIN_FREE_KB" ] || return 1
  fi
  mkdir -p "$LP_ROOT" 2>/dev/null && [ -w "$LP_ROOT" ]
}

# the folder of this boot: the one remembered in RAM, else the next number of the card's counter
lp_dir() {
  D=
  if [ -r "$LP_STATE" ]; then
    read -r D < "$LP_STATE"
    [ -d "$D" ] || D=
  fi
  if [ -z "$D" ]; then
    _n=0
    [ -r "$LP_ROOT/.bootcount" ] && read -r _n < "$LP_ROOT/.bootcount"
    case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
    _n=$((_n + 1))
    [ "$_n" -le 9999 ] || _n=1
    printf '%04d\n' "$_n" > "$LP_ROOT/.bootcount" 2>/dev/null || return 1
    D="$LP_ROOT/boot-$(printf '%04d' "$_n")"
    rm -rf "$D" 2>/dev/null
    mkdir -p "$D" 2>/dev/null || return 1
    echo "$D" > "$LP_STATE" 2>/dev/null
  fi
  return 0
}

lp_commit() {   # NAME TMPFILE: replace the saved file only when the content changed
  if [ -s "$2" ] && ! cmp -s "$2" "$D/$1" 2>/dev/null; then mv -f "$2" "$D/$1"; else rm -f "$2"; fi
}

lp_rotate() {
  _cnt=0
  for _d in "$LP_ROOT"/boot-[0-9][0-9][0-9][0-9]; do [ -d "$_d" ] && _cnt=$((_cnt + 1)); done
  _del=$((_cnt - LP_KEEP))
  for _d in "$LP_ROOT"/boot-[0-9][0-9][0-9][0-9]; do
    [ "$_del" -gt 0 ] || break
    [ -d "$_d" ] || continue
    [ "$_d" = "$D" ] && continue
    rm -rf "$_d"; _del=$((_del - 1))
  done
}

lp_save() {   # $1 = why
  lp_enabled || return 0
  lp_card_ok || return 0
  # one saver at a time (the loop and a shutdown may meet); a lock of a dead process is taken over
  if ! mkdir "$LP_LOCK" 2>/dev/null; then
    { read -r _lpid < "$LP_LOCK/pid"; } 2>/dev/null
    if [ -n "$_lpid" ] && kill -0 "$_lpid" 2>/dev/null; then return 0; fi
    rm -rf "$LP_LOCK"; mkdir "$LP_LOCK" 2>/dev/null || return 0
  fi
  echo $$ > "$LP_LOCK/pid"
  lp_save_files "$1"
  _rc=$?
  rm -rf "$LP_LOCK"
  return $_rc
}

lp_save_files() {
  lp_dir || return 1
  # dmesg: the kernel's own ring buffer (oopses, SD or Wi-Fi errors)
  if [ -n "$LP_DMESG_FILE" ]; then tail -c "$LP_FILECAP" "$LP_DMESG_FILE" > "$D/.dmesg.tmp" 2>/dev/null
  else dmesg 2>/dev/null | tail -c "$LP_FILECAP" > "$D/.dmesg.tmp"; fi
  lp_commit dmesg.log "$D/.dmesg.tmp"
  # syslog (the notice level and above, RAM only), older part first
  { for _f in $LP_SYSLOG; do [ -f "$_f" ] && cat "$_f"; done; } 2>/dev/null | tail -c "$LP_FILECAP" > "$D/.syslog.tmp"
  lp_commit syslog.log "$D/.syslog.tmp"
  # the video server
  [ -f "$LP_RTSPLOG" ] && tail -c "$LP_FILECAP" "$LP_RTSPLOG" > "$D/.rtsp.tmp" 2>/dev/null
  lp_commit tc100_rtsp.log "$D/.rtsp.tmp"
  # everything else the services log in RAM, each file's tail with its name
  {
    for _dir in $LP_OTHER_DIRS; do
      for _f in "$_dir"/*; do
        [ -f "$_f" ] || continue
        [ "$_f" = "$LP_RTSPLOG" ] && continue
        echo "=== $_f ==="
        tail -c 30000 "$_f" 2>/dev/null
      done
    done
  } 2>/dev/null | tail -c "$LP_OTHERCAP" > "$D/.other.tmp"
  lp_commit other.log "$D/.other.tmp"
  # what this is
  _up=; read -r _up _ < /proc/uptime 2>/dev/null
  {
    echo "boot=${D##*/}"
    echo "saved=$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)"
    echo "uptime_s=${_up%.*}"
    echo "why=${1:-periodic}"
    echo "version=$(cat /mnt/VERSION 2>/dev/null)"
    echo "kernel=$(uname -r 2>/dev/null)"
  } > "$D/.meta.tmp"
  mv -f "$D/.meta.tmp" "$D/meta.txt"
  # a boot never keeps more than LP_BOOTCAP bytes: the least useful file goes first
  _sz=$(du -sk "$D" 2>/dev/null | awk '{print $1}')
  case "$_sz" in ''|*[!0-9]*) _sz=0 ;; esac
  [ "$_sz" -le $((LP_BOOTCAP / 1024)) ] || rm -f "$D/other.log"
  lp_rotate
  sync
  return 0
}

lp_json_str() { printf '%s' "$1" | sed 's/[^A-Za-z0-9 :._=+-]//g'; }

lp_list() {
  _cur=; [ -r "$LP_STATE" ] && read -r _cur < "$LP_STATE"
  _all=
  for _d in "$LP_ROOT"/boot-[0-9][0-9][0-9][0-9]; do [ -d "$_d" ] && _all="$_d $_all"; done
  printf '['
  _first=1
  for _d in $_all; do
    _saved=; _why=
    if [ -r "$_d/meta.txt" ]; then
      while IFS='=' read -r _k _v; do
        case "$_k" in saved) _saved="$_v" ;; why) _why="$_v" ;; esac
      done < "$_d/meta.txt"
    fi
    [ "$_first" = 1 ] || printf ','
    _first=0
    _c=0; [ "$_d" = "$_cur" ] && _c=1
    printf '{"boot":"%s","current":%s,"saved":"%s","why":"%s","files":[' "${_d##*/}" "$_c" "$(lp_json_str "$_saved")" "$(lp_json_str "$_why")"
    _ff=1
    for _f in "$_d"/*.log "$_d"/meta.txt; do
      [ -f "$_f" ] || continue
      [ "$_ff" = 1 ] || printf ','
      _ff=0
      printf '{"name":"%s","size":%s}' "${_f##*/}" "$(wc -c < "$_f" | awk '{print $1}')"
    done
    printf ']}'
  done
  printf ']\n'
}

lp_cat() {   # BOOT FILE
  case "$1" in boot-[0-9][0-9][0-9][0-9]) ;; *) echo "bad boot name" >&2; return 2 ;; esac
  case "$2" in ''|*[!A-Za-z0-9._-]*|.*) echo "bad file name" >&2; return 2 ;; esac
  [ -f "$LP_ROOT/$1/$2" ] || { echo "not found" >&2; return 1; }
  cat "$LP_ROOT/$1/$2"
}

# LOG_PERSIST_MIN in minutes, 1..1440, else 10 (-> $_m)
lp_minutes() {
  _m=$(lp_conf LOG_PERSIST_MIN 10)
  case "$_m" in ''|*[!0-9]*) _m=10 ;; esac
  [ "$_m" -ge 1 ] && [ "$_m" -le 1440 ] || _m=10
}

lp_run() {
  echo $$ > "$LP_PIDFILE" 2>/dev/null
  sleep "$LP_FIRST"
  while :; do
    lp_save periodic
    lp_minutes
    sleep $((_m * 60))
  done
}

# one cycle for scripts/housekeeper.sh (which runs it, the first time after LP_FIRST): save, then tell the
# housekeeper the period of the next run (LOG_PERSIST_MIN is read at every cycle)
lp_hk() {
  lp_save periodic
  lp_minutes
  mkdir -p "${HK_DIR:-/tmp/housekeeper}/period" 2>/dev/null
  echo $((_m * 60)) > "${HK_DIR:-/tmp/housekeeper}/period/log-persist" 2>/dev/null
}

if [ -z "$LP_TEST_SOURCE" ]; then
  case "$1" in
    run) lp_run ;;
    hk) lp_hk ;;
    save) lp_save "${2:-manual}" ;;
    shutdown) lp_save "shutdown${2:+: $2}" ;;
    list) lp_list ;;
    cat) lp_cat "$2" "$3" ;;
    *) echo "usage: $0 run | save [why] | shutdown [why] | list | cat BOOT FILE" >&2; exit 2 ;;
  esac
fi
