# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Changed
- **`main` holds 3.0 only.** The 2.x firmware moved to the branch `2.x`: its boot script, lighttpd and its
  configurations, the vendor RTSP server and `libtc100fix`, the 2.x flash install and update tools (`src/flash`,
  `src/release`, `flash-*.sh`, `fw-update.sh`...), the CPU scaler, the old PTT players, the OpenIPC 4.4 kit and their
  tests (about 150 files).
- **No proprietary file in the repository**: the RTL8188FU firmware is downloaded by the kernel build from
  linux-firmware (pinned tag and checksum); the encoder API library (`libmpi_venc`) and the sensor tuning file come
  from the camera at install, like the other vendor libraries.
- The 3.0 versions became the only ones: `controlscripts/rtsp-h26x`, `bin/setconf`, `www/cgi-bin/update.cgi` and
  `flashinstall.cgi`; the wizard, push-to-talk and the speaker test have no 2.x path left.
- `config/boot.conf.dist`: about 60 settings nothing reads any more removed (lite RTSP server, low-CPU overrides,
  CPU scaler, motion schedule, storage cleanup, print levels...); `WEB_MODE=http` by default.
- README rewritten for 3.0.

### Fixed
- The local-network filter (`libnetacl.so`, built for uClibc) was preloaded into musl programs too (telnet, rescue
  telnet): now only into programs of the uClibc runtime.
- The setup wizard's French text for the 3.0 steps (password, one-click install).
- Settings → System → "Run the wizard again" now also clears the 3.0 marker.
- The Services page and the RTSP control script agree on the pid file of `tc100_rtsp`.
- The self-test checks the picture of `tc100_rtsp` instead of the removed software streamer.

## [3.0.1-rc1] — 2026-10-26 (not yet run on a camera)

### Added
- **Built from git, installable by anyone**: CI makes `tc100-<version>-sd.zip` and `tc100-<version>-update.tar`
  with free files only. On first start the stock (or 2.x) firmware runs the card's hook: it checks the camera,
  saves the whole flash to the card, copies the camera's own vendor libraries, settings and Wi-Fi, and adds the
  3.0 start commands to U-Boot (stock start kept as fallback). Trial mode from the card, then **one-click install
  to flash** from the setup wizard or Settings; web updates write the flash; `restore-stock.sh` goes back.
  New flash partition `vendor` (1 MiB) for the camera's libraries. Details: `docs/linux-port/install-3.0.md`.
- **Web login** on 3.0 (busybox httpd, root + camera password); the 3.0 wizard sets the password.
- **RTSP sub-stream** 640x360 (`video1_unicast`, `ch1`, `sub`), **recording** inside tc100_rtsp to fragmented MP4
  with a JPEG thumbnail per file (no ffmpeg), sound level, motion zones and on/off.
- Every page on 3.0: speaker and push-to-talk through ALSA, Telegram and update check (curl), Wi-Fi rescue access
  point (hostapd), reset button polling, IR-cut pulse, auto day/night with luminance thresholds, ONVIF over HTTP,
  SD panel, a single RTSP restarter, settings deletions kept by `cfg-persist` and a "Settings not saved" badge.
  What the hardware cannot do is hidden on 3.0 with a note.

### Changed
- Wi-Fi changes from the web page and the wizard are written where the boot reads them and used at once.
- One flash writer (`flashw`, now with `-m MD5` and `-b DIR`); `flash-code.sh` refuses the 6.6 layout.
- LF line endings in every checkout (`.gitattributes`).

### Fixed
- Automatic day / night no longer stays stuck in NIGHT: its own switch used the manual-override path; it now keeps
  the automatic mode (`NIGHT_KEEP_AUTO=1`) and its loop starts no process (2026-10-25).
- Fewer processes in the background services (cached `timeout` probe, watchdogs and `cfg-persist` without forks);
  the MQTT bridge launcher no longer holds the console.

### Documentation
- `docs/linux-port/README.md` brought up to date with the flash install (status, memory map, flash layout,
  10-patch series, encoder progress, open items); README: what 3.0 really serves today (one RTSP stream, no
  sub-stream yet; H.264 / H.265 through the vendor encoder libraries on the free driver).

## [3.0.0] — 2026-10-24

The same firmware on Linux 6.6 instead of the vendor 3.4 kernel, running from the SPI flash with the SD card
optional. The 2.x firmware is unchanged and stays available. Details: [docs/linux-port](docs/linux-port/README.md).

### Added
- **Linux 6.6 port** of the AK3918EV300 as a 10-patch series on `v6.6` (`patches/kernel-6.6/series`), built by CI:
  machine, interrupts, timer, console, L2 buffer engine, SD card, USB host, Wi-Fi RTL8188FU (mainline `rtl8xxxu`),
  GPIO, I2C, watchdog, audio (`ak39_codec`, `ak_pcm`), V4L2 video for the JX-F23 (`ak39_vi` + the ISP core), encoder
  access (`ak39_venc`), SPI controller and NOR partitions (`spi-ak39`).
- **Hardware encoder on the free kernel**: `ak39_venc` + `libakuio` (free replacement of the vendor library) let the
  vendor encoder control libraries make H.264 and H.265; `src/jpegenc` makes JPEG on the hardware core with free code.
- **`tc100_rtsp`** (`src/tc100rtsp`): RTSP server for the main 1080p stream, H.265 (RFC 7798) or H.264 (RFC 6184),
  RTP over TCP or UDP, Digest/Basic login with the camera password, optional G.711 A-law audio, web UI pictures and
  the light level from the hardware JPEG engine, grey-world white balance, black and white, and, burned in before the
  encoder: image tuning (brightness, contrast, saturation, hue; `ISP_TUNE=1`), up to 4 privacy masks and the OSD clock.
- **Runs from flash**: kernel, xz initramfs and a 3.2 MiB xz squashfs user space (`v3/linux66-sd/build-slim-stack.sh`)
  in the SPI flash; settings in two alternating 36 KiB slots (`cfga` / `cfgb`, `cfg-persist`); guarded writer
  `flashw` (allow-list, read-back check). U-Boot, `boot` and `mac` are never written. An SD card with
  `tc100test/c66.img` boots first (development and the way back).
- `v3/`: 6.6 boot script, initramfs builder, autorun, self-test (`selftest66.sh`), glue for the 2.x web UI
  (`rtsp-h26x` and `setconf` shims, `rtsp-launch.sh`, `sdinfo-sd.sh`).
- Web UI on 6.6: flash layout and usage on the dashboard, MQTT with Home Assistant discovery (more entities, LED and
  telemetry from the 6.6 sysfs), day / night with thresholds, motion detection, `ntpd` clock, services ticked in the
  UI started at boot.
- Study tools: H.265 command list generator (`src/h265enc`, 40 recorded frames reproduced offline), `venctrace`,
  `venctest`, `AK39_VI_G_PHYS` ioctl (physical address of a capture buffer).
- OpenIPC SD boot kit (`contrib/openipc_sd_kit/`, Linux 4.4, historical) and a first Thingino board port
  (`thingino_port/`).

### Changed
- Core PLL at 480 MHz (ASIC 120 MHz, the stock 3.4 setting): at 640 MHz long H.265 runs crashed.
- Memory: encoder pool 12 MiB with 1 MiB guard zones, CMA 18 MiB from the command line, 3D-NR off (its reference
  frame does not fit), OOM watermarks lowered so small daemons are not killed with memory still free.

### Fixed
- Audio: the delayed capture start is cancelled on stop / close (NULL pointer oops when a stream ended within 300 ms).
- Flash mode without a card: the ISP tuning file is shipped in the squashfs (no video otherwise).
- MQTT discovery refresh; health payload retained.

### Not available on 3.0 yet
- RTSP sub-stream, sharpness and the other ISP-daemon settings, resolution / frame rate settings (fixed 1080p,
  15 fps), speaker and two-way audio (not tested on 6.6), one-click flash installer.

---

## [2.1.9] — 2026-10-18

A lighter RTSP server, sound both ways, motion zones.

### Added
- **Lite RTSP server** (`src/tc100fix/rtsp.c`, inside the video process). It sends the frames the SoC encoders already produce, without decoding or re-encoding them, and does not change the vendor server.
  - **Settings → Video → RTSP server**:
    - *Original* (live555) or *Lite* on the RTSP port (`RTSP_SERVER=lite`). The addresses (`/video0`, `/video0_unicast`, `/video1`…) and the password stay the same, so recorders see no difference.
    - The vendor server keeps running for the encoders, on `RTSP_VENDOR_PORT` (8555), with no client.
    - If the lite server has not opened the port 30 s after a start, the vendor server takes it back until the next reboot.
  - **What it sends**:
    - H.265/H.264 video and the G.711 sound (trackID=1), with both timestamps on the same clock.
    - RTP over the RTSP TCP connection (UDP is refused, and clients fall back to TCP).
    - RTCP sender reports.
    - HTTP Digest authentication: the main account, plus `RTSP_LITE_USER`/`RTSP_LITE_PASS` as a second account.
  - **Fast start**: the frames since the last keyframe are kept (`RTSP_LITE_FASTSTART=1`). A new client gets a picture in about 1 s instead of waiting for the next keyframe.
  - **Slow clients**: a client that cannot keep up skips to the next keyframe. The others are not slowed down.
  - **Measured on a TC100** with Frigate as the only client:
    - the vendor server's RTSP thread went from 15.4 % to 1.8 % CPU, and the lite server uses 6–7 %;
    - 0 decode errors, 16 fps, 25 audio frames per second.
- **Two-way audio** (`RTSP_LITE_TALK=1`, lite server). A client that asks for the ONVIF backchannel gets a send-only audio track; go2rtc does this, so it works from the microphone button of Home Assistant and go2rtc.
  - The G.711 it sends is played on the speaker through `libplat_ao`, opened only while someone talks.
  - The volume is the push-to-talk volume, one talker at a time.
- **Motion zones** (Settings → Detection): up to 4 areas that the camera's own motion detection ignores (MQTT event, picture on motion).
  - The cells of the SoC detector grid (32×24) inside a zone get sensitivity 1, which the library treats as "never" (`src/tc100fix/md.c`).
  - The zones are applied when the detector starts or restarts. Frigate keeps its own zones.
- **Secondary stream on/off** in the same card (`RTSP_SUBSTREAM`).
- Home Assistant diagnostics:
  - *RTSP Clients* and *RTSP Skipped Frames* of the lite server;
  - *Last Restart Cause* (requested / unexpected);
  - *Unexpected Restarts (history)*;
  - an *Unexpected Restart* problem sensor, which turns on after a restart nobody asked for (hardware watchdog, power loss, crash). An automation can notify on it.
- **Snapshots without a helper program.** The video server already encodes one JPEG a second. libtc100fix now keeps the last one in `/tmp/snapshot.jpg`, and `currentpic.cgi` serves it directly while it is under 3 s old. The web page and Home Assistant get the picture at once, without starting `getimage` for each request. `getimage` remains the fallback.

### Changed
- **Clean microphone without sound detection.**
  - The vendor echo canceller and noise gate are now off whenever the sound is served, not only with sound detection. They cost about 4 % CPU and silenced everything below speech level.
  - `RTSP_AEC=1` keeps them.
- **Health snapshot every 5 minutes** instead of every minute (`HEALTH_SNAPSHOT_INTERVAL_SECONDS=300`). Each run probes about 15 services. The Diagnostics page and `health.cgi` follow the new cadence.
- **Less memory.** The reset button is watched by `tc100-button`, a small C program in the code zone (`src/button`). It is one blocked process instead of a shell loop with a `dd | od` pipeline, which held four processes and about 230 KB. The rules are the same, and `scripts/button-watch.sh` stays as the fallback.
- **Faster web requests.** `action.cgi` keeps its checks and helpers, and its 89 commands moved to `scripts/action.d/<group>.sh` (video, stream, audio, storage, detection, hardware, system, network, integrations, setup, logs). A request reads only its group's file: the shell parsed the whole 115 KB file on each request, about 0.3 s on the camera. The commands themselves are unchanged.
- **The camera's own motion detection is off by default** (`mdenabled=0` in `rtspserver.conf.dist`): Frigate does the detection. It saves the detector's work in the video process. Turn it on in Services when its MQTT events or pictures on motion are used. Cameras already set up keep their setting.
- `NR3D_STRENGTH` (test, `isp_tune.conf`): scales the 3D noise-reduction strengths, mapped on the camera's 112-byte sets. Not in the web page yet.

### Security
- **Local network only by default** (`NET_LAN_ONLY=1`). Connections from outside the private networks (10/8, 172.16/12, 192.168/16, link-local, 100.64/10 for Tailscale) are closed at once by the web server, telnet, FTP and both RTSP servers. A port forwarded by the router by mistake no longer reaches the password prompt.
  - The kernel has no packet filter, so the check is a small library on `accept()` (`src/netacl`): `lib/libnetacl.so` for lighttpd, telnetd and ftpd, and the same code is built into `libtc100fix` for the video process.
  - `NET_ALLOW_EXTRA` adds networks (a VPN).
  - An empty or unreadable list, or a missing library, means no filter. If lighttpd does not come up with the filter, it is started again without it.
- **RTSP**: the original server behind the lite one listens on 127.0.0.1 only (`RTSP_VENDOR_LOCAL=1`). The lite server refuses an address outside the local network for 15 min after 5 wrong passwords. The local network is never refused.
- **Telnet and FTP** started from the web page stop by themselves after 15 min (`REMOTE_SHELL_TIMEOUT_MIN`). FTP is no longer started at boot by default.
- **Emergency telnet (port 9527)**: only when the web interface is not up 2 min after a boot (`EMERGENCY_TELNET=auto`), instead of 60 s at every boot.

### Removed
- Features unused with Frigate, or that need internet, while the camera stays offline:
  - the old recorder (`controlscripts/recording`, `bin/ffmpeg-min-recorder`), replaced by the local backup recording;
  - timelapse;
  - motion mail and motion snapshots (`sendPictureMail.sh`, `motion-mail`, `motion-snapshot`);
  - ONVIF event push (`onvif-notify.sh`). The ONVIF service itself stays;
  - `audio_stream.cgi`, which did not work. The lite RTSP server carries the sound.

  Telegram stays in the code, off and hidden in flash mode.

### Fixed
- **SD card format interrupted by a restart.** A code update rebooted a camera while it was formatting its card: the new partition table was written, but there was no file system, and the card then only showed as "no readable file system".
  - Code updates are now refused while a format runs.
  - A format that did not finish is remembered (`/mnt/config/sd-format.pending`). The card is then shown as *formatting did not finish* and the question is asked again.
- The frame tap of the local recording and of the lite server could take the JPEG snapshot encoder for the main stream. Both encoders have the same size, and one JPEG a second ended up as broken video. Only frames with an H.264/H.265 start code are used now.

---

## [2.1.8] — 2026-10-18

### Added
- **SD card from flash** (`scripts/sd-card.sh`, checked every minute by `web-guard.sh`):
  - a card put in is recognised: firmware/install kit (boot files: never mounted, since the vendor boot would start from it), card with files, empty card, card without a readable file system, or card with errors;
  - a usable card (FAT32/exFAT, no boot files, no card errors in the kernel log) is mounted on `/mnt/sd` automatically (`SD_AUTOMOUNT=1`), ready for the local backup recording; a card taken out is released;
  - the web page asks once per card: **"SD card inserted: what do you want to do?"** — set up recording, format the card, or leave it as it is (the answer is kept per card in the persistent config);
  - **formatting from the camera**, only when it runs from flash (never the card it boots from): recording paused and card released, one FAT32 partition from 4 MB (erase-block aligned), label TC100, then mounted again. Refused for a card that reports errors. Runs in the background; the page follows it.
  - Settings → Recording shows the card and its state, with "Mount the card" and "Format or set up…".

---

## [2.1.7] — 2026-10-18

Flash space.

### Changed
- **Code zone 487 KB → about 405 KB of its 640 KB.** Packages and system images are now built from a shrunk copy of the code (`src/flash/minify.sh`, called by `stage-tc100.sh`): comments and indentation removed from the shell scripts and CGIs by `shfmt -mn` (a real shell parser, so here-documents and strings are untouched), web scripts and stylesheets minified by `esbuild` (checked with `node --check`). The repository stays the readable source; without the tools nothing changes; `MINIFY=0` turns it off.
- Shell scripts are only minified when the camera's own shell is available to check them (`CAMERA_SH`, the vendor busybox 1.24.1 ash run with qemu), and a file it refuses keeps its source. A first build checked with a newer busybox booted a test camera without network: the old ash misparsed the minified `autorun.sh` where its 8 KB read buffer ended inside `;then`. The camera rolled back to its built-in code by itself (no confirmation within 5 min), as designed. A test now parses every script with the vendor ash when `TC100_ROOTFS` points to an extracted rootfs.
- Removed from the camera: the icon font's `.eot`, `.ttf` and `.svg` copies (only the WOFF is used by current browsers) and the host-side Python helper that was copied with the scripts.

---

## [2.1.6] — 2026-10-18

Hardware features that cost no CPU.

### Added
- **Privacy masks** (Settings → Image): drag up to 4 rectangles on the camera picture. The ISP paints them (black, grey or white) before encoding, so they are gone from both streams, the snapshots, the recordings and what Frigate analyses, at no CPU cost (`ak_vpss_mask_set_area`, struct checked against the camera's library). Stored as `MASK1..MASK4=x1,y1,x2,y2` in percent in `isp_tune.conf`, set again if a day/night ISP reload drops them. Saving a mask switches live tuning on. Checked on a camera: the masked area is exactly where it was drawn on the 1080p snapshot. (The SDK's "mosaic" type left the area black, so it is not offered.)
- **Wi-Fi rescue access point from flash.** The flash `/usr` has no vendor `hostapd`, so the rescue access point (`WIFI_RESCUE`) could not start there. The code package now carries `hostapd-rtw`, built from Realtek's hostapd 0.8.x_rtw source for the RTL8188FU's `rtl871xdrv` interface (`src/hostapd`, WPA2-PSK only, no WPS/EAP/RADIUS, 190 KB). Checked on a camera: access point up in Master mode on `wlan1` while the station link kept working, then stopped.

### Fixed
- The rescue access point's DHCP server kept running after the access point stopped (busybox `udhcpd` did not write its pidfile): it now runs in the foreground of a background job whose PID is recorded.
- The image-tuning status of the web page and MQTT is removed when tuning is switched off, instead of showing the last values.

### Notes
- WDR (wide dynamic range) is already on: the sensor's ISP file runs it in gain-linked mode for 8 of its 9 gain levels (read on a camera; the status file now reports `WDR_MODE/WDR_MANUAL/WDR_LINK`). Nothing to switch on.
- Wi-Fi transmit power cannot be lowered at run time with this driver build (`tx_power_offset` and `tx_gain_offset` are accepted but change nothing measurable); a camera too close to its access point is better moved by a couple of metres.

---

## [2.1.5] — 2026-10-18

Reliability.

### Added
- **Network guard** (`scripts/net-guard.sh`, checked every minute by `web-guard.sh`): when the default gateway has not answered for `NET_GUARD_MIN` minutes (15) while the rest of the system runs, the camera reboots. The hardware watchdog does not catch that case (its feeder keeps running): a test camera stayed off the network for over 20 minutes until it was unplugged. If the reboot itself hangs, the watchdog feeder is stopped after 2 min so the hardware resets the camera. After such a reboot the next limit doubles (15 → 30 → 60 → 120 min) until the network has been back for 10 min, so a router switched off for the night costs a few reboots. Never while the Wi-Fi rescue access point is up. `NET_GUARD=0` turns it off.
- **Build identity in code packages**: the header now carries the build date and the git commit (`flash-code.sh info`). Settings → Firmware update shows them for the installed code and for an uploaded package, and warns when a package has the same version as the installed code but another build (an older file with the same name was nearly installed). Older packages and the `/usr` copy of `flash-code.sh` still read the new header.

### Fixed
- **Remote syslog got everything.** BusyBox `syslogd -R` sends every message to the remote host before its own filters (they only apply to the local file), so the remote server also received kernel and daemon info/debug lines, and bursts line by line. A small forwarder (`tc100-logfwd`, 10 KB, `src/logfwd`) now follows the filtered local log instead: notice and above plus logins; the same message (numbers ignored) at most once a minute with a "repeated N times" line after; at most 60 lines a minute. It ships in the code package; without it (older system image) the camera falls back to `syslogd -R`.

---

## [2.1.4] — 2026-10-18

### Fixed
- **Day/night flapping at dawn and dusk.** The infrared lights feed back into the light measure (IR on: bright enough for day; IR off: dark enough for night), so a camera switched 4 times in 50 s at dawn. Each switch drops frames (`ak_vi_get_frame … get frame failed`, kernel `>50, sjf`, `set td ok`), changes the whole picture (seen as motion by Frigate) and sent a burst of error lines to the remote syslog. The automatic switch now waits until the ISP has asked for the new mode for `RTSP_DAYNIGHT_HOLD_S` (10 s) and happens at most every `RTSP_DAYNIGHT_DWELL_S` (120 s); 0 = vendor behaviour. Simulated: 3 minutes of flapping → 3 switches instead of ~12; a 3-second flash at night no longer switches.

### Changed
- A code package can now update the RTSP server fixes (`libtc100fix.so` in the code zone, preferred by `rtsp-h26x` over the copy in `/usr`): no system package needed for them.

---

## [2.1.3] — 2026-10-17

### Changed
- **Vendor libraries log errors only** (`VENDOR_PRINT_LEVEL` now defaults to 1 instead of the vendor's 3). At 3 the encoder library writes every slow frame (`>>> encode frame type=0 … time=…ms`, `group_type=…`) at *emergency* priority: with remote syslog on, a NAS received bursts of "emergency" events and sent an alert for each. Checked on a camera: after a stream start only the vendor's error lines remain. Set 3 in boot.conf to get the vendor behaviour back.

---

## [2.1.2] — 2026-10-16

What the logs of two cameras showed over a day (details: docs/known-issues.md, "Reading the camera logs").

### Fixed
- **Time zone**: `timezone.conf` was read whole, comments included (a camera on the template got that as its `TZ`), and only the RTSP server used it, so kernel and vendor lines in one log were hours apart and cron ran on UTC. The first non-comment line is used, checked, and exported to every program from the start of `autorun.sh`; klogd is restarted with it so kernel lines carry the same clock. The template now shows POSIX strings (`CET-1CEST,M3.5.0,M10.5.0/3` for Paris; `UTC+1` meant one hour *behind* UTC).
- False boot warnings from flash: "/mnt has less than 4 MB free", "Self-heal skipped: missing libcurl", "lighttpd.conf rejected by lighttpd".

### Changed
- **Logs page**: syslog lines are classed by the priority they carry, and the vendor drivers' start-up chatter (sensor register dump at "err", encoder start at "emerg", Wi-Fi driver banner, cloud command server not found…) shows as "Vendor" instead of errors: 31–37 "errors" per boot → 0 on a healthy camera, while SD card timeouts and other real faults stay errors.
- **Reboot history**: each heartbeat records the SD card state; an unexpected restart after card errors says "SD card errors (N kernel errors): likely cause". Heartbeat every 5 minutes from flash (15 on an SD card).
- Settings → Network: the time zone field explains the POSIX format.

---

## [2.1.1] — 2026-10-16

### Changed
- **Lighter web requests.** `state.cgi?cmd=statusline` (polled by every open page) runs without subshells on its usual path: about half the time per request on the camera (0.94 → 0.50 s). `func.cgi`, sourced by every CGI, no longer runs `timeout` at each request (the probe is kept in `/tmp` once per boot) and only url-decodes values that need it.
- **HTTPS from flash prefers ChaCha20-Poly1305** (the AK3918 has no AES instructions): serving a page costs about 55 % less CPU and is about twice as fast. Clients that only offer AES-GCM still get it. The certificate was already ECDSA P-256.
- Diagnostics, Logs, Services, Config editor and Recordings get the same page title as the rest; the log tabs are one segmented control; the recordings player follows the dark theme.
- Settings: the page title shows the open section; the search also finds the Wi-Fi and backup cards (loaded on the first search).
- A web code or system update now records its restart as planned in the reboot history, instead of "UNEXPECTED".

---

## [2.1.0] — 2026-10-16

### Changed
- **New web interface layout, after the OpenIPC web interface.** Top bar with the camera name and firmware version, and Dashboard, Live, Recordings, Camera ▾, Services ▾, System ▾. Dark theme by default (light still one click away), one indigo accent.
- **Settings**: a sidebar grouped by use (Image, Video & audio, Events, Network & integrations, System) with a search box that shows every matching card across sections. On a phone it becomes a row of chips. Each section also opens straight from the menus.
- Dashboard and Live switch instantly: the home page is kept aside while other pages are open, not downloaded again.

### Added
- **Dashboard**: CPU, memory, Wi-Fi signal, network out and uptime tiles with small graphs; network in/out and CPU/memory graphs over the last 5 minutes; snapshot, streams, device and storage cards. The graphs are kept in the browser only, and are fed by `dash.cgi` (raw counters from `/proc`, a separate tiny CGI, shell built-ins only, every 5 s while the dashboard is on screen) and `cmd=dashinfo` (once a minute).

---

## [2.0.1] — 2026-10-16

### Added
- **System update from the web page, without SD card or telnet** (flash mode): Settings → Update & backup accepts `tc100-system-<version>.tar` (made by `src/flash/build-flash-kit.sh` next to the install kit). It is unpacked in RAM (the video is paused), checked (same original `/usr`, image md5, squashfs with the files a boot needs, valid code package), then `scripts/usr-update.sh` runs from RAM with the rootfs shell only: it replaces the watchdog feeder, stops every program running from `/usr` (Wi-Fi included), writes `/usr` and reads it back (up to 5 times), writes the code zone, sets up a one-shot boot from flash when an SD card with the firmware hook is in the slot, and reboots. Nothing is written if a program cannot be stopped.
- **SD card health** (`scripts/sd-health.sh`): kernel card/file-system errors, read-only remount, and a write/read-back test after each boot and daily. Shown under the live view ("failing: replace it", "read-only", "errors"), in Home Assistant ("SD Card Problem" now also covers garbled writes, new "SD Card State"), and logged as an event.
- **Rescue access** (`scripts/web-guard.sh`, SD card and flash): when no web port answers, the web server is restarted once, then a rescue telnet opens on port 23; it is closed again once the web interface has been back for two minutes (a telnet started from Services is left alone). An HTTPS → HTTP fallback is shown as an "HTTP" badge in the top bar.

### Changed
- The update work directory on the card is `tc100-update/` instead of `update/`, a name the vendor `service.sh` reserves for reflashing the camera from the card (`update_check.sh`, when `wifitest/` is absent). An existing `update/` holding only our state files is moved at boot.
- The install to flash records the fingerprint of the original `/usr` in the settings partition, so system packages can be matched to it.

---

## [2.0.0] — 2026-10-16

The firmware runs from the camera's flash memory: the SD card becomes optional.

### Added
- **Install to flash from the SD card** (README "Step 3"), in three steps through a `tc100-flash/` folder on the card: the camera copies its original `/usr` to the card (`scripts/flash-install.sh prepare`, read-only for the flash); a computer turns it into `usr.img` + `code.bin` (`src/flash/build-flash-kit.sh`, Linux / macOS / WSL, prebuilt stripped binaries in `src/flash/prebuilt/` so no cross toolchain is needed); the camera installs both at boot before any video service runs, copies the settings, Wi-Fi and an ECDSA certificate into jffs2, reads everything back and does one test boot from flash with the card still in. Every check (partition table, kernel size, empty code area, fingerprint of the original `/usr`, image md5, no process using `/usr`, room in jffs2) refuses without writing anything and reports in `tc100-flash/STATUS.txt`. Also from Settings → Update & backup → *Install to flash* and from the wizard.
- **Setup wizard** rewritten: language and Wi-Fi (kept network as fallback), profile, web access, Frigate and MQTT with Frigate's address, recording on the card, install to flash; all answers validated before anything is written; `wizard.cgi?info`.
- Settings → System → **Password**: one password for web, RTSP, FTP and telnet; characters the writers cannot carry are refused.
- **ONVIF back in the flash image** (`monvifd`, about 94 KB; 312 KB still free in `/usr`). Off by default, started from Tools → Services; the install to flash keeps it on when it was on the SD card. Its health check tries plain HTTP first (the flash curl has no TLS).
- Local recording on **exFAT** cards from flash (`rec-storage.sh`).
- Release: CI also attaches the SD card zip (`tc100-sd-<version>.zip`). Screenshot tool `src/webui/screenshots/shots.py` (canned answers, test pattern) and `docs/screenshots/`.
- README rewritten for 2.0 (possibilities, step-by-step guides, hardware, OpenIPC references); platform notes and the bring-up bug table moved to `docs/known-issues.md`.

### Changed
- Settings → Network Wi-Fi goes through `wifi-txt.sh` like `wifi.txt`: the new network first, the previous ones kept as fallbacks (a wrong password no longer takes the camera off the network).
- `flash-usr.sh` and `flashmode-once.sh` moved from `src/flash/` to `scripts/` (they run on the camera and ship with it).
- `src/flash/stage-tc100.sh`, `build-usr.sh` and `build-code.sh` work on a user's computer (no git checkout or root needed, macOS `md5`).

### Fixed
- Form drafts kept in the browser (`localStorage`, up to 60 min) included password fields (Wi-Fi, Telegram token). Password fields are no longer stored.
- Example addresses and camera names from the test setup were replaced by neutral ones in the documentation and UI placeholders.

---

## [1.8.4] — 2026-10-12

### Added
- `wifi.txt` at the root of the SD card (`SSID=` / `PASSWORD=`): Wi-Fi settings applied at boot by `scripts/wifi-txt.sh` (flashboot.sh from flash — kept in jffs2 —, autorun.sh from the card), password removed from the card afterwards, previous networks (or the vendor `anyka_cfg.ini` network) kept as lower-priority fallbacks. Settings → Wi-Fi from flash now writes `/etc/jffs2/tc100/wpa_supplicant.conf` (it wrote to RAM and was lost at reboot).
- Rescue access point (`scripts/wifi-rescue.sh`) on hold: the vendor hostapd authenticates phones but no data reaches them on this driver, even with the station stopped.
- Local backup recording (`REC_LOCAL=1`, `REC_SEGMENT_SEC`, `REC_RESERVE_MB`, `REC_STREAM`): `src/tc100fix/rec.c` hooks `ak_venc_open` / `ak_venc_request_stream` / `ak_venc_get_stream_ex` in the vendor RTSP server, queues each encoded frame (never blocking the encoder thread: frames are dropped and recording resumes at the next keyframe when the card is too slow) and a low-priority thread writes fragmented MP4 (H.264 `avc1` / H.265 `hvc1`, one fragment a second, new file at the first keyframe after `REC_SEGMENT_SEC` or when the parameter sets change). Refuses RAM and flash filesystems. `scripts/rec-storage.sh` (dir / eject / resume / status). Verified on camera 2: 1080p H.265 and 640×360 H.264 files decode cleanly with ffmpeg, 0 dropped frames; CPU cost measured per thread (writer, mmcqd, writeback): ~4.5 % main stream, ~0.8 % sub-stream.
- Local recording only while the recorder is away (`REC_WHEN=offline`, default): the writer checks `/proc/net/tcp` every 2 s for an established RTSP connection from the recorder (`REC_CLIENT`, by default the host of the Frigate URL) whose data flows (send queue < 256 KB, no retransmission timeout — a client lost on the network stays "established" for minutes); in standby nothing is processed or written: the frame queue (1 MB, ~5 s) is trimmed by whole GOPs and becomes the pre-roll; recording starts `REC_OFFLINE_SEC` (5) after the stream stops flowing and ends `REC_POSTROLL_SEC` after it is back.
- Flash `/usr` replacement, written from Linux without opening the camera (README "Install to flash"): `src/flash/build-usr.sh` (vendor `/usr` minus the cloud app, SD card keeps priority in `service.sh`, `/usr/tc100` HTTP-only binaries, size check) and `scripts/flash-usr.sh` (partition check, write, read-back through `/dev/mtd6`). HTTP-only builds: `src/curl/build.sh` (HTTP/MQTT/RTSP) and `NO_TLS=1 src/lighttpd/build.sh`. camera 2 runs from it since 2026-10-15.
- `src/release/build-sd.sh` builds the content of a new SD card (`dist/tc100-sd-<version>/`, and a zip), with `SD-CARD.txt` (formatting, bringing the settings over) and checks that no reflash file name or live configuration ends up on it. The boot hook `wifitest/wifi_test.sh` (the vendor `service.sh` sees `/mnt/wifitest`, skips the cloud app and runs it; it starts `autorun.sh`) was only on the cameras' cards and is now in the repository: a card made from git alone did not boot the firmware.

### Fixed
- The camera contacted GitHub (`api.github.com`) at every boot to check for a new release, although it is meant to stay off the internet. The check now only runs with `UPDATE_CHECK=1` in boot.conf (default 0); updates are installed from Settings → Firmware update.
- Settings → Firmware update showed nothing on a camera whose update log held control characters (file names made of random bytes from the 2026-10-13 FAT incident): `update.cgi?cmd=status` returned invalid JSON. They are replaced in the log excerpt.
- **Settings: sound detection showed "off" (interval 5 s) on frigate_ha cameras where it was on.** state.cgi fullconfig did not read sound_detection.conf in that profile, even though detection runs in every profile since 1.8.4.
- **Settings: the Telegram card was squeezed into one row.** The show/hide password button set `display:flex` on the field's parent. The field now gets its own wrapper, and the 👁/🙈 emojis became "Show"/"Hide".
- Sound detection never worked on this camera: it read `/dev/voice` / `/dev/dsp`, which do not exist on the AK3918 (the microphone is `/dev/akpcm_cdev0` behind the vendor `ak_ai` library), treated 16-bit PCM as 8-bit, and without a device fell back to a "shim mode" that reported a level above the threshold — enabling it would have published a fake "sound" event every poll. Replaced by a level meter in `libtc100fix.so` (`TC100FIX_SOUND_LEVEL`): it sees the raw PCM the vendor audio encoder reads (`ak_ai_get_frame`), computes RMS/peak in dBFS once a second and counts the seconds at or above `THRESHOLD_DB` (new key, default -30 dBFS; `THRESHOLD` is legacy), so the daemon polls a tmpfs file every `INTERVAL` s (default 2, the forced 10 s minimum is gone) and misses nothing. rtsp-h26x serves audio while sound detection is enabled (v4l2rtspserver only opens the audio encoder for served audio, so the meter needs it even if `RTSP_AUDIO=0`) and turns off the vendor echo canceller and noise reduction for it (`TC100FIX_AEC_OFF`): measured on hardware, with them on the microphone delivered digital silence (stream flat at the A-law floor, -72 dBFS, on both cameras) because the noise gate removes everything below speech; with them off the ADC carries a DC offset of ~-1450/32768 (-27 dBFS on its own), removed in place before the encoder by a one-pole DC blocker (`TC100FIX_DC_BLOCK`) — stream DC offset -0.045 → -0.003, ambient room level -43 dBFS measured identically by the meter and by ffmpeg on the RTSP audio. The meter also measures around the window mean. Switching sound detection restarts RTSP. The daemon no longer is skipped under `frigate_ha` (it is cheap now) but only starts when enabled. Events carry `level_db` / `threshold_db`.
- Settings → Motion & Sound: the save handler read `motionBlink`, a field the form never sent (the LED switch was ignored), and dropped the sound threshold. It now reads the form's fields (sanitised), and the card has a sound detection switch and a threshold in dBFS.
- FTP / Telnet showed "running" with their port closed and refused to start ("already running"): `status` trusted any live PID from the pidfile, and `ftp-server` wrote every PID matching `ftpd` (session children included). `status` now also requires the right process and a listening port (`port_listening`, from `/proc/net/tcp`) and removes a stale pidfile; `ftp-server` records `$!` (tcpsvd itself). The Services page fast path checks the port too. Verified on hardware: after `kill -9` of tcpsvd the service reads "stopped" and starts again.
- Frigate/go2rtc lost the camera 30–50 times an hour ("dial tcp …:554: i/o timeout", mostly on the sub-stream) while ping and already-open streams kept working. `00_system-config` enabled `tcp_tw_recycle`, which makes the kernel silently drop a SYN whose TCP timestamp is older than the last one seen from the same IP — the normal case for clients behind NAT or with per-connection timestamp offsets (go2rtc in Docker). Measured on hardware: `PAWSPassive` grew by ~22 per minute; after setting `tcp_tw_recycle=0` it stopped growing and go2rtc logged no error for the camera. The boot script now sets `tcp_tw_recycle=0` and `tcp_tw_reuse=1` (quick restarts still work: it only affects outgoing connections); a test forbids turning recycle back on.
- Logs page showed `{"ok":false,"error":"CSRF token missing or invalid…"}` instead of the logs: `logs.html` posted to `action.cgi` without the CSRF header, which every POST requires. It now sends the token.
- Settings → Config Profiles: "Failed to refresh preset list" on every visit and presets that could not be loaded — the page asked `list_presets` / `load_preset` without `format=json` and got plain text. Verified on hardware: save → list → load → delete round trip.
- Network page: "Primary IP" and "Default gateway" were `n/a`. The firmware's `timeout` shim (`busybox timeout`) could not find bare command names ("can't execute 'ifconfig'"), so `ifconfig`/`route` never ran; the shim now resolves the path first (`func.cgi`, `common_functions.sh`). Routes are read with `route -n` (the gateway had shown as "lan.home"), `ip route` "default via" is parsed, and ONVIF/FTP/Telnet ports are "expected" only when the service starts at boot.
- Logout did nothing (`action.cgi` has no `logout` command; HTTP Basic auth cannot be ended server-side). The button now replaces the browser's cached credentials and reloads to the login prompt.
- Device Info: binary versions showed printf placeholders (`curl 8.1.2 (…) %s`, `%s version 2.1.3`); "Release" showed only the vendor flash version — the SD firmware version is now listed first.
- Disk page: the summary showed "Root usage: 100 %" — the read-only squashfs root, full by design. It now shows SD card usage.
- System Usage → Service Health listed the boot hooks `00_system-config`, `01_system-emergency-telnet`, `02_system-webserver` as permanently "absent".
- Services: memory-guard and cpu-scaler (started at boot, off until enabled in `boot.conf`) now report "Disabled" (status exit code 3) instead of needing attention; Settings can still enable them without touching autostart.
- Dark theme: the logs table header was a blank light bar (light text on a light background); other light-only panels got dark counterparts.
- Services → View opened a new browser tab with an unescaped `<pre>` (a script containing `<` rendered as markup). It now opens the source in a dialog (Copy, Esc / click outside to close; Ctrl/⌘-click still opens a tab), served as plain text by `scripts.cgi?cmd=source`; the full-page view escapes the source.
- Services page: every row stayed on "Loading…" with "Service status is unavailable". The page polls `scripts.cgi?cmd=allstates` without a script name, but `allstates` was only handled inside the per-script branch, so the request got the HTML listing and the JSON parse failed. It is now answered first. A status exit code of 1 now means "stopped" instead of "error" (onvif, timelapse, sound-detection return 1 when not running); `web-server` finds lighttpd by process (its config writes no pidfile, so a running server showed as failed); `telegram-bot` and `network-monitor` no longer print their "configure first" message on `status` (read as "running"); `syslog-forward status` returns 1 when stopped. The summary counts only real problems (failures and services set to start at boot that are not running). Dark theme: the services table had a light background behind light text. Verified on hardware: 8 running · 17 stopped · 2 need attention (memory-guard and cpu-scaler start at boot but are disabled in `boot.conf`).
- Settings → Dashboard: the Wi-Fi gauge was never filled — the page read `wifi_qual` but `statusline` did not send it. `statusline` now reports `wifi_qual` (link quality 0–100 from `/proc/net/wireless`, shell only) and `wifi_iface`. The "Gateway" field showed `0.0.0.0` from a config key nothing writes; it now shows the live default route. Verified on hardware: Wi-Fi 85–93 %, gateway 192.168.1.1.
- The web server could not start from a fresh install: `lighttpd.conf.dist` loaded `mod_setenv`, which the bundled lighttpd 1.4.69 (static build) does not include ("mod_setenv plugin not found", lighttpd exits). Its `mod_deflate` is missing as well (keys silently ignored), so the gzip and cache/security-header blocks never worked. They were removed from the templates; the rebuilt binary (see *Changed*) brings them back through a migrated block, and a test pins every module the templates load to `src/lighttpd/plugin-static.h`.
- Restarting the web server (web UI service toggle, `memory-guard`, Let's Encrypt renewal) left the camera without a web UI until the next reboot: `http_server` started lighttpd without `LD_LIBRARY_PATH`, and it exits at once ("can't load library 'libpcre2-8.so.0'"). It now starts it like `02_system-webserver`, and honours `WEB_MODE=http`. Verified on hardware.
- Sensor frame rate no longer drops from 25 to ~10 fps in low light (and back), which made the RTSP frame rate oscillate under Frigate. The vendor `libplat_vi.so` (V1.0.04) arms an automatic switch thread from `ak_vi_set_channel_attr()`; `v4l2rtspserver` never disabled it. `RTSP_FPS_LOCK=1` now disables it at run time (see `libtc100fix.so` below). Night test on hardware (IR on, 2026-10-13): the switch is disabled (`rc=0`, sensor kept at 25), but the main stream (configured 12 fps) delivers 10.1 fps in night mode with the lock on *and* off, and with the AE exposure cap at 50 % and 15 %; frame intervals are 93–106 ms rather than multiples of the 40 ms sensor period, so night mode is limited by something else in the capture/ISP path. The default stays `RTSP_FPS_LOCK=0`.
- Restarting the RTSP service could leave it down: with the previous server's client sockets still closing on port 554, the new server exited at once with a misleading "Address family not supported by protocol" and stayed down until the watchdog's next pass (~1 min). `rtsp-h26x` now waits for the port to drain (max 45 s) and retries up to 3 times if the server dies right after start. Reproduced and verified on hardware.
- With `RTSP_AUDIO=0` the server still opened the microphone and ran the echo canceller and noise reduction (`aec_task` + `ai_capture` ≈ 6.4 % CPU measured over 30 s). `RTSP_MIC_OFF_WHEN_NO_AUDIO=1` skips them; both threads disappear on hardware.
- Starting a service from the web UI no longer hangs: `scripts.cgi` captured the start output through `$(...)`, and services that background a daemon (`ftp-server`'s `tcpsvd`, the service watchdogs) inherited that pipe, so the request never completed although the service had started. Output now goes through a temp file with stdin from `/dev/null`. Verified on hardware (start returns in ~1.6 s).

### Changed
- **Settings regrouped into six tabs**: Image & video (streams, day/night, on-screen text, image tuning), Sound & detection (microphone, motion/sound detection, timelapse), Integrations (MQTT/HA and its status, Frigate live view, RTSP addresses, Telegram, syslog), Network (Wi-Fi, IP/DHCP, DNS, Wi-Fi scan, name, time), System (performance and security, LEDs, maintenance, setup wizard, firmware update) and Backup (restore point, presets, export/import, full backup and JSON exchange, with a short guide to which one to use). The Settings "Dashboard" tab, a duplicate of the main screen, is gone; its warnings stay above the tabs. **Tools** now holds one **Diagnostics** page (system usage, device, storage, network state, each loaded when its tab is opened), Logs and, under Advanced, the config editor; Network & DNS and Backup & Restore moved into Settings. `network.cgi?part=settings|diag` serves either half (the settings half skips the netstat/route probes). The "Retry" button of a page that failed to load called an undefined function; fixed. The Wi-Fi scan is part of the Settings Wi-Fi card (a click on a network fills in its name); the scan output now HTML-escapes SSIDs, which come from any neighbour.
- **Web UI, continued:**
  - Settings tabs are underlined and scroll horizontally on a phone. Checkboxes are switches. Card headers are compact. Sliders and code use the ink colour; info and danger banners are outlined.
  - Card titles are in plain English: the French/English mix is gone, and so are "Elite … Mastery/Studio".
  - System Usage reads like a summary: up time, load, CPU busy since boot, memory in MB with the available share. The process list is collapsed, and "absent" boot entries are no longer listed as services.
- **Web UI, "control monitor" style (css/ui-v2.css, loaded after ui-modern):**
  - the live image is the centrepiece, with its status overlaid in the picture (state, time, camera name, profile, light level);
  - one line of readings sits under the picture: CPU, memory, Wi-Fi, SD card, MQTT;
  - visual hierarchy: one dark primary action; Push-to-talk ("Talk") is no longer an alarm-red button; flat background without halos; underlined active menu item;
  - Services is a list with a state dot, a "Boot" switch and a plain Start/Stop button. On a phone the button used to be off-screen;
  - Device Info and System Usage no longer overflow the screen on a phone (they were 714 px and 1036 px wide on a 390 px screen).
- **Firmware updates extract only the files that differ from the installed ones.** The whole package used to be written to the SD card. Measured on a TC100: 12 files extracted instead of 179, and upload + verification took 68 s instead of 132 s.
- **Day/night thread polls every 500 ms instead of 100 ms** (`RTSP_DAYNIGHT_POLL_MS`, applied by libtc100fix to that single `ak_sleep_ms` call site, identified by its return address in the bundled binary). Measured on a TC100 at night: the thread wakes up 2×/s, v4l2rtspserver goes from 30 % to 28 % CPU.
- **Sound detection:** the default threshold moves to -24 dBFS. At -30, an evening at home gave ~170 events an hour, 70 % of them within 3 dB of the threshold. New `MIN_LOUD_SECONDS` setting: publish only once a burst has lasted that long (default 1).
- **MQTT: publishes reuse the persistent connection.** Each message used to open its own TCP connection, with CONNECT, a 1 s wait and DISCONNECT. That made ~1,100 connections in 4 h on a camera with sound detection. Now the packet is written in one go into the listener's connection, once its handshake is written and the broker has accepted it; otherwise it falls back to the old path. Measured on a TC100:
  - 5 publishes: 0 new connections, all received by a subscriber;
  - bridge startup: 13 s instead of 44 s, because the listener now starts before the ~40 Home Assistant discovery messages;
  - discovery payloads: all valid JSON on the broker.
- **Main-stream audio defaults to G.711 A-law instead of AAC** (new installs; settings page labels the cost). Measured on a TC100 at 1080p: v4l2rtspserver 36 % → 28-29 % CPU, idle 52 % → 55-60 %. Frigate's `preset-record-generic-audio-aac` re-encodes recordings to AAC anyway (checked: copy video + AAC audio from the G.711 stream).
- **SD card wear: routine logs stay in RAM.** Measured on a TC100: a cron heartbeat file rewritten every minute (temp file + rename), a stability sample appended every 5 minutes, one sound-detection log line per event (hundreds an evening) and the RTSP server's output all went to the SD card. Now:
  - the sound-detection and RTSP server logs live in /tmp/log, bounded;
  - stability samples are batched in RAM and appended once an hour;
  - the heartbeat is overwritten in place (64 bytes, no new cluster or directory entry) every 15 minutes;
  - /mnt is remounted noatime.
- **System log:** notice and above plus logins, in at most 256 KB of RAM. It used to keep everything, in up to 800 KB; three quarters of it was a USB host controller info line every ~15 s and crond's per-job lines. Remote forwarding sends the same filtered stream and keeps logging locally; stopping the syslog-forward service used to leave the camera with no syslogd at all.
- **Critical lines survive reboots:** every 5 minutes, new warning-or-worse lines about storage, memory, kernel faults and our own `tc100_log_event` failures (RTSP start failure, GOP stall) are appended to /mnt/log/important.log. Nothing is written when nothing happened.
- **System usage page:** one load-average line. The `uptime` output printed it a second time.
- Hardware watchdog: fed every second with an 8 s timeout (the AK39 driver maximum) instead of every 2 s / 5 s, at nice -15 so a loaded system does not starve it. Suspected cause of an unexplained reboot under load. Verified on hardware (`watchdog -t 1 -T 8`, nice -15).
- `vm.min_free_kbytes` 1024 → 2048 at boot: free RAM hovered at 1.5–2 MB, fragmented, and the RTL8188FU driver drops what it cannot buffer.
- The RTSP password no longer shows in `ps` / `/proc/<pid>/cmdline`: `libtc100fix.so` (`TC100FIX_HIDE_CREDENTIALS`, set by rtsp-h26x whenever credentials are passed) overwrites the `-U` argument once v4l2rtspserver has copied it; the start line in the RTSP log is masked too. Verified on hardware (`-U *********`, clients still authenticate).
- The Services page cache is built in the background 45 s after boot (first visit took ~9 s, now ~0.3 s).
- Main stream default 1920×1080 (sensor resolution; was 1280×720), 1.6 Mbit/s target. Tested on hardware at 12 fps: 1.5 Mbit/s, 3 MB RAM free, CPU ~29 %, Frigate unaffected. Second camera at 16 fps: 15.6 fps, 1.6 Mbit/s, keyframes ~220 KB. The sub-stream codec makes no measurable difference to Frigate (same camera, 640×360, H.265 vs H.264: decoder ~6.8 % CPU both ways); the template keeps H.264 for browser playback. Existing cameras keep their own `rtspserver.conf`.
- Web server: `bin/lighttpd` rebuilt (same 1.4.69, `src/lighttpd/build.sh`, Anyka toolchain). The previous binary had `mod_setenv`, `mod_expire` and `mod_deflate` compiled but not registered, and no zlib. The new one registers them (plus `mod_access`, `mod_accesslog`), links zlib statically and OpenSSL/PCRE2 against the libraries already in `lib/`; 428 KB stripped (old 654 KB with debug info). A new `# @migrate webperf` block in the lighttpd templates enables, for existing cameras too (added only once `lighttpd -tt` accepts it, i.e. with the new binary):
  - gzip of static CSS/JS/HTML, compressed once per file and kept in `/tmp/lighttpd-deflate` (84 KB of tmpfs); CGI output is never compressed. A first page load drops from 281 KB to 51 KB (Bulma 123 → 16 KB, `index.bundle.min.js` 93 → 21 KB).
  - versioned assets (`?v=1.8.4`) cached 30 days by the browser: a reload sends no request for them (checked in Chrome: transfer 0 B). Bulma's link is now versioned too.
  - `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: same-origin` on every response.
  Measured on the camera (lighttpd CPU, 7 assets per load): first load after boot 0.42 s (compression), each later full load 0.14 s instead of 0.28 s with the old binary (fewer bytes to encrypt). Memory footprint unchanged (VSZ 6.2 MB vs 6.3 MB). With the 1.8.3 binary still in place the block is refused and logged, and the web server keeps its current config.
- Services page: `allstates` answers in ~1 s instead of 5–12 s (measured on the camera, CLI 5.3 s → 1.0 s). Services whose status is "PID in the pidfile is alive" are read from the pidfile and `/proc`; the LED / IR / night / motion / auto-night / web-server toggles are computed from the same files their `status()` reads; script capabilities are cached in `/tmp` until a controlscript changes. No script is started per poll any more (each start cost ~0.2 s). States verified identical to the probe-based version on hardware.
- `RTSP_MIC_OFF_WHEN_NO_AUDIO` defaults to 1: with `RTSP_AUDIO=0` the vendor server no longer runs the microphone, echo canceller and noise reduction (~6.5 % CPU). No effect when audio is served; set 0 to restore the vendor behaviour.
- Version 1.8.4: `VERSION`, asset cache keys (`?v=1.8.4`), README; the boot log printed a hard-coded "Version: 1.0.0" and now reads `/mnt/VERSION`.
- Motion detection monitor polls every 10 s (12 s after a detection), the values the camera had been tuned to, instead of 20/20 s.
- Removed dead code: the lazy loader for `bulma-switch`/`bulma-badge`/`bulma-divider` (only triggered by a `status.cgi` page that no longer exists, so they were never applied) and the three stylesheets.
- The web UI loads a purged Bulma: 677 KB → 123 KB uncompressed (16 KB gzipped with the rebuilt lighttpd); measured on the camera 0.9 s → 0.2 s for the stylesheet. Rendering checked identical against the full Bulma on 84 screenshots (every page and Settings tab, light/dark, desktop/mobile, real CGI output from the camera); only the "Updated" clock differs.
- Push-to-talk is confirmed working on hardware: README *Known issues* and `docs/api.md` (`upload_audio.cgi`, `get_ptt_status`) now describe the patched `/mnt/bin/ak_ao_ptt` player, the RTSP pause during playback, CSRF on uploads and the `READ_FAILED` / `AUDIO_DEVICE_BUSY` responses.

### Added
- **Optional wpa_supplicant 2.11** (`WIFI_CLIENT=new` in boot.conf, default `vendor`). The vendor Wi-Fi client is Realtek's patched 0.8.x from 2013, older than the KRACK fixes. `bin/wpa_supplicant` is 2.11 built for the RTL8188FU's wireless extensions with internal crypto, no WPS/EAP (`src/wpa_supplicant/build.sh`, reproducible, sha256-checked source). `scripts/wifi-client.sh` starts it in place of the vendor daemon (the vendor configuration's WPS keys, which 2.11 would reject, are filtered out; the vendor connect script adds the network as usual) and falls back to the vendor client, with an important event, if it has not associated within 60 s. Tested on hardware (.24): associated in 4 s, WPA2-PSK/CCMP, 0.7 MB RSS.
- **French / English interface** (`scripts/i18n.js`, `i18n/fr.js`). A FR/EN switch in the top bar; the choice is kept per browser and defaults to the browser language. Pages stay written in English; in French a dictionary (~600 strings, 12 KB compressed, cached 30 days) is loaded once and visible text, placeholders, tooltips and confirmation messages are translated, including what the scripts load or update later (MutationObserver) and the few messages built with numbers (rules). In English nothing extra runs. `src/webui/i18n-strings.py --missing` lists untranslated strings; a test keeps it empty.
- **Smooth live view through Frigate.** Settings → Automation → Frigate live view: enter Frigate's address (e.g. `http://192.168.1.20:5000`); the camera's name in Frigate is found from Frigate's configuration (input or go2rtc stream with this camera's IP; one request, only when saving). A "Smooth live" button under the picture then opens the camera in Frigate's live page (go2rtc restream, full frame rate and sound) in its own tab: Frigate is plain HTTP and the camera UI HTTPS, so it cannot be embedded (mixed content), and relaying the video through the camera would cost it CPU. Frigate already pulls the stream through go2rtc, so viewing adds no connection to the camera.
- **Remote syslog ready for a NAS.** The Settings card explains the Synology Log Center setup (BSD, UDP 514) and the host is validated (host name or IP only: boot.conf is sourced by the shell, a crafted value could run commands at boot); enabling without an address is refused with a message. Verified on hardware with a UDP listener: notice-level messages, logins and `tc100-event` lines arrive with their priority (~13 lines/min at rest; the remote also receives info-level kernel lines, which busybox syslogd cannot filter per destination).
- **Read-only firmware image** (`firmware.sqfs`, `scripts/rofs.sh`). The code directories (`bin lib scripts controlscripts www`) run from one squashfs file, loop-mounted read-only at boot and bind-mounted over the FAT copies, so a FAT corruption caused by the logs/recordings written all day can no longer damage the code (the 2026-10-13 incident). The FAT copies stay underneath as the fallback, used when the image is missing, its `VERSION` differs from the card's, the mount or a smoke test fails, `FIRMWARE_IMAGE=0` (boot.conf) or `RECOVERY` mode. Its md5 is checked once, niced, 5 min after boot; a corrupt image is renamed `.bad` and logged as an important event. Updates keep both up to date: files go to the FAT copies through an overlay-free view of the card (`/tmp/rofs/fat`), the image is written as `firmware.sqfs.new` and swapped in at the next boot (the previous one stays as `.old`, which a rollback puts back). `src/release/build-image.sh` builds it reproducibly (gzip, 32 KiB blocks, FAT-like 0755 modes); `build-update.sh` ships it. The patched PTT player is built into RAM (`/tmp/bin`) when `/mnt/bin` is read-only. An image file on the existing partition rather than a second partition: the cards have one. Measured on hardware: reading every code file takes 8.8 s from the image vs 6.4 s from exFAT (xz: 14.5 s, lzo unsupported by the kernel); CPU and free memory unchanged in steady state.
- **Home Assistant diagnostics** in `<root>/health` (`diag`) with discovery entities:
  - Wi-Fi signal (dBm), Wi-Fi dropped packets, refused connections (PAWSPassive);
  - available memory, sound level (dBFS), light level, night mode;
  - "SD card problem" binary sensor (card read-only, or FAT/MMC errors in the kernel log).
  - Checked on hardware: 8 entities on the broker, values in the real health message.
- **`TAMPER_DETECTION=1`: ISP sharpness and histogram statistics** sampled every 2 s into /var/run/od by libtc100fix (`ak_vpss_od_get`), as groundwork for a lens-covered alert. On the camera's library, histogram bin 255 holds an aggregate and is ignored.
- **ISP tuning: `NR3D=0` turns the temporal (3D) noise reduction off** live; removing the line restores the ISP file's setting. Measured on a TC100 in low indoor light at 1080p: the frame rate stays at ~10 fps (the 3D NR is not what caps it), and the bitrate rises by 39 %. So the default stays on.
- Settings → System → **Firmware update**: upload a package built by `src/release/build-update.sh` (`dist/tc100-update-<version>.tar`, payload + `MANIFEST` of md5 sums). `update.cgi` streams it to the SD card (lighttpd `server.stream-request-body`, new `# @migrate updatestream` block, so the upload never sits in RAM); `scripts/fw-update.sh` checks every file's md5, shell syntax and paths, then installs only changed files by rename (safe for running binaries and scripts), keeps the replaced ones under `/mnt/backup/update-<date>`, runs config-migrate, checks the web server config with the new lighttpd (rolls back by itself if it fails) and reboots. One click rolls back. Start-at-boot toggles and `wpa_supplicant.conf.dist` are never overwritten. Every write is re-read and retried: on hardware one extraction came out with 8.7 KB of zeros at the 128 KiB boundary of a 428 KB file (memory pressure, not reproducible) and was caught by the check. Validated on the camera end to end: upload 16 MB (~100 s over HTTPS), verify, install + reboot, rollback + reboot, reinstall.
- Reboot tracking (`scripts/reboot-tracker.sh`): every deliberate reboot (web UI, MQTT, network-monitor, service-watchdog, schedule, firmware update) records why; a heartbeat (cron, once a minute) records the last time seen alive; at boot the previous run is classified and Device Info shows "Previous run ended: …" (history in `/mnt/log/reboot-history.log`). A run that ended with no recorded reason was a hardware-watchdog reset, a power loss or a crash.
- `scripts/config-migrate.sh`, run at boot: configs from older releases now receive new settings. `install_config` only copied a `.dist` when the file was missing, so an existing camera never got new keys (measured on a 1.8.3 camera: `boot.conf` lacked 34 keys, `mqtt.conf` 7). Append-only and idempotent: missing keys are added with their default, a key the user commented out counts as present, existing lines are never changed. When a `.dist` default differs from what the code does without the key (e.g. `MEM_WATCHDOG_ENABLE`), the code default is written so behaviour does not change; a test fails if such a divergence is not declared. lighttpd configs receive `# @migrate` blocks from the `.dist`, checked with `lighttpd -tt` first, and a config naming the missing `mod_setenv` is repaired. A checksum stamp makes later boots a single `md5sum`. Verified on hardware with the camera's BusyBox 1.24 (also covered under qemu by the tests), including a reboot.
- `src/webui/purge-bulma.mjs` (PurgeCSS 6.0.0): builds `www/css/bulma.1.0.2.purged.min.css` from the full Bulma kept in `src/webui/`. A test fails if a class the UI uses is missing from the purged file.
- Image tuning controls: a "Live image tuning" card in Settings → Image & text (sliders, anti-flicker, exposure cap, applied-values line) and Home Assistant entities over MQTT (six `number` sliders, an anti-flicker `select`, an `Image Tuning` switch; retained `<root>/isp/state`). Shared validation in `scripts/isp-tune.sh`; endpoints `state.cgi?cmd=isp_tune` and `action.cgi?cmd=isp_tune` (see `docs/api.md`). Verified on hardware: UI save → brightness 30 applied, stream luma 111.9; MQTT commands in Home Assistant's exact format applied (brightness −10, exposure cap 40 %, anti-flicker, reset), invalid values rejected with a command result.
- Live image tuning (`ISP_TUNE=1`, `config/isp_tune.conf`): brightness, contrast, saturation, sharpness, hue (−50..50, relative to the sensor ISP file), mains frequency 50/60 Hz and an auto-exposure time cap (% of the ISP value). A thread in `libtc100fix.so` applies changes within ~2 s without restarting the stream and writes `/var/run/isp_tune.status`. Uses the camera's own `ak_vpss_effect_set` numbering (0–4 effects, 5 style, 6 Hz), which differs from the public EV300 SDK v18 header. The vendor re-applies effects after each day/night ISP reload; the exposure cap is re-applied by the thread. Verified on hardware: brightness +40 → mean luma 89.8→113.1, contrast +40 → black 38→16 / white 145→165, saturation +40 → +63 %, sharpness ±40 → edge energy 7.48/5.22 vs 6.70, exposure cap 40 % → `exp_time_max` 1125→450 and back to 1125; same server PID throughout.
- `lib/libtc100fix.so` (source `src/tc100fix/`, Anyka uClibc toolchain): run-time fixes for the closed vendor `v4l2rtspserver`, preloaded into that process only, each opt-in from `boot.conf`: `RTSP_FPS_LOCK`, `RTSP_MIC_OFF_WHEN_NO_AUDIO` (only acts when `RTSP_AUDIO=0`) and `VENDOR_PRINT_LEVEL` (replaces the level 3 the server forces into `/var/log/ak_print_level`). Inert when no option is set. Tests include an ARM-emulated run against the camera's uClibc (`TC100_SYSROOT`, fixtures in `tests/tc100fix/`).
- `scripts/collect-platform-dump.sh`: read-only platform inventory for reverse engineering (raw MTD images via `dd if=`, `/proc` and `/sys` facts, vendor filesystem, library fingerprints), written to the SD card only. Uncompressed archives: the camera busybox has no `gzip` applet.
- Restore `.gitignore` (live configs with credentials, `wpa_supplicant.conf`, runtime artifacts, Python bytecode). `.github/` is no longer ignored.
- GitHub Actions CI: `busybox ash -n` syntax check of every camera-side shell script, Python host regressions and Node frontend tests.

## [1.8.3-rc20] — 2026-09-11

### Changed
- Final stabilization candidate for 1.8.3: Frigate Light profile, bounded monitoring, restored PTT, transactional configuration updates, flat low-cost UI, and the completed operator workflow.
- Tighten release readiness by documenting the final validation gates required before tagging 1.8.3.

### Validation
- Candidate branch is prepared for the final AK3918 trial and release checks before promoting to the 1.8.3 tag.

## [1.8.3-rc10] — 2026-09-10

### Fixed
- Coordinate PTT with the AK3918 exclusive audio device: pause RTSP only for the clip, keep the upload lock until playback ends, then restart RTSP from a detached cleanup worker.


## [1.8.3-rc9] — 2026-09-10

### Fixed
- Release the PTT upload lock when the CGI exits, preserve PCM until playback finishes, and recover locks orphaned by older versions when no playback PID is alive.


## [1.8.3-rc8] — 2026-09-10

### Fixed
- Rebuild PTT playback from the stock firmware behavior: the TC100 amplifier enable is active-low, while ak_ao_demo drives it with the opposite polarity. A source-MD5-guarded installer creates /mnt/bin/ak_ao_ptt and flips only the two speaker-control instructions; /usr/bin/ak_ao_demo remains untouched.


## [1.8.3-rc3] — 2026-09-10 (device trial pending)

### Changed
- Validate imported ports, video geometry/rates/codecs, schedules, recording,
  sound, MQTT and one-line system values before touching active files.
- Stage JSON, legacy text and tar.gz restores under `/tmp`; commit all candidate
  files together and automatically restore originals after a write or readback failure.
- Bound backup decompression to 2 MiB and keep all import work sequential, with no
  resident process or added idle-memory cost.
- Add `frigate-light-ak3918`: H.265 720p/12 fps main stream and H.265 360p/8 fps substream, matching the AK3918 dual-encoder constraint observed on real hardware
- Preserve valid AK3918 audio codec values when profiles disable RTSP audio; `RTSP_AUDIO=0` now controls publication without breaking RTSP startup
- Retry RTSP DESCRIBE during encoder warm-up so a healthy stream is not rolled back before its listener becomes ready
- Use a raw RTSP DESCRIBE probe for profile validation because the bundled curl sends OPTIONS; accept Digest 401 or a video SDP 200 response
  detection stream, 1.32 Mbit/s combined target and audio disabled.

### Fixed
- Correct JSON import mappings for RTSP sections 0/1, audio sections 2/3, OSD,
  motion sensitivity and recording keys. Preserve raw JSON POST bodies.
- Export the real hostname, timezone, NTP server, flip/log flags, OSD placement and
  recording values so exported JSON can be restored without silent drift.
- Preserve the uploaded archive path while creating a rollback archive.

### Validation
- 38 host regression tests cover valid commits, full-batch rejection, JSON and legacy
  imports, staged archive restore, the new profile values, shell/JavaScript syntax and
  existing resource regressions. Real AK3918 validation remains pending.

## [1.8.3-rc2] — 2026-09-09 (device trial pending)

### Changed
- Keep everyday video/audio controls visible and collapse advanced encoding,
  audio formats and day/night thresholds in native, keyboard-accessible details.
  Opening a section preserves all values and makes no network request.
- Save main and secondary streams independently, including the selected stream
  and all existing advanced parameters. Correct the quality preset label to 720p.
- Settings submissions request JSON and inspect the application result, keep
  drafts on failure, prevent concurrent submissions, and show persistent feedback.
- Video/audio saves perform one configuration readback. A requested restart is
  clearly distinguished from a verified RTSP health check. Quick profiles return
  the result of the existing restart/rollback checks and refresh clean video forms.
- Disable settings submission until configuration is loaded; reveal and focus
  invalid fields inside closed advanced sections. Update asset cache versions.

### Fixed
- Read real INI sections when loading settings; expose CBR/VBR as the bitrate
  mode and read audio codecs from sections 2/3. Audio saves write the volume and
  section 2 codec, preserving the main video codec in section 0.
- Video/audio write failures no longer schedule a restart or return success.
- The local draft is removed only after the asynchronous save is confirmed.
- Improve inactive tab contrast and primary button text in settings.

### Validation
- 27 host regression tests and 14 Chrome interaction checks using simulated CGI
  responses. Mobile (390 px), desktop (1280 px), light and dark views inspected.
- Hardware behavior and CPU/RAM gains remain pending. No new background polling
  or frontend dependency. See the rc2 trial guide (removed from the tree, see git history).

## [1.8.3-rc1] — 2026-09-09 (device trial pending)

### Changed
- Share the main statusline poll with dashboard gauges; respect the configured
  health snapshot interval and adapt cache expiry to it (60 seconds by default).
- Bound MQTT capture size and decode only unread bytes in 16 KiB batches, with
  session-specific offsets and a 4 KiB maximum command frame. Add a retained
  offline Will and clean up the listener's own child processes.
- Skip identical configuration writes and unnecessary config-install hashing.
  Remove the unconditional FTP watchdog and boot-time cache drop. Existing
  live configurations and video settings are preserved.
- Limit backup uploads to 1 MiB compressed / 2 MiB expanded / 512 entries,
  rejecting archive links. Require POST and CSRF on the corrected mutation routes.
  Frontend callers and asset cache versions are updated together.

### Fixed
- Preserve raw POST bodies in the config editor and backup upload; refuse
  truncated writes and invalid shell syntax, keep a bounded editor backup.
- Remove recursive configuration installation in action.cgi; correct backup and
  timelapse date formatting; make package backups include the rollback manifest.
- Subtract shared memory from the fallback available-memory estimate and report
  failed deep RTSP/ONVIF probes instead of treating a live PID as healthy.
- Prevent FTP/Telnet starts in security hardening mode and bound update-check waits.

### Validation
- Host regression tests, syntax checks and existing binary hashes checked.
  ARM/BusyBox compatibility and resource gains still require the camera trial.
- French trial and rollback procedure: docs/essai-1.8.3-rc1.md (removed from the tree, see git history).

## [1.8.2] — 2026-08-13

### Fixed
- **Capability probe reported `fail` on a healthy camera.** `capability-check.sh`
  runs right after `run_autostart_scripts`, which starts the video daemons in the
  background — so the ISP pipeline is frequently not capturing yet and the single
  `getimage` attempt returned 0 bytes. A camera that served a 42 KB frame one
  minute later was flagged `{"status":"fail","failed":["getimage"]}`, and a
  monitoring signal that cries wolf is worse than no signal at all.
  The probe now retries up to 3 times (~24 s worst case; a healthy camera answers
  on the first, so it costs nothing normally) and distinguishes the two cases it
  previously conflated: a genuine `fail` only when `/var/run/v4l2rtspserver.pid`
  shows RTSP is up and `getimage` *still* yields nothing; otherwise
  `getimage_unverified` under `shimmed`, because with the pipeline down the probe
  honestly cannot tell "broken" from "not ready yet".
  Verified across two reboots of `.11`: `fail` before, `degraded` with
  `failed:[]` after, while `currentpic.cgi` served 41 976 bytes.

## [1.8.1] — 2026-08-13

TLS certificate lifecycle. Measured on both live cameras.

### Fixed
- **Expired HTTPS certificate was never renewed.** The certificate was generated
  with `-days 365` and only ever when the file was *absent*, so every camera older
  than a year served an expired cert — `.11` had been expired since 8 May 2026,
  which is what produced the `sslv3 alert certificate unknown` entries in
  `lighttpd-error.log`. `02_system-webserver` now also regenerates when
  `openssl x509 -checkend 0` fails, moving the old file aside as
  `lighttpd.pem.expired` rather than deleting it. Validity raised to 10 years.

### Changed
- **Self-signed certificate is now ECDSA P-256 instead of RSA-1024.** On this
  ARMv5 core (no crypto instructions) the TLS handshake measured **~0.09 s against
  ~0.14 s** — a real but modest gain, because the key being replaced was RSA-1024,
  already cheap to verify; against RSA-2048 the difference would have been far
  larger. The stronger reasons are correctness: RSA-1024 is below any current
  security floor, and EC keygen is instant where RSA took seconds — which matters
  because it runs during boot. Verified end-to-end on `.11`: `lighttpd -t` clean,
  HTTPS back 5 s after restart, certificate valid to 2036.

### Notes
- **`AK_PRINT_LEVEL` is a no-op on this hardware — deliberately left unset.**
  Probed on `CLOUD39EV3_AK3918EV300_MNBD`: none of the three candidate sysfs/proc
  paths exist, and there is no message flood to suppress in the first place (last
  `dmesg` line unchanged over 15 s; `syslogd` and `klogd` together consumed 1.35 s
  of CPU across 6 h of uptime, ~0.006%). The knob is kept for builds that expose
  it, but `boot.conf.dist` now records the measurement so nobody chases the
  phantom win again.
- Contrary to an earlier suspicion, certificate generation on a fresh card is
  **not** broken: `config/openssl.cnf` ships with the payload and
  `02_system-webserver` already exports `OPENSSL_CONF`. The manual failure that
  prompted the concern came from invoking `openssl` without that variable set.

## [1.6.2] — 2026-08-11

Closes the last MQTT gap: Home Assistant can now **control** the camera, not just
watch it. Everything below is verified on both live cameras.

### Added
- **Forged SUBSCRIBE — inbound HA → camera commands work.** `subscribe_once_command()`
  now builds the MQTT 3.1.1 CONNECT + SUBSCRIBE frames in shell, pipes them to
  `nc`, and decodes the reply stream (read as decimal bytes via `od -An -tu1`,
  since busybox awk has no `strtonum()`). Verified end-to-end: publishing
  `{"cmd":"front_led","value":"on"}` yields
  `{"command":"front_led","status":"applied","ok":1,"source":"mqtt"}` on
  `<root>/command/result`, on both cameras independently.
  - Beyond the feature, this **frees CPU**: the old curl path failed on every
    attempt (`rc=28`), leaving a hung 10 s process every ~32 s, forever.
  - The curl implementation is kept as `subscribe_once_command_curl()` and stays
    reachable via `MQTT_FORGE_SUBSCRIBE=0` — disabled, not deleted.

### Fixed
- **Cameras listened on a shared command topic (regression from 1.6.1).** 1.6.1
  derived `MQTT_CLIENT_ID` and `MQTT_TOPIC_ROOT` from the hostname, but
  `MQTT_TOPIC_COMMAND` is written out explicitly in `mqtt.conf`, so it stayed at
  `teckin/tc100/command`: each camera published under its own root while every
  camera listened on the *same* topic — the exact collision 1.6.1 set out to fix.
  The command topic is now re-derived alongside the root whenever it still matches
  a shipped default; a genuinely custom topic is preserved.
- **`is_truthy` was out of scope in `mqtt-bridge.sh`.** The bridge's helper is
  `is_truthy_local`; `is_truthy` only exists in `autorun.sh`. Calling it failed
  silently and always took the fallback branch — the same "call something that
  isn't there, fail quietly" pattern as the `tr` family of bugs.

### Changed
- **HA "Live" camera entity is off by default** (`MQTT_HA_CAMERA_ENTITY_ENABLE=0`).
  Its discovery config points at `snapshot/last_path`, which carries a filesystem
  *path*, while HA's MQTT camera platform expects the image *bytes* — the entity
  could never render. Publishing the JPEG over MQTT instead would cost tens of KB
  per snapshot on a 33 MB device, so the supported route stays RTSP/go2rtc. The
  entity is disabled, not removed: set the flag to `1` to publish it again.

### Notes
- Command delivery is polled in ~12 s windows, so a QoS 0 message published
  between windows is missed. Publish **retained** for guaranteed delivery, then
  clear the retained value so the command is not replayed on the next subscribe.

---

## [1.8.0] — 2026-08-13

### Added
- **Boot-time capability probe** (`scripts/capability-check.sh`). This firmware has now shipped two bug classes where a tool *existed* but did not behave as the code assumed, and failed **silently**:
  - `tr` — busybox carries the applet but ships no symlink, and `/mnt/bin` is not on the CGI `PATH`. Exit 127 inside `$(...)` yields `""`, so callers got empty data rather than an error. Five shipped bugs.
  - `timeout` — `/bin/timeout` exists *and is on `PATH`*, but is the pre-2014 busybox variant wanting `-t SECS`. Given the modern form it execs the duration as the command; inside a redirect that is invisible. `currentpic.cgi` served a 0-byte JPEG with HTTP 200 and the correct MIME type, and the dashboard liveview was simply blank.

  A `command -v` check passes in the second case, which is precisely why this probe runs each tool and inspects the **result**: `tr` must actually translate, `timeout SECS CMD` must run CMD, `awk` must `gsub()` and split on `RS`, `getimage` must emit a non-empty JPEG, `od -An -tu1` must yield decimal bytes (the MQTT decoder depends on it), and `nc` must exist (the MQTT transport).

  Results land in `/tmp/capability-check.json` and are surfaced under `capabilities` in `health.cgi`, so a misbehaving tool shows up in monitoring instead of as corrupted data downstream. The report distinguishes **`shimmed`** (expected here — the `tr()`/`timeout()` shims cover it) from **`failed`** (something the project genuinely relies on is broken). Verified on hardware: the probe independently rediscovered both known traps — `{"status":"degraded","failed":[],"shimmed":["tr","timeout"]}`.

  Cost: a handful of execs, once, at the end of boot. No daemon, no polling, and it never blocks boot (always exits 0).

### Fixed
- **Power-draw sensor missing on one camera in Home Assistant.** `POWER_ESTIMATE_ENABLE` was `1` on one unit and `0` (the shipped default) on the other, so `power_estimated_mw` published as `null` and the HA template resolved to `none`. The hardware sensor was fine on both — only the estimate was off. Aligned. Worth remembering that this value is *computed* (base + CPU share + IR-LED bonus), not measured: the camera reads voltage only, never current.

---

## [1.7.3] — 2026-08-13

Two real PTT bugs fixed. **Push-to-talk still produces no audible sound** — the
remaining cause is below the software layer; see *Known issues*.

### Fixed
- **Every PTT control was greyed out even with a healthy backend.** `ptt-audio.js` compared the `get_ptt_status` response strictly against `OK`, but `action.cgi` appends an HTML footer to every non-JSON reply, so the body is `OK\n<hr/>`. The mismatch reported "audio backend missing" and disabled the PTT button, the volume slider and the test button. Only the first line is read now.
- **Every PTT upload answered `EMPTY_INPUT`.** `upload_audio.cgi` streams a raw PCM body, but a hygiene pass had made it source `func.cgi` (for the `tr`/`timeout` shims) — and `func.cgi` slurps stdin at load time to parse form bodies, draining the stream before the PCM reader ran. A `FUNC_CGI_SKIP_BODY=1` guard now skips that slurp for binary-body callers; the shims stay. Upload returns `OK`/200 on both cameras.

### Known issues
- **PTT is silent: `v4l2rtspserver` holds the audio codec, and freeing it is not enough.** Diagnosed on hardware:
  - `ak_ao_demo` (the playback binary the CGI uses) prints `play finished` and exits 0 while producing **zero** DAC events in the kernel — it never reaches the hardware and never reports the failure.
  - The full-duplex path reveals the real error: `open /dev/akpcm_cdev1 failed: Operation not permitted`. `v4l2rtspserver` keeps that device open to capture `audio0`, and on this Anyka codec output requires opening it too.
  - With RTSP stopped, `ak_aec_demo` drives the kernel through the *exact* sequence the stock firmware logs at boot — `IOC_SET_SPEAKER value=1`, `ak39_set_hp_power 1`, `set_channel_source: s_dac=1` — identically for `spk_gpio` 0 and 1 (the driver powers the amp itself; that GPIO is not the gate). **Still no audible output.**

  So the software chain is now provably complete down to the driver powering the amplifier, and the remaining gap is below it. Disabling audio in the RTSP stream would free the device but, on this evidence, would *not* restore sound — it was effectively tested by stopping RTSP entirely.

  Next discriminator (needs the operator): boot a camera **without the SD card** so the stock firmware and its `anyka_ipc` app run, and test two-way audio from the vendor app. Working there points at an initialisation `anyka_ipc` performs that our environment never runs (we kill it in `stop_cloud`); silent there points at hardware.

---

## [1.7.2] — 2026-08-13

Consolidation release: no new features, only truthfulness — of logs, of metrics,
and of documentation — plus the first real reboot validation of the 1.6.x boot
changes.

### Fixed
- **`health.cgi` / `health-snapshot` reported `mem_avail_kb:0`.** This kernel ships no `MemAvailable` line and neither consumer had the fallback `state.cgi` already used. Both now estimate available memory as free + buffers + cached + SReclaimable. (While auditing this, the RAM gauges in `state.cgi` and the MQTT health payload turned out to already be cache-aware — the ~17–19 MB "used" figures are honest, and the inter-camera delta is page-cache noise, not a leak. Verified: process sets on both cameras are identical, no orphaned listeners.)
- **The bridge logged `using legacy one-shot polling` while the persistent listener was active.** The pre-persistent FIFO "stream mode" still ran its detection and printed its verdict; in persistent mode it would even have opened a competing broker connection had the shell supported it. The persistent path now short-circuits that block and logs what is actually happening (`Command path: persistent listener`). This line cost real debugging time twice.

### Documentation
- **Quick Start: still image in HA at zero camera cost** — a *Generic Camera* integration pointing at `currentpic.cgi` (basic auth, SSL verify off). HA pulls the JPEG on demand and the camera's 2 s snapshot cache absorbs the polling. This is the supported replacement for the disabled MQTT camera entity.

### Validated
First controlled reboot since the 1.6.x boot changes, on both cameras:
- `initialize_gpio` applies the configured LED intent (`FRONT_LED=0` → LED off at boot, previously only verified by inspection).
- The blocking NTP step before lighttpd holds: the error log opens with a real 2026 date and contains **zero** `clock jumped` graceful restarts (previously one per boot, killing every open connection ~40 s in).
- The `frigate_ha` autostart trim is back in effect — deploy sessions had left `ftp-server` running on both units; after reboot it is off, as profiled. Start it on demand for deploys (`scripts.cgi?cmd=start&script=ftp-server`).
- `mem_avail_kb` reports ~24.7 MB where it previously reported 0.

---

## [1.7.1] — 2026-08-13

### Fixed
- **Dashboard liveview and snapshots were blank on every camera.** `/bin/timeout` on this firmware is the pre-2014 busybox variant, which wants `timeout -t SECS CMD`. Given the modern `timeout SECS CMD` it tries to exec the *duration* as the command:

      timeout 5 /mnt/bin/getimage  ->  timeout: can't execute '5': No such file or directory

  Inside a redirect that failure is silent, so `currentpic.cgi` returned HTTP 200 with `Content-Type: image/jpeg` and **zero bytes** — the browser simply showed nothing. `getimage` itself was fine all along (57 KB JPEG when run directly).

  A `timeout()` shim now routes to `busybox timeout` (whose applet accepts the modern form) from `func.cgi` and `common_functions.sh`, covering `action.cgi`, `state.cgi` and `clip_thumb.cgi`. `currentpic.cgi` is deliberately standalone — it sits on the liveview hot path and sources neither — so it carries its own copy. Verified on both cameras: a real 1280×720 JPEG is served again.

  Same shape as the `tr` class of bug, with a twist worth remembering: the binary **exists and is on `PATH`**, so a `command -v` check passes. Only its *behaviour* differs, which is why the shim probes with `timeout 1 true` instead.

### Notes
- The firmware version shown on the HA device page comes from the **retained** discovery config, which is only republished when the bridge starts. Deploying a new `VERSION` therefore does not update Home Assistant on its own — restart `mqtt-bridge` (or reboot) to refresh it. If HA still shows the old value afterwards, reload the MQTT integration; HA caches device metadata in its own registry.

---

## [1.7.0] — 2026-08-13

Validated on one camera (CAMERA1) before propagating; the second unit stays on
1.6.3 as a control until this is signed off.

### Added
- **Persistent MQTT listener — commands from Home Assistant are no longer lost.** The bridge used to subscribe in ~12 s windows, so a QoS 0 command published between windows was silently dropped and latency was 0–30 s (the README told users to publish *retained* and then clear the topic to work around it). One connection is now held open — CONNECT + SUBSCRIBE once, PINGREQ to keep it — and decoded frames are dispatched by the main loop. Verified on hardware with a **non-retained** command, the exact case that previously could not work: `{"cmd":"front_led","value":"on"}` was executed.

  Two device constraints shaped the design and are worth recording:
  - `od` **block-buffers its pipe output**, so the obvious `nc | od | awk` live pipeline delivers nothing until the connection closes (measured: 50 bytes sent, awk saw them only at stream end). `nc` therefore writes the raw stream to a file and the main loop decodes the increment — `od` flushes because it exits each pass.
  - The decoder resumes on an exact frame boundary and reports how many bytes it consumed, so a frame split across two passes is reassembled rather than lost. Covered by a split-frame test.

  The listener recycles its connection hourly (`MQTT_LISTENER_MAX_PINGS`) to bound the raw capture file. `MQTT_PERSISTENT_SUBSCRIBE=0` restores the previous windowed behaviour; nothing was deleted.

### Performance
- **`state.cgi` `json_escape` no longer forks for the common case.** It ran `printf | sed` — a fork+exec pair — for each of ~80 values per statusline poll, though hostnames, profile names and paths contain neither backslash nor quote. A pure-shell `case` guard now handles those; `sed` is spawned only when escaping is genuinely needed. Output verified byte-identical across backslash/quote/empty edge cases. Warm statusline: **~1.0 s → ~0.83 s**.
- **`health-probe.sh` gates the expensive deep probes behind a pidfile check.** `rtsp-h26x` and `onvif` both carry a pidfile *and* a costly probe (an RTSP DESCRIBE measured at ~1.2 s). A dead process is now reported `stopped` without paying for a network round-trip that could only confirm it. A live process still gets the full deep check, so a hung-but-running daemon is still detected.

### Notes
- The persistent listener trades resident memory for the loss of connect/teardown churn every ~13 s. Measured on both cameras after the rollout: RAM went from ~14.8 MB to **17.3 MB (CAMERA1) / 19.5 MB (CAMERA2)** of 33.4 MB, CPU unchanged at **43 % / 51 %** against a 41–43 % baseline. On a 33 MB device that memory cost is a real trade, not a free win — set `MQTT_PERSISTENT_SUBSCRIBE=0` if memory matters more than command latency on a given unit.
- Beware when measuring: `state.cgi?cmd=sysusage` read 98–100 % CPU immediately after a burst of HTTPS polls, because every CGI request is itself a fork on this core. Let the device idle ~90 s before trusting a CPU figure; `/proc/loadavg` (~1.2 steady, dominated by the RTSP stream) is the more honest signal.
- **Watchdog consolidation was evaluated and deliberately not done.** Measured cost of the current design: 504 KB per `service-watchdog.sh`, 1 008 KB for the two running instances, waking once per 60 s. Merging them into a single supervisor would mean moving per-service reboot-escalation state out into files (POSIX sh has no arrays) inside the one component that can reboot the device. ~500 KB does not justify that risk.

---

## [1.6.3] — 2026-08-11

### Fixed
- **The dashboard reported the front/red LED state from configuration, not from the hardware.** `state.cgi` read `get_cfg FRONT_LED 0` / `RED_LED`, but those keys were **absent from `boot.conf.dist`** — and therefore from every camera's live `boot.conf` — so the lookup always fell through to the default `0`. The UI showed "off" permanently while the LED was physically lit, on every camera. Verified on both units: `blue_led/brightness=1` and `controlscripts/front-led status` → `ON`, while the dashboard insisted it was off.

  Both LEDs are now read from `/sys/class/leds/*/brightness`, matching what `mqtt-bridge.sh` already did and what `controlscripts/front-led status` reports — one source of truth, so the whole class of drift becomes impossible. Confirmed on hardware: lighting the LED now flips the reported value to `1`, which the old code could never do.

  This mattered because the LED can be changed without the config ever being rewritten — by the motion blink, an MQTT command, or a controlscript — so configuration records *intent*, never *reality*.

### Changed
- **`initialize_gpio()` applies the configured LED intent at boot** instead of unconditionally forcing both LEDs off. `FRONT_LED` / `RED_LED` are now declared in `boot.conf.dist` (both `0`), so out-of-the-box behaviour is unchanged — but a camera deliberately left with its LED lit now survives a reboot, and what boot applies agrees with what `state.cgi` reports.

---

## [1.6.1] — 2026-08-11

Multi-camera follow-up to 1.6.0's MQTT publishing: two cameras seeded from the
same image no longer collide as one device in Home Assistant.

### Added
- **MQTT identity derives from the hostname.** `mqtt-bridge.sh` now sets
  `MQTT_CLIENT_ID` and `MQTT_TOPIC_ROOT` from a slug of the device hostname when
  they are still at a shipped default (empty / `tc100-camera` / `teckin-tc100`).
  Naming a camera `CAMERA1` vs `CAMERA2` is then the single action that gives
  each its own topic root, `uniq_id` prefix and HA device — no more two
  publishers fighting over `teckin/tc100`. Verified on both cameras: roots
  `camera1` / `camera2`, distinct HA devices.
- **Firmware version on the HA device page.** The discovery device dict now
  carries `"sw"` read from `/mnt/VERSION` (HA merges device info across a
  device's entities, so it's set on the CPU sensor). Verified: `"sw":"v1.6.1"`.

### Changed
- **`config/hostname.conf.dist` no longer ships a specific device name.** It held
  the literal `Anyka`; replaced with a neutral `TC100-CAMERA` default plus a note
  that each camera needs a unique hostname (which now also drives MQTT identity).
- **`tools/deploy-full.sh`** usage example uses `<camera-ip>` instead of a real
  LAN address.

### Notes
- The inbound command path (HA → camera) still uses `curl` for SUBSCRIBE and
  times out (`rc=28`); only the publish path was reforged. Camera → HA discovery,
  telemetry and availability all work.
- Upgrading from a pre-1.6.1 topic root leaves the old retained discovery under
  `homeassistant/.../teckin-tc100` as a ghost device in HA. Clear it by
  publishing empty retained payloads to those `.../config` topics (done for the
  two live cameras this release), or delete the stale device in HA.

---

## [1.6.0] — 2026-08-11

The headline: **MQTT actually publishes now** — the camera's whole reason to
speak MQTT (Home Assistant discovery, telemetry, motion events) worked for the
first time on hardware this release.

### Added / Fixed — MQTT publishing
- **`mqtt-bridge.sh` — messages are finally delivered.** `curl --upload-file mqtt://…` never published on this device's curl 8.1.2 (it sent SUBSCRIBE, not PUBLISH). `mqtt_publish_raw()` now forges the MQTT 3.1.1 CONNECT + PUBLISH(QoS0) + DISCONNECT packets in pure ash — `printf` is a builtin and emits `\xNN` bytes including NUL — and pipes them to `nc`. Success is confirmed by the broker's CONNACK in nc's reply. Verified end-to-end against the live broker: HA discovery config topics, health, availability and events all arrive; `mqtt_last_pub_ok` flips to 1. QoS is 0 (no packet-id/PUBACK bookkeeping in shell); the retain flag is preserved, which is what discovery and availability need.

### Performance
- **`state.cgi` statusline drops two `jq` forks.** The update-notifier read `/tmp/update_status.json` via two `jq` invocations, ~0.3 s each on the AK3918 and the dominant per-poll cost. Replaced with a single `read` + shell parameter expansion (the file is a flat one-line object).
- **NTP steps the clock before the web server starts.** In daemon mode `sync_time` ran a bare `ntpd -p` that forks and returns immediately, then makes its first step ~30–40 s later — after lighttpd is up. The jump tripped lighttpd's "clock jumped" graceful restart, dropping every keep-alive connection and stamping early logs with 1970 dates. A bounded (`busybox timeout 15`) one-shot step now runs first, then the disciplining daemon.

### Fixed
- **`conf-import.cgi` — latent `tr` bug (same class as 1.4.0/1.5.0).** This CGI sources neither `func.cgi` nor `common_functions.sh`, so it has no `tr()` shim, yet it used bare `tr`: `tr -d '\r'` on the uploaded body would have emptied it (silent no-op import), and the CSRF token strip would have collapsed both sides and bypassed the check. Rewritten in awk. Exercised end-to-end on hardware (export → import round-trip applies 92 keys; malformed input rejected).

### CI
- **`tr(1)` lint added to `.github/workflows/test.yml`.** Shim-aware: a bare `tr` fails CI unless the file has the `tr()`→`busybox tr` shim in scope (defines it, or sources `func.cgi`/`common_functions.sh`). This is the guard that would have caught all five `tr` bugs before they shipped.

### Tooling
- **`tools/deploy-full.sh` rewritten** around the failures observed during the 2026-08-11 deploy to the first camera (each one hit on real hardware):
  - Binaries (`bin/*`, `lib/*`) identical to the camera's copy are skipped by size comparison; differing ones are refused with a clear list unless `--force-binaries`. This is what prevents the ETXTBSY write onto a running daemon's binary that killed lighttpd mid-deploy.
  - Everything is batched — one curl invocation carries many URLs, so the camera's slow FTP login (~7 s on one unit, ~19 s on the other) is paid ~15 times instead of ~500. Preflight timeouts raised accordingly (the second camera's FTP accepts too slowly for the old 15 s cap).
  - The backup phase downloads only files that actually exist remotely (from a batched directory scan) — the old per-file loop burned a 20 s timeout per missing file, an hour on a fresh camera.
  - The health probe authenticates; unauthenticated, it read the 401 page and rolled back healthy deploys.
  - Upload success is established by re-listing the tree and comparing sizes — curl with several URLs only reports the last transfer's status. Failed files are retried individually.
  - No more `SITE CHMOD` (answers 500 on this ftpd; exec bits come from the vfat mount options).
  - A final `RESULT: exit N (reason)` line survives pipelines that mask the exit code.

---

## [1.5.0] — 2026-08-11

Performance release, driven by on-device measurements (AK3918, 33 MB RAM, CPU at
74% baseline). Every number below was measured on hardware before and after.

### Performance
- **Shared fork-free service prober** (`scripts/health-probe.sh`) — health.cgi and the health-snapshot daemon probed ~20 services by exec'ing each controlscript (a shell spawn + 21 KB `common_functions.sh` source per service): ~10 s of CPU per sweep, paid every 30 s by the daemon — roughly a third of the CPU budget spent on monitoring alone. The prober replicates the pidfile checks with ash builtins (`read` + `kill -0`, zero forks: 12 probes in 0.16 s) and still execs the controlscript for deep or composite services (rtsp-h26x RTSP DESCRIBE/GOP, onvif, motion-detection, motion-snapshot, auto-night-detection — 2.6 s). Sweep: ~10 s → ~2.8 s. Unknown services fall back to the slow-but-correct exec path.
- **lighttpd keep-alive raised to 45 s idle / 500 requests** (`lighttpd*.conf.dist` + live conf). The dashboard polls every 20 s but lighttpd's default idle is 5 s, so **every poll paid a full RSA handshake** — measured 0.2 s unloaded to 4.8 s under load, against 0.3–1.0 s for the same request on a reused connection. An idle connection costs a few KB of RAM; the handshake costs CPU. Note `install_config` never re-seeds an existing conf, so the live `/mnt/config/lighttpd.conf` was patched directly as well.
- **`state.cgi` `load_conf_file` no longer forks per config key** — the `$(printf | tr -cd)` key sanitizer ran once per line of every conf file loaded; replaced by a pure-shell `case` guard that outright rejects malformed keys (also stricter for the `eval` it protects).

### Fixed
- **health-snapshot daemon rewrote invalid JSON every 30 s** — it carried the same one-space meminfo bug fixed in health.cgi in 1.4.0, and since the daemon owns the cache, the 1.4.0 fix only held until the next refresh. Both paths now agree.
- **`tr` audit outside the CGI layer** (same missing-binary failure mode as 1.4.0):
  - `common_functions.sh` now carries the `tr()` → `busybox tr` shim, covering `autorun.sh` (boot-time CSRF token generation silently produced "", masked by func.cgi's lazy regen) and `mqtt-bridge.sh` (HA discovery node_id, and inbound command normalization — subscribe works even though publish is broken, so commands from HA hit these paths).
  - `update-check.sh` — version comparison fed empty strings to the badge logic; rewritten in awk.
  - `motion-event.sh` — event-log sanitizer emitted empty descriptions; rewritten in awk.

---

## [1.4.0] — 2026-08-11

Minor rather than patch: the theme toggle goes from inert to functional, which is
a visible behaviour change. Everything else here is a fix for a defect that made
a shipped 1.3.0 feature unusable on real hardware.

### Changed
- **Theme switching now actually works, and the dark palette matches the wizard.** `index.html` had a working toggle writing `data-theme` to `<html>` and persisting it, but `ui-modern.css` keyed its dark rules off `@media (prefers-color-scheme: dark)` and contained zero `[data-theme]` selectors — so pressing the toggle only swapped the icon. The three media blocks are now `:root[data-theme="dark"]` rules (56 selectors), the theme is resolved in JS (stored choice, else OS preference) and stamped in `<head>` before any stylesheet so no light frame paints, and the dark palette was remapped from its blue tones to the wizard's violet/indigo: background `#0d0f1a`, surfaces `#131624`, text `#e2e8f0`, accent `#6d58f5`. Only `index.html` needed the change — the other five HTML files are fragments injected into it and inherit the attribute.
  - `--ui-muted` is `#8a93a6` rather than the wizard's `#6b7280`: the wizard uses it for short card descriptions, but the dashboard uses it for table headers and dense rows, where `#6b7280` on `#0d0f1a` sits at the edge of the 4.5:1 contrast floor.

### Fixed
- **`action.cgi` `wifi_get_ssid` returned an empty SSID.** It read `/mnt/config/wpa_supplicant.conf`, a path that need not exist — this camera carries no `wpa_supplicant.conf` at all, the credentials live in flash. It now queries the interface first (`wpa_cli -i wlan0 status`, then `iwconfig wlan0`), falling back to the config files. Only the `ssid=` line is taken: `wpa_cli status` also prints `passphrase=` in the clear.
- **`action.cgi` `wifi_set_config` wrote to a file nothing reads.** It wrote `/mnt/config/wpa_supplicant.conf` and then called `wpa_cli reconfigure`, but `autorun.sh` starts `wpa_supplicant -c /mnt/wpa_supplicant.conf` — so the reconnect re-read the old file and the new credentials were used neither immediately nor at the next boot. Both commands now share a `WIFI_CONFIG_PATH` constant pinned to `autorun.sh`'s path.
- **`wizard.cgi` — the first-boot wizard could never complete on real hardware.** `get_field()` split the POST body with `tr '&' '\n'`, but `tr(1)` does not exist on the camera: busybox carries the applet without shipping a symlink for it, and `/mnt/bin` is not on the CGI `PATH` (`/sbin:/usr/sbin:/bin:/usr/bin`). Every field parsed as empty, so the handler always returned `{"ok":false,"error":"missing_params"}` and the UI showed only a bare "Réessayer" button. Splitting is now done with awk's record separator (`RS="&"`).
- **`wizard.cgi` — MQTT field sanitizers replaced.** The four `tr -cd` filters added in 1.3.0 were dead for the same reason; they now use `awk gsub()` with the equivalent negated character classes.

- **`func.cgi` — the dashboard was read-only: every mutating request returned 403.** `csrf_guard()` filtered both the stored token and the `X-CSRF-Token` header through `tr -cd` (lines 302, 322). Both sides collapsed to an empty string, the stored token was regenerated on each call, and the comparison could never match; `state.cgi` handed the browser an empty `csrf_token` for the same reason. Rather than patch each call site, a `tr()` shell function now routes to `busybox tr` when no `tr` binary is on `PATH`. It is defined at the top of `func.cgi`, which all 19 CGIs source, so every `tr` call in the CGI layer is repaired at once — including the WiFi SSID/PSK filters in `action.cgi` (lines 3176–3177), which silently blanked both fields.
- **`health.cgi` — emitted invalid JSON.** `/proc/meminfo` pads its values with several spaces, but line 62 stripped only one (`${_mv# }`), so `${_mv%% *}` yielded an empty string and the output contained `"mem_total_kb":,`. Values are now taken by word-splitting, which is padding-agnostic. Note `mem_avail_kb` legitimately reports `0`: this kernel's `/proc/meminfo` has no `MemAvailable` line.

### Known issues — verified on hardware, not yet fixed

- **`mqtt-bridge.sh` — no message is ever published.** `mqtt_publish_raw()` publishes with `curl --upload-file`, but curl 8.1.2 on this device sends `CONNECT` followed by `SUBSCRIBE`, never `PUBLISH` — confirmed against an instrumented broker, with both a stdin pipe and a real file, with and without credentials. The bridge's `rc=28` timeouts are this, not a broker or credential problem. Fixing it means replacing the publish mechanism, not tuning the config.
- `conf-import.cgi` and `configeditor.cgi` also call `tr`; they source `func.cgi` so the shim covers them, but their code paths have not been exercised on hardware.

### Tooling notes
- `tools/deploy-full.sh` — three defects hit during a live deploy: it overwrites binaries without stopping the daemons using them (`ETXTBSY`, which killed lighttpd mid-deploy), its `health.cgi` probe sends no credentials so it always reads the 401 body as a failure, and piping the script into `tail` masks its exit code. A caller that checks `$?` on the pipeline sees `0` for a failed deploy.
- Camera-side backups pulled by that script (`backup-<ip>-<timestamp>/`) are now git-ignored.

---

## [1.3.0] — 2026-06-25

### Added
- **First-boot wizard** (`wizard.cgi`) — guided 3- or 4-step setup on first insert of a fresh SD card: profile selection, security (password + HTTPS), MQTT (frigate_ha profile only), and summary with one-click apply.
- **MQTT step in wizard** — host, port, user, password fields; skipped automatically when profile ≠ `frigate_ha`; dynamic step bar adjusts dot count accordingly.
- **WiFi reconfiguration** (Network tab) — reads current SSID from `wpa_supplicant.conf`, form to update SSID + PSK, live `wpa_cli reconfigure` trigger; warns about connection interruption.
- **Wizard reset** (System tab) — button to delete `.wizard_done` and re-run the setup wizard; confirmation required.
- **Config export** (`conf-export.cgi`) — downloads `boot.conf` + `mqtt.conf` as a single versioned `.conf` file.
- **Config import** (`conf-import.cgi`) — uploads a previously exported file, validates the magic header, filters keys against an allowlist (60+ boot keys, 12 MQTT keys), writes atomically; CSRF-protected.
- **RTSP pipeline optimizations for `frigate_ha` profile** — GOP length tuning, keyframe interval alignment, reduced VBR overhead for Frigate's segment ingestion.
- **Frigate HA daemon denylist** — when `INTEGRATION_PROFILE=frigate_ha`, autorun.sh automatically excludes telegram-bot, timelapse, syslog-forward, sound-detection, ftp-server, telnet-server, and recording from autostart (3–6 MB RAM freed).
- **state.cgi profile-aware skipping** — with `frigate_ha` profile, sections for disabled daemons (telegram, timelapse, syslog, recording) are skipped to reduce per-call shell overhead (~900 calls/hour at 4 s polling).
- **MQTT health interval raised** — default `MQTT_HEALTH_INTERVAL_SECONDS` changed from 120 s to 300 s (transparent to HA, which uses LWT for availability).
- **Memory-guard interval raised** — default `MEM_GUARD_INTERVAL_SECONDS` changed from 20 s to 60 s when fewer daemons are running under `frigate_ha`.
- **CGI API reference** (`docs/api.md`) — 2 200-line reference documenting all 25+ endpoints: method, parameters, JSON response schema, and curl examples. Includes full CSRF workflow section.
- **`csrfFetch` exposed on `window.EliteUI`** — inline scripts in `settings.html` can now call `window.EliteUI.csrfFetch()` for CSRF-aware requests without duplicating the token logic.
- **Claude Code tooling** — project-local skills (`/deploy`, `/commit`, `/validate-cgi`, `/healthcheck`, `/camera-probe`, `/camera-logs`) and sub-agents (`shell-reviewer`, `security-reviewer`, `frontend-reviewer`, `code-reviewer`); PostToolUse hook auto-rebuilds `www/` on frontend edits.

### Changed
- `action.cgi` — three new commands: `wifi_get_ssid` (read-only, CSRF-exempt), `wifi_set_config`, `wizard_reset`.
- `deploy` skill — now diffs from `.claude/.last-deploy-sha` instead of `HEAD` so committed-but-undeployed files are always included.

### Fixed
- `wizard.cgi` — `applyConfig()` now checks `response.ok === true` before showing the success screen; previously any HTTP 200 was treated as success.
- `wizard.cgi` — MQTT user/password sanitized with `tr -cd` before writing to config (downstream sourcing safety).
- `wizard.cgi` — `renderSummary()` now escapes MQTT fields with `esc()` before inserting into `innerHTML`.
- `conf-import.cgi` — `set_conf()` escapes backslashes via `sed` before passing values to `awk -v` to prevent `\n`/`\t` expansion.
- `conf-import.cgi` — uses `expr` for arithmetic throughout (no `$((...))` bash-ism).
- `action.cgi` `wifi_set_config` — temp file cleaned on `mv` failure to avoid leaving stale files on FAT32.
- `action.cgi` `wifi_get_ssid` — uses `[ \t]` in awk instead of `[[:space:]]` for Busybox compatibility.

---

## [1.2.0] — 2025 — *Elite Edition*

### Added
- Full rewrite of the web dashboard as a single-page tabbed UI (Dashboard, Video, ISP, Automation, Network, System) using Bulma 1.0.2.
- 100% custom SVG iconography — no icon font CDN dependency.
- **Elite Optimization Presets** — one-click tuning for `Frigate Balanced`, `Universal H264`, and `Maximum Performance`.
- **Safety Snapshot** — save and restore "Known-Good" configuration checkpoints.
- **Privacy Shield / Stealth Mode** — one-click isolation of all outbound traffic paths.
- **CPU scaler** daemon — dynamically adjusts stream resolution/fps under load.
- **Service watchdog** — monitors RTSP and ONVIF processes; auto-restarts with backoff, alerts via MQTT.
- **RTSP deep health check** — detects GOP stalls, not just process liveness.
- **MQTT bridge** (`mqtt-bridge.sh`) — structured telemetry, motion events, system health; Home Assistant MQTT discovery.
- **Firmware update checker** — semantic version comparison against remote manifest, shown as dashboard notification.
- **SD write preflight** — checks available space and write speed before starting recording or timelapse.
- **Log-level filtering** — configurable verbosity per daemon without restarting.
- **Configuration editor** (`configeditor.cgi`) — in-browser editing of raw `.conf` files with validation.
- **Config profiles** (`config_exchange.cgi`) — save, load, and share named configuration presets.
- **CSRF protection** — per-boot token, enforced on all mutating CGI commands; read-only commands explicitly whitelisted.
- Zero-fork state polling — replaced shell `date` subprocesses with an inline ISO 8601 formatter in awk.
- Frontend source-of-truth enforced: `frontend/src/` → `www/` via `npm run build:web`; `npm run check:web` is a CI gate.

---

## [1.1.x] — Legacy

- Two-way audio (listen + PTT via HTTPS mic API).
- Timelapse studio with schedule management.
- Telegram bot daemon for motion notifications.
- Remote Syslog forwarding.
- LED granular control (front activity LED + IR LEDs).
- ONVIF support.
- Memory guard daemon (OOM prevention, configurable thresholds).
- Storage cleanup daemon (auto-prune recordings at threshold).
- FTP server controlscript.
- Email notifications (sendPictureMail).
- Night mode auto-detection daemon.

---

## [1.0.0] — Initial release

- Cloud-free MicroSD boot.
- RTSP streaming via `v4l2rtspserver`.
- lighttpd web server with CGI.
- Motion detection integration.
- Basic web UI.
