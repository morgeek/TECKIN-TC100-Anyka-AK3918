# Linux 6.6 series for the TECKIN TC100 (AK3918EV300)

Ten patches on top of tag `v6.6`, one per subsystem:

    git clone --depth 1 -b v6.6 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
    cd linux && git am ../patches/kernel-6.6/series/*.patch   # or: git apply

The series is the only source of the kernel changes (CI applies it with `git am`).
Configuration: `../defconfig_cma` (copy to `.config`, then `make olddefconfig`).
The RTL8188FU firmware is embedded: put `rtlwifi/rtl8188fufw.bin` from linux-firmware (tag 20241017) in `firmware/` of the
kernel tree first (CI and `scripts/build-kernel-docker.sh` download it and check its SHA-256).

Whitespace warnings from `git apply` come from the vendor-derived drivers and are harmless.
