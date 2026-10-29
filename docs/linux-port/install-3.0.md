# Installing 3.0 on a TECKIN TC100 (SD card trial, flash install, updates)

Since 2026-10-26 the whole 3.0 firmware is built from git by CI (artifact `tc100-3-release`): an SD card package
`tc100-<version>-sd.zip` and a web update `tc100-<version>-update.tar`. No vendor file is published: the few vendor
libraries 3.0 needs (the uClibc runtime of the stock toolchain and the video encoder control libraries) are copied
from each camera's own stock firmware at install time.

## Flash layout (8 MiB, 4 KiB erase)

| Partition | Offset | Size | Content | Written by |
|---|---|---|---|---|
| `boot` | 0x0 | 228 KiB | U-Boot, partition table | never |
| `kernel` | 0x39000 | 2 MiB | Linux 6.6 uImage | install, update |
| `mac` | 0x239000 | 4 KiB | radio data | never |
| `env` | 0x23a000 | 4 KiB | U-Boot environment | once, from the stock firmware (`envtool`) |
| `initrd` | 0x23b000 | 2 MiB | xz initramfs padded to 2,012,654 bytes | install, update (last) |
| `stack` | 0x43b000 | 2.7 MiB | squashfs of the free user space (`v3/build-stack.sh`) | install, update |
| `vendor` | 0x6ee000 | 1 MiB | squashfs of this camera's vendor libraries | install (made on the camera) |
| `cfga`, `cfgb` | 0x7ee000, 0x7f7000 | 36 KiB each | settings (`cfg-persist`) | at each settings change |

`initrd` + `stack` + `vendor` are exactly the stock partitions A, B and C. `stack` and `vendor` were one 3.7 MiB
`stack` partition until 2026-10-26 (see "Cameras installed by hand" below).

## The four steps

1. **SD card**: unzip `tc100-<version>-sd.zip` to a FAT32 card. It holds the user space as plain files (trial mode
   runs it from the card), `tc100test/c66.img` + `c66rd.gz` (kernel and initramfs, with their md5),
   `wifitest/wifi_test.sh` (the hook below), `tc100-3/` (`envtool`, `stack.sqfs`, `known-stock.txt`).
2. **Stock firmware, once** (`v3/install/stock-hook.sh`, run by the vendor's factory test hook
   `wifitest/wifi_test.sh`): checks the camera (partition table; md5 of the stock `/usr` V1.1.41; md5 of U-Boot and
   of the stock root when `known-stock.txt` lists them; the U-Boot environment reads and has `boot_normal`), saves
   the whole flash to `tc100-3/backup/flash-stock.bin` (read twice), copies the vendor libraries to `lib/` on the
   card (`v3/install/collect-vendor.sh`), then adds to the U-Boot environment (`envtool`, environment saved first,
   written, read back, restored on a difference):
   ```
   sdload=fatload mmc 0 0x82000000 tc100test/c66.img; fatload mmc 0 0x81000000 tc100test/c66rd.gz
   sdboot=setenv bootargs initrd=0x81000000,2012654 console=ttySAK0,115200n8 mem=64M panic=10 ak_wdt_reboot=300 initcall_blacklist=gpio_keys_init oops=panic cma=18M root=/dev/ram0 rdinit=/init; bootm 0x82000000
   flashcheck=sf probe 0:0 20000000 0; sf read 0x81000000 0x23b000 0x1ec000; mw.b 0x80800000 0xfd; … ; cmp.b 0x80800000 0x81000000 6
   flashboot=sf read 0x82000000 0x39000 0x200000; setenv bootargs <same> flashroot=1; bootm 0x82000000
   bootcmd=run sdload sdboot; run flashcheck flashboot; run boot_normal
   ```
   `flashcheck` compares the first 6 bytes of the `initrd` area with the xz magic: the stock flash has a squashfs
   there, so before the install (and after a return to stock) it fails and `boot_normal`, the stock start, runs.
   `run a b` stops at the first command that fails, which this U-Boot already showed with `sdload`.
3. **Trial mode**: U-Boot starts Linux 6.6 from the card; the user space runs from the card with the vendor
   libraries in `lib/`. Nothing of 3.0 is in the flash yet.
4. **Install to flash** (Settings -> Update & backup, `v3/install/install66.sh`): builds `vendor.sqfs` on the card
   from `lib/` (mksquashfs from the Buildroot base), then writes with `flashw` (allow-list, each partition saved to
   `tc100-3/backup` first, md5 checked before and after) `vendor`, `stack`, `kernel` and `initrd` last, copies the
   settings of the card into `cfga`/`cfgb`, renames `tc100test/c66.img` to `c66.img.installed` and restarts.

**Updates** (Settings -> Update & backup, `v3/install/update66.sh`): the package is checked (md5, sizes, xz initrd),
then from a copy in RAM the services stop and `stack`, `kernel`, `initrd` are written; `vendor` and the settings are
kept.

**Way back**: a card with `tc100test/c66.img` always starts first. From the trial mode,
`v3/install/restore-stock.sh` writes the stock kernel and A/B/C back from `flash-stock.bin` and blanks the settings
slots; the 3.0 commands stay in the environment but `flashcheck` then fails, so the stock firmware starts.

## Cameras with the 2.x firmware installed in flash

2.x replaced the stock `/usr` (partition C) after checking it was the V1.1.41 one, and kept the vendor libraries in
it; U-Boot, the kernel, the stock root (A) and the U-Boot environment are untouched. The hook therefore accepts a
`/usr` that is a squashfs with `/usr/tc100/VERSION` (recorded as `usrkind 2.x <version>` in `tc100-3/camera.txt`),
saves the whole flash (the 2.x system: `restore-stock.sh` brings 2.x back), and copies the 2.x settings
(`/etc/jffs2/tc100/config`) and Wi-Fi (`/etc/jffs2/tc100/wpa_supplicant.conf`) to the card, so the trial mode
starts on the same network with the same password. A stock camera's Wi-Fi comes from `/etc/jffs2/anyka_cfg.ini`
(`v3/install/anyka-wifi.awk`).

## Setup wizard and one-click install

`autorun-linux66.sh` opens the wizard on the first 3.0 start (marker `config/.wizard3_done`, so it runs once even
with settings brought over from 2.x). On 3.0 its access step sets the camera password (no HTTPS on busybox httpd,
`WEB_MODE=http`), and in trial mode its last step, "Install into the camera now", starts `install66.sh run` once the
settings are written: one click from the card to the flash. It is offered only when `install66.sh check` passes.

## What the author must still provide

- `v3/install/known-stock.txt` now has the md5 of U-Boot and of the stock root of the author's stock dump
  (2026-10-11); other firmware versions get their own lines from the inventories sent in issues. The hardware itself
  is checked against the board profiles: [hardware variants](../hardware-variants.md).
- A first run of the hook on a stock camera, with the serial console connected, to confirm that the stock kernel
  lets `envtool` write `/dev/mtd3`, and that the stock U-Boot runs `flashcheck` (`mw.b`, `cmp.b`) as expected.

## Cameras installed by hand on 2026-10-24 (the author's)

They have a single 3.7 MiB `stack` with the vendor libraries inside and U-Boot commands `flashload`/`flashboot`
typed by hand (`flashload` reads 0x1ce000 bytes of the kernel: CI warns when the kernel grows past that). To move to
the new layout without touching the environment:

1. Copy the new SD package to the card, keeping the card's `lib/` (it holds the vendor libraries). Make sure
   `tc100test/c66.img` is the new kernel (it has the `vendor` partition).
2. Power on: the card starts first (trial mode, new kernel).
3. Settings -> Update & backup -> Install to flash. `vendor.sqfs` is made from the card's `lib/`.
4. The hand-made `flashboot` keeps working: same `initrd` size, kernel under 0x1ce000.
