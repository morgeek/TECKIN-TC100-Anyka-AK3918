#!/bin/bash
set -e

# Run directly inside an Ubuntu / Debian environment or via Docker
echo "=== Building Linux 6.6 LTS with CMA 16MB for TECKIN TC100 ==="

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build_kernel"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

if [ ! -d linux-src ]; then
  echo "[+] Cloning Linux 6.6 stable tree (Tag v6.6)..."
  git clone --depth 1 -b v6.6 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git linux-src
fi

cd linux-src
git checkout -f

echo "[+] Applying Unified Anyka hardware, CMA 16MB & ALSA audio patch..."
patch -p1 < "$ROOT_DIR/patches/kernel-6.6/linux-6.6-ak3918-v3-unified.patch"

echo "[+] Configuring CMA in kernel..."
cp "$ROOT_DIR/patches/kernel-6.6/defconfig_cma" .config
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- olddefconfig

echo "[+] Compiling kernel..."
make ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu || echo 4)" zImage dtbs

echo "[+] Creating bootable uImage (oipc.img)..."
cat arch/arm/boot/zImage arch/arm/boot/dts/anyka/ak3918ev300-tc100.dtb > arch/arm/boot/zImage-dtb
mkimage -A arm -O linux -T kernel -C none -a 0x80008000 -e 0x80008000 -n "Linux 6.6 True V3 CMA16" -d arch/arm/boot/zImage-dtb "$ROOT_DIR/oipc.img"

echo "[✓] Kernel build complete: $ROOT_DIR/oipc.img"
ls -lh "$ROOT_DIR/oipc.img"
