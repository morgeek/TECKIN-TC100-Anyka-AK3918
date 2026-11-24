# Test queue: changes waiting for a run on a real TC100

Several agents work on this repository. The ones without the camera write code; another one runs it on the camera.
This file is the hand-off between them. **Implementers:** add an entry for every change that needs the camera, with a
switch to turn it off. **Testers:** run the entries, write the result under the entry (date, camera, build, numbers),
set the status, and, when it passes, make the change the default in a follow-up commit (or say why not).

Status values: `to test`, `testing`, `passed`, `failed`, `blocked`.

Finished entries (passed and made the default, superseded or abandoned) are moved to [test-queue-archive.md](test-queue-archive.md); this file keeps what is still open.
Closed entries moved to test-queue-archive.md on 2026-11-06. Status labels in the older dated sections below are
historical snapshots, not a second current backlog; use the owner-confirmed list above for current work.

**Current field summary (2026-11-14):** both cameras on **3.0.1-rc43** (build `495609d`, CI green), installed by web
update and validated the same morning (see "State on 2026-11-14" just below and the dated results at the end). Both
ran with 0 reboot, 0 oops, 0 3D-NR overflow, 0 Wi-Fi URB error. Older entries below remain as the audit trail.

Rules that apply to every entry:
- Test kernels boot from the SD card in RAM (`pack66/boot66b.sh`, `tc100test/c66.img`); nothing is written to the flash.
  Pass test-only kernel arguments with `EXTRA` to `boot66b.sh`; do not edit `bootargs` or enter U-Boot commands. After
  boot, check that `/proc/cmdline` holds the full initrd size and every requested argument. If anything is missing,
  stop and report the result before interpreting the test.
- Changes to `tc100_rtsp` can be tried without a reboot: `v3/dev/try-rtsp.sh CAMERA BINARY [VAR=value]`, or switches in
  `/mnt/config/rtsp.env` followed by a restart of the server (`controlscripts/rtsp-h26x restart`).
- The CI build of a change is the run whose title starts with the commit's prefix (`[hwaccel]` for the entries below):
  artifact `tc100-linux66-cma16-kernel` (`oipc.img`, `tc100test/*`, `tc100_rtsp`).
- Measure with the `STAT` lines of `/tmp/logs/tc100_rtsp.log`, `scripts/cpu-profile.sh 60`, `/proc/meminfo`
  (`MemAvailable`), `/proc/interrupts` (two reads 60 s apart), and look at the picture (snapshot, VLC).
- Memory of a process: **PSS** (`awk '/^Pss:/ {print $2}' /proc/<pid>/smaps_rollup`, KB), not RSS. RSS counts the busybox
  and C library pages shared by every shell once per process (the C MQTT bridge looked 5 MB lighter in RSS, 0.9 MB in PSS).

## State on 2026-11-14 (rc43 on both cameras): closed subjects, do not rework
Validated on the cameras and made the default where it applies; the entries are in test-queue-archive.md or marked here.
- **3D-NR always on (`NR3D=1`, default since rc43):** NR3D-01 + NR3D-02 passed, 0 overflow on both cameras by day
  (1080p / 720p, 25 / 20 fps) and by night (10 fps) over 18-21 h, and again on rc43 after boot and reboot. Archived.
- **Day / night stock method (`DAYNIGHT_SOURCE=vendor`) with `AWB_DAY_CNT=200000` (default since rc43):** an evening
  under a dim lamp in colour, night in the dark, dawn without bounce (.24, 13-14/11); on rc43 both cameras in day mode
  with counts 0.4-1.0 M. IR-cut day 592 / night 593 is the board default. Night part on rc43: next dusk (routine check).
- **Patch 0017 (3D-NR UV plane in the encoder pool)** and **KRN-01** (`awb_live` writable), **HOOK-01** (U-Boot built-in
  environment): passed, archived.
- **Web UI on busybox 1.37 and 1.36 (`json_escape` without awk gsub, Frigate `has_ip` literal match):** host tests on both
  busybox versions + mawk/gawk; on the cameras 12 + 17 JSON answers valid, special characters valid. WEBUI-CACHE-01
  camera side passed (browser tab check left to the owner).
- **Reboot reason + day/night log saved before a reboot (`reboot-tracker.sh`, `daynight-last.log`):** passed on both.
- **Wi-Fi / HCD read-only counters (patches 0020 / 0021, `wifi-stall-watch.sh`), merged into main for rc43:** passed on both
  cameras (all counters present, coherent, no error). They did their job in WIFI-STALL-01 (USB/HCD path refuted).
- **CI flakes fixed (supervisord, mqttd, wq_now / route, backchannel one-talker race):** CI green on `bf84a38` and `495609d`.
- **Web update (UPD-01 part a):** rc41 -> rc42 -> rc43 by the web page on both cameras, config and host key kept.

**Still open (in priority order):** WIFI-STALL-01 (next: `ampdu_tx` switch, owner's decision), AWB-01 step 3 (owner,
white paper / tungsten), UPD-01 (b), WIFI-TRY-01 / WIFI-TXATTEN / WIFI-RXAGG on a camera, ENC-01 and AEC-01 measurements,
HW-09 night part, the patch 0003 `finish_request_epx` fix (a-faire-implementeur.md, 13/11), HRTIMER-01, MQTT-HA-01, ENC-02
(just below, 2026-11-15), and the
older `to test` entries below.

## Audit of 2026-11-16 (`[audit-1116]`): fixes waiting for the camera

The findings and the reasons are in [audit-2026-11-16.md](audit-2026-11-16.md). Each fix was read by the reviewer agent
(no blocker left). None of them ran on a camera yet. Test the kernel entry on the SD kernel first, one kernel change
per flash write.

### AUDIT-1116-KERNEL Kernel robustness fixes (patches 0001, 0005, 0006, 0007, 0008, 0014) — `to test`
- **What:** the encoder IRQ arm/mask is balanced in every path (no IRQ masked for good after a SIGTERM during a wait),
  `mmap` bounds cannot wrap, the delayed audio capture start cannot restart DMA after STOP (plus a NULL check in the L2
  callback), the I2C poll times out after 10 ms (plus the partial-word offset and per-message address), the OSD ioctl
  size checks cannot wrap, and the restart register is mapped at boot. After the Fable review: a refused OSD bitmap
  leaves the current OSD running (the update flag is cleared only after the size check) and `AK_ISP_SET_OSD` returns
  the refusal instead of 0.
- **Revert:** boot the previous CI kernel from the SD card (no switch, compiled in). Do not flash before it passes.
- **Test:**
  1. Boot and check `/proc/cmdline`. Check dmesg for oopses and I2C timeouts.
  2. Run 3 h of 1080p H.265 with audio (`-a 1`).
  3. Do 50 `kill -TERM` of `tc100_rtsp` while it streams, then restart it with the autorun arguments. Video must come
     back each time, and the encoder line of `/proc/interrupts` must keep counting.
  4. Do 200 fast audio client connect/disconnect cycles.
  5. Do 20 stream stop/start cycles.
  6. Bring Wi-Fi down and up 10 times while streaming.
  7. With `RTSP_ISPOSD=1`, check that the clock is drawn and keeps ticking for the whole 3 h run.
  8. Reboot 5 times from the web UI and by `reboot`.
- **Pass:** no oops or kernel error, the 3 h run is stable, the encoder IRQ is alive after every kill, and every reboot
  comes back.

### AUDIT-1116-USB Anyka USB host: unlink of the active URB, locked `endpoint_disable`, ep0 dispatch (`[usb0003]`, kernel patch 0024) — `to test`
- **What:** `0024-usb-host-anyka-give-an-unlinked-active-URB-back-at-o.patch`, on top of 0003/0013/0021/0022. The
  transfer paths (enqueue, interrupt handler, `done`) are not changed. Built by the local kernel CI only, never run on
  a camera.
  1. `urb_dequeue`: the transfer in progress is stopped and its URB given back at once, whatever its age. Before, a
     packet started less than 20 ms earlier was left to the next interrupt of its endpoint. For a bulk IN packet that
     interrupt never comes when the adapter has nothing to send, and `usb_kill_urb()` slept for good. `rtl8xxxu_stop`
     (interface down) kills the receive URBs right after it has closed the receive filters, so this is the path of a
     hung `ifconfig wlan0 down`. For an IN transfer the request is withdrawn by a plain write of RXCSR1 and the FIFO
     is flushed only when it holds a packet (`flush_epx_rx_fifo`): a flush of an empty FIFO can corrupt its pointer,
     and this path now runs at every interface down (review of 2026-11-16).
  2. `urb_dequeue`: ep0 is finished by `finish_request_ep0()` (chosen on the endpoint number). Before, it almost always
     went through `finish_request_epx()` and `next_async_epx[-1]`, which is `next_async_ep0` by the layout of the
     structure: the same result, by luck.
  3. `endpoint_disable` runs under the controller lock, clears every pointer to the endpoint before it frees it, and
     enables the endpoint interrupt again after the flush. Before, the interrupt stayed masked until the next
     disconnect (the driver only enables it when it maps the FIFO), so the endpoint was dead after a driver unbind or a
     `usb_reset_device` without a disconnect.
  4. `endpoint_reset` (empty until now for these endpoints) clears the data toggle of a mapped, idle endpoint. usbcore
     calls it when the device starts again at DATA0 (`usb_reset_device`, set interface, clear halt); without it the
     first packet could be taken for a repeat and dropped. It is not done in `endpoint_disable`: an unbind keeps the
     toggles of the device (`usb_unbind_interface` re-enables the interface "without affecting the endpoint toggles").
     Nothing changes before the first transfer of an endpoint (not mapped yet).
- **Switch:** `echo 1 > /sys/module/otg_hs/parameters/unlink_wait_irq` (0644, read at each unlink, endpoint disable
  and endpoint reset; `otg_hs.unlink_wait_irq=1` on a test command line) restores the 20 ms rule and the unconditional
  FLUSHFIFO of point 1, leaves the interrupt masked in point 3 and the toggle alone in point 4. The lock of point 3 and the dispatch of point 2 have no switch. Revert = the previous CI
  kernel from the SD card.
- **Test** (SD kernel in RAM first, nothing in flash; **from the serial console**, the Wi-Fi is the only network):
  1. Boot, check `/proc/cmdline` (full initrd size). Wi-Fi associates as before, `dmesg` has no USB error, no
     `WARNING` (`otg-hs: ep... disabled with URBs queued` must never show).
     `cat /sys/module/otg_hs/parameters/unlink_wait_irq` prints `N`.
  2. 20 times, while an RTSP client is streaming (traffic makes the receive URB young): `ifconfig wlan0 down`, wait
     2 s, `ifconfig wlan0 up`, wait for the association. Each `down` must return within 1 s. Note the time of each.
     Then 10 cycles of `ip link set wlan0 down`, 2 s, `ip link set wlan0 up`, each followed, once associated, by a
     30 s ping of the camera from the LAN (no loss after the first second) and by opening the RTSP stream (picture
     within the usual delay): this is the check of the receive FIFO after the abort of point 1.
  3. 5 times `wpa_cli -i wlan0 reassociate` and 3 Wi-Fi restarts by the web UI (settings save).
  4. Endpoint disable (the Wi-Fi driver is built in, there is no `modprobe -r`): `ls /sys/bus/usb/drivers/rtl8xxxu/`
     gives the interface name (`1-1:1.0`); `echo -n 1-1:1.0 > /sys/bus/usb/drivers/rtl8xxxu/unbind`, then the same to
     `bind`, restart the Wi-Fi service, wait for the association. 5 times. For comparison only, once with
     `unlink_wait_irq=1`: by the reading of the code the Wi-Fi does not come back until a reboot (report what happens).
  5. 5 reboots (`reboot` and the web UI): each one ends (a hung unlink would block the shutdown) and comes back.
  6. 12 h soak: 1080p H.265 RTSP stream with audio, `wifi-stall-watch.sh 60` running. Compare `bulk_out_nak`,
     `bulk_in_oldest_ms`, `rx_urb_lost` / `rx_urb_alive` and the stall count with a night of the previous kernel.
- **Pass:** every `down` of step 2 returns (no process stuck in `usb_kill_urb`, no `task ... blocked for more than`
  in `dmesg`), the Wi-Fi comes back every time in steps 2 to 5, no oops, `WARNING` or soft lockup, and the 12 h soak
  shows no more stalls or lost receive URBs than the previous kernel. If the Wi-Fi does not come back: power cycle
  (flash firmware), write `unlink_wait_irq=1` at boot and repeat the failed step to tell points 1, 3 and 4 from the
  rest. Every ping and RTSP view of step 2 works.
- **Known and left as is:** after the unlink of the head URB the next URB of the same endpoint is started by the next
  enqueue or interrupt, not by the unlink (same as before for a packet older than 20 ms; the Wi-Fi driver and usbcore
  unlink from the tail). An interrupt of the stopped packet that was already pending is ignored, as before. The
  `BUG()` of the resume timer and the dead DMA code of patch 0003 are not touched.

### AUDIT-1116-VENCIRQ Encoder interrupt: no replay of a late interrupt at the next wait (`[venc-irq]`, kernel patch 0025) — `to test`
- **What:** `ak39_venc` disarms the encoder interrupt with `disable_irq_nosync()`, which was lazy (line left unmasked).
  An encoder interrupt that came with nobody waiting (after the 2 s timeout, after a signal during the wait, after
  the last close: the picture in progress still ends) was noted as pending by the IRQ core and, the controller of
  patch 0001 not marking its lines `IRQ_LEVEL`, replayed in software at the next `enable_irq()`: `AKUIO_WAIT_IRQ`
  returned 0 at once with nothing encoded, libakuio read an end status of 0 and reported result 0, and the free
  encoder took the stream buffer of a core that was still encoding. The likeliest way in is a `kill -TERM` of
  `tc100_rtsp` (it spends most of its time in that wait): the note survives the close and hits the first picture of
  the next process. Patch 0025 sets `IRQ_DISABLE_UNLAZY` on the line: disarmed = masked at the controller, nothing is
  noted. The line is a level (no latch, no acknowledge in the controller; the end status 0x8018 stays set until user
  space clears it), so an end that is still pending fires at the next unmask: no interrupt is lost. The `irq_armed`
  accounting of AUDIT-1116-KERNEL is unchanged (the patch only adds lines). Compiled by CI only, never run.
- **Switch:** `echo 0 > /sys/module/ak39_venc/parameters/irq_unlazy` (0644, read at every wait) restores the lazy
  disable; `echo 1` turns the fix back on (a note taken while it was 0 can still be replayed once). Or boot the
  previous CI kernel from the SD card. SD kernel first, do not flash before it passes; one kernel change at a time
  (not together with patch 0024 if a failure must be attributed).
- **Test:**
  1. Boot the SD kernel, check `/proc/cmdline` (full initrd size) and `cat /sys/module/ak39_venc/parameters/irq_unlazy`
     (`Y`). Note the encoder line: `grep venc /proc/interrupts`.
  2. 3 h of 1080p H.265 with audio (`-a 1`), a client connected. Every 30 min read `grep venc /proc/interrupts` and
     the last `STAT` line: the interrupt count must grow at the rate of the encoded pictures (`enc` + `sub_enc`, plus
     the JPEG snapshots taken), not faster (a replay adds an interrupt without a picture) and without 2 s holes.
     In the log: no `free encoder: ... picture failed` line; `enc_ms` stays at its usual value (a replayed wait gives
     a picture "encoded" in about 0 ms, a lost interrupt gives 2000 ms).
  3. 50 times, while a client plays the stream: `kill -TERM` of `tc100_rtsp`, then restart with the arguments of
     `v3/autorun-linux66.sh`. After each restart: the video comes back, the first picture decodes (`ffprobe` or VLC
     without a grey / broken first GOP), the log has no `picture failed` line with `wait 0; after: 8018 00000000`
     (the signature of a replayed wait: success reported, empty end status), and the encoder line of
     `/proc/interrupts` counts again.
  4. Control, to know whether the defect showed at all on this camera: `echo 0 > .../irq_unlazy`, repeat 20 of the
     kills of step 3 and compare the first pictures and the log; then `echo 1` and one more kill + restart (this one
     may still show one replay), then five clean ones.
  5. Induced timeout, optional and only with the owner next to the camera (it stops the encoder clock from Linux, a
     reboot undoes it; nothing is written to the flash): while streaming, gate the encoder clock for 3 s (bit 18 of
     SYSCTRL 0x0800001c, e.g. `v=$(devmem 0x0800001c); devmem 0x0800001c 32 $((v | 0x40000)); sleep 3; devmem
     0x0800001c 32 $v`, if the image has `devmem`). Expected: `picture failed` lines with `wait -1` during the gate
     (2 s each), then the stream resumes by itself with an IDR, the interrupt count grows again, and no later picture
     is reported in 0 ms. Pausing the sensor does not give this timeout (the encoder reads the frame from memory;
     the capture stall has its own exit, AUDIT-1116-RTSP). This step checks the recovery after a timeout; the late
     interrupt itself is produced by step 3.
  6. `dmesg`: no `irq NN: nobody cared`, no `Unbalanced enable for IRQ`, no oops.
- **Pass:** 3 h without a stall, a restart of `tc100_rtsp` or a failed picture; the interrupt count follows the
  picture count; 50 of 50 restarts give a clean first picture and a counting interrupt line; after the induced
  timeout (if done) the stream resumes without a restart; no kernel message. A 2 s stall per picture with
  `irq_unlazy=1` that disappears with `=0` would mean a lost interrupt (the line is not the level it is taken for):
  fail, leave the switch at 0 and report.

### AUDIT-1116-BOOT Boot counter saved at once after an unclean end — `to test`
- **What:** `boot-guard start` saves the counter synchronously when the previous run did not end with a requested
  restart, or when the count is already >= 1. A crash at video start is now counted, and safe mode is reached on the
  4th start. After a crash or power loss, the boot takes about 10 s longer.
- **Switch:** `BOOT_GUARD=0` in `boot.conf` turns the whole guard off.
- **Test:**
  1. Pull the power, then check that the boot log shows the synchronous save and that `/mnt/config/.boot-guard` holds
     the new count.
  2. Make the video server crash at start 3 times in a row, for example with a broken `tc100_rtsp` from `try-rtsp.sh`.
     The next start must be in safe mode (`/tmp/safemode`).
  3. Reboot cleanly from the web UI. The boot time must be unchanged.
- **Pass:** safe mode is reached after repeated early crashes, and a clean reboot is not slower.

### AUDIT-1116-RECOVERY Rescue mode of the initramfs when `stack` is damaged (`[recovery]`) — `to test`
- **What:** the initramfs boot script (`v3/S39tc100-linux66`, step 1a) checks the `stack` partition before using it:
  squashfs magic, size against the partition, end of the image written (an update cut by a power loss leaves an
  erased start or end), mount, start files readable, `flashmode-prep.sh`. When one fails:
  1. an SD card that carries a user space (the 3.0 package) starts the camera in SD mode, as before;
  2. else **rescue mode** (`v3/initrd-rescue`, `/etc/tc100/rescue` in the initramfs): Wi-Fi and password from the
     settings slots `cfga`/`cfgb` (read-only; `wpa_supplicant.conf` of the card is tried in turn when the saved
     network gives no link), and a telnet on port 23 for the private networks only (`tcpsvd` + address check, login
     `root` with the camera password). No video, no web. `/etc/tc100/rescue help` and `images` give the command that
     writes a user space back: `FLASHW_ALLOW=stack flashw -m <md5> stack <file>` (`flashw` is now in the initramfs).

  Nothing is written to the flash by the initramfs; the write is the owner's. The same telnet opens when a user space
  was started but neither the web interface (80), ssh nor telnet listens 5 minutes later (`rescue watch`); that one
  writes no `/tmp/rescue-mode` and no login banner, and `web-guard.sh` closes it once the web interface is back.
  Not done, and why: the backups of the web update (`tc100-3/backup/stack-*.bin`) cannot be started from the card
  (the kernel has no loop device), they are images to write back by hand; no rescue access point (`hostapd` lives in
  the `stack`, and `wpa_supplicant` is built without AP mode): with wrong saved Wi-Fi settings the way in is a
  `wpa_supplicant.conf` on the SD card. No boot counter in the initramfs either (it would have to write the flash):
  the watcher works within one boot, and a dead user space does not restart the camera.
- **Switch:** `INITRD_RESCUE=0` in `boot.conf` (read from the settings slot when a check fails; a comment after the
  value, quotes and leading blanks are accepted): the behaviour before this change. No rescue mode, no watcher, and
  the two new checks do not count: a stack that mounts and whose `flashmode-prep.sh` succeeds is started. The way
  back is then the 3.0 SD card.
- **Needs:** the new initramfs (`c66rd.gz`). Its size limit (2,012,654 bytes) is checked by the build; two shell
  scripts are added (15 KB of text, under 6 KB of xz), the headroom of the CI image is not measured yet.
- **Test (nothing on the flash is damaged or written):** boot the SD kernel in RAM (`pack66/boot66b.sh`,
  `tc100test/c66.img` + the new `c66rd.gz`), flash mode by `tc100test/flashmode` on the card.
  1. Without any test file: normal start from the flash, no `[rescue]` line on the console, `/tmp/rescue-mode`
     absent, boot time unchanged (the check reads three 4 KiB blocks), and 6 minutes later no `tcpsvd` in `ps`.
  2. `tc100test/stackbad` holding the word `rescue`: the console shows `the user space of the flash cannot be used:
     test file ...` then `[rescue] RESCUE MODE`; the camera joins the Wi-Fi with its usual address; `telnet <camera>`
     from the LAN logs in as `root` with the camera password; `cat /tmp/rescue-mode`; `/etc/tc100/rescue images`
     lists the backups of the card as `good` with the `flashw` line (do **not** run it); `ps` shows no `tc100_rtsp`
     and no `httpfront`; `md5sum /dev/mtd*ro` before and after is the same for every partition.
  3. `tc100test/stackbad` empty, card with the 3.0 package: the user space of the card starts (SD mode).
  4. With `INITRD_RESCUE=0` saved in `boot.conf` (set it from a normal start, wait for the settings save), repeat 2:
     `INITRD_RESCUE=0: no rescue mode` on the console, no `tcpsvd` on port 23.
  5. Watcher: from a normal start, stop the web guard, the service watchdog, `httpfront` and `dropbear`, then run
     `RS_WAIT=60 /etc/tc100/rescue watch /mnt/config/boot.conf`: the rescue telnet opens after a minute; a
     connection from an address outside the private networks gets no prompt.
  6. Remove `tc100test/stackbad` and `flashmode` afterwards.
- **Pass:** 1 to 5 as described, and no partition changed. Only then flash the initramfs (owner's agreement).
- **Owner's questions:** telnet (password in clear) as the rescue door, open as long as the rescue mode lasts, and
  opened whatever `SECURITY_HARDENING_MODE` says, like the rescue telnet of `web-guard.sh`; a rescue access point in
  the initramfs or not; a loop device in the kernel to start a backup from the card.

### AUDIT-1116-UPDATE Update safety: no restart during a write, atomic lock, backups — `to test`
- **What:**
  - web reboot and shutdown, the button (3 s and longer) and the scheduled reboot are refused while a live update lock
    exists. A lock is ignored when its pid is dead or it is older than 30 min.
  - crond and the button watcher are stopped during the write and restarted if the update fails;
  - `update.cgi` takes the lock with `mkdir`;
  - the backup is made on the first attempt only;
  - the SD free space is checked first, counting what the prune of old backups will free;
  - `flashw` syncs the backup and compares it with the flash before the erase.
- **Switch:** none (safety checks).
- **Test:**
  1. During a web update, a reboot from the UI must answer `UPDATE_RUNNING`.
  2. Two install POSTs at once must start one run only.
  3. `crond` and `button-watch` must be absent during the write.
  4. `/tmp/update66.simfail` must leave one good backup per partition.
  5. A card too full even after the prune must be refused before any service stops. A nearly full card whose old
     backups free enough room must go ahead.
  6. Kill the apply process: a web reboot and the scheduled reboot must work again.
- **Pass:** all of the above, and a normal update completes and reboots.

### AUDIT-1116-INSTALL Settings slot check and SD install checks — `to test`
- **What:**
  - `cfg-persist` checks the slot it just wrote (`slot_valid` now reads its argument);
  - `install66.sh` uses the kernel and initrd checks of the web update (`v3/install/imgcheck.sh`) and the published md5;
  - it checks the card space up front;
  - it reads every partition back before it renames `c66.img`.
- **Switch:** none.
- **Test:**
  1. Run `cfg-persist save`, then `status`: both slots must be valid.
  2. On a trial-mode SD install, a corrupted `c66.img.md5` or a truncated `c66.img` must stop the install at the check
     step with nothing written.
  3. A normal install must end with `c66.img.installed` and a boot from the flash.
- **Pass:** all three.

### AUDIT-1116-FLASHBOOT Does a camera installed by `stock-hook.sh` boot 3.0 from the flash? — `owner`
- **Why:** the `flashboot` value written by `stock-hook.sh` is about 270 characters. AGENTS.md says this U-Boot reads
  at most 256 characters per line. The hand-made camera uses the `flashargs` variable form instead. No test record
  shows a hook-installed camera starting 3.0 from its flash.
- **Test (read-only):**
  1. On a camera installed by the hook, take the card out and power-cycle.
  2. It must start 3.0 from the flash (hostname, `/proc/cmdline` with `flashroot=1`).
- **If it fails:** the camera starts the stock firmware (`boot_normal`). The hook must then write `flashargs` and a
  short `flashboot`. This is a U-Boot environment change, so it waits for the owner's agreement.

### AUDIT-1116-RTSP `tc100_rtsp`: monotonic timeouts, capture stall exit, UDP burst, audio gap, SETUP — `to test`
- **What:**
  - every interval timeout uses the monotonic clock;
  - the server exits with status 3 after `RTSP_CAPTURE_STALL_S` (default 30) without a frame, or after 100 DQBUF errors
    in a row; iterations blocked elsewhere do not count, and the service watchdog restarts it with the same arguments;
  - `wait_idr` stays set after a UDP burst that hit backpressure;
  - the audio RTP timestamp skips a microphone gap;
  - ABR uses a generation counter and counts main-stream drops only;
  - a SETUP of a disabled track answers 404.
- **Switch:** `RTSP_CAPTURE_STALL_S=0` in `/mnt/config/rtsp.env` turns off the stall exit. The rest has no switch:
  revert the commit.
- **Test:**
  1. Connect UDP and TCP clients within 30 s of boot. They must survive the NTP step.
  2. Stall a TCP client: it must be closed after 20 s.
  3. Run 1 h or more across a day/night switch, the eco frame rate and the low-light rate: no spurious stall exit.
  4. Force a stall with `RTSP_CAPTURE_STALL_S=5` and SIGSTOP. The log must say "no frame for", exit 3 must follow, and
     the stream must come back.
  5. Kill `arecord` while audio plays: no growing A/V offset, no zombie.
  6. With audio and talk off, SETUP track2 and track3 must get 404 and the video must keep playing.
- **Pass:** all of the above.

### AUDIT-1116-WIFI Same-SSID password fallback, refused characters, rescue AP cap — `to test`
- **What:**
  - saving the current SSID with another password keeps the old one as a priority-1 fallback;
  - `"` and `\` in the SSID or PSK, and bad MQTT password characters, are refused with a message instead of being
    stripped;
  - credential temp files are created with umask 077;
  - the rescue AP stops after `WIFI_RESCUE_MAX_MIN` (default 30) even with clients connected;
  - the dead 2.x branches of wifi-rescue, rec-storage and button-watch are removed.
- **Switch:** `WIFI_RESCUE_MAX_MIN=1440` (cap effectively off). For the fallback, revert the commit.
- **Test:**
  1. In Settings, save the current SSID with a wrong password. `/mnt/config/wpa_supplicant.conf` must hold two blocks.
     Reboot: the camera must be back on the network.
  2. A quote in the password must be refused with the message.
  3. Open the rescue AP (button 3-7 s), connect a phone with the rescue password and wait past 30 min. The AP must stop
     and the station must reconnect.
  4. Press the button 3-7 s (rescue AP), then 8 s (reboot). SD eject and resume must behave as before.
- **Pass:** all of the above.

### AUDIT-1116-NET Login lockout, ONVIF replay, rwconf, netacl, ssh LAN only — `to test`
- **What:**
  - `httpfront`, with `WEB_LOCKOUT=1`, answers 431 when the headers do not end within 4 KB or carry two `Authorization`
    lines;
  - Basic is parsed like busybox httpd, any unverified `Authorization` counts, and a full lock table fails closed for
    5 min;
  - `onvifd` refuses a replayed WS-Security digest (not counted) and escapes the WS-Discovery MessageID;
  - `rwconf` writes atomically and refuses CR/LF;
  - `netacl` filters IPv4-mapped peers and logs a warning when the filter cannot load;
  - **ssh follows `NET_LAN_ONLY`** (owner's decision 2026-11-16): dropbear starts through `netacl_exec`, and fails
    open with a warning if the library is missing.
- **Switch:** `WEB_LOCKOUT=0`, and `NET_LAN_ONLY=0` (also lifts the ssh filter).
- **Test:**
  1. Use the web UI normally (login, Services, Settings, a browser with many cookies): no 431.
  2. `curl -H "X-Pad: $(head -c 5000 /dev/zero | tr '\0' a)" -u root:wrong http://cam/x` must get 431.
  3. 10 wrong logins must lock the address for 5 min.
  4. Connect an NVR or Home Assistant over ONVIF, then unplug and replug the network: it must reconnect without being
     locked out.
  5. Save the password, Wi-Fi and OSD text from the web UI.
  6. ssh from the LAN must work after a normal boot, in safe mode, in SD test mode, from the rescue AP network and
     from 127.0.0.1. `/proc/<dropbear pid>/maps` must show `libnetacl-musl.so` in both flash and SD mode.
  7. From a non-private address (forwarded port, or 4G), the ssh connection must be closed at once. With
     `NET_LAN_ONLY=0` it must reach the prompt.
  8. `logread` must show no "WITHOUT the LAN filter".
- **Pass:** all of the above. **Never lose ssh from the LAN:** if step 6 fails, set `NET_LAN_ONLY=0` and report.

### AUDIT-1116-FTP Does the busybox `ftpd` of 3.0 check the password? — `owner`
- **Why:** `controlscripts/ftp-server` runs `busybox ftpd -w /` under `tcpsvd`, with no chroot. The busybox fragment
  does not name `FEATURE_FTPD_AUTHENTICATION`. FTP is off by default.
- **Test:** turn FTP on and log in with a wrong password.
- **Pass:** the login is refused. If it is accepted, keep FTP off and report: chroot it to the card and require the
  password.

### B2B3-CONF Settings files read whole: buffers too small for boot.conf (`[b2b3-conf]`, audit 2026-11-24 B2/B3) — `to test`
- **What:** `boot.conf.dist` is 23.7 KB. `tc100-supervisord` read it into 16 KB (`REC_WHEN` is at byte 16 461: a sound
  event never started a recording with `REC_WHEN=motion`) and `mqtt.conf` into 8 KB; `tc100-onvifd` read `boot.conf`,
  `rtspserver.conf` and `rtsp.env` into 8 KB (`RTSP_LITE_TALK` at byte 19 177 never seen: the backchannel stayed
  advertised with two-way audio off). All these buffers are 64 KB (tests keep them at least twice the largest `.dist`
  file), and a file that still fills one is reported on the console / stderr.
- **Revert:** the previous build (no behaviour switch: only more of the file is read).
- **Test:**
  1. `REC_LOCAL=1`, `REC_WHEN=motion`, sound detection on, C supervisor (default): a loud sound starts a recording
     (`/tmp/motion_detected` touched, a file in the recordings).
  2. Two-way audio off in Settings (`RTSP_LITE_TALK=0`): within 2-3 s ONVIF Media2 `GetProfiles` has no `AudioOutput`
     (go2rtc / HA no longer offer the backchannel); on again: it comes back.
  3. No `is larger than` line on the console or in the onvif log.
- **Pass:** 1 to 3.

### B1-ONVIF ONVIF sees a password change at once (`[b1-onvif]`, audit 2026-11-24 B1) — `to test`
- **What:** `tc100-onvifd` read `user.pwd` (and `rtspserver.conf`, `boot.conf`, `rtsp.env`, `timezone.conf`) only at
  start and on SIGHUP, and nothing sends SIGHUP: after a password change in the web UI the old password kept working on
  ONVIF until a restart, and a daemon started before the wizard set a password stayed open. Now `user.pwd` is looked at
  (one `stat`) before every authentication and the five files every 2 s; a change reloads the configuration. A password is
  never dropped to "open" by a file emptied 2 s ago or less. `all_password` writes `user.pwd` beside it and renames it;
  if that fails (full file system) the old password stays and the failure is logged (`logger -t all_password`), no
  in-place fallback.
- **Revert:** none needed for the reload (it only re-reads what a restart would); the previous build if something breaks.
- **Test:**
  1. ONVIF client (ONVIF Device Manager, go2rtc or `curl` with WS-Security) logged in with the current password.
  2. Change the password in the web UI. Within a second, the old password gets `NotAuthorized` on ONVIF and the new one
     works, without restarting onvif (`pidof tc100-onvifd` unchanged).
  3. `ls -l /mnt/config/user.pwd`: mode 0600, no `user.pwd.*.tmp` left; `cfg-persist` saves it (reboot keeps it).
  4. Change the sub stream or the codec in the web UI: ONVIF `GetProfiles` shows it within 2-3 s.
  5. CPU: `top` shows no change for `tc100-onvifd` with an NVR polling it.
- **Pass:** 2 to 4 as described, no restart of onvif, no extra CPU.

### B4-HUE The user's hue survives the day / night switches (`[video-fix]`, audit 2026-11-24 B4) — `to test`
- **What:** with `ISP_TUNE=1` and `HUE` not 0, `tc100_rtsp` gave the hue to the ISP and then set its own copy of the
  setting to 0 (that copy was also the "CPU hue table needed" flag). The next `tune_hw_apply` (every black-and-white
  switch, every parameter-set switch) gave the ISP hue 0: from the first dawn the day picture had no hue and
  `/var/run/isp_tune.status` said `HUE=0`, until a config file changed; then for up to 0.5 s the CPU table and the ISP
  both turned the colours. Now the setting (`hue_cfg`) and the CPU table's hue (`p_hue = hue_hw == 1 ? 0 : hue_cfg`)
  are kept apart; the per-byte table runs only when the ISP does not take the hue.
- **Revert:** the previous build (bug fix, no switch). `RTSP_ISPTUNE=0` still forces the tables as before.
- **Test:**
  1. Image page: image tuning on, hue +20, saved. `cat /var/run/isp_tune.status`: `HUE=20`; the log has
     `image tuning: hue 20 in the ISP`; the picture is visibly turned (compare with hue 0).
  2. `/mnt/scripts/nightmode.sh on`, wait 5 s, `/mnt/scripts/nightmode.sh off`, wait 5 s (or the next real dusk and
     dawn): `HUE=20` still in the status file, a new `hue 20 in the ISP` line after each switch, the day picture
     still turned the same way.
  3. Hue -20 in the Image page: within 3 s the status shows `HUE=-20`; no frame turned twice as far (snapshot burst
     or VLC recording around the save).
  4. `pp_ms` of the STAT lines with hue 20 is the same as with hue 0 (no CPU table while the ISP takes the hue).
  5. Night parameter set on (`RTSP_NIGHTSTYLE=1`, the default) and hue +20: two full day / night cycles (real dusk
     and dawn, or `nightmode.sh on` / `off` twice, 30 s apart). After each return to day the colours are the same as
     before the first night (same snapshot of the same scene), never turned further. Why: every parameter-set switch
     runs `isp_bases_reset`, which reads the ISP's hue table again (`hue0`) and turns it by the setting. Kernel patch
     0006 loads the tuning file's hue again on a style switch, so the hue should not stack, but only if the tuning
     file has a hue block for each set; before B4 the hue went back to 0 at the first switch, so this was never
     exercised.
- **Pass:** 1 to 5. If 5 fails (the hue grows at each dawn): report it; the fix is to read `hue0` once per video
  start instead of at every parameter-set switch.

### R1-MDENC Encoder motion detection follows the budget per picture (`[video-fix]`, audit 2026-11-24 R1) — `to test`
- **What:** `RTSP_MD_ENC` (on by default) compares each main-stream P frame with a running mean of the P frame
  sizes, and the mean learns calm frames only. When the free encoder's per-picture budget grows (the capture rate in
  use going down: night parameter set 10 fps, low-light rate, idle rate; an ABR step up) the P frames grow for a
  reason that is not motion, every frame stayed above the old mean, which never learned again (motion "on" all
  night in CBR with a high sensitivity, false events every ~10 s with `IDLE_FPS`). `md_enc_track` now follows the
  main free encoder's budget per picture (`rc.budget`) at every picture, which covers the capture rate, the ABR
  steps and a reopened encoder (compared with the last one's budget):
  - **budget bigger:** the mean starts again (`md_enc_restart`); its warm-up teaches it every P frame at 1/4 weight
    and never triggers, for at least `MD_ENC_WARM_N` (6) P frames and `MD_ENC_WARM_S` (1.5 s). At an idle rate of
    1-2 fps that is 3-6 s without this detector after each drop to the idle rate (the luma grid still watches);
    at 10 fps and above, 1.5 s.
  - **budget smaller** (idle -> full rate when someone walks in, night -> day, ABR step down): no restart (a
    restart taught the mean the frames of the person who walked in: the rest of that walk and a second one soon
    after were missed). In CBR the mean is scaled by new / old budget, then a hold of 6 P frames and 0.5 s neither
    triggers nor learns while the rate control comes down. In VBR the mean is kept (a calm picture sits under the
    ceiling, its size does not follow the budget).
  - the smart floor released without motion restarts it, as before.
  - the vendor encoder has no budget to follow: unchanged there.
- **Revert:** `RTSP_MD_ENC=0` in `/mnt/config/rtsp.env` turns the whole detector off (as before); the previous build
  for the reset alone.
- **Test:**
  1. CBR main stream (vbr 0), motion detection on, sensitivity 90, a still scene, a viewer on the main stream.
     `/mnt/scripts/nightmode.sh on` (the log shows `free encoder main: capture rate 10 fps`) or wait for the idle
     rate. The picture change of the switch itself may count as motion for a few seconds (the luma grid); then
     `/tmp/rec_control` goes back to 0 within ~10 s and stays 0 for the next 5 minutes, no MQTT motion event in
     that time. Same after `nightmode.sh off`. Old build for comparison: with these settings it stays at 1.
  2. Walk in front of the camera 30 s after the switch: motion is still seen.
  3. One night with `REC_WHEN=motion`: no all-night series of motion files in the recordings.
  4. `IDLE_FPS` on, motion zones covering only part of the picture, a still scene at the idle rate. Walk in outside
     the zones (only the encoder detector sees it), stay 10 s, leave, come back 5 s later: motion (`/tmp/rec_control`
     = 1, MQTT event) for the first walk, kept while you stay after the `capture rate 25 fps` line, and again for the
     second walk.
- **Pass:** 1 to 4.

### W1-PRIVFILL Privacy mode paints the chroma with memset (`[video-fix]`, audit 2026-11-24 W1) — `to test`
- **What:** `fill()` (privacy mode, CPU masks, the CPU clock box) wrote the chroma rows two bytes per loop turn into
  the uncached capture memory, ~1 M byte stores per 1080p frame with `/tmp/tc100_privacy`. The chroma rows are now one
  `memset(…, 128, x2 - x1)` each. Same bytes (U = V = 128 everywhere, x1 and x2 even; a host test compares it with
  the old loop on random rectangles).
- **Revert:** the previous build (no behaviour change, no switch).
- **Test:**
  1. Note `pp_ms` and `sub_ms` of three STAT lines (`/tmp/logs/tc100_rtsp.log`, every 5 s) without privacy, then
     `touch /tmp/tc100_privacy` and note three more, on the old build and on this one (`v3/dev/try-rtsp.sh`).
  2. With privacy on: the picture is black on both streams, the snapshot too; masks and the clock look as before
     with privacy off.
- **Pass:** `pp_ms` with `/tmp/tc100_privacy` present is clearly lower than on the old build (estimate 10-40 ms per
  frame saved), the same without privacy, and 2 unchanged.

### W3-ZERO One zeroing of the encoder's pool block per open (`[video-fix]`, audit 2026-11-24 W3) — `to test`
- **What:** each free encoder open zeroed its pool block twice: `akuio_alloc_pmem` (unless `AKUIO_NOZERO`) and
  `fe_open_wh` (`freeenc.h`), 7.4 MB for the 1080p main encoder, at every viewer after an idle period. The free
  encoder now allocates through `akuio_alloc_pmem_nozero` (new in libakuio, the same allocator without the memset)
  and keeps its own `memset`, which it relies on (the 0x4040-byte tables block past its 20-byte head, the 0x400-byte
  "small" block, the reference's motion / co-located areas before the first P picture). The
  vendor libraries and the other pool users of `tc100_rtsp` still get zeroed memory from `akuio_alloc_pmem`. A
  `libakuio` without the new call (vendor library): `akuio_alloc_pmem` as before.
- **Revert:** the previous build (no switch: same memory contents for the encoder).
- **Test:**
  1. Main stream idle (no client) for a minute, then open it in VLC: time from PLAY to the first picture, five
     times, old and new build; the log shows `free encoder: H.265 1920x1080 ...` at each open, no
     `picture failed` line.
  2. One hour with a viewer that connects and leaves every minute (`ffprobe` loop): no encoder failure, no
     `ak_venc_open failed`, the picture is clean from the first frame (no green or stale blocks at the first IDR).
- **Pass:** 1 and 2 clean; the open is faster or the same.

### R2-BUTTON The reset button keeps its timing while night mode or MQTT work runs (`[r2-button]`, audit 2026-11-24 R2) — `to test`
- **What:** `tc100-supervisord` (`SUPERVISOR_IMPL=c`, the default) runs the button, day / night and sound jobs in one
  loop, and waited for `nightmode.sh` with no time limit (sound-event MQTT publishes: up to 30 s each). While it waited
  the button was not read: a hung `nightmode.sh` stopped the button for good (no reboot, no rescue access point), and a
  hold that overlapped a switch lost the blocked seconds (8 s could become the 3-7 s rescue access point, 20 s a plain
  reboot; a press that began during the wait could also gain seconds). Every wait for a child now polls every 50 ms and
  takes the button's one-second samples on time meanwhile (same thresholds: 3-7 s rescue access point, 8-19 s reboot,
  20 s and more back to the built-in code + reboot; acts on release). `nightmode.sh` is killed after 120 s, the script only
  (what it starts in the background, such as `tc100_rtsp` restarted with `NIGHT_720P=1`, lives on), and the console says `[auto-night] /mnt/scripts/nightmode.sh on did not end within 120 s: killed`.
  The shell fallback (`SUPERVISOR_IMPL=sh`) is unchanged: `button-watch.sh` was always a process of its own.
- **Revert:** `SUPERVISOR_IMPL=sh` in `/mnt/config/boot.conf` (shell loops), or the previous build.
- **Test (RAM only, undone by `umount` or a reboot):** make the switch slow so the hold surely overlaps it:
  ```
  cp /mnt/scripts/nightmode.sh /tmp/nm-real.sh
  printf '#!/bin/sh\nsleep 30\nexec /bin/sh /tmp/nm-real.sh "$@"\n' > /tmp/nm-slow.sh; chmod +x /tmp/nm-*.sh
  mount --bind /tmp/nm-slow.sh /mnt/scripts/nightmode.sh
  ```
  1. Cover the lens until the console shows `Switching to NIGHT mode` (the IR-cut clicks 30 s later). Within those
     30 s, hold the button 5 s: the rescue access point starts (`logread | grep 'button:'` says `held 5s: rescue access
     point`) before the IR-cut clicks. Stop it (`/mnt/scripts/wifi-rescue.sh stop-ap` or wait for its timeout).
  2. Uncover the lens, wait for `Switching to DAY mode`, and within the 30 s hold the button 8-10 s: the camera reboots
     (`held 8s: reboot` .. `held 10s`), not the rescue access point. (After the reboot the bind mount is gone.)
  3. Optional, hung switch: as above with `sleep 300`; after 120 s the console shows `did not end within 120 s:
     killed`, and a 5 s hold still starts the rescue access point during and after the hang.
- **Pass:** 1 and 2 (and 3 when run); `umount /mnt/scripts/nightmode.sh` if no reboot happened.

### R3-MQTT A retained MQTT command is not executed (`[r3-mqtt]`, audit 2026-11-24 R3) — `to test`
- **What:** a message published *retained* on the command topic is sent again by the broker at every subscription
  (with the RETAIN flag set, MQTT 3.1.1 3.3.1.3). `tc100-mqttd` executed it at every connection (a retained
  `{"cmd":"reboot"}` = a reboot loop: the repeat filter lives in `/tmp`). Command PUBLISH packets with RETAIN set are
  now dropped with one log line (`MQTT retained command ignored (N bytes): clear it with an empty retained message on
  <topic>`, no payload). A live message, also one published with retain, reaches an existing subscription with RETAIN
  clear and runs as before: Home Assistant buttons publish without retain. The shell bridge
  (`MQTT_BRIDGE_IMPL=sh`, persistent listener and windowed subscriber) does the same; its legacy curl stream mode
  (`MQTT_PERSISTENT_SUBSCRIBE=0` with curl) cannot see the flag.
  Behaviour change: a command published retained on purpose so that it runs when the camera reconnects no longer
  runs; publish it live instead.
- **Revert:** the previous build (no switch: a retained command is never wanted).
- **Test:** from a PC on the LAN (the owner types the credentials):
  1. `mosquitto_pub -h BROKER -u USER -P PASS -t <root>/command -r -m '{"cmd":"snapshot"}'` (a harmless command;
     `-r` = retained). Restart the bridge (`/mnt/controlscripts/mqtt-bridge restart`) or drop Wi-Fi a moment: the
     command does not run (no `<root>/command/result` message), and `/tmp/log/mqtt-bridge.log` has one
     `retained command ignored` line per connection.
  2. A Home Assistant button press (or the same `mosquitto_pub` without `-r`) still runs at once.
  3. Clear the retained message: `mosquitto_pub ... -t <root>/command -r -n`.
- **Pass:** 1 and 2.

### T1B5-PARITY httpfront `isp_tune` prints what `state.cgi` prints; `fullconfig` back to the CGI (`[parity]`, audit 2026-11-24 B5/T1) — `to test`
- **What:** the parity test of the native routes (`tests/test_httpfront_poll.py`) never ran: it skips without
  `arm-linux-gnueabi-gcc` and `qemu-arm`, the GitHub "Python regressions" step runs before qemu is installed and
  `local-ci.sh cross` did not list it. It now runs in `local-ci.sh cross` and in a GitHub step "httpfront under
  qemu-arm" (a skip fails both). Once it ran:
  1. **B5, native `isp_tune` (Settings -> Image, `state.cgi?cmd=isp_tune&format=json`):** it never answered on a
     camera with a privacy mask (a mask like `10,20,30,40` made it give up and the CGI answered), and when it did
     answer it normalized the values where `isp-tune.sh` `isp_tune_json` prints them as written: a missing key gave `0`
     (shell `null`), an out-of-range value `null` (shell prints it), `EXPOSURE_MAX_PCT=0` `null` (shell `0`), a
     `POWER_HZ` other than 50/60/auto `null` (shell prints it); a line `KEY` without `=` was taken for `KEY=`. It now
     copies `_isp_num`, `isp_tune_get` (first line starting with `KEY=`) and the mask check (`IFS=,`: a last comma
     makes no empty field) exactly; a mask with a leading zero (octal in the shell) goes to the CGI. The web UI shows
     the same sliders as before: `null` and a missing value both put a slider at 0.
  2. **Route 7, native `fullconfig`, removed:** the CGI answers again (it keeps its answer 5 s). It gave up on any value
     of 24 characters or more (a Frigate URL), took `perf_profile` from the last match in 11 files with any truthy
     value (the shell: first match in `boot.conf` / `service_trim.conf`, exactly `1`, 5 s cache), answered
     `application/json` without `format=json` (the CGI: `text/plain`), and the router took
     `cmd=daynight&format=json&cmd=fullconfig` too. One load per Settings open was not worth the ~270 lines.
  3. **Day/night (route 3):** a value of 24 characters or more in `daynight.conf` that is not a number (e.g. a long
     `DAYNIGHT_SOURCE`) made it give up since 2026-11-15; it reads it again as "not a known word" (as before).
  4. Route 5 (`health.cgi` from a fresh cache) and 4 (`hw_state`) unchanged; their tests now run.
- **Switch / revert:** `HTTPFRONT_NATIVE=0` in `/mnt/config/boot.conf` (every request to httpd and the CGIs), or the
  previous build.
- **Test (one camera, `U=root:PASSWORD`):**
  1. Settings -> Image: the sliders, the anti-flicker choice, the exposure cap and the privacy masks show the same values
     as with `HTTPFRONT_NATIVE=0`; move a slider, wait for "Applied on the camera: ...".
  2. Same JSON: `REQUEST_METHOD=GET QUERY_STRING='cmd=isp_tune&format=json' STATE_RESPONSE_CACHE_BYPASS=1 sh /mnt/www/cgi-bin/state.cgi | sed '1,/^$/d' > /tmp/it-cgi.json; curl -s -u $U "http://127.0.0.1/cgi-bin/state.cgi?cmd=isp_tune&format=json" > /tmp/it-native.json; diff /tmp/it-cgi.json /tmp/it-native.json`
     with `ISP_TUNE=1` and `0`, one mask set and none.
  3. Settings opens and fills every tab as before (`fullconfig` from the CGI: `curl -si -u $U "http://127.0.0.1/cgi-bin/state.cgi?cmd=fullconfig"` says `Content-type: text/plain`).
- **Pass:** 1 and 3 unchanged, `diff` empty in 2.

### W5-AUDIT Read-only queries no longer noted in the audit log (`[w5-audit]`, audit 2026-11-24 W5, owner's decision) — `to test`
- **What:** `action.cgi` noted every command in `/tmp/log/audit.log`, the read-only ones too (`ACTION_GET_READS`:
  `hw_state`, `showlog`, `wifi_scan`, ...); the Hardware page polls `hw_state` every 2 s, which filled the 64 KB log in
  about an hour and its 100-line rotation erased the real entries. Read-only queries are no longer noted, in the CGI
  and in httpfront's native `hw_state` (its audit-line code is gone). Every other command is noted as before.
- **Revert:** the previous build (no switch: the owner does not want these lines).
- **Test:** open the Hardware page 10 min, then reboot from the web UI: `/tmp/log/audit.log` (before the reboot, or
  the persisted copy) holds the reboot line and no `cmd=hw_state` line.
- **Pass:** as described.

### CLEANUP-1124 Dead or never-paid optimisations removed (`[cleanup]`, audit 2026-11-24 section 5) — `to test`
- **What:** code paths that were off by default (or impossible) are gone; the default path is unchanged, byte for byte
  on the host tests (RTP packets over UDP and TCP, the live view's fMP4). The `STAT` line is not touched.
  1. `tc100_rtsp`: `RTSP_UDPMMSG` (one `sendmmsg` per frame; P-09 artefacts), `RTSP_PACING_US` and `pace_udp` (a sleep
     after each UDP packet; at HZ=100 it slept 10 ms, with `cl_mu` held under the sender thread: risk R4),
     `RTSP_SNDBUF` (never measured), `RTSP_FRAMECOPY=0` (encoder output and JPEGs read in place; the in-place read stays
     only as the fallback when the copy finds no memory, as before), `RTSP_LIVE_DIRECT=0` in `livemp4.c` (a payload
     buffer per frame then a copy per viewer). `RTSP_UDPSG=1` sends each packet at once (it always did by default).
     The startup line `rtp scatter-gather N sendmmsg N; pacing N us sndbuf N KB; live direct` is now
     `rtp scatter-gather N`.
  2. `tc100_rtsp` capture: `RTSP_ZEROCOPY` (USERPTR capture into the encoder pool: impossible, the driver needs at
     least 3 slots and the code asked 2; kernel patch 0011 stays), `RTSP_POOLPAD` and the HW-01 guard at the start of
     the encoder pool (off with any pool under 12 MiB, the 9600K default included: the start line `encoder pool:
     9830400 bytes (ak39_venc.pool), no guard at its start` is gone), and the `/dev/mem` search of the capture buffers
     when the driver gives no physical address (every kernel of `patches/kernel-6.6/series` has `AK39_VI_G_PHYS`,
     patch 0006, since 2026-10-22; without it the server now uses the copy mode).
  3. Day / night, `luma` source (`DAYNIGHT_SOURCE=luma`, or the fallback when the AE / vendor inputs are missing):
     without `/tmp/cam_luma` both `tc100-supervisord` and `scripts/auto-night-daemon.sh` took the mean of the first 512
     bytes of `/tmp/currentpic.cache.jpg` (JPEG header bytes, not light); they now use 50, as for an unreadable file.
     `tc100_rtsp` writes both files, so while it runs nothing changes; the default `vendor` source falls back to
     `luma` only when its own inputs are missing.
- **Switch / revert:** none (removal of non-default paths); the previous build. A `/mnt/config/rtsp.env` that still
  sets one of these variables does no harm: they are ignored.
- **Test (one camera, then both; a normal run):** install the build, leave it 24 h with the usual viewers (VLC or
  Frigate over RTSP, the web live view), and the day / night switches of an evening and a morning.
  Start of `/tmp/logs/tc100_rtsp.log`: `direct capture: buffer N at 0x... (... bytes, from the driver)` for each
  buffer and `encoder pool: no picture copy (direct capture and the ISP sub channel)`, as before.
- **Pass:** the `STAT` lines of `/tmp/logs/tc100_rtsp.log` have the same fields and the same order of magnitude as on
  the previous build (`cap`, `enc`, `snd_ms`, `pp_ms`, `dropped`, `pic_fail` 0, `cap_stall` 0, `exit3` 0); no reboot,
  no oops; RTSP and the web live view play; the day / night switches happen as before.

### SMALL-B-1124 Small CPU savings of the audit (W2, W6, W7, W9) (`[small]`, audit 2026-11-24 section 4) — `to test`
- **What:** four small cuts in work that was paid for nothing; the default output is the same (host tests compare the
  old and new results byte for byte or sample for sample).
  1. W2, `tc100_rtsp` `post_awb_sample` (AWB, twice a second): the luma byte of each of the 16 200 samples was found
     with a signed library division (`i / W`); row and column are now stepped (`awb_grid_next`, `util.h`), same samples.
  2. W6, `tc100-mdnsd`: host name, address and netmask are kept 5 s (they were read with an open/read/close and two
     ioctls for every query); the TXT strings of `MDNS_INFO=1` (`/mnt/VERSION`, `/proc/loadavg`,
     `/tmp/wifi-signal.avg`) are read only when a DNS-SD answer is due, not for every query of the subnet. A new host
     name or address is answered within 5 s (at once before).
  3. W7, `tc100-onvifd`: `/tmp/rec_control` is read only while a PullPoint subscription exists (twice a second, as
     before) and once when one is created, so its first `Initialized` message has the current state.
  4. W9, `tc100_rtsp`: the copy of the encoder output and of the JPEG is a plain `memcpy` (the volatile word loop
     `nal_copy` is gone: the pool is write-combined, the libc copy reads it in words and bursts); one clock read for
     `lis_scan`, `live_scan` and `talk_tick`, and `live_scan` uses its argument instead of a second clock read.
- **Switch / revert:** none (no setting); the previous build.
- **Test (one camera, then both; a normal day):**
  - W2: colours and white balance as on the previous build, day and evening (`isp_tune.status`, the picture); the
    `pp_ms` field of the `STAT` lines of `/tmp/logs/tc100_rtsp.log` not higher, and `tc100_rtsp` in `top` not higher.
  - W6: mDNS / Bonjour still finds the camera: `ping <hostname>.local` from a PC, `avahi-browse -rt _rtsp._tcp` (or
    the Bonjour list of VLC / Home Assistant) shows it with `model`, `fw`, `load` and `rssi` in the TXT.
  - W7: ONVIF motion events still arrive in Home Assistant (ONVIF integration, motion binary sensor) or an NVR: walk
    in front of the camera, the event turns on, then off; after a restart of Home Assistant (new subscription) the
    sensor starts with the right state.
  - W9: video as before: RTSP main and sub stream in VLC or Frigate, the web live view, a recording and a snapshot.
- **Pass:** the four checks above; `STAT` lines with the same fields and order of magnitude as on the previous build
  (`cap`, `enc`, `snd_ms`, `pp_ms`, `dropped`, `pic_fail` 0, `cap_stall` 0, `exit3` 0); no reboot, no oops.

### SMALL-A-1124 Six small fixes of the audit (`[small]`, audit 2026-11-24 R5 R6 R7 R8 W4 W8) — `to test`
- **What:** no visible change with the default configuration.
  1. R5 `mqtt-bridge.sh`: each FIFO record for `tc100-mqttd` is built in `/tmp/.mqtt_rec.PID` and handed over by one
     `dd bs=4096 count=1` (one `write()`, under PIPE_BUF), as the fast path already did. The 3000-byte limit stays.
  2. R6 `supervisor.sh` / `tc100-supervisord`: the job flag now holds a nonce (pid + uptime); the daemon restarts the
     night job when it changes. An empty flag (older callers) still works.
  3. R7 `log-cap.sh` leaves `daynight.log` alone (the daemon rotates it at 400 lines).
  4. R8 `rwconf`: temp file `FILE.<pid>.tmp` (matches the `*.tmp` exclusions of `cfg-persist`).
  5. W4 `health-probe.sh`: a 0 exit of `onvif health` / `rtsp-h26x health` is "running" (no `status` run behind it);
     `ssh-server` is a pid-file probe (`/var/run/dropbear.pid`).
  6. W8 `health-snapshot.sh`: `memory.csv` is flushed by `memwatch.sh` itself (boot, hourly) and by the stop path, no
     longer a second time by the stability flush.
- **Switch / revert:** none; the previous build.
- **Test (one camera, a normal run):** (a) R5 with `MQTT_BRIDGE_IMPL=c`: trigger two MQTT events at once (motion and a
  sound event, or two `mqtt-bridge.sh publish` in parallel with 2-3 KB payloads): both arrive at the broker. (b) R6: with
  a DN-FLAP hold running (`daynight.log`), `controlscripts/auto-night-detection restart` ends it (log line
  `Daemon started`, no hold). (c) R7: `daynight.log` stays up to 400 lines (`wc -l`) after 10 minutes. (d) R8: Settings
  save works, no `*.tmp` stays next to the file. (e) W4: Services page health unchanged; `ps` shows no extra
  `controlscripts/onvif status` every 5 minutes. (f) W8: `memory.csv` gets its rows once an hour (`ls -l --time-style=full-iso`
  twice an hour apart), the stop of health-snapshot still flushes.
- **Pass:** (a) both events arrive; (b) the hold is gone; (c)-(f) as described, no error in the log.

### WIFIQ-FORKS `wifi-quality.sh` with 8 forks a minute instead of 13, no awk over the 24 h log (`[wifiq]`, audit 2026-11-24 section 7) — `to test`
- **What:** `scripts/wifi-quality.sh` gives the same files (`/tmp/wifi-quality.log`, `/tmp/wifi-quality`,
  `/tmp/wifi-signal.avg`, the previous-state file), byte for byte, with far less work. No `$(...)` subshell or pipe:
  `iw` and `ping` write to `/tmp/.wifi-quality.prev.iw` / `.ping` (under `timeout`, as before) and are read back with
  `read`; the gateway and the `iw` path are found in the shell; the awk over the 1440-line log is gone: the last hour
  is kept in `/tmp/.wifi-quality.prev.win` (a few dozen lines) and summed with `$(( ))` (the same integers as the awk,
  leading zeros handled). `wifi-quality.sh summary` still reads the whole log. Forks of a run: 13 -> 8 pids (busybox
  `timeout` costs 3 each: timeout + iw, timeout + ping, and the two `mv` of the avg and the summary file).
  Only difference: after a clock that goes back by more than an hour the old awk counted the "future" lines again.
- **Switch to turn it off:** `WIFI_QUALITY=0` in `boot.conf` (the whole job); otherwise the previous build.
- **Test (one camera, a day):** (1) the Wi-Fi page, `mqtt` diag values (`wifi_loss_pct`, `wifi_tx_retries`,
  `wifi_rssi_min`), the mDNS TXT signal and `wifi-roam.sh` behave as before; `cat /tmp/wifi-quality` has its seven keys
  and `samples_1h` is about 60. (2) `/proc/stat` `processes` twice 600 s apart, housekeeper running: fewer than
  before (about 50 less per 10 minutes from this script alone). (3) `top` CPU not higher.
- **Pass:** (1) values plausible and unchanged in format; (2) lower; (3) not higher; no error in `/tmp/logs`.
  Host test: `tests/test_wifiq_forks.py` (identical files over 132 simulated minutes against the old script, fork count).

### FAILCOUNT Failure totals of the video server over a day: STAT, /tmp file, memory-hourly.csv (`[failcount]`) â€” `to test` (both cameras, 24 h or more)

- **What:** measurement only, no behaviour change. `src/tc100rtsp/tc100_rtsp.c` counts since the process start
  `pic_fail` (every encoder call without a picture, main and sub), `enc_reopen` (core reset and encoder reopened after
  5 failures in a row), `cap_stall` (stall exit), `dq_err` (DQBUF errors), `sub_off`, `exit3` (every status-3 exit), and
  `starts`. The totals of the boot (earlier processes included) are appended to the end of the `STAT` line (old fields
  unchanged) and kept in `/tmp/tc100_rtsp.counters` (one line, temp + rename, written only when a STAT tick sees a
  change and at exit; no flash write). `scripts/memwatch.sh` adds the seven values at the end of `memory-hourly.csv`
  (columns `rtsp_starts,pic_fail,enc_reopen,cap_stall,dq_err,sub_off,exit3`); `stability.csv` is unchanged.
- **Switch to turn it off:** none needed (a few integer increments, one 100-byte write to RAM when a counter moves);
  `MEMWATCH=0` stops only the CSV copy.
- **Test:** (1) after the install, `cat /tmp/tc100_rtsp.counters` shows `starts=1 pic_fail=0 ...` and the last
  `STAT` line of `/tmp/logs/tc100_rtsp.log` ends with the same numbers. (2) `kill -TERM $(pidof tc100_rtsp)`: the
  watchdog starts it again; the file then shows `starts=2` and the other totals unchanged (`exit3` stays 0: a TERM is a
  clean stop, not a status-3 exit). (3) Run 24 h or more on both cameras (.11 and .24), then read the last row of
  `/mnt/sd/logs/memory-hourly.csv` (and `uptime`): that is the window. Use the numbers as the evidence for the
  AUDIT-1116-VENCIRQ, AWB-NIGHT and DN-FLAP verdicts over a day.
- **Pass:** the file and the STAT tail are present and agree; the TERM test gives `starts` +1 with the totals kept; the
  hourly rows carry the seven columns and grow without gaps over the run; `/tmp/tc100_rtsp.counters` is rewritten only
  when something changed (its mtime does not move every 5 s on a quiet camera); no change in frame rate, bit rate or CPU.
- **Results:** (testers write here)

### HARDEN Stack protector and full RELRO in the free programs (`[harden]`) — `to test` (one camera, 24 h, then both)

- **What:** build change only, no new setting on the camera. The musl programs (`tc100_rtsp`, `tc100-onvifd`,
  `tc100-mqttd`, `tc100-supervisord`, `tc100-logfwd`, `rwconf`, `libnetacl-musl.so`; `src/musl.mk`) are built with
  `-fstack-protector-strong` and `-Wl,-z,relro,-z,now`; the freestanding `httpfront`, `tc100-mdnsd` and `isp_flip`
  with `-fstack-protector-strong` and their own canary (`src/ssp-freestanding.h`, taken from `AT_RANDOM` in `_start`).
  A function with a local array now checks a random canary before it returns, and the GOT of the musl programs is
  read-only after loading. Cost: +3.7 KB in `stack.sqfs` (flash-budget.md "Hardening"); about 4 to 8 instructions per
  call of an instrumented function. In `tc100_rtsp` that includes per-packet and per-frame functions (`send_nal`,
  `send_pkt`, `rtp_out`, `sg_pkt`, `pace_udp` (removed 2026-11-24, audit), `now_us`, `q_push`, `live_frame`, `mdct`, `aec_process`, `md_frame`,
  `akuio_wait_irq`), so the CPU check below matters. `_FORTIFY_SOURCE` is not used (musl has no fortified headers).
- **Switch to turn it off:** a build switch, not a camera setting: the CI input `harden` = off (Actions, "Run
  workflow" of `build-kernel-linux66.yml`), or `HARDEN=0` for `make` / `sh tests/docker/local-ci.sh cross`. The
  build of `0f827ec` (the commit before) is the same firmware without it. Install either by web update.
- **How a hit shows:** a musl program prints nothing and dies of `SIGILL` (musl's `__stack_chk_fail`): "Illegal
  instruction" in the log of whoever started it (`/tmp/logs/tc100_rtsp.log`, the supervisor log, `logread`), then a
  restart by the watchdog or the supervisor (`starts` of `/tmp/tc100_rtsp.counters` goes up, FAILCOUNT). The
  freestanding programs print `*** stack smashing detected ***` to stderr and die of `SIGABRT`.
- **Test:**
  1. Before the update, on the camera that will run it: note `top -b -n 1 | head -20` three times one minute apart,
     the last `STAT` line of `/tmp/logs/tc100_rtsp.log` (frame rate, bit rate) and `/tmp/tc100_rtsp.counters`.
  2. Install the `[harden]` build by web update; after the reboot the web UI shows the new build.
  3. Boot: all services up (Services page), `dmesg` without errors.
  4. Stream 24 h: one RTSP client on the main stream (VLC or Frigate) and the sub stream, with audio (`-a 1`), and a
     recording on the SD card if one is fitted.
  5. Web UI: log in, Live (WebRTC and MP4), Settings (save one value), Day/night page, Records, update page (open only).
  6. ONVIF: discovery from a client (ONVIF Device Manager or Home Assistant), profile, snapshot and one settings
     read; one wrong password (the lockout path).
  7. MQTT: the broker sees the health and status messages; Home Assistant entities answer one command (e.g. the IR
     mode); `tc100-mqttd` keeps its connection over the 24 h.
  8. ssh from the LAN (dropbear, filtered by `libnetacl-musl.so`), and a refused connection from outside the allowed
     networks if one can be made; `telnet`/`ftp` if enabled.
  9. mDNS: `ping <name>.local` from the LAN.
  10. Picture orientation: Settings -> Picture -> flip on, then off (`isp_flip`).
  11. After 24 h: `top -b -n 1 | head -20` three times as in step 1, the last `STAT` line, `/tmp/tc100_rtsp.counters`,
      `grep -ri "stack smashing\|illegal instruction" /tmp/logs /mnt/sd/logs 2>/dev/null; logread | grep -i "smash\|illegal"`.
- **Pass:** no `stack smashing detected` and no `Illegal instruction` in any log; no crash or restart that was not
  asked for (`starts` of the counters file and the supervisor's restart counts unchanged over the 24 h, no reboot);
  every step 3-10 works as before; `top` shows the same CPU for `tc100_rtsp`, `tc100-onvifd`, `tc100-mqttd` and
  `httpfront` as before the update (within the usual spread of the three readings), same frame rate and bit rate.
- **If it fails:** a canary hit is a real memory bug that the old build hid: keep the log line and the program name,
  go back to the `0f827ec` build (or a `harden` = off build), and report the steps that led to it.
- **Results:** (testers write here)

### AWB-05-SAVED Instant manual white balance from saved gains (`[awb]`) — `to test`

- **What:** `src/tc100rtsp/tc100_rtsp.c` (`awb_state_save`, `awb_state_load`, `awb_hw_init`): `/mnt/config/awb.state` now stores `ex_r ex_b mwb_r mwb_g mwb_b bw_want timestamp` (backwards-compatible with 2-number files). When `awb_hw_init()` finds recent (`<= 6 h`, or pre-NTP boot with wall-clock `awb.state`) manual gains from the same day/night mode (`sbw == bw_want`), it enters ISP manual mode (`ISP_SET_WB_TYPE=0`, `ISP_SET_MWB`) immediately instead of running 10 s of ISP automatic mode (`AWB_MANUAL_AFTER`). Falls back to the 10 s auto warmup when missing, stale, or day/night differs.
- **Switch to turn it off:** `RTSP_AWB_STATE=0` (disables loading/saving `awb.state`) or `RTSP_AWB_MANUAL=0` (keeps ISP automatic mode).
- **Test:** On a camera with `awb.state` written after settling in day mode, run `controlscripts/rtsp-h26x restart` and check `/tmp/logs/tc100_rtsp.log` for `white balance: ISP in manual mode from saved gains` at startup, then check a snapshot within the first 5 s.
- **Pass criteria:** Immediate manual mode from saved gains on restart in the same day/night mode (no 10 s auto color shift); 10 s auto fallback when `awb.state` is removed or stale.

### AWB-NIGHT AWB-05 hands white balance back to the ISP at night (`[awb-night]`) — `to test` (both cameras)

- **What:** `src/tc100rtsp/tc100_rtsp.c` (`awb_night_pause`, `awb_day_resume`, `post_awb_sample`, `awb_state_load`,
  `awb_state_save`, `awb_hw_init`). Night = `/tmp/tc100_bw` (written by `night-mode` / `setconf -k v`, the signal the
  video server already reads for the night parameter set). At night the loop is paused and the ISP gets its automatic
  white balance back (`AK_ISP_SET_WB_TYPE` auto, neutral extra gains, as after a start at night); the day gains
  (`rex`, `bex`, MWB base) are kept in memory and applied again at dawn (manual mode at once; without a manual base
  the usual 10 s warm-up). `awb.state` is never saved at night. A state saved at night, or with `rex` / `bex` above
  900, is never loaded (3.0.1 / 3.0.2-rc1 left such a state on the .24: `bex` 1228). The bound 900 (x3.5): day
  gains of a steady scene sit near 256-600 (the .11: 141 by day, 941 at night), the .24 polluted value was 1228, so 900
  keeps real dusk lamp-light states and drops polluted ones.
- **Log lines (video log):** `AWB-05 paused (night), ISP auto (day gains kept: rex .. bex ..)`; at dawn
  `AWB-05 resumed from saved day gains r .. g .. b .. (rex .. bex ..)`; at start `white balance: saved state ignored
  (saved at night | implausible for day: ...)`.
- **Switch to turn it off:** `RTSP_AWB_NIGHT=0` in `/mnt/config/rtsp.env` (3.0.1 behaviour: the loop only stops
  measuring; the load / save rules are the 3.0.1 ones too). The only rule that stays with `=0` is the refusal of a
  saved state with `rex` or `bex` above 900, which only falls back to the ISP's automatic mode. `RTSP_AWB_STATE=0` /
  `RTSP_AWB_MANUAL=0` as before.
- **Default configuration (`RTSP_NIGHTSTYLE=1`):** the day / night switch re-runs `awb_hw_init` (`isp_bases_reset`); the
  paused state and the day gains survive it, nothing puts the ISP in manual mode at night, and the morning goes
  through `awb_day_resume`. The gains kept are clamped to 900. A refused automatic mode is logged.
- **Test (each camera):** (1) with the video server running since the day (no restart), note bit rate and the MWB gains
  (`/tmp/cam_awb`, `rex= bex=`) in the video log shortly before the evening switch to night; after the switch note
  the two log lines, the bit rate over 30 min and `bex`; (2) next morning `cat /mnt/config/awb.state` (last field is
  a day timestamp, mode field 0, `bex` below 900) and check the `resumed` line at the switch to day and the colours
  of a snapshot; (3) a video restart at night (`AWB-05 paused` at start, 650-ish kbit/s), then a day start after
  a night (manual mode from the saved day gains or the 10 s warm-up, correct colours); (4) with a polluted state
  left from 3.0.1 (`rex 375 bex 1228`), restart: the `saved state ignored` line.
- **Pass:** night bit rate about 650-950 kbit/s instead of about 1600 on the .24 after an evening switch without a
  restart; no blue gain near the cap (1536) at night; correct day colours next morning; `awb.state` has no night
  content.
 to tell a kernel leak from benign growth (`[memwatch]`) — `to test`

- **What:** `scripts/memwatch.sh`, called by `health-snapshot.sh` every 5 minutes, writes `memory.csv` (26 columns from
  `/proc/meminfo` and `/proc/vmstat`; kinds `boot` = baseline at 10 min of uptime, `sample`, `hourly`, `drop`) and, once
  an hour, `memory-hourly.csv` (sockets, `df` of /tmp /mnt /var, open deleted files, threads, rtl8xxxu URBs, buddyinfo,
  rtsp-h26x restarts). Next to `stability.csv`: `/mnt/sd/logs/` with a card (caps 2016 and 720 rows), else `/mnt/log/` in RAM
  (caps 1008 rows, about 140 KB, and 168 rows, about 42 KB; lost at reboot). Reading guide and decision table:
  `internals.md` "Memory watch". Measurement only, no kernel change.
- **Switches:** `MEMWATCH=0` in `/mnt/config/boot.conf` = nothing new is read or written (default 1, read at every sample).
  `MEMWATCH_DROP_HOUR=4` = a `drop` row, `sync; echo 3 > /proc/sys/vm/drop_caches; sleep 5`, a second `drop` row, once a day
  at the first sample of 04:xx (default empty = off; re-reads files through the polled SPI driver, measurement runs only).
- **Test:** 3 days or more on both cameras (one with a card, one without is the best mix; set `MEMWATCH_DROP_HOUR=4` on one
  of them from day 2), then read `memory.csv` and apply the table. `top` (or `scripts/cpu-profile.sh 60`) before and after.
- **Pass criteria:** both files exist, are written hourly and stay under their caps (`wc -l`, `ls -l`); no visible CPU cost
  (`top` the same within noise, the script is a short burst every 5 min); the data is enough to apply the table
  (`unaccounted` computable, `SUnreclaim`, `SReclaimable`, `Shmem`, `CmaFree` series without gaps). Verdict per camera:
  slab leak, page leak, CMA leak, process leak or benign growth.
- **Next step:** only if `SUnreclaim` grows linearly, an SD test kernel with `CONFIG_SLUB_DEBUG` (`/proc/slabinfo`,
  `slabtop`) to name the cache. Otherwise close the item in a-faire B2.

### DN-FLAP Day held back after a quick day -> night round trip, vendor source (`[dn-flap]`) — `to test` (the .11 over 2+ evenings, the .24 at dawn and dusk)

- **What:** `src/supervisord/supervisord.c` (`dn_flap_*`, `dn_switch`, `dn_step_vendor`) and, as the shell fallback,
  `scripts/auto-night-daemon.sh` (same names; the C daemon is the live path of 3.0, the shell loop runs when
  `tc100-supervisord` is missing or died; both are kept identical by `tests/test_supervisord.py`). Source `vendor` only.
  A return to night less than 15 min (`DN_FLAP_WINDOW_MIN`) after a switch to day is a round trip: the day switch is then
  held until 15 min after the night switch, and each further round trip doubles it (15, 30, 60, 120 min, capped by
  `DN_FLAP_MAX_MIN`). It builds on `MIN_SWITCH` (the day switch waits for the larger of the two). The switch to night is
  never held back. The hold is cleared by a real day: `lum` below `DN_DAY_RESET_LUM` (600) for `DN_DAY_RESET_MIN` (5)
  minutes in a row. State in memory only; a reboot or a daemon restart starts again without hold.
- **Why these values (field data of 2026-11-16 / 18, the .11):** the night readings sat at `lum` 1670-1880 (IR) against
  `VENDOR_DAY_LUM` 1536, the day readings at 3000-6800 at maximum gain, each phase 3-9 min. 15 min is longer than every
  observed day phase, so each flap is seen as a round trip, and the 120 min cap lets a lamp-lit evening settle in one
  or two switches. 600 is under a third of the 1536 threshold and far from the 1670+ the IR lifts the night picture
  to; the day phases never went under 3000, so 5 min under 600 cannot be a flap, it is daylight.
- **Switch to turn it off:** `DN_FLAP_BACKOFF=0` in `/mnt/config/daynight.conf` (same file as the other day/night keys;
  read again on the next write of the file, no restart). Other keys, defaults in brackets: `DN_FLAP_WINDOW_MIN` (15),
  `DN_FLAP_MAX_MIN` (120), `DN_DAY_RESET_LUM` (600), `DN_DAY_RESET_MIN` (5). Not on the settings page: a save of the
  page keeps them. They are in the parameter catalog and in the configuration export / import.
- **Log lines:** in `/tmp/logs/daynight.log` (copied to the card by `log-persist.sh`) and on the console:
  `HH:MM [auto-night] day held back N min after a round trip (night again S s after day)` when it engages or grows,
  `... day hold reset: lum below 600 for 5 min (real day)` when a real day clears it. While it holds, the console shows
  `day wanted (...) S s after the last switch: waiting N s`. Also changed on the way: the 15 s "switching back" lock of
  the vendor source starts only after a real switch (a switch that was only made to wait no longer starts it).
- **Test:** the .11 in its dim room, 2+ evenings, 3.0.x with this build and `DAYNIGHT_SOURCE=vendor`. In the morning:
  `grep -c 'Switching to DAY' ` and the `nightmode.log` (`/tmp/log/nightmode.log`) lines between 22:00 and 02:00 give the
  number of IR-cut switches (2 per round trip); read the `held back` lines in `daynight.log`. Then the same with
  `DN_FLAP_BACKOFF=0` for one evening if the room allows, to compare. On the .24: one normal sunrise and one sunset,
  times of the two switches against the days before.
- **Pass criteria:** the .11: at most 2-3 switches to day per evening between 22 h and 2 h (was 9 and 4 on the two
  evenings of 16 and 18/11), the `held back` lines show 15, 30, 60 ... min. The .24: sunrise and sunset switch at the
  same time as before, within a few minutes (a normal sunrise: `lum` falls under 600 and the day switch follows
  5 min later at the latest). No missed switch to night: the switch to night comes within about a minute of the
  picture getting dark (`MIN_SWITCH` aside), also while a hold is running.
- **The 15 s lock of the vendor source (changed, read this):** in 3.0.1 a want of the other mode that arrived inside
  `MIN_SWITCH` (180 s) and had to wait started the `VENDOR_LOCK` lock (900 s) by accident, in both directions: that was
  the only thing that held back the flapping (and it also delayed a night switch by up to ~15 min). With the backoff on,
  the lock now starts only from a real switch, so a wait no longer locks. `DN_FLAP_BACKOFF=0` restores the 3.0.1 start
  of the lock exactly. Consequence: with the backoff on and the default thresholds the lock is practically inert (it is
  set only within 15 s of a real switch with the lum of that switch, and the other mode's lum is always more than 30 %
  away, 3584 / 1536 = 2.33, so it opens at the next decision, about 18 s after the switch); the backoff is the
  anti-flap. Reviewer's simulation, 1 h, a scene that wants the other mode at once, `MIN_SWITCH=180`: 3.0.1 and
  `DN_FLAP_BACKOFF=0` 4 switches; backoff on 7 (15, 30, 60 min holds). The 2 h field pattern: 6 switches to day with
  3.0.1 behaviour, 3 with the backoff. If a night is worse than before, set `DN_FLAP_BACKOFF=0` and report.
- **Config values:** leading zeros (`08`, `010`) are read as decimal by the shell daemon too (before, 08 was a syntax
  error that would have stopped the fallback daemon, 010 octal); `DN_FLAP_MAX_MIN` is at most 1440 and a lowered value
  also limits a hold already running.
- **Host tests:** `tests/test_supervisord.py` `test_flap_*` (closed loop on the field pattern: 6 day switches in 2 h
  with the backoff off, 3 with it; holds 15 / 30 / 60 / 120 / 120; sunrise; sunset; switch off equals 3.0.1 on a scene
  that bounces inside `MIN_SWITCH`; leading zeros; cap; shell and C compared step by step),
  `tests/test_daynight_catalog.py` (the five keys everywhere).

### POLISH-01 Post-3.0.1 safe polish: cfg-persist single md5sum, AWB restart ignore, fe_hw_init guard, native fullconfig/isp_tune (`[polish]`) — `to test`

- **What:**
  1. `v3/linux66-sd/cfg-persist`: `signature()` computes a single `xargs md5sum | md5sum` over tracked files instead of ~180 per-file `cmp`/`md5sum` forks.
  2. `src/supervisord/supervisord.c` + `scripts/auto-night-daemon.sh`: ignore `/tmp/cam_awb` counts for `AWB_RESTART_IGNORE` s (default 30) after `tc100_rtsp` starts/restarts (PID change or `/tmp/cam_ae` recovery), preventing false day switches from ISP startup AWB spikes.
  3. `src/tc100rtsp/tc100_rtsp.c`: move `fe_hw_init(&fe_env)` from `fe_setup()` to right after `VIDIOC_REQBUFS` succeeds so a second instance failing `REQBUFS` never resets the running encoder core.
  4. `src/httpfront/poll.h`: native C handlers for `state.cgi?cmd=isp_tune&format=json` and `state.cgi?cmd=fullconfig` (byte-for-byte parity with `state.cgi`, fallback to `httpd` on edge cases).
     (2026-11-24, `T1B5-PARITY`: the `fullconfig` route is removed and `isp_tune` rewritten; test item 4 with that entry.)
- **Switches / revert:**
  - `AWB_RESTART_IGNORE=0` in `/mnt/config/daynight.conf` disables the 30 s AWB ignore window.
  - `TC100_NATIVE_STATUS=0` disables all native `httpfront` handlers (falls back to `httpd`).
- **Test & pass criteria:**
  1. `time sh /mnt/v3/linux66-sd/cfg-persist flush` (or `save` after a config change): completes in ~1-2 s instead of ~5.4 s; `cfg-persist status` shows `state=ok`.
  2. At night (`ircut=0`), run `controlscripts/rtsp-h26x restart`: `/tmp/logs/daynight.log` stays `mode=night` over the next 60 s (no false switch to day 20 s after restart).
  3. While `tc100_rtsp` is streaming, launch a second `/tmp/tc100_rtsp` (expected to fail `REQBUFS: Device or resource busy`): running `tc100_rtsp` logs 0 `picture failed` / `AKUIO_WAIT_IRQ` errors.
  4. Open Settings and Image tuning tabs in the web UI: loads cleanly in < 50 ms for `fullconfig` and `isp_tune`, values match `state.cgi`.

### ENC-02 Free encoder: budget at the real frame rate, oversize path, IDR size limit, still-scene keyframe, failure escalation (`[enc-fixes]`) — `to test`

- **Why:** the read-only review of 2026-11-15 (`frontier/encoder-2026-11-15-reponse.md`, items R1, R2, R3, L1 + L2;
  approved by the owner). Host tests only so far: nothing of this has run on a camera.
- **What (`src/h265enc/rc.h`, `freeenc.h`, `src/tc100rtsp/tc100_rtsp.c`):**
  1. **R1, budget and GOP at the real capture rate.** The rate control computed the bytes per picture from the
     configured 25 fps even at the 10 fps of the night parameter set (the measured 64 kbit per picture = 647 kbit/s
     for a 1600 kbit/s setting). `fe_set_fps()` now gets the rate in use before every picture: the lower of the idle /
     configured rate and `cap_fps_now()` (night set, low-light rate). The pay-back time and the VBR credit keep their
     length in time. With the clock (`fe_set_time`, now given in every mode) the base GOP also ends after 5/4 of its
     time at the configured rate (50 frames at 25 fps: 2.5 s; at 10 fps a keyframe every 25 pictures instead of every
     50 = 5 s). Smart mode's still state is unchanged (long GOP, `RTSP_FE_SMART_MAXS`). At the configured rate nothing
     changes (the frame count decides down to 20 fps for 25).
  2. **R2, a picture larger than the stream buffer.** Before: lost, and the same IDR tried again at the same QP, for
     ever. Now the next IDR is coded 6 QP higher (`rc_over`, again 6 if it still does not fit) and the buffer's size is
     counted as sent. **IDR size limit:** an IDR is coded at the QP at which the last IDR would have stayed under
     0.4 s of the bit rate (80 KB at 1600 kbit/s; never asked below 32 KB, never above 3/4 of the stream buffer), CBR
     and VBR. **Sub-stream buffer 57 KB -> 128 KB** (`fe_sub_stream`): the 9600 KiB pool holds the JPEG buffer
     (0.54 MB), the 1920x1080 encoder (7.39 MB) and the 640x360 one (0.92 -> 0.99 MB), about 0.9 MB stay free. The
     list word 0x3d of the H.264 640x360 pictures is then 0x20000 instead of the vendor's 0xdf80: **the one thing here
     the core has never seen** (the 720p / 1080p encoders already use other sizes).
  3. **R3, smart mode on a still scene.** The QP floor (`minqp` + `RTSP_FE_SMART_QP` = 29) did nothing since the VBR
     quality QP is 33 (VBR-QP-01). It is gone; instead the keyframes of the still state are coded
     `RTSP_FE_SMART_QP` (default 4, 2 to 5) below the P pictures instead of 2, within the IDR size limit: with the long
     GOP nearly every P block is a skip, the keyframe is the picture. Normal mode keeps 2.
  4. **L1 + L2, failures.** After any lost picture the next IDR goes to the other frame buffer (as after a good
     picture). Failed pictures in a row are counted per stream: every 5 the core is reset and the encoder closed and
     opened again (log `pictures failed in a row: core reset, encoder closed and opened again`); after 30 on the main
     stream `tc100_rtsp` leaves with status 3 (log `the video server stops (status 3)`) and the service watchdog
     (`scripts/service-watchdog.sh`, one check a minute, its usual error count before a reboot) starts it again: no
     restart storm. A picture without interrupt takes 2 s: reopen after 10 s, exit after 60 s. The sub-stream still
     goes off after 50.
- **Switches / revert (`/mnt/config/rtsp.env`, then `controlscripts/rtsp-h26x restart`):** `RTSP_FE_FPS=0`: the
  capture rate is not given to the encoders (budget and GOP as before; the clock alone changes nothing at the
  configured rate). `RTSP_FE_SUBBUF=1`: the 128 KB sub-stream buffer (opt-in; the default stays the vendor's 57 KB until a bench test, the core has never been given that list value). `RTSP_FE_SMART_QP=2`: the still state's
  keyframes as the others. The QP +6 on an oversized picture, the IDR size limit, the frame buffer toggle and the
  escalation have no switch (they only act where the encoder failed or burst before).
- **Test (one camera first, `RTSP_DEBUG=1` for the `FRAME main IDR|P len` lines; log `/tmp/logs/tc100_rtsp.log`):**
  1. **Start and sub-stream (the first thing to check, with `RTSP_FE_SUBBUF=1`):** open the sub-stream (VLC on the sub path) for 10 min, by day.
     Log: `encoder sub 640x360 ... open; pool used U, free F` (F about 0.9 MB, not less than 0.5 MB), no
     `picture failed` line, the picture decodes without errors. If the sub-stream gives `picture failed` at once:
     remove `RTSP_FE_SUBBUF=1`, restart, note it here. Passed: make 128 KB the default.
  2. **Night budget (R1):** at night with the 10 fps set: the log shows `free encoder main: capture rate 10 fps
     (configured 25): 20000 bytes per picture` (1600 kbit/s). Compare `STAT ... bytes` per 5 s with the night before
     (about 400 KB = 647 kbit/s when the ceiling was binding): on a noisy / busy night scene it may now rise up to
     about 1 MB (1600 kbit/s), never above; on a calm scene with `RTSP_VBR_QP=33` it stays where the quality QP puts
     it. `FRAME main IDR` every 25 pictures (2.5 s) at 10 fps, every 50 by day. Back to day: `capture rate 25 fps`.
     The same with `IDLE_FPS` if it is used.
  3. **IDR sizes (R2, R3):** `grep 'FRAME main IDR'`: by day no IDR above about 85 KB after the first one (1600
     kbit/s); with `smart=1` on a still scene the IDRs are larger than with `smart=0` (QP 29 instead of 31 at
     `RTSP_VBR_QP=33`) and the still picture is cleaner (snapshot of a detailed area, both ways), the still-scene bit
     rate (`STAT bytes`) not more than about 10 % above the smart=0 one thanks to the long GOP.
  4. **Failures:** `grep -c 'picture failed'` stays 0 over a night and a day; the `closed after N pictures (... F
     failed, O of them too large)` lines show F = 0. If a failure ever shows: the next lines must be an IDR and, from 5
     in a row, the reopen line. The exit path cannot be provoked without hanging the core: checked on the host only.
  5. Recording and the browser live view over one day / night switch: files play, thumbnails present, no gap at the
     switch (the GOP in time moves the keyframes at 10 fps).
- **Pass criteria:** 1: sub-stream clean with the 128 KB buffer, pool free >= 0.5 MB. 2: the night log line, night
  `STAT bytes` <= the ceiling and >= the night before on the same scene, keyframe every 2.5 s at 10 fps. 3: IDR <= 85 KB
  at 1600 kbit/s after the first, smart still picture not worse. 4: 0 failed pictures in 24 h on both cameras, no
  `status 3` exit. 5: recordings and live view as before. Host tests: `tests/test_h265cmdlist.py` (RateControl
  `test_enc02_*`, FreeEnc `test_enc02_*`, FreeEncEnc02Wiring).
- **2026-11-15, .24 (main b2f734a, RAM binary with the stock environment, night set 10 fps, still indoor scene, 2
  clients):** start OK, `free encoder main: capture rate 10 fps (configured 25): 20000 bytes per picture` and
  `sub: ... 3125` (R1 line as planned); sub-stream opened at the vendor's 57 KB (default since b2f734a), pool free
  975616 bytes; IDR every 25 pictures (2.5 s) at 10 fps; IDR 71-74 KB (<= 85 KB); 0 failed pictures. Bit rate, same
  scene, back to back: `RTSP_FE_FPS=0` 280 KB / 5 s (P 2.47 KB, IDR 81 KB), R1 on 280 KB / 5 s (P 2.75 KB, IDR 73 KB):
  on a still scene in VBR the QP sits on `RTSP_VBR_QP` 33 and R1 changes nothing, as expected (an earlier run at 165
  KB / 5 s was the dawn light, not the code). rc44 stock on the same scene before: about 400 KB / 5 s (its quality
  QP was 27, no `RTSP_VBR_QP`). Still to see: 2 (a busy / noisy night scene rising above 650 kbit/s), 1 with
  `RTSP_FE_SUBBUF=1`, 3 smart=1, 4 over 24 h, 5. Left running on the .24 from 08:17 UTC.
- **2026-11-24 08:10, .24 updated to 3.0.2-rc2 too (web update by the owner, same build; no 3.0.1 reference left):**
  first boot clean this time (no `Failed power on`, `autorun_start` 13.8 s, `rtsp_launched` 26.6 s, `boot_complete`
  71.8 s), counters at 0, A-MPDU TX off, -56 dBm, ping 4.7 ms. Night set at start (dark room at dawn):
  `AWB-05 paused (night), ISP auto (day gains kept: rex 288 bex 154)` = the AWB-NIGHT fix as designed. **But the bit
  rate is at the ceiling anyway:** 5-s samples 157-1967 kbit/s, mostly 1500-1870 over the first 3 min, total gain 26x,
  exposure 2812 lines (10 fps). So the ceiling is not (only) AWB-05 steering under IR: dawn light rising under the
  IR and the auto-exposure moving all the time may be enough. To settle: a steady deep night (22 h - 5 h) on both
  cameras with the server running across the evening switch; if the ceiling remains with AWB-05 paused, look at the
  night noise reduction (NR levels 64-512 / 512-1024 at 26x), the 3D NR (`NR3D=1`) and R1 (the budget at 10 fps
  lets a noisy picture use the whole ceiling; `RTSP_FE_FPS=0` caps it at 640 kbit/s as before).
- **2026-11-24 18:20, day watch of both cameras on 3.0.2-rc2 (tester; one line every 5 min from 08:07 in
  `/tmp/watch.log`: bit rate, fps, mode, AWB gains, pid, `MemAvailable`, signal, counters):**
  - **Stable all day:** `tc100_rtsp` never restarted (.11 19.5 h, .24 10.2 h since boot), every counter at 0
    (`pic_fail enc_reopen cap_stall dq_err sub_off exit3`), no `Failed power on` since the .11 reboot of 23/11.
  - **Memory flat:** .11 `MemAvailable` 17.5-18.0 MB over 19 h, `SUnreclaim` 3.44-3.56 MB; .24 17.3-18.2 MB,
    `SUnreclaim` 3.62-3.73 MB. No trend: the slow drop seen on 3.0.1 is not there on rc2 so far (to confirm over 3 days).
  - **Wi-Fi:** 0 TX URB error, 0 RX URB lost, TCP retransmits 0.07 % (.11) / 0.17 % (.24), `txq_stops` 122 / 137.
  - **Bit rate by day:** .11 220-380 kbit/s at 24 fps, 108-156 kbit/s at 10 fps in the dim late afternoon (15:50-17:10),
    450-750 kbit/s when the room lights came on (18:13); .24 88-340 kbit/s, one 714 kbit/s sample (15:12, motion).
    The 10-fps low-light step goes both ways without a night switch (luma 83-118): correct.
  - **NIGHT-CEIL, the dawn case of this morning explained:** the .24's `nightmode.log` shows night 08:08 -> **08:11**
    (local): the ceiling samples were a 3-min night spell right after the start at dawn, then day. Not the steady
    night case: lower priority; the night of 24-25/11 decides.
  - **No evening switch yet at 18:20** (both still in day, rooms lit): AWB-NIGHT hand-over and DN-FLAP still to read.
  - **Plan of the main session applied (18:22):** `RTSP_LOGMAX=1048576` added to `/mnt/config/rtsp.env` on both
    (backup `/tmp/rtsp.env.before-logmax`, md5 before: .11 `bf72029f2d2f`, .24 `94fb3ad3be4c`), video restarted with
    `controlscripts/rtsp-h26x restart` (new pids, `RTSP_LOGMAX` seen in the process environment). No restart until
    the morning; `watch.sh` keeps running. In the morning: copy the logs before any reboot, then remove the line
    (check the md5 is back to the one above).
- **2026-11-24, reading of the first rc2 night and plan for the night of 24-25/11 (main session):**
  - **Passed so far, nothing to fix:** FAILCOUNT (all 0, hourly copy works), AWB-NIGHT on the .11 (650-890 kbit/s,
    day gains resumed and saved, no night state saved), MEMWATCH (flat over 9 h). DN-FLAP: no round trip, but the
    room may not have reproduced the fault: two more evenings before a conclusion.
  - **No fix yet for the two anomalies, on purpose:**
    1. `rtl8xxxu: Failed power on` x2 on the first boot after the web update of the .11 only (healed by the driver's
       retries, +7 s; not on the .24 with the same update). A fix would touch the update chain (power the chip down
       before the update's reboot) for one self-healed case: more risk than the fault. Watch item WIFI-POWERON in
       `a-faire-implementeur.md`; act only if it repeats.
    2. Night bit rate at the ceiling on the .24: 3 min of samples right after a start at dawn, light rising under the
       IR. AWB-05 was paused as designed, so it is not the cause there, but the data cannot yet tell between dawn
       light, night noise at 26x gain, the 3D NR and the R1 budget (by design R1 lets a noisy picture use the whole
       ceiling at 10 fps). Item NIGHT-CEIL in `a-faire-implementeur.md`.
  - **The real gap was the measurement:** the capped video log (128 KB + `.1`, 2-4 h) lost the evening AWB hand-over
    line and the bit rate from 00:11 to 05:00. Test of the night of 24-25/11, no new build:
    1. On both cameras, `RTSP_LOGMAX=1048576` in `/mnt/config/rtsp.env`, then `controlscripts/rtsp-h26x restart`
       before the evening: 1 MB + `.1` keeps about 9 h of `STAT` lines (up to 2 MB of RAM; `Shmem` in `memory.csv`
       rises by that much that night: expected). Remove the line after the test.
    2. No video restart until the morning, so that the evening switch happens with the server running.
    3. In the morning, before any reboot (the logs are in RAM): copy `/tmp/logs/tc100_rtsp.log*` and
       `/tmp/logs/daynight.log` of both cameras.
  - **Reading (the .24):** ceiling through the whole deep night on a steady scene -> night noise at high gain (next:
    night NR levels, 3D NR, or a night budget cap); ceiling only at dusk / dawn -> changing light under the IR, likely
    acceptable as is; normal night bit rate as on the .11 -> this morning was a start-at-dawn case. Then one targeted
    fix with its off switch.
- **2026-11-24 08:05, first night of 3.0.2-rc2 on the .11 (up 9.2 h since the 22:51 reboot; the .24 on 3.0.1 as the
  reference):**
  - **FAILCOUNT:** `starts=1 pic_fail=0 enc_reopen=0 cap_stall=0 dq_err=0 sub_off=0 exit3=0`, the same in every
    `memory-hourly.csv` row (9 rows), no `picture failed` / AKUIO_WAIT_IRQ, `tc100_rtsp` up since boot.
  - **AWB-NIGHT:** night 00:11 -> 07:51 (local); night bit rate 650-890 kbit/s at 10 fps over the hours the log
    still holds (05:00-07:00), never the ceiling (the .24 on 3.0.1 reached 1618 kbit/s on 17-18/11); at the morning
    switch `AWB-05 resumed from saved day gains r 426 g 256 b 376 (rex 173 bex 326)`; `awb.state` written at 08:03
    with day gains (193 318 ... day flag 0): no night state saved. The evening hand-over line itself had rotated
    out of the log (log cap): to read at the next evening switch. Passed so far; one more night with the server
    running across the evening switch to close it.
  - **DN-FLAP:** one night entry (00:11) and one exit (07:51), no round trip (the .11 had 4-9 a night on 3.0.1); the
    room was not necessarily dim-lit long enough to trigger the old fault: two more evenings. The .24 (3.0.1, no
    fix) kept single round trips (22/11 23:45 -> 23:57, 23/11 23:03 -> 23:11).
  - **MEMWATCH:** `/mnt/log/memory.csv` (no card: RAM) and `memory-hourly.csv` written every hour. 9 h:
    `MemAvailable` 17.5-18.2 MB with no trend, `SUnreclaim` 3.45-3.64 MB flat, `Shmem` 1.28-1.46 MB, `CmaFree` 2.3 MB,
    46 threads, 7 TCP sockets, no open deleted file, buddyinfo steady. The .24 (3.0.1): 17.1 MB after 4 d 15 h.
  - **Wi-Fi:** .11 -36 dBm, 0 TX URB error, 0 RX URB lost, `txq_stops` 122, TCP retransmits 0.08 %, no
    `Failed power on` since the reboot. The .24: SSH timed out once at 08:04 (ping 75 % lost for a few seconds, then
    fine; -52 dBm instead of -43 on 18/11), 0 URB error, video up 111 h: a radio dip, not the firmware.
- **2026-11-23 22:48, .11 updated to 3.0.2-rc2 (web update by the owner, build 1ede3c4; the .24 stays on 3.0.1 as
  the reference):** version 3.0.2-rc2, video up, new `STAT` tail and `/tmp/tc100_rtsp.counters` present
  (`starts=1 pic_fail=0 enc_reopen=0 cap_stall=0 dq_err=0 sub_off=0 exit3=0`), `memwatch.pending` written, A-MPDU TX
  off, AWB-05 in manual mode in day (room lit at 22:49, day correct). **First boot after the update:** two
  `rtl8xxxu_init_device: Failed power on` (probe -16) before the RTL8188FU came up, and `autorun` at 19.8 s
  (`rtsp_launched` 31.2 s) instead of 12-13 s (25 s). **Reboot at 22:51:** no Wi-Fi failure, `autorun` 12.8 s,
  `rtsp_launched` 25.6 s: the first boot after the web update only (the Wi-Fi chip probably left powered by the old
  firmware across the update's reboot; the .24 on 3.0.1 has no such line). Watch at the next update: if it repeats,
  reset the USB device (or the chip's power) before the update's reboot. `awb.state` carried over from 3.0.1 in the
  old 2-number form (`260 744`, extra gains only): accepted. Still to see: AWB-NIGHT at the evening switch, DN-FLAP
  over two evenings, FAILCOUNT after 24 h, MEMWATCH after 3 days.
- **2026-11-18 03:00, both cameras on 3.0.1 for 2 days (readings for the project):**
  - **Stable:** no reboot, `tc100_rtsp` up 58.5 h on both, 0 `picture failed` in the logs kept, CPU 23 % busy on
    average since boot (user 6.5 %, system 13 %, softirq 3.6 %), load 1.1-1.6.
  - **Memory:** `MemAvailable` 17.9 MB at boot -> 17.0 (.11) / 16.8 MB (.24) after 2 days. Not the user space
    (AnonPages 1.9-2.0 MB, largest process 1.6 MB `sh`, `tc100_rtsp` 1.2-1.5 MB): Cached 11.4 MB, Slab 4.5 MB
    (SUnreclaim 3.7 MB), Shmem 1.5 MB (/tmp 0.8-0.9 MB + /mnt 0.4-0.5 MB, logs capped), CMA 30 MB with 2.2-2.3 MB free.
    No `/proc/slabinfo` on 6.6: to tell slab growth from cache, log `SUnreclaim` and `Shmem` in the stability file.
  - **Wi-Fi:** signal -31 dBm (.11) / -43 dBm (.24), 0 TX URB error, 0 RX URB lost, TCP retransmits 0.12 % / 0.09 %
    of segments, `txq_stops` 680 (.11) / 5242 (.24) (always matched by wakes), RX dropped 1.6 % of packets on both
    (`/proc/net/dev`, errors 0: frames for protocols the camera does not run, e.g. IPv6 / LLDP; harmless, about 180
    received packets / s).
  - **Day / night flip-flop on the .11 (new, the main finding):** 9 night -> day -> night cycles on 16/11 22:13-23:51
    and 4 on 18/11 00:52-01:57 (3-9 min each, IR-cut clack every time). Source `vendor` (luma + AWB counts), room
    dimly lit by a lamp or a screen. In night (IR on) the IR raises the picture: `lum` 1670-1880 near
    `VENDOR_DAY_LUM` 1536 and the AWB counts show visible light (`DN_AWB_VIS`=1) -> day; in day (IR off) the sensor
    is at its maximum gain (`idx` 33000-75000, `lum` 3000-6800 > `VENDOR_NIGHT_LUM` 3584) but the AWB counts stay
    around `AWB_DAY_CNT` 200000 (177000-650000) and hold day until they dip below -> night again. See the
    implementer list (DN-FLAP).
  - **Night bit rate at the ceiling on the .24 (new):** 1618 kbit/s for hours (night since 21:37, the video server
    running since 15/11). Video restart at 02:10 (same scene, same saved gains `rex 375 bex 1228`):
    `RTSP_AWB_MANUAL=0` 680 kbit/s, then the normal settings again 650 kbit/s and staying there (no "ISP in manual
    mode" line: AWB-05 does not start at night after a start). So the ceiling built up across the day -> night switch
    of a running server, most likely AWB-05 kept steering the ISP gains under IR (blue x 4.8, `bex` 1228 near the
    1536 cap; the .11 at night: `bex` 141, 941 kbit/s): grey-world on an IR picture, chroma noise amplified. Also
    `awb.state` now holds that night blue gain. To confirm at the next evening switch (bit rate and MWB gains
    before / after a video restart). See the implementer list (AWB-NIGHT).
- **2026-11-16 18:55, both cameras on 3.0.1 for 32 h (one night):** no reboot; `tc100_rtsp` up 26.5 h without a
  restart on both (its only restart, 15/11 15:24-15:27, follows the owner's `set_all_password` in the audit log), so
  no failure storm (L2 would exit after 30); 0 `picture failed` / AKUIO_WAIT_IRQ in the logs kept (the log cap keeps the
  last 2-4 h only: a per-day failure counter in `STAT` or the stability file would close this). Memory: `MemAvailable`
  17.1-17.7 MB on both, 17.9 MB just after boot: no leak. Night: .11 01:32 -> 07:47, .24 23:21 -> 07:49 (local),
  switches done by the vendor-luma source; **.24 went back to day for 3 min at dawn (06:43 -> 06:46, then night until
  07:49)**: the dawn flip-flop of the polish list, seen once. Evening (18:52) both in day mode with room lights on
  (exposure at its maximum, luma 87 / 111): correct. .24: `FAT-fs ... not properly unmounted` at the update reboot
  (SD card, harmless). Still to see by eye: the AWB-05 tint (owner).
- **2026-11-15, .24, second look (same still night scene):** the RAM binary had 4 `picture failed` (AKUIO_WAIT_IRQ
  timeout, one picture each, the next one fine) in 15 min, each within seconds of a `service-watchdog` restart of the
  stock `tc100_rtsp` (its check did not see a process of that name): that start resets the encoder core (`fe_hw_init`)
  before it finds the capture busy (`REQBUFS: Resource busy`). Run under the name `tc100_rtsp` (watchdog satisfied): 0
  failed in 2 x 55 s. A RAM-test artefact, not an ENC-02 fault; see the implementer list (a second instance must not
  touch the core before it holds the capture). The bit rate is the white balance, not the encoder: rc44 400 KB / 5 s
  (P 6.7 KB, IDR 68-78 KB every 50 at budget 8000); new binary with `RTSP_AWB_MANUAL=0` 1 MB / 5 s (P 18 KB: the ISP's
  automatic white balance moves the colour every picture, and R1 now lets that rise to the 1600 kbit/s ceiling at
  10 fps); new binary with AWB-05 (default) 155 KB / 5 s (P 170 bytes, IDR 73 KB every 25).

### T1-QP-BENCH Is the encoder's 0x4040 "tables" buffer its QP control buffer? Bench only (`[t1-qp]`) — `to test` (owner, test camera)
- **What:** a bench program, `src/h265enc/qpbench.c` + `qpctl.h` (CI test pack `tc100test/qpbench`): `freeenc.h` at a
  fixed QP from the ISP, three phases per run (vendor's values / one change / vendor's values), raw `.265` / `.264` files
  and `run.csv` (size, QP and the core's status words per picture). `freeenc.h` gets a hook that only the bench defines
  (`FE_BENCH_HOOK`). **Nothing is on by default and `tc100_rtsp` does not change** (same code without the hook).
  Procedure, experiments E0-E6 and how to read them: [frontier/t1-qp-bench.md](frontier/t1-qp-bench.md).
- **Switch / revert:** nothing to turn off: the bench only runs when started by hand, with `tc100_rtsp` stopped
  (`controlscripts/rtsp-h26x stop`, then `start`). It stops at the first failed picture and writes the vendor's values back.
- **Test:** E0 (`-x ctl`) first, then E1a `min=45`, E1b `max=28 -q 40`, E1c (`ctl` at QP 51 / 48 / 20 / 25), E2 `dq=0`,
  E3 `map=+10`, E4 `map=intra` / `map=skip`, E5 `map=+15,top`; E6 (list bits) only if E3-E4 show nothing, one bit per run.
  One experiment per run; note the exit status and `summary.txt` of each under this entry.
- **Pass criteria (of the bench, not of the hypothesis):** E0 ends with exit 0 and `no change` on a still scene, its
  three files decode without error (`ffmpeg -v error -i base1.265 -f null -`), and the video comes back after
  `rtsp-h26x start`. The result wanted is the answer per experiment (`CHANGED` or not, the PNG pair for E5): a visible
  top / bottom split in E5 confirms the per-block map; "no change" from E1 to E4 refutes it as things are (E6 or stop).
- **Risk:** a hung core needs a reboot (exit 5); nothing touches the flash or the settings.

### NATIVE-02 httpfront answers daynight, hw_state and health.cgi (`src/httpfront/poll.h`) — `to test`
- **What:** with `HTTPFRONT_NATIVE=1` (the default since rc28), `httpfront` now also answers by itself, without httpd and `sh`, the polled reads: `GET /cgi-bin/state.cgi?cmd=daynight&format=json` (Settings -> Day/night, every 5 s), `GET /cgi-bin/action.cgi?cmd=hw_state&format=json` (Hardware page, every 2 s), and `GET /cgi-bin/health.cgi` (when `/tmp/health_snapshot.cache` is fresh within TTL). Same JSON as the CGI byte for byte, same Basic login (no or wrong login: httpd answers as before). Anything it cannot print exactly as the shell does goes to httpd and the CGI: no `format=json` in the query, a `%XX` / `+` in `cmd` or `format`, a number with a leading zero or too long in `/tmp/cam_ae`, a value ending in `=`; for `hw_state` also a missing `/tmp/csrf_token`, no `/tmp/log`, `/tmp/log/audit.log` over 64 KB (the CGI rotates it), a pid file that is not one number; for `health.cgi` also a missing, expired, or > 1536-byte `/tmp/health_snapshot.cache`. `daynight` reads the files at each request and writes nothing (the CGI keeps its answer 1 s in `/tmp/state-response-daynight-json.cache`). `hw_state` appends the same line as `audit_log` of `action.cgi` to `/tmp/log/audit.log` (`<epoch> cmd=hw_state ip=<client>`). Host tests: `tests/test_httpfront_poll.py` (CGI under busybox ash against the native route on twin trees).
- **Switch / revert:** `HTTPFRONT_NATIVE=0` in `/mnt/config/boot.conf` (`TC100_NATIVE_STATUS=0` for `httpfront`), then restart the web server or reboot: every request goes to httpd and the CGIs again.
- **Test (one camera, `U=root:PASSWORD`, `C=http://CAMERA`):**
  1. Reference with `HTTPFRONT_NATIVE=0`: `time curl -s -u $U "$C/cgi-bin/state.cgi?cmd=daynight&format=json"` and `time curl -s -u $U "$C/cgi-bin/action.cgi?cmd=hw_state&format=json"`, 5 times each; note the times.
  2. `HTTPFRONT_NATIVE=1`, web server restarted: the same 10 requests, note the times. `curl -si` once on each: `HTTP/1.0 200 OK`, `Content-Type: application/json`, a `Content-Length`.
  3. Identical JSON: on the camera run the CGI itself, without httpfront, and compare with the native answer taken in the same second (repeat if the light or the sound level moved in between):
     `REQUEST_METHOD=GET QUERY_STRING='cmd=daynight&format=json' STATE_RESPONSE_CACHE_BYPASS=1 sh /mnt/www/cgi-bin/state.cgi | sed '1,/^$/d' > /tmp/dn-cgi.json; curl -s -u $U "http://127.0.0.1/cgi-bin/state.cgi?cmd=daynight&format=json" > /tmp/dn-native.json; diff /tmp/dn-cgi.json /tmp/dn-native.json`
     `REQUEST_METHOD=GET QUERY_STRING='cmd=hw_state&format=json' REMOTE_ADDR=127.0.0.1 sh /mnt/www/cgi-bin/action.cgi | sed '1,/^$/d' > /tmp/hw-cgi.json; curl -s -u $U "http://127.0.0.1/cgi-bin/action.cgi?cmd=hw_state&format=json" > /tmp/hw-native.json; diff /tmp/hw-cgi.json /tmp/hw-native.json`
     By day and by night (IR-cut moved), with each `DAYNIGHT_SOURCE` the camera uses, with the sound detection on (a `sound_db` value) and off, button pressed and released.
  4. 0 fork: `grep -E '^processes|^ctxt' /proc/stat` before and after 20 native requests of each kind sent from the Mac: `processes` rises by 1 per request (the child of `httpfront` for the connection), against about 10-30 per request with `HTTPFRONT_NATIVE=0`. `tail -3 /tmp/log/audit.log`: one `cmd=hw_state ip=<the Mac>` line per request, as before.
  5. Fallback still works: `curl -si -u $U "$C/cgi-bin/state.cgi?cmd=daynight"` (answered by the CGI: `Content-type: text/plain`), `curl -s -u $U "$C/cgi-bin/state.cgi?cmd=fullconfig&format=json"` (the CGI's JSON), `curl -si "$C/cgi-bin/action.cgi?cmd=hw_state&format=json"` without login (`401`), Open Settings -> Day/night and the Hardware page for 2 min: live values move, no error in the browser console.
- **Pass criteria:** native answers in < 50 ms each (reference: 0.5-2.5 s), 1 process per request (no `sh`, no httpd), `diff` empty in step 3 in every state tried, step 5 answers as before, pages unchanged. Any difference in step 3: note the two files and `HTTPFRONT_NATIVE=0`.

### VBR-QP-01 Configurable VBR quality QP (`RTSP_VBR_QP`, default 33) — `to test`
- **What:** `src/h265enc/rc.h`, `freeenc.h`, and `src/tc100rtsp/tc100_rtsp.c` add `rc_set_vbr_qp()` / `RTSP_VBR_QP` (default `33` when VBR is enabled). Previously VBR used `qmin + 2 = 27`, keeping indoor scenes pinned near the 1600 kbit/s ceiling (acting like CBR).
- **Switch / revert:** `RTSP_VBR_QP=0` in `/mnt/config/rtsp.env` followed by `controlscripts/rtsp-h26x restart` restores the previous `qmin + 2` (`27`) behaviour.
- **Test (`.24` with `vbr=1`, daytime indoor & covered lens):**
  1. Compare `RTSP_VBR_QP=30`, `33` (default), and `36` using `/tmp/logs/tc100_rtsp.log` (`STAT` kbit/s) and a snapshot/VLC check.
  2. Verify bitrate drops noticeably on a calm / covered-lens scene while staying crisp on motion under the configured ceiling.
- **Pass criteria:** Calm scene bitrate drops below ceiling (~20-40%+ reduction) with acceptable visual quality at `33`.

### KRN-02 Anyka OTG host: URB read after the giveback in `finish_request_epx` (`[kernel]`, kernel patch 0022) — `running 2026-11-14 on the .11 (build 4f43f3e): no oops / hang since boot; no specific trigger to test`
- **What:** `0022-usb-host-anyka-do-not-read-the-URB-after-giveback.patch`: the pipe type is taken before `usb_hcd_giveback_urb()` (the completion runs inline and may free the URB), and the periodic deschedule is left when `ep->period` is 0 (the loop could spin with interrupts off). No other behaviour change; fixes the defect of patch 0003 listed in a-faire-implementeur.md (13/11, point 2).
- **Switch / revert:** none at run time; revert = previous kernel (test from the SD card in RAM first, nothing in flash).
- **Test:** boot the kernel from the SD card on one camera; Wi-Fi associates, RTSP stream for 30 min, `wifi-stall-watch.sh 60` shows the HCD counters moving as before (`bulk_out_nak`, `bulk_in_oldest_ms`), one `wpa_cli -i wlan0 reassociate` and one reboot test; `dmesg` without USB error, oops or soft lockup.
- **Pass criteria:** same behaviour as rc43 (the fault itself is not reproducible on demand: review plus no regression).

### HRTIMER-01 High-resolution timers and NO_HZ_IDLE (`[kernel]`) — `to test (venc_soft_reset fixed 2026-11-14)`

- **What (`H4`/`H5`):** a kernel with `CONFIG_HIGH_RES_TIMERS=y` and `CONFIG_NO_HZ_IDLE=y` (the AK39 timer in patch 0001 declares `CLOCK_EVT_FEAT_ONESHOT`), and `src/tc100rtsp/tc100_rtsp.c` used `nanosleep()` in `pace_udp()` (works on both kernels; `pace_udp` and `RTSP_PACING_US` removed 2026-11-24, audit, CLEANUP-1124). Patch `0008` (`venc_soft_reset()`) was updated on 2026-11-14 from `usleep_range(100, 200)` to `usleep_range(1000, 2000)` so the hardware encoder soft-reset pulse stays 1–2 ms under `HIGH_RES_TIMERS=y` instead of shrinking to ~0.2 ms (and stays 1 jiffy under `HZ_PERIODIC`).
- **Test kernel only (2026-11-13):** 9d37efe had put both options in the base `defconfig_cma`, so every CI kernel (the next RC too) carried a timer mode no camera had ever booted; the read-only review classed it brick-class for a flash (if the one-shot path of patch 0001 misbehaves, the tick dies before the initramfs: SD recovery only), with side effects to watch: exact `usleep_range` before `ispdrv_ae_work()` (exposure writes earlier in the frame; `venc_soft_reset` pulse fixed in 0008). The base config is back to `HZ_PERIODIC`; build the test kernel with the workflow input `test_hrtimers` (packages get `-testkernel` in their version, see the 2026-10 entry below).
- **Test (SD kernel from a `test_hrtimers` run, nothing flashed):** Boot on SD (`boot66b.sh`), check `/proc/timer_list` shows `resolution: 1 nsecs` / `Event Handler: hrtimer_interrupt`, and run a 2 h H.265 soak (the `RTSP_PACING_US=200` step is void: the switch was removed 2026-11-24, audit); also check the picture for exposure flicker and the encoder after a reset (`vencreset`). Only after a pass, with the owner's agreement, move the two options into `defconfig_cma` as a change of its own.

### IDLE-MIC-01 Idle microphone DSP bypass & zero-fork MQTT/presence (`[opt]`) — `to test`

- **What:**
  1. `src/tc100rtsp/tc100_rtsp.c` (`aud_pump()`): when only `snd_on` keeps the microphone open (no RTSP audio viewer `aud_tx`, no local audio recording `rec_a`, no Web UI Listen FIFO `lis_count()`), skip `access("/tmp/speaker-play.lock")`, skip `adsp_sample()` / `aud_aec_sample()`, and skip `pcm[]` / `alaw()` packing while keeping raw samples flowing to `lvl_add(&snd_w, s)`. When an audio consumer connects (`0 -> 1`), reset `aud_dsp` filter/AGC state (`adsp_init`) and `aud_aec` (`aec_reset`). Also skip `pcm[]` / `lis_write()` whenever `lis_count() == 0`.
  2. `scripts/mqtt-bridge.sh`, `scripts/presence-mode.sh`, `scripts/common_functions.sh`: `build_health_payload var` runs in-process without subshells (`publish_health` keeps `BTIME` and `motion_state_payload`), `build_diag_payload` uses `/tmp/sd-health` without running `dmesg | grep` when `/tmp/sd-health` exists, and `presence_current var` runs in-process without spawning `sh presence-mode.sh current`.
- **Switch:** None required on shell scripts; sound detection stays identical (level meter runs before processing).
- **Test:**
  1. With `sound-detection` active and no audio client listening, measure `tc100_rtsp` main-thread CPU (`scripts/cpu-profile.sh 30 threads`) vs baseline, verify sound alerts still trigger normally, then connect VLC audio / Web Listen / recording and confirm clean audio with no initial click or stale AGC gain.
  2. Check `/health` and `/diag` MQTT messages arrive normally with valid JSON and zero stale `sd_errors` / `presence_mode`.

### WIFI-STALL-01 The ~8 s downstream stall of the .11: one evening to tell TX, RX, AP and scans apart (`[wifi]`) — `ROOT CAUSE FOUND 2026-11-14: TX A-MPDU (BlockAck) sessions; ampdu_tx=0 removes the stalls (results at the end)`

- **Diagnosis (read-only Fable analysis of the rtl8xxxu / mac80211 sources of the CI kernel, 2026-11-13; key facts
  checked):**
  - **mac80211 power save is ruled out:** rtl8xxxu sets only `SIGNAL_DBM`, `HAS_RATE_CONTROL`, `SUPPORT_FAST_XMIT`,
    `AMPDU_AGGREGATION` (no `SUPPORTS_PS`), no firmware LPS command is sent, `iw` shows `Power save: off`.
  - **RX reorder buffer unlikely** (mac80211 timeout 100 ms; RX DMA aggregation of the 8188F is off); `ampdu_rx=0`
    (WIFI-RXAGG below) stays a cheap control.
  - **No user-space scan at -25 dBm:** `wifi-roam.sh` scans only below -75 dBm twice in a row; no bgscan / autoscan;
    `wifi-quality.sh` = `iw station dump` + one ping a minute. Two stalls back to back (seq 54-69 then 71-80+) do not fit
    a 60 s job.
  - **Silent losses in the driver:** an RX URB that completes with an error is freed and never resubmitted (only a
    `dev_dbg`, compiled out): the pool of 32 can shrink without a trace. The Anyka host controller (patch 0003) has a
    bulk-OUT NAK limit of 16 and none on bulk-IN; a NAK timeout only counts and keeps the transfer pending, with no log.
  - **No debug tools on the camera:** no debugfs, dynamic debug, usbmon, ftrace or tcpdump in the image.
  - The "upstream has no stall" result (.11 -> gateway) was a separate 30 s run, not simultaneous with a stall: weak.
- **Ranked hypotheses:** **H5 (new) the camera's TX side stalls** (8188F NAKs bulk-OUT, silent HCD retries, TX URBs run
  out, mac80211 queues stop, echo replies released together: fits 0 % loss, the exact 0.5 s latency steps and the IRQ
  collapse); **H3** USB RX stops (fits the IRQ drop, but the residual 14-35 IRQ/s and self-recovery argue against);
  **H7 (new) receiver overload / CFO tracking at very strong signal** (the .11 read `level -13` dBm during a stall,
  extremely strong for this chip; only the MCS 7 camera is affected); H1 AP buffering (needs the camera silent: back to
  H5), H2 reorder buffer, H4 periodic job: unlikely.
- **Evening plan (steps 1-3 read-only; 4-5 change a setting, RAM only, revert by reboot; `wifi-try.sh` does not exist
  yet, so run 4-5 only with the owner able to power-cycle):**
  1. **TX or RX (10 min):** on the camera, `ping -c 1200 192.168.1.1 > /tmp/up.txt &` and
     `while :; do echo "$(date +%T) $(grep '^Icmp:' /proc/net/snmp | tail -1) rx=$(cat /sys/class/net/wlan0/statistics/rx_packets) irq=$(grep usb /proc/interrupts | awk '{print $2}')"; sleep 1; done > /tmp/s.txt`,
     while the Mac runs `ping -i 0.5 192.168.1.11`. Take the positions of `InEchos` / `OutEchoReps` from the `Icmp:`
     header line of `/proc/net/snmp`. During a stall: `InEchos` frozen = requests do not reach the camera (AP or RX:
     H1/H3); `InEchos` and `OutEchoReps` still +2/s while the Mac sees nothing = **TX side (H5)**; `up.txt` stalling in the
     same seconds = the whole link; `up.txt` clean = look at the AP.
  2. **Is RX alive during the stall (same run):** add `timeout 2 iw dev wlan0 station dump | grep -E 'beacon rx|tx retries|tx failed'`
     to the loop: `beacon rx` still rising ~10/s = radio and USB-IN alive (H3 out). Also `dmesg | grep -iE 'writeN retry|requeue urb|usb'`.
  3. **Scans:** `iw event -t > /tmp/ev.txt &` during step 1; then one deliberate `wpa_cli -i wlan0 scan` while pinging,
     to see what a scan looks like. No scan event at the stall times rules scans out.
  4. `WIFI_QUALITY=0` for 30 min, repeat step 1 (stalls unchanged = H4 closed).
  5. `echo 0 > /sys/module/rtl8xxxu/parameters/ampdu_rx && wpa_cli -i wlan0 reassociate` (drops the link a few seconds;
     net-guard reassociates at 2 min, reboots at 15 min), repeat step 1 (WIFI-RXAGG).
  6. Optional, decisive for the air side: macOS Wireless Diagnostics sniffer on channel 3 (2422 MHz) during a stall
     (null-data PM=1 from the camera, AP retries without ACK, or no camera frames at all).
  7. **H7:** move the .11 a few metres from the AP (or reduce its TX power with `tx_atten`, patch 0019) for 15 min and
     repeat step 1.
  - Also note whether the RTSP client was on TCP or UDP during the IRQ measurement of 2026-11-12: with UDP the IRQ drop
    alone already shows that TX stopped.
- **Step "counters" (test kernel, branch `wifi-counters`, `[wifi-counters]`; read-only, no behaviour change):** patches
  `0020-wifi-rtl8xxxu-read-only-tx-rx-counters.patch` and `0021-usb-host-anyka-read-only-nak-counters.patch` merged to
  main on 2026-11-14 (in rc43; read-only, `0444`): the regular rc kernel carries the counters, no separate test kernel needed.
  - **Build:** GitHub Actions, workflow "Build Linux 6.6", Run workflow on branch `wifi-counters` (~12-19 min); artifact
    `tc100-linux66-cma16-kernel`: `tc100test/c66.img` + `c66rd.gz`.
  - **Boot (RAM only, nothing flashed):** copy both to the SD card (`tc100test/`), `pack66/boot66b.sh` as in the AGENTS.md
    test loop; check `/proc/cmdline` has the full initrd size. A reboot without the card goes back to the flash firmware.
  - **Run during stalls (on the .11):** `sh /mnt/sd/wifi-stall-watch.sh 600 > /tmp/stall.txt &` (copy
    `scripts/wifi-stall-watch.sh` to the card; one line per second: `tx/s rx/s irq/s` and the counters; a missing counter
    is skipped, so on another kernel only the first three show). Keep `ping -i 0.5 192.168.1.11` running from the Mac to
    know the stall seconds; copy `/tmp/stall.txt` off afterwards.
  - **Counters.** rtl8xxxu (`/sys/module/rtl8xxxu/parameters/`): `tx_urb_free` (free of 64 TX URBs now), `tx_urb_min`
    (lowest since start), `txq_stops` / `txq_wakes` (all mac80211 queues stopped below 25 free / woken above 32),
    `tx_urb_err` (TX URB completions with status != 0), `tx_last_ms` (ms since the last TX URB completion), `rx_urb_lost`
    (RX URBs freed on error, never resubmitted; it also counts the URBs killed when the interface goes down),
    `rx_urb_alive` (of 32, in flight or pending). Anyka HCD (`/sys/module/otg_hs/parameters/`): `bulk_out_nak`,
    `bulk_in_nak` (NAK timeouts of bulk endpoints), `bulk_out_oldest_ms` / `bulk_in_oldest_ms` (age of the head pending bulk
    transfer per direction, 0 = none; IN is only "time since the last received frame", since rtl8xxxu keeps RX URBs queued
    permanently, so it is large on a quiet link and is not a fault; OUT is the one that shows a stuck transmit).
    **Traps:** every interface down/up kills the anchored URBs, so `rx_urb_lost` rises by up to 32 and `tx_urb_err` by the
    in-flight count: deltas across an interface restart are not stall evidence (also a reassociate that goes through
    ifdown, or net-guard). `tx_last_ms` reads 0 until the first TX completion after the start; it keeps growing while
    the interface is down (reset only at start), and a single sample taken exactly at an ifup can be huge or negative
    (two reads of the stamp): ignore one odd sample, trust a value that grows second after second. A NAK timeout of an
    interrupt endpoint (if the chip uses one) would also count in `bulk_*_nak`.
    All `0444`; a value on the command line is refused (`-EPERM`), harmless.
  - **Reading the patterns (compare a stall second with a normal second):**
    - `tx_urb_free` near 0 (and `tx_urb_min` low), `txq_stops` rising, `tx_last_ms` growing = TX URBs stuck in the HCD
      (submitted, never completed); then `bulk_out_oldest_ms` > 1000 says the HCD holds a transfer, and:
    - `bulk_out_nak` rising in the same seconds = the 8188F NAKs bulk-OUT (adapter FIFO full or busy: the TX side of the
      chip or its firmware is the one waiting; look at `irq/s` collapsing with it);
    - `bulk_out_nak` flat with `bulk_out_oldest_ms` large = the HCD does not restart the transfer (IRQ / schedule problem in
      patch 0003, no NAK timeout involved);
    - `tx_urb_free` high (about 64, no `txq_stops` change) but `tx_last_ms` large and `tx/s` ~6 = mac80211 / the driver
      does not submit (frames wait above the driver: queues, rate control, power-save-like holds); the HCD counters stay
      quiet;
    - `tx_urb_err` rising = URBs complete with an error (device or bus error), not a wait;
    - `rx_urb_lost` rising or `rx_urb_alive` below 32 = RX pool shrinking (H3 side); `bulk_in_nak` rising with `rx/s` low
      goes with it.
    - `txq_stops` and `txq_wakes` both rising by the same amount, `tx_urb_free` back to ~64 right after = a short stall
      the driver recovered from by itself; note the stall length in `tx_last_ms`.
  - **Pass:** at least two stalls recorded with the counters; the pattern above tells where the transmit side waits (record
    the lines around the stall under this entry). Nothing else is expected from this kernel; do not make it the default.
- **Follow-up for the implementer (only after the evening, no fix is certain yet):** the read-only `0444` counters are
  built (step "counters" above; still to add if wanted: the current crystal cap); a `rtl8xxxu.cfo_track` switch (0644, default on) for H7; requeue an RX URB on a
  transient error instead of freeing it (default-off until soaked); `scripts/wifi-try.sh` as designed in
  `audit-2026-11-06.md` before any remote parameter trial.
- **Pass:** the evening separates H5 / H3 / H7 / H1 with one decisive observation; record the four lines of `s.txt`
  around a stall and the step-1 verdict under this entry.

### MDNS-01 mDNS daemon: four correctness fixes after a read-only review (`[mdns]`) — `partly passed 2026-11-14 (rc43, Mac): names, browse and rate limit OK; iPhone / Windows / HA by the owner`
- **Host update (2026-11-13 — three remaining limits resolved on host):**
  1. Unified reply header + RFC 6762 §6.7 verbatim legacy question copy in `mdns_reply_head()` (`src/mdnsd/mdns_pkt.h`), eliminating the unchecked `n + 4` legacy copy in `mdns_answer()` and echoing exact original `q[4..5]` and `q[12..p)`.
  2. Added per-source-IP + global answer rate limiter (`struct mdns_ip_rl`, 16 IP slots x 20/s, global 80/s cap) in `src/mdnsd/mdns_pkt.h` and `src/mdnsd/mdnsd.c`.
  3. Added dedicated regression assertions in `src/mdnsd/test_mdns.c` (verified with `cc -O2 -Wall -Wextra -Werror -fsanitize=address,undefined`).
  *(Still awaiting live LAN camera verification of unicast/legacy mDNS responders on 3.0.1-rc43+.)*

- **Review (2026-11-13, read-only, `src/mdnsd`):** no memory-safety, loop or leak issue. Every length is checked against
  the received size, labels are at most 63, at most 8 pointer jumps, names at most 254, every write to `out` is length
  checked; the hostname is already sanitised by autorun with `tr -cd 'A-Za-z0-9-'` and again by the daemon. Four
  correctness defects were found.
- **What changes:** (1) a question name that uses a compression pointer (e.g. "A host.local" + "AAAA host.local" with the
  second name `c0 0c`, as Apple and Windows send) no longer makes the whole packet unanswered: the matcher follows pointers
  with the bounded logic of the DNS-SD path (8 jumps, only backwards, never onto itself, name < 255); malformed names are
  still refused. (2) Global limit of 20 answers a second (raw `clock_gettime`, no limit if the clock cannot be read), and
  the QR / opcode / question-count checks now come before the per-datagram ioctls and hostname read, so other hosts'
  responses cost nothing. (3) `out` is 1500 bytes (was 700): a full DNS-SD answer needs about 416 + 9 x hostname length,
  so 63-character hostnames got no answer. (4) Legacy unicast DNS-SD answers (source port != 5353) repeat the question
  section, clear the cache-flush bit and use TTL 10, like the A record path.
- **Switch:** none; revert the commit (`[mdns]` fix).
- **Test on the camera:** resolve `<name>.local` from a Mac, an iPhone, a Windows PC and Home Assistant (`ping`, browser);
  `dns-sd -B _rtsp._tcp` / `avahi-browse -art` lists the camera (with `MDNS_SERVICES=1`); `dns-sd -G v4 <name>.local` and
  `dig -p 5353 @224.0.0.251 <name>.local` (legacy, repeats the question); repeat with a 63-character hostname; flood
  `for i in $(seq 200); do dig +short -p 5353 @<camera> <name>.local; done` and check at most about 20 answers per second;
  compare idle CPU of `tc100-mdnsd` (`top`) with the previous build.
- **Pass:** all names resolve on all four systems, the browse lists the camera, the long hostname answers, no change in
  idle CPU, no crash or restart of the daemon (`/var/run/mdns.pid` stable) after the flood.
- **Known limits (re-check of 3d6dd92, verdict safe; not fixed):** the legacy (port != 5353) **A** answer still writes
  its own question (kernel-case host, type A) instead of echoing the query, so a strict resolver may discard a legacy
  ANY / mixed-case / multi-question answer (the DNS-SD path echoes since this fix); four bytes after `mdns_put_name` in
  that path are not bound-checked (unreachable today: ~172 bytes against `out[1500]`); the limiter is global, so one
  in-subnet sender at >= 20 matching queries/s takes each second's answers until it stops. Candidates for a later
  small change.

### RTSP-AUTH-01 tc100_rtsp: slot DoS, Digest replay, failed-login lockout, UDP talk source port, Content-Length (`[rtsp-auth]`) — `partly passed 2026-11-14 (rc43, .24): 50-connection slot flood, Frigate stream kept; Digest / lockout / talk with the owner`

- **Review (2026-11-13, read-only, `src/tc100rtsp/tc100_rtsp.c`):** no buffer overflow, no injection and no authentication
  bypass found (request line, header scanner, base64 and Digest field copies are all bounded; the password check cannot be
  skipped). Six weaknesses were verified and are fixed here.
- **What changes:** (1) At most `RTSP_PERIP` (rtsp.env, default 3, clamped 1..4) concurrent connections per source IPv4 (127/8 exempt: the WHEP gateway, `live.cgi`, the
  recorder). When the table or the address is full, a connection that is not authenticated goes first, whatever its age,
  from the address holding the most connections (oldest of them); then the old rule (idle >= 2 s and not playing). A
  playing client is never evicted, so a LAN host opening a connection every 0.5 s can no longer keep the 4 slots.
  (2) Digest: the nonce is random per connection (16 bytes of `/dev/urandom` read once, a counter and the clock through
  MD5, 32 hex digits; renewed on a challenge when older than 5 min); the `uri=` must equal the request-line URL (with or
  without `rtsp://host:port`, one trailing `/` ignored; the VLC / live555 form is accepted too: a uri that is the request path or a parent of it at a `/` boundary, e.g. `uri="rtsp://h/video0/"` on SETUP `.../video0/track1`, never a sibling such as `/video1`), so a captured response no longer authorises another URL such as
  `track3`; the Digest response, user name and the Basic `user:password` are compared in constant time. A client may
  reuse the nonce for the whole connection. (3) Wrong answers (an Authorization header that does not verify; the first
  request without one is the normal challenge and is not counted) are counted per source address: 20 in a minute lock
  that address (401 without checking) for the rest of the minute, as `src/onvifd`; 127/8 never counted, a locked address
  is never evicted from the 32-entry table, other addresses are untouched. A connection that already authenticated is never locked (a stale-password client on the NVR's address cannot make its keepalives fail). Known trade-off, not fixed (same as onvifd): with 32 locked addresses in the table, failures from a 33rd address are not counted for the rest of the minute. (4) UDP backchannel RTP must come from the exact
  port given in SETUP; `RTSP_TALK_NAT=1` in `/mnt/config/rtsp.env` brings back "same host, any port" for a client behind a
  NAT (default 0). (5) `Content-Length` is honoured (SET_PARAMETER, GET_PARAMETER, ANNOUNCE): the body is waited for and
  consumed with the request; a body larger than the 4 KB buffer closes the client. (6) `b64dec` and `num()` no longer
  overflow a signed int (mask, cap at 999999999).
- **Switches:** `RTSP_TALK_NAT=1` (rtsp.env) for (4); `RTSP_PERIP=<1-4>` for (1) (2 = the strictest); otherwise revert the `[rtsp-auth]` commit. The host tests use
  `TC100_TEST_NO_EXEMPT=1`, honoured only in the `TC100_HOST_TEST` build.
- **Test on the camera:** with a password set, stream from the NVR, Frigate, Home Assistant, go2rtc and VLC, each with
  Digest and (where the client allows it) Basic; WHEP live view; a talk session over UDP and over TCP (UDP: `RTSP_TALK_NAT`
  unset, the client keeps its SETUP port); with the NVR streaming, from one PC run
  `for i in $(seq 50); do (exec 3<>/dev/tcp/<ip>/554; sleep 1) & sleep 0.3; done` and check the NVR stream never drops
  and `/var/log` (or `rtsp.log`) shows "connections from one address, client N closed"; then 25 wrong passwords from one
  PC (`for i in $(seq 25); do ffprobe -v quiet rtsp://root:bad@<ip>:554/video0; done`) and check the NVR and a second PC
  still stream, while the first PC is refused for the rest of the minute even with the right password.
- **Pass:** every legitimate client streams as before (no new 401 loops, no dropped connection), the reconnect storm and
  the wrong-password run do not disturb the NVR, a PC behind a NAT talks with `RTSP_TALK_NAT=1` and not without, no
  crash or restart of `tc100_rtsp`.
- **Re-check of e7e2f9c (verdict safe), known limits not changed:** a Digest `uri=` of `/` (or empty, or
  `rtsp://host` alone) covers every path — still bound to the method and the per-connection nonce, and stricter than
  before (no uri check at all); there is no percent-decoding and no `?` boundary in the uri compare, so `uri=/video0`
  for a request `/video0?x` (or `%30`-style encoding) gets 401 and counts as a failure (fails closed; no known client
  does it); an authenticated connection may send wrong credentials without being locked (its holder knows the
  password). `RTSP_PERIP` that is not a plain number 1-9 (typo, `-1`, leading space) is ignored with a log line and
  keeps the default 3 (fixed after the re-check; it became 1 before).

### RTSP-UDP-NB non-blocking UDP RTP send (`[rtsp]`) — `to test`

- **What:** `src/tc100rtsp/tc100_rtsp.c` now passes `MSG_DONTWAIT | MSG_NOSIGNAL` on UDP `sendto`/`sendmsg`/`sendmmsg` (video, audio, and `RTSP_UDPSG=1`; the `sendmmsg` path, `RTSP_UDPMMSG`, removed 2026-11-24, audit). On transient `EAGAIN`/`EWOULDBLOCK`/`ENOBUFS` (e.g. during a Wi-Fi stall), video marks `wait_idr` + `want_idr` and increments `c->dropped` once instead of blocking capture or closing the client.
- **Test:** Stream UDP RTSP (`rtsp://.../stream0`) during a Wi-Fi disturbance or rate-limited link; verify `STAT` shows `dropped` incrementing without killing the UDP client or stalling `cap` fps.
- **Fix (rc42, `[rtsp-udp-nb]`):** the IDR request caused by UDP backpressure is rate-limited to one per stream every 2 s (`UDP_IDR_MIN_S`); the client still waits for the next IDR, natural or requested. Before, an IDR larger than the socket buffer (small `RTSP_SNDBUF`) made every frame an IDR for all clients of the stream. `sg_pkt` also stops queuing the rest of a frame for a UDP client in `wait_idr`. TCP clients unchanged. Extra check: with a small `RTSP_SNDBUF` and a UDP client, the encoder must not switch to all-IDR (frame sizes in `STAT`) (`RTSP_SNDBUF` removed 2026-11-24, audit: the check is void).

### WHEP-ONDEMAND start `tc100-whep` on demand (`[whep]`) — `to test`

- **What (`H10`):** `v3/autorun-linux66.sh` no longer starts `whep` at boot. When `WHEP!=0` in `boot.conf` and `/mnt/ext/bin/tc100-whep` is present, `www/cgi-bin/whep.cgi` answers `200 {"viewers":0,"ondemand":1}` to `GET` without spawning the daemon, and starts `/mnt/controlscripts/whep start` (`-I 300`, auto-exit after 5 min with 0 viewers) on the first `POST` SDP offer. Set `WHEP=0` to disable completely.
- **Fix (rc42, `[whep]`):** two POSTs at once no longer start two daemons: `controlscripts/whep start` takes a lock (`/tmp/whep-start.lock`, `mkdir`, about 10 s wait, a lock of a dead owner is removed) and re-checks the status once it has it; the pid file is written only after the daemon is up (a daemon that cannot bind never overwrites the pid of the live one); `whep.cgi` and `status` trust a pid only if the process is really `tc100-whep` (`/proc/<pid>/comm`, `cmdline`), otherwise the stale file is removed (a pid reused after the 300 s idle exit no longer gives 503/502). `TC100_NET_ALLOW` is still passed. Extra check: open the live view in two browser tabs at the same moment after an idle exit, then `ps` must show one `tc100-whep` and `/var/run/whep.pid` must name it.
- **Test:** After boot, verify `ps` has no `tc100-whep` (1–4 MB RAM saved), open the web UI live view, verify `tc100-whep` starts on the WebRTC `POST` and streams video cleanly.

### ENC-01 Free encoder: VBR and smart mode drive the free encoder (`[fe-smart]`) — `on, being watched; 2026-11-14: VBR active on both (log '1600 kbit/s ceiling (VBR)', .11 smart=1), mean ~1580 kbit/s on the indoor day scene; still-scene saving needs a covered lens (owner)`

- **Observation (2026-11-12 22:35, `.11` rc40, night):** 58,578 H.265 frames encoded across sessions with `0 failed`;
  `ABR` stepped down `1600 -> 1120 kbit/s` on 3 skipped frames and back up to `1600 kbit/s`. At night without 3D-NR
  (including 20 s with the lens covered), `STAT` stays at `970–1014 KB / 5 s` (~1550–1623 kbit/s ceiling) because
  high-gain sensor noise saturates the `QP 27/29` (`qmin=25 + 2/4`) quality target. Still-scene bit-rate drop
  remains to be checked by day or with 3D-NR on.

- **What:** the `rtspserver.conf` `[0]` `vbr` / `smart` settings (exported by `rtsp-launch.sh` as `RTSP_VBR` /
  `RTSP_SMART`, still the single source) had no effect since rc34 (the vendor library, and with it
  `ak_venc_set_smart_config`, is not loaded any more). They now act on the free encoder (`src/h265enc/rc.h`,
  `freeenc.h`, `tc100_rtsp.c`):
  - **`vbr=1`, quality first.** The configured kbit/s (`bps`) is a ceiling, not a target. The picture is coded at
    max(QP that just meets the ceiling, quality QP = `minqp` + 2). A still scene settles at the quality QP and costs
    less than the ceiling (CBR sinks to `minqp` and fills the budget); a busy one rises to the ceiling's QP. The credit
    saved below the budget is limited to 1 s, so a calm period does not allow a long burst. `vbr=0` is the old
    controller, bit for bit (golden output of the pre-change `rc.h` in `tests/test_h265cmdlist.py`).
  - **`smart=1`, needs `vbr=1`** (as on the vendor firmware; without VBR the log says "smart mode needs VBR" and
    nothing changes). `smart=2` (the vendor's variable GOP) has no free equivalent: treated as 1, logged.
    While the scene is still the GOP grows to `RTSP_FE_SMART_GOP` frames (default 250, at most 300, never below the
    base GOP `goplen` / `-g`) and the lowest QP is `minqp` + `RTSP_FE_SMART_QP` (default 4). Still means motion
    detection is running (`md_on`), no motion and no sound event for 8 s. Rule: `idr = frame == 0 || force_idr ||
    frame >= gop_long || (frame >= gop && (!still || idr_want))`: never more keyframes than today, and a client that
    waits for a keyframe (`wait_idr`, every place that sets it also sets `idr_want`) gets one at the base GOP at the
    latest. On motion the floor goes at once and the next keyframe comes at the base GOP.
  - **Fixed GOP is kept** on the recorded stream while recording is configured (`REC_LOCAL`, `rec.c` rotates on
    keyframes, 128 samples a fragment) and on the stream the browser live view reads (`livemp4.c`, 10 s without a
    keyframe). The recorder's thumbnails follow the encoder's real GOP (`fe_next_idr`).
  - **Lossy viewers.** A UDP client and the WHEP gateway (it reads `tc100_rtsp` over loopback TCP; WHEP ignores
    receiver reports and RTSP's RTCP is skipped) cannot ask for a keyframe after a lost packet. While any playing client of
    a stream is UDP or from 127.0.0.1, that stream keeps the base GOP (like the recording and live-view rule). The long
    GOP is used only when every playing client is a non-loopback TCP one (NVR, Frigate) or there is none.
  - **Time cap.** At least one keyframe every `RTSP_FE_SMART_MAXS` seconds (default 10, clamped 2-12) whatever the frame
    rate (`IDLE_FPS` lowers it under the same still condition, and the GOP counts frames).
  - **No burst of a long GOP.** A client joining when the cached GOP is longer than the base GOP gets no burst of old
    video: it waits for a keyframe and the encoder is asked for one at once.
  - **`RTSP_FE_SMART_QP` is clamped to 1-5** (default 4): with `RTSP_MD_ENC=1` a bigger floor makes its release look like
    motion to the encoder-size motion detector (false events from +6 at sensitivity 100); the detector's mean also
    restarts when the floor is released.
  - **Existing configs:** a camera whose `rtspserver.conf` already has `vbr=1` (and `smart=1|2`) gets real VBR / smart
    after the update, with no change by the user (these keys did nothing since rc34).
  - The vendor smart path (`smart_apply`, `p_smart`, `RTSP_SMART_FORCE`, `RTSP_SMART_GOP/_Q/_V`) is removed;
    `RTSP_FE_SMART_GOP` / `RTSP_FE_SMART_QP` are new optional names in `rtsp.env` (the launcher never overwrites them).
  - Relevant to #64 / R12-07: the Streams & audio page's bit rate mode and the vbr / smart readback now have a real effect
    to check there.
- **Switch:** `vbr=0` and `smart=0` in `[0]` (both are the defaults; nothing changes unless the owner sets them), then
  `controlscripts/rtsp-h26x restart`. Smart alone: `smart=0`.
- **Camera check first (30 min):** H.265 and H.264 at `-g 300` on the free encoder (`goplen=300` in `[0]`, which the
  launcher passes as `-g 300`, the sub stream follows it; run it once with `codec=2` and once with H.264 as the main
  codec), `vbr=0`, `smart=0`: no `picture failed` in
  `/tmp/logs/tc100_rtsp.log`, `ffmpeg -i rtsp://... -t 1800 -f null -` without decode errors, no oops. This is the
  longest fixed GOP the new mode can use (POC 2 x 299 < 1024, H.264 `frame_num` wraps at 16).
- **Test:**
  1. VBR alone (`vbr=1`, `smart=0`) with the log line `kbit/s ceiling (VBR)`: a still scene (cover the lens or aim at a
     wall, motion detection on) for 5 min, then a busy one (walk, wave) for 5 min. Bit rate from the `STAT` lines or
     `ffprobe -show_entries packet=size` over 60 s: still scene clearly below `bps` (expect -20 to -40 % against `vbr=0`),
     busy scene not above `bps` (mean over 60 s within +5 %).
  2. Smart (`vbr=1`, `smart=1`) with recording off and no browser live view: log "smart mode on: GOP 30 to 250". On a
     still scene count keyframes over 5 min (`FRAME ... IDR` with `RTSP_DEBUG`, or `ffprobe -skip_frame nokey`): about
     1 per 250 frames instead of 1 per 30. Wave a hand: within a base GOP the keyframe interval is back to `goplen`.
  3. Decode checks: Frigate on the main and the sub stream (no `Invalid data` / `missing reference`, detection and
     recordings fine), VLC (open mid-GOP on a still scene: the picture appears within the base GOP, 2 s at `goplen=30`
     and 15 fps), the browser live view and a recorded file (REC_LOCAL=1: files start on a keyframe, rotate on time,
     thumbnails present; the GOP of the recorded stream stays `goplen`).
  4. A second client joining during a still scene (TCP and UDP): no gray picture longer than the base GOP.
  5. Loss: a WebRTC (WHEP) viewer and an RTSP/UDP viewer on a still scene with `smart=1`: the log shows the GOP stays at
     `goplen` while they play (keyframe every 2 s at `goplen=30`, 15 fps), a corrupted picture heals within that time;
     with only an NVR over TCP the keyframes are far apart again. With `IDLE_FPS=5` the keyframe interval is at most
     `RTSP_FE_SMART_MAXS` seconds. With `RTSP_MD_ENC=1` no false motion event when a still scene turns to motion or back.
  6. `smart=2`: the log says "treated as smart=1". `smart=1` with `vbr=0`: "needs VBR", behaviour as CBR.
- **Pass:** camera check clean; 1 and 2 as expected with no decode error and no frozen image in 3 and 4; no `picture
  failed`, no oops over the 30 min. If a client misbehaves with long GOPs, set `RTSP_FE_SMART_GOP=100` in `rtsp.env`
  and report which client.

### AEC-01 Echo cancellation of the two-way audio, behind a switch (`[audio-aec]`) — `switched on, not measured` (2026-11-12, .11 rc40; step 1 measurements and a talk session still to do)

- **What (plan 3 of `plans-2026-11-12.md`):** with `RTSP_AUDIO_AEC=1`, a talk session (go2rtc, Home Assistant, Frigate: the
  RTSP backchannel) is played by `tc100_rtsp` itself on the playback device (`apb.c`, stereo S16_LE 8 kHz, non-blocking),
  not through `aplay`. The written samples are the reference of a fixed-point NLMS filter (`aec.c`, 256 taps = 32 ms, Q15, no
  floats, no libm) that removes the speaker's echo from the microphone before the level control (order: high-pass, echo
  canceller, residual suppressor 0 to -18 dB, level control). Double talk: Geigel test plus an error test freeze the
  adaptation (100 ms hold); the suppressor does not act when someone talks. The level gain does not rise while the far
  end plays. The microphone is **not** muted any more during a session (the half duplex duck of today), so the listener
  can talk over the speaker. `speaker-play.sh -hold` keeps the lock, the volume and the amplifier (no `aplay`).
  Clock skew between the DAC and the ADC (up to 0.16-0.7 %, plan) is handled by a linear resampler of the reference,
  `RTSP_AUDIO_AEC_RATIO` (`625/624` or ppm); the camera measurement gives the value, default 1.0.
  If the playback device does not open, today's path (`aplay` + the microphone duck) is used. Push-to-talk of the web
  UI and the sounds (`upload_audio.cgi`) keep the duck. Cost: 18 KB of RAM only when the switch is on, CPU only while the far end
  plays (256 multiply-accumulates a sample plus 128 updates on average, one division per 16 samples; to be
  measured, plan estimate 6-12 %).
- **Known cost to measure:** opening the playback stream (session start, and every underrun recovery) calls the codec
  driver's prepare (patch 0007: `akpcm_playback_prepare`, DAC clock, headphone power-up) which busy-waits tens of
  milliseconds (up to about 200 ms, to be measured) in the main loop of `tc100_rtsp`: a gap in the video and the audio
  at the start of a talk session. Mitigation in the code: 128 ms of silence queued first so underruns are rare, at
  most one recovery a second and eight in all (then `aplay` for the rest of the session, log line `keeps
  underrunning`); a device failure also falls back to `aplay` for the session. Measure the video frame gap
  (`STAT` lines / the RTSP timestamps of a viewer) when a talk session starts.
- **Switch:** `RTSP_AUDIO_AEC=0` (default, unset = 0) in `/mnt/config/rtsp.env`, restart `rtsp-h26x`. At 0 nothing
  changes: no allocation, the same `adsp_sample` path, `speaker-play.sh -` and the duck. Companions: `RTSP_AUDIO_AEC_RATIO`,
  `_DELAY` (ms, 20), `_TAPS` (256).
- **Prerequisite:** the end-to-end talk test (F1) passes with the switch at 0 (sound reaches the speaker from go2rtc / Home
  Assistant, push-to-talk refused during a session).
- **Test, in this order:**
  1. **Measurements first** (`audio-aec-measure.md`): `dmesg` rates, the probe at volumes 50/90/100 (RTSP server
     stopped, restarted by `rtsp-h26x start`), peak below -3 dBFS, click spacing (ppm), response length, offline echo
     reduction with `test_aec -f` with and without the ratio. Write the numbers below. Put the ratio and the delay
     in `rtsp.env`.
  2. `RTSP_AUDIO_AEC=1` and the measured values; restart the server. Log: `echo cancellation on`.
  3. With go2rtc or Home Assistant talk to the camera, a second person in the room talking in turns and at the same
     time, a viewer listening to the RTSP audio (VLC) or the Listen button: the sound of the speaker is not heard back
     (or only as a faint tail), the second person is heard without cuts while the talker speaks.
  4. `scripts/cpu-profile.sh 60` during a session (talk running) with the switch at 1, and at 0 for comparison;
     the log line `talk: speaker closed (echo canceller: N resets, M realigns)` after the session.
  5. Stop the session, push-to-talk of the web UI works at once; restart the talk; a web sound while talking is refused as before.
  6. Switch back to 0: the old behaviour (duck: the microphone is silent while the speaker plays) returns.
- **Pass:** echo reduction of the probe 20 dB or more at volume 90 offline; in step 3 the echo is not audible or at most
  a short faint tail after the talker stops, the near-end voice is clear during double talk; CPU of `tc100_rtsp` during
  a session at most +12 points over the switch at 0 and no frame drops of the video (`STAT` lines); `resets` 0 or 1 per
  session and `realigns` a few per minute at most; no underrun noise (clicks) in the sound; the amplifier and the lock
  behave as before (lock released after the session, no pop at the end beyond today's); switch 0 behaves exactly like
  the previous build.
- **If it fails:** keep 0 (the feature is off), write which step; the measurement files tell whether the ratio, the delay or
  the speaker's distortion (volume 100) is the cause.
- **Result:** (to fill in)
- **Known limitation (re-check of 735ef0e):** after the one allowed PREPARE the playback restarts without the
  128 ms prefill, so a single underrun can end echo cancellation for the rest of the session (the talk goes on
  through the safe aplay + duck fallback). Count the "keeps underrunning" log lines during the test; if they
  appear, re-prefill after PREPARE in a follow-up.

### ONVIF-02 onvifd: lockout per address, full answers on slow links, connection and discovery limits (`[onvifd-review]`) — `partly passed 2026-11-14 (rc43): discovery and auth refusal OK; (b) lockout needs the owner's password`

- **What (read-only Fable review of `tc100-onvifd`, 2026-11-12: no authentication bypass, no out-of-bounds access):**
  - Wrong logins are counted per address (20 a minute locks that address only; 127/8 never; 32 slots, a locked
    address is never evicted). Before, one global counter let any LAN host lock the NVR and Home Assistant out by
    sending 20 bad tokens a minute. Residual: more than 32 guessing addresses at once are not all counted.
  - `send_all` puts the socket back in blocking mode before sending, with 3 s for the whole answer. Before, the
    accepted sockets were non-blocking and an answer larger than the socket buffer (GetProfiles, Media2: up to
    24 KB) was cut at the first `EAGAIN` on a slow Wi-Fi link: a possible cause of a "flaky" ONVIF in an NVR.
  - At most 4 of the 6 connections from one address (127/8 not limited): six idle connections from one host held
    every slot.
  - WS-Discovery answers only a SOAP envelope and at most 20 answers a second, probes for other types not counted
    (a 7-byte `<Probe>` from a spoofed source got a 1 KB answer); a Resolve with a `wsa:ReplyTo` header is answered (it compared the ReplyTo address).
  - The five XML entities and ASCII character references (`&#39;`) are decoded in the user name and password: a password with `& < > " '` works in
    PasswordText (it failed before). `dur_s` no longer overflows on a huge duration.
  - Not changed (owner's choice): no nonce cache against replay of a captured PasswordDigest within ±300 s (some
    clients reuse nonces; LAN only).
- **Switch:** none; revert the commit.
- **Test:** (a) NVR and Home Assistant: discovery, add the camera, live view, motion events, as usual; restart Home
  Assistant: the ONVIF integration comes back. (b) Optional, from another LAN machine: 25 requests with a wrong
  password (e.g. a script with `curl` and a bad UsernameToken), then the NVR still works while that machine gets
  NotAuthorized even with the right password for the rest of the minute. (c) Optional: an ONVIF client on a slow
  link (phone app over Wi-Fi) lists both profiles completely.
- **Pass:** (a); (b)/(c) if run.

### WHEP-02 WebRTC gateway: LAN filter on its UDP port, consent from authenticated checks only (`[whep-udp]`) — `to test` (next RC, owner, with the WHEP entry of 2026-11-05; `.11` rc40 startup log confirmed `udp 8189: datagrams from the allowed networks only (NET_LAN_ONLY)`)

- **What (read-only Fable review of the UDP side of `tc100-whep`, 2026-11-12: no out-of-bounds access, nothing
  reachable without a session):**
  - UDP 8189 was bound to every interface and outside `NET_LAN_ONLY` (libnetacl filters accept / bind only, and the
    gateway was not started through it). `controlscripts/whep` now passes `TC100_NET_ALLOW` (`netacl_allow_list`, the
    same list as httpfront) and the gateway drops datagrams from other networks; log line `udp 8189: datagrams from
    the allowed networks only`. `NET_LAN_ONLY=0` gives an empty list = no filter, as before.
  - Only an ICE consent check with the right MESSAGE-INTEGRITY keeps a viewer alive (RFC 7675). DTLS and SRTCP
    datagrams no longer reset the timer: a datagram sent from a spoofed address kept a dead viewer's slot (one of
    `WHEP_MAX=2`) and its stream forever. The timer is 30 s instead of 12 s (Firefox checks every 4-6 s; two lost
    datagrams on the Wi-Fi must not drop a viewer). The page still sends its stop request when it closes or hides
    the video, so a closed tab frees its slot at once; the 30 s only matters for a viewer that vanished.
  - `profile-level-id=` at the end of a long fmtp line no longer reads past the copy (authenticated offer only).
  - Not changed: spoofed datagrams during the handshake window or a replayed binding request (needs sniffing on the
    LAN); one slow authenticated HTTP request stalls the single thread for a few seconds; a non-browser WHEP client
    whose keepalive is a STUN Binding Indication (libnice) is now dropped after 30 s; the network list is read when
    the gateway starts (after a change of `NET_ALLOW_EXTRA` / `NET_LAN_ONLY`, restart the WebRTC service too).
- **Switch:** `NET_LAN_ONLY=0` disables the filter; revert the commit for the old consent rule.
- **Test:** (a) Live view in Chrome and Firefox on the LAN, 10 minutes each: no "no sign of life (consent)" in
  `/tmp/logs/whep.log` while the tab is open; closing the tab frees the viewer at once (stop request), killing the
  browser without closing frees it within ~30 s. (b) Two viewers at once,
  then a third is refused as before. (c) The log shows the "allowed networks only" line. (d) Optional: from a non-LAN
  address (VPN outside `NET_ALLOW_EXTRA`), the live view falls back (no WebRTC) and the log shows no new viewer.
- **Pass:** (a)-(c); a browser that does not send consent checks would be dropped after 30 s: if one is seen, report
  which one.

### UPD-01 Web update: no upload / discard during an install, stricter package, true failure message (`[update-review]`) — `(a) passed, (c) passed 2026-11-14; (b) to test (owner, during a real install)`

- **What (read-only Fable review of `update66.sh`, `update.cgi`, `boot-guard`, 2026-11-12: no brick path):**
  - `update.cgi` refuses `upload` and `discard` while `/tmp/update66.running` exists. Before, a second tab or API call
    could delete the package being written, and without a card (services stopped for memory) `discard` restarted the
    camera in the middle of a flash erase.
  - `update66.sh check` refuses a package whose files are links, or whose `MD5SUMS` holds any line other than
    `md5  name` / `md5 *name` for `VERSION`, `stack.sqfs`, `c66.img`, `c66rd.gz` (a `VERSION` link showed any file in
    the page; a `/dev/zero` entry hung it). The real `MD5SUMS` of `build-release.sh` passes (test
    `test_md5sums_names_only_the_package_files`).
  - After a write failure the message no longer promises the web page (it lives in the stack partition, written
    first): it points to the SD card. `update66.sh` leaves `/tmp/update66.failed`, and `update.cgi` then refuses any
    upload, discard or install until a restart (a discard deleted the package and could restart on a half-written
    stack; a new install recopied its tools from the rewritten `/mnt`). No manual ssh retry is offered: `apply-ram`
    skips the package checks, and a retry pruned the only good backup. If the stack write was refused before any
    erase (flashw exit 1-4 or 7: no room for the backup on the card, md5, size), the message says the flash is
    unchanged and a restart starts the old firmware.
  - Known, not changed: two install POSTs a few ms apart can both start (check and marker are not atomic); a kill of
    the install shell (OOM) leaves no failed marker.
  - Not changed (owner's decision if wanted): writing kernel and initrd before the stack would keep the web retry for
    those two; mixed old/new partitions were not tested.
- **Switch:** none; revert the commit.
- **Test (next RC update over the web, owner):** (a) normal web update with and without a card: works as before.
  (b) During the install, from a second tab or `curl` with the CSRF token, POST `cmd=discard` and `cmd=upload`: both
  answer `busy`, the install finishes and the camera restarts normally. (c) Optional: a package with an extra line in
  `MD5SUMS` is refused at upload ("MD5SUMS names other files"). (d) Optional, SD test system only: `touch
  /tmp/update66.failed`, then upload / discard / install from the page answer the "failed half way" message.
- **Pass:** (a) and (b); no change for a normal update.

### WEB-01 httpfront login counting and remembered login (`[httpfront-auth]`) — `to test` (SD test system)

- **What (read-only Fable review of httpfront, 2026-11-12; `WEB_LOCKOUT=1` and `HTTPFRONT_NATIVE=1` are the
  `boot.conf` defaults, so this concerns every camera):**
  - A new password now forgets the remembered login: the cache `/tmp/.httpfront-ok` holds the MD5 of the header *and*
    of `/etc/httpd.conf`. Before, the old password kept getting the status line / dashboard JSON until a reboot.
  - Only the headers are searched for `Authorization:`: a form body line no longer counts as a wrong login (a hostile
    page could lock the owner's address out for 5 min, again and again).
  - Header name and `Basic` are read in any case, as httpd does: `AUTHORIZATION:` guesses are now counted.
  - A token cut by the end of the 2 KB peek (long cookies or URL) is neither checked nor counted, instead of counting
    as a wrong login.
  - Still possible, by design (LAN only, defence in depth): guesses placed after 2 KB of headers or sent after the 2 s
    wait are not counted; httpd still refuses them.
- **Switch:** `WEB_LOCKOUT=0` / `HTTPFRONT_NATIVE=0` in `boot.conf` as before; revert the commit for the old code.
- **Test:** SD test system with the CI `httpfront`. (a) Log in, change the password in Settings, then
  `curl -u root:<old> http://<ip>/cgi-bin/statusline.cgi` → 401 (before: JSON). New password → JSON. (b) From another
  LAN machine: 10 × `curl -s -o /dev/null -H 'AUTHORIZATION: Basic eDp5' http://<ip>/` → the 11th connection is closed
  (locked 5 min; 127.0.0.1 is never locked). (c) 12 × `curl -X POST --data-binary $'Authorization: Basic eDp5\r\n' -u
  root:<right> http://<ip>/cgi-bin/statusline.cgi` → never locked. (d) The web pages and the dashboard poll as usual,
  no extra 401 prompt.
- **Pass:** (a)-(d) as above, `/tmp/log/httpfront.log` without new errors.

### AWB-01 Why the ISP white balance goes blue on live statistics: live checks, then a fix (`[awb-fix]`) — `steps 1, 2, 4 done 2026-11-13 on both cameras; step 3 (paper, tungsten) needs the owner` (results at the end)

- **Diagnosis (read-only Fable analysis of patch 0006 and the recorded data, 2026-11-13; key facts checked):**
  - Every recorded `/tmp/cam_awb` line, on both cameras, by day and by night, fills **only bins 0 and 5** (bins 1-2
    tiny, 3-4 zero): `1894122 1083 8 0 0 3502` (.24), `272604 30 1 0 0 233` (.11), `17306 8 8 0 0 4572`, ...
    (`cam_awb` format: `cnt0..cnt9 ct rex=N bex=N u=N v=N`, field 11 = the kernel's colour-temperature index;
    tc100_rtsp.c ~1143-1154). Colour temperatures: A=0, TL84=1, D50=2, D65=3, A_1=4, TL84_1=5, D50_1=6 (start: D65).
  - With `awb_live=1` the arg-max picks bin 0 = illuminant **A** (tungsten): the A colour matrix and hue are applied in
    daylight and the gains come from a small set of (probably warm, non-white) pixels: the "lavender walls" of R15-01.
    Why bins 1-4 never fill is not established: region registers packed differently on the EV300 (`_set_awb_attr`),
    overlapping regions with first-match priority, or statistics taken after the WB gains.
  - The R12-09 dump means (203 / 183 / 80) show sums of 8-bit values in R, G, B order: a B/R swap is unlikely.
  - Secondary: the compiled `_calc_awb_gain` (the second one; the first is under `#if 0`) truncates (`sum >> 8`, then
    `max / (chan >> 8)`): blue over-driven by up to ~58 % on a small bin. Gains and the user-space extra gains
    (`_awb_ex_ctrl`) are only updated when the current bin passes `total_cnt_thresh` (patch 0006 ~6956): otherwise both
    freeze ("the software white balance changes little").
  - With `awb_live=0` the algorithm reads words 1032-1071, which are not counts; if that block is leftover memory it can
    differ per unit (possible reason for the .24 green). Nothing prints the ISP's r/g/b gains today.
- **Switch:** `echo 0 > /sys/module/ak_isp/parameters/awb_live` (default) and `rm -f /mnt/config/awb.off`.
- **Live checks (white paper or a white wall in view; one camera at a time, then the other):**
  1. Baseline: `cat /sys/module/ak_isp/parameters/awb_live; cat /tmp/cam_awb; sleep 3; cat /tmp/cam_awb` (note
     field 11).
  2. **Statistics before or after the gains:** static scene, `awb_live=0`: note the bins, `touch /mnt/config/awb.off`,
     wait ~10 s (rex / bex go back to 256), read `cam_awb` again, `rm /mnt/config/awb.off`. Bins changing by a large
     factor = statistics after the gains; unchanged = before.
  3. **A/B:** `echo 1 > /sys/module/ak_isp/parameters/awb_live`, read `cam_awb` every 2 s for 30 s in daylight, then
     under a tungsten lamp; finish with `echo 0`. Field 11 going to 0 (or 5) under both lights with bins 1-4 near 0 =
     the bin cause confirmed; rex / bex stuck at 128 or 1536 while u / v stay far from 0 = the frozen-gain cause; field
     11 following the light with bins 2-3 filling by day = bin cause refuted (look at the gain arithmetic). Then
     `dmesg | grep -i 'division by zero'` (the gain code divides by a bin count guarded only by the threshold).
  4. **Fixed block per unit:** `dmesg | grep 'statistics DMA area'` on both cameras; if a dump of words 1032-1071 is
     possible, compare .11 and .24 (different = leftover memory, the .24 green explained).
  5. Paste the `cam_awb` lines of steps 1-3 under this entry (no secret in them) and say what the paper looked like.
- **Fix (for the implementer, after these results; default off):** `ak_isp.awb_fix` (0644 bitmask, read per frame):
  bit 0 exact gains (64-bit division on the un-shifted sums, zero-count guard); bit 1 keep the colour matrix / hue at
  D65 and accept a bin only above N % of the frame; bit 2 apply `_awb_ex_ctrl` even below the threshold; bit 3 (only if
  step 2 shows statistics after the gains) closed-loop gains. If bins 1-4 stay empty with sane regions, compare the
  `_set_awb_attr` region packing with a stock register dump. For the .24, a mode with explicit fixed gains instead of
  the 1032 block. tc100_rtsp: add the R/G/B sums and the kernel r/g/b gains to `/tmp/cam_awb` (already in the ioctl
  struct). Test on both cameras (SD kernel): paper R/G/B within ±5 % under daylight and tungsten, field 11 follows the
  light, no kernel message.

### INST-01 SD install skips the per-partition backup only on a first install (`[fast-install-fix]`) — `to test`

- **What:** `v3/install/install66.sh` skipped the per-partition backup (`flashw -b`) whenever
  `restore-stock.sh --check` passed. That check compares only the `boot` and `mac` areas, so reinstalling from the card
  on a camera that already runs 3.0 from its flash overwrote its 3.0 vendor, stack, kernel and initrd with no copy
  (found by the read-only Fable review of `8077ff1`, 2026-11-12). The skip now also requires no valid settings slot in
  the flash (`cfg-persist saved` fails), i.e. a first install over the stock firmware. Not a brick path: every write is
  still read back by `flashw`.
- **Switch:** `INSTALL66_FORCE_PART_BACKUP=1` keeps forcing the backup in every case. To go back to the old behaviour,
  revert the commit.
- **Test:** (a) first install on a stock camera with a card holding a verified `flash-stock.bin`: the log shows
  "skipping redundant per-partition read-back" and `tc100-3/backup/` gets no new partition files. (b) SD reinstall on a
  camera already running 3.0 from its flash (`cfg-persist saved` prints a slot): no skip message, and
  `tc100-3/backup/` holds the vendor, stack, kernel and initrd copies of the previous flash content. Both installs need
  the owner's agreement per flash write.
- **Pass:** (a) and (b) as above, both installs finish, the camera boots from its flash afterwards.

## Owner-confirmed current work (2026-11-10)

These are the current owner-confirmed work items. The detailed switch-by-switch procedures stay in their existing entries.

1. **RTSP and recording qualification:** run the sender-thread multi-client and mixed TCP/UDP procedure in R16 below;
   also record to the SD card while RTSP is active, play the resulting file, test browser push-to-talk (UI-13), and
   confirm end-to-end talk through go2rtc, Frigate or Home Assistant. Record the camera, current build, transports,
   frame rates, `dropped`, memory, recording playback and both talk results. No flash write is part of this check.
2. **RTSP parameter schema:** the VBR/Smart pilot catalog and its focused consistency check are in the repository;
   run the camera save/reload and preservation check in R12-07. Extending the catalog beyond these two modes remains
   separate work.
3. **WHEP:** run the missing-key default, explicit `WHEP=0`, browser fallback, latency, one/two-viewer and resource
   checks in the WHEP entry below. No flash write is part of this check.
4. **Presence modes (#65):** configure each profile, apply it, check manual edits switch the selected-profile label
   to Custom, and check Home Assistant selection and state. Confirm an unsaved profile is rejected with a clear
   instruction to save it in Settings first. Run PRES-01 below from the SD test system; do not install this change
   in flash as part of the test.

### PRES-01 Presence modes — `to test` (owner, SD test system)

- **What:** user-configured Present, Away and Night presets apply privacy screen, motion detection, local SD recording
  and outbound Webhook/Ntfy/Telegram notification delivery, including alert image uploads. The initial state is Custom
  and does not alter any setting. Profile definitions and the selected mode persist in `presence.conf`; live values
  remain in `boot.conf` and `rtspserver.conf`.
  Home Assistant receives a Presence Mode select entity. MQTT telemetry and event topics continue in every mode.
- **Switch / return to Custom:** select Custom in the web page or Home Assistant. This leaves the current privacy,
  motion and recording settings in place and allows configured notifications again. Restore any desired baseline values
  through their existing Settings controls. Manually changing alert-channel configuration also returns to Custom.
- **Test:** boot the test user space from SD/RAM. Confirm the selected profile is Custom and settings have not changed.
  Save each profile without applying it and confirm this also leaves live settings unchanged. Apply each profile and
  verify the privacy image/audio behavior, motion detector state, `REC_LOCAL`, and notification delivery using a test
  recipient or endpoint. Confirm MQTT health and event topics remain available. Change privacy, motion or recording
  manually; the mode must become Custom without undoing the manual value. Change alert-channel settings and confirm the
  mode becomes Custom. Reapply a saved profile and confirm its values are restored. Reboot the SD test system and
  confirm the selected profile and values persist. In Home Assistant, select every configured profile and Custom;
  confirm an unconfigured profile is rejected with an instruction to save it in Settings, and that the reported state
  follows the applied profile. Do not use `flashw` or install
  a partition during this test.
- **Pass:** no action before an explicit profile selection; saved profiles survive an SD test reboot; applying one
  changes only its four selected actions; manual edits switch the reported mode to Custom and remain in effect; the
  Home Assistant entity and local controls agree; no service or RTSP regression.


---
Historical dated reports (2026-10-30 onward) were archived to [test-queue-archive.md](test-queue-archive.md).
