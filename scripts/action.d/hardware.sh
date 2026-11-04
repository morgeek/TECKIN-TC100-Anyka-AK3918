# shellcheck shell=sh
# action.cgi commands: LEDs, IR, day/night.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    hw_state)
      # What the Hardware page (www/hardware.html) shows, read live: the two LEDs, the IR LEDs, the IR-cut filter
      # (1 = in, day), the automatic day/night, the microphone level (only while the sound detection writes it) and
      # the reset button (GPIO 522, 0 = pressed). Read-only, no CSRF; null when the camera cannot tell.
      _hs_bool() { case "$1" in 0) printf false ;; ''|*[!0-9]*) printf null ;; *) printf true ;; esac; }
      _hs_led() { _v=""; read -r _v < "/sys/class/leds/$1/brightness" 2>/dev/null || read -r _v < "/sys/class/leds/${1%_led}/brightness" 2>/dev/null; _hs_bool "$_v"; }
      _hs_ir=""; read -r _hs_ir < /sys/class/leds/ir/brightness 2>/dev/null
      _hs_cut=""; read -r _hs_cut < /var/run/ircut 2>/dev/null
      case "$_hs_cut" in 0|1) ;; *) _hs_cut=null ;; esac
      _hs_auto=false
      [ -f /var/run/auto-night-detection.pid ] && kill -0 "$(cat /var/run/auto-night-detection.pid 2>/dev/null)" 2>/dev/null && _hs_auto=true
      _hs_db=null
      if [ -r /var/run/sound_level ]; then
        _hs_t=""; _hs_r=""; read -r _hs_t _hs_r _hs_rest < /var/run/sound_level
        _hs_now=$(date +%s 2>/dev/null)
        case "$_hs_t" in ''|*[!0-9]*) ;; *)
          [ $((_hs_now - _hs_t)) -le 10 ] && case "$_hs_r" in -[0-9]*|0) _hs_db="$_hs_r" ;; esac ;;
        esac
      fi
      _hs_btn=null
      if [ -r /sys/class/gpio/gpio522/value ]; then
        _hs_b=""; read -r _hs_b < /sys/class/gpio/gpio522/value
        case "$_hs_b" in 0) _hs_btn=true ;; 1) _hs_btn=false ;; esac
      fi
      printf '{"ok":true,"front_led":%s,"red_led":%s,"ir_led":%s,"ir_cut":%s,"auto_daynight":%s,"sound_db":%s,"button":%s}\n' \
        "$(_hs_led blue_led)" "$(_hs_led red_led)" "$(_hs_bool "$_hs_ir")" "$_hs_cut" "$_hs_auto" "$_hs_db" "$_hs_btn"
    ;;

    front_led_on)
      front_led on
      if wants_json_response; then
        json_body_ok "Front LED turned on"
      fi
    ;;

    front_led_off)
      front_led off
      if wants_json_response; then
        json_body_ok "Front LED turned off"
      fi
    ;;

    red_led_on)
      red_led on
      if wants_json_response; then
        json_body_ok "Red LED turned on"
      fi
    ;;

    red_led_off)
      red_led off
      if wants_json_response; then
        json_body_ok "Red LED turned off"
      fi
    ;;

    ir_led_on)
      ir_led on
      if wants_json_response; then
        json_body_ok "IR LED turned on"
      fi
    ;;

    ir_led_off)
      ir_led off
      if wants_json_response; then
        json_body_ok "IR LED turned off"
      fi
    ;;

    ir_cut_on)
      ir_cut on
      if wants_json_response; then
        json_body_ok "IR cut filter enabled"
      fi
    ;;

    ir_cut_off)
      ir_cut off
      if wants_json_response; then
        json_body_ok "IR cut filter disabled"
      fi
    ;;

    auto_night_mode_start)
      /mnt/controlscripts/auto-night-detection start
    ;;

    auto_night_mode_stop)
      /mnt/controlscripts/auto-night-detection stop
    ;;

    night-mode-on)
      /mnt/controlscripts/night-mode start
    ;;

    night-mode-off)
      /mnt/controlscripts/night-mode stop
    ;;
    
    set_led_config)
      install_config /mnt/config/boot.conf
      led_front=$(normalize_bool "${F_led_front}")
      led_red=$(normalize_bool "${F_led_red}")
      
      rewrite_config /mnt/config/boot.conf FRONT_LED "$led_front"
      rewrite_config /mnt/config/boot.conf RED_LED "$led_red"
      
      [ "$led_front" = "1" ] && /mnt/controlscripts/front-led start || /mnt/controlscripts/front-led stop
      [ "$led_red" = "1" ] && /mnt/controlscripts/red-led start || /mnt/controlscripts/red-led stop
      
      echo "LED configuration updated.<br/>"
    ;;

  esac
