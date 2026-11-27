# `[up-base]`: base system off unmaintained branches (plan phase 3)

Stream of the branch `upgrade-3.2` (see [README.md](README.md), [../plan-upgrade-3.1.md](../plan-upgrade-3.1.md) section 1).
Nothing here touches the kernel, U-Boot or the flash layout. The way back is the same as for any user-space change: a
web update with a 3.0 package, or the 3.0 SD card.

## Versions, before and after

| Component | Before (3.0.2) | After (`up-base`) |
|---|---|---|
| Buildroot | 2024.02.9 (`d37527ba`) | **2025.02.20** (`2f9129e7909bff6d78ae8cfda3d0e73503dfcac6`; no 2025.02.21 exists on 2026-11-27) |
| Mbed TLS (curl HTTPS, WebRTC DTLS) | 2.28.9 | **3.6.7** (SHA-256 `a7e8bcbe...d11f6`, equal to Buildroot's own `.hash`) |
| musl in the image (Buildroot toolchain) | 1.2.4 | 1.2.6 (the Bootlin armv5-eabi musl stable toolchain of the new branch) |
| musl for the free programs (`v3/musl/build-musl.sh`) | 1.2.4 | **1.2.6** (SHA-256 `d585fd3b...0512a`, equal to Buildroot's `musl.hash`) |
| BusyBox | 1.36.1 | 1.37.0 |
| Dropbear | 2024.85 | 2026.93 |
| wpa_supplicant / hostapd | 2.10 | 2.12 |
| curl | 8.11.0 | 8.23.0 |
| alsa-lib / iw / zlib / xz | 1.2.11 / 5.19 / 1.3.1 / 5.4.5 | 1.2.13 / 6.9 / "1.4" soname / 5.6.4 (as Buildroot ships them) |

The pins are in `.github/ci-pins.sh` (`BUILDROOT_TAG`, `BUILDROOT_COMMIT`, `MBEDTLS_VERSION`, `MBEDTLS_SHA256`;
`MBEDTLS_URL` follows the version). The interop test and the musl compile test take Mbed TLS from there.

## What changed, file by file, and why

- `.github/ci-pins.sh`: the three pins above.
- `.github/workflows/build-base-rootfs.yml`: Buildroot 2025.02.20 in the title, the step name and the download cache key
  (`buildroot-dl-2025.02.20-...`). The four `sed` workarounds of 2024.02 are gone: m4 1.4.21 is Buildroot's own now, and
  the CMake policy flag for Mbed TLS / `pkg-cmake.mk` is not needed with Mbed TLS 3.6 (`cmake_minimum_required 3.5.1`).
  The image cache key hashes `v3/buildroot/**`, `src/whep/**` and `ci-pins.sh`, so it changes by itself.
- `v3/buildroot/configs/tc100_defconfig`: `BR2_PACKAGE_MBEDTLS_DTLS_SRTP=y`. Buildroot 2025.02 has this option and switches
  `MBEDTLS_SSL_DTLS_SRTP` on in `mbedtls_config.h`. The toolchain symbol
  `BR2_TOOLCHAIN_EXTERNAL_BOOTLIN_ARMV5_EABI_MUSL_STABLE` still exists and now selects the newer toolchain: no change.
- `v3/buildroot/external.mk`:
  - the old `MBEDTLS_POST_PATCH_HOOKS` (a `sed` on `include/mbedtls/config.h` plus `MBEDTLS_SSL_EXPORT_KEYS`) is replaced by
    a configure hook that only **checks** the options `tc100-whep` needs in `mbedtls_config.h` (SRTP, DTLS, hello verify,
    ECDSA, P-256, X.509 write, PEM write, PK write, ECDHE-ECDSA). `MBEDTLS_SSL_EXPORT_KEYS` does not exist in 3.x (the key
    export is always built) and is no longer checked.
  - wpa_supplicant 2.12 turns 802.11ax, 802.11be and IPv6 on by default, hostapd 2.12 turns 802.11be on: all four
    are in the `*_CONFIG_DISABLE` lists now (the radio is an 802.11n 1T1R RTL8188FU, the kernel has no IPv6). Measured:
    hostapd 755 KB -> 669 KB with the 11be switch.
- `v3/buildroot/board/tc100/busybox.fragment`: BusyBox 1.37 removed `CONFIG_FEATURE_FLASHCP_ERASE` (flashcp always erases): line
  removed with a comment; `CONFIG_GETFATTR` is new in the default configuration and is switched off like `SETFATTR`
  (no caller). Verified on the built `.config`: every `CONFIG_` line of the fragment has the wanted state, and
  `busybox.links` gives the same 192 applets as `tests/fixtures/busybox-6.6-applets.txt` (no change of the fixture).
  `stat -c` (`FEATURE_STAT_FORMAT`), `sha256sum`, `md5sum`, `telnetd`, `ftpd`, `ntpd`, `crond`, `timeout`, `nc -l`,
  `syslogd -D -f` are all built; `wget` is still off on purpose (the scripts use curl).
- `v3/buildroot/board/tc100/post-build.sh`: two files that 2025.02 installs and the image must not carry:
  `usr/bin/wcurl` (new curl script, no caller) and `etc/init.d/S50crond` (**new in the 2025.02 BusyBox package**: it would
  start a resident `crond` at every boot; the camera starts `crond` itself, only when the managed crontab has an entry,
  `v3/autorun-linux66.sh`, "Scheduled reboot". Left in, it would have been a silent behaviour change).
- `v3/initramfs-prune.txt`: the library names that move out of the initramfs follow the new sonames
  (`libmbed{crypto,tls,x509}.so.{16,21,7}` and `.3.6.7`, `liblzma.so.5.6.4`, `libz.so.1.4`) and two new libraries: Mbed
  TLS 3.6 built shared pulls in `libeverest.so` and `libp256m.so` (5 KB each, `NEEDED` by all three Mbed TLS libraries,
  not by anything else), which go to `ext/lib` with them. `v3/build-stack.sh` follows `NEEDED` and needed no change
  (checked: `ext/lib` of the built tree has the ten libraries).
- `v3/musl/build-musl.sh`, `src/musl.mk`, `src/*/Makefile`, `tests/test_harden.py`, `tests/test_musl_programs_qemu.py`,
  `.github/workflows/ci.yml` (musl cache key `musl-1.2.6-...`), `build-kernel-linux66.yml` (comment): 1.2.4 -> 1.2.6.
- `tests/test_whep.py`: pins the new hook name and the new defconfig line. `tests/docker/whep-interop.sh`,
  `whep-musl.sh`, `local-ci.sh`, `ci.yml`: Mbed TLS 3.6.7, `mbedtls_config.h` instead of `config.h`, no
  `MBEDTLS_SSL_EXPORT_KEYS` set.
- `v3/buildroot/README.md`, `docs/linux-port/whep-design.md`: version mentions.

Not changed: the squashfs patch (`patches/squashfs`, still applies: the build succeeded), `external.desc`, the
`tc100-whep` package files (same `-lmbedtls -lmbedx509 -lmbedcrypto` link line).

## The `src/whep/tc100_whep.c` port, API by API

Behaviour is meant to be identical: same cipher suite (`ECDHE-ECDSA-AES128-GCM-SHA256`), same SRTP profile
(`AES128_CM_HMAC_SHA1_80`), same certificate (ECDSA P-256, `CN=tc100-whep`, 2020-2050, serial `0x10000 | 16 random
bits`, SHA-256 fingerprint of the DER), same DTLS timeouts (500 ms / 4 s), MTU 1200, no cookies (the STUN check proved
the address), client certificate optional and checked by fingerprint, TLS 1.2 minimum.

| 2.28 | 3.6 | Note |
|---|---|---|
| `mbedtls_ssl_conf_export_keys_ext_cb(conf, cb, p)` (per configuration, key block included) | `mbedtls_ssl_set_export_keys_cb(ssl, cb, p)` (per SSL context, set after `mbedtls_ssl_setup`) | the callback now returns `void` and gets `(type, secret, secret_len, client_random, server_random, prf_type)`; it keeps the 48-byte master secret only for `MBEDTLS_SSL_KEY_EXPORT_TLS12_MASTER_SECRET`. The key block is not used by the daemon (it derives the SRTP keys itself with the TLS 1.2 PRF). |
| `mbedtls_ssl_conf_min_version(conf, MAJOR_VERSION_3, MINOR_VERSION_3)` | `mbedtls_ssl_conf_min_tls_version(conf, MBEDTLS_SSL_VERSION_TLS1_2)` | the old call is deprecated; DTLS 1.2 uses the TLS 1.2 constant |
| `mbedtls_pk_parse_keyfile(&k, path, NULL)` | `... (&k, path, NULL, mbedtls_ctr_drbg_random, &drbg)` | 3.x takes an RNG (blinding) |
| `mbedtls_pk_parse_key(&k, buf, len, NULL, 0)` | `... NULL, 0, mbedtls_ctr_drbg_random, &drbg)` | same |
| `mbedtls_x509write_crt_set_serial(&w, &mpi)` and the bignum | `mbedtls_x509write_crt_set_serial_raw(&w, bytes, 3)` with `{0x01, r0, r1}` | the old call is deprecated; same value; `mbedtls/bignum.h` is no longer included |
| `info.chosen_dtls_srtp_profile` | `info.MBEDTLS_PRIVATE(chosen_dtls_srtp_profile)` with `MBEDTLS_ALLOW_PRIVATE_ACCESS` defined before the includes | the structure field is private in 3.x and 3.6 has no accessor; this is the only private field read |
| `mbedtls_pk_ec(k)` | unchanged | still a public inline in 3.6 (private access happens inside the header) |

Unchanged calls (same signature in 3.6): `mbedtls_ctr_drbg_*`, `mbedtls_entropy_*`, `mbedtls_ecp_gen_key`,
`mbedtls_pk_setup`, `mbedtls_pk_write_key_pem`, `mbedtls_x509write_crt_*` (pem writer, names, validity, md, keys,
version), `mbedtls_x509_crt_parse[_file]`, `mbedtls_md`, `mbedtls_md_hmac`, `mbedtls_ssl_config_defaults`,
`..._conf_rng`, `..._own_cert`, `..._authmode`, `..._ciphersuites`, `..._dtls_cookies`, `..._handshake_timeout`,
`..._dtls_srtp_protection_profiles`, `mbedtls_ssl_setup`, `..._set_bio`, `..._set_timer_cb`, `..._set_mtu`,
`..._handshake`, `..._read`, `..._close_notify`, `..._get_peer_cert`, `..._get_dtls_srtp_negotiation_result`.
`psa_crypto_init()` is not called: the daemon is DTLS 1.2 with the legacy API only (TLS 1.3 is the part of 3.6 that
needs PSA), and the interoperability run confirms it.

Verified:
- `sh tests/docker/local-ci.sh whep` equivalent (run with the volume `tc100-whep-up`): host unit tests `whep_test: all ok`,
  `-Wall -Wextra -Werror` build against the real 3.6.7, then the aiortc interoperability test `Ran 1 test ... OK`
  (offer, ICE, DTLS-SRTP up, streaming 36 video and 15 audio packets, viewer limit, stop). The musl (alpine) compile
  check `whep-musl.sh` is OK.
- Certificate persistence: a first start writes `whep-key.pem` / `whep-cert.pem`, a second start loads them (no
  new certificate, same fingerprint), and a SEC1 `EC PRIVATE KEY` PEM + X.509 PEM made by OpenSSL (the format the 2.28 build
  wrote, so a camera that already has its files) loads and starts. A camera updated from 3.0.x therefore keeps its fingerprint.
- Not tested here: a real browser (Chrome, Firefox, Safari) on the camera, see the camera test below.

## Sizes (built locally in Docker, `tc100_defconfig`, same inputs for both sides)

Both Buildroot trees were built from scratch in Docker (volumes `tc100-br-up-old` = 3.0.2 tree, `tc100-br-up` = this
branch); the stack and the initramfs were then built with `v3/build-stack.sh` / `v3/build-rootfs66.sh` of the respective
tree (Debian bookworm `squashfs-tools` 4.5.1, the CI has 4.6: a few KB of difference possible; no kernel, so no
`--kernel` in the budget line).

| | before | after | limit |
|---|---|---|---|
| `rootfs.cpio.gz` (base image) | 3,251,149 | 3,572,387 | none |
| `stack.sqfs` | **2,174,976** | **2,338,816** (+163,840) | 2,830,336 (free 491,520) |
| initramfs xz payload (`oipcrd66.gz`, padded to the fixed `INITRD_SIZE` 2,012,654) | 906,872 | 981,560 (+74,688) | 2,012,654 |
| initramfs unpacked file data (RAM, never reclaimed) | 2,167,938 | 2,360,332 (+192,394) | about 7 MB |

`python3 scripts/flash_budget.py --initrd ... --stack ...`: initrd OK (free 81,920 sectors-rounded before and after: the
image is padded to the fixed size), stack OK. `tests/ci-vendor-budget.sh` and the kernel line of the budget were **not**
run locally (no kernel built, the vendor budget does not depend on this change).

Main growths (bytes, stripped, before -> after): `wpa_supplicant` 610,048 -> 763,688 (in the initramfs, Wi-Fi needs it
before the user space), `hostapd` 577,052 -> 669,252, `libc.so` 710,208 -> 747,076, `dropbear` 247,664 -> 288,620,
`libcurl` 453,756 -> 538,856, `curl` 144,728 -> 165,160, Mbed TLS (three libraries) 683,436 -> 843,236 plus the two 5 KB
stubs, `iw` 231,420 -> 244,088. BusyBox is the same size. Candidates if the budget ever gets tight (none needed now):
Dropbear without the new post-quantum / extra key exchanges (about 40 KB), libcurl without HTTP/2 and the extra protocols (the
camera only uses https GET/POST and file upload), wpa_supplicant options (SAE-PK, FILS, PASN) if the WPA2-PSK-only
policy of `external.mk` is extended.

**Not built locally:** the kernel and `oipc.img` (not part of this stream), the release zip / update tar
(`v3/build-release.sh`), `tests/ci-vendor-budget.sh`. The GitHub CI must run the base job (about 40 min), the kernel
workflow (it reads `tc100-base-rootfs`) with its two budget steps, and the `whep-interop` job.

## Local CI results (Docker, Windows)

- `sh tests/docker/local-ci.sh tests`: node tests OK; python `Ran 1335 tests in 833 s`, `OK (skipped=63)`, "local CI: ok"
  (the first run, before the hook-name fix, had one failure: `test_whep.Wiring.test_base_image`).
- `sh tests/docker/local-ci.sh cross` (musl 1.2.6 built from the tarball with the new SHA-256, tc100_rtsp, libakuio,
  httpfront, mqttd, supervisord, onvifd, rwconf, logfwd, netacl, qemu tests, harden checks): `tests.test_musl_programs_qemu`
  11 tests OK, `tests.test_harden` 8 tests OK; stripped sizes rwconf 9,284, httpfront 33,828, mqttd 38,000, supervisord
  34,120, onvifd 54,428, logfwd 13,496, libnetacl 5,056. Both runs of the whole
  `cross` job (twice, with other Docker jobs on the machine) failed two parity cases of `tests.test_httpfront_native`, each
  time different ones (`sd_used_kb` 1296 / 688 / 556 / 672 KB apart, limit 512): the test compares the native `df` with the
  CGI's `df` of the busy container filesystem while a Buildroot build and other jobs were writing to it; the freestanding
  `httpfront` does not use musl and is unchanged. The same test file alone, re-run: 11 tests OK. Everything else of the
  job (builds, qemu, harden) was OK; it is a load-sensitive test, not a result of this change (not proven on a quiet
  machine against the old base).
- `whep` (see above): green.

## Camera test (SD card, kernel and initramfs in RAM, nothing written to the flash)

Build: the GitHub CI of this branch gives `tc100-linux66-cma16-kernel` (`tc100test/c66.img`, `c66rd.gz`) built from the new
base, and `tc100-3-release` (SD zip, update tar). Boot with `pack66/boot66b.sh` as for every SD test. The SD user space of
the same CI run goes on the card (`tree/`). Owner runs, in this order (stop at the first failure and report):

1. Boot, `/proc/cmdline` has the full initrd size, `cat /etc/os-release` says Buildroot 2025.02.20, `free`: note
   MemFree against the same camera on 3.0.2 (the initramfs is 192 KB bigger).
2. Wi-Fi join (home network, WPA2-PSK) and a reboot that rejoins; `iw` and `wpa_cli status` work; no `wpa_supplicant` errors
   in the log about the options switched off (AX/BE/IPv6).
3. Rescue AP (hostapd 2.12): force the rescue mode, a phone joins the AP (WPA2, fixed channel) and reaches telnet/web;
   hostapd stays up for 10 minutes.
4. ssh (Dropbear 2026.93): login with the owner's key and with the password, `scp` a file in and out, LAN-only filter
   still refuses an outside address (`NET_LAN_ONLY`).
5. Web UI: login, Status, Settings save, Logs, the HTTPS-using features (update check, Telegram or ntfy test, upload
   test): they use curl 8.23 + Mbed TLS 3.6 with the CA bundle; check one certificate failure case (wrong date or an
   unknown CA) is still refused.
6. Live view WebRTC in Chrome, Firefox and Safari (the WHEP gateway on Mbed TLS 3.6): the video and the audio start within
   a few seconds, two viewers, the third is refused, a viewer that closes frees its slot, CPU headroom as on 3.0.2
   (`top` during one viewer); the HTML5 / MJPEG fallback with `WHEP=0` in `boot.conf`; the certificate file survives
   a reboot (same fingerprint in the log).
7. RTSP in Frigate (main and sub stream, 15 minutes, no reconnects), with audio.
8. MQTT: connect, state topics, a command, Home Assistant discovery.
9. ONVIF: discovery, snapshot, stream URL, PTZ-less profile in the NVR.
10. Two-way audio: microphone in the live view and the speaker (`talk`) with the 3.6 `ALSA` 1.2.13 libs; `arecord -D hw:0,0`
    and `aplay -D plughw:0,0` by hand once.
11. Scheduled reboot (Settings -> System) with an entry: `crond` starts then, and **only** then (`ps` shows no `crond`
    without an entry; that is the S50crond removal).
12. A web update package built by this branch (the CI update tar): applied from the SD-card test only, no flash write
    (use the 3.0 SD update path, never `flashw`); the camera comes back and the version shows the new build.
13. 48 hours: soak on the SD test, no kernel error, no `tc100-whep`, `wpa_supplicant`, `hostapd` or `dropbear` restart in
    the supervisor log, no memory growth beyond what 3.0.2 shows.

Switch to go back: none in the image (one base). The way back is booting the 3.0.2 kernel and card, or a 3.0.x web update
for a camera that ever had this base flashed (owner's decision, after the SD rounds).

## Open points for the main session

- The GitHub CI must confirm the base image build (cache key changed, it builds from scratch) and the two budget steps.
- Dropbear 2026.93 and curl 8.23 ship defaults of their own (post-quantum key exchange, HTTP/2, more protocols): only
  sizes were measured here, not their behaviour on the camera.
- `src/whep/whep_proto.h` still says "mbedTLS 2.28 does not reassemble a ClientHello" in a comment about fragmented
  handshakes; whether 3.6 does was not checked (the interop test with aiortc passes either way).
- `CHANGELOG.md`, `test-queue.md`, the release notes and `VERSION` are not edited by this stream (README rule): the camera test
  above is to be copied into `test-queue.md` as one entry with the switch "none (one base)".
