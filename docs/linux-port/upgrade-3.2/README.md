# Branch `upgrade-3.2`: the major upgrade (future 3.2)

Owner's request of 2026-11-27: prepare the major upgrade of
[../plan-upgrade-3.1.md](../plan-upgrade-3.1.md) on its own branch, as the future **3.2** with every phase of that plan
(1 to 6), each tested and validated by the GitHub CI, ready to try **from the SD card** (kernel and initramfs in RAM,
`pack66/boot66b.sh`, nothing written to the flash). `main` stays the 3.0.2 line until 3.0.2 final; this branch is
merged into `main` only on the owner's word, after the camera rounds.

The CI runs on this branch (`ci.yml` and `build-kernel-linux66.yml` list `upgrade-3.2`). The artifacts of a run are
the ones of `main`: `tc100-linux66-cma16-kernel` (`tc100test/c66.img`, `c66rd.gz` for the SD test loop),
`tc100-3-release` (SD zip and update tar), `tc100-linux66-symbols`, `tc100-base-rootfs`.

## Work streams

| Stream | Plan phase | Content | Notes file |
|---|---|---|---|
| `[up-sbom]` | 1 | software bill of materials and CVE report as release artifacts | [sbom.md](sbom.md) |
| `[up-fuzz]` | 1 | libFuzzer harnesses for the network parsers, run in CI | [fuzz.md](fuzz.md) |
| `[up-sign]` | 2 | signed update packages (ed25519, Monocypher), warn-only until the owner's key is in | [sign.md](sign.md) |
| `[up-base]` | 3 | Buildroot 2025.02.x, Mbed TLS 3.6 LTS (WebRTC port), musl 1.2.6, toolchain | [base.md](base.md) |
| `[up-kernel]` | 4 | kernel 6.6.0 -> latest 6.6.y, the 26 patches rebased | [kernel.md](kernel.md) |
| `[up-privdrop]` | 6 | network daemons without root, behind a switch | [privdrop.md](privdrop.md) |

Rules for every stream (on top of `AGENTS.md`):
- One stream per commit prefix; local CI (`sh tests/docker/local-ci.sh ...`) green before a push, then the GitHub CI.
- Each stream writes what it changed, the switch that turns it off, and the camera test (SD first) in its notes file
  here. The main session moves them into `CHANGELOG.md`, `test-queue.md` and the release notes when it merges, so the
  streams do not edit those three files nor `VERSION`.
- No U-Boot or environment write, no flash write from any test; camera tests of this branch run from the SD card in RAM
  until the owner decides otherwise.
