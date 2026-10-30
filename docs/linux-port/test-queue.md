# Test queue: changes waiting for a run on a real TC100

Several agents work on this repository. The ones without the camera write code; another one runs it on the camera.
This file is the hand-off between them. **Implementers:** add an entry for every change that needs the camera, with a
switch to turn it off. **Testers:** run the entries, write the result under the entry (date, camera, build, numbers),
set the status, and, when it passes, make the change the default in a follow-up commit (or say why not).

Status values: `to test`, `testing`, `passed`, `failed`, `blocked`.

Rules that apply to every entry:
- Test kernels boot from the SD card in RAM (`pack66/boot66b.sh`, `tc100test/c66.img`); nothing is written to the flash.
  Check that `/proc/cmdline` holds the full initrd size. **U-Boot keeps only 256 characters of `bootargs`**: add the
  kernel parameters below at the end, and check that none of them was cut off.
- Changes to `tc100_rtsp` can be tried without a reboot: `v3/dev/try-rtsp.sh CAMERA BINARY [VAR=value]`, or switches in
  `/mnt/config/rtsp.env` followed by a restart of the server (`controlscripts/rtsp-h26x restart`).
- The CI build of a change is the run whose title starts with the commit's prefix (`[hwaccel]` for the entries below):
  artifact `tc100-linux66-cma16-kernel` (`oipc.img`, `tc100test/*`, `tc100_rtsp`).
- Measure with the `STAT` lines of `/tmp/logs/tc100_rtsp.log`, `scripts/cpu-profile.sh 60`, `/proc/meminfo`
  (`MemAvailable`), `/proc/interrupts` (two reads 60 s apart), and look at the picture (snapshot, VLC).

## Blocking findings for the implementers (tester, 2026-10-30)

- **HW-01 breaks the main stream** (build bde3887): with no picture copy at the start of the encoder pool, H.265
  falls to ~72 bytes per frame after 5-10 s. A 3.4 MB allocation at the start of the pool cures it. Do not make
  the next build with HW-01 as is. Details under HW-01.
- **Wi-Fi chip stuck after a reboot from the bde3887 kernel** (`rtl8xxxu ... Failed power on`), only a power cut
  clears it. Patch 0013 is suspected, not proven. Details under HW-03.
- Not tested yet because of these two: HW-02 test 2, HW-04 to HW-08, the UI checks.

## Hardware use and memory (2026-10-30, commits `[hwaccel] ...`)

Context: [hardware-acceleration.md](hardware-acceleration.md). None of this was compiled or run before it was pushed
(no compiler on the author's machine): the first check is that the CI run is green.

### HW-01 No picture copy in the encoder pool with direct capture — `failed`
- **What:** `tc100_rtsp` allocated a 3.4 MB copy of the main and sub pictures in the encoder pool even when the encoder
  reads the capture buffers (direct capture, the default). It now allocates it only in copy mode (`RTSP_DIRECT=0`), and
  only the 0.35 MB sub picture when the sub picture is made by the CPU (`RTSP_HWSUB=0`). The H.265 warm-up frame is
  encoded from the capture buffer too.
- **Test:** the log says `encoder pool: no picture copy (direct capture and the ISP sub channel)`. The `pool used ..., free ...`
  lines after both encoders open: write down **used** with the main stream in H.265 and the sub-stream on, and again in
  H.264. Video, sub-stream and snapshots as before. Then the same with `RTSP_DIRECT=0` (copy mode must still work).
- **Pass:** free pool about 3.4 MB larger than before; no `ak_venc_open failed`; 15 fps.
- **Gives:** the pool size for HW-02 (largest "used" + 0.5 MB).
- **Result 2026-10-30, IPCAM2 (.11), build bde3887 (CI run 41032639092), kernel of the same build booted once from
  the card: FAILED, the main stream dies.** Log as expected (`encoder pool: no picture copy ...`, main pool used
  7946976, sub 8866880, free 3716032), but 5-10 s after the start the H.265 main stream falls to about 5.4 KB per
  5 s (72 bytes per frame) instead of about 1 MB, for good, with `cap 75 enc 75` and a client connected. The capture
  itself is fine (`/tmp/cam_luma` 110, the 640x360 web JPEG is a normal picture). Same with `RTSP_HWSUB=0` (dies
  after about 10 s). `RTSP_DIRECT=0` (copy mode) works (11 fps, copy cost, as before).
  - **Cause isolated:** the same source with one line added after the "no picture copy" log,
    `if (dm && getenv("RTSP_PFPAD")) p_alloc(ftot);` (the 3.4 MB the old code allocated first, never used), streams
    normally (1.0 MB per 5 s, 15 fps, pool used 11402976 / 12322880 as in rc5). So the encoder's own buffers must
    not be in the first ~3.4 MB of the pool: something else writes there, or the encoder library mishandles that
    area. With the old layout only the (rewritten every frame) picture copy sat there, which hid it.
  - **Not settled yet:** whether it also happens with the rc5 kernel (no-map pool, no patch 0015): to be run after
    the Wi-Fi problem below. Until then, suspect patch 0015 as much as the layout.
  - **Asked of the implementer:** do not ship HW-01 as is. Either keep a 3.4 MB allocation at the start of the
    pool (and say why in the code), or find what writes at 0x81800000..0x81b50000 (ISP 3D-NR? the JPEG engine?
    the CMA area handed to the kernel?) and fix that; then a new entry to test.

### HW-01b Start of the encoder pool: guard and diagnosis — `to test`
- **What (implementer, after the HW-01 result):** with direct capture `tc100_rtsp` again takes the first 3.4 MB of the
  pool (the old layout, which streamed), now as a guard: filled with `a5a5a5a5` and checked every 10 s. Any write
  into it is logged: `pool guard: written from +0x.. to +0x.. (phys 0x..): w0 w1 w2 w3` (at most 20 reports, the area
  is re-armed after each). `RTSP_POOLPAD=<bytes>` sets its size, `0` = none (the failing HW-01 layout).
  The log at start: `encoder pool: N-byte guard at its start (phys 0x81800000)`.
- **Test, in this order** (main H.265 + sub on, one client, 5 min each, STAT bytes per 5 s):
  1. Default: streams normally (about 1 MB per 5 s). Any `pool guard:` line? Write it down: it names the writer's
     range and its first words (`ffd8ffe0` = JPEG, `00000001` / `000001..` = a video bitstream, zeros, ...).
  2. `RTSP_POOLPAD=0`: the HW-01 failure should come back; confirms the reproduction.
  3. `RTSP_POOLPAD=65536`, then `1048576`, `2097152`: the smallest size that streams, and any guard reports.
  4. Steps 1-2 again on the **rc5 kernel** (no-map pool, without patch 0015), to tell the layout from 0015.
- **Reading it:** guard reports with the failure gone = something writes at the start of the pool (find it from
  the address and content). No report but a size threshold = the encoder's own buffers cannot sit at those
  addresses (alignment or address window of the core): then keep the pad, sized to the threshold, and note it.
  Failure only on the 0015 kernel = the CMA pool (cache or mapping of the area) is the cause.

### HW-02 Encoder pool from a reusable CMA area, size on the command line (kernel patch 0015) — `to test`
- **What:** the 12 MiB `no-map` region of the encoder became a CMA area of its own. The driver takes the pool from it
  at boot; `ak39_venc.pool=<size>` takes less, and the rest is usable by the kernel. Default (no parameter) = 12 MiB,
  same as before.
- **Test 1 (default):** dmesg `video encoder: ... pool 12288 KiB at 0x81800000 (CMA)`; video, sub-stream, JPEG as before;
  `MemTotal` 12 MiB higher than before and `MemAvailable` unchanged.
- **Test 2:** with the size from HW-01, e.g. `ak39_venc.pool=8M`: `MemAvailable` higher by the difference (about
  4 MB); both encoders open, recording with the sub-stream works, one hour of streaming without `ak_venc_open failed`
  or kernel errors. Then H.265 + H.264 sub, and a client switching codecs (Settings → Video).
- **Fail / revert:** no `/dev/uio0` or `cannot map the ... pool` in dmesg: boot the previous kernel. Pool too small:
  drop the parameter.
- **Result 2026-10-30, IPCAM2, build bde3887, test 1 (default): passed for memory.** dmesg `video encoder: ...
  pool 12288 KiB at 0x81800000 (CMA)`, MemTotal 59436 kB (47164 before), MemAvailable 10.8 MB (unchanged), no OOM,
  video 15 fps with the rc5 `tc100_rtsp` (which keeps the 3.4 MB copy at the start of the pool). Test 2 not run
  (needs HW-01). See HW-01: the area at the start of the pool may be the one being overwritten.
- **If it passes:** put the measured size in `flashargs` / `stock-hook.sh` (U-Boot environment: ask the owner first),
  or as the default in the device tree (`anyka,pool-size` is not used for CMA; change `reg` size or add a default in
  the driver).

### HW-03 USB host: FIFO data in 32-bit words (kernel patch 0013, `otg_hs.fifo32=1`) — `blocked`
- **Result 2026-10-30, IPCAM2: Wi-Fi dead after the bde3887 kernel, survives resets.** The bde3887 kernel (fifo32
  left at its default 0) ran for about 10 minutes, Wi-Fi fine. After a `reboot` from it, the Wi-Fi chip no longer
  starts, on the rc5 kernel too: `rtl8xxxu_init_device: Failed power on`, `probe of 1-1:1.0 failed with error -16`,
  no wlan0. Not cleared by 4 more `reboot`s, by USB re-authorisation (`authorized` 0 then 1), nor by a hardware
  watchdog reset (U-Boot starts again): a power cut is needed. More than ten warm reboots of rc4/rc5 kernels the
  same day never did this. Patch 0013 is the only USB change in that kernel; that it caused it is not proven (one
  occurrence). **Asked of the implementer:** check what 0013 changes with fifo32=0 (registers written at probe or
  shutdown, the controller's reset / suspend path) and whether the rtl8xxxu power-off at shutdown still runs. HW-03
  waits until a warm reboot after the new kernel keeps the Wi-Fi (to be retried after the power cut).
- **Implementer's answer (2026-10-30):** with `fifo32=0` patch 0013 runs the same code as before: the byte loops
  only moved into `fifo_write()` / `fifo_read()` (the receive loop no longer advances `buf`, which nothing reads
  afterwards); nothing is written at probe, shutdown or reset. The rest of that kernel: 0014 (ISP OSD ioctls, not
  called unless `RTSP_ISPOSD=1`) and 0015 (encoder pool from CMA). Warm reboots that leave the RTL8188FU in "Failed
  power on" until a power cut are a known `rtl8xxxu` / 8188FU behaviour (the chip is not powered off at reboot).
  Proposed check after the power cut: boot the new kernel, 5 warm reboots **without** starting a stream test, then 5
  with the stream running; if it comes back, 5 warm reboots of the rc5 kernel in the same way, to see whether it is
  the kernel or the reboot itself.

- **What:** the Wi-Fi USB host moved every byte of a packet with its own bus access. With `otg_hs.fifo32=1` it moves
  32-bit words (tail bytes as before). Off by default. Can be switched live:
  `echo 1 > /sys/module/otg_hs/parameters/fifo32` (do it from the **serial console**: Wi-Fi is the only network).
- **Test:** with one client playing H.265 at 15 fps, before and after the switch: USB line of `/proc/interrupts` per
  second, system and idle % (`cpu-profile.sh 60`), STAT `cap` (74-76 per 5 s). Then 30 min with `fifo32=1`: no image
  corruption, no `rtl8xxxu` errors, `OverFlow` or `-EPROTO` in dmesg; restart the access point and check that the camera
  reconnects and gets its DHCP lease.
- **Pass:** lower system %, same interrupt rate (one per packet is unchanged), stable Wi-Fi. Then default `fifo32` to 1
  in a follow-up patch.
- **Also note:** the USB interrupt rate **with no video client**. If it stays near 1000/s, the start-of-frame interrupt
  is kept on for an interrupt endpoint of `rtl8xxxu`: the next fix would let the hardware poll that endpoint
  (see the patch description).
- **Not done:** DMA. The vendor DMA path (`CONFIG_USB_AKOTG_DMA`) unmaps buffers usbcore already maps (and with a NULL
  device), may write past the end of an RX buffer and does not handle short / zero-length packets; it needs a rework.

### HW-04 Privacy masks by the ISP (`RTSP_ISPMASK=1`) — `to test`
- **What:** `AK_ISP_SET_MAIN_CHAN_MASK_AREA`, `_SUB_CHAN_MASK_AREA`, `_MASK_COLOR` (as the 2.x firmware did through the
  vendor library: opaque, type 0, alpha 0) instead of painting the areas in every frame. Off by default because a mask
  in the wrong place is a privacy failure.
- **Test:** draw 2 masks on the Image page (one in a corner, one in the middle), `RTSP_ISPMASK=1` in `rtsp.env`, restart
  the server. Log: `privacy masks: 2 in the ISP`. Check main stream, sub-stream (`/ch1`), snapshot and a recording: the
  areas are covered exactly where the editor shows them, in black, grey and white. Remove the masks: they disappear.
- **Pass:** then make it the default (`mask_hw` starts at 1 unless `RTSP_ISPMASK=0`).

### HW-05 Sharpness by the ISP (Image page, `SHARPNESS`) — `to test`
- **What:** the Sharpness slider is back on the Image page. `tc100_rtsp` scales the tuning file's medium and high
  frequency gains (`AK_ISP_SET_SHARP`, manual and 9 gain-linked sets) by 2 % per step. On by default (nothing is written
  while the slider is at 0).
- **Test:** live tuning on, sharpness -50, 0, +50: log `sharpness: N in the ISP (medium a -> b, high c -> d)`; the
  picture gets softer / sharper (compare snapshots of the same scene); bit rate goes down / up a little. The "Applied on
  the camera" line under the form shows the value.
- **Fail:** picture broken or unchanged at ±50: note the logged gains; `RTSP_ISPTUNE` does not cover it, set SHARPNESS=0.

### HW-06 Exposure cap by the ISP (Image page, `EXPOSURE_MAX_PCT`) — `to test`
- **What:** the Exposure time cap slider is back. `AK_ISP_SET_AE` `exp_time_max` = the tuning file's value × percent,
  never below `exp_time_min` (the 2.x firmware did the same through the vendor library).
- **Test:** in low light, 100 % (off) then 30 %: log `exposure cap: 30 % (exp_time_max A -> B)`; moving things blur less,
  the picture is darker. `/tmp/cam_ae` (HW-08) shows `exp_time` not above B.

### HW-07 Clock by the ISP OSD (`RTSP_ISPOSD=1`, kernel patch 0014) — `to test`
- **What:** new ioctls `AK_ISP_SET_OSD_COLOR_TABLE` / `AK_ISP_SET_OSD` reach the ISP's on-screen display code (window 0,
  4 bits per pixel, 16 colours, swapped at the next frame). `tc100_rtsp` draws the clock into it once a second instead
  of into each frame (and no cache clean of those rows). Off by default; any refusal falls back to the CPU clock.
- **Test:** OSD on in Settings → Video, `RTSP_ISPOSD=1`, restart. Log: `clock: in the ISP OSD (WxH at x,y)`. The clock
  shows on the main stream and in snapshots, ticks every second, black box, white digits, same place as before.
- **Unknowns to settle:** nibble order (garbled digits: `RTSP_OSD_NIBBLE=1`), alpha (box transparent or invisible:
  try `RTSP_OSD_ALPHA=15`), whether colour 0 is transparent. Write down what worked; then make the values the defaults.
- **Fail:** no clock or a corrupted picture: remove `RTSP_ISPOSD`; dmesg of the ISP.

### HW-08 Exposure state for day / night (`/tmp/cam_ae`) — `to test`
- **What:** every 2 s `tc100_rtsp` writes `lumi exp_time a_gain d_gain isp_d_gain dark_flag` from
  `AK_ISP_GET_AE_RUN_INFO`. Nothing uses it yet. The day / night daemon decides from `/tmp/cam_luma`, the mean luma
  of the picture *after* auto exposure, which stays near the AE target whatever the light: exposure time and gains
  measure the scene light.
- **Test:** record `/tmp/cam_ae` and `/tmp/cam_luma` in daylight, at dusk, at night with the IR LEDs on and off.
- **Next:** if the values separate day and night clearly, switch `scripts/auto-night-daemon.sh` to them (with
  hysteresis), so the IR light itself does not flip the mode back.

### Looked at and not possible / not done (2026-10-30)
- **SD card 4-bit bus:** the SD controller's data lines 2-3 are GPIO 80 / 81, the IR-cut filter on the TC100
  (OpenIPC device tree `mci0_pins`: 0x1f-0x22 and 0x50, 0x51). The card stays 1-bit.
- **USB DMA:** see HW-03.
- **3D noise reduction:** its reference frame (about 3 MB) does not fit the capture CMA area. With HW-01/HW-02 freeing
  memory it could be tried again (`AK_ISP_SET_3D_NR_PHYADDR` is refused by the 6.6 char driver today; needs a kernel
  change to give it a buffer). Quality and bit rate at night, not CPU.
- **Anti-flicker (`POWER_HZ`):** the 2.x firmware set it through the vendor library (`ak_vpss_effect_set(6, hz)`),
  whose ISP calls are not known; the field stays hidden on 3.0.

## Web UI on 3.0: checks that need the camera (audit of 2026-10-30)

A static audit traced every control of the web UI to what acts on it on 3.0. The fixes are in the commits
`[ui30] ...`; these checks remain. Write the result after each line.

- UI-01 `to test` — Busybox applets: `busybox --list | grep -E '^(crond|crontab|usleep|mkfifo|timeout)$'`. Without
  `usleep` the IR-cut pulse of `bin/setconf` becomes 1 s; without `crond` the scheduled reboot never runs.
- UI-02 `to test` — Time zone: set `CET-1CEST,M3.5.0,M10.5.0/3`, reboot; `date` over telnet, the OSD clock, a new
  recording's file name and the log times agree.
- UI-03 `to test` — IR-cut: Day / Night from the dashboard; the filter clicks and the picture changes the right way
  (the UI state is `/var/run/ircut`, not read from the coil).
- UI-04 `to test` — Auto day / night at dusk or in a dark room: `watch -n2 'cat /tmp/cam_luma /tmp/cam_ae'` and the
  `[auto-night]` lines; note any flapping when the IR LEDs switch on (see HW-08).
- UI-05 `to test` — Image orientation select: Mirror, Flip, Rotate 180; masks, OSD clock and snapshots follow.
- UI-06 `to test` — Video: GOP, min / max QP from Settings reach `tc100_rtsp` (`-q -Q -g -G` in `ps`, keyframe
  interval in VLC's codec info). A camera still holding the old shipped values (QP 20..51, GOP 64 / 32, never applied
  before) keeps QP 25..48 and GOP 2 s; set e.g. GOP 15 and QP 22..45 and check they apply, then the bit rate and the
  picture under motion. Orientation select (Mirror / Flip / Rotate 180): picture changes within 1 s without a
  stream restart, kept after a reboot; `docs/api.md` says 1 = horizontal flip, the code (`bin/setconf`,
  `src/ispflip`) 1 = flip, 2 = mirror: correct the doc after looking.
- UI-06b `to test` — No stream restart any more when switching live tuning, sound detection, two-way audio or the
  motion zones (all read live); the sub-stream switch still restarts. Saving the Image form keeps values set from MQTT.
  Home Assistant: the anti-flicker and Privacy Shield entities are gone. Wizard: only Standalone and Frigate + HA;
  after the Frigate profile, motion and OSD switched on again in Settings stay on after a reboot. Motion events carry
  a picture (`/tmp/motion_snap_*.jpg`, 5 kept).
- UI-07 `to test` — Motion: red LED blinks on motion with "Blink LED" on; the Recordings page timeline shows a
  picture for each event; "On motion" recording with Detection off records nothing (the UI says so).
- UI-08 `to test` — Network: static IP without DNS, reboot: `/etc/resolv.conf` holds the gateway, `ntpd` resolves.
  Changing the RTSP port restarts the server on the new port.
- UI-09 `to test` — Wi-Fi tile: `cat /proc/net/wireless` and `iw dev wlan0 link` give the signal.
- UI-10 `to test` — Rescue access point, from the serial console (it takes wlan0): `sh /mnt/scripts/wifi-rescue.sh
  start`; a phone sees it, `http://10.42.0.1` answers.
- UI-11 `to test` — Scheduled reboot 2 minutes ahead fires (needs UI-01 `crond`).
- UI-12 `to test` — Microphone level 0..15: `amixer -c 0 cget name='LineIn Capture Volume'` follows the setting.
- UI-13 `to test` — Speaker / push-to-talk: a clip through `scripts/speaker-play.sh` is heard; amplifier polarity
  (`SPEAKER_AMP_ACTIVE`, GPIO 14) and RTSP two-way audio from go2rtc / Home Assistant.
- UI-14 `to test` — Home Assistant: the entities that appear all act (no anti-flicker or privacy entities any more).
- UI-15 `to test` — Telegram: `/mnt/bin/telegram p`, and curl over TLS to `api.telegram.org`.
- UI-16 `to test` — Settings size: 10 presets plus MQTT, then `cat /tmp/cfg-persist.status` (a 36 KB slot).
- UI-17 `to test` — Memory Guard: its default thresholds (warn 8192, critical 4096 KB) against the real MemAvailable
  (about 10 MB, more after HW-02); the critical stage must not stop motion detection in normal use.
- UI-18 `to test` — Listen in the browser with the RTSP audio track on; syslog (`ps | grep syslogd`, `/var/log`).
- UI-19 `to test` — SD card mount / eject / resume with FAT32 and exFAT cards; an update uploaded without a card.
- UI-20 `to test` — Reset button held 20 s: only a reboot on 3.0.
- UI-21 `to test` — Settings regrouped (commits `[ui30] Settings: shorter menu...`, `Privacy masks apply whatever
  live tuning is...`): on a desktop and a phone, every tab opens (Picture, Privacy & overlay, Day/night, Streams &
  audio, Detection, Recording, Network, Integrations, System, Update & backup), an old `#nav_audio` bookmark lands on
  Streams & audio. A mask saved with live tuning **off** is painted (stream, snapshot) and the tuning switch stays off;
  a mask-only save with tuning on keeps it on. Orientation alone changes only the flip (OSD, clock, day/night kept).
  Saving the recording settings does not restart the stream. MQTT save and "Refresh Home Assistant Entities" work in
  the merged card; the rescue Wi-Fi line fills in under the Wi-Fi card.
- UI-22 `to test` — Web UI pass (commits `[webui] ...`, HTML/CSS/JS only, no CGI change). On a desktop and a phone, in
  French and English:
  - Settings: orientation alone saves (was blocked by the "ip" check); a negative sound threshold (-30) saves; Wi-Fi
    refuses a password with `"` or `\` or outside 8..63 characters before sending; "Install & reboot" posts
    `update.cgi?cmd=install` (was a ReferenceError; cancel at the confirm or use a test package); the Home Assistant
    badge follows the MQTT and Discovery switches; drawing a mask on a phone marks the form changed.
  - Shell: reboot from the menu gives a green toast (a dropped connection gives the neutral "probably restarting");
    with the network cut, open Logs, restore it and click Logs again: it reloads; leaving Live for Settings closes the
    `live.cgi` connection (`ps`: the sub-stream encode stops); `camcontrols.cgi?cmd=panel` is not polled while the
    Dashboard is shown; the dashboard snapshot keeps refreshing over slow Wi-Fi.
  - Config editor: switch files with unsaved edits and cancel (the list goes back); a value containing a literal `\n`
    and a file with a tab load and save unchanged. Backup: restore and JSON import right after a page load (no 403).
  - Recordings: play, download and delete a clip, also one whose name has a space. Logs: switch tabs quickly, Clear,
    Download, the saved-logs list.
  Found on the way, needs a CGI change (not done): `wizard.cgi` says an empty Wi-Fi password gives an open network but
  `wifi_set_config` refuses it; `wifi_set_config` strips `"` and `\` instead of refusing them; `configeditor.cgi`
  read does not escape control characters in its JSON (the page works around it); `viewrecords.cgi` remove leaves the
  `.jpg` thumbnail; `config_exchange.cgi` / `upload_backup.cgi` messages are English only.

Not fixed, for later: the action endpoints left from 2.x that no page calls (`set_stream_topology`,
`set_onvif_stream_policy`, `set_rtsp_preset`, `set_rtsp_quality_profile`, `set_client_profile`, `pair_home_assistant`,
`complete_setup_wizard`, `conf_autodaynight`, ...); the performance profiles of `system.sh` write values 3.0 does not
read; anti-flicker (see above).

## New features using the freed CPU (2026-10-30, commits `[feat30] ...`, `[live] ...`)

Checked before pushing with `tests/docker/local-ci.sh` (tests + ARM build); nothing run on a camera.

### F-01 Live video in the browser (`live.cgi`, Media Source Extensions) — `to test`
- **What:** the live view plays the camera's H.264 stream (sub-stream 640x360 when it is H.264, else the main stream)
  as fragmented MP4, no re-encoding; "Video / Snapshots" switch on the live view (remembered by the browser); at most
  2 viewers, a viewer is dropped after 1.5 s without reading, reconnects every 10 min. Snapshots as before otherwise.
- **Test:** Chrome / Safari on a desktop and a phone: video within 1-3 s, `/tmp/tc100_live/status` reads
  `stream=sub codec=avc1...`; CPU with Video vs Snapshots (`cpu-profile.sh 60`); a third tab stays on snapshots;
  after closing the tabs `/tmp/tc100_live` is empty and the sub encoder stops (STAT); hiding the tab closes the
  connection; 15 min of video over Wi-Fi (reconnect near 10 min without a long freeze); sub codec H.265 with main
  H.264 serves the main stream, both H.265 = snapshots.
- **Off:** "Snapshots" on the switch.

### F-02 Frame rate select (Streams & audio) — `to test`
- **What:** 10 / 12 / 15 (default) / 20 / 25 fps for both streams, `-f` from `rtspserver.conf [0] fps`; other values
  mean 15. A camera holding 20 or 25 there from an old preset changes rate at the next stream restart.
- **Test:** each rate: log `sensor: N fps`, STAT `cap` = N x 5 per 5 s, keyframe interval, CPU and Wi-Fi at 25.

### F-03 Lower frame rate when nothing moves (`IDLE_FPS`, opt-in) — `to test`
- **What:** with motion detection on, `IDLE_FPS=5`, `IDLE_AFTER=10` (boot.conf, Streams & audio card): after 10 s
  without motion or sound event the encoders get 5 fps; full rate again at the first motion. Not applied while the
  recorder writes continuously.
- **Test:** stay still: log `idle frame rate: ... 5 fps instead of 15`, STAT `cap` 25 per 5 s; wave: `back to the full
  rate` within about 1 s; Frigate and a motion recording still start correctly. **Off:** `IDLE_FPS=0`.

### F-04 Day / night from the ISP exposure (`DAYNIGHT_SOURCE=ae|isp`, opt-in) — `to test`
- **What:** index `exp_time * a_gain/256 * d_gain/256 * isp_d_gain/256` with `AE_NIGHT_ABOVE` / `AE_DAY_BELOW` (the
  defaults 4000 / 1000 are placeholders), or the ISP's own dark flag; night after 10 s, day after 60 s. Live reading
  on the Day/night tab. Default stays `luma`. Uses the HW-08 data.
- **Test:** note the reading in daylight, dusk, night with IR on and off; set the thresholds (day clearly below the
  IR-lit night index); switch to the `ae` source: no flapping when the IR LEDs come on. Check the gain unit (256 = 1x?).
  **Off:** source "Picture luminance".

### F-05 Logs kept across reboots (`scripts/log-persist.sh`, on by default) — `to test`
- **What:** dmesg, syslog, `tc100_rtsp.log` and tails of the other logs to `/mnt/sd/logs/boot-NNNN` 120 s after the
  start, every 10 min and before a reboot from the web UI (`reboot-tracker.sh intent`); last 5 boots, about 2 MB
  each; skipped when the card is not vfat/exfat, ejected / recording paused, unhealthy or under 64 MB free. A bare
  `reboot` in a shell and a panic keep only the last 10-minute copy. Logs page: "Logs of previous boots".
- **Test:** files appear after about 2 min; reboot from the UI gives a `why=shutdown` save and `boot-0002`; nothing
  written while ejected; card writes over a day are small. **Off:** `LOG_PERSIST=0`.

### F-06 Memory Guard defaults (warn 6144 / critical 3072 KB) — `to test`
- **What:** the old defaults (8192 / 4096) sat next to the normal MemAvailable; cameras holding exactly them are
  migrated when the service starts; the warn stage no longer stops `auto-night-detection`.
- **Test:** `/tmp/log/memory-guard.log` shows the migration once; no warn / critical stage in a day of normal use.
  **Off:** `MEM_GUARD_ENABLE=0`.

Not done: 3D-NR (its 6.2 MB reference frame does not fit until HW-01b / HW-02 free memory); `conf-import.cgi` does not
know `IDLE_FPS` and `LOG_PERSIST` yet.
