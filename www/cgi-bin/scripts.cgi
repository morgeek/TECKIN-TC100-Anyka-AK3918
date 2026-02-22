#!/bin/sh
source ./func.cgi

echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"

SCRIPT_HOME="${SCRIPT_HOME:-/mnt/controlscripts/}"
# Allow tests to override autostart dir for safer testing
AUTOSTART_DIR="${AUTOSTART_DIR:-/mnt/config/autostart}"

is_valid_script_name() {
  case "$1" in
    ''|*[!A-Za-z0-9._-]* ) return 1 ;;
    *) return 0 ;;
  esac
}

run_status_probe() {
  script_path="$1"
  timeout_seconds="${2:-2}"
  probe_output="/tmp/scripts-status.$$.tmp"

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

  if [ -f "$probe_output" ]; then
    cat "$probe_output"
    rm -f "$probe_output"
  fi

  if [ "$probe_rc" -ge 128 ]; then
    return 124
  fi
  return "$probe_rc"
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
        echo "Content-type: text/html"
        echo ""

        echo "Running script '$script'..."
        echo "<pre>$(sh "$SCRIPT_HOME/$script" start 2>&1)</pre>"
        ;;  
      disable)
        rm "${AUTOSTART_DIR}/$script" 2>/dev/null || true
        echo "Content-type: application/json"
        echo ""
        echo "{\"status\":\"ok\",\"autostart_enabled\":0}"
        ;;
      stop)
        echo "Content-type: text/html"
        echo ""
        status='unknown'
        echo "Stopping script '$script'..."
        echo "<pre>"
        sh "$SCRIPT_HOME/$script" stop 2>&1 && echo "OK" || echo "NOK"
        echo "</pre>"
        ;;
      enable)
        if [ -e "$SCRIPT_HOME/$script" ]; then
          mkdir -p "${AUTOSTART_DIR}"
          printf "#!/bin/sh\nsh \"%s%s\"\n" "$SCRIPT_HOME" "$script" > "${AUTOSTART_DIR}/$script"
          chmod +x "${AUTOSTART_DIR}/$script"
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
          has_start=0
          has_stop=0
          has_status=0
          state="unknown"
          running=0
          autostart_enabled=0

          # Parse start/stop/status function presence in one pass to keep
          # state polling lightweight when the Services page checks each row.
          function_flags="$(awk '
            BEGIN { s=0; t=0; u=0 }
            /^[[:space:]]*start[[:space:]]*\(\)/  { s=1 }
            /^[[:space:]]*stop[[:space:]]*\(\)/   { t=1 }
            /^[[:space:]]*status[[:space:]]*\(\)/ { u=1 }
            END { printf "%s %s %s", s, t, u }
          ' "$SCRIPT_HOME/$script" 2>/dev/null)"
          has_start=0
          has_stop=0
          has_status=0
          if [ -n "$function_flags" ]; then
            IFS=' ' read -r has_start has_stop has_status <<EOF
$function_flags
EOF
          fi

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
          printf '{"status":"ok","script":"%s","state":"%s","running":%s,"has_start":%s,"has_stop":%s,"has_status":%s,"autostart_enabled":%s}\n' \
            "$script" "$state" "$running" "$has_start" "$has_stop" "$has_status" "$autostart_enabled"
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
    SCRIPTS=$(ls -A "$SCRIPT_HOME")
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

    for i in $SCRIPTS; do
      [ -f "$SCRIPT_HOME/$i" ] || continue
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
