# OpenIPC Linux 4.4 SD Boot Kit for TECKIN TC100 (Anyka AK3918EV300)

This directory contains the fully validated, working **OpenIPC (Linux 4.4.302 + Musl userspace)** images and dual-boot scripts for the **TECKIN TC100** camera.

## Hardware Support
- **SoC**: Anyka AK3918EV300 (ARM926EJ-S rev 5, ARMv5TEJ)
- **Sensor**: SOI JX-F23 (`0xf23`)
- **RAM**: 64 MiB DDR2
- **Storage**: MicroSD (FAT32)
- **Wi-Fi**: Realtek RTL8188FU / RTL8188FTV (USB high-speed)
- **Bootloader**: Stock U-Boot `2013.10.0-AK_V3.0.05`

---

## Zero-Brick Dual-Boot Architecture

The camera uses a non-destructive dual-boot configuration stored in U-Boot environment partition (`0x23a000` on SPI flash):
- **When MicroSD is inserted**: U-Boot automatically loads Linux 4.4 (`oipc.img`) and OpenIPC initramfs (`oipcrd.gz`) into RAM.
- **When MicroSD is removed**: U-Boot falls back instantly to `boot_normal` and runs the internal flash firmware (`TC100 V3 ULTIME`).
- **Safety**: The SPI NOR bootloader (`0x0 - 0x39000`) is never touched.

---

## Memory Map

- `0x80008000`: Linux 4.4 Kernel load address
- `0x80900000`: OpenIPC Initramfs rootfs (`oipcrd.gz`, ~4.4 MB)
- `0x81400000 - 0x82c00000`: Reserved DMA memory pool (24 MiB) for Anyka ISP / video buffers
- `0x82000000`: Kernel temporary load buffer for U-Boot `bootm`

---

## Quick Setup Instructions

1. Format a MicroSD card as **FAT32** (MBR).
2. Copy the folder `tc100test` containing `oipc.img` and `oipcrd.gz` to the root of the SD card.
3. In U-Boot, configure the dual-boot variables:
   ```text
   setenv sdload 'fatload mmc 0 0x82000000 tc100test/oipc.img; fatload mmc 0 0x80900000 tc100test/oipcrd.gz'
   setenv sdboot 'setenv bootargs console=ttySAK0,115200n8 mem=64M root=/dev/ram0 rdinit=/init initrd=0x80900000,6921241 mtdparts=spi0.0:8192k(all)ro initcall_blacklist=gpio_keys_init panic=10 loglevel=7; bootm 0x82000000'
   setenv bootcmd 'run sdload sdboot; run boot_normal'
   ```
4. Save to flash:
   ```text
   mw.b 0x83000000 0 0x1000
   mw.l 0x83000000 ffffffff 1
   env export -b -s 0xff8 0x83000008
   crc32 0x83000008 0xff8 0x83000004
   sf probe 0:0 20000000 0
   sf erase 0x23a000 0x1000
   sf write 0x83000000 0x23a000 0x1000
   ```
5. Reboot with `reset`. The camera will boot OpenIPC and connect to your Wi-Fi automatically.
   - Web Interface: `http://<camera-ip>`
   - SSH (Dropbear): `ssh root@<camera-ip>` (port 22)
