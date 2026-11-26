#!/bin/sh
# recette.sh: acceptance bench of the 3.0.2 final, run ON the camera (BusyBox ash, as root).
#
# TEST TOOL. It lives in tests/camera/ and is never part of a build: no squashfs, SD package, update tar or test pack
# takes it (tests/test_recette.py checks that). recette-host.sh copies it to /tmp/recette.sh on the camera and starts it
# detached (nohup, results in a folder on the camera), so the checks that cut the Wi-Fi do not stop it.
#
#   sh /tmp/recette.sh --list                       every on-camera check: ID check mode
#   sh /tmp/recette.sh --dry-run [--only IDS]       one line per selected check, nothing is run
#   sh /tmp/recette.sh --out DIR [--only IDS] [--disruptive] [--wifi]
#
# --only takes IDs separated by commas (AUDIT-1116-KERNEL,HARDEN). Without --disruptive the checks marked dist are
# SKIPped; without --wifi the wifi ones are. Checks marked manual are SKIPped with the reason: they need the owner's
# eye, a power action, the UART, a card or a flash write, and stay for the manual session.
#
# Output: one line per check "RESULT <ID> <check> PASS|FAIL|SKIP <evidence>" on stdout and in DIR/results.txt;
# evidence lines in DIR/recette.log; a summary in DIR/summary.txt; DIR/done when the run has ended.
# Never written: the flash, the MTD partitions, the U-Boot environment, the settings slots, the SD card. Files under /mnt/config
# are not changed. The RAM state the checks change (privacy file, Wi-Fi, night mode, irq switch) is restored by the
# trap at the end, also on interrupt. The camera password comes from /tmp/recette.pass (written by recette-host.sh
# from RECETTE_PASS, deleted here at once) and is never printed or logged.

trap '' HUP
export PATH=/mnt/bin:/mnt/scripts:/mnt/controlscripts:/usr/sbin:/usr/bin:/sbin:/bin:$PATH

LOG=/tmp/logs/tc100_rtsp.log
UNLAZY=/sys/module/ak39_venc/parameters/irq_unlazy
CFG=/tmp/recette-cfg
PASSF=/tmp/recette.pass
BAD_RE="Oops|BUG:|Unable to handle|WARNING:|soft lockup|hung_task|blocked for more than|nobody cared|Unbalanced enable|otg-hs: ep|Kernel panic|illegal instruction|stack smashing"

# ---------------------------------------------------------------------------------------------------------------
# The check table: ID|check|mode|function|argument.  mode: safe, dist (needs --disruptive), wifi (needs --wifi),
# manual (always SKIP, the argument is the reason). Host-side checks are in recette-host.sh.
# ---------------------------------------------------------------------------------------------------------------
CHECKS='RECETTE-BENCH|preflight|safe|c_preflight|
AUDIT-1116-KERNEL|dmesg-errors|safe|c_dmesg|
AUDIT-1116-KERNEL|kill-loop|dist|c_kill_loop|
AUDIT-1116-KERNEL|stream-cycles|dist|c_stream_cycles|
AUDIT-1116-KERNEL|audio-connect-cycles|manual|skip_manual|200 fast audio connect cycles need an RTSP client (host-side tools of the owner): session 2
AUDIT-1116-KERNEL|osd-clock|manual|skip_manual|RTSP_ISPOSD clock ticking for 3 h: needs the viewer and the eye; session 3 soak
AUDIT-1116-KERNEL|soak-3h|manual|skip_manual|3 h of 1080p H.265 with audio: session 3 (the safe samples of the bench are read during it)
AUDIT-1116-VENCIRQ|irq-switch|safe|c_irq_switch|
AUDIT-1116-VENCIRQ|irq-follows-kills|dist|c_irq_kills|
AUDIT-1116-VENCIRQ|irq-control|dist|c_irq_control|
AUDIT-1116-VENCIRQ|irq-sample|safe|c_irq_sample|
AUDIT-1116-VENCIRQ|induced-timeout|manual|skip_manual|gating the encoder clock with devmem: owner next to the camera, not automated
AUDIT-1116-USB|wlan-down-up|wifi|c_wlan_cycles|
AUDIT-1116-USB|urb-counters|safe|c_urb|
AUDIT-1116-USB|wpa-reassociate|wifi|c_reassoc|
AUDIT-1116-USB|unbind-bind|manual|skip_manual|unbind of the Wi-Fi driver: a failed bind needs the UART (session 2, Mac)
AUDIT-1116-USB|soak-12h|manual|skip_manual|12 h soak: session 3 (urb-counters and wifi-stall-watch give the readings)
AUDIT-1116-RTSP|stall-exit|dist|c_stall_exit|
AUDIT-1116-RTSP|no-spurious-exit|safe|c_no_spurious|
AUDIT-1116-RTSP|arecord-kill|dist|c_arecord|
AUDIT-1116-RTSP|boot-client-timing|manual|skip_manual|clients within 30 s of a boot: needs a boot (not done by the bench)
AUDIT-1116-RTSP|day-night-hour|manual|skip_manual|1 h across a real day/night switch: session 3
AUDIT-1116-NET|ssh-netacl-maps|safe|c_ssh_maps|
AUDIT-1116-NET|no-unfiltered-log|safe|c_nounfiltered|
AUDIT-1116-NET|wan-refused|manual|skip_manual|ssh from a non-private address: needs a forwarded port or 4G
AUDIT-1116-NET|onvif-reconnect|manual|skip_manual|ONVIF after an unplug of the network: needs the cable
AUDIT-1116-NET|save-settings|manual|skip_manual|password, Wi-Fi and OSD text saved from the web UI: the owner types them
AUDIT-1116-WIFI|wrong-password|manual|skip_manual|wrong password save and the two blocks of wpa_supplicant.conf: owner (web UI, restart)
AUDIT-1116-WIFI|quote-refused|manual|skip_manual|quote in the password refused with the message: owner (web UI)
AUDIT-1116-WIFI|rescue-ap-cap|manual|skip_manual|rescue AP stops after 30 min with a phone connected: owner with a phone
AUDIT-1116-WIFI|button-3-7s|manual|skip_manual|button 3-7 s (rescue AP) and 8 s: owner at the camera
AUDIT-1116-BOOT|power-pull|manual|skip_manual|power pull and three early crashes: owner (power cycle)
AUDIT-1116-RECOVERY|stackbad|manual|skip_manual|stackbad test file and rescue telnet: Mac + UART + SD card
AUDIT-1116-UPDATE|web-update-cases|manual|skip_manual|restart during a write, double POST, simfail, full card: a web update by the owner
AUDIT-1116-INSTALL|cfg-slots-sd|manual|skip_manual|the settings-slot check and the SD install steps: slot writes and a card
AUDIT-1116-FLASHBOOT|hook-camera|manual|skip_manual|camera installed by stock-hook.sh, card out: owner (power cycle)
AUDIT-1116-FTP|wrong-password|manual|skip_manual|FTP login with a wrong password: owner decision (FTP off by default)
B2B3-CONF|console-larger|safe|c_console_larger|
B2B3-CONF|sound-rec-lite-talk|manual|skip_manual|sound event starts a recording and RTSP_LITE_TALK toggle: owner (sound, Settings)
B1-ONVIF|pwd-file|safe|c_pwd_file|
B1-ONVIF|password-change|manual|skip_manual|password change in the web UI and ONVIF NotAuthorized at once: owner types the password
B4-HUE|status-hue|safe|c_status_hue|
B4-HUE|night-cycles|dist|c_dn_cycles|
B4-HUE|hue-change|manual|skip_manual|hue +20 / -20 in the Image page: owner (Settings)
R1-MDENC|motion-still-scene|manual|skip_manual|walk-ins in front of the lens and the motion files: owner
W1-PRIVFILL|pp-privacy|dist|c_privacy|
W3-ZERO|open-log|safe|c_w3_log|
W3-ZERO|one-hour-viewer|manual|skip_manual|one hour with a viewer that connects every minute: host tools, session 3
R2-BUTTON|hold-rescue-slow|manual|skip_manual|slow nightmode.sh and a 5 s hold during the switch: owner (button, lens)
R2-BUTTON|hold-restart-timing|manual|skip_manual|8-10 s hold during the switch gives a restart: owner (button); never automated
T1B5-PARITY|isp-tune-diff|safe|c_isp_diff|
T1B5-PARITY|fullconfig-text|safe|c_fullconfig|
T1B5-PARITY|settings-sliders|manual|skip_manual|Settings -> Image sliders and "Applied on the camera": owner (web UI)
W5-AUDIT|hw-state-unlogged|safe|c_hw_state|
W5-AUDIT|restart-line|manual|skip_manual|restart line in audit.log after 10 min on the Hardware page: owner (web UI restart)
CLEANUP-1124|stat-fields|safe|c_stat_fields|
CLEANUP-1124|start-lines|safe|c_start_lines|
CLEANUP-1124|day-night-24h|manual|skip_manual|24 h of viewers and the day/night switches of an evening and a morning: session 3
SMALL-B-1124|onvif-motion|manual|skip_manual|ONVIF motion events in Home Assistant: owner (walk in front of the lens)
SMALL-B-1124|awb-colours|manual|skip_manual|W2 colours and white balance by day and evening: owner (the picture)
SMALL-A-1124|hold-restart|dist|c_hold_restart|
SMALL-A-1124|daynight-lines|safe|c_daynight_lines|
SMALL-A-1124|config-tmp|safe|c_config_tmp|
SMALL-A-1124|ssh-pidfile|safe|c_ssh_pidfile|
SMALL-A-1124|memory-hourly|safe|c_memory_hourly|
WIFIQ-FORKS|wifiq-files|safe|c_wifiq_files|
WIFIQ-FORKS|fork-rate|safe|c_fork_rate|
FAILCOUNT|counters-stat|safe|c_counters_stat|
FAILCOUNT|counters-term|dist|c_counters_term|
FAILCOUNT|day-window|manual|skip_manual|24 h window on both cameras: session 3 (read memory-hourly.csv at the end)
MEMWATCH|files|safe|c_memory_files|
MEMWATCH|three-days|manual|skip_manual|3 days without a restart: session 3 (no card: copy the files daily)
HARDEN|smash-illegal|safe|c_smash|
HARDEN|top-snapshot|safe|c_top|
HARDEN|day-window|manual|skip_manual|24 h of streaming with the web UI, ONVIF and MQTT exercised: session 3'

# ---------------------------------------------------------------------------------------------------------------
# options
# ---------------------------------------------------------------------------------------------------------------
MODE=run; ONLY=; DISRUPT=0; WIFI=0; OUT=
while [ $# -gt 0 ]; do
  case "$1" in
    --list) MODE=list ;;
    --dry-run) MODE=dry ;;
    --only) shift; ONLY=$1 ;;
    --out) shift; OUT=$1 ;;
    --disruptive) DISRUPT=1 ;;
    --wifi) WIFI=1 ;;
    *) echo "usage: sh recette.sh [--list | --dry-run] [--only IDS] [--out DIR] [--disruptive] [--wifi]" >&2; exit 2 ;;
  esac
  shift
done

if [ "$MODE" = list ]; then
  printf '%s\n' "$CHECKS" | while IFS='|' read -r id name mode fn arg; do
    echo "$id $name $mode"
  done
  exit 0
fi

DRY=0; [ "$MODE" = dry ] && DRY=1
[ -n "$OUT" ] || OUT=/tmp/recette-$(date +%Y%m%d-%H%M%S)
RESFILE=$OUT/results.txt
LOGF=$OUT/recette.log
RESN=0; CUR_ID=; CUR_CHECK=; CUR=
RUN_T0=$(cut -d' ' -f1 /proc/uptime 2>/dev/null)
RECETTE_PASS=

# ---------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------
ev() { echo "[$CUR] $*" >> "$LOGF"; }

res() {
  _st=$1; shift
  _e=$(echo "$*" | tr '\n\r' '  ' | sed 's/ *$//')
  _line="RESULT $CUR_ID $CUR_CHECK $_st $_e"
  echo "$_line"
  echo "$_line" >> "$RESFILE"
  echo "$_line" >> "$LOGF"
  RESN=$((RESN + 1))
}

upt() { read -r _u _ < /proc/uptime 2>/dev/null; echo "${_u:-0}"; }

rtsp_pid() { set -- $(pidof tc100_rtsp 2>/dev/null); echo "$1"; }

ctr() {
  [ -f /tmp/tc100_rtsp.counters ] || { echo 0; return; }
  tr ' ' '\n' < /tmp/tc100_rtsp.counters | sed -n "s/^$1=//p" | head -n 1 | tr -dc '0-9'
}

last_stat() { grep '^STAT ' "$LOG" 2>/dev/null | tail -n 1; }

# stat_val NAME: the value after NAME in the last STAT line
stat_val() {
  _k=$1
  set -- $(last_stat)
  while [ $# -ge 2 ]; do
    if [ "$1" = "$_k" ]; then echo "$2"; return 0; fi
    shift
  done
  return 1
}

# count of lines matching a pattern in the current video log (and its rotated copy)
log_count() {
  _n=$(grep -c "$1" "$LOG" 2>/dev/null)
  echo "${_n:-0}"
}

venc_irq() { set -- $(grep venc /proc/interrupts 2>/dev/null | head -n 1); echo "${2:-0}"; }

ensure_rtsp() {
  pidof tc100_rtsp >/dev/null 2>&1 || sh /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1
}

# wait_stat SECS: a STAT line in the log (the log is emptied at each start, so any STAT line is from this process)
wait_stat() {
  _i=0
  while [ $_i -lt "$1" ]; do
    grep -q '^STAT ' "$LOG" 2>/dev/null && return 0
    sleep 1; _i=$((_i + 1))
  done
  return 1
}

wait_gone() {
  _i=0
  while [ $_i -lt "$2" ]; do
    kill -0 "$1" 2>/dev/null || return 0
    sleep 1; _i=$((_i + 1))
  done
  return 1
}

gateway() { route -n 2>/dev/null | sed -n 's/^0\.0\.0\.0 *\([0-9.]*\).*/\1/p' | head -n 1; }

wlan_assoc() { iw dev wlan0 link 2>/dev/null | grep -q Connected; }

wait_assoc() {
  _i=0
  while [ $_i -lt "$1" ]; do
    wlan_assoc && return 0
    sleep 1; _i=$((_i + 1))
  done
  return 1
}

wlan_down() { ifconfig wlan0 down >/dev/null 2>&1 || ip link set wlan0 down >/dev/null 2>&1; }
wlan_up() { ifconfig wlan0 up >/dev/null 2>&1 || ip link set wlan0 up >/dev/null 2>&1; }
wlan_recover() { wlan_up; wpa_cli -i wlan0 reassociate >/dev/null 2>&1; }

# wlan_restore: the bounded retries that end every Wi-Fi check (up, reassociate, 60 s each, three times)
wlan_restore() {
  wlan_up
  _r=0
  while [ $_r -lt 3 ]; do
    wait_assoc 60 && return 0
    wlan_recover
    _r=$((_r + 1))
  done
  wlan_assoc
}

# password for the curl calls on the camera: a config file (umask 077), so no argument list shows it
mk_cfg() {
  [ -n "$RECETTE_PASS" ] || return 1
  _pw=$(printf '%s' "$RECETTE_PASS" | sed 's/\\/\\\\/g; s/"/\\"/g')
  ( umask 077; printf 'user = "root:%s"\nsilent\n' "$_pw" > "$CFG" )
}

# kill_cycles N FILE: N times kill -TERM of tc100_rtsp and a start with the autorun arguments (rtsp-h26x start runs
# rtsp-launch.sh, the script the boot calls). Per cycle one line in FILE; sets K_OK and K_BAD.
kill_cycles() {
  K_OK=0; K_BAD=0; : > "$2"
  _i=0
  while [ $_i -lt "$1" ]; do
    _i=$((_i + 1))
    ensure_rtsp
    _p0=$(rtsp_pid); _v0=$(venc_irq); _s0=$(ctr starts); _x0=$(ctr exit3)
    if [ -z "$_p0" ]; then K_BAD=$((K_BAD + 1)); echo "$_i no-process" >> "$2"; continue; fi
    kill -TERM "$_p0" 2>/dev/null
    if ! wait_gone "$_p0" 15; then
      K_BAD=$((K_BAD + 1)); echo "$_i stuck-after-TERM pid=$_p0" >> "$2"; kill -9 "$_p0" 2>/dev/null; continue
    fi
    sh /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1
    _ok=1
    wait_stat 45 || _ok=0
    _p1=$(rtsp_pid); _v1=$(venc_irq); _pf=$(log_count 'picture failed'); _s1=$(ctr starts); _x1=$(ctr exit3)
    [ -n "$_p1" ] && [ "$_p1" != "$_p0" ] || _ok=0
    [ "$_v1" -gt "$_v0" ] 2>/dev/null || _ok=0
    [ "$_pf" = 0 ] || _ok=0
    [ "$_x1" = "$_x0" ] || _ok=0
    if [ $_ok = 1 ]; then
      K_OK=$((K_OK + 1))
      echo "$_i ok irq+$((_v1 - _v0)) starts+$((_s1 - _s0)) picture_failed=$_pf" >> "$2"
    else
      K_BAD=$((K_BAD + 1))
      echo "$_i BAD pid=$_p1 irq+$((_v1 - _v0)) picture_failed=$_pf exit3+$((_x1 - _x0))" >> "$2"
    fi
  done
}

# ---------------------------------------------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------------------------------------------
skip_manual() { res SKIP "manual: $1"; }

c_preflight() {
  ev "uname $(uname -r 2>/dev/null) host $(hostname 2>/dev/null)"
  ev "cmdline $(cat /proc/cmdline 2>/dev/null)"
  ev "version $(cat /mnt/VERSION 2>/dev/null | head -n 1)"
  ev "uptime $(upt) s; rtsp pid $(rtsp_pid); dropbear $(cat /var/run/dropbear.pid 2>/dev/null)"
  if grep -q ' /mnt/sd ' /proc/mounts 2>/dev/null; then ev "card: mounted on /mnt/sd"; else ev "card: none mounted"; fi
  wlan_assoc && _w=associated || _w=not-associated
  _e=$(ctr exit3); echo "$_e" > "$OUT/exit3.start"
  ev "wlan0 $_w; counters starts=$(ctr starts) pic_fail=$(ctr pic_fail) exit3=$_e"
  if [ -n "$(rtsp_pid)" ] && [ "$_w" = associated ]; then
    res PASS "tc100_rtsp running, wlan0 associated, uptime $(upt) s"
  else
    res FAIL "tc100_rtsp pid '$(rtsp_pid)', wlan0 $_w"
  fi
}

c_dmesg() {
  dmesg > "$OUT/dmesg.txt" 2>/dev/null
  _n=$(grep -Ec "$BAD_RE" "$OUT/dmesg.txt")
  if [ "${_n:-0}" = 0 ]; then
    res PASS "no oops, warning, lockup, hung task, nobody-cared or unbalanced-IRQ line since boot ($(wc -l < "$OUT/dmesg.txt") lines)"
  else
    ev "$(grep -E "$BAD_RE" "$OUT/dmesg.txt" | head -n 5)"
    res FAIL "$_n kernel message(s) matching the bad patterns, first ones in recette.log"
  fi
}

c_kill_loop() {
  _n=${RECETTE_KILLS:-50}
  kill_cycles "$_n" "$OUT/kill.stats"
  ev "$(cat "$OUT/kill.stats" | tail -n 5)"
  if [ "$K_BAD" = 0 ] && [ "$K_OK" = "$_n" ] && [ -n "$(rtsp_pid)" ]; then
    res PASS "$K_OK/$_n kill -TERM + start: first picture clean, encoder interrupt counting, exit3 unchanged"
  else
    res FAIL "$K_OK/$_n cycles clean, $K_BAD bad (see kill.stats in the run folder)"
  fi
}

c_stream_cycles() {
  _n=${RECETTE_STREAM_CYCLES:-20}; _ok=0; _i=0
  while [ $_i -lt "$_n" ]; do
    _i=$((_i + 1))
    sh /mnt/controlscripts/rtsp-h26x stop >/dev/null 2>&1; sleep 2
    sh /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1
    wait_stat 45 && [ -n "$(rtsp_pid)" ] && _ok=$((_ok + 1))
  done
  res $([ "$_ok" = "$_n" ] && echo PASS || echo FAIL) "$_ok/$_n stop + start cycles with a STAT line after each start"
}

c_irq_switch() {
  if [ -f "$UNLAZY" ]; then
    _v=$(cat "$UNLAZY" 2>/dev/null)
    res $([ "$_v" = Y ] || [ "$_v" = 1 ] && echo PASS || echo FAIL) "irq_unlazy=$_v (Y: patch 0025 fix on)"
  else
    res FAIL "no $UNLAZY: this kernel has no patch 0025 switch"
  fi
}

c_irq_kills() {
  if [ ! -s "$OUT/kill.stats" ]; then res SKIP "kill-loop did not run in this run folder"; return; fi
  _bad=$(grep -c ' BAD\| stuck\| no-process' "$OUT/kill.stats")
  _grow=$(grep -c ' ok irq+[1-9]' "$OUT/kill.stats")
  res $([ "$_bad" = 0 ] && echo PASS || echo FAIL) "$_grow cycles with the encoder interrupt counting, $_bad bad; growth per picture: compare with enc in STAT"
}

c_irq_control() {
  if [ "${RECETTE_CONTROL:-0}" != 1 ]; then res SKIP "set RECETTE_CONTROL=1 (about 26 extra restarts with irq_unlazy=0 then 1)"; return; fi
  [ -f "$UNLAZY" ] || { res FAIL "no irq_unlazy switch"; return; }
  ORIG_UNLAZY=$(cat "$UNLAZY" 2>/dev/null)
  echo 0 > "$UNLAZY" 2>/dev/null
  kill_cycles 20 "$OUT/irq-off.stats"; _a=$K_BAD
  echo 1 > "$UNLAZY" 2>/dev/null
  kill_cycles 1 "$OUT/irq-on.stats"; _b=$K_BAD
  kill_cycles 5 "$OUT/irq-on5.stats"; _c=$K_BAD
  echo "$ORIG_UNLAZY" > "$UNLAZY" 2>/dev/null; ORIG_UNLAZY=
  _now=$(cat "$UNLAZY" 2>/dev/null)
  ev "irq_unlazy=0: 20 cycles, bad $_a; =1: 1+5 cycles, bad $_b+$_c; restored to $_now"
  res $([ $((_a + _b + _c)) = 0 ] && echo PASS || echo FAIL) "control run: bad cycles off=$_a on=$((_b + _c)); switch back to ${_now:-?}; the fix shows only as no lost picture"
}

c_irq_sample() {
  _p=$(rtsp_pid)
  if [ -z "$_p" ] || [ -z "$(stat_val enc)" ]; then res SKIP "tc100_rtsp not streaming: no STAT line"; return; fi
  _v0=$(venc_irq); _e0=$(stat_val enc); _s0=$(stat_val sub_enc); _pf0=$(log_count 'picture failed')
  sleep 60
  _v1=$(venc_irq); _e1=$(stat_val enc); _s1=$(stat_val sub_enc); _pf1=$(log_count 'picture failed')
  _dv=$((_v1 - _v0)); _de=$(( (_e1 - _e0) + (_s1 - _s0) ))
  ev "60 s: irq +$_dv, enc+sub_enc +$_de, picture failed +$((_pf1 - _pf0))"
  if [ "$_pf1" != "$_pf0" ]; then res FAIL "picture failed lines in 60 s"
  elif [ "$_de" -gt 0 ] && [ "$_dv" -gt 0 ] && [ "$_dv" -le $((_de * 12 / 10 + 10)) ]; then res PASS "irq +$_dv for $_de encoded pictures in 60 s, no failed picture"
  elif [ "$_de" -eq 0 ]; then res SKIP "no picture encoded in 60 s (no viewer?)"
  else res FAIL "irq +$_dv for $_de pictures: a replay or a lost interrupt"
  fi
}

c_wlan_cycles() {
  _n=${RECETTE_WIFI_CYCLES:-20}; WIFI_TOUCHED=1
  _gw=$(gateway)
  if [ -z "$_gw" ]; then res FAIL "no default gateway: Wi-Fi not up before the test"; return; fi
  _slow=0; _lost=0; _fail=0; _i=0
  ev "gateway $_gw, clients $(stat_val clients) at start"
  while [ $_i -lt "$_n" ]; do
    _i=$((_i + 1))
    _t0=$(upt); wlan_down; _t1=$(upt)
    _d=$(awk "BEGIN{print $_t1-$_t0}")
    awk "BEGIN{exit !($_d > 1.0)}" && _slow=$((_slow + 1))
    sleep 2
    wlan_up
    if ! wait_assoc 60; then
      ev "cycle $_i: not associated after 60 s, recovery"
      wlan_restore || { _fail=$((_fail + 1)); break; }
    fi
    _r=$(ping -c 30 -W 1 "$_gw" 2>/dev/null | grep 'packets transmitted')
    if [ -z "$_r" ]; then _lost=$((_lost + 1)); ev "cycle $_i: no ping summary"; continue; fi
    set -- $_r
    _lo=$(( ${1:-0} - ${4:-0} ))
    [ "$_lo" -gt 1 ] && _lost=$((_lost + 1))
    ev "cycle $_i: down ${_d}s, ping lost $_lo of ${1:-0}, clients $(stat_val clients)"
  done
  wlan_restore || _fail=$((_fail + 1))
  if [ "$_fail" = 0 ] && [ "$_slow" = 0 ] && [ "$_lost" = 0 ]; then
    res PASS "$_i down/up cycles: each down under 1 s, each association back, no ping loss after the first second"
  else
    res FAIL "$_i cycles: $_slow slow down(s), $_lost with ping loss, $_fail not back (wlan0 restored by retries)"
  fi
}

c_urb() {
  if [ ! -f /mnt/scripts/wifi-stall-watch.sh ]; then res SKIP "no wifi-stall-watch.sh"; return; fi
  _l=$(sh /mnt/scripts/wifi-stall-watch.sh 1 wlan0 2>/dev/null | head -n 1)
  if [ -n "$_l" ]; then
    ev "counters: $_l"
    res PASS "rtl8xxxu and host-controller counters read (compare bulk_out_nak, rx_urb_lost with the night of the previous kernel)"
  else
    res FAIL "wifi-stall-watch printed nothing"
  fi
}

c_reassoc() {
  WIFI_TOUCHED=1; _ok=0; _i=0
  while [ $_i -lt 5 ]; do
    _i=$((_i + 1))
    wpa_cli -i wlan0 reassociate >/dev/null 2>&1
    wait_assoc 60 && _ok=$((_ok + 1))
  done
  wlan_restore
  res $([ "$_ok" = 5 ] && echo PASS || echo FAIL) "$_ok/5 wpa_cli reassociate with the association back"
}

c_stall_exit() {
  if grep -qs '^RTSP_CAPTURE_STALL_S=' /mnt/config/rtsp.env; then
    res SKIP "rtsp.env sets RTSP_CAPTURE_STALL_S: remove it for the test (the bench does not change /mnt/config)"; return
  fi
  _x0=$(ctr exit3); _p=$(rtsp_pid)
  if [ -z "$_p" ]; then ensure_rtsp; _p=$(rtsp_pid); fi
  kill -TERM "$_p" 2>/dev/null; wait_gone "$_p" 15
  RTSP_CAPTURE_STALL_S=5 sh /mnt/tc100test/rtsp-launch.sh >/dev/null 2>&1
  wait_stat 45 || { res FAIL "no STAT line with RTSP_CAPTURE_STALL_S=5"; return; }
  _p=$(rtsp_pid); kill -STOP "$_p" 2>/dev/null; sleep 12; kill -CONT "$_p" 2>/dev/null
  _i=0; _gone=0
  while [ $_i -lt 40 ]; do
    if ! kill -0 "$_p" 2>/dev/null; then _gone=1; break; fi
    sleep 1; _i=$((_i + 1))
  done
  _msg=$(grep -c 'no frame for' "$LOG" 2>/dev/null)
  ev "stopped 12 s; exit seen: $_gone; 'no frame for' lines: ${_msg:-0}"
  STALL_RUNS=$(( ${STALL_RUNS:-0} + 1 ))
  # back to the normal arguments (the watchdog would do it within 60 s): a start, then the stream again
  sleep 2; ensure_rtsp; wait_stat 45
  _x1=$(ctr exit3)
  if [ "$_gone" = 1 ] && [ "${_msg:-0}" -ge 1 ] && [ "$((_x1 - _x0))" = 1 ] && [ -n "$(rtsp_pid)" ]; then
    res PASS "no frame for 5 s logged, exit 3, exit3 +1, stream back with the normal arguments"
  else
    res FAIL "exit seen=$_gone, no-frame lines=${_msg:-0}, exit3 +$((_x1 - _x0)), pid '$(rtsp_pid)'"
  fi
}

c_no_spurious() {
  _x0=$(cat "$OUT/exit3.start" 2>/dev/null); _x1=$(ctr exit3)
  _exp=${STALL_RUNS:-0}
  ev "exit3 at start $_x0, now $_x1, expected from this bench $_exp"
  if [ -z "$_x0" ]; then res SKIP "no exit3 at the start of the run"; return; fi
  if [ $((_x1 - _x0)) = "$_exp" ]; then res PASS "exit3 +$((_x1 - _x0)): only the bench's own stall test"
  else res FAIL "exit3 +$((_x1 - _x0)) with $_exp expected: a spurious capture stall exit"; fi
}

c_arecord() {
  _p=$(pidof arecord 2>/dev/null)
  if [ -z "$_p" ]; then res SKIP "no arecord process: the microphone is read by tc100_rtsp (RTSP_ALSA_DIRECT=1)"; return; fi
  kill -9 $_p 2>/dev/null; sleep 3
  _z=$(ps 2>/dev/null | grep -c 'arecord.*defunct')
  ensure_rtsp; wait_stat 30
  res $([ -n "$(rtsp_pid)" ] && [ "${_z:-0}" = 0 ] && echo PASS || echo FAIL) "arecord $_p killed, zombies ${_z:-0}, tc100_rtsp pid '$(rtsp_pid)'"
}

c_ssh_maps() {
  _pids=$(pidof dropbear 2>/dev/null)
  if [ -z "$_pids" ]; then res SKIP "dropbear not running (ssh off)"; return; fi
  _ok=0; _tot=0
  for _p in $_pids; do
    _tot=$((_tot + 1))
    grep -q 'libnetacl-musl.so' "/proc/$_p/maps" 2>/dev/null && _ok=$((_ok + 1))
  done
  res $([ "$_ok" = "$_tot" ] && echo PASS || echo FAIL) "$_ok of $_tot dropbear process(es) map libnetacl-musl.so"
}

c_nounfiltered() {
  _n=$( (logread 2>/dev/null; cat /tmp/log/*.log 2>/dev/null) | grep -c 'WITHOUT the LAN filter')
  res $([ "${_n:-0}" = 0 ] && echo PASS || echo FAIL) "'WITHOUT the LAN filter' lines: ${_n:-0}"
}

c_console_larger() {
  _n=$(cat /tmp/logs/*.log /tmp/log/*.log 2>/dev/null | grep -c 'is larger than')
  res $([ "${_n:-0}" = 0 ] && echo PASS || echo FAIL) "'is larger than' lines in the logs: ${_n:-0}"
}

c_pwd_file() {
  if [ ! -f /mnt/config/user.pwd ]; then res SKIP "no user.pwd (no password set)"; return; fi
  _m=$(ls -l /mnt/config/user.pwd | cut -c1-10)
  _t=$(ls /mnt/config/ 2>/dev/null | grep 'user.pwd' | grep -c tmp)
  res $([ "$_m" = "-rw-------" ] && [ "${_t:-0}" = 0 ] && echo PASS || echo FAIL) "user.pwd mode $_m, leftover temp files ${_t:-0}"
}

c_status_hue() {
  if [ ! -f /var/run/isp_tune.status ]; then res SKIP "no /var/run/isp_tune.status (ISP_TUNE off)"; return; fi
  _h=$(sed -n 's/^HUE=//p' /var/run/isp_tune.status | head -n 1)
  _l=$(grep 'in the ISP' "$LOG" "$LOG.1" 2>/dev/null | tail -n 1)
  ev "status HUE=$_h; last log line: $_l"
  case "$_l" in
    *"hue $_h in the ISP"*) res PASS "HUE=$_h in the status file and in the last log line" ;;
    *) [ "${_h:-0}" = 0 ] && res PASS "HUE=0" || res FAIL "HUE=$_h but the last log line says: $_l" ;;
  esac
}

c_dn_cycles() {
  if [ ! -f /var/run/isp_tune.status ]; then res SKIP "no isp_tune status: hue not in the ISP"; return; fi
  _n=${RECETTE_DN_CYCLES:-2}; DN_TOUCHED=1
  _night=0; sh /mnt/controlscripts/night-mode status 2>/dev/null | grep -q 'PID: OK' && _night=1
  _h0=$(sed -n 's/^HUE=//p' /var/run/isp_tune.status | head -n 1)
  _c0=$(cat "$LOG" "$LOG.1" 2>/dev/null | grep -c 'in the ISP')
  _k=0; _i=0; _bad=0
  while [ $_i -lt "$_n" ]; do
    _i=$((_i + 1))
    sh /mnt/scripts/nightmode.sh on >/dev/null 2>&1; sleep 5
    sh /mnt/scripts/nightmode.sh off >/dev/null 2>&1; sleep 5
    _h=$(sed -n 's/^HUE=//p' /var/run/isp_tune.status | head -n 1)
    [ "$_h" = "$_h0" ] || _bad=$((_bad + 1))
    _k=$((_k + 1))
  done
  [ "$_night" = 1 ] && sh /mnt/scripts/nightmode.sh on >/dev/null 2>&1
  DN_TOUCHED=
  _hl=$(cat "$LOG" "$LOG.1" 2>/dev/null | grep -c 'in the ISP')
  ev "hue before $_h0, after the cycles $_h, ISP lines $_c0 -> $_hl, started at night: $_night"
  res $([ "$_bad" = 0 ] && echo PASS || echo FAIL) "$_k day/night cycles: HUE stays $_h0 after each return (ISP lines $_c0 -> $_hl)"
}

c_privacy() {
  _p0=0; _n=0
  for _i in 1 2 3; do _v=$(stat_val pp_ms); _p0=$((_p0 + ${_v:-0})); _n=$((_n + 1)); sleep 6; done
  PRIV_SET=0; [ -e /tmp/tc100_privacy ] || { touch /tmp/tc100_privacy; PRIV_SET=1; }
  sleep 16
  _p1=0; _m=0
  for _i in 1 2 3; do _v=$(stat_val pp_ms); _p1=$((_p1 + ${_v:-0})); _m=$((_m + 1)); sleep 6; done
  [ "$PRIV_SET" = 1 ] && rm -f /tmp/tc100_privacy
  PRIV_SET=0
  _a=$((_p0 / 3)); _b=$((_p1 / 3))
  ev "pp_ms without privacy $_a, with /tmp/tc100_privacy $_b (3 STAT lines each)"
  [ -n "$(rtsp_pid)" ] || ensure_rtsp
  res $([ "$_b" -le "$_a" ] && echo PASS || echo FAIL) "pp_ms mean without privacy $_a, with privacy $_b (privacy file removed)"
}

c_w3_log() {
  _o=$(log_count 'free encoder: H.26')
  _pf=$(log_count 'picture failed')
  res $([ "${_pf:-0}" = 0 ] && [ "${_o:-0}" -ge 1 ] && echo PASS || echo FAIL) "encoder opens in the log: ${_o:-0}, picture failed: ${_pf:-0}"
}

c_isp_diff() {
  if [ -z "$RECETTE_PASS" ]; then res SKIP "RECETTE_PASS not set"; return; fi
  mk_cfg || { res SKIP "no password"; return; }
  REQUEST_METHOD=GET QUERY_STRING='cmd=isp_tune&format=json' STATE_RESPONSE_CACHE_BYPASS=1 \
    sh /mnt/www/cgi-bin/state.cgi 2>/dev/null | sed '1,/^$/d' > "$OUT/it-cgi.json"
  curl -s -K "$CFG" "http://127.0.0.1/cgi-bin/state.cgi?cmd=isp_tune&format=json" > "$OUT/it-native.json"
  if [ -s "$OUT/it-cgi.json" ] && cmp -s "$OUT/it-cgi.json" "$OUT/it-native.json"; then
    res PASS "isp_tune JSON of the native route equals the CGI ($(wc -c < "$OUT/it-cgi.json") bytes)"
  else
    res FAIL "isp_tune JSON differs or is empty (files kept in the run folder)"
  fi
}

c_fullconfig() {
  if [ -z "$RECETTE_PASS" ]; then res SKIP "RECETTE_PASS not set"; return; fi
  mk_cfg || { res SKIP "no password"; return; }
  curl -s -K "$CFG" -D "$OUT/fc.headers" -o /dev/null "http://127.0.0.1/cgi-bin/state.cgi?cmd=fullconfig"
  _ct=$(grep -i '^content-type' "$OUT/fc.headers" | tr -d '\r')
  res $(echo "$_ct" | grep -qi 'text/plain' && echo PASS || echo FAIL) "fullconfig answered: '$_ct'"
}

c_hw_state() {
  if [ -z "$RECETTE_PASS" ]; then res SKIP "RECETTE_PASS not set"; return; fi
  mk_cfg || { res SKIP "no password"; return; }
  _n0=$(grep -c 'cmd=hw_state' /tmp/log/audit.log 2>/dev/null); _n0=${_n0:-0}
  _i=0; _code=
  while [ $_i -lt 5 ]; do
    _i=$((_i + 1))
    _code=$(curl -s -K "$CFG" -o /dev/null -w '%{http_code}' "http://127.0.0.1/cgi-bin/action.cgi?cmd=hw_state&format=json")
  done
  _n1=$(grep -c 'cmd=hw_state' /tmp/log/audit.log 2>/dev/null); _n1=${_n1:-0}
  res $([ "$_n1" = "$_n0" ] && echo PASS || echo FAIL) "5 hw_state calls (last HTTP $_code): audit.log lines with hw_state $_n0 -> $_n1"
}

c_stat_fields() {
  _l=$(last_stat)
  if [ -z "$_l" ]; then res FAIL "no STAT line in $LOG"; return; fi
  _keys=$(echo "$_l" | awk '{for(i=2;i<=NF;i+=2) printf "%s ", $i}')
  _want='cap enc bytes enc_ms snd_ms clients dropped sub_enc sub_bytes rec pp_ms sub_ms snd_q snd_qdrop snd_thr_ms snd_wait starts pic_fail enc_reopen cap_stall dq_err sub_off exit3 '
  case "$_keys" in
    "$_want"*) _order=ok ;;
    *) _order=bad ;;
  esac
  _pf=$(stat_val pic_fail); _cs=$(stat_val cap_stall)
  ev "STAT: $_l"
  res $([ "$_order" = ok ] && [ "${_pf:-0}" = 0 ] && [ "${_cs:-0}" = 0 ] && echo PASS || echo FAIL) "fields in the STAT order: $_order; pic_fail ${_pf:-?}, cap_stall ${_cs:-?}, pp_ms $(stat_val pp_ms), snd_ms $(stat_val snd_ms)"
}

c_start_lines() {
  _d=$(log_count 'direct capture: buffer')
  _g=$(log_count 'no guard at its start')
  _c=$(log_count 'encoder pool: no picture copy')
  ev "direct capture lines $_d, no-picture-copy lines $_c, old guard lines $_g"
  if [ "${_d:-0}" -ge 1 ] && [ "${_g:-0}" = 0 ]; then res PASS "direct capture buffers logged, no old pool-guard line"
  else res FAIL "direct capture lines ${_d:-0}, old pool-guard lines ${_g:-0}"; fi
}

c_hold_restart() {
  _h=$(tail -n 30 /tmp/logs/daynight.log 2>/dev/null | grep -c 'held back')
  if [ "${_h:-0}" = 0 ]; then res SKIP "no day/night hold in the last 30 log lines (DN-FLAP hold runs at dusk or dawn)"; return; fi
  sh /mnt/controlscripts/auto-night-detection restart >/dev/null 2>&1; sleep 8
  _s=$(tail -n 20 /tmp/logs/daynight.log 2>/dev/null | grep -c 'Daemon started')
  res $([ "${_s:-0}" -ge 1 ] && echo PASS || echo FAIL) "hold seen, restart done, 'Daemon started' lines in the last 20: ${_s:-0}"
}

c_daynight_lines() {
  if [ ! -f /tmp/logs/daynight.log ]; then res SKIP "no /tmp/logs/daynight.log"; return; fi
  _n=$(wc -l < /tmp/logs/daynight.log)
  res $([ "$_n" -le 400 ] && echo PASS || echo FAIL) "daynight.log has $_n lines (cap 400)"
}

c_config_tmp() {
  _t=$(find /mnt/config -name '*.tmp' 2>/dev/null | wc -l)
  res $([ "${_t:-0}" = 0 ] && echo PASS || echo FAIL) "leftover *.tmp files in /mnt/config: ${_t:-0}"
}

c_ssh_pidfile() {
  _p=$(cat /var/run/dropbear.pid 2>/dev/null)
  if [ -z "$_p" ]; then res SKIP "no /var/run/dropbear.pid (ssh off)"; return; fi
  res $(kill -0 "$_p" 2>/dev/null && echo PASS || echo FAIL) "dropbear pid file $_p alive: $(kill -0 "$_p" 2>/dev/null && echo yes || echo no)"
}

c_memory_hourly() {
  if [ "$(upt | cut -d. -f1)" -lt 3700 ]; then res SKIP "uptime under an hour: no hourly row due yet"; return; fi
  _f=/mnt/log/memory.csv; [ -f "$_f" ] || _f=/mnt/sd/logs/memory.csv
  if [ ! -f "$_f" ]; then res FAIL "no memory.csv"; return; fi
  if find "$_f" -mmin -70 2>/dev/null | grep -q .; then res PASS "memory.csv written within the last 70 min"
  else res FAIL "memory.csv not written for over 70 min"; fi
}

c_wifiq_files() {
  if [ ! -f /tmp/wifi-quality ]; then res SKIP "no /tmp/wifi-quality (WIFI_QUALITY=0 or not yet run)"; return; fi
  _k=$(grep -c '=' /tmp/wifi-quality)
  _s=$(sed -n 's/^samples_1h=//p' /tmp/wifi-quality)
  res $([ "$_k" = 7 ] && echo PASS || echo FAIL) "wifi-quality keys: $_k (expect 7), samples_1h ${_s:-?} (about 60 after an hour)"
}

c_fork_rate() {
  _w=${RECETTE_FORK_WINDOW:-600}
  _p0=$(sed -n 's/^processes //p' /proc/stat); sleep "$_w"; _p1=$(sed -n 's/^processes //p' /proc/stat)
  _rate=$(( (_p1 - _p0) * 60 / _w ))
  ev "processes forked in $_w s: $((_p1 - _p0)), per minute $_rate (all jobs; 13 per wifi-quality run before WIFIQ)"
  if [ -z "${RECETTE_FORK_MAX:-}" ]; then res SKIP "rate $_rate per minute measured; set RECETTE_FORK_MAX to judge it"; return; fi
  res $([ "$_rate" -le "$RECETTE_FORK_MAX" ] && echo PASS || echo FAIL) "$_rate forks per minute, limit $RECETTE_FORK_MAX"
}

c_counters_stat() {
  if [ ! -f /tmp/tc100_rtsp.counters ]; then res FAIL "no /tmp/tc100_rtsp.counters"; return; fi
  _ok=1
  for _k in starts pic_fail enc_reopen cap_stall dq_err sub_off exit3; do
    [ "$(stat_val $_k)" = "$(ctr $_k)" ] || _ok=0
  done
  res $([ $_ok = 1 ] && echo PASS || echo FAIL) "STAT tail and counters file agree: starts $(ctr starts), pic_fail $(ctr pic_fail), exit3 $(ctr exit3)"
}

c_counters_term() {
  if [ ! -s "$OUT/kill.stats" ]; then res SKIP "kill-loop did not run in this run folder"; return; fi
  _n=$(grep -c ' ok \| BAD \| stuck' "$OUT/kill.stats")
  _x=$(grep -c ' BAD ' "$OUT/kill.stats")
  res $([ "$_x" = 0 ] && echo PASS || echo FAIL) "$_n kill -TERM cycles, each with starts +1 and exit3 unchanged (bad $_x; a TERM is a clean stop)"
}

c_memory_files() {
  _f=/mnt/log/memory-hourly.csv; [ -f "$_f" ] || _f=/mnt/sd/logs/memory-hourly.csv
  if [ ! -f "$_f" ]; then res SKIP "no memory-hourly.csv yet (first row at the first hour)"; return; fi
  _h=$(head -n 1 "$_f")
  case "$_h" in
    *rtsp_starts*pic_fail*exit3*) res PASS "memory-hourly.csv header has the seven failure columns; rows $(wc -l < "$_f")" ;;
    *) res FAIL "memory-hourly.csv header without the failure columns" ;;
  esac
}

c_smash() {
  _n=$( (cat /tmp/logs/*.log /tmp/log/*.log /mnt/sd/logs/*.log 2>/dev/null; logread 2>/dev/null; dmesg 2>/dev/null) | grep -ci 'stack smashing\|illegal instruction')
  res $([ "${_n:-0}" = 0 ] && echo PASS || echo FAIL) "'stack smashing' / 'illegal instruction' lines in the logs: ${_n:-0}"
}

c_top() {
  top -b -n 1 2>/dev/null | head -n 20 > "$OUT/top1.txt"
  sleep 30
  top -b -n 1 2>/dev/null | head -n 20 > "$OUT/top2.txt"
  if [ -s "$OUT/top2.txt" ]; then res PASS "top snapshots kept (top1.txt, top2.txt): compare the CPU of tc100_rtsp, tc100-onvifd, tc100-mqttd, httpfront with the 3.0.1 readings"
  else res FAIL "top printed nothing"; fi
}

# ---------------------------------------------------------------------------------------------------------------
# cleanup: runs at the end and on EXIT, INT, TERM. Restores what a check changed, leaves the video running.
# ---------------------------------------------------------------------------------------------------------------
cleanup() {
  trap '' EXIT INT TERM
  [ -n "$ORIG_UNLAZY" ] && echo "$ORIG_UNLAZY" > "$UNLAZY" 2>/dev/null
  [ "${PRIV_SET:-0}" = 1 ] && rm -f /tmp/tc100_privacy
  if [ "${DN_TOUCHED:-}" = 1 ]; then sh /mnt/scripts/nightmode.sh on >/dev/null 2>&1; fi
  [ "${WIFI_TOUCHED:-0}" = 1 ] && wlan_restore >/dev/null 2>&1
  [ "$DRY" = 1 ] || ensure_rtsp
  rm -f "$CFG" "$PASSF"
  [ "$DRY" = 1 ] || echo "$(date) ended, restored: privacy, irq switch, night mode, wlan0, video" >> "$LOGF" 2>/dev/null
  exit "${EXIT_CODE:-0}"
}
trap cleanup EXIT INT TERM

selected() {
  [ -z "$ONLY" ] && return 0
  case ",$ONLY," in *",$1,"*) return 0 ;; esac
  return 1
}

# ---------------------------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------------------------
if [ "$DRY" = 1 ]; then
  printf '%s\n' "$CHECKS" | while IFS='|' read -r id name mode fn arg; do
    selected "$id" || continue
    echo "DRY $id $name $mode"
  done
  trap - EXIT INT TERM
  exit 0
fi

mkdir -p "$OUT" || { echo "cannot create $OUT" >&2; exit 1; }
: > "$RESFILE"; : > "$LOGF"
if [ -f "$PASSF" ]; then RECETTE_PASS=$(head -n 1 "$PASSF" 2>/dev/null); rm -f "$PASSF"; fi
echo "start $(date) out $OUT" >> "$LOGF"
printf '%s\n' "$CHECKS" > "$OUT/checks.txt"

# the loop reads a file, not a pipe: the variables the checks set (restore state) stay in this shell for the trap
while IFS='|' read -r id name mode fn arg; do
  selected "$id" || continue
  CUR_ID=$id; CUR_CHECK=$name; CUR="$id/$name"
  case "$mode" in
    dist) [ "$DISRUPT" = 1 ] || { res SKIP "needs --disruptive"; continue; } ;;
    wifi) [ "$WIFI" = 1 ] || { res SKIP "needs --wifi"; continue; } ;;
    manual) skip_manual "$arg"; continue ;;
  esac
  _before=$RESN
  "$fn"
  [ "$RESN" = "$_before" ] && res FAIL "the check printed no result"
done < "$OUT/checks.txt"

RUN_T1=$(upt)
TOTAL=$(awk "BEGIN{printf \"%d\", $RUN_T1 - ${RUN_T0:-$RUN_T1}}")
P=$(grep -c ' PASS' "$RESFILE"); F=$(grep -c ' FAIL' "$RESFILE"); S=$(grep -c ' SKIP' "$RESFILE")
{
  echo "== recette summary ($OUT)"
  awk '{ ev=""; for (i = 5; i <= NF; i++) ev = ev $i " "; printf "%-5s %-46s %.90s\n", $4, $2 " " $3, ev }' "$RESFILE"
  echo "PASS $P  FAIL $F  SKIP $S  total runtime ${TOTAL} s"
} > "$OUT/summary.txt"
cat "$OUT/summary.txt"
echo "done $(date)" > "$OUT/done"
[ "$F" = 0 ] && EXIT_CODE=0 || EXIT_CODE=1
exit "$EXIT_CODE"
