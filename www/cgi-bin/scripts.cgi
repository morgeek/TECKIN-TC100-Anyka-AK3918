#!/bin/sh
. /mnt/www/cgi-bin/func.cgi

# Ensure temp files are cleaned up on exit/interrupt. The allstates cache is
# intentionally NOT removed here — it's supposed to survive across requests
# (ALLSTATES_CACHE_TTL_SECONDS governs its lifetime); deleting it on every
# exit made the cache permanently dead code and forced a full re-scan of
# every controlscript on every poll.
trap 'rm -f /tmp/scripts-status.$$.tmp' EXIT INT TERM

echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"

SCRIPT_HOME="${SCRIPT_HOME:-/mnt/controlscripts/}"
# Allow tests to override autostart dir for safer testing
AUTOSTART_DIR="${AUTOSTART_DIR:-/mnt/config/autostart}"
# One switch per service (scripts/service-switch.sh): for the services with a settings key, the "Boot" toggle reads
# and writes that key, not a file in AUTOSTART_DIR
svc_switch() { return 1; }
[ -r "${SVC_SWITCH_SH:-/mnt/scripts/service-switch.sh}" ] && . "${SVC_SWITCH_SH:-/mnt/scripts/service-switch.sh}"
# R17: boot.conf has ~400 lines; reading it with a shell loop for each key (svc_kv, boot_conf_flag) cost ~0.4 s a time,
# ~7 times per Services scan (4.3 s cold on IPCAM2, rc32). bc_load reads the keys allstates needs in ONE awk pass
# (last line wins, one pair of quotes removed, as svc_kv); bc_get KEY sets _bcg (no fork). Not loaded: the old paths.
BC_KEYS="SYSLOG_ENABLE REC_LOCAL MEM_GUARD_ENABLE WIFI_RESCUE WHEP"
_bc_loaded=""; _bc_vals=""
bc_load() {
  [ -n "$_bc_loaded" ] && return 0
  _bc_loaded=1
  _bc_vals="$(awk -v keys=" $BC_KEYS " '{ k = $0; sub(/=.*/, "", k) } index($0, "=") && index(keys, " " k " ") {
      v = $0; sub(/^[^=]*=/, "", v); sub(/\r$/, "", v); val[k] = v }
    END { for (k in val) print k "=" val[k] }' "${SW_CONF_DIR:-/mnt/config}/boot.conf" 2>/dev/null)"
}
bc_get() {
  _bcg=""
  _bc_ifs=$IFS; IFS='
'
  set -f
  for _bc_l in $_bc_vals; do case "$_bc_l" in "$1="*) _bcg=${_bc_l#*=} ;; esac; done
  set +f; IFS=$_bc_ifs
  _bcg=${_bcg#[\"\']}; _bcg=${_bcg%[\"\']}
}
# boot_enabled SCRIPT -> 0 when it starts at boot
boot_enabled() {
  if svc_switch "$1"; then
    if [ -n "$_bc_loaded" ] && [ "$SW_FILE" = "${SW_CONF_DIR:-/mnt/config}/boot.conf" ]; then
      bc_get "$SW_KEY"; [ -n "$_bcg" ] || _bcg=$SW_DEF
      case "$_bcg" in 1|true|yes|on|enabled) return 0 ;; esac
      return 1
    fi
    svc_on "$1"
  else [ -f "$AUTOSTART_DIR/$1" ]; fi
}
status_timeout_cmd=""
ALLSTATES_CACHE_FILE="${ALLSTATES_CACHE_FILE:-/tmp/scripts-allstates.cache}"
ALLSTATES_CACHE_TTL_SECONDS="${ALLSTATES_CACHE_TTL_SECONDS:-4}"

case "$ALLSTATES_CACHE_TTL_SECONDS" in
  ''|*[!0-9]*) ALLSTATES_CACHE_TTL_SECONDS=4 ;;
esac
[ "$ALLSTATES_CACHE_TTL_SECONDS" -lt 0 ] && ALLSTATES_CACHE_TTL_SECONDS=0
[ "$ALLSTATES_CACHE_TTL_SECONDS" -gt 30 ] && ALLSTATES_CACHE_TTL_SECONDS=30

is_valid_script_name() {
  case "$1" in
    ''|*[!A-Za-z0-9._-]* ) return 1 ;;
    *) return 0 ;;
  esac
}

now_epoch_safe() {
  now_ts="$(date +%s 2>/dev/null)"
  case "$now_ts" in
    ''|*[!0-9]*) echo "0" ;;
    *) echo "$now_ts" ;;
  esac
}

# Cached /proc/uptime integer seconds — read once per request, reused across all PID probes
_PROC_UPTIME_S=-1
_svc_read_uptime_s() {
  [ "$_PROC_UPTIME_S" -ge 0 ] 2>/dev/null && return
  if [ -r /proc/uptime ]; then
    read -r _up _idle < /proc/uptime
    _PROC_UPTIME_S="${_up%.*}"
  fi
}

# Compute how long a PID has been running (in seconds) via /proc/<pid>/stat.
# Result stored in _svc_uptime_s (-1 = unknown/unavailable). No forks.
_svc_pid_uptime() {
  _svc_uptime_s=-1
  _spid="$1"
  case "$_spid" in ''|0|*[!0-9]*) return ;; esac
  [ -r "/proc/$_spid/stat" ] || return
  read -r _stat_raw < "/proc/$_spid/stat"
  # Strip "pid (comm) " prefix — handles spaces in comm name by cutting at first ') '
  _stat_rest="${_stat_raw#*) }"
  set -- $_stat_rest
  # Field 20 of _stat_rest = field 22 of /proc/pid/stat = starttime in jiffies since boot
  _startjif="${20}"
  case "$_startjif" in ''|0|*[!0-9]*) return ;; esac
  _svc_read_uptime_s
  [ "$_PROC_UPTIME_S" -ge 0 ] 2>/dev/null || return
  _svc_uptime_s=$((_PROC_UPTIME_S - _startjif / 100))
  [ "$_svc_uptime_s" -lt 0 ] && _svc_uptime_s=0
}

invalidate_allstates_cache() {
  if [ -f "$ALLSTATES_CACHE_FILE" ]; then
    : > "${ALLSTATES_CACHE_FILE}.stale"
  else
    rm -f "${ALLSTATES_CACHE_FILE}.stale" >/dev/null 2>&1 || true
  fi
  # The Settings form also reports service switches from boot.conf.
  rm -f /tmp/state-response-fullconfig*.cache >/dev/null 2>&1 || true
  rm -f /tmp/action-response-md_zones_info.cache >/dev/null 2>&1 || true
}

allstates_cache_is_fresh() {
  [ "$ALLSTATES_CACHE_TTL_SECONDS" -gt 0 ] || return 1
  [ -f "$ALLSTATES_CACHE_FILE" ] || return 1
  [ ! -e "${ALLSTATES_CACHE_FILE}.stale" ] || return 1

  read -r cache_header < "$ALLSTATES_CACHE_FILE" || return 1
  case "$cache_header" in
    ts=*) cache_ts="${cache_header#ts=}" ;;
    *) return 1 ;;
  esac
  case "$cache_ts" in
    ''|*[!0-9]*) return 1 ;;
  esac

  now_ts="$(now_epoch_safe)"
  [ "$now_ts" -gt 0 ] || return 1
  [ "$cache_ts" -le "$now_ts" ] || return 1

  age=$((now_ts - cache_ts))
  [ "$age" -le "$ALLSTATES_CACHE_TTL_SECONDS" ]
}

allstates_cache_age() {
  [ -f "$ALLSTATES_CACHE_FILE" ] || return 1
  if [ -e "${ALLSTATES_CACHE_FILE}.stale" ]; then allstates_age=60; return 0; fi
  read -r cache_header < "$ALLSTATES_CACHE_FILE" || return 1
  case "$cache_header" in ts=*) cache_ts="${cache_header#ts=}" ;; *) return 1 ;; esac
  case "$cache_ts" in ''|*[!0-9]*) return 1 ;; esac
  now_ts="$(now_epoch_safe)"
  case "$now_ts" in ''|0|*[!0-9]*) return 1 ;; esac
  [ "$cache_ts" -le "$now_ts" ] || return 1
  allstates_age=$((now_ts - cache_ts))
}

run_status_probe() {
  script_path="$1"
  timeout_seconds="${2:-2}"
  probe_output="/tmp/scripts-status.$$.tmp"
  rm -f "$probe_output" 2>/dev/null || true

  if [ -z "$status_timeout_cmd" ]; then
    if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox timeout 1 sh -c ':' >/dev/null 2>&1; then
      status_timeout_cmd="/mnt/bin/busybox timeout"
    elif command -v timeout >/dev/null 2>&1; then
      status_timeout_cmd="timeout"
    elif [ -x /bin/busybox ] && /bin/busybox timeout 1 sh -c ':' >/dev/null 2>&1; then
      status_timeout_cmd="/bin/busybox timeout"
    fi
  fi

  if [ -n "$status_timeout_cmd" ]; then
    case "$status_timeout_cmd" in
      "/mnt/bin/busybox timeout")
        /mnt/bin/busybox timeout "$timeout_seconds" sh "$script_path" status </dev/null >"$probe_output" 2>/dev/null
        probe_rc=$?
        ;;
      "/bin/busybox timeout")
        /bin/busybox timeout "$timeout_seconds" sh "$script_path" status </dev/null >"$probe_output" 2>/dev/null
        probe_rc=$?
        ;;
      *)
        timeout "$timeout_seconds" sh "$script_path" status </dev/null >"$probe_output" 2>/dev/null
        probe_rc=$?
        ;;
    esac
  else
    sh "$script_path" status </dev/null >"$probe_output" 2>/dev/null &
    probe_pid=$!

    (
      sleep "$timeout_seconds"
      if kill -0 "$probe_pid" >/dev/null 2>&1; then
        kill "$probe_pid" >/dev/null 2>&1 || true
        sleep 1
        kill -9 "$probe_pid" >/dev/null 2>&1 || true
      fi
    ) >/dev/null 2>&1 &
    watchdog_pid=$!

    wait "$probe_pid" >/dev/null 2>&1
    probe_rc=$?

    kill "$watchdog_pid" >/dev/null 2>&1 || true
    wait "$watchdog_pid" >/dev/null 2>&1 || true
  fi

  if [ -f "$probe_output" ]; then
    cat "$probe_output"
    rm -f "$probe_output"
  fi

  case "$probe_rc" in
    124|137|143)
      return 124
      ;;
  esac
  if [ "$probe_rc" -ge 128 ]; then
    return 124
  fi
  return "$probe_rc"
}

parse_script_capabilities() {
  script_file="$1"
  has_start=0
  has_stop=0
  has_status=0
  script_pidfile=""
  # Parse start/stop/status function presence (and the declared PIDFILE /
  # PID_FILE) using shell builtins to save forks
  while IFS= read -r line; do
    case "$line" in
      *"start()"*)  has_start=1 ;;
      *"stop()"*)   has_stop=1 ;;
      *"status()"*) has_status=1 ;;
      PIDFILE=*|PID_FILE=*)
        if [ -z "$script_pidfile" ]; then
          script_pidfile="${line#*=}"
          script_pidfile="${script_pidfile%%[ 	#]*}"
          script_pidfile="${script_pidfile#[\"\']}"; script_pidfile="${script_pidfile%[\"\']}"
        fi ;;
    esac
  done < "$script_file"
}

# Services whose status() is exactly "the PID in the pidfile is alive". For
# them allstates reads the pidfile and /proc directly instead of running the
# script: running 25 controlscripts one after another (each sourcing
# common_functions.sh under busybox timeout) took ~12 s per Services poll.
# memory-guard adds "disabled" when its boot.conf key is off.
# LED/IR toggles, motion, auto-night and web-server go through
# fast_toggle_state; any other script is probed.
SERVICES_HIDDEN="night-mode ir-led ir-cut black-white front-led red-led auto-night-detection motion-detection sound-detection telegram-bot"
SERVICES_SYSTEM="rtsp-h26x web-server mqtt-bridge memory-guard health-snapshot button-actions ftp-server telnet-server ssh-server syslog-forward onvif wifi-rescue whep mdns"
# item 46: the page shows them in three themed cards (any other script goes to a fourth, "Other")
SERVICES_CORE="rtsp-h26x web-server memory-guard health-snapshot button-actions"
SERVICES_ACCESS="ssh-server telnet-server ftp-server mdns wifi-rescue"
SERVICES_INTEGRATIONS="mqtt-bridge onvif syslog-forward whep"
FAST_PIDFILE_SERVICES=" button-actions ftp-server health-snapshot mqtt-bridge onvif rtsp-h26x sound-detection ssh-server syslog-forward telegram-bot telnet-server memory-guard wifi-rescue mdns whep "

# port_listening PORT (same as common_functions.sh) -> 0 if a TCP socket is in LISTEN state on PORT
# (/proc/net/tcp, no fork). A pid that is alive is not enough: a recycled PID
# or a half-dead tcpsvd showed services as running with their port closed.
port_listening() {
  case "$1" in ''|*[!0-9]*) return 1 ;; esac
  for _pl_f in /proc/net/tcp /proc/net/tcp6; do
    [ -r "$_pl_f" ] || continue
    while read -r _pl_sl _pl_local _pl_rem _pl_st _pl_rest; do
      [ "$_pl_st" = 0A ] || continue
      _pl_p="${_pl_local##*:}"
      case "$_pl_p" in ''|*[!0-9A-Fa-f]*) continue ;; esac
      [ "$((0x$_pl_p))" -eq "$1" ] 2>/dev/null && return 0
    done < "$_pl_f"
  done
  return 1
}

# read_first FILE -> first word of FILE ("" if unreadable), no fork.
read_first() {
  _rf_v=""
  [ -r "$1" ] && read -r _rf_v _rf_rest < "$1" 2>/dev/null
  printf '%s' "$_rf_v"
}

# kv_value FILE KEY -> raw value of KEY=... in FILE, no fork.
kv_value() {
  _kv_v=""
  [ -r "$1" ] || return 0
  while IFS= read -r _kv_l; do
    case "$_kv_l" in "$2="*) _kv_v="${_kv_l#*=}" ;; esac
  done < "$1"
  _kv_v="${_kv_v#[\"\']}"; _kv_v="${_kv_v%[\"\']}"
  printf '%s' "$_kv_v"
}

# fast_toggle_state SCRIPT -> same result as the script's status(), computed
# here: those status() functions only read a sysfs/run file or setconf, but
# starting each script costs ~0.2 s (common_functions.sh + busybox timeout).
# Keep in sync with common_functions.sh (led, ir_led, ir_cut, black_white,
# motion_detection) — tests/test_regressions.py checks the files they read.
fast_toggle_state() {
  _ft_on=""
  case "$1" in
    front-led) { [ "$(read_first /sys/class/leds/blue_led/brightness)" = 1 ] || [ "$(read_first /sys/class/leds/blue/brightness)" = 1 ]; } && _ft_on=1 ;;
    red-led)   { [ "$(read_first /sys/class/leds/red_led/brightness)" = 1 ] || [ "$(read_first /sys/class/leds/red/brightness)" = 1 ]; } && _ft_on=1 ;;
    ir-led)    { [ "$(read_first /sys/user-gpio/ir-led)" = 1 ] || [ "$(read_first /sys/class/leds/ir/brightness)" = 1 ]; } && _ft_on=1 ;;
    ir-cut)    [ "$(read_first /var/run/ircut)" = 1 ] && _ft_on=1 ;;
    privacy)   [ -f /tmp/tc100_privacy ] && _ft_on=1 ;;
    black-white) [ "$(read_first /var/run/vday)" = 0 ] && _ft_on=1 ;;
    night-mode)
      { [ "$(read_first /sys/user-gpio/ir-led)" = 1 ] || [ "$(read_first /sys/class/leds/ir/brightness)" = 1 ]; } \
        && [ "$(read_first /var/run/ircut)" = 0 ] && [ "$(read_first /var/run/vday)" = 0 ] && _ft_on=1 ;;
    auto-night-detection) [ "$(/mnt/bin/setconf -g n 2>/dev/null)" = 2 ] && _ft_on=1 ;;
    motion-detection)
      if [ "$(/mnt/bin/setconf -g p 2>/dev/null)" != 0 ]; then
        _ft_pid="$(read_first /var/run/detection-monitor.pid)"
        case "$_ft_pid" in ''|*[!0-9]*) ;; *) [ -d "/proc/$_ft_pid" ] && _ft_on=1 ;; esac
      fi ;;
    recording)	# 3.0: the recorder inside tc100_rtsp, on while REC_LOCAL=1
      case "$(boot_conf_flag REC_LOCAL)" in 1|true|yes|on)
        _ft_pid="$(read_first /var/run/v4l2rtspserver.pid)"	# tc100_rtsp's pid (the file kept its 2.x name)
        case "$_ft_pid" in ''|*[!0-9]*) ;; *) [ -d "/proc/$_ft_pid" ] && _ft_on=1 ;; esac ;;
      esac ;;
    web-server)
      # R20-U7: the age is the one of httpfront (the server), not of a busybox httpd child that answers one request (or of
      # this CGI): httpfront wins; a standalone httpd (no httpfront) is only the fallback, its lowest pid (the daemon)
      _ft_fb=""
      for _ft_p in /proc/[0-9]*; do
        [ -r "$_ft_p/stat" ] || continue
        read -r _ft_stat 2>/dev/null < "$_ft_p/stat" || continue
        case "$_ft_stat" in
          *"(httpfront)"*) _ft_on=1; _ft_pid="${_ft_p#/proc/}"; _ft_fb=""; break ;;
          *"(httpd)"*) [ -n "$_ft_fb" ] || _ft_fb="${_ft_p#/proc/}" ;;
        esac
      done
      if [ -z "$_ft_on" ] && [ -n "$_ft_fb" ]; then _ft_on=1; _ft_pid="$_ft_fb"; fi ;;
    *) return 1 ;;
  esac
  if [ -n "$_ft_on" ]; then
    state="running"; running=1
    if [ "$1" = web-server ] || [ "$1" = motion-detection ]; then
      _svc_pid_uptime "$_ft_pid"; uptime_s="$_svc_uptime_s"
    fi
  else
    state="stopped"
  fi
  return 0
}

# boot_conf_flag KEY -> prints the raw value of KEY from boot.conf (no forks).
boot_conf_flag() {
  _bcf_v=""
  if [ -n "$_bc_loaded" ]; then
    case " $BC_KEYS " in *" $1 "*) bc_get "$1"; printf '%s' "$_bcg"; return 0 ;; esac
  fi
  [ -r /mnt/config/boot.conf ] || return 0
  while IFS= read -r _bcf_l; do
    case "$_bcf_l" in "$1="*) _bcf_v="${_bcf_l#*=}" ;; esac
  done < /mnt/config/boot.conf
  _bcf_v="${_bcf_v#[\"\']}"; _bcf_v="${_bcf_v%[\"\']}"
  printf '%s' "$_bcf_v"
}

# fast_pidfile_state SCRIPT -> sets state / running / uptime_s; returns 1 when
# SCRIPT is not on the fast path (caller probes it).
fast_pidfile_state() {
  case "$FAST_PIDFILE_SERVICES" in *" $1 "*) ;; *) return 1 ;; esac
  [ -n "$script_pidfile" ] || return 1
  _fp_pid=""
  [ -r "$script_pidfile" ] && read -r _fp_pid < "$script_pidfile" 2>/dev/null
  case "$_fp_pid" in ''|*[!0-9]*) _fp_pid="" ;; esac
  case "$1" in
    ftp-server)    _fp_port="$(kv_value /mnt/config/ftp.conf PORT)" ;;
    telnet-server) _fp_port="$(kv_value /mnt/config/telnetd.conf TELNET_PORT)" ;;
    *)             _fp_port="" ;;
  esac
  # Listener services: a live PID whose port is closed is not running.
  if [ -n "$_fp_pid" ] && [ -n "$_fp_port" ] && ! port_listening "$_fp_port"; then
    _fp_pid=""
  fi
  if [ -n "$_fp_pid" ] && [ -d "/proc/$_fp_pid" ]; then
    state="running"; running=1
    _svc_pid_uptime "$_fp_pid"
    uptime_s="$_svc_uptime_s"
    return 0
  fi
  state="stopped"
  case "$1" in
    memory-guard) _fp_key=MEM_GUARD_ENABLE ;;
    *)            _fp_key="" ;;
  esac
  if [ -n "$_fp_key" ]; then
    case "$(boot_conf_flag "$_fp_key")" in 1|true|yes|on|enabled) ;; *) state="disabled" ;; esac
  fi
  return 0
}

service_impact_level_for() {
  case "$1" in
    rtsp-h26x|motion-detection)
      echo "heavy"
      ;;
    onvif|mqtt-bridge|telegram-bot|auto-night-detection)
      echo "med"
      ;;
    *)
      echo "min"
      ;;
  esac
}

service_impact_hint_for() {
  case "$1" in
    rtsp-h26x)
      echo "Continuous video encode and streaming load."
      ;;
    motion-detection)
      echo "Continuous detection loop uses CPU while active."
      ;;
    onvif)
      echo "Adds network discovery and ONVIF control workload."
      ;;
    mqtt-bridge)
      echo "Low-to-medium network polling and publish workload."
      ;;
    telegram-bot)
      echo "Triggered network tasks can spike CPU and RAM briefly."
      ;;
    auto-night-detection)
      echo "Periodic checks with moderate overhead."
      ;;
    *)
      echo "Lightweight service with minimal runtime overhead."
      ;;
  esac
}

service_impact_label_for() {
  case "$1" in
    heavy) echo "Heavy" ;;
    med) echo "Med" ;;
    *) echo "Min" ;;
  esac
}

# Script capabilities (start/stop/status, PIDFILE) only change when the
# controlscripts do; parsing all of them line by line cost ~1.3 s per poll.
# Cached in tmpfs, rebuilt when the list changes or any script is newer.
CAPS_CACHE_FILE="${CAPS_CACHE_FILE:-/tmp/scripts-caps.cache}"
ensure_caps_cache() {
  _cc_names=""
  _cc_stale=0
  [ -f "$CAPS_CACHE_FILE" ] || _cc_stale=1
  for _cc_p in "$SCRIPT_HOME"/*; do
    [ -f "$_cc_p" ] || continue
    _cc_n="${_cc_p##*/}"
    is_valid_script_name "$_cc_n" || continue
    _cc_names="$_cc_names $_cc_n"
    [ "$_cc_stale" = 1 ] || [ ! "$_cc_p" -nt "$CAPS_CACHE_FILE" ] || _cc_stale=1
  done
  if [ "$_cc_stale" = 0 ]; then
    read -r _cc_head < "$CAPS_CACHE_FILE" 2>/dev/null
    [ "$_cc_head" = "#$_cc_names" ] && return 0
  fi
  _cc_tmp="$CAPS_CACHE_FILE.$$"
  {
    echo "#$_cc_names"
    for _cc_n in $_cc_names; do
      parse_script_capabilities "$SCRIPT_HOME/$_cc_n"
      echo "$_cc_n $has_start $has_stop $has_status ${script_pidfile:--}"
    done
  } > "$_cc_tmp" && mv -f "$_cc_tmp" "$CAPS_CACHE_FILE"
}

generate_allstates_payload() {
  ensure_caps_cache
  bc_load 2>/dev/null || :
  printf '{"status":"ok","services":['
  first=1
  while read -r script has_start has_stop has_status script_pidfile; do
    case "$script" in '#'*|'') continue ;; esac
    [ "$script_pidfile" = "-" ] && script_pidfile=""
    script_path="$SCRIPT_HOME/$script"
    [ -f "$script_path" ] || continue

    [ "$first" -eq 0 ] && printf ','
    first=0

    autostart_enabled=0
    running=0
    state="unknown"
    uptime_s=-1

    boot_enabled "$script" && autostart_enabled=1

    if [ "$has_status" -eq 1 ] && { fast_pidfile_state "$script" || fast_toggle_state "$script"; }; then
      :
    elif [ "$has_status" -eq 1 ]; then
      # For bulk listing, use a shorter timeout to avoid blocking the whole response.
      status_output="$(run_status_probe "$script_path" 1)"
      status_rc=$?
      if [ "$status_rc" -eq 0 ]; then
        if [ -n "$status_output" ]; then
          state="running"
          running=1
          # Extract PID from "PID: <number>" and compute process uptime via /proc
          _svc_pid=0
          case "$status_output" in
            *"PID: "[0-9]*) _tmp="${status_output#*PID: }"; _svc_pid="${_tmp%%[!0-9]*}" ;;
          esac
          case "$_svc_pid" in ''|0|*[!0-9]*) _svc_pid=0 ;; esac
          if [ "$_svc_pid" -gt 0 ]; then
            _svc_pid_uptime "$_svc_pid"
            uptime_s="$_svc_uptime_s"
          fi
        else
          state="stopped"
        fi
      elif [ "$status_rc" -eq 143 ] || [ "$status_rc" -eq 124 ]; then
        state="timeout"
      elif [ "$status_rc" -eq 1 ]; then
        # Most controlscripts' status() returns 1 when the daemon is not
        # running (onvif, sound-detection, ...): that is "stopped",
        # not a failure. Other codes (2 = shell error, 127 = missing command)
        # remain "error".
        state="stopped"
      elif [ "$status_rc" -eq 3 ]; then
        state="disabled"   # turned off in boot.conf (memory-guard)
      else
        state="error"
      fi
    fi
    printf '{"script":"%s","state":"%s","running":%s,"has_start":%s,"has_stop":%s,"has_status":%s,"autostart_enabled":%s,"uptime_s":%s}' \
      "$script" "$state" "$running" "$has_start" "$has_stop" "$has_status" "$autostart_enabled" "$uptime_s"
  done < "$CAPS_CACHE_FILE"
  echo ']}'
}

_emit_cached_allstates() {
  {
    IFS= read -r _
    while IFS= read -r _asl || [ -n "$_asl" ]; do
      printf '%s\n' "$_asl"
    done
  } < "$ALLSTATES_CACHE_FILE"
}

emit_allstates_response() {
  if allstates_cache_is_fresh; then
    _emit_cached_allstates
    return
  fi

  # A scan can take longer than the 4 s freshness window. Keep a recent
  # snapshot visible while one background refresh runs, instead of making
  # every Services page wait for the sequential status probes.
  if [ "$ALLSTATES_CACHE_TTL_SECONDS" -gt 0 ] && allstates_cache_age && [ "$allstates_age" -le 60 ]; then
    refresh_lock="${ALLSTATES_CACHE_FILE}.refresh.lock"
    if mkdir "$refresh_lock" 2>/dev/null; then
      (
        refresh_body="/tmp/scripts-allstates-body.$$.tmp"
        refresh_tmp="/tmp/scripts-allstates.$$.tmp"
        trap 'rm -f "$refresh_body" "$refresh_tmp"; rmdir "$refresh_lock" 2>/dev/null' EXIT HUP INT TERM
        if generate_allstates_payload > "$refresh_body"; then
          refresh_ts="$(now_epoch_safe)"
          if [ "$refresh_ts" -gt 0 ] 2>/dev/null && {
            printf 'ts=%s\n' "$refresh_ts"
            cat "$refresh_body"
          } > "$refresh_tmp"; then
            mv -f "$refresh_tmp" "$ALLSTATES_CACHE_FILE" 2>/dev/null || true
            rm -f "${ALLSTATES_CACHE_FILE}.stale" >/dev/null 2>&1 || true
          fi
        fi
      ) </dev/null >/dev/null 2>&1 &
    fi
    _emit_cached_allstates
    return
  fi

  if [ "$ALLSTATES_CACHE_TTL_SECONDS" -gt 0 ]; then
    tmp_body="/tmp/scripts-allstates-body.$$.tmp"
    tmp_cache="/tmp/scripts-allstates.$$.tmp"
    if generate_allstates_payload > "$tmp_body"; then
      # Start the TTL after the slow scan has completed, not before it.
      now_ts="$(now_epoch_safe)"
      if [ "$now_ts" -gt 0 ] 2>/dev/null && {
        printf 'ts=%s\n' "$now_ts"
        cat "$tmp_body"
      } > "$tmp_cache"; then
        mv -f "$tmp_cache" "$ALLSTATES_CACHE_FILE" 2>/dev/null || true
        rm -f "${ALLSTATES_CACHE_FILE}.stale" >/dev/null 2>&1 || true
      fi
    fi
    rm -f "$tmp_body" "$tmp_cache"
    if [ -s "$ALLSTATES_CACHE_FILE" ]; then
      _emit_cached_allstates
      return
    fi
  fi

  generate_allstates_payload
}

# allstates is a page-wide poll: the Services page calls it without a script
# name. It used to be handled only inside the per-script branch below, so the
# request fell through to the HTML listing, the page's JSON parse failed and
# every row stayed on "Loading..." ("Service status is unavailable").
if [ "$F_cmd" = "allstates" ]; then
  echo "Content-type: application/json"
  echo ""
  emit_allstates_response
  exit 0
fi

if [ -n "$F_script" ]; then
  script="${F_script##*/}"
  if ! is_valid_script_name "$script"; then
    echo "Content-type: application/json"
    echo ""
    echo "{\"status\":\"error\",\"reason\":\"invalid script name\"}"
    exit 0
  fi

  if [ -e "$SCRIPT_HOME/$script" ]; then
    case "$F_cmd" in
      start)
        mutation_guard
        echo "Content-type: text/html"
        echo ""

        echo "Running script '$script'..."
        # Capture via a temp file, never via $(...): services that background a
        # daemon (ftp-server's tcpsvd, the service watchdogs) would inherit the
        # command-substitution pipe and keep it open, so the CGI never returned
        # and the browser hung even though the service had started.
        _start_out="/tmp/scripts-start.$$.out"
        sh "$SCRIPT_HOME/$script" start </dev/null >"$_start_out" 2>&1
        _start_rc=$?
        if [ "$_start_rc" -eq 0 ]; then
          case "$script" in privacy|motion-detection|recording) sh /mnt/scripts/presence-mode.sh manual >/dev/null 2>&1 || true ;; esac
        fi
        echo "<pre>$(cat "$_start_out" 2>/dev/null)</pre>"
        rm -f "$_start_out"
        invalidate_allstates_cache
        ;;
      disable)
        mutation_guard
        if svc_switch "$script"; then svc_set "$script" 0; else rm "${AUTOSTART_DIR}/$script" 2>/dev/null || true; fi
        case "$script" in motion-detection|recording) sh /mnt/scripts/presence-mode.sh manual >/dev/null 2>&1 || true ;; esac
        invalidate_allstates_cache
        echo "Content-type: application/json"
        echo ""
        echo "{\"status\":\"ok\",\"autostart_enabled\":0}"
        ;;
      stop)
        mutation_guard
        echo "Content-type: text/html"
        echo ""
        status='unknown'
        echo "Stopping script '$script'..."
        echo "<pre>"
        if sh "$SCRIPT_HOME/$script" stop 2>&1; then
          echo "OK"
          case "$script" in privacy|motion-detection|recording) sh /mnt/scripts/presence-mode.sh manual >/dev/null 2>&1 || true ;; esac
        else
          echo "NOK"
        fi
        echo "</pre>"
        invalidate_allstates_cache
        ;;
      enable)
        mutation_guard
        if [ -e "$SCRIPT_HOME/$script" ]; then
          if svc_switch "$script"; then
            svc_set "$script" 1
          else
            mkdir -p "${AUTOSTART_DIR}"
            printf "#!/bin/sh\nsh \"%s%s\"\n" "$SCRIPT_HOME" "$script" > "${AUTOSTART_DIR}/$script"
            chmod +x "${AUTOSTART_DIR}/$script"
          fi
          case "$script" in motion-detection|recording) sh /mnt/scripts/presence-mode.sh manual >/dev/null 2>&1 || true ;; esac
          invalidate_allstates_cache
          echo "Content-type: application/json"
          echo ""
          echo "{\"status\":\"ok\",\"autostart_enabled\":1}"
        else
          echo "Content-type: application/json"
          echo ""
          echo "{\"status\":\"error\",\"reason\":\"script not found\"}"
        fi
        ;;
      view)
        # Full page (direct link / new tab). The source is HTML-escaped: a
        # script containing "<" used to be rendered as markup.
        echo "Content-type: text/html"
        echo ""
        echo "Contents of script '$script':"
        printf '<pre>'
        sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' "$SCRIPT_HOME/$script" 2>&1
        printf '</pre>\n'
        ;;
      source)
        # Plain text for the Services page dialog.
        echo "Content-type: text/plain; charset=utf-8"
        echo ""
        cat "$SCRIPT_HOME/$script" 2>&1
        ;;
      state)
        if [ ! -f "$SCRIPT_HOME/$script" ]; then
          echo "Content-type: application/json"
          echo ""
          echo "{\"status\":\"error\",\"reason\":\"script not found\"}"
        else
          state="unknown"
          running=0
          autostart_enabled=0
          uptime_s=-1

          parse_script_capabilities "$SCRIPT_HOME/$script"

          if boot_enabled "$script"; then
            autostart_enabled=1
          fi

          if [ "$has_status" -eq 1 ]; then
            status_output="$(run_status_probe "$SCRIPT_HOME/$script" 2)"
            status_rc=$?
            if [ "$status_rc" -eq 0 ]; then
              if [ -n "$status_output" ]; then
                state="running"
                running=1
                _svc_pid=0
                case "$status_output" in
                  *"PID: "[0-9]*) _tmp="${status_output#*PID: }"; _svc_pid="${_tmp%%[!0-9]*}" ;;
                esac
                case "$_svc_pid" in ''|0|*[!0-9]*) _svc_pid=0 ;; esac
                if [ "$_svc_pid" -gt 0 ]; then
                  _svc_pid_uptime "$_svc_pid"
                  uptime_s="$_svc_uptime_s"
                fi
              else
                state="stopped"
              fi
            elif [ "$status_rc" -eq 143 ] || [ "$status_rc" -eq 124 ]; then
              state="timeout"
            elif [ "$status_rc" -eq 1 ]; then
              state="stopped"   # status() returns 1 when not running (see allstates)
            elif [ "$status_rc" -eq 3 ]; then
              state="disabled"
            else
              state="error"
            fi
          fi

          echo "Content-type: application/json"
          echo ""
          printf '{"status":"ok","script":"%s","state":"%s","running":%s,"has_start":%s,"has_stop":%s,"has_status":%s,"autostart_enabled":%s,"uptime_s":%s}\n' \
            "$script" "$state" "$running" "$has_start" "$has_stop" "$has_status" "$autostart_enabled" "$uptime_s"
        fi
        ;;
      *)
        echo "Content-type: text/html"
        echo ""
        echo "<p>Unsupported command</p>"	# request values are not printed back (reflected script)
        ;;
    esac
  else
    echo "Content-type: text/html"
    echo ""
    echo "<p>Not a valid script.</p>"
  fi
else
  echo "Content-type: text/html"
  echo ""
  
  if [ ! -d "$SCRIPT_HOME" ]; then
    echo "<p>No scripts.cgi found in $SCRIPT_HOME</p>"
  else
    echo "<header class='page-head'><h1 class='page-title'>Services</h1></header>"
    # item 46: one card per theme in a grid that uses the width of the screen; each service a compact card: name,
    # state, CPU/RAM impact, Start/Stop, start at boot, source
    echo "<div class='services-overview'><strong id='services_summary'>Checking services...</strong><label><input id='services_issues_only' type='checkbox'> Problems only</label></div>"
    echo "<div id='services_error' class='message is-danger services-error' hidden><div class='message-body'><span id='services_error_text'></span> <button id='services_retry' class='button is-small' type='button'>Retry</button> <a class='button is-small onpage' href='javascript:void(0)' data-target='logs.html'>Open logs</a></div></div>"
    # Only the camera's own programs are listed here. Camera controls
    # (day/night, IR, LEDs) are under the live picture; features have their
    # on/off switch in their Settings tab (Detection, Recording, Integrations).
    # Any other script (added later) still shows, under "Other".
    echo "<div class='svc-grid'>"
    for _grp in core access integrations other; do
    case "$_grp" in
      core) _gt="Core: video, web and system" ;;
      access) _gt="Network and access" ;;
      integrations) _gt="Integrations" ;;
      *) _gt="Other" ;;
    esac
    _gopen=0
    for script_path in "$SCRIPT_HOME"/*; do
      [ -f "$script_path" ] || continue
      i="${script_path##*/}"
      if ! is_valid_script_name "$i"; then
        continue
      fi
      case " $SERVICES_HIDDEN " in *" $i "*) continue ;; esac
      case " $SERVICES_CORE " in *" $i "*) _in=core ;; *)
        case " $SERVICES_ACCESS " in *" $i "*) _in=access ;; *)
          case " $SERVICES_INTEGRATIONS " in *" $i "*) _in=integrations ;; *) _in=other ;; esac ;;
        esac ;;
      esac
      [ "$_in" = "$_grp" ] || continue
      if [ "$_gopen" = 0 ]; then
        _gopen=1
        echo "<section class='card status_card svc-group' data-group='$_grp'><header class='card-header'><p class='card-header-title'>$_gt</p></header><div class='card-content svc-list'>"
      fi

      script_id="$(printf '%s' "$i" | sed 's/[^A-Za-z0-9._-]/_/g')"
      autorun_checked=""
      if boot_enabled "$i"; then
        autorun_checked="checked='checked'"
      fi
      impact_level="$(service_impact_level_for "$i")"
      case "$i" in rtsp-h26x|web-server|memory-guard) essential="1" ;; *) essential="0" ;; esac
      impact_label="$(service_impact_label_for "$impact_level")"
      impact_hint="$(service_impact_hint_for "$i")"

      echo "<div class='svc-card' data-script-name='$i' data-essential='$essential' data-service-state='loading'>"
      echo "<div class='svc-head'><strong>$i</strong><span class='services-tag services-impact-tag impact-$impact_level' title='$impact_hint'>$impact_label</span></div>"
      echo "<span class='services-tag services-status-tag service-status is-unknown' data-service-status='loading' title='Loading service state...'>Loading...</span>"
      echo "<div class='svc-actions'>"
      echo "<button data-target='cgi-bin/scripts.cgi?cmd=start&script=$i' class='button is-small is-link script_action_toggle' data-script-name='$i' title='Start this service now.'>Start</button>"
      echo "<span class='services-autorun-cell'><input type='checkbox' id='autorun_$script_id' name='autorun_$script_id' class='switch is-rtl autostart' data-unchecked='cgi-bin/scripts.cgi?cmd=disable&script=$i' data-checked='cgi-bin/scripts.cgi?cmd=enable&script=$i' $autorun_checked title='Start this service when the camera boots'>"
      echo "<label for='autorun_$script_id' title='Start this service when the camera boots'>Boot</label></span>"
      echo "<a href='cgi-bin/scripts.cgi?cmd=view&script=$i' class='button is-small is-light view_script' data-script-name='$i' title='View this script source'>View</a>"
      echo "</div>"
      echo "</div>"
    done
    [ "$_gopen" = 1 ] && echo "</div></section>"
    done
    echo "</div>"
    echo "<div class='services-impact-legend'>"
    echo "<span class='services-tag services-impact-tag impact-min'>Min</span><span>Low impact</span>"
    echo "<span class='services-tag services-impact-tag impact-med'>Med</span><span>Moderate impact</span>"
    echo "<span class='services-tag services-impact-tag impact-heavy'>Heavy</span><span>High CPU/RAM usage when active</span>"
    echo "</div>"
    echo "<p class='help'>Boot switches add or remove the service's startup entry (${AUTOSTART_DIR}).</p>"
    echo "<p class='help'>Services that also have an on/off setting (recording, syslog-forward, memory-guard, whep, wifi-rescue, mqtt-bridge, telegram-bot) share one switch with their Settings tab: Stop turns that setting off for good, not only until the next start, and the Boot toggle is the same switch.</p>"
    echo "<p class='help'>Remote shell: ssh-server (SSH, encrypted) is on by default; telnet-server sends the password in clear, is off by default and stops by itself after a while.</p>"
  fi
  
  # Use bundled script to allow client caching and reduce server CPU
  echo "<script src=\"/scripts/scripts.bundle.min.js?v=3f36601f\"></script>"
fi
