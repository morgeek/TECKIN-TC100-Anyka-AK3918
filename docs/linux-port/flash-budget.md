# Flash budget of the Linux 6.6 firmware

Checked against the code on 2026-11-16. The 2026-10-22 layout (one root partition A+B+C, a `--rootfs` option) and its
measurements are gone: the figures of that day are in [history.md](history.md).

Flash: 8 MiB SPI NOR (XM25QH64A, 4 KiB sectors). The partitions are those of the device tree
(`patches/kernel-6.6/series/0010-spi-*.patch`); `tests/test_flash_budget.py` checks that the script and the patch agree.
The layout is described in [internals.md](internals.md) ("Flash layout of 3.0") and [install-3.0.md](install-3.0.md).

| Partition | Offset | Size | Written by |
|---|---|---|---|
| `boot` (U-Boot, table) | 0x000000 | 228 KiB | never |
| `kernel` | 0x039000 | 2 MiB | install, update (uImage, `oipc.img`) |
| `mac`, `env` | 0x239000, 0x23a000 | 4 KiB each | never |
| `initrd` | 0x23b000 | 2 MiB | install, update |
| `stack` | 0x43b000 | 2.7 MiB (0x2b3000) | install, update (squashfs of the free user space) |
| `vendor` | 0x6ee000 | 1 MiB | install, made on the camera (sensor tuning `isp.conf`, about 12 KB) |
| `cfga`, `cfgb` | 0x7ee000, 0x7f7000 | 36 KiB each | settings slots |

## The check

`scripts/flash_budget.py [--kernel FILE] [--initrd FILE] [--stack FILE] [--vendor FILE] [--json]` checks each file
against its partition (sizes rounded up to 4 KiB; the 64-byte uImage header is counted for the kernel) and exits 1
when one does not fit. A file larger than its partition would overwrite the next one, and the stock update path has
no size check of its own, so the check runs before any image goes on a card or into the flash.

The gates that run it or repeat its limits:

- **Kernel, in CI:** `.github/workflows/build-kernel-linux66.yml` (about lines 151-155) runs
  `python3 scripts/flash_budget.py --kernel output/oipc.img`, which fails the build above 2 MiB. It also warns above
  1,892,352 bytes (0x1ce000), the length that the first hand-made flashload of 2026-10-24 read.
- **Release package:** `v3/build-release.sh` (lines 12-15) sets `KERNEL_MAX=2097152` and `INITRD_SIZE=2012654` and
  refuses a kernel that does not fit the kernel partition.
- **Stack:** `v3/build-stack.sh` (`STACK_MAX=2830336`, lines 20 and 174) refuses a `stack.sqfs` larger than the
  `stack` partition.
- **Vendor and settings:** not in the image. `vendor` is made on each camera at install (`v3/install/`), and the
  settings slots are written through `v3/linux66-sd/cfg-persist` (the flash writer `flashw` does the partition writes).

## Rules that stay

- Nothing is written to `boot`, `mac` or `env`; the U-Boot environment is never written by the 3.0 system (the one
  sanctioned exception is described in [AGENTS.md](../../AGENTS.md), the first-install hook).
- A kernel that does not fit is refused before flashing: a kernel that fails to boot cannot be recovered from Linux,
  because U-Boot always loads `mtd1` (see AGENTS.md, "Unattended recovery").
- A/B slots do not fit in 8 MiB with two roots: updates are single-slot, staged from the SD card, with the reset-button
  reinstall as recovery.
