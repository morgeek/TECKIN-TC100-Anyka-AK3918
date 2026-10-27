# shellcheck shell=sh
# action.cgi commands: Microphone, speaker, push-to-talk, sound detection.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    conf_audioin)
      # the stream audio is fixed (G.711 A-law, 8 kHz): only the microphone level is a setting
      volume=$(sanitize_int_range "${F_audioinVol}" 0 12 10)
      if ! /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " volume "$volume"; then
        if wants_json_response; then
          json_body_err "CONFIG_WRITE_FAILED" "Settings could not be written. Check the SD card."
        else
          echo "Settings write failed; no restart scheduled.<br/>"
        fi
        exit 0
      fi

      # the level applies at once
      amixer -q -c 0 cset name='LineIn Capture Volume' "$volume" >/dev/null 2>&1
      if wants_json_response; then
        json_body_ok "Audio settings updated."
      else
        echo "Audio settings updated.<br/>"
      fi
    ;;

    set_sound_detection)
      enable=$(normalize_bool "${F_sound_det_enable}")
      threshold=$(sound_threshold_db "${F_sound_det_threshold}" -24)
      interval=$(sanitize_int_range "${F_sound_det_interval}" 1 300 2)
      apply_sound_detection "$enable" "$threshold" "$interval"
      if wants_json_response; then
        json_body_ok "Sound detection settings updated."
      else
        echo "Sound detection settings updated.<br/>"
      fi
    ;;

    audio_test)
      F_audioSource=$(printf '%b' "${F_audioSource//%/\\x}")
      F_audiotestVol=$(sanitize_int_range "${F_audiotestVol}" 0 100 90)
      if [ -z "$F_audioSource" ]; then
        F_audioSource="$(resolve_audio_test_source || true)"
      fi
      play_audio_test_source "$F_audioSource" "$F_audiotestVol"
    ;;


    get_ptt_vol)
        read_ptt_volume
    ;;

    get_ptt_status)
        ptt_backend_status
    ;;

    conf_ptt)
        safe_ptt_vol="$(sanitize_int_range "$F_audiooutVol" 0 100 90)"
        echo "$safe_ptt_vol" > "$PTT_VOLUME_FILE"
        if wants_json_response; then
          json_body_ok "Push-to-talk volume set to $safe_ptt_vol"
        else
          echo "Push-to-talk volume set to $safe_ptt_vol"
        fi
    ;;
  esac
