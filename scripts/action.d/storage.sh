# shellcheck shell=sh
# action.cgi commands: SD card, local recording, timelapse.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    # Local backup recording (libtc100fix, src/tc100fix/rec.c): settings in
    # boot.conf, applied by restarting the RTSP server.
    set_local_recording)
      install_config /mnt/config/boot.conf
      _lr_on=$(normalize_bool "${F_rec_local}")
      case "${F_rec_when}" in always) _lr_when=always ;; *) _lr_when=offline ;; esac
      case "${F_rec_stream}" in sub) _lr_stream=sub ;; *) _lr_stream=main ;; esac
      _lr_seg=$(sanitize_int_range "${F_rec_segment_min}" 1 60 5)
      _lr_res=$(sanitize_int_range "${F_rec_reserve_mb}" 32 8192 256)
      rewrite_config /mnt/config/boot.conf REC_LOCAL "$_lr_on"
      rewrite_config /mnt/config/boot.conf REC_WHEN "$_lr_when"
      rewrite_config /mnt/config/boot.conf REC_STREAM "$_lr_stream"
      rewrite_config /mnt/config/boot.conf REC_SEGMENT_SEC "$((_lr_seg * 60))"
      rewrite_config /mnt/config/boot.conf REC_RESERVE_MB "$_lr_res"
      schedule_service_restart /mnt/controlscripts/rtsp-h26x 1
      if wants_json_response; then
        json_body_ok "Local recording settings saved; the video stream restarts once."
      else
        echo "Local recording settings saved.<br/>"
      fi
    ;;

    local_rec_status)
      # Settings and live state, for Settings → Recording.
      _lr_b=/mnt/config/boot.conf
      _lr_kv() { _v="$(sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}\$/\1/p" "$_lr_b" 2>/dev/null | tail -n 1)"; printf '%s' "${_v:-$2}"; }
      _lr_st() { sed -n "s/^$1=//p" /var/run/tc100rec 2>/dev/null | head -n 1; }
      _lr_seg="$(_lr_kv REC_SEGMENT_SEC 300)"; case "$_lr_seg" in ''|*[!0-9]*) _lr_seg=300 ;; esac
      _lr_card=0; grep -qE " /mnt/sd | /mnt vfat " /proc/mounts 2>/dev/null && _lr_card=1
      _lr_paused=0; [ -f /var/run/tc100rec.pause ] && _lr_paused=1
      printf '{"ok":true,"rec_local":"%s","rec_when":"%s","rec_stream":"%s","rec_segment_min":%s,"rec_reserve_mb":"%s","card":%s,"paused":%s,"state":"%s","file":"%s","files":"%s","free_mb":"%s","rtsp_client":"%s","storage":"%s"}\n' \
        "$(json_escape "$(_lr_kv REC_LOCAL 0)")" "$(json_escape "$(_lr_kv REC_WHEN offline)")" "$(json_escape "$(_lr_kv REC_STREAM main)")" \
        "$((_lr_seg / 60))" "$(json_escape "$(_lr_kv REC_RESERVE_MB 256)")" "$_lr_card" "$_lr_paused" \
        "$(json_escape "$(_lr_st state)")" "$(json_escape "$(_lr_st file)")" "$(json_escape "$(_lr_st files)")" \
        "$(json_escape "$(_lr_st free_mb)")" "$(json_escape "$(_lr_st rtsp_client)")" \
        "$(cat /tmp/tc100-storage 2>/dev/null || echo sd)"
    ;;

    sd_card_info)
      if [ "$(cat /tmp/tc100-storage 2>/dev/null)" = flash ]; then
        [ "$(sed -n 's/^state=//p' /tmp/sd-format 2>/dev/null)" = running ] || sh /mnt/scripts/sd-card.sh inspect >/dev/null 2>&1
      fi
      _sc_v() { sed -n "s/^$1=//p" "$2" 2>/dev/null | head -n 1; }
      _sc_num() { case "$1" in ''|*[!0-9]*) printf 'null' ;; *) printf '%s' "$1" ;; esac; }
      _sc_rec="$(sed -n 's/^REC_LOCAL=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p' /mnt/config/boot.conf 2>/dev/null | tail -n 1)"
      printf '{"ok":true,"storage":"%s","present":%s,"id":"%s","size_mb":%s,"fs":"%s","kind":"%s","mounted":%s,"free_mb":%s,"prompt":%s,"health":"%s","rec_local":"%s","format_state":"%s","format_msg":"%s"}\n' \
        "$(json_escape "$(cat /tmp/tc100-storage 2>/dev/null || echo sd)")" \
        "$(_sc_num "$(_sc_v present /tmp/sd-card)")" "$(json_escape "$(_sc_v id /tmp/sd-card)")" \
        "$(_sc_num "$(_sc_v size_mb /tmp/sd-card)")" "$(json_escape "$(_sc_v fs /tmp/sd-card)")" \
        "$(json_escape "$(_sc_v kind /tmp/sd-card)")" "$(_sc_num "$(_sc_v mounted /tmp/sd-card)")" \
        "$(_sc_num "$(_sc_v free_mb /tmp/sd-card)")" "$(_sc_num "$(_sc_v prompt /tmp/sd-card)")" \
        "$(json_escape "$(_sc_v state /tmp/sd-health)")" "$(json_escape "$_sc_rec")" \
        "$(json_escape "$(_sc_v state /tmp/sd-format)")" "$(json_escape "$(_sc_v msg /tmp/sd-format)")"
    ;;

    sd_card_format)
      _sc_out="$(sh /mnt/scripts/sd-card.sh format 2>&1)"
      case "$_sc_out" in started*) json_body_ok "Formatting the SD card…" ;; *) json_body_err "SD_FORMAT" "$_sc_out" ;; esac
    ;;

    sd_card_mount)
      if sh /mnt/scripts/sd-card.sh mount >/dev/null 2>&1; then sh /mnt/scripts/sd-card.sh inspect >/dev/null 2>&1; json_body_ok "SD card mounted on /mnt/sd"
      else json_body_err "SD_MOUNT" "This card cannot be mounted (boot files, card errors or no FAT32/exFAT file system)"; fi
    ;;

    sd_card_ack)
      if sh /mnt/scripts/sd-card.sh ack "${F_id}" >/dev/null 2>&1; then json_body_ok "ok"; else json_body_err "SD_ACK" "bad id"; fi
    ;;

    local_rec_eject|local_rec_resume)
      _lr_out="$(sh /mnt/scripts/rec-storage.sh "${F_cmd#local_rec_}" 2>&1)"
      case "$_lr_out" in
        ok*) json_body_ok "$_lr_out" ;;
        *) json_body_err "REC_STORAGE" "$_lr_out" ;;
      esac
    ;;


    conf_timelapse)
      tlinterval=$(printf '%s' "${F_tlinterval}")
      tlinterval=$(echo "$tlinterval" | sed "s/[^0-9\.]//g")
      if [ "$tlinterval" ]; then
        rewrite_config /mnt/config/timelapse.conf TIMELAPSE_INTERVAL "$tlinterval"
        echo "Timelapse interval set to $tlinterval seconds."
      else
        echo "Invalid timelapse interval"
      fi
      tlduration=$(printf '%s' "${F_tlduration}")
      tlduration=$(echo "$tlduration" | sed "s/[^0-9\.]//g")
      if [ "$tlduration" ]; then
        rewrite_config /mnt/config/timelapse.conf TIMELAPSE_DURATION "$tlduration"
        echo "Timelapse duration set to $tlduration minutes."
      else
        echo "Invalid timelapse duration"
      fi
    ;;

    conf_recording)
      # SECURITY: recording.conf is sourced as root by controlscripts/recording
      # (`. $CONFIGPATH/recording.conf`). These four values MUST be validated to
      # bare bool/integers before being written, otherwise a newline or backtick
      # in the POST body lands in the sourced file and executes as root. The
      # sibling conf_dns/conf_static_ip handlers already validate; this one did
      # not. normalize_bool/sanitize_int_range strip anything non-numeric.
      motion_act="$(normalize_bool "${F_motion_act}")"
      postrec="$(sanitize_int_range "${F_postrec}" 0 3600 8)"
      maxduration="$(sanitize_int_range "${F_maxduration}" 1 3600 60)"
      diskspace="$(sanitize_int_range "${F_diskspace}" 0 1000000 512)"

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
  esac
