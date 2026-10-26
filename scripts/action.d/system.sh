# shellcheck shell=sh
# action.cgi commands: System: power, services, accounts, time, profiles, presets.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    reboot)
      csrf_check
      if wants_json_response; then
        json_body_ok "Rebooting device..."
      else
        echo "Rebooting device..."
      fi
      _ac_now
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"reboot","source":"action.cgi"}' "$now_ts")"
      /bin/sh /mnt/scripts/reboot-tracker.sh intent "web UI reboot (${REMOTE_ADDR:-?})" >/dev/null 2>&1
      /sbin/reboot
    ;;

    shutdown)
      csrf_check
      if wants_json_response; then
        json_body_ok "Shutting down device.."
      else
        echo "Shutting down device.."
      fi
      /bin/sh /mnt/scripts/reboot-tracker.sh intent "web UI shutdown (${REMOTE_ADDR:-?})" >/dev/null 2>&1
      /sbin/halt
    ;;

    clear_mem)
      sync
      echo 3 > /proc/sys/vm/drop_caches
      if wants_json_response; then
        json_body_ok "System caches cleared. Memory freed."
      else
        echo "System caches cleared. Memory freed.<br/>"
      fi
    ;;


    set_telnet)
      if security_hardening_enabled; then
        if wants_json_response; then
          json_body_err "SECURITY_HARDENING_ENABLED" "Telnet changes are blocked."
        else
          echo "<p>Security hardening is enabled. Telnet changes are blocked.</p>"
        fi
        exit 0
      fi
      telnetport=$(printf '%s' "${F_telnetport}")
      case "$telnetport" in
        ''|*[!0-9]*)
          if wants_json_response; then
            json_body_err "INVALID_PORT" "Invalid telnet port. Allowed range is 1-65535."
          else
            echo "<p>Invalid telnet port. Allowed range is 1-65535.</p>"
          fi
          ;;
        *)
          if [ "$telnetport" -lt 1 ] || [ "$telnetport" -gt 65535 ]; then
            if wants_json_response; then
              json_body_err "INVALID_PORT" "Invalid telnet port. Allowed range is 1-65535."
            else
              echo "<p>Invalid telnet port. Allowed range is 1-65535.</p>"
            fi
          else
            echo "TELNET_PORT=$telnetport" > /mnt/config/telnetd.conf
            restart_service_if_need /mnt/controlscripts/telnet-server
            if wants_json_response; then
              json_body_ok "Setting telnet service port to: $telnetport"
            else
              echo "<p>Setting telnet service port to : $telnetport</p>"
            fi
          fi
          ;;
      esac
    ;;

    set_ftp)
      if security_hardening_enabled; then
        if wants_json_response; then
          json_body_err "SECURITY_HARDENING_ENABLED" "FTP changes are blocked."
        else
          echo "<p>Security hardening is enabled. FTP changes are blocked.</p>"
        fi
        exit 0
      fi
      ftpport=$(printf '%s' "${F_ftpport}")
      case "$ftpport" in
        ''|*[!0-9]*)
          if wants_json_response; then
            json_body_err "INVALID_PORT" "Invalid ftp port. Allowed range is 1-65535."
          else
            echo "<p>Invalid ftp port. Allowed range is 1-65535.</p>"
          fi
          ;;
        *)
          if [ "$ftpport" -lt 1 ] || [ "$ftpport" -gt 65535 ]; then
            if wants_json_response; then
              json_body_err "INVALID_PORT" "Invalid ftp port. Allowed range is 1-65535."
            else
              echo "<p>Invalid ftp port. Allowed range is 1-65535.</p>"
            fi
          else
            if wants_json_response; then
              json_body_ok "Setting ftp service port to: $ftpport"
            else
              echo "<p>Setting ftp service port to: $ftpport</p>"
            fi
            echo "PORT=$ftpport" > /mnt/config/ftp.conf
            start_service_if_need /mnt/controlscripts/ftp-server
          fi
          ;;
      esac
    ;;

    settz)
       ntp_srv=$(printf '%s' "${F_ntp_srv}")

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
      hst=$(printf '%s' "${F_hostname}")
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
      password_raw="${F_password}"
      [ -n "$password_raw" ] || password_raw="${F_httppassword}"
      password=$(printf '%b' "${password_raw//%/\\x}")
      if [ -z "$password" ] || [ "$password" = "*****" ]; then
        echo "<p>Refusing empty/placeholder HTTP password.</p>"
        exit 0
      fi
      echo "<p>Setting http password to : $password</p>"
      http_password "$password"
    ;;

    set_all_password)
      password_raw="${F_password}"
      [ -n "$password_raw" ] || password_raw="${F_allpassword}"
      password=$(printf '%b' "${password_raw//%/\\x}")
      # Characters that the passwd/htdigest/rtspserver.conf writers cannot
      # carry safely are refused (the form says so too).
      case "$password" in
        ''|'*****') _pw_err="Refusing an empty password." ;;
        *[\"\'\$\`\\\ %]*|*"$(printf '\t')"*) _pw_err="Refused: no spaces, quotes, %, \$, \` or \\ in the password." ;;
        *) _pw_err="" ;;
      esac
      [ ${#password} -lt 6 ] && [ -z "$_pw_err" ] && _pw_err="The password needs at least 6 characters."
      if [ -n "$_pw_err" ]; then
        if wants_json_response; then json_body_err "INVALID_VALUE" "$_pw_err"; else echo "<p>$_pw_err</p>"; fi
        exit 0
      fi
      if wants_json_response; then json_body_ok "Password changed for the web interface, RTSP, FTP and telnet."
      else echo "<p>Password changed for the web interface, RTSP, FTP and telnet.</p>"; fi
      all_password "$password"
      restart_service_if_need /mnt/controlscripts/ftp-server
      restart_service_if_need /mnt/controlscripts/telnet-server
      schedule_rtsp_restart
    ;;

    service_trim_on)
      install_config /mnt/config/service_trim.conf
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 1
      echo "Service trimming enabled. Non-essential services will stop; reboot for full effect.<br/>"

      for svc in ftp-server telnet-server motion-detection auto-night-detection front-led night-mode network-monitor; do
        if [ -x "/mnt/controlscripts/$svc" ]; then
          /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
        fi
      done
      rm -f /tmp/health_snapshot.cache 2>/dev/null || true
    ;;

    service_trim_off)
      install_config /mnt/config/service_trim.conf
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0
      echo "Service trimming disabled. Reboot to restore autostart services.<br/>"
      rm -f /tmp/health_snapshot.cache 2>/dev/null || true
    ;;

    set_performance_profile)
      install_config /mnt/config/boot.conf
      install_config /mnt/config/service_trim.conf
      capture_prechange_stream_snapshot
      profile=$(printf '%s' "${F_performance_profile}")
      profile_summary_line=""
      profile_detail_line=""
      profile_detail_line2=""
      apply_low_cpu_defaults_after_finalize=0
      stop_trimmed_services_after_finalize=0

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

          profile_summary_line="Performance profile set to Balanced."
          profile_detail_line="Dual stream + audio defaults enabled; reboot to restore all background services if they were trimmed."
          ;;
        low-cpu)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 1
          rewrite_config /mnt/config/boot.conf LOW_RAM_PROFILE 1
          rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_OSD 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG 1
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 0
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-only
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 0
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0

          # Apply conservative stream settings immediately.
          /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
              0 width 640 0 height 360 0 fps 10 0 bps 600 0 goplen 20 0 brmode 1 0 codec 0 0 profile 1 \
              0 smartmode 1 0 smartgoplen 20 0 smartquality 60 0 smartstatic 350 0 maxkbps 800 0 targetkbps 600 \
              1 width 352 1 height 200 1 fps 5 1 bps 120 1 goplen 10 1 brmode 1 1 codec 0 1 profile 0 \
              1 smartmode 1 1 smartgoplen 10 1 smartquality 50 1 smartstatic 100 1 maxkbps 160 1 targetkbps 120
          apply_low_cpu_defaults_after_finalize=1
          profile_summary_line="Performance profile set to Low CPU."
          profile_detail_line="Applied conservative dual-stream RTSP settings now (safe geometry, H264) and enabled memory guard."
          profile_detail_line2="Reboot recommended for full low-CPU service profile."
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

          apply_low_cpu_defaults_after_finalize=1
          stop_trimmed_services_after_finalize=1
          profile_summary_line="Performance profile set to RTSP + ONVIF only."
          profile_detail_line="Stopped non-essential services now; reboot to enforce trimmed autostart persistently."
          ;;
        *)
          echo "Unknown performance profile '$profile'<br/>"
          exit 0
          ;;
      esac

      if finalize_stream_apply "performance-profile:${profile}"; then
        if [ "$apply_low_cpu_defaults_after_finalize" = "1" ]; then
          apply_low_cpu_background_defaults
        fi
        if [ "$stop_trimmed_services_after_finalize" = "1" ]; then
          stop_trimmed_runtime_services
        fi
        sync_memory_guard_service_with_config
        echo "${profile_summary_line}<br/>"
        [ -n "$profile_detail_line" ] && echo "${profile_detail_line}<br/>"
        [ -n "$profile_detail_line2" ] && echo "${profile_detail_line2}<br/>"
        _ac_now
        publish_mqtt_event "$(printf '{"ts":%s,"type":"profile","value":"%s"}' "$now_ts" "$profile")"
      fi
      rm -f /tmp/health_snapshot.cache 2>/dev/null || true
    ;;

    set_web_mode)
      if wants_json_response; then
        json_body_err "FORMAT_NOT_SUPPORTED" "set_web_mode command does not support JSON format"
      else
        install_config /mnt/config/boot.conf
        web_mode=$(printf '%s' "${F_web_mode}")
        ultralite_http_port=$(printf '%s' "${F_ultralite_http_port}")

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
        _ac_now
        publish_mqtt_event "$(printf '{"ts":%s,"type":"web_mode","mode":"%s"}' "$now_ts" "$web_mode")"
        rm -f /tmp/health_snapshot.cache 2>/dev/null || true
      fi
    ;;

    set_reboot_schedule)
      install_config /mnt/config/boot.conf

      reboot_schedule_enable="$(normalize_bool "${F_reboot_enable}")"
      reboot_schedule_minute="$(sanitize_int_range "${F_reboot_min}" 0 59 0)"
      reboot_schedule_hour="$(sanitize_int_range "${F_reboot_hour}" 0 23 4)"
      reboot_schedule_weekday="$(sanitize_weekday_expr "${F_reboot_dow}")"

      # shellcheck disable=SC1090
      if [ -f /mnt/config/boot.conf ]; then
        . /mnt/config/boot.conf
      fi
      current_enable_crond="$(normalize_bool "${ENABLE_CROND}")"

      if [ "$reboot_schedule_enable" = "1" ] && [ "$current_enable_crond" != "1" ]; then
        current_enable_crond=1
        rewrite_config /mnt/config/boot.conf ENABLE_CROND 1
      fi

      rewrite_config /mnt/config/boot.conf REBOOT_SCHEDULE_ENABLE "$reboot_schedule_enable"
      rewrite_config /mnt/config/boot.conf REBOOT_SCHEDULE_MINUTE "$reboot_schedule_minute"
      rewrite_config /mnt/config/boot.conf REBOOT_SCHEDULE_HOUR "$reboot_schedule_hour"
      rewrite_config /mnt/config/boot.conf REBOOT_SCHEDULE_WEEKDAY "$reboot_schedule_weekday"

      sync_managed_reboot_cron "$reboot_schedule_enable" "$reboot_schedule_minute" "$reboot_schedule_hour" "$reboot_schedule_weekday"
      restart_crond_if_enabled "$current_enable_crond"

      if [ "$reboot_schedule_enable" = "1" ]; then
        echo "Scheduled reboot enabled via cron: ${reboot_schedule_minute} ${reboot_schedule_hour} * * ${reboot_schedule_weekday}<br/>"
        if [ "$reboot_schedule_weekday" = "*" ]; then
          echo "Reboot will run daily at $(printf '%02d:%02d' "$reboot_schedule_hour" "$reboot_schedule_minute").<br/>"
        else
          echo "Reboot will run weekly pattern '$reboot_schedule_weekday' at $(printf '%02d:%02d' "$reboot_schedule_hour" "$reboot_schedule_minute").<br/>"
        fi
      else
        echo "Scheduled reboot disabled. Managed cron entry removed.<br/>"
      fi

      if [ "$current_enable_crond" = "1" ]; then
        echo "Crond is enabled and cron schedule has been reloaded.<br/>"
      else
        echo "Warning: crond is disabled in boot config. Enable ENABLE_CROND=1 for schedules to run.<br/>"
      fi

      _ac_now
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"reboot_schedule","enabled":%s,"minute":%s,"hour":%s,"weekday":"%s"}' "$now_ts" "$reboot_schedule_enable" "$reboot_schedule_minute" "$reboot_schedule_hour" "$reboot_schedule_weekday")"
    ;;

    set_telegram_config)
      install_config /mnt/config/telegram.conf
      telegram_enable=$(normalize_bool "${F_telegram_enable}")
      telegram_token=$(printf '%s' "${F_telegram_token}")
      telegram_chat_id=$(printf '%s' "${F_telegram_chat_id}")
      
      rewrite_config /mnt/config/telegram.conf TELEGRAM_ENABLE "$telegram_enable"
      rewrite_config /mnt/config/telegram.conf apiToken "$telegram_token"
      rewrite_config /mnt/config/telegram.conf userChatId "$telegram_chat_id"
      
      if [ -x /mnt/controlscripts/telegram-bot ]; then
        # the boot starts the bot from config/autostart: the switch here survives a restart
        if [ "$telegram_enable" = "1" ]; then
          ensure_autostart_script telegram-bot >/dev/null 2>&1 || true
          /mnt/controlscripts/telegram-bot restart >/dev/null 2>&1 || true
        else
          rm -f /mnt/config/autostart/telegram-bot
          /mnt/controlscripts/telegram-bot stop >/dev/null 2>&1 || true
        fi
      fi
      echo "Telegram configuration updated.<br/>"
    ;;

    set_syslog_config)
      install_config /mnt/config/boot.conf
      syslog_enable=$(normalize_bool "${F_syslog_enable}")
      syslog_host=$(printf '%s' "${F_syslog_host}")
      syslog_port=$(sanitize_int_range "${F_syslog_port}" 1 65535 514)
      # boot.conf is sourced by the shell: only a host name or an IP address
      # (v4 or v6) may go in it.
      syslog_err=""
      case "$syslog_host" in
        *[!A-Za-z0-9.:-]*) syslog_err="The syslog server must be a host name or an IP address (e.g. 192.168.1.10)." ;;
      esac
      [ "${#syslog_host}" -le 253 ] || syslog_err="The syslog server name is too long."
      if [ -z "$syslog_err" ] && [ "$syslog_enable" = "1" ] && [ -z "$syslog_host" ]; then
        syslog_err="Enter the syslog server address (e.g. your NAS: 192.168.1.10) to enable remote logging."
      fi
      if [ -n "$syslog_err" ]; then
        if wants_json_response; then json_body_err "INVALID_VALUE" "$syslog_err"; else echo "<p>$syslog_err</p>"; fi
      else
        rewrite_config /mnt/config/boot.conf SYSLOG_ENABLE "$syslog_enable"
        rewrite_config /mnt/config/boot.conf SYSLOG_HOST "$syslog_host"
        rewrite_config /mnt/config/boot.conf SYSLOG_PORT "$syslog_port"

        if [ -x /mnt/controlscripts/syslog-forward ]; then
          if [ "$syslog_enable" = "1" ]; then
            /mnt/controlscripts/syslog-forward restart >/dev/null 2>&1 || true
          else
            /mnt/controlscripts/syslog-forward stop >/dev/null 2>&1 || true
          fi
        fi
        if [ "$syslog_enable" = "1" ]; then
          echo "Syslog configuration updated: sending to ${syslog_host}:${syslog_port} (UDP).<br/>"
        else
          echo "Syslog configuration updated: remote logging off.<br/>"
        fi
      fi
    ;;

    save_preset)
        preset_name="${F_name:-}"
        preset_data="${F_data:-}"
        presets_dir="/mnt/config/presets"

        mkdir -p "$presets_dir"

        if [ -z "$preset_name" ] || [ -z "$preset_data" ]; then
            if wants_json_response; then
              json_body_err "INVALID_PRESET" "Preset name and data required"
            else
              echo "ERROR: Preset name and data required"
            fi
        else
            # Validate preset name (alphanumeric, underscore, hyphen only).
            # Fork-free case idiom — busybox grep may lack -E (CLAUDE.md), in
            # which case `grep -qE` errored and rejected EVERY name.
            case "$preset_name" in ''|*[!a-zA-Z0-9_-]*) _preset_name_bad=1 ;; *) _preset_name_bad=0 ;; esac
            if [ "$_preset_name_bad" = "1" ]; then
                if wants_json_response; then
                  json_body_err "INVALID_NAME" "Preset name must be alphanumeric with underscore/hyphen only"
                else
                  echo "ERROR: Invalid preset name"
                fi
            else
                # Limit to 10 presets
                preset_count=$(find "$presets_dir" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l)
                preset_file="$presets_dir/$preset_name.json"

                if [ -f "$preset_file" ]; then
                    # Update existing preset
                    printf '%s' "$preset_data" > "$preset_file"
                    if wants_json_response; then
                      json_body_ok "Preset '$preset_name' updated"
                    else
                      echo "Preset '$preset_name' updated"
                    fi
                elif [ "$preset_count" -lt 10 ]; then
                    # Create new preset
                    printf '%s' "$preset_data" > "$preset_file"
                    if wants_json_response; then
                      json_body_ok "Preset '$preset_name' created"
                    else
                      echo "Preset '$preset_name' created"
                    fi
                else
                    if wants_json_response; then
                      json_body_err "PRESET_LIMIT" "Maximum 10 presets allowed"
                    else
                      echo "ERROR: Maximum 10 presets allowed"
                    fi
                fi
            fi
        fi
    ;;

    delete_preset)
        preset_name="${F_name:-}"
        presets_dir="/mnt/config/presets"

        if [ -z "$preset_name" ]; then
            if wants_json_response; then
              json_body_err "INVALID_PRESET" "Preset name required"
            else
              echo "ERROR: Preset name required"
            fi
        else
            # Validate preset name (busybox-safe, no grep -E — see save_preset)
            case "$preset_name" in ''|*[!a-zA-Z0-9_-]*) _preset_name_bad=1 ;; *) _preset_name_bad=0 ;; esac
            if [ "$_preset_name_bad" = "1" ]; then
                if wants_json_response; then
                  json_body_err "INVALID_NAME" "Invalid preset name"
                else
                  echo "ERROR: Invalid preset name"
                fi
            else
                preset_file="$presets_dir/$preset_name.json"
                if [ -f "$preset_file" ]; then
                    rm -f "$preset_file"
                    if wants_json_response; then
                      json_body_ok "Preset '$preset_name' deleted"
                    else
                      echo "Preset '$preset_name' deleted"
                    fi
                else
                    if wants_json_response; then
                      json_body_err "PRESET_NOT_FOUND" "Preset '$preset_name' not found"
                    else
                      echo "ERROR: Preset '$preset_name' not found"
                    fi
                fi
            fi
        fi
    ;;
  esac
