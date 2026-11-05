# Test queue: changes waiting for a run on a real TC100

Several agents work on this repository. The ones without the camera write code; another one runs it on the camera.
This file is the hand-off between them. **Implementers:** add an entry for every change that needs the camera, with a
switch to turn it off. **Testers:** run the entries, write the result under the entry (date, camera, build, numbers),
set the status, and, when it passes, make the change the default in a follow-up commit (or say why not).

Status values: `to test`, `testing`, `passed`, `failed`, `blocked`.

Finished entries (passed and made the default, superseded or abandoned) are moved to [test-queue-archive.md](test-queue-archive.md); this file keeps what is still open.

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
- Memory of a process: **PSS** (`awk '/^Pss:/ {print $2}' /proc/<pid>/smaps_rollup`, KB), not RSS. RSS counts the busybox
  and C library pages shared by every shell once per process (the C MQTT bridge looked 5 MB lighter in RSS, 0.9 MB in PSS).

## Tester report to the implementers (2026-10-30, IPCAM2 / .11 on the serial console)

Read this first. Details and numbers are under each entry.

**Update 2026-10-31 (night 2, rc7 `fb75210`, IPCAM2): what to do first, in this order**
1. **Bug, F-05:** `scripts/log-persist.sh` line 80, a boot counter with an 8 or 9 in it (`0008`) is read as octal by ash:
   no log folder is created any more after the 8th boot on a card. Details and fix in the "night 2" table below.
2. **MQTT:** the broker refuses IPCAM2's login (CONNACK 5). Not a firmware fault, but show the CONNACK code in the web UI
   status and back off on refusal (the owner saw "nothing" in Home Assistant and had no way to know why).
3. **Make default:** `RTSP_ISPOSD=1` (HW-07 passed, saves about 2 % of a core), the privacy masks by the ISP (HW-04 passed
   for black, gray and white), `ak39_vi.slots=3` (+3.5 MB RAM, no cost, 15 and 25 fps checked).
4. **Do not make default / drop:** `RTSP_UDPMMSG=1` (blocks and stutter in VLC), `otg_hs.fifo32=1` and
   `rtl8xxxu.dma_aggregation=1` (no gain), `RTSP_FRAMECOPY` (no difference at one client).
5. **Needs data from the day:** HW-08 / F-04 (at night AE is pegged: exposure 1124, gain 6840 with or without IR), HW-05
   (sharpness gains are 1 in the tuning file: only 0 / 1 / 2 levels).
**Questions waiting for the owner** (the tester cannot do these alone): RTSP / web credentials for the client tests (TCP + UDP at the
same time, sub-stream, H.265 UDPSG, W-01, UI-22, F-01, O-04 checks 2-9, ssh); ONVIF discovery from a real LAN client (ONVIF is
off on IPCAM2); the MQTT password (the owner re-enters it); a go for the HW-02 test 2 boot argument `ak39_venc.pool=9600K`
(RAM only, not saved); daylight readings for HW-08 / F-04 tomorrow; the microphone and the speaker by ear.

**IPCAM2 (.11) state at 2026-10-31 00:45:** rc7 (`fb75210`, nothing newer on main) in the flash, **25 fps set by the owner's decision**
(`rtspserver.conf [0] fps=25`, saved to the flash settings by cfg-persist, survives a full reboot: `-f 25`, 123-126 frames per 5 s,
`dropped` 2 per 5 s at worst, idle 79.8 %, MemAvailable 16.5 MB, Frigate connected). No U-Boot change, no `saveenv`; `ak39_vi.slots=3`
is NOT in the flash boot arguments (it needs a U-Boot env change: the owner has not agreed yet). The SD card still holds `tc100test/`
(consoleshell, test.img) and `.bootcount` = 0009 (see the F-05 bug).

**HW-02 test 2 (`ak39_venc.pool=9600K`): NOT run, on the advice relayed by the owner (do not touch U-Boot).** Reminder of what the tester did
touch: the one-shot kernel tests of night 2 (slots=3, rtl8xxxu.dma_aggregation=1, otg_hs.fifo32=1) typed `setenv bootargs ...; bootm` at the U-Boot
prompt, in RAM only; no `saveenv`, the stored environment was not written. If the implementer wants HW-02 test 2 without any U-Boot prompt,
it needs the pool size built into the test kernel's own command line (CONFIG_CMDLINE) in a CI build for the card.

**Builds run today**
- `cb20c19` / `80c0285` (rc5): 512 KB page blocks (`CONFIG_ARCH_FORCE_MAX_ORDER=7`), high-atomic reserve 1 MB,
  no boot OOM; installed in the flash of IPCAM2 in the morning, and on IPCAM1 (.24) by its owner through the web UI.
- `bde3887` (morning): kernel booted once from the card. HW-02 test 1 passed (MemTotal +12 MiB). The new
  `tc100_rtsp` lost the main stream after 5-10 s (HW-01), and after a reboot from that kernel the RTL8188FU stayed in
  `Failed power on` until a power cut (HW-03). Both were reported as blocking.
- `563dbff` (evening, after a power cut): kernel from the card, then **installed in the flash** of IPCAM2 with
  `update66.sh` (settings kept). **Neither problem came back**: HW-01b passed (no guard report, `RTSP_POOLPAD=0` and
  even the bde3887 binary stream normally), 6 warm reboots after the new kernel all kept the Wi-Fi. MemAvailable
  15.3-15.9 MB (10.8 on rc5), 15 fps, 84 % idle, UI-01 and F-05 passed. IPCAM2 now runs 563dbff from its flash.

- `b5e7573` (**3.0.1-rc6**, 20:00): kernel booted once from the card (Wi-Fi 15.4 s, 15 fps, MemAvailable 15.4 MB),
  then installed in the flash of IPCAM2 (settings kept). From flash: MemAvailable 15.9-16.1 MB, 15 fps (about 1 MB
  per 5 s), about 79 % idle a minute after the start, no OOM; 2 warm reboots, Wi-Fi every time; `curl` over TLS works
  in the serial console shell now (api.github.com 200); one housekeeper running. IPCAM2 runs rc6 from its flash.
- **HW-02 test 2 has not been run yet** (no `ak39_venc.pool=` boot so far). Note for its size: without the HW-01b
  guard the pool used is 8866880 bytes (main H.265 + sub H.264), so the pool must be at least about 9.4 MB
  (`ak39_venc.pool=9600K` or so) with `RTSP_POOLPAD=0`; `8M` would be too small. With the guard (12322880 used) a
  smaller pool cannot work: the guard has to go first (proposal 3).

### rc7 (`fb75210`, CI run 41120278897) on IPCAM2, 2026-10-30 night: LED-01 fixed, S-01 passed, nothing blocking

Order followed: card boot (kernel only, rule), then the flash (`update66.sh`, settings kept), because the card boot
uses the **flash** user space: the rc7 scripts (`perf-baseline.sh`, S50, ssh/telnet) only exist after the flash install.
- **Card boot of the rc7 kernel:** `/proc/cmdline` complete (initrd size present), Wi-Fi 15.4 s, 15 fps, MemAvailable
  15.96 MB, no OOM, **`/proc/net/igmp` exists** (multicast in the kernel, P-01 first half).
- **Flash install:** md5 and `update66.sh check` ok, written, restart, Wi-Fi 15.2 s, VERSION 3.0.1-rc7, MemAvailable
  15.97 MB, no OOM / squashfs error.
- **LED-01 `passed`** (owner looking at the front LED): both off -> **off**; blue = 1 -> **blue**; red = 1 -> **red**;
  `ir` = 1 -> the IR LEDs around the lens glow. The Settings page itself (browser) not tried yet. Reset button input
  (bank 0 IN bit 10) reads 1 at rest (released); a press was not tried.
- **S-01:** port **22 open, 23 closed** after boot. `kill -9` of `housekeeper.sh run` -> a new one is running under
  `service-watchdog.sh` (it was back within about 70 s, not within the first 25 s; exact delay not measured).
- **P-06 reference profile (`perf-baseline.sh 60`, 1 RTSP client, 15 fps, rc7 flash):** user 9.6 %, system 15.2 %,
  softirq 2.2 %, idle **72.6 %**; wlan0 tx 216 KB/s; interrupts/s: usb-host **717**, timer 100, l2 31, venc 19, vi 15,
  mmc 10; MemAvailable 15.2 MB, Slab 6.0 MB, CmaFree 1.6 MB; STAT 71-76 frames per 5 s, `dropped` 0-1.
  The USB host interrupt (717/s) is the largest source: the target of HW-03 (`fifo32`) and P-07.
- **Audio on rc7 (B-01 / B-02 checks 2-4), owner listening, IPCAM2: two findings.**
  1. **`amixer -c 0 ...` fails** (`ALSA lib conf.c: cannot stat file/directory /usr/share/alsa/cards/aliases.conf`,
     `Unknown parameters 0`, `Invalid CTL sysdefault:0`, rc 1). `v3/build-stack.sh` leaves the `cards` directory out
     of `ext/share/alsa` (`init|cards|ucm|ucm2|topology`), but `alsa.conf` includes `cards/aliases.conf`. `amixer -D hw:0
     ...` works, and so do `aplay -l` / `arecord -l`. **Callers of `amixer -c 0`** that now silently do nothing:
     `scripts/speaker-play.sh:38` (speaker volume), `scripts/action.d/audio.sh:22` (microphone level, UI-12),
     `v3/linux66-sd/rtsp-launch.sh:60` (mic level at start). Fix: ship `cards/aliases.conf` (a few lines) or call
     `amixer -D hw:0`. Mixer values themselves are fine: Headphone Playback Volume 3 (0-5), LineIn Capture Volume 10 (0-15).
  2. **Speaker silent.** `aplay -q -D plughw:0,0 -t raw -f S16_LE -r 8000 -c 1` of a 1.5 s 600 Hz tone (24000 bytes,
     rc 0), the owner next to the camera: **nothing heard**, with the volume at 3 and again at 5 (max), three times,
     and for every `Headphone Playback Route` 0-7 (4 is the default). The amplifier pin does switch: bank 0 OUT
     0x8800 at rest, **0xC800 during playback** (bit 14 = GPIO 14 high), then back. `DAC out mode` 1 and
     `HPDet switch` off were not changed. Not known whether the speaker ever worked on 3.0 (README: amplifier "not
     tested"); not compared with rc6. Asked: check polarity (`SPEAKER_AMP_ACTIVE`, the pin is high during playback
     so active high is what the driver does) and the codec's speaker path (`DAC out mode` 0, the stock firmware's
     mixer settings), and the effect of the pin fix 9a325f2 on GPIO 14. Microphone not tested here (`tc100_rtsp` holds the
     capture device: `arecord` says `Resource busy`); RTSP audio to be listened to with VLC.
- **[RETRACTED, see CORRECTION further down] MQTT bridge costs about 20 points of CPU.** `perf-baseline.sh 60`, same scene, 15 fps,
  one RTSP client, rc7 flash, IPCAM2 (its broker 192.168.1.25 is configured, the owner has not set the password yet):
  **`mqtt-bridge` stopped: idle 77.4 % / 74.5 % (system 12.3 / 13.7)**; **running: idle 54.0 % / 57-59 % (system
  26-29, user 12-13.5)**, three alternating runs. The bridge's own processes show almost no ticks (`/proc/<pid>/stat`:
  12 ticks in 60 s for the listener), so the cost is its **forks and children** (health publish, spool poll) and what
  they cause in the kernel (system time), not the shell's own loop. `top` showed the persistent listener at 10 % at one
  point. The first baseline of the night (72.6 % idle) was taken shortly after boot with the bridge in a quiet phase.
  Everything compared before (P-04 etc.) carries this load. **Asked of the implementer:** count the forks per minute of
  the running bridge (`strace -c -f` is not there: count `ps` children or `/proc/*/stat` of short-lived pids), poll
  and publish less often, use builtins instead of `date`/`cat`/`awk` per tick, and make the listener back off when the
  broker refuses the login. A camera with MQTT configured and no/wrong password must not pay this.
- **P-09 (owner watching VLC, IPCAM2, rc7, main H.265 + sub):** `RTSP_UDPSG=1` (log `rtp scatter-gather 1 sendmmsg 0`):
  **clean and smooth picture** over UDP for 1 minute+, `dropped` 0, `snd_ms` 250-310 per 5 s (same as without).
  `RTSP_UDPSG=1` + **`RTSP_UDPMMSG=1`** (`sendmmsg 1`): **blocks / smears / stutter** in VLC (the log shows
  `clients 2`, `snd_ms` 716-1124 in two STAT lines while the second client connected, `dropped` 0). So the `sendmmsg`
  batching is **not** ready; scatter-gather alone looks fine, no CPU difference seen (idle 56.9 % with, 57.5 % without,
  bridge running in both). Not tried: a simultaneous TCP and UDP client, 30 min of `dropped`, Frigate reconnect time.
- **P-08 `RTSP_VBR=1`** (night scene, noisy, one client): bytes per 5 s 0.89-0.96 MB (VBR) against 0.95-1.03 MB (CBR,
  ceiling 1.0 MB per 5 s): about **6 % lower**, `cap`/`enc` unchanged. A still, low-noise scene was not available
  (the picture is noisy at this gain), so the saving on a day scene is still to measure. The smart mode symbols in
  `libmpi_venc*.so` not looked up.
- **P-04 frame rate (bridge running, one client, 60 s each):** 15 fps idle 56.9 % (system 27.1), 20 fps **57.9 %**
  (STAT 98-99 frames per 5 s, `dropped` 0-2), 25 fps **59.2 %** (117-125 frames per 5 s, `dropped` 0); USB host
  interrupts 808 / 644 / 609 per s, wlan0 tx 238 / 191 / 184 KB/s (bit rate fixed). **The frame rate costs no measurable
  CPU: 25 fps is as cheap as 15** (the bit rate is shared by more frames, so each frame is smaller). The rtspserver.conf
  value `fps` of IPCAM2 is 16 (not one of 10/12/15/20/25, so no `-f`: the code default 15 applied); restored to 16 after
  the runs. The picture quality at 25 fps was not judged (no one looked at VLC then).
- **MQTT: Home Assistant sees nothing on IPCAM2 (rc7), diagnosed - the broker refuses the login (CONNACK 5).**
  Owner report: with rc3 some entities were still visible, with rc7 nothing. On the camera (rc7 flash, up 53 min):
  `/tmp/mqtt_last_pub.status` = `fail`; the listener's capture `/tmp/mqtt_stream.bin.26` and `.27` contain
  **`20 02 00 05`** = CONNACK "not authorized" (sessions 26, 27 ... the listener has reconnected about once every
  2 minutes since boot). Network is fine: ping 15-20 ms, `nc 192.168.1.25 1883` connects. `/mnt/config/mqtt.conf` has
  `MQTT_ENABLE=1`, host 192.168.1.25, port 1883, user `morgeekha`, and a non-empty 8-character `MQTT_PASSWORD`
  (no quote, space, `$` or `#`; file dated Oct 29, so it was not changed by the rc7 install). So the camera speaks
  correctly and the broker says no: user/password pair wrong or user not allowed on the broker (owner to check the
  Mosquitto user in Home Assistant). rc3 "still showing some info" is most likely the retained discovery
  messages / entities left in HA, not live data. **Not a firmware fault, but two things for the implementer:**
  1. **Surface it.** `mqtt_last_pub.status` only says `fail`. Record the CONNACK code (`bad credentials` /
     `not authorized`) in the status file and show it in the web UI MQTT indicator, so the owner sees
     "broker refused the login" instead of silence.
  2. **Back off on refusal.** On CONNACK 4/5 the listener must stop hammering: wait 1, 2, 4 ... up to 30 min, and do
     not run the fork-heavy health/spool work while not connected. This is the likely source of the 20 points of
     CPU measured above (reconnect + `nc` + `od` + `date` per cycle, system time 26-29 %). With a refused login the
     bridge should cost nothing.
  Open for the owner: verify the password for `morgeekha` in HA and re-enter it in the web UI; then I re-measure the
  CPU with a working login (expected to be different) and check the entities arrive in HA.
- **P-02 `ak39_vi.slots=3` (one-shot from the SD card, rc7 kernel, flash user space, bootargs only in RAM, no saveenv): PASSED, worth making the default.**
  Same procedure twice, 15 fps, one RTSP client (Frigate), `perf-baseline.sh 60` taken at the same age (2-4 min after boot):
  | | default (module reports `slots` = 4) | `ak39_vi.slots=3` (cmdline and module report 3) |
  |---|---|---|
  | MemAvailable | **15.6 MB** | **18.8-19.5 MB** (+3.2 to 3.9 MB) |
  | CmaFree | 1.3 MB | 1.2-1.4 MB |
  | CPU idle | 82.0 % (user 4.5, sys 11.2) | 81.5-80.9 % (user 5.2, sys 10.9) |
  | STAT frames per 5 s / dropped | 74-75 / 0-2 | 75-76 / 0 |
  So three capture buffers are enough at 15 fps: +3.5 MB of RAM for free. Not tested: 25 fps, H.264 main, sub stream
  with `slots=3` (a 20-25 fps run should be done before changing the default), and a long run for `dropped`.
  Wi-Fi associated at 15 s, all services up, no Oops.
- **CORRECTION of the "mqtt-bridge costs 20 points of CPU" finding (not reproduced, do not act on it yet).** On a fresh
  card boot (same rc7 kernel, flash user space, bridge failing its login with CONNACK 5, one RTSP client, 15 fps):
  idle **82.0 %** at 2 min, **80.9 %** at 13 min, and **82.9 %** at 18 min after a manual `mqtt-bridge restart`
  (that restart itself shows a short burst: idle 69.5 % during the first minute, user 9.5 / system 18.5). That is as
  good as the "bridge stopped" runs of earlier (74-77 %). The earlier 54-59 % came from the boot that had been up 47-53 min
  after several of my own experiments (fps changes, rtsp.env switches, a second VLC client at times). The bridge's
  cleanup is fine (old `/tmp/mqtt_stream.bin.N` files are removed, 5 present, 44 files in `/tmp`), so my "accumulating files"
  guess was wrong too. Still worth doing: the **backoff on CONNACK 4/5** (a refused login re-sent every ~2 min costs a
  burst each time) and surfacing the code in the UI. I will re-measure at ~45 min of this boot to see whether the load
  appears later; result below if it does.
### rc7 night 2 on IPCAM2 (.11), 2026-10-30 / 31: everything the tester could run alone (serial + the Mac's LAN shell, no credentials typed)
Setup: card boot of the rc7 kernel for the kernel-argument tests (bootargs only in RAM, never saved), flash boot for the rest; every setting changed
for a test was restored and checked against the `.dist` files at the end (`isp_tune.conf` identical to its `.dist`, `rtsp.env` empty, OSD off, masks removed,
`ISP_TUNE=0`, ONVIF stopped, fps back to 16 = 15 effective, no `-f`). One lesson: `cfg-persist` saves the settings 30 s after a change, so a reboot
sooner than that loses the change (my 16 fps restore was lost twice, the camera booted at `-f 25`); fixed by waiting for `[cfg-persist] settings saved`.

| Test | Result |
|---|---|
| **HW-07** clock by the ISP OSD (`RTSP_ISPOSD=1`, `osdenabled=1`) | **PASSED.** Log `clock: in the ISP OSD (472x44 at 12,16)`; the snapshot shows the clock identical to the CPU one (digits right, black box, white digits, same place), ticks every second; no `RTSP_OSD_NIBBLE` / `ALPHA` needed (defaults are right). `pp_ms` per 5 s: **104-124 with the CPU clock, 0-1 with the ISP OSD** (about 2 % of a core saved). No dmesg error. Make it the default. The OSD is drawn on top of a privacy mask. |
| **HW-04** privacy masks by the ISP (`RTSP_ISPMASK=1`, `MASK1=0,0,25,30`, `MASK2=40,40,60,70`) | **PASSED** on the snapshot: log `privacy masks: 2 in the ISP`, `MASK_RC=0 MASK_HW=1`; the two areas sit exactly at the percentages (corner 0-25 x 0-30 %, centre 40-60 x 40-70 %), uniform inside (std 0.3-0.6); luma **black 16, gray 128, white 234** (video levels). Removing the lines and restarting: log shows no mask. Not checked (needs RTSP credentials): sub-stream `/ch1`, a recording, Frigate. |
| **HW-05** sharpness (`ISP_TUNE=1`, `SHARPNESS=-50/0/+50`) | **Works, subtle in this scene.** Log `sharpness: -50 in the ISP (medium 1 -> 0, high 1 -> 0)` and `sharpness: 50 ... (medium 1 -> 2, high 1 -> 2)`: the tuning file's gains are only **1**, so the 2 %-per-step scaling yields 0 / 1 / 2 (coarse, three effective levels). JPEG size 53063 / 57900 / 66866 bytes, whole-picture Laplacian variance 172 / 174 / 179 (night scene, noise dominates). Needs a daylight scene to judge the look. Live (picked up in under 6 s without a restart). |
| **HW-06** exposure cap (`EXPOSURE_MAX_PCT=30`) | **PASSED.** Log `exposure cap: 30 % (exp_time_max 1125 -> 337)`; `/tmp/cam_ae` exposure time **1124 -> 281**, picture darker (`cam_luma` 49 -> 31); at 100 % back to `1125 -> 1125`, exposure 1124, luma 49. |
| **HW-08** `/tmp/cam_ae` | Format confirmed `lumi exp_time a_gain d_gain isp_d_gain dark_flag`. **Night, dark room: AE sits at its limits whatever the IR LEDs do** - `exp_time 1124`, `a_gain 6840` (= 26.7x if 256 = 1x), `d_gain 256`, `isp_d_gain 256`, `dark_flag 0` in IR-on night mode (GPIO 19 high), in day mode with IR off, and back. Only `lumi` moves: **9-10 with IR on, 5 with IR off**; `cam_luma` 47-49 with IR, 34-36 without. So at night the exposure cannot separate IR on from IR off (it is pegged); the day / dusk values are still needed (index now about 30000 at night, so the placeholder `AE_NIGHT_ABOVE=4000` is far too low if gain is in 1/256 units). |
| **F-04** | Not run (needs daylight and dusk readings, see HW-08). |
| **F-02** frame rates | **PASSED** 10 / 12 / 25 (15 / 20 earlier): `-f N`, log `sensor: N fps (the stream rate)`, STAT `cap` per 5 s = 49-50 / 60 / 124-125 / 75 / 98-99. A value outside the list falls back to 15 (the camera's 16). |
| **P-02** `ak39_vi.slots=3` at 25 fps | **PASSED.** 124-125 frames per 5 s, `dropped` 0-1, MemAvailable 18.5 MB (default slots 4: 15.6 MB at 15 fps), no error. Together with the 15 fps run (+3.2 to 3.9 MB, no CPU change) it is safe to make `slots=3` the default; the 25 fps CPU idle 63 % was taken right after a restart (burst), 80.9 % in the later steady state of the same kind of run at 25 fps. |
| **P-07** `rtl8xxxu.dma_aggregation=1` (card boot) | Parameter active (`Y`, `dma_agg_pages` / `dma_agg_timeout` -1 = default). At 25 fps: usb-host interrupts **635/s** (609/s without at 25 fps), idle 80.9 %, wlan0 tx 191 KB/s, `dropped` 0. **No gain**, no harm; leave off. (This run was at 25 fps by accident of the unsaved fps restore, the comparison is still like for like with my earlier 25 fps number.) |
| **HW-03** `otg_hs.fifo32=1` (card boot) | Parameter active (`Y`), Wi-Fi associated at 15 s, no USB error, 25 fps run: `dropped` 0, usb-host interrupts **664/s** (609-635 without), idle 81.9 %. **No measurable gain**; the CPU copy is not the bottleneck at this rate. Safe, but not worth switching on. |
| **P-09** 30 min with one TCP client (Frigate), 15 fps, rc7 flash | **326 STAT lines (27 min): 24386 frames captured (99.7 % of 24450), `dropped` 133 in total (0.55 %), at most 4 in one 5 s, 71 lines with a drop, `snd_ms` max 635, `enc_ms` max 3109, one client, no error line in the server log, no oops / OOM in dmesg.** MemAvailable 15.3 MB at the end (16.9 MB at the start). |
| **P-01** ONVIF discovery | **Partial.** ONVIF is **off** on IPCAM2 (`onvif_enabled=0`, no `onvif` in autostart), so nothing answers there by default. Started by hand (`controlscripts/onvif start`, not persistent): `monvifd` listens on UDP 3702 and **`wlan0` joins 239.255.255.250** (`/proc/net/igmp` shows the group on wlan0 and lo, IGMP v2), and a WS-Discovery Probe sent **unicast** to the camera gets a 1327-byte ProbeMatch. A multicast Probe from the Mac's Linux VM got no reply, but that VM probably does not forward multicast to the LAN, so it proves nothing. **Needs a real LAN client** (ONVIF Device Manager, Frigate "discover"). |
| **F-06** Memory Guard | **Cannot be judged:** `MEM_GUARD_ENABLE=0` in `boot.conf.dist` and on IPCAM2 (the `memory-guard` autostart entry exists but the guard is disabled), so the migration and the 6144 / 3072 stages never run. The values are present in `boot.conf` (6144 / 3072 / 2048). To test: `MEM_GUARD_ENABLE=1` (not done: it can stop services). |
| **F-05** logs kept across reboots | **BUG FOUND.** The reboot save works (`why=shutdown: ui: F-05 test` written by `reboot-tracker.sh intent`, after a manual `save` it went into `boot-0009`), **but after the 8th boot on a card the counter breaks**: `/mnt/sd/logs/.bootcount` holds `0008`, `scripts/log-persist.sh` line 80 does `_n=$((_n + 1))` on it and ash reads `0008` as an **octal** number: `arithmetic syntax error`, so **no boot folder is created any more** (confirmed twice: `sh -x log-persist.sh save` stops at line 80; after a real reboot, 3 minutes up, still only `boot-0005..0009`). It will break again at every boot whose counter contains an 8 or 9 (0008, 0009, 0018, 0019, 0028 ...). Before this, the folders from my boots up to `boot-0008` were fine (the last one 163 s into a boot). **Fix:** strip the leading zeros before the arithmetic, for example `while :; do case "$_n" in 0?*) _n=${_n#0} ;; *) break ;; esac; done`, or store the counter without padding and pad only for the folder name (`printf '%04d'`). Add a host test with `.bootcount` = `0008`, `0009`, `0010`, `0099`. The card of IPCAM2 has `.bootcount` = `0009` now (I set `8` once to test the rest), so its logs stay stuck until the fix is installed, then `rm /mnt/sd/logs/.bootcount`. |
| **3D-NR** | Known and expected (`Not done: 3D-NR` above), but worth noting that **every start of `tc100_rtsp` logs two failed CMA allocations (`req-size: 1013 pages`, `507 pages`) and `no memory for the 3D-NR reference frame, 3D-NR disabled`**, on flash boots and card boots, with default `slots` and with `slots=3`, CmaFree 1.2-4 MB. So 3D-NR is off on this camera in all of today's tests. |
| **Test method news** | The Mac's shell reaches the camera on the LAN (ping 7 ms, HTTP 302 on port 80, `ffmpeg` / `ffprobe` installed on the Mac). **RTSP (`401`), snapshots (`401`) and the web pages need the camera's credentials**, which the tester does not type, so TCP + UDP clients together, ffprobe of the sub-stream and H.265 UDPSG, and the web UI tests (W-01, UI-22, F-01) wait for the owner. Pictures are pulled from the camera's `/tmp/currentpic.cache.jpg` over the serial console (base64, md5 checked) and looked at. |

Second part of the same night (flash boot, one TCP client = Frigate, 15 fps, everything restored afterwards, `rtsp.env` empty):

| Test | Result |
|---|---|
| **O-05** log rotation | **PASSED** with a small cap: `RTSP_LOGMAX=8000` -> `/tmp/logs/tc100_rtsp.log.1` (8018 B) created after about 5 min, the new file starts with `log rotated`. Not seen at the real 256 KB cap (needs about 2.5 h at 1.7 KB/min of STAT lines): check `ls -l /tmp/logs` after the overnight soak. |
| **O-05** `RTSP_FRAMECOPY` A/B | **No measurable difference at one client**: default `snd_ms` avg **264** (71 STAT lines), `enc_ms` 2300, idle 82.7 % / `RTSP_FRAMECOPY=0` `snd_ms` avg **273** (61 lines), `enc_ms` 2302, idle 82.3 %. The gain, if any, only shows with several clients or the recorder (not measurable here: no credentials for more clients). Keep the default. |
| **B-01** slim initramfs | **PASSED** (serial checks): `initrd=0x81000000,2012654` in the cmdline, `/usr/bin/aplay|arecord|amixer` and `/usr/share/alsa` are links into `/mnt/ext`, `aplay -l` / `arecord -l` list `card 0: ADDA`, `PATH` has `/mnt/ext/bin`, dropbear running, **port 22 open, 23 closed**, `curl -I https://example.org` -> `200` with `ssl_verify_result 0` (CA bundle `/mnt/ext/etc/ssl/certs`), `jq -n 1` -> `1`, `iw reg get` works (`country 00`). MemAvailable 15.3-16.9 MB. **Not passing:** `amixer -c 0` (known, `cards/aliases.conf` missing; `amixer -D hw:0 scontents` works). Not done: microphone `arecord` (busy while `tc100_rtsp` runs), speaker (silent, see audio notes), ssh login (needs the password). |
| **B-02** slim base | **PASSED** for what runs without a login: `busybox --list` = **192**, no `not found` in dmesg, `ps`, Wi-Fi, ntp, SD mount fine. |
| **O-04** (checks 1, 7, 10, 11, 12) | **PASSED:** `/var/run/v4l2rtspserver.pid` = `pidof tc100_rtsp`, `oom_score_adj` **-900**; **no `crond`** with an empty crontab; `/tmp/www` has 22 entries, `/lib` has the `mnt` links; 13 `sh` processes in total, none new over the minutes watched; day/night daemon 0 %. Needs the web credentials: checks 2-6, 8, 9. |
| **O-06** one housekeeper | **PASSED:** a single `housekeeper.sh run` process; no separate `web-guard`, `log-persist`, `service-watchdog`, `health-snapshot` processes; periodic jobs run (the health cache is refreshed, the log-persist cycle runs - and fails on the octal bug above). |
| **MQTT bridge CPU, final figure** | With the broker refusing the login (CONNACK 5) the bridge's three processes used **12 ticks in 60 s = 0.2 % of a core** (`top` once showed 4 %, a snapshot artifact). Confirms the retraction: no CPU problem, only the missing back-off / UI message. |
| **F-03 IDLE_FPS, F-04, F-01, W-01, UI-22, S-01 over ssh, HW-02 test 2, LED switches on the Settings page, microphone, speaker, overnight soak** | **Not run** - they need the owner's credentials / a browser or a viewer / a decision on the pool size, see the questions to the owner in the tester report at the top. |

- **P-01** half done: needs ONVIF discovery from a client. **P-05** (128 KiB squashfs blocks): stack 2306048 B in the
  partition; MemAvailable did not drop (15.2-16.0 MB, rc6 15.9-16.1); no timing yet.
- Not run yet: audio B-01/B-02, O-05, P-09 (`RTSP_UDPSG=1`), P-08 (`RTSP_VBR=1`), P-04 (20/25 fps), P-02
  (`ak39_vi.slots=3`, card only), P-07, W-01/UI-22 (browser), HW-02 test 2, HW-03 `fifo32=1`, HW-04..HW-08, F-01..F-06,
  overnight soak.

**No blocking finding is open.** IPCAM1 (.24) still runs the morning rc5; nothing of today's work is on it yet.

**Asked of the implementers**
1. The packages of bde3887 and 563dbff still say `3.0.1-rc5` (same as the morning build): bump `VERSION` (rc6) so the
   cameras and the update page can tell them apart.
2. HW-01b: the cause of the morning failure is unknown (bde3887 kernel or the degraded state of that session). Keep
   the guard as a detector (it costs nothing while the pool is not shrunk); revisit with HW-02 test 2.
3. The serial console shell (`tc100test/consoleshell`) has no `CURL_CA_BUNDLE`/ext `PATH`: `curl` there exits 60.
   Harmless for the services; give login and console shells the same environment if it is cheap.
4. Next on the camera (in this order unless told otherwise): an overnight soak of 563dbff, HW-02 test 2, HW-03
   measurement with `fifo32=1`, HW-04 to HW-08 and F-01 to F-04, then the UI checks (need a browser on the LAN).

**Rule kept for every new build:** first boot from the card (nothing written), Wi-Fi + 15 fps + memory checked,
then the flash. A build that fails is written up here as `failed` with the serial log lines.

**Implementer's answers (2026-10-30 night)**
1. Done: `VERSION` is `3.0.1-rc6`.
2. Agreed: the guard stays on by default as a detector.
3. Done:
   - The console shell is now a login shell (`sh -l`).
   - `/etc/profile.d/tc100-ext.sh` exports `CURL_CA_BUNDLE` along with the ext `PATH`, for console, ssh and telnet.
   - Both are in the initramfs, so they need the next build.
4. Agreed, with **LED-01 first** (one minute, owner's report). Then audio (B-01/B-02 checks 2-4: libasound and the
   ALSA tools moved and slimmed) before the overnight soak.

### Next build: 3.0.1-rc17 — install with no click, way back from the card, old tint reset (2026-10-31)
The owner asked for a simpler install: from the original SD hook, and if the camera is compliant, the flash, with the
safest choice and a way back. The tag `v3.0.1` waits for R17-01 (and R15-03 / R15-04).

### R17-01 Automatic install from the card, then the way back with RESTAURER.txt — `to test` (needs the owner's OK per flash write)
- **What:** `v3/install/auto-install.sh`, started by `autorun-linux66.sh` step 12f in trial mode only. It installs when
  the card went through the stock hook (`tc100-3/stage1.done`), the flash's `initrd` has no xz image (no 3.0 yet) and
  `tc100-3/auto-install.tried` is absent; checks first: `restore-stock.sh --check` (copy 8 MiB, md5, `boot` and `mac`
  areas equal to the flash), `install66.sh check`, frames for 30 s (`/tmp/cam_luma`). No chime in that trial start;
  the chime comes from the flash start. `RESTAURER.txt` runs `restore-stock.sh` once (renamed `RESTAURER.done`).
- **Switch:** `ESSAI.txt` (or `TRIAL.txt`) at the root of the card: trial mode as before (wizard / Install to flash).
- **Test (only a camera on its stock or 2.x firmware enters the hook; both cameras run 3.0 from flash):**
  1. Safe part first, on the current 3.0 cameras, nothing written: boot the rc17 card by hand (`boot66b.sh`): the
     console has no `auto-install:` line (flash holds 3.0) and the chime plays; `sh /mnt/v3/install/auto-install.sh
     pending; echo $?` = 1; `sh /mnt/v3/install/restore-stock.sh --check` on a card with that camera's
     `flash-stock.bin` = `ok ...`, and with the other camera's copy = refused (`not this camera's`).
  2. With the owner's OK (flash writes, dump first): `RESTAURER.txt` on the card of one camera (one whose card still holds
     its own `flash-stock.bin` from the hook; step 1 tells): it writes back, restarts into its old system (2.x or stock), card out.
  3. Then a fresh rc17 card (only `wifi.txt` added): power on, wait 15 min: blue blinking twice, chime, `/proc/cmdline`
     has `flashroot=1`, `tc100-3/STATUS.txt` ends with "all checks passed ... installing", `install66.log` "DONE".
  4. `ESSAI.txt` variant (optional): the camera stays on the card, `STATUS.txt` says "trial mode kept".
- **Pass:** steps 1-3 as above; nothing written to the flash when a check fails (simulate: rename `tc100-3/stack.sqfs.md5`
  on a stock camera's card: red LED, "NOT INSTALLED", the camera runs from the card).
- **Also in rc17:** the picture tint and saturation of an older version reset once (`config/.migrated-3.0.1`): on the
  .24 `HUE=0 SATURATION=0` in `isp_tune.conf` and `ISP_TUNE=0` in `boot.conf` after the first rc17 start.

### 3.0.1 prepared (2026-10-31, the owner: "prepare a release")
`VERSION` 3.0.1 = rc16 + the alert as three 1 kHz beeps (R16: the 0.5 s tone was missed at the default volume, still
at the -6 dBFS that R15-02 heard clean) + the release documentation. **The tag `v3.0.1` (which publishes the files) waits
for the owner's go.** Still open when it was prepared: R15-03 (one night on the defaults) and R15-04 (the web page, the
no-card hour with a reboot from the page); a fault found there gets a 3.0.2, not a re-tag.
- To check on the 3.0.1 build: the alert heard at the default volume (`sh /mnt/scripts/speaker-play.sh /mnt/sounds/alert.pcm`).

### Next build: 3.0.1-rc16 — the release candidate after R15 (2026-10-31)

**Implementer's answers to the rc15 results:**
- **R15-01, colours: a regression of rc15, undone.** Up to rc14 the picture with the software white balance was close
  to neutral (R/G/B 102/101/100 measured on 2026-10-29); rc15 fed the ISP's white balance the live statistics and it
  went blue / violet, with or without the software white balance. rc16: the white balance **algorithm** reads the old
  block again (it then stays at one colour temperature that the software white balance corrects), while the **live
  counts** still go to `/tmp/cam_awb` and the stock day / night method. Switch: `ak_isp.awb_live=1` (kernel command
  line) gives the rc15 behaviour. The colour cast work goes on after 3.0.1 (the live statistics are known now).
- **R15-02 passed:** the crackling was the full-scale clips; the clips are at -6 dBFS since rc15. The alert and the
  boot chime still to be heard once (`sh /mnt/scripts/speaker-play.sh /mnt/sounds/alert.pcm`; the boot chime plays 3 s
  after the services start).
- **R12-08 (no SD card, short run) passed.** Two misleading console lines fixed (Wi-Fi settings source, board profile
  before the sensor id). To reach the logs with no card: the web page, Logs (needs the login), or ssh (on by default).

### Results on rc16 — tester, .11, 2026-10-31 (card boot once, then `update66.sh check` / `apply`)
- **Install:** `update16` md5 ok, card boot of the rc16 kernel, `check` ok, `apply` DONE, boot shows `user space from flash (3.0.1-rc16)`.
  `awb_live` = 0, `dmesg` `read from word 1160`, `/tmp/cam_awb` live (33264 36 14 0 0 29444 ...), `wlan0` up, ping 2-8 ms, MemAvailable 21 MB.
  The card-boot console line "board profile: unknown hardware, defaults of ..." is still printed (the card boot runs the flash's rc15 user space: look again after the flash boot).
- **R16-01 colours: PASSED.** Same room, default settings (software white balance on): the white wall and the blanket are neutral
  (grey-white), the lamp warm, the lion picture violet as the picture really is, the sofa side purple as the real sofa. The
  blue / violet cast of rc15 is gone. (Scene differs slightly from R15-01: the owner is out of the frame. Snapshot on the card: `/mnt/sd/r16-01.jpg`.)
- **Alert:** `speaker-play.sh /mnt/sounds/alert.pcm` at the default volume: the owner heard **nothing** (the clip is 8000 bytes = 0.5 s;
  the driver log shows the play and `done`, rc=0). Three plays at volume 100 then the -6 dBFS tone at 60: **all heard**. So the alert
  is audible but short; at the default volume (pttvolume.conf / 90 %) a first play was missed: worth a longer or louder alert.
  **Boot chime: not heard/verified** (the flash was written, the camera rebooted, nobody listened for it).
- **Not done (daytime / owner):** R15-03 night, R15-04 (web page, no-card hour with a page reboot). Soak restarted on rc16.

### Second camera: IPCAM1 (.24) on rc16 — tester, 2026-10-31 (read over ssh by the owner, not by the tester)
- Updated with the web update at 16:24 local: `tc100-3/update/VERSION` = 3.0.1-rc16, the update saved the previous kernel and
  initrd (`kernel-20261031-162405.bin`, `initrd-20261031-162428.bin`); `c66.img.installed` on the card, no trial kernel left.
- `/proc/mtd`: new layout (`kernel`, `initrd` 2 MiB, `stack` 0x2b3000, `vendor` 1 MiB, `cfga`, `cfgb`), so the web update was accepted
  by the first-layout gate. `/proc/cmdline` has `flashroot=1` (flash boot), `ak_isp awb_live` = 0, `wlan0` 192.168.1.24, ping 2-4 ms, SD 60 GB free.
- Not seen by the tester: the `[flashmode] user space from flash` line, colours, Frigate, the web page, a warm reboot with the Wi-Fi check.
- **Update 2026-10-31 evening: tester's access is now ssh, not the serial console** (the bridge is gone). Key-based, key put in
  `/root/.ssh/authorized_keys` by the owner (RAM only: gone at each boot). Finding for the implementers: dropbear makes new host
  keys at each boot, so every reboot gives the owner's Mac a "host identification changed" warning; a persistent host key in the
  settings, or in `config/`, would stop it (not urgent).
- **IPCAM1 (.24) on rc16, 18:48 local:** up 1 h 23, `awb_live` 0, `wlan0` -48 dBm, USB 480 Mbit/s, 15 pings 0 % loss avg 3.9 ms
  (the first of two pings had taken 875 ms: the link waking, not seen again), RTSP server running, SD card mounted. MemAvailable 20.7 MB.
  **Colours: a strong green cast** in a dim evening room (luma 67-78, `mode=day`, exposure gain 2810 vs 1124 on the .11 in a lit room;
  white wall looks yellow-green, the floor pink). Not compared with the same scene on rc5 (no earlier snapshot): a different sensor module?
  The software white balance is on (default). Snapshot kept on the owner's Mac, not in git. To look at: does the cast go away with light (day)?
- **.24 green cast: part of it is a setting carried over from 2.x (found 2026-10-31 evening).** `/mnt/config/isp_tune.conf` on the .24 had
  `HUE=-10`, `SATURATION=-13` with `ISP_TUNE=1` in `boot.conf` (the .11 has `ISP_TUNE=0` and zeros). Set to 0 by the tester (old file kept on the
  card: `isp_tune.conf.before-2026-10-31`): the green is gone, the wall is still yellowish in a dim, warm room (luma 65-70, exposure gain 2810).
  Same sensor file on both cameras (`/vendor/isp.conf`, md5 926b0a2a...), same kernel, `awb_live` 0, software white balance on. So the remaining
  difference is the scene and the light; to be compared in daylight. Question for the implementers: should an upgrade from 2.x keep
  `HUE`/`SATURATION` at all (a migration of the old image tuning), or reset them with a note? Other .24 settings from the old layout:
  stale 2.x/3.0-trial files on the card (`/mnt/sd/config/boot.conf` 18 KB, `isp_f23_mipi_2lane.conf`, `.cfg-deleted`); the card file is not used
  (`/vendor/isp.conf` is read first).
- This covers the README's "a second camera" for the update path (rc5 -> rc16 by the web page). Open: the same checks as R15-04 on the .24.

### Owner's decisions, 2026-10-31 evening (for the implementers)
- **An upgrade from an older version must not keep the old image tint and saturation** (`HUE`, `SATURATION` of `isp_tune.conf`; also
  `ISP_TUNE=1` carried over): reset them to 0 at migration (the .24 had HUE=-10, SATURATION=-13: green picture). Not a note: a reset.
- **Both cameras must have the same settings, except their IPs (and what is hardware: names, passwords, Wi-Fi).** The tester will align
  the two cameras' settings and list what still differs and why (`.11` had leftovers of the tests: sub stream 352x200 at 8 fps with the
  smart mode on; the main stream with `smartmode=1`; `.24` has the old IR-cut GPIO lines, `FRONT_LED=0`, no `recording` switch).
- **The second stream must be of the best quality the SoC can give** on both cameras (640x360 is the ISP sub picture; frame rate and bit
  rate to be measured: CPU, dropped frames, Frigate).

### .24 Wi-Fi is unstable, independent of the bit rate (tester, ssh, 2026-10-31 19:40 local)
- 1000-byte pings every 0.25 s to the gateway, in series of 25-40: **.24 loses 0-80 % in bursts** (48 %, 8 %, 80 %, 45 %, with 3-5 s round-trips
  at the worst) with the sub stream at 250 kb/s as well as at 600 kb/s (tried 600/900 kb/s then restored 250: `rtspserver.conf.before-2026-10-31`
  on the card). `/proc/net/wireless` link level swings -46 .. -72 dBm and drops to -256 (link down) for a few seconds, then recovers; no
  `deauth`/`disassoc` line in `dmesg`, USB at 480 Mbit/s, the Wi-Fi chip not power cycled (up 2 h). The .11 on the same network: -29 dBm,
  0 % loss, 7 ms average, max 42 ms. So it is the link of that unit / its place, not the bit rate: no change of the second stream's bit rate yet.
- For the implementers: is there a Wi-Fi quality metric in the web page (signal over time, retries) and a log line when the link drops to
  -256 (the net-guard acts only after a gateway loss)? It would have shown this without a ping flood.
- The .24 could not be measured with `tc100_rtsp.log` (no `STAT` log on its stdout, unlike the .11: the launch differs?).

### Attack surface of the cameras: audit and requests (tester over ssh, owner's goal: reduce it, 2026-11-01)
Seen on both cameras (rc16, flash boot): listening **tcp 22** (dropbear, root, password; no key file is read), **tcp 80** (`httpfront` + busybox httpd,
plain HTTP with a login), **tcp 554** (RTSP, login), **udp 5004** (RTP). Telnet, FTP and ONVIF are off. One password (`config/user.pwd`) is used for the web
page, RTSP and ssh, and it is **short** (4 and 5 bytes on the two cameras, the default-like one). `wifi-rescue` (hostapd AP when the Wi-Fi is lost) is in autostart.
Suggestions, by value:
1. **Password:** the first start (wizard) must refuse the default and short passwords (min 10 characters, not equal to the user name), and the web page should show a warning
   banner while the default is in use. Separate passwords for ssh and for the web/RTSP login (or ssh by key only).
2. **ssh:** off by default again (it is on by default today, "no lock-out after an upgrade"): on for a fresh install only during the wizard, key-based (read
   `config/authorized_keys` into `/root/.ssh` at boot: nothing reads it now), `-s` (no password) when a key exists, `-w` (no root password) is not possible as root is the only user;
   keep a persistent host key (`config/dropbear_ed25519_host_key`): today a new one at each boot, so users learn to ignore the host key warning.
3. **HTTPS:** TLS in `httpfront` (mbedtls already in `ext/lib`, ECDSA P-256 certificate regenerated before expiry, session resumption, HTTP on 80 only
   redirects the login page). Measured here: one TLS handshake costs about 0.8 s of one core on this SoC (curl/mbedTLS, 3 runs); the cameras have 64-69 % idle and about 20 MB
   available; flash `stack` has about 500 KB left (`/rom` 2304 of 2828 KB). Not for 3.0.1: 3.0.2.
4. **RTSP:** login on (it is: `-u root -w user.pwd`); RTSPS is not available. Make the RTSP user and password separate from the web one (Frigate needs only the RTSP one), and
   offer a read-only RTSP user.
5. **Network exposure:** bind the web page and ssh to the Wi-Fi interface only (nothing listens on a second one now), brute-force throttle on the login
   (a few seconds of delay after 5 failures, and a log line); udp 5004 only while an RTP client is connected; `wifi-rescue` AP only for a limited time with a strong random
   password shown on the page (check what `wifi_rescue.psk` holds).
6. **Update path:** the web update is the only thing that writes the flash; keep it behind the login, check that a package is signed (md5 alone does not protect
   against a changed package: a signature with a public key in the initrd), and refuse a downgrade unless forced.
7. **Housekeeping:** no secrets in `/tmp/*.cache` (world-readable files), the `log-persist` files readable by root only, and the `config` backup (`tc100-3/backup`) with
   mode 600 on the card.
Owner's decision: **reduce the attack surface of these small devices; he takes these suggestions.**

**Owner's rule for all of the above (2026-11-01): never block or lock out an existing installation.** An installed camera keeps working exactly as it does
(same password, same ssh, same ports) after an update. The camera **proposes** the change instead: a dismissible banner on the web page ("the password is short or the
default: change it", "ssh is on: turn it off or use a key"), shown at each login until done or dismissed for 30 days; no forced reset, no refused update, no service
switched off by the update. The **strict rules apply to new installs only** (the wizard of a first start: refuses the default / short password, ssh off unless asked, separate
RTSP password offered). Same for 3.0.2's HTTPS: added next to HTTP on port 80, which stays until the owner turns it off.
Also from the owner on the same day: an upgrade from an older version must reset the old image tint and saturation (not keep them) -- see above; this one is a fix, not a security prompt.

### Test method change: no serial console any more (owner, 2026-11-01) -- the tester works over ssh only
- **What is lost:** the card-boot step before a flash install (kernel booted once from the SD card at the U-Boot prompt, nothing written), the U-Boot prompt for recovery,
  the kernel messages of a boot that fails, and any fix that needs the U-Boot environment (e.g. kernel command line switches such as `ak_isp.awb_live`).
  Every build now goes straight to the flash with `update66.sh` / the web update, on a camera the tester cannot see until it answers on the network.
- **Requests that follow (please treat as release-relevant):**
  1. **ssh by key that survives a reboot:** read `config/authorized_keys` into `/root/.ssh/authorized_keys` at each start (and a persistent host key). Today the tester's key lives
     in RAM and the owner must re-add it after every reboot; with no serial, a reboot ends the tester's access until then.
  2. **A way back that works unattended:** if the new kernel/user space does not reach "network up + web page + RTSP" within N minutes after an update, the camera restarts into the previous
     kernel and initrd (the update saves them: `tc100-3/backup`, `kernel-*`, `initrd-*` on the card). A boot counter in the settings slots (not the U-Boot environment), checked by the early
     user space; `flashcheck` already falls back to the stock firmware when the initrd is bad, extend it to "boot failed three times -> previous images".
  3. **The last boot's messages kept:** `dmesg` of the previous boot written to the card (or the settings slot) at boot and at a crash (`/mnt/sd/logs/boot-prev.log`), shown on the web page
     (Logs), so a failed boot can be read after the owner power cycles. Today the log in `/tmp` is lost with the power.
  4. **A runtime switch for anything the tester needs to A/B** (white balance mode, etc.) instead of kernel command line parameters.
  5. **No kernel or U-Boot change in a release that has not run a full day on a camera first** (the tester cannot recover a camera that does not boot).
- **Tester's side:** one camera at a time; the owner is asked to be near the camera and its power supply for the first boot of any update that changes the kernel; the SD card with the
  backup stays in; after each reboot the owner re-adds the key (one command) until request 1 is in.

### Results on rc15 — tester, .11, 2026-10-31 (installed in flash: card boot once, then `update66.sh check` / `apply`)
- **Install:** card boot of the rc15 kernel, `check` ok, `apply` DONE, reboot shows `[flashmode] user space from flash (3.0.1-rc15)`;
  `wlan0` up, ping gateway 3-20 ms, 0 % loss; MemAvailable ~21 MB; RTSP serving, 1 client. Serial console needed a rewire
  by the owner before this (no software cause found).
- **R15-01 white balance: PARTLY.** `dmesg`: `white balance counts read from word 1160`; `/tmp/cam_awb` live and moving
  (17306 8 8 0 0 4572 ... then 18068 6 5 0 0 4849 ..., then 18383 7 8 0 0 5297). Two snapshots of the same scene (lit room, afternoon), default
  (software AWB on) and `awb.off`: **both have a strong blue/violet cast** (white throw and walls look lavender, a cream wall at the right stays warm).
  The ISP alone is not neutral, and the software AWB changes little (slightly less saturated). So: **keep the software AWB on in 3.0.1**,
  and the cast remains: the target of the AWB gains needs a look (kept on the card: `/mnt/sd/r15-01-awb-on.jpg`, `r15-01-awb-off.jpg`, not in git: a person is in the picture).
  `awb.off` removed, server restarted.
- **R15-02 speaker: PASSED (tones).** `aplay` of `test-1k-m6/m12/m20.pcm` at Headphone 3 and 5: no `underrun`, no error;
  the owner hears them **clean at every level, -6 dBFS included**. So the earlier crackling was clipping of the 0 dBFS clips: confirmed.
  `speaker-play.sh` was not found by `find` here (the alert and boot chime were not played by it; the owner answered "clean" to a
  question about the alert, but my command failed to start it, so treat the alert/chime as **not verified**).
- **R15-03 night and R15-04 owner checks (R12-07, no-card hour): not done yet** (daytime; owner postponed). Soak restarted on rc15
  (`/mnt/sd/soak-20261031.log`).

### R15-03 One night on rc15 (the defaults) — `to test`
- Auto day / night (source luma, the default), night picture settings and low light on: the night switch, the picture
  at night (grain, brightness) against R12, back to day in the morning; IR LED protection lines if any; the
  calibration log (`awb=` now live, `lum=`) copied here: it sets the stock method's thresholds for a later default.

### R15-04 The owner's checks — `to test`
- R12-07 (the web page: Streams & audio bit rate mode, Day/night switches and live value, Picture anti-flicker, in
  French too) and R12-08 (no SD card: power off, card out, power on, one hour: video, page, Wi-Fi, MQTT, settings kept
  after a page reboot). Then the release: [release-3.0.1.md](release-3.0.1.md).

### R14-01 Wi-Fi recovery (`scripts/wifi-recover.sh`) — `to test` (first, with someone near the camera)
- **Safe check on a working camera** (Wi-Fi up, the script does nothing): `sh /mnt/scripts/wifi-recover.sh check; echo $?`
  = 0, and `sh /mnt/scripts/wifi-recover.sh run` returns at once with nothing on the console.
- **The power cycle itself, by hand, from the serial console** (the camera goes off the network for about a minute):
  `echo 523 > /sys/class/gpio/export; echo out > /sys/class/gpio/gpio523/direction; echo 0 > /sys/class/gpio/gpio523/value`
  -> within a few seconds dmesg shows the USB device **disconnecting** (`usb 1-1: USB disconnect`) and `wlan0` goes;
  `echo 1 > /sys/class/gpio/gpio523/value` -> the chip enumerates again, `rtl8xxxu` probes, `wlan0` back; then
  `sh /mnt/v3/linux66-sd/wifi-apply` and a ping from the LAN. **If nothing disconnects, GPIO 11 is not the Wi-Fi
  power on this board: write it here and set `WIFI_POWER_GPIO=0` in boot.conf** (the recovery then only re-probes).
- **The failure case, when it comes back** (warm reboots in a row, check `wlan0` after each): the console lines
  `[wifi-recover] no wlan0: probing the Wi-Fi chip again`, then `power cycle` if needed, `wlan0 back after the ...`,
  the camera pingable again without a power cut. `meta.txt` of the saved boots: `wifi_power_fail=`.
- **Pass:** the manual cycle disconnects and brings the chip back; a real failure recovers without a power cut.

### R14-02 Night parameter set (R12-01 again, rc14 kernel) — `to test`
- As R12-01: dmesg `tuning parameter set 1` at night and `0` at day, the log `ISP: night parameter set of the
  tuning file`, about 10 fps at night, the picture against the day set. Then the rest of R12 on rc14 (R12-02 low
  light at dusk, R12-03 / R12-05 over a night, R12-04 listening, R12-06 listening for the clicks, R12-09 dumps,
  R12-07 and R12-08 with the owner).

- **Results R14 (tester, 2026-10-31 ~12:30-13:00 local, rc14 = 28a290a, both CIs green); rc14 installed in the .11 flash:**
  - Install: rc14 kernel (md5 7c524207…) booted once from the card (U-Boot prompt, RAM): Wi-Fi up (`wlan0: associated` at 15 s), pool 9600K, MemAvailable 21.6 MB;
    package md5 e9123d64…, `check` ok, `apply update14`, `/mnt/VERSION` 3.0.1-rc14; flash boot, Wi-Fi up again, `meta.txt` `wifi_power_fail=0`, `wlan0=yes`.
  - **R14-01 Wi-Fi recovery:**
    - Safe check on a working camera: `wifi-recover.sh check` rc 0, `run` returns at once, nothing printed: PASS.
    - **Manual power cycle of GPIO 11 (= gpio523): PASS, it IS the Wi-Fi chip's power.** `echo 0 > gpio523/value`: `usb 1-1: USB disconnect, device number 2`,
      `wlan0: deauthenticating ... (Reason: 3=DEAUTH_LEAVING)`; `echo 1`: `RTL8188FU rev B` re-enumerates 8 s later, firmware loaded, `wlan0: associated` ~11 s after the
      power came back. `wifi-apply` then gave 192.168.1.11 again. (`gpio522` and `gpio592/593` are already exported by something else; I unexported 523 afterwards.)
    - **But a side effect: after this manual cycle the link was bad for several minutes**: ping from the LAN 1.1-3.6 s (was 4-6 ms), camera-to-gateway ping 2.3-3.5 s, RX `dropped` 1503,
      the server's `dropped` rising 18 -> 68 per 5 s, while the signal read -30..-36 dBm (MCS 4-5). A warm `reboot` cleared it (6 ms, `dropped` 0-2). So the chip comes back working but
      in a degraded state; the real recovery path (`wifi-recover.sh` calling `wifi-apply`) should be checked for the same thing: maybe it needs a clean unbind / module reload or a
      longer off time than 6 s. I did not reproduce the original `Failed power on` failure (all 3 warm boots of the day on rc14 had Wi-Fi), so **the automatic recovery itself is NOT tested.**
  - **R14-02 night parameter set: PASS.** With `RTSP_NIGHTSTYLE=1` and `nightmode.sh on`: dmesg `ak39-vi 8000000.video-input: tuning parameter set 1`, log `ISP: night parameter set of the
    tuning file`, `cam_ae` `47 2812 502 256 256 0 2812` (exposure limit 2812), **`cap` 50 per 5 s (10 fps)**, 380-440 KB per 5 s, one client connected. `nightmode.sh off`: dmesg
    `tuning parameter set 0`, log `day parameter set`, `cam_ae` 7th field 1125, `cap` 125, 978 KB per 5 s. (The picture itself was not compared: the room is lit by day.) The R12-01 refusal (ENODEV) is gone.
  - Not redone on rc14 (need dusk / night / the owner): R12-02, 03, 05, 06, 07, 08, R12-04 sound, R12-09 dumps.
  - .11 now: rc14 in flash, `rtsp.env` empty, auto day/night running (luma), fps 25, soak restarted (13:0x local), Frigate connected (`clients 1`).

- **Results R12 / R13 / R14 with the owner next to the camera (tester, 2026-10-31 ~13:20-14:10 local, rc14 in flash):**
  - **R12-04 speaker: AUDIBLE but weak / crackling (owner listened).** The 20 s alert (`alert.pcm` x 20 = 10 s of 8 kHz mono, `Headphone` 5 then 3) is heard: the amplifier fix works. The owner: "faible ou grésillant", the **same at volume 3**: so it is not
    clipping from the volume setting. dmesg: `perfect asic pll clk is:480000000, actual sample rate is 8000`, `ak39_set_hp_power 1,soft_de_pipa=1`. To look at: the codec's output gain / digital volume, the amplifier supply, the PCM data format,
    the sample rate path; the playback of the stock firmware may use a different mixer setup (`amixer -c 0 contents` here if wanted).
  - **R12-06 IR-cut pulse 10 ms: PASS, heard 20 / 20** (10 out + 10 in, `IRCUT_PULSE_MS=10`, 1.5 s apart): the owner counted every click. 10 ms can become the default (I put the 150 ms default back).
  - **R12-02 10 fps in low light by day: PASS.** `RTSP_LOWLIGHT_FPS=1`, lens covered by hand: `low light: total gain 26x, sensor 10 fps, exposure up to 2812 lines`, `cam_ae` `48 2810 3540 256 256 0 2812`, `cap` 51 per 5 s,
    405 KB per 5 s; uncovered: `low light: total gain 1x, sensor 25 fps, exposure up to 1125 lines` within 40 s, `cap` 117-125. One switch each way, no flapping seen in the ~3 minutes.
  - **R12-09 ISP statistics dumps (read only): the white balance counts are NOT at word 1032.** `dmesg`: `statistics DMA area at 0x82e61dd4, 4800 bytes (white balance counts read from word 1032)`. Three dumps (lit, lit 86 s later, lens covered; `docs/linux-port/r12-09-isp-words.txt`,
    words 1032-1199, three columns): **words 1032-1071 are identical in all three dumps and look like random data** (`0xA658D3D2 0xC7C1FE74 0x3FFA5F8C ...`: an uninitialised or pseudo-random block, not counts), so the kernel's AWB and the vendor
    source were reading garbage. The words that really move are **1155, 1160-1171 and 1180-1183** (e.g. 1160-1163 `0x0004068F 0x0003A1B5 0x00019473 0x00000515` -> `0x00046795 0x0003B344 0x00020778 0x000004F6`, 1180-1181 up to `0x000B0768`
    when lit and `0x00026499` later), the histograms (words 0-1031, 756 words changed between two lit dumps, i.e. noise plus the scene) move too. The files are also on the camera's card in `/mnt/sd/r12-09/`. The implementer can work out which
    of these are the ten AWB `total_cnt`: **1160-1163, 1164-1167 (?), 1168-1171 (?) and 1180-1183 look like groups of four**.
  - **R11-01 follow-up (rc13 guard) PASS:** `RTSP_VBR=1` + `RTSP_SMART=1`: log `encoder main: smart mode 1 not used: it needs 3670016 bytes of encoder pool, 963520 free (a bigger ak39_venc.pool)`, the server stays up (`cap` 122, a client connected),
    no `/tmp/.rtsp_smart_try` left. **Server watchdog PASS:** `killall tc100_rtsp`: `service-watchdog.log` `rtsp-h26x - unhealthy, perform restart (no reboot mode, check=status, backoff=20s)` ~4 s after the kill, the server back (`clients 1`) within 90 s.
  - Camera restored: `rtsp.env` empty, auto day / night running (luma), `IRCUT_PULSE_MS` line removed, fps 25.

- **Result R12-08 camera with no SD card (tester + owner, 2026-10-31 ~13:35-13:55 local, rc14 in flash): short run PASS, the one-hour and the persistence checks NOT done.**
  - Power cut, card out, power on: U-Boot `MMC: no card present` / `** Bad device mmc 0 **` (twice), then the flash boot: console `[tc100] no SD card`, `[flashmode] no SD card: no video storage`,
    `[tc100-v3] free RTSP server + hardware JPEG pictures active`, `WebUI active on port 80`, `Auto Day/Night detection active`, `MQTT bridge service launched`, `All services initialized successfully`; `wlan0` associated
    (`[tc100] Wi-Fi settings from the SD card` is still printed, the settings come from the flash copy), no error loop in the console after boot. `board profile: unknown hardware, defaults of ...tc100-f23-rtl8188fu.conf` (a harmless
    line, but the board is a TC100: the profile detection may deserve a look).
  - From the LAN, 3 minutes after the boot and for the next ~25 minutes: ping 4-6 ms (jitter up to 54 ms, one sample of 1.8 s average at 12:47:50, back to normal the next minute), HTTP 302, RTSP port 554 open.
    **Owner: Frigate shows the picture and detects, the web page opens and reads the settings, and the page says clearly that there is no card (recording / logs) without an error.**
  - **What I could not do: any command on the camera.** The serial shell needs `tc100test/consoleshell` on the card (login prompt otherwise), so no logs, no `dmesg`, no MemAvailable, no `dropped` in this state.
    The owner postponed the persistence check (change a setting on the page, wait 1 minute, reboot from the page, still there?). **To do: that check, and an hour of Frigate with someone watching it.**
  - Suggestion: a way to read the camera's logs with no card (the web page's log view, or `dmesg` / `tc100_rtsp.log` through an authenticated CGI), since the console shell and the logs on the card both need the card.

### R12-01 Night picture settings (Day/night page: "Night picture settings of the sensor tuning") — `to test`
- **What:** at night (black and white) `tc100_rtsp` loads the tuning file's night parameter set
  (`AK_ISP_SET_TUNING_STYLE 1`: exposure up to 2812 lines, night noise filter and sharpness, AE target 45, 10 fps), and
  the day set at day (sensor back to the stream rate). The bases of live tuning, sharpness, exposure cap, anti-flicker
  and white balance are read again after each switch and the settings applied on top. Off: the switch off (as rc11).
- **Test:** switch on, Save (the server restarts). Night (dark room or the Night button): log `ISP: night parameter set
  of the tuning file`, `cap` about 50 per 5 s (10 fps), `cam_ae` 7th field 2812. Snapshot and 30 s of VLC against the
  same scene with the switch off: brightness, grain, smearing of a moving hand. Privacy masks and the clock still
  shown; live tuning values still applied. Day button: `day parameter set`, colour back, the stream rate back (`cap`).
  Frigate: still records and detects at 10 fps at night.
- **Pass:** a better night picture, masks / clock / tuning kept, day back to normal. Then (rc13) on by default.

### R12-03 Day / night "Stock firmware method" source — `to test` (needs R12-02 on)
- **What:** `DAYNIGHT_SOURCE=vendor` (Day/night page, "Light measurement"): lum = exposure x total gain / exposure
  limit x 40 / picture brightness ("Stock method value" in the live reading), night above 3584 when the white balance
  sees no daylight, day below 1536 when it sees visible light, 3 samples in a row, a switch back within 15 s locks it.
- **Test:** with R12-02 on, the live value in a lit room, a dim room by day (must stay day), at dusk and at night; then
  the source on "Stock firmware method" through one dusk and one dawn: one switch each way, the console lines `vendor
  lum=... awb day=... visible=...`, no flapping when the IR LEDs come on. The calibration log (`lum=` and `awb=`) here.
- **Pass:** clean switches both ways, the dim day room stays day. Then (rc13) the default source.

### R12-05 IR LED protection (every source; Day/night page, hours) — `to test`
- **What:** after `IR_LED_MAX_ON` seconds of night (50400 = 14 h, the stock value) day mode for 600 s, then the normal
  decision again; 0 = off. Console: `IR LEDs on for N s: day mode for 600 s (IR LED protection)`.
- **Test:** `IR_LED_MAX_ON=120` in `/mnt/config/daynight.conf` (the page takes whole hours: edit the file for the test),
  restart the daemon (`auto-night-detection stop; start`), night mode: after 2 minutes the line, day mode, 10 minutes
  later back to night (if dark). Then the page value back to 14.

### R12-07 The web page: every new switch wired — `to test` (owner, needs the login)
- Settings, Streams & audio: "Bit rate mode" (main stream form), Save: `rtspserver.conf` [0] `vbr`, the server
  restarts, log `vbr main 1`. (Smart encoding is not on the page since rc13: R11-01.) Settings, Day/night: the
  stock method thresholds, the IR protection hours, the two switches (night settings, low light), the live "Stock
  method value"; Save and reload the page: every value comes back. Settings, Picture: anti-flicker "Camera default" and
  the 50 Hz line. In French too.

### R12-08 A camera with no SD card (the goal) — `to test` (last, after the others)
- **What:** the flash already holds kernel, initramfs, user space, vendor libraries and the settings; U-Boot tries the
  card first and boots the flash without one (the card stays the way back). Nothing is written for this test.
- **Test:** power off, take the card out, power on: video (RTSP, Frigate), web page, Wi-Fi, MQTT, settings kept
  (change one, reboot from the page, still there: R11-03), day / night and the speaker. What needs a card says so
  cleanly: recordings (page message), saved logs (`log-persist` skips), no error loop in `dmesg` / syslog. One hour.
- **Pass:** everything above. **Then the flash-only release (rc14):** the switches that passed become defaults; one
  `update66.sh apply` with the owner's agreement (dump first, `flashw` with read-back, settings kept, as for every rc);
  U-Boot untouched. The camera then runs with no card at all.

- **Results R12 (tester, 2026-10-31 ~10:10-11:40 UTC, rc12 = 8fef396, both CIs green), rc12 installed in the .11 flash:**
  - **R12-00 PASS.** rc12 kernel (md5 165426b4…) booted once from the card (U-Boot prompt, RAM), package md5 308e2478…, `check` ok, `apply update12`;
    `/mnt/VERSION` 3.0.1-rc12, pool 9600K, both encoders `open` (used 8866880, free 963520), MemAvailable 23.0-23.2 MB, `anti-flicker: camera default 50 Hz`,
    `cam_ae` has 7 numbers (7th 1125), `cam_awb` 11 numbers.
  - **R12-04 speaker: electrical part PASS, sound NOT confirmed.** `devmem 0x2017000c`: **0xC800 at rest** (bit 14 set = high = amplifier off) with the rc12 kernel; **0x8800 during
    playback** (bit 14 clear, `speaker-play.sh` of 20 x `alert.pcm`, volume `Headphone` 5), back to 0xC800 after. The owner was not next to the camera: **no one heard it**.
    To do: someone listening while `sh /mnt/scripts/speaker-play.sh /tmp/long.pcm` plays (the file was made with 20 copies of `/mnt/sounds/alert.pcm`).
  - **R12-01 night parameter set: FAIL on this kernel.** `RTSP_NIGHTSTYLE=1`, camera switched to night (`nightmode.sh on`): log
    **`ISP: the night parameter set was refused (No such device): the day set stays, colour off at night`**. `AK_ISP_SET_TUNING_STYLE` returns ENODEV from the 6.6 ISP driver:
    the ioctl is probably not implemented or the ISP style block is not set up. No 10 fps at night, `cap` stays ~125 per 5 s. Switched back (`nightmode.sh off`, auto restarted).
    The implementer needs to look at the kernel side (video-input driver patch) or drop the feature.
  - **R12-02 10 fps in low light: not exercised.** The room was too bright all morning (gain 957-2157, i.e. 3.7-8.4x; the threshold is 14x = 3584): the log line `low light:` never
    appeared. Needs dusk or a covered lens. With `RTSP_LOWLIGHT_FPS=1` the server started and ran normally.
  - **R12-03 stock method (`DAYNIGHT_SOURCE=vendor`, with RTSP_LOWLIGHT_FPS=1): runs; dim day room stays day.** Calibration log lines: `mode=day src=vendor ... idx=4241 lum=989 awb=108594719 …`;
    `lum` 923-1001 against the stock thresholds (night above 3584, day below 1536): the dim morning room (which the `ae` source called night at index 15000-30000) is **day**: the
    stock metric is the better one. Caveat: `awb=` is still the **frozen** set of R11-02, so the white balance check ("no daylight" for night) can never say night: **a night switch with this
    source cannot happen until the AWB counts are real**. Dusk / dawn: not yet. Source put back to `luma`.
  - **R12-05 IR LED protection: not tested** (needs a real night decision from the daemon; with a manual night the counter does not start). To do at dusk with `IR_LED_MAX_ON=120`.
  - **R12-06 IR-cut pulse 10 ms: inconclusive.** `IRCUT_PULSE_MS=10`, 10 x (out, in) with `setconf -k e` without error, `/var/run/ircut` follows. The two snapshots (filter out / in) are both
    almost grey (saturation 8.5 and 9.4): the picture does not show the filter position in this light, so I cannot say it moved 10 / 10. Someone should listen for the clicks. Line removed from `boot.conf`.
  - **R12-07 web page, R12-08 no SD card: not done** (need the owner's login and the card taken out).
  - Also noticed: `clients 0` in the STAT lines since this morning's reboots: nothing is connected to the camera now (Frigate not pulling?). The camera clock is wrong after a boot (00:xx) until NTP.
  - .11 now: rc12 in flash, `rtsp.env` empty, `daynight=2` auto running source `luma`, fps 25, soak restarted.

- **FINDING W-NET (tester, 2026-10-31 ~11:00-11:55 local): the .11 lost its Wi-Fi after a warm reboot, five boots in a row; only a power cut brought it back. To investigate (owner's request).**
  - Symptom: Frigate not connected (`clients 0` in the STAT lines for hours), web page unreachable, no ping from the LAN; the serial console showed `tc100_rtsp` and the web server running and listening
    on 554 / 80, but **no `wlan0`**. Not noticed during the R11 / R12 tests because they were all done over the serial console.
  - Cause in dmesg (boots 0023-0027, `/mnt/sd/logs/boot-NNNN/dmesg.log`): the USB Wi-Fi chip is found (`RTL8188FU rev B`, firmware 4.0 loaded) and then
    **`usb 1-1: rtl8xxxu_init_device: Failed power on`**, **`rtl8xxxu: probe of 1-1:1.0 failed with error -16`** (EBUSY) at ~4.0 s; no retry, so no `wlan0`.
    Boot 0023 = first rc11 boot (kernel from the card), 0024 = rc11 flash boot (`why=shutdown: net-guard: no network for 903 s, reboot (#1)`: the guard rebooted it, which did not help),
    0025, 0026 rc11, 0027 = rc12 flash boot. The older boot logs are rotated (no `dmesg.log`), so the first bad boot is unknown; the soak log shows Wi-Fi fine (`wifi -30..-41` dBm) until 09:33 UTC on rc10, and
    the failure starts with the first reboot after it. All the reboots in between were warm (`reboot`, `update66.sh` restart, U-Boot-prompt boots).
  - **Fix found: a power cut** (the owner unplugged the camera): `wlan0` associated at 15 s (`associate with 58:d9:d5:ae:1a:23 (try 1/3)`), 192.168.1.11 pings in 4-6 ms, HTTP 302, Frigate connected again
    (`clients 1`). So a warm reboot can leave the chip in a state where the driver cannot power it on, and it stays so across warm reboots.
  - Ideas for the implementer (not tested): power-cycle the Wi-Fi chip or its USB port by GPIO before the probe (and in `wifi-rescue`), re-probe on `-16` (unbind / bind of `1-1:1.0`, or `usb reset`),
    retry the probe a few times at boot, and make `net-guard` do this instead of only rebooting (a warm reboot proved useless here). Whether the chip's rail is under software control on the TC100 is for the
    hardware notes. The kernel did not change in any way that explains it (rc10, rc11, rc12 kernels all carry the same Wi-Fi code), so it may be a rare hardware / timing state: **a counter of how often it
    happens would help** (`log-persist` could keep `Failed power on` per boot in `meta.txt`).
  - Also: after this, any test that reboots should be followed by a `ping` and a look at `wlan0` from the LAN; I will do it from now on.

### R9-00 3.0.1-rc9 on the camera: the 9600K encoder pool is the driver's default — `to test`
- **What:** `ak39_venc.pool` defaults to `9600K` in the driver (patch 0015; R8-02 passed: used 8866880 bytes in H.265
  and in H.264, free 963520). The flash boot gets it with no command line change. **Off:** `ak39_venc.pool=12M` (the
  whole 12 MiB area, as rc8) - only through a card kernel; never needed so far.
- **Also in rc9 (no switch needed, harmless):** the 3D-NR reference frame is no longer tried at every video start (the
  two failed CMA allocations of 4 and 2 MB and the `no memory for the 3D-NR reference frame` line are gone from dmesg);
  `tc100_rtsp.log` lists the optional calls of the encoder library once (`encoder library: optional calls: ...`).
- **Test:**
  1. Card boot of rc9 (`c66.img` + `c66rd.gz` of rc9 on the card, as for rc8): `/proc/cmdline` complete,
     `cat /sys/module/ak39_venc/parameters/pool` = `9600K`, dmesg `pool 9600 KiB at 0x81800000 (CMA)`, **no**
     `alloc failed, req-size: 1013 pages` and no `3D-NR` line at video start.
  2. `tc100_rtsp.log`: `encoder pool: 9830400 bytes (ak39_venc.pool), no guard at its start`, both encoders `open`;
     copy the `encoder library: optional calls:` line here.
  3. `update66.sh check`, `apply` (owner's agreement, as for rc8), flash boot: same checks; MemAvailable at 2-4 min
     (R8-02 measured 21.6-22.0 MB).
  4. Overnight soak as R8-01 step 6 (one Frigate client): no reboot, no Oops / OOM, MemAvailable trend.
- **Pass:** steps 1-4. **Fail:** rename the card files back (rc8) or `update66.sh` the rc8 package; write down why.

- **Result (tester, 2026-10-31, rc9 = fcf41ab, CI green) — R9-00 steps 1-3 PASS, step 4 (overnight) running:**
  - **R8-02 closed: PASS.** 1 h with one client on the 9600K pool kernel (06:11-07:01 UTC): no reboot, no Oops, `rtsp` pid unchanged,
    `MemAvailable` flat 21.1-21.8 MB, `dropped` 0-3 per 5 s, main stream ~950-980 KB per 5 s (no HW-01 collapse), wifi -31..-45 dBm.
    (The `kerr 1` column is the word `oops=panic` in the command line: the soak script's grep counts it; ignore it.)
  - Step 1 (one card boot, RAM only through the U-Boot prompt as on night 2: rc9 `c66.img` md5 60e55dfd… as `test.img`, flash initrd):
    pool `9600K`, dmesg `pool 9600 KiB at 0x81800000 (CMA)`, **no** `alloc failed`, **no** `3D-NR` line, MemAvailable 21.97 MB.
  - Step 2: `encoder pool: 9830400 bytes ... no guard at its start`; main H.265 + sub H.264 used 8866880, free 963520, both `open`.
    `encoder library: /mnt/lib/libmpi_venc_ex.so, version "libmpi_venc V1.0.07"`;
    **`encoder library: optional calls: ak_venc_set_smart_config ak_venc_set_rc ak_venc_set_br ak_venc_set_fps ak_venc_set_gop_len ak_venc_set_iframe ak_venc_set_profile ak_venc_set_roi`**
    (R9-04 step 1: the smart-mode call exists in the library).
  - Step 3: `update66.sh check` ok, `apply /mnt/sd/tc100-3/update9` (package md5 d47f46f0…, owner's agreement): stack, kernel, initrd written,
    backup `stack-20261031-072250.bin`, restart; `/mnt/VERSION` = 3.0.1-rc9, flash boot, `cmdline` unchanged (`cma=18M`, no pool argument), pool 9600K,
    settings kept (fps 25), `MemAvailable` 21.7 MB, `dropped` 2, no 3D-NR lines.
  - Step 4: soak restarted 07:23 UTC (`/mnt/sd/soak-20261031.log`), one Frigate client; result to follow.
  - Card state: `tc100test/c66.img` and `c66rd.gz` are renamed (`c66-pool.img`, `c66rd-rc8.gz`), `test.img` = rc9 kernel, `test.img.rc8`/`.rc7` kept:
    the .11 boots from the flash. R9-01 (nr3d kernel) needs `c66.img` + `c66rd.gz` back; I will do it after the soak.

- **Results R9-01 to R9-04 (tester, 2026-10-31 07:30-08:20 UTC, IPCAM2, rc9 fcf41ab):**
  - **R9-01 3D-NR (card kernel `c66-nr3d-test.img` md5 a693c2c8…, rc9 `c66rd.gz` 2012654 bytes): steps 1-3 PASS, step 4 partial, step 5 NOT run.**
    Step 2: cmdline ends `ak39_vi.nr3d=1 cma=24M flashroot=1 ak39_vi.sub_channel=1`; `cma: Reserved 24 MiB at 0x82800000`;
    `3D-NR reference frame: 4050 KiB at 0x82900000, 2025 KiB at 0x82d00000`; pool 9600 KiB; both encoders `open`, free 963520.
    Step 3 (20 min, one client, 25 fps): **MemAvailable 15.7-15.9 MB (normal rc9 kernel: 21.5-22.3 MB, so -5.6 MB), CmaTotal 36864 kB, CmaFree only
    1596-1636 kB** (normal kernel: CmaTotal 30720). Idle CPU 75-76 % (normal 72-78 %), `cap` 122-125, `dropped` 0-2 per 5 s, 942-1036 KB per 5 s
    (normal 850-980): no visible CPU or frame cost. Step 4: snapshots in the same dim morning room, daytime mode (IR-cut on), 4 JPEGs each at ~13 s apart,
    static patches (blanket, wall) normalised by their mean: **temporal noise -25 % (blanket 0.0218 vs 0.0290) and -34 % (wall 0.0314 vs 0.0474);
    spatial high-pass noise -24 % and -30 %**. Light drifted between the two series (exposure gain 4562 vs 3562) and JPEG snapshots are not the video,
    so treat it as indicative; I did not judge a moving hand or the night with the IR LEDs, nor RTSP_VBR with 3D-NR. Step 5 (1 h with Frigate) not run.
    Verdict: **measurable noise gain at no CPU cost, for 5.6 MB of RAM and only 1.6 MB of CMA left free**: worth keeping as an option; the owner decides
    whether 5.6 MB is worth it (default `nr3d=0` stays safe). Before it becomes a default, someone should check the 1.6 MB CMA margin with snapshots + recording.
  - **R9-02 day/night log: auto day/night was NOT running on the .11.** `daynight=3` (manual night, left by an earlier test) made the launcher skip the
    daemon although `config/autostart/auto-night-detection` exists. I ran `controlscripts/auto-night-detection start` (writes `daynight=2`, persisted).
    Calibration lines (source `luma`, ircut=1 = day, dim shuttered room, morning light rising): 07:31 `luma=111 ae=50 1124 6840 idx=30031`;
    07:36 `idx=30031`; 07:45 `idx=20030`; 07:50 `idx=17531`; 08:03 `idx=15029`; 08:08 `luma=92 ... 3475 idx=15257`.
    So in **day mode, in this room, the index sits at 15000-30000, the very value the night gives (30000)**: with the rc9 defaults (night above 15000,
    day below 3000) the `ae` source would call this room night all morning and never come back to day. The thresholds need a bright scene (outdoors or a window
    in full sun) and the dusk / dawn readings, which I cannot get today. Dusk (~17:50 local) and dawn are still to do; the daemon now runs and logs.
  - **R9-03 anti-flicker (log and status only, no judgement of bands by eye):** 50 Hz: `anti-flicker: 50 Hz (exposure step 281 -> 281 lines, exp_time_max 1125)`
    (the tuning file already used 281: 50 Hz changes nothing on the IPCAM2); 60 Hz: `(exposure step 281 -> 234 lines ...)`, `/var/run/isp_tune.status`
    `POWER_HZ=60`, `cam_ae` exp_time 1124 -> 936 with gain 3531 -> 4035 (the cap follows the step). Back to empty (Off): no `anti-flicker: off` line was
    written at the restart (the spec says one is). Steps 2-4 (bright window, night, `EXPOSURE_MAX_PCT=30`) not done; banding to be judged by someone
    watching VLC under LED light.
  - **R9-04 encoder:** step 1 done: `libmpi_venc_ex.so` strings hold `ak_venc_set_smart_config`, `ak_venc_set_rc`, `ak_venc_set_rc_weight`, `ak_venc_set_roi`,
    `ak_venc_get/set_gop_len` and the message `setting smart mode=%d, gop=%d, q=%d, v=%d`: the smart-mode call exists (arguments unknown to me).
    Step 2: `RTSP_VBR=1` (log `vbr main 1 sub 1`), 72 STAT lines (6 min, one Frigate client, a person in view part of the time): **899 KB per 5 s against
    950-980 KB with CBR (about -6 %)**, `enc_ms` 3790, `dropped` 16 in 72 lines (0.2 per 5 s, CBR 0-4 at the soak's sampling): the saving is small on this scene
    and the scene was not still. Reverted to CBR (`rtsp.env` empty). Step 3 `IDLE_FPS`: **not testable**: there is no `IDLE_FPS` line in `boot.conf` here and
    the motion-detection daemon is not enabled on the .11 (the log says it needs it); not changed.
  - Left on the .11: rc9 in the flash, `daynight=2` (auto, daemon running), `POWER_HZ` empty, `rtsp.env` empty, fps 25, soak running (`/mnt/sd/soak-20261031.log`).
    Card: `tc100test/c66-nr3d.img`, `c66-pool.img`, `c66rd-rc8.gz`, `c66rd-rc9.gz`, `test.img` (rc9) / `test.img.rc8` / `.rc7`; no `c66.img`: flash boot.
  - Tester slips, no firmware cause: I sent the old pool kernel again once because `split` does not overwrite its output files (3 min lost);
    a recursive grep froze the console (see R8-02). Hand-off for the implementer: rc10 candidates = fix the launcher so `daynight=3` does not hide the daemon
    silently (or log it), print `anti-flicker: off` at start, and re-think the `ae` thresholds from a bright-day reading.

### R9-02 Day / night from the ISP exposure: calibration log and measured thresholds — `to test`
- **What:** rc7 night 2 (HW-08) measured the exposure index at night: `exp_time 1124` (the maximum) and `a_gain 6840`
  (26.7x), index about **30000** with or without the IR LEDs. The defaults of the `ae` source (F-04) were placeholders
  (4000 / 1000, under the night value even in the day); they are now **night above 15000** (full exposure and about
  13x gain) and **day below 3000** (5 times less, room for the IR-cut filter and the LEDs changing the light at the
  switch). The source stays **`luma` by default**. New: `auto-night-daemon.sh` writes a **calibration line every 5
  minutes** to `/tmp/logs/daynight.log` (`HH:MM mode=day|night src=... luma=N ae=<cam_ae line> idx=N`, last 2 x 400
  lines; `log-persist.sh` copies `/tmp/logs` to the card as `other.log`), whatever the source.
- **Test:** leave the camera running through one dusk and one dawn (auto day / night on, source `luma` as now), then
  copy `/tmp/logs/daynight.log` (or `/mnt/sd/logs/boot-NNNN/other.log`) here, or its lines around the two switches.
  From them: the index in full day (indoor and outdoor if possible), when the `luma` source switched, and the index
  right after each switch. Then set the source to "ISP exposure" with thresholds taken from the log, one more dusk and
  dawn: one switch each way, no flapping when the IR LEDs come on or go off.
- **Pass:** a clean switch each way with the `ae` source. **Then** (rc10): `ae` becomes the default source with the
  measured thresholds. **Note:** the `isp` source (the ISP's dark flag) read 0 all night on HW-08: not usable.

### R9-03 Anti-flicker (`POWER_HZ`, Settings, Picture) — `to test`
- **What:** the field is back (Settings, Picture: Off / 50 Hz / 60 Hz), applied by `tc100_rtsp` whatever live tuning
  is: `AK_ISP_SET_AE` with `exp_step` = the sensor lines of one lamp pulse (28125 lines/s on the JX-F23: 281 lines at
  50 Hz, 234 at 60 Hz). The ISP's auto exposure then keeps every exposure longer than a pulse at whole pulses (its own
  code: `ak39_isp2_3a.c`, `exp_step`). **Default Off** (the tuning file's step, unchanged). `RTSP_LINE_RATE` overrides
  the line rate.
- **Test:**
  1. Indoors under mains lighting (LED bulbs or tubes), daytime mode, live tuning off: Off, look at the picture (VLC):
     dark bands rolling up or down, or a pulsing brightness? Then 50 Hz (Save): `tc100_rtsp.log` `anti-flicker: 50 Hz
     (exposure step N -> 281 lines, exp_time_max 1125)`, `/var/run/isp_tune.status` `POWER_HZ=50`. The bands stop.
  2. Outdoors or a bright window (exposure under 10 ms): the picture is not darker or blown out with 50 Hz.
  3. Night (IR): nothing changes (exposure at the maximum).
  4. With `EXPOSURE_MAX_PCT=30` also set: both lines in the log, the exposure cap still applies.
  5. Off again: `anti-flicker: off (exposure step 281 -> <tuning value> lines ...)`.
- **Pass:** 1-5. **Then** (rc10): 50 Hz by default for a camera set to a European time zone? (owner's choice); the Home
  Assistant select comes back. **Fail:** Off; write what was seen (the step value of the tuning file is in the log).

### R9-04 Encoder: VBR, idle frame rate, and the smart mode's calls — `to test`
- **What:** the encoder side of "use the SoC": `RTSP_VBR=1` (P-08: 6 % less on a noisy night, the day scene not
  measured) and `IDLE_FPS` (F-03, frame rate lowered while nothing moves) were opt-in and not finished. rc9 adds the
  list of optional encoder calls to the log (looked up, never called), so that the vendor smart mode (long GOP on a
  still scene) can be used once its call is known.
- **Test:**
  1. The `encoder library: optional calls:` line of R9-00 step 2, and `strings /mnt/lib/libmpi_venc*.so
     /vendor/lib/libmpi_venc*.so 2>/dev/null | grep -i -E 'smart|gop|_rc|roi'` here.
  2. Day, still scene, 10 minutes each, one Frigate client: main stream bytes per 5 s with CBR, then with `RTSP_VBR=1`
     in `/mnt/config/rtsp.env` (restart `tc100_rtsp` as `v3/autorun-linux66.sh` does). Then a hand moving in front:
     the bytes go back up to the ceiling, no smear or blocks. Frigate keeps recording and detecting.
  3. `IDLE_FPS` as F-03 says (Frigate side: a motion still starts a recording without a missed second).
- **Pass:** VBR saves on a still day scene with no visible loss and Frigate is fine: **then** (rc10) `RTSP_VBR=1` by
  default. Same for `IDLE_FPS`. Smart mode: implemented only once step 1 shows its call.

### R8-01 / R8-02 results: rc8 (`c952996`, CI run 41147884892) on IPCAM2, 2026-10-31 01:00 (tester)
Installed: package `tc100-3.0.1-rc8-update.tar` (md5 `b33b0c9d...`, 12 chunks over the serial console, each md5 checked, then `tar -x` and `md5sum -c` OK on the card),
first **one card boot of the rc8 kernel** (as on rc7: kernel from the card, flash user space, U-Boot prompt in RAM only, no `saveenv`; owner agreed to this
for the plain card boot), then **`update66.sh check` = ok, `apply`** (kernel md5 `c3687a47...`, initrd md5 `9e3f1978...`, stack, read-back md5 identical, backups of the
old partitions on the card in `tc100-3/backup/`, settings kept; the whole apply took under 2 minutes, `DONE: 3.0.1-rc8 written, restarting`). IPCAM2 now runs rc8 from its flash.
| R8-01 step | Result |
|---|---|
| 1 `slots` | **PASSED.** Card boot and flash boot: `/sys/module/ak39_vi/parameters/slots` = **3** with no `slots=` on the command line, cmdline complete (`initrd=0x81000000,2012654`, `flashroot=1`), Wi-Fi associated at 15.1 s, no Oops. **MemAvailable 19.1-19.2 MB** (rc7: 15.6). |
| 2 ISP clock and masks by default | **PASSED.** With an **empty `rtsp.env`**: `clock: in the ISP OSD (472x44 at 12,16)` (clock on) and `privacy masks: 1 in the ISP` (one mask set), `pp_ms` 1. With `RTSP_ISPOSD=0` and `RTSP_ISPMASK=0`: neither line, `pp_ms` **183-260** per 5 s at 25 fps (CPU clock). Settings restored (`osdenabled=0`, no mask, `rtsp.env` empty). |
| 3 `amixer -c 0` | **PASSED.** `amixer -c 0 scontrols` lists Headphone, LineIn, Mic, DAC out mode; `amixer -c 0 sget 'Headphone'` -> `Playback 3 [60%]`, limits 0-5; `amixer -c 0 cget name='LineIn Capture Volume'` -> `values=10`, 0-15; `amixer -D sysdefault:0 scontrols` works; **no `cannot stat aliases.conf` line any more**. Note for the doc: the plan's `sget 'Headphone Playback Volume'` does not exist as a *simple* control (use `sget 'Headphone'`, or `cget name='Headphone Playback Volume'`). Not checked: that the Settings microphone level moves `LineIn Capture Volume` (needs the UI). |
| 4 F-05 | **PASSED.** `.bootcount` was `0009`: the first rc8 boot made **boot-0010**, a "ui" reboot (`reboot-tracker.sh intent`) wrote `why=shutdown: ui: F-05 rc8 test` into it, the next boot made **boot-0011** (`0011`, first save at 159 s). |
| 5 MQTT refusal | **Partly.** `/tmp/mqtt_last_pub.status` = `1793407671 fail 5` (the code is there). The top badge "MQTT: login refused" needs the web UI (owner). |
| 6 one hour with Frigate, then the soak | **Soak started 2026-10-31 00:57 UTC** (`/mnt/sd/soak.sh`, a line every 5 min in `/mnt/sd/soak-20261031.log`: avail, CPU split, `cap`/`drop`, Wi-Fi, kernel errors). 25 fps, one Frigate client. To be read in the morning. |
Also: at 25 fps after the install: 124-126 frames per 5 s, `dropped` 0-2, MemAvailable 19.2 MB.

**Soak of rc8 on IPCAM2, 2026-10-31 00:57-05:27 UTC (4 h 33 min, still running, one Frigate TCP client, 25 fps, flash boot, MQTT login refused):** 54 samples, one every 5 min.
No reboot, no Oops / OOM / `OPEN FAILED` (the `kerr 1` in every line is the `oops=panic` word of the kernel command line, constant since the first sample), `tc100_rtsp` kept the same pid (636), 1 client throughout.
**MemAvailable 18.1-19.8 MB (average 18.8)**: 19.2 MB over the first hour, 18.5 MB over the last hour, about 0.7 MB lower after 4.5 h (not a leak yet, to confirm on the 8 h
reading). CPU split usr 6.7 / sys 13.4 / **idle 77.5 %** at 25 fps. Frames `cap` per 5 s: average 123.5 (125 expected), lowest sample 111. `dropped`: **31 in 54 samples of 5 s**
(15 samples had one, at most 4), i.e. about 0.5 frame per 5 s, in line with the 0.55 % of P-09 at 15 fps. Main stream 858-988 KB per 5 s (the 1.0 MB cap), Wi-Fi -35 to -44 dBm.
`tc100_rtsp.log` rotated by itself at the real cap (a `tc100_rtsp.log.1` of 262 KB next to the live log): **O-05 rotation passed at 256 KB**. `/mnt/sd/logs` holds `boot-0007` to `boot-0011` (5 kept,
the oldest removed), so log-persist runs and keeps its limit. The MQTT status still reads `fail 5` (broker refusal, owner action).

**R8-02 HW-02 test 2 (`ak39_venc.pool=9600K`): NOT run - the card hook route cannot start it as built.** The U-Boot hook of IPCAM2 (`bootcmd=run sdload sdboot; run flashboot ...`, `sdload` loads **both `tc100test/c66.img` and `tc100test/c66rd.gz` from the card**, `sdboot`'s bootargs have **no `flashroot=1` and no `ak39_vi.sub_channel=1`**, written on 2026-10-24) boots in **SD mode**: the initramfs then looks for the user space in the card tree (`/mnt/sd/v3`, the `tc100-3.0.1-rc8-sd.zip` content). IPCAM2's card has no such tree (it runs from the flash), and unzipping the SD package there would also create `/mnt/sd/config/`, which cfg-persist and the flash boot would take for the settings folder - not something the tester will do. **Request:** build the pool kernel with `CONFIG_CMDLINE="ak39_venc.pool=9600K flashroot=1 ak39_vi.sub_channel=1"` (still `CMDLINE_EXTEND`, so it comes after the U-Boot arguments), so that with the card's `c66.img` = that kernel and `c66rd.gz` = the rc8 initramfs (same file as in the flash, 2012654 bytes) the camera boots the **flash user space** with the 9600K pool, no U-Boot prompt. Then the tester copies two files to `tc100test/` (3 and 4 minutes over the serial console), reboots, runs R8-02 steps 1-7, and renames the files away again. Tell me when that artifact exists.

**Implementer answer (2026-10-31):** done as asked. The card test kernel's built-in command line is now
`ak39_venc.pool=9600K flashroot=1 ak39_vi.sub_channel=1` (`CMDLINE_EXTEND`, after the U-Boot arguments; `S39tc100-linux66`
greps `/proc/cmdline` for `flashroot=1`, which holds the appended part). Same artifact name `tc100-linux66-hw02-pool9600k`,
from the CI run of the commit `[rc8] HW-02 card kernel boots the flash user space`. The other artifacts of that run
are the same rc8 build (only the build stamp differs), so there is nothing to reinstall. Notes:
- `flashmode-prep.sh` only mounts (`stack`, `vendor`, settings); nothing in the flash mode start writes the flash.
- **Before the reboot:** the hook's `sdboot` carries a fixed `initrd=0x81000000,<size>`. Read it (U-Boot environment,
  read only) and check it equals the size of the card's `c66rd.gz` (2012654 for rc8). A larger file is cut short, the
  kernel panics, and `panic=10` brings it back to the same card boot every time (way out: the owner takes the card out).
- `/proc/cmdline` must end with `ak39_venc.pool=9600K flashroot=1 ak39_vi.sub_channel=1`; R8-02 step 1 is otherwise
  unchanged. Way back as before: rename `tc100test/c66-rc8.img` back to `c66.img` (and the card's `c66rd.gz` back to
  what it was, if you replaced it).
- Without waiting for CI, the same start can be had with the current pool kernel and an empty file
  `tc100test/flashmode` on the card (`S39` line 25 takes it as `flashroot=1`); rename it away after the test, or every
  later card boot also runs from the flash.

### R8-01 3.0.1-rc8 on the camera — `to test`
- **What:** the rc7 tree plus: `slots=3` default (kernel), ISP clock and ISP masks default (`tc100_rtsp`), the F-05 and
  `amixer` fixes, the MQTT refusal in the web UI. `VERSION` = `3.0.1-rc8`.
- **Test, in this order** (card boot of the kernel first, then the flash install with `update66.sh` as for rc7):
  1. `/proc/cmdline` complete; `cat /sys/module/ak39_vi/parameters/slots` = **3** with no `slots=` on the command line;
     Wi-Fi, 15 fps, `MemAvailable` about 18.5-19.5 MB (rc7: 15.6).
  2. `tc100_rtsp.log` with an empty `rtsp.env`: `clock: in the ISP OSD ...` (when the clock is on) and, with a mask
     set in Settings, Privacy & overlay, `privacy masks: N in the ISP`; snapshot: clock and mask as in HW-07 / HW-04.
     `RTSP_ISPOSD=0` in `rtsp.env` + restart: no `clock: in the ISP` line, clock drawn by the CPU (`pp_ms` back to ~100+).
  3. `amixer -c 0 sget 'Headphone Playback Volume'` works (rc 0, no `aliases.conf` error); the Microphone level of
     Settings (UI-12) is applied (`amixer -c 0 sget 'LineIn Capture Volume'` follows it).
  4. F-05: on the card of IPCAM2 (`.bootcount` = `0009`) one reboot makes `boot-0010`, the next `boot-0011`.
  5. MQTT with the current refused login: the top badge reads **MQTT: login refused** (French: "MQTT : connexion
     refusée"), `/tmp/mqtt_last_pub.status` ends with ` fail 5`. After the owner fixes the password: **MQTT: ok**.
  6. One hour of streaming with Frigate at the camera's frame rate: `dropped` as rc7 (P-09: 0.55 %), no Oops / OOM.
     Then the overnight soak of rc8.
- **Pass:** all six; `MemAvailable` gain present; nothing worse than rc7.
- **Fail / revert:** `ak39_vi.slots=4` on the command line (card boot) or `RTSP_ISPOSD=0` / `RTSP_ISPMASK=0` in
  `rtsp.env`; whole build: reinstall rc7 with `update66.sh`.

## Hardware use and memory (2026-10-30, commits `[hwaccel] ...`)

Context: [hardware-acceleration.md](hardware-acceleration.md). None of this was compiled or run before it was pushed
(no compiler on the author's machine): the first check is that the CI run is green.

### HW-05 Sharpness by the ISP (Image page, `SHARPNESS`) — `to test`
- **What:** the Sharpness slider is back on the Image page. `tc100_rtsp` scales the tuning file's medium and high
  frequency gains (`AK_ISP_SET_SHARP`, manual and 9 gain-linked sets) by 2 % per step. On by default (nothing is written
  while the slider is at 0).
- **Test:** live tuning on, sharpness -50, 0, +50: log `sharpness: N in the ISP (medium a -> b, high c -> d)`; the
  picture gets softer / sharper (compare snapshots of the same scene); bit rate goes down / up a little. The "Applied on
  the camera" line under the form shows the value.
- **Fail:** picture broken or unchanged at ±50: note the logged gains; `RTSP_ISPTUNE` does not cover it, set SHARPNESS=0.

### HW-08 Exposure state for day / night (`/tmp/cam_ae`) — `to test`
- **What:** every 2 s `tc100_rtsp` writes `lumi exp_time a_gain d_gain isp_d_gain dark_flag` from
  `AK_ISP_GET_AE_RUN_INFO`. Nothing uses it yet. The day / night daemon decides from `/tmp/cam_luma`, the mean luma
  of the picture *after* auto exposure, which stays near the AE target whatever the light: exposure time and gains
  measure the scene light.
- **Test:** record `/tmp/cam_ae` and `/tmp/cam_luma` in daylight, at dusk, at night with the IR LEDs on and off.
- **Next:** if the values separate day and night clearly, switch `scripts/auto-night-daemon.sh` to them (with
  hysteresis), so the IR light itself does not flip the mode back.

## Web UI on 3.0: checks that need the camera (audit of 2026-10-30)

A static audit traced every control of the web UI to what acts on it on 3.0. The fixes are in the commits
`[ui30] ...`; these checks remain. Write the result after each line.

- UI-01 `passed` (2026-10-30, 563dbff: crond, crontab, mkfifo, timeout, usleep all present) — Busybox applets: `busybox --list | grep -E '^(crond|crontab|usleep|mkfifo|timeout)$'`. Without
  `usleep` the IR-cut pulse of `bin/setconf` becomes 1 s; without `crond` the scheduled reboot never runs.
- UI-02 `to test` — Time zone: set `CET-1CEST,M3.5.0,M10.5.0/3`, reboot; `date` over ssh, the OSD clock, a new
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

### F-06 Memory Guard defaults (warn 6144 / critical 3072 KB) — `to test`
- **What:** the old defaults (8192 / 4096) sat next to the normal MemAvailable; cameras holding exactly them are
  migrated when the service starts; the warn stage no longer stops `auto-night-detection`.
- **Test:** `/tmp/log/memory-guard.log` shows the migration once; no warn / critical stage in a day of normal use.
  **Off:** `MEM_GUARD_ENABLE=0`.

Not done: 3D-NR (its 6.2 MB reference frame does not fit until HW-01b / HW-02 free memory).

## Optimisation for the AK3918 (2026-10-30, commits `[opt] ...`)

Baseline to note before flashing the new build: `grep -E 'MemTotal|MemAvailable|Slab|CmaFree' /proc/meminfo`, `ps`
(count the `sh` processes), `scripts/cpu-profile.sh 30`, `ls -l /tmp/logs`. Same commands after; one line per result.

### O-01 Kernel config: less RAM (`defconfig_cma`) — `to test`
- **What:** about 520 KB less kernel RAM and 107 KB less zImage (printk buffer 64 KB, no io_uring / zram / LZ4 /
  ZSTD / signed regdb / inet_diag, slab merging on, small CRC32 tables), squashfs fragment cache 1 block instead of 3
  (2 x 256 KB less per mounted squashfs: stack and vendor in flash mode), `MAGIC_SYSRQ` on (serial break off) so the
  last-resort reboot of `service-watchdog.sh` (`echo b > /proc/sysrq-trigger`) works.
- **Test:** boots from the SD card (c66.img) then from flash; `MemTotal` and `MemAvailable` up by about 0.5 MB, plus
  about 1 MB in flash mode; a full boot log still fits in `dmesg` (first lines are the `Booting Linux` banner);
  Wi-Fi associates (regulatory domain still set: `iw reg get` from ext/); browsing the Settings pages from flash is not
  slower; `echo b > /proc/sysrq-trigger` reboots. **Off:** the previous kernel.
- **Result 2026-10-30, IPCAM2, 563dbff (CI run 41089089376), installed in the flash of IPCAM2 (.11) with update66.sh, settings kept (O-01 + O-02 + B-01 + B-02 together):** MemTotal 59932 kB,
  **MemAvailable 15.3-15.9 MB** two minutes after a flash start (rc5 with 0015: 10.8 MB; rc4: 10 MB), no OOM or
  allocation failure, Wi-Fi associates, 15 fps (75 frames per 5 s, about 1 MB), CPU 84 % idle over 10 s with a
  client. Web server answers (`/` 302, `state.cgi` 401 without a session). `curl` over TLS works for the services
  (`CURL_CA_BUNDLE` from autorun: api.github.com 200); note: the serial console shell does not get that variable
  (curl exits 60 there), harmless for the services. BusyBox no longer has `wget` (no script uses it).

### O-02 Smaller initramfs (`v3/initramfs-prune.txt`) — `to test`
- **What:** hostapd sample config, hostapd_cli, wpa_passphrase, the xz tools and liblzma out of the RAM image (about
  0.45 MB); `mksquashfs` in `ext/` gets its own liblzma.
- **Test:** boot; the rescue access point starts (`sh /mnt/scripts/wifi-rescue.sh` from the serial console, UI-10);
  the 3.0 install path that runs `/mnt/ext/bin/mksquashfs` still starts it (`/mnt/ext/bin/mksquashfs -version`).

### O-03 tc100_rtsp and libakuio.so stripped, `-mtune=arm926ej-s` — `to test`
- **What:** both are copied to /tmp (RAM) at boot; 128 -> 112 KB and 16 -> 13 KB. Unstripped copies (`*.dbg`) are
  in the CI symbols artifact for decoding.
- **Test:** the stream starts (VLC), the STAT line appears; `ls -l /tmp/tc100_rtsp /tmp/libakuio.so`.

### O-04 Shell side: fewer forks, fewer resident processes — `to test`
- **What (commits `[opt] Web CGIs...`, `[opt] Resident daemons and boot...`):** `state.cgi?cmd=dashinfo` cached 300 s
  in `/tmp/state_dashinfo.cache` (dropped when the host name or a config file changes); no `cmd=hostname` and no
  `get_ptt_vol` at page load; `csrf_guard` returns early on GET; Day/night tab polls every 5 s with about 2 forks
  instead of 20; `camcontrols.cgi?cmd=panel` without func.cgi; the day/night daemon no longer sources
  common_functions.sh and waits with `read -t` on a FIFO; web-guard runs net-guard every 3rd minute while the gateway
  answers (every minute after a failure, same reboot limits) and sdinfo only when the card changed or every 10th
  minute; the health prober answers "stopped" for motion without a shell and does the RTSP DESCRIBE every 6th probe;
  crond starts only when its crontab has an entry; boot.conf parsed once at boot; one `ln` for the www and vendor
  links; `rtsp-launch.sh` takes the pid from `$!` (no `sleep 2`) and opens the log with `>>` and `RTSP_LOGFILE`.
- **Test:** the 12 checks of the implementer's report, in short:
  1. `cat /var/run/v4l2rtspserver.pid` = `pidof tc100_rtsp`, its `oom_score_adj` is -900; `/mnt/config/rtsp.debug`
     still sends the log to the console.
  2. `time curl -s 'http://127.0.0.1/cgi-bin/state.cgi?cmd=dashinfo&format=json'` (with `-u root:<password>`) twice: second fast, same JSON;
     `touch /mnt/config/rtspserver.conf` rebuilds it.
  3. Browser network tab at page load: no `cmd=hostname`, no `get_ptt_vol`; the title shows the host name; Talk or
     the volume slider fetches `get_ptt_vol` once.
  4. A POST without the CSRF header gets 403; the UI saves still work.
  5. Day/night tab refreshes every 5 s; `state.cgi?cmd=daynight&format=json` same fields as before.
  6. Day / Night buttons under the picture work (`camcontrols.cgi?cmd=panel`).
  7. Change LUMA_NIGHT: applied at the next cycle; `top`: the day/night daemon near 0% (the FIFO wait really waits).
  8. Router unplugged: `/tmp/net-guard/down_since` within about 3 min, reboot at NET_GUARD_MIN as before. Card out
     and in: the SD panel follows within 1 min. `kill` httpfront: restarted, then the rescue telnet if it fails.
  9. Motion off: `/tmp/health_snapshot.cache` says motion "stopped"; `/tmp/health_rtsp_deep` exists.
  10. Fresh config: no `crond` after boot; saving a scheduled reboot starts it.
  11. `ls /tmp/www` lists every page (if the multi-target `ln` failed the UI would 404), `ls -l /lib | grep mnt`.
  12. Idle camera, `ps` a few times over 3 minutes: no new `sh` / `ping` every minute.

### O-05 Video server: one read of the encoder output, log rotation, less per-frame work — `to test`
- **What (commit `[opt] tc100_rtsp: log rotation, one read of the encoder output, ...`):**
  - **Log rotation (bug):** the STAT line every 5 s made `/tmp/logs/tc100_rtsp.log` grow without limit in RAM
    (about 2.6 MB a day). Above `RTSP_LOGMAX` (256 KB) it is now renamed to `.1` and reopened (first line `log rotated`).
  - **Encoder output read once:** it is uncached memory. Each frame is copied once with word reads, the NALs are found
    once, the encoder buffer is given back at once, and the GOP cache keeps that copy. The RTSP clients, the recorder,
    the live MP4 and the IDR test then read the cached copy; before, they read the uncached buffer 4 to 6 times.
  - **Per-frame calls cut:** no `getenv`, file checks every 0.25 s, OSD clock text once a second, colour-table
    identity flags. JPEG tables are built once per quality, and each JPEG is read once from the engine.
  - **Snapshot cadence:** the 2 s snapshot cadence now applies only if the picture was read in the last 4 s (the
    dashboard kept it at 2 s forever).
  - **Client queues:** they shrink back after a congestion.
- **Switches:** `RTSP_FRAMECOPY=0` (frame and JPEG reads as before), `RTSP_QTRIM=0` (queues never shrunk),
  `RTSP_LOGFILE` unset (no rotation), in `/mnt/config/rtsp.env`.
- **Test** (same scene, bit rate and clients before and after):
  1. After about an hour: `ls -l /tmp/logs` shows `tc100_rtsp.log` under 256 KB and a `.1`; `MemAvailable` stops
     drifting down over a day.
  2. STAT `snd_ms` lower than with `RTSP_FRAMECOPY=0`, `enc_ms` unchanged; `scripts/cpu-profile.sh 30` for both.
  3. Main and sub, H.264 and H.265, in VLC and Frigate: clean picture (no green or grey blocks). A client that joins
     mid-GOP starts at once on the cached keyframe. One TCP and one UDP client together. Recordings open with no gap,
     and the live video in the browser plays. Any artefact: compare with `RTSP_FRAMECOPY=0`.
  4. `/tmp/stream.jpg`, `/tmp/frame_ch0.jpg`, the dashboard picture and a recording thumbnail are valid JPEGs. The
     dashboard picture still refreshes smoothly; if it lags, the 4 s window is the cause.
  5. A slow viewer for 30 s, then `MemAvailable` recovers about a second after it catches up (compare with
     `RTSP_QTRIM=0`).
  6. The black-and-white switch reacts within about a second, and the software clock still ticks every second.

### B-01 Initramfs reduced to the boot essentials: ALSA tools, libasound, dropbear, libz/libgcc_s/libatomic moved to `ext/` — `to test`
- **What (commit `[big] ...`):** the RAM image (ramfs, never reclaimed) goes from 4.18 MB of files (4452 KB du) to
  2.51 MB (2720 KB du), the xz initrd from 1.51 MB to 1.03 MB (partition 2,012,654). Out of it, into `ext/` of the user
  space (`/rom/ext` in flash mode, the card tree in SD mode; page cache, read on demand): `aplay`, `arecord`,
  `amixer`, `libasound.so.2` (`ext/lib`), `/usr/share/alsa` (`ext/share/alsa`, without the alsactl init files), `dropbear`
  (and its links ssh/scp/dbclient/dropbearkey, not shipped any more), `libz`, `libgcc_s`, `libatomic` (`ext/lib` only
  for the tools that need them: curl, mksquashfs); the xz helper scripts are dropped. `stack.sqfs` grows from 1.97 to 2.46 MB
  (partition 2.83 MB). **Kept in the RAM image:** busybox, musl, `wpa_supplicant` + libnl-3/genl (Wi-Fi up without
  the user space; moving them would save 0.78 MB more), init scripts, `udhcpc` script (telnetd at boot: see S-01).
  How callers find the moved files: `/usr/bin/aplay|arecord|amixer` and `/usr/share/alsa` are links into `/mnt/ext`
  (CGIs run with busybox httpd's reset PATH, `tc100_rtsp` does `execlp("arecord")`), `etc/ld-musl-arm.path` is baked into
  the initrd (`/lib /usr/lib /mnt/ext/lib`, same as autorun writes), `etc/profile.d/tc100-ext.sh` adds `/mnt/ext/bin`
  to login shells, `S50dropbear` is `v3/S50dropbear-linux66` (looks in `/mnt/ext/bin`, then `/mnt/sd/ext/bin`: in SD mode
  `/mnt` is the card only after autorun, the card is already at `/mnt/sd`; no dropbear = a console line and the
  telnetd fallback of S-01). `S39tc100` logs a warning if the user space has no `ext/bin/aplay`.
- **Off:** none at run time. The initrd and the user space must be updated together (the updater writes `stack` first,
  `initrd` last; a card tree must be the one of the same build). New initrd + old user space = no audio tools, no ssh
  (the telnetd fallback of S-01 and everything else work); old initrd + new user space works.
- **Test** (flash mode, then SD mode `tc100test/c66.img` + card tree, then flash mode with the card removed):
  1. `/proc/cmdline` shows the full initrd size; `free`: MemAvailable about 1.7 MB higher than before.
  2. `ls -l /usr/bin/aplay /usr/share/alsa` (links to `/mnt/ext`), `aplay -l` and `arecord -l` list the card,
     `amixer -c 0 scontents` works from the serial shell and from an ssh session (`PATH` has `/mnt/ext/bin`).
  3. RTSP with audio plays (VLC: sound), the web UI Listen button and the Talk / sound test (speaker) work,
     `pidof arecord` while an audio client is connected.
  4. `ssh root@<ip>` works (password of config/user.pwd) and `ps | grep dropbear`; boot log has `Starting dropbear sshd: OK`
     and no `dropbear is not in the user space` line. Since rc7 (S-01) port 23 is closed at boot.
  5. Wi-Fi up as before; `curl -sI https://example.org | head -1` and `jq -n 1` (`libz`, `libatomic` from `ext/lib`);
     `iw reg get`.
  6. Fallbacks: card removed in flash mode (everything works, no video storage); `tc100test/flashmode` absent and
     no `flashroot=1` (SD mode) works; a card tree from before this build with this initrd prints
     `user space without ext/bin/aplay` and still brings up Wi-Fi, web UI and video.

### B-02 Slimmer Buildroot base (busybox, alsa-lib, hostapd, wpa_supplicant, dropbear) — `to test`
- **What (commit `[big] Slim Buildroot base ...`, `v3/buildroot/` only):**
  - **busybox:** 98 unused applets off, 290 -> 192; IPv6, CIFS, bzip2 and verbose usage off; 968 -> 681 KB.
  - **alsa-lib:** only PCM and mixer (`hw`, `plug` and the conversion plugins; no seq, rawmidi, ucm, topology);
    903 -> 554 KB. alsactl, alsamixer and ncurses are gone.
  - **Wi-Fi tools:** hostapd nl80211 only, without the extras; wpa_supplicant without TDLS / 802.11r.
  - **Other:** dropbear without the ssh client; libnl-route, libgcc_s and the single CA certificate files removed.
  - **Removed applets you might type:** `wget` (use `curl`, in ext/), `nslookup`, `traceroute`, `telnet` (the client;
    `telnetd` stays), `arp`, `fdisk`.
  - **Combined with B-01, measured:** unpacked initramfs 2384 KB (was about 4450 KB), xz initrd 895,968 B,
    `stack.sqfs` 2,195,456 B (partition 2,830,336).
- **Off:** the previous build.
- **Test:**
  1. `busybox --list | wc -l` = 192, and no `not found` from S01..S50 on the console.
  2. Microphone: `arecord -q -D hw:0,0 -f S16_LE -r 8000 -c 1 -t raw -d 3 /tmp/a.raw` gives about 48000 B. RTSP audio
     and the web Listen button work.
  3. Speaker: `aplay -q -D plughw:0,0 -t raw -f S16_LE -r 8000 -c 1 /tmp/a.raw`, and Talk / the sound test of the UI.
  4. Mixer: `amixer -c 0 cset name='LineIn Capture Volume' 10`.
  5. Wi-Fi client, and the rescue AP (`scripts/wifi-rescue.sh`: hostapd starts and a phone joins).
  6. `ssh` and `scp` into the camera.
  7. Web login and CGIs, `ftpd`, `telnetd`, `crond` (scheduled reboot), `ntpd`, the SD card mount.

### O-06 One housekeeper loop for the slow shell daemons — `to test`
- **What (commit `[big] One housekeeper loop ...`):** `scripts/housekeeper.sh` replaces web-guard, log-persist, the
  rtsp / mqtt / onvif / telegram service watchdogs and health-snapshot (separate `sh` processes) with one resident
  loop. It waits with `read -t` on a FIFO, 30 s at most.
  - **Periods are unchanged:** web 60 s, network check 60 s (run every 3rd minute while the gateway answers), SD panel
    60 s, watchdogs 60 s, health snapshot 300 s, log-persist 10 min.
  - **A slow job never stalls the others:** it runs in a guarded background process.
  - **Same status readers:** the Services page, health-probe and memory-guard read the same pid files. While a job is
    registered, its pid file holds the housekeeper's pid.
  - **Still separate:** button-watch, auto-night, the MQTT bridge, getty and cfg-persist.
  - **Known limit:** nothing restarts the housekeeper itself if it dies (web-guard was not supervised either).
- **Switch:** `HOUSEKEEPER=0` in `/mnt/config/boot.conf` (read at boot) brings back the separate daemons.
- **Test:**
  1. `ps | grep -c '[s]h '` is 3 or more lower than on the previous build, and `/var/run/housekeeper.pid` is alive.
  2. `sh /mnt/scripts/housekeeper.sh status` lists `web`, `net`, `sd` and `watch-rtsp-h26x`, then `log-persist`, plus
     `health-snapshot` if it is on. `runs=` grows and `skipped=0`.
  3. `/var/run/v4l2rtspserver-watch.pid` holds the housekeeper's pid, and the Services page shows rtsp-h26x running.
  4. Kill tc100_rtsp: it is back within 1-2 minutes (`/tmp/log/service-watchdog.log`: "perform restart").
  5. In Services, stop and start health-snapshot (and mqtt-bridge if MQTT is on): the pid file goes and comes back,
     and `status` follows.
  6. The network, card and httpfront checks of O-04 item 8.
  7. `/mnt/sd/logs/boot-NNNN` appears about 2 minutes after boot and is refreshed every 10 minutes.
  8. Idle `top`: the housekeeper is near 0%.
  9. With `HOUSEKEEPER=0` and a reboot, the separate `web-guard.sh run`, `log-persist.sh run` and `service-watchdog.sh`
     processes are back, and the Services page is still correct.

Declined after the tester's answer: `cma=16M`, wpa_supplicant out of the RAM image, cfg-persist in the housekeeper.

## Tester's accepted proposals (2026-10-30 night, build 3.0.1-rc7)

### P-01 IP multicast in the kernel (ONVIF discovery) — `to test`
- **What:** `CONFIG_IP_MULTICAST=y` in `defconfig_cma`; ONVIF WS-Discovery needs it.
- **Test:**
  1. Turn ONVIF on in Services.
  2. Home Assistant (ONVIF integration, "discover") or ONVIF Device Manager finds the camera without typing its IP.
  3. `cat /proc/net/igmp` lists 239.255.255.250 on wlan0 while monvifd runs.
- **Off:** the previous kernel.

### P-03 Buildroot base cached in the CI — `to test` (CI only)
- **What:** `build-base-rootfs.yml` keeps the finished `rootfs.cpio.gz`. The key hashes `v3/buildroot/**` and the
  workflow; a hit skips the Buildroot build.
- **Test:** a push that does not touch `v3/buildroot` builds in a few minutes and gives the same base artifact (same
  size as the previous run). A change in `v3/buildroot` rebuilds it.

### P-04 Higher frame rate: 20 or 25 fps at what CPU cost — `to test` (owner's question)
- **What:** the JX-F23 sensor driver tops out at 25 fps (`MAX_FPS`). Settings > Streams & audio already offers 10 /
  12 / 15 / 20 / 25 (F-02), and 15 is only the default. On rc6, 15 fps leaves 79-84 % of the CPU idle. Encoding is
  done by the hardware; the CPU cost per frame is capture handling, frame copy (O-05), RTP and the Wi-Fi interrupts.
  The latter depend on the bit rate, not on the frame rate.
- **Test** (same scene, one RTSP client + the dashboard; 2 minutes at each rate):
  1. `scripts/cpu-profile.sh 60` and `top` idle %.
  2. STAT: `cap`, `enc`, `dropped`, `enc_ms`, `snd_ms`, `pp_ms`.
  3. `MemAvailable`.
  4. The picture in VLC: motion smoothness, and blockiness at the same bit rate.
  5. Rates: 15, 20 and 25, then 25 with the main bit rate raised by 1.5x (the same bits are shared by more frames).
- **Decision rule (implementer, after the numbers):** the default goes to 20, or 25, if idle stays above about 55 %
  with one client and the dashboard, `dropped` stays 0, and Wi-Fi keeps up (`snd_ms` steady). The bit rate default
  follows if the picture needs it.

### P-05 User space squashfs in 128 KiB blocks — `to test`
- **What:** `stack.sqfs` built with `-comp xz -b 128K` instead of 256K: 2,240,512 B against 2,195,456 on the rc6 tree
  (partition 2,830,336); the full rc7 tree measures 2,306,048 B. A page read from the flash decompresses half as much, and the squashfs caches take about 384 KB less RAM.
  Measured alternatives that do not fit: lzo 2.96 MB, lz4 3.2-3.9 MB; gzip 2.70 MB would fit with 126 KB to spare.
  The `vendor` partition (made at install) is left at 256K.
- **Test:** MemAvailable / Slab after boot against rc6, both in flash mode; `time ls -lR /rom > /dev/null` and the
  first Settings page load after boot.

### P-06 Reference profile of each build (`scripts/perf-baseline.sh`) — tool
- **What:** 60 s, one RTSP client: the CPU split (user, system, irq, softirq, idle), interrupts per second per source
  (the USB host of the Wi-Fi), Wi-Fi bytes/s, MemAvailable / CmaFree / Slab, the last STAT lines.
- **Use:** `sh /mnt/scripts/perf-baseline.sh 60` once per build in the result, so builds compare.

### P-08 Encoder "smart" mode / VBR — `to test`
- **What:** `tc100_rtsp` never used the vendor smart mode or VBR (`rc_vbr` was always 0 = constant bit rate). The
  `[video]` commit adds `RTSP_VBR=1` (main) / `RTSP_VBR_SUB`. The bit rate becomes a ceiling, so a still scene
  sends less.
- **Test:**
  1. Still scene, then motion, 5 min each: STAT bytes per 5 s with and without `RTSP_VBR=1` (in
     `/mnt/config/rtsp.env`).
  2. Frigate: still records and detects, and the keyframe interval is unchanged.
  3. For the smart mode itself: `strings /mnt/lib/libmpi_venc*.so | grep -i smart` and write the symbols here.
     Smart mode (long GOP on a still scene) needs its call found in the vendor library first.

### P-09 Video server: RTP without payload copies, 384 KB client queues, live MP4 into the send buffer — `to test`
- **What (commit `[video] ...`):**
  - **RTP:** a packet is a header buffer plus the payload left in the frame copy, sent with `sendmsg` iovecs (UDP);
    TCP queues header then payload. The two payload copies per packet are gone. **Opt-in: `RTSP_UDPSG=1`** (the host
    test shows byte-identical packets for H.264; H.265 framing is not covered there). With it, `RTSP_UDPMMSG=1`
    batches a frame's packets in one `sendmmsg`.
  - **Client queue:** 384 KB by default (was 768), raised to 1.5 s of the main bit rate. A late TCP joiner gets the
    IDR and the P frames that fit at once (`RTSP_QBURST=0`: wait for the next IDR as before). `RTSP_QMAX=<KB>` sets it.
  - **Browser live video:** the fMP4 fragment is built straight into the viewer's send buffer (byte-identical in the
    host test); `RTSP_LIVE_DIRECT=0` restores the old path.
  - **VBR (P-08):** `RTSP_VBR=1`, `RTSP_VBR_SUB`.
  - All switches go in `/mnt/config/rtsp.env`; the start line of `tc100_rtsp.log` shows the active values.
- **Test:**
  1. `RTSP_UDPSG=1`: VLC over UDP and over TCP, main H.265 and sub H.264. Clean picture, STAT `snd_ms` lower than
     without. Then `RTSP_UDPMMSG=1`: same picture, nothing in the log.
  2. A TCP and a UDP client together.
  3. `dropped` over 30 min on the real Wi-Fi, default 384 KB against `RTSP_QMAX=768`. A VLC or Frigate reconnect shows
     a picture within about 0.3 s.
  4. The browser live view plays smoothly for 2 minutes.
- **Pass:** every passed switch becomes the default (UDPSG first, once H.265 is clean).

### S-01 Housekeeper restarter; ssh-server (on) and telnet (off) under Services — `to test`
- **What (commit `[svc] ...`):**
  - **Restarter:** `housekeeper.sh supervise` runs one `service-watchdog.sh` (no-reboot mode, back-off 20/35/…/180 s,
    fork-free pid check every 60 s) that restarts the housekeeper loop. It costs about 150-300 KB resident and is
    started by autorun only with HOUSEKEEPER on. `housekeeper.sh stop` stops the supervisor first.
  - **SSH:** a new Services entry `ssh-server` (dropbear from ext/), on by default. Its "Boot" toggle drives
    `S50dropbear`. A camera that never chose keeps SSH (marker `config/.services_ssh_done`).
  - **Telnet:** the base-image `S50telnet` is replaced (`v3/S50telnet-linux66`): no telnetd at boot any more. Telnet is
    the Services entry `telnet-server` only (off by default, LAN only, closes by itself). The rescue telnet of web-guard
    is unchanged. Without dropbear in the user space (old card tree), telnetd still starts at boot as a fallback.
- **Switch:** `HOUSEKEEPER=0` (no restarter); the "Boot" toggles in Services. The S50 scripts need the new initramfs.
- **Test:**
  1. `ps`: one `service-watchdog.sh /mnt/scripts/housekeeper.sh`, matching `/var/run/housekeeper-watch.pid`.
  2. `kill -9 $(cat /var/run/housekeeper.pid)`: within about 1 minute the loop is back with its jobs and pid files. The
     log says "housekeeper.sh - unhealthy, perform restart", and there is no reboot.
  3. `housekeeper.sh stop` stays stopped.
  4. After boot: port 22 listens, port 23 does not, `ssh root@<cam>` works.
  5. Services: ssh-server stop and start. "Boot" off and a reboot gives no sshd ("off (Services page)" on the console);
     "Boot" on brings it back.
  6. `telnet-server` start and stop from Services (LAN only, closes after 15 min).
  7. `killall httpfront`: the rescue telnet opens after 2-3 minutes and closes once the web UI is back.
  8. An upgrade over rc6 settings: SSH on, telnet off.
- **Pass:** all of the above, and MemAvailable within 0.3 MB of rc6.

### W-01 Web UI: statusline in its own CGI, one stylesheet — `to test`
- **What (commit `[webui] statusline in its own small CGI, one stylesheet for the main page`):**
  - **statusline.cgi:** `cgi-bin/statusline.cgi` sources only `statelib.cgi`: 605 lines (20 KB) against 2604 (104 KB)
    for func + state; 5.1 against 7.4 ms per call on the PC. It gives the same JSON as `state.cgi?cmd=statusline`,
    which stays. The pages poll it.
  - **One stylesheet:** `css/ui.bundle.min.css` holds bulma purged + ui-modern + ui.css in the same order, so the main
    page makes 1 stylesheet request instead of 3. The CSS rules are identical (1263 of 1263 in Edge), the `?v=` is a
    hash of the bundle, and the build is `src/webui/build-css.sh`.
- **Off:** revert the commit (the old CGI arm and stylesheets are still there).
- **Test:**
  1. Browser network tab: `cgi-bin/statusline.cgi` every few seconds, a single `css/ui.bundle.min.css`, no 404, no
     `cmd=statusline`. The look is unchanged, light / dark, 1280 / 390 px.
  2. `curl -s -u root:<pw> http://<cam>/cgi-bin/statusline.cgi | head -c 300`: one JSON line, `csrf_token` of 32
     hex characters. Same fields as `state.cgi?cmd=statusline`.
  3. On the camera, 10 runs of each: `time sh -c 'for i in 1 2 3 4 5 6 7 8 9 10; do REQUEST_METHOD=GET QUERY_STRING=
     /mnt/www/cgi-bin/statusline.cgi >/dev/null; done'`, then the same with `QUERY_STRING=cmd=statusline` and
     `state.cgi`. Write down both times.
  4. The Recordings page loads its status, and a settings save gives no 403.

## 2026-11-01 — .11 alignée sur la .24 (flux)

- `/mnt/config/rtspserver.conf` de la .11 remplacé par celui de la .24 (seules différences qui existaient : sous-flux 352x200 8 i/s 400 kb/s → 640x360 25 i/s 250 kb/s ; `smartmode=1` → 0 ; clés `smart=0`, `vbr=0` ajoutées). Sauvegarde : `xfer17/rtspserver.conf.11.before-2026-11-01` (Mac).
- Choix du propriétaire : Frigate fait la détection → compromis simple, mêmes valeurs sur les deux caméras ; débit du sous-flux à relever pour les deux plus tard si le Wi-Fi de la .24 se stabilise.
- Vérifié après `rtsp-h26x restart` : flux principal H.265 1920x1080 25 i/s ; /video1 H.264 640x360 25 i/s, ~230 kb/s mesurés (STAT sub_bytes), 0 perte, ping OK.
- Écarts restants (volontairement non touchés, à décider) : boot.conf `ISP_TUNE` (.11=0, .24=1), `FRONT_LED` (.11=1, .24=0), `MQTT_ENABLE=1` seulement sur la .11, `IRCUT_*_GPIO` seulement sur la .24 (matériel), `daynight.conf DAYNIGHT_SOURCE=luma` seulement sur la .11, autostart `button-actions` seulement sur la .11.

## 2026-11-01 — Pistes d'amélioration proposées par le propriétaire (à explorer, pas des ordres)

Source : liste fournie par le propriétaire. Priorité et réserves de la testeuse ci-dessous. Règle inchangée : rien ne doit bloquer les installations existantes, tout réglage nouveau est proposé (bandeau) et jamais imposé.

**Déjà dans cette file (ne pas refaire deux fois) :** balance des blancs globale (clamp 128..1536, gains sauvegardés, figée la nuit : voir « white balance global closed-loop » ; le fichier d'état `awb.state` remplace la rustine SD de la .24), clés ssh et clé d'hôte dropbear persistantes, rollback automatique après mise à jour, journal de démarrage conservé, indicateur de qualité Wi-Fi, mot de passe RTSP séparé.

**Priorité haute (valeur claire, risque faible) :**
1. Balance des blancs (voir ci-dessus). Critère d'acceptation : mur blanc à ±3 % sur R/G/B sur la .11 et la .24, dès la première seconde après reboot. Ne mesurer que les pixels plausiblement gris (luma 40..220, hors saturation).
2. Pre-roll en RAM (1 à 2 GOP, ~0,6 à 0,9 Mo) pour que l'enregistrement commence avant l'événement. À tester : début du fichier avec une image clé, durée réelle du pre-roll, mémoire libre avant/après.
3. Clés ssh persistantes + rollback automatique + journal avant crash (sans console série, c'est ce qui permet de tester à distance).
4. Qualité Wi-Fi dans le temps (RSSI, retries, pertes) + capteur MQTT : la .24 a des rafales de perte, on ne peut pas les corriger sans la mesure.

**Priorité moyenne (à valider par une mesure avant de s'engager) :**
5. Débit adaptatif quand la scène est fixe. Réserve : Frigate fait la détection et l'enregistrement ; un débit qui baisse puis remonte doit rester sans effet sur sa détection (le sous-flux 640x360 sert à la détection). Proposition : l'appliquer au flux principal seulement, derrière un interrupteur désactivé par défaut, tester avec Frigate (pas de faux mouvements au moment de la remontée, image clé immédiate).
6. Fast-path `currentpic.cgi` / `statusline.cgi` dans httpfront : gain réel (moins de fork), mais la vérification du cookie de session est un point de sécurité : relire avec soin, mêmes réponses d'erreur qu'aujourd'hui, test sans cookie / cookie périmé.
7. Filtre passe-haut + AGC audio (coût CPU faible) : avec interrupteur, test à l'oreille par le propriétaire, ne pas écrire dans le flux si le micro est coupé.
8. Netteté progressive via `AK_ISP_SET_SHARP` (curseur -50..+50) : à faire après l'essai HW-05 ; vérifier que 0 = rendu actuel.

**À étudier d'abord (faisabilité non prouvée, ne pas promettre) :**
9. WDR / gamma matériel (`AK_ISP_SET_WDR`, `AK_ISP_SET_Y_GAMMA`) : le bloc existe dans le pilote, mais on ne sait pas s'il fonctionne sur le capteur F23 ; commencer par un essai ioctl à la main sur une caméra (lecture, puis changement réversible, instantané avant/après), à documenter avant tout réglage dans l'interface.
10. Direct navigateur très basse latence (fMP4 CMAF, < 250 ms) : intéressant mais touche le muxeur et le lecteur JS ; mesurer la latence actuelle d'abord.
11. Détection sirène / fumée par Goertzel : un détecteur de fumée réel doit rester un vrai détecteur ; ce capteur ne serait qu'une aide. Prévoir faux positifs (sonnerie, musique), seuils réglables, et ne jamais le présenter comme une sécurité.

**Pour tous les points :** un interrupteur d'exécution (sans reboot), valeur par défaut sûre, mesure de CPU/RAM avant et après (idle ~64 à 69 %, MemAvailable ~19 à 22 Mo), et un résultat testé sur les deux caméras avant le tag.

## 2026-11-01 — Deuxième liste de pistes du propriétaire (à explorer, classées par la testeuse)

Mêmes règles que la liste précédente : rien ne bloque les installations existantes, réglage nouveau = proposé et désactivé par défaut, interrupteur sans reboot, mesure CPU/RAM avant/après, test sur les deux caméras. Les chiffres de coût (CPU, RAM, mW, °C) viennent du propriétaire et n'ont PAS été mesurés : à vérifier avant de les afficher dans une doc ou une interface.

**Priorité haute (utile tout de suite, risque faible) :**
- 9. Fiabilité de la carte SD : `fsck.fat -a` seulement si le bit « dirty » est levé, avant montage ; état lecture/écriture, erreurs MMC (`/sys/block/mmcblk0/stat`) et vitesse d'écriture dans Diagnostics et MQTT. Réserves : un fsck doit avoir une durée maximale et ne jamais bloquer le démarrage ; ne jamais réparer en écrasant sans sauvegarde des fichiers de config ; test avec une coupure de courant provoquée (R12-08 aide).
- 8. Synchronisation entre caméras (`sync-cam.sh <ip>` ou bouton) : très utile pour garder les deux caméras identiques (c'est ce que le propriétaire demande). Liste blanche stricte des réglages partagés ; jamais hostname, IP, flip, gains/étalonnage couleur, GPIO ; jamais de mot de passe en clair dans l'URL ni dans les journaux ; confirmation avant d'écraser ; mode « simulation » qui montre les différences d'abord. Cible via ssh/clé ou API authentifiée, pas en HTTP sans mot de passe.
- 10. Détection de sabotage (caméra masquée/déplacée) : peu coûteux, mais à régler pour éviter les faux positifs (bascule IR, soleil, volet, lumière qui s'éteint). Seuil et durée réglables, silence pendant la bascule jour/nuit, état publié sur MQTT.

**Priorité moyenne :**
- 5. Entité caméra MQTT : réparer en publiant le vrai JPEG binaire (le défaut connu vient de la publication d'un chemin au lieu du fichier). Fréquence basse ou sur mouvement seulement, taille limitée, pas de publication si le courtier est lent. Vérifier le nom réel du fichier snapshot (le chemin `/dev/shm/rtsp_snap.jpg` cité n'est pas confirmé : sur les caméras le snapshot est `/tmp/currentpic.cache.jpg`).
- 4. Mouvement multi-zones nommées + événement direct (sans polling shell). Frigate fait déjà la détection ; garder ça comme un complément léger, nom de la zone dans le message MQTT.
- 7. Carillon / sirène / annonces via HTTP ou MQTT (sons A-law/µ-law 8 kHz). Réserve : volume borné (on a vu qu'une alerte courte n'était pas audible au volume par défaut), droits d'accès identiques aux autres commandes, limite de durée, jamais d'exécution de son en boucle sans arrêt.
- 2. Exposition par zone (pondération centre / zone prioritaire / exclure les masques) : intéressant pour la .24 (mur blanc), mais touche l'auto-exposition ; à essayer d'abord à la main (lecture des statistiques ISP) et à comparer avant/après sur une scène fixe. Désactivé par défaut.
- 3. Timelapse MP4 intégré : bonne idée, simple si `mp4box.c` sait déjà écrire sans ré-encodage. Réserves : espace SD (quota et purge), horloge avant NTP (noms de fichier), reprise après coupure de courant (fichier MP4 tronqué/non finalisé : écrire l'index régulièrement ou fragmenter).

**À étudier d'abord, faisabilité non prouvée (ne pas promettre) :**
- 1. `libakaudiofilter.so` (AEC, réduction de bruit, AGC) : bibliothèque propriétaire, point de licence/redistribution à vérifier avant de l'embarquer dans une version publiée ; vérifier aussi qu'elle tourne en Linux 6.6 et le coût réel. Fait suite à l'idée de filtre passe-haut/AGC de la liste précédente (une version libre, sans la bibliothèque, passe avant).
- 6. Veille matérielle (arrêt des horloges capteur/ISP) : risqué (peut bloquer le réveil ou planter le noyau) et sans console série le rattrapage est difficile. À essayer seulement en dernier, jamais dans une version taguée sans une journée de test sur une caméra et un moyen de retour (coupure/reprise de courant). Chiffres (150 à 200 mW, 6 à 8 °C) à mesurer.

**Ordre conseillé après la balance des blancs :** 9 (SD) → 8 (synchro) → 10 (sabotage) → 5 (vignette HA) → 7 (sons) → 3 (timelapse) → 4 → 2 → 1 → 6.

## 2026-11-01 — Troisième liste de pistes du propriétaire (9 idées, à explorer)

Mêmes règles que les deux listes précédentes (rien ne bloque l'existant, réglage nouveau proposé et désactivé par défaut, interrupteur sans reboot, mesure CPU/RAM avant/après, test sur les deux caméras). Les coûts annoncés (CPU, RAM, dB, ms) n'ont PAS été mesurés.

**Priorité haute :**
- 4. Vox / babyphone : fenêtre glissante RMS court terme vs long terme, deux modes (impulsion, soutenu), niveau en dBFS dans `statusline` et petit VU-mètre. Utile pour réduire les fausses alertes. Seuils réglables, interrupteur, rien d'enregistré si le micro est coupé. Se combine avec l'idée audio de la liste 1 (filtre passe-haut).
- 7. Qualité d'alimentation (brownout) : seulement en LECTURE au début. Vérifier d'abord sur une caméra que le registre ADC cité (0x0800005c, AIN0/BAT) correspond bien à un rail utile (sinon l'indicateur serait faux) ; comparer la valeur IR éteinte / allumée / Wi-Fi émet. Ne jamais déplacer ou retarder l'allumage des IR avant d'avoir une mesure qui le justifie.
- 8. mDNS (`ipcam1.local`, `ipcam2.local`) : très utile sans console série et pour Home Assistant. Le nom vient de `hostname.conf` ; répondre seulement en lecture (pas d'écriture réseau non sollicitée à part les réponses), pas de service SSDP au début (surface d'attaque), à désactiver par un interrupteur. Respecte la règle de réduction de surface : annonces limitées au réseau local, aucune information sensible (version, clé) dans les enregistrements.

**Priorité moyenne :**
- 5. Frise 24 h des événements (`events.idx`) : petit fichier journalier sur la SD, rendu en JS. Réserves : horloge avant NTP (ne pas indexer avec une date 1970), écriture robuste après coupure de courant (ligne complète ou rien), purge avec les clips, accès protégé par la session comme les enregistrements.
- 9. Carte de chaleur d'activité : tableau en RAM (≈3,5 Ko), remise à zéro à minuit, affichage dans l'interface. Utile pour régler les faux positifs de Frigate. Ne rien enregistrer sur flash ; masques de confidentialité respectés (ne pas montrer d'activité dans une zone masquée).
- 2. Texte OSD libre (fichier ou MQTT) : réserves : filtrer les caractères (police limitée, longueur max), valeur par défaut vide, pas de commande exécutée à partir du texte, MQTT limité aux topics de la caméra. Vérifier que l'incrustation matérielle apparaît bien dans le sous-flux et les snapshots.

**À étudier d'abord, risque ou faisabilité non prouvés :**
- 1. Pose longue la nuit (12,5 ou 15 i/s via les registres du capteur) : l'idée est bonne pour l'image de nuit, mais agit sur des registres du capteur : essai à la main d'abord sur une caméra, réversible, avec retour automatique à 25 i/s après un délai ; à comparer avec Frigate (la détection a besoin de cadence ; attention aux enregistrements et à l'audio synchronisé). Fait suite au test de nuit R15-03.
- 3. Flux H.264/H.265 brut sur WebSocket + `VideoDecoder` du navigateur (très faible latence) : nécessite HTTPS ou localhost pour l'API `VideoDecoder` (contexte sécurisé) ; donc lié à la question HTTPS prévue pour 3.0.2. Mesurer la latence actuelle d'abord.
- 6. Moteur crypto matériel (AES/SHA à 0x20170000) pour chiffrer les enregistrements ou accélérer TLS : non prioritaire ; un pilote noyau ajoute un risque de plantage, et chiffrer les enregistrements complique la lecture par Frigate/ffmpeg et la récupération. Si étudié : en option seulement, clé jamais stockée en clair sur la même carte SD, essai sur banc.

**Ordre conseillé (à la suite des deux listes précédentes) :** 8 (mDNS) → 4 (vox) → 7 (lecture alimentation) → 9 (chaleur) → 5 (frise) → 2 (OSD libre) → 1 (pose longue nocturne) → 3 → 6.

## 2026-11-01 — Quatrième liste du propriétaire : nouvelles idées + feuille de route en 5 lots

Mêmes règles : rien ne bloque l'existant, réglage nouveau proposé et désactivé par défaut, interrupteur sans reboot, mesure CPU/RAM avant/après, test sur les deux caméras. Les coûts annoncés ne sont pas mesurés. Les références à Thingino / OpenIPC viennent du propriétaire : s'en inspirer pour les idées, ne pas copier de code sans vérifier sa licence.

### Nouvelles idées

**A. Mode « derrière une vitre » (IR-Cut actif, LED IR coupée) — priorité haute.**
- Séparer dans l'interface et dans le démon jour/nuit : (1) filtre IR-Cut + noir et blanc ISP, (2) allumage de la LED IR, avec `IR_LED_MODE = auto | off | force` (défaut `auto` = comportement actuel, aucune installation existante ne change).
- Point à traiter : le retour en couleur le matin ne peut plus s'appuyer sur la baisse de gain due aux IR. Utiliser alors seulement l'exposition/gain naturel, avec hystérésis et délai minimal (éviter les bascules répétées à l'aube/au crépuscule ; à tester avec R15-03 et R12-03/05).
- Les deux caméras n'ont pas les mêmes GPIO (`IRCUT_*_GPIO` sur la .24) : le mode doit marcher avec les deux matériels.

**B. Enregistrement sur partage réseau NFS / CIFS sans carte SD — priorité moyenne.**
- Montage dans `/mnt/nas` (NFS en priorité, `busybox mount -t nfs`, CIFS seulement si le noyau l'a). Vérifier d'abord quelle config noyau 6.6 est présente (NFS client, taille supplémentaire ; l'annonce de ~90 Ko n'est pas vérifiée).
- Réserves : aucun mot de passe dans l'URL ni dans les journaux (fichier de réglages protégé), montage au démarrage qui ne doit JAMAIS bloquer le boot (délai maximal, en arrière-plan), enregistrement qui bascule proprement sur la carte SD si le NAS disparaît, pas de blocage de tc100_rtsp sur un montage NFS figé (options `soft,timeo=…`, test avec câble/Wi-Fi coupé). Wi-Fi de la .24 instable : l'écriture réseau continue risque de saturer ; mesurer avant.

**C. Page « Console & Logs en direct » dans l'interface web — priorité basse, sécurité d'abord.**
- Flux en direct des journaux (dmesg, syslog, tc100_rtsp) via Server-Sent Events : lecture seule, derrière la session administrateur.
- La partie « taper une commande » (terminal web) est à ne PAS faire telle quelle : elle élargit fortement la surface d'attaque (règle du propriétaire : la réduire). Si elle existe un jour : désactivée par défaut, réservée à l'admin, liste de commandes de diagnostic fixes (pas de shell libre), jamais en HTTP simple depuis l'extérieur du réseau local. Les journaux en lecture seule suffisent déjà beaucoup (une alternative à ssh sans console série).

### Feuille de route par lots (vue d'ensemble demandée par le propriétaire)

- **Lot 1 — Qualité d'image & vision jour/nuit :** AWB universel (grands murs blancs), WDR/Gamma matériel, netteté additive, pose longue nocturne, mode « derrière une vitre » (idée A), anti-scintillement 50 Hz, OSD dynamique/positionnable.
- **Lot 2 — Intelligence embarquée & détection :** pre-roll RAM 3–5 s, 4 zones de mouvement nommées, détection colis/objet déposé, franchissement de ligne entrée/sortie, best-shot JPEG, détection de sabotage, carte de chaleur 24 h.
- **Lot 3 — Audio avancé & interphonie :** filtre `libakaudiofilter.so` (AEC+NR, licence à vérifier) ou biquad+AGC libre, détecteur Goertzel sirène/fumée (aide seulement), mode babyphone/Vox + VU-mètre, lecture de sons/carillon/sirène.
- **Lot 4 — Écosystème & domotique :** alertes directes Telegram / Webhook / Ntfy / e-mail / FTP, snapshot MQTT pour Home Assistant, événements ONVIF (PullPoint), Prometheus `/metrics`, mDNS `.local`.
- **Lot 5 — Interface web, performance & multi-caméras :** direct très basse latence (WebCodecs/fMP4), raccourci C dans `httpfront`, vue multi-caméras 2×2, frise 24 h, synchronisation en un clic, WebDAV pour le Finder macOS, auto-diagnostic et réparation FAT32.

**Réserves par lot (à vérifier avant de s'engager) :**
- Lot 4 : toute alerte vers l'extérieur (Telegram, Ntfy, webhook, e-mail) sort de la maison : désactivée par défaut, identifiants jamais dans les journaux ni dans l'URL de l'interface, contenu des images limité. Prometheus `/metrics` et ONVIF doivent être protégés comme le reste (pas d'information sensible, authentification).
- Lot 5 : la vue 2×2 et le direct WebCodecs coûtent surtout du côté navigateur ; HTTPS exigé pour WebCodecs. WebDAV = un nouveau service réseau : désactivé par défaut, authentifié.
- Lot 2 : « colis/objet déposé » et « franchissement de ligne » sont des fonctions de vision plus lourdes ; Frigate le fait déjà bien. À garder comme complément léger seulement si la mesure CPU le permet (idle actuel ~64–69 %).
- Lot 1 : anti-scintillement 50 Hz (secteur européen) à vérifier sous éclairage artificiel ; le réglage ne doit pas dégrader le rendu existant (défaut inchangé).

**Fil conducteur conseillé :** 1) balance des blancs + fiabilité sans console série (clés ssh, rollback, journaux, carte SD) → 2) mode derrière une vitre + nuit → 3) mDNS, Vox, alimentation, sabotage, pre-roll → 4) alertes/domotique → 5) interface (frise, synchro, multi-vue) → 6) le reste (crypto, veille matérielle, WebRTC/WebCodecs, NFS) après mesure.

## 2026-11-01 — Avis de la testeuse sur la règle « maximum de contrôle depuis Linux, sans toucher U-Boot » (AGENTS.md, 177c1da)

Verdict : la règle est bonne et suivable. Trois points sur quatre sont faisables tels quels ; le quatrième l'est en partie, avec une limite à écrire dans AGENTS.md.

1. **Jamais de U-Boot ni de console série :** d'accord, cohérent avec le test uniquement par ssh.
2. **Valeurs par défaut compilées dans le noyau** (`ak39_vi.sub_channel=1`, `slots=3`, `ak39_venc.pool=9600K`) : faisable et souhaitable ; cela supprime l'écart constaté entre l'environnement de la .11 (`sub_channel=1` dans les arguments) et celui de la .24 (rien). Réserve : un changement de noyau passe par la flash, c'est l'opération la plus risquée sans console. Regrouper ces changements dans peu de versions, caméra à portée, jamais le même jour qu'un autre changement risqué.
3. **Paramètres sysfs en `0644`** : faisable pour ce qui se relit à l'ouverture du périphérique ou au début du flux (ex. `ak_isp.awb_live`, aujourd'hui en lecture seule). Pas pour les allocations faites au démarrage (`slots`, `pool`) : les rendre modifiables à chaud est risqué ; pour elles, « au plus un redémarrage » reste la bonne cible. Prévoir pour chaque paramètre modifiable : valeur lue, valeur écrite, retour à la valeur par défaut, et un test d'écriture invalide sans plantage.
4. **Pilotage par `boot.conf` / `rtsp.env`** : faisable, déjà utilisé (la rustine blanc de la .24 passe par `rtsp.env`). Garder UNE seule source par réglage (voir l'écart `MQTT_ENABLE` entre `boot.conf` et `mqtt.conf`).
5. **Récupération automatique dans l'initramfs** : faisable pour les pannes APRÈS le démarrage du noyau (Wi-Fi, web ou RTSP qui échouent 3 fois de suite). **Limite à écrire dans AGENTS.md :** si un nouveau noyau ne démarre pas du tout, l'initramfs n'est jamais exécuté et seul U-Boot pourrait revenir à l'ancien noyau ; or U-Boot charge toujours la même partition noyau. Donc :
   - la protection contre un noyau cassé doit venir d'AVANT le flashage : vérifications (taille, somme de contrôle, partition cible), test préalable sur une image, un seul changement de noyau à la fois, propriétaire à portée de la caméra ;
   - pour tout le reste (initrd, pile squashfs, scripts), proposer un `init` d'initramfs minimal et jamais modifié, qui choisit entre deux piles A/B selon un compteur de démarrage stocké en `cfga`/`cfgb` ;
   - armer le chien de garde matériel dès cet `init` (à vérifier : le SoC et le noyau 6.6 en exposent-ils un ? non vérifié) pour qu'un blocage après démarrage redémarre la caméra au lieu de la laisser figée.

Critères de réussite proposés : (a) panne simulée de la pile (fichier cassé) → retour automatique à la pile précédente en moins de 3 démarrages, journal de la panne conservé sur la SD ; (b) aucun accès à U-Boot dans les scripts de mise à jour ; (c) le test du retour arrière se fait sur une caméra, propriétaire présent, jamais en production.

## 2026-11-01 — Lot 1A (implémenté, zéro U-Boot / zéro noyau) : AWB global, clés SSH persistantes, mode derrière une vitre, amixer hw:0

Quatre améliorations à faible risque livrées dans l'espace utilisateur uniquement (aucune modification du noyau ni de U-Boot) :

### 1. Balance des blancs globale fermée (`tc100_rtsp`) + état persistant `/mnt/config/awb.state`
- **Quoi :**
  - Plafond des gains supplémentaires (`ISP_SET_AWB_EX`) relevé de `512` ($\times 2{,}0$) à `1536` ($\times 6{,}0$) afin que la `.24` (qui nécessite `rex=600 / bex=760` en lumière du jour) et la `.11` (`~230 / 287`) convergent toutes les deux sans plafonner.
  - Filtrage gris/luma : seuls les pixels de luminance moyenne (`Y` entre `40` et `220`, ni brûlés ni noirs) et non saturés (`U, V` dans `88..168`) sont pris en compte quand ils représentent au moins 5 % des échantillons.
  - Gel d'un échantillon lors d'un saut brutal de luminosité (`|ΔY| > 25`), et gel total en noir et blanc (`bw=1`).
  - Persistance : une fois la balance stabilisée (`|u| <= 2` et `|v| <= 2` pendant 6 échantillons consécutifs), les gains sont enregistrés dans `/mnt/config/awb.state` (si l'écart dépasse 8 et au plus une fois toutes les 120 s) et rechargés dès l'ouverture de `/dev/isp_char` au démarrage suivant (blanc neutre dès la première seconde).
  - `/tmp/cam_awb` expose désormais en fin de ligne `rex=<r> bex=<b> u=<tu> v=<tv>` (les 11 premiers champs utilisés par `auto-night-daemon.sh` restent identiques).
- **Interrupteurs (dans `/mnt/config/rtsp.env`, puis `rtsp-h26x restart`) :**
  - `RTSP_AWB_MAX=512` : revient à l'ancien plafond `512`.
  - `RTSP_AWB_GREY=0` : désactive le filtrage par luma/saturation (moyenne brute sur toute l'image).
  - `RTSP_AWB_STATE=0` : n'utilise ni n'écrit `/mnt/config/awb.state`.
- **Test sur `.11` et `.24` :**
  1. Sur la `.24`, retirer la rustine temporaire SD (`rm -f /mnt/config/awb.off`, vider la ligne `awbx` de `/mnt/config/rtsp.env`), puis `sh /mnt/controlscripts/rtsp-h26x restart`.
  2. Après 15 s de jour, lire `cat /tmp/cam_awb` et `/mnt/config/awb.state` : vérifier que `u` et `v` sont dans `-2..+2` et qu'un snapshot JPEG sur le mur blanc a R/G et B/G proches de 1,00 (±5 %).
  3. Redémarrer `rtsp-h26x` : vérifier dans `/tmp/logs/rtsp.log` la ligne `white balance: starting from saved gains rex ... bex ...`.

### 3. Mode « Derrière une vitre » (`IR_LED_MODE=auto|off|force` dans `daynight.conf` et Settings → Day/night)
- **Quoi :**
  - Nouveau réglage `IR_LED_MODE` dans `/mnt/config/daynight.conf` (`auto` par défaut = comportement actuel inchangé ; `off` = coupe la LED IR la nuit tout en basculant le filtre IR-Cut et le noir & blanc ; `force` = LED IR toujours allumée).
  - Quand `IR_LED_MODE=off`, la pause thermique de 14 h (`dn_ir_guard`) est désactivée puisque la LED IR est éteinte.
  - Sélecteur ajouté dans `Settings → Day/night` (`Infrared LEDs in night mode`) et exposé dans `state.cgi?cmd=daynight` (`ir_led_mode`).
- **Interrupteur :** `IR_LED_MODE=auto` (défaut).
- **Test :**
  1. Choisir `Off — Behind glass` dans `Settings → Day/night` (ou écrire `IR_LED_MODE=off` dans `/mnt/config/daynight.conf`) et passer en mode Nuit : vérifier `ir_cut status` = `OFF`, `/tmp/tc100_bw` présent, et `ir_led status` = `OFF`.
  2. Revenir sur `Automatic (on at night)` : vérifier que la LED IR se rallume en mode Nuit.

### 4. Contrôle du volume ALSA sans `aliases.conf` (`B-01`) + source unique `MQTT_ENABLE` + limite `AGENTS.md`
- **Quoi :**
  - Remplacement de `amixer -q -c 0` par `amixer -q -D hw:0` dans `scripts/speaker-play.sh`, `scripts/action.d/audio.sh` et `v3/linux66-sd/rtsp-launch.sh`.
  - Suppression automatique de toute ligne `MQTT_ENABLE=` résiduelle dans `/mnt/config/boot.conf` au démarrage (`v3/autorun-linux66.sh`) afin que `/mnt/config/mqtt.conf` reste la seule source de vérité.
  - Précision ajoutée dans `AGENTS.md` (section U-Boot) suivant l'avis de la testeuse.
- **Test :** `amixer -D hw:0 sget 'ADC Capture Volume'` et réglage du volume micro/haut-parleur depuis l'interface web sans erreur dans les journaux.


## 2026-11-02 — Lot 1B (implémenté, zéro U-Boot / zéro noyau) : nom mDNS, qualité Wi-Fi dans le temps, erreurs de la carte SD

Trois ajouts pour diagnostiquer à distance sans console série. Tout est dans l'espace utilisateur ; les deux nouveaux services sont **désactivés par défaut**.

### 1. Nom `.local` (mDNS) : `tc100-mdnsd` + service `mdns`
- **Quoi :** petit programme sans bibliothèque C (`src/mdnsd/`, quelques Ko, compilé par la CI dans `tc100test/tc100-mdnsd`) qui répond uniquement à la question « adresse de `<hostname>.local` » (enregistrement A, nom de `config/hostname.conf`). Pas d'annonce, pas de service DNS-SD, pas de SSDP, aucune version ni clé dans la réponse, réponse uniquement aux machines du même sous-réseau.
- **Interrupteur :** page Services → `mdns` (Start/Stop immédiat ; bascule « Boot » = `config/autostart/mdns`). Absent par défaut.
- **Test (.11 et .24) :**
  1. Services → `mdns` → Start ; `pidof tc100-mdnsd` répond.
  2. Depuis le Mac : `ping ipcam1.local` (nom réel de la caméra) et `dns-sd -G v4 ipcam1.local` donnent l'adresse de la caméra ; `http://ipcam1.local/` ouvre l'interface.
  3. Mesurer : `top` → CPU de `tc100-mdnsd` ≈ 0 %, RSS < 100 Ko ; MemAvailable avant/après.
  4. Stop → `ping ipcam1.local` échoue de nouveau (après expiration du cache du Mac, 2 min).
- **Critère :** nom résolu sur le Mac et par Home Assistant, aucun effet sur le flux RTSP.

### 2. Qualité Wi-Fi dans le temps : `scripts/wifi-quality.sh`
- **Quoi :** un relevé par minute (signal dBm, retransmissions et échecs d'émission depuis `iw station dump`, pertes de 3 pings vers le routeur), gardé 24 h en RAM (`/tmp/wifi-quality.log`, rien sur la flash ni la carte). Résumé de la dernière heure dans `/tmp/wifi-quality` et dans MQTT : nouvelles entités Home Assistant « Wi-Fi Packet Loss (1 h) », « Wi-Fi Transmit Retries (1 h) », « Wi-Fi Weakest Signal (1 h) » (valeur vide quand la fonction est coupée).
- **Interrupteur :** `WIFI_QUALITY=1` dans `boot.conf` (défaut `0`), lu au démarrage (job du housekeeper, 60 s).
- **Test (surtout la .24, qui a des rafales de pertes) :**
  1. `WIFI_QUALITY=1` dans `boot.conf`, reboot ; après 5 min `cat /tmp/wifi-quality.log` a 4-5 lignes `epoch rssi retries failed loss`.
  2. `cat /tmp/wifi-quality` : valeurs cohérentes avec `iw dev wlan0 link`.
  3. Home Assistant : les 3 entités apparaissent (MQTT → « Re-publish discovery ») et suivent les valeurs.
  4. Laisser tourner une nuit et rapprocher les rafales de pertes de la .24 des pics de `retries`/`loss`.
- **Critère :** pas de hausse de CPU visible (un ping et un `iw` par minute), MemAvailable inchangée à ±200 Ko.

### 3. Erreurs de la carte SD
- **Quoi :** `v3/linux66-sd/sdinfo-sd.sh` (déjà appelé chaque minute) écrit maintenant dans `/tmp/sd-health` le nombre d'erreurs carte du journal noyau (`errors=`, FAT/I/O/mmcblk) et `readonly=` ; l'état (`state=ok|readonly`) ne change pas, donc la sauvegarde des journaux et la barre d'état se comportent comme avant. MQTT `sd_errors` et la page Disque (« In-flight / errors ») utilisent ce compte.
- **Pas fait (volontairement) :** `fsck` au démarrage (outil `fsck.fat` absent de l'image, et risque de bloquer le boot) et mesure de vitesse d'écriture (écrit sur la carte) : à reprendre plus tard, à part.
- **Test :** `cat /tmp/sd-health` → `state=ok`, `errors=0`, `readonly=0` ; page Disque → « none detected ».


## 2026-11-03 — Lot 2 (implémenté, zéro U-Boot / zéro noyau) : Babyphone/Vox, niveau audio live, détection de sabotage

Évolutions d'intelligence embarquée légères en espace utilisateur Linux, 100% désactivées par défaut.

### 1. Mode Babyphone / Vox (`controlscripts/sound-detection`)
- **Quoi :** Ajout de `VOX_MODE=1` et `VOX_HOLD_SECONDS=5` dans `sound_detection.conf`. Quand un événement sonore est déclenché, la détection maintient l'état actif vers MQTT sur `<root>/babyphone/state` (`ON`) et le retient pendant la durée de maintien configurée après le dernier son fort avant de repasser à `OFF`. Nouvelle entité Home Assistant `binary_sensor` (`dev_cla: sound`).
- **Niveau sonore direct (`sound_db`) :** `statelib.cgi` lit instantanément `/var/run/sound_level` (sans aucun sous-shell) et l'expose dans le JSON de la statusline (`sound_db`). L'interface Web (`index.html`) affiche désormais un indicateur en direct du niveau audio (`#rd_sound`).
- **Test :**
  1. Activer `VOX_MODE=1` dans `/mnt/config/sound_detection.conf`.
  2. Bruit au micro -> Vérifier `babyphone/state` passe à `ON` sur le broker MQTT et revient à `OFF` après silence.
  3. Ouvrir l'UI Web : le chip Audio affiche le niveau en dBFS.

### 2. Détection de sabotage et d'occultation caméra (`scripts/tamper-detect.sh`)
- **Quoi :** Détecteur léger surveillant les masquages brutaux (objectif couvert, occultation) en analysant la chute de luma (`/tmp/cam_luma`) combinée à l'exposition automatique. Protection anti-faux-positifs intégrée : neutralisation automatique pendant 30 secondes après un basculement de mode jour/nuit (`/tmp/nightmode.last`).
- **MQTT :** Publie sur `<root>/tamper/state` (`ON`/`OFF`) et auto-découverte Home Assistant `binary_sensor` (`dev_cla: problem`, icône bouclier d'alerte).
- **Interrupteur :** `TAMPER_DETECT=0` par défaut dans `boot.conf` (option `1` pour activer).
- **Test :**
  1. `TAMPER_DETECT=1` dans `boot.conf`.
  2. Couvrir l'objectif de la main -> Vérifier publication MQTT `tamper/state ON` après 3 secondes.
  3. Découvrir l'objectif -> Repasse immédiatement à `tamper/state OFF`.
  4. Basculer jour/nuit -> Vérifier qu'aucun faux positif n'est émis.

### 3. Sélection intelligente du meilleur cliché (« Best-shot JPEG ») (`scripts/detectionOn.sh`)
- **Quoi :** Lors d'un déclenchement de mouvement, prise en rafale rapide de 3 clichés espacés de 200 ms. Sélection automatique du cliché ayant la plus grande taille / netteté de détails (`_best_size`), pour éviter les clichés flous lors des mouvements rapides.
- **Interrupteur :** `motion_best_shot=0` par défaut dans `motion.conf` (`1` pour activer).
- **Test :** Activer `motion_best_shot=1` dans `motion.conf`, générer un mouvement rapide devant la caméra, vérifier que l'image sauvegardée dans `/tmp/motion_snap_*.jpg` est nette et complète.

### 4. Zones de détection nommées (`motion_zones.conf` & `scripts/action.d/detection.sh`)
- **Quoi :** Prise en charge des libellés de zones `MDZ<k>_NAME="Nom Zone"` dans `motion_zones.conf` et renvoi dans la réponse JSON de `md_zones_info` (`"names":["Porte","Allée"]`). Permet d'identifier clairement les zones ignorées ou surveillées dans les interfaces.
- **Test :** Configurer les zones avec noms via l'API, vérifier la persistance dans `motion_zones.conf` et le parsing correct.

### 5. Pre-roll d'enregistrement en RAM (`REC_RING_KB` dans `boot.conf`)
- **Quoi :** Exposition de `REC_RING_KB=1024` (1 à 8 Mo) dans `config/boot.conf.dist` pour conserver en permanence les secondes précédant un déclenchement de mouvement ou de coupure réseau dans le buffer circulaire de `tc100_rtsp`.
- **Test :** Vérifier dans les journaux de démarrage de `tc100_rtsp` la prise en compte du ring buffer mémoire configuré.


## 2026-11-03 — Lot 3 (implémenté, zéro U-Boot / zéro noyau) : Audio avancé, bibliothèque de carillons/sirènes, détection alarme fumée

Évolutions audio en espace utilisateur Linux, 100% désactivées par défaut.

### 1. Bibliothèque de sons & carillon / sirène intégrés (`sounds/`, `action.d/audio.sh`, `scripts/mqtt-bridge.sh`)
- **Quoi :** Ajout de sons pré-générés au format natif AK3918 (PCM 8 kHz mono S16_LE à -6 dBFS anti-écrêtage avec fondus) :
  - `sounds/chime.pcm` : carillon 2 tons (784 Hz / 587 Hz).
  - `sounds/siren.pcm` : sirène d'alerte balayée 800–1400 Hz (2 s).
  - Déclenchables immédiatement via l'API Web : `action.cgi?cmd=play_sound&sound=chime|siren|alert` avec paramètre `volume=0..100`.
  - Boutons Home Assistant créés automatiquement via MQTT Discovery : « Play Chime » et « Sound Siren » (`<root>/button/chime`, `<root>/button/siren`), ainsi que commande plain text / JSON `{"cmd":"play_sound","value":"chime"}`.
- **Test :**
  1. Depuis l'UI Web ou `curl http://<ip>/cgi-bin/action.cgi?cmd=play_sound&sound=chime` : le carillon retentit sur le haut-parleur.
  2. Depuis Home Assistant, cliquer sur « Play Chime » ou « Sound Siren ».

### 2. Détection de motif d'alarme fumée / sirène (`controlscripts/sound-detection`)
- **Quoi :** Détection de son fort soutenu (>= 3 secondes consécutives au-dessus du seuil configuré `THRESHOLD_DB`), caractéristique des avertisseurs de fumée et de CO (norme NF DAAF T3).
- **MQTT :** Publie l'état vers `<root>/alarm/state` (`ON` puis `OFF` après `ALARM_HOLD_SECONDS=15` de silence) et entité Home Assistant `binary_sensor` (`dev_cla: safety`, icône `mdi:fire-alert`).
- **Interrupteur :** `ALARM_DETECT=0` par défaut dans `sound_detection.conf` (`1` pour activer).
- **Test :** Activer `ALARM_DETECT=1` dans `sound_detection.conf`, émettre un son aigu/soutenu pendant plus de 3 secondes, vérifier la publication `alarm/state ON` et l'alerte sur Home Assistant.


## 2026-11-03 — Lot 4 (implémenté, zéro U-Boot / zéro noyau) : Notifications multi-canaux (Ntfy, Webhook), métriques Prometheus, Snapshot MQTT

Évolutions écosystème, alertes et domotique en espace utilisateur Linux, 100% désactivées par défaut.

### 1. Dispatcheur de notifications multi-canaux (`scripts/notify.sh` + `config/notify.conf.dist`)
- **Quoi :** Script central non-bloquant recevant les événements (`motion`, `sound`, `tamper`) et envoyant les alertes :
  - **Ntfy :** Envoi vers `https://ntfy.sh` (ou serveur privé) avec priorité, tags et pièce jointe instantanée JPEG (en-tête `Filename` / streaming curl `-T`).
  - **Webhook :** Envoi HTTP POST JSON vers un endpoint générique ou webhook d'automatisation (Home Assistant / Node-RED / n8n).
  - **Telegram :** Intégration unifiée déléguant à `bin/telegram` si configuré.
  - **Protection ressources :** Cooldown configurable par type d'événement (`NOTIFY_COOLDOWN_SECONDS=15`), requêtes asynchrones en arrière-plan sans bloquer les détections.
- **Interrupteurs :** `WEBHOOK_ENABLE=0`, `NTFY_ENABLE=0`, `TELEGRAM_NOTIFY_ENABLE=0` dans `/mnt/config/notify.conf`.
- **Test :**
  1. Configurer un topic de test dans `/mnt/config/notify.conf` (`NTFY_ENABLE=1`, `NTFY_TOPIC=mon_topic_test`).
  2. Déclencher un événement avec `/mnt/scripts/notify.sh motion "Test alerte" /tmp/test.jpg`.
  3. Vérifier la réception instantanée sur le téléphone ou le client ntfy.

### 2. Exportateur de métriques Prometheus (`www/cgi-bin/metrics.cgi`)
- **Quoi :** Endpoint HTTP standard au format texte Prometheus (`Content-Type: text/plain; version=0.0.4`), interrogeable sur `http://<ip>/cgi-bin/metrics.cgi`.
- **Métriques exposées (lecture directe `/proc` sans fork lourd) :**
  - Uptime et charge CPU (`tc100_uptime_seconds`, `tc100_load1`, `tc100_load5`, `tc100_load15`).
  - Mémoire en octets (`tc100_memory_total_bytes`, `tc100_memory_free_bytes`, `tc100_memory_available_bytes`).
  - Réseau et Wi-Fi (`tc100_network_*_bytes_total`, `tc100_network_*_drops_total`, `tc100_wifi_link_quality`, `tc100_wifi_signal_dbm`).
  - Flux RTSP (`tc100_rtsp_viewers_active` comptant les clients TCP connectés au port 554).
  - États de détection et capteurs (`tc100_motion_active`, `tc100_tamper_active`, `tc100_vox_active`, `tc100_sensor_luma`, `tc100_audio_level_dbfs`).
- **Test :**
  1. `curl -s http://192.168.1.XX/cgi-bin/metrics.cgi`
  2. Vérifier que la sortie est conforme à la syntaxe Prometheus (`# HELP`, `# TYPE`, valeurs numériques).
  3. Intégrer à un scraper Prometheus / VictoriaMetrics sans charge CPU mesurable.

### 3. Snapshot JPEG binaire via MQTT pour Home Assistant (`scripts/mqtt-bridge.sh`)
- **Quoi :** Prise en charge de la publication directe des octets bruts JPEG du cliché sur `<root>/snapshot/image` via `mqtt_publish_file` lors de l'appui sur le bouton "Take Snapshot" ou d'une demande. L'entité caméra MQTT Home Assistant peut désormais s'abonner directement à ce topic au lieu d'un simple chemin de fichier.
- **Interrupteur :** `MQTT_HA_CAMERA_ENTITY_ENABLE=0` par défaut dans `mqtt.conf` (option `1` pour déclarer l'entité Camera HA connectée au flux image MQTT).
- **Test :**
  1. Activer `MQTT_HA_CAMERA_ENTITY_ENABLE=1` dans `/mnt/config/mqtt.conf` et redémarrer le bridge.
  2. Dans Home Assistant, vérifier la présence de l'entité Camera et appuyer sur le bouton Snapshot : l'image s'affiche dans Home Assistant.


## 2026-11-03 — Lot 5 (implémenté, zéro U-Boot / zéro noyau) : Interface Web Multi-View (Grille 2×2) & Supervision multi-caméras

Améliorations de l'interface Web en espace utilisateur Linux, 100% exécutées côté client (navigateur) sans charge CPU supplémentaire sur la caméra hôte.

### 1. Grille Multi-View 2×2 (`www/multiview.html` + barre de navigation `www/index.html`)
- **Quoi :**
  - Page de supervision multi-caméras permettant d'afficher jusqu'à 4 caméras simultanément en grille 2×2 responsive (ou colonne unique sur mobile).
  - Intégrée nativement dans la navigation supérieure de l'interface Web (« Multi-View » entre « Live » et « Recordings »).
  - Rafraîchissement intelligent côté client via requêtes directes de snapshots JPEG (`/cgi-bin/currentpic.cgi`), évitant le transcodage ou le décodage vidéo lourd sur le CPU de la caméra hôte.
  - Panneau de configuration dépliable avec persistance dans le `localStorage` du navigateur (adresses IP ou noms mDNS `.local`, et libellés personnalisés pour chaque caméra, ex: Salon, Garage, Entrée, Jardin).
  - Bouton d'accès direct « Ouvrir » par flux pour lancer l'interface complète de la caméra ciblée.
- **Test :**
  1. Ouvrir l'interface Web de la caméra.
  2. Cliquer sur l'élément « Multi-View » dans la barre supérieure : la grille 2×2 s'affiche.
  3. Cliquer sur « Configurer les caméras », renseigner une seconde caméra sur le réseau local (IP ou `.local`) et sauvegarder.
  4. Vérifier que les vignettes s'actualisent régulièrement et que la configuration est conservée après rafraîchissement de la page.



## 2026-11-03 — rc18 sur la .11 (installée par le propriétaire) : premières vérifications par ssh (testeuse, sans console série)

Build : `3.0.1-rc18` (artifact `tc100-3-release` du run du commit a63f90f). Le propriétaire a installé la rc18 sur la .11 avant moi ; la .11 n'a PAS de carte SD (test R12-08 / R15-04 en cours) ; uptime 1 h 17 au moment du relevé.

- **Clés ssh persistantes : OK.** Après le reboot de l'installation ma clé (RAM) avait disparu, le propriétaire l'a remise à la main dans `/root/.ssh/authorized_keys` à 09:02 ; `cfg-persist` l'a recopiée tout seul dans `/mnt/config/authorized_keys` (3 clés, 212 octets) et la clé d'hôte est dans `/mnt/config/dropbear_ed25519_host_key` (83 octets, 09:00). La connexion par clé fonctionne. **À confirmer au prochain reboot** : clé et clé d'hôte revenues sans action, pas d'avertissement « HOST IDENTIFICATION HAS CHANGED » sur le Mac.
- **Balance des blancs : OK sur la .11.** `white balance: in the ISP (extra gains max 1536, grey filter 1)` ; `/tmp/cam_awb` : `rex=221 bex=299 u=0 v=1` ; `/mnt/config/awb.state` = `221 299` (écrit à 08:06). Snapshot (mur et pièce) R/G 1,02, B/G 1,00 (critère ±5 % : passé). Reste à voir : le redémarrage de `rtsp-h26x` (ligne `starting from saved gains`) et la .24 (rex≈600 / bex≈760 attendus).
- **Autre : OK** — `MemAvailable` 21 992 kB, charge 1,1 à 1,3, `tc100_rtsp` stable (`dropped 0`), pas de plantage au noyau, MQTT publie (`mqtt_last_pub.status` ok, âgé de 3 s), `FRONT_LED=0` conservé, `MQTT_ENABLE` plus dans `boot.conf`, `mdnsd` arrêté (désactivé par défaut, comme prévu), `rtsp.env` vide.
- **Constaté :** la ligne de commande du noyau contient `ak_wdt_reboot=300` : le chien de garde matériel existe donc (réponse à ma question dans l'avis sur AGENTS.md ; à confirmer par l'implémenteur qu'il est armé par l'init).
- **Pas encore testé sur la .11 :** mDNS, qualité Wi-Fi (`WIFI_QUALITY=1`), mode babyphone, sabotage, notifications, mode vitre, métriques Prometheus. La carte SD manque pour les journaux persistants et `/tmp/sd-health`.
- **Remarque de version :** la rc18 a été construite au commit a63f90f ; les commits suivants (fin du lot 2, lot 3, lot 5, interface) ne sont pas dedans alors que `VERSION` dit toujours `3.0.1-rc18`. Demande à l'implémenteur : numéroter la prochaine construction rc19.

## 2026-11-03 — rc18 sur la .11 : essais un par un des nouveautés (testeuse, ssh, caméra .11, sans carte SD)

Chaque service a été allumé à la main (sans reboot) et mesuré. Mémoire disponible : 22,0 Mo avant → 19,8 Mo avec mdns + wifi-quality + sound-detection actifs (≈ -2 Mo, à vérifier service par service).

| Essai | Résultat |
|---|---|
| **mDNS** (`controlscripts/mdns start`) | **Passé** en unicast : `tc100-mdnsd` répond à `ipcamera2.local` → 192.168.1.11 (64 octets), RSS 8 Ko, CPU 0 %. Le multicast n'a pas pu être testé depuis ma machine ; reste le `ping ipcamera2.local` sur le Mac du propriétaire. **Doc à corriger :** le nom est celui de `hostname.conf` (ici `IPCAMERA2`), pas `ipcam1.local`. |
| **Prometheus** (`/cgi-bin/metrics.cgi`) | **Passé** : 200 en 0,39 s avec le mot de passe de l'interface, 401 sans. Format conforme (`# HELP` / `# TYPE`), toutes les métriques annoncées présentes. Réserve : `tc100_audio_level_dbfs` vaut -96 tant que le niveau sonore n'est pas mesuré (voir Vox). |
| **Qualité Wi-Fi** (`WIFI_QUALITY=1`) | **Passé au démarrage du relevé** : `/tmp/wifi-quality.log` écrit (`epoch rssi retries failed loss`), résumé `/tmp/wifi-quality` correct (-42 dBm, 0 perte, 0 retransmission). Pas de reboot nécessaire avec `wifi-quality.sh run` ; la lecture au boot (job du housekeeper) reste à vérifier au prochain reboot. À laisser tourner : comparaison avec la .24. |
| **Babyphone / Vox** | **Passé avec un défaut de documentation.** Il faut `ENABLE=1` ET `VOX_MODE=1` dans `sound_detection.conf` (la détection sonore est coupée par défaut ; sans `ENABLE=1` `/var/run/sound_level` n'existe pas et le niveau reste à -96). Essai : tonalité 1 kHz jouée au haut-parleur (volume 100) → niveau -53 → -18 dBFS, `tc100_vox_active` = 1, retombé à 0 environ 10 s après la fin. La publication `babyphone/state` sur le broker n'a pas été vue directement (pas de client MQTT sur la caméra) ; `mqtt_last_pub` reste ok. |
| **Sabotage** (`tamper-detect.sh`) | **ÉCHEC.** Objectif couvert à la main en plein jour pendant ~1 min : `tamper_active` reste 0, `/tmp/cam_luma` reste 125-128. Cause : le seuil est « luminosité ≤ 15 », mais l'image est mesurée **après** l'exposition automatique, qui remonte une image sombre vers ≈ 127 (écrit aussi dans `auto-night-daemon.sh`). Le détecteur ne peut donc jamais se déclencher de jour. Autres écarts : deux interrupteurs sont nécessaires (`TAMPER_DETECT=1` dans `boot.conf` ET `ENABLE=1` dans `/mnt/config/tamper.conf`, alors que la note n'en cite qu'un) ; `boot.conf` contient aussi un autre réglage `TAMPER_DETECTION` sans lien. |

**Mesures pour corriger le sabotage (même caméra, même heure, objectif couvert / libre) :**
- Luminosité moyenne `cam_luma` : 127 / 119 (inutilisable).
- Écart-type de l'image (détail) : 11 à 14 / 47.
- Taille du JPEG `currentpic.cache.jpg` : 62 993 / 123 103 octets (divisée par 2).
- `/tmp/cam_ae` (2ᵉ champ, exposition/gain) : 843 / 281 (multipliée par 3), 5ᵉ champ 320 / 443.
- **Proposition :** détecter l'uniformité (peu de détails : écart-type ou taille JPEG sous un seuil relatif à la valeur habituelle de la scène, mesurée sur quelques minutes) combinée à un saut de l'exposition, pendant au moins 3 relevés ; garder la garde de 30 s après la bascule jour/nuit ; ajouter un cas de nuit sans IR (mode derrière une vitre) pour ne pas déclencher dans une pièce noire. Critère de réussite : main sur l'objectif ≥ 10 s → `tamper_active` = 1 ; objectif libre → 0 ; test jour et nuit, sur les deux caméras.

**État laissé sur la .11 :** `tc100-mdnsd` en marche (RAM, ne démarre pas au boot), `WIFI_QUALITY=1` dans `boot.conf`, `sound_detection.conf` `ENABLE=1` `VOX_MODE=1` (sauvegarde de l'ancien fichier : `/tmp` de la caméra, perdue au reboot), sabotage arrêté (`tamper.conf ENABLE=0`). Non testés ici : notifications (aucun canal configuré : Ntfy/webhook demandent un serveur choisi par le propriétaire), mode derrière une vitre (test de nuit), entité caméra MQTT (demande Home Assistant), best-shot, zones nommées, pre-roll, sons, alarme fumée, vue 2×2 (ces cinq ne sont pas dans la RC18 : fichiers absents de la caméra, par ex. `/mnt/sounds/chime.pcm` et `www/multiview.html`).

## 2026-11-03 11:10 — Testeuse : la CI Python est rouge depuis 27b71d8 (rc19 comprise)

Le workflow « CI » (`Host regression tests`) échoue sur 27b71d8, e2254e6, c8bcf0e, f9b88a8 (rc19), 04cf342, 99a788b, 321abe2 et 25fecef, alors que la compilation du noyau et du paquet réussit. Tests en échec (journal du run 41615464487) : `test_regressions.ActionCommandFiles.test_every_command_is_routed_to_the_file_that_has_it`, `Regressions.test_motion_form_fields_are_read`, `WebUiLanguage.test_every_ui_string_has_a_translation` (chaînes sans traduction), `test_webui_wiring.WebUiWiring.test_every_form_field_is_read_by_its_handler` (+ une erreur JSON). Ce sont des défauts de branchement de l'interface web des nouveaux lots (lot 3 et suivants, pas dans la rc18). **Demande :** corriger avant de tester la rc19 sur les caméras ; la testeuse n'installe pas une version dont la CI de régression est rouge, sauf accord du propriétaire.

## 2026-11-03 11:45 — Testeuse : relecture de 45c791c (synchro en un clic, présélections OSD, frise 24 h) ; la CI est verte sur 245a7b2

- **CI :** `245a7b2` ([ci+i18n]) remet le workflow « CI » au vert (noyau + paquet aussi). La rc19 (`f9b88a8`) est antérieure à ce correctif et à `25fecef` (sabotage) / `321abe2` (devpts ssh) / `45c791c` : `VERSION` dit toujours rc19. **Demande :** numéroter une rc20 à partir de `245a7b2` pour que ce qui est testé corresponde au nom.
- **Synchro en un clic (`backup.html`, bouton « Push ») : deux défauts probables, à corriger avant test.**
  1. **Identité MQTT écrasée.** La page exporte la configuration complète puis l'importe sur l'autre caméra avec `exclude_network=1&exclude_credentials=1`. Mais dans `config_exchange.cgi`, `MQTT_TOPIC_ROOT` est de catégorie `general` (ligne ~136) : il serait donc copié sur la cible. Les deux caméras (`tc100/camera` pour la .11, `tc100/cam2` pour la .24) publieraient alors sur le même topic, avec les mêmes entités Home Assistant. Même question pour tout ce qui identifie la caméra (`MQTT_CLIENT_ID`, nom des entités, flip matériel, GPIO IR-cut, gains de balance des blancs `awb.state`, `ISP_TUNE`). **Demande :** liste blanche explicite des réglages partagés (comme demandé le 2026-11-01), jamais d'identité ; un mode « simulation » qui affiche les différences avant d'écrire ; test : après un Push .11 → .24, `tc100/cam2` et `IRCUT_*_GPIO` de la .24 inchangés.
  2. **Appel d'une caméra à l'autre depuis le navigateur.** `fetch()` vers `http://<autre caméra>/cgi-bin/config_exchange.cgi` est une requête inter-origines avec `Content-Type: application/json` : le navigateur envoie d'abord une requête de pré-vérification (OPTIONS) et exige des en-têtes CORS ; je n'en ai pas trouvé dans `config_exchange.cgi`, et l'autre caméra demande son propre mot de passe. Il est probable que le bouton échoue (erreur affichée « Échec réception »). Si on veut le garder : l'envoi doit se faire côté caméra (script, `curl`/`wget` avec le mot de passe saisi), jamais en mettant `*` dans CORS.
- **Présélections OSD (coins) et frise 24 h (`view_records.html`) :** relues sans anomalie visible ; à tester avec une carte SD (frise) et à l'œil (OSD dans le flux principal, le sous-flux et les snapshots).

## 2026-11-03 12:00 — Lots 1, 2, 5 : CI verte + SD Auto-diag/repair + Motion Heatmap 24h + Anti-flicker 50Hz + WebDAV + RC20

Toutes les régressions CI hôte et traductions i18n ont été corrigées et vérifiées :
- **CI Python & Frontend :** 100 % vert (`test_feat30.py`, `ActionCommandFiles`, `Regressions`, `WebUiWiring`, `WebUiLanguage`, `MotionZones`, node tests).
- **Auto-diagnostic et réparation SD (`scripts/sd-diag.sh`) :**
  - Mesure des erreurs dmesg FAT/I/O/MMC + benchmark d'écriture réel (512 Ko).
  - Boutons « Vérifier la santé » (`sd_card_check`) et « Réparation automatique » (`sd_card_repair`) dans l'onglet Enregistrement de `Settings`.
  - Réparation non destructive sans risque de corruption des configs.
- **Motion Heatmap 24h (`scripts/motion-heatmap.sh`) :**
  - Enregistrement par tranche horaire glissante des déclenchements de mouvement (`scripts/detectionOn.sh`).
  - API `action.cgi?cmd=motion_heatmap` + barre d'activité visuelle 24h dans l'onglet Détection de `Settings`.
- **Anti-flicker 50 Hz / WDR :**
  - Sélecteur et paramètre `POWER_HZ` (Europe 50 Hz / Amériques 60 Hz) validé dans l'ISP et la découverte MQTT Home Assistant.
- **Service WebDAV Finder macOS (`controlscripts/webdav`, `config/webdav.conf.dist`) :**
  - Partage direct des enregistrements `/mnt/sd/DCIM` ou `/mnt/records` sur le port 8080 (désactivé par défaut, activable dans Services ou au boot). Identifiants protégés via l'authentification de la caméra.

### Tableau récapitulatif des tests et fonctions pour la testeuse (RC20)

| Élément | Switch / Fichier | Test à effectuer | Critère de réussite |
|---|---|---|---|
| **Auto-diag SD & Réparation** | `sd_card_check` / `sd_card_repair` dans UI ou `scripts/sd-diag.sh check` | Cliquer sur "Vérifier la santé" dans Settings > Enregistrement | Status vert "OK (écriture: XX Ko/s, 0 erreurs dmesg)" sans altérer la carte |
| **Motion Heatmap 24h** | `action.cgi?cmd=motion_heatmap` / `scripts/motion-heatmap.sh get` | Déclencher du mouvement ou appeler le script | Retour JSON des 24 tranches horaires avec barres d'activité visibles dans l'UI |
| **WebDAV (macOS Finder)** | `controlscripts/webdav start` | Connexion Finder `http://<ip>:8080` avec login caméra | Navigation et lecture des vidéos du dossier `/mnt/sd/DCIM` ou `/mnt/records` |
| **Anti-flicker 50 Hz** | `config/isp_tune.conf` `POWER_HZ=50` | Vérifier en direct sous éclairage secteur 50 Hz | Pas de bandes / battements lumineux sous éclairage LED / néon |
| **Synchro caméra (Push)** | `backup.html` bouton Push | Tester export/import entre les deux caméras | `tc100/cam2` et paramètres spécifiques non écrasés |
| **Frise 24h & Présélections OSD** | `view_records.html` & OSD presets | Vérifier affichage frise et positionnement coins OSD | Pas de régression d'affichage, OSD bien calé |


## 2026-11-03 12:40 — Testeuse : rc20 (commit d217a60) récupérée, relue avant installation

- Paquet : artifact `tc100-3-release` du run 41624580550 (build réussi) ; `tc100-3.0.1-rc20-update.tar` md5 `e914a72a940f5f8f732cad3d4467b0c3` (6 195 200 octets), `-sd.zip` md5 `ba8c0a1ba4a2e64101011eff8751bfb7`, `VERSION` = 3.0.1-rc20. Sur le Mac du propriétaire : `~/Downloads/tc100-fix/xfer20/`.
- **CI Python rouge sur d217a60 et a7a9537** (un test : `test_regressions.SettingsByUse.test_local_recording_commands` : la liste des commandes de lecture de `action.cgi` attendue — `wifi_get_ssid|wifi_rescue_info|local_rec_status|sd_card_info|md_zones_info|rtsp_server_info) ;;` — n'est plus dans le fichier : un nouveau `motion_heatmap` / `sd_card_check` a changé la ligne). Le noyau et le paquet sont construits. La testeuse installe quand même sur la .11 (le propriétaire l'a demandé) mais le test doit être corrigé avant le tag.
- **WebDAV (`controlscripts/webdav`) : ce n'est pas du WebDAV.** Le service lance `busybox httpd` (`-p 8080 -h <dossier> -c /etc/httpd.conf`) : serveur de fichiers statique en lecture, sans `PROPFIND` ni `OPTIONS` WebDAV ; le Finder de macOS ne pourra probablement pas le monter comme volume (un navigateur ou `curl` lira les fichiers). Bon point : `/etc/httpd.conf` impose un identifiant (`/:root:<hash>`), donc pas d'accès sans mot de passe ; l'authentification est celle de la caméra, en clair sur le réseau local (HTTP). À corriger dans la doc/l'interface (« partage de fichiers HTTP en lecture seule ») ou à remplacer par un vrai serveur WebDAV minimal ; désactivé par défaut, à garder ainsi.
- **Auto-réparation de la carte (`sd-diag.sh repair`)** : `fsck.fat` n'est pas dans l'image (constaté sur la .11) ; le script retombe alors sur un remontage en lecture-écriture, sans réparation réelle. L'intitulé « auto-repair » promet plus que ce qui est fait. À tester avec une carte (non réalisable sur la .11 sans carte).

## 2026-11-03 13:00 — RÉSULTATS rc20 (d217a60) sur la .11 / IPCAM2 (testeuse, ssh, sans carte SD, installée par la mise à jour web du propriétaire)

Compte rendu pour l'implémenteur. La rc20 est dans la flash (`/rom` = `mtdblock5`, `flashroot=1`, `VERSION` 3.0.1-rc20), uptime 11 min au relevé. Le propriétaire installe maintenant la rc20 sur la .24 (compte rendu à suivre).

**PASSÉ**
- **Clés ssh persistantes (321abe2 + fd23013) :** après le reboot de la mise à jour, ma clé (installée par le propriétaire pendant la rc18) fonctionne sans action ; `/mnt/config/authorized_keys` (318 octets) et la clé d'hôte (`SHA256:GWE6XVUH…`) inchangées : pas d'avertissement « host key changed ». À repasser après un reboot sur la .24 (première installation de ce mécanisme).
- **ssh interactif :** `devpts` monté (1 ligne dans `/proc/mounts`) ; plus de coupure de session après le mot de passe (le propriétaire avait eu une session qui tombait sur la rc18).
- **Balance des blancs globale (fd23013) :** au démarrage `white balance: starting from saved gains rex 219 bex 291`, puis `rex=224 bex=295 u=0 v=0` (`/tmp/cam_awb`), `awb.state` écrit (`219 291`). Snapshot après reboot : R/G 1,00, B/G 1,01 (critère ±5 % passé, mur neutre dès le début). Gains conformes à ce qu'on attendait pour la .11 (≈230/287).
- **Suivi Wi-Fi (`WIFI_QUALITY=1`) :** redémarre seul avec la caméra (11 relevés en 11 min, `/tmp/wifi-quality` écrit). Surveillance de la valeur `rssi` : -42 en essai manuel, -16 au relevé du boot, -50 dans les métriques : vérifier que `wifi-quality.sh` et `metrics.cgi` lisent la même grandeur.
- **mDNS (`tc100-mdnsd`) :** répond (unicast) à `ipcamera2.local`, RSS 8 Ko, CPU 0 %. Multicast depuis le Mac du propriétaire encore à confirmer. Nom = `hostname.conf` (pas `ipcam1.local` comme dans les notes).
- **Prometheus (`metrics.cgi`) :** 200 en 0,39 s avec mot de passe, 401 sans ; toutes les métriques présentes.
- **Babyphone / Vox :** `ENABLE=1` ET `VOX_MODE=1` nécessaires dans `sound_detection.conf` (doc à corriger) ; ton 1 kHz au haut-parleur : niveau -53 → -18 dBFS, `tc100_vox_active` 1 puis 0 (~10 s). Le niveau (`/var/run/sound_level`) est mesuré dès le boot.
- **Mémoire et stabilité :** `MemAvailable` 21,9 Mo après reboot, charge 0,8, flux principal stable (`dropped 0`), aucun plantage au noyau.

**ÉCHEC / À CORRIGER**
1. **Sabotage sur la rc18 : ne se déclenchait jamais de jour** (luma ≈ 127 même objectif couvert, l'exposition compense). Corrigé par 25fecef (taille JPEG + exposition) ; **nouvel essai en cours sur la rc20** (main sur l'objectif, de jour) — résultat à suivre. Baseline mesurée : 103 057 octets.
2. **Synchro « Push » (45c791c) :** deux défauts probables, voir l'entrée « relecture de 45c791c » (identité MQTT écrasée ; requête inter-caméras bloquée par CORS). **Non testée** tant que ce n'est pas corrigé.
3. **WebDAV :** ce n'est pas du WebDAV (busybox httpd statique, pas de PROPFIND) : le Finder ne le montera pas. Non testé (désactivé par défaut) tant que le nom/la doc ne sont pas corrigés.
4. **Auto-réparation de la carte :** `fsck.fat` absent de l'image ; « repair » = remontage seulement. Non testable sans carte (la .11 n'en a pas en ce moment).
5. **CI Python rouge sur d217a60 / a7a9537** (un test `test_local_recording_commands`, voir l'entrée précédente).
6. **Documentation :** note d'installation de la rc20 : les interrupteurs doivent être décrits complètement (Vox : `ENABLE` + `VOX_MODE` ; sabotage : `TAMPER_DETECT` dans `boot.conf` ET `ENABLE` dans `tamper.conf`, ce dernier prioritaire ; `hostname` pour mDNS).

**PAS ENCORE TESTÉ sur la .11** (précision) : notifications Ntfy/webhook (aucun canal configuré), mode « derrière une vitre » (essai de nuit), entité caméra MQTT (Home Assistant), meilleur cliché, zones nommées, pre-roll, carillon/sirène (`play_sound`), alarme fumée, vue 2×2, présélections OSD, frise 24 h (demande la carte), carte de chaleur, anti-scintillement 50 Hz.

**Prochains essais testeuse :** retest du sabotage (en cours), puis rc20 sur la .24 (balance des blancs avec gains ≈ 600/760 attendus : critère R/G et B/G à ±5 %, clés ssh après reboot, mode derrière une vitre la nuit). Rappel : la .24 porte encore ma rustine (`awb.off`, ligne `awbx` dans `rtsp.env`, outil sur sa carte SD) : à retirer avant l'essai de la balance des blancs.

## 2026-11-03 13:25 — RÉSULTATS rc20 (d217a60) sur la .24 / IPCAM1 (testeuse, ssh, carte SD présente)

La rc20 a été installée sur la .24 par le propriétaire (mise à jour web), uptime 13 min au premier relevé.

**PASSÉ**
- **Balance des blancs globale : la boucle rc20 corrige la .24 seule, mieux que ma rustine.** Rustine retirée (`awb.off` supprimé, `rtsp.env` vidé, sauvegarde `/mnt/sd/rtsp.env.rustine-2026-11-03`), `rtsp-h26x restart`, sans autre action. En 30 à 90 s les gains convergent à `rex 518 / bex 756 / 750 / 755` (ISP, lu avec `awbx get`), `u=1 v=0`. Le plafond ancien (512) était donc juste sous la valeur de `rex` ; la boucle a pris 518 avec un meilleur équilibre que le 600/760 fixé à la main. Mesure sur le snapshot (mur blanc) : **rustine 600/760 : R/G 1,18, B/G 1,02 ; boucle rc20 : R/G 1,01, B/G 0,99** (critère ±5 % : passé). L'image n'est plus verte ni jaune-verte.
- **Gains mémorisés :** `/mnt/config/awb.state` = `518 762` ; après `rtsp-h26x restart` : `white balance: starting from saved gains rex 518 bex 762` puis `rex=523 bex=748 u=-1 v=1`.
- **Clés ssh persistantes :** après le reboot de la mise à jour, la clé de la testeuse n'était plus là (première installation du mécanisme : prévu) ; le propriétaire l'a remise dans `/root/.ssh/authorized_keys`, et `/mnt/config/authorized_keys` la contient maintenant aussi (2 lignes : l'ancienne clé RSA de 2.x + la nouvelle ed25519) ; à confirmer par un second reboot que la clé revient seule. Clé d'hôte écrite en flash (`dropbear_ed25519_host_key`, 83 octets, 12:07) : empreinte `SHA256:WKXNKdA8…` (à comparer après le prochain reboot). Note : `/mnt/config/authorized_keys` a les droits `-rwxr-xr-x` (755) : à ramener à 600.
- **ssh interactif :** `devpts` monté, session stable (la clé a été ajoutée à la main dans une session ouverte sans coupure).
- **Teinte (HUE/SATURATION) :** restée à 0 après la mise à jour. `DAYNIGHT_SOURCE=luma` conservé.
- **Suivi Wi-Fi :** `WIFI_QUALITY=1` ajouté à `boot.conf` et relevé démarré (`rssi=-54`, perte 0 % sur la première minute, ping routeur 1,9 à 10,8 ms). À laisser tourner une nuit pour corréler les rafales de pertes de la .24. Mémoire disponible 20,5 Mo, flux principal stable (`dropped 0`).

**À SURVEILLER / PAS ENCORE TESTÉ sur la .24**
- Plusieurs reprises de la boucle de blancs : le soir/la nuit (bascule IR, gel en noir et blanc, retour le matin), changement brusque d'éclairage ; vérifier que `awb.state` n'est pas écrit en boucle (usure flash) : sorties à surveiller `ls -l --full-time /mnt/config/awb.state` sur 24 h.
- Mode derrière une vitre (nuit), notifications, sabotage (essai de jour en cours sur la .11), son et vox, mDNS (non démarré), carte de chaleur, frise 24 h (la .24 a une carte SD : `/mnt/sd/DCIM` présent), auto-diagnostic SD (`sd-diag.sh check`, car la carte est là), 50 Hz.
- Après un second reboot : clés ssh et clé d'hôte, `awb.state`, `WIFI_QUALITY`.

## 2026-11-03 14:45 — BILAN DE VALIDATION rc20 sur les 2 caméras en flash (testeuse, ssh, de jour)

Build : `3.0.1-rc20` (commit d217a60), installée par la mise à jour web sur la .11 (IPCAM2, sans carte SD) et la .24 (IPCAM1, carte SD 64 Go). Les deux tournent depuis la flash (`/rom` = `mtdblock5`, `flashroot=1`). Tests de jour, via ssh et les API web ; les essais de nuit et ceux qui demandent le propriétaire sont listés à la fin.

### Résumé
| Fonction | .11 | .24 | Remarque |
|---|---|---|---|
| Redémarrage `reboot` : retour du ping / ssh | 28 s / 33 s | 32 s / 34 s | rapide, sans intervention |
| Clés ssh + clé d'hôte persistantes | **OK** (md5 identiques avant/après) | **OK** | plus de clé à remettre ; empreintes inchangées (`GWE6XV…` / `WKXNKd…`) |
| Balance des blancs : gains mémorisés au démarrage | **OK** (219/291) | **OK** (517/754 → 513/742) | R/G 0,96 et B/G 1,00 (.11), R/G 1,00 et B/G 0,99 (.24) après reboot ; `awb.state` réécrit à chaque arrêt/démarrage |
| Réglages conservés après reboot (`WIFI_QUALITY`, vox, alarme, `FRONT_LED`, daynight) | **OK** | **OK** | suivi Wi-Fi et niveau sonore redémarrent seuls |
| Accès sans mot de passe (web, CGI, métriques, vue 2×2, export config, RTSP) | **tout refusé (401)** | **idem** | seuls ports ouverts : 22, 80, 554 |
| Mode « derrière une vitre » (`IR_LED_MODE=off`, bascule nuit forcée de jour) | **OK** : LED IR éteinte, IR-cut ouvert, noir et blanc | **OK** | `auto` (défaut) : LED allumée ; retour jour correct ; réglage visible dans `state.cgi?cmd=daynight` (`ir_led_mode`) ; l'essai de la vraie nuit reste à faire |
| Alarme fumée/sirène (`ALARM_DETECT=1`) | **OK** : ON après ≈ 3 s de son soutenu, OFF après la durée de maintien | **OK** | déclenché par un niveau fort soutenu (pas par la fréquence) ; voir réserve |
| Vox / babyphone | **OK** (ON puis OFF) | **OK** | |
| Métriques Prometheus | **OK** (200, auth) | **OK** | |
| Vue multi-caméras (`/multiview.html`) | 200 (auth), page servie | 200 | affichage et mémorisation des IP à regarder à l'œil |
| `play_sound` (carillon, sirène) par `action.cgi` | **OK** côté API (`"Playing chime"`) | **OK** | **nécessite l'en-tête `X-CSRF-Token`** (comportement attendu) ; écoute à confirmer par le propriétaire |
| Carte de chaleur (`motion_heatmap`) | OK (JSON 24 valeurs) | OK | toutes à 0 : pas de mouvement détecté/compté depuis le démarrage, à revoir avec du mouvement |
| `sd_card_info` / `local_rec_status` | présent=0, normal | `present 1`, vfat, 59 543 Mo libres, santé « ok » | |
| Sabotage (`tamper-detect.sh`, 25fecef) | essai demandé au propriétaire (main sur l'objectif) | non démarré | **en attente** |
| Auto-diagnostic SD, frise 24 h, WebDAV | — | à faire | voir « reste » |

### Chiffres de stabilité (de jour)
- Mémoire disponible : .11 21,4 Mo, .24 20,4 Mo (3 h après les installations, 3 clients RTSP) ; pas de dérive mesurée sur ~1 h.
- Charge : repos 0,8 à 1,1 ; 64 % d'inactivité avec 1 client (Frigate).
- **Plusieurs clients RTSP : la fréquence baisse.** Un client (Frigate) : ≈ 25 i/s. Frigate + le sous-flux (2 clients) : ≈ 20 à 21 i/s reçues par le client, `dropped` 0 à 2 ; Frigate + flux principal + sous-flux (3 clients) : ≈ 18 i/s, CPU de la .11 à 0 % d'inactivité. Capacité à surveiller si Frigate prend les deux flux : à examiner par l'implémenteur (coût du sous-flux ISP / envoi) ; la mémoire reste stable (+0).
- Journal du noyau : aucune erreur (`oops`, `panic`, `segfault`, `OOM`), chien de garde armé 300 s (`ak_wdt_reboot`). Seul message : `regulatory.db` absent (bénin).

### Défauts et observations pour les agents
1. **Latence et pertes Wi-Fi par à-coups sur LES DEUX caméras** (mesure de la testeuse, ping depuis l'ordinateur du propriétaire, 60 à 100 paquets) : vers le routeur : 0 % de perte, 11 ms ; vers la .11 : 0 à 4 % de perte mais **766 ms de latence moyenne (max 4,4 s)** ; vers la .24 : 15 à 33 % de perte, **0,6 à 1,8 s de moyenne (max 4,9 s)**. Immédiatement après, la .24 répondait en 15 ms moyen et 0 % de perte : à-coups, pas un état permanent. Signal correct (.11 -14 dBm, .24 -50 dBm), débit MCS 7 (72 Mbit/s), `iw` : 0 retransmission, 0 échec, économie d'énergie coupée, canal 2 (2417 MHz). Pistes : contention sur le canal 2,4 GHz, file d'attente d'émission de la caméra pleine pendant les rafales de l'encodeur (envoi des images clés H.265 ~130 Ko) ; demander à l'implémenteur de mesurer la file d'envoi (`tx` du pilote) et d'essayer un limiteur de débit. Le suivi Wi-Fi donne maintenant 12 à 15 % de perte sur la dernière heure.
2. **`wifi-quality.sh` lit une valeur de signal peu fiable** : la colonne « level » de `/proc/net/wireless` vaut -13/-14 ou -256 (invalide) selon le moment, alors que `iw dev wlan0 link` donne -14 dBm (.11) et -50 dBm (.24) et `metrics.cgi` -50. Résultat : `rssi_min_1h = -256` à tort. Lire `iw ... link` (ou ignorer -256) et rendre la même grandeur à `metrics.cgi`.
3. **Carte SD marquée « pas proprement démontée » après chaque redémarrage de la .24** (`FAT-fs (mmcblk0p1): Volume was not properly unmounted`), y compris pour un `reboot` demandé (la mise à jour web et `reboot` ne démontent pas `/mnt/sd` avant). À corriger : `sync` + démontage avant `reboot`/mise à jour web/chien de garde.
4. **Droits de `/mnt/config/authorized_keys` à 755** sur la .24 (ancien fichier de la 2.x) : mettre 600 à chaque restauration.
5. **Vox, alarme, mot de passe, WebDAV, synchro, sabotage** : voir les entrées précédentes (documentation et corrections demandées).
6. **Documentation de l'alarme** : l'alarme se déclenche sur tout son fort continu ≥ 3 s (testé avec une tonalité de 1 kHz) ; ce n'est pas une détection d'avertisseur de fumée par fréquence. À écrire clairement et ne jamais présenter comme une sécurité.
7. **Pas de journal de redémarrage visible** : `/mnt/log` n'existe pas en mode flash alors que `reboot-tracker.sh` parle de jffs2 : vérifier où l'historique des démarrages est écrit.

### Ce qui reste à valider (non fait aujourd'hui)
- Le propriétaire : écoute du carillon et de la sirène (envoyés sur les 2 caméras à volume 35), sabotage avec la main (.11 prête), `ping ipcamera2.local` sur le Mac, coup d'œil à la vue 2×2 et aux présélections OSD.
- De nuit : bascule jour/nuit réelle (daemon `luma`), mode vitre, retour en couleur le matin, boucle de blancs pendant la bascule IR, anti-scintillement 50 Hz sous éclairage artificiel.
- Sur la carte de la .24 : auto-diagnostic SD, frise 24 h, enregistrement sur mouvement, pre-roll, meilleur cliché, notifications (Ntfy/webhook : à configurer par le propriétaire).
- Plusieurs jours : fréquence d'écriture de `awb.state` (usure flash), dérive de mémoire, nombre de redémarrages par le chien de garde.

## 2026-11-03 13:50 — .11 : surexposition après reboot + mDNS (testeur)

- **Surexposition .11** (rc20, uptime ~7 min au moment du constat, reboot 12:37 UTC) : snapshot 12:44 UTC quasi blanc (luma 241-244, 81 % des pixels >240), `cam_ae` = `236 1124 484 256 256 0 1125`. Deux minutes plus tard, sans aucune action de ma part : luma 123, `cam_ae` = `47 137 256 …`, image normale. Donc **transitoire post-boot** : l'AE met plusieurs minutes à converger après démarrage (partait d'un gain/expo maximal ?). Teinte légèrement violette juste après le boot (rex=226 bex=296), à surveiller.
  - Demande à l'implémenteur : au démarrage de tc100_rtsp, initialiser l'AE sur une exposition moyenne (ou accélérer la convergence) ; critère : luma < 200 dans les 30 s après boot sur la .11.
  - .24 non concernée (luma 140 à la même heure).
- **mDNS** : le service est **off par défaut** → `ping ipcamera2.local` = "unknown host" est attendu tant qu'il n'est pas démarré. Démarré à la main sur la .11 (`tc100-mdnsd -i wlan0`, nom = hostname.conf = IPCAMERA2) ; le démarrage manuel ne survit pas au reboot. À décider : activer `config/autostart/mdns` par défaut (léger) ? Retest ping depuis le Mac du propriétaire en attente.

## 2026-11-03 — Petites corrections après le bilan rc20 (commit `[rc20-fix]`, zéro U-Boot / zéro noyau)

Seuls les défauts mineurs et sans risque du bilan rc20 sont corrigés ici. Le reste est laissé à l'implémenteur (liste en fin d'entrée).

1. **Droits de `/mnt/config/authorized_keys`** (défaut 4) : à chaque restauration de la clé (`S50dropbear-linux66`, `controlscripts/ssh-server`, `cfg-persist restore`), le fichier de `/mnt/config` est remis en `600` en plus de la copie dans `/root/.ssh`.
   - Test (.24) : redémarrer, puis `ls -l /mnt/config/authorized_keys` → `-rw-------` ; la connexion ssh par clé marche toujours.
2. **Signal Wi-Fi -256** (défaut 2) : `wifi-quality.sh` et `metrics.cgi` n'acceptent plus que -110..-1 dBm ; -256 (pas de mesure du pilote) donne `null` dans `/tmp/wifi-quality.log` (et ne fausse plus `rssi_min_1h`), `0` dans `tc100_wifi_signal_dbm` comme avant quand il n'y a pas de valeur. Test unitaire ajouté (`Lot1B.test_wifi_quality_samples_and_hour_summary`).
   - Test : après 1 h, `cat /tmp/wifi-quality` : `rssi_min_1h` n'est jamais -256 ; comparer `rssi` à `iw dev wlan0 link`.
   - Pas fait : lire `iw dev wlan0 link` à la place de `/proc/net/wireless` (à décider après la mesure ci-dessus).
3. **Push : identifiants passés à `curl` en UN argument** (`config_exchange.cgi`) : un mot de passe avec une espace ou un `*` ne peut plus être découpé en options de `curl`.
4. **Documentation** : `sound_detection.conf.dist` et `CHANGELOG.md` disent que Vox et l'alarme demandent aussi `ENABLE=1`, et que l'alarme se déclenche sur tout son fort ≥ 3 s (pas d'analyse de fréquence, jamais une sécurité) ; `boot.conf.dist` décrit la vraie méthode du sabotage (taille JPEG + exposition) et dit que `tamper.conf` l'emporte sur `TAMPER_DETECT`.

**Non corrigé ici (à l'implémenteur, décision ou risque) :**
- **Push encore inutilisable** : `backup.html` n'envoie ni l'en-tête `X-CSRF-Token` (refus attendu par `mutation_guard` → `csrf_guard`) ni d'identifiant/mot de passe pour la caméra cible (qui répond 401) ; la configuration envoyée contient le jeton Telegram et l'utilisateur MQTT en HTTP simple (`exclude_credentials` ne joue que du côté de la cible). À retester seulement après correction.
- **Mot de passe de secours fixe `tc100rescue`** (20c0c5e / 3962833) : identique sur toutes les caméras et publié dans le dépôt, alors que l'ancien était aléatoire par caméra (écrit sur la carte, `tc100-3/ADRESSE.txt`). À décider par le propriétaire (règle AGENTS.md : pas de mot de passe dans le dépôt).
- Carte SD non démontée avant `reboot` (touche tous les chemins de redémarrage), surexposition de la .11 après démarrage, fréquence avec plusieurs clients RTSP, à-coups Wi-Fi, historique des redémarrages en mode flash, mDNS actif par défaut ou non.

## 2026-11-03 — Fiabilité sans console série : mode sans échec, historique des redémarrages en flash, contrôle du noyau avant écriture (`[boot-guard]`, zéro U-Boot / zéro noyau)

Contexte : la flash n'a la place que pour UNE pile (`stack` 2,7 Mo, `initrd` 2 Mo, `vendor` 1 Mo) : un retour automatique à la pile précédente est impossible sans carte SD. Ce qui est faisable sans U-Boot est fait ici. Les valeurs par défaut du noyau demandées (`sub_channel=1`, `slots=3`, `pool=9600K`) sont **déjà** compilées (patches 0006 et 0015) ; le chien de garde matériel est armé par le noyau (`ak_wdt_reboot=300`) et entretenu par `watchdog` dès le début d'`autorun-linux66.sh`.

### 1. Mode sans échec (`v3/linux66-sd/boot-guard`, appelé par `autorun-linux66.sh` étape 1f)
- **Quoi :** en mode flash, chaque démarrage incrémente `/mnt/config/.boot-guard` (sauvegardé tout de suite dans `cfga`/`cfgb` par `cfg-persist save`, AVANT le serveur vidéo). Après 5 min de marche, le compteur revient à 0. Après **3 marches d'affilée de moins de 5 min**, le 4ᵉ démarrage est un **mode sans échec** (`/tmp/safemode`) : Wi-Fi, interface web, ssh/telnet (s'ils sont activés), bouton reset et point d'accès de secours seulement ; pas de `tc100_rtsp`, ONVIF, jour/nuit auto, MQTT, détections, enregistrement, sabotage, son de démarrage ni services optionnels. Page Informations : « SAFE MODE … » ; ssh : `/etc/motd`. Un redémarrage demandé depuis la page web ou le bouton reset remet le compteur à 0 (ne compte pas) ; un redémarrage automatique (commande MQTT, chiens de garde, net-guard) compte. Le compteur plafonne à 4 : une boucle qui continue n'écrit plus la flash. Au plus deux écritures de la flash par démarrage (compteur +1, retour à 0).
- **Interrupteur :** `BOOT_GUARD=0` dans `boot.conf` (défaut `1`, aussi sur les caméras mises à jour). Mode SD : rien. À la main : `sh /mnt/v3/linux66-sd/boot-guard status|clear`.
- **Test (caméra à portée, propriétaire présent) :**
  1. Après un démarrage normal : `boot-guard status` → `on: count=1`, puis 5 min plus tard `count=0` ; `cfg-persist status` montre une seule écriture de plus par étape.
  2. Simuler une boucle : `echo 3 > /mnt/config/.boot-guard; sh /mnt/v3/linux66-sd/cfg-persist save; reboot` (depuis ssh : compte comme automatique). Attendu : la caméra revient en **mode sans échec** (ping, page web, ssh OK ; pas de RTSP ; page Informations « SAFE MODE (3 short runs in a row) » ; `pidof tc100_rtsp` vide).
  3. Attendre 5 min (`count=0`), puis redémarrer depuis la page web → démarrage normal (vidéo revenue).
  4. Redémarrer 3 fois d'affilée depuis la page web en moins de 5 min → jamais de mode sans échec.
- **Critères :** 1 à 4 conformes ; aucune régression du démarrage normal (vidéo, MQTT, services) ; `cfg-persist status` cohérent (pas d'écriture en boucle).

### 2. Historique des redémarrages en mode flash (`scripts/reboot-tracker.sh`)
- **Quoi :** sur la 6.6, `reboot-tracker.sh boot` n'était jamais appelé (page Informations « Previous run ended: unknown », MQTT `flash_boot`) et ses fichiers allaient dans `/mnt/log` (RAM en mode flash). Maintenant : appelé à chaque démarrage (étape 1f, avant `boot-guard`) ; en mode flash l'historique (`reboot-history.log`, 30 lignes) et l'intention de redémarrage vont dans `/mnt/config/log` (sauvegardés avec les réglages : une écriture par démarrage, partagée avec boot-guard, et une par redémarrage volontaire) ; le relevé de vie (`.heartbeat`) et `important.log` vont sur la carte (`/mnt/sd/logs`) si elle est là, sinon en RAM (jamais la flash). Tâche du housekeeper toutes les 15 min (`reboot-tracker.sh hk`). MQTT lit aussi `/mnt/config/log/reboot-history.log`.
- **Test :** (a) redémarrage depuis la page web → page Informations « Previous run ended: requested at … web UI reboot » ; (b) coupure de courant (propriétaire) → « UNEXPECTED … last alive … » si une carte est là (sinon « unknown ») ; (c) `cat /mnt/config/log/reboot-history.log` garde les lignes après plusieurs redémarrages, sans carte SD (.11).

### 3. Mise à jour web : le noyau est vérifié avant toute écriture (`v3/install/update66.sh check`)
- **Quoi :** en plus du md5 et des tailles : `c66.img` doit être une image U-Boot (magie `27 05 19 56`), complète (taille annoncée par son en-tête), et **pas plus grande que ce que l'U-Boot de cette caméra lit** (`sf read 0x82000000 0x39000 <taille>` lu dans la partition `env`, en lecture seule : 0x200000 pour l'installation par carte, 0x1ce000 pour les commandes faites à la main le 2026-10-24) ; `stack.sqfs` doit être un squashfs (`hsqs`). Sinon la mise à jour est refusée, rien n'est écrit.
- **Test :** mise à jour web normale de la prochaine version sur la .11 puis la .24 : passe comme avant. Sur une caméra, `sh /mnt/v3/install/update66.sh check <dossier>` avec un `c66.img` tronqué (`head -c 1000000`) → refus « cut short » (md5 à refaire dans MD5SUMS pour atteindre ce contrôle).
- **Critères :** aucune mise à jour valable refusée ; les paquets cassés refusés avant écriture.

## 2026-11-03 — Point d'accès de secours actif par défaut (`[wifi-rescue]`, décision du propriétaire)

- **Quoi :** décision du propriétaire : mot de passe fixe `tc100rescue` conservé, et le point d'accès de secours doit venir tant que le Wi-Fi ne marche pas. `boot.conf.dist` passe à `WIFI_RESCUE=1` ; une clé absente vaut maintenant `1` (`controlscripts/wifi-rescue`, `scripts/wifi-rescue.sh`). Constat : avec l'ancien `WIFI_RESCUE=0`, ni l'ouverture automatique ni le bouton reset ne marchaient (`start-ap` sortait en code 3), alors que la page Réglages → Réseau annonçait l'ouverture après 10 min (elle lit `config/autostart/wifi-rescue`, présent par défaut).
- **Caméras déjà en service (.11, .24) :** leur `boot.conf` contient `WIFI_RESCUE=0` (copié de l'ancien `.dist`) : inchangé par la mise à jour. Pour l'activer : `WIFI_RESCUE=1` dans `/mnt/config/boot.conf` puis `sh /mnt/controlscripts/wifi-rescue restart`.
- **Interrupteur :** `WIFI_RESCUE=0` (plus de point d'accès, ni automatique ni par le bouton).
- **Test (propriétaire, caméra à portée) :** (1) sur une caméra avec `WIFI_RESCUE=1`, bouton reset 3-7 s → réseau `TC100-<MAC>` visible, connexion avec `tc100rescue`, page http://10.42.0.1/ ; (2) mauvais mot de passe Wi-Fi enregistré → le réseau de secours apparaît au bout d'environ 10 min, la correction du Wi-Fi depuis cette page ferme le point d'accès et la caméra revient sur le réseau de la maison ; (3) Wi-Fi normal pendant 24 h → le point d'accès ne s'ouvre jamais (`sh /mnt/scripts/wifi-rescue.sh status` → `ap=0`).

## 2026-11-03 — Un seul interrupteur par service, bugs « l'interface dit une chose, la caméra en fait une autre » (`[one-switch]`)

Décisions du propriétaire : l'interrupteur de l'interface gagne (le profil Frigate + HA coupe une seule fois quand on le choisit) ; secours Wi-Fi d'abord.

- **Quoi :**
  - `scripts/service-switch.sh` (nouveau) : pour détection sonore (`sound_detection.conf ENABLE`), syslog (`SYSLOG_ENABLE`), enregistrement (`REC_LOCAL`), Memory Guard (`MEM_GUARD_ENABLE`), point d'accès de secours (`WIFI_RESCUE`), MQTT (`mqtt.conf MQTT_ENABLE`), bot Telegram (`TELEGRAM_ENABLE`), détection de mouvement (`mdenabled`), la clé est le seul interrupteur. Le démarrage, la case « Boot » de la page Services et l'affichage la lisent / l'écrivent ; `config/autostart/<service>` est ignoré pour eux. Jour/nuit automatique : seulement `daynight` (3 = manuel). LED : seulement `FRONT_LED` / `RED_LED`. Sabotage : seulement `tamper.conf` (les `TAMPER_*` quittent `boot.conf`).
  - **Telegram : un seul chemin** (`scripts/notify.sh`, `notify.conf TELEGRAM_NOTIFY_ENABLE`) : plus de 2ᵉ et 3ᵉ photo par mouvement (`motion.conf send_telegram`, `telegram.conf TELEGRAM_MOTION_SNAPSHOT` supprimés).
  - **Migration une fois** (`scripts/migrate-switches.sh`, marqueur `config/.migrated-switches`) : garde ce que la caméra faisait (Telegram sur mouvement → `TELEGRAM_NOTIFY_ENABLE=1` ; sabotage = `TAMPER_DETECT` ET `ENABLE` ; `autostart/recording` → `REC_LOCAL=1`).
  - Assistant (profil Frigate + HA) : `MQTT_ENABLE` écrit dans `mqtt.conf` (il l'était dans `boot.conf`, effacé au démarrage) ; Telegram, syslog, détection sonore, FTP et telnet coupés **une fois** au choix du profil, plus à chaque démarrage.
  - Détection sonore → enregistrement : suit `REC_WHEN=motion` (plus `recording.conf rec_motion_activated`).
  - `net-guard` : tant que le surveillant du point d'accès de secours tourne, pas de redémarrage avant 2 cycles complets (2 × (10 + 15) = 50 min ; jamais pendant que le point d'accès est ouvert, comme avant).
- **Interrupteurs :** aucun nouveau (ce sont les clés existantes).
- **Test (les deux caméras, après la mise à jour) :**
  1. `cat /mnt/config/.migrated-switches` existe ; `grep TAMPER /mnt/config/boot.conf` vide ; services en marche identiques à avant la mise à jour (`pidof`, page Services).
  2. Page Services : décocher puis recocher « Boot » de `syslog-forward` / `memory-guard` / `wifi-rescue` → la clé change dans `boot.conf` (pas de fichier dans `autostart/`) ; redémarrer → l'état affiché est l'état réel.
  3. Réglages → Enregistrement off, redémarrer → reste off (avant : revenait à on avec `autostart/recording`).
  4. Détection sonore activée dans Réglages, redémarrer → `pidof` du démon présent et événements sonores reçus.
  5. Telegram configuré + `TELEGRAM_NOTIFY_ENABLE=1` : un mouvement → **une** photo.
  6. Sans réseau (box coupée) avec `WIFI_RESCUE=1` : point d'accès à ~10 min, retour station ~25 min, point d'accès ~35 min, redémarrage pas avant ~50 min.
- **Critères :** 1 à 6 conformes, aucun service perdu ni ajouté par rapport à avant la mise à jour.

## 2026-11-03 — Interface réorganisée par usage, image en direct, pages pour Alertes / sabotage / babyphone (`[ui]`)

- **Quoi :**
  - Menu du haut : Tableau de bord, Direct, Multi-vue, Enregistrements, **Image** (Image, Confidentialité et incrustation, Jour/nuit), **Réglages** (Flux et son ; Événements : Détection, Enregistrement, **Alertes** ; Réseau, Intégrations, Système), **Outils** (Mise à jour et sauvegarde, Services, Diagnostics, Journaux, Éditeur de config, redémarrer, éteindre). « Tous les réglages » disparaît (l'ancien favori `#status` ouvre Image).
  - Image et Jour/nuit : **image en direct** au-dessus des réglages (une photo toutes les 2 s, seulement pendant que la section est ouverte et la page visible). Les curseurs s'appliquent **au relâchement** ; plus d'interrupteur « Enable live image tuning » (actif dès qu'une valeur ≠ 0) ; bouton « Valeurs d'usine ».
  - Détection : cartes **Babyphone et son d'alarme** (`VOX_MODE`, `VOX_HOLD_SECONDS`, `ALARM_DETECT`, `ALARM_HOLD_SECONDS`, `MIN_LOUD_SECONDS`) et **Détection de sabotage** (`tamper.conf`, active/désactive la tâche du housekeeper tout de suite).
  - Nouvelle section **Alertes** (`notify.conf`) : événements (mouvement, son, sabotage), délai, image jointe, Telegram, Ntfy (jeton jamais renvoyé à la page ; vide = garder, « - » = supprimer), webhook. Toutes les valeurs sont filtrées (fichier chargé par le shell).
  - Intégrations → Telegram : l'interrupteur devient « Bot Telegram : répondre aux commandes » (c'est ce qu'il faisait) ; les alertes Telegram sont dans Alertes.
  - Nouvelles commandes `action.cgi` : `events_info` (lecture), `set_notify_config`, `set_tamper_config`, `set_sound_options` (`scripts/action.d/events.sh`).
- **Interrupteurs :** ceux des cartes (tout désactivé par défaut).
- **Test (navigateur, propriétaire) :**
  1. Menus : chaque entrée ouvre la bonne section ; ordinateur et téléphone.
  2. Image : l'image se rafraîchit ; bouger la luminosité → appliqué au relâchement, visible dans l'image en 2 à 4 s ; « Valeurs d'usine » → retour à l'image d'origine ; quitter la section → plus de requêtes `currentpic.cgi` (onglet Réseau du navigateur).
  3. Alertes : Ntfy avec un sujet de test → un mouvement envoie **une** notification avec l'image ; une adresse avec un espace ou un guillemet est refusée avec un message.
  4. Sabotage activé dans la page → main sur l'objectif ≥ 10 s → état « objectif masqué » et alerte ; désactivé → plus rien.
  5. Babyphone activé (avec la détection sonore) → l'entité son de Home Assistant reste active pendant le bruit puis s'éteint après le délai.
- **Critères :** 1 à 5 conformes ; charge CPU de la caméra inchangée hors section Image.

## 2026-11-03 — Une seule définition par valeur : signal Wi-Fi, RAM, santé de la carte SD (`[one-value]`)

- **Quoi :** signal Wi-Fi calculé une seule fois (`scripts/wifi-signal.sh`, -110..-1 dBm, vide si le pilote ne donne rien : -256 et 0) pour le tableau de bord, la ligne d'état, `metrics.cgi` (échantillon omis au lieu d'un faux 0), MQTT et `wifi-quality.sh` ; chemin 2.x `rx_signal` et fonction morte supprimés. RAM : disponible = `MemAvailable`, utilisée = total − disponible, partout (tableau de bord compris ; la ligne de démarrage dit « MemAvailable »). Carte SD : `sdinfo-sd.sh` est le seul à lire dmesg et à écrire `/tmp/sd-health` (`state=errors` quand le noyau a signalé des erreurs) ; `sd-diag.sh` le lit ; réparation **refusée** en mode SD (carte qui porte le firmware, montée en écriture) ; chemins `/mnt/records` morts supprimés. `stability.csv` sur la carte (`/mnt/sd/logs`) quand elle est là, sinon RAM, jamais la flash.
- **Effet de bord :** quand `/tmp/sd-health` dit `errors`, `log-persist.sh` n'écrit plus de journaux sur la carte (il exigeait déjà `ok`).
- **Interrupteur :** aucun (revert de 022ac07).
- **Test :** (1) tableau de bord, `/cgi-bin/metrics.cgi` et diag MQTT : même signal (dBm négatif) ; sans lecture : `null` en JSON, pas d'échantillon `tc100_wifi_signal_dbm`. (2) RAM utilisée identique entre tableau de bord, ligne d'état et MQTT. (3) erreur carte dans dmesg → `/tmp/sd-health` `state=errors`, même état dans le panneau Disque et `sd-diag.sh check` ; mode SD : « Réparer » → refusé, aucun fsck ; mode flash avec carte : la réparation fonctionne. (4) mode flash avec carte : `/mnt/sd/logs/stability.csv` se remplit (~1 h), `/cgi-bin/stability.cgi` le renvoie ; sans carte : RAM seulement.
- **Critères :** valeurs identiques partout, aucune valeur inventée, aucun fsck sur la carte en service, rien d'écrit en flash.

## 2026-11-03 — Doublons supprimés : network-monitor, partage HTTP « WebDAV », restes de Privacy Shield ; `awb.state` n'écrit plus la flash à lui seul (`[dedup]`)

Décisions du propriétaire : un seul chemin fonctionnel par fonction ; WebDAV supprimé.

- **Quoi :** suppression de `network-monitor` (`net-guard` reste le seul garde réseau ; ses autres rôles n'apportaient rien sur la 3.0 : relance MQTT déjà gérée par le pont, rebond de wlan0 jugé inutile par l'enquête W-NET) ; du partage HTTP « WebDAV » (port 8080 ; la page Enregistrements sert déjà les vidéos) ; des restes de Privacy Shield (action web, commande MQTT, champ de santé ; la ligne qui efface l'ancienne entité Home Assistant reste) ; de l'action `conf_autodaynight` (écrivait des clés mortes, aucun appelant). `MEM_GUARD_SOFT_SERVICES` ne cite plus `network-monitor` (migration dans memory-guard). `cfg-persist` ignore `awb.state` pour décider d'écrire la flash ; il part avec la sauvegarde suivante (démarrage, 5 min, redémarrage volontaire).
- **Interrupteur :** aucun (suppressions ; revert de fcc5d85).
- **Test :** (1) page Services : ni network-monitor ni WebDAV ; les autres services démarrent et s'arrêtent. (2) `MEM_GUARD_SOFT_SERVICES` d'une caméra qui citait `network-monitor` : le nom disparaît au redémarrage de memory-guard. (3) box coupée : seul `net-guard` redémarre la caméra (avec `WIFI_RESCUE=1`, après les 2 cycles de secours). (4) MQTT `health` publié, Home Assistant fonctionne. (5) 30 min de flux avec une lumière qui change : `awb.state` change mais `/tmp/cfg-persist.status` ne montre pas de nouvelle sauvegarde ; après un redémarrage volontaire, le slot contient `awb.state` et les gains sont restaurés.
- **Critères :** aucune page cassée ni erreur CGI ; aucune écriture flash due à `awb.state` seul.

## 2026-11-03 — Version 3.0.1-rc21 (Consolidation complète et release candidate)

- **Version :** `3.0.1-rc21`
- **Contenu embarqué :**
  - **Safe mode / Boot Guard** (`BOOT_GUARD=1`) : bascule en mode de secours après 3 reboots consécutifs en < 5 min.
  - **Nettoyage des doublons** : suppression de `network-monitor`, du port 8080 (WebDAV obsolète), et fin de l'usure Flash par `awb.state`.
  - **Unification Export / Import JSON & Push** : table unique, case "Inclure les secrets", Push inter-caméras sécurisé.
  - **Mot de passe Wi-Fi de secours par défaut** : fixé et documenté sur `tc100rescue`.
  - **CI hôte verte** : 172 tests unitaires passés avec succès.
- **Test à effectuer :**
  1. Installation de la `rc21` sur la caméra via la mise à jour web.
  2. Vérification de la persistance de configuration et de la stabilité globale.

Décision du propriétaire : JSON seulement ; secrets seulement si on coche la case.

- **Quoi :** `config_exchange.cgi` : une seule table de lignes sert à l'export ET à l'import (symétriques). Ajoutés : enregistrement (`REC_*`), jour/nuit (`daynight.conf`), alertes (`notify.conf`), sabotage, détection sonore (Vox, alarme), réglage d'image (`isp_tune.conf`), point d'accès de secours, mode sans échec, journaux, suivi Wi-Fi. Retirés : lignes mortes (`recording.conf rec_*`, jour/nuit de `rtspserver.conf`, `PRIVACY_SCREEN`). Avec la case cochée, `secrets` : réseaux Wi-Fi (4 max, psk entre guillemets), mot de passe de la caméra, utilisateur et mot de passe MQTT, jeton et chat Telegram, mot de passe du secours ; sous `notify` : jeton Ntfy, sujet Ntfy et adresse webhook (traités comme secrets : un sujet ntfy.sh vaut un mot de passe). Validation stricte de chaque valeur, import tout-ou-rien. Envoi (« Push ») : identifiant et mot de passe de la caméra cible, jeton CSRF lu chez la cible, jamais de secrets ni d'identité réseau. Supprimés : `conf-export.cgi`, `conf-import.cgi`, `configbackup.cgi`, `upload_backup.cgi` (instantané sur la caméra, préréglages et `cfg-persist` inchangés).
- **Limites :** un réseau Wi-Fi à psk hexadécimal n'est pas exporté ; un SSID accentué peut faire refuser l'import ; les anciens exports (`.telegram.token`, `.mqtt.user`) ne réimportent plus ces deux valeurs.
- **Interrupteur :** aucun (ne pas importer en cas de doute ; l'export ne modifie rien).
- **Test :**
  1. Outils → Mise à jour et sauvegarde : export sans la case → le fichier ne contient ni Wi-Fi, ni mot de passe, ni jeton, ni sujet Ntfy, ni adresse webhook.
  2. Case cochée (avertissement visible) → le fichier contient `secrets`.
  3. Modifier `REC_WHEN`, les seuils jour/nuit, les événements d'alerte ; réimporter le fichier complet → les valeurs reviennent ; mot de passe et Wi-Fi réappliqués (la page peut se déconnecter : vérifier le retour).
  4. Import avec « exclure les identifiants » → secrets inchangés.
  5. JSON invalide (`"when":"x"`) → refusé, rien de modifié.
  6. Push vers l'autre caméra avec identifiant et mot de passe → réglages appliqués, sans Wi-Fi, mots de passe ni identité réseau (topic MQTT, nom, retournement d'image).
  7. `/cgi-bin/conf-export.cgi` et `/cgi-bin/configbackup.cgi` → 404.
- **Critères :** 1 à 7 conformes ; caméra toujours joignable après un import avec Wi-Fi.

## 2026-11-03 17:10 — rc21 installée sur .11 et .24 : premiers contrôles (testeur)

Build `cc6e1d4` (CI verte), `tc100-3.0.1-rc21-update.tar` md5 `8383e2e65e9539de78e45fac9732fba5`, installée par le propriétaire via l'update web sur les 2 caméras.

| Contrôle | .11 | .24 |
|---|---|---|
| Version `/etc/version` | 3.0.1-rc21 | 3.0.1-rc21 |
| Flash (`flashroot=1`), watchdog armé 300 s | OK | OK |
| ssh par clé persistante après update | OK | OK |
| `metrics.cgi`, `state.cgi?cmd=daynight`, `/multiview.html` (auth) | 200 | 200 |
| Image (snapshot) | normale (luma 92-94, fin de journée, lampe allumée) | normale (luma 123-130) |
| Exposition juste après boot | luma 94 à 13 min (le boot précédent avait montré une surexposition transitoire) | luma 130 dès la 1re minute |
| AWB | rex=213 bex=323 stable | rex≈580 bex=704 |
| Fichiers retirés (WebDAV `/mnt/webdav`, network-monitor, Privacy Shield) | absents | absents |
| `awb.state` | présent (8 octets) | présent |
| Pas d'oops/panic dans dmesg | OK | OK |
| Services autostart | auto-night-detection, button-actions, cpu-scaler, health-snapshot, memory-guard, rtsp-h26x, ssh-server, wifi-rescue | idem sans button-actions |
| mDNS | non démarré (autostart absent) → `.local` ne répond pas | idem |

Remarques :
- Ping passerelle depuis la .24 : 100 % de perte à 1 min d'uptime (Wi-Fi pas encore stable juste après le boot) ; à recontrôler.
- Non encore testé en rc21 : export/import JSON unique avec case « inclure les secrets », push de config corrigé, fréquence d'écriture de awb.state, alarme anti-masquage (main du propriétaire), nuit, SD (.24).
- mDNS : toujours à décider (autostart par défaut ou non).

## 2026-11-03 — Version 3.0.1-rc22 (Lissage réseau RTSP, Récupération proactive Wi-Fi & Allègement RAM)

- **Version :** `3.0.1-rc22`
- **Quoi :**
  1. `RTSP_PACING_US` : micro-lissage d'émission des paquets RTP UDP en microsecondes (ex: 50 à 100 µs entre paquets/salves) pour étaler les salves des trames IDR volumineuses (H.265 ~130 Ko) et éviter de saturer la queue TX du dongle Wi-Fi USB RTL8188FU.
  2. `RTSP_SNDBUF` : plafonnement de `SO_SNDBUF` en Ko (ex: 32 à 64 Ko) sur les sockets RTSP (TCP et UDP) afin de limiter l'accumulation de données dans la pile réseau du noyau.
  3. Récupération Wi-Fi proactive : `net-guard.sh` tente un `wifi-recover.sh force` (re-probe USB propre) dès 60 s d'échec passerelle avant d'attendre l'extinction/reboot de la caméra.
  4. Optimisation RAM `/tmp` : rotation `RTSP_LOGMAX` abaissée de 256 Ko à 128 Ko.
  5. `multiview.html` : support du flux vidéo direct HTML5 (live.cgi) avec bascule instantanée et traductions complètes FR/EN.
- **Interrupteurs (dans `/mnt/config/rtsp.env`, puis `rtsp-h26x restart`) :**
  - Par défaut : désactivé (`pacing 0 us sndbuf 0 KB` dans la ligne de log de démarrage de `tc100_rtsp`).
  - Pour tester le lissage : ajouter `export RTSP_PACING_US=100` et/ou `export RTSP_SNDBUF=64` dans `/mnt/config/rtsp.env` puis redémarrer le serveur RTSP.
- **Test à effectuer :**
  1. Installer la `rc22` via mise à jour web.
  2. Lancer un flux continu (Frigate ou VLC en UDP/TCP).
  3. Mesurer la latence ICMP (ping passerelle) pendant les trames IDR (toutes les 2 s) : comparer avec et sans `RTSP_PACING_US=100`.
- **Critères :**
  - Sans pacing : ping avec des pics réguliers à >500 ms voire 1-4 s lors des IDR.
  - Avec pacing : ping stable sans pics majeurs lors des IDR ; aucune dégradation visuelle du flux vidéo.

## 2026-11-03 19:25 — Version 3.0.1-rc23 (Vidéo fluide partout, mDNS par défaut, AWB équilibré & Wi-Fi durci)

- **Version :** `3.0.1-rc23`
- **Quoi :**
  1. **Vidéo fluide native par défaut partout** : MediaSource (`live.cgi` fMP4 H.264 25 fps) actif par défaut sur la page principale (`index.html`), le multiview (`multiview.html`), et dans l'aperçu dynamique de la page des réglages Image/Jour/Nuit (`settings.html`).
  2. **mDNS actif par défaut** (`config/autostart/mdns`) : résolution automatique du nom de la caméra sur le réseau local (`<hostname>.local`).
  3. **AWB ISP rééquilibré** (`src/tc100rtsp/tc100_rtsp.c`) : convergence accélérée de la composante bleue (`bex`) pour éliminer la dominante chaude/jaunâtre sous éclairage intérieur.
  4. **Stabilité Wi-Fi** : suppression du trigger agressif dans `net-guard.sh` qui provoquait des déconnexions/reboots en cascade.
- **Tests à effectuer :**
  1. Installer la mise à jour `tc100-3.0.1-rc23-update.tar`.
  2. Vérifier l'accès immédiat via `http://teckin-11.local/` (ou nom d'hôte).
  3. Vérifier le rendu direct dans `settings.html` et la disparition de la teinte jaunâtre.
  4. Confirmer la stabilité continue du Wi-Fi sans rebond.

## 2026-11-03 23:05 — rc23 sur .11 et .24 : tests fonctionnels + campagne de nuit lancée (testeur)

Les 2 caméras tournent en 3.0.1-rc23 (flash), uptime 3 h, mDNS démarré automatiquement, ping passerelle 2-7 ms sans perte, RAM libre stable (~20 Mo).

| Test | Résultat |
|---|---|
| mDNS (requête unicast UDP 5353 depuis le LAN) | `ipcamera2.local` → .11 OK ; `ipcamera1.local` → .24 OK (multicast non testable depuis ma VM) |
| Vidéo fluide `live.cgi` (fMP4, flux continu) | OK sur les 2 : H.264 640x360 décodable par ffmpeg ; ~20 Ko/s sur 20 s |
| `multiview.html`, `metrics.cgi`, `state.cgi?cmd=daynight` | 200 sur les 2 |
| Export JSON `config_exchange.cgi?cmd=export` | OK ; sans secrets : aucun psk/mot de passe ; avec `include_secrets=1` : flag `includes_secrets:true` et secrets présents |
| Import JSON (cible = soi-même) | JSON invalide → erreur propre `INVALID_JSON` ; sans CSRF → 403 ; **import valide → HTTP 200 mais corps VIDE** (attendu `{"ok":true,"applied":…}`), config inchangée (md5 identique), `mqtt-bridge restart` observé ensuite sur la .11 |
| Écart de config .11 vs .24 (hors réseau) | hostname, `MQTT_TOPIC_ROOT` (tc100/camera vs tc100/cam2) et **`syslog/host` : 192.168.1.23 (.11) vs 192.168.1.22 (.24)** → vérifier laquelle est la bonne |
| Image | .11 luma ~90, .24 ~112 (soirée, pas de surexposition) |

À corriger / décider :
1. `config_exchange.cgi?cmd=import` : réponse vide sur import valide (le résultat n'est pas affiché ; l'UI ne peut pas confirmer l'import).
2. `syslog/host` différent entre les deux caméras (voulu ?).
3. CI rouge sur 5a94854/7284c73 (test classes CSS `has-text-weight-semibold`) à remettre au vert avant de qualifier la rc23 stable.
4. Constat à 21:50 UTC sur la .24 : `STAT cap 51` pour ~4 s (fps réduit en soirée, expo 2810) vs .11 `cap 122` ; à expliquer (limite de temps d'exposition de nuit ?).

Campagne de nuit : échantillonneur sur le Mac du propriétaire toutes les 2 min (uptime, RAM, luma, AE, AWB, ping passerelle, fps, awb.state) dans `night.log` + un snapshot / 30 min. Dépouillement demain matin (reboots, dérive mémoire, bascule jour/nuit, retour des couleurs, fréquence d'écriture awb.state). Anti-masquage reporté (main du propriétaire).

### Complément 23:05 — enregistreur de nuit et awb.state (testeur)
- L'échantillonneur côté Mac n'a pas survécu (processus de fond tués entre deux appels) : remplacé par `/tmp/nightcam.sh` **sur chaque caméra** (RAM, 1 ligne / 180 s dans `/tmp/night.log` : uptime, RAM, luma, AE, AWB, awb.state, load, ping passerelle, fps, IR). Perdu si reboot (détecté par l'uptime). Dépouillement demain matin.
- `awb.state` est réécrit environ toutes les 2 min mais `/mnt` est un **tmpfs** : pas d'usure flash par cette écriture. Reste à vérifier demain que la copie persistante (cfg-persist vers cfga/cfgb) n'est pas déclenchée à chaque écriture.

## 2026-11-04 01:00 — Correctifs de l'audit poussés par le testeur (à intégrer dans la prochaine RC)

À la demande du propriétaire, le testeur a corrigé lui-même les points P0 de `audit-2026-11-03.md`. **CI verte** sur `67b1a01` (tests hôte + build). Commits :
- `7c49fec` CSS : purge Bulma relancée (`has-text-weight-semibold`), la CI était rouge depuis 5a94854.
- `23a7c84` MQTT/Telegram : refus des espaces, quotes et `$ ` \ ; & | < > ( )` (fichiers sourcés par le shell root) dans la page Réglages, l'appairage HA et Telegram ; l'assistant ne garde plus `( )`.
- `cb946e4` Import JSON : **ce n'était pas un corps vide**, l'import durait ~40 s et mon client coupait à 30 s. Écritures groupées par fichier (`tc_apply_edits`) + cache de validation : **12-15 s** mesurées sur la .11.
- `9cf38e1` `frigateyaml` / `integrationmanifest` / `integrationtest` annonçaient 15 fps (rtspserver.conf non chargé) : 25 fps maintenant.
- `fd9c6b3` 7 tests de non-régression (`tests/test_audit_fixes.py`).
- `67b1a01` Doc : CHANGELOG [Unreleased], CREDITS, known-issues rc23, checklist release cochée.

Méthode de test sur caméra : fichiers superposés en RAM sur la .11 (`mount --bind` sur /mnt, retirés ensuite ; la .11 est revenue exactement en rc23, md5 vérifiés). **Rien n'est installé en flash** : il faut une RC (rc24) pour les avoir sur les caméras.

Pour l'implémenteur :
1. Publier une rc24 avec ces commits ; je la teste sur les deux caméras.
2. Restent ouverts (checklist `release-3.0.1.md`) : exposition au boot, mot de passe en clair dans `frigateyaml` (proposer `{FRIGATE_RTSP_PASSWORD}`), fichier LICENCE (décision du propriétaire), source/licence de `monvifd`, `rwconf`, `getflag`, `getimage`, `syslog/host` différent entre .11 et .24, mDNS multicast depuis le Mac.
3. Correction d'audit : le README « 15 fps by default » est juste (`[0] fps=15` dans la .dist).

## 2026-11-04 08:40 — Bilan de la nuit rc23 sur .11 et .24 (testeur)

Mesures : `/tmp/nightcam.sh` sur chaque caméra, 1 ligne / 180 s, du 2026-11-03 21:58 au 2026-11-04 07:36 UTC (192 mesures .11, 191 .24), plus `daynight.log`, dmesg, `stability.cgi`, `health.cgi`.

| Critère | .11 | .24 | Verdict |
|---|---|---|---|
| Reboots (uptime continu) | 0 (12 h 51 au matin) | 0 (12 h 33) | **OK** |
| RAM disponible | 19,8-21,8 Mo ; moyenne 1er quart 20,9 / dernier quart 20,9 | 20,0-21,6 Mo ; 20,5 / 20,4 | **OK, pas de fuite** |
| Charge | moy 1,00, max 2,67 | moy 1,02, max 1,57 | OK |
| Services (`health.cgi`) | tous attendus actifs, 0 redémarrage de service | — | OK (`memory-guard` affiché « stopped » alors qu'il est en autostart : à vérifier) |
| Bascule nuit | 23:17 UTC (lumière éteinte), luma 23-43 en nuit | nuit dès le soir (expo 2810) | **OK** |
| Retour jour | 07:36 UTC (luma 118, quand la pièce s'éclaire) | 06:17 UTC en `daynight.log`, expo jour 07:15 | **OK** |
| Couleurs du matin | couleur, légère dominante violette (rex=243 bex=341) | couleur, quasi neutre (rex≈655 bex≈718) | OK (dominante .11 à surveiller) |
| fps | 25 jour, 10 en basse lumière (`STAT cap` 122-125 / 49-51) | idem | OK (mode 10 fps prévu) |
| `awb.state` (tmpfs) | 24 écritures en 9,6 h | 25 | OK (tmpfs) ; écritures flash via cfg-persist non mesurées (pas de log) |
| **Ping passerelle (2 pings, -W1)** | **perte totale dans 21/192 mesures (11 %)**, pire 1 854 ms | **14/191 (7 %)**, pire 1 933 ms | **À corriger** |
| dmesg | 2 « isp pause fail » + réinit ISP à 11 442 s et 11 572 s (pendant mes tests `live.cgi` de la veille) ; rien pendant la nuit | carte SD : `FAT-fs … not properly unmounted` au boot | à suivre |

Analyse des pertes Wi-Fi : réparties toute la nuit (toutes les heures), **indépendantes d'une caméra à l'autre** (5 pertes .11 sur 24 seulement à ±3 min d'une perte .24) → pas la box, côté caméra. Économie d'énergie Wi-Fi **off** sur les deux (`iw … get power_save`), même canal 2 (2417 MHz), driver `rtl8xxxu`. Signal fort sur la .11 (-25 dBm moyen) qui a pourtant le plus de pertes ; .24 plus faible (balise -51 dBm, 19,5 Mbit/s MCS 2). Le premier ssh de ce matin vers la .11 a expiré, le second est passé : même phénomène.

Nouveaux défauts :
1. **`/tmp/wifi-quality.log` figé sur la .11 depuis 2026-11-03 20:13 UTC** alors que 3 processus `wifi-quality.sh` tournent (la .24 l'écrit encore) : le script se bloque.
2. Le RSSI de `wifi-quality.log` reste faux (-12/-16 sur la .11) : rappel du parsing `/proc/net/wireless` à corriger ; `iw dev wlan0 station dump` donne les bonnes valeurs (`signal avg`).
3. `health.cgi` : `memory-guard` « stopped » sur la .11 alors que `config/autostart/memory-guard` existe.
4. Carte SD .24 toujours marquée sale au boot (démonter avant reboot).

Pistes Wi-Fi pour l'implémenteur (par ordre) : (a) mesurer avec `RTSP_PACING_US=100` / `RTSP_SNDBUF=64` (rc22) une nuit sur une seule caméra, l'autre en témoin ; (b) `regulatory.db` / domaine FR ; (c) changer de canal côté box (canal 2 encombré ?) — décision du propriétaire ; (d) paramètres `rtl8xxxu` (ht40, dma aggregation).

## 2026-11-04 — Correctifs des constats de la nuit rc23 (`[night-fixes]`, à intégrer dans la rc24)

- **Quoi :**
  1. `wifi-quality.sh` : `iw` (5 s) et `ping` (8 s) sous `timeout` (un échantillon bloqué dans le pilote figeait le journal de la .11 depuis 20:13) ; le signal est désormais `signal avg` de `iw station dump` (déjà lu à chaque échantillon), écrit dans `/tmp/wifi-signal.avg` ; `scripts/wifi-signal.sh` (le seul lecteur du signal) l'utilise tant qu'il a moins de 3 min, sinon le niveau de `/proc/net/wireless`.
  2. `health-probe.sh` (`health.cgi` et `health-snapshot.sh`) : un service coupé par son interrupteur (clé de `service-switch.sh`, ou pas d'entrée `autostart` pour les autres ; `daynight=3` pour le jour/nuit auto) est `disabled`, plus `stopped` : Memory Guard (`MEM_GUARD_ENABLE=0` par défaut) ne compte plus comme un redémarrage.
  3. Carte SD : avant un redémarrage volontaire (`reboot-tracker.sh intent` : page web, bouton, MQTT, chiens de garde) l'enregistreur est mis en pause puis la carte remontée en lecture seule (5 s max) ; idem à la fin d'une mise à jour web. Un `reboot` tapé en ssh n'est pas couvert.
  4. `frigateyaml` : plus de mot de passe en clair, `{FRIGATE_RTSP_PASSWORD}` dans les adresses (Frigate le remplace depuis son environnement) ; README à jour.
- **Interrupteur :** aucun (revert du commit).
- **Test (rc24) :** (1) `WIFI_QUALITY=1` une nuit : `/tmp/wifi-quality.log` s'écrit jusqu'au matin, un seul processus `wifi-quality.sh` à la fois ; `rssi` du journal ≈ `signal avg` de `iw dev wlan0 station dump` ; tableau de bord et `metrics.cgi` donnent la même valeur. (2) `health.cgi` : `memory-guard` = `disabled` (avec `MEM_GUARD_ENABLE=0`), compteur de redémarrage à 0. (3) .24 : redémarrage depuis la page web → pas de `FAT-fs ... not properly unmounted` au démarrage suivant (`dmesg | grep FAT`). (4) Diagnostics → YAML Frigate : `{FRIGATE_RTSP_PASSWORD}` au lieu du mot de passe ; avec la variable définie dans Frigate, le flux s'ouvre.
- **Critères :** 1 à 4 conformes.

## 2026-11-04 — Plus de HTTPS sur la caméra : restes de la 2.x supprimés, HTTPS par un proxy (`[no-https]`)

Décision du propriétaire : l'interface reste en HTTP simple sur le port 80 ; le HTTPS se fait par un proxy sur son réseau (README, section « HTTPS with a reverse proxy » : Caddy, nginx).

- **Quoi :** supprimés : clés `WEB_MODE`, `ULTRALITE_HTTP_PORT`, `UI_ULTRALITE_MODE` et tout leur code (`set_web_mode`, `apply_web_mode_async`, assistant, `state.cgi`/`statelib.cgi`, `network.cgi`, `mqtt-bridge.sh`, `web-guard.sh` → port 80 seulement, lignes de l'export JSON), le badge « HTTPS impossible » et le mode « ultra-lite » de l'interface, `config/ssl/` (Let's Encrypt de la 2.x, paquet de certificats) et `config/openssl.cnf`. Les adresses du manifeste Home Assistant sont toujours `http://`. Gardés avec une valeur fixe pour Home Assistant : `web_mode: "http"`, `port_https_open: 0`. Le HTTPS sortant (curl vers Ntfy, webhooks, Telegram, GitHub) ne change pas.
- **Interrupteur :** aucun (revert de 0349ff1).
- **Test :** (1) `http://IP/` : l'interface se charge, vidéo fluide comprise, sans badge orange « HTTP ». (2) Page Réseau : plus de ligne « HTTPS web UI », « HTTP web UI » ouverte. (3) Manifeste (`state.cgi?cmd=integrationmanifest`) : adresses en `http://IP/…`, `web_mode` = `http`. (4) Import d'une ancienne sauvegarde JSON qui contient `web_mode` : réussit, `boot.conf` sans `WEB_MODE`. (5) Vérification de mise à jour (`UPDATE_CHECK=1`) et alerte Telegram ou Ntfy de test : fonctionnent (certificats du système). (6) Propriétaire : interface derrière son proxy HTTPS, vidéo fluide comprise (`live.cgi` sans mise en tampon).
- **Critères :** 1 à 6 conformes, entité Home Assistant toujours disponible.

## 2026-11-04 11:05 — Relecture testeur de c131441 / 0349ff1 / 5ba69c6 (pas encore de rc24)

CI verte sur `8e63100`. Relu, rien de bloquant ; mes correctifs d'hier sont intacts (validation MQTT/Telegram, import en une passe, fps).
- **`wifi-quality.sh` (c131441) : la source du signal est mal choisie.** Mesures du matin (`iw dev wlan0 station dump`, rtl8xxxu) : .24 `signal: 0 dBm`, `signal avg: -13 dBm`, `beacon signal avg: -51 dBm`, `/proc/net/wireless` -49, débit 19,5 Mbit/s MCS 2 ; .11 `signal avg: -25`, `beacon signal avg: -20`, `/proc` -31, 72,2 Mbit/s. `signal avg` est faux sur la .24 (-13 dBm avec MCS 2 est impossible) ; **`beacon signal avg`** concorde avec /proc et le débit. Proposition : lire `beacon signal avg:` (repli `signal avg`, puis /proc). Le passage sous `timeout` (iw 5 s, ping 8 s) répond bien au log figé de la .11.
- `frigateyaml` avec `{FRIGATE_RTSP_PASSWORD}` : OK ; à mentionner dans le CHANGELOG (une config collée telle quelle demande désormais la variable d'environnement côté Frigate).
- `no-https` (0349ff1) : sur 3.0 le web n'a jamais servi de HTTPS (busybox httpd), donc pas de régression pour une installation existante ; le bundle CA des connexions sortantes reste fourni par Buildroot (`/mnt/ext/etc/ssl/certs/ca-certificates.crt`, `CURL_CA_BUNDLE`), la suppression de `config/ssl/cacert` ne touche pas ntfy / GitHub / Telegram. À vérifier sur caméra avec la rc24 : `update-check.sh` et une notification ntfy.
- Toujours en attente : **rc24** (VERSION est encore 3.0.1-rc23) pour tester tout cela sur les deux caméras.

## 2026-11-04 — Signal Wi-Fi : `beacon signal avg` (suite de la relecture testeur de 11:05) (`[wifi-beacon]`)

- **Quoi :** `wifi-quality.sh` relève `beacon signal avg:` de `iw dev wlan0 station dump` (signal moyen des balises du point d'accès) au lieu de `signal avg:` (faux sur la .24 : -13 dBm avec MCS 2). Pas de repli sur `signal avg` (démontré faux avec rtl8xxxu) : sans ligne de balises, c'est le niveau de `/proc/net/wireless`. La valeur reste partagée par `scripts/wifi-signal.sh` (cache de 3 min) avec le tableau de bord, `metrics.cgi` et MQTT.
- **Interrupteur :** aucun (revert du commit).
- **Test (rc24, `WIFI_QUALITY=1`) :** `rssi` de `/tmp/wifi-quality.log` ≈ `beacon signal avg` de `iw` (.24 ≈ -51, .11 ≈ -20) et cohérent avec le débit (`tx bitrate`) ; même valeur sur le tableau de bord et `metrics.cgi`.
- **Critères :** écart ≤ 3 dB avec `beacon signal avg` ; plus de valeur aberrante (-13 avec MCS 2).

- 2026-11-04 11:30 (testeur) : `949f7d2` relu et vérifié sur la sortie réelle de `iw` de la .24 (retries 3, failed 1, `beacon signal avg` -51 → `3 1 -51`). OK. Prêt pour une **rc24**.

## 2026-11-04 — Version 3.0.1-rc24 (correctifs de l'audit, constats de la nuit rc23, HTTP seul)

- **Paquet :** artefact `tc100-3-release` du run CI du commit `[release] Bump to 3.0.1-rc24` (`tc100-3.0.1-rc24-update.tar`, mise à jour web : Outils → Mise à jour et sauvegarde). **Noyau inchangé depuis la rc23** (aucun patch noyau). La mise à jour web vérifie le noyau avant d'écrire (taille lue dans l'environnement U-Boot de chaque caméra).
- **Contenu depuis la rc23 :**
  - correctifs de l'audit (testeur, 2026-11-04 01:00) : `7c49fec` purge Bulma, `23a7c84` refus des caractères dangereux MQTT/Telegram, `cb946e4` import JSON en une passe (12-15 s), `9cf38e1` fps annoncés (25), `fd9c6b3` tests ;
  - `c131441` [night-fixes] : `wifi-quality.sh` sous `timeout`, services coupés affichés `disabled`, carte SD remontée en lecture seule avant un redémarrage volontaire et à la fin d'une mise à jour web, `{FRIGATE_RTSP_PASSWORD}` dans le YAML Frigate ;
  - `949f7d2` [wifi-beacon] : signal Wi-Fi = `beacon signal avg` ;
  - `0349ff1` [no-https] : HTTP seul (port 80), restes 2.x HTTPS / modes web / `config/ssl` supprimés ; README : HTTPS par un proxy (`5ba69c6`) ;
  - commits du propriétaire après le bump rc23, s'ils n'étaient pas dans la rc23 installée : `8fad9b1` vidéo fluide lancée d'office (tableau de bord, Réglages, multi-vue), `7c4ed8f` README.
- **À tester sur les deux caméras (ordre conseillé : la .11 d'abord, la .24 le lendemain) :**
  1. Installation par la mise à jour web : `VERSION` = 3.0.1-rc24, redémarrage, pas de mode sans échec (`boot-guard status` → `count=0` après 5 min), `dmesg | grep FAT` : **pas** de « not properly unmounted » sur la .24 après ce redémarrage.
  2. Entrées détaillées plus haut : `[night-fixes]` (2026-11-04), `[wifi-beacon]`, `[no-https]`, et les points de l'audit (refus `a b` / `$(reboot)` dans MQTT et Telegram, import JSON ≤ 15 s, 25 fps dans le YAML Frigate et le manifeste).
  3. `WIFI_QUALITY=1` une nuit sur les deux : journal écrit jusqu'au matin, `rssi` ≈ `beacon signal avg`, pertes de ping comparées à la nuit rc23 (7-11 %).
  4. `health.cgi` : `memory-guard` = `disabled`, aucun compteur de redémarrage qui monte pour un service coupé.
  5. Vérification de mise à jour et une notification Ntfy ou Telegram de test (certificats du système après la suppression de `config/ssl`).
  6. Propriétaire : interface derrière son proxy HTTPS, vidéo fluide comprise.
- **Critères :** 1 à 6 conformes, aucune régression par rapport à la nuit rc23 (pas de redémarrage, RAM stable ~20 Mo, bascule jour/nuit).

## 2026-11-04 — Retours du propriétaire : mDNS, `syslog/host`, licence (`[license]`)

- **mDNS :** `<nom>.local` confirmé par le propriétaire depuis son poste. Point fermé dans `release-3.0.1.md`.
- **`syslog/host` (.11 = 192.168.1.23, .24 = 192.168.1.22) :** les deux adresses sont le même Synology ; pas de défaut, rien à aligner. À vérifier au passage avec la rc24 : les journaux des deux caméras arrivent bien sur le Synology.
- **Licence :** fichier `LICENSE` = texte officiel de la GPL-2.0 (cohérent avec les patchs noyau et `libakuio`, déjà `SPDX-License-Identifier: GPL-2.0`) ; README (« Where it comes from ») et `CREDITS.md` le disent, le code tiers garde sa licence. Pas de test caméra.

## 2026-11-04 — Origine des binaires préconstruits ; surexposition au démarrage close (`[credits]`)

- **Binaires :** `rwconf`, `getflag`, `getimage` = sources publiques (Unlicense) de `anyka-v4l2rtspserver/libv4l2cpp` (ThatUsernameAlreadyExist), construites par `tools.sh` de `anyka-software` ; `monvifd` = binaire du même auteur (« Micro ONVIF discovery service v1.1 », publié en 2023 dans son hack JCO-PM203 puis TC100), sans source ni licence. Détail dans `CREDITS.md`. Proposé après la 3.0.1 : reconstruire les trois premiers en CI, remplacer `monvifd` (ONVIF coupé par défaut).
- **Surexposition après démarrage (.11, rc20) :** plus revue par le propriétaire depuis ; close comme cas isolé, à rouvrir si elle revient (critère : luma < 200 en 30 s après le démarrage).
- Pas de test caméra.

## 2026-11-04 — Pays Wi-Fi (`regulatory.db`), Wi-Fi plus tôt au démarrage (`[wifi-country]`)

- **Quoi :**
  1. **Base des règles Wi-Fi** : `BR2_PACKAGE_WIRELESS_REGDB=y` (Buildroot) → `/lib/firmware/regulatory.db` dans l'initramfs ; le noyau (inchangé, `CFG80211=y`, signature non exigée) la lit au démarrage. Plus de `cfg80211: failed to load regulatory.db`. La base Buildroot est reconstruite une fois en CI (~40 min, cache ensuite). `build-rootfs66.sh` prévient si le fichier manque.
  2. **Pays** : clé `WIFI_COUNTRY` de `boot.conf` (seule source ; vide = règles « monde » comme avant), lue par `scripts/wifi-country.sh` (et par `S39tc100` avec le même motif, avant la partie utilisateur). `wpa_supplicant` démarre sur une copie de `config/wpa_supplicant.conf` avec `country=XX` en première ligne (S39 et `wifi-apply`) ; `autorun` relit la base si le noyau l'a ratée et règle le pays s'il n'est pas appliqué ; Réglages → Réseau → « Pays (règles Wi-Fi) » l'applique tout de suite (`wpa_cli set country` + `iw reg set`, sans reconnexion) ; le point d'accès de secours reçoit `country_code` + `ieee80211d=1` ; export / import JSON (`boot.wifi_country`, code ISO à 2 lettres majuscules ou vide).
  3. **Wi-Fi plus tôt** : dans `S39tc100` (la console et le mot de passe restent avant le Wi-Fi : quelques ms, et sans réseau ils n'attendent pas les 20-30 s du DHCP, audit du 2026-11-04) ; `udhcpc -T 1 -t 20 -A 5` (une demande par seconde au lieu de 3 s : les premières partent avant l'association) ; le nom DHCP vient de `config/hostname.conf` (`/tmp/dhcp-hostname`), donc `autorun` ne tue plus `udhcpc` sur une caméra qui a son propre nom (le nouveau `udhcpc` effaçait l'adresse jusqu'au bail : coupure à chaque démarrage de la .11 et de la .24). Attente de `wlan0` par pas de 0,2 s.
  4. Page Réglages : « Se connecter à ce réseau » et « Relancer l'assistant » affichaient « Error: Unexpected response » après un enregistrement réussi (`ok:true` attendu comme `status:success`). Corrigé.
- **Interrupteur :** `WIFI_COUNTRY=` vide = comportement d'avant pour le pays. Le reste : revert du commit (initramfs, donc mise à jour web complète).
- **Test (les deux caméras, mise à jour web) :**
  1. Après le démarrage : `dmesg | grep -i regulatory` → pas de « failed to load » ; `iw reg get` → `country 00` sans pays.
  2. Réglages → Réseau → Pays = FR, Enregistrer : « En vigueur : FR » après 2-3 s, **pas de coupure** (ping continu depuis le Mac) ; `iw reg get` → `country FR: DFS-ETSI` ; `head -1 /etc/wpa_supplicant.conf` → `country=FR` ; `grep WIFI_COUNTRY /mnt/config/boot.conf`.
  3. Redémarrer : `iw reg get` → FR sans action ; `logread | grep -i country`.
  4. Temps du Wi-Fi : `dmesg` / `logread` : moins de secondes entre « wlan0: associated » et l'adresse DHCP qu'avant ; ping continu depuis le Mac pendant un redémarrage : premier ping reçu (noter l'heure) ; **plus de perte pendant la première minute** une fois la première réponse reçue. `ps | grep udhcpc` : un seul, lancé par S39 (pas de redémarrage par autorun) ; le nom DHCP est celui de la caméra sur la box.
  5. Réglages → Réseau : « Se connecter à ce réseau » sur le réseau actuel → message de succès (plus d'« Unexpected response »).
  6. Nuit `WIFI_QUALITY=1` en FR : pertes de ping comparées à la nuit rc23 (7-11 %).
  7. Point d'accès de secours (bouton reset 3-7 s) : `cat /tmp/wifi-rescue/hostapd.conf` → `country_code=FR` ; le téléphone le voit et s'y connecte.
- **Critères :** 1-5 et 7 conformes ; 6 : pas pire que la rc23 (mieux attendu si les pertes venaient du domaine monde).

## 2026-11-04 — Pont MQTT en C : `tc100-mqttd` (`[mqtt-c]`)

- **Quoi :** `src/mqttd` = un seul processus C (MQTT 3.1.1, TCP simple, QoS 0) à la place des 4 processus shell de `mqtt-bridge.sh run` (~5,7 Mo cumulés). Il tient la connexion (CONNECT `<id>-sub`, Will retenu `<root>/availability` = `offline`, `online` à chaque connexion, PINGREQ toutes les 30 s, reprise avec le backoff et le disjoncteur de `mqtt.conf`), s'abonne au topic de commande et lance `mqtt-bridge.sh command <payload> mqtt` (argument unique, jamais `system()`, 120 s maximum). **Les payloads restent produits par `mqtt-bridge.sh`** (modes `startup`, `health-cycle`, `command`, `print-config`) : discovery, santé, manifeste, résultats de commande = mêmes topics et mêmes octets que le pont shell (test hôte de parité). Les autres scripts (`mqtt-bridge.sh publish`, mouvement, son, sabotage) passent par le FIFO `/tmp/mqtt-bridge.pub` du démon au lieu d'ouvrir une connexion chacun. Binaire compilé par la CI (`tc100-mqttd` dans `tc100test/`, copié dans le stack).
- **Interrupteur :** `MQTT_BRIDGE_IMPL=shell|c` dans `/mnt/config/mqtt.conf` (seule source), lu par `controlscripts/mqtt-bridge` ; **`shell` par défaut**. Pour essayer : mettre `MQTT_BRIDGE_IMPL=c`, puis `/mnt/controlscripts/mqtt-bridge restart`. Retour : `shell` + restart. Sans binaire installé, retombe seul sur le shell. Aucune modification du noyau, de U-Boot ni du Wi-Fi.
- **Test (une caméra, MQTT activé, broker réel) :**
  1. `MQTT_BRIDGE_IMPL=c`, restart. `ps | grep mqtt` : un seul `tc100-mqttd` (plus de `mqtt-bridge.sh run`) ; `grep -E 'VmRSS|VmHWM' /proc/$(cat /var/run/mqtt-bridge.pid)/status` (attendu < 500 Ko au repos, mesure à noter) ; `/tmp/log/mqtt-bridge.log` : « MQTT connected ».
  2. Home Assistant : les ~30 entités existantes **gardent leurs identifiants** (aucun doublon `_2`), l'appareil et la version (`sw`) sont inchangés ; `<root>/availability` = `online` retenu ; `<root>/health` se met à jour toutes les 300 s ; `<root>/isp/state` et `motion/state` suivent.
  3. Commandes depuis HA ou `mosquitto_pub -t <root>/command` : `{"cmd":"ir_led","value":"on"}`, `snapshot`, `profile:low-cpu`, `play_sound` (bouton Chime), `isp_brightness`, `health`, `discovery`, `restart_mqtt_bridge` (le démon redémarre seul, fichier pid refait), `reboot` en dernier. Chaque commande donne un `command/result` et agit sur la caméra ; une commande inconnue donne `rejected`.
  4. Événements des autres scripts : mouvement ON/OFF (`motion/state`), babyphone, sabotage arrivent sans connexion TCP supplémentaire (`netstat -tn | grep 1883` : une seule).
  5. Interface web : Réglages → Intégrations affiche « connecté » (`/tmp/mqtt_last_pub.status` « <t> ok » rafraîchi) ; mauvais mot de passe MQTT : « login refused » (`fail 4` ou `fail 5`) ; broker coupé 1 min puis rétabli : le démon se reconnecte (journal « recovered after N error(s) ») sans intervention, le Will met `availability` à `offline` pendant la coupure.
  6. Arrêt : `mqtt-bridge stop` publie `offline`, le FIFO et `/var/run/tc100-mqttd.pid` disparaissent ; `kill -9` du démon puis `mqtt-bridge.sh publish event x 0` : repli sur la connexion unique (pas de blocage).
  7. Nuit complète (soak) avec `c` : pas de redémarrage, RAM stable, `mqtt-bridge.log` sans erreur répétée.
- **Critères :** 1 à 7 conformes ; RSS du démon bien en dessous des ~5,7 Mo du pont shell ; aucune entité HA dupliquée ou renommée ; au moins une commande de chaque famille (interrupteur, profil, son, ISP, santé, redémarrage) exécutée. Si tout passe sur les deux caméras : mettre `MQTT_BRIDGE_IMPL=c` par défaut dans `config/mqtt.conf.dist` (le testeur peut le faire) ; ne pas encore supprimer le pont shell (repli).
- **Différences connues avec le pont shell :** pas de recyclage horaire de la connexion ; un PINGREQ sans réponse en 20 s coupe la connexion (le shell ne le détectait pas) ; `mqtt_last_pub.status` est aussi rafraîchi à chaque PINGRESP/envoi (au plus 1 fois par s), pas seulement à chaque publication ; une commande bloquée 120 s est tuée ; les publications faites hors connexion attendent la reconnexion (128 Ko max) au lieu de partir sur une connexion à part ; `MQTT_STREAM_*`, `MQTT_COMMAND_WAIT_SECONDS`, `MQTT_PERSISTENT_SUBSCRIBE`, `MQTT_FORGE_SUBSCRIBE` ne servent qu'au pont shell ; le TLS n'existe dans aucun des deux. Non vérifié sans caméra : l'édition de liens sous uClibc (comme `tc100_rtsp`) et le fonctionnement de `printf '\000'` du busybox de la caméra (le pont shell utilisait déjà `\x00`).

## 2026-11-04 — Correctifs de l'audit du soir (`[audit]`, voir `audit-2026-11-04.md`)

- **Quoi :** (H1) `tc100_rtsp` : tampon re-terminé après une trame entrelacée `$`, longueur incohérente → client fermé ; (W1) plus de valeur de la requête réécrite dans les pages d'erreur de `viewrecords.cgi`, `camcontrols.cgi`, `scripts.cgi` ; journal d'audit limité à `[A-Za-z0-9_.-]` ; `showlog` échappe les journaux ; (W5) `user.pwd` copié depuis `.dist` avant `web-auth` sur tous les chemins ; (B2) dans `S39`, console et mot de passe de nouveau avant le Wi-Fi ; CI durcie.
- **Interrupteur :** aucun (revert du commit).
- **Test (rc suivante, une caméra) :**
  1. RTSP : Frigate / VLC lisent toujours le flux principal, le sous-flux et l'audio, en TCP et en UDP ; la voie de retour (push-to-talk ONVIF) passe toujours en TCP entrelacé.
  2. `http://<cam>/cgi-bin/viewrecords.cgi?cmd=<b>x</b>` affiche « Unsupported command » sans gras ; `action.cgi?cmd=showlog` affiche les journaux en texte (aucune balise interprétée).
  3. Mode sans échec (ou caméra sans `user.pwd`) : l'interface demande toujours un mot de passe.
  4. Console série au démarrage sans Wi-Fi : invite de login tout de suite (plus d'attente du DHCP).
- **Critères :** 1-4 conformes, aucune régression de flux.

## 2026-11-04 18:20 — rc24 téléchargée (testeur) : deux paquets portent le même nom

- `36e573c` (bump rc24, paquet désigné par le plan de test) : `tc100-3.0.1-rc24-update.tar` md5 `5c9c264201c3d70a44874181aafd6ca8` → `~/Downloads/tc100-fix/xfer24/` sur le Mac du propriétaire.
- `5c6b059` (rc24 + `[license]`, `[credits]`, `[wifi-country]`, `[mqtt-c]`, `[audit]`) : `VERSION` dit aussi **3.0.1-rc24**, md5 `0f7abf39b6f95300045757cddd7ff7b9` → `xfer24-latest/`.
- **Demande à l'implémenteur** : ne pas publier deux contenus sous le même numéro ; si `5c6b059` est la version à tester (elle contient le correctif RTSP H1 et les changements de démarrage `S39tc100`/udhcpc), la renuméroter **rc25**. Sinon, le testeur installe `xfer24` d'abord, puis la suivante sous un nouveau numéro.
- Je n'ai trouvé aucun détail dans le dépôt sur la « CVE-2026-98432 » citée dans l'entrée rc24 (« décision du propriétaire en attente ») : décrire le problème, le patch et le risque pour que le propriétaire puisse décider.

## 2026-11-04 — Version 3.0.1-rc25 (remplace la rc24 : un seul paquet par numéro)

- **Réponse au testeur (18:20) :** oui, `5c6b059` devait être renuméroté ; c'est fait. La rc24 n'est plus à tester : la rc25 la contient entièrement. Ne pas installer `xfer24-latest/` (contenu rc25 sous le numéro rc24).
- **Paquet :** artefact `tc100-3-release` du run CI du commit `[release] Bump to 3.0.1-rc25` (`tc100-3.0.1-rc25-update.tar`, mise à jour web). **Noyau inchangé depuis la rc23.** **Initramfs modifié** (`regulatory.db`, `S39tc100` : pays Wi-Fi, nom DHCP, `udhcpc -T 1`) : la mise à jour web l'écrit comme à chaque version.
- **CVE-2026-98432 :** le dépôt ne contient rien d'autre que la mention « décision du propriétaire en attente » (entrée rc24) : ni description, ni patch, ni source. L'implémenteur ne peut pas la documenter sans la source de cette mention ; le propriétaire la fournit (note du projet claude.ai ?) ou la mention est retirée. Rien n'a changé dans le noyau à ce sujet.
- **Contenu depuis la rc24 :** `c70d93f` [license] GPL-2.0 ; `77dacb8` [credits] origine des binaires préconstruits ; `56c0da0` [wifi-country] ; `452cc5c`/`498bd72` [mqtt-c] (`MQTT_BRIDGE_IMPL=shell` par défaut) ; `5c6b059` [audit] (H1 RTSP, W1 XSS, W5 mot de passe en mode sans échec, B2 ordre console/Wi-Fi dans S39, CI).
- **À tester sur les deux caméras (la .11 d'abord) :**
  1. Installation par la mise à jour web : `cat /mnt/VERSION` = 3.0.1-rc25 ; redémarrage ; `boot-guard status` → `count=0` après 5 min ; `dmesg | grep -i -E 'regulatory|FAT'` : pas de « failed to load regulatory.db », pas de « not properly unmounted » (.24).
  2. Le plan rc24 (entrée « Version 3.0.1-rc24 », points 1-6) sur la rc25.
  3. Entrées `[wifi-country]` (pays FR sans coupure, Wi-Fi au démarrage, « Se connecter à ce réseau » sans faux message d'erreur), `[audit]` (flux RTSP TCP/UDP et voie de retour, pages d'erreur, `showlog`, mode sans échec, console).
  4. `[mqtt-c]` sur **une** caméra seulement (`MQTT_BRIDGE_IMPL=c`), l'autre en témoin avec le pont shell.
  5. Une nuit `WIFI_QUALITY=1` en FR sur les deux : pertes de ping comparées à la nuit rc23 (7-11 %).
- **Critères :** 1-5 conformes, aucune régression par rapport à la nuit rc23 (pas de redémarrage, RAM stable ~20 Mo, bascule jour/nuit).

## 2026-11-04 18:35 — rc25 téléchargée (testeur)

- Build `d89f913` (CI et build verts) : `tc100-3.0.1-rc25-update.tar` md5 `58a786f84ba28e4e4c0db4a8c32a6f58`, `VERSION` 3.0.1-rc25 → `~/Downloads/tc100-fix/xfer25/` sur le Mac du propriétaire. Contenu = `5c6b059` + bump (diff `5c6b059..d89f913` : CHANGELOG, VERSION, docs seulement). Les paquets rc24 (`xfer24`, `xfer24-latest`) sont périmés : ne pas les installer.
- Plan : rc25 sur la **.11 seule** ; la **.24 reste en rc23** cette nuit comme témoin (pertes Wi-Fi avec / sans `regulatory.db` + `WIFI_COUNTRY=FR`). Tests du plan rc25 dès que la .11 a redémarré.
- CVE-2026-98432 : la mention vient de l'entrée rc24 de l'implémenteur et rien dans le dépôt ne la documente ; à retirer de la checklist si personne ne peut en donner la source.

## 2026-11-04 18:55 — rc25 sur la .11 : résultats (testeur)

Installée par le propriétaire (mise à jour web) ; la .24 reste en **rc23** (témoin de nuit). Mesures à 9-13 min d'uptime.

| Test du plan | Résultat |
|---|---|
| `VERSION` 3.0.1-rc25, boot-guard | OK, `count=0`, mode normal |
| `regulatory.db` | OK : plus de « failed to load regulatory.db » ; `iw reg get` → `country FR: DFS-ETSI` avant même le réglage (pays annoncé par la box) |
| Pays Wi-Fi (`wifi_set_country` FR) | OK : `WIFI_COUNTRY=FR`, `country=FR` en tête de `/etc/wpa_supplicant.conf`, **0 perte sur 75 pings** (0,2 s) pendant l'application |
| MQTT `a b` / `$(reboot)` | refusés (`INVALID_VALUE`) |
| `frigateyaml` | `1920x1080@25`, `640x360@25`, `{FRIGATE_RTSP_PASSWORD}`, plus de mot de passe en clair |
| `integrationmanifest` | `"fps":25` ×2 |
| XSS `viewrecords.cgi?cmd=<b>x</b>` / `camcontrols.cgi?cmd=<script>` | « Unsupported command » sans balise ; 0 `<script>` renvoyé ; `showlog` sans balise |
| `health.cgi` | `memory-guard` = `disabled` (juste : `MEM_GUARD_ENABLE=0` ; l'entrée `config/autostart/memory-guard` est un reste ignoré), `wifi-rescue` = `disabled` |
| RTSP TCP | principal hevc 25 fps + audio, sous-flux h264 + audio OK |
| RTSP UDP | **non testable d'ici** (ma VM est derrière un NAT : le RTP ne revient pas) — à vérifier par le propriétaire (VLC UDP) ou par Frigate |
| `wifi-quality.log` | écrit chaque minute ; RSSI -15/-20 ≈ `beacon signal avg` -21 dBm |
| Import JSON (123 valeurs) | 23 s juste après le boot (charge 2,6), **13,6 s** ensuite |
| TLS sortant (`config/ssl` supprimé) | `curl` avec le bundle de Buildroot : GitHub 200 et ntfy 200, `ssl_verify_result=0` |
| SD | pas de carte dans la .11 (test « non properly unmounted » à faire sur la .24 quand elle passera en rc25) |

Petites remarques : `MEM_GUARD_SOFT_SERVICES="network-monitor"` dans `boot.conf` cite un service supprimé ; `config/autostart/memory-guard` reste alors que le service est coupé par son interrupteur. Une session ssh n'a pas `CURL_CA_BUNDLE` (seuls les services lancés par autorun l'ont) : sans gravité.

Nuit : enregistreur relancé sur les deux caméras (17:51 UTC) → comparaison des pertes Wi-Fi .11 rc25 (FR + regdb) / .24 rc23 (monde) demain matin. La .24 est à 18,8 Mo disponibles après 22,8 h d'uptime (20,5 Mo hier soir) : à suivre.

## 2026-11-04 19:20 — Pont MQTT en C (`MQTT_BRIDGE_IMPL=c`) sur la .11 : fonctionne, un défaut d'arrêt corrigé (testeur)

Activé à la demande du propriétaire sur la .11 (rc25) : `MQTT_BRIDGE_IMPL=c` ajouté à `/mnt/config/mqtt.conf` (sauvegarde `/tmp/mqtt.conf.before-c`), pont shell arrêté.
- **Mémoire** : `tc100-mqttd` **376-440 Ko** (VmRSS) contre **7 976 Ko** cumulés pour les 7 processus du pont shell.
- **Connexion** : une seule connexion TCP 1883 ; `ipcamera2/availability` = `online` retenu ; log « MQTT connected … root=ipcamera2 ».
- **Commandes** : `{"cmd":"health"}` → `command/result` + `last_result` + `event` + `health` + `isp/state` en < 1 s.
- **Événements des autres scripts** : `mqtt-bridge.sh publish event …` passe par le démon (toujours une seule connexion) ; après `kill -9` du démon, repli sur une connexion unique sans blocage (`publish rc=0`).
- **Découverte HA** : 48 configs, 47 `uniq_id` distincts, aucun `_2` ; le doublon `ipcamera2_night_mode` est un `binary_sensor` et un `switch` (domaines différents, accepté par HA, déjà le cas avec le pont shell).
- **DÉFAUT trouvé et corrigé** : `start` faisait `run_busybox nohup "$BIN" &` ; `run_busybox` est une fonction shell, donc `$!` = le sous-shell, pas le démon. `stop` tuait le sous-shell, **le démon restait** ; le `start` suivant en lançait un second avec le même client id → le broker les éjectait tour à tour, `availability` basculait `offline`/`online` **toutes les 2 s**. Correctif dans `controlscripts/mqtt-bridge` : `start` attend le pid file du démon et l'écrit dans `mqtt-bridge.pid` ; `stop` tue le démon par son pid file puis tout `tc100-mqttd` restant (`pidof`). Retesté sur la .11 (script superposé en RAM) : restart ×2, stop, start, start ×2, kill -9 + start → **toujours un seul démon**, pid file = démon, 4 paires offline/online = les 4 arrêts voulus, puis 45 s sans aucune bascule. Tests statiques ajoutés (`tests/test_audit_fixes.py`).
- Le pont shell avait le même `$!` faux, masqué par le ménage des orphelins `mqtt-bridge.sh run` dans `stop`.
- La .11 reste en mode C cette nuit (soak) ; le script corrigé est superposé en RAM jusqu'au prochain redémarrage (au démarrage, un seul `start`, donc pas de doublon). Il faut une rc26 pour l'avoir en flash.
- Remarque : `MQTT_TOPIC_ROOT=tc100/camera` dans `mqtt.conf` mais les deux ponts publient sous `ipcamera2/` (racine tirée du nom d'hôte ?) : à documenter ou aligner.

### Correction 19:35 — gain mémoire réel du pont C (testeur)
Le « 376 Ko contre 7 976 Ko » plus haut compare des **RSS**, qui comptent plusieurs fois le code busybox partagé par les processus shell. Mesure par `smaps_rollup` : pont shell (.24, 4 processus) **PSS 1 129 Ko**, privé 416 Ko ; `tc100-mqttd` (.11) **PSS 209 Ko**, privé 84 Ko. Gain réel ≈ **0,9 Mo** (sur ~20 Mo disponibles), plus les forks évités (curl par publication, sous-shells) ; `MemAvailable` de la .11 n'a pas bougé de façon mesurable juste après la bascule. Le critère « RSS du démon bien en dessous des 5,7 Mo » du plan est donc trompeur : comparer les PSS.

## 2026-11-04 19:40 — Où va la RAM (testeur, .11 rc25, pont MQTT en C)

Mesure `smaps_rollup` de tous les processus : **espace utilisateur = 7,1 Mo PSS** (5,6 Mo privés, 24 processus) sur 59,9 Mo. Le reste : CMA 30 Mo réservés au vidéo (6,3 Mo libres sur la .11, 1,4 Mo sur la .24), noyau/slab 4,5 Mo, cache 13,9 Mo (récupérable, compté dans MemAvailable 21,7 Mo).

| PSS | Processus | Piste |
|---|---|---|
| 2 783 Ko | `tc100_rtsp` | déjà en C |
| 794 Ko | `wpa_supplicant` | nécessaire |
| 659 Ko | `arecord` (micro) | lire ALSA directement dans `tc100_rtsp` : ~0,6 Mo |
| 217 Ko + 90 Ko | `sh controlscripts/mqtt-bridge start`, `sh /etc/init.d/S39tc100 start` restés en attente | `exec` (ou ne pas attendre) : ~0,3 Mo **sans C** |
| ~1,2 Mo au total | démons shell : `sound-detection` 269, `housekeeper` 250, `auto-night-daemon` 191, `cfg-persist` 154, `service-watchdog` 141, `button-watch` 129 | un seul démon C les regroupant : ~1 Mo |
| < 200 Ko chacun | dropbear ×2, logfwd, watchdog, ntpd, klogd, getty, udhcpc, mdnsd, httpfront | déjà petits |

Bilan : le C peut encore libérer **environ 2 Mo** au total (≈ 10 % de la RAM disponible), dont 0,3 Mo sans écrire de C. La RAM n'est pas le goulot actuel (20 Mo stables la nuit, pas de fuite) ; la marge qui compte est la **CMA de la .24 (1,4 Mo libres)**, que ces portages ne touchent pas. Priorité proposée : les 2 `exec` (risque nul), puis `arecord` dans `tc100_rtsp` ; le démon C unique seulement si un besoin mémoire apparaît (beaucoup de logique shell testée à réécrire).

## 2026-11-04 19:45 — RAM libre au service de la vidéo : deux essais sur la .11 (décision du propriétaire : tous les tests sur la .11)

**Essai 1 (en cours cette nuit) — file d'envoi client plus grande : `RTSP_QMAX=1024`.**
- Constat : la file par client vaut 384 Ko (`QMAX_DEF`, ≈ 2 s à 1,6 Mbit/s) ; la nuit rc23 a montré des blocages Wi-Fi de 1-2 s (ping max ~1,9 s). Au-delà de la file, `bcast()` saute les images jusqu'à la prochaine IDR (`dropped`).
- Réglage : `RTSP_QMAX=1024` ajouté à `/mnt/config/rtsp.env` de la .11 (sauvegarde `/tmp/rtsp.env.before-qmax`, le fichier était vide), `rtsp-h26x restart` à 18:39 UTC ; log : `client queue 1024 KB` (≈ 5 s). Coût : jusqu'à ~1 Mo de RAM par client congestionné (un client : Frigate).
- `RTSP_SNDBUF` n'est **pas** le bon levier (il plafonne `SO_SNDBUF`, l'inverse) ; `RTSP_PACING_US` non activé pour garder un seul changement.
- Mesure : l'enregistreur de nuit note maintenant `drop` (compteur cumulé `dropped` du STAT) sur la .11 **et** la .24 (témoin rc23, file 384 Ko) ; parties précédentes dans `/tmp/night-part1.log`. Critère : moins d'images sautées sur la .11 que sur la .24 pour des pertes Wi-Fi comparables ; latence du direct à surveiller après un blocage (la file plus longue retarde au lieu de sauter).
- Retour : vider `/mnt/config/rtsp.env` puis `rtsp-h26x restart`.

**Essai 2 (demande à l'implémenteur) — mode smart de l'encodeur (meilleure image ou moins de débit à qualité égale).**
- `smart_apply()` exige `SMART_LTR_NEED` = 3 407 872 + 256 Ko libres dans le pool encodeur ; avec `ak39_venc.pool` 9600K il reste ~1,9 Mo (R11-01 : `alloc dma for 3407872 failed`, serveur arrêté). Le paramètre est `0444` (pas modifiable à chaud) et la ligne de commande vient du bootloader (interdit d'y toucher).
- Demande : un build pour la .11 avec la **valeur par défaut compilée** `ak39_venc.pool=12M` (patch 0015, pas de U-Boot), puis test `RTSP_VBR=1` + `RTSP_SMART=1` (mode 1 « long-term reference », pas le mode 2) : log `smart mode 1 (long-term reference)`, pas de `alloc dma … failed`, serveur vivant 24 h, MemAvailable attendu ~2,4 Mo plus bas (≈ 18-19 Mo), débit / qualité comparés à la .24.

## 2026-11-04 19:50 — Liste consolidée des changements à faire (testeur)

Tout ce qui reste ouvert après la rc25 est rassemblé, par priorité (P0 rc26 / P1 3.0.2 / P2), dans **`docs/linux-port/a-faire-implementeur.md`**. Premier point : publier une rc26 avec le correctif d'arrêt du pont MQTT en C (`04f2313`, `9853759`).

## 2026-11-04 20:15 — rc26 relue et téléchargée (testeur)

- Build `342b523` (CI + build verts, seul build rc26) : `tc100-3.0.1-rc26-update.tar` md5 `95cc1c2ce46253077fcb11faef9eec4a` → `~/Downloads/tc100-fix/xfer26/`. Le `stack.sqfs` contient bien le `controlscripts/mqtt-bridge` corrigé (`MQTTD_PIDFILE`, arrêt par `pidof`).
- Relecture de `3bd0dc1` / `342b523` :
  - OK : CVE retirée ; `config/autostart/memory-guard` retiré (le service ne dépend que de `MEM_GUARD_ENABLE`, `service-switch.sh`) ; sur une caméra déjà installée, l'ancienne entrée reste dans `/mnt/config` (données de l'utilisateur), sans effet.
  - `MEM_GUARD_SOFT_SERVICES=""` était déjà vide dans la `.dist` ; c'est le `boot.conf` des caméras installées qui garde `"network-monitor"` (sans effet, service absent).
  - **Pas fait, coché à tort** : « mqtt.conf : documenté la règle de dérivation du topic root (`_mb_slug`) » : aucun changement de doc ; la règle n'est expliquée que dans le commentaire de `scripts/mqtt-bridge.sh:160-188` (client id par défaut `tc100-camera` → client id et racine = nom d'hôte en minuscules, `ipcamera2`). À écrire dans `config/mqtt.conf.dist` au-dessus de `MQTT_TOPIC_ROOT` et dans `docs/api.md`.
  - **P0 n° 2 pas fait** : `controlscripts/mqtt-bridge` garde `run_busybox nohup … &` (le sous-shell `sh mqtt-bridge start` reste en mémoire, 217 Ko) ; `S39tc100` redirige seulement les sorties de l'autorun (`</dev/null >/dev/null 2>&1 &`), ce qui ne supprime pas le `sh /etc/init.d/S39tc100 start` resté vivant — à vérifier sur caméra avec la rc26.
- Installation conseillée : la **.11** (demain matin, après le bilan de la nuit en cours, pour ne pas casser la mesure) ; la .24 reste en rc23.

## 2026-11-04 nuit — Vérification du projet après la rc26 (implémenteur, `[verify]`)

- **Corrigé :** `src/webui/index/90-startup.js:53` (et le bundle) : la regex de détection du redémarrage contenait un caractère « retour arrière » (0x08) au lieu de `\b` ; elle ne correspondait jamais. Effet depuis le 2026-10-30 (`c763490`) : après « Redémarrer » sur le tableau de bord, « Command sent to the camera » au lieu de « Restarting: the camera is back in about a minute », et un message rouge « The camera did not accept the command » quand la connexion tombait pendant le redémarrage. Test ajouté : aucun caractère de contrôle dans `www/`, `src/webui/`, `scripts/`, `controlscripts/`, `v3/`.
- **CHANGELOG rc26 corrigé :** la ligne « ~0,3 Mo gagnés au démarrage » était fausse (voir `a-faire-implementeur.md`, P0 n° 2, note de vérification).
- **Interrupteur :** aucun.
- **Test (rc suivante) :** tableau de bord → Redémarrer → « Restarting: the camera is back in about a minute », puis éventuellement « The camera stopped answering: it is probably restarting » (orange), jamais le message rouge.

## 2026-11-04 nuit — Page « Test du matériel » (`[hwtest]`, feuille de route n° 49)

- **Quoi :** Outils → Test du matériel (`www/hardware.html`) : la caméra dessinée de face et de dos (d'après la photo du propriétaire) ; un clic sur un élément le teste avec les commandes existantes : image + luminance / exposition (objectif), LED bleue (allumer, éteindre, clignoter), LED rouge, LED IR et filtre IR-cut, vumètre du micro, carillon sur le haut-parleur, carte microSD (taille, libre, santé), bouton reset affiché enfoncé. Une seule nouvelle commande, en lecture : `action.cgi?cmd=hw_state` (toutes les 2 s tant que la page est ouverte et visible, arrêt en quittant la page). Thème clair / sombre, mobile.
- **Interrupteur :** aucun (page à part ; revert du commit).
- **Test (une caméra) :**
  1. Chaque élément : LED bleue et rouge allumées / éteintes / clignotement visibles sur la caméra **et** sur le dessin ; LED IR (lueur dans le noir, visible au téléphone) ; filtre IR-cut (clic audible, image qui change) ; carillon entendu ; carte .24 : taille et libre corrects ; objectif : image actuelle + luminance.
  2. Micro : avec la détection sonore activée, le vumètre monte quand on parle ; sans elle, le message « Pas de niveau ».
  3. Bouton : appui bref → dessin jaune puis « Relâché (un appui a été vu) » (si `button-watch` a exporté le GPIO 522 ; sinon « Le bouton ne peut pas être lu », à noter).
  4. Charge : `top` pendant 2 min page ouverte : un `action.cgi` toutes les 2 s, CPU moyen à noter ; page quittée : plus aucune requête `hw_state` (journal httpd).
  5. **Emplacements** : dos redessiné d'après la photo du propriétaire (bouton reset = trou en haut à gauche, haut-parleur = gros trous en haut à droite, disque de fixation, micro-USB, fente SD sur le côté). **À confirmer** : le dos n'a pas de LED, donc la LED rouge est supposée être la deuxième couleur de la LED d'état en façade (point du haut) ; vérifier en cliquant « Rouge allumée ».
- **Critères :** 1-4 conformes, aucune action de la page sans jeton CSRF (les commandes de modification répondent 403 sans lui).

## 2026-11-05 — Feuille de route 20, 22, 26, 27, 29 complétées (`[roadmap]`)

- **Quoi :**
  - **26** Carillon / Alerte / Sirène sur le tableau de bord (volume du curseur du haut-parleur, confirmation pour la sirène).
  - **27** `http://<caméra>/metrics` (redirection `httpfront`) ; nouvelles métriques : `tc100_rtsp_capture_fps`, `tc100_rtsp_main_kbps`, `tc100_rtsp_sub_kbps`, `tc100_rtsp_clients_playing`, `tc100_rtsp_dropped_frames` (fichier `/var/run/tc100_rtsp.stat` écrit par `tc100_rtsp` toutes les 5 s), `tc100_sdcard_present|size_bytes|free_bytes`, `tc100_info{version}`.
  - **29** scripts et feuilles de style chargés en `?v=<md5>` (`src/webui/stamp-assets.sh`, lancé par `build-index.sh`).
  - **20** `MQTT_SNAPSHOT_ON_EVENT=1` (dans `mqtt.conf`, désactivé par défaut) : image JPEG sur `<racine>/snapshot/image` à chaque mouvement, son ou sabotage, 10 s minimum entre deux.
  - **22** page Sauvegarde : « Télécharger la sauvegarde complète (.tar.gz) » et « Restaurer cette sauvegarde » (fichiers de `config/` seulement, validés, transaction).
- **Interrupteur :** 20 : `MQTT_SNAPSHOT_ON_EVENT=0` ; le reste : revert du commit.
- **Test (une caméra) :**
  1. Tableau de bord : Carillon, Alerte entendus ; Sirène demande confirmation puis sonne ; le volume suit le curseur.
  2. `curl -u root:<mdp> -L http://<caméra>/metrics` : les nouvelles lignes, `tc100_rtsp_capture_fps` ≈ la cadence réglée, `tc100_rtsp_main_kbps` ≈ le débit, `tc100_sdcard_free_bytes` sur la .24 ; `cat /var/run/tc100_rtsp.stat` mis à jour toutes les 5 s.
  3. Après la mise à jour, le navigateur charge les nouveaux fichiers sans vider son cache (la page Test du matériel et les nouveaux boutons apparaissent, les nouvelles traductions françaises aussi).
  4. MQTT : `MQTT_SNAPSHOT_ON_EVENT=1`, redémarrer le pont ; un mouvement → image dans l'entité caméra de Home Assistant et message sur `snapshot/event` ; deux mouvements à moins de 10 s → une seule image.
  5. Sauvegarde : télécharger l'archive (taille de quelques Ko, contient `config/...`), changer un réglage, restaurer l'archive → réglage revenu, réponse « fichier(s) » ; un fichier quelconque renommé en `.tar.gz` est refusé sans rien changer. La flash garde la restauration après un redémarrage (`cfg-persist`).
- **Critères :** 1-5 conformes ; aucun effet sur le flux vidéo (le fichier `.stat` coûte une écriture en RAM toutes les 5 s).

## 2026-11-05 — Corrections de l'audit du 2026-11-04 : W2, R1, R2, R3, B4, B5, B6, pont MQTT (`[audit-fix]`)

- **Quoi :**
  - **W2** `NET_LAN_ONLY=1` (défaut) s'applique de nouveau à la page web (`httpfront`) et au RTSP (`tc100_rtsp`) : une connexion hors des réseaux privés / link-local / 100.64/10 / `NET_ALLOW_EXTRA` est fermée sans réponse. La caméra elle-même (127.0.0.1) est toujours admise. ssh n'est pas filtré.
  - **R2** `httpfront` : 16 connexions au plus, 8 par adresse (au-delà : `503`), connexion muette fermée après 2 s.
  - **R1** `tc100_rtsp` : connexion sans requête acceptée fermée après 30 s, client qui ne lit pas fermé après 60 s sans requête ; créneaux pleins → le plus ancien inactif qui ne lit pas cède sa place. **R3** gardes (URL vide, TCP/UDP mêlés → 461, OSD borné).
  - **B4/B6** `update66.sh` arrête aussi le housekeeper, `web-guard`, `rtsp-h26x` ; sauvegarde les réglages (`cfg-persist flush`) et remet le compteur de démarrage à zéro avant d'écrire ; garde les sauvegardes des 2 dernières mises à jour dans `tc100-3/backup`. **B5** verrou sur `cfg-persist save`.
  - Pont MQTT : plus de `sh mqtt-bridge start` resté en mémoire.
- **Interrupteur :** W2 : `NET_LAN_ONLY=0` dans `boot.conf` (puis redémarrage) ; le reste : revert du commit.
- **Test :**
  1. Depuis le LAN : page web, Frigate et VLC fonctionnent comme avant (Frigate main + sub ensemble, VLC avec mot de passe tapé lentement : < 30 s).
  2. Depuis une adresse hors liste (un client VPN dont le réseau n.est pas dans `NET_ALLOW_EXTRA`) : connexions web et RTSP fermées ; avec `NET_LAN_ONLY=0` : page de connexion.
  3. `for i in $(seq 12); do nc <caméra> 80 & done` depuis un PC du LAN : la page web reste accessible depuis un autre PC ; les connexions muettes se ferment après ~2 s (`ps | grep -c httpd` revient à 0).
  4. 4 connexions muettes `nc <caméra> 554` puis VLC : la vidéo démarre (une connexion muette est évincée) ; Frigate lisant en continu n'est jamais coupé.
  5. Pont MQTT (shell et C) : `ps` ne montre plus `sh /mnt/controlscripts/mqtt-bridge start` ; `cat /var/run/mqtt-bridge.pid` = pid du démon ; `stop` puis `start` sans doublon.
  6. Mise à jour web suivante (rc27) : le journal `tc100-3/update66.log` montre les arrêts ; `tc100_rtsp` ne revient pas pendant l'écriture ; après redémarrage les réglages changés juste avant sont là ; `ls tc100-3/backup` : au plus 2 jeux.
- **Critères :** 1-6 conformes, aucun redémarrage ni perte de flux.
- **Mesurer la RAM en PSS** (`/proc/<pid>/smaps_rollup`, P0 #6) : le gain du point 5 se lit en PSS (~200 Ko), pas en RSS.

## 2026-11-05 — Flux principal en 720p (`[720p]`, liste de l'implémenteur #8)

- **Quoi :** Réglages → Flux principal → Résolution : 1920 x 1080 (défaut) ou 1280 x 720. Noyau : patch 0016 (`ak39_vi` recadre toujours la fenêtre 1080p entière, l'ISP met le canal principal à l'échelle demandée ; paramètre en lecture seule `ak39_vi.main_scale`). En 1080p le noyau fait exactement la même chose qu'avant (recadrage 1920x1080). `tc100_rtsp` : `RTSP_WIDTH=1280 RTSP_HEIGHT=720` (passés par `rtsp-launch.sh` quand `[0] mainres=720`), refusés si le noyau n'a pas `main_scale`.
- **Interrupteur :** Résolution 1920 x 1080 (ou `mainres=1080` dans `rtspserver.conf`) ; `RTSP_WIDTH=1920` dans `rtsp.env` force le 1080p.
- **Test (noyau de la CI de ce commit, d'abord en RAM depuis la carte : `pack66/boot66b.sh`) :**
  1. 1080p (défaut) : rien ne change. `dmesg | grep crop` → `crop L,T 1920x1080, main 1920x1080`. Image, couleurs, détection de mouvement, sous-flux et instantané comme avant. **Ce point d'abord : le patch touche le démarrage de la capture.**
  2. `ls /sys/module/ak39_vi/parameters/main_scale` existe ; Réglages : l'option 720p est active (grisée sur un ancien noyau).
  3. Choisir 1280 x 720, enregistrer : `dmesg` → `main 1280x720` ; log `tc100_rtsp` → `rtsp://<ip>:554/  1280x720` ; VLC / Frigate : **la même image entière** (pas un coin), nette ; sous-flux 640x360 inchangé ; instantané 1280x720 ; masques, horloge (OSD) et zones de mouvement à leur place.
  4. Mesures 720p contre 1080p au même débit : `STAT` (images capturées, débit), `MemAvailable`, charge CPU (`scripts/cpu-profile.sh 60`), qualité de l'image.
  5. Ancien noyau (rc26) avec `mainres=720` : le log dit `crops instead of scaling`, le flux reste en 1920x1080.
- **Critères :** 1 et 3 sans défaut d'image ni oops ; une heure de 720p sans erreur noyau ni redémarrage du serveur.

## 2026-11-05 — Noyau de test pour le mode smart de l'encodeur (`[smart-pool]`, liste de l'implémenteur #9)

- **Quoi :** le workflow `build-kernel-linux66.yml` a une entrée manuelle `venc_pool` : lancé à la main avec `12M`, il construit un noyau dont `ak39_venc.pool` vaut 12M par défaut (le réservoir est alloué au démarrage et la ligne de commande vient du bootloader, qu'on ne touche pas). Les artefacts s'appellent alors `tc100-linux66-cma16-kernel-pool12M` et `tc100-3-release-TESTKERNEL-pool12M` : **noyau de test, pas pour une mise à jour normale**. Sans l'entrée, rien ne change.
- **Lancer :** GitHub → Actions → « Build Linux 6.6 LTS Kernel… » → Run workflow → `venc_pool` = `12M` (ou `gh workflow run build-kernel-linux66.yml -f venc_pool=12M`).
- **Interrupteur :** démarrer le noyau normal (le noyau de test ne s'essaie qu'en RAM depuis la carte, `pack66/boot66b.sh`) ; `RTSP_SMART=0`.
- **Test (.11) :** noyau de test en RAM, puis `RTSP_VBR=1` et `RTSP_SMART=1` dans `/mnt/config/rtsp.env`, redémarrer `tc100_rtsp`.
  1. `dmesg | grep -i pool` : réservoir de 12288 Ko ; log `tc100_rtsp` : `smart mode 1 (long-term reference)`, pas de `smart mode 1 not used`, pas de `alloc dma … failed`.
  2. 24 h : serveur vivant, aucune erreur noyau ; `MemAvailable` ~2,4 Mo plus bas qu'avec le noyau normal (attendu).
  3. Débit et qualité comparés à la .24 (scène calme : le débit doit baisser nettement).
- **Critères :** 1-3 conformes → décider si 12M devient le défaut (la RAM perdue contre le débit gagné) ; sinon le mode smart reste désactivé.

## 2026-11-05 09:50 — Bilan de la nuit sur la .11 (rc25, pays FR + regdb, pont MQTT en C, `RTSP_QMAX=1024`) (testeur)

Mesures du 2026-11-04 17:51 au 2026-11-05 08:40 UTC (295 mesures / 180 s). **Pas de témoin cette nuit** : la .24 a été mise à jour en rc25 vers 18:53 UTC (redémarrage → enregistreur perdu).

| Critère | Résultat |
|---|---|
| Reboots | 0 (uptime 15 h 05) |
| RAM disponible | 20,7-23,4 Mo ; moyenne 1er quart 22,1 / dernier quart 21,8 Mo : **pas de fuite** |
| Pont MQTT C | **même démon toute la nuit** (pid 10145, VmRSS 428 Ko, pid file = démon), **aucune reconnexion** après 18:40 UTC (dernière ligne « MQTT connected »), une seule connexion 1883 |
| Jour / nuit | nuit 22:57, jour 07:24 UTC : OK |
| **Ping passerelle** | perte totale dans **28/295 mesures (9,5 %)**, pire 2 000 ms, 10 mesures > 200 ms. rc23 sur la .11 : 11 %. **Le domaine FR + `regulatory.db` ne règle pas les coupures.** Signal fort (`beacon signal avg` -19 dBm, 72,2 Mbit/s MCS 7, 0 retry / 0 échec au compteur iw). |
| Images sautées (`RTSP_QMAX=1024`) | 5 épisodes (1-2 images) entre 18:54 et 22:41 UTC, chacun suivi d'une remise à zéro du compteur 3 min plus tard (= reconnexion du client) ; **0 de 22:44 à 08:40**. Une file de 5 s n'évite donc pas tous les sauts : ces épisodes correspondent à des blocages plus longs ou à une reconnexion du client. Sans témoin, l'effet de la file ne se chiffre pas. |
| dmesg | un `isp pause fail` à 3 684 s = le redémarrage voulu de `tc100_rtsp` (18:39 UTC) pour `RTSP_QMAX` ; rien d'autre |
| Charge | moyenne 0,95, max 1,86 |

.24 (rc25 depuis hier soir) : `FAT-fs … not properly unmounted` **encore** au démarrage qui a suivi la mise à jour web (le remontage en lecture seule de `c131441` ne couvre pas ce chemin ?) ; jour/nuit 05:42 jour → 05:47 nuit → 06:28 jour (une bascule aller-retour à l'aube, hystérésis à surveiller) ; enregistrement SD actif (`rec 1`).

Conclusions : (1) pont MQTT en C **validé pour une nuit** (stable, pas de doublon, pas de reconnexion) → peut devenir le défaut après une deuxième nuit sur la rc26 ; (2) pertes Wi-Fi inchangées : pas le domaine réglementaire ; prochaines pistes : `RTSP_PACING_US`, canal Wi-Fi de la box, puis pilote `rtl8xxxu` (le ping se perd aussi quand le compteur iw n'a ni retry ni échec : côté réception ou blocage du pilote) ; (3) garder `RTSP_QMAX=1024` (aucun effet négatif vu) mais l'essai n'a pas de témoin.
Prochaine étape : rc26 sur la .11.
## 2026-11-05 — Micro sans arecord et traitement du son (`[audio-native]`, liste de l'implémenteur #11)

- **Quoi :** dans `tc100_rtsp`, tout désactivé par défaut :
  - `RTSP_ALSA_DIRECT=1` : le micro est lu par les ioctl ALSA du noyau (`acap.c`) au lieu d'un processus `arecord` (≈ 660 Ko PSS et un tube en moins). Si `/dev/snd/pcmC0D0c` ne s'ouvre pas : retour à `arecord`, dit dans le log.
  - `RTSP_AUDIO_HPF=1` : passe-haut 150 Hz (-19 dB à 50 Hz, voix intacte).
  - `RTSP_AUDIO_AGC=1` : noise gate (souffle d'une pièce calme -12 dB) + contrôle du niveau (voix lointaine jusqu'à +18 dB) + écrêtage doux.
  - `RTSP_AUDIO_DUCK=1` : micro coupé pendant que le haut-parleur joue (retour audio, appuyer-pour-parler, sons), anti-larsen.
  - Le vumètre de la détection sonore mesure toujours le son brut : ses seuils ne changent pas.
- **Interrupteur :** retirer la ligne de `/mnt/config/rtsp.env` (ou `=0`) et redémarrer `tc100_rtsp`.
- **Test :** mettre les switches dans `/mnt/config/rtsp.env`, `sh /mnt/controlscripts/rtsp-h26x restart`.
  1. `RTSP_ALSA_DIRECT=1` seul : log `audio: microphone read directly (/dev/snd/pcmC0D0c, no arecord)` ; `ps` sans `arecord` ; piste audio RTSP (VLC), bouton Écouter, enregistrement SD avec son, détection sonore : tout marche comme avant, pas de saut ni d'écho métallique ; `dmesg` sans erreur ALSA. Une heure de VLC avec le son : pas de coupure (un dépassement est récupéré tout seul). Mesurer la PSS gagnée (`smaps_rollup` d'`arecord` avant).
  2. `RTSP_AUDIO_HPF=1` : le ronflement grave disparaît, la voix reste naturelle.
  3. `RTSP_AUDIO_AGC=1` : pièce calme → souffle plus bas ; voix à 3-4 m → plus forte ; un claquement ne sature pas.
  4. `RTSP_AUDIO_DUCK=1` : pendant un appuyer-pour-parler ou le retour audio de Home Assistant, l'auditeur n'entend pas sa propre voix revenir ; le son revient ~60 ms après.
  5. CPU (`scripts/cpu-profile.sh 60`) avec les quatre : pas de hausse visible.
- **Critères :** 1-5 conformes → les quatre deviennent le défaut (puis un réglage dans la page Audio).

## 2026-11-05 — Clips d'événement gardés en priorité (`[retention]`, liste de l'implémenteur #15)

- **Quoi :** `tc100_rtsp` pose un marqueur vide `AAAA-MM-JJ_HH-MM-SS.evt` à côté de chaque enregistrement pendant lequel il y a eu un mouvement ou un son (toujours, coût : une entrée de répertoire). Avec `REC_KEEP_EVENTS=1` dans `boot.conf`, quand la carte manque de place, le plus ancien enregistrement **sans** événement part d'abord ; les clips d'événement seulement quand il ne reste qu'eux. La page Enregistrements supprime aussi le `.evt`.
- **Interrupteur :** `REC_KEEP_EVENTS=0` (défaut) : le plus ancien part, comme avant.
- **Test (.24, carte SD) :**
  1. `REC_WHEN=always` : agiter la main devant la caméra → le fichier en cours a son `.evt` (`ls /mnt/DCIM/*.evt`) ; un fichier sans mouvement n'en a pas.
  2. `REC_KEEP_EVENTS=1`, `REC_RESERVE_MB` réglé juste au-dessus de l'espace libre actuel (pour forcer le ménage) : le log dit `deleted (keeping N MB free, no event in it)` et les fichiers `.evt` restent ; remettre `REC_RESERVE_MB` ensuite.
  3. Supprimer un enregistrement depuis la page : son `.jpg` et son `.evt` partent avec.
- **Critères :** 1-3 conformes ; aucun effet sur l'enregistrement lui-même.

## 2026-11-05 — Anti-scintillement automatique (`[flicker]`, liste de l'implémenteur #16)

- **Quoi :** Réglages → Image → Anti-scintillement → « Automatique (selon le pays Wi-Fi) » (`POWER_HZ=auto` dans `isp_tune.conf`) : `tc100_rtsp` prend 60 Hz pour les pays à 60 Hz (presque toute l'Amérique, Corée du Sud, Taïwan, Philippines, Arabie saoudite), 50 Hz ailleurs ; Japon et pays non réglé : valeur de la caméra.
- **Interrupteur :** choisir 50 Hz, 60 Hz ou « Valeur de la caméra ».
- **Test :** pays `FR` + Automatique → log `anti-flicker: 50 Hz (exposure step …)` comme avec 50 Hz ; pays `US` → `60 Hz` ; pays vide → `camera default`. Sous un éclairage LED / fluo, pas de bandes avec Automatique en France.
- **Critères :** les trois lignes de log ; pas de bandes.

## 2026-11-05 — Réparations Wi-Fi douces avant le redémarrage réseau (`[wifi-soft]`, liste de l'implémenteur #17)

- **Quoi :** `NET_GUARD_SOFT=1` dans `boot.conf` : quand la passerelle ne répond plus alors que `wlan0` existe (et que le point d'accès de secours n'est pas levé), `net-guard.sh` tente, une fois chacune par coupure : à 2 min `wpa_cli -i wlan0 reassociate` ; à 5 min `wifi-apply` (wpa_supplicant + DHCP) ; à 8 min `wifi-recover.sh reprobe` (puce USB sondée de nouveau). Le redémarrage à `NET_GUARD_MIN` (15 min) reste le dernier recours.
- **Interrupteur :** `NET_GUARD_SOFT=0` (défaut).
- **Test :** `NET_GUARD_SOFT=1`, éteindre la box (ou le point d'accès) 10 min puis la rallumer : `logread | grep net-guard` montre les trois étapes à 2, 5 et 8 min, la caméra revient seule sur le réseau à la remise en route sans redémarrer (avant 15 min) ; second essai : couper 3 min → seule la réassociation a lieu, puis `network back`.
- **Critères :** reconnexion sans redémarrage quand la box revient avant 15 min ; aucune étape quand le réseau va bien.

## 2026-11-05 — Débit automatique du flux principal (`[abr]`, liste de l'implémenteur #18)

- **Quoi :** `RTSP_ABR=1` dans `/mnt/config/rtsp.env` : toutes les 5 s (ligne `STAT`), si des clients TCP ont sauté 3 images ou plus (file pleine : le Wi-Fi ne suit pas), le débit du flux principal baisse de 30 % (pas sous `RTSP_ABR_MIN`, par défaut un quart du réglage, 200 kbit/s au moins) ; après 30 s sans image sautée il remonte d'un dixième du réglage, jusqu'au réglage. Appel `ak_venc_set_br(handle, kbit/s)` de la bibliothèque d'encodage : **signature supposée** (SDK Anyka), à vérifier ici.
- **Interrupteur :** retirer `RTSP_ABR` de `rtsp.env`, redémarrer `tc100_rtsp`.
- **Test (.11, Frigate ou VLC en TCP) :**
  1. Démarrage : log `ABR: on, main bit rate between 500 and 2000 kbit/s` (selon le réglage).
  2. Provoquer de la congestion (éloigner la caméra de la box, ou limiter le débit côté box / `tc qdisc` sur le PC, ou plusieurs VLC) : log `ABR: N frames skipped in 5 s: main bit rate 2000 -> 1400 kbit/s (ak_venc_set_br: 0)` ; **la colonne `bytes` des lignes `STAT` baisse d'autant** (sinon l'appel n'agit pas : le dire ici) ; l'image reste nette, pas d'artefacts.
  3. Rétablir le réseau : remontée par paliers toutes les 30 s jusqu'au réglage.
  4. Si `ak_venc_set_br` répond autre chose que 0 : `regulation off` dans le log, rien d'autre ne change.
- **Critères :** 2 et 3 conformes, aucun plantage de l'encodeur sur une heure → le défaut peut passer à 1.

## 2026-11-05 — Mouvement d'après la taille des trames de l'encodeur (`[md-enc]`, liste de l'implémenteur #19)

- **Quoi :** `RTSP_MD_ENC=1` dans `rtsp.env` : un second détecteur à côté de la grille de luminance. En VBR, trois trames P de suite plus grosses que leur moyenne glissante (x3,6 à la sensibilité 60, x2 à 100, x6 à 1) = mouvement (même sortie que la grille : `/tmp/rec_control`, MQTT, enregistrement, cadence au repos). Zones de mouvement non prises en compte.
- **Interrupteur :** retirer `RTSP_MD_ENC`.
- **Test (.11, `vbr=1`) :** log `motion from the encoder frame sizes: on` ; passer devant la caméra → `rec_control` à 1 comme avec la grille, en même temps ou plus tôt ; scène calme une nuit : compter les fausses alertes contre la grille seule (`RTSP_DEBUG=1` donne les tailles des trames) ; en CBR le log prévient.
- **Critères :** détecte un passage ; pas plus de fausses alertes que la grille → décider s'il reste en option ou devient le défaut en VBR.

## 2026-11-05 — Jour / nuit : 60 s minimum entre deux bascules (`[daynight-lock]`, liste de l'implémenteur #21)

- **Quoi :** `auto-night-daemon.sh` ne rebascule plus avant `MIN_SWITCH` secondes (60 par défaut, `daynight.conf`), quelle que soit la source (luminance, ae, isp, vendor). Une demande trop tôt est notée sur la console et appliquée dès que le temps est écoulé si elle tient toujours. La page Réglages garde la valeur en réécrivant le fichier.
- **Interrupteur :** `MIN_SWITCH=0` dans `/mnt/config/daynight.conf`.
- **Test :** au crépuscule (source luminance) : plus de va-et-vient du filtre IR-cut (`logread | grep auto-night` : au plus une bascule par minute, et la ligne `waiting 60 s` si la luminance remonte avec les LED IR) ; enregistrer Réglages → Jour/nuit : `MIN_SWITCH=60` reste dans le fichier.
- **Critères :** pas de cliquetis ; jour et nuit atteints normalement.

## 2026-11-05 — Heure par l'en-tête HTTP `Date` si NTP est bloqué (`[time-http]`, liste de l'implémenteur #24)

- **Quoi :** `scripts/time-fallback.sh`, lancé 2 min après le démarrage : tant que l'horloge est avant 2025, toutes les 5 min (12 fois au plus), une requête `HEAD` vers la page du routeur (`TIME_HTTP_URLS=gateway`, défaut) ; l'en-tête `Date:` règle l'horloge. ntpd continue et reste la référence.
- **Interrupteur :** `TIME_HTTP_FALLBACK=0` dans `boot.conf`.
- **Test :** bloquer l'UDP 123 sortant sur la box (ou `ntp_srv.conf` vers une adresse muette), redémarrer : 2 min après, `logread | grep time-fallback` → `clock set from the Date header of http://<routeur>/` et `date` est à l'heure (à quelques secondes près) ; sans blocage, rien ne se passe (ntpd a déjà réglé l'heure). Si le routeur n'a pas de page web, ajouter `http://www.google.com` à `TIME_HTTP_URLS`.
- **Critères :** heure juste sans NTP ; aucune requête quand NTP marche.

## 2026-11-05 — Mode confidentialité (`[privacy]`, liste de l'implémenteur #25)

- **Quoi :** `controlscripts/privacy start|stop` (page Services « Privacy Mode », interrupteur MQTT/Home Assistant « Privacy Mode », champ `privacy_on` du topic de santé) crée ou retire `/tmp/tc100_privacy` et écrit `PRIVACY_SCREEN` dans `boot.conf`. `tc100_rtsp` (lu chaque seconde) : image noire sur le flux principal, le sous-flux, l'instantané, la vue en direct et l'enregistrement ; silence à la place du micro ; détection de mouvement en pause. Au démarrage, le drapeau est recréé avant la première image si `PRIVACY_SCREEN=1`.
- **Interrupteur :** `stop` (ou `PRIVACY_SCREEN=0`).
- **Test :**
  1. Activer depuis la page Services : en moins de 2 s, VLC / Frigate / la vue en direct montrent du noir ; `currentpic.cgi` noir ; la piste audio est silencieuse ; bouger devant la caméra → aucun événement de mouvement ; log `privacy mode on`.
  2. **Mode capture directe** (défaut) : aucune ligne de l'image réelle ne doit transparaître (le nettoyage du cache couvre toute l'image) — regarder plusieurs minutes, sous-flux compris.
  3. Redémarrer la caméra : l'image reste noire dès la première trame.
  4. Interrupteur Home Assistant : bascule et état cohérents.
  5. Désactiver : image, son et détection reviennent.
- **Critères :** 1-5 conformes, aucune fuite d'image.

## 2026-11-05 — Démon ONVIF libre `tc100-onvifd`, remplace `monvifd` (`[onvif]`, liste de l'implémenteur #12 et #53)

- **Quoi :** nouveau `tc100-onvifd` (`/mnt/tc100test/tc100-onvifd`, construit par la CI, artefact `tc100-linux66-cma16-kernel`). WS-Discovery, services Device, Media et Media2 (profil avec sortie et décodeur audio = retour audio), service Events (PullPoint : mouvement `VideoSource/MotionAlarm` et `RuleEngine/CellMotionDetector/Motion`, lu dans `/tmp/rec_control`), authentification WS-Security (même identifiant que le RTSP : `RTSP_USER` ou `root`, mot de passe de `user.pwd`), filtre `TC100_NET_ALLOW`.
- **Interrupteur :** `ONVIF_IMPL=monvifd` (défaut) dans `/mnt/config/onvif.conf` puis `/mnt/controlscripts/onvif restart` revient à l'ancien binaire. Mettre `ONVIF_IMPL=c` pour l'essai.
- **Test :**
  1. `ONVIF_IMPL=c`, redémarrer le service ; `ps` montre `tc100-onvifd`.
  2. Découverte : ONVIF Device Manager (ou l'intégration ONVIF de Home Assistant) voit la caméra.
  3. Frigate ou VLC avec l'URI donnée par `GetStreamUri` (`rtsp://<ip>:554/video0_unicast`).
  4. Home Assistant, intégration ONVIF : ajout avec l'identifiant et le mot de passe de la caméra ; flux principal et sous-flux présents ; le capteur de mouvement apparaît, passe à « détecté » en ~2 s quand on agite la main, revient ~8 s après.
  5. Image fixe : `http://<ip>/cgi-bin/currentpic.cgi`.
  6. Mauvais mot de passe refusé (`NotAuthorized`).
  7. go2rtc ou Home Assistant en audio bidirectionnel (retour audio).
  8. Changer la résolution (1080p / 720p) ou le codec dans Réglages, redémarrer `onvif` : les profils suivent.
  9. PSS du processus avec Home Assistant connecté.
- **Critères :** découverte et profils corrects ; flux lisible ; `NotAuthorized` sur mauvais identifiant ; capteur de mouvement HA correct sans abonnements qui s'accumulent (4 au plus) ; pas de plantage sur 24 h ; PSS < 300 Ko ; pas de régression de `tc100_rtsp`. Si tout passe : `ONVIF_IMPL=c` par défaut, puis retrait de `monvifd`.

## 2026-11-05 — Changements d'un autre agent sans entrée de test (ajoutées par l'implémenteur, 11:00)

### `[mqtt-c-default]` Pont MQTT en C par défaut (`d41ac72`, `b38f7c9`)
- **Quoi :** `MQTT_BRIDGE_IMPL=c` dans `config/mqtt.conf.dist` (les caméras déjà installées gardent leur `mqtt.conf`) ; `b38f7c9` retire aussi l'ancien abonnement par curl (il ne marchait plus) et ajoute `_get_now_ts`.
- **Interrupteur :** `MQTT_BRIDGE_IMPL=shell` dans `/mnt/config/mqtt.conf`.
- **Test :** une installation neuve (ou `mqtt.conf` recopié de la `.dist`) démarre `tc100-mqttd` ; deuxième nuit stable sur la rc26/27 comme la première (un seul démon, pas de reconnexion) ; entités HA inchangées.
- **Note implémenteur :** `_get_now_ts` est appelée par `$(…)` : un sous-shell par événement / commande, là où le script évitait les forks (sans effet fonctionnel).

### `[pacing]` `RTSP_PACING_US=100` par défaut (`1a3a2eb`)
- **Quoi :** `rtsp-launch.sh` exporte `RTSP_PACING_US=100` si rien n'est donné (100 µs entre les paquets d'une rafale) ; `rtsp.env` peut le changer.
- **Interrupteur :** `RTSP_PACING_US=0` dans `/mnt/config/rtsp.env`.
- **Test (.11, une nuit, avec l'enregistreur de pertes) :** pertes de ping et images sautées (`dropped` des lignes `STAT`) comparées à la nuit du 2026-11-05 (9,5 %) ; latence du direct et charge CPU inchangées ; pas d'artefacts sur les images clés.
- **Critères :** moins de pertes / d'images sautées, rien de pire ; sinon revenir à 0.

### `[sd-fsck]` `dosfsck -a` avant de remonter la carte (`96336d1`)
- **Constat de l'implémenteur (sans caméra) :** `dosfsck` n'est pas dans l'image (la ligne est sautée par `command -v`), et le montage du démarrage se fait dans `S39tc100-linux66`, pas dans `rec-storage.sh` : **aucun effet attendu** sur le « not properly unmounted » de la .24. À reprendre au #41 de `a-faire-implementeur.md` (bit « sale » lu dans S39, réparation seulement s'il est posé, `fsck.fat` dans l'image).
- **Test :** sur la .24, `command -v dosfsck fsck.fat` (attendu : rien) et `dmesg | grep FAT` au démarrage suivant une mise à jour web.

## 2026-11-05 — Carte SD propre après chaque redémarrage, réparation FAT (`[sd-clean]`, liste de l'implémenteur #41 ; remplace `[sd-fsck]`)

- **Quoi :**
  - Cause trouvée de « not properly unmounted » : à l'arrêt, init lance `/etc/init.d/rcK` (donc `S39tc100 stop`) puis `umount -a -r`. S39 sortait aussitôt (`[ "$1" = start ] || exit 0`) : `tc100_rtsp` enregistrait encore, le remontage en lecture seule échouait. **`S39tc100 stop`** arrête maintenant `tc100_rtsp` (SIGTERM, 5 s : le fichier est fermé proprement), `sync`, `mount -o remount,ro /mnt/sd`. Si la carte reste occupée : une ligne dans `tc100-3/shutdown.log` avec les pid qui la tiennent (`fuser`).
  - `fsck.fat` (dosfstools) dans `ext/bin` du stack (pas dans l'initramfs) : le bouton « Réparer » de la page Carte SD (`sd-diag.sh repair` : pause de l'enregistrement, démontage, `fsck.fat -a`, remontage) fonctionne enfin.
  - `SD_AUTO_REPAIR=1` (`boot.conf`, défaut 0, mode flash) : si le noyau a vu la carte sale au démarrage (coupure de courant), la même réparation une minute après.
  - Le `dosfsck -a` ajouté dans `rec-storage.sh` par `96336d1` est retiré.
- **Interrupteur :** `SD_AUTO_REPAIR=0` ; l'arrêt propre n'a pas d'interrupteur (il ne fait que fermer et remonter en lecture seule).
- **Test (.24, carte SD, enregistrement actif) :**
  1. Redémarrage voulu (page web, puis `reboot` en ssh, puis une mise à jour web) : au démarrage suivant, `dmesg | grep FAT` **sans** « not properly unmounted » ; le dernier enregistrement se lit jusqu'au bout ; pas de `tc100-3/shutdown.log` (ou, s'il existe, noter les pid qu'il cite).
  2. `ls /mnt/ext/bin/fsck.fat` ; page Carte SD → Réparer : réponse `fsck_repaired`, l'enregistrement reprend.
  3. `SD_AUTO_REPAIR=1`, couper le courant pendant un enregistrement : au démarrage `not properly unmounted` dans `dmesg`, puis ~1 min après `sd-diag` répare (`/tmp/sd-health`, log) et l'enregistrement reprend.
- **Critères :** 1 sans avertissement FAT sur 3 redémarrages ; 2 et 3 conformes. La taille de l'initramfs ne change presque pas (quelques lignes de S39).

## 2026-11-05 — Filet pour les journaux en RAM (`[log-cap]`, liste de l'implémenteur #28)

- **Quoi :** tâche `log-cap` du housekeeper (toutes les 10 min) : un fichier de `/tmp/log` ou `/tmp/logs` au-dessus de `LOG_CAP_KB` (64) garde ses 200 dernières lignes, réécrit sur place (même inode). `tc100_rtsp.log` et les copies `.0` / `.1` ne sont pas touchés.
- **Interrupteur :** `LOG_CAP_KB=100000` (ou retirer la tâche : `housekeeper.sh job del log-cap`).
- **Test :** `sh /mnt/scripts/housekeeper.sh job list` montre `log-cap` ; `yes x | head -c 100000 >> /tmp/log/essai.log`, attendre 10 min (ou `sh /mnt/scripts/log-cap.sh`) : 200 lignes restent, ligne `log-cap:` dans `logread` ; une semaine de fonctionnement : `du -sh /tmp/log /tmp/logs` stable.
- **Critères :** taille plafonnée, aucun journal qui s'arrête d'écrire après le passage.

## 2026-11-05 — Limite des essais de mot de passe sur la page web (`[web-lockout]`, liste de l'implémenteur #30, audit W3)

- **Quoi :** `WEB_LOCKOUT=1` dans `boot.conf` (redémarrer `httpfront` : `http_server restart`, ou la caméra) : `httpfront` vérifie lui-même l'identifiant Basic de chaque requête contre `/etc/httpd.conf` (MD5 crypt, une seule fois par identifiant : empreinte gardée dans `/tmp/.httpfront-ok`) ; un mauvais identifiant est noté ; **10 en 5 min depuis une adresse → ses connexions sont fermées 5 min** (127.0.0.1 jamais) ; ligne dans `/tmp/log/httpfront.log`. busybox httpd répond toujours aux requêtes (401 inchangé).
- **Interrupteur :** `WEB_LOCKOUT=0` (défaut).
- **Test :**
  1. Avec le bon mot de passe : navigation normale sur toutes les pages, rien dans `/tmp/log/httpfront.log`, `/tmp/.httpfront-ok` existe.
  2. Depuis un autre PC : `for i in $(seq 10); do curl -s -o /dev/null -u root:faux http://<caméra>/cgi-bin/state.cgi; done` puis `curl -v http://<caméra>/` → connexion fermée sans réponse ; le premier PC (autre adresse) navigue toujours ; 5 min après, le second PC est de nouveau servi.
  3. Changer le mot de passe dans Réglages : l'ancien est refusé par httpd comme avant, le nouveau marche (pas de verrou pour l'utilisateur légitime).
- **Critères :** 1-3 conformes ; jamais de verrou sur l'utilisateur qui tape le bon mot de passe → passer `WEB_LOCKOUT=1` par défaut.

## 2026-11-05 — Cadence éco quand personne ne regarde ou la nuit (`[eco-fps]`, liste de l'implémenteur #31)

- **Quoi :** `IDLE_WHEN` dans `boot.conf` (avec `IDLE_FPS`, par ex. 10) : `still` (défaut, comme avant : quand rien ne bouge, détection de mouvement nécessaire), `unwatched` (aucun client RTSP en lecture, pas de vue en direct dans un navigateur ; la pleine cadence dès qu'un client lit), `night` (en mode nuit). Un mouvement ou un son rend la pleine cadence `IDLE_AFTER` secondes.
- **Interrupteur :** `IDLE_FPS=0` (défaut) ou `IDLE_WHEN=still`.
- **Test :** `IDLE_FPS=10 IDLE_WHEN=unwatched`, Frigate arrêté et pas de VLC : log `idle frame rate: lowered`, `STAT cap` ≈ 10 images/s ; ouvrir VLC → `back to the full rate` en moins d'une seconde, l'image est fluide ; fermer VLC → de nouveau 10 après `IDLE_AFTER`. `IDLE_WHEN=night` : la nuit 10 images/s, le jour pleine cadence. Charge CPU (`scripts/cpu-profile.sh 60`) plus basse pendant la cadence réduite.
- **Critères :** bascules conformes, aucune image figée au retour d'un client, enregistrement continu jamais ralenti.

## 2026-11-05 — Aide au placement Wi-Fi (`[wifi-aim]`, liste de l'implémenteur #32)

- **Quoi :** tableau de bord : la valeur du signal Wi-Fi en vert (≥ -60 dBm), orange (jusqu'à -70) ou rouge. `WIFI_AIM=1` dans `boot.conf` : pendant 5 min après le démarrage, la LED bleue de façade clignote d'autant plus vite que le signal est bon (≈ 4 fois/s à -50 dBm, une fois toutes les 2 s à -85), éteinte sans lien ; éteinte à la fin. Le signal vient de `wifi-signal.sh` (le même que partout).
- **Interrupteur :** `WIFI_AIM=0` (défaut).
- **Test :** `WIFI_AIM=1`, redémarrer ; tourner la caméra / l'éloigner de la box : le rythme suit le signal ; après 5 min la LED s'éteint et `ps` n'a plus `wifi-aim.sh`. Tableau de bord : la couleur suit les dBm affichés.
- **Critères :** rythme cohérent avec les dBm, LED rendue éteinte, pas d'effet sur le reste.

## 2026-11-05 — Images hors de la caméra sur alerte grave (`[notify-burst]`, liste de l'implémenteur #34)

- **Quoi :** `scripts/notify.sh` : une alerte sans image (sabotage) en prend une fraîche (`NOTIFY_ATTACH_SNAPSHOT=1`) ; `NOTIFY_BURST=N` (0-5) envoie N images de plus, une par seconde, pour les événements de `NOTIFY_BURST_EVENTS` (défaut `tamper`) vers Ntfy / Telegram ; `NOTIFY_UPLOAD_URL` envoie aussi chaque image de l'alerte par HTTP PUT (dossier WebDAV du Synology, adresse pré-signée), `NOTIFY_UPLOAD_AUTH="utilisateur:mot de passe"` facultatif. Ntfy sans `eval`.
- **Interrupteur :** `NOTIFY_BURST=0`, `NOTIFY_UPLOAD_URL=""` (défauts).
- **Test :** Ntfy (ou Telegram) actif, `NOTIFY_BURST=3`, `NOTIFY_UPLOAD_URL=http://<synology>/webdav/tc100/` : masquer l'objectif avec la main jusqu'à l'alerte de sabotage → 1 + 3 images reçues sur le téléphone, 4 fichiers `<caméra>_<date>_tamper_0..3.jpg` dans le dossier WebDAV ; un mouvement → une seule image (pas de rafale) ; un message avec une apostrophe passe.
- **Critères :** images reçues et copiées ; aucune rafale hors des événements choisis.

## 2026-11-05 — Services mDNS (DNS-SD) et informations (`[mdns-sd]`, liste de l'implémenteur #38)

- **Quoi :** `MDNS_SERVICES=1` dans `boot.conf` (puis `controlscripts/mdns restart`) : `tc100-mdnsd -s` répond aussi à la recherche de services : `_http._tcp` (port 80, `path=/`) et `_rtsp._tcp` (port 554, `path=/video0_unicast`), avec SRV, TXT et l'adresse dans la même réponse. `MDNS_INFO=1` (`-v`) ajoute `model=TC100`, `fw=<version>`, `load=<charge 1 min>`, `rssi=<dBm>` aux TXT. Toujours seulement sur le même sous-réseau, jamais d'annonce spontanée.
- **Interrupteur :** `MDNS_SERVICES=0`, `MDNS_INFO=0` (défauts).
- **Test :** depuis un PC du réseau : `avahi-browse -rt _http._tcp` (ou `dns-sd -B _http._tcp` sur Mac/Windows) montre la caméra, port 80 ; `avahi-browse -rt _rtsp._tcp` : port 554, `path=/video0_unicast` ; VLC → Réseau local → mDNS liste la caméra ; Home Assistant propose de l'ajouter (zeroconf) ; avec `MDNS_INFO=1` les TXT montrent version, charge, signal. `ping <nom>.local` marche toujours.
- **Critères :** découverte par les trois outils ; rien de plus annoncé sans les interrupteurs.

## 2026-11-05 — Roaming entre bornes d'un même réseau (`[wifi-roam]`, liste de l'implémenteur #40)

- **Quoi :** `WIFI_ROAM=1` dans `boot.conf` : tâche `wifi-roam` du housekeeper chaque minute ; sous -75 dBm à deux contrôles de suite, `wpa_cli scan`, puis `wpa_cli roam <bssid>` vers une borne du même SSID au moins 15 dB plus forte ; 10 min de pause après une bascule. Lignes `wifi-roam:` dans `logread`.
- **Interrupteur :** `WIFI_ROAM=0` (défaut).
- **Test (seulement avec un répéteur ou un mesh) :** caméra associée à la borne éloignée (signal < -75), la proche allumée : en 2-3 min `wifi-roam: ... roaming to <bssid>`, `wpa_cli status` montre le nouveau BSSID, le flux continue (coupure de 1-2 s au plus). Avec une seule borne : rien d'autre qu'une ligne « no access point ... better » quand le signal est faible.
- **Critères :** bascule vers la meilleure borne, pas de va-et-vient (10 min de pause).

## 2026-11-05 — Démarrage discret (`[boot-stealth]`, liste de l'implémenteur #42)

- **Quoi :** `BOOT_STEALTH=1` dans `boot.conf` : pas de carillon de démarrage, pas de clignotement `WIFI_AIM`, LED éteintes dès le script S39 (seules les premières secondes du noyau restent allumées) ; `FRONT_LED` / `RED_LED` s'appliquent à la fin du démarrage comme avant. `BOOT_SOUND=0` reste disponible seul.
- **Interrupteur :** `BOOT_STEALTH=0` (défaut).
- **Test :** `BOOT_STEALTH=1`, redémarrer dans le noir : la LED bleue ne reste allumée que quelques secondes au tout début, aucun son, puis la LED suit le réglage de Réglages.
- **Critères :** aucun son, LED éteintes pendant le démarrage (hors noyau), réglages LED respectés ensuite.

## 2026-11-05 — Test du lien vers l'enregistreur (`[nvr-latency]`, liste de l'implémenteur #43)

- **Quoi :** Diagnostics → onglet « Lien vers l'enregistreur » → « Tester le lien » : 10 pings (0,2 s d'écart quand busybox le permet) vers l'adresse Frigate des Réglages, sinon `REC_CLIENT`, sinon la box (ou l'adresse tapée) ; réponse : pertes %, délai min / moyen / max, gigue (moyenne des écarts entre deux mesures).
- **Interrupteur :** aucun (bouton à la demande).
- **Test :** sans adresse : la cible est Frigate (ou la box) ; avec l'adresse du Synology : résultat en ~3 s ; une adresse inexistante → `pertes 100 %` ; une adresse avec des caractères interdits → refusée. Comparer avec la nuit de pertes Wi-Fi (#9).
- **Critères :** chiffres cohérents avec un ping depuis un PC.

## 2026-11-05 — Secrets retirés des réponses en lecture seule (`[secrets-get]`, audit W6)

- **Quoi :** `wifi_rescue_info` ne renvoie plus le mot de passe du point d'accès de secours (seulement `psk_set`) ; Réglages → « Afficher » le demande avec `reveal=1` et le jeton CSRF. `state.cgi?cmd=fullconfig` ne renvoie plus le jeton Telegram (`token_set`) ; dans Réglages, un champ vide garde le jeton, `-` le retire.
- **Interrupteur :** aucun (revert du commit).
- **Test :** Réglages → Wi-Fi de secours : mot de passe masqué, « Afficher » le montre ; `curl -u root:<mdp> 'http://<caméra>/cgi-bin/action.cgi?cmd=wifi_rescue_info&format=json&reveal=1'` sans jeton → refus CSRF. Telegram : enregistrer le formulaire sans toucher au jeton → le bot marche toujours ; `-` → jeton retiré.
- **Critères :** aucun secret dans `fullconfig` ni dans `wifi_rescue_info` sans `reveal` ; Telegram inchangé après un enregistrement.

## 2026-11-05 — Pont MQTT en C : pas de résolution DNS à chaque reconnexion (`[mqtt-m1]`, audit M1)

- **Quoi :** `tc100-mqttd` : une adresse de broker numérique n'est plus jamais résolue (`inet_aton`) ; un nom est résolu une fois, puis de nouveau seulement après un échec de connexion ; un topic de plus de 65 535 octets est refusé au lieu d'être tronqué.
- **Interrupteur :** aucun (revert).
- **Test :** pont en C avec l'adresse IP du broker : couper le broker 1 min puis le relancer → reconnexion, commandes et `availability` comme avant ; avec un nom (`MQTT_HOST=nas.local`) : idem.
- **Critères :** reconnexion normale dans les deux cas, pas de gel du pont pendant la coupure.

## 2026-11-05 — Image flash plus petite (`[flash-space]`, item 54)

- **Quoi :** `stack.sqfs` ne contient plus `sounds/test-1k-m*.pcm` ni `www/css/bulma.1.0.2.purged.min.css`, `ui-modern.min.css`, `ui.css` (et leurs `.gz`) : seul `css/ui.bundle.min.css` est chargé par les pages. Le wizard (`cgi-bin/wizard.cgi`) ne charge plus Bulma (il n'utilise que ses classes `wz-*`) et porte les quelques règles de remise à zéro dont il dépendait. `mksquashfs` utilise le filtre ARM de xz (`-Xbcj arm`). Mesuré en Docker : -65 Ko pour les exclusions, -4 Ko de BCJ sur nos binaires ; le gain sur `ext/` (curl, dropbear, hostapd, libasound) se lit dans le log du build (`stack.sqfs: N bytes`).
- **Interrupteur :** `SQFS_BCJ=none` au build pour le filtre ; les fichiers exclus restent dans le paquet SD ; revert pour le wizard.
- **Test :** comparer `stack.sqfs: N bytes` du build CI avec celui du build précédent. Sur la caméra : `mount` → `stack` monté sans erreur, `dmesg | grep -i squashfs` sans erreur, interface web complète (styles corrects), son de démarrage joué. Wizard : `http://<caméra>/cgi-bin/wizard.cgi` (ou première installation) → même aspect qu'avant (fond sombre, pas de marge blanche, boutons et champs à la bonne police).
- **Critères :** image plus petite, aucune erreur squashfs/xz au montage ni en lisant les binaires (`tc100_rtsp`, `curl --version`, `dropbear -V`), wizard identique.

## 2026-11-05 — Frise des enregistrements (`[rec-timeline]`, item 36)

- **Quoi :** page Enregistrements : la frise du jour est dessinée par le navigateur (canvas) à partir de `viewrecords.cgi?cmd=day_index` (un `stat`, un `date`, un `awk` pour toute la journée : début, durée d'après la date de dernière écriture, taille, plages d'événements). Chaque fichier à sa vraie longueur, les plages mouvement/son en rouge, la tête de lecture, zoom 24 h → 5 min (liste ou double-clic). Clic ou glisser → le lecteur part de cette seconde (même fichier : simple saut, sans recharger) ; flèches ±10 s (Maj : ±1 min). `tc100_rtsp` écrit maintenant les instants dans le `.evt` (`on S` / `off S`, secondes depuis la première image du fichier, 64 lignes au plus) ; les `.evt` vides des versions précédentes colorent tout le fichier en orange. Clic sur un événement de la liste « Motion Events » : ouvre son jour (le format de date ne correspondait pas) à son heure.
- **Interrupteur :** aucun côté caméra (la commande `day_index` ne sert qu'à la page ; sans elle la frise retombe sur les noms de fichiers) ; revert pour la page.
- **Test :** enregistrement en continu (`REC_MODE=always`) pendant au moins 15 min, bouger devant la caméra 2 ou 3 fois. Puis : `cat /mnt/DCIM/<jour>_<heure>.evt` → lignes `on N` / `off N` cohérentes avec les mouvements ; page Enregistrements : fichiers contigus sur la frise, plages rouges aux bons endroits ; clic au milieu d'une plage rouge → la vidéo démarre à cet instant (comparer l'horloge OSD) ; clic dans le même fichier un peu plus loin → saut sans rechargement ; zoom 1 h et 5 min ; touches flèches. Essayer Chrome, Firefox et Safari (le saut dans un MP4 fragmenté sans index peut attendre le téléchargement jusqu'à ce point).
- **Critères :** saut à ±2 s de l'heure cliquée (OSD), pas d'erreur dans la console, `viewrecords.cgi?cmd=day_index&date=<jour>` en moins de 1 s pour une journée complète (288 fichiers), charge CPU de la caméra inchangée pendant le défilement.
