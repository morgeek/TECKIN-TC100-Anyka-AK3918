#!/bin/sh

. /mnt/www/cgi-bin/func.cgi
. /mnt/scripts/common_functions.sh

export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

# Debounce expensive service restarts to avoid restart storms when multiple
# settings are applied in quick succession from the web UI.
schedule_service_restart() {
  service_script="$1"
  delay_seconds="${2:-2}"
  lock_dir="/tmp/$(basename "$service_script").restart.pending"

  if [ ! -x "$service_script" ]; then
    return 0
  fi
  if ! mkdir "$lock_dir" 2>/dev/null; then
    return 0
  fi

  (
    sleep "$delay_seconds"
    rmdir "$lock_dir" >/dev/null 2>&1 || true
    restart_service_if_need "$service_script"
  ) >/dev/null 2>&1 &
}

schedule_rtsp_restart() {
  schedule_service_restart /mnt/controlscripts/rtsp-h26x 2
}

schedule_onvif_restart() {
  schedule_service_restart /mnt/controlscripts/onvif 2
}

normalize_bool() {
  case "$1" in
    1|true|on|yes|enabled)
      echo 1
      ;;
    *)
      echo 0
      ;;
  esac
}

sanitize_int_range() {
  value="$1"
  min="$2"
  max="$3"
  fallback="$4"

  case "$value" in
    ''|*[!0-9]*)
      value="$fallback"
      ;;
  esac

  if [ "$value" -lt "$min" ]; then
    value="$min"
  fi
  if [ "$value" -gt "$max" ]; then
    value="$max"
  fi
  echo "$value"
}

apply_web_mode_async() {
  mode="$1"
  (
    sleep 1
    killall lighttpd >/dev/null 2>&1 || true
    killall httpd >/dev/null 2>&1 || true
    if [ "$mode" != "off" ]; then
      if [ -x /mnt/config/autostart/02_system-webserver ]; then
        /mnt/config/autostart/02_system-webserver >/dev/null 2>&1 || true
      else
        http_server on >/dev/null 2>&1 || true
      fi
    fi
  ) >/dev/null 2>&1 &
}

security_hardening_enabled() {
  hardening=0
  if [ -f /mnt/config/boot.conf ]; then
    hardening="$(awk -F= '/^SECURITY_HARDENING_MODE=/{print $2; exit}' /mnt/config/boot.conf 2>/dev/null)"
  fi
  case "$hardening" in
    1|true|on|yes|enabled) return 0 ;;
    *) return 1 ;;
  esac
}

publish_mqtt_event() {
  payload="$1"
  if [ -x /mnt/scripts/mqtt-bridge.sh ] && [ -n "$payload" ]; then
    /mnt/scripts/mqtt-bridge.sh publish event "$payload" 0 >/dev/null 2>&1 || true
  fi
}

if [ -n "$F_cmd" ]; then
  if [ -z "$F_val" ]; then
    F_val=100
  fi
  case "$F_cmd" in
    showlog)
      echo "<pre>"
      case "${F_logname}" in
        "" | 1)
          echo "Summary of all log files:<br/>"
          tail /var/log/*
          echo "<br/>===SD card logs===<br/>"
          tail /mnt/log/*
          ;;

        2)
          echo "Content of dmesg<br/>"
          /bin/dmesg
          ;;

        3)
          echo "Content of v4l2rtspserver.log<br/>"
          tail -n 256 /mnt/log/v4l2rtspserver.log
          ;;

      esac
      echo "</pre>"
    ;;
    clearlog)
      echo "<pre>"
      case "${F_logname}" in
        "" | 1)
          echo "Summary of all log files cleared<br/>"
          for i in /var/log/*
          do
              echo -n "" > $i
          done
          ;;
        2)
          echo "Content of dmesg cleared<br/>"
          /bin/dmesg -c > /dev/null
          ;;
        3)
          echo "Content of v4l2rtspserver.log cleared<br/>"
          echo -n "" > /mnt/log/v4l2rtspserver.log
          ;;
      esac
      echo "</pre>"
    ;;

    reboot)
      echo "Rebooting device..."
      now_ts="$(date +%s 2>/dev/null)"
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"reboot","source":"action.cgi"}' "$now_ts")"
      /sbin/reboot
    ;;

    shutdown)
      echo "Shutting down device.."
      /sbin/halt
    ;;

    blue_led_on)
      blue_led on
    ;;

    blue_led_off)
      blue_led off
    ;;

    red_led_on)
      red_led on
    ;;

    red_led_off)
      red_led off
    ;;

    ir_led_on)
      ir_led on
    ;;

    ir_led_off)
      ir_led off
    ;;

    ir_cut_on)
      ir_cut on
    ;;

    ir_cut_off)
      ir_cut off
    ;;

    audio_test)
      F_audioSource=$(printf '%b' "${F_audioSource//%/\\x}")
      if [ "$F_audioSource" == "" ]; then
        F_audioSource="/mnt/media/police.wav"
      fi
      /mnt/bin/busybox nohup /mnt/bin/audioplay $F_audioSource $F_audiotestVol > /dev/null 2>&1 &
      echo  "Play $F_audioSource at volume $F_audiotestVol"
    ;;


    set_telnet)
      if security_hardening_enabled; then
        echo "<p>Security hardening is enabled. Telnet changes are blocked.</p>"
        exit 0
      fi
      telnetport=$(printf '%b' "${F_telnetport}")
      case "$telnetport" in
        ''|*[!0-9]*)
          echo "<p>Invalid telnet port. Allowed range is 1-65535.</p>"
          ;;
        *)
          if [ "$telnetport" -lt 1 ] || [ "$telnetport" -gt 65535 ]; then
            echo "<p>Invalid telnet port. Allowed range is 1-65535.</p>"
          else
            echo "TELNET_PORT=$telnetport" > /mnt/config/telnetd.conf
            restart_service_if_need /mnt/controlscripts/telnet-server
            echo "<p>Setting telnet service port to : $telnetport</p>"
          fi
          ;;
      esac
    ;;

    set_ftp)
      if security_hardening_enabled; then
        echo "<p>Security hardening is enabled. FTP changes are blocked.</p>"
        exit 0
      fi
      ftpport=$(printf '%b' "${F_ftpport}")
      case "$ftpport" in
        ''|*[!0-9]*)
          echo "<p>Invalid ftp port. Allowed range is 1-65535.</p>"
          ;;
        *)
          if [ "$ftpport" -lt 1 ] || [ "$ftpport" -gt 65535 ]; then
            echo "<p>Invalid ftp port. Allowed range is 1-65535.</p>"
          else
            echo "<p>Setting ftp service port to: $ftpport</p>"
            echo "PORT=$ftpport" > /mnt/config/ftp.conf
            restart_service_if_need /mnt/controlscripts/ftp-server
          fi
          ;;
      esac
    ;;

    settz)
       ntp_srv=$(printf '%b' "${F_ntp_srv}")

      #read ntp_serv.conf
      conf_ntp_srv=$(cat /mnt/config/ntp_srv.conf)

      if [ "$conf_ntp_srv" != "$ntp_srv" ]; then
        echo "<p>Setting NTP Server to '$ntp_srv'...</p>"
        echo "$ntp_srv" > /mnt/config/ntp_srv.conf
        echo "<p>Syncing time on '$ntp_srv'...</p>"
        if /mnt/bin/busybox ntpd -q -n -p "$ntp_srv" > /dev/null 2>&1; then
          echo "<p>Success</p>"
        else
          echo "<p>Failed</p>"
        fi
      fi

      tz=$(printf '%b' "${F_tz//%/\\x}")
      if [ "$(cat /mnt/config/timezone.conf)" != "$tz" ]; then
        echo "<p>Setting TZ to '$tz'...</p>"
        echo "$tz" > /mnt/config/timezone.conf
        echo "<p>Syncing time...</p>"
        if /mnt/bin/busybox ntpd -q -n -p "$ntp_srv" > /dev/null 2>&1; then
          echo "<p>Success</p>"
        else echo "<p>Failed</p>"
        fi
        schedule_rtsp_restart
      fi
      hst=$(printf '%b' "${F_hostname}")
      if [ "$(cat /mnt/config/hostname.conf)" != "$hst" ]; then
        echo "<p>Setting hostname to '$hst'...</p>"
        echo "$hst" > /mnt/config/hostname.conf
        if hostname "$hst"; then
          echo "<p>Success</p>"
        else echo "<p>Failed</p>"
        fi
      fi
    ;;

    set_http_password)
      password=$(printf '%b' "${F_password//%/\\x}")
      echo "<p>Setting http password to : $password</p>"
      http_password "$password"
    ;;

    set_all_password)
      password=$(printf '%b' "${F_password//%/\\x}")
      echo "<p>Setting all services password to : $password</p>"
      all_password "$password"
      restart_service_if_need /mnt/controlscripts/ftp-server
      restart_service_if_need /mnt/controlscripts/telnet-server
      schedule_rtsp_restart
    ;;

    osd)
      osd_enabled="${F_OSDenable}"
      case "$osd_enabled" in
        1|enabled|true|on|yes)
          osd_enabled=1
          ;;
        *)
          osd_enabled=0
          ;;
      esac

      # F_osdtext is already URL-decoded in func.cgi; do not decode '%' again.
      osdtext="$F_osdtext"
      # Recover from legacy invalid escaped values like '\xH' -> '%H'.
      osdtext=$(printf '%s' "$osdtext" | sed 's/\\x/%/g')
      if [ -z "$osdtext" ]; then
        osdtext="%H:%M:%S %d.%m.%Y"
      fi

      frontcolor="${F_frontcolor:-1}"
      backcolor="${F_backcolor:-0}"
      edgecolor="${F_edgecolor:-2}"
      alpha="${F_alpha:-0}"
      osdsize0="${F_OSDSize0:-16}"
      posx0="${F_posx0:-0}"
      posy0="${F_posy0:-0}"
      osdsize1="${F_OSDSize1:-16}"
      posx1="${F_posx1:-0}"
      posy1="${F_posy1:-0}"

      if [ "$osd_enabled" = "1" ]; then
        /mnt/bin/setconf -k o -v "$osdtext"
      fi
      /mnt/bin/setconf -k c -v "$frontcolor"
      /mnt/bin/setconf -k i -v "$backcolor"
      /mnt/bin/setconf -k j -v "$edgecolor"
      /mnt/bin/setconf -k h -v "$alpha"
      /mnt/bin/setconf -k l -v "$osd_enabled"
      /mnt/bin/setconf -k s -v "$osdsize0"
      /mnt/bin/setconf -k x -v "$posx0"
      /mnt/bin/setconf -k y -v "$posy0"
      /mnt/bin/setconf -k z -v "$osdsize1"
      /mnt/bin/setconf -k w -v "$posx1"
      /mnt/bin/setconf -k t -v "$posy1"

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " osdtext "$osdtext" \
          " " osdfrontcolor "$frontcolor" \
          " " osdbackcolor "$backcolor" \
          " " osdalpha "$alpha" \
          " " osdedgecolor "$edgecolor" \
          " " osdenabled "$osd_enabled" \
          0  osdfontsize "$osdsize0" \
          0  osdx "$posx0" \
          0  osdy "$posy0" \
          1  osdfontsize "$osdsize1" \
          1  osdx "$posx1" \
          1  osdy "$posy1"

      schedule_rtsp_restart

      echo "OSD set to \"$osdtext\" and enabled: $osd_enabled<br/>"
    ;;

    auto_night_mode_start)
      /mnt/controlscripts/auto-night-detection start
    ;;

    auto_night_mode_stop)
      /mnt/controlscripts/auto-night-detection stop
    ;;

    toggle-rtsp-nightvision-on)
      /mnt/bin/setconf -k n -v 1
    ;;

    toggle-rtsp-nightvision-off)
      /mnt/bin/setconf -k n -v 0
    ;;

    night-mode-on)
      /mnt/controlscripts/night-mode start
    ;;

    night-mode-off)
      /mnt/controlscripts/night-mode stop
    ;;

    image-flip)
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " imageflip ${F_flipValue}
      /mnt/bin/setconf -k f -v ${F_flipValue}
    ;;

    rtsp-log-on)
      rewrite_config /mnt/config/rtspserver.conf RTSPLOGENABLED 1
      schedule_rtsp_restart
    ;;

    rtsp-log-off)
      rewrite_config /mnt/config/rtspserver.conf RTSPLOGENABLED 0
      schedule_rtsp_restart
    ;;

    motion_detection_on)
        mdsens=$(read_config rtspserver.conf mdsens)

        /mnt/bin/setconf -k m -v $mdsens
        /mnt/bin/setconf -k p -v 1
        rewrite_config /mnt/config/rtspserver.conf mdenabled 1
    ;;

    motion_detection_off)
      /mnt/bin/setconf -k p -v 0
      rewrite_config /mnt/config/rtspserver.conf mdenabled 0
    ;;

    service_trim_on)
      install_config /mnt/config/service_trim.conf
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 1
      echo "Service trimming enabled. Non-essential services will stop; reboot for full effect.<br/>"

      for svc in ftp-server telnet-server motion-detection recording timelapse auto-night-detection blue-led night-mode network-monitor; do
        if [ -x "/mnt/controlscripts/$svc" ]; then
          /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
        fi
      done
    ;;

    service_trim_off)
      install_config /mnt/config/service_trim.conf
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0
      echo "Service trimming disabled. Reboot to restore autostart services.<br/>"
    ;;

    set_performance_profile)
      install_config /mnt/config/boot.conf
      install_config /mnt/config/service_trim.conf
      profile=$(printf '%b' "${F_performance_profile}")

      case "$profile" in
        balanced)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 0
          rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE 0
          rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE 0
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 1
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-primary
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 0
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0

          echo "Performance profile set to Balanced.<br/>"
          echo "Dual stream + audio defaults enabled; reboot to restore all background services if they were trimmed.<br/>"
          ;;
        low-cpu)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 1
          rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE 1
          rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_OSD 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG 1
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 0
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 0
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-only
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 0
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0

          # Apply conservative stream settings immediately.
          /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
              0 width 640 0 height 360 0 fps 10 0 bps 600 0 goplen 20 0 brmode 1 \
              0 smartmode 1 0 smartgoplen 20 0 smartquality 60 0 smartstatic 350 0 maxkbps 800 0 targetkbps 600 \
              1 width 320 1 height 180 1 fps 5 1 bps 120 1 goplen 10 1 brmode 1 \
              1 smartmode 1 1 smartgoplen 10 1 smartquality 50 1 smartstatic 100 1 maxkbps 160 1 targetkbps 120

          echo "Performance profile set to Low CPU.<br/>"
          echo "Applied conservative RTSP settings now and enabled memory guard.<br/>"
          echo "Reboot recommended for full low-CPU service profile.<br/>"
          ;;
        rtsp-only)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 1
          rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE 1
          rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_OSD 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG 1
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 0
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 0
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-only
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 1
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 1

          for svc in ftp-server telnet-server motion-detection recording timelapse auto-night-detection blue-led night-mode network-monitor; do
            if [ -x "/mnt/controlscripts/$svc" ]; then
              /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
            fi
          done

          echo "Performance profile set to RTSP + ONVIF only.<br/>"
          echo "Stopped non-essential services now; reboot to enforce trimmed autostart persistently.<br/>"
          ;;
        *)
          echo "Unknown performance profile '$profile'<br/>"
          exit 0
          ;;
      esac

      schedule_rtsp_restart
      schedule_onvif_restart
      if [ -x /mnt/controlscripts/memory-guard ]; then
        if [ "$profile" = "balanced" ]; then
          /mnt/controlscripts/memory-guard stop >/dev/null 2>&1 || true
        else
          /mnt/controlscripts/memory-guard start >/dev/null 2>&1 || true
        fi
      fi
      now_ts="$(date +%s 2>/dev/null)"
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"profile","value":"%s"}' "$now_ts" "$profile")"
    ;;

    set_web_mode)
      install_config /mnt/config/boot.conf
      web_mode=$(printf '%b' "${F_web_mode}")
      ultralite_http_port=$(printf '%b' "${F_ultralite_http_port}")

      if security_hardening_enabled; then
        if [ "$web_mode" != "full" ]; then
          echo "Security hardening is enabled. WEB_MODE is locked to full (HTTPS).<br/>"
          exit 0
        fi
      fi

      case "$web_mode" in
        full|http|ultra-lite|ultralite|off) ;;
        *)
          echo "Unknown web mode '$web_mode'<br/>"
          exit 0
          ;;
      esac

      if [ "$web_mode" = "ultralite" ]; then
        web_mode="ultra-lite"
      fi

      case "$ultralite_http_port" in
        ''|*[!0-9]*) ultralite_http_port=80 ;;
      esac
      if [ "$ultralite_http_port" -lt 1 ] || [ "$ultralite_http_port" -gt 65535 ]; then
        ultralite_http_port=80
      fi

      rewrite_config /mnt/config/boot.conf WEB_MODE "$web_mode"
      rewrite_config /mnt/config/boot.conf ULTRALITE_HTTP_PORT "$ultralite_http_port"

      apply_web_mode_async "$web_mode"
      schedule_onvif_restart

      echo "Web mode set to: $web_mode<br/>"
      if [ "$web_mode" = "ultra-lite" ]; then
        echo "Ultra-lite HTTP port set to: $ultralite_http_port<br/>"
      fi
      echo "If the web UI disconnects, reconnect using the updated protocol/port.<br/>"
      now_ts="$(date +%s 2>/dev/null)"
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"web_mode","mode":"%s"}' "$now_ts" "$web_mode")"
    ;;

    set_stream_topology)
      install_config /mnt/config/boot.conf
      topology=$(printf '%b' "${F_stream_topology}")
      case "$topology" in
        dual-audio)
          rtsp_substream=1
          rtsp_audio=1
          topology_label="Dual stream + audio"
          ;;
        dual-no-audio)
          rtsp_substream=1
          rtsp_audio=0
          topology_label="Dual stream, audio disabled"
          ;;
        main-audio)
          rtsp_substream=0
          rtsp_audio=1
          topology_label="Main stream + audio"
          ;;
        main-only)
          rtsp_substream=0
          rtsp_audio=0
          topology_label="Main stream only (lowest CPU)"
          ;;
        *)
          echo "Unknown stream topology '$topology'<br/>"
          exit 0
          ;;
      esac

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      schedule_rtsp_restart
      schedule_onvif_restart
      echo "Stream topology set to: $topology_label<br/>"
    ;;

    set_onvif_stream_policy)
      install_config /mnt/config/boot.conf
      # shellcheck disable=SC1090
      if [ -f /mnt/config/boot.conf ]; then
        . /mnt/config/boot.conf
      fi

      policy=$(printf '%b' "${F_onvif_stream_policy}")
      case "$policy" in
        main-primary)
          policy_label="Main primary (default)"
          ;;
        sub-primary)
          policy_label="Substream primary"
          ;;
        sub-only)
          policy_label="Substream only"
          ;;
        main-only)
          policy_label="Main only"
          ;;
        *)
          echo "Unknown ONVIF stream policy '$policy'<br/>"
          exit 0
          ;;
      esac

      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$policy"
      schedule_onvif_restart

      echo "ONVIF stream policy set to: $policy_label<br/>"
      if [ "$RTSP_SUBSTREAM" != "1" ] && [ "$policy" != "main-primary" ] && [ "$policy" != "main-only" ]; then
        echo "Note: RTSP substream is disabled, ONVIF will fall back to main stream.<br/>"
      fi
    ;;

    set_mqtt_config)
      install_config /mnt/config/mqtt.conf

      mqtt_enable=$(normalize_bool "${F_mqtt_enable}")
      mqtt_host=$(printf '%b' "${F_mqtt_host}")
      mqtt_port=$(sanitize_int_range "${F_mqtt_port}" 1 65535 1883)
      mqtt_user=$(printf '%b' "${F_mqtt_user}")
      mqtt_password=$(printf '%b' "${F_mqtt_password}")
      mqtt_client_id=$(printf '%b' "${F_mqtt_client_id}")
      mqtt_topic_root=$(printf '%b' "${F_mqtt_topic_root}")
      mqtt_topic_command=$(printf '%b' "${F_mqtt_topic_command}")
      mqtt_qos=$(sanitize_int_range "${F_mqtt_qos}" 0 2 0)
      mqtt_health_interval_seconds=$(sanitize_int_range "${F_mqtt_health_interval_seconds}" 10 86400 60)
      mqtt_command_wait_seconds=$(sanitize_int_range "${F_mqtt_command_wait_seconds}" 3 120 12)
      mqtt_command_repeat_window_seconds=$(sanitize_int_range "${F_mqtt_command_repeat_window_seconds}" 0 600 20)
      mqtt_ha_discovery_enable=$(normalize_bool "${F_mqtt_ha_discovery_enable}")
      mqtt_ha_discovery_prefix=$(printf '%b' "${F_mqtt_ha_discovery_prefix}")
      power_estimate_enable=$(normalize_bool "${F_power_estimate_enable}")
      power_estimate_base_mw=$(sanitize_int_range "${F_power_estimate_base_mw}" 500 10000 1700)
      power_estimate_cpu_scale_mw=$(sanitize_int_range "${F_power_estimate_cpu_scale_mw}" 0 5000 500)
      power_estimate_ir_led_mw=$(sanitize_int_range "${F_power_estimate_ir_led_mw}" 0 5000 700)
      power_sensor_path=$(printf '%b' "${F_power_sensor_path}")

      case "$mqtt_host" in
        ''|*[!A-Za-z0-9._:-]*)
          mqtt_host="127.0.0.1"
          ;;
      esac

      mqtt_client_id="$(printf '%s' "$mqtt_client_id" | sed 's/[^A-Za-z0-9._-]/-/g')"
      [ -n "$mqtt_client_id" ] || mqtt_client_id="tc100-camera"

      mqtt_topic_root="$(printf '%s' "$mqtt_topic_root" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      [ -n "$mqtt_topic_root" ] || mqtt_topic_root="tc100/camera"

      mqtt_topic_command="$(printf '%s' "$mqtt_topic_command" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      if [ -z "$mqtt_topic_command" ]; then
        mqtt_topic_command="${mqtt_topic_root}/command"
      fi

      mqtt_ha_discovery_prefix="$(printf '%s' "$mqtt_ha_discovery_prefix" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      [ -n "$mqtt_ha_discovery_prefix" ] || mqtt_ha_discovery_prefix="homeassistant"

      case "$power_sensor_path" in
        ''|auto)
          power_sensor_path="auto"
          ;;
        /*)
          power_sensor_path="$(printf '%s' "$power_sensor_path" | sed 's#[^A-Za-z0-9._/-]##g')"
          [ -n "$power_sensor_path" ] || power_sensor_path="auto"
          ;;
        *)
          power_sensor_path="auto"
          ;;
      esac

      rewrite_config /mnt/config/mqtt.conf MQTT_ENABLE "$mqtt_enable"
      rewrite_config /mnt/config/mqtt.conf MQTT_HOST "$mqtt_host"
      rewrite_config /mnt/config/mqtt.conf MQTT_PORT "$mqtt_port"
      rewrite_config /mnt/config/mqtt.conf MQTT_USER "$mqtt_user"
      rewrite_config /mnt/config/mqtt.conf MQTT_PASSWORD "$mqtt_password"
      rewrite_config /mnt/config/mqtt.conf MQTT_CLIENT_ID "$mqtt_client_id"
      rewrite_config /mnt/config/mqtt.conf MQTT_TOPIC_ROOT "$mqtt_topic_root"
      rewrite_config /mnt/config/mqtt.conf MQTT_TOPIC_COMMAND "$mqtt_topic_command"
      rewrite_config /mnt/config/mqtt.conf MQTT_QOS "$mqtt_qos"
      rewrite_config /mnt/config/mqtt.conf MQTT_HEALTH_INTERVAL_SECONDS "$mqtt_health_interval_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_COMMAND_WAIT_SECONDS "$mqtt_command_wait_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_COMMAND_REPEAT_WINDOW_SECONDS "$mqtt_command_repeat_window_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_ENABLE "$mqtt_ha_discovery_enable"
      rewrite_config /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_PREFIX "$mqtt_ha_discovery_prefix"
      rewrite_config /mnt/config/mqtt.conf POWER_ESTIMATE_ENABLE "$power_estimate_enable"
      rewrite_config /mnt/config/mqtt.conf POWER_ESTIMATE_BASE_MW "$power_estimate_base_mw"
      rewrite_config /mnt/config/mqtt.conf POWER_ESTIMATE_CPU_SCALE_MW "$power_estimate_cpu_scale_mw"
      rewrite_config /mnt/config/mqtt.conf POWER_ESTIMATE_IR_LED_MW "$power_estimate_ir_led_mw"
      rewrite_config /mnt/config/mqtt.conf POWER_SENSOR_PATH "$power_sensor_path"

      if [ -x /mnt/controlscripts/mqtt-bridge ]; then
        if [ "$mqtt_enable" = "1" ]; then
          /mnt/controlscripts/mqtt-bridge stop >/dev/null 2>&1 || true
          /mnt/controlscripts/mqtt-bridge start >/dev/null 2>&1 || true
        else
          /mnt/controlscripts/mqtt-bridge stop >/dev/null 2>&1 || true
        fi
      fi

      echo "MQTT bridge configuration saved.<br/>"
      echo "Enabled=$mqtt_enable, broker=${mqtt_host}:${mqtt_port}, topic_root=${mqtt_topic_root}, command_topic=${mqtt_topic_command}, qos=${mqtt_qos}, dedupe_window=${mqtt_command_repeat_window_seconds}s<br/>"
      echo "HA discovery=${mqtt_ha_discovery_enable} (prefix=${mqtt_ha_discovery_prefix}), power_estimate=${power_estimate_enable}, base=${power_estimate_base_mw}mW, cpu_scale=${power_estimate_cpu_scale_mw}mW, ir_led=${power_estimate_ir_led_mw}mW<br/>"
    ;;

    set_advanced_tuning)
      install_config /mnt/config/boot.conf

      lightweight_mode=$(normalize_bool "${F_lightweight_mode}")
      ui_ultralite_mode=$(normalize_bool "${F_ui_ultralite_mode}")
      security_hardening_mode=$(normalize_bool "${F_security_hardening_mode}")
      enable_ntp=$(normalize_bool "${F_enable_ntp}")
      ntp_one_shot=$(normalize_bool "${F_ntp_one_shot}")
      mem_guard_enable=$(normalize_bool "${F_mem_guard_enable}")
      mem_guard_drop_caches=$(normalize_bool "${F_mem_guard_drop_caches}")

      mem_guard_interval_seconds=$(sanitize_int_range "${F_mem_guard_interval_seconds}" 5 600 20)
      mem_guard_warn_kb=$(sanitize_int_range "${F_mem_guard_warn_kb}" 2048 65535 8192)
      mem_guard_critical_kb=$(sanitize_int_range "${F_mem_guard_critical_kb}" 1024 65535 4096)
      mem_guard_recovery_margin_kb=$(sanitize_int_range "${F_mem_guard_recovery_margin_kb}" 256 32768 1536)
      mem_guard_warn_hits=$(sanitize_int_range "${F_mem_guard_warn_hits}" 1 10 2)
      mem_guard_critical_hits=$(sanitize_int_range "${F_mem_guard_critical_hits}" 1 10 1)
      mem_guard_cooldown_seconds=$(sanitize_int_range "${F_mem_guard_cooldown_seconds}" 10 3600 120)
      mem_guard_emergency_kb=$(sanitize_int_range "${F_mem_guard_emergency_kb}" 512 32768 2048)
      rtsp_healthcheck_timeout_seconds=$(sanitize_int_range "${F_rtsp_healthcheck_timeout_seconds}" 2 30 4)
      onvif_healthcheck_timeout_seconds=$(sanitize_int_range "${F_onvif_healthcheck_timeout_seconds}" 2 30 4)

      if [ "$mem_guard_critical_kb" -ge "$mem_guard_warn_kb" ]; then
        mem_guard_critical_kb=$((mem_guard_warn_kb / 2))
        if [ "$mem_guard_critical_kb" -lt 1024 ]; then
          mem_guard_critical_kb=1024
        fi
      fi

      if [ "$mem_guard_emergency_kb" -ge "$mem_guard_critical_kb" ]; then
        mem_guard_emergency_kb=$((mem_guard_critical_kb / 2))
        if [ "$mem_guard_emergency_kb" -lt 512 ]; then
          mem_guard_emergency_kb=512
        fi
      fi

      rewrite_config /mnt/config/boot.conf LIGHTWEIGHT_MODE "$lightweight_mode"
      rewrite_config /mnt/config/boot.conf UI_ULTRALITE_MODE "$ui_ultralite_mode"
      rewrite_config /mnt/config/boot.conf SECURITY_HARDENING_MODE "$security_hardening_mode"
      rewrite_config /mnt/config/boot.conf ENABLE_NTP "$enable_ntp"
      rewrite_config /mnt/config/boot.conf NTP_ONE_SHOT "$ntp_one_shot"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE "$mem_guard_enable"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_INTERVAL_SECONDS "$mem_guard_interval_seconds"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_WARN_KB "$mem_guard_warn_kb"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_CRITICAL_KB "$mem_guard_critical_kb"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_RECOVERY_MARGIN_KB "$mem_guard_recovery_margin_kb"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_WARN_HITS "$mem_guard_warn_hits"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_CRITICAL_HITS "$mem_guard_critical_hits"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_COOLDOWN_SECONDS "$mem_guard_cooldown_seconds"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_EMERGENCY_KB "$mem_guard_emergency_kb"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_DROP_CACHES "$mem_guard_drop_caches"
      rewrite_config /mnt/config/boot.conf RTSP_HEALTHCHECK_TIMEOUT_SECONDS "$rtsp_healthcheck_timeout_seconds"
      rewrite_config /mnt/config/boot.conf ONVIF_HEALTHCHECK_TIMEOUT_SECONDS "$onvif_healthcheck_timeout_seconds"

      if [ "$security_hardening_mode" = "1" ]; then
        rewrite_config /mnt/config/boot.conf WEB_MODE full
        apply_web_mode_async full
        for svc in ftp-server telnet-server; do
          if [ -x "/mnt/controlscripts/$svc" ]; then
            "/mnt/controlscripts/$svc" stop >/dev/null 2>&1 || true
          fi
          rm -f "/mnt/config/autostart/$svc" >/dev/null 2>&1 || true
        done
      fi

      if [ -x /mnt/controlscripts/memory-guard ]; then
        if [ "$mem_guard_enable" = "1" ]; then
          /mnt/controlscripts/memory-guard start >/dev/null 2>&1 || true
        else
          /mnt/controlscripts/memory-guard stop >/dev/null 2>&1 || true
        fi
      fi

      schedule_rtsp_restart
      schedule_onvif_restart

      echo "Advanced tuning saved.<br/>"
      echo "LIGHTWEIGHT_MODE=$lightweight_mode, UI_ULTRALITE_MODE=$ui_ultralite_mode, SECURITY_HARDENING_MODE=$security_hardening_mode, ENABLE_NTP=$enable_ntp, NTP_ONE_SHOT=$ntp_one_shot<br/>"
      echo "MEM_GUARD_ENABLE=$mem_guard_enable (interval=${mem_guard_interval_seconds}s, warn=${mem_guard_warn_kb}kB, critical=${mem_guard_critical_kb}kB, emergency=${mem_guard_emergency_kb}kB, recovery_margin=${mem_guard_recovery_margin_kb}kB, hits=${mem_guard_warn_hits}/${mem_guard_critical_hits}, cooldown=${mem_guard_cooldown_seconds}s, drop_caches=${mem_guard_drop_caches})<br/>"
      echo "Healthcheck timeouts: RTSP=${rtsp_healthcheck_timeout_seconds}s, ONVIF=${onvif_healthcheck_timeout_seconds}s<br/>"
      if [ "$security_hardening_mode" = "1" ]; then
        echo "Security hardening is enabled: FTP/Telnet disabled, WEB_MODE forced to full (HTTPS).<br/>"
      fi
      echo "Reboot recommended to fully apply lightweight/NTP boot behavior.<br/>"
      now_ts="$(date +%s 2>/dev/null)"
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"security_hardening","enabled":%s}' "$now_ts" "$security_hardening_mode")"
    ;;

    set_rtsp_preset)
      preset=$(printf '%b' "${F_preset}")
      case "$preset" in
        full)
          width0=1280; height0=720; fps0=25; bps0=2000; gop0=50; maxkbps0=2500; targetkbps0=2000; smartq0=100; smartstatic0=550
          width1=640;  height1=360; fps1=10; bps1=300;  gop1=20; maxkbps1=400;  targetkbps1=300;  smartq1=70;  smartstatic1=150
          ;;
        medium)
          width0=1280; height0=720; fps0=20; bps0=1200; gop0=40; maxkbps0=1500; targetkbps0=1200; smartq0=80; smartstatic0=450
          width1=320;  height1=180; fps1=8;  bps1=200;  gop1=16; maxkbps1=250;  targetkbps1=200;  smartq1=60; smartstatic1=120
          ;;
        low)
          width0=640;  height0=360; fps0=10; bps0=600;  gop0=20; maxkbps0=800;  targetkbps0=600;  smartq0=60; smartstatic0=350
          width1=320;  height1=180; fps1=5;  bps1=120;  gop1=10; maxkbps1=160;  targetkbps1=120;  smartq1=50; smartstatic1=100
          ;;
        *)
          echo "Unknown preset '$preset'<br/>"
          exit 0
          ;;
      esac

      echo "RTSP preset applied: $preset (fps max 25)<br/>"

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          0 width        "$width0" \
          0 height       "$height0" \
          0 fps          "$fps0" \
          0 bps          "$bps0" \
          0 goplen       "$gop0" \
          0 brmode       1 \
          0 smartmode    1 \
          0 smartgoplen  "$gop0" \
          0 smartquality "$smartq0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 width        "$width1" \
          1 height       "$height1" \
          1 fps          "$fps1" \
          1 bps          "$bps1" \
          1 goplen       "$gop1" \
          1 brmode       1 \
          1 smartmode    1 \
          1 smartgoplen  "$gop1" \
          1 smartquality "$smartq1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      schedule_rtsp_restart
    ;;

    set_client_profile)
      client_profile=$(printf '%b' "${F_client_profile}")
      install_config /mnt/config/boot.conf

      case "$client_profile" in
        ha-frigate)
          profile_label="HA Frigate"
          width0=1920; height0=1080; fps0=15; bps0=1800; gop0=30; maxkbps0=2200; targetkbps0=1800; smartq0=85; smartstatic0=500
          width1=640;  height1=360;  fps1=8;  bps1=260;  gop1=16; maxkbps1=360;  targetkbps1=260;  smartq1=65; smartstatic1=150
          rtsp_substream=1
          rtsp_audio=0
          onvif_policy="sub-primary"
          ;;
        nvr-low-cpu)
          profile_label="NVR low-CPU"
          width0=1280; height0=720;  fps0=10; bps0=900;  gop0=20; maxkbps0=1200; targetkbps0=900;  smartq0=65; smartstatic0=360
          width1=320;  height1=180;  fps1=5;  bps1=120;  gop1=10; maxkbps1=180;  targetkbps1=120;  smartq1=50; smartstatic1=100
          rtsp_substream=0
          rtsp_audio=0
          onvif_policy="main-only"
          ;;
        high-quality)
          profile_label="High quality"
          width0=1920; height0=1080; fps0=25; bps0=2600; gop0=50; maxkbps0=3200; targetkbps0=2600; smartq0=100; smartstatic0=600
          width1=640;  height1=360;  fps1=12; bps1=500;  gop1=24; maxkbps1=700;  targetkbps1=500;  smartq1=75; smartstatic1=200
          rtsp_substream=1
          rtsp_audio=1
          onvif_policy="main-primary"
          ;;
        *)
          echo "Unknown client profile '$client_profile'<br/>"
          exit 0
          ;;
      esac

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          0 width        "$width0" \
          0 height       "$height0" \
          0 fps          "$fps0" \
          0 bps          "$bps0" \
          0 goplen       "$gop0" \
          0 brmode       1 \
          0 smartmode    1 \
          0 smartgoplen  "$gop0" \
          0 smartquality "$smartq0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 width        "$width1" \
          1 height       "$height1" \
          1 fps          "$fps1" \
          1 bps          "$bps1" \
          1 goplen       "$gop1" \
          1 brmode       1 \
          1 smartmode    1 \
          1 smartgoplen  "$gop1" \
          1 smartquality "$smartq1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      if [ "$rtsp_audio" = "0" ]; then
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w 2 codec 0 3 codec 0
      fi

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$onvif_policy"
      if [ "$client_profile" = "nvr-low-cpu" ]; then
        rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 1
      else
        rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 0
      fi

      schedule_rtsp_restart
      schedule_onvif_restart

      echo "Client preset applied: $profile_label<br/>"
      echo "RTSP_SUBSTREAM=$rtsp_substream, RTSP_AUDIO=$rtsp_audio, ONVIF_STREAM_POLICY=$onvif_policy<br/>"
      echo "Main=${width0}x${height0}@${fps0}fps, Sub=${width1}x${height1}@${fps1}fps<br/>"
      now_ts="$(date +%s 2>/dev/null)"
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"client_profile","value":"%s"}' "$now_ts" "$client_profile")"
    ;;

    set_video_size)
      wh0=${F_video_size0}
      width0="${wh0%x*}"
      height0="${wh0#*x}"

      wh1=${F_video_size1}
      width1="${wh1%x*}"
      height1="${wh1#*x}"

      username=$(printf '%b' "${F_videouser//%/\\x}")
      userpassword=$(printf '%b' "${F_videopassword//%/\\x}")

      echo "Video resolution set to $wh0 and $wh1<br/>"

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " USERNAME "${username}" \
          " " USERPASSWORD "${userpassword}" \
          " " PORT "${F_videoport}" \
          0 bps          "${F_brbitrate0}" \
          0 brmode       "${F_video_format0}" \
          0 codec        "${F_video_codec0}" \
          0 fps          "${F_fps0}" \
          0 goplen       "${F_goplen0}" \
          0 height       "$height0" \
          0 maxqp        "${F_maxqp0}" \
          0 minqp        "${F_minqp0}" \
          0 profile      "${F_codec_profile0}" \
          0 width        "$width0" \
          0 smartmode    "${F_smartmode0}" \
          0 smartgoplen  "${F_smartgoplen0}" \
          0 smartquality "${F_smartquality0}" \
          0 smartstatic  "${F_smartstatic0}" \
          0 maxkbps      "${F_maxkbps0}" \
          0 targetkbps   "${F_targetkbps0}" \
          1 bps          "${F_brbitrate1}" \
          1 brmode       "${F_video_format1}" \
          1 codec        "${F_video_codec1}" \
          1 fps          "${F_fps1}" \
          1 goplen       "${F_goplen1}" \
          1 height       "$height1" \
          1 maxqp        "${F_maxqp1}" \
          1 minqp        "${F_minqp1}" \
          1 profile      "${F_codec_profile1}" \
          1 width        "$width1" \
          1 smartmode    "${F_smartmode1}" \
          1 smartgoplen  "${F_smartgoplen1}" \
          1 smartquality "${F_smartquality1}" \
          1 smartstatic  "${F_smartstatic1}" \
          1 maxkbps      "${F_maxkbps1}" \
          1 targetkbps   "${F_targetkbps1}" \

      schedule_rtsp_restart
    ;;


    conf_timelapse)
      tlinterval=$(printf '%b' "${F_tlinterval}")
      tlinterval=$(echo "$tlinterval" | sed "s/[^0-9\.]//g")
      if [ "$tlinterval" ]; then
        rewrite_config /mnt/config/timelapse.conf TIMELAPSE_INTERVAL "$tlinterval"
        echo "Timelapse interval set to $tlinterval seconds."
      else
        echo "Invalid timelapse interval"
      fi
      tlduration=$(printf '%b' "${F_tlduration}")
      tlduration=$(echo "$tlduration" | sed "s/[^0-9\.]//g")
      if [ "$tlduration" ]; then
        rewrite_config /mnt/config/timelapse.conf TIMELAPSE_DURATION "$tlduration"
        echo "Timelapse duration set to $tlduration minutes."
      else
        echo "Invalid timelapse duration"
      fi
    ;;

    conf_recording)
      motion_act=$(printf '%b' "${F_motion_act}")
      postrec=$(printf '%b' "${F_postrec}")
      maxduration=$(printf '%b' "${F_maxduration}")
      diskspace=$(printf '%b' "${F_diskspace}")

      echo "Motion activated recording set to $motion_act.<BR>"
      echo "Postrecord set to $postrec seconds.<BR>"
      echo "Max file duration set to $maxduration seconds.<BR>"
      echo "Reserved free disk space set to $diskspace Megabytes.<BR>"

      echo "rec_motion_activated=$motion_act" > /mnt/config/recording.conf
      echo "rec_postrecord_sec=$postrec" >> /mnt/config/recording.conf
      echo "rec_file_duration_sec=$maxduration" >> /mnt/config/recording.conf
      echo "rec_reserverd_disk_mb=$diskspace" >> /mnt/config/recording.conf

      restart_service_if_need /mnt/controlscripts/recording
    ;;

    conf_motiondetect)
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " mdsens ${F_mdsens} 
      /mnt/bin/setconf -k m -v "${F_mdsens}"
      rewrite_config /mnt/config/motion.conf motion_trigger_led "${F_motionBlink}"

      echo "Motion red led blink set to ${F_motionBlink}<BR>"
      echo "Motion sensitivity set to ${F_mdsens}<BR>"
    ;;

    conf_audioin)
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " samplerate "${F_samplerate}" \
          " " volume "${F_audioinVol}" \
          2 codec "${F_audioCodec0}" \
          2 samplerate "${F_samplerate}" \
          3 codec "${F_audioCodec1}" \
          3 samplerate "${F_samplerate}"

       echo "In audio bitrate ${F_samplerate} <BR>"
       echo "Volume $F_audioinVol <BR>"

       schedule_rtsp_restart
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


    conf_ptt)
        echo "$F_audiooutVol" > /mnt/config/pttvolume.conf
        echo "Push-to-talk volume set to $F_audiooutVol"
    ;;

     motion_detection_mail_on)
         rewrite_config /mnt/config/motion.conf sendemail "true"
         ;;

     motion_detection_mail_off)
          rewrite_config /mnt/config/motion.conf sendemail "false"
          ;;

     motion_detection_snapshot_on)
          rewrite_config /mnt/config/motion.conf save_snapshot "true"
          ;;

     motion_detection_snapshot_off)
          rewrite_config /mnt/config/motion.conf save_snapshot "false"
          ;;
     *)
        echo "Unsupported command '$F_cmd'"
        ;;

  esac
fi

echo "<hr/>"
