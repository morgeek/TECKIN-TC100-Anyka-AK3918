# Base root filesystem (Buildroot)

Our own replacement for the OpenIPC image: Buildroot 2024.02.9, Bootlin ARM926 musl
toolchain, BusyBox init, dropbear, wpa_supplicant (nl80211), curl (mbedTLS), jq,
alsa-utils, iw. Kernel and bootloader are not built here.

- `configs/tc100_defconfig`: the configuration. `board/tc100/busybox.fragment`: extra BusyBox applets.
  `board/tc100/post-build.sh`: size trimming, locked root password, empty Wi-Fi config.
- CI: `.github/workflows/build-base-rootfs.yml` (called by the kernel workflow). Output: `rootfs.cpio.gz`,
  uploaded as the artifact `tc100-base-rootfs`; `v3/build-rootfs66.sh` and `v3/build-flash-rootfs66.sh` take it as input.
- Local build: `git clone --branch 2024.02.9 https://github.com/buildroot/buildroot; make -C buildroot BR2_EXTERNAL=$PWD/v3/buildroot O=$PWD/out tc100_defconfig && make -C buildroot O=$PWD/out`.
