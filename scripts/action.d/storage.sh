# shellcheck shell=sh
# action.cgi commands: SD card, local recording.
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
      if [ -f /tmp/linux66 ]; then
        # 3.0: the recorder is controlscripts/recording (same boot.conf keys), not inside the RTSP server
        ( sleep 1; sh /mnt/controlscripts/recording stop
          [ "$_lr_on" = 1 ] && sh /mnt/controlscripts/recording start ) </dev/null >/dev/null 2>&1 &
      else
        schedule_service_restart /mnt/controlscripts/rtsp-h26x 1
      fi
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
      _lr_card=0; grep -qE " /mnt/sd vfat | /mnt vfat " /proc/mounts 2>/dev/null && _lr_card=1
      _lr_paused=0; [ -f /var/run/tc100rec.pause ] && _lr_paused=1
      printf '{"ok":true,"rec_local":"%s","rec_when":"%s","rec_stream":"%s","rec_segment_min":%s,"rec_reserve_mb":"%s","card":%s,"paused":%s,"state":"%s","file":"%s","files":"%s","free_mb":"%s","rtsp_client":"%s","storage":"%s"}\n' \
        "$(json_escape "$(_lr_kv REC_LOCAL 0)")" "$(json_escape "$(_lr_kv REC_WHEN offline)")" "$(json_escape "$(_lr_kv REC_STREAM main)")" \
        "$((_lr_seg / 60))" "$(json_escape "$(_lr_kv REC_RESERVE_MB 256)")" "$_lr_card" "$_lr_paused" \
        "$(json_escape "$(_lr_st state)")" "$(json_escape "$(_lr_st file)")" "$(json_escape "$(_lr_st files)")" \
        "$(json_escape "$(_lr_st free_mb)")" "$(json_escape "$(_lr_st rtsp_client)")" \
        "$(cat /tmp/tc100-storage 2>/dev/null || { [ -f /tmp/flashmode ] && echo flash; } || echo sd)"
    ;;

    sd_card_info)
      # 3.0 (Linux 6.6): the card is only video storage at /mnt/sd, sdinfo-sd.sh describes it
      [ -f /tmp/linux66 ] && sh /mnt/v3/linux66-sd/sdinfo-sd.sh >/dev/null 2>&1
      if [ "$(cat /tmp/tc100-storage 2>/dev/null)" = flash ]; then
        [ "$(sed -n 's/^state=//p' /tmp/sd-format 2>/dev/null)" = running ] || sh /mnt/scripts/sd-card.sh inspect >/dev/null 2>&1
      fi
      _sc_v() { sed -n "s/^$1=//p" "$2" 2>/dev/null | head -n 1; }
      _sc_num() { case "$1" in ''|*[!0-9]*) printf 'null' ;; *) printf '%s' "$1" ;; esac; }
      _sc_rec="$(sed -n 's/^REC_LOCAL=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p' /mnt/config/boot.conf 2>/dev/null | tail -n 1)"
      printf '{"ok":true,"storage":"%s","present":%s,"id":"%s","size_mb":%s,"fs":"%s","kind":"%s","mounted":%s,"free_mb":%s,"prompt":%s,"health":"%s","rec_local":"%s","format_state":"%s","format_msg":"%s"}\n' \
        "$(json_escape "$(cat /tmp/tc100-storage 2>/dev/null || { [ -f /tmp/flashmode ] && echo flash; } || echo sd)")" \
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
      if [ -f /tmp/linux66 ]; then
        # 3.0: a card put in after boot replaces the 16 KiB RAM placeholder at /mnt/sd
        if ! grep -q ' /mnt/sd vfat ' /proc/mounts; then
          umount /mnt/sd 2>/dev/null
          for _d in /dev/mmcblk0p1 /dev/mmcblk0; do
            [ -b "$_d" ] && mount -t vfat -o rw,noatime "$_d" /mnt/sd 2>/dev/null && break
          done
          grep -q ' /mnt/sd ' /proc/mounts || mount -t tmpfs -o size=16k tmpfs /mnt/sd 2>/dev/null
        fi
        sh /mnt/v3/linux66-sd/sdinfo-sd.sh >/dev/null 2>&1
        if grep -q ' /mnt/sd vfat ' /proc/mounts; then
          mkdir -p /mnt/sd/DCIM 2>/dev/null
          json_body_ok "SD card mounted on /mnt/sd"
        else
          json_body_err "SD_MOUNT" "This card cannot be mounted (no FAT32 file system?)"
        fi
      elif sh /mnt/scripts/sd-card.sh mount >/dev/null 2>&1; then sh /mnt/scripts/sd-card.sh inspect >/dev/null 2>&1; json_body_ok "SD card mounted on /mnt/sd"
      else json_body_err "SD_MOUNT" "This card cannot be mounted (boot files, card errors or no FAT32/exFAT file system)"; fi
    ;;

    sd_card_ack)
      if sh /mnt/scripts/sd-card.sh ack "${F_id}" >/dev/null 2>&1; then json_body_ok "ok"; else json_body_err "SD_ACK" "bad id"; fi
    ;;

    local_rec_eject|local_rec_resume)
      if [ -f /tmp/linux66 ]; then
        # 3.0: stop the recorder (controlscripts/recording) and release the card, or the reverse
        if [ "$F_cmd" = local_rec_eject ]; then
          : > /var/run/tc100rec.pause
          sh /mnt/controlscripts/recording stop </dev/null >/dev/null 2>&1
          sync
          if ! grep -q ' /mnt/sd vfat ' /proc/mounts || umount /mnt/sd 2>/dev/null; then
            grep -q ' /mnt/sd ' /proc/mounts || mount -t tmpfs -o size=16k tmpfs /mnt/sd 2>/dev/null
            _lr_out="ok: recording stopped, the card can be taken out"
          else
            _lr_out="the card is still in use, try again"
          fi
        else
          rm -f /var/run/tc100rec.pause
          if ! grep -q ' /mnt/sd vfat ' /proc/mounts; then
            umount /mnt/sd 2>/dev/null
            for _d in /dev/mmcblk0p1 /dev/mmcblk0; do
              [ -b "$_d" ] && mount -t vfat -o rw,noatime "$_d" /mnt/sd 2>/dev/null && break
            done
            grep -q ' /mnt/sd ' /proc/mounts || mount -t tmpfs -o size=16k tmpfs /mnt/sd 2>/dev/null
          fi
          if grep -q ' /mnt/sd vfat ' /proc/mounts; then
            mkdir -p /mnt/sd/DCIM 2>/dev/null
            ( sh /mnt/controlscripts/recording start ) </dev/null >/dev/null 2>&1 &
            _lr_out="ok: card mounted, recording resumes"
          else
            _lr_out="no usable card"
          fi
        fi
        sh /mnt/v3/linux66-sd/sdinfo-sd.sh >/dev/null 2>&1
      else
        _lr_out="$(sh /mnt/scripts/rec-storage.sh "${F_cmd#local_rec_}" 2>&1)"
      fi
      case "$_lr_out" in
        ok*) json_body_ok "$_lr_out" ;;
        *) json_body_err "REC_STORAGE" "$_lr_out" ;;
      esac
    ;;


  esac
