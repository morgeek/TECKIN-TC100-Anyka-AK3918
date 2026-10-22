# Linux 6.6 series for the TECKIN TC100 (AK3918EV300)

Nine patches on top of tag `v6.6`, one per subsystem:

    git clone --depth 1 -b v6.6 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
    cd linux && git am ../patches/kernel-6.6/series/*.patch   # or: git apply

Applying the whole series gives exactly the tree produced by
`../linux-6.6-ak3918-v3-unified.patch` (generated from it, do not edit by hand).
Configuration: `../defconfig_cma` (copy to `.config`, then `make olddefconfig`).
The RTL8188FU firmware (`../firmware/rtlwifi/rtl8188fufw.bin`) is embedded.

Whitespace warnings from `git apply` come from the vendor-derived drivers and are harmless.
