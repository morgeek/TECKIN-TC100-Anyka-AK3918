#!/bin/sh
# TC100 Intelligent Auto Day/Night Detection Daemon for Linux 6.6 LTS
#
# Where the light level comes from (DAYNIGHT_SOURCE in config/daynight.conf, Settings -> Day/night):
#   luma  (default) the mean picture luminance, /tmp/cam_luma. The picture is *after* auto exposure, so it stays near
#                   the AE target whatever the light, and with the IR LEDs on it brightens: it can flap back to day.
#   ae              an exposure index from the ISP's own exposure state, /tmp/cam_ae (written every 2 s by tc100_rtsp:
#                   "lumi exp_time a_gain d_gain isp_d_gain dark_flag", AK_ISP_GET_AE_RUN_INFO). The index measures the
#                   scene light: the longer the exposure and the higher the gains, the darker the scene.
#                     index = exp_time * a_gain/256 * d_gain/256 * isp_d_gain/256   (integer, step by step)
#                   i.e. the exposure time times the total gain, a gain of 256 being 1x. The gain units are not
#                   documented: if they differ the index is only scaled, it stays monotonic (twice the light, half the
#                   index): read it on Settings -> Day/night at dusk and set the two thresholds from it.
#                   Night when the index stays above AE_NIGHT_ABOVE for NIGHT_HOLD seconds; day again when it stays
#                   below AE_DAY_BELOW for DAY_HOLD seconds. With the IR LEDs on, the scene is lit and the exposure
#                   falls: AE_DAY_BELOW must lie clearly below the index seen at night with the LEDs on (and the
#                   long DAY_HOLD, default 60 s, rides over short brightening).
#   isp             the dark flag of /tmp/cam_ae, the ISP's own day/night decision (tuning file thresholds): night
#                   after NIGHT_HOLD seconds of dark=1, day after DAY_HOLD seconds of dark=0.
# Without a usable /tmp/cam_ae (tc100_rtsp not running) the ae and isp sources fall back to luma.
# Calibration log: every DN_LOG_EVERY seconds (300) one line "HH:MM mode=day|night src=... luma=N ae=<cam_ae line>
# idx=N awb=<cam_awb line: white balance counts cnt0..cnt9, colour temperature index>" in $DN_LOG (/tmp/logs/daynight.log, kept to the last 2 x 400 lines; log-persist.sh copies /tmp/logs to the
# card), whatever the source, so the index thresholds can be set from real dusk and dawn readings (F-04).
# Test hook: DN_TEST=1 only defines the functions (tests/test_regressions.py feeds samples to dn_step_ae).
if [ -z "$DN_TEST" ]; then
  PIDFILE="/var/run/auto-night-detection.pid"
  echo "$$" > "$PIDFILE"
  # (common_functions.sh, 31 KB, is not sourced: the daemon uses none of it; the switch is done by nightmode.sh)
fi

CONSOLE=${DN_CONSOLE:-/dev/console}
DN_CONF=${DN_CONF:-/mnt/config/daynight.conf}
DN_RTSPCONF=${DN_RTSPCONF:-/mnt/config/rtspserver.conf}
CAM_AE=${CAM_AE:-/tmp/cam_ae}
CAM_LUMA=${CAM_LUMA:-/tmp/cam_luma}
CAM_AWB=${CAM_AWB:-/tmp/cam_awb}
IRCUT_FILE=${DN_IRCUT:-/var/run/ircut}
NIGHTMODE=${DN_NIGHTMODE:-/mnt/scripts/nightmode.sh}
DN_LOG=${DN_LOG:-/tmp/logs/daynight.log}
DN_LOG_EVERY=${DN_LOG_EVERY:-300}
DN_LOG_AT=0
DN_LOG_N=0

LOW_LIGHT_COUNT=0
BRIGHT_LIGHT_COUNT=0
# Thresholds on the mean picture luminance (0-255): night below LUMA_NIGHT, day again above LUMA_DAY
# (config/daynight.conf, Settings -> Day/night on 3.0; the gap stops the flapping at dusk).
THRESHOLD_NIGHT=40
THRESHOLD_DAY=100
DAYNIGHT_SOURCE=luma
# index defaults from IPCAM2 (rc7 night 2, HW-08): a dark room pegs the exposure at 1124 lines and the analogue gain
# at 6840 (26.7x), index about 30000 with or without the IR LEDs; night above 15000 = full exposure and about 13x
# gain, day below 3000 (5 times less, room for the IR filter and LEDs changing the light at the switch). To be set
# from the dusk and dawn lines of the calibration log (/tmp/logs/daynight.log) once a day of them exists
AE_NIGHT_ABOVE=15000
AE_DAY_BELOW=3000
NIGHT_HOLD=10
DAY_HOLD=60
DN_DARK_SINCE=0
DN_BRIGHT_SINCE=0
DN_ACT=

echo "[auto-night] Daemon started" > "$CONSOLE"

# The daemon itself must stay in auto mode (daynight=2) while it switches: nightmode.sh -> night-mode normally
# means "manual override" and writes daynight=3, which silently froze the daemon in NIGHT mode all day.
export NIGHT_KEEP_AUTO=1

# daynight value and the settings of the config without any fork (the loop runs every 2-8 s)
read_daynight() {
  DN_MODE=2
  if [ -r "$DN_RTSPCONF" ]; then
    while IFS='= ' read -r _k _v _; do
      case "$_k" in daynight) DN_MODE="$_v"; break ;; '[0]') break ;; esac
    done < "$DN_RTSPCONF"
  fi
  [ -r "$DN_CONF" ] || return 0
  while IFS='=' read -r _k _v; do
    case "$_k" in
      LUMA_NIGHT|LUMA_DAY)
        case "$_v" in [0-9]|[0-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5]) ;; *) continue ;; esac
        if [ "$_k" = LUMA_NIGHT ]; then THRESHOLD_NIGHT="$_v"; else THRESHOLD_DAY="$_v"; fi ;;
      DAYNIGHT_SOURCE)
        case "$_v" in luma|ae|isp) DAYNIGHT_SOURCE="$_v" ;; esac ;;
      AE_NIGHT_ABOVE|AE_DAY_BELOW)
        case "$_v" in ''|*[!0-9]*) continue ;; esac
        [ "${#_v}" -le 9 ] || continue
        if [ "$_k" = AE_NIGHT_ABOVE ]; then AE_NIGHT_ABOVE="$_v"; else AE_DAY_BELOW="$_v"; fi ;;
      NIGHT_HOLD|DAY_HOLD)
        case "$_v" in ''|*[!0-9]*) continue ;; esac
        [ "${#_v}" -le 4 ] && [ "$_v" -ge 1 ] && [ "$_v" -le 3600 ] || continue
        if [ "$_k" = NIGHT_HOLD ]; then NIGHT_HOLD="$_v"; else DAY_HOLD="$_v"; fi ;;
    esac
  done < "$DN_CONF"
  # the gap: day must need a clearly lower index than night
  [ "$AE_DAY_BELOW" -lt "$AE_NIGHT_ABOVE" ] || AE_DAY_BELOW=$((AE_NIGHT_ABOVE / 2))
}

# the IR-cut state straight from its state file (same as `ir_cut status`, no fork); 1 = ON = day
read_cut() {
  CUR_CUT=ON
  [ -r "$IRCUT_FILE" ] && { read -r _ic < "$IRCUT_FILE"; [ "$_ic" = 0 ] && CUR_CUT=OFF; }
}

read_now() {
  if [ -n "$DN_NOW" ]; then NOW="$DN_NOW"; else read -r _up _ < /proc/uptime; NOW="${_up%.*}"; fi
}

# exposure index of the "lumi exp_time a_gain d_gain isp_d_gain dark_flag" line in $1..$6 -> DN_IDX (empty when the
# line is not made of plain numbers)
dn_index() {
  DN_IDX=
  # six plain decimal numbers (no empty field, no leading zero: that would be octal; at most 9 digits)
  for _v in "$1" "$2" "$3" "$4" "$5" "$6"; do
    case "$_v" in ''|*[!0-9]*|0[0-9]*) return 1 ;; esac
    [ "${#_v}" -le 9 ] || return 1
  done
  DN_IDX=$(( $2 * $3 / 256 ))
  DN_IDX=$(( DN_IDX * $4 / 256 ))
  DN_IDX=$(( DN_IDX * $5 / 256 ))
}

# Hold logic for the ae and isp sources. $1 = 1 when the scene is dark (wants night), $2 = 1 when it is bright (wants
# day), $3 = now (seconds). Sets DN_ACT to night or day when the condition has held long enough, else empty.
dn_hold() {
  DN_ACT=
  if [ "$CUR_CUT" = ON ]; then
    DN_BRIGHT_SINCE=0
    if [ "$1" = 1 ]; then
      [ "$DN_DARK_SINCE" = 0 ] && DN_DARK_SINCE="$3"
      [ $(( $3 - DN_DARK_SINCE )) -ge "$NIGHT_HOLD" ] && DN_ACT=night
    else
      DN_DARK_SINCE=0
    fi
  else
    DN_DARK_SINCE=0
    if [ "$2" = 1 ]; then
      [ "$DN_BRIGHT_SINCE" = 0 ] && DN_BRIGHT_SINCE="$3"
      [ $(( $3 - DN_BRIGHT_SINCE )) -ge "$DAY_HOLD" ] && DN_ACT=day
    else
      DN_BRIGHT_SINCE=0
    fi
  fi
}

dn_switch() {   # $1 = night|day, $2 = what the decision was based on
  if [ "$1" = night ]; then
    echo "[auto-night] Low light detected ($2): Switching to NIGHT mode" > "$CONSOLE"
    "$NIGHTMODE" on
  else
    echo "[auto-night] Bright light detected ($2): Switching to DAY mode" > "$CONSOLE"
    "$NIGHTMODE" off
  fi
  DN_DARK_SINCE=0; DN_BRIGHT_SINCE=0
  LOW_LIGHT_COUNT=0; BRIGHT_LIGHT_COUNT=0
}

# One decision of the ae / isp source; returns 1 when /tmp/cam_ae cannot be used (the caller falls back to luma).
# $1 = now when given (tests), else the clock.
dn_step_ae() {
  [ -r "$CAM_AE" ] || return 1
  read -r _l _e _a _d _i _k < "$CAM_AE" || return 1
  dn_index "$_l" "$_e" "$_a" "$_d" "$_i" "$_k" || return 1
  [ -n "$1" ] && NOW="$1" || read_now
  read_cut
  if [ "$DAYNIGHT_SOURCE" = isp ]; then
    _dark=0; [ "$_k" != 0 ] && _dark=1
    _bright=$((1 - _dark))
    _why="isp dark flag=$_k"
  else
    _dark=0; [ "$DN_IDX" -gt "$AE_NIGHT_ABOVE" ] && _dark=1
    _bright=0; [ "$DN_IDX" -lt "$AE_DAY_BELOW" ] && _bright=1
    _why="exposure index=$DN_IDX exp=$_e gains=$_a/$_d/$_i"
  fi
  dn_hold "$_dark" "$_bright" "$NOW"
  [ -n "$DN_ACT" ] && dn_switch "$DN_ACT" "$_why"
  return 0
}

# the original decision on the picture luminance: two samples in a row beyond the threshold
dn_step_luma() {
  # Read luminance directly from real-time streamer or cache
  LUMA=50
  if [ -f "$CAM_LUMA" ]; then
    read -r LUMA < "$CAM_LUMA"
  elif [ -f /tmp/currentpic.cache.jpg ]; then
    LUMA=$(hexdump -n 512 -v -e '1/1 "%d\n"' /tmp/currentpic.cache.jpg 2>/dev/null | awk '{s+=$1} END {if (NR>0) print int(s/NR); else print 50}')
  fi
  case "$LUMA" in ''|*[!0-9]*) LUMA=50 ;; esac

  read_cut
  if [ "$CUR_CUT" = "ON" ]; then
    # Currently DAY mode
    if [ "$LUMA" -lt "$THRESHOLD_NIGHT" ]; then
      LOW_LIGHT_COUNT=$((LOW_LIGHT_COUNT + 1))
      if [ "$LOW_LIGHT_COUNT" -ge 2 ]; then
        dn_switch night "luma=$LUMA"
      fi
    else
      LOW_LIGHT_COUNT=0
    fi
  else
    # Currently NIGHT mode
    if [ "$LUMA" -gt "$THRESHOLD_DAY" ]; then
      BRIGHT_LIGHT_COUNT=$((BRIGHT_LIGHT_COUNT + 1))
      if [ "$BRIGHT_LIGHT_COUNT" -ge 2 ]; then
        dn_switch day "luma=$LUMA"
      fi
    else
      BRIGHT_LIGHT_COUNT=0
    fi
  fi
}

# one calibration line when DN_LOG_EVERY seconds have passed (one date fork every 5 minutes; mv every 400 lines)
dn_log() {
  read_now
  [ $(( NOW - DN_LOG_AT )) -ge "$DN_LOG_EVERY" ] || return 0
  DN_LOG_AT=$NOW
  read_cut
  _ll=-; [ -r "$CAM_LUMA" ] && read -r _ll < "$CAM_LUMA"
  _la=-; [ -r "$CAM_AE" ] && read -r _la < "$CAM_AE"
  _lw=-; [ -r "$CAM_AWB" ] && read -r _lw < "$CAM_AWB"
  # shellcheck disable=SC2086
  dn_index $_la 2>/dev/null || DN_IDX=-
  _lm=day; [ "$CUR_CUT" = OFF ] && _lm=night
  if [ "$DN_LOG_N" -ge 400 ]; then mv -f "$DN_LOG" "$DN_LOG.1" 2>/dev/null; DN_LOG_N=0; fi
  echo "$(date +%H:%M 2>/dev/null) mode=$_lm src=$DAYNIGHT_SOURCE luma=${_ll:--} ae=${_la:--} idx=${DN_IDX:--} awb=${_lw:--}" >> "$DN_LOG" 2>/dev/null
  DN_LOG_N=$((DN_LOG_N + 1))
}

# The two config files are read again only when one of them was written since the last read (stamp file): the loop runs
# every 2-8 s and a parse is some hundred shell steps each time. A file that is missing is read (and ignored) each time.
dn_conf_changed() {
  [ -e "$DN_STAMP" ] || return 0
  for _cf in "$DN_RTSPCONF" "$DN_CONF"; do
    [ -e "$_cf" ] || return 0
    [ "$DN_STAMP" -nt "$_cf" ] || return 0   # written since, or in the same second as the stamp
  done
  return 1
}

# Waiting without a fork: read -t on a FIFO that nobody writes to (as scripts/button-watch.sh does); sleep when the shell
# has no working read -t (probed once: the first wait must really last a second).
dn_wait() {
  if [ "$DN_WAITMODE" = fifo ]; then read -t "$1" _x <> "$DN_FIFO" 2>/dev/null; else sleep "$1"; fi
  return 0
}
dn_centis() { read -r _up _ < /proc/uptime; DN_CS="${_up%.*}${_up#*.}"; }

if [ -z "$DN_TEST" ]; then
  SLP=8
  DN_STAMP=/tmp/.auto-night.stamp.$$; DN_FIFO=/tmp/.auto-night.fifo.$$; DN_WAITMODE=sleep
  trap 'rm -f "$DN_STAMP" "$DN_FIFO"; exit 0' TERM INT
  if mkfifo "$DN_FIFO" 2>/dev/null; then
    dn_centis; _c0=$DN_CS
    read -t 1 _x <> "$DN_FIFO" 2>/dev/null
    dn_centis
    case "$_c0$DN_CS" in *[!0-9]*) ;; *) [ $((DN_CS - _c0)) -ge 90 ] && DN_WAITMODE=fifo ;; esac
  fi
  while true; do
    dn_wait "$SLP"

    # Check if auto detection is enabled in config (manual day/night = 3 pauses the daemon)
    if dn_conf_changed; then read_daynight; : > "$DN_STAMP"; fi
    dn_log
    [ "$DN_MODE" != "2" ] && continue

    if [ "$DAYNIGHT_SOURCE" != luma ]; then
      SLP=2     # /tmp/cam_ae changes every 2 s; the hold times are measured in seconds
      dn_step_ae && continue
    fi
    SLP=8
    dn_step_luma
  done
fi
