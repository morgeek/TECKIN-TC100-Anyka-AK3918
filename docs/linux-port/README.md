# Linux for the TC100 (AK3918EV300): video on 4.4 and a 6.6 port

Research notes and patches, 2026-10-21. Nothing here is part of a firmware release: it was all tested from RAM (kernel loaded from the SD card by the stock U-Boot), with the flash untouched. The goal is a free firmware on a recent kernel, with the V3 web interface, H.264 and H.265.

## Files

| File | What it is |
|---|---|
| `linux-4.4-isp-video.patch` | 4 files against OpenIPC/linux `anyka-tc100-fixes` (5b87a69): real video from the JX-F23 on 4.4 (soc_camera `ak_camera` + ISP2) |
| `linux-6.6-ak3918.patch` | one patch (74 files, `git apply`-checked) against the **v6.6** tag: `ARCH_ANYKA`, the drivers listed below and the board device tree |
| `linux-6.6-ak3918.config` | kernel config used for the tests (ARM, no modules needed for the board) |

The 6.6 config embeds `rtlwifi/rtl8188fufw.bin` (21,020 bytes, from linux-firmware, not included here): put it in `firmware/rtlwifi/` of the kernel tree before building. The vendor ISP tuning file `/lib/firmware/anyka/isp.conf` (the stock `isp_f23_mipi2lane.conf`) must be on the root filesystem before streaming.

## Linux 4.4: what was needed for frames

Found by comparing register dumps taken while the stock 3.4 firmware was streaming against the 4.4 kernel.

1. **SYSCTRL 0x78 bits 19-24 must be clear.** The device-tree MIPI pin groups are the EV330 ones and set them on EV300; with them set the ISP never gets a frame. `REG32(AK_VA_SYSCTRL + 0x78) &= ~0x01F80000;` after the pinctrl select.
2. **JX-F23 MIPI:** 2 lanes, 768 Mbps, THS-SETTLE = the plain index 9 (D-PHY 0x40/0x60/0x80 = 0x89).
3. **Sensor init:** wait 10 ms after writes to register 0x12 (soft reset), otherwise most of the list is lost.
4. **ISP lifecycle:** `ak_camera` acquires and prepares the ISP core itself, and releases it on close so the next open re-runs the sensor init. The ISP soft reset (SYSCTRL 0x20 bit 19) comes right after the CIS sclk, only when the core is down.
5. **Tuning validator:** the real vendor files are the `4.003` layout (modules 1128 / 38 bytes) with fewer styles stored than the header count; the patch accepts them.

## Linux 6.6 port: state

| Area | State |
|---|---|
| CPU, interrupt controller, timer, console (TX polled, RX interrupt-driven) | works |
| Restart (top watchdog), `/dev/watchdog` | works |
| L2 buffer engine, SD card (`akmci`, 1-bit), USB host (`otg-hs`) | works |
| Wi-Fi: mainline `rtl8xxxu` on the RTL8188FU | works: WPA2, DHCP, transfers |
| GPIO (3 banks), LEDs, IR LEDs, IR-cut | works |
| I2C (`i2c-ak39`) | works: JX-F23 answers (id 0x0F23) |
| Video: new V4L2 / vb2-dma-contig driver `ak39_vi` + the 4.4 ISP core | works: 1920x1080 NV12, 25 fps, real colours, AE running; open / stream / close repeats |
| H.264 / H.265 encoder | not done (Allegro DVT core, see `h265-free-encoder-plan` notes) |
| Audio, SPI NOR, root filesystem for the V3 firmware | not done |

## Hardware facts (verified on the board)

- **Core PLL, SYSCTRL 0x08.** U-Boot leaves 0x010213c8 (400 MHz, ASIC 100 MHz); the ISP then receives no lines. The 4.4 kernel runs 0x010203a0 (640 MHz, ASIC 160 MHz). Change: write the value with bit 23 set, then SYSCTRL 0x04 |= bit 28. The UART divisor is ASIC / baud - 1 (bit 22 when there is a remainder) and must be reprogrammed with it. Field layout: m bits 0-7, n 8-11, od 12-13, vclk shift 17-19; PLL = 12·m / (n·2^od) MHz, vclk = PLL >> shift, ASIC = vclk / 2.
- **Clock gates** SYSCTRL 0x1C (1 = gated), soft resets 0x20 with the same bits: mmc0 1, uart0 7, l2 9, i2c0 10, gpio 12, usb-otg 15, mipi 16, camera/ISP 19.
- **GPIO** (stock 3.4 board table, then checked on the board for everything but the speaker): IR LEDs 19, IR-cut A 81 / B 80 (pulse 150 ms, then both low), red LED 47, blue LED 15, reset button 10 (active low), speaker amplifier 14 (not tested). Registers at 0x20170000: DIR +0x00 (1 = output), OUT +0x0c, IN +0x18, one word per 32 pins. In 6.6 the chips are numbered 512, 544, 576.
- **L2 buffer engine** is shared by the UART rings, MMC, USB and SPI. Its init must not rewrite `rL2_CONBUF8_15`, or the UART RX dies. UART RX is a 128-byte ring at the TX buffer + 0x80; the write position is in DATA_CONF bits 13-19.
- **Watchdog restart:** SYSCTRL +0xE4 = (0x55 << 24) | ticks, then +0xE8 = (0xAA << 24) | 1, then | 3. 46875 ticks/s, about 357 s at most. A watchdog armed by the boot environment must not be reported to the core as hardware-running, or the core keeps feeding it.
- **RTL8188FU over the Anyka USB host:** the firmware download needs 64-byte EP0 writes (`writeN_block_size = 64` for the 8188f) and a few retries in `rtl8xxxu_writeN`.
- **Sensor pads / I2C:** OR 0x40000710 into SYSCTRL 0x74, 0x01450525 into 0x7c and 0x100 into 0x80 (the 4.4 values), keep 0x78 bits 19-24 clear.
- **Memory:** the capture pool is a device-tree reserved region (28 MB at 0x82400000), so the initramfs is loaded at 0x81000000.

## Test loop (no flash writes, no SD swap)

Build `uImage` = zImage + `ak3918ev300-tc100.dtb` (`mkimage -a/-e 0x80008000`), copy it to a test folder on the SD card (never at the card root), then from the stock U-Boot prompt: `fatload` the image and the initramfs, `setenv bootargs console=ttySAK0,115200 panic=10 ak_wdt_reboot=300 initrd=0x81000000,<size> rdinit=/sbin/init`, `bootm`. `ak_wdt_reboot=<s>` arms the watchdog once at boot, so a hung test kernel returns to the installed system by itself. Compare the image checksum on the card before booting: an empty or truncated image hangs the stock U-Boot.

## Applying

```
git clone --depth 1 --branch v6.6 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
cd linux && git apply ../teckin-tc100-anyka-ak3918/docs/linux-port/linux-6.6-ak3918.patch
cp ../teckin-tc100-anyka-ak3918/docs/linux-port/linux-6.6-ak3918.config .config
```

The source files in `drivers/media/platform/anyka-isp`, `drivers/usb/host/anyka`, `drivers/mmc/host/akmci*` and the headers under `include/plat-anyka` derive from the vendor's GPL kernel sources (via OpenIPC/linux); they keep their original copyright headers.
