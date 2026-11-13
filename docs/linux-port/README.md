# Linux for the TC100 (AK3918EV300): the 3.0 work

Everything about running this camera on a free, recent kernel, in one place: the Linux 6.6 port, the
encoder work and the V3 user space (the 4.4 video fixes and the OpenIPC and Thingino experiments are in [history.md](history.md)).
**Nothing here is part of a 2.x release.** Until 2026-10-23 all tests ran from RAM (kernel loaded from the SD
card by the stock U-Boot) with the flash untouched; since 2026-10-24 the author's camera runs 3.0 from the SPI
flash (see [install-3.0.md](install-3.0.md) and the flash layout in [internals.md](internals.md), section "Flash layout of 3.0"). Goal: a free firmware on a recent kernel,
with the V3 web interface, H.264 and H.265.

Contents: [Status](#status) · [Hardware facts](#hardware-facts-verified-on-the-board) · [Building the 6.6 kernel](#building-the-66-kernel) ·
[Video encoder](#video-encoder-h264--h265--jpeg) · [User space](#user-space-on-66) · [Test loop](#test-loop-no-flash-writes-no-sd-swap) ·
[History and open items](#history-and-open-items)

## Status

**Field status (2026-11-09):** V3.0 has been qualified on many core aspects across both TC100 cameras. The
latest recorded installs are 3.0.1-rc36 on IPCAM2 and 3.0.1-rc35 on IPCAM1. Both ran for 12–15 hours after
installation with no recorded reboot, kernel oops, or OOM; the free encoder reported no failed frames and short
RTSP captures decoded without errors. This is strong field evidence, not a completed long-duration soak: the
planned seven-day watch was cancelled on 2026-11-09. See the latest report in [test-queue.md](test-queue.md).

| Area | State |
|---|---|
| CPU, interrupt controller, timer, console (TX polled, RX interrupt-driven) | works |
| Restart (top watchdog), `/dev/watchdog` | works |
| L2 buffer engine, SD card (`akmci`, 1-bit), USB host (`otg-hs`) | works |
| Wi-Fi: mainline `rtl8xxxu` on the RTL8188FU | works: WPA2, DHCP, transfers |
| GPIO (3 banks), LEDs, IR LEDs, IR-cut | works |
| I2C (`i2c-ak39`) | works: JX-F23 answers (id 0x0F23) |
| Video: V4L2 / vb2-dma-contig driver `ak39_vi` + the 4.4 ISP core | works: 1920x1080 NV12, 25 fps, real colours, AE running |
| Audio (`ak39_codec`, `ak_pcm`) | microphone captured through ALSA (`hw:0,0`); G.711 A-law track in RTSP; speaker playback is confirmed. Browser push-to-talk is implemented but remains in camera qualification (UI-13). ONVIF/RTSP backchannel code is present; end-to-end talk from go2rtc / Frigate / Home Assistant also remains to be confirmed |
| Encoder access (`ak39_venc` + `libakuio`) | works: hardware H.264 / H.265 / JPEG |
| Free hardware video encoder (`src/h265enc/freeenc.h`) | works (default since 3.0.1-rc34): free H.265/H.264 engine driving the ASIC core directly without vendor libraries (`RTSP_FREE_ENC=1`, 1080p & 720p H.265/H.264 + 360p H.264 sub-stream) |
| Hardware JPEG (free code, `src/jpegenc`, also inside `tc100_rtsp`) | works (web UI pictures, snapshots) |
| H.264 / H.265 + RTSP (`src/tc100rtsp`) | works: free hardware encoding via `musl` and `freeenc.h`, H.264/H.265 at 1080p and 720p, H.264 640x360 sub-stream; 25 fps supported. All main-stream modes were decoded without errors on IPCAM2; the latest short field captures on both cameras also decoded cleanly. The asynchronous sender is opt-in as `RTSP_SENDER_THREAD=1`; any default change follows a separate decision after its four-client and mixed TCP/UDP camera qualification. Long soak, UDP, recording, and end-to-end talk checks remain in the [test queue](test-queue.md) |
| V3 user space on 6.6 (`v3/`) | core services field-tested on both cameras: Pico web UI, CSRF-protected setup, Wi-Fi configuration, ONVIF, MQTT, supervisor, day/night, motion, WebRTC (enabled by default), and web updates. The timezone and Wi-Fi country are available in the wizard. Current build: `3.0.1-rc43` (field tests ongoing, last full multi-hour baseline was rc35/rc36; see [RELEASE-NOTES.md](../../v3/install/RELEASE-NOTES.md) and [current status and remaining work](a-faire-implementeur.md)) |
| SPI NOR (`spi-ak39`, polled PIO, 4 KiB erase) | works: read and write; `kernel`, `initrd`, `stack`, `vendor`, `cfga`, `cfgb` writable, `boot`, `mac`, `env` read-only |
| Boot from flash without the SD card | works since 2026-10-24 (cold boot without a card verified: video, snapshots, services) |

## Hardware facts (verified on the board)

- **SoC and board:** Anyka AK3918EV300 (ARM926EJ-S, chip id 0x20160100), 64 MiB DDR2 (about 33 MB usable by the stock Linux), sensor SOI **JX-F23** (I2C bus 0, 0x40), Wi-Fi Realtek **RTL8188FU** (USB `0bda:f179`), 8 MiB SPI NOR (XMC XM25QH64A), integrated AD/DA codec, GMAC without PHY. Board marking WVC3310S2_V5.0 (PCB YZ01-V1.0.0).
- **Core PLL, SYSCTRL 0x08.** U-Boot leaves 0x010213c8 (400 MHz, ASIC 100 MHz); the ISP then receives no lines. The 4.4 kernel runs 0x010203a0 (640 MHz, ASIC 160 MHz); on 6.6 that speed gave random crashes (corrupted registers and pointers), so 6.6 uses the stock 3.4 value 0x010213f0 (480 MHz, ASIC 120 MHz) by default (`ak_core_pll=` on the command line overrides it). Change: write the value with bit 23 set, then SYSCTRL 0x04 |= bit 28. The UART divisor is ASIC / baud - 1 (bit 22 when there is a remainder) and must be reprogrammed with it. Fields: m bits 0-7, n 8-11, od 12-13, vclk shift 17-19; PLL = 12·m / (n·2^od) MHz, vclk = PLL >> shift, ASIC = vclk / 2.
- **Clock gates** SYSCTRL 0x1C (1 = gated), soft resets 0x20 with the same bits (1 asserts, 0 releases): mmc0 1, uart0 7, l2 9, i2c0 10, gpio 12, usb-otg 15, mipi 16, encoder 18, camera/ISP 19. SYSCTRL physical base 0x08000000.
- **GPIO** (stock 3.4 board table, then checked on the board for everything but the speaker): IR LEDs 19, IR-cut A 81 / B 80 (pulse 150 ms, then both low), red LED 47, blue LED 15 (active high), reset button 10 (active low), speaker amplifier 14 (not tested). Registers at 0x20170000: DIR +0x00 (1 = output), OUT +0x0c, IN +0x18, one word per 32 pins. In 6.6 the chips are numbered 512, 544, 576.
- **L2 buffer engine** is shared by the UART rings, MMC, USB, SPI and the camera interface. Its init must not rewrite `rL2_CONBUF8_15`, or the UART RX dies. UART RX is a 128-byte ring at the TX buffer + 0x80; the write position is in DATA_CONF bits 13-19.
- **Watchdog restart:** SYSCTRL +0xE4 = (0x55 << 24) | ticks, then +0xE8 = (0xAA << 24) | 1, then | 3. 46875 ticks/s, about 357 s at most. A watchdog armed by the boot environment must not be reported to the core as hardware-running, or the core keeps feeding it and a hung test kernel never comes back.
- **RTL8188FU over the Anyka USB host:** the firmware download needs 64-byte EP0 writes (`writeN_block_size = 64` for the 8188f) and a few retries in `rtl8xxxu_writeN`. The firmware (`rtlwifi/rtl8188fufw.bin`, 21,020 bytes) is embedded in the kernel.
- **Sensor pads / I2C:** OR 0x40000710 into SYSCTRL 0x74, 0x01450525 into 0x7c and 0x100 into 0x80 (the 4.4 values); keep 0x78 bits 19-24 clear.
- **SD card:** with SDXC cards at 50 MHz, `CMD18 -84` (CRC) errors were seen on the OpenIPC 4.4 kernel; capping the clock to 25 MHz is the expected fix (not tried here).
- **Memory (6.6):** kernel at 0x80008000, initrd at 0x81000000, encoder pool 12 MiB at 0x81800000 (a reusable CMA area of its own since patch 15, pool 9600K by default; it was `no-map` before; the 1 MiB guard zones at 0x81700000 and 0x82400000 were removed on 2026-10-29: they never caught a write, +2 MiB of RAM), CMA capture pool from `cma=18M` on the command line (about 20 MiB at 0x82c00000; the 28 MiB of the device tree do not fit). The 3D-NR reference frame never fitted at video start; since rc9 `ak39_vi.nr3d=1` reserves it at boot (off by default, test queue R9-01). `ak39_vi.nr3d` is writable (0644) since the `[nr3d]` change and `boot.conf` `NR3D=1` sets it before the video starts; the reference is programmed at the 1080p crop size; the memory map is unchanged (test queue NR3D-01). Encoder pool 9600K by default since rc9 (`ak39_venc.pool`).
- **SPI NOR layout (6.6, 8 MiB, 4 KiB erase):** `boot` 0x0 (228 KiB, RO), `kernel` 0x39000 (2 MiB), `mac` 0x239000 (4 KiB, RO), `env` 0x23a000 (4 KiB, RO), `initrd` 0x23b000 (2 MiB), `stack` 0x43b000 (3.7 MiB squashfs), `cfga` 0x7ee000 and `cfgb` 0x7f7000 (36 KiB each, settings). `CONFIG_MTD_SPI_NOR_USE_4K_SECTORS=y` is required, otherwise the unaligned partitions are forced read-only.
- **Do not trust the first OpenIPC 4.4 report for pin numbers.** It lists IR LED 5, speaker enable 79, sensor reset 49, reset button 10, taken from the generic device tree; the table above is the verified one. The generic Anyka DTS maps `gpiokeys` to GPIO 84: on the TC100 that freezes the boot (IRQ storm), use `initcall_blacklist=gpio_keys_init`.

## Building the 6.6 kernel

The port is a series of 19 patches on the `v6.6` tag, in `patches/kernel-6.6/series/`:

1. `ARM: anyka` — `ARCH_ANYKA`, machine, interrupt controller, system timer, UART
2. `soc: anyka` — L2 buffer engine helper and the SD/MMC host (`akmci`)
3. `usb: host: anyka` — USB OTG host controller
4. `wifi: rtl8xxxu` — the AK3918 fixes for the RTL8188FU
5. gpio, watchdog, i2c
6. `media: anyka-isp` — ISP, video input (`ak39_vi`) and the sensor drivers
7. `ASoC: arm` — AK39 codec and PCM
8. `misc: ak39_venc` — encoder access
9. `ARM: dts` — the TC100 board
10. `spi` — the AK3918EV300 SPI controller (polled PIO) and the SPI NOR partitions
11. `media: anyka-isp` — USERPTR capture buffers
12. `media: anyka-isp` — cached capture buffers
13. `usb: host: anyka` — optional 32-bit FIFO access
14. `media: anyka-isp` — OSD ioctls for main and sub channels
15. `misc: ak39_venc` — encoder pool from reusable CMA area
16. `media: anyka-isp` — a smaller main format (1280x720) scaled from the whole sensor window
17. `media: anyka-isp` — allocate 3D-NR UV reference plane from the encoder CMA pool (`venc@81800000`)
18. `wifi: rtl8xxxu` — runtime `ampdu_rx` module parameter
19. `wifi: rtl8xxxu` — runtime `tx_atten` TX power attenuation parameter (`8188f`)

```
git clone --depth 1 -b v6.6 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
cd linux && git am ../patches/kernel-6.6/series/*.patch
cp ../patches/kernel-6.6/defconfig_cma .config && make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- olddefconfig
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- -j$(nproc) zImage dtbs
```

CI (`.github/workflows/build-kernel-linux66.yml`) does this on every push and publishes `oipc.img` (zImage + DTB as a uImage, load and entry 0x80008000) and the `tc100test/` folder in the artifact `tc100-linux66-cma16-kernel`, plus `System.map` and `vmlinux` in `tc100-linux66-symbols` (decode an oops with the symbols of the same run). The RTL8188FU firmware must be in `firmware/rtlwifi/` of the kernel tree: CI downloads it from linux-firmware (tag 20241017, SHA-256 checked); it is not stored in this repository. The vendor ISP tuning file `/lib/firmware/anyka/isp.conf` (the stock `isp_f23_mipi2lane.conf`) must be on the root filesystem before streaming.

The sources in `drivers/media/platform/anyka-isp`, `drivers/usb/host/anyka`, `drivers/mmc/host/akmci*` and `include/plat-anyka` derive from the vendor's GPL kernel sources (via OpenIPC/linux) and keep their copyright headers. `git apply` warns about whitespace in them; that is harmless.

### The video driver (`drivers/media/platform/anyka-isp/`)

Kept from 4.4: the ISP core (`ak39_isp2*.c`, `ispdrv_interface.c`), `/dev/isp_char` and the tuning loader, the sensor I2C and sensor drivers. Small changes: one hard-coded 4.4 virtual address, `dma_alloc_coherent` gets a real device, time64, JX-F23 at 768 Mbps. New `ak39_vi.c` replaces the soc_camera `ak_camera.c`: vb2-dma-contig, 4 buffers (the 4 ISP output slots) in continuous RGB video mode; at stream start it sets the pads, the CIS clock, resets the ISP, probes the sensor, sets MIPI 2 lanes (THS 0x89), loads the tuning, crop, scale, slots and starts; the IRQ completes the oldest slot while another stays armed; stop pauses and releases the ISP core so the next open re-runs the sensor init.

## Video encoder (H.264 / H.265 / JPEG)

**The hardware.** An Allegro DVT encoder IP (H.264, HEVC, JPEG; the family of Xilinx's ZynqMP VCU) at 0x20020000 (64 KiB), IRQ 2, clock/reset bit 18. The vendor `libakv_encode.so` ("AKV Encoder Lib V2.2.16", 361 KB) is only its control software: it imports libc and nothing else, and reaches the hardware through a table of 22 callbacks (print, malloc/free, register read/write, DMA alloc/free, cache flush, mutex and semaphore, IRQ wait, reset) that `libmpi_venc` provides, built on `libakuio` (physically contiguous memory, register window, interrupt).

**What exists for 6.6:**

- `drivers/misc/ak39_venc.c`: a misc device named `uio0` that maps the register window, waits for the IRQ, resets and gates the block, and exports a reserved 12 MiB DMA pool. ioctls (`include/uapi/linux/ak39_venc.h`): `AKUIO_SYSREG_WRITE` 'U',100; `AKUIO_WAIT_IRQ` 'U',101; `AKUIO_VIDEO_RESET` 'U',105; `AK39_VENC_POOL_INFO` 'U',110; mmap offsets: registers 0, pool 0x10000000.
- `src/libakuio/`: a free drop-in for the vendor `libakuio.so` (the 7 functions imported by `libmpi_venc`, `libplat_vi`, `libplat_venc_cb`, `libmpi_osd`), sub-allocating the pool in 32-byte units. `make selftest` checks the allocator on the host. It replaces `/dev/ion`, the patched UIO core and the pool at the fixed address 0x80000000 that the vendor library needs.
- `src/jpegenc/`: JPEG through the hardware JPEG engine, no vendor library (see its README).

**What the registers do** (from the vendor encoder's recorded hardware trace, about 29 registers):
0x20028010/14/18/1c/20 interrupt mask, status, core enable; 0x2002822c, 0x20028054, 0x20028300; 0x2002c004 (0xce00 / 0x4e00 toggled around the JPEG path); **0x20028080 = physical address of the command list, 0x20028084 = start** (2 = H.265 encoder 1, 0x10 = JPEG).
- **JPEG is register-driven** (0x200283c0..e8, eleven words, then 0x84 = 0x10; the length comes back in 0x3f4): done in `src/jpegenc`.
- **H.265 per-frame parameters are in a DMA command list** (two alternating lists of 896 / 448 bytes): words 0x000-0x0fc are written by the CPU, from 0x104 the core writes status back. Word 1 = 0x880860ef holds the size in 8-pixel units (bits 0-10 = 239, bits 12-22 = 134 for 1920x1080). The rest are buffer addresses (source Y/UV, stride 0x780, 2 reference frames of 3.4 MB, the stream buffer 0x7e900). `SliceParamToCmdRegsEnc1/2` in `libakv_encode` give the exact bit layout.
- Vendor DMA allocations at 1080p: 12 buffers, 7.6 MB.

**The open half.** [Xilinx/vcu-ctrl-sw](https://github.com/Xilinx/vcu-ctrl-sw) (MIT licence, same Allegro family) contains 142 of the 285 `AL_*` functions exported by `libakv_encode`: bitstream writers (SPS/PPS/VPS, SEI, scaling lists), API, buffers, part of rate control. Missing there: the CPU scheduler, `AL_EncCore`, `AL_EncChannel`, reference management, DPB, GOP manager, the encoder slice parameters. Rate control and HEVC reference management are the heart of the closed half: a long job.

**Plan and progress.**
1. Run the vendor `libakv_encode` / `libmpi_venc` on 6.6 through `ak39_venc` and `libakuio`: **done** (used up to 3.0.1-rc33). Direct capture
   is the default: the encoder and the JPEG engine read the V4L2 capture buffer itself (physical address from
   `AK39_VI_G_PHYS`, translated by `akuio_map_extra`), with no 3 MB copy per frame; `RTSP_DIRECT=0` goes back to the
   copy (`direct_setup` in `src/tc100rtsp/tc100_rtsp.c`).
2. Free JPEG (`src/jpegenc`): **done**, valid JFIF from the hardware core; the same code makes the web UI pictures
   inside `tc100_rtsp`.
3. Free H.265 / H.264 IDR + P frames with rate control (`src/h265enc/freeenc.h`, `listgen.h`, `worktab.h`): **done** (3.0.1-rc33/rc34),
   covering H.265 and H.264 at 1920x1080 and 1280x720 plus the 640x360 H.264 sub-stream, driving the hardware directly.
4. Remove `libmpi_venc` and `libakv_encode`: **done** (3.0.1-rc34/rc35). `tc100_rtsp` is compiled against `musl` with `libakuio`
   and `freeenc.h` built in; no vendor `.so` library is loaded or copied into the flash any more.

Tracing tool (2.x branch only, not in `main`): `libtc100fix` records the vendor encoder's hardware accesses (`VENC_TRACE=/tmp/<name>` in `boot.conf`, then restart `rtsp-h26x` in the background over telnet, never through a 60 s CGI call). The traces are vendor-derived data and stay out of git.

## User space on 6.6

- `v3/S39tc100-linux66`: the boot script of the initramfs. SD mode: it mounts the SD card. Flash mode (`flashroot=1`
  on the command line): `v3/linux66-sd/flashmode-prep.sh` mounts the `stack` squashfs, builds `/mnt` in RAM and restores
  the settings from the newest valid `cfga`/`cfgb` slot; a card, if present, is video storage at `/mnt/sd`. Then it sets
  the root password from `config/user.pwd` (without that file, root login stays disabled), brings Wi-Fi up from
  `config/wpa_supplicant.conf` and runs `v3/autorun-linux66.sh`. An optional hardware report runs when `tc100test/diag`
  exists, a self-test when `tc100test/selftest` exists (`v3/selftest66.sh`).
- `v3/autorun-linux66.sh`: V3 services: watchdog keeper, `tc100_rtsp` through `v3/linux66-sd/rtsp-launch.sh` (RTSP on
  port 554 and the web UI pictures), web server (`httpfront`), ONVIF, day/night, MQTT bridge, motion, recording (only
  with a card), `ntpd`, then the services ticked in the web UI (`config/autostart/`). The RTSP login is the camera
  password from `config/user.pwd`, read from that file by `tc100_rtsp`, never on the command line and never in git.
  Without the encoder stack (no vendor libraries, no `/dev/uio0`) there is no video; the web UI still starts.
- `v3/linux66-sd/`: glue between the web UI / scripts and the free stack (`rtsp-launch.sh`, `sdinfo-sd.sh`,
  `web-auth`, `wifi-apply`, `net-apply`), the flash tools (`flashw`, `cfg-persist`, `flashmode-prep.sh`). Its README
  is an inventory of the folder. The RTSP control script is `controlscripts/rtsp-h26x`, the IR-cut and
  LED helper `bin/setconf` (both shell scripts).
- `v3/build-rootfs66.sh [in] [out]`: builds the 6.6 initramfs from our Buildroot base (`v3/buildroot/`, built by CI) (replaces the boot script, drops the 4.4 modules, locks the image's default root password). About 2.5 MB unpacked instead of 6.9 MB: only what the boot needs stays (busybox, musl, wpa_supplicant + libnl, init scripts); the ALSA tools and libasound, dropbear (`v3/S50dropbear-linux66`), libz, libgcc_s and libatomic live in `ext/` of the user space (links and the musl path file in the initramfs find them, see test-queue B-01). Needs root.

## Test loop (no flash writes, no SD swap)

The owner starts the UART logger (`uart.sh`) and runs the test from the Mac with `pack66/boot66b.sh`. Copy the CI kernel and initramfs to the SD test paths with `pack66/send.sh`; `boot66b.sh` prepares the RAM boot and returns to the installed firmware when the test kernel hangs. The script may stop in the bootloader internally, but the test procedure does not require a manually entered U-Boot command or an edited environment.

Before booting, compare the kernel and initramfs checksums on the SD card with the CI artifacts. Pass any test-only kernel arguments through `EXTRA` to `pack66/boot66b.sh`; do not edit `bootargs` or enter commands at a U-Boot prompt. After the camera starts, check that `/proc/cmdline` contains the complete `initrd=0x81000000,<size>` value; if it does not, stop and report the result because the camera may have fallen back to the flash firmware. Use `ucmd.sh` for camera commands and the script's documented `RD`, `CMA`, `EXTRA` and `WDT` settings for the test boot.

The installed boot order tries the SD test kernel first and then the flash firmware, so an SD test does not write any flash partition. The owner handles any required physical power cycle. Flash writes, when separately authorized, go only through `v3/linux66-sd/flashw` after a dump and read-back verification; `boot`, `mac` and `env` are never written from Linux.

## History and open items

- Open items, ranked: [a-faire-implementeur.md](a-faire-implementeur.md) (priority list) and
  [audit-2026-11-06.md](audit-2026-11-06.md) (audit of the whole project); the hand-off with the real camera is
  [test-queue.md](test-queue.md).
- Everything dated and finished (Linux 4.4 video fixes, OpenIPC and Thingino experiments, the H.265 command list, the
  first boot of the slim 6.6 kernel, the first `tc100_rtsp` sub-stream / recorder / Listen / live-video notes):
  [history.md](history.md).
