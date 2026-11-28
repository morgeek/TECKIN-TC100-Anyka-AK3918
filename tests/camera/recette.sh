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
#
# Never written: the flash, the MTD partitions, the U-Boot environment, the settings slots, the SD card, and nothing under
# /mnt/config. /mnt/config is only listed (md5) at the start and compared at the end (GLOBAL config-unchanged): settings
# files that changed are a FAIL, the camera's own daemon files an INFO line. Nothing is restored (detect-only). The RAM state a check changes (privacy file, irq switch, night
# mode, the Wi-Fi link and its address and route, the video server) is restored by the trap, also on interrupt.
# The camera password comes from /tmp/recette.pass (written by recette-host.sh from RECETTE_PASS, deleted here at once)
# and is never printed or logged.

trap '' HUP
PATH=/mnt/ext/bin:/mnt/bin:/mnt/scripts:/mnt/controlscripts:/usr/sbin:/usr/bin:/sbin:/bin:$PATH
export PATH

LOG=/tmp/logs/tc100_rtsp.log
UNLAZY=/sys/module/ak39_venc/parameters/irq_unlazy
CFG=/tmp/recette-cfg
PASSF=/tmp/recette.pass
BAD_RE="Oops|BUG:|Unable to handle|WARNING:|soft lockup|hung_task|blocked for more than|nobody cared|Unbalanced enable|otg-hs: ep|Kernel panic|illegal instruction|stack smashing"
# Hard upper bounds of every loop (defence in depth: a counter that a called function clobbers cannot run past them).
# Counts are capped at MAX_LOOP, waits in seconds at MAX_WAIT_S. Each helper and check names its own counters (the
# prefix of the helper: _ws_ for wait_stat, _kc_ for kill_cycles, ...), so no called function resets a caller's counter.
MAX_LOOP=1000
MAX_WAIT_S=3600

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
AUDIT-1116-RTSP|stall-exit|manual|skip_manual|SIGSTOP does not simulate a capture stall (tc100_rtsp.c:4606 discounts a stopped process); a real stall needs the driver to stop delivering frames, and no switch exists for that
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
R2-BUTTON|hold-restart-timing|manual|skip_manual|8-10 s hold during the switch restarts the camera: owner (button); never automated
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
SMALL-A-1124|hold-restart|manual|skip_manual|DN-FLAP hold restart: owner at dusk or dawn; the restart rewrites rtspserver.conf (daynight=3), not run by the bench
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
ORIG_UNLAZY=; PRIV_SET=0; DN_TOUCHED=0; DN_ORIG=0; DN_REAPPLIED=0; WIFI_TOUCHED=0
WLAN_ADDR=; WLAN_GW=; STALL_RUNS=0; CONFIG_CHECKED=0

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

# the first tc100_rtsp that is not stopped (state T): a stopped instance is not a running server
rtsp_pid() {
  for _p in $(pidof tc100_rtsp 2>/dev/null); do
    _st=$(sed 's/^.*) //' "/proc/$_p/stat" 2>/dev/null | cut -c1)
    [ "$_st" = T ] && continue
    echo "$_p"; return 0
  done
}

# counter from /tmp/tc100_rtsp.counters: empty when the file or the key is missing (never a made-up 0)
ctr() {
  [ -f /tmp/tc100_rtsp.counters ] || return 0
  tr ' ' '\n' < /tmp/tc100_rtsp.counters | sed -n "s/^$1=//p" | head -n 1 | tr -dc '0-9'
}

last_stat() { grep '^STAT ' "$LOG" 2>/dev/null | tail -n 1; }

# stat_val NAME: the value after NAME in the last STAT line (empty when absent)
stat_val() {
  _sv_k=$1
  set -- $(last_stat)
  while [ $# -ge 2 ]; do
    if [ "$1" = "$_sv_k" ]; then echo "$2"; return 0; fi
    shift
  done
  return 0
}

# count of lines matching a pattern in the current video log (the log is emptied at each start)
log_count() {
  _lc_n=$(grep -c "$1" "$LOG" 2>/dev/null)
  echo "${_lc_n:-0}"
}

# the STAT lines of the current log (the count only grows until the log is rotated: see log_bytes)
stat_count() {
  _stc_n=$(grep -c '^STAT ' "$LOG" 2>/dev/null)
  echo "${_stc_n:-0}"
}

log_bytes() { wc -c < "$LOG" 2>/dev/null || echo 0; }

# the start lines are read from the current log and from its rotated copy (tc100_rtsp renames the log to LOG.1 when it
# grows, and the next rotation replaces LOG.1): every file LOG.<n> that exists
log_all() { cat "$LOG" "$LOG".[0-9]* 2>/dev/null; }

# stat_sum KEY FROM TO: the sum of KEY over the STAT lines FROM+1 .. TO of the current log. Each STAT line holds the count
# of its own 5 s tick (enc, sub_enc, pp_ms ...), so a window is the sum of its lines.
stat_sum() {
  grep '^STAT ' "$LOG" 2>/dev/null | awk -v k="$1" -v a="$2" -v b="$3" 'NR > a && NR <= b {
    for (i = 1; i < NF; i++) if ($i == k) { s += $(i + 1); break } } END { printf "%d", s + 0 }'
}

# stat_window_vals KEY FROM TO: one value of KEY per STAT line FROM+1 .. TO (lines without KEY give nothing)
stat_window_vals() {
  grep '^STAT ' "$LOG" 2>/dev/null | awk -v k="$1" -v a="$2" -v b="$3" 'NR > a && NR <= b {
    for (i = 1; i < NF; i++) if ($i == k) { print $(i + 1); break } }'
}

# stat_mean KEY FROM TO: the integer mean of KEY over those windows (empty when there is none)
stat_mean() {
  stat_window_vals "$1" "$2" "$3" | awk '{ s += $1; n++ } END { if (n) printf "%d", s / n }'
}

# stat_settled KEY: the last 3 STAT windows of KEY are within 10% of their mean, or all 0. A video server restarted just
# before (the kill loop) catches up first, with windows above the capture rate (113 and 104 at 10 fps on 2026-11-27),
# then runs at its steady rate: a baseline must not start on the catch-up.
stat_settled() {
  _ss_n=$(stat_count)
  [ "$_ss_n" -ge 3 ] || return 1
  stat_window_vals "$1" $((_ss_n - 3)) "$_ss_n" | awk '{ v[n++] = $1; s += $1 } END {
    if (n < 3) exit 1; if (s <= 0) exit 0; m = s / n
    for (i = 0; i < n; i++) if (v[i] * 10 > m * 11 || v[i] * 10 < m * 9) exit 1; exit 0 }'
}

# wait_stat_count N: until the current log has at least N STAT lines (MAX_WAIT_S seconds at most)
wait_stat_count() {
  _swc_t=0
  while [ "$(stat_count)" -lt "$1" ] && [ "$_swc_t" -lt 60 ]; do sleep 1; _swc_t=$((_swc_t + 1)); done
  [ "$(stat_count)" -ge "$1" ]
}

venc_irq() { set -- $(grep venc /proc/interrupts 2>/dev/null | head -n 1); echo "$2"; }

ensure_rtsp() {
  [ -n "$(rtsp_pid)" ] || sh /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1
}

# wait_stat SECS: a STAT line in the log (the log is emptied at each start, so any STAT line is from this process)
wait_stat() {
  _ws_n=0
  while [ "$_ws_n" -lt "$1" ] && [ "$_ws_n" -lt "$MAX_WAIT_S" ]; do
    grep -q '^STAT ' "$LOG" 2>/dev/null && return 0
    sleep 1; _ws_n=$((_ws_n + 1))
  done
  return 1
}

wait_gone() {
  _wg_n=0
  while [ "$_wg_n" -lt "$2" ] && [ "$_wg_n" -lt "$MAX_WAIT_S" ]; do
    kill -0 "$1" 2>/dev/null || return 0
    sleep 1; _wg_n=$((_wg_n + 1))
  done
  return 1
}

gateway() { route -n 2>/dev/null | sed -n 's/^0\.0\.0\.0 *\([0-9.]*\).*/\1/p' | head -n 1; }

wlan_addr_now() { ip -4 addr show dev wlan0 2>/dev/null | sed -n 's/.*inet \([0-9.]*\)\/.*/\1/p' | head -n 1; }

wlan_assoc() { iw dev wlan0 link 2>/dev/null | grep -q Connected; }

wait_assoc() {
  _wa_n=0
  while [ "$_wa_n" -lt "$1" ] && [ "$_wa_n" -lt "$MAX_WAIT_S" ]; do
    wlan_assoc && return 0
    sleep 1; _wa_n=$((_wa_n + 1))
  done
  return 1
}

# net_save: the address and the default gateway of wlan0 before anything is cut (ifconfig down flushes both)
net_save() {
  WLAN_ADDR=$(ip -4 addr show dev wlan0 2>/dev/null | sed -n 's/.*inet \([0-9.]*\/[0-9]*\).*/\1/p' | head -n 1)
  WLAN_GW=$(gateway)
  ev "saved wlan0 address '$WLAN_ADDR' gateway '$WLAN_GW'"
}

# net_static_fill: the saved address and default route, when they are not there
net_static_fill() {
  # a udhcpc running for wlan0 owns the address and the route: renew it (SIGUSR1), never add a static one next to it
  _dh=$(pidof udhcpc 2>/dev/null)
  if [ -n "$_dh" ]; then kill -USR1 $_dh 2>/dev/null; return 0; fi
  [ -n "$(wlan_addr_now)" ] || { [ -n "$WLAN_ADDR" ] && ip addr add "$WLAN_ADDR" dev wlan0 2>/dev/null; }
  [ -n "$(gateway)" ] || { [ -n "$WLAN_GW" ] && ip route add default via "$WLAN_GW" dev wlan0 2>/dev/null; }
}

# net_back SECS: wait for the address and the default route; after 5 s ask udhcpc to renew (SIGUSR1), then put the
# saved values back. True only when both are there.
net_back() {
  _nb_n=0
  while [ "$_nb_n" -lt "$1" ] && [ "$_nb_n" -lt "$MAX_WAIT_S" ]; do
    [ -n "$(wlan_addr_now)" ] && [ -n "$(gateway)" ] && return 0
    if [ "$_nb_n" -eq 5 ]; then _nb_up=$(pidof udhcpc 2>/dev/null); [ -n "$_nb_up" ] && kill -USR1 $_nb_up 2>/dev/null; fi
    sleep 1; _nb_n=$((_nb_n + 1))
  done
  net_static_fill
  [ -n "$(wlan_addr_now)" ] && [ -n "$(gateway)" ]
}

wlan_down() { ifconfig wlan0 down >/dev/null 2>&1 || ip link set wlan0 down >/dev/null 2>&1; }
wlan_up() { ifconfig wlan0 up >/dev/null 2>&1 || ip link set wlan0 up >/dev/null 2>&1; }
wlan_recover() { wlan_up; wpa_cli -i wlan0 reassociate >/dev/null 2>&1; }

# wlan_restore: up, association, address and route; three tries of 60 s + 30 s, then it reports the state
wlan_restore() {
  wlan_up
  _wr_n=0
  while [ "$_wr_n" -lt 3 ]; do
    if wait_assoc 60 && net_back 30; then return 0; fi
    wlan_recover
    _wr_n=$((_wr_n + 1))
  done
  wlan_assoc && [ -n "$(wlan_addr_now)" ] && [ -n "$(gateway)" ]
}

# /mnt/config is only READ by the bench (detect-only): the md5 list of the start, compared at the end. Nothing is copied
# (no secrets left in /tmp) and nothing is restored or removed in /mnt/config.
config_snapshot() {
  if [ ! -d /mnt/config ]; then : > "$OUT/config-absent"; return; fi
  ( cd /mnt/config 2>/dev/null && find . -type f | sort | while read -r f; do md5sum "$f"; done ) > "$OUT/config-before.md5" 2>/dev/null
}

# cc_note KIND FILE: a settings file (the checks read them, a web save or a writer of the camera would change them) is a
# FAIL; any other file is INFO: the daemons write their own state there (awb.state, .net-guard counter, ...)
cc_note() {
  case "$2" in
    rtspserver.conf|rtsp.env|daynight.conf|boot.conf|isp_tune.conf|mqtt.conf|sound_detection.conf|onvif.conf|timezone.conf|user.pwd|wpa_supplicant.conf)
      _fail="$_fail $1:$2" ;;
    *) _info="$_info $1:$2" ;;
  esac
}

config_check() {
  CONFIG_CHECKED=1
  CUR_ID=GLOBAL; CUR_CHECK=config-unchanged; CUR="GLOBAL/config-unchanged"
  if [ -f "$OUT/config-absent" ] || [ ! -f "$OUT/config-before.md5" ]; then
    res FAIL "no /mnt/config snapshot (directory missing at the start or not taken): not checked"; return
  fi
  ( cd /mnt/config 2>/dev/null && find . -type f | sort | while read -r f; do md5sum "$f"; done ) > "$OUT/config-now.md5" 2>/dev/null
  _fail=; _info=
  while read -r h p; do
    q=${p#./}
    awk -v p="$p" -v h="$h" '$2 == p && $1 == h { f = 1 } END { exit !f }' "$OUT/config-before.md5" && continue
    if awk -v p="$p" '$2 == p { f = 1 } END { exit !f }' "$OUT/config-before.md5"; then cc_note changed "$q"; else cc_note new "$q"; fi
  done < "$OUT/config-now.md5"
  while read -r h p; do
    q=${p#./}
    awk -v p="$p" '$2 == p { f = 1 } END { exit !f }' "$OUT/config-now.md5" || cc_note removed "$q"
  done < "$OUT/config-before.md5"
  if [ -n "$_info" ]; then
    echo "INFO GLOBAL files written by the camera's own daemons during the run (not a FAIL):$_info" | tee -a "$LOGF"
  fi
  if [ -z "$_fail" ]; then
    res PASS "no settings file changed (rtspserver.conf, rtsp.env, daynight.conf, boot.conf, isp_tune.conf, mqtt.conf, sound_detection.conf, onvif.conf, timezone.conf, user.pwd, wpa_supplicant.conf)"
  else
    res FAIL "settings file(s) changed during the run, nothing restored (detect-only; find the writer): $_fail"
  fi
}

# password for the curl calls on the camera: a config file (umask 077), so no argument list shows it
mk_cfg() {
  [ -n "$RECETTE_PASS" ] || return 1
  _pw=$(printf '%s' "$RECETTE_PASS" | sed 's/\\/\\\\/g; s/"/\\"/g')
  ( umask 077; printf 'user = "root:%s"\nsilent\n' "$_pw" > "$CFG" )
}

# night mode: NIGHT_KEEP_AUTO=1 keeps the automatic mode (auto-night-detection is not stopped, so rtspserver.conf
# keeps its daynight value). The only place the bench switches the night mode.
dn_set() { NIGHT_KEEP_AUTO=1 sh /mnt/scripts/nightmode.sh "$1" >/dev/null 2>&1; }
night_now() { sh /mnt/controlscripts/night-mode status 2>/dev/null | grep -q 'PID: OK'; }
# automatic day/night on: rtspserver.conf daynight=2 (read only)
auto_on() { sed -n 's/^daynight=//p' /mnt/config/rtspserver.conf 2>/dev/null | tail -n 1 | grep -qx 2; }
# dn_settle: the end of the day/night cycles. Automatic mode on with the night job running: a new nonce in its RAM flag
# (the same way supervisor.sh starts the job) makes the daemon re-decide from the current picture (night_reset); the
# daemon's own switches use NIGHT_KEEP_AUTO=1, so nothing is written to /mnt/config. Otherwise the starting state is
# put back with the forced switch.
dn_settle() {
  DN_TOUCHED=0
  if auto_on && [ -e /var/run/tc100-sv.night ]; then
    echo "recette $$ $(upt)" > /var/run/tc100-sv.night.recette && mv -f /var/run/tc100-sv.night.recette /var/run/tc100-sv.night
    ev "automatic day/night on: the night job flag got a new nonce; the daemon re-decides on its next look"
    echo "INFO GLOBAL day/night: automatic mode on, the daemon re-decides on its own. Tester: watch the next switch (ISP hue line, night state)." | tee -a "$LOGF"
    DN_REAPPLIED=1
  else
    if [ "$DN_ORIG" = 1 ]; then dn_set on; else dn_set off; fi
  fi
}

# kill_cycles N FILE: N times kill -TERM of tc100_rtsp and a start with the autorun arguments (rtsp-h26x start runs
# rtsp-launch.sh, the script the boot calls). One line per cycle in FILE: "<n> ok ..." or "<n> BAD|no-process|stuck ...".
# Sets K_OK and K_BAD.
kill_cycles() {
  _kc_want=$1; _kc_file=$2; _kc_n=0
  case "$_kc_want" in ''|*[!0-9]*) _kc_want=0 ;; esac
  K_OK=0; K_BAD=0; : > "$_kc_file"
  # the loop ends at the requested count, and also when the outcomes so far (each cycle adds exactly one to K_OK or
  # K_BAD) reach it: a counter that a called function clobbers cannot make it run longer
  while [ "$_kc_n" -lt "$_kc_want" ] && [ "$_kc_n" -lt "$MAX_LOOP" ] && [ $((K_OK + K_BAD)) -lt "$_kc_want" ]; do
    _kc_n=$((_kc_n + 1))
    ensure_rtsp
    _kc_p0=$(rtsp_pid); _kc_v0=$(venc_irq); _kc_s0=$(ctr starts); _kc_x0=$(ctr exit3)
    if [ -z "$_kc_p0" ]; then K_BAD=$((K_BAD + 1)); echo "$_kc_n no-process" >> "$_kc_file"; continue; fi
    kill -TERM "$_kc_p0" 2>/dev/null
    if ! wait_gone "$_kc_p0" 15; then
      K_BAD=$((K_BAD + 1)); echo "$_kc_n stuck-after-TERM pid=$_kc_p0" >> "$_kc_file"; kill -9 "$_kc_p0" 2>/dev/null; continue
    fi
    sh /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1
    _kc_ok=1
    wait_stat 45 || _kc_ok=0
    _kc_p1=$(rtsp_pid); _kc_v1=$(venc_irq); _kc_pf=$(log_count 'picture failed'); _kc_s1=$(ctr starts); _kc_x1=$(ctr exit3)
    [ -n "$_kc_p1" ] && [ "$_kc_p1" != "$_kc_p0" ] || _kc_ok=0
    [ -n "$_kc_v0" ] && [ -n "$_kc_v1" ] && [ "$_kc_v1" -gt "$_kc_v0" ] 2>/dev/null || _kc_ok=0
    [ "$_kc_pf" = 0 ] || _kc_ok=0
    [ -n "$_kc_x0" ] && [ "$_kc_x1" = "$_kc_x0" ] || _kc_ok=0
    if [ "$_kc_ok" = 1 ]; then
      K_OK=$((K_OK + 1))
      echo "$_kc_n ok irq+$((_kc_v1 - _kc_v0)) starts+$(( ${_kc_s1:-0} - ${_kc_s0:-0} )) picture_failed=$_kc_pf" >> "$_kc_file"
    else
      K_BAD=$((K_BAD + 1))
      echo "$_kc_n BAD pid=$_kc_p1 irq_before=$_kc_v0 irq_after=$_kc_v1 picture_failed=$_kc_pf exit3_before=$_kc_x0 exit3_after=$_kc_x1" >> "$_kc_file"
    fi
  done
}

have_logs() { logread >/dev/null 2>&1 || ls /tmp/log/*.log /tmp/logs/*.log >/dev/null 2>&1; }

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
  if [ ! -s "$OUT/dmesg.txt" ]; then res FAIL "dmesg printed nothing"; return; fi
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
  ev "$(tail -n 5 "$OUT/kill.stats")"
  if [ "$K_BAD" = 0 ] && [ "$K_OK" = "$_n" ] && [ -n "$(rtsp_pid)" ]; then
    res PASS "$K_OK/$_n kill -TERM + start: first picture clean, encoder interrupt counting, exit3 unchanged"
  else
    res FAIL "$K_OK/$_n cycles clean, $K_BAD bad (see kill.stats in the run folder)"
  fi
}

c_stream_cycles() {
  _sc_want=${RECETTE_STREAM_CYCLES:-20}; _sc_ok=0; _sc_n=0
  while [ "$_sc_n" -lt "$_sc_want" ] && [ "$_sc_n" -lt "$MAX_LOOP" ]; do
    _sc_n=$((_sc_n + 1))
    sh /mnt/controlscripts/rtsp-h26x stop >/dev/null 2>&1; sleep 2
    sh /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1
    wait_stat 45 && [ -n "$(rtsp_pid)" ] && _sc_ok=$((_sc_ok + 1))
  done
  res $([ "$_sc_ok" = "$_sc_want" ] && echo PASS || echo FAIL) "$_sc_ok/$_sc_want stop + start cycles with a STAT line after each start"
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
  _total=$(wc -l < "$OUT/kill.stats")
  _ok=$(grep -c '^[0-9]* ok irq+[1-9]' "$OUT/kill.stats")
  res $([ "$_total" -ge 1 ] && [ "$_ok" = "$_total" ] && echo PASS || echo FAIL) "$_ok of $_total cycles: encoder interrupt counting after each start (growth per picture: compare with enc in STAT)"
}

c_irq_control() {
  if [ "${RECETTE_CONTROL:-0}" != 1 ]; then res SKIP "set RECETTE_CONTROL=1 (about 26 extra restarts with irq_unlazy=0 then 1)"; return; fi
  [ -f "$UNLAZY" ] || { res FAIL "no irq_unlazy switch"; return; }
  ORIG_UNLAZY=$(cat "$UNLAZY" 2>/dev/null)
  echo 0 > "$UNLAZY" 2>/dev/null
  kill_cycles 20 "$OUT/irq-off.stats"; _a=$K_BAD; _ao=$K_OK
  echo 1 > "$UNLAZY" 2>/dev/null
  kill_cycles 1 "$OUT/irq-on.stats"; _b=$K_BAD; _bo=$K_OK
  kill_cycles 5 "$OUT/irq-on5.stats"; _c=$K_BAD; _co=$K_OK
  echo "$ORIG_UNLAZY" > "$UNLAZY" 2>/dev/null
  _want=$ORIG_UNLAZY; ORIG_UNLAZY=
  _now=$(cat "$UNLAZY" 2>/dev/null)
  ev "irq_unlazy=0: 20 cycles ($_ao ok); =1: 1+5 cycles ($_bo+$_co ok); restored to '$_now', was '$_want'"
  res $([ $((_a + _b + _c)) = 0 ] && [ -n "$_now" ] && [ "$_now" = "$_want" ] && echo PASS || echo FAIL) "control run: bad cycles off=$_a on=$((_b + _c)); switch back to '${_now}' (was '$_want')"
}

c_irq_sample() {
  if [ -z "$(rtsp_pid)" ] || [ -z "$(stat_val enc)" ]; then res SKIP "tc100_rtsp not streaming: no STAT line"; return; fi
  _is_v0=$(venc_irq); _is_n0=$(stat_count); _is_b0=$(log_bytes); _is_pf0=$(log_count 'picture failed')
  sleep 60
  _is_v1=$(venc_irq); _is_n1=$(stat_count); _is_b1=$(log_bytes); _is_pf1=$(log_count 'picture failed')
  if [ -z "$_is_v0" ] || [ -z "$_is_v1" ]; then res FAIL "interrupt counter missing (no venc line in /proc/interrupts)"; return; fi
  if [ "$_is_n1" -lt "$_is_n0" ] || [ "$_is_b1" -lt "$_is_b0" ]; then res SKIP "video log rotated during the 60 s: not counted"; return; fi
  # the window is every STAT line that came in the 60 s (one line per 5 s tick, each with the pictures of its tick), not
  # two single lines: enc (main) and sub_enc (sub stream, same encoder interrupt) are summed over the window
  _is_w=$((_is_n1 - _is_n0))
  _is_e=$(stat_sum enc "$_is_n0" "$_is_n1"); _is_s=$(stat_sum sub_enc "$_is_n0" "$_is_n1")
  _dv=$((_is_v1 - _is_v0)); _de=$((_is_e + _is_s))
  ev "60 s: irq +$_dv; $_is_w STAT windows: enc +$_is_e, sub_enc +$_is_s, pictures +$_de; picture failed +$((_is_pf1 - _is_pf0)). JPEG snapshots are not in STAT and not counted"
  if [ "$_is_pf1" != "$_is_pf0" ]; then res FAIL "picture failed lines in 60 s"
  elif [ "$_is_w" -lt 1 ]; then res SKIP "no STAT line in 60 s"
  elif [ "$_de" -gt 0 ] && [ "$_dv" -gt 0 ] && [ "$_dv" -le $((_de * 12 / 10 + 10)) ]; then res PASS "irq +$_dv for $_de encoded pictures (enc + sub_enc of $_is_w STAT windows) in 60 s, no failed picture"
  elif [ "$_de" -eq 0 ]; then res SKIP "no picture encoded in 60 s (no viewer?)"
  else res FAIL "irq +$_dv for $_de pictures (enc + sub_enc of $_is_w STAT windows): a replay or a lost interrupt"
  fi
}

c_wlan_cycles() {
  command -v iw >/dev/null 2>&1 || { res SKIP "no iw on the PATH (/mnt/ext/bin)"; return; }
  _wc_want=${RECETTE_WIFI_CYCLES:-20}; WIFI_TOUCHED=1
  net_save
  if [ -z "$WLAN_GW" ] || [ -z "$WLAN_ADDR" ]; then res FAIL "no address or default route before the test (address '$WLAN_ADDR', gateway '$WLAN_GW')"; return; fi
  _wc_slow=0; _wc_lost=0; _wc_bad=0; _wc_n=0
  ev "clients $(stat_val clients) at start"
  while [ "$_wc_n" -lt "$_wc_want" ] && [ "$_wc_n" -lt "$MAX_LOOP" ]; do
    _wc_n=$((_wc_n + 1))
    _wc_t0=$(upt); wlan_down; _wc_t1=$(upt)
    _wc_d=$(awk "BEGIN{print $_wc_t1-$_wc_t0}")
    awk "BEGIN{exit !($_wc_d > 1.0)}" && _wc_slow=$((_wc_slow + 1))
    sleep 2
    wlan_up
    if ! wait_assoc 60 || ! net_back 30; then
      _wc_bad=$((_wc_bad + 1)); ev "cycle $_wc_n: association, address or default route not back"
      wlan_restore >/dev/null || break
      continue
    fi
    _wc_r=$(ping -c 30 -W 1 "$WLAN_GW" 2>/dev/null | grep 'packets transmitted')
    if [ -z "$_wc_r" ]; then _wc_lost=$((_wc_lost + 1)); ev "cycle $_wc_n: no ping summary"; continue; fi
    set -- $_wc_r
    _wc_lo=$(( ${1:-0} - ${4:-0} ))
    [ "$_wc_lo" -gt 1 ] && _wc_lost=$((_wc_lost + 1))
    ev "cycle $_wc_n: down ${_wc_d}s, ping lost $_wc_lo of ${1:-0}, clients $(stat_val clients)"
  done
  wlan_restore || _wc_bad=$((_wc_bad + 1))
  if [ "$_wc_bad" = 0 ] && [ "$_wc_slow" = 0 ] && [ "$_wc_lost" = 0 ] && [ "$_wc_n" -ge 1 ]; then
    res PASS "$_wc_n down/up cycles: each down under 1 s, association, address and default route back, no ping loss after the first second"
  else
    res FAIL "$_wc_n cycles: $_wc_slow slow down(s), $_wc_lost with ping loss, $_wc_bad without association/address/route (restored by retries: $(wlan_assoc && echo associated || echo NOT associated))"
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
  command -v wpa_cli >/dev/null 2>&1 || { res SKIP "no wpa_cli on the PATH (/mnt/ext/bin)"; return; }
  command -v iw >/dev/null 2>&1 || { res SKIP "no iw on the PATH (/mnt/ext/bin)"; return; }
  WIFI_TOUCHED=1; net_save
  _ra_cmd=0; _ra_drop=0; _ra_ok=0; _ra_n=0
  while [ "$_ra_n" -lt 5 ]; do
    _ra_n=$((_ra_n + 1))
    _ra_o=$(wpa_cli -i wlan0 reassociate 2>&1); _ra_rc=$?
    if [ "$_ra_rc" = 0 ] && ! echo "$_ra_o" | grep -q FAIL; then _ra_cmd=$((_ra_cmd + 1)); else ev "cycle $_ra_n: reassociate failed: $_ra_o"; fi
    # a drop is looked for for 3 s: evidence only. A reassociate may be too quick to see, and the USB entry asks for the
    # commands, not for a drop; the criterion is the link back with its address and route (wait_assoc, net_back)
    _ra_j=0; _ra_dropped=0
    while [ "$_ra_j" -lt 15 ]; do
      wlan_assoc || { _ra_dropped=1; break; }
      sleep 0.2; _ra_j=$((_ra_j + 1))
    done
    [ "$_ra_dropped" = 1 ] && _ra_drop=$((_ra_drop + 1))
    ev "cycle $_ra_n: drop seen in 3 s: $_ra_dropped"
    wait_assoc 60 && net_back 30 && _ra_ok=$((_ra_ok + 1))
  done
  wlan_restore >/dev/null
  res $([ "$_ra_cmd" = 5 ] && [ "$_ra_ok" = 5 ] && echo PASS || echo FAIL) "$_ra_cmd/5 reassociate commands ok, $_ra_ok/5 back with address and route (drops seen $_ra_drop/5: evidence, not a criterion)"
}

c_no_spurious() {
  _x0=$(cat "$OUT/exit3.start" 2>/dev/null); _x1=$(ctr exit3)
  _exp=${STALL_RUNS:-0}
  ev "exit3 at start '$_x0', now '$_x1', expected from this bench $_exp"
  if [ -z "$_x0" ] || [ -z "$_x1" ]; then res FAIL "exit3 unknown (no preflight or no counters file)"; return; fi
  if [ $((_x1 - _x0)) = "$_exp" ]; then res PASS "exit3 +$((_x1 - _x0)): only the bench's own stall test"
  else res FAIL "exit3 +$((_x1 - _x0)) with $_exp expected: a spurious capture stall exit"; fi
}

c_arecord() {
  _p=$(pidof arecord 2>/dev/null)
  if [ -z "$_p" ]; then res SKIP "no arecord process: the microphone is read by tc100_rtsp (RTSP_ALSA_DIRECT=1)"; return; fi
  kill -9 $_p 2>/dev/null; sleep 3
  _z=$(ps 2>/dev/null | grep -c 'arecord.*defunct')
  # the server is restarted the normal way: with RTSP_ALSA_DIRECT=0 the audio is only restarted by a server start
  sh /mnt/controlscripts/rtsp-h26x restart >/dev/null 2>&1; wait_stat 45
  res $([ -n "$(rtsp_pid)" ] && [ "${_z:-0}" = 0 ] && echo PASS || echo FAIL) "arecord $_p killed, zombies ${_z:-0}, server restarted the normal way, pid '$(rtsp_pid)'"
}

c_ssh_maps() {
  _pids=$(pidof dropbear 2>/dev/null)
  if [ -z "$_pids" ]; then res SKIP "dropbear not running (ssh off)"; return; fi
  _ok=0; _tot=0; _sess=0
  for _p in $_pids; do
    # Dropbear >=2026 re-execs per session with -2 <fd> without LD_PRELOAD; the listener checks LAN access at accept.
    _cmd=$(tr '\0' ' ' < "/proc/$_p/cmdline" 2>/dev/null)
    case " $_cmd " in *" -2 "*) _sess=$((_sess + 1)); continue ;; esac
    _tot=$((_tot + 1))
    grep -q 'libnetacl-musl.so' "/proc/$_p/maps" 2>/dev/null && _ok=$((_ok + 1))
  done
  if [ "$_tot" = 0 ]; then res FAIL "no dropbear listener found ($_sess session child(ren) skipped)"; return; fi
  res $([ "$_ok" = "$_tot" ] && echo PASS || echo FAIL) "$_ok of $_tot dropbear listener(s) map libnetacl-musl.so ($_sess session child(ren) skipped)"
}

c_nounfiltered() {
  if ! have_logs; then res SKIP "no log readable (logread, /tmp/log, /tmp/logs)"; return; fi
  _n=$( (logread 2>/dev/null; cat /tmp/log/*.log 2>/dev/null) | grep -c 'WITHOUT the LAN filter')
  res $([ "${_n:-0}" = 0 ] && echo PASS || echo FAIL) "'WITHOUT the LAN filter' lines: ${_n:-0}"
}

c_console_larger() {
  if ! have_logs; then res SKIP "no log readable (logread, /tmp/log, /tmp/logs)"; return; fi
  _n=$( (logread 2>/dev/null; cat /tmp/logs/*.log /tmp/log/*.log 2>/dev/null) | grep -c 'is larger than')
  res $([ "${_n:-0}" = 0 ] && echo PASS || echo FAIL) "'is larger than' lines in the logs: ${_n:-0}"
}

c_pwd_file() {
  if [ ! -f /mnt/config/user.pwd ]; then res SKIP "no user.pwd (no password set)"; return; fi
  if [ ! -f /tmp/flashmode ]; then res SKIP "SD trial (FAT has no Unix modes; flash enforces 600/640)"; return; fi
  _pd=$(sed -n "s/^PRIVDROP=[\"']\{0,1\}\([^\"' 	#]*\).*\$/\1/p" /mnt/config/boot.conf 2>/dev/null | tail -n 1)
  set -- $(ls -ln /mnt/config/user.pwd 2>/dev/null)
  _m=$1; _g=$4
  _t=$(ls /mnt/config/ 2>/dev/null | grep 'user.pwd' | grep -c tmp)
  case "$_pd" in
    0|no|off|false) _want="-rw-------"; _ok=$([ "$_m" = "$_want" ] && [ "${_t:-0}" = 0 ] && echo PASS || echo FAIL) ;;
    *) _want="-rw-r----- (gid 1001)"; _ok=$([ "$_m" = "-rw-r-----" ] && [ "$_g" = "1001" ] && [ "${_t:-0}" = 0 ] && echo PASS || echo FAIL) ;;
  esac
  res "$_ok" "user.pwd mode $_m group $_g (expected $_want), leftover temp files ${_t:-0}"
}

c_status_hue() {
  if [ ! -f /var/run/isp_tune.status ]; then res SKIP "no /var/run/isp_tune.status (ISP_TUNE off)"; return; fi
  _h=$(sed -n 's/^HUE=//p' /var/run/isp_tune.status | head -n 1)
  if [ -z "$_h" ]; then res FAIL "no HUE= line in the status file"; return; fi
  _l=$(grep 'in the ISP' "$LOG" "$LOG.1" 2>/dev/null | tail -n 1)
  ev "status HUE=$_h; last log line: $_l"
  case "$_l" in
    *"hue $_h in the ISP"*) res PASS "HUE=$_h in the status file and in the last log line" ;;
    *) [ "$_h" = 0 ] && res PASS "HUE=0" || res FAIL "HUE=$_h but the last log line says: $_l" ;;
  esac
}

c_dn_cycles() {
  if [ ! -f /var/run/isp_tune.status ]; then res SKIP "no isp_tune status: hue not in the ISP"; return; fi
  _h0=$(sed -n 's/^HUE=//p' /var/run/isp_tune.status | head -n 1)
  if [ -z "$_h0" ]; then res FAIL "no HUE= line in the status file"; return; fi
  _dn_want=${RECETTE_DN_CYCLES:-2}
  night_now && DN_ORIG=1 || DN_ORIG=0
  DN_TOUCHED=1
  _c0=$(log_all | grep -c 'in the ISP')
  _dn_k=0; _dn_n=0; _dn_bad=0
  while [ "$_dn_n" -lt "$_dn_want" ] && [ "$_dn_n" -lt "$MAX_LOOP" ]; do
    _dn_n=$((_dn_n + 1))
    dn_set on; sleep 5
    dn_set off; sleep 5
    _h=$(sed -n 's/^HUE=//p' /var/run/isp_tune.status | head -n 1)
    [ "$_h" = "$_h0" ] || _dn_bad=$((_dn_bad + 1))
    _dn_k=$((_dn_k + 1))
  done
  dn_settle
  _hl=$(log_all | grep -c 'in the ISP')
  ev "hue before $_h0, after the cycles $_h, ISP lines $_c0 -> $_hl, started at night: $DN_ORIG"
  res $([ "$_dn_bad" = 0 ] && [ "$_hl" -gt "$_c0" ] && echo PASS || echo FAIL) "$_dn_k day/night cycles: HUE stays $_h0 after each return, ISP lines $_c0 -> $_hl"
}

c_privacy() {
  if [ -e /tmp/tc100_privacy ]; then res SKIP "privacy already on at the start: not measured"; return; fi
  # The windows are the STAT lines (one per 5 s tick). Without privacy: the windows of the 30 s before the switch. With
  # privacy: the windows after the first one that came after the file appeared (that window holds the switch itself).
  # After removal: the first window after the removal is skipped and the next two are recorded, as evidence only.
  # The baseline starts once the capture rate is steady (stat_settled: after the kill loop the first windows are the
  # catch-up of the restarted server, which made a false FAIL on 2026-11-27), 12 more windows (60 s) at most.
  _pv_w=0
  while [ "$_pv_w" -lt 12 ] && ! stat_settled cap; do
    _pv_s=$(stat_count)
    wait_stat_count $((_pv_s + 1)) || break
    _pv_w=$((_pv_w + 1))
  done
  if stat_settled cap; then ev "capture rate steady before the baseline (after $_pv_w more windows)"
  else ev "capture rate still not steady after $_pv_w more windows: baseline taken anyway"; fi
  _pv_a0=$(stat_count)
  wait_stat_count $((_pv_a0 + 6)) || true
  _pv_a1=$(stat_count)
  touch /tmp/tc100_privacy; PRIV_SET=1
  _pv_b0=$(stat_count)
  wait_stat_count $((_pv_b0 + 7)) || true
  _pv_b1=$(stat_count)
  rm -f /tmp/tc100_privacy; PRIV_SET=0
  _pv_c0=$(stat_count)
  wait_stat_count $((_pv_c0 + 3)) || true
  _pv_c1=$(stat_count)
  if [ "$_pv_a1" -lt "$_pv_a0" ] || [ "$_pv_b1" -lt "$_pv_b0" ] || [ "$_pv_c1" -lt "$_pv_c0" ]; then
    res SKIP "video log rotated during the test: not measured"; return
  fi
  # the evidence: every window, per key, in the three phases
  for _pv_k in pp_ms sub_ms cap enc; do
    ev "$_pv_k without privacy (all windows): $(stat_window_vals $_pv_k "$_pv_a0" "$_pv_a1" | tr '\n' ' ')"
    ev "$_pv_k with privacy (first window after the file appeared skipped): $(stat_window_vals $_pv_k $((_pv_b0 + 1)) "$_pv_b1" | tr '\n' ' ')"
    ev "$_pv_k after removal (first window skipped, evidence only): $(stat_window_vals $_pv_k $((_pv_c0 + 1)) "$_pv_c1" | tr '\n' ' ')"
  done
  _pv_pa=$(stat_mean pp_ms "$_pv_a0" "$_pv_a1");           _pv_pb=$(stat_mean pp_ms $((_pv_b0 + 1)) "$_pv_b1")
  _pv_ca=$(stat_mean cap "$_pv_a0" "$_pv_a1");             _pv_cb=$(stat_mean cap $((_pv_b0 + 1)) "$_pv_b1")
  _pv_ea=$(stat_mean enc "$_pv_a0" "$_pv_a1");             _pv_eb=$(stat_mean enc $((_pv_b0 + 1)) "$_pv_b1")
  _pv_sa=$(stat_mean sub_ms "$_pv_a0" "$_pv_a1");          _pv_sb=$(stat_mean sub_ms $((_pv_b0 + 1)) "$_pv_b1")
  [ -n "$(rtsp_pid)" ] || ensure_rtsp
  if [ -z "$_pv_pa" ] || [ -z "$_pv_pb" ]; then res FAIL "no pp_ms in the STAT lines (privacy file removed)"; return; fi
  if [ -z "$_pv_ca" ] || [ -z "$_pv_cb" ] || [ -z "$_pv_ea" ] || [ -z "$_pv_eb" ]; then res FAIL "no cap or enc in the STAT lines"; return; fi
  if [ "$_pv_ca" -le 0 ] || [ "$_pv_ea" -le 0 ]; then res SKIP "no frame captured or encoded in the windows without privacy: not judged (no viewer?)"; return; fi
  # the criterion: privacy must not lose frames. A window of 5 s with privacy that has less than 90% of the captured or
  # encoded pictures of a window without privacy fails. pp_ms itself is the cost of the mask and is not judged here (the
  # bench cannot tell W1's gain without an old-build run: see test-queue W1-PRIVFILL).
  _pv_lost=
  [ $((_pv_cb * 10)) -lt $((_pv_ca * 9)) ] && _pv_lost="cap $_pv_ca -> $_pv_cb"
  [ $((_pv_eb * 10)) -lt $((_pv_ea * 9)) ] && _pv_lost="$_pv_lost enc $_pv_ea -> $_pv_eb"
  ev "mean per window: pp_ms $_pv_pa -> $_pv_pb, sub_ms $_pv_sa -> $_pv_sb, cap $_pv_ca -> $_pv_cb, enc $_pv_ea -> $_pv_eb (without -> with privacy)"
  if [ -n "$_pv_lost" ]; then
    res FAIL "frames lost under privacy (more than 10% per window): $_pv_lost; pp_ms $_pv_pa -> $_pv_pb"
  else
    res PASS "no frame lost under privacy: cap $_pv_ca -> $_pv_cb, enc $_pv_ea -> $_pv_eb per window; pp_ms $_pv_pa -> $_pv_pb (the cost of the mask, evidence)"
  fi
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
  _code=$(curl -s -K "$CFG" -o "$OUT/it-native.json" -w '%{http_code}' "http://127.0.0.1/cgi-bin/state.cgi?cmd=isp_tune&format=json")
  if [ -s "$OUT/it-cgi.json" ] && [ "$_code" = 200 ] && cmp -s "$OUT/it-cgi.json" "$OUT/it-native.json"; then
    res PASS "isp_tune JSON of the native route equals the CGI ($(wc -c < "$OUT/it-cgi.json") bytes)"
  else
    res FAIL "isp_tune JSON differs, is empty or the native route answered HTTP $_code (files kept in the run folder)"
  fi
}

c_fullconfig() {
  if [ -z "$RECETTE_PASS" ]; then res SKIP "RECETTE_PASS not set"; return; fi
  mk_cfg || { res SKIP "no password"; return; }
  curl -s -K "$CFG" -D "$OUT/fc.headers" -o /dev/null "http://127.0.0.1/cgi-bin/state.cgi?cmd=fullconfig"
  _ct=$(grep -i '^content-type' "$OUT/fc.headers" 2>/dev/null | tr -d '\r')
  res $(echo "$_ct" | grep -qi 'text/plain' && echo PASS || echo FAIL) "fullconfig answered: '$_ct'"
}

c_hw_state() {
  if [ -z "$RECETTE_PASS" ]; then res SKIP "RECETTE_PASS not set"; return; fi
  mk_cfg || { res SKIP "no password"; return; }
  if [ ! -f /tmp/log/audit.log ]; then res SKIP "no /tmp/log/audit.log: nothing to count"; return; fi
  _n0=$(grep -c 'cmd=hw_state' /tmp/log/audit.log 2>/dev/null); _n0=${_n0:-0}
  _hw_n=0; _codes=
  while [ "$_hw_n" -lt 5 ]; do
    _hw_n=$((_hw_n + 1))
    _c=$(curl -s -K "$CFG" -o /dev/null -w '%{http_code}' "http://127.0.0.1/cgi-bin/action.cgi?cmd=hw_state&format=json")
    _codes="$_codes $_c"
  done
  _n1=$(grep -c 'cmd=hw_state' /tmp/log/audit.log 2>/dev/null); _n1=${_n1:-0}
  _ok200=$(echo "$_codes" | tr ' ' '\n' | grep -cx 200)
  res $([ "$_ok200" = 5 ] && [ "$_n1" = "$_n0" ] && echo PASS || echo FAIL) "5 hw_state calls, HTTP codes:$_codes; audit.log lines with hw_state $_n0 -> $_n1"
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
  if [ -z "$_pf" ] || [ -z "$_cs" ]; then res FAIL "pic_fail or cap_stall missing from the STAT line"; return; fi
  res $([ "$_order" = ok ] && [ "$_pf" = 0 ] && [ "$_cs" = 0 ] && echo PASS || echo FAIL) "fields in the STAT order: $_order; pic_fail $_pf, cap_stall $_cs, pp_ms $(stat_val pp_ms), snd_ms $(stat_val snd_ms)"
}

c_start_lines() {
  # the start lines leave the current log by rotation (LOG.1 after the first trim): both are read, and the rotated copy
  # of any older rotation that exists
  _d=$(log_all | grep -c 'direct capture: buffer')
  _g=$(log_all | grep -c 'no guard at its start')
  _c=$(log_all | grep -c 'encoder pool: no picture copy')
  ev "direct capture lines $_d, no-picture-copy lines $_c, old guard lines $_g (current log and rotated copies)"
  if [ "${_g:-0}" -ge 1 ]; then res FAIL "old pool-guard lines ${_g} in the logs (the guard was removed on 2026-10-29)"; return; fi
  if [ "${_d:-0}" -ge 1 ]; then res PASS "direct capture buffers logged, no old pool-guard line"; return; fi
  res SKIP "start lines rotated out: no direct capture line in the current log or its rotated copies (read it right after a start)"
}

c_daynight_lines() {
  if [ ! -f /tmp/logs/daynight.log ]; then res SKIP "no /tmp/logs/daynight.log"; return; fi
  _n=$(wc -l < /tmp/logs/daynight.log)
  res $([ "$_n" -le 400 ] && echo PASS || echo FAIL) "daynight.log has $_n lines (cap 400)"
}

c_config_tmp() {
  if [ ! -d /mnt/config ]; then res FAIL "no /mnt/config"; return; fi
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
  if [ -z "$_p0" ] || [ -z "$_p1" ]; then res FAIL "no processes counter in /proc/stat"; return; fi
  _rate=$(( (_p1 - _p0) * 60 / _w ))
  ev "processes forked in $_w s: $((_p1 - _p0)), per minute $_rate (all jobs; 13 per wifi-quality run before WIFIQ)"
  if [ -z "${RECETTE_FORK_MAX:-}" ]; then res SKIP "rate $_rate per minute measured; set RECETTE_FORK_MAX to judge it"; return; fi
  res $([ "$_rate" -le "$RECETTE_FORK_MAX" ] && echo PASS || echo FAIL) "$_rate forks per minute, limit $RECETTE_FORK_MAX"
}

c_counters_stat() {
  if [ ! -f /tmp/tc100_rtsp.counters ]; then res FAIL "no /tmp/tc100_rtsp.counters"; return; fi
  _ok=1; _shown=
  for _cs_k in starts pic_fail enc_reopen cap_stall dq_err sub_off exit3; do
    _cs_s=$(stat_val "$_cs_k"); _cs_c=$(ctr "$_cs_k")
    if [ -z "$_cs_s" ] || [ -z "$_cs_c" ] || [ "$_cs_s" != "$_cs_c" ]; then _ok=0; fi
  done
  res $([ $_ok = 1 ] && echo PASS || echo FAIL) "STAT tail and counters file agree: starts $(ctr starts), pic_fail $(ctr pic_fail), exit3 $(ctr exit3)"
}

c_counters_term() {
  if [ ! -s "$OUT/kill.stats" ]; then res SKIP "kill-loop did not run in this run folder"; return; fi
  _total=$(wc -l < "$OUT/kill.stats")
  _ok=$(grep -c '^[0-9]* ok ' "$OUT/kill.stats")
  res $([ "$_total" -ge 1 ] && [ "$_ok" = "$_total" ] && echo PASS || echo FAIL) "$_ok of $_total kill -TERM cycles OK (each: starts +1, exit3 unchanged, a clean TERM is not an exit 3)"
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
  if ! have_logs && ! dmesg >/dev/null 2>&1; then res SKIP "no log readable"; return; fi
  _n=$( (cat /tmp/logs/*.log /tmp/log/*.log /mnt/sd/logs/*.log 2>/dev/null; logread 2>/dev/null; dmesg 2>/dev/null) | grep -ci 'stack smashing\|illegal instruction')
  res $([ "${_n:-0}" = 0 ] && echo PASS || echo FAIL) "'stack smashing' / 'illegal instruction' lines in the logs: ${_n:-0}"
}

c_top() {
  top -b -n 1 2>/dev/null | head -n 20 > "$OUT/top1.txt"
  sleep 30
  top -b -n 1 2>/dev/null | head -n 20 > "$OUT/top2.txt"
  if [ -s "$OUT/top2.txt" ] && [ -s "$OUT/top1.txt" ]; then res PASS "top snapshots kept (top1.txt, top2.txt): compare the CPU of tc100_rtsp, tc100-onvifd, tc100-mqttd, httpfront with the 3.0.1 readings"
  else res FAIL "top printed nothing"; fi
}

# ---------------------------------------------------------------------------------------------------------------
# cleanup: runs at the end and on EXIT, INT, TERM. Restores what a check changed,
# compares /mnt/config, leaves the video running.
# ---------------------------------------------------------------------------------------------------------------
cleanup() {
  trap '' EXIT INT TERM
  [ -n "$ORIG_UNLAZY" ] && echo "$ORIG_UNLAZY" > "$UNLAZY" 2>/dev/null
  [ "$PRIV_SET" = 1 ] && rm -f /tmp/tc100_privacy
  if [ "$DN_TOUCHED" = 1 ]; then dn_settle; fi
  [ "$WIFI_TOUCHED" = 1 ] && wlan_restore >/dev/null 2>&1
  [ "$DRY" = 1 ] || ensure_rtsp
  if [ "$CONFIG_CHECKED" = 0 ] && [ -f "$OUT/config-before.md5" ]; then config_check; fi
  rm -f "$CFG" "$PASSF"
  [ "$DRY" = 1 ] || echo "$(date) ended; restored: privacy, irq switch, night mode, wlan0 address and route, video server; /mnt/config checked, not written" >> "$LOGF" 2>/dev/null
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
config_snapshot

# the loop reads the list on fd 3, and each check runs with stdin on /dev/null: a command that reads its stdin cannot eat
# the rest of the list. The variables the checks set (restore state) stay in this shell for the trap.
while IFS='|' read -r id name mode fn arg <&3; do
  selected "$id" || continue
  CUR_ID=$id; CUR_CHECK=$name; CUR="$id/$name"
  case "$mode" in
    dist) [ "$DISRUPT" = 1 ] || { res SKIP "needs --disruptive"; continue; } ;;
    wifi) [ "$WIFI" = 1 ] || { res SKIP "needs --wifi"; continue; } ;;
    manual) skip_manual "$arg"; continue ;;
  esac
  _before=$RESN
  "$fn" </dev/null
  [ "$RESN" = "$_before" ] && res FAIL "the check printed no result"
done 3< "$OUT/checks.txt"

config_check

RUN_T1=$(upt)
TOTAL=$(awk "BEGIN{printf \"%d\", $RUN_T1 - ${RUN_T0:-$RUN_T1}}")
# the counts are the RESULT lines by their status field (field 4), not a grep of the text: evidence can hold the word
set -- $(awk '$1 == "RESULT" { c[$4]++ } END { printf "%d %d %d", c["PASS"] + 0, c["FAIL"] + 0, c["SKIP"] + 0 }' "$RESFILE")
P=$1; F=$2; S=$3
{
  echo "== recette summary ($OUT)"
  awk '{ ev=""; for (i = 5; i <= NF; i++) ev = ev $i " "; printf "%-5s %-46s %.90s\n", $4, $2 " " $3, ev }' "$RESFILE"
  echo "PASS $P  FAIL $F  SKIP $S  total runtime ${TOTAL} s"
} > "$OUT/summary.txt"
cat "$OUT/summary.txt"
echo "done $(date)" > "$OUT/done"
[ "$F" = 0 ] && EXIT_CODE=0 || EXIT_CODE=1
exit "$EXIT_CODE"
