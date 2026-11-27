# Major upgrade plan: 3.1 (kept updated, authenticated) and 4.0 (new kernel LTS)

Written on 2026-11-27 at the owner's request, after the security audit
[audit-2026-11-27-security.md](audit-2026-11-27-security.md). **A proposal: nothing starts before the owner's
decision**, and nothing starts before 3.0.2 final (`readiness-3.0.2.md`). Every step keeps the rules of `AGENTS.md`:
U-Boot and its environment never written, flash writes only through `flashw` with the owner's agreement, one kernel
change at a time, SD card (RAM) first, local CI then GitHub CI green before any rc.

Upstream facts were checked on 2026-11-27 (kernel.org `releases.json` and release page, Buildroot package files at
each tag, Buildroot tag dates, Mbed TLS `BRANCHES.md`, musl releases page).

## 1. What replaces what

| Component | In the image today | State | Replace with | Why this one |
|---|---|---|---|---|
| Linux kernel | **6.6.0** (tag `v6.6`, October 2023) + 26 patches | branch maintained (6.6.163 on 2026-11-23, projected EOL December 2027), but **none of its 163 stable releases is in the image** | **3.1: 6.6.163** (latest 6.6.y at the time); **4.0: 6.18 LTS** (projected EOL December 2028) | the same branch first: same APIs, the patches rebase instead of being ported; 6.18 rather than 6.12 for 4.0 (same projected EOL, newer, more likely to be extended) |
| Buildroot (base system) | 2024.02.9 (December 2024) | branch no longer updated (last point release 2024.02.13, April 2025) | **2025.02.x** (2025.02.20 on 2026-11-17) | the branch that still gets point releases; 2026.02 stopped at 2026.02.3 (June 2026) and ships older point versions than 2025.02.20 |
| Mbed TLS (WebRTC DTLS, curl HTTPS) | **2.28.9** | branch out of maintenance | **3.1: 3.6 LTS** (3.6.7 in Buildroot 2025.02.20, supported until March 2027); **4.0: 4.1 LTS** (until March 2029) | the only candidate that is small, has DTLS-SRTP, and a licence compatible with this GPL-2.0 project (Apache-2.0 **or GPL-2.0-or-later**) |
| curl | 8.11.0 | old | 8.23.0 (with Buildroot 2025.02.20) | kept: the HTTPS clients (update check, Telegram, ntfy, upload) need certificate checks; BusyBox `wget` TLS does not verify certificates |
| BusyBox | 1.36.1 | old | 1.37.0 | same tool, follows Buildroot; the `busybox.fragment` is re-checked (applets, `stat -c`, `ash`) |
| Dropbear (ssh) | 2024.85 | old | 2026.93 | kept: OpenSSH is too large for the `stack` partition |
| wpa_supplicant / hostapd | 2.10 | old | 2.12 | follows Buildroot; the Wi-Fi rescue AP and the join paths re-tested |
| alsa-lib / alsa-utils, iw | 1.2.11, 5.19 | old | 1.2.13, 6.9 | follow Buildroot (the microphone is `hw:0,0`, the `arecord` traps of `AGENTS.md` re-checked) |
| musl of the free programs (`tc100_rtsp` and others, static) | 1.2.4 (`v3/musl/build-musl.sh`) | two releases behind | **1.2.6** | the libc linked into every network-facing free program |
| Toolchain | Bootlin armv5-eabi musl stable of Buildroot 2024.02 | old | the Bootlin toolchain of Buildroot 2025.02 | follows Buildroot; the HARDEN flags and the freestanding ARM CI check stay |
| RTL8188FU firmware | linux-firmware 20241017 | blob, rarely changes | unchanged unless linux-firmware changes `rtl8188fufw.bin` | nothing to gain otherwise |

**Rejected:** OpenSSL 3 (several MB, Apache-2.0 only), wolfSSL (GPL-3.0 or commercial: not compatible with GPL-2.0
code linking it), BearSSL (no DTLS, barely maintained), OpenSSH (size), a move away from Buildroot (no gain for a
fixed small image).

**New components:**
- **Monocypher** (BSD-2-Clause or CC0, a few KB of C, audited) for the update signature check on the camera
  (ed25519, the verifier only).
- **Buildroot's own tooling** for the bill of materials: `make show-info` and `make legal-info` give names, versions
  and licences; Buildroot's `pkg-stats` checks the packages against the NVD CVE list.
- **libFuzzer** (clang, host only, never in the image) for the parser fuzzing.

## 2. Constraints to watch

- **Flash space.** The kernel slot is 2 MiB; the 2026-11-06 audit measured about 110 KB free in it. 6.6.163 should
  stay close to 6.6.0; **6.18 may not fit** without kernel config trims (audit S14 lists 20-60 KB of candidates). The
  `stack` partition is close to full: Mbed TLS 3.6 and the newer packages are measured by `scripts/flash_budget.py`
  before anything else. A failed budget stops the step; nothing is forced.
- **Mbed TLS 2 -> 3 API.** The WebRTC gateway calls Mbed TLS 66 times (`src/whep/tc100_whep.c`): DTLS with SRTP
  negotiation, the key export used for SRTP, a self-signed certificate written at start. In 3.x most structure fields
  are private and the key export callback changed: a real port, checked by the existing aiortc interoperability job of
  the CI and by a browser on the camera.
- **Kernel drivers.** The 26 patches carry the Anyka drivers (ISP / video input, encoder, audio, USB host, SPI flash,
  clocks) and the fixes of the audits. Rebasing on 6.6.163 meets every change of those subsystems in three years;
  6.18 is a port (V4L2, ALSA, USB core and DT changes).
- **Recovery while upgrading.** User space can always go back by a web update or the 3.0 SD card. A flashed kernel that
  does not boot never reaches the initramfs (`AGENTS.md`): every kernel step runs from the SD card in RAM first.

## 3. Phases

Each phase is one or more release candidates on `main`, with test-queue entries, the switch to turn it off when there
is one, and the owner's go before the next phase.

| Phase | Version | Content | Camera risk | Gate to go on |
|---|---|---|---|---|
| 0 | 3.0.2 final | as decided in `readiness-3.0.2.md` | — | released |
| 1 | 3.1-rc1 | **SBOM + CVE report** as a release artifact (A); **fuzz harnesses** for the RTSP request parser, the HTTP front, the ONVIF SOAP parser, MQTT and STUN, run in CI (E) | none (CI only) | fuzzers run clean for a week of pushes; every crash found is fixed with a regression test |
| 2 | 3.1-rc2 | **signed updates** (D): `sigcheck` (Monocypher) in the updater; the owner generates the key pair on his own machine, keeps the private key off GitHub and signs the release tar with a host script; rc2 accepts an unsigned package with a warning, 3.1 final refuses it | low (update path only; the 3.0 SD card stays the way back) | a signed update and a refused forged one on both cameras; the web page says why a package is refused |
| 3 | 3.1-rc3 | **base system**: Buildroot 2025.02.x, Mbed TLS 3.6 (WebRTC port), curl, BusyBox, Dropbear, wpa_supplicant / hostapd, ALSA, iw, the Bootlin toolchain; musl 1.2.6 for the free programs (C) | medium (user space; recoverable by a web update) | flash budget green; aiortc job green; on both cameras: Wi-Fi join, rescue AP, ssh, web, live view (WebRTC and the HTML5 fallback), RTSP in Frigate, MQTT, ONVIF, two-way audio, a web update; 48 h without an incident |
| 4 | 3.1-rc4 (one or more) | **kernel 6.6.0 -> 6.6.163** (B): the 26 patches rebased, CI symbols kept; **SD card in RAM first** (`boot66b.sh`), 24 h, then the flash with the owner | medium-high (kernel) | SD run: boot, video 1080p / 720p, 3D-NR, audio in and out, Wi-Fi, USB, encoder for 24 h, no oops; then the bench on the flash and 48 h; one kernel change at a time (no config change in the same rc) |
| 5 | 3.1 final | the full bench on both cameras, the owner's session, 48 h on the last rc (the 3.0.2 criteria) | — | release |
| 6 | 3.2 (optional) | **privilege drop** (F): `httpfront`, `onvifd`, `mqttd`, `mdnsd`, `whep` under a dedicated user; `tc100_rtsp` keeps device access through group permissions | low-medium | the bench and the services on both cameras |
| 7 | 4.0 | **kernel 6.18 LTS** (G), Mbed TLS 4.1 LTS, the Buildroot LTS of that time | high | a separate plan when 3.1 is out: kernel size in 2 MiB, driver port, SD-only for weeks before any flash |

Why this order: tooling first (no camera risk, and the fuzzers protect the later phases); signatures before the big
updates, so the base system and the kernel already arrive signed; user space before the kernel, because user space
is recoverable from the web page and the kernel is not; one large risk per rc.

## 4. Decisions for the owner

1. Go or no go for 3.1 as described (phases 1-5), after 3.0.2 final.
2. Buildroot **2025.02.x** (recommended: the maintained branch) or the next LTS when it appears.
3. Signed updates: refuse unsigned packages from 3.1 final (recommended), or warn only. The owner keeps the private
   key; losing it means the next update goes through the SD card.
4. Phase 6 (privilege drop) in 3.2, with 3.1, or not at all.
5. 4.0 (kernel 6.18): planned after 3.1, or left until 6.6 nears its end of life (December 2027).
