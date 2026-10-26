# Linux for the TC100 (AK3918EV300): the 3.0 work

Everything about running this camera on a free, recent kernel, in one place: the Linux 6.6 port, the
video fixes on 4.4, the encoder work, the V3 user space, and the OpenIPC and Thingino experiments.
**Nothing here is part of a 2.x release.** Until 2026-10-23 all tests ran from RAM (kernel loaded from the SD
card by the stock U-Boot) with the flash untouched; since 2026-10-24 the author's camera runs 3.0 from the SPI
flash (see [the flash install](flash-install-plan-2026-10-24.md)). Goal: a free firmware on a recent kernel,
with the V3 web interface, H.264 and H.265.

Contents: [Status](#status) · [Hardware facts](#hardware-facts-verified-on-the-board) · [Building the 6.6 kernel](#building-the-66-kernel) ·
[Video encoder](#video-encoder-h264--h265--jpeg) · [User space](#user-space-on-66) · [Test loop](#test-loop-no-flash-writes-no-sd-swap) ·
[Linux 4.4 video fixes](#linux-44-what-was-needed-for-frames) · [OpenIPC](#openipc) · [Thingino](#thingino) · [Open items](#open-items)

## Status

| Area | State |
|---|---|
| CPU, interrupt controller, timer, console (TX polled, RX interrupt-driven) | works |
| Restart (top watchdog), `/dev/watchdog` | works |
| L2 buffer engine, SD card (`akmci`, 1-bit), USB host (`otg-hs`) | works |
| Wi-Fi: mainline `rtl8xxxu` on the RTL8188FU | works: WPA2, DHCP, transfers |
| GPIO (3 banks), LEDs, IR LEDs, IR-cut | works |
| I2C (`i2c-ak39`) | works: JX-F23 answers (id 0x0F23) |
| Video: V4L2 / vb2-dma-contig driver `ak39_vi` + the 4.4 ISP core | works: 1920x1080 NV12, 25 fps, real colours, AE running |
| Audio (`ak39_codec`, `ak_pcm`) | works: microphone captured through ALSA (`hw:0,0`); G.711 A-law track in the RTSP stream (`tc100_rtsp -a 1`); speaker not tested on 6.6 |
| Encoder access (`ak39_venc` + `libakuio`) | works: hardware H.264 / H.265 / JPEG |
| Hardware JPEG (free code, `src/jpegenc`, also inside `tc100_rtsp`) | works (web UI pictures, snapshots) |
| H.264 / H.265 + RTSP (`src/tc100rtsp`) | works: one 1920x1080 stream, 15 fps by default, H.265 or H.264, RTP over TCP or UDP, Digest/Basic login; Frigate reads it; 6 soak runs of 1-2 h survived at 480 MHz. Encoding goes through the vendor control libraries (`libmpi_venc_ex`, `libakv_encode`) on the free driver. 640x360 sub-stream on `video1_unicast` / `ch1` / `sub` (2026-10-26, not yet run on the camera); RTSP over UDP and the audio track not yet checked from a client |
| V3 user space on 6.6 (`v3/`) | works: web UI, ONVIF, recording, MQTT bridge, day / night, motion (Home Assistant entities to be confirmed). Gaps (no web login, Wi-Fi from the UI, IR-cut, 2.x pages): [feature audit](feature-audit-2026-10-26.md) |
| SPI NOR (`spi-ak39`, polled PIO, 4 KiB erase) | works: read and write; `kernel`, `initrd`, `stack`, `cfga`, `cfgb` writable, `boot`, `mac`, `env` read-only |
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
- **Memory (6.6):** kernel at 0x80008000, initrd at 0x81000000, encoder pool 12 MiB at 0x81800000 (`no-map`) with 1 MiB guard zones at 0x81700000 and 0x82400000, CMA capture pool from `cma=18M` on the command line (about 20 MiB at 0x82c00000; the 28 MiB of the device tree do not fit). The 3D-NR reference frame never fits, so 3D-NR is off.
- **SPI NOR layout (6.6, 8 MiB, 4 KiB erase):** `boot` 0x0 (228 KiB, RO), `kernel` 0x39000 (2 MiB), `mac` 0x239000 (4 KiB, RO), `env` 0x23a000 (4 KiB, RO), `initrd` 0x23b000 (2 MiB), `stack` 0x43b000 (3.7 MiB squashfs), `cfga` 0x7ee000 and `cfgb` 0x7f7000 (36 KiB each, settings). `CONFIG_MTD_SPI_NOR_USE_4K_SECTORS=y` is required, otherwise the unaligned partitions are forced read-only.
- **Do not trust the first OpenIPC 4.4 report for pin numbers.** It lists IR LED 5, speaker enable 79, sensor reset 49, reset button 10, taken from the generic device tree; the table above is the verified one. The generic Anyka DTS maps `gpiokeys` to GPIO 84: on the TC100 that freezes the boot (IRQ storm), use `initcall_blacklist=gpio_keys_init`.

## Building the 6.6 kernel

The port is a series of 10 patches on the `v6.6` tag, in `patches/kernel-6.6/series/`:

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

```
git clone --depth 1 -b v6.6 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
cd linux && git am ../patches/kernel-6.6/series/*.patch
cp ../patches/kernel-6.6/defconfig_cma .config && make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- olddefconfig
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- -j$(nproc) zImage dtbs
```

CI (`.github/workflows/build-kernel-linux66.yml`) does this on every push and publishes `oipc.img` (zImage + DTB as a uImage, load and entry 0x80008000) and the `tc100test/` folder in the artifact `tc100-linux66-cma16-kernel`, plus `System.map` and `vmlinux` in `tc100-linux66-symbols` (decode an oops with the symbols of the same run). The RTL8188FU firmware must be in `firmware/rtlwifi/` of the kernel tree (from linux-firmware; `patches/kernel-6.6/firmware/` has a copy). The vendor ISP tuning file `/lib/firmware/anyka/isp.conf` (the stock `isp_f23_mipi2lane.conf`) must be on the root filesystem before streaming.

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
1. Run the vendor `libakv_encode` / `libmpi_venc` on 6.6 through `ak39_venc` and `libakuio`: **done**. `tc100_rtsp`
   loads `libmpi_venc_ex.so` (`ak_venc_open/send_frame/release_stream/close`) with the free `libakuio.so`; each captured
   frame is copied into the encoder pool first (`AK39_VI_G_PHYS` would avoid the copy, not used yet). This is what
   runs on the camera today.
2. Free JPEG (`src/jpegenc`): **done**, valid JFIF from the hardware core; the same code makes the web UI pictures
   inside `tc100_rtsp`.
3. Free H.265 IDR with a fixed QP: the command list generator (`src/h265enc/cmdlist.py`) reproduces the 40 recorded
   frames word for word, **offline only**; not yet driving the hardware. Then P frames and reference management.
4. Remove `libmpi_venc` and `libakv_encode`: not started.

Tracing tool: `libtc100fix` records the vendor encoder's hardware accesses (`VENC_TRACE=/tmp/<name>` in `boot.conf`, then restart `rtsp-h26x` in the background over telnet, never through a 60 s CGI call). The traces are vendor-derived data and stay out of git.

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
  Fallback when the encoder stack is missing: the older `tc100_streamer` (software MJPEG) + `thingino-rtsp-server`
  (JPEG over RTSP, path `/ch0`); neither is in the flash build.
- `v3/linux66-sd/`: glue between the 2.x web UI / scripts and the free stack (`rtsp-h26x` shim, `setconf` shim,
  `rtsp-launch.sh`, `sdinfo-sd.sh`), the flash tools (`build-slim-stack.sh`, `flashw`, `cfg-persist`,
  `flashmode-prep.sh`). Its README lists what is not available on this stack.
- `v3/build-rootfs66.sh [in] [out]`: builds the 6.6 initramfs from our Buildroot base (`v3/buildroot/`, built by CI) (replaces the boot script, drops the 4.4 modules, locks the image's default root password). About 3 MB instead of 6.9 MB. Needs root.

## Test loop (no flash writes, no SD swap)

Build `uImage` = zImage + `ak3918ev300-tc100.dtb` (`mkimage -A arm -O linux -T kernel -C none -a 0x80008000 -e 0x80008000`), copy it to a test folder on the SD card (never at the card root), then from the stock U-Boot prompt: `fatload` the image and the initramfs, `setenv bootargs console=ttySAK0,115200 panic=10 ak_wdt_reboot=300 initrd=0x81000000,<size> rdinit=/sbin/init`, `bootm`. `ak_wdt_reboot=<s>` arms the watchdog once at boot, so a hung test kernel returns to the installed system by itself. **Compare the image checksum on the card before booting:** an empty or truncated image hangs the stock U-Boot. Serial console: 115200 8N1 on the test pads next to the SD slot (a Raspberry Pi Pico 2 running the DebugProbe firmware works as a bridge). Never run the U-Boot download commands, `erase_env` or `format`. **U-Boot truncates `bootargs` at 256 characters**: keep `initrd=0x81000000,<size>` early and check `/proc/cmdline`, otherwise the camera silently falls back to the flash system and looks "up".

Since the flash install the U-Boot `bootcmd` is `run sdload sdboot; run flashboot; run boot_normal`: a card with `tc100test/c66.img` boots the SD kernel first (development and the way back), otherwise the flash system starts. A test kernel on the card therefore still needs no flash write. Flash writes go only through `v3/linux66-sd/flashw` (allow-list, read-back check), after a dump, one partition at a time; `boot`, `mac` and `env` are never written from Linux.

## Linux 4.4: what was needed for frames

Found by comparing register dumps taken while the stock 3.4 firmware was streaming against the 4.4 kernel. The patch is `linux-4.4-isp-video.patch` (4 files against OpenIPC/linux `anyka-tc100-fixes` 5b87a69).

1. **SYSCTRL 0x78 bits 19-24 must be clear.** The device-tree MIPI pin groups are the EV330 ones and set them on EV300; with them set the ISP never gets a frame. `REG32(AK_VA_SYSCTRL + 0x78) &= ~0x01F80000;` after the pinctrl select.
2. **JX-F23 MIPI:** 2 lanes, 768 Mbps, THS-SETTLE = the plain index 9 (D-PHY 0x40/0x60/0x80 = 0x89).
3. **Sensor init:** wait 10 ms after writes to register 0x12 (soft reset), otherwise most of the list is lost.
4. **ISP lifecycle:** `ak_camera` acquires and prepares the ISP core itself, and releases it on close so the next open re-runs the sensor init. The ISP soft reset (SYSCTRL 0x20 bit 19) comes right after the CIS sclk, only when the core is down.
5. **Tuning validator:** the real vendor files are the `4.003` layout (modules 1128 / 38 bytes) with fewer styles stored than the header count; the patch accepts them.

## OpenIPC

[OpenIPC](https://openipc.org) is the reference open firmware for IP cameras; it does not support this camera. What was learnt about it was shared in [OpenIPC/firmware#2639](https://github.com/OpenIPC/firmware/issues/2639) and in [the camera report](https://openipc.org/cameras/report/?id=r-rxh32hs4).

**Findings on the OpenIPC Linux 4.4.302 kernel, in RAM** (`docs/openipc/`, collected over the Pico 2 serial bridge):
`01-system-info.txt` (kernel, command line, cpuinfo, meminfo, mtd, iomem, interrupts), `02-dmesg-full.log` (boot log), `03-gpio-pinctrl.txt`, `04-i2c-sensor-video.txt`, `05-usb-wifi.txt`, `06-audio.txt`, `07-mmc-storage.txt`, `devicetree.dts` (decompiled device tree of the running kernel) and `devicetree.tar.gz`.
- `/dev/video0` appears with the OpenIPC kernel (`ak_camera`, `20000000.isp`, JX-F23 at I2C-0 0x40), with a 24 MiB capture pool at 0x81400000; real frames needed the fixes above.
- The generic `r8188eu` driver binds the RTL8188FU but the radio never locks (0 scan results); the dedicated `8188fu` driver (workflow `build-wifi-driver.yml`, `docs/openipc/8188fu.ko.gz`) works on 4.4. On 6.6 the mainline `rtl8xxxu` does it.
- Audio: ALSA driver `akpcm` registers; speaker amplifier gate on GPIO 14 (the report said 79, see the warning above).

**The SD boot kit** (`contrib/openipc_sd_kit/`, historical, no longer used by the build): `tc100test/oipc.img` (Linux 4.4 uImage), `oipcrd.gz` (musl initramfs, loaded at 0x80900000 so that the ISP's 24 MiB pool at 0x81400000 is not overwritten), `uEnv.txt`, and the tools used over the serial bridge. Its README describes a persistent dual boot written into U-Boot's environment; **for tests the RAM-only loop above is enough and writes nothing**. If you do write the environment, keep the stock `boot_normal` fallback and the SD recovery of the stock U-Boot in mind. No Wi-Fi credentials are in the initramfs: they come from `tc100test/wpa_supplicant.conf` on the card.

## Thingino

`thingino_port/` holds a first Board Support Package for [Thingino](https://github.com/themactep/thingino-firmware): SoC rules (`soc/anyka/ak3918.mk`), Buildroot fragments and a camera config for the TC100 (`configs/`), two Thingino patches (`patches/`: add the Anyka vendor, disable gpio-keys), a known-good 4.4 kernel config (`kernel/`), and packages (`package/thingino-rtsp-server`, `package/thingino-webui`).

- `thingino-rtsp-server` (static ELF, about 80 KB, about 1 MB of RAM): RTSP/1.0 with CSeq tracking, SDP, RTP over TCP interleaved and UDP, RFC 2435 JPEG streams. It is the RTSP server that V3 on 6.6 uses (`v3/autorun-linux66.sh`). Options: `-p port`, `-u user -P password` or `-c config` with `port=`, `username=`, `password=`.
- The Thingino WebUI previews through multipart MJPEG (`cgi-bin/ch0.mjpg`) and JPEG snapshots (`cgi-bin/ch0.jpg`); RTSP paths are `/ch0` and `/ch1`.
- The camera config (`thingino.json`, defconfig) now carries the verified values: GPIO table above (IR LEDs 19, IR-cut 81/80, LEDs 15/47, button 10, speaker 14, not tested), sensor at I2C 0x40, 28 MiB ISP window, 8 MB flash. The boot offsets (`uboot_env_offset`) are still unverified.
- The same RAM-placement rule applies: a root file system loaded inside the ISP pool is wiped during early boot.

## Open items

Done on 2026-10-26 (3.0.1-rc1, not yet run on a camera): web login, Wi-Fi from the UI, one flash writer, the image
built from git with a `vendor` partition and an install from the stock or 2.x firmware without a serial console,
one-click install from the wizard, web updates, sub-stream, MP4 recorder, and every web page on 3.0 (details and what
is hidden: [feature-audit-2026-10-26.md](feature-audit-2026-10-26.md), install: [install-3.0.md](install-3.0.md)).

On the camera, in this order:
1. The stock-firmware hook on a second camera (2.x in flash, no serial console): `tc100-3/STATUS.txt`,
   `camera.txt`, the U-Boot environment written (`env-3.0.txt`), then the start from the card (`flashcheck` with
   `mw.b` / `cmp.b` must fail before the install).
2. Trial mode: web login, wizard, Wi-Fi carried over, video, sub-stream (both encoders in the 12 MiB pool).
3. One-click install, the start from flash, then a web update.
4. IR-cut direction, speaker and amplifier level (device tree `speak-gpios-en`), reset button (GPIO 10 at 1 when
   released), rescue access point, `cfg-persist` deletions across a reboot, the RTSP restarter.
5. Recorder (MP4 + thumbnails), sound level, motion zones; RTSP over UDP, audio in Frigate / VLC, MQTT entities in
   Home Assistant; ISP colour cast (blue is low); day/night thresholds under IR light.

Also: fill `v3/install/known-stock.txt` with the U-Boot and stock root md5 of the author's dump; check the CI run
(`tc100-3-release`); smaller flash image (busybox uClibc, guard zones); encoder: `AK39_VI_G_PHYS` instead of a copy
per frame, free H.265 on the hardware.

## H.265 command list and self-test (2026-10-22)

- `src/h265enc/cmdlist.py` decodes and encodes the 112-word command list of the H.265 encoder and regenerates it: 0 different words over the 40 recorded frames (`python3 src/h265enc/cmdlist.py`).
- `src/h265enc/hwseq.py` models the register write sequence (H.265 clock `v | 0x8e00`) and compares it with the traces: 34/34 and 40/41 cycles.
- Still unknown: where the picture / stream sizes come from. (The physical addresses of the V4L2 buffers are available through `AK39_VI_G_PHYS`, see below.)
- `v3/selftest66.sh`: self-test run at boot when `tc100test/selftest` exists on the card (Wi-Fi, video, audio, uio0; hardware JPEG when `tc100test/selftest-jpeg` exists). Log: `tc100test/selftest-N.log`.
- CI (`build-kernel-linux66.yml`) produces the `tc100test/` folder ready to copy (oipc.img, oipcrd66.gz, jpegenc, libakuio.so, selftest66.sh, README-TEST.txt, md5sums.txt).

## Encoder access without copies (2026-10-22)

- `ak39_vi` has a private ioctl `AK39_VI_G_PHYS` (`include/uapi/linux/ak39_vi.h`): given a buffer index it returns the physical address of the Y and UV planes and the size, so the encoder can read a captured frame in place. It is in patch 0006 of the series. `tc100_rtsp` does not use it yet: it copies each captured frame into the encoder pool (one 3 MB `memcpy` per frame).
- `tests/check_akuio_symbols.py VENDOR_LIB_DIR` checks that every `akuio_*` symbol imported by the vendor libraries (`libmpi_venc`, `libplat_vi`, `libplat_venc_cb`, `libmpi_osd`) is exported by the free `libakuio`: all of them are. A run under qemu was not done: the vendor libraries need uClibc and the free library is built for glibc.
- The old `linux-6.6-ak3918-step*.patch` files are removed; the series in `patches/kernel-6.6/series/` is the only source.

## First boot of the slim 6.6 kernel with the Buildroot base (2026-10-22)

Booted from RAM (U-Boot `bootm`, nothing written to flash) with `oipc.img` (1.8 MB) and the
test initramfs built from `v3/buildroot`:

| Check | Result |
|---|---|
| Kernel, DT, serial console, SD card (FAT), USB host | ok |
| Wi-Fi RTL8188FU (`rtl8xxxu`), WPA2, DHCP (`udhcpc`) | ok, the gateway answers |
| Sensor F23 over MIPI, `/dev/video0` | registered, streamer starts |
| Audio codec (`akpcm`) | card present |
| Encoder access `/dev/uio0` (`ak39_venc`) | ok after the pool fix below |
| Hardware JPEG (`jpegenc --run`) | the core answers (IRQ, length, EOI) but the stream is **not yet valid**: see below |

**RAM budget.** With the 28 MiB CMA pool and the 12 MiB encoder pool only about 15 MB are left for
Linux (`Memory: 16480K/65536K available`). The unpacked initramfs must stay below ~7 MB (a first
8.5 MB image ended in an out-of-memory panic while unpacking), so `v3/initramfs-prune.txt` strips
curl, jq, mbedtls, ncurses, `iw` and friends from the **RAM test image only**; the flash squashfs
keeps them. Do not prune `usr/share/udhcpc` (no DHCP without it) or `usr/share/alsa/alsa.conf`.

**Encoder pool.** The 12 MiB `no-map` region cannot come from `dma_alloc_wc()` (the allocator rounds
the request up to 16 MiB, bigger than the region). `ak39_venc` now `memremap()`s the reserved region
(write-combined) and maps it to user space the same way.

**JPEG: the hardware core now produces valid pictures.** The table block (quantisation, reciprocals,
Huffman words) belongs in the *table buffer*, control word 6 (register 0x3d8), and not at the start of
the output buffer (word 7, 0x3dc) as first assumed. With the block in the wrong place the core read
nothing and fell back to whatever its internal RAM held: a header with junk DQT/DHT bodies and a
40-bit-per-MCU scan (zeroing the block changed nothing, which is how this was found). With the block
at word 6 the core writes a complete, standard JFIF file by itself: the DQT are the quality-35 tables,
the DHT the standard ones, a grey frame gives the textbook `28 a2 8a 00` scan, and a real 1920x1080
frame decodes to the picture (116 KB at quality 35, no software header needed). Free JPEG
encoding on the hardware core works from user space (`src/jpegenc`, `/dev/uio0`).

## tc100_rtsp: sub-stream, sound level, motion zones, recorder (2026-10-26)

Written and tested on the host only (`python3 tests/test_tc100rtsp.py`); not yet run on the camera.

- **Sub-stream:** a second encoder channel, 640x360, same frame rate, fed from the scaled picture that also makes
  `stream.jpg`. Codec and bit rate from `rtspserver.conf` `[1] codec` (0 H.264, 2 H.265) and `[1] bps`; off with
  `RTSP_SUBSTREAM=0` in `boot.conf` (launcher flag `-s 0`). Paths containing `video1` (`video1`, `video1_unicast`) or
  starting with `/ch1` or `/sub` serve it; every other path the main stream. Encoder fields as the vendor server
  (`AnykaCameraManager::getVideoEncodeParams`): channel 1, group 2 (`RTSP_SUB_CHN`, `RTSP_SUB_GROUP` in
  `config/rtsp.env` override). The log shows the pool use after each open; if the sub-stream does not open, or later
  gives no frames, its paths serve the main stream.
- **Sound level:** with `ENABLE=1` in `config/sound_detection.conf`, `/var/run/sound_level` is rewritten 4 times a
  second in the 2.x format `<epoch> <rms_dbfs> <peak_dbfs> <events> <last_event_epoch> <last_event_dbfs>` (RMS and peak
  of the last 0.25 s around the mean; an event per second whose RMS reaches `<file>.threshold`). `arecord` runs only
  while an audio client plays or the sound detection is on.
- **Motion:** on while `/tmp/tc100_md` exists and `mdenabled` is not 0; sensitivity from `/tmp/tc100_md_sens` or
  `mdsens`; the zones of `config/motion_zones.conf` (`MDZ1..4="x1,y1,x2,y2"`, percent) are left out of the 64x36 luma
  grid (2.x `md.c` rule: a cell is ignored when its centre lies in a zone). `/tmp/rec_control` as before;
  `/var/run/md_zones` holds the 2.x status line. The boot starts it only when `mdenabled=1` or
  `config/autostart/motion-detection` exists.
- **Recorder** (`src/tc100rtsp/rec.c`, no ffmpeg): the encoded frames go into fragmented MP4 files (the 2.x writer of `src/tc100fix/rec.c`, one fragment a second: a cut file plays up to its last second)
  `/mnt/DCIM/YYYY-MM-DD_HH-MM-SS.mp4` (the name the Recordings page lists) with a hardware-JPEG thumbnail
  `YYYY-MM-DD_HH-MM-SS.jpg` of the first keyframe next to each. Settings of `boot.conf`, read while running:
  `REC_LOCAL`, `REC_WHEN=offline|always|motion`, `REC_STREAM=main|sub`, `REC_SEGMENT_SEC`, `REC_RESERVE_MB`,
  `REC_OFFLINE_SEC`, `REC_POSTROLL_SEC`, `REC_CLIENT` (else the host of `FRIGATE_URL`). Only into a vfat/exfat card;
  the oldest recordings are deleted to keep `REC_RESERVE_MB` free; `/var/run/tc100rec.pause` (`rec-storage.sh eject`)
  closes the file and leaves the card alone; state in `/var/run/tc100rec`. Card I/O runs in a writer thread so a slow
  card never stalls the capture loop. `controlscripts/recording start|stop` sets `REC_LOCAL`.
