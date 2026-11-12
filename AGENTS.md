# Instructions for AI agents working on this repository

Free firmware for the TECKIN TC100 camera (Anyka AK3918EV300, JX-F23 sensor, RTL8188FU Wi-Fi): Linux 6.6, the V3 web UI,
free H.264/H.265 encoding and RTSP, to behave like the original firmware. Read `docs/linux-port/README.md` first (status,
hardware facts, test loop), then `docs/known-issues.md`.

## Ground rules
- **Language:** the owner writes French; answer in the language of his last message. Commit messages and docs are English
  unless the file is already French.
- **No brick, ever.** U-Boot, `boot` and `mac` are never written; the bootloader is out of scope. Since 2026-10-24 the kernel,
  initramfs, user space (`stack`) and settings (`cfga`/`cfgb`) live in the SPI flash and are written only with `v3/linux66-sd/flashw`
  (read-back checked) and with the owner's explicit agreement for each partition write. The U-Boot environment was changed once
  (adds `flashboot`; SD kernel `tc100test/c66.img` keeps priority = way back). Take a dump before writing anything: the web
  update saves each partition to the SD card first (`flashw -b`, a failed backup = nothing written); without a card it
  writes only after the user confirmed "install without a backup" (`update66.sh`, `UPDATE66_NOBACKUP=1`, owner's decision
  of 2026-11-06), the way back being then the 3.0 SD card.
- The owner power-cycles the camera himself; do not try to automate a power cycle. After a panic the camera reboots into the
  flash firmware (also Linux 6.6, hostname IPCAM2), which is the fallback shell.
- Never put passwords, tokens or the MQTT/RTSP credentials in the repo, in docs or in chat. The owner enters them himself.
- Deleting files in his connected Mac folders is disabled: rename instead. Do not delete `_archive_*` folders without his OK.
- OpenIPC forum post #2639: update as a draft only, and do not mention 6.6.
- Commit trailers (required): `Co-Authored-By: <model> <noreply@anthropic.com>` and the `Claude-Session:` URL; push to `main`.
  A stop hook refuses to end a session with uncommitted changes.

## Maximum control from Linux without ever touching U-Boot
- **Never touch U-Boot or its environment (`boot`, `env`, `saveenv`, `bootargs`).** There is no serial console attached in
  normal operation. Never require a U-Boot prompt command or a kernel command-line edit to test or enable a feature.
  **The one sanctioned exception** (owner, 2026-11-06): the first-install hook of the SD package
  (`v3/install/stock-hook.sh`, run once by the stock firmware) adds the 3.0 boot commands to the environment with
  `envtool` (`sdload`/`sdboot`/`flashcheck`/`flashboot`, `boot_normal` unchanged), after a verified backup of the
  environment and of the whole flash, and restores the original if the write fails; without it a new camera cannot
  start 3.0 from its flash. No other code, script or agent writes the environment, and this hook must not grow.
- **Bypass U-Boot limitations entirely from Linux:**
  1. **Compiled-in kernel defaults:** Validated parameters (`ak39_vi.sub_channel=1`, `ak39_vi.slots=3`,
     `ak39_venc.pool=9600K`) must be the C defaults in `patches/kernel-6.6/series/00NN-*.patch` so they work regardless
     of `/proc/cmdline`.
  2. **Runtime-writable sysfs parameters (`0644`):** Expose driver switches that are re-read at device open or streaming
     start (e.g. `ak_isp.awb_live`, `0644` since 2026-11-12, read at every frame) as `0644` `module_param` /
     `module_param_cb` instead of read-only `0444`. A switch that the driver only *applies* and never undoes stays
     `0444`: `ak39_vi.sub_channel=0` at stream start leaves the sub channel programmed (no reset), and `tc100_rtsp`
     chooses the hardware sub picture from the buffer size, not from this parameter. Boot-time
     DMA allocations (`slots`, `pool`) stay boot-time with C defaults ("at most one reboot", never live realloc).
  3. **User-space control via `/mnt/config/` (single source per setting):** Drive all hardware and kernel toggles from
     `/mnt/config/boot.conf` or `/mnt/config/rtsp.env` (`autorun-linux66.sh` / `rtsp-launch.sh` writing to
     `/sys/module/*/parameters/*` or issuing ioctls), requiring at most a service restart or normal Linux reboot. Keep a
     single authoritative config file per setting (never duplicate a key across `boot.conf` and a service `.conf`).
  4. **Unattended recovery in initramfs & pre-flash kernel boundary:** Boot counters, fallback to the previous
     user-space/initrd, persistent SSH keys, and previous-boot logs live in the Linux initramfs and `cfga`/`cfgb`/SD
     card, never in U-Boot. **Limit:** if a flashed kernel itself fails to boot, the initramfs is never reached and
     U-Boot always loads `mtd1`. Therefore, protection against a broken kernel must happen *before* flashing (strict size,
     checksum, and target-partition verification; one kernel change at a time; owner near the camera).

## Work shared between agents
- `docs/linux-port/test-queue.md` is the hand-off: every change that needs the real camera gets an entry there (what,
  switch to turn it off, test, pass criteria). Testers write results under the entry and make passed changes the
  default. Read it before starting; update it in the same commit as the change.
- Run `sh tests/docker/local-ci.sh tests|cross|kernel|all` (Docker) before pushing: GitHub CI only confirms.
- Prefix the commit subject of a work stream (e.g. `[hwaccel] ...`): the CI run carries the subject as its title, so
  the tester can find the build of an entry.

## Where things are
- `main` is 3.0 only. The 2.x firmware (vendor kernel 3.4, lighttpd, `libtc100fix`, `src/flash`, `autorun.sh`) is on the
  branch `2.x`; do not bring its files back. Shared scripts still carry `[ -f /tmp/linux66 ]` branches from the time both
  lived here: the 3.0 side is the one that matters.
- `patches/kernel-6.6/series/00NN-*.patch` are the source of truth for the kernel (applied on tag `v6.6`). `patches/kernel-6.6/audio/`
  and `defconfig_cma` are reference copies. Editing a patch that adds a whole file: recompute the `@@ -0,0 +1,N @@` count
  (`git apply --stat` must pass).
- CI `.github/workflows/build-kernel-linux66.yml` (~12-19 min per push) builds the kernel: artifact `tc100-linux66-cma16-kernel`
  (`oipc.img` = uImage, `tc100test/*`) and `tc100-linux66-symbols` (System.map, vmlinux). Decode oopses with the symbols of
  the same run, not with a local build (addresses differ).
- `src/tc100rtsp` = free RTSP server (H.264/H.265 over RTP, TCP and UDP, optional G.711 A-law audio track, `-a 1`); built with
  `make` using the glibc ARM cross compiler but linked to run under the camera's uClibc loader. `src/libakuio` = userspace
  access to the vendor encoder libraries. `v3/` = boot script and initramfs for 6.6; `controlscripts/`, `www/` = V3 user space.
  The other free programs, all built by CI: `src/httpfront` (web front), `src/whep` (WebRTC gateway, built by Buildroot),
  `src/onvifd`, `src/mqttd`, `src/supervisord`, `src/mdnsd`, `src/logfwd`, `src/netacl`, `src/rwconf`, `src/ispflip`,
  `src/jpegenc`; bench / research tools: `src/ispfps`, `src/h265enc`; `src/webui` = build steps of the web UI (CSS
  bundles, index bundle, minification, screenshots). Full list: `docs/linux-port/internals.md` "Repository structure".
- Project notes (status, test results, traps) live in the claude.ai Project "Teckin Camera Alternative Firmware" as `claude/*.md`
  docs; start with the newest (`status-*`, `clock-480mhz-*`, `audio-mqtt-memoire-*`).

## Test loop (serial + SD, no flash)
- A Pico debugprobe gives the UART on the Mac; `uart.sh` (the owner starts it) logs to `uart.log` and reads `uart-in.txt`.
  From the Mac shell: `ucmd.sh "cmd" [wait]` runs a command on the camera, `pack66/send.sh <local> <path-on-sd>` copies a file
  to the SD card, `pack66/boot66b.sh` (env `RD`, `CMA`, `EXTRA`, `WDT`) reboots, stops in U-Boot and boots `tc100test/c66.img`
  + `c66rd.gz` (RAM only). Mac shell calls last at most 180 s and background processes do not survive.
- **U-Boot truncates `bootargs` at 256 characters.** Keep `initrd=0x81000000,<size>` early. Always check `/proc/cmdline`
  contains the full initrd size, otherwise the camera silently falls back to the flash firmware and looks "up".
- Files from the cloud container to the Mac: copy to `/mnt/user-data/outputs/<new name>` and `device_commit_files` with
  `stagedPath`. Use a **new file name** for each version (an overwritten name was not refreshed once).
- Overnight soak queue on the Mac: `nq/nqstep.sh` (phases DEPLOY, CONFIG, BOOT, WAITUP, SOAK, DONE; variants in
  `nq/variants.txt`, results in `nq/results/`). Verdicts: kernel errors, a second "Starting kernel" (reboot) or three silent
  shell checks (wedge).

## Hardware and kernel facts that cost time
- **Core PLL must be 480 MHz (SYSCTRL 0x08 = 0x010213f0, ASIC 120 MHz).** At 640 MHz (the 4.4 value) 2 of 4 one-hour H.265 runs
  crashed with corrupted registers; at 480 MHz 6 of 6 runs survived (up to 2 h). `ak_core_pll=<value>` overrides it for tests.
- Memory map: encoder pool: 12 MiB region at 0x81800000 (reusable CMA area of its own, pool 9600K by default; the 1 MiB guard zones were removed on 2026-10-29), CMA 20 MiB at 0x82c00000
  (`cma=18M` on the command line; the DT value of 28 MiB does not fit). The 3D-NR reference frame (6 MiB) never fits at video start, so 3D-NR is off by default; `NR3D=1` in `boot.conf` takes it before the video starts (720p is the reliable mode; the only free 8 MiB window, 0x82400000-0x82c00000, is deliberately left alone; test queue NR3D-01).
- ISP sub channel: on by default in the kernel (`ak39_vi.sub_channel=0` turns it off; older kernels need `=1` on the
  command line, U-Boot `flashargs`/`flashboot`, `stock-hook.sh`); `tc100_rtsp`
  then takes the 640x360 picture from the ISP (`RTSP_HWSUB=0` = CPU sampling). U-Boot reads at most 256 characters per line:
  long values are set through a variable (`setenv flashboot run flashload\; setenv bootargs \${flashargs}\; bootm 0x82000000`).
- Debug switches: `ak39_vi.guard=1`, `slub_debug=ZP page_poison=1`, `oops=panic`, `ak_wdt_reboot=300`,
  `AKUIO_REGSCAN=1` (libakuio).
- Audio: the microphone is ALSA `hw:0,0` (mono, S16_LE, fixed 512-byte period). Do not pass `arecord -F/-B` (I/O errors).
  `/dev/akpcm_cdev*` of the vendor firmware does not exist on 6.6. The capture start is delayed 300 ms in the driver; the
  stop/close paths must cancel it (fixed in patch 0007).
- MQTT: `/mnt/config/mqtt.conf` (copy of `config/mqtt.conf.dist`); `MQTT_ENABLE=1`, broker host, and
  `MQTT_HA_DISCOVERY_ENABLE=1` for Home Assistant entities.
- Killing `tc100_rtsp` is safe again (audio fix), but restart it with the same arguments as `v3/autorun-linux66.sh`.

## Open items
- The ranked list of what is left: `docs/linux-port/a-faire-implementeur.md` (French; its top sections are the current
  priorities), with the measured audit `docs/linux-port/audit-2026-11-06.md` (flash size, Wi-Fi losses, features,
  hardware headroom). What waits for the cameras: `docs/linux-port/test-queue.md` (closed entries are in
  `test-queue-archive.md`). Older audits (`feature-audit-2026-10-26.md`, `audit-2026-11-03/04.md`) are history.
- Done for the rc32 (owner, 2026-11-06): the Classic look (Bulma, `ui-modern.min.css`, the Appearance choice) and
  `bin/monvifd` are removed; Pico and `tc100-onvifd` are the only ones.
- The project notes of the claude.ai Project (`claude/status-*`) complement this; the repository is the reference.
