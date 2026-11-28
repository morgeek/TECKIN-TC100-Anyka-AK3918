Free firmware for the **TECKIN TC100** camera: Linux 6.6, RTSP H.264 / H.265 for Frigate or any NVR, MQTT / Home
Assistant, local web interface, no cloud. Read **"Is it safe?"** in the
[README](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918#is-it-safe) first.

## What is new in 3.2.0-rc4 (test build, branch upgrade-3.2: SD gate then UP32-FLASH)
Everything of 3.2.0-rc3, plus:
- **SD trial video (`SD_FLASH_VENDOR=1`):** loads the camera's own `isp.conf` read-only from the flash `vendor` partition on SD trial boots of 3.0.x cameras.
- **Stable Wi-Fi link monitoring:** fixes `wifi-rescue` gateway detection on Linux 6.6 (`[wifi-rescue-gw]`) so the camera does not open a spurious rescue AP every 25 minutes.
- **Support bundle on BusyBox 1.37:** uses `tar cf - | gzip -9` instead of `tar -czf`.
- **Plug-and-play SD package (`UP32-ONBOARD`):** ships a `wifi.txt` template (silently skipped while empty) and `ESSAI.txt.example`, falls back read-only to flash Wi-Fi slots (`SD_FLASH_WIFI=1`) in SD trial mode, persists the SSH host key on the SD card, and updates the SD readmes (`tc100-3/ADRESSE.txt`, `pass` in SD trial mode, safe eject).

## What is new in 3.2.0-rc3 (test build, branch upgrade-3.2: try it from the SD card only)
Everything of 3.0.2-rc8, plus the major upgrade:
- **Up-to-date kernel:** Linux 6.6.163 (three years of stable fixes).
- **Up-to-date base system:** BusyBox, Dropbear (ssh), wpa_supplicant / hostapd (Wi-Fi), curl, and the TLS library of
  the WebRTC live view moved to maintained versions.
- **Signed updates:** a package can carry a signature that the camera checks before writing anything; unsigned
  packages are still accepted with a warning in this build.
- **Less root:** the ONVIF, WebRTC, mDNS and log-forwarding services run without administrator rights
  (`PRIVDROP=0` in `boot.conf` turns it off).
- **Fix:** an ONVIF subscription with a very long duration got 5 s instead of one hour.
- **rc2 and rc3 (two audits of the branch):** `/tmp` is reserved to root while those services run without
  administrator rights, and a settings backup with an empty `boot.conf` no longer empties the camera's.
- **To test (SD card, nothing written to the flash):** `UP32-KERNEL`, `UP32-BASE`, `UP32-SIGN`, `UP32-PRIVDROP`,
  `UP32-FUZZ` in `docs/linux-port/test-queue.md` of the branch.

## What is new in 3.0.2-rc8 (test build, branch main)
Everything of 3.0.2-rc7, plus:
- **Night bit rate capped at 900 kbit/s by default:** in a dark room the sensor noise used to fill the whole 1600
  kbit/s all night. The night picture is a little softer (tried on one camera for a night and accepted).
  `RTSP_NIGHT_KBPS=0` in `rtsp.env` removes the ceiling; another value sets another one.
- **To test:** `NIGHT-KBPS-DEFAULT` (one night on a camera without `RTSP_NIGHT_KBPS` in `rtsp.env`), the rest of
  `SECRET-MODES` (ONVIF, settings import), then the acceptance bench again.

## What is new in 3.0.2-rc7 (test build, branch main)
Everything of 3.0.2-rc6, plus:
- **Password and key files protected:** the files of the settings folder that hold a password, a token or the Wi-Fi
  key (`user.pwd`, `rtspserver.conf`, `mqtt.conf`, `wpa_supplicant.conf`, `telegram.conf`, `notify.conf`) are set to
  mode 600 at every boot, after a settings restore and after a settings import. Nothing else changes.
- **To test:** `SECRET-MODES` (after the update and a reboot: `ls -l` of those files shows `-rw-------`; web login,
  ONVIF, RTSP and MQTT work as before), then the acceptance bench (`RECETTE-BENCH`) and the readiness plan
  (`docs/linux-port/readiness-3.0.2.md`).

## What is new in 3.0.2-rc6 (test build, branch main)
Everything of 3.0.2-rc5, plus:
- **`MQTT_ADMIN_CMDS`** in `mqtt.conf` (1 by default, nothing changes): 0 refuses telnet, ftp and reboot sent over MQTT.
- **Cleanup:** the test tools made for problems now fixed are gone (self-test and hardware-report hooks of the
  SD card, benches, capture tools). Nothing changes for normal use.
- **To test:** `MQTT-ADMIN`, `TOOLS-CLEANUP-1125` (a normal boot, video and snapshots as before), plus the rc5 entries
  (`SUBSTREAM-LOOP`, `NIGHT-CEIL-AUTO`) and the readiness plan (`docs/linux-port/readiness-3.0.2.md`).

## What is new in 3.0.2-rc5 (test build, branch main)
Everything of 3.0.2-rc4, plus two measurements and one option, nothing that changes the default behaviour:
- **Why the sub-stream client keeps reconnecting:** each RTSP client that leaves now writes one line with the reason in
  `/tmp/logs/tc100_rtsp.log` (look at it after a night, together with the Frigate / go2rtc logs).
- **The night bit rate measured by the camera:** `nightceil.csv` (on the SD card when there is one) records gain,
  light, image settings and bit rate at each day/night switch and every 10 minutes. Leave the cameras alone for one
  night and send the file.
- **Night setting, off:** `RTSP_NIGHT_VBR_QP_ADD` / `RTSP_NIGHT_KBPS` in `rtsp.env`, to try only if the file shows the
  night ceiling is noise.
- **To test:** `SUBSTREAM-LOOP`, `NIGHT-CEIL-AUTO`, plus the rc4 entries.

## What is new in 3.0.2-rc4 (test build, branch main)
Everything of 3.0.2-rc3, plus:
- **Lighter Wi-Fi quality job:** 8 processes a minute instead of 13, same Wi-Fi page and MQTT values.
- **Safer build chain:** everything the build downloads is checked, and the images are reproducible. The base system
  (busybox, dropbear, wpa_supplicant, curl, WebRTC gateway) is a fresh build of the same versions: check Wi-Fi, ssh,
  the web live view, MQTT and a web update once (test-queue CI-PIN).
- **To test:** `WIFIQ-FORKS`, `CI-PIN` (camera smoke test), plus the rc3 entries.

## What is new in 3.0.2-rc3 (test build, branch main)
Everything of 3.0.2-rc2, plus the fixes of the audit of the C optimisation code (24/11). Updating keeps the settings.
- **Security:** after a password change ONVIF no longer accepts the old password (it did until a restart); a
  *retained* MQTT command is no longer executed at every connection (a retained reboot made a reboot loop).
- **Fixes:** a sound starts a recording again with `REC_WHEN=motion`; two-way audio off is seen by ONVIF; the hue you
  set survives the day/night switches; encoder motion detection no longer sticks "on" all night; the reset button keeps
  its timing during a day/night switch, and a stuck night script no longer blocks it.
- **Lighter:** privacy mode and a few loops cost less CPU; read-only web queries no longer fill the audit log; about
  4 KB of dead video code removed (default behaviour unchanged).
- **To test:** the test-queue entries `B1-ONVIF`, `R3-MQTT`, `B2B3-CONF`, `B4-HUE`, `R1-MDENC`, `R2-BUTTON`,
  `W1-PRIVFILL`, `W3-ZERO`, `T1B5-PARITY`, `W5-AUDIT`, `CLEANUP-1124`, `SMALL-A-1124`, `SMALL-B-1124`, plus those of
  rc2 and rc1 still open.

## What is new in 3.0.2-rc2 (test build, branch main)
Everything of 3.0.2-rc1, plus the fixes from the 2-day readings of 3.0.1 and new measurements. Updating keeps the settings.
- **White balance at night (`AWB-NIGHT`):** the AWB-05 loop is paused at night and the ISP's automatic white balance is back (the .24 sat at 1618 kbit/s all night after an evening switch); the day gains return at dawn; a night or implausible `awb.state` is never loaded (`RTSP_AWB_NIGHT=0` to revert).
- **Day / night flip-flop (`DN-FLAP`):** in a dimly lit room the camera no longer clacks between day and night all
  evening: after a quick round trip the next switch to day waits 15, 30, 60, then 120 min (5 min of real daylight
  resets it). The switch to night is never delayed. `DN_FLAP_BACKOFF=0` in `daynight.conf` restores 3.0.1.
- **Measurements for long runs:** `memory.csv` / `memory-hourly.csv` next to `stability.csv` (`MEMWATCH`, to settle
  the slow memory drop), and failure totals since boot at the end of the video `STAT` line (`FAILCOUNT`).
- **Hardening (`HARDEN`):** stack canaries in the free programs and a read-only GOT in the musl ones (+3.8 KB).
- **To test:** the test-queue entries `AWB-NIGHT`, `DN-FLAP`, `MEMWATCH`, `FAILCOUNT`, `HARDEN`, plus the rc1 ones
  still open (`AUDIT-1116-*`, USB, VENCIRQ, RECOVERY).

## What is new in 3.0.2-rc1 (test build, branch main)
Pre-release test build gathering everything since 3.0.1 (`AUDIT-1116-*`, `POLISH-01`, `AWB-05-SAVED`, USB/VENC kernel fixes, and initramfs rescue):
- **Initramfs rescue mode (`[recovery]`):** when `stack` is damaged or offers no access after 5 min, joins saved Wi-Fi and opens a private-LAN telnet rescue shell (`/etc/tc100/rescue help`, `INITRD_RESCUE=0` disables; needs the new initramfs).
- **Kernel fixes:** USB host unlink of active URB without waiting for an IRQ + ep0/toggle fixes (patch 0024); `ak39_venc` masks late encoder IRQs when disarmed (`irq_unlazy`, patch 0025); `venc` IRQ balance & `mmap` bounds, audio start race, I2C poll timeout, and OSD limits (`[audit-1116]`).
- **Security & reliability (`[audit-1116]`):** closed web login lockout bypass in `httpfront`, ONVIF anti-replay, atomic `rwconf`, SSH (`dropbear`) restricted to private LANs, monotonic timeouts & capture-stall exit in `tc100_rtsp`, safer flash update/backup checks (`imgcheck.sh`, no reboot during flash writes).
- **White balance (`AWB-05-SAVED`):** starts ISP manual WB immediately from `/mnt/config/awb.state` when recent (`<= 6 h`) and in the same day/night mode, skipping the 10 s auto warmup (`RTSP_AWB_STATE=0` or `RTSP_AWB_MANUAL=0` to revert).
- **Polish (`POLISH-01`):** `cfg-persist` single `md5sum`, `AWB_RESTART_IGNORE=30` to prevent false day switches on video restart, `fe_hw_init` after `VIDIOC_REQBUFS`, native `fullconfig` and `isp_tune` in `httpfront`, faster `step_12b` boot spacing.
- **Bench:** `qpbench` (`[t1-qp]`, bench tool only, not active in firmware).

## What is new in 3.0.1 (Final Release)
3.0.1 gathers the test builds 3.0.1-rc37 to rc44 (details below) and the work of 14-15 November. Updating from 3.0.0
keeps the settings. In short:
- **Picture colour:** the ISP's white balance runs in manual mode and our grey-world loop steers its gains after the
  first 10 s (AWB-05): the slow tint cycle seen on both test cameras is gone (picture colour spread 0.05-0.6 instead of
  10-13 on a steady scene), and a still scene costs far fewer bits (night, 10 fps: 155 KB per 5 s instead of 400 KB).
  `RTSP_AWB_MANUAL=0` in `/mnt/config/rtsp.env` returns to the ISP's automatic mode, with its colour-temperature
  hysteresis raised (`RTSP_ISP_AWB_STABLE`, default 60).
- **Free encoder (ENC-02):** the budget per picture and the GOP follow the real capture rate (10 fps at night: the
  bit rate can now use the whole ceiling when the scene needs it, keyframe every 2.5 s); a picture larger than the
  stream buffer no longer fails again and again; keyframes are kept under 0.4 s of the bit rate; in smart mode the
  keyframe of a still scene is coded 4 QP below the P pictures (`RTSP_FE_SMART_QP`); after repeated failures the
  encoder is reopened, then the video server stops for the service watchdog to start it again. Switches:
  `RTSP_FE_FPS=0`, `RTSP_FE_SUBBUF=1` (128 KB sub-stream buffer, not the default yet).
- **VBR really variable:** quality QP `RTSP_VBR_QP` (default 33) instead of 27, which kept VBR at the ceiling.
- **Wi-Fi:** TX aggregation (A-MPDU) off by default (`WIFI_AMPDU_TX=0`): 0 video stalls on the camera that had them;
  USB host fix (kernel patch 0022).
- **IR-cut:** the filter position is asserted again every 30 min (`IRCUT_REASSERT_MIN`): a filter left out of the day
  position gave a magenta picture.
- **Settings:** a key removed from daynight.conf no longer keeps its last value until a restart; saving the settings
  to the flash takes half the time (no more 10 s of full CPU); the boot guard saves its count in the background;
  `/tmp/boot-trace.txt` logs the boot steps.
- **Web interface:** reorganized menus, native answers for the polled pages (`httpfront`), faster CGIs and caches.

Known limits: the 128 KB sub-stream buffer and the echo cancellation (`RTSP_AUDIO_AEC=1`) stay off until tested;
after a restart of the video server the day / night switch may go to day for about 20 s in the dark.

## What is new in 3.0.1-rc44 (test build, branch main)
Everything in 3.0.1-rc43 below, plus:
- **Web UI organization & responsiveness:** navigation and Settings sidebar organized into 4 logical poles (`Watch`, `Camera`,
  `Automation`, `Tools` with `Configuration`/`Diagnostics`/`Maintenance` subsections) and `Memory` tab linked; background
  polling stopped on page leave / hidden tab (`multiview.html`, `AbortController` on camera/day-night polls); smooth
  click-to-dismiss toast; 15 s `fullconfig` cache on Settings revisit (invalidated on save), `/` and `Ctrl/Cmd+K` search
  shortcut, and auto-opening matching advanced `<details>` sections during search.
- **Native `httpfront` polls (`NATIVE-02`):** `tc100-httpfront` answers `daynight`, `hw_state`, and fresh `health.cgi`
  snapshot cache hits directly in C without spawning CGI shells.
- **VBR quality QP (`RTSP_VBR_QP`, default `33`):** configurable quality floor in `rc.h` / `tc100_rtsp` so VBR drops
  bitrate on calm scenes instead of staying pinned at the ceiling (`RTSP_VBR_QP=0` reverts to `qmin + 2`; parsed without
  `atoi` for uClibc compatibility).
- **Boot & CGI speedups:** symlink `tc100_rtsp` instead of copying to RAM in flash mode, start RTSP before `/tmp/www`
  symlinks, skip redundant `rwconf` credential writes at boot, batch-load `state.cgi` configs in a single `awk` pass
  (`load_conf_files`), and avoid reverse DNS lookups (`netstat -n`) + repeated `/proc/net/tcp` reads in `network.cgi`.
- **Wi-Fi & Kernel (patches 0022 / 0023):** Anyka OTG host no longer reads the URB after giveback; `rtl8xxxu` runtime
  `ampdu_tx` switch and BlockAck counters; `WIFI_AMPDU_TX=0` default (0 stalls on `WIFI-STALL-01`).
- **IR-cut & AWB:** periodic IR-cut position re-assertion (`IRCUT_REASSERT_MIN`) and closed-loop AWB tint oscillation
  fixes (symmetric rounding, hysteresis, 4-sample hold/average).
- **MQTT, DSP & Boot trace:** skip idle mic DSP, reduce MQTT/presence forks, fix hrtimer venc reset pulse, fix MQTT
  privacy dispatch, restore `isp_power_hz`, add recording/flip/mirror Home Assistant switches, and fork-free
  `/tmp/boot-trace.txt` step logging.

## What is new in 3.0.1-rc43 (test build, branch main)
Everything in 3.0.1-rc42 below, plus:
- **Web UI responsiveness:** pure-shell fast path for `json_escape` (`func.cgi`), batched configuration loading and
  fork-free response caching in `state.cgi`, `action.cgi`, `disk.cgi` and `devinfo.cgi`, `config-transaction.sh` tab-check
  fast path, and in-memory HTML fragment caching across tabs (`20-pages.js`).
- **Flash space:** build-time HTML comment and indentation stripping outside `<script>`/`<style>`/`<pre>`/`<textarea>`
  (`src/webui/minify.mjs`, ~32.8 KB raw saved) and install-only files (`anyka-wifi.awk`, `known-stock.txt`) excluded from
  `stack.squashfs`.
- **mDNS (`tc100-mdnsd`):** unified RFC 6762 §6.7 verbatim legacy question echo (`mdns_reply_head`) and per-source-IP +
  global answer rate limiter (`struct mdns_ip_rl`).
- **Wi-Fi runtime trials:** `scripts/wifi-try.sh` (`ampdu_rx=0|1`, `tx_atten=0..30`) with automatic gateway-ping watchdog
  and safety-window revert.
- **Boot milestones, CI & tests:** `web_ready` startup milestone, per-boot reset of `/tmp/boot-milestones.txt` with
  bounded persistent log, dusk/dawn IR-lift hysteresis regression tests (`tests/test_supervisord.py`), GitLab firmware
  mirror fallback, and Docker worktree cleanup in `local-ci.sh`.
- **Background load:** fewer forks in the periodic jobs (`wifi-quality.sh` uptime-based clock, no `wc`), the MQTT
  bridge and the CGIs, fewer repeated reads.
- **3D noise reduction always on by default (`NR3D=1`):** measured with the rc41 memory layout on both test cameras,
  0 overflow by day at 1080p / 720p, 25 / 20 fps, and 0 overflow for 18-21 h day and night. `NR3D=auto` (night / low
  light only, at 15 fps or less) is still accepted; `NR3D=0` turns it off. A camera whose boot.conf already holds an
  `NR3D=` line keeps it.
- **Day / night, stock method:** the daylight white-balance count `AWB_DAY_CNT` is 200 000 by default (was 50 000):
  a dark room still showed 60-66 k and stayed in colour, a dim lamp shows 390 k and more. A value already in
  daynight.conf is kept.
- **Wi-Fi stall diagnostics (branch `wifi-counters` merged):** kernel patches 0020 / 0021 add read-only (`0444`)
  counters, rtl8xxxu TX/RX URBs (`/sys/module/rtl8xxxu/parameters/tx_urb_free`, `tx_urb_min`, `txq_stops`, `txq_wakes`,
  `tx_urb_err`, `tx_last_ms`, `rx_urb_lost`, `rx_urb_alive`) and Anyka HCD NAKs (`/sys/module/otg_hs/parameters/bulk_*`).
  No behaviour change. `scripts/wifi-stall-watch.sh [seconds]` prints one line per second for the WIFI-STALL-01 test.

## What is new in 3.0.1-rc42 (test build, branch main)
Everything in 3.0.1-rc41 below, plus:
- **RTSP access:** at most 3 connections per address (`RTSP_PERIP`), random Digest nonce and `uri` check (a parent
  path is accepted, as VLC sends it), lockout after repeated failed logins (authenticated connections are never locked
  out), the UDP two-way audio only accepted from the client's own port.
- **mDNS:** compression pointers followed in question names, rate limit, 1500-byte answers, legacy DNS-SD answers.
- **3D noise reduction:** `NR3D=auto` is the default (reference allocated at boot, switched on at night / low light),
  and only when the capture rate in use is 15 fps or less; the reason is logged. Measured on 2026-11-13: no overflow by
  day at 1080p 25 fps on both test cameras, so this rule may change after the night measurements.
- **RTSP over UDP:** non-blocking sends, keyframe requests caused by UDP backpressure rate-limited, no frame queued for
  a client still waiting for a keyframe.
- **WebRTC (WHEP):** started on demand and stopped when idle; starts serialised with a lock (a stale lock is taken over).
- **Day / night log kept across a planned reboot:** the last 200 lines are copied to `/mnt/config/log/daynight-last.log`
  (saved to the flash with the settings) before an update, web UI, MQTT or button reboot.
- **Wi-Fi:** `rtl8xxxu.tx_atten` (TX power attenuation at run time) and `ampdu_rx` parameters; the kernel is back to
  `HZ_PERIODIC` (high-resolution timers stay in a test kernel).
- **Audio:** echo cancellation prefill (`RTSP_AUDIO_AEC=1`, still off by default).

## What is new in 3.0.1-rc41 (test build, branch main)
Everything in 3.0.1-rc40 below, plus:
- **3D-NR 1080p memory layout (patch 0017):** `ak39_vi` allocates the 2025 KiB 3D-NR UV reference plane from the
  2688 KiB unused tail of the encoder CMA area (`venc@81800000`), freeing ~2 MiB in the default CMA for 1080p capture
  buffers (`NR3D=0` remains the default; `dmesg` shows `(UV in venc pool)` when active).
- **Test queue updates:** `HOOK-01` (U-Boot built-in env) and `KRN-01` (`ak_isp.awb_live` `0644`) verified `passed` on
  `.11` rc40.

## What is new in 3.0.1-rc40 (test build, branch main)
Everything in 3.0.1-rc39 below, plus:
- **Free encoder, VBR and smart mode:** the H.264 / H.265 encoder now follows `vbr` (a ceiling, quality first) and
  `smart` in rtspserver.conf; smart mode lengthens the GOP on a still scene (clients that lose packets keep the base
  GOP, time cap, no long-GOP burst, QP floor clamped). A camera with `vbr=1` now really encodes in VBR.
- **3D noise reduction:** `NR3D` in boot.conf / `ak39_vi.nr3d` writable at run time, reference picture at the crop
  size, overflow counter; freed when idle.
- **Two-way audio echo cancellation:** behind `RTSP_AUDIO_AEC=1` (off by default).

## What is new in 3.0.1-rc39 (test build, branch main)
Everything in 3.0.1-rc38 below (DEV is now merged: from here on the work goes on `main`), plus the reviews of
2026-11-12:
- **Install from the card:** the per-partition backup is skipped only on a first install (a reinstall over 3.0 on
  the flash kept no copy of its 3.0 partitions).
- **First-install hook:** the identity file of the stock firmware is required, the card copy of the flash is read back
  before use, the exact envtool error is shown.
- **Web update:** no upload, discard or install while an install runs or after a failed one; a stricter package
  check; true failure messages.
- **Web login (httpfront):** failed logins counted from the headers only, in any case; a new password forgets the
  remembered login at once.
- **ONVIF:** wrong logins counted per address (one LAN host can no longer lock the NVR out), full answers on slow
  links, connection and discovery limits.
- **WebRTC (WHEP):** its UDP port follows the LAN-only rule; consent only from authenticated STUN checks.
- **Video:** with the sender thread on, a frame lost for lack of memory is applied in order (no corrupt picture until
  the next keyframe); white balance statistics source switchable at run time (`awb_live`).

## What is new in 3.0.1-rc38 (test build, branch DEV)
Everything in 3.0.1-rc37 below, plus:
- **IR-cut filter:** the default pulses are now day = GPIO 592, night = GPIO 593. With the old default the filter could
  stay in front of the sensor at night (a dark, grainy picture under IR). A camera wired the other way keeps working
  with `IRCUT_DAY_GPIO=593` and `IRCUT_NIGHT_GPIO=592` in `boot.conf`, which still win.
- **Background load:** the once-a-minute Wi-Fi quality and roaming jobs start about 13 fewer processes a minute
  (same output).

## What is new in 3.0.1-rc37 (test build, branch DEV)
- **Day / night:** every copy of the day / night settings checked against one catalog; a save of the Day / night page
  no longer drops the stock method's white balance counts, its lock and the IR LED rest; those keys and
  `MIN_SWITCH` are exported and checked on import. Default source unchanged (`luma`).
- **Image:** new **Noise reduction** slider (Image page, MQTT / Home Assistant `isp_denoise`, -50..50, 0 = the sensor
  tuning). Brightness, contrast, saturation and hue are bounded to -50..50 even in a hand-edited file. The start-up log
  shows the noise reduction of each gain level.
- **Security:** a GET on `action.cgi` is answered only for read commands (any other gets `405`; a link or image on
  another site could reboot the camera); form values are never expanded as file names nor executed; an empty CSRF
  token is refused; the configuration import can no longer write shell code into `notify.conf`.
- **Two-way audio:** a stopping server waits for its player (the speaker was found busy after a restart), a busy
  speaker no longer costs 2 s of sound, the first talker keeps the speaker, a stop signal never plays without the lock.
- **Defaults when a line is missing:** no `mdenabled` line = motion detection off (as the web page shows);
  no `REC_KEEP_EVENTS` line = recordings with an event are kept (as the default file).

## What is new in 3.0.0 (Final Release)
- **100% free hardware video encoder & userspace**:
  - Direct hardware encoding (`freeenc.h`) for H.265 and H.264 up to 1080p and 720p, zero proprietary vendor `.so` libraries loaded, linked, or flashed.
  - Native musl-linked services: `tc100_rtsp`, `tc100-mqttd`, `tc100-supervisord`, `tc100-onvifd`, `tc100-mdnsd`, `tc100-logfwd`.
- **Rock-solid streaming & performance**:
  - Dedicated RTSP sender thread (`RTSP_SENDER_THREAD=1`): clients no longer consume sensor capture loop cycles.
  - Prioritized CPU scheduling: background maintenance and monitoring jobs run under `nice -n 10`.
  - Dynamic 720p night mode option (`NIGHT_720P`) for lighter continuous memory footprint and sharper night frames.
  - Anti-flapping day/night transitions (`MIN_SWITCH=180s`).
- **Storage, Network & Setup**:
  - In-camera FAT32 microSD format action directly from the web interface.
  - Setup wizard with Wi-Fi country regulatory domain selection.
  - Fast SD-to-flash install: automatic verification of full 8 MiB stock backup.
- Runs from the camera's flash with **no SD card**; the card only holds recordings and saved logs.
- **The speaker works** (its amplifier was driven the wrong way round), and the camera's sounds no longer clip.
- **Night picture** from the sensor tuning's own night settings, **10 fps in low light** by day, anti-flicker
  (50 / 60 Hz, the camera default shown), the IR-cut pulsed as the stock firmware does.
- **Wi-Fi recovers by itself** when the chip fails to start after a reboot; Wi-Fi regulatory domain: pick your country in Settings → Network ("Country (Wi-Fi rules)", `WIFI_COUNTRY` in `boot.conf`), applied at once without reconnecting; settings changed just before a reboot are kept; the video server restarts by itself if it stops.
- **Native mDNS local discovery** (`tc100-mdnsd`) enabled out of the box (`<hostname>.local`).
- **Fluid live video preview** powered by native MediaSource fMP4 across all dashboard and settings views.
- Plain HTTP on port 80 only (external TLS delegated cleanly to a reverse proxy).
- About 21 MB of free memory (was 10 MB in the first 3.0 builds), the clock and privacy masks drawn by the image
  processor, a 640x360 sub-stream from its own scaler.
- Bit rate mode (constant / variable), the stock firmware's day / night method as an option, IR LED protection.
- **Hardware test page** (Tools → Hardware test): the camera drawn from the front and the back, each part (lens, LEDs,
  IR-cut, microphone, speaker, microSD card, reset button) tested in one click.
- **Chime, alert and siren buttons** on the dashboard, next to Listen / Talk.
- **Full backup of the camera** (Backup page): every changed setting, secrets and ssh keys included, in one `.tar.gz`,
  and its restore.
- **Picture on events over MQTT** (`MQTT_SNAPSHOT_ON_EVENT=1` in `mqtt.conf`, off by default): a fresh JPEG goes to the
  broker on motion, sound or tamper (Home Assistant camera entity).
- **Prometheus metrics** at `http://<camera>/metrics` (video server rates, clients, microSD card, version).
- Web pages load their scripts and styles with a content stamp, so a browser takes the new files at once after an update.

## Install (copy to a card, power on)

1. Download `tc100-<version>-sd.zip` below.
2. Take a microSD card of **32 GB or less** and format it **FAT32** (bigger cards come as exFAT, which the camera cannot
   read: format them FAT32 with a tool such as Rufus or `guiformat` on Windows, Disk Utility "MS-DOS (FAT)" on macOS).
3. Unzip **into the root of the card**: the card must show `wifitest`, `tc100test`, `tc100-3`, `www`... directly, not
   inside a folder (Windows "Extract all" proposes a folder: remove the folder name from the path).
4. Camera never connected to Wi-Fi? Add a file `wifi.txt` at the root of the card with two lines:
   `SSID=your network` and `PASSWORD=its password`. A camera already on Wi-Fi (TECKIN app or 2.x) keeps its network.
5. Card in, power on. The **blue LED blinks** about 2 minutes while the camera saves its whole flash to the card,
   then it restarts. **Red LED on** = stopped, nothing written: the reason is in `tc100-3/STATUS.txt` on the card.
6. About a minute later the camera plays its **startup chime**. Open **http://tc100/** (or the address in your
   router, also written to `tc100-3/ADRESSE.txt` on the card), sign in as `root` / `pass` (or the password of your
   2.x camera). The setup wizard asks for a new password, and its last step installs the firmware into the camera
   in one click.
7. No chime and no page after 15 minutes (wrong Wi-Fi)? The camera opens its own rescue Wi-Fi (`TC100-<MAC>`,
   default password: `tc100rescue`). Connect to it and open http://10.42.0.1/ to configure your Wi-Fi.

Updates: Settings → Update & backup → Firmware update with `tc100-<version>-update.tar`.
Way back: [docs/linux-port/install-3.0.md](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/blob/main/docs/linux-port/install-3.0.md).

`MD5SUMS.txt` lists the checksums of the files below.
