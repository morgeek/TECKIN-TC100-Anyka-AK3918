#!/bin/sh
source ./func.cgi

# Ensure temp files are cleaned up on exit/interrupt
trap 'rm -f /tmp/scripts-status.$$.tmp /tmp/scripts-allstates.cache' EXIT INT TERM

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
        /mnt/bin/busybox timeout "$timeout_seconds" sh "$script_path" status >"$probe_output" 2>/dev/null
        probe_rc=$?
        ;;
      "/bin/busybox timeout")
        /bin/busybox timeout "$timeout_seconds" sh "$script_path" status >"$probe_output" 2>/dev/null
        probe_rc=$?
        ;;
      *)
        timeout "$timeout_seconds" sh "$script_path" status >"$probe_output" 2>/dev/null
        probe_rc=$?
        ;;
    esac
  else
    sh "$script_path" status >"$probe_output" 2>/dev/null &
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
  # Parse start/stop/status function presence using shell builtins to save forks
  while IFS= read -r line; do
    case "$line" in
      *"start()"*)  has_start=1 ;;
      *"stop()"*)   has_stop=1 ;;
      *"status()"*) has_status=1 ;;
    esac
  done < "$script_file"
}

service_impact_level_for() {
  case "$1" in
    rtsp-h26x|recording|motion-detection|timelapse)
      echo "heavy"
      ;;
    onvif|mqtt-bridge|motion-mail|motion-snapshot|telegram-bot|auto-night-detection|network-monitor)
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
    recording)
      echo "Video writing and rotation can be RAM and IO intensive."
      ;;
    motion-detection)
      echo "Continuous detection loop uses CPU while active."
      ;;
    timelapse)
      echo "Repeated capture and encoding over long periods."
      ;;
    onvif)
      echo "Adds network discovery and ONVIF control workload."
      ;;
    mqtt-bridge)
      echo "Low-to-medium network polling and publish workload."
      ;;
    motion-mail|motion-snapshot|telegram-bot)
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

generate_allstates_payload() {
  printf '{"status":"ok","services":['
  first=1
  for script_path in "$SCRIPT_HOME"/*; do
    [ -f "$script_path" ] || continue
    script="${script_path##*/}"
    if ! is_valid_script_name "$script"; then
      continue
    fi

    [ "$first" -eq 0 ] && printf ','
    first=0

    autostart_enabled=0
    running=0
    state="unknown"
    uptime_s=-1
    parse_script_capabilities "$script_path"

    [ -f "$AUTOSTART_DIR/$script" ] && autostart_enabled=1

    if [ "$has_status" -eq 1 ]; then
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
      else
        state="error"
      fi
    fi
    printf '{"script":"%s","state":"%s","running":%s,"has_start":%s,"has_stop":%s,"has_status":%s,"autostart_enabled":%s,"uptime_s":%s}' \
      "$script" "$state" "$running" "$has_start" "$has_stop" "$has_status" "$autostart_enabled" "$uptime_s"
  done
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
        csrf_guard
        echo "Content-type: text/html"
        echo ""

        echo "Running script '$script'..."
        echo "<pre>$(sh "$SCRIPT_HOME/$script" start 2>&1)</pre>"
        invalidate_allstates_cache
        ;;
      disable)
        csrf_guard
        rm "${AUTOSTART_DIR}/$script" 2>/dev/null || true
        invalidate_allstates_cache
        echo "Content-type: application/json"
        echo ""
        echo "{\"status\":\"ok\",\"autostart_enabled\":0}"
        ;;
      stop)
        csrf_guard
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
        csrf_guard
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
        echo "Content-type: text/html"
        echo ""
        echo "Contents of script '$script':"
        echo "<pre>$(cat "$SCRIPT_HOME/$script" 2>&1)</pre>"
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
      allstates)
        echo "Content-type: application/json"
        echo ""
        emit_allstates_response
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
    echo "<div class='card status_card services-table-card'>"
    echo "<header class='card-header'>"
    echo "<p class='card-header-title'>Services</p>"
    echo "<a class='card-header-icon onpage' href='javascript: void(0)' data-target='cgi-bin/camcontrols.cgi?cmd=getsettings' title='Choose which toggles appear in the Camera Controls dropdown'>Camera Controls</a>"
    echo "</header>"
    echo "<div class='card-content services-table-wrap'>"
    echo "<table class='table is-fullwidth is-hoverable services-table'>"
    echo "<thead><tr>"
    echo "<th title='Service name and current runtime state'>Title</th>"
    echo "<th title='Estimated runtime impact on CPU and RAM when this service is active'>Impact</th>"
    echo "<th title='Start, stop, or run this service now'>Start/Stop</th>"
    echo "<th title='Enable or disable automatic startup when the camera boots'>Autorun at boot</th>"
    echo "<th title='Open the script source in quick view'>View</th>"
    echo "</tr></thead>"
    echo "<tbody>"

    for script_path in "$SCRIPT_HOME"/*; do
      [ -f "$script_path" ] || continue
      i="${script_path##*/}"
      if ! is_valid_script_name "$i"; then
        continue
      fi

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
      impact_label="$(service_impact_label_for "$impact_level")"
      impact_hint="$(service_impact_hint_for "$i")"

      echo "<tr data-script-name='$i'>"
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
      echo "<a href='cgi-bin/scripts.cgi?cmd=view&script=$i' class='button is-small is-light view_script' title='View this script source'>View</a>"
      echo "</td>"
      echo "</tr>"
    done

    echo "</tbody>"
    echo "</table>"
    echo "</div>"
    echo "<div class='services-impact-legend'>"
    echo "<span class='services-tag services-impact-tag impact-min'>Min</span><span>Low impact</span>"
    echo "<span class='services-tag services-impact-tag impact-med'>Med</span><span>Moderate impact</span>"
    echo "<span class='services-tag services-impact-tag impact-heavy'>Heavy</span><span>High CPU/RAM usage when active</span>"
    echo "</div>"
    echo "<p class='help'>Autorun toggles create/remove per-service startup entries in ${AUTOSTART_DIR}.</p>"
    echo "</div>"
  fi
  
  # Prefer external bundled/minified scripts to reduce server CPU and allow client caching
  if [ -f /mnt/www/scripts/scripts.bundle.min.js ]; then
    echo "<script src=\"/scripts/scripts.bundle.min.js\"></script>"
  else
    echo "<script src=\"/scripts/scripts.cgi.js\"></script>"
  fi
fi
