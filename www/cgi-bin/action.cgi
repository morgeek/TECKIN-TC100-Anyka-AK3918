#!/bin/sh

. /mnt/www/cgi-bin/func.cgi
. /mnt/scripts/common_functions.sh

export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

# Debounce expensive service restarts to avoid restart storms when multiple
# settings are applied in quick succession from the web UI.
schedule_service_restart() {
  service_script="$1"
  delay_seconds="${2:-2}"
  lock_dir="/tmp/$(basename "$service_script").restart.pending"

  if [ ! -x "$service_script" ]; then
    return 0
  fi
  if ! mkdir "$lock_dir" 2>/dev/null; then
    return 0
  fi

  (
    sleep "$delay_seconds"
    rmdir "$lock_dir" >/dev/null 2>&1 || true
    restart_service_if_need "$service_script"
  ) >/dev/null 2>&1 &
}

schedule_rtsp_restart() {
  schedule_service_restart /mnt/controlscripts/rtsp-h26x 2
}

schedule_onvif_restart() {
  schedule_service_restart /mnt/controlscripts/onvif 2
}

apply_web_mode_async() {
  mode="$1"
  (
    sleep 1
    killall lighttpd >/dev/null 2>&1 || true
    killall httpd >/dev/null 2>&1 || true
    if [ "$mode" != "off" ]; then
      if [ -x /mnt/config/autostart/02_system-webserver ]; then
        /mnt/config/autostart/02_system-webserver >/dev/null 2>&1 || true
      else
        http_server on >/dev/null 2>&1 || true
      fi
    fi
  ) >/dev/null 2>&1 &
}

if [ -n "$F_cmd" ]; then
  if [ -z "$F_val" ]; then
    F_val=100
  fi
  case "$F_cmd" in
    showlog)
      echo "<pre>"
      case "${F_logname}" in
        "" | 1)
          echo "Summary of all log files:<br/>"
          tail /var/log/*
          echo "<br/>===SD card logs===<br/>"
          tail /mnt/log/*
          ;;

        2)
          echo "Content of dmesg<br/>"
          /bin/dmesg
          ;;

        3)
          echo "Content of v4l2rtspserver.log<br/>"
          tail -n 256 /mnt/log/v4l2rtspserver.log
          ;;

      esac
      echo "</pre>"
    ;;
    clearlog)
      echo "<pre>"
      case "${F_logname}" in
        "" | 1)
          echo "Summary of all log files cleared<br/>"
          for i in /var/log/*
          do
              echo -n "" > $i
          done
          ;;
        2)
          echo "Content of dmesg cleared<br/>"
          /bin/dmesg -c > /dev/null
          ;;
        3)
          echo "Content of v4l2rtspserver.log cleared<br/>"
          echo -n "" > /mnt/log/v4l2rtspserver.log
          ;;
      esac
      echo "</pre>"
    ;;

    reboot)
      echo "Rebooting device..."
      /sbin/reboot
    ;;

    shutdown)
      echo "Shutting down device.."
      /sbin/halt
    ;;

    blue_led_on)
      blue_led on
    ;;

    blue_led_off)
      blue_led off
    ;;

    red_led_on)
      red_led on
    ;;

    red_led_off)
      red_led off
    ;;

    ir_led_on)
      ir_led on
    ;;

    ir_led_off)
      ir_led off
    ;;

    ir_cut_on)
      ir_cut on
    ;;

    ir_cut_off)
      ir_cut off
    ;;

    audio_test)
      F_audioSource=$(printf '%b' "${F_audioSource//%/\\x}")
      if [ "$F_audioSource" == "" ]; then
        F_audioSource="/mnt/media/police.wav"
      fi
      /mnt/bin/busybox nohup /mnt/bin/audioplay $F_audioSource $F_audiotestVol > /dev/null 2>&1 &
      echo  "Play $F_audioSource at volume $F_audiotestVol"
    ;;


    set_telnet)
      telnetport=$(echo "${F_telnetport}"| sed -e 's/+/ /g')
      echo "TELNET_PORT=$telnetport" > /mnt/config/telnetd.conf
      restart_service_if_need /mnt/controlscripts/telnet-server
      echo "<p>Setting telnet service port to : $telnetport</p>"
    ;;

    set_ftp)
      ftpport=$(echo "${F_ftpport}"| sed -e 's/+/ /g')
      echo "<p>Setting ftp service port to: $ftpport</p>"
      echo "PORT=$ftpport" > /mnt/config/ftp.conf
      restart_service_if_need /mnt/controlscripts/ftp-server
    ;;

    settz)
       ntp_srv=$(printf '%b' "${F_ntp_srv}")

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
      hst=$(printf '%b' "${F_hostname}")
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
      password=$(printf '%b' "${F_password//%/\\x}")
      echo "<p>Setting http password to : $password</p>"
      http_password "$password"
    ;;

    set_all_password)
      password=$(printf '%b' "${F_password//%/\\x}")
      echo "<p>Setting all services password to : $password</p>"
      all_password "$password"
      restart_service_if_need /mnt/controlscripts/ftp-server
      restart_service_if_need /mnt/controlscripts/telnet-server
      schedule_rtsp_restart
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

    auto_night_mode_start)
      /mnt/controlscripts/auto-night-detection start
    ;;

    auto_night_mode_stop)
      /mnt/controlscripts/auto-night-detection stop
    ;;

    toggle-rtsp-nightvision-on)
      /mnt/bin/setconf -k n -v 1
    ;;

    toggle-rtsp-nightvision-off)
      /mnt/bin/setconf -k n -v 0
    ;;

    night-mode-on)
      /mnt/controlscripts/night-mode start
    ;;

    night-mode-off)
      /mnt/controlscripts/night-mode stop
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

    service_trim_on)
      install_config /mnt/config/service_trim.conf
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 1
      echo "Service trimming enabled. Non-essential services will stop; reboot for full effect.<br/>"

      for svc in ftp-server telnet-server motion-detection recording timelapse auto-night-detection blue-led night-mode network-monitor; do
        if [ -x "/mnt/controlscripts/$svc" ]; then
          /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
        fi
      done
    ;;

    service_trim_off)
      install_config /mnt/config/service_trim.conf
      rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0
      echo "Service trimming disabled. Reboot to restore autostart services.<br/>"
    ;;

    set_performance_profile)
      install_config /mnt/config/boot.conf
      install_config /mnt/config/service_trim.conf
      profile=$(printf '%b' "${F_performance_profile}")

      case "$profile" in
        balanced)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 0
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 1
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-primary
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 0
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0

          echo "Performance profile set to Balanced.<br/>"
          echo "Dual stream + audio defaults enabled; reboot to restore all background services if they were trimmed.<br/>"
          ;;
        low-cpu)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_SUBSTREAM 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_AUDIO 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_MOTION 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_OSD 1
          rewrite_config /mnt/config/boot.conf LOW_CPU_DISABLE_JPEG 1
          rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM 0
          rewrite_config /mnt/config/boot.conf RTSP_AUDIO 0
          rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY main-only
          rewrite_config /mnt/config/boot.conf SERVICE_TRIM 0
          rewrite_config /mnt/config/service_trim.conf SERVICE_TRIM 0

          # Apply conservative stream settings immediately.
          /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
              0 width 640 0 height 360 0 fps 10 0 bps 600 0 goplen 20 0 brmode 1 \
              0 smartmode 1 0 smartgoplen 20 0 smartquality 60 0 smartstatic 350 0 maxkbps 800 0 targetkbps 600 \
              1 width 320 1 height 180 1 fps 5 1 bps 120 1 goplen 10 1 brmode 1 \
              1 smartmode 1 1 smartgoplen 10 1 smartquality 50 1 smartstatic 100 1 maxkbps 160 1 targetkbps 120

          echo "Performance profile set to Low CPU.<br/>"
          echo "Applied conservative RTSP settings now; reboot recommended for full low-CPU service profile.<br/>"
          ;;
        rtsp-only)
          rewrite_config /mnt/config/boot.conf LOW_CPU_PROFILE 1
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

          for svc in ftp-server telnet-server motion-detection recording timelapse auto-night-detection blue-led night-mode network-monitor; do
            if [ -x "/mnt/controlscripts/$svc" ]; then
              /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
            fi
          done

          echo "Performance profile set to RTSP + ONVIF only.<br/>"
          echo "Stopped non-essential services now; reboot to enforce trimmed autostart persistently.<br/>"
          ;;
        *)
          echo "Unknown performance profile '$profile'<br/>"
          exit 0
          ;;
      esac

      schedule_rtsp_restart
      schedule_onvif_restart
    ;;

    set_web_mode)
      install_config /mnt/config/boot.conf
      web_mode=$(printf '%b' "${F_web_mode}")
      ultralite_http_port=$(printf '%b' "${F_ultralite_http_port}")

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
    ;;

    set_stream_topology)
      install_config /mnt/config/boot.conf
      topology=$(printf '%b' "${F_stream_topology}")
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
      schedule_rtsp_restart
      schedule_onvif_restart
      echo "Stream topology set to: $topology_label<br/>"
    ;;

    set_onvif_stream_policy)
      install_config /mnt/config/boot.conf
      # shellcheck disable=SC1090
      if [ -f /mnt/config/boot.conf ]; then
        . /mnt/config/boot.conf
      fi

      policy=$(printf '%b' "${F_onvif_stream_policy}")
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
      schedule_onvif_restart

      echo "ONVIF stream policy set to: $policy_label<br/>"
      if [ "$RTSP_SUBSTREAM" != "1" ] && [ "$policy" != "main-primary" ] && [ "$policy" != "main-only" ]; then
        echo "Note: RTSP substream is disabled, ONVIF will fall back to main stream.<br/>"
      fi
    ;;

    set_rtsp_preset)
      preset=$(printf '%b' "${F_preset}")
      case "$preset" in
        full)
          width0=1280; height0=720; fps0=25; bps0=2000; gop0=50; maxkbps0=2500; targetkbps0=2000; smartq0=100; smartstatic0=550
          width1=640;  height1=360; fps1=10; bps1=300;  gop1=20; maxkbps1=400;  targetkbps1=300;  smartq1=70;  smartstatic1=150
          ;;
        medium)
          width0=1280; height0=720; fps0=20; bps0=1200; gop0=40; maxkbps0=1500; targetkbps0=1200; smartq0=80; smartstatic0=450
          width1=320;  height1=180; fps1=8;  bps1=200;  gop1=16; maxkbps1=250;  targetkbps1=200;  smartq1=60; smartstatic1=120
          ;;
        low)
          width0=640;  height0=360; fps0=10; bps0=600;  gop0=20; maxkbps0=800;  targetkbps0=600;  smartq0=60; smartstatic0=350
          width1=320;  height1=180; fps1=5;  bps1=120;  gop1=10; maxkbps1=160;  targetkbps1=120;  smartq1=50; smartstatic1=100
          ;;
        *)
          echo "Unknown preset '$preset'<br/>"
          exit 0
          ;;
      esac

      echo "RTSP preset applied: $preset (fps max 25)<br/>"

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

      schedule_rtsp_restart
    ;;

    set_video_size)
      wh0=${F_video_size0}
      width0="${wh0%x*}"
      height0="${wh0#*x}"

      wh1=${F_video_size1}
      width1="${wh1%x*}"
      height1="${wh1#*x}"

      username=$(printf '%b' "${F_videouser//%/\\x}")
      userpassword=$(printf '%b' "${F_videopassword//%/\\x}")

      echo "Video resolution set to $wh0 and $wh1<br/>"

      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " USERNAME "${username}" \
          " " USERPASSWORD "${userpassword}" \
          " " PORT "${F_videoport}" \
          0 bps          "${F_brbitrate0}" \
          0 brmode       "${F_video_format0}" \
          0 codec        "${F_video_codec0}" \
          0 fps          "${F_fps0}" \
          0 goplen       "${F_goplen0}" \
          0 height       "$height0" \
          0 maxqp        "${F_maxqp0}" \
          0 minqp        "${F_minqp0}" \
          0 profile      "${F_codec_profile0}" \
          0 width        "$width0" \
          0 smartmode    "${F_smartmode0}" \
          0 smartgoplen  "${F_smartgoplen0}" \
          0 smartquality "${F_smartquality0}" \
          0 smartstatic  "${F_smartstatic0}" \
          0 maxkbps      "${F_maxkbps0}" \
          0 targetkbps   "${F_targetkbps0}" \
          1 bps          "${F_brbitrate1}" \
          1 brmode       "${F_video_format1}" \
          1 codec        "${F_video_codec1}" \
          1 fps          "${F_fps1}" \
          1 goplen       "${F_goplen1}" \
          1 height       "$height1" \
          1 maxqp        "${F_maxqp1}" \
          1 minqp        "${F_minqp1}" \
          1 profile      "${F_codec_profile1}" \
          1 width        "$width1" \
          1 smartmode    "${F_smartmode1}" \
          1 smartgoplen  "${F_smartgoplen1}" \
          1 smartquality "${F_smartquality1}" \
          1 smartstatic  "${F_smartstatic1}" \
          1 maxkbps      "${F_maxkbps1}" \
          1 targetkbps   "${F_targetkbps1}" \

      schedule_rtsp_restart
    ;;


    conf_timelapse)
      tlinterval=$(printf '%b' "${F_tlinterval}")
      tlinterval=$(echo "$tlinterval" | sed "s/[^0-9\.]//g")
      if [ "$tlinterval" ]; then
        rewrite_config /mnt/config/timelapse.conf TIMELAPSE_INTERVAL "$tlinterval"
        echo "Timelapse interval set to $tlinterval seconds."
      else
        echo "Invalid timelapse interval"
      fi
      tlduration=$(printf '%b' "${F_tlduration}")
      tlduration=$(echo "$tlduration" | sed "s/[^0-9\.]//g")
      if [ "$tlduration" ]; then
        rewrite_config /mnt/config/timelapse.conf TIMELAPSE_DURATION "$tlduration"
        echo "Timelapse duration set to $tlduration minutes."
      else
        echo "Invalid timelapse duration"
      fi
    ;;

    conf_recording)
      motion_act=$(printf '%b' "${F_motion_act}")
      postrec=$(printf '%b' "${F_postrec}")
      maxduration=$(printf '%b' "${F_maxduration}")
      diskspace=$(printf '%b' "${F_diskspace}")

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

    conf_motiondetect)
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " mdsens ${F_mdsens} 
      /mnt/bin/setconf -k m -v "${F_mdsens}"
      rewrite_config /mnt/config/motion.conf motion_trigger_led "${F_motionBlink}"

      echo "Motion red led blink set to ${F_motionBlink}<BR>"
      echo "Motion sensitivity set to ${F_mdsens}<BR>"
    ;;

    conf_audioin)
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
          " " samplerate "${F_samplerate}" \
          " " volume "${F_audioinVol}" \
          2 codec "${F_audioCodec0}" \
          2 samplerate "${F_samplerate}" \
          3 codec "${F_audioCodec1}" \
          3 samplerate "${F_samplerate}"

       echo "In audio bitrate ${F_samplerate} <BR>"
       echo "Volume $F_audioinVol <BR>"

       schedule_rtsp_restart
     ;;


    conf_autodaynight)
        /mnt/bin/rwconf /mnt/config/rtspserver.conf w \
            " " daynightawb "${F_dnawb}" \
            " " daynightlum "${F_dnlum}" \
            " " nightdayawb "${F_ndawb}" \
            " " nightdaylum "${F_ndlum}"

        /mnt/bin/setconf -k r -v "${F_dnawb}"
        /mnt/bin/setconf -k a -v "${F_dnlum}"
        /mnt/bin/setconf -k b -v "${F_ndawb}"
        /mnt/bin/setconf -k d -v "${F_ndlum}"

        echo "daynightawb ${F_dnawb} <BR>"
        echo "daynightlum ${F_dnlum} <BR>"
        echo "nightdayawb ${F_ndawb} <BR>"
        echo "nightdaylum ${F_ndlum} <BR>"
     ;;


    conf_ptt)
        echo "$F_audiooutVol" > /mnt/config/pttvolume.conf
        echo "Push-to-talk volume set to $F_audiooutVol"
    ;;

     motion_detection_mail_on)
         rewrite_config /mnt/config/motion.conf sendemail "true"
         ;;

     motion_detection_mail_off)
          rewrite_config /mnt/config/motion.conf sendemail "false"
          ;;

     motion_detection_snapshot_on)
          rewrite_config /mnt/config/motion.conf save_snapshot "true"
          ;;

     motion_detection_snapshot_off)
          rewrite_config /mnt/config/motion.conf save_snapshot "false"
          ;;
     *)
        echo "Unsupported command '$F_cmd'"
        ;;

  esac
fi

echo "<hr/>"
