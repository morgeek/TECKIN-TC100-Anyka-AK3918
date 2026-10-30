# shellcheck shell=sh
# action.cgi commands: RTSP server, stream profiles, Frigate and ONVIF stream choices.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    rtsp_server_info)
      # one server, tc100_rtsp; its clients are the established connections to the RTSP port
      _rs_num() { case "$1" in ''|*[!0-9]*) printf 'null' ;; *) printf '%s' "$1" ;; esac; }
      _rs_cfg() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" /mnt/config/boot.conf 2>/dev/null | tail -n 1; }
      _rs_sub="$(_rs_cfg RTSP_SUBSTREAM)"; [ "$_rs_sub" = 0 ] || _rs_sub=1
      _rs_talk="$(_rs_cfg RTSP_LITE_TALK)"; case "$_rs_talk" in 0|no|off|false) _rs_talk=0 ;; *) _rs_talk=1 ;; esac
      _rs_port="$(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf /mnt/config/rtspserver.conf r " " PORT 2>/dev/null)"
      case "$_rs_port" in ''|*[!0-9]*) _rs_port=554 ;; esac
      _rs_hex="$(printf '%04X' "$_rs_port")"
      _rs_clients="$(awk -v p=":$_rs_hex" 'NR > 1 && $4 == "01" && substr($2, length($2) - 4) == p { n++ } END { print n + 0 }' /proc/net/tcp 2>/dev/null)"
      _rs_idle="$(_rs_cfg IDLE_FPS)"; case "$_rs_idle" in ''|*[!0-9]*) _rs_idle=0 ;; esac
      _rs_after="$(_rs_cfg IDLE_AFTER)"; case "$_rs_after" in ''|*[!0-9]*) _rs_after=10 ;; esac
      _rs_md=0; [ -e /tmp/tc100_md ] && _rs_md=1
      printf '{"ok":true,"server":"tc100_rtsp","substream":%s,"talk":%s,"port":%s,"clients":%s,"idle_fps":%s,"idle_after":%s,"motion_detection":%s}\n' \
        "$_rs_sub" "$_rs_talk" "$_rs_port" "$(_rs_num "$_rs_clients")" "$_rs_idle" "$_rs_after" "$_rs_md"
    ;;

    set_rtsp_server)
      # Settings -> Video: the sub-stream and two-way audio (ONVIF backchannel) switches
      _rs_sub="$(normalize_bool "${F_rtsp_substream:-0}")"
      _rs_talk="$(normalize_bool "${F_rtsp_talk:-0}")"
      install_config /mnt/config/boot.conf
      # the sub-stream is chosen when tc100_rtsp starts; two-way audio (RTSP_LITE_TALK) is read while it runs
      _rs_old_sub="$(sed -n 's/^RTSP_SUBSTREAM="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' /mnt/config/boot.conf 2>/dev/null | tail -n 1)"
      case "$_rs_old_sub" in 0|no|off|false) _rs_old_sub=0 ;; *) _rs_old_sub=1 ;; esac
      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$_rs_sub"
      rewrite_config /mnt/config/boot.conf RTSP_LITE_TALK "$_rs_talk"
      # lower frame rate while nothing moves (tc100_rtsp reads both while it runs; 0 = off). Written only when sent.
      if [ -n "${F_rtsp_idle_fps}" ]; then
        rewrite_config /mnt/config/boot.conf IDLE_FPS "$(sanitize_int_range "${F_rtsp_idle_fps}" 0 24 0)"
        rewrite_config /mnt/config/boot.conf IDLE_AFTER "$(sanitize_int_range "${F_rtsp_idle_after}" 1 3600 10)"
      fi
      if [ "$_rs_old_sub" != "$_rs_sub" ]; then
        schedule_service_restart /mnt/controlscripts/rtsp-h26x 2
        _rs_msg="Sub-stream $_rs_sub, two-way audio $_rs_talk. The stream restarts."
      else
        _rs_msg="Sub-stream $_rs_sub, two-way audio $_rs_talk. Applied without restarting the stream."
      fi
      if wants_json_response; then
        json_body_ok "$_rs_msg"
      else
        echo "$_rs_msg<br/>"
      fi
    ;;

    set_stream_topology)
      install_config /mnt/config/boot.conf
      capture_prechange_stream_snapshot
      topology=$(printf '%s' "${F_stream_topology}")
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
      if finalize_stream_apply "stream-topology:${topology}"; then
        echo "Stream topology set to: $topology_label<br/>"
      fi
    ;;

    set_onvif_stream_policy)
      install_config /mnt/config/boot.conf
      capture_prechange_stream_snapshot
      # shellcheck disable=SC1090
      if [ -f /mnt/config/boot.conf ]; then
        . /mnt/config/boot.conf
      fi

      policy=$(printf '%s' "${F_onvif_stream_policy}")
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
      if finalize_stream_apply "onvif-policy:${policy}"; then
        echo "ONVIF stream policy set to: $policy_label<br/>"
        if [ "$RTSP_SUBSTREAM" != "1" ] && [ "$policy" != "main-primary" ] && [ "$policy" != "main-only" ]; then
          echo "Note: RTSP substream is disabled, ONVIF will fall back to main stream.<br/>"
        fi
      fi
    ;;

    set_rtsp_preset)
      capture_prechange_stream_snapshot
      preset=$(printf '%s' "${F_preset}")
      case "$preset" in
        full)
          width0=1280; height0=720; fps0=25; bps0=2000; gop0=50; maxkbps0=2500; targetkbps0=2000; smartq0=100; smartstatic0=550
          width1=640;  height1=360; fps1=10; bps1=300;  gop1=20; maxkbps1=400;  targetkbps1=300;  smartq1=70;  smartstatic1=150
          ;;
        medium)
          width0=1280; height0=720; fps0=20; bps0=1200; gop0=40; maxkbps0=1500; targetkbps0=1200; smartq0=80; smartstatic0=450
          width1=352;  height1=200; fps1=8;  bps1=200;  gop1=16; maxkbps1=250;  targetkbps1=200;  smartq1=60; smartstatic1=120
          ;;
        low)
          width0=640;  height0=360; fps0=10; bps0=600;  gop0=20; maxkbps0=800;  targetkbps0=600;  smartq0=60; smartstatic0=350
          width1=352;  height1=200; fps1=5;  bps1=120;  gop1=10; maxkbps1=160;  targetkbps1=120;  smartq1=50; smartstatic1=100
          ;;
        *)
          if wants_json_response; then json_body_err "INVALID_PRESET" "Unknown video profile."
          else echo "Unknown preset '$preset'<br/>"; fi
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

      if ui_finalize_stream_apply "rtsp-preset:${preset}"; then
        if ! wants_json_response; then echo "RTSP preset applied: $preset (fps max 25)<br/>"; fi
      fi
    ;;

    set_rtsp_quality_profile)
      install_config /mnt/config/boot.conf
      capture_prechange_stream_snapshot
      quality_profile=$(printf '%s' "${F_rtsp_quality_profile}")

      case "$quality_profile" in
        max-quality-h264)
          profile_label="Max quality 1080p H264 (recommended)"
          width0=1920; height0=1080; fps0=25; bps0=3600; gop0=50; maxkbps0=4500; targetkbps0=3600; smartq0=100; smartstatic0=620
          width1=640;  height1=360;  fps1=15; bps1=700;  gop1=30; maxkbps1=900;  targetkbps1=700;  smartq1=80; smartstatic1=240
          codec0=0; profile0=1
          codec1=0; profile1=0
          rtsp_substream=1
          rtsp_audio=1
          onvif_policy="main-primary"
          ;;
        max-quality-hevc)
          profile_label="Max quality 1080p H265/HEVC"
          width0=1920; height0=1080; fps0=25; bps0=3000; gop0=50; maxkbps0=3800; targetkbps0=3000; smartq0=100; smartstatic0=600
          width1=640;  height1=360;  fps1=12; bps1=550;  gop1=24; maxkbps1=760;  targetkbps1=550;  smartq1=78; smartstatic1=220
          codec0=2; profile0=3
          codec1=2; profile1=3
          rtsp_substream=1
          rtsp_audio=1
          onvif_policy="main-primary"
          ;;
        max-main-h264)
          profile_label="Max quality main-only H264"
          width0=1920; height0=1080; fps0=25; bps0=4200; gop0=50; maxkbps0=5200; targetkbps0=4200; smartq0=100; smartstatic0=650
          width1=352;  height1=200;  fps1=5;  bps1=120;  gop1=10; maxkbps1=180;  targetkbps1=120;  smartq1=50; smartstatic1=100
          codec0=0; profile0=1
          codec1=0; profile1=0
          rtsp_substream=0
          rtsp_audio=1
          onvif_policy="main-only"
          ;;
        *)
          echo "Unknown RTSP quality profile '$quality_profile'<br/>"
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

      rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM "$rtsp_substream"
      rewrite_config /mnt/config/boot.conf RTSP_AUDIO "$rtsp_audio"
      rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY "$onvif_policy"
      rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 0
      rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 0

      if finalize_stream_apply "rtsp-quality:${quality_profile}"; then
        echo "RTSP quality profile applied: $profile_label<br/>"
        echo "Main=${width0}x${height0}@${fps0}fps codec=${codec0}, Sub=${width1}x${height1}@${fps1}fps codec=${codec1}<br/>"
        echo "RTSP_SUBSTREAM=$rtsp_substream, RTSP_AUDIO=$rtsp_audio, ONVIF_STREAM_POLICY=$onvif_policy<br/>"
      fi
    ;;

    set_client_profile)
      client_profile=$(printf '%s' "${F_client_profile}")
      install_config /mnt/config/boot.conf
      capture_prechange_stream_snapshot
      if ! select_compat_profile_values "$client_profile"; then
        if wants_json_response; then json_body_err "INVALID_PROFILE" "Unknown recorder profile."
        else echo "Unknown client profile '$client_profile'<br/>"; fi
        exit 0
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

      if ui_finalize_stream_apply "compat-profile:${client_profile}"; then
        if [ "$low_cpu_profile" = "1" ]; then
          apply_low_cpu_background_defaults
        fi
        if ! wants_json_response; then
        echo "Compatibility preset applied: $profile_label<br/>"
        echo "RTSP_SUBSTREAM=$rtsp_substream, RTSP_AUDIO=$rtsp_audio, ONVIF_STREAM_POLICY=$onvif_policy<br/>"
        echo "Main=${width0}x${height0}@${fps0}fps, Sub=${width1}x${height1}@${fps1}fps<br/>"
        fi
        _ac_now
        [ -n "$now_ts" ] || now_ts=0
        publish_mqtt_event "$(printf '{"ts":%s,"type":"client_profile","value":"%s"}' "$now_ts" "$client_profile")"
      fi
    ;;

    save_known_good_profile)
      if save_known_good_snapshot "manual:web-ui"; then
        saved_ts="$(read_kv_or_default "$KNOWN_GOOD_STREAM_CONF" TS 0)"
        echo "Known-good snapshot saved.<br/>"
        echo "Timestamp (epoch): ${saved_ts}<br/>"
      else
        echo "Failed to save known-good snapshot.<br/>"
      fi
    ;;

    restore_known_good_profile)
      capture_prechange_stream_snapshot
      if restore_stream_from_snapshot "$KNOWN_GOOD_RTSP_CONF" "$KNOWN_GOOD_STREAM_CONF"; then
        restore_reason="$(read_kv_or_default "$KNOWN_GOOD_STREAM_CONF" REASON unknown)"
        restore_ts="$(read_kv_or_default "$KNOWN_GOOD_STREAM_CONF" TS 0)"
        echo "Known-good snapshot restored.<br/>"
        echo "Source: ${restore_reason} (ts=${restore_ts})<br/>"
      else
        echo "Known-good restore failed.<br/>"
        if restore_stream_from_snapshot "$PRECHANGE_RTSP_CONF" "$PRECHANGE_STREAM_CONF"; then
          echo "Reverted to pre-restore snapshot.<br/>"
        fi
      fi
    ;;

    set_frigate_live)
      # Smooth live view: a link to this camera in Frigate's own live page
      # (go2rtc restream: no extra connection to the camera). Frigate is
      # plain HTTP and this UI HTTPS, so it opens in its own tab rather than
      # being embedded (mixed content). Stored in config/frigate_live.conf.
      fl_url="$(printf '%s' "${F_frigate_url}")"; fl_cam="$(printf '%s' "${F_frigate_camera}")"
      fl_url="${fl_url%/}"; fl_err=""; fl_note=""
      if [ -n "$fl_url" ]; then
        case "$fl_url" in http://*|https://*) ;; *) fl_url="http://$fl_url" ;; esac
        case "${fl_url#*://}" in
          ''|*[!A-Za-z0-9.:/_-]*) fl_err="The Frigate address must look like http://192.168.1.20:5000." ;;
        esac
      fi
      case "$fl_cam" in *[!A-Za-z0-9_-]*) fl_err="The Frigate camera name may only contain letters, digits, - and _." ;; esac
      if [ -z "$fl_err" ] && [ -n "$fl_url" ] && [ -z "$fl_cam" ]; then
        # Find which Frigate camera reads this one: an input or a go2rtc
        # stream with this camera's IP (one request, only when saving).
        fl_ip=""; [ -r /tmp/camera_ip.txt ] && read -r fl_ip < /tmp/camera_ip.txt
        if [ -n "$fl_ip" ] && [ -x /mnt/bin/curl ] && [ -r /mnt/scripts/jsonflat.awk ]; then
          # Frigate's /api/config flattened (scripts/jsonflat.awk, no jq): the
          # first camera with an input on this IP, or on a go2rtc stream that
          # points to this IP.
          fl_cam="$(/mnt/bin/curl -s -m 6 "$fl_url/api/config" 2>/dev/null |
            LC_ALL=C awk -f /mnt/scripts/jsonflat.awk 2>/dev/null | LC_ALL=C awk -F '\t' -v ip="$fl_ip" '
            function has_ip(u,   r) { r = ip; gsub(/\./, "\\.", r); return u ~ ("[@/]" r "([:/]|$)") }
            $2 == "s" && index($1, ".go2rtc.streams.") == 1 {
              n = substr($1, 17); sub(/\[[0-9]+\]$/, "", n); if (has_ip($3)) st[n] = 1; next }
            $2 == "s" && $1 ~ /^\.cameras\.[^.]+\.ffmpeg\.inputs\[[0-9]+\]\.path$/ {
              c = substr($1, 10); sub(/\.ffmpeg\..*/, "", c)
              if (!(c in seen)) { seen[c] = 1; order[++nc] = c }
              paths[c] = paths[c] "\n" $3; next }
            END {
              for (i = 1; i <= nc; i++) {
                c = order[i]; m = split(paths[c], P, "\n")
                for (j = 2; j <= m; j++) {
                  if (has_ip(P[j])) { print c; exit }
                  for (k in st) if (substr(P[j], length(P[j]) - length(k)) == "/" k) { print c; exit }
                }
              }
            }' | head -n 1)"
          case "$fl_cam" in *[!A-Za-z0-9_-]*) fl_cam="" ;; esac
        fi
        [ -n "$fl_cam" ] && fl_note=" (camera ${fl_cam} found in Frigate)" ||
          fl_note=" — this camera was not found in Frigate's configuration; enter its Frigate name"
      fi
      if [ -n "$fl_err" ]; then
        if wants_json_response; then json_body_err "INVALID_VALUE" "$fl_err"; else echo "<p>$fl_err</p>"; fi
      elif [ -z "$fl_url" ]; then
        rm -f /mnt/config/frigate_live.conf
        echo "Smooth live view link removed.<br/>"
      else
        printf 'FRIGATE_URL=%s\nFRIGATE_CAMERA=%s\n' "$fl_url" "$fl_cam" > /mnt/config/frigate_live.conf.tmp &&
          mv -f /mnt/config/frigate_live.conf.tmp /mnt/config/frigate_live.conf
        echo "Smooth live view: ${fl_url}/#${fl_cam}${fl_note}.<br/>"
      fi
    ;;
  esac
