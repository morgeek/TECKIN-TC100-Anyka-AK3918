#!/bin/sh
source ./func.cgi

echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"

SCRIPT_HOME="${SCRIPT_HOME:-/mnt/controlscripts/}"
# Allow tests to override autostart dir for safer testing
AUTOSTART_DIR="${AUTOSTART_DIR:-/mnt/config/autostart}"
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
    echo "<header class='card-header'><p class='card-header-title'>Services</p></header>"
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

      script_id="$(printf '%s' "$i" | tr -c 'A-Za-z0-9._-' '_')"
      has_start=0
      has_stop=0
      has_status=0
      status_output=""
      status_label="Unknown"
      status_class="is-unknown"

      if grep -q "^start()" "$SCRIPT_HOME/$i"; then
        has_start=1
      fi
      if grep -q "^stop()" "$SCRIPT_HOME/$i"; then
        has_stop=1
      fi
      if grep -q "^status()" "$SCRIPT_HOME/$i"; then
        has_status=1
      fi

      if [ "$has_status" -eq 1 ]; then
        status_output="$("$SCRIPT_HOME/$i" status)"
        status_rc=$?
        if [ "$status_rc" -eq 0 ]; then
          if [ -n "$status_output" ]; then
            status_label="Running"
            status_class="is-running"
          else
            status_label="Stopped"
            status_class="is-stopped"
          fi
        else
          status_label="Error"
          status_class="is-error"
        fi
      fi

      action_cmd="start"
      action_label="Run"
      action_class="is-link"
      action_hint="Run this script now."
      action_disabled=""

      if [ "$has_start" -eq 1 ]; then
        action_label="Start"
        action_hint="Start this service now."
        if [ "$status_class" = "is-running" ]; then
          if [ "$has_stop" -eq 1 ]; then
            action_cmd="stop"
            action_label="Stop"
            action_class="is-danger"
            action_hint="Stop this service now."
          else
            action_disabled="disabled"
            action_hint="This service is already running."
          fi
        fi
      elif [ "$has_stop" -eq 1 ] && [ "$status_class" = "is-running" ]; then
        action_cmd="stop"
        action_label="Stop"
        action_class="is-danger"
        action_hint="Stop this service now."
      fi

      autorun_checked=""
      if [ -f "$AUTOSTART_DIR/$i" ]; then
        autorun_checked="checked='checked'"
      fi

      echo "<tr>"
      echo "<td class='services-title-cell'>"
      echo "<strong>$i</strong>"
      echo "<span class='services-status-tag $status_class' title='Current state reported by this script'>$status_label</span>"
      echo "</td>"
      echo "<td>"
      echo "<button data-target='cgi-bin/scripts.cgi?cmd=$action_cmd&script=$i' class='button is-small $action_class script_action_toggle' data-script='$script_id' title='$action_hint' $action_disabled>$action_label</button>"
      echo "</td>"
      echo "<td class='services-autorun-cell'>"
      echo "<input type='checkbox' id='autorun_$script_id' name='autorun_$script_id' class='switch is-rtl autostart' data-script='$script_id' data-unchecked='cgi-bin/scripts.cgi?cmd=disable&script=$i' data-checked='cgi-bin/scripts.cgi?cmd=enable&script=$i' $autorun_checked title='Enable or disable autorun for this service'>"
      echo "<label for='autorun_$script_id' title='Enable or disable autorun for this service'>Boot</label>"
      echo "</td>"
      echo "<td>"
      echo "<a href='cgi-bin/scripts.cgi?cmd=view&script=$i' class='button is-small is-light view_script' data-script='$script_id' title='View this script source'>View</a>"
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
    script=$(cat /mnt/www/scripts/scripts.cgi.js)
    echo "<script>$script</script>"
  fi
fi
