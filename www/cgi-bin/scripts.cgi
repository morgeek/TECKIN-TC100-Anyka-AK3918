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
  
    for i in $SCRIPTS; do
      # Card - start
      echo "<div class='card script_card'>"
      # Header
      echo "<header class='card-header'><p class='card-header-title'>"
      # echo "<div class='card-content'>"
      if [ -x "$SCRIPT_HOME/$i" ]; then
        if grep -q "^status()" "$SCRIPT_HOME/$i"; then
          status=$("$SCRIPT_HOME/$i" status)
          if [ $? -eq 0 ]; then
            if [ -n "$status" ]; then
              badge="";
            else 
              badge="is-badge-warning";
            fi
          else
            badge="is-badge-danger"
            status="NOK"
          fi
          echo "<span class='badge $badge' data-badge='$status'>$i</span>"
        else
          echo "$i"
        fi
        # echo "</div>"
        echo "</p></header>"
  
        # Footer
        echo "<footer class='card-footer'>"
        echo "<span class='card-footer-item'>"
  
        # Start / Stop / Run buttons
        echo "<div class='buttons'>"
        if grep -q "^start()" "$SCRIPT_HOME/$i"; then
          echo "<button data-target='cgi-bin/scripts.cgi?cmd=start&script=$i' class='button is-link script_action_start' data-script='$i' "
          if [ ! -z "$status" ]; then
            echo "disabled"
          fi
          echo ">Start</button>"
        else
          echo "<button data-target='cgi-bin/scripts.cgi?cmd=start&script=$i' class='button is-link script_action_start' data-script='$i' "
          echo ">Run</button>"
        fi
  
        if grep -q "^stop()" "$SCRIPT_HOME/$i"; then
          echo "<button data-target='cgi-bin/scripts.cgi?cmd=stop&script=$i' class='button is-danger script_action_stop' data-script='$i' "
          if [ ! -n "$status" ]; then
            echo "disabled"
          fi
          echo ">Stop</button>"
        fi
        echo "</div>"
        echo "</span>"
  
        # Autostart Switch
        echo "<span class='card-footer-item'>"
        echo "<input type='checkbox' id='autorun_$i' name='autorun_$i' class='switch is-rtl autostart' data-script='$i' "
          echo " data-unchecked='cgi-bin/scripts.cgi?cmd=disable&script=$i'"
          echo " data-checked='cgi-bin/scripts.cgi?cmd=enable&script=$i'"
        if [ -f "/mnt/config/autostart/$i" ]; then
          echo " checked='checked'"
        fi
        echo "'>"
        echo "<label for='autorun_$i'>Autorun</label>"
        echo "</span>"
  
        # View link
        echo "<a href='cgi-bin/scripts.cgi?cmd=view&script=$i' class='card-footer-item view_script' data-script="$i">View</a>"
        echo "</footer>"
      fi
      # Card - End
      echo "</div>"
    done
  fi
  
  # Prefer external bundled/minified scripts to reduce server CPU and allow client caching
  if [ -f /mnt/www/scripts/scripts.bundle.min.js ]; then
    echo "<script src=\"/scripts/scripts.bundle.min.js\"></script>"
  else
    script=$(cat /mnt/www/scripts/scripts.cgi.js)
    echo "<script>$script</script>"
  fi
fi
