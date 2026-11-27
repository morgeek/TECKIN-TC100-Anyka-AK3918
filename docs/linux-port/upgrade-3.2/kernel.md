# Stream `[up-kernel]`: kernel 6.6.0 to 6.6.163 (phase 4 of the upgrade plan)

Written 2026-11-27. Scope: only the kernel version changes. The 25 patches of `patches/kernel-6.6/series/` are rebased
on the latest 6.6.y, nothing else in the kernel is changed on purpose (no new option, no trimmed option).

## Target

| | |
|---|---|
| Tag | `v6.6.163` (kernel.org `releases.json` on 2026-11-27: 6.6.163 is the newest 6.6.y) |
| Commit | `e2bb30811e063ce0db964484357973b855b06572` (the tag is annotated: object `a5587be2...`, peeled commit above) |
| Pinned in | `.github/ci-pins.sh` (`LINUX_TAG`, `LINUX_COMMIT`) |
| Sources | `LINUX_URLS`: `git.kernel.org/.../stable/linux.git`, then `github.com/gregkh/linux.git` (the torvalds mirror has no 6.6.y tags; both mirrors were checked to carry `v6.6.163` at the pinned commit) |
| Switch back | none needed at run time; to go back, pin `v6.6` / `ffc253263a1375a65fa6c9f62a893e9767fbebfa` and use the patch files of commit `37474bb` |

The series had 25 patch files (the "26" counted `README.md`).

## What was done

1. Full clone of the stable tree, series applied with `git am` on `v6.6` (all 25 apply, as before), then
   `git rebase --onto v6.6.163 v6.6`.
2. One conflict in the whole series. Everything else merged without fuzz problems (only index hashes and line offsets
   changed).
3. `git format-patch -N --no-signature v6.6.163..HEAD`, copied over the existing files: same numbers, same file names,
   same authors, dates and commit messages (the `[PATCH n/9]` counters in the old subjects are now plain `[PATCH]`).
   `git apply --stat` passes on all 25 files; patches that add whole files carry correct hunk counts because
   `format-patch` computes them.

## Patch by patch

| Patch | Result |
|---|---|
| 0001 to 0003, 0005 to 0017, 0021 to 0025 | applied cleanly (offsets only). These add or touch files that stable did not change (Anyka code, the dts, the Makefiles and Kconfigs only as one-line additions). |
| 0004 `wifi: rtl8xxxu: AK3918 fixes ... (64-byte writes)` | **conflict** in `rtl8xxxu_core.c`, `rtl8xxxu_writeN()` error path. Stable 6.6.y has gated the "Failed to write block" message behind `rtl8xxxu_debug & RTL8XXXU_DEBUG_REG_WRITE`; the patch makes it unconditional and adds the `ret` value (the camera logs showed it was needed to diagnose the 64-byte write failures). Resolved by keeping the patch's version (unconditional message with `ret`), i.e. the behaviour of the 6.6.0 image. |
| 0018, 0019, 0020, 0023 (rtl8xxxu parameters and counters) | applied cleanly. Stable touched the same driver in ten commits (retry of the firmware download, RX skb size without aggregation, use-after-free on stop, `cancel_work_sync` for `c2hcmd_work`, MFP flag, 8188F TX power limit, ...). None of them overlaps the parameters or counters of these patches. |

No patch is dropped: none of the Anyka-specific fixes has an equivalent in stable.

### Stable changes that alter behaviour on the camera (for the camera test)

- `wifi: rtl8xxxu: 8188f: Limit TX power index`: an efuse TX power index above 0x3F (uncalibrated chip, 0xFF) is replaced
  by a default (0x22 CCK, 0x27 HT40). Can only lower a bogus value; `tx_atten` (patch 0019) works on top.
- `wifi: rtl8xxxu: retry firmware download on error`, `fix use-after-free from rx_urb_wq on stop`, `free RX skb when
  URB submission fails`, `Fix RX skb size for aggregation disabled`: the Wi-Fi path the camera uses most; watch the
  Wi-Fi counters (`/sys/module/rtl8xxxu/parameters/`) and the RX freezes of `docs/known-issues.md`.
- Build-time only: `arch/arm` stable fixes, CPU mitigations option (below).

## Configuration (`patches/kernel-6.6/defconfig_cma`)

`olddefconfig` run on both trees with the same compiler (Debian 12 `arm-linux-gnueabi-gcc` 12.2), 6.6.0 versus 6.6.163,
from the same `defconfig_cma`. `defconfig_cma` itself is **left as it is** (header still says 6.6.0): the CI runs
`olddefconfig` on it, and regenerating it here would only add compiler-text noise (Ubuntu gcc 13 of the old file versus
Debian gcc 12 of the local container). No option was changed on purpose; every difference comes from the new tree:

| Symbol | Change | Why it is fine |
|---|---|---|
| `GCC_ASM_GOTO_OUTPUT_WORKAROUND=y` | added | hidden compiler-bug switch, backported by stable |
| `GCC11_NO_ARRAY_BOUNDS` -> `GCC10_NO_ARRAY_BOUNDS` | renamed | same switch, renamed by a stable backport; only a warning flag |
| `CPU_MITIGATIONS=y` | added | new umbrella option (default y) for CPU vulnerability mitigations; on ARM it only gates generic code |
| `PCP_BATCH_SCALE_MAX=5` | added | new tunable with its default, per-CPU page lists |
| `PROC_MEM_ALWAYS_FORCE=y` (+ two "not set" siblings) | added | the new choice defaults to the old behaviour of `/proc/pid/mem` writes |
| `CRYPTO_SIG=y`, `CRYPTO_SIG2=y` | added | hidden, selected by the crypto core of the newer tree |
| `ARCH_HAS_DMA_ALLOC=y` | added | hidden architecture fact for non-MMU/uncached DMA, unchanged use |
| `FORCE_NR_CPUS=y` | added | hidden, `def_bool !SMP` (our uniprocessor build) |
| `ARM_TIMER_SP804` | now listed "is not set" | already off; becomes a visible prompt |
| `UNIX_SCM` | removed | now internal to `UNIX` |
| `MAC80211_MESSAGE_TRACING`, `HVC_DCC`, `MFD_TI_AM335X_TSCADC`, `NTFS_FS`, `WARN_ALL_UNSEEDED_RANDOM`, `DEBUG_CREDENTIALS` | removed (all were "is not set") | options no longer exist in 6.6.y (removed or merged by stable); nothing was enabled |

Not one option the camera depends on (CMA, ALSA, ZRAM, SQUASHFS, USB host, the Anyka drivers) changed.

## Build

- `sh tests/docker/local-ci.sh kernel`: zImage and the Anyka dtb build, `kernel: ok`. 12 warnings in total, all in
  vendor-derived Anyka code (`ak_pcm.c` unused function, `ak39_isp2*.h/.c` macro redefinitions, misleading indentation,
  frame sizes over 1024 bytes, `akmci-of.c` unused label, `ak_isp_char.c` function-type casts, `sensor_f22...c`). None
  is in a file touched by 6.6.y; no warning outside Anyka code. A full warning baseline of 6.6.0 was not rebuilt.
- The 6.6.0 `zImage` found in the Docker volume (build of 2026-11-16) is 1 784 672 bytes.

### Image sizes (the way the CI makes `oipc.img`: `zImage` + tc100 dtb, `mkimage`)

| | Bytes |
|---|---|
| `arch/arm/boot/zImage` | 1 809 704 |
| `ak3918ev300-tc100.dtb` | 4 784 |
| `oipc.img` (uImage) | **1 814 552** |
| Kernel slot | 2 097 152 (2 MiB) |
| `scripts/flash_budget.py --kernel oipc.img` | OK, 1 818 624 in sectors, **278 528 free** |
| Limit of the hand-made first `flashload` (0x1ce000 = 1 892 352) | respected (77 800 spare) |

zImage grew by about 25 KB against the 2026-11-16 build of 6.6.0. The 2026-11-06 audit's "about 110 KB free" was a
different measurement; the number that counts here is the gate output above. No config trim was needed.

## Files changed outside the series

`.github/ci-pins.sh` (tag, commit, `gregkh/linux` mirror), `.github/workflows/build-kernel-linux66.yml` (step name only:
the clone already uses `$LINUX_TAG`), `scripts/build-kernel-docker.sh` (message), `tests/docker/local-ci.sh`
(`run_kernel`: directory `/k/linux-$LINUX_TAG`, `git reset --hard "$LINUX_COMMIT"`; the old `/k/v6.6` content of the
Docker volume is not used any more and can be removed with `docker volume rm tc100-linux66`), `tests/test_ci_pinning.py`
(new test `test_kernel_base_is_a_stable_release`), `docs/linux-port/README.md`, `internals.md`,
`patches/kernel-6.6/series/README.md`. `AGENTS.md` still says "applied on tag `v6.6`" (not edited by this stream: the
main session should change it when it merges).

## Camera test (SD card only, the owner runs it)

Nothing is written to the flash, U-Boot and its environment are not touched. The way back is a power cycle (the flash
kernel boots).

1. Take the CI artifact `tc100-linux66-cma16-kernel` of the run on `upgrade-3.2` (subject `[up-kernel] ...`):
   `tc100test/c66.img` and `c66rd.gz`.
2. Boot from the SD card with `pack66/boot66b.sh` (RAM only).
3. Checks:
   - `/proc/cmdline` holds the full initrd size (the 256-character truncation trap);
   - `uname -r` prints `6.6.163`;
   - video 1080p and 720p, with the sub-stream (`ak39_vi.sub_channel`) and 3D-NR (`NR3D=1`);
   - audio in and out;
   - Wi-Fi: associates, stays up, no new RX/TX freeze (watch the rtl8xxxu counters), no "Failed to write block";
   - USB host (the camera's own USB device nodes, no NAK counter anomaly, `dmesg` without `anyka-hc` errors);
   - `dmesg` clean (no oops, no `BUG`, no `WARN` new compared with the 6.6.0 boot);
   - encoder soak of 24 h (H.265, as in `nq/`), no oops, no reboot.
4. Verdict: pass = all of the above; any oops or freeze = report with the CI symbols of the same run
   (`tc100-linux66-symbols`).

Not verified here: everything that needs the camera (this stream has only a compile test), and the behaviour of the
stable Wi-Fi changes listed above on the real RTL8188FU.
