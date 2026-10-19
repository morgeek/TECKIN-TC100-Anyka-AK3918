# shellcheck shell=sh
# action.cgi commands: LEDs, IR, day/night.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

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

    conf_autodaynight)
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
            " " daynightawb "${F_dnawb}" \
            " " daynightlum "${F_dnlum}" \
            " " nightdayawb "${F_ndawb}" \
            " " nightdaylum "${F_ndlum}"

        /mnt/bin/setconf -k r -v "${F_dnawb}"
        /mnt/bin/setconf -k a -v "${F_dnlum}"
        /mnt/bin/setconf -k b -v "${F_ndawb}"
        /mnt/bin/setconf -k d -v "${F_ndlum}"

        echo "daynightawb ${F_dnawb} <BR>"
        echo "daynightlum ${F_dnlum} <BR>"
        echo "nightdayawb ${F_ndawb} <BR>"
        echo "nightdaylum ${F_ndlum} <BR>"
     ;;
  esac
