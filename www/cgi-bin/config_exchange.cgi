#!/bin/sh
# config_exchange.cgi — JSON-based configuration export and import.

if [ -r /mnt/www/cgi-bin/func.cgi ]; then
  . /mnt/www/cgi-bin/func.cgi
else
  . ./func.cgi
fi

rate_limit_check 10 60
csrf_guard

# Content type will be set by each command
output_json_header() {
  echo "Content-type: application/json"
  echo "Pragma: no-cache"
  echo "Cache-Control: no-store, no-cache"
}

case "$F_cmd" in
  export)
    _ce_now="$(date +%Y%m%d_%H%M%S)"
    output_json_header
    echo "Content-Disposition: attachment; filename=tc100_config_${_ce_now}.json"
    echo ""
    # Internally call state.cgi fullconfig logic
    # We could exec it, but we need to ensure headers from state.cgi don't interfere
    # or just replicate the call.
    QUERY_STRING="cmd=fullconfig" F_cmd="fullconfig" sh ./state.cgi | sed '1,/^$/d'
    ;;

  import)
    output_json_header
    echo ""
    if [ "$REQUEST_METHOD" != "POST" ]; then
      json_error "INVALID_METHOD" "POST required for import"
      exit 0
    fi

    # Read POST body (JSON)
    _tmp_json="/tmp/config_import.json"
    head -c "${CONTENT_LENGTH:-0}" > "$_tmp_json"
    
    if [ ! -s "$_tmp_json" ]; then
      json_error "EMPTY_PAYLOAD" "No JSON data received"
      exit 0
    fi

    # Validation: basic JQ check
    if ! /mnt/bin/jq . "$_tmp_json" > /dev/null 2>&1; then
      json_error "INVALID_JSON" "Malformed JSON received"
      rm -f "$_tmp_json"
      exit 0
    fi

    # Check for exclusion flags
    _exclude_network="$(truthy_flag "$F_exclude_network")"
    _exclude_credentials="$(truthy_flag "$F_exclude_credentials")"

    # Mapping helper function
    # apply_json_val <section> <json_path> <file> <key>
    apply_json_val() {
      _section="$1"
      _path="$2"
      _file="$3"
      _key="$4"
      
      _val=$(/mnt/bin/jq -r ".${_section}${_path}" "$_tmp_json" 2>/dev/null)
      if [ -n "$_val" ] && [ "$_val" != "null" ]; then
        # Exclude network triggers
        if [ "$_exclude_network" = "1" ]; then
           case "$_key" in
             HOSTNAME|TIMEZONE|NTP_SERVER|DEFAULT_GATEWAY|WEB_MODE|ULTRALITE_HTTP_PORT) return 0 ;;
           esac
        fi
        # Exclude credentials trigger
        if [ "$_exclude_credentials" = "1" ]; then
           case "$_key" in
             USERNAME|USERPASSWORD|MQTT_USER|MQTT_PASSWORD|apiToken|userChatId) return 0 ;;
           esac
        fi

        /mnt/bin/rwconf "$_file" w " " "$_key" "$_val" >/dev/null 2>&1
        return 0 # Mark as changed (reverse logic for loop)
      fi
      return 1
    }

    _changes=0
    
    # BOOT
    apply_json_val "boot" ".web_mode" "/mnt/config/boot.conf" "WEB_MODE" || _changes=1
    apply_json_val "boot" ".topology" "/mnt/config/boot.conf" "STREAM_TOPOLOGY" || _changes=1
    apply_json_val "boot" ".ultralite_port" "/mnt/config/boot.conf" "ULTRALITE_HTTP_PORT" || _changes=1
    apply_json_val "boot" ".lightweight_mode" "/mnt/config/boot.conf" "LIGHTWEIGHT_MODE" || _changes=1
    apply_json_val "boot" ".security_hardening" "/mnt/config/boot.conf" "SECURITY_HARDENING_MODE" || _changes=1
    apply_json_val "boot" ".service_trim" "/mnt/config/service_trim.conf" "SERVICE_TRIM" || _changes=1

    # VIDEO / RTSP
    apply_json_val "video" ".rtsp_port" "/mnt/config/rtspserver.conf" "PORT" || _changes=1
    apply_json_val "video" ".main.codec" "/mnt/config/rtspserver.conf" "0_codec" || _changes=1
    apply_json_val "video" ".main.width" "/mnt/config/rtspserver.conf" "0_width" || _changes=1
    apply_json_val "video" ".main.height" "/mnt/config/rtspserver.conf" "0_height" || _changes=1
    apply_json_val "video" ".main.fps" "/mnt/config/rtspserver.conf" "0_fps" || _changes=1
    apply_json_val "video" ".main.bitrate" "/mnt/config/rtspserver.conf" "0_bps" || _changes=1
    apply_json_val "video" ".main.gop" "/mnt/config/rtspserver.conf" "0_goplen" || _changes=1
    apply_json_val "video" ".sub.codec" "/mnt/config/rtspserver.conf" "1_codec" || _changes=1
    apply_json_val "video" ".sub.width" "/mnt/config/rtspserver.conf" "1_width" || _changes=1
    apply_json_val "video" ".sub.height" "/mnt/config/rtspserver.conf" "1_height" || _changes=1
    apply_json_val "video" ".sub.fps" "/mnt/config/rtspserver.conf" "1_fps" || _changes=1
    apply_json_val "video" ".sub.bitrate" "/mnt/config/rtspserver.conf" "1_bps" || _changes=1
    apply_json_val "video" ".sub.gop" "/mnt/config/rtspserver.conf" "1_goplen" || _changes=1
    apply_json_val "video" ".flip" "/mnt/config/rtspserver.conf" "imageFlip" || _changes=1
    apply_json_val "video" ".rtsp_log" "/mnt/config/rtspserver.conf" "enable_rtsp_log" || _changes=1

    # AUDIO
    apply_json_val "audio" ".samplerate" "/mnt/config/rtspserver.conf" "samplerate" || _changes=1
    apply_json_val "audio" ".volume" "/mnt/config/rtspserver.conf" "volume" || _changes=1
    apply_json_val "audio" ".codec_main" "/mnt/config/rtspserver.conf" "audioCodec0" || _changes=1
    apply_json_val "audio" ".codec_sub" "/mnt/config/rtspserver.conf" "audioCodec1" || _changes=1

    # ISP
    apply_json_val "isp" ".daynight_lum" "/mnt/config/rtspserver.conf" "daynightlum" || _changes=1
    apply_json_val "isp" ".daynight_awb" "/mnt/config/rtspserver.conf" "daynightawb" || _changes=1
    apply_json_val "isp" ".nightday_lum" "/mnt/config/rtspserver.conf" "nightdaylum" || _changes=1
    apply_json_val "isp" ".nightday_awb" "/mnt/config/rtspserver.conf" "nightdayawb" || _changes=1

    # OSD
    apply_json_val "osd" ".enabled" "/mnt/config/rtspserver.conf" "osdenabled" || _changes=1
    apply_json_val "osd" ".text" "/mnt/config/rtspserver.conf" "osdtext" || _changes=1
    apply_json_val "osd" ".alpha" "/mnt/config/rtspserver.conf" "osdalpha" || _changes=1
    apply_json_val "osd" ".fontsize0" "/mnt/config/rtspserver.conf" "osdfontsize0" || _changes=1
    apply_json_val "osd" ".frontcolor" "/mnt/config/rtspserver.conf" "frontcolor" || _changes=1
    apply_json_val "osd" ".backcolor" "/mnt/config/rtspserver.conf" "backcolor" || _changes=1
    apply_json_val "osd" ".edgecolor" "/mnt/config/rtspserver.conf" "edgecolor" || _changes=1
    apply_json_val "osd" ".x0" "/mnt/config/rtspserver.conf" "osdx0" || _changes=1
    apply_json_val "osd" ".y0" "/mnt/config/rtspserver.conf" "osdy0" || _changes=1

    # MQTT
    apply_json_val "mqtt" ".enabled" "/mnt/config/mqtt.conf" "MQTT_ENABLE" || _changes=1
    apply_json_val "mqtt" ".host" "/mnt/config/mqtt.conf" "MQTT_HOST" || _changes=1
    apply_json_val "mqtt" ".port" "/mnt/config/mqtt.conf" "MQTT_PORT" || _changes=1
    apply_json_val "mqtt" ".user" "/mnt/config/mqtt.conf" "MQTT_USER" || _changes=1
    apply_json_val "mqtt" ".topic_root" "/mnt/config/mqtt.conf" "MQTT_TOPIC_ROOT" || _changes=1
    apply_json_val "mqtt" ".discovery" "/mnt/config/mqtt.conf" "MQTT_HA_DISCOVERY_ENABLE" || _changes=1
    apply_json_val "mqtt" ".discovery_prefix" "/mnt/config/mqtt.conf" "MQTT_HA_DISCOVERY_PREFIX" || _changes=1

    # RECORDING
    apply_json_val "recording" ".postrec" "/mnt/config/recording.conf" "postrec" || _changes=1
    apply_json_val "recording" ".maxduration" "/mnt/config/recording.conf" "maxduration" || _changes=1
    apply_json_val "recording" ".reserved_mb" "/mnt/config/recording.conf" "diskspace" || _changes=1
    apply_json_val "recording" ".motion_activated" "/mnt/config/recording.conf" "motion_act" || _changes=1

    # SYSTEM
    apply_json_val "system" ".hostname" "/mnt/config/hostname.conf" "HOSTNAME" || _changes=1
    apply_json_val "system" ".timezone" "/mnt/config/timezone.conf" "TIMEZONE" || _changes=1
    apply_json_val "system" ".ntp_server" "/mnt/config/ntp_srv.conf" "NTP_SERVER" || _changes=1
    apply_json_val "system" ".reboot_schedule.enable" "/mnt/config/boot.conf" "REBOOT_SCHEDULE_ENABLE" || _changes=1
    apply_json_val "system" ".reboot_schedule.hour" "/mnt/config/boot.conf" "REBOOT_SCHEDULE_HOUR" || _changes=1
    apply_json_val "system" ".reboot_schedule.min" "/mnt/config/boot.conf" "REBOOT_SCHEDULE_MINUTE" || _changes=1
    apply_json_val "system" ".reboot_schedule.dow" "/mnt/config/boot.conf" "REBOOT_SCHEDULE_WEEKDAY" || _changes=1

    # SERVICES
    apply_json_val "services" ".telnet_port" "/mnt/config/telnetd.conf" "TELNET_PORT" || _changes=1
    apply_json_val "services" ".sound_det_enable" "/mnt/config/sound_detection.conf" "ENABLE" || _changes=1
    apply_json_val "services" ".sound_det_threshold" "/mnt/config/sound_detection.conf" "THRESHOLD" || _changes=1
    apply_json_val "services" ".sound_det_interval" "/mnt/config/sound_detection.conf" "INTERVAL" || _changes=1
    apply_json_val "services" ".motion_sens" "/mnt/config/motion.conf" "mdsens" || _changes=1
    apply_json_val "services" ".motion_led" "/mnt/config/motion.conf" "motion_trigger_led" || _changes=1

    # TELEGRAM
    apply_json_val "telegram" ".enabled" "/mnt/config/telegram.conf" "TELEGRAM_ENABLE" || _changes=1
    apply_json_val "telegram" ".token" "/mnt/config/telegram.conf" "apiToken" || _changes=1
    apply_json_val "telegram" ".chat_id" "/mnt/config/telegram.conf" "userChatId" || _changes=1

    # SYSLOG
    apply_json_val "syslog" ".enabled" "/mnt/config/boot.conf" "SYSLOG_ENABLE" || _changes=1
    apply_json_val "syslog" ".host" "/mnt/config/boot.conf" "SYSLOG_HOST" || _changes=1
    apply_json_val "syslog" ".port" "/mnt/config/boot.conf" "SYSLOG_PORT" || _changes=1

    # PERIPHERALS
    apply_json_val "peripherals" ".led_front" "/mnt/config/boot.conf" "FRONT_LED" || _changes=1
    apply_json_val "peripherals" ".led_red" "/mnt/config/boot.conf" "RED_LED" || _changes=1
    apply_json_val "peripherals" ".privacy" "/mnt/config/boot.conf" "PRIVACY_MODE" || _changes=1

    # Finalize
    if [ "$_changes" = "1" ]; then
      # Re-trigger services if needed (async)
      (
        sleep 2
        /mnt/controlscripts/rtsp-h26x restart >/dev/null 2>&1
        /mnt/controlscripts/mqtt-bridge restart >/dev/null 2>&1
      ) >/dev/null 2>&1 &
      
      json_response "success" "Config imported successfully. Restarting affected services..."
    else
      json_response "success" "No changes applied."
    fi
    
    rm -f "$_tmp_json"
    ;;

  *)
    output_json_header
    echo ""
    json_error "UNKNOWN_COMMAND" "Command '$F_cmd' not recognized"
    ;;
esac
