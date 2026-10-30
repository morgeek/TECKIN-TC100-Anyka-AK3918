# shellcheck shell=sh
# action.cgi commands: Image and video settings.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    set_video_params)
      # Supports both stream 0 and 1, plus all advanced SmartVBR/QP tuning
      stream_idx="$(sanitize_int_range "${F_stream}" 0 1 0)"
      
      # Determine which inputs to use based on stream index. tc100_rtsp encodes 1920x1080 and 640x360 at 15 fps
      # whatever the file says: those are written, so that every reader of the file sees the real values.
      if [ "$stream_idx" = "1" ]; then
          raw_size=640x360
          fps=15
          bitrate=$(sanitize_int_range "${F_brbitrate1}" 32 8000 300)
          codec=$(sanitize_int_range "${F_video_codec1}" 0 2 0)
          gop=$(sanitize_int_range "${F_goplen1}" 1 300 50)
          format=$(sanitize_int_range "${F_video_format1}" 0 1 1)
          minqp=$(sanitize_int_range "${F_minqp1}" 10 51 20)
          maxqp=$(sanitize_int_range "${F_maxqp1}" 10 51 45)
          smartmode=$(sanitize_int_range "${F_smartmode1}" 0 2 0)
      else
          raw_size=1920x1080
          fps=15
          bitrate=$(sanitize_int_range "${F_brbitrate0}" 32 8000 1000)
          codec=$(sanitize_int_range "${F_video_codec0}" 0 2 0)
          gop=$(sanitize_int_range "${F_goplen0}" 1 300 50)
          format=$(sanitize_int_range "${F_video_format0}" 0 1 1)
          minqp=$(sanitize_int_range "${F_minqp0}" 10 51 20)
          maxqp=$(sanitize_int_range "${F_maxqp0}" 10 51 45)
          smartmode=$(sanitize_int_range "${F_smartmode0}" 0 2 0)
      fi
      
      width=$(echo "$raw_size" | cut -d'x' -f1)
      height=$(echo "$raw_size" | cut -d'x' -f2)

      if ! /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          "$stream_idx" width "$width" \
          "$stream_idx" height "$height" \
          "$stream_idx" codec "$codec" \
          "$stream_idx" fps "$fps" \
          "$stream_idx" bps "$bitrate" \
          "$stream_idx" goplen "$gop" \
          "$stream_idx" brmode "$format" \
          "$stream_idx" minqp "$minqp" \
          "$stream_idx" maxqp "$maxqp" \
          "$stream_idx" smartmode "$smartmode"; then
        if wants_json_response; then
          json_body_err "CONFIG_WRITE_FAILED" "Settings could not be written. Check the SD card."
        else
          echo "Settings write failed; no restart scheduled.<br/>"
        fi
        exit 0
      fi

      # tc100_rtsp reads bit rate, codec, QP range (main stream, both streams) and keyframe interval at its start
      # (a range with the maximum below the minimum is ignored by rtsp-launch.sh)
      schedule_rtsp_restart
      if wants_json_response; then
        json_body_ok "Video settings for stream $stream_idx updated."
      else
        echo "Video settings for stream $stream_idx updated. RTSP restarting...<br/>"
      fi
    ;;

    isp_pro)
      # Three forms post here: Settings → Day/night (the thresholds), Settings → Privacy & overlay
      # (on-screen clock, osd_form) and Settings → Picture (orientation only). Each part is only
      # written when its fields were sent.
      if [ -n "${F_daynightlum}${F_nightdaylum}" ]; then
        # scripts/auto-night-daemon.sh compares the mean picture luminance (0-255), read while it runs
        _ln=$(sanitize_int_range "${F_daynightlum}" 0 255 40)
        _ld=$(sanitize_int_range "${F_nightdaylum}" 0 255 100)
        [ "$_ld" -gt "$_ln" ] || _ld=$((_ln + 20))
        [ "$_ld" -le 255 ] || _ld=255
        printf 'LUMA_NIGHT=%s\nLUMA_DAY=%s\n' "$_ln" "$_ld" > /mnt/config/daynight.conf
      fi
      if [ -n "${F_osd_form}" ]; then
        osdenabled=$(normalize_bool "${F_osdenabled}")
        osdtext=$(printf '%s' "${F_osdtext}")
        osdfontsize0=$(sanitize_int_range "${F_osdfontsize0}" 8 128 32)
        osdx0=$(sanitize_int_range "${F_osdx0}" 0 2000 20)
        osdy0=$(sanitize_int_range "${F_osdy0}" 0 2000 24)
        osdalpha=$(sanitize_int_range "${F_osdalpha}" 0 255 0)
        frontcolor=$(sanitize_int_range "${F_frontcolor}" 0 7 1)
        backcolor=$(sanitize_int_range "${F_backcolor}" 0 2 0)
        edgecolor=$(sanitize_int_range "${F_edgecolor}" 0 2 2)
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
            " " osdenabled "$osdenabled" \
            " " osdtext "$osdtext" \
            " " osdalpha "$osdalpha" \
            " " osdfrontcolor "$frontcolor" \
            " " osdbackcolor "$backcolor" \
            " " osdedgecolor "$edgecolor" \
            0 osdfontsize "$osdfontsize0" \
            0 osdx "$osdx0" \
            0 osdy "$osdy0"
        /mnt/bin/setconf -k l -v "$osdenabled"
        /mnt/bin/setconf -k o -v "$osdtext"
        /mnt/bin/setconf -k h -v "$osdalpha"
        /mnt/bin/setconf -k c -v "$frontcolor"
        /mnt/bin/setconf -k i -v "$backcolor"
        /mnt/bin/setconf -k j -v "$edgecolor"
        /mnt/bin/setconf -k s -v "$osdfontsize0"
        /mnt/bin/setconf -k x -v "$osdx0"
        /mnt/bin/setconf -k y -v "$osdy0"
      fi
      # Orientation (0 normal, 1 flip = upside down, 2 mirror = left-right, 3 both = rotated 180): the ISP does it
      # at once (setconf -k f -> isp_flip); rtsp-launch.sh applies the stored value after every video start.
      # Settings -> Picture posts only this field: nothing else is touched.
      if [ -n "${F_imageflip+x}" ]; then
        _flip=$(sanitize_int_range "${F_imageflip}" 0 3 0)
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " imageflip "$_flip"
        /mnt/bin/setconf -k f -v "$_flip"
      fi

      if wants_json_response; then
        json_body_ok "ISP and OSD settings updated."
      else
        echo "ISP and OSD settings updated.<br/>"
      fi
    ;;

    isp_tune)
      # Live image tuning (see scripts/isp-tune.sh). Values and the ISP_TUNE switch apply within ~2 s
      # without restarting the stream (tc100_rtsp reloads boot.conf and isp_tune.conf).
      . /mnt/scripts/isp-tune.sh
      _it_bad=""
      for _it_k in $ISP_TUNE_KEYS; do
        case "$_it_k" in
          BRIGHTNESS) _it_in="$F_isp_brightness" ;;
          CONTRAST) _it_in="$F_isp_contrast" ;;
          SATURATION) _it_in="$F_isp_saturation" ;;
          SHARPNESS) _it_in="$F_isp_sharpness" ;;
          HUE) _it_in="$F_isp_hue" ;;
          POWER_HZ) _it_in="$F_isp_power_hz" ;;
          EXPOSURE_MAX_PCT) _it_in="$F_isp_exposure_max_pct" ;;
        esac
        isp_tune_norm "$_it_k" "$_it_in" >/dev/null || _it_bad="$_it_bad $_it_k"
      done
      for _it_k in $ISP_MASK_KEYS; do
        case "$_it_k" in
          MASK1) _it_in="$F_isp_mask1" ;; MASK2) _it_in="$F_isp_mask2" ;;
          MASK3) _it_in="$F_isp_mask3" ;; MASK4) _it_in="$F_isp_mask4" ;;
          MASK_COLOR) _it_in="$F_isp_mask_color" ;;
        esac
        isp_tune_norm "$_it_k" "$_it_in" >/dev/null || _it_bad="$_it_bad $_it_k"
      done
      if [ -n "$_it_bad" ]; then
        if wants_json_response; then json_body_err "INVALID_VALUE" "Invalid value for:$_it_bad"; else echo "Invalid value for:$_it_bad<br/>"; fi
        exit 0
      fi
      # Only the keys the form posted: a partial form (or an old page) must not reset values set elsewhere (MQTT).
      # POWER_HZ has no field on 3.0 (not applied by the ISP code).
      [ -n "${F_isp_brightness+x}" ] && isp_tune_set BRIGHTNESS "$F_isp_brightness"
      [ -n "${F_isp_contrast+x}" ] && isp_tune_set CONTRAST "$F_isp_contrast"
      [ -n "${F_isp_saturation+x}" ] && isp_tune_set SATURATION "$F_isp_saturation"
      [ -n "${F_isp_sharpness+x}" ] && isp_tune_set SHARPNESS "$F_isp_sharpness"
      [ -n "${F_isp_hue+x}" ] && isp_tune_set HUE "$F_isp_hue"
      [ -n "${F_isp_power_hz+x}" ] && isp_tune_set POWER_HZ "$F_isp_power_hz"
      [ -n "${F_isp_exposure_max_pct+x}" ] && isp_tune_set EXPOSURE_MAX_PCT "$F_isp_exposure_max_pct"
      for _it_k in $ISP_MASK_KEYS; do
        case "$_it_k" in
          MASK1) _it_in="$F_isp_mask1" ;; MASK2) _it_in="$F_isp_mask2" ;;
          MASK3) _it_in="$F_isp_mask3" ;; MASK4) _it_in="$F_isp_mask4" ;;
          MASK_COLOR) _it_in="$F_isp_mask_color" ;;
        esac
        # Old pages (no mask fields): leave the masks as they are.
        [ -n "${F_isp_mask_form:-}" ] || continue
        isp_tune_set "$_it_k" "$_it_in" || continue
      done
      # The tuning switch is only touched by the form that has it (Settings -> Picture: sliders or the
      # switch posted). The mask form (Privacy & overlay) posts only mask fields: the masks apply whatever
      # the switch is (tc100_rtsp), and it must not switch live tuning off.
      _it_want="$(isp_tune_enabled)"
      if [ -n "${F_isp_enable+x}" ] || [ -n "${F_isp_brightness+x}" ]; then
        _it_want="$(normalize_bool "${F_isp_enable}")"
      fi
      _it_msg="Image settings saved; applied within a few seconds."
      if [ "$_it_want" != "$(isp_tune_enabled)" ]; then
        install_config /mnt/config/boot.conf
        rewrite_config /mnt/config/boot.conf ISP_TUNE "$_it_want"
        _it_msg="Image tuning $( [ "$_it_want" = 1 ] && echo enabled || echo disabled ); applied within a few seconds."
      fi
      if wants_json_response; then json_body_ok "$_it_msg"; else echo "$_it_msg<br/>"; fi
    ;;

    set_advanced_tuning)
      install_config /mnt/config/boot.conf
      lightweight=$(normalize_bool "${F_lightweight_mode}")
      hardening=$(normalize_bool "${F_security_hardening}")

      # Mem Guard settings
      mg_enable=$(normalize_bool "${F_mem_guard_enable}")
      mg_warn=$(sanitize_int_range "${F_mem_guard_warn}" 1024 32768 8192)
      mg_crit=$(sanitize_int_range "${F_mem_guard_crit}" 512 16384 4096)
      mg_interval=$(sanitize_int_range "${F_mem_guard_interval}" 5 600 20)

      # Persist to boot.conf
      rewrite_config /mnt/config/boot.conf LIGHTWEIGHT_MODE "$lightweight"
      rewrite_config /mnt/config/boot.conf SECURITY_HARDENING_MODE "$hardening"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_ENABLE "$mg_enable"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_WARN_KB "$mg_warn"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_CRITICAL_KB "$mg_crit"
      rewrite_config /mnt/config/boot.conf MEM_GUARD_INTERVAL_SECONDS "$mg_interval"

      if wants_json_response; then
        json_body_ok "Advanced tuning updated. Reboot may be required."
      else
        echo "Advanced tuning updated.<br/>"
      fi
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

    toggle-rtsp-nightvision-on)
      /mnt/bin/setconf -k n -v 1
    ;;

    toggle-rtsp-nightvision-off)
      /mnt/bin/setconf -k n -v 0
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

    enable_privacy_shield)
      install_config /mnt/config/boot.conf
      # Privacy Shield: Stop all non-essential outbound/inbound services.
      for svc in telegram-bot syslog-forward mqtt-bridge ftp-server telnet-server; do
        if [ -x "/mnt/controlscripts/$svc" ]; then
          "/mnt/controlscripts/$svc" stop >/dev/null 2>&1 || true
        fi
      done
      rewrite_config /mnt/config/boot.conf PRIVACY_MODE 1
      echo "Privacy Shield activated: Cloud & outbound services disabled.<br/>"
      _ac_now
      [ -n "$now_ts" ] || now_ts=0
      publish_mqtt_event "$(printf '{"ts":%s,"type":"privacy_shield","enabled":1}' "$now_ts")"
    ;;

    set_video_size)
      capture_prechange_stream_snapshot
      safe_values_changed=0
      wh0=${F_video_size0}
      width0="${wh0%x*}"
      height0="${wh0#*x}"
      req_width0="$width0"
      req_height0="$height0"

      wh1=${F_video_size1}
      width1="${wh1%x*}"
      height1="${wh1#*x}"
      req_width1="$width1"
      req_height1="$height1"

      codec0="$(sanitize_video_codec "${F_video_codec0}")"
      codec1="$(sanitize_video_codec "${F_video_codec1}")"

      normalize_stream_geometry "$width0" "$height0" "$codec0" 1280 720
      width0="$NORMALIZED_STREAM_WIDTH"
      height0="$NORMALIZED_STREAM_HEIGHT"
      codec0="$NORMALIZED_STREAM_CODEC"

      normalize_stream_geometry "$width1" "$height1" "$codec1" 352 200
      width1="$NORMALIZED_STREAM_WIDTH"
      height1="$NORMALIZED_STREAM_HEIGHT"
      codec1="$NORMALIZED_STREAM_CODEC"

      username=$(printf '%b' "${F_videouser//%/\\x}")
      userpassword=$(printf '%b' "${F_videopassword//%/\\x}")
      videoport="$(sanitize_int_range "${F_videoport}" 1 65535 554)"

      bps0="$(sanitize_int_range "${F_brbitrate0}" 64 12000 2000)"
      bps1="$(sanitize_int_range "${F_brbitrate1}" 64 4000 300)"
      brmode0="$(sanitize_video_brmode "${F_video_format0}")"
      brmode1="$(sanitize_video_brmode "${F_video_format1}")"
      fps0="$(sanitize_int_range "${F_fps0}" 1 25 20)"
      fps1="$(sanitize_int_range "${F_fps1}" 1 25 10)"
      goplen0="$(sanitize_int_range "${F_goplen0}" 1 120 50)"
      goplen1="$(sanitize_int_range "${F_goplen1}" 1 120 20)"
      minqp0="$(sanitize_int_range "${F_minqp0}" 1 51 20)"
      minqp1="$(sanitize_int_range "${F_minqp1}" 1 51 20)"
      maxqp0="$(sanitize_int_range "${F_maxqp0}" 1 51 51)"
      maxqp1="$(sanitize_int_range "${F_maxqp1}" 1 51 51)"
      if [ "$minqp0" -gt "$maxqp0" ]; then
        minqp0="$maxqp0"
      fi
      if [ "$minqp1" -gt "$maxqp1" ]; then
        minqp1="$maxqp1"
      fi
      profile0="$(sanitize_codec_profile_for_codec "$codec0" "${F_codec_profile0}" 0)"
      profile1="$(sanitize_codec_profile_for_codec "$codec1" "${F_codec_profile1}" 1)"
      smartmode0="$(sanitize_video_smartmode "${F_smartmode0}")"
      smartmode1="$(sanitize_video_smartmode "${F_smartmode1}")"
      smartgoplen0="$(sanitize_int_range "${F_smartgoplen0}" 1 600 "$goplen0")"
      smartgoplen1="$(sanitize_int_range "${F_smartgoplen1}" 1 600 "$goplen1")"
      smartquality0="$(sanitize_int_range "${F_smartquality0}" 1 100 80)"
      smartquality1="$(sanitize_int_range "${F_smartquality1}" 1 100 65)"
      smartstatic0="$(sanitize_int_range "${F_smartstatic0}" 0 1000 550)"
      smartstatic1="$(sanitize_int_range "${F_smartstatic1}" 0 1000 150)"
      maxkbps0="$(sanitize_int_range "${F_maxkbps0}" 64 12000 "$bps0")"
      maxkbps1="$(sanitize_int_range "${F_maxkbps1}" 64 4000 "$bps1")"
      targetkbps0="$(sanitize_int_range "${F_targetkbps0}" 64 12000 "$bps0")"
      targetkbps1="$(sanitize_int_range "${F_targetkbps1}" 64 4000 "$bps1")"
      if [ "$targetkbps0" -gt "$maxkbps0" ]; then
        targetkbps0="$maxkbps0"
      fi
      if [ "$targetkbps1" -gt "$maxkbps1" ]; then
        targetkbps1="$maxkbps1"
      fi

      echo "Video resolution set to $wh0 and $wh1<br/>"
      if [ "$req_width0" != "$width0" ] || [ "$req_height0" != "$height0" ] || [ "${F_video_codec0}" != "$codec0" ]; then
        echo "Main stream normalized to ${width0}x${height0} (codec=${codec0}) for encoder safety.<br/>"
      fi
      if [ "$req_width1" != "$width1" ] || [ "$req_height1" != "$height1" ] || [ "${F_video_codec1}" != "$codec1" ]; then
        echo "Sub stream normalized to ${width1}x${height1} (codec=${codec1}) for encoder safety.<br/>"
      fi
      if [ "${F_videoport}" != "$videoport" ] || [ "${F_brbitrate0}" != "$bps0" ] || [ "${F_brbitrate1}" != "$bps1" ] || [ "${F_video_format0}" != "$brmode0" ] || [ "${F_video_format1}" != "$brmode1" ] || [ "${F_fps0}" != "$fps0" ] || [ "${F_fps1}" != "$fps1" ] || [ "${F_goplen0}" != "$goplen0" ] || [ "${F_goplen1}" != "$goplen1" ] || [ "${F_minqp0}" != "$minqp0" ] || [ "${F_minqp1}" != "$minqp1" ] || [ "${F_maxqp0}" != "$maxqp0" ] || [ "${F_maxqp1}" != "$maxqp1" ] || [ "${F_codec_profile0}" != "$profile0" ] || [ "${F_codec_profile1}" != "$profile1" ] || [ "${F_smartmode0}" != "$smartmode0" ] || [ "${F_smartmode1}" != "$smartmode1" ] || [ "${F_smartgoplen0}" != "$smartgoplen0" ] || [ "${F_smartgoplen1}" != "$smartgoplen1" ] || [ "${F_smartquality0}" != "$smartquality0" ] || [ "${F_smartquality1}" != "$smartquality1" ] || [ "${F_smartstatic0}" != "$smartstatic0" ] || [ "${F_smartstatic1}" != "$smartstatic1" ] || [ "${F_maxkbps0}" != "$maxkbps0" ] || [ "${F_maxkbps1}" != "$maxkbps1" ] || [ "${F_targetkbps0}" != "$targetkbps0" ] || [ "${F_targetkbps1}" != "$targetkbps1" ]; then
        safe_values_changed=1
      fi
      if [ "$safe_values_changed" = "1" ]; then
        echo "One or more advanced fields were sanitized to safe ranges/profile combinations.<br/>"
      fi

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " USERNAME "${username}" \
          " " USERPASSWORD "${userpassword}" \
          " " PORT "$videoport" \
          0 bps          "$bps0" \
          0 brmode       "$brmode0" \
          0 codec        "$codec0" \
          0 fps          "$fps0" \
          0 goplen       "$goplen0" \
          0 height       "$height0" \
          0 maxqp        "$maxqp0" \
          0 minqp        "$minqp0" \
          0 profile      "$profile0" \
          0 width        "$width0" \
          0 smartmode    "$smartmode0" \
          0 smartgoplen  "$smartgoplen0" \
          0 smartquality "$smartquality0" \
          0 smartstatic  "$smartstatic0" \
          0 maxkbps      "$maxkbps0" \
          0 targetkbps   "$targetkbps0" \
          1 bps          "$bps1" \
          1 brmode       "$brmode1" \
          1 codec        "$codec1" \
          1 fps          "$fps1" \
          1 goplen       "$goplen1" \
          1 height       "$height1" \
          1 maxqp        "$maxqp1" \
          1 minqp        "$minqp1" \
          1 profile      "$profile1" \
          1 width        "$width1" \
          1 smartmode    "$smartmode1" \
          1 smartgoplen  "$smartgoplen1" \
          1 smartquality "$smartquality1" \
          1 smartstatic  "$smartstatic1" \
          1 maxkbps      "$maxkbps1" \
          1 targetkbps   "$targetkbps1"

      if ! finalize_stream_apply "manual-video-settings"; then
        echo "Manual video settings were rolled back.<br/>"
      fi
    ;;
  esac
