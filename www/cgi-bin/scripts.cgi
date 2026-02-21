#!/bin/sh
source ./func.cgi

echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"

SCRIPT_HOME="${SCRIPT_HOME:-/mnt/controlscripts/}"
# Allow tests to override autostart dir for safer testing
AUTOSTART_DIR="${AUTOSTART_DIR:-/mnt/config/autostart}"

run_status_probe() {
  script_path="$1"
  timeout_seconds="${2:-2}"
  probe_output="/tmp/scripts-status.$$.tmp"

  "$script_path" status >"$probe_output" 2>/dev/null &
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

if [ -n "$F_script" ]; then
  script="${F_script##*/}"
  if [ -e "$SCRIPT_HOME/$script" ]; then
    case "$F_cmd" in
      start)
        echo "Content-type: text/html"
        echo ""

        echo "Running script '$script'..."
        echo "<pre>$("$SCRIPT_HOME/$script" 2>&1)</pre>"
        ;;  
      disable)
        # sanitize script name
        script="${script##*/}"
        case "$script" in
          ''|*[!A-Za-z0-9._-]* )
            echo "Content-type: application/json"
            echo ""
            echo "{\"status\": \"error\", \"reason\": \"invalid script name\"}"
            ;;
          *)
            rm "${AUTOSTART_DIR}/$script" 2>/dev/null || true
            echo "Content-type: application/json"
            echo ""
            echo "{\"status\": \"ok\"}"
            ;;
        esac
        ;;
      stop)
        echo "Content-type: text/html"
        echo ""
        status='unknown'
        echo "Stopping script '$script'..."
        echo "<pre>"
        "$SCRIPT_HOME/$script" stop 2>&1 && echo "OK" || echo "NOK"
        echo "</pre>"
        ;;
      enable)
        # sanitize script name and ensure service exists
        script="${script##*/}"
        case "$script" in
          ''|*[!A-Za-z0-9._-]* )
            echo "Content-type: application/json"
            echo ""
            echo "{\"status\": \"error\", \"reason\": \"invalid script name\"}"
            ;;
          *)
            if [ -e "$SCRIPT_HOME/$script" ]; then
              mkdir -p "${AUTOSTART_DIR}"
              printf "#!/bin/sh\n%s%s\n" "$SCRIPT_HOME" "$script" > "${AUTOSTART_DIR}/$script"
              chmod +x "${AUTOSTART_DIR}/$script"
              echo "Content-type: application/json"
              echo ""
              echo "{\"status\": \"ok\"}"
            else
              echo "Content-type: application/json"
              echo ""
              echo "{\"status\": \"error\", \"reason\": \"script not found\"}"
            fi
            ;;
        esac
        ;;
      view)
        echo "Content-type: text/html"
        echo ""
        echo "Contents of script '$script':"
        echo "<pre>$(cat "$SCRIPT_HOME/$script" 2>&1)</pre>"
        ;;
      state)
        # sanitize script name
        script="${script##*/}"
        case "$script" in
          ''|*[!A-Za-z0-9._-]* )
            echo "Content-type: application/json"
            echo ""
            echo "{\"status\": \"error\", \"reason\": \"invalid script name\"}"
            ;;
          *)
            if [ ! -x "$SCRIPT_HOME/$script" ]; then
              echo "Content-type: application/json"
              echo ""
              echo "{\"status\": \"error\", \"reason\": \"script not found\"}"
            else
              has_start=0
              has_stop=0
              has_status=0
              state="unknown"
              running=0

              if grep -q "^start()" "$SCRIPT_HOME/$script"; then
                has_start=1
              fi
              if grep -q "^stop()" "$SCRIPT_HOME/$script"; then
                has_stop=1
              fi
              if grep -q "^status()" "$SCRIPT_HOME/$script"; then
                has_status=1
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
              printf '{"status":"ok","script":"%s","state":"%s","running":%s,"has_start":%s,"has_stop":%s}\n' \
                "$script" "$state" "$running" "$has_start" "$has_stop"
            fi
            ;;
        esac
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
    echo "<th title='Start, stop, or run this service now'>Start/Stop</th>"
    echo "<th title='Enable or disable automatic startup when the camera boots'>Autorun at boot</th>"
    echo "<th title='Open the script source in quick view'>View</th>"
    echo "</tr></thead>"
    echo "<tbody>"

    for i in $SCRIPTS; do
      [ -x "$SCRIPT_HOME/$i" ] || continue
      case "$i" in
        ''|*[!A-Za-z0-9._-]* ) continue ;;
      esac

      script_id="$(printf '%s' "$i" | tr -c 'A-Za-z0-9._-' '_')"
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

      echo "<tr data-script-name='$i'>"
      echo "<td class='services-title-cell'>"
      echo "<strong>$i</strong>"
      echo "<span class='services-status-tag service-status $status_class' data-service-status='loading' title='Loading service state...'>$status_label</span>"
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
    echo "</div>"
  fi
  
  # Prefer external bundled/minified scripts to reduce server CPU and allow client caching
  if [ -f /mnt/www/scripts/scripts.bundle.min.js ]; then
    echo "<script src=\"/scripts/scripts.bundle.min.js\"></script>"
  else
    echo "<script src=\"/scripts/scripts.cgi.js\"></script>"
  fi
fi
