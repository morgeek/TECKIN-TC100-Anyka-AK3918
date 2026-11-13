# Known issues and platform notes

Moved out of the README in 2.0.0. History of every fix: [CHANGELOG.md](../CHANGELOG.md).

## 3.0 (Linux 6.6)

State as of 2026-11-13 (development head: `3.0.1-rc42` on `main`; last multi-hour baseline snapshot: 2026-11-09 on rc36 IPCAM2 / rc35 IPCAM1): two cameras of the same variant;
details and results are in [linux-port/test-queue.md](linux-port/test-queue.md):
- **Qualification status:** many core areas have passed real-camera checks on both devices, including flash boot,
  V3 services, the free encoder, and short RTSP decoding checks. After the latest installs, the report records
  12–15 hours without reboot, oops, or OOM. The planned seven-day soak was cancelled by the owner on 2026-11-09,
  so it has no pass result.
- **Free Video Encoder:** 100% free hardware encoder (`src/h265enc/freeenc.h`) built against `musl` with `libakuio`.
  No proprietary vendor `.so` libraries are loaded or stored in SPI flash. Supports H.265/H.264 at 1080p and 720p,
  and H.264 at 360p sub-stream.
- **Multi-client RTSP streaming:** Asynchronous sender thread (`RTSP_SENDER_THREAD=1`) is available as an opt-in to keep
  socket sends out of the capture/encode loop. It remains off by default pending a recorded pass of the four-client
  throughput and one-hour mixed TCP/UDP criteria; changing the default requires a separate follow-up.
- **Presence modes (#65):** implementation is complete but the camera check is still open (PRES-01). Home Assistant
  lists the fixed profile choices; save a profile in camera Settings before applying it. The displayed state is the
  selected profile and returns to Custom after a controlled setting is changed manually.
- **Colours:** slightly warm; the software white balance of the video server corrects them (on by default). The
  image processor's own white balance on its live statistics gave a blue cast and is not used
  (`ak_isp.awb_live=1` to try it).
- **Wi-Fi after a warm reboot:** the Wi-Fi chip sometimes failed to power on (no `wlan0`). 3.0.1 recovers it by
  itself (`scripts/wifi-recover.sh`: probe again, power cycle through GPIO 11, one clean restart if needed); a power
  cut remains the last resort. Background tasks in housekeeper are run with `nice -n 10` to avoid scheduling stalls on
  the Wi-Fi USB driver.
- **Intermittent Wi-Fi ping loss:** bursts have been recorded, including one 90% loss sample on IPCAM2 followed by clean
  samples. A two-hour diagnostic run did not show the USB interrupt or Wi-Fi receive counters freezing; the cause is
  still unresolved and may be on the access point / LAN / ICMP path. Normal association and transfers work.
- **Speaker and talk:** speaker playback works, but browser push-to-talk (UI-13) and end-to-end ONVIF/RTSP backchannel
  talk from go2rtc / Frigate / Home Assistant (P4) still need camera qualification. The audio-duck code mutes the
  microphone while the speaker plays (`RTSP_AUDIO_DUCK=1`).
- **Day / night:** anti-flapping minimum switch delay defaults to 180 s; optional dynamic 720p night mode (`NIGHT_720P=1`)
  can drop resolution at night for higher SNR and lower bitrate.
- **Storage:** in-camera FAT32 format action available in Settings (`scripts/sd-format.sh`) with 32 KB clusters for smooth
  long-term video recording without card exhaustion.
- **Memory:** about 23 MB available in the latest short field report with the 9600K encoder pool.
- **Logs with no SD card:** the web page (Logs) or ssh; the saved logs need a card.
- **Picture right after a boot:** once (rc20) the picture stayed almost white for several minutes after a reboot,
  then the exposure settled by itself. Not seen again since (owner, 2026-11-04): treated as an isolated case.
- **Wi-Fi country & Time zone:** the setup wizard prompts for both local time zone (POSIX TZ rule) and Wi-Fi regulatory
  country (`WIFI_COUNTRY`), unlocking channels 12-13 and proper regulatory transmit power automatically.
- **Frame rate in low light:** configurable via `LOWLIGHT_FPS_VALUE` (10, 15, or 20 fps) with proportional sensor exposure scaling.
- **MQTT and Telegram settings:** the MQTT user / password and the Telegram token / chat id cannot hold spaces,
  quotes or `$ ` \ ; & | < > ( )` (the files that hold them are read by shell scripts). Use other characters.
- **Web UI responsiveness:** immutable binary versions and short-lived device states are cached in RAM (`/tmp/`), avoiding
  slow repeated SquashFS decompression loops.

The 2.x-era notes (remote syslog 2.1.5, reading the camera logs 2.1.2, the 2026 bring-up fixes, the `tr(1)` platform constraint of the 2.x busybox) moved to [linux-port/history.md](linux-port/history.md#2x-known-issues-history).
