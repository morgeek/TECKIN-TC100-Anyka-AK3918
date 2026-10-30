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
  (adds `flashboot`; SD kernel `tc100test/c66.img` keeps priority = way back). Take a dump before writing anything.
- The owner power-cycles the camera himself; do not try to automate a power cycle. After a panic the camera reboots into the
  flash firmware (also Linux 6.6, hostname IPCAM2), which is the fallback shell.
- Never put passwords, tokens or the MQTT/RTSP credentials in the repo, in docs or in chat. The owner enters them himself.
- Deleting files in his connected Mac folders is disabled: rename instead. Do not delete `_archive_*` folders without his OK.
- OpenIPC forum post #2639: update as a draft only, and do not mention 6.6.
- Commit trailers (required): `Co-Authored-By: <model> <noreply@anthropic.com>` and the `Claude-Session:` URL; push to `main`.
  A stop hook refuses to end a session with uncommitted changes.

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
- Memory map: encoder pool 12 MiB at 0x81800000 (nomap) with 1 MiB guard zones around it, CMA 20 MiB at 0x82c00000
  (`cma=18M` on the command line; the DT value of 28 MiB does not fit). The 3D-NR reference frame never fits, so 3D-NR is off.
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

## Open items (see the newest `claude/status-*` doc)
Ranked list and feature-by-feature status: `docs/linux-port/feature-audit-2026-10-26.md` (web login missing on 6.6,
flash image built from the SD card instead of git, Wi-Fi from the UI not kept, IR-cut, second flash writer).
Sub-stream and RTSP over UDP checks, audio listening test in Frigate/VLC, MQTT entities in Home Assistant, ISP colour cast
(blue is low), day/night, final SD package and README (install by copying to the SD card, way back to the original firmware),
SD test-file cleanup, optional removal of the guard zones (2 MiB) from the final build.
