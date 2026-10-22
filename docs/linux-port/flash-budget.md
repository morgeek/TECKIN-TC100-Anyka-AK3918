# Flash budget of the Linux 6.6 firmware (2026-10-22)

Flash: 8 MiB SPI NOR (XM25QH64A, 4 KiB sectors). Layout from the stock partition table (flash 0x37000):

| Region | Offset | Size | Used by 6.6 |
|---|---|---|---|
| U-Boot + table | 0x000000 | 228 KiB | never written |
| KERNEL | 0x039000 | 2 MiB | kernel (uImage) |
| MAC | 0x239000 | 4 KiB | never written |
| ENV | 0x23a000 | 4 KiB | never written |
| A + B + C | 0x23b000 | 5.70 MiB (0x5b3000) | root filesystem (squashfs xz) |
| tail | 0x7ee000 | 72 KiB | never written |

`scripts/flash_budget.py [--kernel FILE] [--rootfs FILE]` checks a file against its region (sizes rounded up to sectors, 64 bytes of uImage header counted) and exits 1 if it does not fit. The stock SD update path has no size check, so this must run before any image goes on a card.

## Measured (2026-10-22)

| Item | Size |
|---|---|
| Test kernel (large config, xz) | 2,368,840 B: **does not fit** the 2 MiB KERNEL region |
| Root filesystem `v3/build-flash-rootfs66.sh` (OpenIPC base pruned by `v3/rootfs-prune.txt` + V3 web UI, scripts, `tc100_streamer`, `thingino-rtsp-server`; squashfs xz 128 KiB) | 2,646,016 B of 5,976,064 B: **3.3 MB free** |
| Slim kernel (no ext4, IPv6, ftrace, swap, VT, KALLSYMS, namespaces, debugfs; squashfs xz + RAM disk added), `defconfig_cma` | 1,842,992 B zImage: **fits, 248 KB free** (first slim pass, with KALLSYMS: 2,048,344 B, 44 KB free) |

The vendor media libraries (`libakv_encode`, `libmpi_venc`, ...; about 0.85 MB, about 0.35 MB compressed) are not in the image: the V4L2 + free encoder path does not use them.

## What the figures do not cover

- **The 6.6 kernel cannot read the flash yet.** It has no Anyka SPI controller driver and no MTD in the device tree. Two ways to deliver the root filesystem: (a) port the SPI driver from the 4.4 tree and describe the partitions in the DT, then `root=/dev/mtdblockN rootfstype=squashfs` (no U-Boot change; the stock command line already says `root=/dev/mtdblock4 rootfstype=squashfs`); (b) have U-Boot load the squashfs from flash to RAM and pass it as initrd (needs a change of the `bootcmd` in ENV, which means `saveenv`; not done so far). (a) is preferred.
- **A/B update does not fit** (two roots would need 5.3 MB plus the kernel). Updates stay single-slot: stage on the SD card, write from RAM, keep the reset-button reinstall as recovery. That reinstall writes fixed partition sizes (A 1.5 MiB, B 500 KiB, C 3.7 MiB); a 2.6 MB root only fits if written by Linux (`flashcp`) or by changing the table.
- **RAM:** with the root as squashfs on MTD, RAM is not used for the file contents. With an initrd (b) the compressed image sits in RAM (2.6 MB).
- Writable state (Wi-Fi, passwords, logs, recordings) stays on the SD card.

The slim kernel was compiled but not booted. Without KALLSYMS an oops shows addresses only; resolve them with `System.map` from the CI build. CI now refuses a kernel that does not fit the region (`scripts/flash_budget.py --kernel output/oipc.img`).
