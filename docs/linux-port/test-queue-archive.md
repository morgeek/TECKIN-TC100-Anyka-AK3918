# Test queue archive: finished entries

Entries moved out of [test-queue.md](test-queue.md) once finished (passed and made the default, superseded,
abandoned, or a build note with nothing left to test), in their original order. Each block keeps its text as it
was; "From:" names the section it came from. Open entries stay in test-queue.md.


## From: Tester report to the implementers (2026-10-30, IPCAM2 / .11 on the serial console)

### URGENT DIAG-01 Frigate gets no picture and the web page does not show since rc11 (owner, 2026-10-31) — `found: W-NET (the Wi-Fi chip did not power on after warm reboots); answered in rc14`
The owner: since rc11 Frigate receives no picture and the web interface is not visible. The tester saw `clients 0` in
the STAT lines since the morning reboots. Nothing in the rc11 code explains it on paper (no web or network change;
the new ISP calls print nothing), so the camera must tell. **Read only, nothing written** (except the restart in 4).
1. Network: `ip addr show wlan0` (address, same as before?), `iw dev wlan0 link`, `ip route`, `cat /etc/resolv.conf`.
   From the Mac: `ping -c3 <ip>`, `curl -sI http://<ip>/` (HTTP code), `curl -sI http://<ip>/index.html`.
2. Services: `ps | grep -E 'httpfront|httpd|tc100_rtsp|dropbear|mqtt'`, `netstat -tln` (ports 80 and 554 listening?),
   `wget -qO- http://127.0.0.1/ | head -c 300` on the camera, `cat /var/run/v4l2rtspserver.pid`.
3. Logs: `tail -40 /tmp/logs/tc100_rtsp.log` (RTSP connections, `401`, errors), `logread | tail -60`,
   `dmesg | tail -40`, `cat /tmp/log/service-watchdog.log | tail -20`, `sh /mnt/scripts/web-guard.sh` output if any,
   `ls -l /mnt/config/user.pwd /etc/httpd.conf` (the web and RTSP password files: present, sizes).
4. RTSP from the Mac: `ffprobe -rtsp_transport tcp rtsp://<user>:<password>@<ip>:554/video0_unicast` (the owner types
   the password) or VLC; then `sh /mnt/controlscripts/rtsp-h26x restart` and the same again.
5. Write every output here (no passwords). If the camera is not reachable at all on the network, say so first: that
   points at Wi-Fi / the address, not at the RTSP server or the web server.

### Next build: 3.0.1-rc14 = rc13 + the W-NET recovery + the night parameter set fix — the release candidate (2026-10-31)

rc13 was not installed (the tester ran R12 on rc12); install **rc14** directly. It holds rc13 (smart mode guarded and
off the page, frozen white balance counts ignored, statistics area diagnostic) and:
- **W-NET answer.** The stock board data (vendor kernel, `anyka-wifi` platform device, read with Ghidra) names
  **GPIO 11** as the Wi-Fi power / reset pin, driven high, with 200 ms after the reset and 2000 ms after power-on
  before the stock firmware loads `otg-hs.ko` and `8188fu.ko` (`sdio_wifi.ko`, its "wifi power on" / "wifi power
  reset"). New `scripts/wifi-recover.sh`, run **only when `wlan0` is missing**: (1) the USB device probed again
  (`authorized` 0 -> 1), (2) GPIO 11 low 1 s, high, 2 s, probed again; each step waits up to 20 s; then `wifi-apply`
  (wpa_supplicant, DHCP). Called at boot (autorun step 9b) and by the net-guard as soon as it sees the network down
  with no `wlan0` (tries spaced by 5 minutes), before any reboot. `WIFI_POWER_GPIO=0` in boot.conf leaves the pin alone.
  `meta.txt` of each saved boot gets `wifi_power_fail=<count>` and `wlan0=yes|no` (the counter you asked for).
- **R12-01 answer:** ENODEV came from the video driver, which registered with the ISP without its parameter-set
  callback (`ak_isp_acquire(NULL, NULL)`). rc14 gives it (`vi_set_style`: the capture mutex, then
  `ak_isp_apply_tuning_style`, as the stock app does while capturing); dmesg says `tuning parameter set 1`.

### .24 colours on rc16: the ISP white balance is wrong on this unit (tester, 2026-10-31 20:45 local, lit room, luma 148)
- With `HUE`/`SATURATION` back to 0, the wall that is white is still **yellow-green** with the software white balance on (default), and
  **bright green** with `awb.off` (the ISP alone; snapshots on the owner's Mac, not in git: an animal and a room). So the ISP's own white
  balance sits at a green colour temperature on the .24; the software white balance corrects most of it, not all. The .11 (same
  `/vendor/isp.conf`, md5 926b0a2a..., same kernel, `awb_live` 0) is neutral by the same test. Same sensor name F23 on both; the ISP file does not differ.
- rc15 (live statistics) went **blue** on the .11 (R15-01). So neither the old block (green on the .24) nor the live counts (blue on the .11) give a
  neutral picture on both units: the white balance algorithm needs a look with data of both cameras. `awb_live` is read-only at runtime
  (`/sys/module/ak_isp/parameters`, 0444): it cannot be flipped on the .24 without a kernel command line change (U-Boot; no serial on that camera), so
  no live counts test on the .24 was made.
- `cam_awb` on the .24 in this scene: `1894122 1083 8 0 0 3502 7 ...` (.11 in a dimmer scene: `272604 30 1 0 0 233 ...`).
- Requested: make `awb_live` a runtime-writable parameter (0644) or a `/mnt/config` switch the kernel reads at the start of capture, so the tester can A/B on both cameras without U-Boot.
- Owner's expectation: **the same neutral picture on both cameras** (3.0.1 should not ship with one camera green).

### .24 white balance: the ISP-gain controller of `tc100_rtsp` saturates (tester, ssh, 2026-11-01 10:50 local)
- With `RTSP_DEBUG=1` on the .24 (log in `/tmp/logs/tc100_rtsp.log`; the .24 had a leftover `config/rtsp.debug` from 2.x that sent the log
  to the console: removed): `AWB u -23 v -18 -> rgain_ex 512 bgain_ex 512`, stuck there. Both extra gains are at their **upper clamp (512 = x2)** and the mean
  chroma is still green (U -23, V -18): the .24's picture needs more than x2 on red and blue. The controller climbs 248 -> 270 -> 312 -> 360 -> 512 in a few seconds.
- `RTSP_ISPAWB=0` (software tables, +-85) is **worse** on the .24: green wall, purple wood and floor (over-corrected chroma), so it is not an alternative.
- So a remote fix exists but it is in `tc100_rtsp`: raise the clamp (512 -> 1024 or more, `r`/`b` in `post_awb_sample`), or start from the right base gains for each unit
  (the tuning file's AWB table seems to be a different colour temperature for this unit). Please also keep U/V clamped at +-40 only for the rate, not for the target.
- Test to ask for after the fix: both cameras, a white wall in daylight, `AWB u v` within +-2 and R/G/B within 3 %.
- Restored after the test: `config/rtsp.env` empty as before (copy `rtsp.env.before-2026-11-01` on the card), software white balance default.

### White balance, a global fix (owner: "if the tint can be solved globally, that would be the best") -- proposal from the tester, 2026-11-01
Why a per-camera fix is not enough: the .11 is neutral, the .24 green (needs more than x2 on red and blue), rc15's live statistics were blue on the .11. A third unit
will differ again. So the correction must be a **closed loop that has enough range and a safe target**, the same code on every unit:
1. **Range:** the extra gains in `post_awb_sample` stop at 512 (x2); allow 128..1536 (x0.5 .. x6). The log shows the .24 stuck at 512 with U -23, V -18.
2. **Target and robustness:** grey-world on the whole picture is fooled by a coloured scene (a red wall pulls everything cyan). Measure only pixels that are plausibly grey
   (Y between 40 and 220, |U|,|V| below 25 around the current mean) and ignore the rest; or accept a correction only inside the colour temperatures a lamp or daylight can
   have (a small locus: red/blue ratio between 0.5 and 2.5 once corrected). Step slowly (the 0.5 s sample, 1/4 of the error), freeze when the scene luminance changes quickly.
3. **Start point:** begin each start from the last good gains (saved in `/mnt/config/awb.state` every few minutes, 2 numbers), so the first picture is already right and a unit's
   own bias is learnt once; reset it on a sensor or tuning file change.
4. **Same handling day and night:** hold the gains at the IR switch (colour is meaningless in the B/W night picture), restart the loop from the saved day values in the morning.
5. **Switch to see it:** `RTSP_DEBUG` log line already prints `AWB u v -> rgain_ex bgain_ex`; put the final gains and U/V in `/tmp/cam_awb` too so the tester reads them without debug.
6. **Acceptance (both cameras, daylight, white wall in view, and again in a lamp-lit evening):** `AWB u v` within +-2, R/G/B of the wall within 3 %, gains below the new clamp,
   and the same code on both. A third unit's owner can then check the same two numbers (`/tmp/cam_awb`) in an issue.
Not needed: per-unit calibration files, a kernel parameter, the live-statistics mode (it can stay for the day/night method only).

### .24 white balance: PROOF that the gain range is the cause (tester, ssh, 2026-11-01 14:25 local, daylight, white wall in view)
- New test tool `docs/linux-port/awbx.c` (static ARM build, copied to `/tmp` on the camera, RAM only): `awbx get` / `awbx set R B` read and set the ISP's extra white balance gains
  (`AK_ISP_GET/SET_AWB_EX`, 256 = x1) for the 10 colour temperature ranges. **The driver accepts values above 512** (700 read back as 700).
- Steady state of the loop in `tc100_rtsp`: **.11 settles at rex 230 / bex 287** (about x0.9 / x1.12); **.24 is stuck at 512 / 512** (the clamp) and still green.
- With `awb.off` (loop off) and gains set by hand on the .24 (the same room, mean of boxes of the JPEG snapshot; R,G,B):
  | rex / bex | white wall, lit part | white wall, shaded part | picture |
  |---|---|---|---|
  | 256 / 256 (as the ISP starts) | 82, 244, 0 | bright green | green |
  | loop at its clamp 512 / 512 (software on) | 176, 213, 84 | | yellow-green |
  | 700 / 700 | 255, 249, 216 | 235, 204, 186 | warm, wall clipped |
  | **600 / 760** | 253, 248, 231 | **211, 205, 200** | **neutral: white wall, natural wood and leaves** |
  | 650 / 820 | 254, 245, 243 | 224, 198, 211 | slightly magenta |
  So the .24 needs about **x2.3 red and x3.0 blue** (600 / 760) against **x0.9 / x1.1** on the .11: a clamp at 512 can never work for it, and a clamp up to 1024 does.
- **Fix to build (global, the same code for every unit):** in `post_awb_sample` raise the clamps to 128..1536 (r, b), keep the grey-world loop, start from saved gains. Test with `awbx get` after
  a minute in daylight: the loop must settle by itself near 600 / 760 on the .24 and near 230 / 290 on the .11, wall within 3 %.
- The tester restored the default on the .24 (no `awb.off`, server restarted); the manual gains were RAM only and are gone with the restart.

### R16-01 rc16 on the camera: colours back to rc14, then the last checks — `to test`
- Install as rc15. `dmesg`: `read from word 1160`; `cat /sys/module/ak_isp/parameters/awb_live` = 0; `/tmp/cam_awb`
  moves. A snapshot of the R15-01 scene: **the blue / violet cast is gone** (as rc14: near neutral, maybe slightly warm).
- Then R15-03 (one night) and R15-04 (the owner: the page, the no-card hour with a reboot from the page), the alert
  and boot chime heard once. If they pass: **3.0.1** (VERSION, release documentation, the tag with the owner's go).

### Next build: 3.0.1-rc15 — the release candidate (2026-10-31)

**Implementer's answers to the last results (R12-02/04/06/09, the rc13 guard, the watchdog):**
- **R12-09: found.** The moving words form groups of four (R, G, B, count) from word **1160**; 10 groups end at word
  1199, the last of the 4800-byte area. The kernel read word 1032, a fixed block. rc15 reads 1160 (patch 0006,
  `_get_awb_stat_result`; dmesg now says `read from word 1160`). Consequences: the ISP's own automatic white balance
  works on live statistics for the first time on 3.0 (colours may change: R15-01), `/tmp/cam_awb` moves, and the
  stock day / night method's white balance check works; its thresholds are set to the stock **library** defaults
  (1200 / 50000), the scale of these counts (lit room: 1301 and 4351), not the ini's 15000 / 300000.
- **R12-04:** the clips were full-scale sines (0 dBFS): the small amplifier may clip whatever the analogue volume.
  rc15: the clips at -6 dBFS with fades, and three test tones to tell clipping from a playback fault (R15-02).
- **Defaults in rc15:** night picture settings on (R14-02), 10 fps in low light on (R12-02), IR-cut pulse 10 ms
  (R12-06). The stock day / night method stays opt-in until a night with live counts (R15-03).
- The rc13 smart-mode guard and the server watchdog passed: nothing to change.

### R15-01 Colours with the live white balance statistics — `to test` (owner looks)
- **What changed:** the ISP's automatic white balance now reads real counts (it read fixed data before). The
  software white balance of `tc100_rtsp` still runs on top (`config/awb.off` turns it off).
- **Test:** `dmesg | grep 'read from word 1160'`; `cat /tmp/cam_awb` twice with different light: the numbers change.
  Then by day: a snapshot with the default (software white balance on), then `touch /mnt/config/awb.off`, restart the
  server (`rtsp-h26x restart`), a snapshot of the same scene: is the picture neutral with the ISP alone? A white wall
  or paper in view helps. Write the impression and keep the two snapshots on the card.
- **Then (3.0.1):** if the ISP alone is neutral, the software white balance goes off by default (`awb.off` shipped);
  otherwise it stays.

### R15-02 Speaker with the -6 dBFS clips and the test tones — `to test` (someone listening)
- `aplay -D plughw:0,0 -t raw -f S16_LE -r 8000 -c 1 /mnt/sounds/test-1k-m6.pcm` (no `-q`: an `underrun` message is a
  playback fault), the same with `m12` and `m20`, Headphone at 3 and 5 (`amixer -c 0 sset Headphone 3`). Cleaner when
  lower = clipping (the clips' level answers it); crackling at every level and an `underrun` = the PCM / DMA path
  (then `amixer -c 0 contents` here). Then `speaker-play.sh /mnt/sounds/alert.pcm` and the boot chime.

### Prepared for rc15 (in git, no build to install yet): the answers to R14 (implementer, 2026-10-31)
- **R14-01:** GPIO 11 confirmed as the Wi-Fi power, thank you. The degraded link after the manual cycle is answered
  the way you found it clears: after a power cycle `wifi-recover.sh` applies the Wi-Fi settings, waits 25 s and pings
  the gateway 4 times; lost or slower than 500 ms on average -> one clean restart (`reboot-tracker.sh intent
  "wifi-recover: link slow after a Wi-Fi power cycle, clean restart"`), which starts from the freshly powered chip as
  your warm reboot did. A second restart is not done until the net-guard has seen the network fine for 10 minutes
  (`/mnt/config/.wifi-recover-restarts`, kept in the flash settings). The console line now gives the USB speed after
  the chip comes back (`USB speed N Mbit/s`): **if you cycle it by hand again, please note
  `cat /sys/bus/usb/devices/1-1/speed`** (480 = high speed, 12 = full speed would explain slow pings).
- **R14-02 passed:** the night parameter set becomes **the default in rc15** (`NIGHT_STYLE` on unless the Day/night
  switch is turned off): it is what the stock firmware does at every night switch. The picture at night is still to be
  looked at (R12-01 step: grain, brightness, smearing) on the next dark evening.
- rc15 is built once the night tests (R12-02, R12-03, R12-05), the listening (R12-04, R12-06), the R12-09 dumps and the
  owner's checks (R12-07, R12-08) are in: one build with every default decided ([release-3.0.1.md](release-3.0.1.md)).
  Please run them on rc14 (same features).

### Next build: 3.0.1-rc13 = rc12 + the R11 answers — install rc13, not rc12 (2026-10-31)

rc12 was pushed before the R11 results came in; rc13 replaces it (same R12-xx tests). **Implementer's answers to R11:**
1. **R11-01 smart mode: dropped from the page.** Request (1) done: mode 1 is only called when the pool has 3407872 +
   256 KB free (log `smart mode 1 not used: it needs N bytes of encoder pool, M free`); mode 2 never, unless
   `RTSP_SMART_FORCE=1`. A marker (`/tmp/.rtsp_smart_try`) set before the call and removed after 250 good frames: a
   server that died after trying skips smart mode at its next start (`smart mode skipped: the server stopped after it
   last time`). (2) The restarter exists: `scripts/service-watchdog.sh`, a job of the housekeeper, checks every 60 s and
   restarts with a back-off of 20 s + 15 s per failure. With `RTSP_SMART` still in `rtsp.env` each restart died again,
   which looks like nothing restarting. **Please check** `/tmp/log/service-watchdog.log` and `housekeeper.sh status`
   after the next deliberate `killall tc100_rtsp`: the server must be back within about 80 s. (3) Mode 2's need is not
   known (no message before it dies); not pursued, the stream bit rate gain was small (R9-04: VBR alone -6 %).
2. **R11-02 frozen `/tmp/cam_awb`:** the kernel reads the white balance counts at a fixed offset of its statistics area
   (word 1032); on the TC100 they never change, so the kernel's own automatic white balance works on frozen numbers
   too, **a candidate cause of the colour cast**. rc13: the vendor day / night source ignores counts that do not change,
   dmesg gives the statistics area's address, and R12-09 finds the words that really move.
3. R11-03 passed, thank you (`intent` records the reason, the caller reboots: right).

### R12-09 Where the ISP writes its white balance statistics (`scripts/isp-stat-dump.sh`, read only) — `to test`
- **Test:** `dmesg | grep 'statistics DMA area'` (address, 4800 bytes). Lamp on, `sh /mnt/scripts/isp-stat-dump.sh`
  (about 10 s, writes `/tmp/isp-stat-<time>.txt`); a minute later the same; then lamp off or a coloured object in front
  of the lens and a third dump. `awk 'NR==FNR{a[$1]=$2;next} a[$1]!=$2' dump1 dump2 | wc -l` (noise) and dump2 against
  dump3 (the light change): copy the three files to the card (`/mnt/sd/r12-09/`) and write here which word ranges
  change. Words 0-1031 are the histograms (they must move); 1032-1071 are where the kernel reads the white balance.
- **Then:** if the white balance block is elsewhere, the offset in the kernel is fixed (a kernel patch): the kernel's
  automatic white balance and the vendor day / night source get live counts, and the software white balance may go.

### Next build: 3.0.1-rc12 — everything the stock dump can give, then the flash-only camera (2026-10-31)

The owner (2026-10-31): analyse the binaries deeply, put into rc12 all that the stock dump can bring, **check that
everything is wired in the web UI too**; if rc12 is conclusive, the next step is the complete, persistent flash
install for a camera that needs no SD card. Findings: [vendor-re-findings.md](vendor-re-findings.md). Nothing touches
U-Boot, `boot`, `mac` or `env`. Every new behaviour is switchable from the web page; off by default except the speaker
fix (a bug fix) and the IR LED protection (the stock behaviour, protective).

**Order:** R12-00 install (card boot, then `update66.sh apply`), R12-04 speaker first (one minute), R12-07 the page,
then R12-01/02 (a dim room and an evening), R12-03/05 over a night, R12-06, and R12-08 (no SD card) last.

### R12-00 3.0.1-rc12 on the camera — `to test`
- Card boot of the rc12 kernel, then `update66.sh check` / `apply` (owner's agreement), flash boot. `/mnt/VERSION` =
  3.0.1-rc12, pool 9600K, both encoders `open`, MemAvailable as rc10 (21-22 MB), `tc100_rtsp.log`: `anti-flicker:
  camera default 50 Hz`, `cat /tmp/cam_ae` has 7 numbers (the 7th 1125), `cat /tmp/cam_awb` 11 numbers.

### R12-04 Speaker: amplifier enable active low (`speak-gpios-en = <0>`) — `to test`
- **What:** the stock kernel and app play with GPIO 14 **low** (vendor-re-findings.md); 3.0 drove it high, so the
  amplifier was off while playing and on (hissing) at rest. rc12: active low, off at rest; route changes no longer
  switch it on. **Way back:** `ak39_codec.spk_active=1` on a card kernel's command line, or the rc11 kernel.
- **Test:** `devmem 0x2017000c 32` at rest (bit 14 set = high = amplifier off). `sh /mnt/scripts/speaker-play.sh
  /mnt/sounds/<a clip>` (or `aplay -D plughw:0,0` of a WAV): **the clip is heard**; during it bit 14 is clear. At rest
  after the clip: no hiss. `amixer -c 0 sset Headphone 1` then `5` changes the loudness. Then push-to-talk / two-way
  audio from go2rtc or Home Assistant (UI-13) and the web page sounds.
- **Pass:** audible clip, silent at rest. **Fail:** write `devmem` readings; rc11 kernel back.

### R12-02 10 fps in low light by day (Day/night page) — `to test`
- **What:** by day, total gain above 14 x -> sensor 10 fps and exposure up to 2812 lines; under 5 x -> the stream rate
  and 1125 (5 s apart), as the stock app. Not at night, not with an exposure cap.
- **Test:** switch on, Save. Dim room by day: log `low light: total gain 26x, sensor 10 fps, exposure up to 2812
  lines`, picture brighter, less grain; light on: `... sensor 25 fps, exposure up to 1125 lines`. No flapping between
  the two (watch 10 minutes at dusk light). Frigate fine at 10 fps.
- **Pass:** brighter dim-room picture, clean switches. Then (rc13) on by default (it also makes R12-03's thresholds valid).

### R12-06 IR-cut pulse 10 ms (`IRCUT_PULSE_MS=10` in boot.conf) — `to test`
- **What:** the stock app pulses the IR-cut coil 10 ms; 3.0 uses 150 ms (`bin/setconf`). A shorter pulse heats the
  coil less. Already a setting: nothing new in the code.
- **Test:** `IRCUT_PULSE_MS=10` in `/mnt/config/boot.conf`, Day / Night buttons 10 times each way: the filter clicks
  and the picture changes every time. Then 20 ms if 10 misses once.
- **Pass:** 10 / 10 each way. Then (rc13) the default.

### Next build: 3.0.1-rc11 — what the stock binaries taught (2026-10-31)

The owner asked to read the original binaries (Ghidra) and use what they teach. The full stock dump was in the git
history (`bootloader.bin`, 8 MiB). Findings in [vendor-re-findings.md](vendor-re-findings.md). The owner's choices:
smart mode as an option; for day / night, measure first (the vendor's metric needs the white balance counts in the
log); push after local CI. rc11 = rc10 +:
- **R11-01 encoder smart mode** (off by default).
- **R11-02 white balance counts** for day / night: `/tmp/cam_awb` and `awb=` in the calibration log.
- Confirmed, nothing to change: anti-flicker computes the step exactly as the stock library (R9-03).
- **R11-03 fix:** settings changed less than a minute before a deliberate reboot are saved first.

### R11-01 Encoder smart mode (`RTSP_SMART`) — `to test`
- **What:** `ak_venc_set_smart_config(handle, {mode, gop, quality, static})` after every encoder open, with the stock
  values (GOP 300 frames, quality 100, static 550). `RTSP_SMART=1`: long-term reference (LTR); `RTSP_SMART=2`:
  variable GOP (GOP up to 300 frames on a still scene). Only with `RTSP_VBR=1` (the vendor app uses it in VBR only);
  `RTSP_SMART_SUB` for the sub-stream (default: as the main), `RTSP_SMART_GOP` / `_Q` / `_V` override. **Off:**
  unset or `0` (the call is never made).
- **Test** (`/mnt/config/rtsp.env`, restart `tc100_rtsp` as `v3/autorun-linux66.sh` does; one Frigate client):
  1. `RTSP_VBR=1` + `RTSP_SMART=1`: log `encoder main: smart mode 1 (long-term reference), gop 300, quality 100,
     static 550` (and `sub`), both encoders `open`. 10 minutes on a still day scene: main stream bytes per 5 s
     against VBR alone (R9-04: 899 KB) and CBR (950-980 KB). Then a hand in front: no smear, blocks or freeze.
  2. The same with `RTSP_SMART=2`. Also: VLC opened while the scene is still: the time to the first picture (a long
     GOP means waiting for a keyframe), and Frigate: recordings and detections still start without a missed second.
  3. A codec change in Settings (main H.264, then back): the smart line again after the reopen.
- **Pass:** a clear saving on a still scene, no visible loss, Frigate and VLC fine. **Then** (rc12) the mode that wins
  becomes the default with `RTSP_VBR=1`. **Fail:** `rtsp.env` empty again.

### R11-02 White balance counts for day / night — `to test` (with R9-02's dusk and dawn)
- **What:** every 2 s `tc100_rtsp` writes `/tmp/cam_awb`: the 10 `total_cnt` of `AK_ISP_AWB_STAT_INFO` and the
  colour temperature index. The calibration log line gets `awb=<those 11 numbers>`. The stock switch goes to night
  only when none of the 10 counts is above 300000 (no daylight), and back to day only when one of the first 5 is
  above 15000 (visible light, not just the IR LEDs), on top of its metric `index * 40 / lumi` (lumi = first field of
  `/tmp/cam_ae`).
- **Test:** `cat /tmp/cam_awb` (11 numbers that move with the scene), then nothing but the R9-02 dusk and dawn: copy
  the log lines here. From them the implementer sets the vendor-like source (metric + white balance check).

### R11-03 Settings saved before a deliberate reboot (`cfg-persist flush`) — `to test`
- **What:** R10-01's note: a setting changed 35 s before a reboot was lost (`cfg-persist` saves a change once it has
  been stable for 30 s, checked every 30 s). `reboot-tracker.sh intent` (every reboot from the web UI, MQTT, the
  button, net-guard) now runs `cfg-persist flush` first: a save only when the settings differ from the last saved ones,
  waited for up to 20 s, never interrupted. A plain `reboot` typed in a shell does not go through it.
- **Test:** change a setting from the web page (or `rwconf ... daynight 3` then `sh /mnt/scripts/reboot-tracker.sh
  intent "test: R11-03"`), reboot within 10 s: the console shows `[cfg-persist] settings saved to slot ...` before the
  restart, and the setting is there after it. Reboot again with nothing changed: no save line.
- **Pass:** both. **Fail:** write what was lost; the 30 s daemon keeps working as before either way.

- **Results R11-01..03 (tester, 2026-10-31, rc11 = 1313467, CI green); rc11 installed in the .11 flash:**
  - Install: rc11 kernel (md5 17233877…) booted once from the card (U-Boot prompt, RAM), package md5 1007ad97…, `update66.sh check` ok, `apply update11`:
    `/mnt/VERSION` 3.0.1-rc11, flash boot, pool 9600K, MemAvailable 21.6-23.8 MB, both encoders `open`.
  - **R11-01 FAIL, and a hazard: both smart modes stop the video server.**
    `RTSP_VBR=1` + `RTSP_SMART=1`: log `[ak_venc_set_smart_config:2571] setting smart mode=1, gop=300, q=100, v=550`, then
    **`[venc_cb_dma_alloc:269] alloc dma for 3407872 failed`**, `Encoder failed : Memory shortage detected`, and
    `lib_interface/akv_interface.cpp: 1978: UpdateEncParams: Assertion 'pEnc' failed` (twice); `tc100_rtsp` is gone (0 processes), **nothing restarts it**: no
    stream until someone restarts it or the camera reboots. The LTR mode wants **3407872 bytes (3.25 MB)** of encoder DMA more; the main encoder leaves
    1883424 free in the 9600K pool, and the sub-stream takes 920 KB of it, so it cannot fit (with a 12M pool: 12582912 - 8866880 = 3.7 MB, it might: card kernel
    `ak39_venc.pool=12M` needed, not tried). `RTSP_SMART=2`: both `smart mode 2 (variable GOP)` lines for main and sub are printed, then the server dies after
    3 frames (`stream stopped: 3 frames`, no STAT line, no process, no message in the log or dmesg). So neither mode can be switched on with the rc9+ pool.
    Reverted at once (`rtsp.env` empty, restart: server back). **Requests:** (1) never call the smart config when the pool lacks the room (the log line
    says `free N` per encoder; refuse and log), (2) a respawn or at least a health flag when `tc100_rtsp` dies, (3) find what smart mode 2 asks for.
  - **R11-02 `/tmp/cam_awb`: the file exists but its numbers are constant.** 11 numbers `108594719 72811827 33752465 80479141 111674134 122422761 71303623 43648936
    67961336 7275626 5`, **identical** at 5 readings over 3 minutes while `cam_ae` moved (gain 3475 -> 1433 -> 1246), **and identical after a reboot**: they are
    not live statistics (stale or uninitialised read). All ten counts are far above 300000 and the first five above 15000: "day" by the stock rule, at any hour.
    The first `awb=` calibration line is not written yet (5 min after a boot); it will show in the soak's day / night log.
  - **R11-03 PASS.** `daynight=3` written, `reboot-tracker.sh intent` after 4 s (note: `intent` only records the reason, the reboot is the caller's): `[cfg-persist] settings saved
    to slot cfga (seq 112)` at once, setting kept. Second run: `daynight=2` written, `intent` after 3 s, `sync; reboot`: `settings saved to slot cfgb (seq 113)` before the
    restart and `settings restored from slot cfgb (seq 113)` after: `daynight=2`, `health` `ok: running`. (I did not test the no-save case with nothing changed.)
  - .11 now: rc11 in flash, auto day/night running, `rtsp.env` empty, fps 25, soak restarted (rc11), card boot files as before (`test.img` rc11, older ones renamed).

### Next build: 3.0.1-rc10 — fixes from the R9 results (2026-10-31)

The owner (2026-10-31): 3D-NR is not worth its 5.6 MB of RAM; make the other fixes; for day / night, wait for the
dusk and dawn readings before changing any logic. So rc10 = rc9 +:
- **Anti-flicker:** the default choice is now **"Camera default"** (was "Off"), and the page shows what it is
  ("Camera default: 50 Hz." under the select, from `POWER_HZ_BASE` in `/var/run/isp_tune.status`); `tc100_rtsp.log`
  says it at every start: `anti-flicker: camera default 50 Hz (exposure step 281 lines)`. Back to the default from a
  choice logs `anti-flicker: camera default (exposure step N -> 281 lines ...)`.
- **Day / night launcher:** with `daynight=3` (manual Day / Night) the boot now prints `Auto Day/Night detection not
  started: manual day/night mode (daynight=3)` on the console and in syslog, and `auto-night-detection health` says
  `ok: manual day/night mode (daynight=3), automatic switching off` instead of `warn: stopped`. The behaviour is
  unchanged (manual stays manual).
- **3D-NR:** `nr3d=0` stays the default, the option stays in the kernel; CI no longer builds the card test kernel.
- **Not changed:** the day / night logic and its thresholds (waiting for R9-02's dusk and dawn lines).

### R10-01 3.0.1-rc10 on the camera — `to test`
- **Test:**
  1. Card boot, then `update66.sh apply` as for rc9 (owner's agreement); `/mnt/VERSION` = 3.0.1-rc10.
  2. `grep anti-flicker /tmp/logs/tc100_rtsp.log`: `camera default 50 Hz (exposure step 281 lines)`. Web page
     Settings, Picture: the select shows "Camera default" (FR "Réglage d'usine") and under it "Camera default: 50 Hz.".
     Choose 60 Hz, then Camera default again: the two log lines, `POWER_HZ_BASE=50` in `/var/run/isp_tune.status`.
  3. `rwconf /mnt/config/rtspserver.conf w " " daynight 3`, reboot: the console line `not started: manual day/night
     mode`, `sh /mnt/controlscripts/auto-night-detection health` = `ok: manual ...`. Then `auto-night-detection start`
     (writes `daynight=2`) and check `health` = `ok: running`. Leave it on auto for R9-02.
- **Pass:** 1-3.

- **Result R10-01 (tester, 2026-10-31, rc10 = 95ea86e, CI green): steps 1-3 PASS.**
  - Step 1: rc10 kernel (md5 b47f9bfa…) booted once from the card through the U-Boot prompt in RAM (flash initrd): pool 9600K, no 3D-NR line, MemAvailable 21.3 MB.
    Package md5 16ea9d33…, `update66.sh check` ok, `apply /mnt/sd/tc100-3/update10`: stack, kernel, initrd written, restart; `/mnt/VERSION` = 3.0.1-rc10,
    flash boot, MemAvailable 21.5 MB, `ak39_venc.pool` 9600K, both encoders `open`.
  - Step 2: log `anti-flicker: camera default 50 Hz (exposure step 281 lines)`, `POWER_HZ_BASE=50` in `isp_tune.status`; 60 Hz:
    `anti-flicker: 60 Hz (exposure step 281 -> 234 lines, exp_time_max 1125)`, `POWER_HZ=60`; back to the camera default: the first line again, `POWER_HZ=` empty.
    **Web page (select "Camera default" / "Réglage d'usine" and the 50 Hz line under it) not looked at: needs the owner's login.**
  - Step 3: `daynight=3` persisted (waited for `settings saved`), reboot: console `Auto Day/Night detection not started: manual day/night mode (daynight=3); Auto under the picture or
    Services turns it on`; `auto-night-detection health` = `ok: manual day/night mode (daynight=3), automatic switching off`; no daemon running.
    `auto-night-detection start`: `daynight=2` written, `health` = `ok: running`; persisted to cfgb. The .11 is left on auto with the daemon running.
  - Tester note: the first try at step 3 lost `daynight=3` because the camera was rebooted 35 s after the change, before cfg-persist saved (it needs ~30-60 s: wait for
    `/tmp/cfg-persist.status`).
  - New soak started ~09:12 UTC (`/mnt/sd/soak-20261031.log`, rc10); R9-00 step 4 (overnight) and R9-02 (dusk, dawn) are read from it and from `/tmp/logs/daynight.log`.
  - Card: `tc100test/test.img` = rc10 kernel, `test.img.rc9`, `.rc8`, `.rc7`, `c66-nr3d.img`, `c66-pool.img`, `c66rd-*.gz` kept; no `c66.img` (flash boot).

### Next build: 3.0.1-rc9 — the pool that passed, and the four untapped parts of the SoC (2026-10-31)

The owner (2026-10-31): R8-02's hour with Frigate looked stable ("RAS"), so the 9600K pool is kept; and "do all of
1 to 4" from the list of what the SoC still leaves unused (3D noise reduction, anti-flicker, day / night from the ISP
exposure, the encoder's smart / VBR modes), **with every precaution: no brick**. So rc9 = rc8 + the pool default +
those four, each **off by default** (or a pure measurement) until its entry below passes. Nothing touches U-Boot,
`boot`, `mac` or `env`; 3D-NR is tried with a card kernel only.

**Order** (each step only if the previous one is fine; write the result under each entry):
1. R9-00: rc9 as a card boot (kernel and initramfs on the card, the rule), then `update66.sh apply` as for rc8.
2. R9-03 anti-flicker and R9-04 encoder: on the flash rc9, no kernel change.
3. R9-01 3D-NR: the card test kernel, then back to the normal kernel. An evening or night reading is the useful one.
4. R9-02 day / night: nothing to do but leave the camera running through a dusk and a dawn, then copy the log.

### R9-01 3D noise reduction (`ak39_vi.nr3d=1`, card test kernel) — `passed technically, not kept` (owner 2026-10-31: 25-34 % less noise is not worth 5.6 MB of RAM; `nr3d=0` stays the default)
- **What:** the ISP's temporal noise filter needs a reference frame of 3 bytes a pixel (6.2 MB at 1080p). Until rc8 it
  was asked for at each video start and never found room in CMA next to the capture buffers, so 3D-NR was always off.
  Patch 0006 now: `ak39_vi.nr3d=1` reserves it **once at boot**, while CMA is empty, and keeps it; the tuning file's own
  3D-NR settings then apply. Default `nr3d=0`: off, nothing allocated. The CI builds a **card test kernel** with
  `ak39_vi.nr3d=1 cma=24M flashroot=1 ak39_vi.sub_channel=1` in its own command line (appended after U-Boot's, so its
  `cma=24M` wins over U-Boot's `cma=18M`: 6 MB more CMA for the reference frame). Artifact **`tc100-linux66-nr3d-test`**
  (`c66-nr3d-test.img`, `System.map`, `.config`, `README-NR3D.txt`, `md5sums.txt`).
- **Expected:** less grain at night and in dim light, and with `RTSP_VBR=1` a lower bit rate on a still scene.
  **Costs to measure:** 6.2 MB of RAM (MemAvailable about 16 MB instead of 22), and memory traffic (the ISP reads and
  writes the reference at every frame: watch `cap` and `dropped`).
- **Safety:** card file only, as R8-02. A kernel that cannot reserve 24 MiB of CMA would have no video: rename back.
- **Test (after R9-00, rc9 in the flash):**
  1. On the card: rename `tc100test/c66.img` to `tc100test/c66-before.img`, copy `c66-nr3d-test.img` as
     `tc100test/c66.img` (md5 against `md5sums.txt`). `c66rd.gz` stays the one whose size equals the initrd size of the
     hook's `sdboot` (read the environment, do not write it). Reboot.
  2. `/proc/cmdline` ends with `ak39_vi.nr3d=1 cma=24M flashroot=1 ak39_vi.sub_channel=1`; dmesg `cma: Reserved 24 MiB`
     and `3D-NR reference frame: 4050 KiB at ..., 2025 KiB at ...` (or `no memory for the 3D-NR reference frame`: write
     it down, with `grep -i cma /proc/meminfo`); video starts, both encoders `open`.
  3. Five minutes at 25 fps with one client: `cap` / `dropped` per 5 s against R9-00, idle CPU, MemAvailable, CmaFree.
  4. Picture, the main point: a snapshot and 30 s of VLC in a dim room (and at night with the IR LEDs) with this
     kernel, the same with the normal kernel (rename back, reboot): grain on flat surfaces, smearing of a moving hand.
     Keep the snapshots on the card (`/mnt/sd/r9-01-*.jpg`). With `RTSP_VBR=1`: main stream bytes per 5 s on a still
     dim scene, with and without 3D-NR.
  5. If 1-4 look good: one hour with Frigate as R8-02 step 7 (no `ak_venc_open failed`, no Oops / OOM, stream bytes
     steady), then rename back.
- **Pass:** steps 1-5, no more dropped frames than R9-00, a visible noise gain. **Then** (rc10): `nr3d=1` and `cma=24M`
  become the defaults (`nr3d` in the driver; `cma=24M` through the release kernel's built-in command line, appended
  as here, so no U-Boot change). **Fail:** rename back; write the numbers. A gain too small for 6 MB of RAM is a fail.

### RE-01 Copy the stock binaries to the card for reverse engineering (read only) — `done another way` (the full stock dump was in the git history, see vendor-re-findings.md; only the speaker libraries of the camera might still be wanted)
- **Why:** the owner asks to read the original binaries (Ghidra, on the implementer's PC) instead of guessing vendor
  structures: the `ak_venc_set_smart_config` structure (R9-04: the call exists), the anti-flicker call of the stock
  firmware (`ak_vpss_effect_set(6, hz)`, to check R9-03), the 3D-NR reference frame size of the vendor ISP driver (to
  check R9-01 before its card test), the stock day / night logic and the speaker path. These files are not free: they
  go to the card and then to the owner's PC only, **never into git, a CI artifact or a chat**.
- **Safety:** reads only (`cp`, `dd if=` of a partition into a file on the card). Nothing written to the flash.
- **Do (after the R9-00 soak, card mounted read-write):**
  1. `mkdir -p /mnt/sd/re` and copy the camera's vendor libraries: `/mnt/lib/libmpi_venc_ex.so`, `libakv_encode.so`,
     every `libplat_*.so`, and whatever else the `vendor` partition holds (`ls -l` of it into `/mnt/sd/re/vendor-ls.txt`).
  2. The stock firmware: if `tc100-3/backup/` (written by the 3.0 install) holds the old partitions, list them with
     their md5 into `/mnt/sd/re/backup-ls.txt` (no copy needed, they are already on the card). If a full 8 MB dump or a
     `collect-platform-dump.sh` tar exists on the card or the Mac, say where.
  3. Write here what was copied (names, sizes, md5). The owner copies `/mnt/sd/re/` and the stock partitions to
     `C:\Users\<user>\Documents\tc100-re\in\` on his PC.
- **Then (implementer):** Ghidra headless analysis; the findings (structures, values, call sequences) go into the code
  and `docs/linux-port/`, each as a switch with its own test entry here.

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
5. **`amixer -c 0`: fixed** by writing `ext/share/alsa/cards/aliases.conf` (the slim base drops `cards/`): its four
   includes define `sysdefault`, `dmix`, `dsnoop`; build-stack checks them.
   **Speaker silent: not touched in rc8** (no verified fix; the codec path needs a test of its own, see B-01 notes).
6. **25 fps as the default: not in rc8.** It costs no CPU (P-04), but the picture quality at 25 fps with the same
   bit rate was not looked at. The owner can choose 25 in Streams & audio; a default change waits for a day-time look.
7. **HW-02 test 2 (`ak39_venc.pool=9600K`): the owner says go, in rc8** (card kernel only, built by CI with the parameter in
   its own command line: no U-Boot prompt; kept if it passes, dropped if not). To make it a one-parameter test, `tc100_rtsp` leaves out the start-of-pool
   guard by itself when the pool is smaller than 12 MiB (log `encoder pool: N bytes (ak39_venc.pool), no guard at
   its start`; `RTSP_POOLPAD=<bytes>` still forces one). With the default 12 MiB pool nothing changes. Steps in R8-02.

### R8-00 rc8 CI: the kernel workflow FAILS on `645281b` and on `d60cb12` (tester, 2026-10-31 01:10) - nothing to test yet
- Runs 41146850236 (`645281b`) and 41147148222 (`d60cb12`), workflow "Build Linux 6.6 LTS Kernel ...", job "Compile Linux 6.6 + Anyka AK3918 +
  CMA 16MB", step **"Build the 3.0 release (free user space image, SD package, web update)"**: `sh v3/build-stack.sh ...` stops with
  **`cp: cannot stat 'usr/share/alsa/cards/aliases.conf': No such file or directory`** (the line `cp -L usr/share/alsa/cards/aliases.conf
  "$T/ext/share/alsa/cards/"`, `v3/build-stack.sh` line 87). The Python "CI" workflow is green. No artifact was produced, so the tester has
  no rc8 to put on the camera.
- **Why:** the slim Buildroot base (B-02: alsa-lib with PCM and mixer only) does not install `/usr/share/alsa/cards/aliases.conf` at all (it is
  not in the base rootfs), so there is nothing to copy; on the camera the missing file is what breaks `amixer -c 0` (rc7 report).
- **Fix proposals (either):** (a) if the file is not in the base, write a one-line placeholder in `build-stack.sh` instead of copying
  (`printf '# cards are addressed by number on this camera\n' > "$T/ext/share/alsa/cards/aliases.conf"`; `alsa.conf` only needs the file to
  exist, `-c 0` is a number); keep the `[ -s ... ]` check afterwards (a comment line is not empty); or (b) enable the alsa-lib option that
  installs `cards/` in `v3/buildroot/configs/` and rebuild the base (the CI caches it: bump the cache key). (a) is the quick one and needs no
  new base. After the fix, test on the camera: `amixer -c 0 sget 'Headphone Playback Volume'` rc 0 and no `cannot stat` line.
- The workflow added in `d60cb12` for the pool-9600K card kernel runs after this step, so it has not been exercised either.
- **Implementer (2026-10-31): fixed in `372a83b`,** a variant of (a). A comment-only file is not enough: checked with
  alsa-lib 1.2 in a container, `amixer -D sysdefault:0` still fails (`Unknown parameters 0`, `Invalid CTL sysdefault:0`),
  because the end of the real `aliases.conf` holds four includes (`ctl/default.conf`, `pcm/default.conf`, `pcm/dmix.conf`,
  `pcm/dsnoop.conf`) that define `sysdefault`. `build-stack.sh` now copies the base's file if there is one, else writes
  those four includes (same result as the full file in the container), and checks that the included files are present.
  No new base. On the camera: R8-01 step 3.

### R8-02 HW-02 test 2 on rc8: a 9.4 MiB encoder pool (`ak39_venc.pool=9600K`, card boot) — `passed` (steps 1-5 tester, the hour with Frigate "stable" for the owner, 2026-10-31); the driver default since rc9 (R9-00)
- **Why this size:** the encoders use 8866880 bytes with the main stream in H.265 and the sub-stream in H.264 (HW-01b,
  no guard); 9600K = 9830400 bytes leaves about 0.96 MB. **Gain expected: about 2.6 MB more `MemAvailable`** on top of
  `slots=3`. Never measured: the pool use with the **main stream in H.264**, the riskiest case.
- **No U-Boot prompt (the owner's rule after night 2):** the rc8 CI run also builds a **card test kernel with the
  parameter in its own command line** (`CONFIG_CMDLINE="ak39_venc.pool=9600K flashroot=1 ak39_vi.sub_channel=1"` since
  the tester's 2026-10-31 request: flash user space from a card boot; `CONFIG_CMDLINE_EXTEND`: appended by
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
- **Result so far (tester, 2026-10-31, build 37a5851, CI green) — steps 1-5 PASS, 6-7 running:**
  - Boot: card kernel `c66-hw02-pool9600k.img` (md5 1e335be3…, matches md5sums.txt) + rc8 `c66rd.gz` (2012654 bytes) copied to the card
    as `tc100test/c66.img` / `c66rd.gz`; no U-Boot prompt. The flash user space came up (`flashroot=1`); `/proc/cmdline` ends with
    `ak39_venc.pool=9600K flashroot=1 ak39_vi.sub_channel=1`; `/sys/module/ak39_venc/parameters/pool` = `9600K`;
    dmesg `pool 9600 KiB at 0x81800000 (CMA)`; `/dev/uio0` present; no Oops.
  - `tc100_rtsp.log`: `encoder pool: 9830400 bytes (ak39_venc.pool), no guard at its start`.
    **Main H.265 + sub H.264: used 8866880, free 963520** (main alone 7946976). **Main H.264 + sub H.264: used 7946976 / 8866880, free 963520** (identical), both `open`.
    Back to H.265: both reopen. Smallest free 963520 >= 256 KB: PASS.
  - `MemAvailable` 21.6-22.0 MB at 2-4 min (rc8 default pool: 19.2 MB): about +2.4 MB, as expected. 25 fps, STAT cap ~125, dropped 0-3 per 5 s.
  - How the codec was switched without a browser: `rwconf /mnt/config/rtspserver.conf w 0 codec 0|2` then `/mnt/controlscripts/rtsp-h26x restart`.
  - Tester incident (not a firmware fault): a recursive `grep -r` over /etc and /mnt/lib that I ran on the serial console never returned and
    ^C had no effect; the camera still answered ping/HTTP. The owner power-cycled it. Avoid heavy recursive commands on the console.
  - Still to do: 1 h with Frigate (soak started 06:11 UTC, read at ~07:10 UTC), snapshot, sub-stream recording. Then: card files renamed back, flash boot.
  - Request for the implementer: if the hour passes, make 9600K the default of patch 0015 (rc9).
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

- **Result 2026-10-30 19:45, IPCAM2, f9c3d81, owner looking at the LED: case (b) for both colours.** At the start:
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


## From: Hardware use and memory (2026-10-30, commits `[hwaccel] ...`)

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
- **Result 2026-10-30, IPCAM2 (.11), build 44558cd (CI run 41032639092), kernel of the same build booted once from
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
- **Result 2026-10-30 evening, IPCAM2, build f9c3d81 (CI run 41089089376), installed in the flash of IPCAM2 (.11) with update66.sh, settings kept:** step 1 (default): `encoder pool: 3456000-byte guard at
  its start (phys 0x81800000)`, about 1.0 MB per 5 s, **no `pool guard:` report**. Step 2 (`RTSP_POOLPAD=0`, pool
  used 7946976 / 8866880 = the failing HW-01 layout): **streams normally for 5 min** (59 STAT lines, lowest 0.90 MB
  per 5 s after the first). And the 44558cd CI binary that failed this morning (md5 c66a4edf...) also streams
  normally on this kernel (15 STAT lines, 0.86-1.03 MB). **The HW-01 failure is not reproduced**: it was not the
  pool layout of `tc100_rtsp` alone. It happened on the 44558cd kernel, in the session that ended with the Wi-Fi
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
- **Result 2026-10-30, IPCAM2, build 44558cd, test 1 (default): passed for memory.** dmesg `video encoder: ...
  pool 12288 KiB at 0x81800000 (CMA)`, MemTotal 59436 kB (47164 before), MemAvailable 10.8 MB (unchanged), no OOM,
  video 15 fps with the rc5 `tc100_rtsp` (which keeps the 3.4 MB copy at the start of the pool). Test 2 not run
  (needs HW-01). See HW-01: the area at the start of the pool may be the one being overwritten.
- **If it passes:** put the measured size in `flashargs` / `stock-hook.sh` (U-Boot environment: ask the owner first),
  or as the default in the device tree (`anyka,pool-size` is not used for CMA; change `reg` size or add a default in
  the driver).

### HW-03 USB host: FIFO data in 32-bit words (kernel patch 0013, `otg_hs.fifo32=1`) — `to test`
- **Result 2026-10-30, IPCAM2: Wi-Fi dead after the 44558cd kernel, survives resets.** The 44558cd kernel (fifo32
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
- **Result 2026-10-30 evening, IPCAM2, after a power cut:** Wi-Fi back. 3 cycles "f9c3d81 kernel booted from the
  card with a stream, then `reboot` into the rc5 kernel": Wi-Fi associates every time (about 16.5 s). Then f9c3d81
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

### Looked at and not possible / not done (2026-10-30)
- **SD card 4-bit bus:** the SD controller's data lines 2-3 are GPIO 80 / 81, the IR-cut filter on the TC100
  (OpenIPC device tree `mci0_pins`: 0x1f-0x22 and 0x50, 0x51). The card stays 1-bit.
- **USB DMA:** see HW-03.
- **3D noise reduction:** its reference frame (6.2 MB) did not fit the capture CMA area. Tried again in rc9 (R9-01):
  reserved at boot with `ak39_vi.nr3d=1` and a 24 MiB CMA area, card test kernel.
- **Anti-flicker (`POWER_HZ`):** the 2.x firmware set it through the vendor library (`ak_vpss_effect_set(6, hz)`).
  The ISP's own auto exposure has the means (`exp_step` of `AK_ISP_AE_ATTR`): done that way in rc9 (R9-03).


## From: New features using the freed CPU (2026-10-30, commits `[feat30] ...`, `[live] ...`)

### F-02 Frame rate select (Streams & audio) — `to test`
- **What:** 10 / 12 / 15 (default) / 20 / 25 fps for both streams, `-f` from `rtspserver.conf [0] fps`; other values
  mean 15. A camera holding 20 or 25 there from an old preset changes rate at the next stream restart.
- **Test:** each rate: log `sensor: N fps`, STAT `cap` = N x 5 per 5 s, keyframe interval, CPU and Wi-Fi at 25.

### F-05 Logs kept across reboots (`scripts/log-persist.sh`, on by default) — `failed` on rc7 (octal boot counter), fixed in rc8: `to test`
- **What:** dmesg, syslog, `tc100_rtsp.log` and tails of the other logs to `/mnt/sd/logs/boot-NNNN` 120 s after the
  start, every 10 min and before a reboot from the web UI (`reboot-tracker.sh intent`); last 5 boots, about 2 MB
  each; skipped when the card is not vfat/exfat, ejected / recording paused, unhealthy or under 64 MB free. A bare
  `reboot` in a shell and a panic keep only the last 10-minute copy. Logs page: "Logs of previous boots".
- **Test:** files appear after about 2 min; reboot from the UI gives a `why=shutdown` save and `boot-0002`; nothing
  written while ejected; card writes over a day are small. **Off:** `LOG_PERSIST=0`.
- **Result 2026-10-30, IPCAM2, f9c3d81:** `/mnt/sd/logs/boot-0001` and `boot-0002` created about 120 s after the
  start, each with dmesg.log, meta.txt, other.log, syslog.log, tc100_rtsp.log. Boots rebooted before 120 s leave no
  folder (as described). UI reboot (`why=shutdown`) and the eject case not tried yet.


## From: Tester's accepted proposals (2026-10-30 night, build 3.0.1-rc7)

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

### P-07 Wi-Fi: RX aggregation and USB interrupts — `to test` (measurement only)
- **What:** `rtl8xxxu.dma_aggregation=1` on the kernel command line (from the card, `EXTRA` of `boot66b.sh`); no code
  change. The driver has no power-save path for this chip, so there is nothing to switch there.
- **Test:** `perf-baseline.sh 60` without a client, then with one, then the same with `dma_aggregation=1`. Look at
  interrupts/s of the USB host, and softirq. Throughput: VLC stays smooth.

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

## 2026-11-01 — Rustine blanc de la .24 (temporaire, SD + rtsp.env)

- But : la .24 garde un bon blanc (rex 600 / bex 760) jusqu'à la version avec la boucle corrigée.
- Mis en place sur la .24 seulement : `/mnt/sd/awbx` (outil, md5 bd8da617…), `/mnt/config/awb.off` (boucle logicielle coupée),
  `/mnt/config/rtsp.env` = une ligne qui lance `sleep 25; /mnt/sd/awbx set 600 760` en tâche de fond à chaque (re)démarrage de tc100_rtsp
  (rtsp.env est sourcé par rtsp-launch.sh juste avant l'exec). Sauvegarde : `/mnt/sd/rtsp.env.before-awb-2026-11-01`.
- Vérifié : `rtsp-h26x restart` (sans reboot) → `awbx get` = 600/760 ; snapshot R/G 1.08, B/G 0.96 (identique à g600 ; rc16 d'origine : 0.95 / 0.58).
- Retour arrière : vider rtsp.env, supprimer config/awb.off, `rtsp-h26x restart`.
- Pour l'implémenteur : à retirer dès que la boucle globale (clamp ~1536, gains de départ sauvegardés) est installée ; sans carte SD la rustine ne fait rien (le test `-x` protège).
- Non testé : après un vrai reboot (clé ssh à remettre par le propriétaire) ; de nuit (IR, couleurs sans objet).

## 2026-11-01 — Écarts .11/.24 : LED et luma (décision du propriétaire)

- .11 : `FRONT_LED=0` dans boot.conf (LED bleue éteinte tout de suite, `front_led status` = OFF) ; la .11 a donc le même réglage que la .24.
- .24 : `config/daynight.conf` créé avec `DAYNIGHT_SOURCE=luma` (le journal daynight montrait déjà `src=luma` par défaut : le fichier ne fait que rendre le réglage explicite et identique à la .11).
- Restent différents, non touchés : `ISP_TUNE`, `MQTT_ENABLE` (.11 seulement), `button-actions` (.11 seulement), `IRCUT_*_GPIO` (matériel .24).

## 2026-11-01 — MQTT sur la .24 (déjà actif)

- Le MQTT de la .24 était déjà activé : `config/mqtt.conf` a `MQTT_ENABLE=1`, broker 192.168.1.25, topics propres (`tc100/cam2`, client `tc100-cam2`) ; le pont tourne et `/tmp/mqtt_last_pub.status` = ok, publication il y a moins de 5 min (idem .11 : `tc100/camera`).
- Écart réel : seule la .11 a une ligne `MQTT_ENABLE=1` en trop dans `boot.conf` (sans effet, c'est mqtt.conf qui compte). À nettoyer par l'implémenteur : une seule source du réglage (propositions : ignorer ou supprimer la clé dans boot.conf).
- Reste différent, volontairement : `ISP_TUNE`, `button-actions` (.11 seulement), `IRCUT_*_GPIO` (matériel .24).


## From: 2026-11-01 — Lot 1A (implémenté, zéro U-Boot / zéro noyau) : AWB global, clés SSH persistantes, mode derrière une vitre, amixer hw:0

### 2. Clés SSH (`authorized_keys`) et clé d'hôte Dropbear persistantes à travers les reboots
- **Quoi :**
  - `v3/S50dropbear-linux66` et `controlscripts/ssh-server` restaurent `/root/.ssh/authorized_keys` depuis `/mnt/config/authorized_keys` (permissions `0700`/`0600`) et `/etc/dropbear/dropbear_ed25519_host_key` depuis `/mnt/config/dropbear_ed25519_host_key`.
  - Si une clé est ajoutée à chaud dans `/root/.ssh/authorized_keys`, le démarrage/arrêt de `ssh-server` et `v3/linux66-sd/cfg-persist` (`sync_ssh`) la copient automatiquement dans `/mnt/config/authorized_keys` avant d'écrire la partition `cfga`/`cfgb`.
- **Test :**
  1. Vérifier que `/root/.ssh/authorized_keys` est présent, lancer `/mnt/v3/linux66-sd/cfg-persist save`, vérifier que `/mnt/config/authorized_keys` et `/mnt/config/dropbear_ed25519_host_key` existent.
  2. Après un redémarrage, vérifier que `ssh root@<ip>` se connecte sans mot de passe et sans avertissement `REMOTE HOST IDENTIFICATION HAS CHANGED`.

# Moved from test-queue.md on 2026-11-06

### rc7 (`4e5d534`, CI run 41120278897) on IPCAM2, 2026-10-30 night: LED-01 fixed, S-01 passed, nothing blocking

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
     mixer settings), and the effect of the pin fix 0a224b8 on GPIO 14. Microphone not tested here (`tc100_rtsp` holds the
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
1. The packages of 44558cd and f9c3d81 still say `3.0.1-rc5` (same as the morning build): bump `VERSION` (rc6) so the
   cameras and the update page can tell them apart.
2. HW-01b: the cause of the morning failure is unknown (44558cd kernel or the degraded state of that session). Keep
   the guard as a detector (it costs nothing while the pool is not shrunk); revisit with HW-02 test 2.
3. The serial console shell (`tc100test/consoleshell`) has no `CURL_CA_BUNDLE`/ext `PATH`: `curl` there exits 60.
   Harmless for the services; give login and console shells the same environment if it is cheap.
4. Next on the camera (in this order unless told otherwise): an overnight soak of f9c3d81, HW-02 test 2, HW-03
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

## 2026-11-01 — .11 alignée sur la .24 (flux)

- `/mnt/config/rtspserver.conf` de la .11 remplacé par celui de la .24 (seules différences qui existaient : sous-flux 352x200 8 i/s 400 kb/s → 640x360 25 i/s 250 kb/s ; `smartmode=1` → 0 ; clés `smart=0`, `vbr=0` ajoutées). Sauvegarde : `xfer17/rtspserver.conf.11.before-2026-11-01` (Mac).
- Choix du propriétaire : Frigate fait la détection → compromis simple, mêmes valeurs sur les deux caméras ; débit du sous-flux à relever pour les deux plus tard si le Wi-Fi de la .24 se stabilise.
- Vérifié après `rtsp-h26x restart` : flux principal H.265 1920x1080 25 i/s ; /video1 H.264 640x360 25 i/s, ~230 kb/s mesurés (STAT sub_bytes), 0 perte, ping OK.
- Écarts restants (volontairement non touchés, à décider) : boot.conf `ISP_TUNE` (.11=0, .24=1), `FRONT_LED` (.11=1, .24=0), `MQTT_ENABLE=1` seulement sur la .11, `IRCUT_*_GPIO` seulement sur la .24 (matériel), `daynight.conf DAYNIGHT_SOURCE=luma` seulement sur la .11, autostart `button-actions` seulement sur la .11.

## 2026-11-03 — rc18 sur la .11 (installée par le propriétaire) : premières vérifications par ssh (testeuse, sans console série)

Build : `3.0.1-rc18` (artifact `tc100-3-release` du run du commit 160895f). Le propriétaire a installé la rc18 sur la .11 avant moi ; la .11 n'a PAS de carte SD (test R12-08 / R15-04 en cours) ; uptime 1 h 17 au moment du relevé.

- **Clés ssh persistantes : OK.** Après le reboot de l'installation ma clé (RAM) avait disparu, le propriétaire l'a remise à la main dans `/root/.ssh/authorized_keys` à 09:02 ; `cfg-persist` l'a recopiée tout seul dans `/mnt/config/authorized_keys` (3 clés, 212 octets) et la clé d'hôte est dans `/mnt/config/dropbear_ed25519_host_key` (83 octets, 09:00). La connexion par clé fonctionne. **À confirmer au prochain reboot** : clé et clé d'hôte revenues sans action, pas d'avertissement « HOST IDENTIFICATION HAS CHANGED » sur le Mac.
- **Balance des blancs : OK sur la .11.** `white balance: in the ISP (extra gains max 1536, grey filter 1)` ; `/tmp/cam_awb` : `rex=221 bex=299 u=0 v=1` ; `/mnt/config/awb.state` = `221 299` (écrit à 08:06). Snapshot (mur et pièce) R/G 1,02, B/G 1,00 (critère ±5 % : passé). Reste à voir : le redémarrage de `rtsp-h26x` (ligne `starting from saved gains`) et la .24 (rex≈600 / bex≈760 attendus).
- **Autre : OK** — `MemAvailable` 21 992 kB, charge 1,1 à 1,3, `tc100_rtsp` stable (`dropped 0`), pas de plantage au noyau, MQTT publie (`mqtt_last_pub.status` ok, âgé de 3 s), `FRONT_LED=0` conservé, `MQTT_ENABLE` plus dans `boot.conf`, `mdnsd` arrêté (désactivé par défaut, comme prévu), `rtsp.env` vide.
- **Constaté :** la ligne de commande du noyau contient `ak_wdt_reboot=300` : le chien de garde matériel existe donc (réponse à ma question dans l'avis sur AGENTS.md ; à confirmer par l'implémenteur qu'il est armé par l'init).
- **Pas encore testé sur la .11 :** mDNS, qualité Wi-Fi (`WIFI_QUALITY=1`), mode babyphone, sabotage, notifications, mode vitre, métriques Prometheus. La carte SD manque pour les journaux persistants et `/tmp/sd-health`.
- **Remarque de version :** la rc18 a été construite au commit 160895f ; les commits suivants (fin du lot 2, lot 3, lot 5, interface) ne sont pas dedans alors que `VERSION` dit toujours `3.0.1-rc18`. Demande à l'implémenteur : numéroter la prochaine construction rc19.

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

## 2026-11-03 11:10 — Testeuse : la CI Python est rouge depuis 0a72361 (rc19 comprise)

Le workflow « CI » (`Host regression tests`) échoue sur 0a72361, a680f8f, aaec458, d0d2240 (rc19), 72c5475, 441890d, af38d3a et a23b217, alors que la compilation du noyau et du paquet réussit. Tests en échec (journal du run 41615464487) : `test_regressions.ActionCommandFiles.test_every_command_is_routed_to_the_file_that_has_it`, `Regressions.test_motion_form_fields_are_read`, `WebUiLanguage.test_every_ui_string_has_a_translation` (chaînes sans traduction), `test_webui_wiring.WebUiWiring.test_every_form_field_is_read_by_its_handler` (+ une erreur JSON). Ce sont des défauts de branchement de l'interface web des nouveaux lots (lot 3 et suivants, pas dans la rc18). **Demande :** corriger avant de tester la rc19 sur les caméras ; la testeuse n'installe pas une version dont la CI de régression est rouge, sauf accord du propriétaire.

## 2026-11-03 12:40 — Testeuse : rc20 (commit 01a6311) récupérée, relue avant installation

- Paquet : artifact `tc100-3-release` du run 41624580550 (build réussi) ; `tc100-3.0.1-rc20-update.tar` md5 `e914a72a940f5f8f732cad3d4467b0c3` (6 195 200 octets), `-sd.zip` md5 `ba8c0a1ba4a2e64101011eff8751bfb7`, `VERSION` = 3.0.1-rc20. Sur le Mac du propriétaire : `~/Downloads/tc100-fix/xfer20/`.
- **CI Python rouge sur 01a6311 et a6c2cdb** (un test : `test_regressions.SettingsByUse.test_local_recording_commands` : la liste des commandes de lecture de `action.cgi` attendue — `wifi_get_ssid|wifi_rescue_info|local_rec_status|sd_card_info|md_zones_info|rtsp_server_info) ;;` — n'est plus dans le fichier : un nouveau `motion_heatmap` / `sd_card_check` a changé la ligne). Le noyau et le paquet sont construits. La testeuse installe quand même sur la .11 (le propriétaire l'a demandé) mais le test doit être corrigé avant le tag.
- **WebDAV (`controlscripts/webdav`) : ce n'est pas du WebDAV.** Le service lance `busybox httpd` (`-p 8080 -h <dossier> -c /etc/httpd.conf`) : serveur de fichiers statique en lecture, sans `PROPFIND` ni `OPTIONS` WebDAV ; le Finder de macOS ne pourra probablement pas le monter comme volume (un navigateur ou `curl` lira les fichiers). Bon point : `/etc/httpd.conf` impose un identifiant (`/:root:<hash>`), donc pas d'accès sans mot de passe ; l'authentification est celle de la caméra, en clair sur le réseau local (HTTP). À corriger dans la doc/l'interface (« partage de fichiers HTTP en lecture seule ») ou à remplacer par un vrai serveur WebDAV minimal ; désactivé par défaut, à garder ainsi.
- **Auto-réparation de la carte (`sd-diag.sh repair`)** : `fsck.fat` n'est pas dans l'image (constaté sur la .11) ; le script retombe alors sur un remontage en lecture-écriture, sans réparation réelle. L'intitulé « auto-repair » promet plus que ce qui est fait. À tester avec une carte (non réalisable sur la .11 sans carte).

## 2026-11-03 13:00 — RÉSULTATS rc20 (01a6311) sur la .11 / IPCAM2 (testeuse, ssh, sans carte SD, installée par la mise à jour web du propriétaire)

Compte rendu pour l'implémenteur. La rc20 est dans la flash (`/rom` = `mtdblock5`, `flashroot=1`, `VERSION` 3.0.1-rc20), uptime 11 min au relevé. Le propriétaire installe maintenant la rc20 sur la .24 (compte rendu à suivre).

**PASSÉ**
- **Clés ssh persistantes (af38d3a + ce65ece) :** après le reboot de la mise à jour, ma clé (installée par le propriétaire pendant la rc18) fonctionne sans action ; `/mnt/config/authorized_keys` (318 octets) et la clé d'hôte (`SHA256:GWE6XVUH…`) inchangées : pas d'avertissement « host key changed ». À repasser après un reboot sur la .24 (première installation de ce mécanisme).
- **ssh interactif :** `devpts` monté (1 ligne dans `/proc/mounts`) ; plus de coupure de session après le mot de passe (le propriétaire avait eu une session qui tombait sur la rc18).
- **Balance des blancs globale (ce65ece) :** au démarrage `white balance: starting from saved gains rex 219 bex 291`, puis `rex=224 bex=295 u=0 v=0` (`/tmp/cam_awb`), `awb.state` écrit (`219 291`). Snapshot après reboot : R/G 1,00, B/G 1,01 (critère ±5 % passé, mur neutre dès le début). Gains conformes à ce qu'on attendait pour la .11 (≈230/287).
- **Suivi Wi-Fi (`WIFI_QUALITY=1`) :** redémarre seul avec la caméra (11 relevés en 11 min, `/tmp/wifi-quality` écrit). Surveillance de la valeur `rssi` : -42 en essai manuel, -16 au relevé du boot, -50 dans les métriques : vérifier que `wifi-quality.sh` et `metrics.cgi` lisent la même grandeur.
- **mDNS (`tc100-mdnsd`) :** répond (unicast) à `ipcamera2.local`, RSS 8 Ko, CPU 0 %. Multicast depuis le Mac du propriétaire encore à confirmer. Nom = `hostname.conf` (pas `ipcam1.local` comme dans les notes).
- **Prometheus (`metrics.cgi`) :** 200 en 0,39 s avec mot de passe, 401 sans ; toutes les métriques présentes.
- **Babyphone / Vox :** `ENABLE=1` ET `VOX_MODE=1` nécessaires dans `sound_detection.conf` (doc à corriger) ; ton 1 kHz au haut-parleur : niveau -53 → -18 dBFS, `tc100_vox_active` 1 puis 0 (~10 s). Le niveau (`/var/run/sound_level`) est mesuré dès le boot.
- **Mémoire et stabilité :** `MemAvailable` 21,9 Mo après reboot, charge 0,8, flux principal stable (`dropped 0`), aucun plantage au noyau.

**ÉCHEC / À CORRIGER**
1. **Sabotage sur la rc18 : ne se déclenchait jamais de jour** (luma ≈ 127 même objectif couvert, l'exposition compense). Corrigé par a23b217 (taille JPEG + exposition) ; **nouvel essai en cours sur la rc20** (main sur l'objectif, de jour) — résultat à suivre. Baseline mesurée : 103 057 octets.
2. **Synchro « Push » (530514d) :** deux défauts probables, voir l'entrée « relecture de 530514d » (identité MQTT écrasée ; requête inter-caméras bloquée par CORS). **Non testée** tant que ce n'est pas corrigé.
3. **WebDAV :** ce n'est pas du WebDAV (busybox httpd statique, pas de PROPFIND) : le Finder ne le montera pas. Non testé (désactivé par défaut) tant que le nom/la doc ne sont pas corrigés.
4. **Auto-réparation de la carte :** `fsck.fat` absent de l'image ; « repair » = remontage seulement. Non testable sans carte (la .11 n'en a pas en ce moment).
5. **CI Python rouge sur 01a6311 / a6c2cdb** (un test `test_local_recording_commands`, voir l'entrée précédente).
6. **Documentation :** note d'installation de la rc20 : les interrupteurs doivent être décrits complètement (Vox : `ENABLE` + `VOX_MODE` ; sabotage : `TAMPER_DETECT` dans `boot.conf` ET `ENABLE` dans `tamper.conf`, ce dernier prioritaire ; `hostname` pour mDNS).

**PAS ENCORE TESTÉ sur la .11** (précision) : notifications Ntfy/webhook (aucun canal configuré), mode « derrière une vitre » (essai de nuit), entité caméra MQTT (Home Assistant), meilleur cliché, zones nommées, pre-roll, carillon/sirène (`play_sound`), alarme fumée, vue 2×2, présélections OSD, frise 24 h (demande la carte), carte de chaleur, anti-scintillement 50 Hz.

**Prochains essais testeuse :** retest du sabotage (en cours), puis rc20 sur la .24 (balance des blancs avec gains ≈ 600/760 attendus : critère R/G et B/G à ±5 %, clés ssh après reboot, mode derrière une vitre la nuit). Rappel : la .24 porte encore ma rustine (`awb.off`, ligne `awbx` dans `rtsp.env`, outil sur sa carte SD) : à retirer avant l'essai de la balance des blancs.

## 2026-11-03 13:25 — RÉSULTATS rc20 (01a6311) sur la .24 / IPCAM1 (testeuse, ssh, carte SD présente)

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

## 2026-11-03 13:50 — .11 : surexposition après reboot + mDNS (testeur)

- **Surexposition .11** (rc20, uptime ~7 min au moment du constat, reboot 12:37 UTC) : snapshot 12:44 UTC quasi blanc (luma 241-244, 81 % des pixels >240), `cam_ae` = `236 1124 484 256 256 0 1125`. Deux minutes plus tard, sans aucune action de ma part : luma 123, `cam_ae` = `47 137 256 …`, image normale. Donc **transitoire post-boot** : l'AE met plusieurs minutes à converger après démarrage (partait d'un gain/expo maximal ?). Teinte légèrement violette juste après le boot (rex=226 bex=296), à surveiller.
  - Demande à l'implémenteur : au démarrage de tc100_rtsp, initialiser l'AE sur une exposition moyenne (ou accélérer la convergence) ; critère : luma < 200 dans les 30 s après boot sur la .11.
  - .24 non concernée (luma 140 à la même heure).
- **mDNS** : le service est **off par défaut** → `ping ipcamera2.local` = "unknown host" est attendu tant qu'il n'est pas démarré. Démarré à la main sur la .11 (`tc100-mdnsd -i wlan0`, nom = hostname.conf = IPCAMERA2) ; le démarrage manuel ne survit pas au reboot. À décider : activer `config/autostart/mdns` par défaut (léger) ? Retest ping depuis le Mac du propriétaire en attente.

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

Build `50a642e` (CI verte), `tc100-3.0.1-rc21-update.tar` md5 `8383e2e65e9539de78e45fac9732fba5`, installée par le propriétaire via l'update web sur les 2 caméras.

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
3. CI rouge sur e0e9ea0/a9a0499 (test classes CSS `has-text-weight-semibold`) à remettre au vert avant de qualifier la rc23 stable.
4. Constat à 21:50 UTC sur la .24 : `STAT cap 51` pour ~4 s (fps réduit en soirée, expo 2810) vs .11 `cap 122` ; à expliquer (limite de temps d'exposition de nuit ?).

Campagne de nuit : échantillonneur sur le Mac du propriétaire toutes les 2 min (uptime, RAM, luma, AE, AWB, ping passerelle, fps, awb.state) dans `night.log` + un snapshot / 30 min. Dépouillement demain matin (reboots, dérive mémoire, bascule jour/nuit, retour des couleurs, fréquence d'écriture awb.state). Anti-masquage reporté (main du propriétaire).

### Complément 23:05 — enregistreur de nuit et awb.state (testeur)
- L'échantillonneur côté Mac n'a pas survécu (processus de fond tués entre deux appels) : remplacé par `/tmp/nightcam.sh` **sur chaque caméra** (RAM, 1 ligne / 180 s dans `/tmp/night.log` : uptime, RAM, luma, AE, AWB, awb.state, load, ping passerelle, fps, IR). Perdu si reboot (détecté par l'uptime). Dépouillement demain matin.
- `awb.state` est réécrit environ toutes les 2 min mais `/mnt` est un **tmpfs** : pas d'usure flash par cette écriture. Reste à vérifier demain que la copie persistante (cfg-persist vers cfga/cfgb) n'est pas déclenchée à chaque écriture.

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

## 2026-11-04 11:05 — Relecture testeur de 1df225a / 1ea1a8c / 6290696 (pas encore de rc24)

CI verte sur `3472f1d`. Relu, rien de bloquant ; mes correctifs d'hier sont intacts (validation MQTT/Telegram, import en une passe, fps).
- **`wifi-quality.sh` (1df225a) : la source du signal est mal choisie.** Mesures du matin (`iw dev wlan0 station dump`, rtl8xxxu) : .24 `signal: 0 dBm`, `signal avg: -13 dBm`, `beacon signal avg: -51 dBm`, `/proc/net/wireless` -49, débit 19,5 Mbit/s MCS 2 ; .11 `signal avg: -25`, `beacon signal avg: -20`, `/proc` -31, 72,2 Mbit/s. `signal avg` est faux sur la .24 (-13 dBm avec MCS 2 est impossible) ; **`beacon signal avg`** concorde avec /proc et le débit. Proposition : lire `beacon signal avg:` (repli `signal avg`, puis /proc). Le passage sous `timeout` (iw 5 s, ping 8 s) répond bien au log figé de la .11.
- `frigateyaml` avec `{FRIGATE_RTSP_PASSWORD}` : OK ; à mentionner dans le CHANGELOG (une config collée telle quelle demande désormais la variable d'environnement côté Frigate).
- `no-https` (1ea1a8c) : sur 3.0 le web n'a jamais servi de HTTPS (busybox httpd), donc pas de régression pour une installation existante ; le bundle CA des connexions sortantes reste fourni par Buildroot (`/mnt/ext/etc/ssl/certs/ca-certificates.crt`, `CURL_CA_BUNDLE`), la suppression de `config/ssl/cacert` ne touche pas ntfy / GitHub / Telegram. À vérifier sur caméra avec la rc24 : `update-check.sh` et une notification ntfy.
- Toujours en attente : **rc24** (VERSION est encore 3.0.1-rc23) pour tester tout cela sur les deux caméras.

## 2026-11-04 — Version 3.0.1-rc24 (correctifs de l'audit, constats de la nuit rc23, HTTP seul)

- **Paquet :** artefact `tc100-3-release` du run CI du commit `[release] Bump to 3.0.1-rc24` (`tc100-3.0.1-rc24-update.tar`, mise à jour web : Outils → Mise à jour et sauvegarde). **Noyau inchangé depuis la rc23** (aucun patch noyau). La mise à jour web vérifie le noyau avant d'écrire (taille lue dans l'environnement U-Boot de chaque caméra).
- **Contenu depuis la rc23 :**
  - correctifs de l'audit (testeur, 2026-11-04 01:00) : `4c21283` purge Bulma, `f3568c4` refus des caractères dangereux MQTT/Telegram, `104c65d` import JSON en une passe (12-15 s), `64fa7a2` fps annoncés (25), `9cd90f8` tests ;
  - `1df225a` [night-fixes] : `wifi-quality.sh` sous `timeout`, services coupés affichés `disabled`, carte SD remontée en lecture seule avant un redémarrage volontaire et à la fin d'une mise à jour web, `{FRIGATE_RTSP_PASSWORD}` dans le YAML Frigate ;
  - `a3fd7e7` [wifi-beacon] : signal Wi-Fi = `beacon signal avg` ;
  - `1ea1a8c` [no-https] : HTTP seul (port 80), restes 2.x HTTPS / modes web / `config/ssl` supprimés ; README : HTTPS par un proxy (`6290696`) ;
  - commits du propriétaire après le bump rc23, s'ils n'étaient pas dans la rc23 installée : `921d525` vidéo fluide lancée d'office (tableau de bord, Réglages, multi-vue), `a88efdc` README.
- **À tester sur les deux caméras (ordre conseillé : la .11 d'abord, la .24 le lendemain) :**
  1. Installation par la mise à jour web : `VERSION` = 3.0.1-rc24, redémarrage, pas de mode sans échec (`boot-guard status` → `count=0` après 5 min), `dmesg | grep FAT` : **pas** de « not properly unmounted » sur la .24 après ce redémarrage.
  2. Entrées détaillées plus haut : `[night-fixes]` (2026-11-04), `[wifi-beacon]`, `[no-https]`, et les points de l'audit (refus `a b` / `$(reboot)` dans MQTT et Telegram, import JSON ≤ 15 s, 25 fps dans le YAML Frigate et le manifeste).
  3. `WIFI_QUALITY=1` une nuit sur les deux : journal écrit jusqu'au matin, `rssi` ≈ `beacon signal avg`, pertes de ping comparées à la nuit rc23 (7-11 %).
  4. `health.cgi` : `memory-guard` = `disabled`, aucun compteur de redémarrage qui monte pour un service coupé.
  5. Vérification de mise à jour et une notification Ntfy ou Telegram de test (certificats du système après la suppression de `config/ssl`).
  6. Propriétaire : interface derrière son proxy HTTPS, vidéo fluide comprise.
- **Critères :** 1 à 6 conformes, aucune régression par rapport à la nuit rc23 (pas de redémarrage, RAM stable ~20 Mo, bascule jour/nuit).

## 2026-11-04 — Origine des binaires préconstruits ; surexposition au démarrage close (`[credits]`)

- **Binaires :** `rwconf`, `getflag`, `getimage` = sources publiques (Unlicense) de `anyka-v4l2rtspserver/libv4l2cpp` (ThatUsernameAlreadyExist), construites par `tools.sh` de `anyka-software` ; `monvifd` = binaire du même auteur (« Micro ONVIF discovery service v1.1 », publié en 2023 dans son hack JCO-PM203 puis TC100), sans source ni licence. Détail dans `CREDITS.md`. Proposé après la 3.0.1 : reconstruire les trois premiers en CI, remplacer `monvifd` (ONVIF coupé par défaut).
- **Surexposition après démarrage (.11, rc20) :** plus revue par le propriétaire depuis ; close comme cas isolé, à rouvrir si elle revient (critère : luma < 200 en 30 s après le démarrage).
- Pas de test caméra.

## 2026-11-04 18:20 — rc24 téléchargée (testeur) : deux paquets portent le même nom

- `73493c8` (bump rc24, paquet désigné par le plan de test) : `tc100-3.0.1-rc24-update.tar` md5 `5c9c264201c3d70a44874181aafd6ca8` → `~/Downloads/tc100-fix/xfer24/` sur le Mac du propriétaire.
- `a64823a` (rc24 + `[license]`, `[credits]`, `[wifi-country]`, `[mqtt-c]`, `[audit]`) : `VERSION` dit aussi **3.0.1-rc24**, md5 `0f7abf39b6f95300045757cddd7ff7b9` → `xfer24-latest/`.
- **Demande à l'implémenteur** : ne pas publier deux contenus sous le même numéro ; si `a64823a` est la version à tester (elle contient le correctif RTSP H1 et les changements de démarrage `S39tc100`/udhcpc), la renuméroter **rc25**. Sinon, le testeur installe `xfer24` d'abord, puis la suivante sous un nouveau numéro.
- Je n'ai trouvé aucun détail dans le dépôt sur la « CVE-2026-98432 » citée dans l'entrée rc24 (« décision du propriétaire en attente ») : décrire le problème, le patch et le risque pour que le propriétaire puisse décider.

## 2026-11-04 — Version 3.0.1-rc25 (remplace la rc24 : un seul paquet par numéro)

- **Réponse au testeur (18:20) :** oui, `a64823a` devait être renuméroté ; c'est fait. La rc24 n'est plus à tester : la rc25 la contient entièrement. Ne pas installer `xfer24-latest/` (contenu rc25 sous le numéro rc24).
- **Paquet :** artefact `tc100-3-release` du run CI du commit `[release] Bump to 3.0.1-rc25` (`tc100-3.0.1-rc25-update.tar`, mise à jour web). **Noyau inchangé depuis la rc23.** **Initramfs modifié** (`regulatory.db`, `S39tc100` : pays Wi-Fi, nom DHCP, `udhcpc -T 1`) : la mise à jour web l'écrit comme à chaque version.
- **CVE-2026-98432 :** le dépôt ne contient rien d'autre que la mention « décision du propriétaire en attente » (entrée rc24) : ni description, ni patch, ni source. L'implémenteur ne peut pas la documenter sans la source de cette mention ; le propriétaire la fournit (note du projet claude.ai ?) ou la mention est retirée. Rien n'a changé dans le noyau à ce sujet.
- **Contenu depuis la rc24 :** `1005b38` [license] GPL-2.0 ; `20f69f8` [credits] origine des binaires préconstruits ; `0b11fbf` [wifi-country] ; `6f53bb0`/`48c1596` [mqtt-c] (`MQTT_BRIDGE_IMPL=shell` par défaut) ; `a64823a` [audit] (H1 RTSP, W1 XSS, W5 mot de passe en mode sans échec, B2 ordre console/Wi-Fi dans S39, CI).
- **À tester sur les deux caméras (la .11 d'abord) :**
  1. Installation par la mise à jour web : `cat /mnt/VERSION` = 3.0.1-rc25 ; redémarrage ; `boot-guard status` → `count=0` après 5 min ; `dmesg | grep -i -E 'regulatory|FAT'` : pas de « failed to load regulatory.db », pas de « not properly unmounted » (.24).
  2. Le plan rc24 (entrée « Version 3.0.1-rc24 », points 1-6) sur la rc25.
  3. Entrées `[wifi-country]` (pays FR sans coupure, Wi-Fi au démarrage, « Se connecter à ce réseau » sans faux message d'erreur), `[audit]` (flux RTSP TCP/UDP et voie de retour, pages d'erreur, `showlog`, mode sans échec, console).
  4. `[mqtt-c]` sur **une** caméra seulement (`MQTT_BRIDGE_IMPL=c`), l'autre en témoin avec le pont shell.
  5. Une nuit `WIFI_QUALITY=1` en FR sur les deux : pertes de ping comparées à la nuit rc23 (7-11 %).
- **Critères :** 1-5 conformes, aucune régression par rapport à la nuit rc23 (pas de redémarrage, RAM stable ~20 Mo, bascule jour/nuit).

## 2026-11-04 18:35 — rc25 téléchargée (testeur)

- Build `0cf0a5f` (CI et build verts) : `tc100-3.0.1-rc25-update.tar` md5 `58a786f84ba28e4e4c0db4a8c32a6f58`, `VERSION` 3.0.1-rc25 → `~/Downloads/tc100-fix/xfer25/` sur le Mac du propriétaire. Contenu = `a64823a` + bump (diff `a64823a..0cf0a5f` : CHANGELOG, VERSION, docs seulement). Les paquets rc24 (`xfer24`, `xfer24-latest`) sont périmés : ne pas les installer.
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

Tout ce qui reste ouvert après la rc25 est rassemblé, par priorité (P0 rc26 / P1 3.0.2 / P2), dans **`docs/linux-port/a-faire-implementeur.md`**. Premier point : publier une rc26 avec le correctif d'arrêt du pont MQTT en C (`3193705`, `9853759`).

## 2026-11-04 20:15 — rc26 relue et téléchargée (testeur)

- Build `e0020a5` (CI + build verts, seul build rc26) : `tc100-3.0.1-rc26-update.tar` md5 `95cc1c2ce46253077fcb11faef9eec4a` → `~/Downloads/tc100-fix/xfer26/`. Le `stack.sqfs` contient bien le `controlscripts/mqtt-bridge` corrigé (`MQTTD_PIDFILE`, arrêt par `pidof`).
- Relecture de `4972c5c` / `e0020a5` :
  - OK : CVE retirée ; `config/autostart/memory-guard` retiré (le service ne dépend que de `MEM_GUARD_ENABLE`, `service-switch.sh`) ; sur une caméra déjà installée, l'ancienne entrée reste dans `/mnt/config` (données de l'utilisateur), sans effet.
  - `MEM_GUARD_SOFT_SERVICES=""` était déjà vide dans la `.dist` ; c'est le `boot.conf` des caméras installées qui garde `"network-monitor"` (sans effet, service absent).
  - **Pas fait, coché à tort** : « mqtt.conf : documenté la règle de dérivation du topic root (`_mb_slug`) » : aucun changement de doc ; la règle n'est expliquée que dans le commentaire de `scripts/mqtt-bridge.sh:160-188` (client id par défaut `tc100-camera` → client id et racine = nom d'hôte en minuscules, `ipcamera2`). À écrire dans `config/mqtt.conf.dist` au-dessus de `MQTT_TOPIC_ROOT` et dans `docs/api.md`.
  - **P0 n° 2 pas fait** : `controlscripts/mqtt-bridge` garde `run_busybox nohup … &` (le sous-shell `sh mqtt-bridge start` reste en mémoire, 217 Ko) ; `S39tc100` redirige seulement les sorties de l'autorun (`</dev/null >/dev/null 2>&1 &`), ce qui ne supprime pas le `sh /etc/init.d/S39tc100 start` resté vivant — à vérifier sur caméra avec la rc26.
- Installation conseillée : la **.11** (demain matin, après le bilan de la nuit en cours, pour ne pas casser la mesure) ; la .24 reste en rc23.

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

.24 (rc25 depuis hier soir) : `FAT-fs … not properly unmounted` **encore** au démarrage qui a suivi la mise à jour web (le remontage en lecture seule de `1df225a` ne couvre pas ce chemin ?) ; jour/nuit 05:42 jour → 05:47 nuit → 06:28 jour (une bascule aller-retour à l'aube, hystérésis à surveiller) ; enregistrement SD actif (`rec 1`).

Conclusions : (1) pont MQTT en C **validé pour une nuit** (stable, pas de doublon, pas de reconnexion) → peut devenir le défaut après une deuxième nuit sur la rc26 ; (2) pertes Wi-Fi inchangées : pas le domaine réglementaire ; prochaines pistes : `RTSP_PACING_US`, canal Wi-Fi de la box, puis pilote `rtl8xxxu` (le ping se perd aussi quand le compteur iw n'a ni retry ni échec : côté réception ou blocage du pilote) ; (3) garder `RTSP_QMAX=1024` (aucun effet négatif vu) mais l'essai n'a pas de témoin.
Prochaine étape : rc26 sur la .11.
## 2026-11-05 19:05 — 3.0.1-rc27 (bump par le testeur, à la demande du propriétaire)

- **Paquet :** artefact `tc100-3-release` du run « Build Linux 6.6 » du commit `[release] Bump to 3.0.1-rc27`. Contenu : `184e1e5` (56 commits du 2026-11-05) + ce bump. Remplace le « rc26 » de `main` (le paquet rc26 testable reste `e0020a5`).
- **Installation décidée par le propriétaire : .11, en flash directement par la mise à jour web, sans carte SD.**
- **Plan (un changement à la fois, .11 seule) :** (1) mise à jour web, `VERSION` 3.0.1-rc27, boot-guard `count=0` après 5 min, tout ce qui tournait en rc25 tourne encore (RTSP principal/sous-flux/audio, Frigate, MQTT C, mDNS, pays FR) ; (2) `RTSP_PACING_US=100` (désormais par défaut) : une nuit, images sautées, pertes de ping, latence du direct ; (3) `NET_LAN_ONLY`, expiration des clients RTSP inactifs, limite d'essais du web : Frigate et HA inchangés ; (4) `ONVIF_IMPL` libre, puis `SUPERVISOR_IMPL=c`, puis `MQTT_DISCOVERY_IMPL=c` ; (5) WHEP en dernier.

## 2026-11-05 19:35 — rc27 sur la .11 (flash, mise à jour web, sans carte SD) : résultats (testeur)

| Contrôle | Résultat |
|---|---|
| `VERSION` 3.0.1-rc27, `flashroot=1`, boot-guard | OK, `count=0` après 8 min, mode normal |
| RAM / CMA | MemAvailable 22,7 Mo, CmaFree 6,5 Mo |
| Services | `tc100_rtsp`, `tc100-mqttd` (432 Ko), `tc100-mdnsd`, `httpfront`, dropbear, wpa_supplicant ; `health.cgi` : onvif, motion, memory-guard, ftp, telnet, telegram = `disabled` (juste) |
| **Sous-shells restés en mémoire (P0 n° 2)** | **réglé** : plus de `sh controlscripts/mqtt-bridge start` ni de `S39tc100 start` |
| Console série | plus de `getty` après 5 min (`SERIAL_CONSOLE=auto`) |
| `VM_TUNE` | `vfs_cache_pressure` 150, `min_free_kbytes` 1024 |
| Web | 9 pages (dont `hardware.html`) en 200 avec mot de passe, 401 sans ; snapshot 127 Ko, image normale |
| RTSP TCP | principal hevc 1920x1080 25/1 + G.711, sous-flux h264 640x360 25/1 + G.711, 401 sans mot de passe ; Frigate reconnecté seul |
| `live.cgi` | H.264 640x360, 295 Ko en 10 s |
| `frigateyaml` / manifeste | `@25`, `{FRIGATE_RTSP_PASSWORD}` |
| Audit (MQTT `a b`, XSS) | `INVALID_VALUE` ; 0 balise renvoyée |
| Pays Wi-Fi | FR effectif, regdb 1 |
| MQTT (broker) | `availability` online retenu ; commande `health` → `command/result` ; découverte : 49 configs (une de plus qu'en rc25), seul doublon `night_mode` (binary_sensor + switch, déjà là) |
| mDNS | `ipcamera2.local` → 192.168.1.11 |
| Import JSON (export de la caméra elle-même) | 1er import : `changed_files 3` = les nouvelles clés rc27 écrites une fois ; 2e : `changed_files 0` (idempotent). **Durée 20-25 s** pour 144 valeurs (12-15 s pour 123 en rc25). Pendant l'import, la capture tombe à 11-17 images/s (processeur unique), puis revient à 24-25. |

### Problème trouvé : `RTSP_PACING_US=100` par défaut (`cf4960b`) avec un noyau à 100 Hz
- Le noyau est `CONFIG_HZ=100`, `CONFIG_HZ_PERIODIC=y`, sans minuterie haute résolution : `/proc/timer_list` → `.resolution: 10000000 nsecs`. Un `usleep(100)` dort donc **au moins 10 ms**, pas 100 µs.
- Dans `tc100_rtsp.c`, le pacing (lignes 1675, 1961, 1969) ne touche **que les clients UDP** et dort **dans la boucle principale** (un seul fil) après chaque paquet : à ~143 paquets/s pour 1,6 Mbit/s, il faudrait > 1,4 s de sommeil par seconde. Avec un client RTSP en **UDP** (VLC par défaut, certains NVR), le débit plafonne vers ~100 paquets/s (< 1,2 Mbit/s) et **la capture elle-même est retardée** → images perdues pour tous les clients.
- Frigate/go2rtc en TCP ne sont pas concernés (pas de pacing en TCP) : c'est pour ça que rien ne se voit ici. Ma VM ne peut pas faire d'UDP (NAT) : à confirmer par le propriétaire (VLC en UDP sur la .11 : flux saccadé attendu).
- **Demande** : revenir à `RTSP_PACING_US` vide par défaut (revert de `cf4960b`) avant la rc suivante ; un lissage utile demanderait `CONFIG_HIGH_RES_TIMERS=y` ou un lissage par lots sans `usleep`, mesuré sur caméra. L'essai « une nuit avec le pacing » du plan rc27 n'a pas de sens pour Frigate (TCP).

Nuit : enregistreur relancé sur la .11 (18:24 UTC) : pertes de ping, images sautées, RAM, avec la rc27 (pas de témoin : la .24 est aussi en rc25 → comparaison avec la nuit rc25 de la .11).

## 2026-11-05 20:40 — rc27, .11 : les nouvelles implémentations activées une par une (testeur, à la demande du propriétaire : « si tout est concluant on garde »)

| Remplacement | Réglage (.11) | Résultat |
|---|---|---|
| Superviseur C (jour/nuit + bouton) | `SUPERVISOR_IMPL=c` (boot.conf) | **OK** : `tc100-supervisord` (PSS 145 Ko) remplace `auto-night-daemon.sh` + `button-watch.sh` (209 + 145 Ko) ; `/var/run/tc100-sv.night` et `.button`. ⚠ `controlscripts/auto-night-detection` n'a **pas de `restart`** (seulement start/stop/status/health) : `restart` ne fait rien, il faut stop puis start. Bascule jour/nuit à confirmer cette nuit ; bouton : test physique (propriétaire). |
| Découverte HA en C | `MQTT_DISCOVERY_IMPL=c` (mqtt.conf) | **OK** : 49 configs publiées par le démon en 11 s après un restart, **identiques octet pour octet** aux configs du script ; le script ne tourne plus qu'en `startup nodiscovery`. |
| Micro lu par `tc100_rtsp` | `RTSP_ALSA_DIRECT=1` (rtsp.env) | **OK** : log `audio: microphone read directly (/dev/snd/pcmC0D0c, no arecord)`, plus d'`arecord` (PSS 662 Ko), `tc100_rtsp` PSS 2 649 → 2 514 Ko ; G.711 8 kHz sur les deux flux, son réel (ffmpeg volumedetect -35,7 dB moyen), niveau sonore à jour. |
| ONVIF libre | `ONVIF_IMPL=c` (onvif.conf) + service onvif démarré | **PLANTAIT** : `tc100-onvifd` SIGSEGV au démarrage, même avec `-h`. Cause : `fprintf(stderr, …)` alors que la libc factice du Makefile déclare chaque import comme une fonction → `stderr` lu dans la PLT (si_addr = un mot d'instruction). Reproduit sous `qemu-arm` avec la uClibc de la caméra. **Corrigé : `0bc967c`** (onvifd et supervisord : `dprintf`/`write`, plus aucune variable libc ; test `NoLibcDataImports`). Binaire corrigé superposé en RAM sur la .11 : **OK** — WS-Discovery (XAddrs :8081), `GetDeviceInformation` avec WS-Security (Anyka / TC100 / 3.0.1-rc27), refus sans authentification, `GetProfiles` 1920x1080 + 640x360, `GetStreamUri` video0/video1, `GetSnapshotUri` currentpic.cgi ; PSS 213 Ko. |
| WebRTC (WHEP) | `WHEP=1` + service whep | **Vidéo absente** : négociation 201, ICE completed, DTLS-SRTP, audio reçu (458 paquets / 12 s), **0 image** (179 paquets vidéo). Cause : `on_video()` jetait tout paquet > 1400 octets ; `tc100_rtsp` envoie 1412 (12 + `RTP_PAYLOAD`) → aucune IDR. **Corrigé : `7618d73`** (limite = tampon − étiquette SRTP), test d'interop rendu réaliste (paquets découpés comme `tc100_rtsp`) : l'ancien code **échoue**, le nouveau passe (aiortc + mbedTLS en local). Build de l'image de base lancé (`tc100-whep` est un paquet Buildroot). En attendant : **`WHEP=0` sur la .11** (sinon la page aurait affiché un direct noir avec le son). |

État de la .11 ce soir : rc27 + `SUPERVISOR_IMPL=c`, `MQTT_BRIDGE_IMPL=c`, `MQTT_DISCOVERY_IMPL=c`, `RTSP_ALSA_DIRECT=1`, `RTSP_QMAX=1024`, `ONVIF_IMPL=c` (service onvif démarré), `WHEP=0`. **Binaires corrigés `tc100-onvifd` et `tc100-supervisord` superposés en RAM : au prochain redémarrage, la flash rc27 reprend l'onvifd qui plante** (ONVIF absent) → il faut une **rc28** avec `0bc967c` + `7618d73` (+ revert du pacing par défaut). MemAvailable 22,6 Mo.

## 2026-11-05 21:35 — WHEP corrigé sur la .11 : la vidéo passe (testeur)

- Build manuel `build-base-rootfs` (run 42089030516, commit `7618d73`) vert en 11 min ; `usr/bin/tc100-whep` extrait de `rootfs.cpio.gz` (md5 `6bc8d79d…`, différent de la rc27 `5e00fb69…`), superposé en RAM sur `/mnt/ext/bin/tc100-whep` de la .11, `WHEP=1`, service redémarré.
- **aiortc (navigateur simulé) : 354-360 images 640x360 en 20 s, première image à 1,5 s, ~930 trames audio, 0 perte vidéo.** ICE completed, DTLS-SRTP up. Log : `viewer … gone (212 video, 544 audio packets)` à la fermeture.
- `tc100-whep` : ~9 % CPU pendant une session, PSS ~620 Ko au repos.
- **Coût du sous-flux (pas propre au WebRTC)** : dès qu'un client lit le sous-flux (WHEP ou simple RTSP `video1_unicast`), l'encodeur matériel encode les deux flux et la capture tombe de 24-25 à **~21-22 img/s** (RTSP : `cap` 106-112 / 5 s ; WHEP : 78-102), `enc_ms` ≈ 4 s sur 5 s, CPU encore 64 % libre (pas le processeur : l'encodeur). Avec `arecord` au lieu de `RTSP_ALSA_DIRECT=1`, c'est pire (`cap` 66-75) : le micro direct est meilleur. À noter dans la doc (WHEP, multiview en vidéo fluide, Frigate sur le sous-flux).
- La .11 garde `WHEP=1` (le démon ne travaille que pendant une session). Binaire corrigé en RAM seulement → **rc28** (R1).
- Reste à faire (P7) : le direct WebRTC dans le navigateur du propriétaire.

## 2026-11-05 23:35 — 3.0.1-rc28 (bump par le testeur à la demande du propriétaire)

- Contenu : `3a5519b` (CI verte ; l'échec de `1310577` est `test_mqttd…reconnects_after_the_broker_drops` 1 != 2, test au minutage instable, vert au commit suivant) + ce bump. Le build de release reconstruit l'image de base (`build-base-rootfs.yml` appelé ligne 43) : il embarque le `tc100-whep` corrigé (`src/whep` inchangé depuis `7618d73`).
- Installation : **.11**, mise à jour web, flash, sans carte SD. La .11 avait des binaires corrigés superposés en RAM (onvifd, supervisord, whep) : la mise à jour redémarre la caméra, ils disparaissent et sont remplacés par ceux de la rc28.
- ⚠ `[rc28-defaults]` change les **défauts d'une nouvelle installation** ; sur la .11, les réglages existants de `/mnt/config` restent (`install_config` ne copie pas une `.dist` sur un fichier présent).

## 2026-11-06 00:00 — rc28 sur la .11 (flash, mise à jour web) : contrôles du testeur seul

Build `8131144` (run 42122303317, vert), archive md5 `daeb9449…`. Tout fait à distance (ssh, curl `-u`, ffmpeg, aiortc, Chrome du propriétaire déjà connecté) ; rien de tapé dans un formulaire.

- **Base** — `passed` : `flashroot=1`, boot-guard 0, MemAvailable ~23 Mo, CmaFree 5,8 Mo. Processus : `tc100_rtsp` (PSS 2538 Ko), `tc100-mqttd` (250), `tc100-supervisord` (226, **3 jobs** : `/var/run/tc100-sv.night`, `.button`, `.sound`), `tc100-whep` (672), mdnsd, httpfront. Plus aucune boucle shell résidente, plus d'`arecord`. `tc100_rtsp` : file client 1024 Ko, **pacing 0 µs** (R2 vérifié), micro direct. Réglages de la .11 conservés (`SUPERVISOR_IMPL=c`, `MQTT_*_IMPL=c`, `RTSP_ALSA_DIRECT=1`, `RTSP_QMAX=1024`, `ONVIF_IMPL=c`, `WHEP=1`, `WIFI_COUNTRY=FR`).
- **RTSP** — `passed` : TCP, principal hevc 1920x1080 25 img/s + PCMA, sous-flux h264 640x360 + PCMA ; 401 sans mot de passe.
- **Web** — `passed` : 9 pages HTML en 200 ; `dash.cgi` / ligne d'état natifs en 0,02 s. Une fois, `state.cgi?daynight` a mis **7,2 s** (puis 0,3-0,4 s) : à surveiller (premier appel après démarrage ?). `frigateyaml` : `@25` et `{FRIGATE_RTSP_PASSWORD}`.
- **MQTT / découverte** — `passed` : 49 configurations identiques à la rc27 sauf `dev.sw` (rc27 → rc28) ; `availability` online, commande `health` répond. mDNS répond.
- **ONVIF (`tc100-onvifd`)** — `passed`, avec une remarque : le service ne démarre pas tout seul (pas de `config/autostart/onvif` : voulu, ONVIF reste à activer dans Services). Créé à la main sur la .11 (`/mnt/config/autostart/onvif`). Depuis le flash : PSS 229 Ko, WS-Discovery, `GetDeviceInformation` (FW 3.0.1-rc28), profils 1080p / 360p, URI flux et image, **`FrameRateLimit` 25/25 (R6 vérifié)**, débits 1600 / 250.
- **R5** — `passed` : les 26 scripts de `controlscripts` ont `restart` ; `auto-night-detection restart` relance le job nuit **dans** `tc100-supervisord` (pid du démon inchangé, fichier du job retiré puis recréé).
- **R7** — partiel : import JSON de 156 valeurs en 15,5 s puis 21,8 s (idempotent : 2e passage `changed_files` 0). Pas nettement mieux que la rc27 (20-25 s / 144) ; à mesurer en journée avec `cap` pendant l'import.
- **T2 (charge)** — partiel, **de nuit (10 img/s)** : 4 clients RTSP (Frigate + 3 principaux) : 0 image sautée, CPU 64 % libre, `snd_ms` ~450-490 / 5 s. **À refaire de jour à 25 img/s.**
- **T8 (httpfront, connexions muettes)** — `passed` : 80 connexions TCP ouvertes sans rien envoyer, toutes acceptées ; le web répond toujours en 0,02-0,07 s ; 72 restent ouvertes ≥ 30 s (pas d'expiration des connexions muettes côté httpfront, sans effet mémoire visible). Suggestion : délai de lecture de l'en-tête (10-15 s).
- **T9 (clients RTSP inactifs)** — `passed` avec un écart : un client muet est fermé après **~31 s** alors que `CLI_IDLE_S` vaut 60 dans `tc100_rtsp.c` (autre délai qui s'applique avant ? à expliquer ou aligner la doc). Frigate (TCP, PLAY) n'est pas déconnecté.
- **T7 (`WEB_LOCKOUT`)** — `blocked` à distance : la VM du testeur sort par la même IP que le navigateur du propriétaire (NAT du Mac) ; bloquer cette IP bloquerait le propriétaire. À faire depuis une autre machine du LAN.
- **P7 (WebRTC dans Chrome)** — **`failed`, corrigé** : la page passe tout de suite au MP4, console `WebRTC off (HTTP 413): MP4 live view`. L'offre de Chrome 157 (vidéo + audio recvonly, candidats hôtes) fait **7607 octets** ; `whep.cgi` et `tc100-whep` refusaient tout au-delà de 6000 (les offres d'aiortc, plus courtes, passaient : d'où le test vert du 05/11). Corrigé en `1749475` : limite commune 12000 (`WH_MAX_OFFER`), tampon de requête 16 Ko avec garde en-tête + corps ; tests `test_whep` (offre de 7,6 Ko acceptée, 13 Ko refusée) et `WhepAcceptsBrowserOffers`. **À revalider dans Chrome avec le `tc100-whep` reconstruit (rc29 ou superposition en RAM).**
- **Repli MP4** : observé à ~1,8 img/s (640x360, de nuit) pendant ce test : lent, à mesurer de jour.
- Enregistreur de nuit relancé sur la .11 (`/tmp/nightcam.sh` → `/tmp/night.log`, toutes les 180 s) : bilan le 2026-11-06 au matin.

## 2026-11-06 00:20 — WebRTC dans Chrome : deuxième cause trouvée (ClientHello DTLS fragmenté) et corrigée (testeur)

- Avec `1749475` superposé en RAM sur la .11 (`tc100-whep` md5 `e66d10f0…` de l'image de base du run 42126368363 + `whep.cgi`) : plus de 413, l'offre est acceptée (`offer accepted (sub stream, H.264 pt 102)`), ICE passe, mais **`DTLS handshake failed (-0x7900)`** ; la page affiche `WebRTC off (no picture): MP4 live view`.
- Cause : Chrome 157 propose **DTLS 1.3 avec une clé post-quantique (X25519MLKEM768)** ; son ClientHello (~1,4 Ko) arrive en plusieurs fragments, que mbedTLS 2.28 ne sait pas réassembler (`MBEDTLS_ERR_SSL_BAD_HS_CLIENT_HELLO`). aiortc et les Chrome plus anciens envoient un ClientHello d'un seul tenant : d'où les tests verts.
- **Reproduit en local** : Chromium 141 (Playwright) + `--force-fieldtrials=WebRTC-ForceDtls13/Enabled/WebRTC-EnableDtlsPqc/Enabled/` → même `-0x7900` ; sans ces options → OK.
- **Corrigé en `cfed960`** : `wh_chello_feed()` (`whep_proto.h`) rassemble les fragments et donne à mbedTLS un seul enregistrement contenant le message entier ; mbedTLS répond en DTLS 1.2, que le navigateur accepte. Vérifié : `ClientHello of 1413 bytes rebuilt from fragments`, DTLS-SRTP établi, vidéo + audio reçus. Tests : `whep_test.c` (fragments dans le désordre, répétés, trop gros), nouveau `tests/whep_chrome_interop.py` (Chromium, DTLS 1.2 et DTLS 1.3 + ML-KEM ; ignoré sans Playwright), `tests/whep_interop.py` (aiortc) toujours vert.
- **À faire (implémenteur)** : ajouter `tests/whep_chrome_interop.py` à la CI (une image avec Playwright/Chromium) pour ne plus être pris par une nouvelle version de navigateur ; vérifier Firefox / Safari. Le testeur revalide P7 dans le Chrome du propriétaire avec le binaire de `cfed960` (superposé en RAM), puis rc29.

## 2026-11-06 01:05 — P7 : direct WebRTC dans le Chrome du propriétaire — `passed` (binaires de `cfed960` superposés en RAM) (testeur)

- `.11` en rc28 + `tc100-whep` de l'image de base du run 42132047943 (`cfed960`, md5 `beca047c…`) et `whep.cgi` de `1749475`, superposés en RAM (`mount --bind`, perdus au redémarrage).
- Chrome 157, page Direct : **WebRTC établi** (`srcObject`, 640x360, plus de « WebRTC off » dans la console). Démon : `offer accepted (sub stream, H.264 pt 102)`, `DTLS-SRTP up, streaming`.
- Mesure sur 20 s : **10,1 img/s** (= cadence de capture de nuit, `STAT cap 51` / 5 s), 0 image perdue côté navigateur, `clients 2`, `dropped 0`.
- La page ne demande que la vidéo (`addTransceiver("video")` seul, `30-live-view.js`) : le son reste sur « Écouter ». Normal, à noter dans la doc si on veut le son en WebRTC un jour (`WHEP_AUDIO=1` est prêt côté démon, testé avec aiortc et Chromium).
- **Reste** : rc29 pour avoir ces deux corrections en flash ; mesure de jour à 25 img/s ; Firefox / Safari ; `tests/whep_chrome_interop.py` en CI.


## 2026-11-06 07:30 — rc28 sur la .11 : bilan de la nuit (7 h 43 sans redémarrage) — `passed` (testeur)

Enregistreur `/tmp/nightcam.sh` (148 relevés toutes les 180 s, 23:02 → 06:27 UTC).
- **Stabilité** : aucun redémarrage, aucun OOM / segfault dans `dmesg`, tous les démons présents (`tc100_rtsp`, `tc100-mqttd`, `tc100-supervisord`, `tc100-whep`, `tc100-onvifd`, `httpfront`, `tc100-mdnsd`).
- **Mémoire** : MemAvailable entre 21,9 et 23,5 Mo toute la nuit, sans dérive notable (~23,2 → ~22,1 Mo) ; CmaFree 5,9 Mo. PSS au matin : `tc100_rtsp` 2782 Ko (2538 au démarrage, VmHWM 4056), `tc100-whep` 876 (672, après une session WebRTC), mqttd 205, superviseur 210, onvifd 234, httpfront 1071.
- **Vidéo** : `cap` 50-51 / 5 s à chaque relevé (10 img/s, mode nuit), Frigate connecté toute la nuit (`cl1`), **`dropped 0` sur toute la nuit**.
- **Wi-Fi** : pas de déconnexion (pas de nouvelle association dans `messages`, lien 70, -22 dBm). Ping vers la box (2 paquets / relevé) : 13 relevés à 100 % de perte et 2 à 50 % sur 148 (~9 %), quelques pointes de latence (300-1170 ms) : **même niveau qu'en rc27** (9 / 86) et sans effet sur le flux. Probablement l'économie d'énergie Wi-Fi ou la box : point déjà au backlog (pertes Wi-Fi).
- **Jour / nuit** : à 06:11 UTC la luminosité monte (luma 24 → 48, `ae` 2 → 19), toujours en nuit à 06:27 ; bascule jour à vérifier dans la matinée (`/tmp/logs/daynight.log`).
- Rappel : `tc100-whep` et `whep.cgi` de la .11 sont les versions corrigées superposées en RAM (perdues au redémarrage) en attendant la rc29.

## 2026-11-06 07:35 — rc29 lancée par le testeur (accord du propriétaire)

- Contenu : rc28 + `1749475` (offre WHEP 12000 octets) + `cfed960` (ClientHello DTLS fragmenté) ; CI verte sur les deux ; aucun réglage par défaut modifié.
- Installation prévue : **.11** en flash par la mise à jour web (remplace les binaires superposés en RAM) ; la **.24** est en cours de flash en rc28 par le propriétaire.
- À vérifier en rc29 : P7 WebRTC dans Chrome depuis le flash (sans superposition), `whep.cgi` 12000, réglages de la .11 conservés (dont `autostart/onvif`), puis T2 de jour à 25 img/s.

## 2026-11-06 08:00 — rc28 sur la .24 (flash par le propriétaire) : contrôles du testeur

- **Base** — `passed` : 3.0.1-rc28, `flashroot=1`, MemAvailable 21,8 Mo, CmaFree 5,6 Mo ; `tc100_rtsp` (PSS 3029 Ko, enregistreur ouvert), mqttd C (225), superviseur C (261 ; jobs nuit + son ; pas de bouton : `autostart/button-actions` absent sur la .24), whep (190), httpfront, mdnsd ; pacing 0 µs, micro direct, Frigate connecté, `dropped 0`. Wi-Fi -48 dBm, ping box OK.
- **10 img/s de jour** : normal ici. Mode jour depuis 06:42 UTC, mais gain total 22x (pièce encore sombre au lever du jour) : le mode basse lumière (R12-02, comme l'appli d'origine) garde le capteur à 10 img/s tant que le gain ne repasse pas sous 5x.
- **`failed` — OOM au démarrage sur la carte SD** : la carte de la .24 (64 Go FAT32) est l'**ancienne carte de démarrage SD** (`wifitest`, `bin`, `v3`…), marquée « not properly unmounted ». Avec `SD_AUTO_REPAIR=1` (défaut depuis la rc28), `sd-diag.sh repair` lance `fsck.fat -a -w` 60 s après le démarrage : **tué par l'OOM** à 185 s (`fsck.fat` anon-rss 23,7 Mo). Rien d'autre n'a été tué. Ensuite `rec-storage.sh` refuse de toute façon cette carte (`wifitest` = fichiers de démarrage) : `/mnt/sd` reste le tmpfs de 16 Ko, donc **pas d'enregistrement local sur la .24** malgré `REC_LOCAL=1`, `REC_WHEN=motion`. Deux défauts pour l'implémenteur (R14) : la réparation automatique tourne sur une carte que l'enregistreur va refuser (et l'écrit, `-w`), et `fsck.fat` sur une grande carte FAT32 dépasse la RAM de la caméra.
- **Différences de réglages avec la .11** (hors identité/matériel : MQTT, GPIO IR-cut, enregistrement SD) : `.24` sans `WIFI_COUNTRY=FR`, sans `autostart/onvif` ni `autostart/button-actions`, sans `rtsp.env` (`RTSP_QMAX=1024` : file client 384 Ko au lieu de 1024) ; `SYSLOG_HOST` = 192.168.1.22 sur la .24 contre 192.168.1.23 sur la .11 (question posée au propriétaire). Les clés absentes du `boot.conf` de la .24 (`BOOT_GUARD`, `VM_TUNE`, `WHEP_*`, `IDLE_*`…) prennent leur valeur par défaut.

- **07:56 (heure de Paris ; noté 08:10 par erreur) — réglages de la .24 alignés sur la .11** (décision du propriétaire) : sauvegarde dans `/mnt/config/backup-parity-20261106/`, puis `WIFI_COUNTRY=FR`, `SYSLOG_HOST=192.168.1.23` (la bonne adresse ; .22 était une erreur), `rtsp.env` (`RTSP_QMAX=1024`, `RTSP_ALSA_DIRECT=1`), `autostart/onvif` et `autostart/button-actions`. ONVIF démarré (WS-Security OK, FW 3.0.1-rc28, profils 1080p / 360p vers `192.168.1.24`, `FrameRateLimit` 25/25) et job bouton actif dans le superviseur C (`/var/run/tc100-sv.button`). Wi-Fi, syslog et file RTSP prennent effet au prochain redémarrage. Carte SD de la .24 : le propriétaire va la vider / formater pour l'enregistrement local.

## 2026-11-06 08:10 — rc29 sur les deux caméras (flash, mise à jour web par le propriétaire) : contrôles du testeur

- **Base** — `passed` sur .11 et .24 : 3.0.1-rc29, `flashroot=1`, MemAvailable ~23,1-23,2 Mo, CmaFree 5,9 / 4,7 Mo ; tous les démons présents (`tc100_rtsp`, mqttd, superviseur C, whep, onvifd, httpfront, mdnsd), plus aucune superposition en RAM (`tc100-whep` md5 `beca047c…` et `whep.cgi` 12000 lus depuis la flash). Pacing 0, file client 1024 Ko, micro direct sur les deux.
- **Réglages conservés par la mise à jour** — `passed` : `rtsp.env`, `autostart/onvif` et `button-actions`, `WIFI_COUNTRY=FR`, `SYSLOG_HOST=192.168.1.23` (sur la .24 : les réglages alignés à 08:10 sont pris en compte), identités MQTT. Sauf le jour / nuit, ci-dessous.
- **`failed`, corrigé — jour / nuit automatique coupé par la mise à jour** : sur les deux caméras, `rtspserver.conf` réécrit pendant l'installation (06:59:25 et 06:59:33 UTC) avec `daynight=3`, et au démarrage `auto day/night not started: manual mode (daynight=3)` (pas de job `night` dans le superviseur). Cause : `update66.sh` (et `install66.sh`, et l'arrêt mémoire basse de `update.cgi`) appellent `auto-night-detection stop`, dont le `stop` écrit `daynight=3` (choix manuel, gardé). Ce n'était pas visible avant la rc28 : `/mnt/bin/rwconf` n'existait pas en 3.0, l'écriture échouait sans bruit ; la rc28 l'apporte. **Rétabli sur les deux caméras** (`auto-night-detection start` : `daynight=2`, job `night` actif, `mode=day src=luma`, sauvegardé en flash par `cfg-persist` à 07:13 UTC). **Corrigé en `7e3b1c8`** : nouveau verbe `halt` (arrête le job sans toucher au réglage), utilisé par `update66.sh`, `install66.sh`, `update.cgi` ; `stop` garde son sens (arrêt voulu par l'utilisateur). Tests `UpdateKeepsAutoDayNight` et `test_audit_20261104` mis à jour. À revalider à la prochaine mise à jour (rc30).
- **RTSP** — `passed` : principal hevc 1920x1080 25 img/s + PCMA sur les deux (ffprobe TCP). De jour, `.11` capture 119-120 / 5 s (~24 img/s) avec Frigate, `dropped 0` ; `.24` reste à 10 img/s (mode basse lumière, gain élevé dans sa pièce).
- **ONVIF** — `passed` sur les deux : FW 3.0.1-rc29, `FrameRateLimit` 25/25, débits 1600 / 250.
- **MQTT** — `passed` : `.24` `tc100/cam2/availability` = online ; `.11` connectée au broker (TCP établi), dernière publication `ok`.
- **P7 WebRTC depuis la flash** — `passed` : Chrome 157 sur la .11, `srcObject` 640x360, **20,1 img/s de jour** (le sous-flux consommé abaisse la capture vers ~21 img/s, connu), 5 images perdues sur ~450, aucune ligne « WebRTC off ».
- **Carte SD de la .24** : encore l'ancienne carte de démarrage ; `fsck.fat` à nouveau tué par l'OOM au démarrage (173 s), rien d'autre touché (R14). Le propriétaire va la formater.

## 2026-11-06 08:35 — T2 de jour (25 img/s) sur la .11 en rc29 : `passed` avec une limite mesurée (testeur)

Clients RTSP principaux (hevc 1080p, TCP, `ffmpeg -c copy -f null`) depuis la VM du testeur, en plus de Frigate ; relevés `STAT` toutes les 5 s.

| clients principaux | `cap` / 5 s | img/s | `enc_ms` | `snd_ms` | `dropped` |
|---|---|---|---|---|---|
| 1 (Frigate) | 123-124 | ~24,7 | ~3850 | ~295 | 0 |
| 2 | 111-117 | ~23 | ~3600 | ~550-590 | 0 |
| 4 | 87-95 (72-80 au départ) | ~18 | ~2850 | ~900-1060 | 0 |

- Aucun client décroché, aucune image sautée par client (`dropped 0`), CPU 42 % libre à 4 clients, MemAvailable 22,0 Mo ; retour à 123-124 dès la fin du test.
- **Limite** : l'envoi TCP coûte ~250-300 ms / 5 s **par client** et se fait dans la même boucle que la capture ; avec l'encodeur déjà à ~3,8 s / 5 s, chaque client en plus retire des images à la capture (25 → 23 → 18 img/s). Avec Frigate seul (usage normal) : ~24,7 img/s.
- La .24 n'est pas testable à 25 img/s ce matin : en mode jour mais gain total ~10x, exposition 2810 lignes ; le mode basse lumière (R12-02, comme l'appli d'origine) ne remonte à 25 img/s que sous 5x. Normal dans une pièce peu éclairée ; `RTSP_LOWLIGHT_FPS=0` garderait 25 img/s (image plus sombre).

## 2026-11-06 09:30 — audit de l'interface web (rc29) et syslog (testeur)

- Rapport : `docs/linux-port/webui-audit-2026-11-06.md` (doublons D1-D6, inutiles U1-U9 ; tout est câblé).
- **`failed`, corrigé — syslog** : sur les deux caméras, `syslog-forward` « Arrêté » malgré `SYSLOG_ENABLE=1` ; `syslogd` lancé avec `-D -f` refusés par la BusyBox de la base (« unrecognized option: D ») : plus aucun journal local après le démarrage du service (`/var/log/messages` arrêté à 07:01 UTC) et rien vers 192.168.1.23. Relancé à la main (RAM) à 09:17 sur les deux : `syslogd -n -l 6 -s 128 -b 1` + `tc100-logfwd -r 192.168.1.23:514`, message de test écrit. Corrigé en `bf6d15c` (fragment BusyBox + repli). R21.


## From: open entries closed on 2026-11-14 (rc43 validated on both cameras; results stay at the end of test-queue.md)

### NR3D-01 3D noise reduction: runtime switch, crop-size reference, overflow counter (`[nr3d]`) — `passed, default NR3D=1 since rc43` (2026-11-14)

- **Result (2026-11-12 23:11–23:17, `.11` rc41, flashed web update):**
  - `3D-NR reference frame: 4050 KiB at 0x82f00000, 2025 KiB at 0x82200000 (UV in venc pool)` — **zero CMA/REQBUFS error** at 1080p (`MemAvailable: 17760 kB`, `CmaFree: 2256 kB` while streaming, 2 `rtsp-h26x restart` clean).
  - **25 fps (1080p):** `nr3d_overflow` rose to `3895` (~25/s: `TNR_DMA_OVERFLOW` on every frame at 480 MHz PLL / 120 MHz ASIC). With `nr3d=0`: `0 overflows / 5s`.
  - **15 fps (1080p, `-f 15`):** **`0 overflows / 5s`** — confirms 3D-NR + 1080p works cleanly once DRAM/ISP frame budget is at 15 fps (e.g. night/low-light `15 fps` or `20 fps` to test; 2 h soak + night noise comparison still to do).
  - **`NR3D=auto` default (`[nr3d]`):** `boot.conf.dist` sets `NR3D=auto`; `autorun-linux66.sh` allocates the reference
    at boot for `1|auto`, `rtsp-launch.sh` exports `RTSP_NR3D_AUTO=1`, and `tc100_rtsp` toggles `ak39_vi.nr3d` live
    (`1` only at night (`bw_want`) or in low light (`lowlight_on`) **and** when the capture rate in use is <= 15 fps: the
    accepted night set runs at 10 fps, low light at `LOWLIGHT_FPS_VALUE` 10/15 (20 stays off); `0` by day at 25 fps, and at night
    with `NIGHT_STYLE=0` or a refused night set, which stay at 25 fps; rc42 fix, the log line gives the reason and the fps:
    `3D-NR auto: on|off (night|low light|day, N fps)`). Set `NR3D=0` in `boot.conf` to turn off.

- **What (plans-2026-11-12 section 2; kernel patches 0006, 0016 and 0017, `v3/autorun-linux66.sh`, `config/boot.conf.dist`):**
  - **Patch 0017 (`[nr3d]` UV in encoder CMA tail):** `ak39_venc` exports `ak39_venc_aux_alloc()` / `ak39_venc_aux_free()`
    to allocate the 2025 KiB UV reference plane (`ref_uv`) from the 2688 KiB tail left unused by `ak39_venc.pool=9600K`
    in `venc@81800000` (falling back to the default CMA if unavailable). `dmesg` logs `(UV in venc pool)` on
    `3D-NR reference frame:` when placed there, freeing ~2 MiB in the default CMA for 1080p capture buffers.
    `NR3D=0` remains the default; revert patch 0017 to go back to allocating both planes from the default CMA.
  - `ak39_vi.nr3d` is now a 0644 parameter (default 0). Writing 1 while the queue is not streaming allocates the 6075 KiB
    reference frame (Y 4050 + UV 2025 KiB) from the default CMA and turns 3D-NR on; writing 1 while streaming without a
    reference returns `EBUSY` (CMA is then full of capture buffers); writing 0 while streaming sets `noref` at once (memory
    kept, never freed or reallocated live); writing 0 while NOT streaming frees the reference. Recovery when the 6 MB
    taken first leaves no room for the capture buffers (no video at 1080p): `NR3D=0`, `echo 0 >
    /sys/module/ak39_vi/parameters/nr3d`, restart the video service, no reboot. The ISP is only touched while it runs
    (a write between streams or after a failed start cannot oops); `nr3d_overflow` refuses a command-line value. `ak39_vi.nr3d=1` on the command line still allocates at probe.
  - `program_ref()` programs the crop size (1920x1080, `CROP_W x CROP_H`) at every format. Before it programmed the output
    size: at a 720p main format a 720p reference was declared to a TNR block that works on the 1080p crop. It also keeps
    3D-NR off (`noref`) when the allocation is smaller than the crop.
  - New read-only `ak39_vi.nr3d_overflow`: `TNR_DMA_OVERFLOW` interrupts since boot (each one switches TNR off until the
    3A loop re-arms it).
  - `boot.conf` `NR3D=1` (single source; the dead NR3D lines of `isp_tune.conf.dist` are gone): `autorun-linux66.sh` writes
    1 to the parameter just before `tc100_rtsp` starts (CMA still empty) and logs `[tc100-v3] 3D-NR on (...)` or the refusal
    on the console. `NR3D=0` or absent writes nothing. Read once at boot.
- **Decision on 1080p memory: the memory map is NOT changed.** A 1080p reference stays an option taken from the default
  CMA; **720p is the reliable mode**. Why (all from patches 0009/0015, `cma=18M` is a U-Boot argument and stays):

  | physical range | size | what | source |
  |---|---|---|---|
  | 0x80000000-0x80008000 | 32 KiB | before the kernel | boot |
  | 0x80008000-... | not measured | kernel image, bss | kernel at 0x80008000 |
  | 0x81000000-0x811eb5ee | 2012654 B | initramfs as loaded (`initrd=0x81000000,2012654`) | `stock-hook.sh`, `build-rootfs66.sh` |
  | 0x81800000-0x82400000 | 12 MiB | encoder reusable CMA area (pool 9600K + 2688 KiB tail); contains 0x82000000 (U-Boot uImage load, a 2 MiB read ends at 0x82200000, dead once the kernel runs) | 0009 `venc@81800000`, 0015 |
  | 0x82400000-0x82c00000 | 8 MiB | **the only free window**: ordinary RAM today | by difference |
  | 0x82c00000-0x84000000 | 20 MiB | default CMA (`cma=18M` rounded up to the 4 MiB pageblock; with `cma=24M` it was 0x82800000, R9-01) | command line |

  A second reusable CMA area would have to be exactly 0x82400000 + 8 MiB (6 MiB needed; CMA areas are 4 MiB aligned in base
  and size), with zero slack and touching the default CMA. Not done because: (1) it is a memory-map change whose result
  cannot be seen without booting, and a kernel that fails to boot cannot be repaired from Linux; (2) it takes all of the
  last free window, and the default CMA position depends on the U-Boot `cma=` value (`cma=24M` as used in R9-01 would then
  not fit and the default CMA, hence all video buffers, would be missing); (3) a device CMA area binds every DMA allocation
  of the video device (capture buffers too, with no fallback to the default area) and `cma_alloc()` is not exported to a
  second device; (4) 8 MiB less memory for unmovable kernel allocations on a 64 MiB camera, also when 3D-NR is off.
  Default CMA budget (20 MiB, 1 MiB aligned): 1080p = 3 x 3379 KiB buffers (about 12 MiB with alignment) + 6075 KiB
  reference (about 6 MiB) = about 18 MiB, and today CmaFree is about 5.9 MB with 1080p streaming (the reference needs
  5.93 MiB contiguous): it does not fit at video start, it only fits when taken first, with about 2 MiB spare.
  720p = 3 x 1692 KiB (about 6 MiB) + 6 MiB reference: about 6 MiB spare. (The reference stays 1080p-sized at 720p because
  the crop is 1080p: to confirm below.)
- **Switch to turn it off:** `NR3D=0` in `/mnt/config/boot.conf` and reboot; live: `echo 0 > /sys/module/ak39_vi/parameters/nr3d`
  (3D-NR off at once, memory kept until reboot). Default stays off until a pass and the owner's agreement.
- **Test (SD kernel from CI of this commit `[nr3d]`, `pack66/boot66b.sh`, nothing flashed; owner present):**
  1. Boot without `NR3D`: `cat /sys/module/ak39_vi/parameters/nr3d` = `0`, `ls -l` shows `-rw-r--r--`, `nr3d_overflow` = `0`
     and `-r--r--r--`; no `3D-NR` line in dmesg; MemAvailable and CmaFree as before (22-23 MB / 5.9 MB). Record `cma: Reserved`.
  2. **720p** (`RTSP_WIDTH=1280 RTSP_HEIGHT=720`, `NR3D=1` in boot.conf, reboot): console `[tc100-v3] 3D-NR on (ak39_vi.nr3d=1,
     overflows 0)`, dmesg `3D-NR reference frame: 4050 KiB at ..., 2025 KiB at ...`. Note MemAvailable, CmaFree, picture OK.
  3. **1080p, only after 720p passed**, the same way: either the allocation succeeds (note CmaFree, then the same checks as 2) or dmesg shows `no
     memory for the 3D-NR reference frame` and the console says refused with a normal picture, or the reference is taken
     but REQBUFS then fails (no video): recover with `echo 0` to `nr3d` and a video service restart, without reboot, and
     check that the video comes back. All are results.
     Also `echo 1 > .../nr3d` while streaming without a reference (NR3D=0 boot): must fail with `Device or resource busy`.
  4. Ten `controlscripts/rtsp-h26x restart` (or kill and relaunch with the same arguments) with the reference allocated: no
     `alloc failed`, no oops, `nr3d_overflow` unchanged, picture OK after each.
  5. Day and night (IR cut): `echo 0` then `echo 1` to `nr3d` live, three times, while the stream runs: no freeze, no oops.
  6. Recording to the SD card plus snapshots (`stream.jpg`) during step 2: no CMA failure in dmesg, MemAvailable stays above 15 MB.
  7. 2 h H.265 soak at the chosen resolution with 3D-NR on: no oops, no second `Starting kernel`, `nr3d_overflow` 0 (or
     report its rate), MemAvailable never below 12 MB, `tc100_rtsp` STAT frame counts as without 3D-NR.
  8. Night noise comparison with IR on, 3D-NR off and on, same scene, same bit rate: two stills and the bytes per second of
     an equal-length capture (R9-01 measured 25-34 % less noise at 1080p; give the 720p figure).
  9. Confirm the high-water assumption: at a 720p main format the TNR block still needs the full 1080p reference (no
     `nr3d_overflow` increments, no corrupted bands in the picture).
- **Pass:** steps 1-7 clean at 720p, `nr3d_overflow` 0, MemAvailable thresholds met, a visible night improvement (step 8).
  1080p is optional: report its result, it is only kept if it fits with margin over the soak. Then (and only then, with the
  owner's agreement) the kernel is a flash candidate through `flashw` with its read-back check, and `NR3D=1` can become the
  default for 720p setups. **Nothing is flashed before a pass.**

### NR3D-02 3D-NR by day: why 25 fps overflows, and which setting avoids it (`[nr3d]`) — `passed on both cameras, day and night; default NR3D=1 since rc43` (2026-11-14)

- **Why (read-only Fable analysis, 2026-11-13; facts checked against patch 0006):** the sensor sets its frame rate by
  frame length, not by pixel rate (JX-F23 MIPI table: 25 fps = 0x465 = 1125 lines, 20 fps = 0x56e = 1390, 15 fps =
  0x73d = 1853, 1080 of them active). The ISP therefore works at the same speed during the active lines at every rate;
  what changes is the vertical blanking left to finish the reference DMA: ~45 lines (~1.6 ms) at 25 fps, ~310 (~11 ms)
  at 20 fps, ~773 (~27 ms) at 15 fps. So the overflow at 25 fps is more likely a latency limit (reference DMA not done
  before the next frame) or the encoder being busy all the time than a pure DRAM bandwidth limit (EST: ~770 MB/s total
  with 3D-NR at 1080p25 vs ~460 MB/s without; DDR clock and width are not known from the repo). Nothing in the patches
  sets a DDR arbiter or priority. The meaning of `TNR_COMPRESS_FORMAT` (YUV_REG_9 bits 17-18, `tnr_refFrame_format` of
  the vendor tuning file) is not documented anywhere in the repo.
- **Switch:** `NR3D=auto` (default) or `NR3D=0` in `boot.conf` afterwards; frame rate and main size back to what they
  were (Settings).
- **Test (one RTSP client connected the whole time; nothing else changes):**
  1. `NR3D=1` in `/mnt/config/boot.conf` (not `auto`, which turns 3D-NR off above 15 fps), reboot; dmesg shows
     `3D-NR reference frame: ... (UV in venc pool)`.
  2. For each case below, set it in Settings, wait for the video to restart, then read
     `cat /sys/module/ak39_vi/parameters/nr3d_overflow`, wait 60 s, read again; note the difference, the STAT line
     (`cap`, `dropped`) and the picture:
     - **A:** 1080p, 25 fps (Streams & audio → frame rate 25): control, ~1500 expected in 60 s.
     - **B:** 1080p, 20 fps.
     - **C:** 720p (Main stream → 1280x720, `mainres=720`), 25 fps. The ISP still crops at 1080p (patch 0016), so 3D-NR
       works at the same size: this case tells whether the encoder load matters (encoder and main write drop by ~56 %).
     - **D:** 720p, 20 fps.
  3. Read the vendor's 3D-NR settings from the tuning file (layout derived from patch 0006, unverified on a camera):
     `dd if=/lib/firmware/anyka/isp.conf bs=1 skip=4034 count=4 2>/dev/null | hexdump -C` must show `04 00 68 04`;
     then `for k in 0 1 2 3 4 5 6 7 8 9; do dd if=/lib/firmware/anyka/isp.conf bs=1 skip=$((4042+112*k)) count=12 2>/dev/null | hexdump -C | head -1; done`
     prints, per parameter set (k=0 manual, 1-9 linked to the gain), six little-endian 16-bit values: `uv_min_enable,
     tnr_y_enable, tnr_uv_enable, updata_ref_y, updata_ref_uv, tnr_refFrame_format`. Paste the 10 lines under this
     entry (they hold no secret). If the check bytes differ, paste the first 8 KB offset map instead and do not guess.
  4. `dmesg | grep -i -e GUARD -e isp | tail -20` after the four cases.
- **Reading the result:**
  - **B = 0:** 3D-NR by day at 20 fps is possible: raise the threshold of `nr3d_auto_sync` / `cap_fps_now`
    (`src/tc100rtsp/tc100_rtsp.c`) from 15 to 20 fps (small change, then a 2 h soak at 0).
  - **C = 0 but A > 0:** encoder contention: 3D-NR by day only with a 720p main.
  - **All > 0:** next step is 3D-NR on luma only (`tnr_uv_enable` / `updata_ref_uv` = 0: a third less reference
    traffic, chroma noise stays), which needs a small tool (`src/ispnr3d`, GET/SET of the 1124-byte 3D-NR block through
    `/dev/isp_char` `AK_ISP_GET_3D_NR` / `AK_ISP_SET_3D_NR`, patch 0006 ~12937-12975) — to be written after this test.
- **Not now, and why:** a compressed reference format (`tnr_refFrame_format`) could be the biggest gain, but with unknown
  semantics it risks DMA past the reference buffer (memory corruption). It needs first a kernel guard
  (`ak39_vi.nr3d_refguard`: one extra page per plane, filled with a pattern, high-water mark logged, error if the slack
  is touched), then one value at a time with the owner present. Raising the DDR / core clock is excluded (no
  independent DDR clock is known; 640 MHz is the crash path).
- **Pass:** a configuration with `nr3d_overflow` +0 over 60 s at the rate used by day, then a 2 h soak at +0 with no
  kernel error and a visible noise gain.

### HOOK-01 First-install hook: stricter checks and U-Boot built-in environment (`[stock-hook-review]`) — `passed` (2026-11-12, .11 rc40: built-in U-Boot env verified to boot stock kernel from flash)

- **Result (2026-11-12, `.11` rc40, read-only `mtd0ro` dump):**
  - `bootdelay=1`
  - `bootcmd=run boot_normal`
  - `boot_normal=readcfg; run read_kernel; bootm ${loadaddr}`
  - `read_kernel=sf probe 0:0 ${sf_hz} 0; sf read ${loadaddr} ${kernel_addr} ${kernel_size}` (`loadaddr=0x82208000`, `kernel_addr=0x36000`, `kernel_size=0x200000`)
  - Built-in U-Boot environment loads the stock kernel from SPI flash and runs `bootm`: power-cut during `envtool` write recovers to the stock firmware without a serial console. `internals.md` updated.

- **What (read-only Fable review of `stock-hook.sh` + `envtool.c`, 2026-11-12: no brick path in the code):**
  - `tc100-3/known-stock.txt` is now a required file (with its 32-digit `uboot` md5 line): without it the U-Boot / root / `/usr` md5 checks were skipped
    (only a note) and the environment was still written on an unidentified camera.
  - The flash copy on the card is read back after `drop_caches`, so a card that loses writes fails the md5 check
    instead of passing from the page cache.
  - An unexpected `envtool` exit (killed, >= 128) no longer logs "Nothing was written to the flash"; it says the
    environment may be incomplete and points to `env-stock.bin`.
  - **Open, the one brick question:** after a power cut in the middle of the environment write, U-Boot uses its
    built-in environment; nobody has checked that this one boots the stock firmware (`internals.md`, "What is not
    covered yet" 1).
- **Switch:** none (the hook runs once per new camera); revert the commit for the old checks.
- **Test (read-only, no card needed, on a camera running 3.0 from its flash, over ssh):**
  `m=$(grep '"boot"' /proc/mtd | cut -d: -f1); dd if=/dev/${m}ro bs=4096 count=57 2>/dev/null | tr '\0' '\n' | grep -E '^(bootcmd|boot_normal|bootargs|bootdelay)='`
  (U-Boot's built-in environment is plain text inside its binary). Paste the lines to the implementer; they hold no
  secret. Also record the stock `bootcmd` from `tc100-3/env-stock.txt` if a card from a first install is available.
- **Pass:** the built-in `bootcmd` (directly or through `boot_normal`) loads the kernel from the flash (`sf read` ...
  `bootm`): the power-cut case is then covered; update `internals.md` and close this entry. If it does not, power-cut
  recovery needs the serial console: say so in the install guide.

### KRN-01 `ak_isp.awb_live` writable at run time (`[awb-live-rw]`, patch 0006) — `passed` (2026-11-12, .11 rc40: 0644 writable live, 5 s with `awb_live=1`, zero `division by zero` in `dmesg`, restored to 0)

- **What:** `module_param(awb_live, int, 0644)` instead of `0444` (audit 2026-11-06 D3). The white balance code reads
  it at every frame, so `echo 1 > /sys/module/ak_isp/parameters/awb_live` tries the ISP white balance on the live
  statistics without a reboot, and `echo 0` goes back. Default unchanged (0). `ak39_vi.sub_channel` stays `0444`: the
  driver never undoes it at stream start, so a run-time write would not do what it says.
- **Switch:** none needed (default 0, as before); revert the commit to make it read-only again.
- **Test:** boot the CI kernel from the SD card (`tc100test/c66.img`, RAM only, no flash write). Check
  `ls -l /sys/module/ak_isp/parameters/awb_live` shows `-rw-r--r--` and the value `0`; picture as before. `echo 1`:
  within a few seconds the colours change (blue cast expected, R15-01); `echo 0`: back to the usual tint. No kernel
  message, no capture error, RTSP keeps running during both writes. With `awb_live=1`, also run
  `dmesg | grep -i 'division by zero'`: `_calc_awb_gain()` divides by the pixel count of the current colour bin, guarded
  only by `>= total_cnt_thresh` (patch 0006 ~l. 6582 / 6944); if the sensor configuration sets that threshold to 0, an
  empty live bin logs this warning (ARM32: stack dump, no oops). Not introduced by this change (`ak_isp.awb_live=1` on
  the command line already reached it); if seen, a one-line guard goes in a separate kernel change.
- **Pass:** as above; only then is the kernel a candidate for the next flash update (owner's agreement).


## From: triage of the older `to test` entries on 2026-11-14 (both cameras on rc43, read-only checks; see test-queue.md 'Triage of older entries, 2026-11-14')

### R15-03 One night on rc15 (the defaults) — `superseded: rc15 build note; both cameras on rc43 (2026-11-14)`
- Auto day / night (source luma, the default), night picture settings and low light on: the night switch, the picture
  at night (grain, brightness) against R12, back to day in the morning; IR LED protection lines if any; the
  calibration log (`awb=` now live, `lum=`) copied here: it sets the stock method's thresholds for a later default.

### R15-04 The owner's checks — `superseded: rc15 build note; owner checks now per RC (2026-11-14)`
- R12-07 (the web page: Streams & audio bit rate mode, Day/night switches and live value, Picture anti-flicker, in
  French too) and R12-08 (no SD card: power off, card out, power on, one hour: video, page, Wi-Fi, MQTT, settings kept
  after a page reboot). Then the release: [release-3.0.1.md](release-3.0.1.md).

### R14-02 Night parameter set (R12-01 again, rc14 kernel) — `passed: the night parameter set is the default and in use (10 fps at night, nights of 13-14/11, both cameras) (2026-11-14)`
- As R12-01: dmesg `tuning parameter set 1` at night and `0` at day, the log `ISP: night parameter set of the
  tuning file`, about 10 fps at night, the picture against the day set. Then the rest of R12 on rc14 (R12-02 low
  light at dusk, R12-03 / R12-05 over a night, R12-04 listening, R12-06 listening for the clicks, R12-09 dumps,
  R12-07 and R12-08 with the owner).

- **Results R14 (tester, 2026-10-31 ~12:30-13:00 local, rc14 = 7e45f14, both CIs green); rc14 installed in the .11 flash:**
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

### R12-01 Night picture settings (Day/night page: "Night picture settings of the sensor tuning") — `passed: in use by default since rc13, nights of 13-14/11 on both cameras (2026-11-14)`
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

### R12-03 Day / night "Stock firmware method" source — `passed: vendor + AWB_DAY_CNT=200000 validated (.24 evening/night/dawn 13-14/11) and default since rc43 (2026-11-14)`
- **What:** `DAYNIGHT_SOURCE=vendor` (Day/night page, "Light measurement"): lum = exposure x total gain / exposure
  limit x 40 / picture brightness ("Stock method value" in the live reading), night above 3584 when the white balance
  sees no daylight, day below 1536 when it sees visible light, 3 samples in a row, a switch back within 15 s locks it.
- **Test:** with R12-02 on, the live value in a lit room, a dim room by day (must stay day), at dusk and at night; then
  the source on "Stock firmware method" through one dusk and one dawn: one switch each way, the console lines `vendor
  lum=... awb day=... visible=...`, no flapping when the IR LEDs come on. The calibration log (`lum=` and `awb=`) here.
- **Pass:** clean switches both ways, the dim day room stays day. Then (rc13) the default source.

### R12-08 A camera with no SD card (the goal) — `passed: the .11 runs in flash mode with no card (no mmcblk) for days: video, web, Wi-Fi, MQTT ok, settings kept across reboots, day/night; the speaker is covered by AEC-01 / talk tests (2026-11-14)`
- **What:** the flash already holds kernel, initramfs, user space, vendor libraries and the settings; U-Boot tries the
  card first and boots the flash without one (the card stays the way back). Nothing is written for this test.
- **Test:** power off, take the card out, power on: video (RTSP, Frigate), web page, Wi-Fi, MQTT, settings kept
  (change one, reboot from the page, still there: R11-03), day / night and the speaker. What needs a card says so
  cleanly: recordings (page message), saved logs (`log-persist` skips), no error loop in `dmesg` / syslog. One hour.
- **Pass:** everything above. **Then the flash-only release (rc14):** the switches that passed become defaults; one
  `update66.sh apply` with the owner's agreement (dump first, `flashw` with read-back, settings kept, as for every rc);
  U-Boot untouched. The camera then runs with no card at all.

- **Results R12 (tester, 2026-10-31 ~10:10-11:40 UTC, rc12 = a25e86e, both CIs green), rc12 installed in the .11 flash:**
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

### R9-00 3.0.1-rc9 on the camera: the 9600K encoder pool is the driver's default — `passed: ak39_venc.pool=9600K default on both cameras (rc43) (2026-11-14)`
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

- **Result (tester, 2026-10-31, rc9 = 6f4900c, CI green) — R9-00 steps 1-3 PASS, step 4 (overnight) running:**
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

- **Results R9-01 to R9-04 (tester, 2026-10-31 07:30-08:20 UTC, IPCAM2, rc9 6f4900c):**
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

### R9-02 Day / night from the ISP exposure: calibration log and measured thresholds — `superseded: ae source not chosen; vendor is the default (2026-11-14)`
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

### R9-04 Encoder: VBR, idle frame rate, and the smart mode's calls — `superseded by ENC-01 (VBR + smart on the free encoder) (2026-11-14)`
- **What:** the encoder side of "use the SoC": `[0] vbr=1` in `rtspserver.conf` (P-08: 6 % less on a noisy night, the day scene not
  measured) and `IDLE_FPS` (F-03, frame rate lowered while nothing moves) were opt-in and not finished. rc9 adds the
  list of optional encoder calls to the log (looked up, never called), so that the vendor smart mode (long GOP on a
  still scene) can be used once its call is known.
- **Test:**
  1. The `encoder library: optional calls:` line of R9-00 step 2, and `strings /mnt/lib/libmpi_venc*.so
     /vendor/lib/libmpi_venc*.so 2>/dev/null | grep -i -E 'smart|gop|_rc|roi'` here.
  2. Day, still scene, 10 minutes each, one Frigate client: main stream bytes per 5 s with `[0] vbr=0`, then `[0] vbr=1`
     in `/mnt/config/rtspserver.conf` (restart `tc100_rtsp` as `v3/autorun-linux66.sh` does). Then a hand moving in front:
     the bytes go back up to the ceiling, no smear or blocks. Frigate keeps recording and detecting.
  3. `IDLE_FPS` as F-03 says (Frigate side: a motion still starts a recording without a missed second).
- **Pass:** VBR saves on a still day scene with no visible loss and Frigate is fine: **then** (rc10) `[0] vbr=1` by
  default. Same for `IDLE_FPS`. Smart mode: implemented only once step 1 shows its call.

### R8-01 / R8-02 results: rc8 (`372a83b`, CI run 41147884892) on IPCAM2, 2026-10-31 01:00 (tester) — `superseded: rc8 build note (2026-11-14)`
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

**Historical R8-02 record (2026-10-31; superseded, not an open test):** the old procedure tried to override the
9600K pool through a test-kernel command line. Do not use that procedure or artifact path. The validated 9600K pool is
now the compiled kernel default; test-only arguments use `pack66/boot66b.sh`'s `EXTRA`.

**Historical implementer response (2026-10-31):** the card test kernel's built-in command line was then
`ak39_venc.pool=9600K flashroot=1 ak39_vi.sub_channel=1` (`CMDLINE_EXTEND`, after the U-Boot arguments; `S39tc100-linux66`
greps `/proc/cmdline` for `flashroot=1`, which holds the appended part). Same artifact name `tc100-linux66-hw02-pool9600k`,
from the CI run of the commit `[rc8] HW-02 card kernel boots the flash user space`. The other artifacts of that run
are the same rc8 build (only the build stamp differs). Historical notes, not current instructions:
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

### HW-08 Exposure state for day / night (`/tmp/cam_ae`) — `passed: /tmp/cam_ae written every 2 s on both cameras and used daily by the vendor source (2026-11-14)`
- **What:** every 2 s `tc100_rtsp` writes `lumi exp_time a_gain d_gain isp_d_gain dark_flag` from
  `AK_ISP_GET_AE_RUN_INFO`. Nothing uses it yet. The day / night daemon decides from `/tmp/cam_luma`, the mean luma
  of the picture *after* auto exposure, which stays near the AE target whatever the light: exposure time and gains
  measure the scene light.
- **Test:** record `/tmp/cam_ae` and `/tmp/cam_luma` in daylight, at dusk, at night with the IR LEDs on and off.
- **Next:** if the values separate day and night clearly, switch `scripts/auto-night-daemon.sh` to them (with
  hysteresis), so the IR light itself does not flip the mode back.

### F-04 Day / night from the ISP exposure (`DAYNIGHT_SOURCE=ae|isp`, opt-in) — `superseded: ae / isp sources not chosen; vendor is the default (2026-11-14)`
- **What:** index `exp_time * a_gain/256 * d_gain/256 * isp_d_gain/256` with `AE_NIGHT_ABOVE` / `AE_DAY_BELOW` (the
  defaults 4000 / 1000 are placeholders), or the ISP's own dark flag; night after 10 s, day after 60 s. Live reading
  on the Day/night tab. Default stays `luma`. Uses the HW-08 data.
- **Test:** note the reading in daylight, dusk, night with IR on and off; set the thresholds (day clearly below the
  IR-lit night index); switch to the `ae` source: no flapping when the IR LEDs come on. Check the gain unit (256 = 1x?).
  **Off:** source "Picture luminance".

### F-06 Memory Guard defaults (warn 6144 / critical 3072 KB) — `passed: defaults 6144 / 3072 / 2048 KB in boot.conf of both cameras, guard off by default, MemAvailable ~17.3-17.6 MB (2026-11-14)`
- **What:** the old defaults (8192 / 4096) sat next to the normal MemAvailable; cameras holding exactly them are
  migrated when the service starts; the warn stage no longer stops `auto-night-detection`.
- **Test:** `/tmp/log/memory-guard.log` shows the migration once; no warn / critical stage in a day of normal use.
  **Off:** `MEM_GUARD_ENABLE=0`.

Not done: 3D-NR (its 6.2 MB reference frame does not fit until HW-01b / HW-02 free memory).

### O-01 Kernel config: less RAM (`defconfig_cma`) — `superseded: the kernel config changed many times since; current baseline MemTotal 59976 kB, MemAvailable ~17.3-17.6 MB on rc43 (2026-11-14)`
- **What:** about 520 KB less kernel RAM and 107 KB less zImage (printk buffer 64 KB, no io_uring / zram / LZ4 /
  ZSTD / signed regdb / inet_diag, slab merging on, small CRC32 tables), squashfs fragment cache 1 block instead of 3
  (2 x 256 KB less per mounted squashfs: stack and vendor in flash mode), `MAGIC_SYSRQ` on (serial break off) so the
  last-resort reboot of `service-watchdog.sh` (`echo b > /proc/sysrq-trigger`) works.
- **Test:** boots from the SD card (c66.img) then from flash; `MemTotal` and `MemAvailable` up by about 0.5 MB, plus
  about 1 MB in flash mode; a full boot log still fits in `dmesg` (first lines are the `Booting Linux` banner);
  Wi-Fi associates (regulatory domain still set: `iw reg get` from ext/); browsing the Settings pages from flash is not
  slower; `echo b > /proc/sysrq-trigger` reboots. **Off:** the previous kernel.
- **Result 2026-10-30, IPCAM2, f9c3d81 (CI run 41089089376), installed in the flash of IPCAM2 (.11) with update66.sh, settings kept (O-01 + O-02 + B-01 + B-02 together):** MemTotal 59932 kB,
  **MemAvailable 15.3-15.9 MB** two minutes after a flash start (rc5 with 0015: 10.8 MB; rc4: 10 MB), no OOM or
  allocation failure, Wi-Fi associates, 15 fps (75 frames per 5 s, about 1 MB), CPU 84 % idle over 10 s with a
  client. Web server answers (`/` 302, `state.cgi` 401 without a session). `curl` over TLS works for the services
  (`CURL_CA_BUNDLE` from autorun: api.github.com 200); note: the serial console shell does not get that variable
  (curl exits 60 there), harmless for the services. BusyBox no longer has `wget` (no script uses it).

### O-02 Smaller initramfs (`v3/initramfs-prune.txt`) — `passed: no hostapd / xz / wpa_passphrase in the RAM image; hostapd in /mnt/ext/bin (rc43, both cameras) (2026-11-14)`
- **What:** hostapd sample config, hostapd_cli, wpa_passphrase, the xz tools and liblzma out of the RAM image (about
  0.45 MB); `mksquashfs` in `ext/` gets its own liblzma.
- **Test:** boot; the rescue access point starts (`sh /mnt/scripts/wifi-rescue.sh` from the serial console, UI-10);
  the 3.0 install path that runs `/mnt/ext/bin/mksquashfs` still starts it (`/mnt/ext/bin/mksquashfs -version`).

### O-03 tc100_rtsp and libakuio.so stripped, `-mtune=arm926ej-s` — `passed: /tmp/tc100_rtsp (202 KB, rc43) starts and streams on both cameras (2026-11-14)`
- **What:** both are copied to /tmp (RAM) at boot; 128 -> 112 KB and 16 -> 13 KB. Unstripped copies (`*.dbg`) are
  in the CI symbols artifact for decoding.
- **Test:** the stream starts (VLC), the STAT line appears; `ls -l /tmp/tc100_rtsp /tmp/libakuio.so`.

### O-04 Shell side: fewer forks, fewer resident processes — `superseded: shell fork work redone and measured in the background frontier answer (11/11) and WEBUI-CACHE-01 (rc43) (2026-11-14)`
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

### O-05 Video server: one read of the encoder output, log rotation, less per-frame work — `superseded: video server per-frame work redone in the rtsp frontier answer (11/11); rc43 streams 24-25 fps, dropped 0 (2026-11-14)`
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

### B-01 Initramfs reduced to the boot essentials: ALSA tools, libasound, dropbear, libz/libgcc_s/libatomic moved to `ext/` — `passed: ALSA tools, dropbear, hostapd in /mnt/ext/bin; dropbear started from ext on both cameras (rc43) (2026-11-14)`
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

### B-02 Slimmer Buildroot base (busybox, alsa-lib, hostapd, wpa_supplicant, dropbear) — `superseded: the Buildroot base has been rebuilt since; rc43 boots and runs on both cameras (2026-11-14)`
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

### O-06 One housekeeper loop for the slow shell daemons — `passed: one housekeeper.sh run loop under service-watchdog.sh on both cameras (rc43) (2026-11-14)`
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

### P-03 Buildroot base cached in the CI — `passed: build-base-rootfs.yml cache in use (last base build 2026-11-05 success, kernel builds reuse it) (2026-11-14)`
- **What:** `build-base-rootfs.yml` keeps the finished `rootfs.cpio.gz`. The key hashes `v3/buildroot/**` and the
  workflow; a hit skips the Buildroot build.
- **Test:** a push that does not touch `v3/buildroot` builds in a few minutes and gives the same base artifact (same
  size as the previous run). A change in `v3/buildroot` rebuilds it.

### P-04 Higher frame rate: 20 or 25 fps at what CPU cost — `answered: at 25 fps with one RTSP client the CPU is 20.6 % busy on the .11 and 30.3 % on the .24 (30 s, rc43) (2026-11-14)`
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

### P-05 User space squashfs in 128 KiB blocks — `passed: rc43 stack.sqfs xz with 131072-byte blocks, mounted on both cameras (2026-11-14)`
- **What:** `stack.sqfs` built with `-comp xz -b 128K` instead of 256K: 2,240,512 B against 2,195,456 on the rc6 tree
  (partition 2,830,336); the full rc7 tree measures 2,306,048 B. A page read from the flash decompresses half as much, and the squashfs caches take about 384 KB less RAM.
  Measured alternatives that do not fit: lzo 2.96 MB, lz4 3.2-3.9 MB; gzip 2.70 MB would fit with 126 KB to spare.
  The `vendor` partition (made at install) is left at 256K.
- **Test:** MemAvailable / Slab after boot against rc6, both in flash mode; `time ls -lR /rom > /dev/null` and the
  first Settings page load after boot.

### P-08 Encoder "smart" mode / VBR — `superseded by ENC-01 (2026-11-14)`
- **What:** `tc100_rtsp` never used the vendor smart mode or VBR (`rc_vbr` was always 0 = constant bit rate). The
  `[video]` change maps global `rtspserver.conf [0] vbr` to `RTSP_VBR`; the explicit `RTSP_VBR_SUB` in `rtsp.env`
  overrides only the sub-stream. The bit rate becomes a ceiling, so a still scene sends less.
- **Test:**
  1. Still scene, then motion, 5 min each: STAT bytes per 5 s with `[0] vbr=0`, then `[0] vbr=1` in
     `/mnt/config/rtspserver.conf`.
  2. Frigate: still records and detects, and the keyframe interval is unchanged.
  3. For the smart mode itself: `strings /mnt/lib/libmpi_venc*.so | grep -i smart` and write the symbols here.
     Smart mode (long GOP on a still scene) needs its call found in the vendor library first.

### P-09 Video server: RTP without payload copies, 384 KB client queues, live MP4 into the send buffer — `superseded: video server reworked since (rtsp frontier answer, R16); rc43 streams cleanly (2026-11-14)`
- **What (commit `[video] ...`):**
  - **RTP:** a packet is a header buffer plus the payload left in the frame copy, sent with `sendmsg` iovecs (UDP);
    TCP queues header then payload. The two payload copies per packet are gone. **Opt-in: `RTSP_UDPSG=1`** (the host
    test shows byte-identical packets for H.264; H.265 framing is not covered there). With it, `RTSP_UDPMMSG=1`
    batches a frame's packets in one `sendmmsg`.
  - **Client queue:** 384 KB by default (was 768), raised to 1.5 s of the main bit rate. A late TCP joiner gets the
    IDR and the P frames that fit at once (`RTSP_QBURST=0`: wait for the next IDR as before). `RTSP_QMAX=<KB>` sets it.
  - **Browser live video:** the fMP4 fragment is built straight into the viewer's send buffer (byte-identical in the
    host test); `RTSP_LIVE_DIRECT=0` restores the old path.
  - **VBR (P-08):** `[0].vbr` is the global setting; `RTSP_VBR_SUB` in `rtsp.env` is an explicit sub-stream override.
  - RTSP tuning switches go in `/mnt/config/rtsp.env`; global VBR and Smart mode stay in `[0]` of `rtspserver.conf`.
- **Test:**
  1. `RTSP_UDPSG=1`: VLC over UDP and over TCP, main H.265 and sub H.264. Clean picture, STAT `snd_ms` lower than
     without. Then `RTSP_UDPMMSG=1`: same picture, nothing in the log.
  2. A TCP and a UDP client together.
  3. `dropped` over 30 min on the real Wi-Fi, default 384 KB against `RTSP_QMAX=768`. A VLC or Frigate reconnect shows
     a picture within about 0.3 s.
  4. The browser live view plays smoothly for 2 minutes.
- **Pass:** every passed switch becomes the default (UDPSG first, once H.265 is clean).

### S-01 Housekeeper restarter; ssh-server (on) and telnet (off) under Services — `passed: service-watchdog.sh restarts the housekeeper; ssh-server on, no telnet on both cameras (rc43) (2026-11-14)`
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

### W-01 Web UI: statusline in its own CGI, one stylesheet — `superseded: statusline and dash are answered by httpfront natively ([httpfront-native]) (2026-11-14)`
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

### R8-01 3.0.1-rc8 on the camera — `superseded: rc8 build note (2026-11-14)`
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

### R9-03 Anti-flicker (`POWER_HZ`, Settings, Picture) — `passed 2026-11-14 (.24 rc43): POWER_HZ=50 live, log and status follow, off again restores; the tuning file is already 50 Hz (281 lines), brightness unchanged; no default change needed`
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

### HW-05 Sharpness by the ISP (Image page, `SHARPNESS`) — `passed 2026-11-14 (.24 rc43): sharpness -50 / 0 / +50 live, log medium/high 0/1/2, edge energy 5.7 / 13.0 / 19.9; config restored (same md5)`
- **What:** the Sharpness slider is back on the Image page. `tc100_rtsp` scales the tuning file's medium and high
  frequency gains (`AK_ISP_SET_SHARP`, manual and 9 gain-linked sets) by 2 % per step. On by default (nothing is written
  while the slider is at 0).
- **Test:** live tuning on, sharpness -50, 0, +50: log `sharpness: N in the ISP (medium a -> b, high c -> d)`; the
  picture gets softer / sharper (compare snapshots of the same scene); bit rate goes down / up a little. The "Applied on
  the camera" line under the form shows the value.
- **Fail:** picture broken or unchanged at ±50: note the logged gains; `RTSP_ISPTUNE` does not cover it, set SHARPNESS=0.

### P-01 IP multicast in the kernel (ONVIF discovery) — `passed 2026-11-14: wlan0 joined 224.0.0.251 and 239.255.255.250; WS-Discovery Probe answered by both cameras with their XAddrs`
- **What:** `CONFIG_IP_MULTICAST=y` in `defconfig_cma`; ONVIF WS-Discovery needs it.
- **Test:**
  1. Turn ONVIF on in Services.
  2. Home Assistant (ONVIF integration, "discover") or ONVIF Device Manager finds the camera without typing its IP.
  3. `cat /proc/net/igmp` lists 239.255.255.250 on wlan0 while monvifd runs.
- **Off:** the previous kernel.

### WIFI-TRY-01 Safe `rtl8xxxu` runtime parameter trial script (`scripts/wifi-try.sh`) — `passed 2026-11-14 (.11 rc43): unconfirmed tx_atten=6 reverted after 30 s, confirm keeps the value, refusal when the gateway does not answer; three 600 s trials reverted on time; pre-check now retried 3 times (the .11 stalls made one try fail)`
- **What:** Added `scripts/wifi-try.sh` (`<ampdu_rx=0|1|tx_atten=0..30> [window_s]`, plus `confirm`/`revert`/`status`), automating safe parameter trials over SSH without toggling `wlan0`. Refuses if the rescue AP is running or if the default gateway is unreachable beforehand; saves the previous sysfs value in `/tmp/wifi-try/prev` and spawns a detached watcher that reverts automatically after 3 consecutive gateway ping misses or when `window_s` (default 120s) expires without `wifi-try.sh confirm`.
- **Switch / revert:** Manual `scripts/wifi-try.sh revert` or waiting for the timer window; script writes only to `/sys/module/rtl8xxxu/parameters/{ampdu_rx,tx_atten}` and `/tmp/wifi-try/*`.
- **Test:** On a camera connected over Wi-Fi (not rescue AP): run `scripts/wifi-try.sh tx_atten=6 30` (do NOT confirm) and verify `tx_atten` returns to `0` after ~30 s; run `scripts/wifi-try.sh ampdu_rx=0 30` followed by `scripts/wifi-try.sh confirm` within 30 s and verify `ampdu_rx` remains `N`.
- **Pass criteria:** No Wi-Fi drop required, automatic revert restores the exact prior sysfs value on expiry or simulated gateway loss, `confirm` keeps the tested value (host unit tests `tests/test_wifi_try.py` pass).
