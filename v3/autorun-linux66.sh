#!/bin/sh
# TC100 V3 Startup Script for Linux 6.6 LTS
echo "[tc100-v3] Starting V3 services..." > /dev/console
# Host name: config/hostname.conf (Settings -> Network), as on 2.x; "tc100" while it is the shipped placeholder, so that
# http://tc100/ finds a new camera on most home routers (the name goes to the router with the DHCP request).
H=$(grep -v '^#' /mnt/config/hostname.conf 2>/dev/null | grep -v '^[[:space:]]*$' | head -n 1 | tr -cd 'A-Za-z0-9-')
case "$H" in ''|TC100-CAMERA) H=tc100 ;; esac
hostname "$H"; echo "$H" > /etc/hostname
# the boot script asked for a lease as "tc100": ask again with this name (net-apply, step 1c, starts udhcpc)
[ "$H" = tc100 ] || killall udhcpc 2>/dev/null

mkdir -p /tmp/logs /var/run
# Scripts and CGIs shared with 2.x test this marker to take the Linux 6.6 path
: > /tmp/linux66
# Free tools from the Buildroot base that the initramfs leaves out (curl, jq, iw, wpa_cli, hostapd), in the user space
export PATH=/mnt/ext/bin:$PATH CURL_CA_BUNDLE=/mnt/ext/etc/ssl/certs/ca-certificates.crt
for l in /lib/ld-musl-*.so.1; do	# their libraries: /mnt/ext/lib on the musl search path
  [ -e "$l" ] || continue; n=${l##*/ld-musl-}; echo /lib /usr/lib /mnt/ext/lib | tr ' ' '\n' > /etc/ld-musl-${n%.so.1}.path
done
[ -f /var/run/vday ] || echo 1 > /var/run/vday
[ -f /var/run/ircut ] || echo 1 > /var/run/ircut

# 0a. Memory watermarks. With 45 MB of usable RAM the kernel's default "watermark boost" (4 MB) and the 4 MB
#     high-order atomic reserve made the OOM killer fire with ~6 MB still free, killing small daemons (mqtt bridge,
#     auto day/night) when the web UI started several CGI processes at once.
echo 0 > /proc/sys/vm/watermark_boost_factor 2>/dev/null
echo 1024 > /proc/sys/vm/min_free_kbytes 2>/dev/null

# 0. Start Hardware Watchdog keeper (feed every 15s, 60s timeout)
killall watchdog 2>/dev/null
watchdog -t 15 -T 60 /dev/watchdog >/dev/null 2>&1 &
# never the out-of-memory victim: without its keeper the hardware watchdog restarts the camera 60 s later, even in
# the middle of a flash write
echo -1000 > /proc/$!/oom_score_adj 2>/dev/null

# 0b. The user space (web pages, scripts, status checks) expects its files under /mnt. SD mode: the card is mounted
#     there and /mnt/sd is an alias (the card has an empty "sd" folder for that second mount). Flash mode
#     (/tmp/flashmode, set by flashmode-prep.sh): /mnt already holds the user space from the SPI flash and the card,
#     if any, is the video storage at /mnt/sd: nothing to mount.
if [ ! -f /tmp/flashmode ] && ! grep -q ' /mnt vfat ' /proc/mounts && [ -b /dev/mmcblk0p1 ]; then
  mkdir -p /mnt/sd/sd
  mount -t vfat -o rw,noatime /dev/mmcblk0p1 /mnt && mount -t vfat -o rw,noatime /dev/mmcblk0p1 /mnt/sd
fi

# 1. Setup /mnt symlinks (only when the card is not mounted at /mnt itself)
for d in bin config controlscripts lib scripts www; do
  [ -d /mnt/sd/$d ] && [ ! -d /mnt/$d ] && ln -sfn /mnt/sd/$d /mnt/$d
done

# 1-hw. Which board is this? A read-only inventory (now, while the kernel log still holds the sensor id) chooses the
#     board profile (v3/board/*.conf: IR-cut GPIOs, LEDs, sensor tuning); /tmp/board.conf links to it. An unknown
#     camera gets the first profile, and the flash install refuses it (install66.sh).
sh /mnt/v3/install/inventory.sh --quick > /tmp/inventory.txt 2>/dev/null
BOARD=$(sh /mnt/v3/install/hwcheck.sh /tmp/inventory.txt /mnt/v3/board 2>/dev/null) && BOARD=${BOARD#board=} || BOARD=
echo "${BOARD:-unknown}" > /tmp/board
for f in /mnt/v3/board/${BOARD:-*}.conf; do [ -f "$f" ] && { ln -sf "$f" /tmp/board.conf; break; }; done
echo "[tc100-v3] board profile: ${BOARD:-unknown hardware, defaults of $(readlink /tmp/board.conf 2>/dev/null)}" > /dev/console

# 1a. SD mode on a new card: every shipped *.dist becomes the live setting until the user changes it (flash mode:
#     flashmode-prep.sh does the same).
if [ ! -f /tmp/flashmode ]; then
  for f in /mnt/config/*.dist; do
    b=${f%.dist}
    [ -e "$b" ] || cp "$f" "$b"
  done
fi
# first start of 3.0 (even with settings brought over from 2.x): the web pages open the setup wizard
[ -f /mnt/config/.wizard3_done ] || : > /tmp/.first_boot

# 1b. wifi.txt at the root of the card (SSID=, PASSWORD=), like 2.x: the new network goes first in
#     config/wpa_supplicant.conf, the previous ones stay as fallbacks, and it is used at once.
if [ -f /mnt/sd/wifi.txt ] && [ -f /mnt/scripts/wifi-txt.sh ]; then
  W=/mnt/config/wpa_supplicant.conf
  [ -f $W ] || cp /etc/wpa_supplicant.conf $W 2>/dev/null
  sh /mnt/scripts/wifi-txt.sh apply /mnt/sd/wifi.txt $W && ( sh /mnt/v3/linux66-sd/wifi-apply 0 </dev/null >/dev/null 2>&1 & )
fi

# 1c. Network settings (static address, custom DNS servers) over what the boot script's DHCP gave, as 2.x did
sh /mnt/v3/linux66-sd/net-apply </dev/null >/dev/null 2>&1

# 1d. Choices of boot.conf that 2.x autorun.sh applied at each start (read here, no sourcing of the whole file)
bootv() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}\$/\1/p" /mnt/config/boot.conf 2>/dev/null | tail -n 1; }
on() { case "$1" in 1|true|yes|on|enabled) return 0 ;; esac; return 1; }
PROFILE=$(bootv INTEGRATION_PROFILE); LIGHT=$(bootv LIGHTWEIGHT_MODE)
# Frigate + Home Assistant profile: Frigate detects and stamps the picture itself (2.x apply_frigate_ha_rtsp_profile)
if [ "$PROFILE" = frigate_ha ] && [ -x /mnt/bin/rwconf ]; then
  LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " mdenabled 0 2>/dev/null
  LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " osdenabled 0 2>/dev/null
fi

# 2. Populate shared uClibc libraries into /lib: symlinks, except on the card (SD mode) for the small uClibc runtime,
#    copied to RAM so that the programs keep their loader if the card has trouble. Everything else of lib/ stays a
#    link: a card used by older firmwares holds ~15 MB of libraries (libcrypto, libliveMedia, 3 x libstdc++...)
#    whose copy into RAM left the 6.6 trial mode without memory.
for f in /mnt/lib/*.so*; do
  [ -e "$f" ] || continue
  b="${f##*/}"
  [ -e "/lib/$b" ] && continue
  case "$b" in
    ld-uClibc*|libc.so.0|libuClibc-*|libdl*|libm.so*|libm-*|libpthread*|librt*|libgcc_s*|libcrypt*)
      if [ -f /tmp/flashmode ]; then ln -sf "$f" "/lib/$b"; else cp "$f" "/lib/$b" && chmod +x "/lib/$b" 2>/dev/null || true; fi ;;
    *) ln -sf "$f" "/lib/$b" ;;
  esac
done

# 3. Setup WebUI document root in RAM
mkdir -p /tmp/www
for f in /mnt/www/*; do
  ln -sfn "$f" /tmp/www/$(basename "$f")
done
ln -sfn /tmp/currentpic.cache.jpg /tmp/www/ch0.jpg
ln -sfn /tmp/stream.jpg /tmp/frame_ch0.jpg

# 4. Wait for /dev/video0 and start Hardware V4L2 Optical Streamer
for i in $(seq 1 25); do
  [ -c /dev/video0 ] && break
  sleep 0.2
done

# 4a. Free hardware encoder stack (tc100_rtsp): H.265/H.264 over RTSP and the web UI pictures (stream.jpg, currentpic,
#     cam_luma) from the hardware JPEG engine, one process. Needs the vendor encoder libraries in /mnt/lib and
#     /dev/uio0 (ak39_venc driver); without them there is no video (the web UI still starts).
NEWRTSP=0
TB=/mnt/tc100test
if [ -x $TB/tc100_rtsp ] && { [ -f /mnt/lib/libmpi_venc_ex.so ] || [ -f /mnt/lib/libmpi_venc.so ]; } && [ -c /dev/uio0 ] && [ -f $TB/libakuio.so ]; then
  mkdir -p /lib/firmware/anyka
  # sensor tuning of this camera: the vendor partition (flash), else the card (copied there by the install hook)
  ISPN=$(sed -n 's/^ISP_CONF=//p' /tmp/board.conf 2>/dev/null | head -n 1)
  for f in /vendor/isp.conf ${ISPN:+/mnt/config/$ISPN /mnt/sd/config/$ISPN} /mnt/config/isp_f23_mipi_2lane.conf /mnt/sd/config/isp_f23_mipi_2lane.conf $TB/isp_f23_mipi_2lane.conf $TB/isp_f23_mipi2lane.conf /mnt/config/isp.conf; do
    [ -f $f ] && { cp $f /lib/firmware/anyka/isp.conf; break; }
  done
  [ -e /mnt/lib/ld-uClibc-0.9.33.2.so ] && ln -sf /mnt/lib/ld-uClibc-0.9.33.2.so /lib/ld-uClibc.so.0
  cp $TB/libakuio.so /tmp/libakuio.so; cp $TB/tc100_rtsp /tmp/tc100_rtsp; chmod +x /tmp/tc100_rtsp
  PWD_FILE=/mnt/config/user.pwd
  [ -s "$PWD_FILE" ] || { [ -s "$PWD_FILE.dist" ] && cp "$PWD_FILE.dist" "$PWD_FILE"; }
  # The vendor services (recording, ONVIF...) and the web UI read codec, bit rate and credentials from rtspserver.conf.
  # config/rtsp.codec (h264|h265), if present, seeds the codec there; otherwise what the web UI saved is kept
  # (default H.265 like the original firmware). rtsp-launch.sh then starts tc100_rtsp from that file.
  if [ -x /mnt/bin/rwconf ] && [ -d /mnt/config ]; then
    RC=/mnt/config/rtspserver.conf
    export LD_LIBRARY_PATH=/mnt/lib
    [ -f /mnt/config/rtsp.codec ] && {
      [ "$(head -n 1 /mnt/config/rtsp.codec)" = h264 ] && CODEC_NUM=1 || CODEC_NUM=2
      /mnt/bin/rwconf $RC w 0 codec $CODEC_NUM
    }
    if [ -s "$PWD_FILE" ]; then
      /mnt/bin/rwconf $RC w " " USERNAME "${RTSP_USER:-root}"
      /mnt/bin/rwconf $RC w " " USERPASSWORD "$(head -n 1 "$PWD_FILE")"
    fi
    unset LD_LIBRARY_PATH
  fi
  sh $TB/rtsp-launch.sh
  # the 6.6 kernel logs the sensor id only once the video is open: choose the board profile again then
  ( sleep 20; sh /mnt/v3/install/inventory.sh --quick > /tmp/inventory.txt.new 2>/dev/null && mv /tmp/inventory.txt.new /tmp/inventory.txt
    B=$(sh /mnt/v3/install/hwcheck.sh /tmp/inventory.txt /mnt/v3/board 2>/dev/null) && { echo "${B#board=}" > /tmp/board; ln -sf "/mnt/v3/board/${B#board=}.conf" /tmp/board.conf; } ) </dev/null >/dev/null 2>&1 &
  NEWRTSP=1
  echo "[tc100-v3] free RTSP server + hardware JPEG pictures active (rtsp://<ip>:554/)" > /dev/console
else
  echo "[tc100-v3] no video: tc100_rtsp, the encoder libraries (/mnt/lib) or /dev/uio0 missing" > /dev/console
fi

# 5. (the picture cache is written by tc100_rtsp)

# 6. Start Web Server on port 80, with the camera password (root + config/user.pwd, like 2.x)
killall httpd httpfront 2>/dev/null
sh /mnt/v3/linux66-sd/web-auth
# the busybox httpd of the base image answers 404 for "/" (no directory index): httpfront redirects it to /index.html
if [ -x /mnt/tc100test/httpfront ]; then
  /mnt/tc100test/httpfront -p 80 -h /tmp/www &
else
  /usr/sbin/httpd -p 80 -h /tmp/www
fi
echo "[tc100-v3] WebUI active on port 80" > /dev/console

# 7. (RTSP: tc100_rtsp, step 4a)

# 8. Steps 8 onwards run the control scripts (/tmp/linux66, created at the top of this script, tells shared scripts
#    they run on 3.0). Files from the repository may lack the execute bit: always run
#    them with sh.
: > /tmp/linux66
CS=/mnt/controlscripts
# RTSP restarter (scripts/service-watchdog.sh through the rtsp-h26x shim): tc100_rtsp was started above
[ "$NEWRTSP" = 1 ] && [ -f $CS/rtsp-h26x ] && sh $CS/rtsp-h26x watchdog </dev/null >/dev/null 2>&1
# ONVIF Discovery (monvifd): off by default as on 2.x, on when switched on in Services (config/autostart/onvif)
if [ -f $CS/onvif ] && [ -e /mnt/config/autostart/onvif ]; then
  sh $CS/onvif restart </dev/null >/dev/null 2>&1
  echo "[tc100-v3] ONVIF service active on port 8081 & WS-Discovery UDP 3702" > /dev/console
fi

# 9. Day/night. The IR-cut coil is pulsed once to the position the state file says (day after boot), then the
#    automatic switching starts unless it was switched off (Services, or "Day" / "Night" under the picture:
#    no config/autostart/auto-night-detection, or daynight=3 in rtspserver.conf).
sh /mnt/bin/setconf -k e -v "$(cat /var/run/ircut 2>/dev/null || echo 1)" </dev/null >/dev/null 2>&1
DN=$(sed -n 's/^daynight=//p' /mnt/config/rtspserver.conf 2>/dev/null | head -n 1)
if [ -f $CS/auto-night-detection ] && [ -f /mnt/config/autostart/auto-night-detection ] && [ "$DN" != 3 ]; then
  sh $CS/auto-night-detection start </dev/null >/dev/null 2>&1
  echo "[tc100-v3] Auto Day/Night detection active" > /dev/console
fi

# 10. MQTT Bridge (it does nothing unless MQTT_ENABLE=1 in config/mqtt.conf)
if [ -f $CS/mqtt-bridge ]; then
  sh $CS/mqtt-bridge start </dev/null >/dev/null 2>&1
  echo "[tc100-v3] MQTT bridge service launched" > /dev/console
fi

# 11. Motion detection (in tc100_rtsp): only when the web UI left it on (rtspserver.conf mdenabled=1, or the Services
#     page's start-at-boot toggle config/autostart/motion-detection); otherwise it stays off, as on 2.x.
if [ -f $CS/motion-detection ] && { grep -q '^mdenabled=1' /mnt/config/rtspserver.conf 2>/dev/null || [ -e /mnt/config/autostart/motion-detection ]; }; then
  sh $CS/motion-detection start </dev/null >/dev/null 2>&1
  echo "[tc100-v3] Motion detection service active" > /dev/console
else
  rm -f /tmp/tc100_md
fi

# 12. Recording: the recorder is inside tc100_rtsp and follows REC_LOCAL of boot.conf by itself (it waits for a card).
#     The Services page's start-at-boot toggle (config/autostart/recording) turns REC_LOCAL on, as 2.x started it.
if [ -f $CS/recording ] && [ -e /mnt/config/autostart/recording ]; then
  sh $CS/recording start </dev/null >/dev/null 2>&1
  echo "[tc100-v3] Recording on" > /dev/console
fi

# 12a. Clock: the SoC has no battery-backed time (it starts in 1970), so recordings, logs and MQTT stamps would be
#      wrong. Set it with ntpd once the Wi-Fi is up (server: first line of config/ntp_srv.conf, else pool.ntp.org),
#      then every hour. The time zone comes from config/timezone.conf (Services/Système page).
#      ENABLE_NTP=0 in boot.conf turns it off.
if [ "$(bootv ENABLE_NTP)" != 0 ]; then
  S=$(head -n 1 /mnt/config/ntp_srv.conf 2>/dev/null); [ -n "$S" ] || S=pool.ntp.org
  ntpd -p "$S" </dev/null >/dev/null 2>&1 &
fi
# Scheduled reboot (Settings -> System): the managed entry of config/cron/crontabs/root, run by crond
if on "$(bootv ENABLE_CROND)" || on "$(bootv REBOOT_SCHEDULE_ENABLE)"; then
  mkdir -p /mnt/config/cron/crontabs
  crond -c /mnt/config/cron/crontabs </dev/null >/dev/null 2>&1
fi
# LEDs as set in Settings (FRONT_LED / RED_LED), not left as the boot found them
sh -c '. /mnt/scripts/common_functions.sh
  case "$1" in 1|true|yes|on) front_led on ;; *) front_led off ;; esac
  case "$2" in 1|true|yes|on) red_led on ;; *) red_led off ;; esac' _ "$(bootv FRONT_LED)" "$(bootv RED_LED)" </dev/null >/dev/null 2>&1

# 12b. Services switched on in the web UI (Services page, "Boot" toggle = file in config/autostart): button-actions,
#      wifi-rescue, memory-guard, health-snapshot, telegram-bot, ftp/telnet... Started detached, one after the other.
#      Left out: the ones started above, the numbered system entries of 2.x (their work is done by httpfront and
#      step 12c here) and web-server (httpfront, step 6).
for f in /mnt/config/autostart/*; do
  n=${f##*/}
  case "$n" in [0-9]*|\*|cpu-scaler|web-server|rtsp-h26x|onvif|auto-night-detection|mqtt-bridge|motion-detection|recording) continue ;; esac
  # as on 2.x: the lightweight mode and the Frigate + Home Assistant profile keep some services off at boot
  on "$LIGHT" && case "$n" in front-led) continue ;; esac
  [ "$PROFILE" = frigate_ha ] && case "$n" in telegram-bot|syslog-forward|sound-detection|ftp-server|telnet-server) continue ;; esac
  [ -f $CS/$n ] && sh $CS/$n start </dev/null >/dev/null 2>&1 &
  sleep 1
done

# 12c. Every minute (scripts/web-guard.sh): the web server answers (else restart httpfront, then a rescue telnet),
#      the network (net-guard.sh: reboot after NET_GUARD_MIN minutes without the gateway) and the SD card panel
#      (sdinfo-sd.sh, also run once now).
sh /mnt/v3/linux66-sd/sdinfo-sd.sh </dev/null >/dev/null 2>&1
# the Recordings page plays and downloads /DCIM/<clip>.mkv and shows /DCIM/<clip>.jpg
[ -e /tmp/www/DCIM ] || ln -sfn /mnt/DCIM /tmp/www/DCIM
( exec sh /mnt/scripts/web-guard.sh run ) </dev/null >/dev/null 2>&1 &

# 12d. Update notice (boot.conf UPDATE_CHECK=1): asks GitHub once the clock is set (curl + jq of the flash image)
case "$(sed -n 's/^UPDATE_CHECK="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' /mnt/config/boot.conf 2>/dev/null | tail -n 1)" in
  1|true|yes|on) ( sleep 120; exec sh /mnt/scripts/update-check.sh ) </dev/null >/dev/null 2>&1 & ;;
esac

# 12e. Tell the user the camera is ready: the startup chime of 2.x on the speaker (BOOT_SOUND=0 in boot.conf: silent),
#      and how to reach it, on the card (tc100-3/ADRESSE.txt, Windows line ends): its address once the network gave
#      one; without a network after 12 minutes, the name and password of its rescue access point (scripts/wifi-rescue.sh
#      starts it after 10 minutes without Wi-Fi), so that a camera with a wrong or missing wifi.txt can still be set up.
[ "$(bootv BOOT_SOUND)" = 0 ] || ( sleep 3; sh /mnt/scripts/speaker-play.sh /mnt/sounds/startup_complete.pcm 60 ) </dev/null >/dev/null 2>&1 &
( i=0; IP=
  while [ $i -lt 144 ]; do
    IP=$(ip -4 addr show wlan0 2>/dev/null | sed -n 's/.*inet \([0-9.]*\).*/\1/p' | head -n 1)
    [ -n "$IP" ] && [ "$IP" != 10.42.0.1 ] && break
    IP=; sleep 5; i=$((i + 1))
  done
  grep -q ' /mnt/sd vfat ' /proc/mounts || exit 0
  mkdir -p /mnt/sd/tc100-3
  if [ -n "$IP" ]; then
    printf 'TC100 %s\r\nWeb page: http://%s/  (or http://%s/)\r\nRTSP: rtsp://%s:554/video0_unicast\r\nWritten %s\r\n' \
      "$(cat /mnt/VERSION 2>/dev/null)" "$IP" "$(hostname)" "$IP" "$(date '+%Y-%m-%d %H:%M')"
  else
    S=$(sh /mnt/scripts/wifi-rescue.sh status 2>/dev/null)
    printf 'TC100 %s: no Wi-Fi network after 12 minutes (wrong or missing wifi.txt?).\r\n' "$(cat /mnt/VERSION 2>/dev/null)"
    printf 'Connect a phone or computer to the camera'"'"'s own Wi-Fi:\r\n  name: %s\r\n  password: %s\r\n' \
      "$(echo "$S" | sed -n 's/^ssid=//p')" "$(echo "$S" | sed -n 's/^psk=//p')"
    printf 'then open http://10.42.0.1/ and set the Wi-Fi in Settings -> Network.\r\n'
    printf 'Or: power off, put a wifi.txt (SSID=..., PASSWORD=...) at the root of this card, power on.\r\n'
  fi > /mnt/sd/tc100-3/ADRESSE.txt
  sync ) </dev/null >/dev/null 2>&1 &

# 13. Low memory (45 MB, no swap): when the web pages start many CGI processes at once the kernel OOM killer may
#     run. The streaming server, the web server and ONVIF must never be its victims (shells and CGIs may be).
for p in tc100_rtsp httpfront monvifd; do
  for pid in $(pidof $p 2>/dev/null); do echo -900 > /proc/$pid/oom_score_adj 2>/dev/null; done
done

echo "[tc100-v3] All services initialized successfully." > /dev/console
