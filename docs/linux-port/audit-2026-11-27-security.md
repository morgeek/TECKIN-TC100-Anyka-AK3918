# Security and robustness audit, 2026-11-27 (3.0.2-rc8)

Read-only review written for the owner's decision on a major upgrade (3.1 or 4.0). Nothing in the firmware changes
with this document; `SECURITY.md` at the root of the repository is added with it.

**Method.** The repository at `main` after `6785785` (3.0.2-rc8), the camera results in `test-queue.md` and
`recette-2026-11-26.md`, and upstream facts checked on 2026-11-27: kernel.org `releases.json` and its release page,
the package files of Buildroot at tag `2024.02.9`, the Buildroot tag list, and Mbed TLS `BRANCHES.md`. Reference
frameworks: ETSI EN 303 645 (the European baseline for consumer IoT security; its 13 provisions) and the OWASP IoT
Top 10. A hobby, non-commercial open-source project is largely outside the EU Cyber Resilience Act; that would change
if the firmware were ever sold or bundled with hardware.

## 1. Verdict

- **Robust: yes.** The design cannot brick the camera, the recovery chain is layered, the build is reproducible and
  tested, and the field results are clean. This is the strong side of the project.
- **Secure enough for a trusted home network, not beyond it.** It is far better than the stock firmware (cloud, Linux
  3.4, no updates), and the defaults are sound (local only, services off, LAN filter, login lockout).
- **Not compliant with industry baselines yet.** Four gaps carry most of the risk: a kernel without three years of
  stable fixes, a base system and TLS library out of maintenance, updates without a signature, and no fuzzing of the
  network parsers written in C. A security policy was missing; `SECURITY.md` closes that point.

## 2. What is already at or above the usual level

| Area | Evidence |
|---|---|
| No brick | U-Boot, `boot`, `mac` never written; whole-flash backup before a write; every write read back (`flashw`); the way back to the stock firmware (`restore-stock.sh`) |
| Recovery | watchdog; `boot-guard` safe mode after 3 short runs; initramfs rescue when `stack` is damaged (`v3/initrd-rescue`); Wi-Fi self-recovery (`scripts/wifi-recover.sh`) |
| Field results | days without oops on both cameras; bench of 2026-11-26/27: 72 kill/restart cycles of the video server, Wi-Fi down/up loops, day/night cycles, all clean, state restored |
| Build chain | 1335 host tests (`tests/`), local CI in Docker, every GitHub action pinned by commit, every download pinned by hash (`.github/ci-pins.sh`), reproducible images (`SOURCE_DATE_EPOCH`), flash budget gate |
| Privacy | no cloud, no account, no telemetry; the only default outgoing connection is NTP (`ENABLE_NTP=0` turns it off) |
| Attack surface | ONVIF, FTP, telnet off by default; `NET_LAN_ONLY=1` filters web, RTSP, telnet, FTP and WHEP to private networks; ssh LAN only |
| Authentication | web login with lockout, CSRF protection, RTSP Digest with lockout and slot limits, ONVIF WS-Security with lockout; setup wizard asks for a new password and a banner stays while the default one is in use |
| Binaries | stack protector and full RELRO in the free programs (test-queue HARDEN) |
| Secrets at rest | password, token and Wi-Fi key files at mode 600 (3.0.2-rc7, SECRET-MODES) |

## 3. Findings

Severity is for a camera on a home LAN with `NET_LAN_ONLY=1`. **High** = a known class of public vulnerabilities is
reachable; **Medium** = a baseline requirement is missing; **Low** = hardening.

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| SEC-1 | **High** | **Kernel 6.6.0 without stable fixes.** The series is applied on the tag `v6.6` (October 2023). Upstream 6.6 is at **6.6.163** (2026-11-23): 163 stable releases, three years of fixes (network stack, USB, filesystems, many with CVE numbers), are not in the camera. | `.github/ci-pins.sh`: `LINUX_TAG=v6.6`, `LINUX_COMMIT=ffc2532...`; 26 patches in `patches/kernel-6.6/series/`. kernel.org: 6.6 projected EOL **December 2027**; 6.12 and 6.18 projected EOL December 2028. |
| SEC-2 | **High** | **TLS library out of maintenance, and reachable by default.** Mbed TLS 2.28.9: the 2.28 LTS branch is no longer maintained (Mbed TLS lists only 3.6 LTS, until March 2027, and 4.x, 4.1 LTS until March 2029). It carries the DTLS of the WebRTC gateway, **on by default** (`WHEP=1`, UDP from the LAN), and the HTTPS of curl (Telegram, ntfy, update check: opt-in). | `.github/ci-pins.sh` `MBEDTLS_VERSION=2.28.9`; `config/boot.conf.dist` `WHEP=1`; `src/whep/tc100_whep.c` |
| SEC-3 | Medium | **Base system frozen on an old Buildroot branch.** Buildroot 2024.02.9 (each Buildroot LTS is maintained for about a year; the current LTS branches are 2025.02, at 2025.02.20, and 2026.02, at 2026.02.3). Versions in the image: busybox 1.36.1, dropbear 2024.85, wpa_supplicant 2.10, curl 8.11.0. No CVE watch on them. | `.github/ci-pins.sh` `BUILDROOT_TAG=2024.02.9`; package `.mk` files of that tag |
| SEC-4 | Medium | **Updates are checked, not authenticated.** The update package carries `MD5SUMS`: it catches corruption, not a forged package. Sending one needs the admin login, which limits the risk, but ETSI 5.3 asks for authenticity. The boot chain is not verified either: U-Boot is out of scope by design (no brick), so secure boot is impossible on this hardware. | `v3/install/update66.sh` (`md5sum -c MD5SUMS`) |
| SEC-5 | Medium | **No fuzzing of the network parsers written in C.** RTSP (`src/tc100rtsp`), HTTP (`src/httpfront`), ONVIF/SOAP (`src/onvifd`), MQTT (`src/mqttd`), WHEP/STUN/DTLS glue (`src/whep`) and mDNS (`src/mdnsd`) parse untrusted input; they have unit tests and read-only reviews, no fuzz harness. | no fuzz target in `tests/` or `src/` |
| SEC-6 | Medium | **Cleartext protocols.** Web login over HTTP, RTSP Digest, telnet as the rescue door (LAN only, off in normal use). Acceptable on a trusted LAN, never across the internet; HTTPS is documented through a reverse proxy. | README "Limits"; `controlscripts/telnet-server`, `v3/initrd-rescue` |
| SEC-7 | Medium | **Every service runs as root.** No privilege drop (`setuid`/`setgid`) in any daemon: one memory bug in a network parser gives the whole camera. Mitigated by the stack protector, RELRO and the LAN filter. | no `setuid`/`setgid` call in `src/` |
| SEC-8 | Low | **Default password public until changed.** Not unique per device (ETSI 5.1-1); the wizard and the banner push the change, but RTSP and the web answer with it until then. | README "Limits" |
| SEC-9 | Low | **No software bill of materials.** Nothing lists the components and versions of a release, so a new CVE cannot be matched against the image without reading the build. | release artifacts |
| SEC-10 | Low | **Security policy missing.** Fixed by this commit (`SECURITY.md`). The owner still has to turn on *Private vulnerability reporting* in the GitHub repository settings (Security tab). | `SECURITY.md` |
| SEC-11 | Info | **Hardware coverage.** Two cameras of one variant; the recovery paths with a damaged `stack`, a power pull during a write and the USB unbind / bind were closed without a camera test (owner's decision of 2026-11-27). | `readiness-3.0.2.md` section 3 |

## 4. ETSI EN 303 645, provision by provision

| Provision | State | Notes |
|---|---|---|
| 5.1 No universal default passwords | partial | wizard + banner; the default password stays valid until changed (SEC-8) |
| 5.2 Vulnerability disclosure policy | **added today** | `SECURITY.md`; turn on GitHub private reporting (SEC-10) |
| 5.3 Keep software updated | **gap** | web updates exist; components out of maintenance (SEC-1/2/3); updates not authenticated (SEC-4) |
| 5.4 Securely store sensitive parameters | partial | files at 600, plain text, readable by root (all services are root, SEC-7) |
| 5.5 Communicate securely | **gap** | HTTP, RTSP Digest, telnet rescue; DTLS on an unmaintained library (SEC-2, SEC-6) |
| 5.6 Minimise exposed attack surfaces | good | services off by default, LAN filter, ssh LAN only; root everywhere (SEC-7) |
| 5.7 Ensure software integrity | partial | read-back flash writes, MD5; no signature, no verified boot (SEC-4) |
| 5.8 Ensure personal data is secure | good | local only, recordings on the card, nothing sent out |
| 5.9 Resilience to outages | very good | works without internet, recovery chain, watchdog |
| 5.10 Examine telemetry data | n/a | no telemetry |
| 5.11 Easy deletion of user data | partial | settings reset and card format exist; no single "erase everything" step documented |
| 5.12 Easy installation and maintenance | good | SD install, wizard, web updates, the way back |
| 5.13 Validate input data | partial | reviewed parsers, length checks; no fuzzing (SEC-5) |

## 5. Upgrade options for the owner's decision

Sizes are relative: S = a day of agent work, M = a few days, L = a week or more with camera rounds. Every kernel
change follows the rules of `AGENTS.md`: one at a time, SD card first, the owner near the camera.

| Option | Closes | Size | Risk | Notes |
|---|---|---|---|---|
| A. SBOM in CI + CVE check script | SEC-9 | S | none | list package versions of each build (SPDX or a plain table) in the release artifact |
| B. Kernel rebased on the latest 6.6.y (6.6.0 -> 6.6.163) | SEC-1 | M-L | medium | same branch, same APIs in principle; the 26 patches are rebased, the hardware drivers (ISP, encoder, USB host, audio) re-qualified; supported until December 2027 |
| C. Buildroot 2025.02 or 2026.02 LTS + Mbed TLS 3.6 LTS | SEC-2, SEC-3 | M | medium | the WHEP DTLS-SRTP code moves to the Mbed TLS 3.x API; curl follows Buildroot; the flash budget must still pass |
| D. Signed updates (ed25519) | SEC-4 | S-M | low if staged | a small verifier in the updater, the private key kept by the owner off GitHub (CI signs nothing it can leak); the first signed release installs through the current path |
| E. Fuzzing of the network parsers in CI | SEC-5 | M | none on the camera | host builds of the parsers with libFuzzer or AFL++, a short run per push, a longer one nightly |
| F. Privilege drop for the daemons that do not need root | SEC-7 | M | low-medium | `httpfront`, `onvifd`, `mqttd`, `mdnsd`, `whep` under a dedicated user; `tc100_rtsp` keeps device access through group permissions |
| G. Kernel 6.12 or 6.18 LTS | SEC-1 for longer | L+ | high | a new port (projected EOL December 2028); a 4.0 candidate, only after B |

A possible grouping: **3.1** = A + B + C + D (the "kept updated, authenticated" release), with E running beside it
from the start; **4.0** = G, with F if it is not done earlier. The owner decides; nothing here is planned yet.

## 6. Accepted by design (not counted as findings)

- No HTTPS served by the camera: CPU, certificate handling and the LAN-only model; a reverse proxy is documented.
- No secure boot: U-Boot is never written, which is what makes the project brick-proof.
- Telnet as the rescue door on the LAN (owner's decision of 2026-11-25).
