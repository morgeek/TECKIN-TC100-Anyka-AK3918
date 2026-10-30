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
  rm -f "$ALLSTATES_CACHE_FILE" >/dev/null 2>&1 || true
}

allstates_cache_is_fresh() {
  [ "$ALLSTATES_CACHE_TTL_SECONDS" -gt 0 ] || return 1
  [ -f "$ALLSTATES_CACHE_FILE" ] || return 1

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
SERVICES_SYSTEM="rtsp-h26x web-server mqtt-bridge network-monitor memory-guard health-snapshot button-actions ftp-server telnet-server ssh-server syslog-forward onvif wifi-rescue"
FAST_PIDFILE_SERVICES=" button-actions ftp-server health-snapshot mqtt-bridge network-monitor onvif rtsp-h26x sound-detection ssh-server syslog-forward telegram-bot telnet-server memory-guard wifi-rescue "

# port_listening PORT (same as common_functions.sh) -> 0 if a TCP socket is in LISTEN state on PORT
# (/proc/net/tcp, no fork). A pid that is alive is not enough: a recycled PID
# or a half-dead tcpsvd showed services as running with their port closed.
port_listening() {
  case "$1" in ''|*[!0-9]*) return 1 ;; esac
  _pl_hex="$(printf '%04X' "$1")"
  for _pl_f in /proc/net/tcp /proc/net/tcp6; do
    [ -r "$_pl_f" ] || continue
    while read -r _pl_sl _pl_local _pl_rem _pl_st _pl_rest; do
      [ "$_pl_st" = 0A ] || continue
      case "$_pl_local" in *":$_pl_hex") return 0 ;; esac
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
        _ft_pid="$(read_first /var/run/v4l2rtspserver.pid)"
        case "$_ft_pid" in ''|*[!0-9]*) ;; *) [ -d "/proc/$_ft_pid" ] && _ft_on=1 ;; esac ;;
      esac ;;
    web-server)
      for _ft_p in /proc/[0-9]*; do
        [ -r "$_ft_p/stat" ] || continue
        read -r _ft_stat 2>/dev/null < "$_ft_p/stat" || continue
        case "$_ft_stat" in *"(lighttpd)"*|*"(httpd)"*|*"(httpfront)"*) _ft_on=1; _ft_pid="${_ft_p#/proc/}"; break ;; esac
      done ;;
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
    onvif|mqtt-bridge|telegram-bot|auto-night-detection|network-monitor)
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
    auto-night-detection|network-monitor)
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

    [ -f "$AUTOSTART_DIR/$script" ] && autostart_enabled=1

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

emit_allstates_response() {
  if allstates_cache_is_fresh; then
    sed '1d' "$ALLSTATES_CACHE_FILE"
    return
  fi

  if [ "$ALLSTATES_CACHE_TTL_SECONDS" -gt 0 ]; then
    tmp_cache="/tmp/scripts-allstates.$$.tmp"
    now_ts="$(now_epoch_safe)"
    {
      printf 'ts=%s\n' "$now_ts"
      generate_allstates_payload
    } > "$tmp_cache"
    mv "$tmp_cache" "$ALLSTATES_CACHE_FILE" 2>/dev/null || true
    if [ -f "$ALLSTATES_CACHE_FILE" ]; then
      sed '1d' "$ALLSTATES_CACHE_FILE"
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
        echo "<pre>$(cat "$_start_out" 2>/dev/null)</pre>"
        rm -f "$_start_out"
        invalidate_allstates_cache
        ;;
      disable)
        mutation_guard
        rm "${AUTOSTART_DIR}/$script" 2>/dev/null || true
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
        sh "$SCRIPT_HOME/$script" stop 2>&1 && echo "OK" || echo "NOK"
        echo "</pre>"
        invalidate_allstates_cache
        ;;
      enable)
        mutation_guard
        if [ -e "$SCRIPT_HOME/$script" ]; then
          mkdir -p "${AUTOSTART_DIR}"
          printf "#!/bin/sh\nsh \"%s%s\"\n" "$SCRIPT_HOME" "$script" > "${AUTOSTART_DIR}/$script"
          chmod +x "${AUTOSTART_DIR}/$script"
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

          if [ -f "$AUTOSTART_DIR/$script" ]; then
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
        echo "<p>Unsupported command '$F_cmd'</p>"
        ;;
    esac
  else
    echo "Content-type: text/html"
    echo ""
    echo "<p>$F_script is not a valid script!</p>"
  fi
else
  echo "Content-type: text/html"
  echo ""
  
  if [ ! -d "$SCRIPT_HOME" ]; then
    echo "<p>No scripts.cgi found in $SCRIPT_HOME</p>"
  else
    echo "<header class='page-head'><h1 class='page-title'>Services</h1></header>"
    echo "<div class='card status_card services-table-card'>"
    echo "<header class='card-header'>"
    echo "<p class='card-header-title'>Services</p>"
    echo "</header>"
    echo "<div class='card-content'>"
    echo "<div class='services-overview'><strong id='services_summary'>Checking services...</strong><label><input id='services_issues_only' type='checkbox'> Problems only</label></div>"
    echo "<div id='services_error' class='message is-danger services-error' hidden><div class='message-body'><span id='services_error_text'></span> <button id='services_retry' class='button is-small' type='button'>Retry</button> <a class='button is-small onpage' href='javascript:void(0)' data-target='logs.html'>Open logs</a></div></div>"
    echo "<div class='services-table-wrap'>"
    echo "<table class='table is-fullwidth is-hoverable services-table'>"
    echo "<thead><tr>"
    echo "<th title='Service name and current runtime state'>Title</th>"
    echo "<th title='Estimated runtime impact on CPU and RAM when this service is active'>Impact</th>"
    echo "<th title='Start, stop, or run this service now'>Start/Stop</th>"
    echo "<th title='Enable or disable automatic startup when the camera boots'>Autorun at boot</th>"
    echo "<th title='Open the script source in a new tab'>View</th>"
    echo "</tr></thead>"
    # Only the camera's own programs are listed here. Camera controls
    # (day/night, IR, LEDs) are under the live picture; features have their
    # on/off switch in their Settings tab (Detection, Recording, Integrations);
    # the ONVIF server and the SD-card ffmpeg recorder are not used (local
    # recording is native), the rescue access point is on hold. Any other
    # script (added later) still shows, under "Other".
    for _grp in system features; do
    if [ "$_grp" = system ]; then
      echo "<tbody data-group='system'><tr class='services-group-row'><th colspan='5'>System programs</th></tr>"
    else
      echo "<tbody data-group='features'><tr class='services-group-row'><th colspan='5'>Other</th></tr>"
    fi
    for script_path in "$SCRIPT_HOME"/*; do
      [ -f "$script_path" ] || continue
      i="${script_path##*/}"
      if ! is_valid_script_name "$i"; then
        continue
      fi
      case " $SERVICES_HIDDEN " in *" $i "*) continue ;; esac
      case " $SERVICES_SYSTEM " in *" $i "*) _in=system ;; *) _in=features ;; esac
      [ "$_in" = "$_grp" ] || continue

      script_id="$(printf '%s' "$i" | sed 's/[^A-Za-z0-9._-]/_/g')"
      status_label="Loading..."
      status_class="is-unknown"
      action_cmd="start"
      action_label="Start"
      action_class="is-link"
      action_hint="Start this service now."
      action_disabled=""

      autorun_checked=""
      if [ -f "$AUTOSTART_DIR/$i" ]; then
        autorun_checked="checked='checked'"
      fi
      impact_level="$(service_impact_level_for "$i")"
      case "$i" in rtsp-h26x|web-server|network-monitor|memory-guard) essential="1" ;; *) essential="0" ;; esac
      impact_label="$(service_impact_label_for "$impact_level")"
      impact_hint="$(service_impact_hint_for "$i")"

      echo "<tr data-script-name='$i' data-essential='$essential' data-service-state='loading'>"
      echo "<td class='services-title-cell'>"
      echo "<strong>$i</strong>"
      echo "<span class='services-tag services-status-tag service-status $status_class' data-service-status='loading' title='Loading service state...'>$status_label</span>"
      echo "</td>"
      echo "<td class='services-impact-cell'>"
      echo "<span class='services-tag services-impact-tag impact-$impact_level' title='$impact_hint'>$impact_label</span>"
      echo "</td>"
      echo "<td>"
      echo "<button data-target='cgi-bin/scripts.cgi?cmd=$action_cmd&script=$i' class='button is-small $action_class script_action_toggle' data-script-name='$i' title='$action_hint' $action_disabled>$action_label</button>"
      echo "</td>"
      echo "<td class='services-autorun-cell'>"
      echo "<input type='checkbox' id='autorun_$script_id' name='autorun_$script_id' class='switch is-rtl autostart' data-unchecked='cgi-bin/scripts.cgi?cmd=disable&script=$i' data-checked='cgi-bin/scripts.cgi?cmd=enable&script=$i' $autorun_checked title='Enable or disable autorun for this service'>"
      echo "<label for='autorun_$script_id' title='Enable or disable autorun for this service'>Boot</label>"
      echo "</td>"
      echo "<td>"
      echo "<a href='cgi-bin/scripts.cgi?cmd=view&script=$i' class='button is-small is-light view_script' data-script-name='$i' title='View this script source'>View</a>"
      echo "</td>"
      echo "</tr>"
    done
    echo "</tbody>"
    done

    echo "</table>"
    echo "</div>"
    echo "</div>"
    echo "<div class='services-impact-legend'>"
    echo "<span class='services-tag services-impact-tag impact-min'>Min</span><span>Low impact</span>"
    echo "<span class='services-tag services-impact-tag impact-med'>Med</span><span>Moderate impact</span>"
    echo "<span class='services-tag services-impact-tag impact-heavy'>Heavy</span><span>High CPU/RAM usage when active</span>"
    echo "</div>"
    echo "<p class='help'>Autorun toggles create/remove per-service startup entries in ${AUTOSTART_DIR}.</p>"
    echo "<p class='help'>Remote shell: ssh-server (SSH, encrypted) is on by default; telnet-server sends the password in clear, is off by default and stops by itself after a while.</p>"
    echo "</div>"
  fi
  
  # Use bundled script to allow client caching and reduce server CPU
  echo "<script src=\"/scripts/scripts.bundle.min.js?v=1.8.4-ui2\"></script>"
fi
