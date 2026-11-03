# shellcheck shell=sh
# action.cgi commands: Motion detection.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    md_zones_info)
      # Motion zones (src/tc100fix/md.c): the saved zones and what the
      # detector got at its last start (/var/run/md_zones).
      _mz_list=""
      _mz_names=""
      for _mz_k in 1 2 3 4; do
        _mz_v="$(sed -n "s/^MDZ${_mz_k}=\"\{0,1\}\([0-9,]*\)\"\{0,1\}$/\1/p" /mnt/config/motion_zones.conf 2>/dev/null | tail -n 1)"
        _mz_name="$(sed -n "s/^MDZ${_mz_k}_NAME=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" /mnt/config/motion_zones.conf 2>/dev/null | tail -n 1)"
        case "$_mz_v" in [0-9]*,[0-9]*,[0-9]*,[0-9]*) _mz_list="${_mz_list:+$_mz_list,}\"$_mz_v\""; _mz_names="${_mz_names:+$_mz_names,}\"$(json_escape "$_mz_name")\"" ;; esac
      done
      _mz_on=0; grep -q '^mdenabled=1' /mnt/config/rtspserver.conf 2>/dev/null && _mz_on=1
      _mz_st() { sed -n "s/.*$1=\([^ ]*\).*/\1/p" /var/run/md_zones 2>/dev/null | head -n 1; }
      _mz_ign="$(_mz_st ignored)"; case "$_mz_ign" in ''|*[!0-9]*) _mz_ign=null ;; esac
      printf '{"ok":true,"zones":[%s],"names":[%s],"enabled":%s,"detector":{"grid":"%s","ignored":%s,"result":"%s"}}\n' \
        "$_mz_list" "${_mz_names:-}" "$_mz_on" "$(json_escape "$(_mz_st grid)")" "$_mz_ign" "$(json_escape "$(_mz_st result)")"
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

    conf_motiondetect)
      # Settings → Motion & Sound. The form posts motion_trigger_led (checkbox:
      # "on" or absent) and sound_det_*; older pages posted motionBlink.
      mdsens=$(sanitize_int_range "${F_mdsens}" 1 100 50)
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " mdsens "$mdsens"
      /mnt/bin/setconf -k m -v "$mdsens"
      motion_led="$(normalize_bool "${F_motion_trigger_led:-${F_motionBlink:-0}}")"
      rewrite_config /mnt/config/motion.conf motion_trigger_led "$motion_led"
      if [ -n "${F_motion_best_shot+x}" ] || [ -n "${F_motion_best_shot_present:-}" ]; then
        motion_bs="$(normalize_bool "${F_motion_best_shot:-0}")"
        rewrite_config /mnt/config/motion.conf motion_best_shot "$motion_bs"
      fi
      sound_enable="$(normalize_bool "${F_sound_det_enable:-0}")"
      sound_threshold="$(sound_threshold_db "${F_sound_det_threshold}" -24)"
      apply_sound_detection "$sound_enable" "$sound_threshold"
      # Motion zones (pages from 2.1.9 send md_zone_form): areas the motion
      # detection ignores; tc100_rtsp reads motion_zones.conf while it runs.
      if [ -n "${F_md_zone_form:-}" ]; then
        _mz_new=""; _mz_n=0
        _mz_f1="${F_md_zone1:-}"; _mz_f2="${F_md_zone2:-}"; _mz_f3="${F_md_zone3:-}"; _mz_f4="${F_md_zone4:-}"
        for _mz_idx in 1 2 3 4; do
          eval "_mz_v=\"\${F_md_zone${_mz_idx}:-}\""
          eval "_mz_nm=\"\${F_md_zone${_mz_idx}_name:-}\""
          case "$_mz_v" in ''|*[!0-9,]*) continue ;; esac
          printf '%s' "$_mz_v" | grep -Eq '^[0-9]{1,3},[0-9]{1,3},[0-9]{1,3},[0-9]{1,3}$' || continue
          _mz_n=$((_mz_n + 1))
          _mz_new="${_mz_new}MDZ${_mz_n}=\"${_mz_v}\"
"
          if [ -n "$_mz_nm" ]; then
            _mz_clean_nm="$(printf '%s' "$_mz_nm" | sed 's/[^A-Za-z0-9 _-]//g')"
            _mz_new="${_mz_new}MDZ${_mz_n}_NAME=\"${_mz_clean_nm}\"
"
          fi
        done
        if [ "$(printf '%s' "$_mz_new")" != "$(cat /mnt/config/motion_zones.conf 2>/dev/null)" ]; then
          if [ -n "$_mz_new" ]; then printf '%s' "$_mz_new" > /mnt/config/motion_zones.conf.tmp && mv -f /mnt/config/motion_zones.conf.tmp /mnt/config/motion_zones.conf
          else rm -f /mnt/config/motion_zones.conf; fi
        fi
        echo "Motion zones: ${_mz_n}<BR>"
      fi

      echo "Motion red led blink set to ${motion_led}<BR>"
      echo "Motion sensitivity set to ${mdsens}<BR>"
      echo "Sound detection: enable=${sound_enable} threshold=${sound_threshold} dBFS<BR>"
    ;;

  esac
