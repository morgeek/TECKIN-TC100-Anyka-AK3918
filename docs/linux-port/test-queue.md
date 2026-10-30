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

### LED-01 Front LED stays red, the Settings LED switches do nothing visible — `failed` (owner's report, first)
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

- UI-01 `passed` (2026-10-30, 563dbff: crond, crontab, mkfifo, timeout, usleep all present) — Busybox applets: `busybox --list | grep -E '^(crond|crontab|usleep|mkfifo|timeout)$'`. Without
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
  the user space; moving them would save 0.78 MB more), init scripts, `udhcpc` script, telnetd start.
  How callers find the moved files: `/usr/bin/aplay|arecord|amixer` and `/usr/share/alsa` are links into `/mnt/ext`
  (CGIs run with busybox httpd's reset PATH, `tc100_rtsp` does `execlp("arecord")`), `etc/ld-musl-arm.path` is baked into
  the initrd (`/lib /usr/lib /mnt/ext/lib`, same as autorun writes), `etc/profile.d/tc100-ext.sh` adds `/mnt/ext/bin`
  to login shells, `S50dropbear` is `v3/S50dropbear-linux66` (looks in `/mnt/ext/bin`, then `/mnt/sd/ext/bin`: in SD mode
  `/mnt` is the card only after autorun, the card is already at `/mnt/sd`; no dropbear = a console line, telnetd
  unchanged). `S39tc100` logs a warning if the user space has no `ext/bin/aplay`.
- **Off:** none at run time. The initrd and the user space must be updated together (the updater writes `stack` first,
  `initrd` last; a card tree must be the one of the same build). New initrd + old user space = no audio tools, no ssh
  (telnet and everything else work); old initrd + new user space works.
- **Test** (flash mode, then SD mode `tc100test/c66.img` + card tree, then flash mode with the card removed):
  1. `/proc/cmdline` shows the full initrd size; `free`: MemAvailable about 1.7 MB higher than before.
  2. `ls -l /usr/bin/aplay /usr/share/alsa` (links to `/mnt/ext`), `aplay -l` and `arecord -l` list the card,
     `amixer -c 0 scontents` works from the serial shell and from an ssh session (`PATH` has `/mnt/ext/bin`).
  3. RTSP with audio plays (VLC: sound), the web UI Listen button and the Talk / sound test (speaker) work,
     `pidof arecord` while an audio client is connected.
  4. `ssh root@<ip>` works (password of config/user.pwd) and `ps | grep dropbear`; boot log has `Starting dropbear sshd: OK`
     and no `dropbear is not in the user space` line. `telnet` still answers where S50telnet was answering before.
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

Not done (listed for later): `cma=16M` (about 4 MB more for the kernel if 4 capture slots still fit: needs the owner's U-Boot
change); moving wpa_supplicant + libnl out of the RAM image too (0.78 MB more, but no network without the user
space); the Buildroot `S50telnet` (busybox telnetd on port 23 at every boot) and `S50dropbear` still start from the base image's
init.d: owner's decision whether they stay; `CONFIG_IP_MULTICAST` is off, so ONVIF discovery (off by default) cannot
work.
