# 3.0 feature audit (2026-10-26)

Static check of every user-facing feature of the 3.0 flash build (Linux 6.6), and of features implemented twice.
**The camera was not reachable: nothing here was run on the device.** Each verdict says whether the shipped files,
the binaries they call and the paths they assume exist on the 6.6 flash system. "Card" means the files that are on
the author's SD card, which the flash image is built from (see problem 2).

## Where it stands after the fixes (3.0.1-rc1, end of 2026-10-26, still not run on a camera)

| Problem below | Now |
|---|---|
| 1. no web login | fixed: `v3/linux66-sd/web-auth` (`/etc/httpd.conf`, MD5), password step in the 3.0 wizard |
| 2. image built from the card | fixed: `v3/build-stack.sh` + `v3/build-release.sh` from git and CI only; vendor libraries come from each camera (`vendor` partition); see `install-3.0.md` |
| 3. Wi-Fi from the UI lost | fixed: `config/wpa_supplicant.conf` + `wifi-apply`; scan through `iw` / `wpa_cli` |
| 4. IR-cut never moves | coded: GPIO 593 / 592 pulse in the `setconf` shim; direction to check on the camera |
| 5. second flash writer | fixed: `flash-update66.sh` archived, `flashw -m/-b`, `flash-code.sh` refuses the 6.6 layout |
| 6. settings persistence gaps | fixed: `config/.cfg-deleted`, "Settings not saved" badge |
| 7. pages of missing features | each page works on 3.0 or is hidden with a note (section "Web UI on 3.0" below); ONVIF on HTTP, real sub-stream |

Sub-stream, recorder (fragmented MP4), sound level and motion zones: `docs/linux-port/README.md`, section on tc100_rtsp.

## Most important problems (as found in the morning)

1. **The web interface has no login on 6.6.** `httpfront` hands each connection to busybox `httpd -i -h /tmp/www`
   (`src/httpfront/httpfront.c:66`) and there is no `httpd.conf` anywhere in the initramfs or the stack, and no CGI
   asks for a password (2.x had lighttpd `mod_auth`). Anyone on the network can change settings and the password,
   read the configuration (MQTT password included) and download the bootloader dump (`dumpbootloader.cgi`).
   `state.cgi` gives the CSRF token to any caller, so CSRF does not protect either. RTSP has its own login.
2. **The flash image cannot be rebuilt from git.** `v3/linux66-sd/build-slim-stack.sh` packs a tar of the SD card,
   and the 6.6 versions of several files exist only there:
   - `controlscripts/rtsp-h26x` in git is the 2.x script (starts `v4l2rtspserver`, not shipped): the "Apply" buttons
     of the video page would stop RTSP until a reboot. The 6.6 one is `v3/linux66-sd/rtsp-h26x`.
   - `bin/setconf` in git is the vendor program; the 6.6 one is the shim `v3/linux66-sd/setconf`.
   - `controlscripts/auto-night-detection` in git is the 2.x one and never starts `scripts/auto-night-daemon.sh`
     (fixed on 2026-10-25 but with no caller in git). The 6.6 launcher was lost in merge b2a9772; a copy is in
     `git show d8a83fd:controlscripts/auto-night-detection`.
   - `controlscripts/recording` and `bin/ffmpeg-min-recorder` were removed in 8e5cf3f; `autorun-linux66.sh` still
     calls the script. `bin/tinymix`, `bin/swapon_zram` and the uClibc libraries are not in git either.
   - `scripts/sdinfo-sd.sh` and the `sed` edits listed in `v3/linux66-sd/README.md` (state.cgi, viewrecords.cgi,
     disk.cgi, settings.html) are not in git.
3. **Wi-Fi changes from the web UI or the wizard are lost.** They write `/mnt/wpa_supplicant.conf`
   (`action.cgi:12`) or `/etc/jffs2/tc100/wpa_supplicant.conf` (`wizard.cgi:24`, `action.d/network.sh:180`); the boot
   reads `/mnt/config/wpa_supplicant.conf` (`S39tc100-linux66:61`), the only one `cfg-persist` saves. `wpa_cli` and
   `iwlist` are not in the image, so the change is not applied live and the scan is empty.
4. **The IR-cut filter probably never moves.** The `setconf` shim only writes `/var/run/ircut`
   (`v3/linux66-sd/setconf:29`); nothing pulses GPIO 81/80 (592/593 on 6.6). The 6.6 pulse of d8a83fd was lost in the
   same merge. To check on the camera.
5. **A second flash writer is shipped.** `v3/flash-update66.sh` (in the stack through `cp -a v3`) runs `flashcp` on
   `kernel` without `flashw` (dry run unless `--write`). `scripts/flash-code.sh` writes from 0x160000 of mtdblock1,
   which on 6.6 is inside the Linux kernel; it refuses only because it looks for the partition name `"KERNEL"` in
   capitals (`flash-code.sh:94`), and `update.cgi` can call it.
6. **Settings persistence gaps** (`cfg-persist`): turning off a service that is on by default is not kept (restore
   extracts over the defaults, deleted files are not noticed); a save above 36,000 bytes fails with only a console
   message.
7. **Pages for features 3.0 does not have** are still shown (list below), and ONVIF advertises a sub-stream
   (`video1_unicast`, which serves the main stream) and an HTTPS snapshot URL on port 443 that does not exist.

## Features

| Feature | Verdict | Evidence / note |
|---|---|---|
| RTSP main stream (H.265 / H.264, TCP / UDP, audio) | OK | `rtsp-launch.sh`; audio always on (`RTSP_AUDIO` of `boot.conf` and the UI switch are ignored); no listening test yet |
| RTSP sub-stream | Missing | every path serves the main stream; `RTSP_SUBSTREAM=1` by default |
| Codec / bit rate | OK with the card shim, broken from git | see problem 2; resolution and fps are fixed |
| Image tuning, privacy masks, OSD, black and white | OK | done in software by `tc100_rtsp` (not sharpness) |
| Snapshot, live view | OK | `tc100_rtsp` writes `currentpic.cache.jpg` and `stream.jpg` |
| ONVIF | Degraded | sub-stream and HTTPS snapshot URL (problem 7) |
| Auto day / night | Card only | problem 2 |
| IR-cut | Probably broken | problem 4 |
| IR LED, front / red LEDs | OK | sysfs LEDs of the device tree |
| Button actions | Broken | `gpio_keys` is blacklisted, `tc100-button` not shipped; autostarted by default |
| Motion detection + MQTT event | Degraded | whole-frame luma difference in `tc100_rtsp`; started at boot even when off in the UI; snapshot and Telegram use `getimage` |
| Motion zones | Broken | applied by `libtc100fix` in the vendor server only |
| Sound detection | Broken | level came from `libtc100fix` |
| Push-to-talk, speaker, two-way audio | Broken | `ak_ao_ptt` / `ak_ao_demo` absent; no RTSP backchannel; speaker never tested on 6.6 |
| Listen in the browser | Broken | calls `audio_stream.cgi`, removed in 8e5cf3f |
| SD recording | Card only | problem 2; thumbnails need `ffmpeg-min` (not shipped) |
| View records | Degraded | list OK, no thumbnails |
| MQTT bridge + Home Assistant discovery | OK | snapshot command uses `getimage` (probably fails); entities in HA still to be confirmed |
| Telegram, update check | Broken | need curl / jq, left out of the flash image on purpose |
| NTP, time zone | OK | |
| Wi-Fi change, scan, wizard Wi-Fi step | Broken | problem 3 |
| wifi-rescue access point, `wifi.txt` | Broken | no hostapd, no AP mode in `rtl8xxxu` here; `wifi.txt` only read by 2.x `autorun.sh`; wifi-rescue autostarted by default |
| Network monitor | OK (unverified) | |
| FTP | OK on demand | autostart removed in the flash build |
| Telnet | Unclear | depends on the Buildroot busybox applets; `libnetacl.so` (local-network-only filter) not shipped |
| Syslog forward | OK (unverified) | |
| Health, diagnostics, stability | Degraded | logs in the 6 MiB RAM disk, lost at reboot |
| Config backup / export / import / editor | OK | writes `/mnt/config`, saved by `cfg-persist` |
| Password change | OK | updates `passwd`, `user.pwd`, `rtspserver.conf` |
| Firmware update page, flash install page | Broken, refused | 2.x flash layout; must be hidden on 6.6 |
| Settings persistence | Degraded | problem 6 |

## Features implemented twice

| Group | Used on the 3.0 flash build | Duplicates / dead on 3.0 | Suggestion |
|---|---|---|---|
| Video / RTSP | `tc100_rtsp` via `rtsp-launch.sh` | inline copy of the launcher in `autorun-linux66.sh` (fixed H.265, unset `$RTSP_CODEC`); `tc100_streamer` + `thingino-rtsp-server` fallback (not shipped); 2.x: `v4l2rtspserver`, `src/tc100fix` lite server | keep only `rtsp-launch.sh`; drop the fallback branches; nothing restarts `tc100_rtsp` if it dies (memory-guard watches another pid file) |
| Day / night | `auto-night-daemon.sh` → `nightmode.sh` → `night-mode` | `ir-cut`, `ir-led`, `black-white` are thin Services-page wrappers | restore the 6.6 launcher; no real duplicate |
| Network watchdogs | — | `network-monitor` and `scripts/net-guard.sh` both reboot on network loss; `wifi-client.sh`, `wifi-txt.sh` 2.x only | keep `network-monitor` |
| Service restarters | busybox hardware watchdog, `health-snapshot`, `service-watchdog.sh` | `memory-guard` restarter overlaps `service-watchdog.sh`; `health-probe.sh` | one restarter, covering `tc100_rtsp` |
| SD card info | — (nothing writes `/tmp/sd-card` on 6.6) | `sd-card.sh`, `sd-health.sh`, `rec-storage.sh`, `storage-cleanup.sh` 2.x only; `sdinfo-sd.sh` card only | wire `sdinfo-sd.sh` from `action.d/storage.sh` |
| Flash install / update | `build-slim-stack.sh`, `flashw`, `flashmode-prep.sh`, `cfg-persist` | 6.6 drafts `v3/build-flash-rootfs66.sh`, `v3/flash-update66.sh`; 2.x `flash-install.sh`, `flash-code.sh`, `flash-usr.sh`, `flashboot.sh`, `fw-update.sh`, `usr-update.sh`, `update.cgi`, `flashinstall.cgi` | archive the drafts; keep 2.x files out of the flash image |
| Config export / import | `configbackup.cgi`, `config_exchange.cgi`, `conf-export/import.cgi`, LKG profiles | four mechanisms | keep `config_exchange.cgi` (+ raw editor) |
| Web server | `httpfront` + busybox `httpd` | 2.x `lighttpd`, `web-server` script, 4 `lighttpd*.dist`, `www/http-redirect/` shipped but unused | keep out of the flash image; hide `web-server` on the Services page |
| System info CGIs | `state.cgi` (hub), `dash.cgi`, `stability.cgi` | `sysusageinfo.cgi`, `health.cgi`, `devinfo.cgi`, `diagnostics.html` repeat it | merge into `state.cgi` and the dashboard |
| `setconf` | shim `v3/linux66-sd/setconf` | vendor `bin/setconf` (2.x) | install the shim from the build script |
| BusyBox | initramfs busybox | `bin/busybox` (uClibc, ~500 KB xz in the stack) used for `timeout`, `ftpd`, `tcpsvd`, `ntpd`… | add those applets to `v3/buildroot/board/tc100/busybox.fragment`, then drop it |

### Flash image size

The squashfs is 3.2 MiB in a 3.7 MiB partition. Shipped but unused on 3.0 (xz sizes, measured on the repo files):
`bin/busybox` ~500 KB (once the applets are in the initramfs), `bin/jq` ~233 KB, `bin/wpa_supplicant` ~172 KB,
`lib/libtc100fix.so` ~36 KB, 2.x-only scripts, CGIs and build files ~70 KB; `tc100test/httpfront` is not stripped
(~150 KB to gain). About 1.1 MiB in all. `ffmpeg-min-recorder` (~690 KB) is the 3.0 recorder: keep it.

### Elsewhere in the repository (not in the flash image)

`contrib/openipc_sd_kit/` (Linux 4.4 kit, superseded by the CI artifacts), `thingino_port/`, `src/tc100_streamer`
(identical to `bin/tc100_streamer`), `src/venctest`, `tests/venctrace`: bring-up material, candidates for an
`_archive_*` folder (renamed, not deleted).

## Web UI on 3.0 (2026-10-26, second pass, static: not yet run on the camera)

Code shared with 2.x takes a 6.6 path when `/tmp/linux66` exists; 2.x behaviour is unchanged.

| Feature | 3.0 behaviour now |
|---|---|
| RTSP shim, restarter | `controlscripts/rtsp-h26x` runs `v3/linux66-sd/rtsp-h26x`; `scripts/service-watchdog.sh` restarts `tc100_rtsp` (pid file `/var/run/v4l2rtspserver.pid`), started at boot by autorun step 8; memory-guard leaves services with their own watchdog alone |
| IR-cut | `setconf -k e` pulses GPIO 593 (day) / 592 (night) 150 ms then low; `IRCUT_DAY_GPIO`, `IRCUT_NIGHT_GPIO`, `IRCUT_PULSE_MS` in boot.conf if the filter moves the wrong way; synced once at boot |
| Auto day / night | the launcher starts `scripts/auto-night-daemon.sh`; thresholds = mean luminance 0-255 in `config/daynight.conf` (Settings, Day/night); started at boot unless switched to manual (daynight=3) |
| Snapshots | `take_snapshot` (common_functions.sh) and `currentpic.cgi` ask tc100_rtsp for a new `/tmp/currentpic.cache.jpg` (`/tmp/snapshot_request`): Telegram, MQTT snapshot, motion, self-tests |
| SD card panel | `sdinfo-sd.sh` from `action.d/storage.sh` and every minute from `web-guard.sh`; mount / eject / resume through `scripts/rec-storage.sh` (16 KiB RAM placeholder at `/mnt/sd` without a card) |
| Speaker, push-to-talk | `scripts/speaker-play.sh`: `aplay -D plughw:0,0` (the codec plays stereo only), volume on "Headphone Playback Volume"; RTSP keeps running. The amplifier (GPIO 14) is driven by the codec driver from the device tree (`speak-gpios-en = <1>`, active high); only when the pin is free does the script drive it (`SPEAKER_AMP_ACTIVE`, default 0 = active low as on 2.x) |
| Listen | `audio_stream.cgi` (WAV from `arecord`, 60 s); ALSA takes one capture reader and tc100_rtsp keeps the microphone open for its audio track, so it answers 503 ("listen in VLC / Frigate") while the RTSP audio is on |
| Telegram, update check | musl curl and jq of the image; update-check uses `CURL_CA_BUNDLE`; run at boot when `UPDATE_CHECK=1` |
| Wi-Fi rescue | hostapd (nl80211) + udhcpd on wlan0 itself (one interface on rtl8xxxu): the station stops while the access point is up (`WIFI_RESCUE_MANUAL_MIN`), then retries; saving Wi-Fi settings ends the access point; web page at http://10.42.0.1 |
| Button | `button-watch.sh` polls GPIO 522 once a second (no fork), acts on release only and only after the pin was seen released (a stuck pin never reboots) |
| ONVIF | snapshot URL on http port 80; main 1920x1080, sub-stream 640x360 |
| Services page | `web-server` = httpfront (status, restart, `web-guard.sh` restarts it); `cpu-scaler` hidden (fixed resolution and frame rate) |
| Settings persistence | `cfg-persist` stores the list of removed shipped defaults (`config/.cfg-deleted`) and removes them again after a restore; unchanged defaults are no longer stored; a failed save (too big, write error) shows "Settings not saved" in the top bar (`/tmp/cfg-persist.status`) |
| Logs, self-tests | the video log is `/tmp/logs/tc100_rtsp.log`; RTSP checks use `nc`; snapshot checks use the tc100_rtsp picture |
| Network-loss reboots | net-guard (default, every minute from web-guard) steps aside while network-monitor runs; neither acts while the rescue access point is up |

Hidden on 3.0 (class `hide-l66`, the platform flag comes from the status line): RTSP server choice and two-way audio
(one server, no backchannel), sharpness / mains frequency / exposure cap (not applied by tc100_rtsp), OSD colour,
background, alpha and rotation (tc100_rtsp draws the clock text only), AWB thresholds (the daemon uses luminance), card
formatting (format on a computer), cpu-scaler. Notes (`show-l66`) say that resolution, frame rate, audio codec and rate
are fixed.

Still duplicated: the system information CGIs (`sysusageinfo.cgi`, `health.cgi`, `devinfo.cgi` next to `state.cgi`) are
used by different pages; merging them means changing the pages' data contracts, left for later.
