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
- **Vendor, in CI:** the vendor image is made on each camera, so CI builds a stand-in the same way (mksquashfs, xz,
  256 KiB blocks) from a worst-case `isp.conf` of 64 KiB (five times the measured size) and runs
  `flash_budget.py --vendor` on it (`tests/ci-vendor-budget.sh`, step "Flash budget gate" of the kernel job, which also
  checks `--initrd` and `--stack`). `VENDOR_MAX` of `v3/install/install66.sh` is tested against the partition size.
- **Vendor and settings:** not in the image. `vendor` is made on each camera at install (`v3/install/`), and the
  settings slots are written through `v3/linux66-sd/cfg-persist` (the flash writer `flashw` does the partition writes).

## Rules that stay

- Nothing is written to `boot`, `mac` or `env`; the U-Boot environment is never written by the 3.0 system (the one
  sanctioned exception is described in [AGENTS.md](../../AGENTS.md), the first-install hook).
- A kernel that does not fit is refused before flashing: a kernel that fails to boot cannot be recovered from Linux,
  because U-Boot always loads `mtd1` (see AGENTS.md, "Unattended recovery").
- A/B slots do not fit in 8 MiB with two roots: updates are single-slot, staged from the SD card, with the reset-button
  reinstall as recovery.

## Hardening of the free programs (measured 2026-11-23, `[harden]`)

Audit 2026-11-16: the C programs were built with `-fno-stack-protector -U_FORTIFY_SOURCE` (a reason of the uClibc
stand-in era) and without `-z now`. Measured in Docker (`debian:bookworm`, `arm-linux-gnueabi-gcc` 12.2, musl 1.2.4 of
`v3/musl/build-musl.sh`, the build commands of CI), stripped as shipped. Each cell is raw bytes / xz bytes (xz preset 6
with the ARM branch filter, as `mksquashfs -comp xz -Xbcj arm`); the deltas are against the build of `0f827ec`.

| Program | before | stack protector | `-z relro,-z now` | both (enabled) | PIE (not enabled) |
|---|---|---|---|---|---|
| `tc100_rtsp` | 190,100 / 80,632 | +4,096 / +1,511 | -488 / +1 | +3,608 / +1,514 | +16,436 / +5,366 |
| `tc100-onvifd` | 50,564 / 19,263 | +4 / +308 | -232 / -8 | -232 / +305 | +4,148 / +1,278 |
| `tc100-mqttd` | 34,148 / 12,273 | +4,100 / +269 | -244 / -8 | +3,852 / +258 | +4,148 / +686 |
| `tc100-supervisord` | 30,232 / 12,988 | +4,104 / +507 | -208 / +3 | +3,888 / +507 | +4,148 / +807 |
| `tc100-logfwd` | 9,576 / 4,229 | +4 / +157 | -176 / +10 | +3,920 / +185 | +4,148 / +27 |
| `rwconf` | 9,448 / 2,978 | +4 / +71 | -164 / +21 | -164 / +83 | 0 / -91 |
| `libnetacl-musl.so` | 9,360 / 2,634 | +8 / +185 | -120 / +7 | -120 / +203 | n/a |
| `httpfront` | 41,436 / 21,792 | +804 / +690 | n/a | +804 / +690 | n/a |
| `tc100-mdnsd` | 7,232 / 4,130 | +544 / +246 | n/a | +544 / +246 | n/a |
| `isp_flip` | 940 / 546 | +380 / +216 | n/a | +380 / +216 | n/a |
| **Total** | 383,036 / 161,465 | +14,048 / +4,160 | -1,608 / +32 | **+16,480 / +4,207** | +33,052 / +8,079 |
| **squashfs of the ten files** | 157,421 | +3,708 | +28 | **+3,772** | +8,272 |

The raw jumps of about 4 KiB are page alignment padding (zeros), which xz removes. **Cost of what is enabled: +3.7 KB
in the image.** The `stack` partition is 2,830,336 bytes; the newest `stack.sqfs` sizes written in the repository are
2,146,304 bytes (2026-11-06, after the S1-S7 cuts) and 2,424,832 bytes (2026-11-05, before them). Even at the larger
figure 405,504 bytes are free: the hardening takes 0.9 % of that, one 4 KiB squashfs block at most. The CI line
`stack.sqfs: N bytes` of the `[harden]` build gives the real figure.

What each flag gives here:

- **`-fstack-protector-strong` (enabled).** A canary in every function with a local array or an address-taken local
  (105 functions in `tc100_rtsp`, 2 to 27 in the daemons). ARM GCC reads the canary from the global
  `__stack_chk_guard` (ARMv5 has no thread register; `-mstack-protector-guard=global` is the default), not from the
  thread pointer. musl 1.2.4 exports `__stack_chk_guard` and `__stack_chk_fail`, and its loader fills the guard from
  `AT_RANDOM` before the program's copy relocation is made: checked under qemu with the real musl loader, the guard
  changes at every run and an overflow kills the process. musl's `__stack_chk_fail` prints nothing and ends in
  `SIGILL` (`a_crash`). The freestanding programs (no C library) define both names in `src/ssp-freestanding.h`: their
  `_start` takes the guard from `AT_RANDOM` (lowest byte zero, as glibc) before `run()`, and a smashed stack writes
  `*** stack smashing detected ***` to stderr and ends in `SIGABRT`. The standalone `jpegenc` binary (static glibc, test pack only) was removed from the test pack on 2026-11-25.
- **`-Wl,-z,relro,-z,now` (enabled).** Our programs are dynamic musl programs, not static ones (only the three
  freestanding programs are static, and they have no GOT, no `.dynamic` and no RELRO segment, so the flag is not
  given to them). Debian's and Ubuntu's `ld` already default to `-z relro`, but that RELRO covered only
  `.init_array`, `.fini_array` and `.dynamic`: the GOT stayed writable. `-z now` moves `.got` into `GNU_RELRO`, which
  the musl loader makes read-only once relocation is done (full RELRO; under qemu a write to the GOT then faults). musl
  never binds lazily, so `-z now` changes no behaviour at start.
- **`-D_FORTIFY_SOURCE=2` (not enabled).** musl has no fortified headers and the base system has no fortify-headers
  package: with musl the flag changes nothing (the ten binaries are byte-identical with and without it). It stays
  `-U_FORTIFY_SOURCE`.
- **PIE / static-pie (not enabled).** musl 1.2.4 supports both (`rcrt1.o` is installed; a `-static-pie` test program
  ran under qemu with a random canary). For our dynamic programs PIE costs +8.3 KB xz and makes the ARM926 code reach
  every global through the GOT (slower in the encoder and RTP paths); the freestanding programs would need a
  self-relocating `_start`. Left for a later decision.

**Switch:** `HARDEN=0` (make argument or environment; `src/musl.mk`, the freestanding builds of
`.github/workflows/build-kernel-linux66.yml` and `tests/docker/local-ci.sh`, the CI input `harden`) builds as before.
Tests: `tests/test_harden.py` (wiring, and the canary and RELRO checked in ARM builds under qemu),
`tests/test_musl_programs_qemu.py` (every shipped musl program imports `__stack_chk_fail` and is `BIND_NOW`).
Camera entry: `HARDEN` in [test-queue.md](test-queue.md).
