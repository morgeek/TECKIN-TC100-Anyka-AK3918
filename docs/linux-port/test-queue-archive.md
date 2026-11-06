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

- **Result R10-01 (tester, 2026-10-31, rc10 = c9fc2ec, CI green): steps 1-3 PASS.**
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

### R8-00 rc8 CI: the kernel workflow FAILS on `e99b302` and on `9737a2d` (tester, 2026-10-31 01:10) - nothing to test yet
- Runs 41146850236 (`e99b302`) and 41147148222 (`9737a2d`), workflow "Build Linux 6.6 LTS Kernel ...", job "Compile Linux 6.6 + Anyka AK3918 +
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
- The workflow added in `9737a2d` for the pool-9600K card kernel runs after this step, so it has not been exercised either.
- **Implementer (2026-10-31): fixed in `116036a`,** a variant of (a). A comment-only file is not enough: checked with
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
- **Result so far (tester, 2026-10-31, build f957b90, CI green) — steps 1-5 PASS, 6-7 running:**
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

- **Result 2026-10-30 19:45, IPCAM2, de377eb, owner looking at the LED: case (b) for both colours.** At the start:
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
- **Result 2026-10-30, IPCAM2 (.11), build a3bd5d7 (CI run 41032639092), kernel of the same build booted once from
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
- **Result 2026-10-30 evening, IPCAM2, build de377eb (CI run 41089089376), installed in the flash of IPCAM2 (.11) with update66.sh, settings kept:** step 1 (default): `encoder pool: 3456000-byte guard at
  its start (phys 0x81800000)`, about 1.0 MB per 5 s, **no `pool guard:` report**. Step 2 (`RTSP_POOLPAD=0`, pool
  used 7946976 / 8866880 = the failing HW-01 layout): **streams normally for 5 min** (59 STAT lines, lowest 0.90 MB
  per 5 s after the first). And the a3bd5d7 CI binary that failed this morning (md5 c66a4edf...) also streams
  normally on this kernel (15 STAT lines, 0.86-1.03 MB). **The HW-01 failure is not reproduced**: it was not the
  pool layout of `tc100_rtsp` alone. It happened on the a3bd5d7 kernel, in the session that ended with the Wi-Fi
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
- **Result 2026-10-30, IPCAM2, build a3bd5d7, test 1 (default): passed for memory.** dmesg `video encoder: ...
  pool 12288 KiB at 0x81800000 (CMA)`, MemTotal 59436 kB (47164 before), MemAvailable 10.8 MB (unchanged), no OOM,
  video 15 fps with the rc5 `tc100_rtsp` (which keeps the 3.4 MB copy at the start of the pool). Test 2 not run
  (needs HW-01). See HW-01: the area at the start of the pool may be the one being overwritten.
- **If it passes:** put the measured size in `flashargs` / `stock-hook.sh` (U-Boot environment: ask the owner first),
  or as the default in the device tree (`anyka,pool-size` is not used for CMA; change `reg` size or add a default in
  the driver).

### HW-03 USB host: FIFO data in 32-bit words (kernel patch 0013, `otg_hs.fifo32=1`) — `to test`
- **Result 2026-10-30, IPCAM2: Wi-Fi dead after the a3bd5d7 kernel, survives resets.** The a3bd5d7 kernel (fifo32
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
- **Result 2026-10-30 evening, IPCAM2, after a power cut:** Wi-Fi back. 3 cycles "de377eb kernel booted from the
  card with a stream, then `reboot` into the rc5 kernel": Wi-Fi associates every time (about 16.5 s). Then de377eb
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
- **Result 2026-10-30, IPCAM2, de377eb:** `/mnt/sd/logs/boot-0001` and `boot-0002` created about 120 s after the
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
