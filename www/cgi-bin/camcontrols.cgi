#!/bin/sh

. /mnt/www/cgi-bin/func.cgi

export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'
SCRIPT_HOME="${SCRIPT_HOME:-/mnt/controlscripts}"

# Validate that a controlscript name contains only safe characters (no path traversal)
validate_control_id() {
  case "$1" in
    ''|*[!A-Za-z0-9._-]*|..*|.) return 1 ;;
  esac
  return 0
}

# CSRF check before headers for state-changing commands
case "${F_cmd:-}" in
  setsettings|on|off|set|mode) mutation_guard ;;
esac

# --- Camera controls panel on the main page (JSON) ---------------------------
#   GET  ?cmd=panel                       state of every control
#   POST ?cmd=set&control=<id>&on=0|1     one control (ir-led, ir-cut,
#                                         black-white, front-led, red-led)
#   POST ?cmd=mode&value=auto|day|night   day/night mode
# The state is read from the same files as the controlscripts' status()
# (sysfs, /var/run), without running them; only "auto" needs setconf.
PANEL_RUN="${PANEL_RUN:-/var/run}"
PANEL_SYS="${PANEL_SYS:-/sys}"
PANEL_SETCONF="${PANEL_SETCONF:-/mnt/bin/setconf}"
_panel_first() { _pf=""; [ -r "$1" ] && read -r _pf _pr < "$1" 2>/dev/null; printf '%s' "$_pf"; }
panel_json() {
  # 2.x vendor nodes first, then the Linux 6.6 LED names of the device tree (ir, blue, red)
  _irled=0; { [ "$(_panel_first "$PANEL_SYS/user-gpio/ir-led")" = 1 ] || [ "$(_panel_first "$PANEL_SYS/class/leds/ir/brightness")" = 1 ]; } && _irled=1
  _ircut=0; [ "$(_panel_first "$PANEL_RUN/ircut")" = 1 ] && _ircut=1
  _bw=0;    [ "$(_panel_first "$PANEL_RUN/vday")" = 0 ] && _bw=1
  _blue=0;  { [ "$(_panel_first "$PANEL_SYS/class/leds/blue_led/brightness")" = 1 ] || [ "$(_panel_first "$PANEL_SYS/class/leds/blue/brightness")" = 1 ]; } && _blue=1
  _red=0;   { [ "$(_panel_first "$PANEL_SYS/class/leds/red_led/brightness")" = 1 ] || [ "$(_panel_first "$PANEL_SYS/class/leds/red/brightness")" = 1 ]; } && _red=1
  if [ "$("$PANEL_SETCONF" -g n 2>/dev/null)" = 2 ]; then _mode=auto
  elif [ "$_irled$_ircut$_bw" = 101 ]; then _mode=night
  elif [ "$_irled$_ircut$_bw" = 010 ]; then _mode=day
  else _mode=custom; fi
  printf '{"ok":true,"mode":"%s","ir-led":%s,"ir-cut":%s,"black-white":%s,"front-led":%s,"red-led":%s}\n' \
    "$_mode" "$_irled" "$_ircut" "$_bw" "$_blue" "$_red"
}
case "${F_cmd:-}" in
  panel|set|mode)
    printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n'
    case "$F_cmd" in
      set)
        case "$F_control" in ir-led|ir-cut|black-white|front-led|red-led) ;; *)
          echo '{"ok":false,"error":"unknown control"}'; exit 0 ;;
        esac
        case "$F_on" in 1) _act=start ;; 0) _act=stop ;; *) echo '{"ok":false,"error":"on must be 0 or 1"}'; exit 0 ;; esac
        sh "$SCRIPT_HOME/$F_control" "$_act" </dev/null >/dev/null 2>&1 ;;
      mode)
        case "$F_value" in
          auto)  sh "$SCRIPT_HOME/auto-night-detection" start </dev/null >/dev/null 2>&1 ;;
          day)   sh "$SCRIPT_HOME/night-mode" stop </dev/null >/dev/null 2>&1 ;;
          night) sh "$SCRIPT_HOME/night-mode" start </dev/null >/dev/null 2>&1 ;;
          *) echo '{"ok":false,"error":"mode must be auto, day or night"}'; exit 0 ;;
        esac ;;
    esac
    rm -f /tmp/scripts-allstates.cache 2>/dev/null
    panel_json
    exit 0 ;;
esac

. /mnt/scripts/common_functions.sh
# Allow tests to override config locations via environment for safer testing
ENABLED_CONTROLS_CONFIG="${ENABLED_CONTROLS_CONFIG:-/mnt/config/webcontrols.conf}"

install_config $ENABLED_CONTROLS_CONFIG

containsElement()
{
  for controlId in $2
  do
    if [ "$1" = "$controlId" ]; then
      return 0
    fi
  done

  return 1
}

urldecode() 
{
    local url_encoded="${1//+/ }"
    printf '%b' "${url_encoded//%/\\x}"
}

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

if [ -n "$F_cmd" ]; then
  case "$F_cmd" in
    getsettings)
      # Read enabled controls from config
      . "$ENABLED_CONTROLS_CONFIG" 2> /dev/null

      # Use bundled script to allow client caching and reduce server CPU
      echo "<script src=\"/scripts/camcontrols.bundle.min.js\"></script>"

      echo "<div class='card status_card'> \
           <header class='card-header'><p class='card-header-title'>Enabled Camera Controls</p></header> \
           <div class='card-content'>"

      for filename in $SCRIPT_HOME/*; do
        [ -e "$filename" ] || continue
        controlId="$(basename $filename)"
        if grep -q "^status()" "$filename"; then
          controlName="$(grep SERVICE_NAME= $filename|sed 's/SERVICE_NAME=\|;//g'|sed 's/"//g')"
          if [ -z "$controlName" ]; then
            controlName="$controlId"
          fi
          switchId=camcontrol_$controlId
          echo "<div class='field is-horizontal'> \
                <div class='field'> \
                <input class='switch' name='$switchId' id='$switchId' type='checkbox' $(if containsElement "$controlId" "${ENABLED_CAM_CONTROL_SWITCHES}"; then echo "checked='checked'"; fi)> \
                <label for='$switchId'>$controlName</label> \
                </div> \
                </div>"
        fi
      done

      echo "<div class='field is-horizontal'> \
            <div class='field'> \
            <button id='saveCamControlsBtn' onclick='saveCamControls()' class='button is-primary' type='button'>Save</button> \
            </div> \
            </div> \
            </div> \
            </div>"
    ;;

    setsettings)
      # Safely write config as a single-quoted value to avoid command execution when sourced
      val="$(urldecode "${F_controls}")"
      # Escape single quotes for safe single-quoted assignment
      esc_val="$(printf "%s" "$val" | sed "s/'/'\\''/g")"
      printf "ENABLED_CAM_CONTROL_SWITCHES='%s'\n" "$esc_val" > "$ENABLED_CONTROLS_CONFIG"
    ;;

    getcontrols)
      # Read enabled controls from config
      . "$ENABLED_CONTROLS_CONFIG" 2> /dev/null
      echo "["
      sep=""
      for controlId in $ENABLED_CAM_CONTROL_SWITCHES
      do
        controlName="$(grep SERVICE_NAME= $SCRIPT_HOME/$controlId|sed 's/SERVICE_NAME=\|;//g'|sed 's/"//g')"
        if [ -z "$controlName" ]; then
          controlName="$controlId"
        fi
        printf '%s{"id":"%s","name":"%s"}\n' "$sep" "$controlId" "$controlName"
        sep=","
      done
      echo "]"
    ;;

    on)
      script="${F_control##*/}"
      if validate_control_id "$script" && [ -f "$SCRIPT_HOME/$script" ]; then
        sh "$SCRIPT_HOME/$script" start > /dev/null 2>&1
      fi
    ;;

    off)
      script="${F_control##*/}"
      if validate_control_id "$script" && [ -f "$SCRIPT_HOME/$script" ]; then
        sh "$SCRIPT_HOME/$script" stop > /dev/null 2>&1
      fi
    ;;

    getallstate)
      # Read enabled controls from config
      . "$ENABLED_CONTROLS_CONFIG" 2> /dev/null
      echo "["
      sep=""
      for controlId in $ENABLED_CAM_CONTROL_SWITCHES
      do
        state="OFF"
        if [ -f "$SCRIPT_HOME/$controlId" ]; then
          status="$(sh "$SCRIPT_HOME/$controlId" status 2>/dev/null)"
        else
          status=""
        fi
        if [ -n "$status" ]; then
          state="ON"
        fi
        printf '%s{"id":"%s","status":"%s"}\n' "$sep" "$controlId" "$state"
        sep=","
      done
      echo "]"
    ;;

    getstate)
      script="${F_control##*/}"
      if validate_control_id "$script" && [ -f "$SCRIPT_HOME/$script" ]; then
        status="$(sh "$SCRIPT_HOME/$script" status 2>/dev/null)"
      else
        status=""
      fi
      if [ -n "$status" ]; then
        echo "ON"
      else
        echo "OFF"
      fi
    ;;

    *)
      echo "Unsupported command '$F_cmd'"
   ;;
  esac
fi
