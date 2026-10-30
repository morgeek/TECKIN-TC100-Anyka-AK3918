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

### Next build: 3.0.1-rc8 — stable: only what passed on rc7, and the two bugs fixed (2026-10-31)

The owner asks for a stable rc8 made of verified improvements. Nothing new or untested goes in; every change has a
switch back to the rc7 behaviour.

**Implementer's answers to the tester's priority list (night 2):**
1. **F-05 octal counter: fixed** (`scripts/log-persist.sh` strips the leading zeros; host test with `.bootcount`
   = `0007`, `0008`, `0009`, `0099`, `0000`). After the install on IPCAM2 the stuck `.bootcount` (`0009`) needs no
   `rm`: the next boot makes `boot-0010`.
2. **MQTT:** the refusal code is surfaced (badge "MQTT: login refused" for CONNACK 4 / 5, status line "login refused by
   the broker", `mqtt_refused` in the status JSON). **The longer back-off is not in rc8:** the bridge already backs off
   (up to `MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS`), its cost measured 0.2 % of a core with a refused login, and a change to
   the listener's reconnect loop is not a "verified" change. Later, if a refused login turns out to bother the broker.
3. **Made default:** `RTSP_ISPOSD`, `RTSP_ISPMASK` (`=0` restores the CPU path; a refusal by the ISP falls back to the
   CPU by itself) and `ak39_vi.slots=3` (kernel default; `ak39_vi.slots=4` = rc7). The camera's `rtsp.env` does not
   need these lines any more.
4. **Left opt-in:** `RTSP_UDPMMSG`, `RTSP_UDPSG` (no gain measured, so no reason to switch), `otg_hs.fifo32`,
   `rtl8xxxu.dma_aggregation`, `RTSP_FRAMECOPY=0`.
5. **`amixer -c 0`: fixed** by shipping `cards/aliases.conf` in `ext/share/alsa` (build-stack checks it is there).
   **Speaker silent: not touched in rc8** (no verified fix; the codec path needs a test of its own, see B-01 notes).
6. **25 fps as the default: not in rc8.** It costs no CPU (P-04), but the picture quality at 25 fps with the same
   bit rate was not looked at. The owner can choose 25 in Streams & audio; a default change waits for a day-time look.
7. **HW-02 test 2 (`ak39_venc.pool=9600K`): the owner says go, in rc8** (card kernel only, built by CI with the parameter in
   its own command line: no U-Boot prompt; kept if it passes, dropped if not). To make it a one-parameter test, `tc100_rtsp` leaves out the start-of-pool
   guard by itself when the pool is smaller than 12 MiB (log `encoder pool: N bytes (ak39_venc.pool), no guard at
   its start`; `RTSP_POOLPAD=<bytes>` still forces one). With the default 12 MiB pool nothing changes. Steps in R8-02.

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

### R8-02 HW-02 test 2 on rc8: a 9.4 MiB encoder pool (`ak39_venc.pool=9600K`, card boot) — `to test` (owner's go 2026-10-31)
- **Why this size:** the encoders use 8866880 bytes with the main stream in H.265 and the sub-stream in H.264 (HW-01b,
  no guard); 9600K = 9830400 bytes leaves about 0.96 MB. **Gain expected: about 2.6 MB more `MemAvailable`** on top of
  `slots=3`. Never measured: the pool use with the **main stream in H.264**, the riskiest case.
- **No U-Boot prompt (the owner's rule after night 2):** the rc8 CI run also builds a **card test kernel with the
  parameter in its own command line** (`CONFIG_CMDLINE="ak39_venc.pool=9600K"`, `CONFIG_CMDLINE_EXTEND`: appended by
  the kernel to what U-Boot passes, so the 256-character limit does not apply). Artifact
  **`tc100-linux66-hw02-pool9600k`**: `c66-hw02-pool9600k.img`, its `System.map` / `.config`, `README-HW02.txt`.
- **Safety:** nothing is written to the flash or to the U-Boot environment; only a file on the SD card changes. A pool
  too small only means no video until the card kernel is put back. After a panic the camera boots its flash firmware.
- **Test, after R8-01 (rc8 kernel and initramfs on the card, rc8 in the flash):**
  1. On the card: rename `tc100test/c66.img` to `tc100test/c66-rc8.img` (rename, never delete), copy
     `c66-hw02-pool9600k.img` as `tc100test/c66.img` (check its md5 against `md5sums.txt`), `reboot`.
     `/proc/cmdline` holds the full initrd size **and ends with** `ak39_venc.pool=9600K`;
     `cat /sys/module/ak39_venc/parameters/pool` = `9600K`.
  2. dmesg: `video encoder: ... pool 9600 KiB at 0x81800000 (CMA)`, no `cannot map the ... pool`, `/dev/uio0` present.
  3. `tc100_rtsp.log`: `encoder pool: 9830400 bytes (ak39_venc.pool), no guard at its start`, both encoders `open`,
     and the `pool used ..., free ...` lines: write down **used** and **free** (main H.265 + sub H.264).
  4. `MemAvailable` and `MemFree` at 2-4 min after boot, compared with R8-01 step 1 (same build, default pool).
  5. Main stream in **H.264** (Settings, Streams & audio), then back to H.265: both encoders reopen (`open`, not
     `OPEN FAILED`), write down **used** / **free** in H.264 too. Then switch the sub-stream codec if the UI offers it.
  6. Snapshot (web picture), recording of the sub-stream if Frigate records it, 25 fps for 5 minutes.
  7. **One hour** of streaming with Frigate: `dropped` like R8-01 step 6, the main stream bytes per 5 s stay about
     1 MB (watch for the HW-01 failure: a fall to ~5 KB per 5 s), no `ak_venc_open failed`, no Oops / OOM.
- **Pass:** steps 1-7, smallest **free** at least 256 KB in every codec combination. **Then** (rc9): 9600K (or the
  largest measured **used** + 0.75 MB, rounded up to 64 KB) becomes the driver's default in patch 0015, so the
  flash boot gets it without any U-Boot change.
- **Fail:** any `OPEN FAILED` / `ak_venc_open failed`, the main stream dying, or a free below 256 KB: write down the
  numbers, rename `tc100test/c66-rc8.img` back to `tc100test/c66.img` and reboot; the idea is dropped (or retried
  once at `10240K` if only the margin was short).

### Next build: 3.0.1-rc7 — the owner asks for everything to be tried (2026-10-30 night)

rc7 = rc6 plus the LED / IR / speaker / reset pin fix (LED-01), the tester's accepted proposals and the remaining
optimisations. Nothing in it touches U-Boot, `boot`, `mac` or `env`. The initramfs changes (S50 scripts, profile.d)
come with the kernel package.

**Order** (each step only if the previous one is fine; write the result under each entry):
1. **Card boot first** (rule): `c66.img` of rc7, nothing written. Check `/proc/cmdline`, Wi-Fi, 15 fps, and run
   `sh /mnt/scripts/perf-baseline.sh 60` (P-06) once with one client. Keep its output as the rc7 reference.
2. **LED-01:** the Settings LED switches, then the IR LED, the speaker and the reset button (they were on the same
   wrongly muxed pins).
3. **Audio:** B-01 / B-02 checks 2-4: microphone, speaker, `amixer`.
4. **Access:** S-01. Port 22 open and port 23 closed after boot, Services ssh / telnet, the housekeeper restarter
   (`kill -9`), the rescue telnet.
5. **Then the flash** (`update66.sh`, settings kept) and the same quick checks.
6. **Video, one change at a time** with `perf-baseline.sh` before / after:
   - O-05;
   - P-09: `RTSP_UDPSG=1` with H.265, then the 384 KB queues;
   - P-08: `RTSP_VBR=1` on a still scene;
   - P-04: 20 and 25 fps, the owner's question;
   - P-02: `ak39_vi.slots=3`, from the card only.
7. **Web:** W-01 and UI-22 (a browser on the LAN), O-04, O-06.
8. **Network:** P-01 (ONVIF discovery), P-07 (`rtl8xxxu.dma_aggregation=1` from the card).
9. **The rest of the queue in its order:** HW-02 test 2, HW-03 `fifo32=1`, HW-04 to HW-08, F-01 to F-06, then the
   overnight soak of rc7.

Anything that fails: status `failed`, the serial lines, and the switch that brings back the old behaviour (every
change has one, listed in its entry).

### Tester's answer to the implementer's proposals (2026-10-30 evening; the owner has the last word, U-Boot changes need his agreement)

Order proposed: 2, 7, 9, then 5, then 8 behind switches, then 6. On hold: 3. Declined: `cma=16M`, 1, 4.
- **`cma=16M`: declined as is.** On IPCAM2 with video running, `CmaFree` was 1.5 MB of the 18 MB area (the 4
  capture buffers alone are about 13.8 MB): 16 MB would leave the capture about 0.5 MB short. The gain is 2 MB, not
  4. It also needs `saveenv` on every camera (against plug and play), and 3D-NR needs that area. Better: try **3
  capture buffers instead of 4** (about 3.4 MB of CMA freed, no U-Boot change), measured with the `dropped` counter.
- **1. wpa_supplicant out of the RAM: declined.** Wi-Fi is the only way in; 0.78 MB is not worth a camera that
  cannot be reached without a serial port, now that 5 MB were gained.
- **2. Restart `housekeeper.sh`: yes, first.** Under `service-watchdog.sh` like the other services; the hardware
  watchdog only as the last resort.
- **3. Drop the 3.4 MB guard: on hold until HW-02 test 2.** Free while the pool stays 12 MiB; if the pool shrinks,
  remove the guard first and soak with `RTSP_POOLPAD=0`.
- **4. Merge `cfg-persist` into the housekeeper: declined.** It writes the settings to the flash: it stays isolated
  from a loop that may crash. 150-300 KB is small.
- **5. UI (one front LED choice, `statusline` CGI, one stylesheet): yes.** The LED choice waits for LED-01 (no GPIO
  drives the visible LED today).
- **6. telnet / SSH under the Services page: yes. telnet off by default** (password in clear), **SSH on by default**.
  The tester does not use telnet (serial console).
- **7. IP multicast for ONVIF discovery: yes** (plug and play with Home Assistant / NVRs); the tester checks discovery.
- **8. Video (two copies fewer per UDP RTP packet, 384 KB client queues, browser video into the send buffer): yes,
  each behind a switch.** 384 KB is about 2 s at 1.6 Mbit/s: compared on the real Wi-Fi with `dropped`; UDP picture
  checked with a real client.
- **9. Buildroot build cache in the CI: yes**, invalidated when the Buildroot config changes.

### LED-01 Front LED stays red, the Settings LED switches do nothing visible — `passed` (owner's report, first)
- **What:** the whole software path checks out, so the fault is at the GPIO:
  - Settings > System "LEDs" posts `set_led_config`.
  - That writes `FRONT_LED` / `RED_LED` to boot.conf and runs `controlscripts/front-led` / `red-led`.
  - Those call `front_led` / `red_led` in common_functions.sh, which write `/sys/class/leds/blue|red/brightness`.
  - autorun applies both again at boot.
  - The red LED is `gpios = <&gpio1 15 0>` = GPIO 47, active high, in the device tree (patch 0009), with
    `default-state = "off"`. It still shines red, so either the LED is active-low, or GPIO 47 is not muxed as a GPIO
    (the 6.6 kernel has no pinctrl: it keeps what U-Boot left).
- **Test** (serial or ssh, look at the LED after each line; GPIO bank 1 registers: DIR 0x20170004, OUT 0x20170010,
  bit 15 = 0x8000):
  ```
  cat /sys/class/leds/red/brightness /sys/class/leds/blue/brightness
  devmem 0x20170004; devmem 0x20170010
  echo 1 > /sys/class/leds/red/brightness; devmem 0x20170010     # LED?
  echo 0 > /sys/class/leds/red/brightness; devmem 0x20170010     # LED?
  echo 1 > /sys/class/leds/blue/brightness; echo 0 > /sys/class/leds/blue/brightness   # blue on, then off?
  ```
- **Reading it** (write the case here; the implementer then fixes patch 0009 and the scripts):
  - (a) Red goes **off with 1** and on with 0: the LED is active-low. Fix: `<&gpio1 15 1>` (GPIO_ACTIVE_LOW).
  - (b) Red does not change while bit 15 of OUT toggles, and DIR bit 15 is 1: GPIO 47 is not muxed as a GPIO, or the
    red LED is on another pin. Fix: set the sharepin bit in the board code, or find the pin (stock 3.4 board table).
  - (c) Red goes off with 0 as expected: something lights it again later. `grep -rn red_led` of the running scripts;
    watch it after boot.
  - Also say whether blue works, and which colour(s) the front LED has (red only, or red + blue).

- **Result 2026-10-30 19:45, IPCAM2, 563dbff, owner looking at the LED: case (b) for both colours.** At the start:
  `red` 0, `blue` 1 (boot.conf FRONT_LED=1, RED_LED=0), the front LED shows **red**. Bank 0: DIR 0x0008e800,
  OUT 0x00008800 (bit 15 = blue, output, high). Bank 1: DIR 0x00008000, OUT 0x00000000 (bit 15 = GPIO 47, output).
  - `echo 1 > red/brightness`: OUT bank 1 becomes 0x00008000; LED **still red, no change**.
  - red 0 and blue 0: LED **still red**.
  - blue 1 again (bank 0 OUT bit 15 = 1): LED **still red** (no blue, no violet).
  So neither GPIO 15 nor GPIO 47 changes the visible LED, although both are outputs and their OUT bits toggle: the
  pins are not muxed as GPIO (the 6.6 kernel keeps U-Boot's sharepin setting), or the front LED is wired elsewhere
  (the red seen may be a plain power LED, or a pin outside the board table). The owner does not know whether this
  camera ever showed blue. Device tree as running: led-blue = bank 0 pin 15, led-ir = bank 0 pin 19, led-red = bank 1
  pin 15. Not tried: blind toggling of other pins (IR-cut 80/81, speaker 14 and the sensor pins are on the same
  banks). **Asked of the implementer:** the sharepin bits for GPIO 15 and 47 from the stock 3.4 board code (the ISP
  log shows `share 74=4200071c 78=00000000 7c=01450525`), and a one-minute test that sets them.
- **Implementer's answer (2026-10-30 night): found, our own device tree did it.**
  - **Where:** at each stream start, `vi_power_up()` (patch 0006) ORs `anyka,sharepin-or` into SYSCTRL
    0x74 / 0x78 / 0x7c / 0x80. Patch 0009 held `<0x40000710 0x0 0x01450525 0x100>`, copied from the OpenIPC 4.4
    kernel.
  - **What those values did:** besides the sensor clock pad (pin 3) and I2C (27, 28), they mux the **Ethernet RMII**
    pads that the OpenIPC device tree enables. Its `ethernet_pins_rmii` = pins 10 11 13 14 15 19 20 23 24 47,
    function 1.
  - **Decoded with the EV33x sharepin table** (OpenIPC/linux `drivers/pinctrl/anyka/ak_ev330_pinctrl.c`, the driver
    of this SoC; field value 0 = GPIO):
    - 0x7c = 0x01450525 sets exactly pins 10, 11, 13, 14, 15, 19, 20, 23 and 24 to function 1.
    - Bit 10 of 0x74 sets pin 47 to OPCLK.
    - 0x80 bit 8 is the pull bit of pin 47.
  - **So once the video starts, these pins leave the GPIO block:** blue LED 15 (MII_TXD1), red LED 47 (OPCLK), and
    very likely the **IR LED 19, the speaker amplifier 14 and the reset button 10** too.
  - **Fix (next build):** `anyka,sharepin-or = <0x40000310 0x0 0x0 0x0>`, which keeps pin 3, 27 and 28 only. Checked:
    the series applies, the kernel builds, and the `.dtb` holds the new value.
- **Check now, on the running build** (nothing written; undone by the next stream restart):
  ```
  devmem 0x08000074 32 0x4200031c      # was 0x4200071c: pin 47 back to GPIO
  devmem 0x0800007c 32 0x00000000      # was 0x01450525: pins 10 11 13 14 15 19 20 23 24 back to GPIO
  echo 0 > /sys/class/leds/red/brightness;  echo 1 > /sys/class/leds/red/brightness;  echo 0 > /sys/class/leds/red/brightness
  echo 1 > /sys/class/leds/blue/brightness; echo 0 > /sys/class/leds/blue/brightness
  ```
  Expected: red and blue follow, and the video keeps running (it does not use these pins). If the picture stops,
  restore `0x4200071c` / `0x01450525` and write down which write did it.
- **Then, with the next build:**
  1. The Settings LED switches work.
  2. IR LED: `setconf -k g -v 1` / `0` lights / darkens the IR LEDs at night (look with a phone camera).
  3. Speaker: Talk or the sound test is heard (amplifier pin 14).
  4. Reset button: held 3 s gives the button-watch log line; UI-20 (held 20 s) can then be tested.
  5. The video starts as before.

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

### HW-01b Start of the encoder pool: guard and diagnosis — `passed`
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
- **Result 2026-10-30 evening, IPCAM2, build 563dbff (CI run 41089089376), installed in the flash of IPCAM2 (.11) with update66.sh, settings kept:** step 1 (default): `encoder pool: 3456000-byte guard at
  its start (phys 0x81800000)`, about 1.0 MB per 5 s, **no `pool guard:` report**. Step 2 (`RTSP_POOLPAD=0`, pool
  used 7946976 / 8866880 = the failing HW-01 layout): **streams normally for 5 min** (59 STAT lines, lowest 0.90 MB
  per 5 s after the first). And the bde3887 CI binary that failed this morning (md5 c66a4edf...) also streams
  normally on this kernel (15 STAT lines, 0.86-1.03 MB). **The HW-01 failure is not reproduced**: it was not the
  pool layout of `tc100_rtsp` alone. It happened on the bde3887 kernel, in the session that ended with the Wi-Fi
  chip stuck (HW-03), so a degraded USB / system state or that kernel are the remaining suspects. Steps 3-4 not run
  (nothing to size). Keeping the guard costs nothing while the pool is not shrunk (HW-02 test 2); the implementer
  may drop it later or keep it as a detector.

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

### HW-03 USB host: FIFO data in 32-bit words (kernel patch 0013, `otg_hs.fifo32=1`) — `to test`
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
- **Result 2026-10-30 evening, IPCAM2, after a power cut:** Wi-Fi back. 3 cycles "563dbff kernel booted from the
  card with a stream, then `reboot` into the rc5 kernel": Wi-Fi associates every time (about 16.5 s). Then 563dbff
  installed in the flash, 3 warm `reboot`s with the stream running: associates every time (15.5 s). **Not
  reproduced** (0 of 6). The fifo32=1 measurement itself is still to do: status back to `to test`.

### HW-04 Privacy masks by the ISP (`RTSP_ISPMASK=1`) — `passed` (rc7 night 2), the default since rc8 (`RTSP_ISPMASK=0` = CPU)
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

### HW-06 Exposure cap by the ISP (Image page, `EXPOSURE_MAX_PCT`) — `passed` (rc7 night 2)
- **What:** the Exposure time cap slider is back. `AK_ISP_SET_AE` `exp_time_max` = the tuning file's value × percent,
  never below `exp_time_min` (the 2.x firmware did the same through the vendor library).
- **Test:** in low light, 100 % (off) then 30 %: log `exposure cap: 30 % (exp_time_max A -> B)`; moving things blur less,
  the picture is darker. `/tmp/cam_ae` (HW-08) shows `exp_time` not above B.

### HW-07 Clock by the ISP OSD (`RTSP_ISPOSD=1`, kernel patch 0014) — `passed` (rc7 night 2), the default since rc8 (`RTSP_ISPOSD=0` = CPU)
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

### F-05 Logs kept across reboots (`scripts/log-persist.sh`, on by default) — `failed` on rc7 (octal boot counter), fixed in rc8: `to test`
- **What:** dmesg, syslog, `tc100_rtsp.log` and tails of the other logs to `/mnt/sd/logs/boot-NNNN` 120 s after the
  start, every 10 min and before a reboot from the web UI (`reboot-tracker.sh intent`); last 5 boots, about 2 MB
  each; skipped when the card is not vfat/exfat, ejected / recording paused, unhealthy or under 64 MB free. A bare
  `reboot` in a shell and a panic keep only the last 10-minute copy. Logs page: "Logs of previous boots".
- **Test:** files appear after about 2 min; reboot from the UI gives a `why=shutdown` save and `boot-0002`; nothing
  written while ejected; card writes over a day are small. **Off:** `LOG_PERSIST=0`.
- **Result 2026-10-30, IPCAM2, 563dbff:** `/mnt/sd/logs/boot-0001` and `boot-0002` created about 120 s after the
  start, each with dmesg.log, meta.txt, other.log, syslog.log, tc100_rtsp.log. Boots rebooted before 120 s leave no
  folder (as described). UI reboot (`why=shutdown`) and the eject case not tried yet.

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

### P-02 Three capture buffers instead of four (`ak39_vi.slots=3`) — `passed` (rc7), the default since rc8 (`ak39_vi.slots=4` = before)
- **What:** a module parameter, default 4 (nothing changes without it). With `slots=3` one 1080p capture buffer
  (~3.4 MB of CMA) is not allocated. The ISP's fourth slot stays unarmed: this is the same state as when
  `tc100_rtsp` holds a buffer.
- **Test (from the card only, kernel command line):**
  1. Boot `c66.img` with `ak39_vi.slots=3` added through `EXTRA` of `pack66/boot66b.sh`. Keep `/proc/cmdline` under
     256 characters.
  2. `cat /sys/module/ak39_vi/parameters/slots` gives 3.
  3. `grep -i cma /proc/meminfo`: CmaFree about 3.4 MB higher than with 4.
  4. 15 fps in STAT (`cap` 75 per 5 s), `dropped` 0, the kernel's `stream stopped: N frames, M skipped irqs` with M
     small, over 30 minutes.
  5. Then the same at 25 fps (P-04).
- **Pass:** no frame lost against 4 buffers. Then it can become the default through the device tree; that is the
  owner's decision. No U-Boot change is needed for the test.

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

### P-07 Wi-Fi: RX aggregation and USB interrupts — `to test` (measurement only)
- **What:** `rtl8xxxu.dma_aggregation=1` on the kernel command line (from the card, `EXTRA` of `boot66b.sh`); no code
  change. The driver has no power-save path for this chip, so there is nothing to switch there.
- **Test:** `perf-baseline.sh 60` without a client, then with one, then the same with `dma_aggregation=1`. Look at
  interrupts/s of the USB host, and softirq. Throughput: VLC stays smooth.

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

### Other suggestions of 2026-10-30, not taken now (reasons)
- **Clock gating of unused blocks (Ethernet MAC, extra UART):** no verified clock register map yet. A wrong bit can
  stop the SPI flash, USB or SD; the only gain is heat. The RMII pads are no longer muxed (LED-01 fix).
- **SPI flash DMA / quad read:** it changes the driver that also writes the flash (kernel, initrd, stack, settings).
  Not without a long write/read-back campaign; boot time is not a problem today.
- **USB DMA:** the largest CPU gain left, but the vendor code is unsafe as is (HW-03 notes). Last, after HW-03 fifo32,
  with a long soak.
- **Motion detection from ISP statistics:** the software detector reads 2,304 bytes 4 times a second (about
  0.4 ms/s): no measurable gain.
- **Thumb build of non-critical programs:** busybox would shrink by about 25 % (~170 KB of the RAM image). But it is
  the init and the shell of the rescue path. A later trial on the card only (busybox `CONFIG_EXTRA_CFLAGS="-mthumb"`),
  not in this build.
- **ARMv5TE DSP instructions, PLD:**
  - The audit found no soft-float or division in a hot loop: the sound level log is ~30 µs per 0.25 s, and G.711 is
    a table.
  - The remaining frame copy reads uncached memory, where PLD does nothing.
- **ftrace / perf in the kernel:**
  - The ARM926 has no performance counters, so perf only has software events.
  - The function tracer costs RAM and adds an mcount call to every function.
  - Possible later as a separate debug kernel artifact, never the release. `perf-baseline.sh` covers the
    per-build comparison meanwhile.

Not done (listed for later): one front LED choice in Settings (waits for LED-01 on the new build).
