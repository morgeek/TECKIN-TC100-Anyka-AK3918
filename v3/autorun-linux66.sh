#!/bin/sh
# TC100 V3 Startup Script for Linux 6.6 LTS
echo "[tc100-v3] Starting V3 services..." > /dev/console
hostname tc100; echo "tc100" > /etc/hostname

mkdir -p /tmp/logs /var/run
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

# 2. Populate shared uClibc libraries into /lib (symlinks in flashmode to save ~1.8 MB RAM)
for f in /mnt/lib/*.so*; do
  [ -e "$f" ] || continue
  b="${f##*/}"
  if [ ! -e "/lib/$b" ]; then
    if [ -f /tmp/flashmode ]; then
      ln -sf "$f" "/lib/$b"
    else
      cp "$f" "/lib/$b" && chmod +x "/lib/$b" 2>/dev/null || true
    fi
  fi
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
#     /dev/uio0 (ak39_venc driver); without them the older tc100_streamer + thingino-rtsp-server path below is used.
NEWRTSP=0
TB=/mnt/tc100test
if [ -x $TB/tc100_rtsp ] && [ -f /mnt/lib/libmpi_venc_ex.so ] && [ -c /dev/uio0 ] && [ -f $TB/libakuio.so ]; then
  mkdir -p /lib/firmware/anyka
  for f in $TB/isp_f23_mipi_2lane.conf $TB/isp_f23_mipi2lane.conf /mnt/config/isp_f23_mipi_2lane.conf /mnt/config/isp.conf; do
    [ -f $f ] && { cp $f /lib/firmware/anyka/isp.conf; break; }
  done
  ln -sf /mnt/lib/ld-uClibc-0.9.33.2.so /lib/ld-uClibc.so.0
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
  killall -9 tc100_rtsp tc100_streamer thingino-rtsp-server 2>/dev/null
  if [ -f $TB/rtsp-launch.sh ]; then sh $TB/rtsp-launch.sh; else
  RTSP_LOG=/tmp/logs/tc100_rtsp.log
  [ -f /mnt/config/rtsp.debug ] && RTSP_LOG=/dev/console	# encoder messages on the serial console
  ( cd /tmp && { set -a; [ -f /mnt/config/rtsp.env ] && . /mnt/config/rtsp.env; set +a; }  # debug variables (AKUIO_*, RTSP_DEBUG)
    LD_LIBRARY_PATH=/mnt/lib exec /tmp/tc100_rtsp -c h265 -A /tmp/libakuio.so -p 554 -b "${RTSP_KBPS:-1500}" \
      -u "${RTSP_USER:-root}" -w "$PWD_FILE" -a "${RTSP_AUDIO:-1}" >"$RTSP_LOG" 2>&1 ) &
  fi
  NEWRTSP=1
  echo "[tc100-v3] free $RTSP_CODEC RTSP server + hardware JPEG pictures active (rtsp://<ip>:554/)" > /dev/console
fi

killall -9 tc100_streamer 2>/dev/null
if [ "$NEWRTSP" = 1 ]; then
  :
elif [ -x /mnt/bin/tc100_streamer ]; then
  /mnt/bin/tc100_streamer -d
  echo "[tc100-v3] Hardware V4L2 optical streamer active" > /dev/console
elif [ -x /mnt/tc100test/tc100_streamer ]; then
  /mnt/tc100test/tc100_streamer -d
  echo "[tc100-v3] Hardware V4L2 optical streamer active (tc100test)" > /dev/console
fi

# 5. Seed initial snapshot cache if missing
if [ ! -f /tmp/currentpic.cache.jpg ] && [ -f /mnt/tc100test/tc100-linux66-color-frame.jpg ]; then
  cp /mnt/tc100test/tc100-linux66-color-frame.jpg /tmp/currentpic.cache.jpg
fi
[ -f /tmp/currentpic.cache.jpg ] && date +%s > /tmp/currentpic.cache.ts

# 6. Start Web Server on port 80
killall httpd httpfront 2>/dev/null
# the busybox httpd of the base image answers 404 for "/" (no directory index): httpfront redirects it to /index.html
if [ -x /mnt/tc100test/httpfront ]; then
  /mnt/tc100test/httpfront -p 80 -h /tmp/www &
else
  /usr/sbin/httpd -p 80 -h /tmp/www
fi
echo "[tc100-v3] WebUI active on port 80" > /dev/console

# 7. Start RTSP Server on port 554 (RFC 2435 JPEG stream)
[ "$NEWRTSP" = 1 ] || killall -9 thingino-rtsp-server 2>/dev/null
sleep 0.5
if [ "$NEWRTSP" = 1 ]; then
  :
elif [ -x /mnt/tc100test/thingino-rtsp-server ]; then
  # One password for the whole camera, as in the main firmware: config/user.pwd
  # (seeded from the .dist template, never in git). It goes through a private
  # config file, not the command line, so it does not show in `ps`.
  PWD_FILE=/mnt/config/user.pwd
  [ -s "$PWD_FILE" ] || { [ -s "$PWD_FILE.dist" ] && cp "$PWD_FILE.dist" "$PWD_FILE"; }
  RTSP_CONF=/tmp/rtsp-server.conf
  ( umask 077
    { echo "port=554"
      if [ -s "$PWD_FILE" ]; then
        echo "username=${RTSP_USER:-root}"
        echo "password=$(head -n 1 "$PWD_FILE")"
      fi
    } > "$RTSP_CONF" )
  /mnt/tc100test/thingino-rtsp-server -c "$RTSP_CONF" -d
  echo "[tc100-v3] RTSP stream active on port 554 (path /ch0)" > /dev/console
fi

# 8. Start ONVIF Discovery (monvifd)
if [ -x /mnt/controlscripts/onvif ]; then
  /mnt/controlscripts/onvif restart >/dev/null 2>&1
  echo "[tc100-v3] ONVIF service active on port 8081 & WS-Discovery UDP 3702" > /dev/console
fi

# 9. Start Auto Day/Night Detection
if [ -x /mnt/controlscripts/auto-night-detection ]; then
  /mnt/controlscripts/auto-night-detection start >/dev/null 2>&1
  echo "[tc100-v3] Auto Day/Night detection active" > /dev/console
fi

# 10. Start MQTT Bridge
if [ -x /mnt/controlscripts/mqtt-bridge ]; then
  /mnt/controlscripts/mqtt-bridge start >/dev/null 2>&1
  echo "[tc100-v3] MQTT bridge service launched" > /dev/console
fi

# 11. Start Motion Detection
if [ -x /mnt/controlscripts/motion-detection ]; then
  /mnt/controlscripts/motion-detection start >/dev/null 2>&1
  echo "[tc100-v3] Motion detection service active" > /dev/console
fi

# 12. Start Recording (if enabled and SD card is mounted for video storage)
if [ -x /mnt/controlscripts/recording ] && grep -qE ' (/mnt/sd|/mnt) vfat ' /proc/mounts; then
  /mnt/controlscripts/recording start >/dev/null 2>&1
  echo "[tc100-v3] Recording service launched" > /dev/console
fi

# 12a. Clock: the SoC has no battery-backed time (it starts in 1970), so recordings, logs and MQTT stamps would be
#      wrong. Set it with ntpd once the Wi-Fi is up (server: first line of config/ntp_srv.conf, else pool.ntp.org),
#      then every hour. The time zone comes from config/timezone.conf (Services/Système page).
S=$(head -n 1 /mnt/config/ntp_srv.conf 2>/dev/null); [ -n "$S" ] || S=pool.ntp.org
ntpd -p "$S" </dev/null >/dev/null 2>&1 &

# 12b. Services switched on in the web UI (Services page, "Démarrage" toggle = file in config/autostart).
#      Started detached, one after the other. Left out: the ones started above, the system entries (numbered), and
#      cpu-scaler (it scales the vendor RTSP server's frame rate; nothing to scale here).
for f in /mnt/config/autostart/*; do
  n=${f##*/}
  case "$n" in [0-9]*|\*|cpu-scaler|rtsp-h26x|onvif|auto-night-detection|mqtt-bridge|motion-detection|recording) continue ;; esac
  [ -x /mnt/controlscripts/$n ] && sh /mnt/controlscripts/$n start </dev/null >/dev/null 2>&1 &
  sleep 1
done

# 13. Low memory (45 MB, no swap): when the web pages start many CGI processes at once the kernel OOM killer may
#     run. The streaming server, the web server and ONVIF must never be its victims (shells and CGIs may be).
for p in tc100_rtsp httpfront lighttpd monvifd ffmpeg-min-recorder; do
  for pid in $(pidof $p 2>/dev/null); do echo -900 > /proc/$pid/oom_score_adj 2>/dev/null; done
done

echo "[tc100-v3] All services initialized successfully." > /dev/console
