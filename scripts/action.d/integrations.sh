# shellcheck shell=sh
# action.cgi commands: MQTT and Home Assistant.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    refresh_ha_discovery)
      csrf_check
      if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
        /mnt/scripts/mqtt-bridge.sh discovery > /dev/null 2>&1
        if wants_json_response; then
          json_body_ok "Home Assistant Discovery refresh triggered."
        else
          echo "Home Assistant Discovery refresh triggered.<br/>"
        fi
      else
        if wants_json_response; then
          json_body_err "BRIDGE_MISSING" "MQTT bridge script missing."
        else
          echo "Error: MQTT bridge script missing.<br/>"
        fi
      fi
    ;;

    set_mqtt_config)
      csrf_check
      install_config /mnt/config/mqtt.conf

      mqtt_enable=$(normalize_bool "${F_mqtt_enable}")
      mqtt_host=$(printf '%s' "${F_mqtt_host}")
      mqtt_port=$(sanitize_int_range "${F_mqtt_port}" 1 65535 1883)
      mqtt_user=$(printf '%s' "${F_mqtt_user}")
      # The settings form only posts the fields it shows: a missing or empty password keeps the saved one
      mqtt_password="${F_mqtt_password:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_PASSWORD "")}"
      mqtt_client_id="${F_mqtt_client_id:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_CLIENT_ID tc100-camera)}"
      mqtt_topic_root=$(printf '%s' "${F_mqtt_topic_root}")
      mqtt_topic_command="${F_mqtt_topic_command:-}"
      mqtt_qos=$(sanitize_int_range "${F_mqtt_qos:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_QOS 0)}" 0 2 0)
      mqtt_health_interval_seconds=$(sanitize_int_range "${F_mqtt_health_interval_seconds:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_HEALTH_INTERVAL_SECONDS 120)}" 10 86400 120)
      mqtt_health_slow_cache_ttl_seconds=$(sanitize_int_range "$(read_kv_or_default /mnt/config/mqtt.conf MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS 180)" 10 86400 180)
      mqtt_command_wait_seconds=$(sanitize_int_range "${F_mqtt_command_wait_seconds:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_COMMAND_WAIT_SECONDS 12)}" 3 120 12)
      mqtt_command_repeat_window_seconds=$(sanitize_int_range "${F_mqtt_command_repeat_window_seconds:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_COMMAND_REPEAT_WINDOW_SECONDS 20)}" 0 600 20)
      mqtt_subscribe_backoff_initial_seconds=$(sanitize_int_range "${F_mqtt_subscribe_backoff_initial_seconds:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS 2)}" 1 60 2)
      mqtt_subscribe_backoff_max_seconds=$(sanitize_int_range "${F_mqtt_subscribe_backoff_max_seconds:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS 20)}" 1 600 20)
      mqtt_subscribe_backoff_multiplier=$(sanitize_int_range "${F_mqtt_subscribe_backoff_multiplier:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER 2)}" 1 5 2)
      # the settings form names the checkbox mqtt_discovery
      mqtt_ha_discovery_enable=$(normalize_bool "${F_mqtt_ha_discovery_enable:-$F_mqtt_discovery}")
      mqtt_ha_discovery_prefix="${F_mqtt_ha_discovery_prefix:-$(read_kv_or_default /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_PREFIX homeassistant)}"
      power_estimate_enable=$(normalize_bool "${F_power_estimate_enable:-$(read_kv_or_default /mnt/config/mqtt.conf POWER_ESTIMATE_ENABLE 0)}")
      power_estimate_base_mw=$(sanitize_int_range "${F_power_estimate_base_mw:-$(read_kv_or_default /mnt/config/mqtt.conf POWER_ESTIMATE_BASE_MW 1700)}" 500 10000 1700)
      power_estimate_cpu_scale_mw=$(sanitize_int_range "${F_power_estimate_cpu_scale_mw:-$(read_kv_or_default /mnt/config/mqtt.conf POWER_ESTIMATE_CPU_SCALE_MW 500)}" 0 5000 500)
      power_estimate_ir_led_mw=$(sanitize_int_range "${F_power_estimate_ir_led_mw:-$(read_kv_or_default /mnt/config/mqtt.conf POWER_ESTIMATE_IR_LED_MW 700)}" 0 5000 700)
      power_sensor_path="${F_power_sensor_path:-$(read_kv_or_default /mnt/config/mqtt.conf POWER_SENSOR_PATH auto)}"

      case "$mqtt_host" in
        ''|*[!A-Za-z0-9._:-]*)
          echo "Invalid broker host. Allowed characters: letters, numbers, dot, dash, underscore, colon.<br/>"
          exit 0
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
      rewrite_config /mnt/config/mqtt.conf MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS "$mqtt_health_slow_cache_ttl_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_COMMAND_WAIT_SECONDS "$mqtt_command_wait_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_COMMAND_REPEAT_WINDOW_SECONDS "$mqtt_command_repeat_window_seconds"
      if [ "$mqtt_subscribe_backoff_max_seconds" -lt "$mqtt_subscribe_backoff_initial_seconds" ]; then
        mqtt_subscribe_backoff_max_seconds="$mqtt_subscribe_backoff_initial_seconds"
      fi
      rewrite_config /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS "$mqtt_subscribe_backoff_initial_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS "$mqtt_subscribe_backoff_max_seconds"
      rewrite_config /mnt/config/mqtt.conf MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER "$mqtt_subscribe_backoff_multiplier"
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
      echo "Retry backoff: initial=${mqtt_subscribe_backoff_initial_seconds}s, max=${mqtt_subscribe_backoff_max_seconds}s, multiplier=x${mqtt_subscribe_backoff_multiplier}<br/>"
      echo "HA discovery=${mqtt_ha_discovery_enable} (prefix=${mqtt_ha_discovery_prefix}), power_estimate=${power_estimate_enable}, base=${power_estimate_base_mw}mW, cpu_scale=${power_estimate_cpu_scale_mw}mW, ir_led=${power_estimate_ir_led_mw}mW<br/>"
      rm -f /tmp/health_snapshot.cache 2>/dev/null || true
    ;;

    pair_home_assistant)
      install_config /mnt/config/boot.conf
      install_config /mnt/config/mqtt.conf

      ha_broker_host="$(printf '%s' "${F_ha_broker_host}")"
      ha_broker_port="$(sanitize_int_range "${F_ha_broker_port}" 1 65535 1883)"
      ha_user="$(printf '%s' "${F_ha_user}")"
      ha_password="$(printf '%s' "${F_ha_password}")"
      ha_client_id="$(printf '%s' "${F_ha_client_id}")"
      ha_topic_root="$(printf '%s' "${F_ha_topic_root}")"
      ha_discovery_prefix="$(printf '%s' "${F_ha_discovery_prefix}")"
      ha_profile="$(printf '%s' "${F_ha_profile}")"
      ha_enable_onvif="$(normalize_bool "${F_ha_enable_onvif}")"
      ha_enable_mqtt_autostart="$(normalize_bool "${F_ha_enable_mqtt_autostart}")"

      case "$ha_broker_host" in
        ''|*[!A-Za-z0-9._:-]*)
          echo "Invalid broker host. Allowed characters: letters, numbers, dot, dash, underscore, colon.<br/>"
          exit 0
          ;;
      esac

      ha_client_id="$(printf '%s' "$ha_client_id" | sed 's/[^A-Za-z0-9._-]/-/g')"
      [ -n "$ha_client_id" ] || ha_client_id="tc100-camera"

      ha_topic_root="$(printf '%s' "$ha_topic_root" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      [ -n "$ha_topic_root" ] || ha_topic_root="tc100/camera"

      ha_discovery_prefix="$(printf '%s' "$ha_discovery_prefix" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
      [ -n "$ha_discovery_prefix" ] || ha_discovery_prefix="homeassistant"

      [ -n "$ha_profile" ] || ha_profile="frigate-balanced"
      if ! select_compat_profile_values "$ha_profile"; then
        echo "Unknown compatibility preset '$ha_profile'<br/>"
        exit 0
      fi

      ha_topic_command="${ha_topic_root}/command"

      rewrite_config /mnt/config/mqtt.conf MQTT_ENABLE 1
      rewrite_config /mnt/config/mqtt.conf MQTT_HOST "$ha_broker_host"
      rewrite_config /mnt/config/mqtt.conf MQTT_PORT "$ha_broker_port"
      rewrite_config /mnt/config/mqtt.conf MQTT_USER "$ha_user"
      rewrite_config /mnt/config/mqtt.conf MQTT_PASSWORD "$ha_password"
      rewrite_config /mnt/config/mqtt.conf MQTT_CLIENT_ID "$ha_client_id"
      rewrite_config /mnt/config/mqtt.conf MQTT_TOPIC_ROOT "$ha_topic_root"
      rewrite_config /mnt/config/mqtt.conf MQTT_TOPIC_COMMAND "$ha_topic_command"
      rewrite_config /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_ENABLE 1
      rewrite_config /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_PREFIX "$ha_discovery_prefix"

      capture_prechange_stream_snapshot
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          0 width        "$width0" \
          0 height       "$height0" \
          0 fps          "$fps0" \
          0 bps          "$bps0" \
          0 goplen       "$gop0" \
          0 brmode       1 \
          0 codec        "$codec0" \
          0 profile      "$profile0" \
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
          1 codec        "$codec1" \
          1 profile      "$profile1" \
          1 smartmode    1 \
          1 smartgoplen  "$gop1" \
          1 smartquality "$smartq1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      # RTSP_AUDIO controls publication of the audio tracks. Keep the configured
      # codec values: codec=0 prevents rtsp-h26x startup on the AK3918 firmware.

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$onvif_policy"
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0
      rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE "$low_cpu_profile"
      if finalize_stream_apply "ha-pair:${ha_profile}"; then
        if [ "$low_cpu_profile" = "1" ]; then
          apply_low_cpu_background_defaults
        fi

        ensure_autostart_script rtsp-h26x >/dev/null 2>&1 || true
        /mnt/controlscripts/rtsp-h26x start >/dev/null 2>&1 || true

        if [ "$ha_enable_onvif" = "1" ]; then
          ensure_autostart_script onvif >/dev/null 2>&1 || true
          /mnt/controlscripts/onvif start >/dev/null 2>&1 || true
        else
          rm -f /mnt/config/autostart/onvif >/dev/null 2>&1 || true
          /mnt/controlscripts/onvif stop >/dev/null 2>&1 || true
        fi

        if [ "$ha_enable_mqtt_autostart" = "1" ]; then
          ensure_autostart_script mqtt-bridge >/dev/null 2>&1 || true
        else
          rm -f /mnt/config/autostart/mqtt-bridge >/dev/null 2>&1 || true
        fi
        if [ -x /mnt/controlscripts/mqtt-bridge ]; then
          /mnt/controlscripts/mqtt-bridge stop >/dev/null 2>&1 || true
          /mnt/controlscripts/mqtt-bridge start >/dev/null 2>&1 || true
        fi

        rtsp_health_ok=0
        onvif_health_ok=0
        mqtt_publish_ok=0

        if [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x health >/dev/null 2>&1; then
          rtsp_health_ok=1
        fi
        if [ "$ha_enable_onvif" = "1" ] && [ -x /mnt/controlscripts/onvif ] && /mnt/controlscripts/onvif health >/dev/null 2>&1; then
          onvif_health_ok=1
        fi

        _ac_now
        [ -n "$now_ts" ] || now_ts=0
        mqtt_test_payload="$(printf '{"ts":%s,"type":"ha_pair_test","profile":"%s"}' "$now_ts" "$ha_profile")"
        if [ -x /mnt/scripts/mqtt-bridge.sh ] && /mnt/scripts/mqtt-bridge.sh publish event "$mqtt_test_payload" 0 >/dev/null 2>&1; then
          mqtt_publish_ok=1
        fi

        echo "Home Assistant pairing applied.<br/>"
        echo "Compatibility preset: $profile_label<br/>"
        echo "Broker: ${ha_broker_host}:${ha_broker_port}, discovery prefix: ${ha_discovery_prefix}<br/>"
        echo "Topics: root=${ha_topic_root}, command=${ha_topic_command}<br/>"
        echo "Autostart: RTSP=on, ONVIF=${ha_enable_onvif}, MQTT=${ha_enable_mqtt_autostart}<br/>"
        if [ "$rtsp_health_ok" = "1" ]; then
          echo "RTSP health check: OK<br/>"
        else
          echo "RTSP health check: FAILED (check video profile/network)<br/>"
        fi
        if [ "$ha_enable_onvif" = "1" ]; then
          if [ "$onvif_health_ok" = "1" ]; then
            echo "ONVIF health check: OK<br/>"
          else
            echo "ONVIF health check: FAILED (check ONVIF service/network)<br/>"
          fi
        else
          echo "ONVIF health check: skipped (disabled)<br/>"
        fi
        if [ "$mqtt_publish_ok" = "1" ]; then
          echo "MQTT publish test: OK (discovery should republish at MQTT bridge start)<br/>"
        else
          echo "MQTT publish test: FAILED (check broker credentials/reachability)<br/>"
        fi
        echo "Quick links: /onvif/device_service, rtsp://CAMERA-IP:554/video0_unicast, rtsp://CAMERA-IP:554/video1_unicast<br/>"
        echo "Integration manifest: /cgi-bin/state.cgi?cmd=integrationmanifest<br/>"

        publish_mqtt_event "$(printf '{"ts":%s,"type":"ha_pair","profile":"%s","rtsp_ok":%s,"onvif_ok":%s,"mqtt_ok":%s}' "$now_ts" "$ha_profile" "$rtsp_health_ok" "$onvif_health_ok" "$mqtt_publish_ok")"
      fi
    ;;
  esac
