# Base root filesystem (Buildroot)

Our own replacement for the OpenIPC image: Buildroot 2024.02.9, Bootlin ARM926 musl
toolchain, BusyBox init, dropbear, wpa_supplicant (nl80211), curl (mbedTLS), jq,
alsa-utils, iw. Kernel and bootloader are not built here.

- `configs/tc100_defconfig`: the configuration. `board/tc100/busybox.fragment`: extra BusyBox applets.
  `board/tc100/post-build.sh`: size trimming, locked root password, empty Wi-Fi config.
- CI: `.github/workflows/build-base-rootfs.yml` (called by the kernel workflow). Output: `rootfs.cpio.gz`,
  uploaded as the artifact `tc100-base-rootfs`; `v3/build-rootfs66.sh` takes it as input (`v3/build-flash-rootfs66.sh`, an early draft, is in `_archive_v3-drafts/`).
- Local build: `git clone --branch 2024.02.9 https://github.com/buildroot/buildroot; make -C buildroot BR2_EXTERNAL=$PWD/v3/buildroot O=$PWD/out tc100_defconfig && make -C buildroot O=$PWD/out`.

## Slim base (2026-10-30 audit)

What is left out, and the evidence that nothing calls it (re-check with `tests/test_flash_image.py`, which fails if a
script, CGI, init or install script calls an applet that `board/tc100/busybox.fragment` switched off):

- BusyBox: 98 applets (console/VT, i2c, fdisk and other disk tools, PCI/SCSI, adduser family, inetd, tftp, wget, traceroute,
  nslookup, telnet client, ip rule/neigh/tunnel aliases, uu*, base32, ...) and the features IPv6 (the kernel has none),
  verbose usage texts, CIFS mount, extra filesystem probes. `tests/fixtures/busybox-6.6-applets.txt` is the applet list
  of the new build (`busybox.links` of the build tree, last path component, C sort).
- alsa-lib: only pcm and mixer; PCM plugins limited to what `plughw` (`aplay -D plughw:0,0`) and the default device need.
  The microphone path (`arecord -D hw:0,0`, tc100_rtsp) uses the `hw` PCM, which is always built. No alsactl, alsamixer (so no ncurses).
- hostapd: nl80211 only, no ACS, VLAN, Hotspot 2.0, Interworking, 802.11ax, pre-authentication, ERP (external.mk); this
  drops libnl-route. wpa_supplicant: no TDLS, no fast BSS transition. dropbear: server and scp only (no dbclient/ssh).
- post-build.sh: single CA certificates (only the bundle is read), PCI card configs of alsa, the sample hostapd.conf, libgcc_s
  (no binary of the image needs it), unused libnl libraries (dependents are tested first).
- The CI `base` job (`.github/workflows/build-base-rootfs.yml`) builds from scratch on every run; only the download
  directory is cached. A local incremental rebuild: reuse a Buildroot output tree, run `make ... tc100_defconfig`,
  `make <pkg>-dirclean` for the packages whose options changed, delete `output/target` and every
  `build/*/.stamp_target_installed`, then `make`; stale files in the staging sysroot (old alsa headers) can break an
  incremental build, a clean tree cannot.
