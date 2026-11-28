# Branch `upgrade-3.2`: the major upgrade (future 3.2)

Owner's request of 2026-11-27: prepare the major upgrade of
[../plan-upgrade-3.1.md](../plan-upgrade-3.1.md) on its own branch, as the future **3.2** with every phase of that plan
(1 to 6), each tested and validated by the GitHub CI, ready to try **from the SD card** (kernel and initramfs in RAM,
`pack66/boot66b.sh`, nothing written to the flash). `main` stays the 3.0.2 line until 3.0.2 final; this branch is
merged into `main` only on the owner's word, after the camera rounds.

The CI runs on this branch (`ci.yml` and `build-kernel-linux66.yml` list `upgrade-3.2`). The artifacts of a run are:
`tc100-linux66-cma16-kernel` (`oipc.img`, `tc100test/oipcrd66.gz`),
`tc100-3-release` (`tc100-<ver>-sd.zip` containing `tc100test/c66.img` / `c66rd.gz` for the SD test loop, and `tc100-<ver>-update.tar`),
`tc100-linux66-symbols`, `tc100-base-rootfs`.

## Work streams

| Stream | Plan phase | Content | Notes file |
|---|---|---|---|
| `[up-sbom]` | 1 | software bill of materials and CVE report as release artifacts | [sbom.md](sbom.md) |
| `[up-fuzz]` | 1 | libFuzzer harnesses for the network parsers, run in CI | [fuzz.md](fuzz.md) |
| `[up-sign]` | 2 | signed update packages (ed25519, Monocypher), warn-only until the owner's key is in | [sign.md](sign.md) |
| `[up-base]` | 3 | Buildroot 2025.02.x, Mbed TLS 3.6 LTS (WebRTC port), musl 1.2.6, toolchain | [base.md](base.md) |
| `[up-kernel]` | 4 | kernel 6.6.0 -> latest 6.6.y, the 25 patches rebased | [kernel.md](kernel.md) |
| `[up-privdrop]` | 6 | network daemons without root, behind a switch | [privdrop.md](privdrop.md) |

Rules for every stream (on top of `AGENTS.md`):
- One stream per commit prefix; local CI (`sh tests/docker/local-ci.sh ...`) green before a push, then the GitHub CI.
- Each stream writes what it changed, the switch that turns it off, and the camera test (SD first) in its notes file
  here. The main session moves them into `CHANGELOG.md`, `test-queue.md` and the release notes when it merges, so the
  streams do not edit those three files nor `VERSION`.
- No U-Boot or environment write, no flash write from any test; camera tests of this branch run from the SD card in RAM
  until the owner decides otherwise.

## State on 2026-11-27 evening (hand-off)

**3.2.0-rc3** (second audit: root-only `/tmp` with PRIVDROP, restore re-check, CI hardened; `65f0bc9`) replaces
rc2 for the camera tests: build run 46073514675 and CI run 46073514679 green, no initramfs size warning; artifacts
`tc100-3-release` (SD zip, `tc100-3.2.0-rc3-update.tar`) and `tc100-linux66-cma16-kernel`. Earlier: **3.2.0-rc2** (audit of the branch, `[audit 3.2]`: three read-only reviews, their fixes in `ee731ee`, see CHANGELOG)
replaces rc1 for the camera tests: build run 46066002754 (`e9dc57b`, green; CI run 46066002560 green, the privdrop
module now also runs as root there) gives `tc100-3-release` (SD zip, `tc100-3.2.0-rc2-update.tar`) and
`tc100-linux66-cma16-kernel` (`tc100test/c66.img`, `c66rd.gz`). **3.2.0-rc1** (`df8fb95`) had all six streams merged, each reviewed by the reviewer agent (the
kernel, the signature, the base system / DTLS port and the privilege drop twice), local CI green (tests, cross, kernel,
fuzz, whep). GitHub: build run 46024956529 (`df8fb95`) green, it gives the SD files and the update tar
(`tc100-3-release`); CI run 46051058827 (`1ef1b20`, test and CI fixes only, no firmware change) green. Nothing has run on a
camera yet. Entries: `test-queue.md` section "3.2 on branch `upgrade-3.2`" (UP32-KERNEL, UP32-BASE, UP32-SIGN,
UP32-PRIVDROP, UP32-FUZZ, UP32-FLASH, UP32-SBOM). Owner's decision of 2026-11-27: after the SD gate, the rc2 may be
written to ONE camera (UP32-FLASH, ways back written there).

Open, in order:
1. Camera rounds from the SD card (the tester), then UP32-FLASH on one camera, 48 h, then the other.
2. The owner's signing key: his public key in `v3/install/update-keys/`, then `UPDATE_REQUIRE_SIG=1` by default
   ([sign.md](sign.md) "Remaining before 3.2 final").
3. `tc100_rtsp` without root (device nodes by group, [privdrop.md](privdrop.md)); `httpfront` and `tc100-mqttd` keep
   root by design.
4. Flaky host tests seen only under Docker load: `test_httpfront_native` (`sd_used_kb` compares two real `df` reads,
   limit 512 KB) and `test_supervisord ... agree_in_real_time` (button timing). Both pass on a quiet machine and on
   GitHub; make the first use a fixture `df` if it fails on GitHub.
5. Merge into `main` only on the owner's word, after the camera rounds (`main` is the 3.0.2 line).

Traps met on this branch:
- GitHub job logs need admin rights; failures are read from the public annotations (the CI prints the failing tests
  and the CVE step its errors as `::error::` / `::warning::`). The unauthenticated API allows 60 requests an hour.
- The base image cache key hashes `build-base-rootfs.yml`, `v3/buildroot/**`, `src/whep/**` and `ci-pins.sh`: touching
  any of them rebuilds Buildroot (about 18 minutes on GitHub).
- The CVE step downloads the NVD data (about 20 minutes) once per ISO week (cached); it never fails the build.
- The GitHub runner is an ordinary user with passwordless sudo, local CI runs as root: a test that starts a daemon
  through `sudo` must kill the daemon itself (SIGKILL to sudo leaves it running) and must not let it inherit stdout,
  or the `unittest | tee` step never ends (run 46024956559 hung 6 h; fixed in `1ef1b20`, host tests now limited to
  45 min). Reproduce with a `useradd` + NOPASSWD sudo user in a `python:3.12` container.
- The stream worktrees were local to the main session (scratchpad); the branches `up-*` were merged and are not pushed.
