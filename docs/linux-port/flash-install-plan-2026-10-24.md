# Installing the 6.6 system in the SPI flash (plan, 2026-10-24)

Goal: boot without the SD card (SD becomes video storage only), flash keeps a way back.

## Facts checked on the camera
- Flash: XM25QH64A 8 MiB. 6.6 already has the controller driver (`spi-ak39`, polled PIO) and spi-nor, all 6 partitions are visible and **read-only** (`/dev/mtd0..5`): boot 0-0x39000, kernel 0x39000 (2 MiB), mac, env 0x23a000, rootfs 0x23b000 (0x5b3000 = 5.7 MiB, stock A+B+C), tail 0x7ee000 (72 KiB).
- `tail` is entirely 0xFF in the stock image: safe sacrificial area to prove erase + page program + verify from Linux.
- The kernel has squashfs (xz). No jffs2/ubifs/overlayfs: configuration must live elsewhere (see below).
- Current kernel image `c66.img` = 1.89 MiB (fits the 2 MiB kernel partition); initramfs `c66rd.gz` = 1.92 MiB.

## Size budget (measured with mksquashfs -comp xz -b 256K on the real SD stack)
| Set | xz size |
|---|---|
| whole SD stack (www, scripts, bin, lib, tc100_rtsp, httpfront) | 8.3 MiB (too big) |
| minus tc100_streamer, v4l2rtspserver, lighttpd, hostapd, openssl, vendor liveMedia libs | 6.9 MiB |
| to prune further: libbusybox + busybox (initramfs has one), curl/libcurl/libssl/libcrypto (~2 MiB, check who needs them), unused jq/wpa copies | target ≈ 4 MiB |
- Room: kernel partition 2.0 MiB (kernel 1.89) + rootfs region 5.7 MiB. Today's initramfs (1.92) + a 4 MiB squashfs = 5.9 MiB > 5.7: **too tight**. Fix: merge the base rootfs into the squashfs and keep only a tiny initramfs (busybox, mounts the squashfs from mtdblock, switch_root), or let the kernel and rootfs share one region.

## Design
1. Write driver, non-destructive: `boot` and `mac` stay read-only in the device tree for ever (the MTD core refuses writes). Only `tail` first, then `rootfs`; `kernel`/`env` writable only after the tail test and a guard tool (`flashw`: allow-list, refuses anything else, verifies by read-back, md5 printed).
2. Configuration: no jffs2. A/B slots in `tail` (2 × 32 KiB, a gzip tar of `config/`, sequence number + CRC), written only when a setting changes.
3. Boot: U-Boot ENV `bootcmd` keeps the SD hook first (SD with `tc100test/c66.img` boots from SD, today's behaviour), then falls back to `sf read` of kernel + rootfs from flash. So a bad flash never prevents SD boot, and SD removal boots the flash.
4. Safety nets: full 8 MiB dump (stock), ENV backup `env-11-backup-2026-10-24.bin`, UART (Pico), reset-button SD reflash path (confirmed up to the file load), U-Boot never written.

## Steps
1. (this commit) `tail` writable in the device tree; CI builds the kernel. Test from Linux: erase 4 KiB, program 256 B pages, read back, repeat with 64 KiB, check the rest of the flash md5 unchanged.
2. Prune and build the squashfs + tiny initramfs; boot it from RAM first (SD), then from flash partitions via `sf read` in U-Boot (RAM only).
3. Write kernel + rootfs from Linux with `flashw`, power-cycle with and without the SD card.
4. Keep the case open (UART available) for about a week of use; then close it.

## Result of step 1 (2026-10-24, kernel built from a93e985)
- The 72 KiB `tail` was forced read-only by the MTD core because the NOR used 64 KiB erase blocks (partition not 64 KiB aligned). Fix: `CONFIG_MTD_SPI_NOR_USE_4K_SECTORS=y` (erasesize now 4096).
- Flags after the fix: boot/kernel/mac/env/rootfs 0x800 (read-only), tail 0xc00 (writable).
- `flashw tail <file>`: 4 KiB, 64 KiB and 72 KiB random files, erase + write + verify (flashcp) + md5 read-back = OK each time, the camera kept streaming.
- `flashw kernel|boot`: refused by the allow-list; `dd` to /dev/mtd1: permission denied (read-only partition).
- After erasing `tail` again, md5 of mtd0..mtd5 identical to the dump taken before the tests (flash-md5-before/after.txt).
- Next: tiny initramfs + squashfs (build-slim-stack.sh, 3.2 MiB), boot it from RAM, then from flash.

## Update — flash install done and booting (2026-10-24, evening)

Final SPI NOR layout (8 MiB, 4 KiB erase): `boot` 0x0/0x39000 (RO), `kernel` 0x39000/2 MiB, `mac` (RO), `env` 0x23a000/4 KiB (RO), `initrd` 0x23b000/2 MiB, `stack` 0x43b000/0x3b3000, `cfga` 0x7ee000/36 KiB, `cfgb` 0x7f7000/36 KiB.
(`CONFIG_MTD_SPI_NOR_USE_4K_SECTORS=y` is required, otherwise unaligned partitions are forced read-only.)

Written with `flashw` (flashcp + read-back compare + md5), U-Boot, boot and mac never touched:
- `stack` = slim xz squashfs (3.2 MiB, `build-slim-stack.sh`, ships `*.dist` + static config parts); read back md5 = file md5.
- `kernel` = `c66.img` (1,889,091 B), `initrd` = `c66rd.gz` (xz, **dict=2 MiB**, zero-padded to 2,012,654 B so `initrd=0x81000000,2012654` stays exact). A 64 MiB xz dictionary makes the kernel panic ("XZ decompressor ran out of memory").
- Settings: `cfg-persist` A/B slots. Shipped static files (cacert, openssl.cnf, swap header, autostart/0*) are not saved (they live in the squashfs); a slot is ~10 KB. Wi-Fi (`wpa_supplicant.conf`) is part of the saved settings; round trip tested (save → restore into a temp dir → identical). Secrets stay in flash only, never in the repo.
- U-Boot env (only variables added, ENV partition rewritten with the usual setenv/`env export`/`sf erase/write`/`cmp.b` method):
```
flashload=sf probe 0:0 20000000 0; sf read 0x82000000 0x39000 0x1ce000; sf read 0x81000000 0x23b000 0x1ec000
flashboot=run flashload; setenv bootargs console=ttySAK0,115200n8 mem=64M panic=10 ak_wdt_reboot=300 initcall_blacklist=gpio_keys_init oops=panic cma=18M root=/dev/ram0 rdinit=/init initrd=0x81000000,2012654 flashroot=1; bootm 0x82000000
bootcmd=run sdload sdboot; run flashboot; run boot_normal
```
Boot order: SD kernel if `tc100test/c66.img` exists (recovery/dev), else flash. To go back to SD-only boot rename `tc100test/c66.img.sdbak` to `c66.img`.

Findings:
- The kernel only enumerates the SD card when U-Boot initialised it first (what `sdload` does when a card is present). Calling `flashboot` directly from the prompt gives "no SD card" in Linux; through `bootcmd` it works.
- Flash reads/verification of 3 MiB take minutes while the streamer runs (polled PIO SPI); `flashw` is slow but correct. The serial shell is blocked meanwhile.
- No SD console shell in flash mode unless `tc100test/consoleshell` exists on the card (otherwise a getty login).
- Verified: kernel+initramfs+user space from flash, web UI (302), RTSP 554, Wi-Fi from the flash settings, SD kept as video storage.
