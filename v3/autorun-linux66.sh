#!/bin/sh
# TC100 V3 Startup Script for Linux 6.6 LTS
echo "[tc100-v3] Starting V3 services..." > /dev/console
hostname tc100; echo "tc100" > /etc/hostname

mkdir -p /tmp/logs /var/run

# 0. Start Hardware Watchdog keeper (feed every 15s, 60s timeout)
killall watchdog 2>/dev/null
watchdog -t 15 -T 60 /dev/watchdog >/dev/null 2>&1 &

# 1. Setup /mnt symlinks
for d in bin config controlscripts lib scripts www; do
  [ -d /mnt/sd/$d ] && ln -sfn /mnt/sd/$d /mnt/$d
done

# 2. Populate shared uClibc libraries into /lib with execute permissions
for lib in libpthread.so.0 libdl.so.0 libm.so.0 libstdc++.so.6 libgcc_s.so.1 libcrypt.so.0 librt.so.0 libwolfmqtt.so.5 libzbar.so.0; do
  [ ! -f /lib/$lib ] && [ -f /mnt/sd/lib/$lib ] && cp /mnt/sd/lib/$lib /lib/
done
chmod +x /lib/ld* /lib/lib* 2>/dev/null || true

# 3. Setup WebUI document root in RAM
mkdir -p /tmp/www
for f in /mnt/sd/www/*; do
  ln -sfn "$f" /tmp/www/$(basename "$f")
done
ln -sfn /tmp/currentpic.cache.jpg /tmp/www/ch0.jpg
ln -sfn /tmp/stream.jpg /tmp/frame_ch0.jpg

# 4. Wait for /dev/video0 and start Hardware V4L2 Optical Streamer
for i in $(seq 1 25); do
  [ -c /dev/video0 ] && break
  sleep 0.2
done

# 4a. Free hardware encoder stack (tc100_rtsp): H.264 over RTSP and the web UI pictures (stream.jpg, currentpic,
#     cam_luma) from the hardware JPEG engine, one process. Needs the vendor encoder libraries in /mnt/sd/lib and
#     /dev/uio0 (ak39_venc driver); without them the older tc100_streamer + thingino-rtsp-server path below is used.
NEWRTSP=0
TB=/mnt/sd/tc100test
if [ -x $TB/tc100_rtsp ] && [ -f /mnt/sd/lib/libmpi_venc_ex.so ] && [ -c /dev/uio0 ] && [ -f $TB/libakuio.so ]; then
  mkdir -p /lib/firmware/anyka
  for f in $TB/isp_f23_mipi_2lane.conf $TB/isp_f23_mipi2lane.conf /mnt/sd/config/isp.conf; do
    [ -f $f ] && { cp $f /lib/firmware/anyka/isp.conf; break; }
  done
  ln -sf /mnt/sd/lib/ld-uClibc-0.9.33.2.so /lib/ld-uClibc.so.0
  cp $TB/libakuio.so /tmp/libakuio.so; cp $TB/tc100_rtsp /tmp/tc100_rtsp; chmod +x /tmp/tc100_rtsp
  PWD_FILE=/mnt/sd/config/user.pwd
  [ -s "$PWD_FILE" ] || { [ -s "$PWD_FILE.dist" ] && cp "$PWD_FILE.dist" "$PWD_FILE"; }
  killall -9 tc100_rtsp tc100_streamer thingino-rtsp-server 2>/dev/null
  ( cd /tmp && LD_LIBRARY_PATH=/mnt/sd/lib exec /tmp/tc100_rtsp -A /tmp/libakuio.so -p 554 -b "${RTSP_KBPS:-1500}" \
      -u "${RTSP_USER:-root}" -w "$PWD_FILE" >/tmp/logs/tc100_rtsp.log 2>&1 ) &
  # the vendor services (recording, ONVIF...) read codec and credentials from rtspserver.conf: keep it in step with
  # what tc100_rtsp serves (H.264, the camera password)
  if [ -x /mnt/bin/rwconf ] && [ -d /mnt/config ]; then
    RC=/mnt/config/rtspserver.conf
    export LD_LIBRARY_PATH=/mnt/sd/lib
    /mnt/bin/rwconf $RC w 0 codec 1
    if [ -s "$PWD_FILE" ]; then
      /mnt/bin/rwconf $RC w " " USERNAME "${RTSP_USER:-root}"
      /mnt/bin/rwconf $RC w " " USERPASSWORD "$(head -n 1 "$PWD_FILE")"
    fi
    unset LD_LIBRARY_PATH
  fi
  NEWRTSP=1
  echo "[tc100-v3] free H.264 RTSP server + hardware JPEG pictures active (rtsp://<ip>:554/)" > /dev/console
fi

killall -9 tc100_streamer 2>/dev/null
if [ "$NEWRTSP" = 1 ]; then
  :
elif [ -x /mnt/sd/bin/tc100_streamer ]; then
  /mnt/sd/bin/tc100_streamer -d
  echo "[tc100-v3] Hardware V4L2 optical streamer active" > /dev/console
elif [ -x /mnt/sd/tc100test/tc100_streamer ]; then
  /mnt/sd/tc100test/tc100_streamer -d
  echo "[tc100-v3] Hardware V4L2 optical streamer active (tc100test)" > /dev/console
fi

# 5. Seed initial snapshot cache if missing
if [ ! -f /tmp/currentpic.cache.jpg ] && [ -f /mnt/sd/tc100test/tc100-linux66-color-frame.jpg ]; then
  cp /mnt/sd/tc100test/tc100-linux66-color-frame.jpg /tmp/currentpic.cache.jpg
fi
[ -f /tmp/currentpic.cache.jpg ] && date +%s > /tmp/currentpic.cache.ts

# 6. Start Web Server on port 80
killall httpd httpfront 2>/dev/null
# the busybox httpd of the base image answers 404 for "/" (no directory index): httpfront redirects it to /index.html
if [ -x /mnt/sd/tc100test/httpfront ]; then
  /mnt/sd/tc100test/httpfront -p 80 -h /tmp/www &
else
  /usr/sbin/httpd -p 80 -h /tmp/www
fi
echo "[tc100-v3] WebUI active on port 80" > /dev/console

# 7. Start RTSP Server on port 554 (RFC 2435 JPEG stream)
[ "$NEWRTSP" = 1 ] || killall -9 thingino-rtsp-server 2>/dev/null
sleep 0.5
if [ "$NEWRTSP" = 1 ]; then
  :
elif [ -x /mnt/sd/tc100test/thingino-rtsp-server ]; then
  # One password for the whole camera, as in the main firmware: config/user.pwd
  # (seeded from the .dist template, never in git). It goes through a private
  # config file, not the command line, so it does not show in `ps`.
  PWD_FILE=/mnt/sd/config/user.pwd
  [ -s "$PWD_FILE" ] || { [ -s "$PWD_FILE.dist" ] && cp "$PWD_FILE.dist" "$PWD_FILE"; }
  RTSP_CONF=/tmp/rtsp-server.conf
  ( umask 077
    { echo "port=554"
      if [ -s "$PWD_FILE" ]; then
        echo "username=${RTSP_USER:-root}"
        echo "password=$(head -n 1 "$PWD_FILE")"
      fi
    } > "$RTSP_CONF" )
  /mnt/sd/tc100test/thingino-rtsp-server -c "$RTSP_CONF" -d
  echo "[tc100-v3] RTSP stream active on port 554 (path /ch0)" > /dev/console
fi

# 8. Start ONVIF Discovery (monvifd)
if [ -x /mnt/sd/controlscripts/onvif ]; then
  /mnt/sd/controlscripts/onvif restart >/dev/null 2>&1
  echo "[tc100-v3] ONVIF service active on port 8081 & WS-Discovery UDP 3702" > /dev/console
fi

# 9. Start Auto Day/Night Detection
if [ -x /mnt/sd/controlscripts/auto-night-detection ]; then
  /mnt/sd/controlscripts/auto-night-detection start >/dev/null 2>&1
  echo "[tc100-v3] Auto Day/Night detection active" > /dev/console
fi

# 10. Start MQTT Bridge
if [ -x /mnt/sd/controlscripts/mqtt-bridge ]; then
  /mnt/sd/controlscripts/mqtt-bridge start >/dev/null 2>&1
  echo "[tc100-v3] MQTT bridge service launched" > /dev/console
fi

# 11. Start Motion Detection
if [ -x /mnt/sd/controlscripts/motion-detection ]; then
  /mnt/sd/controlscripts/motion-detection start >/dev/null 2>&1
  echo "[tc100-v3] Motion detection service active" > /dev/console
fi

# 12. Start Recording (if enabled)
if [ -x /mnt/sd/controlscripts/recording ]; then
  /mnt/sd/controlscripts/recording start >/dev/null 2>&1
  echo "[tc100-v3] Recording service launched" > /dev/console
fi

echo "[tc100-v3] All services initialized successfully." > /dev/console
