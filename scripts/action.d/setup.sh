# shellcheck shell=sh
# action.cgi commands: Setup wizard.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    complete_setup_wizard)
      csrf_check
      if wants_json_response; then
        json_body_err "FORMAT_NOT_SUPPORTED" "complete_setup_wizard command does not support JSON format"
      else
        install_config /mnt/config/boot.conf
      install_config /mnt/config/service_trim.conf
      wizard_password=$(printf '%b' "${F_wizard_password//%/\\x}")
      wizard_profile=$(printf '%s' "${F_wizard_profile}")
      wizard_tz=$(printf '%b' "${F_wizard_tz//%/\\x}")
      wizard_ntp_srv=$(printf '%b' "${F_wizard_ntp_srv//%/\\x}")
      wizard_hostname=$(printf '%b' "${F_wizard_hostname//%/\\x}")
      wizard_enable_ntp=$(normalize_bool "${F_wizard_enable_ntp}")

      [ -n "$wizard_profile" ] || wizard_profile="universal-h264"

      case "$wizard_password" in
        ''|'*****')
          wizard_password=""
          ;;
      esac

      if credentials_default_active; then
        if [ -z "$wizard_password" ] || [ "$wizard_password" = "pass" ]; then
          echo "Setup wizard requires changing default credentials before completion.<br/>"
          exit 0
        fi
      fi

      if [ -n "$wizard_password" ] && [ "${#wizard_password}" -lt 4 ]; then
        echo "Password too short. Use at least 4 characters.<br/>"
        exit 0
      fi

      capture_prechange_stream_snapshot
      if ! select_compat_profile_values "$wizard_profile"; then
        echo "Unknown compatibility preset '$wizard_profile'<br/>"
        exit 0
      fi

      if [ -n "$wizard_password" ]; then
        all_password "$wizard_password"
        restart_service_if_need /mnt/controlscripts/ftp-server
        restart_service_if_need /mnt/controlscripts/telnet-server
        echo "All service passwords updated.<br/>"
      fi

      if [ -z "$wizard_tz" ]; then
        wizard_tz="$(cat /mnt/config/timezone.conf 2>/dev/null)"
      fi
      [ -n "$wizard_tz" ] || wizard_tz="UTC0"
      echo "$wizard_tz" > /mnt/config/timezone.conf

      wizard_ntp_srv="$(printf '%s' "$wizard_ntp_srv" | sed 's/[^A-Za-z0-9._:-]//g')"
      if [ -z "$wizard_ntp_srv" ]; then
        wizard_ntp_srv="$(cat /mnt/config/ntp_srv.conf 2>/dev/null)"
      fi
      [ -n "$wizard_ntp_srv" ] || wizard_ntp_srv="pool.ntp.org"
      echo "$wizard_ntp_srv" > /mnt/config/ntp_srv.conf

      wizard_hostname="$(printf '%s' "$wizard_hostname" | sed 's/[^A-Za-z0-9._-]//g')"
      if [ -n "$wizard_hostname" ]; then
        echo "$wizard_hostname" > /mnt/config/hostname.conf
        hostname "$wizard_hostname" >/dev/null 2>&1 || true
      fi

      rewrite_config /mnt/config/boot.conf ENABLE_NTP "$wizard_enable_ntp"
      if [ "$wizard_enable_ntp" = "1" ]; then
        if /mnt/bin/busybox ntpd -q -n -p "$wizard_ntp_srv" >/dev/null 2>&1; then
          echo "NTP sync successful.<br/>"
        else
          echo "NTP sync failed (check server/network).<br/>"
        fi
      fi

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

      if finalize_stream_apply "setup-wizard:${wizard_profile}"; then
        _ac_now
        [ -n "$now_ts" ] || now_ts=0
        rewrite_config /mnt/config/boot.conf SETUP_WIZARD_DONE 1
        rewrite_config /mnt/config/boot.conf SETUP_WIZARD_EPOCH "$now_ts"
        if [ "$low_cpu_profile" = "1" ]; then
          apply_low_cpu_background_defaults
        fi
        echo "Setup wizard completed.<br/>"
        echo "Compatibility preset: $profile_label<br/>"
        echo "Timezone: $wizard_tz, NTP: $wizard_ntp_srv (ENABLE_NTP=$wizard_enable_ntp)<br/>"
        publish_mqtt_event "$(printf '{"ts":%s,"type":"setup_wizard","profile":"%s"}' "$now_ts" "$wizard_profile")"
      fi
      fi
    ;;

    wizard_reset)
        rm -f /mnt/config/.wizard3_done /mnt/config/.wizard_done 2>/dev/null || true
        touch /tmp/.first_boot 2>/dev/null || true
        json_body_ok "Wizard reset. Redirecting to setup wizard."
    ;;
  esac
