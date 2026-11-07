#!/bin/sh
# build-musl.sh [DEST]   the musl C library of the camera's base system, for building our programs against it
#
# The 3.0 base system (Buildroot 2024.02, v3/buildroot) runs musl 1.2.4: /lib/ld-musl-arm.so.1 -> /lib/libc.so on the
# camera ("musl libc (arm) Version 1.2.4"). Our daemons (tc100-mqttd, -onvifd, -supervisord, -logfwd, rwconf) and the
# musl build of libnetacl are compiled with the headers and linked against the libc of that same version, dynamically,
# so they use the camera's own libc and no longer the vendor uClibc runtime (2026-11-07).
#
# DEST (default build/musl in the repository) receives a sysroot: include/, lib/ (crt*.o, libc.so, libc.a) and
# bin/musl-gcc, the wrapper that compiles with these headers (REALGCC = the cross compiler, arm-linux-gnueabi-gcc).
# Source: the release tarball, checked against its SHA-256. Done once: DEST/.musl-1.2.4 marks a finished build.
set -e
VER=1.2.4
SHA=7a35eae33d5372a7c0da1188de798726f68825513b7ae3ebe97aaaa52114f039
URL=${MUSL_URL:-https://musl.libc.org/releases/musl-$VER.tar.gz}
CROSS=${CROSS:-arm-linux-gnueabi-}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DEST=${1:-$ROOT/build/musl}
case "$DEST" in /*) ;; *) DEST=$PWD/$DEST ;; esac
# the kernel's user-space headers (linux/, asm/, asm-generic/, sound/, mtd/) of the cross compiler, which musl does
# not have: tc100_rtsp needs V4L2, ALSA and the encoder driver's ioctls (2026-11-07, the musl tc100_rtsp)
kernel_headers() {
	h=$(printf '#include <linux/videodev2.h>\n' | ${CROSS}gcc -E -M -x c - 2>/dev/null | tr ' \\' '\n\n' | grep '/linux/videodev2.h$' | head -1)
	[ -n "$h" ] || { echo "build-musl: no kernel headers in ${CROSS}gcc" >&2; exit 1; }
	inc=$(dirname "$(dirname "$h")")
	for d in linux asm asm-generic sound mtd; do
		[ -d "$inc/$d" ] && [ ! -d "$DEST/include/$d" ] && cp -r "$inc/$d" "$DEST/include/"
	done
	return 0
}
[ -f "$DEST/.musl-$VER" ] && [ -x "$DEST/bin/musl-gcc" ] && { kernel_headers; echo "musl $VER: $DEST (already built)"; exit 0; }
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
if [ -n "${MUSL_TARBALL:-}" ]; then cp "$MUSL_TARBALL" "$W/musl.tar.gz"; else curl -fsSL -o "$W/musl.tar.gz" "$URL"; fi
echo "$SHA  $W/musl.tar.gz" | sha256sum -c - >/dev/null || { echo "build-musl: SHA-256 mismatch" >&2; exit 1; }
tar xzf "$W/musl.tar.gz" -C "$W"
cd "$W/musl-$VER"
# soft float ARMv5TE as everything on the AK3918 (ARM926EJ-S); same build options as Buildroot's musl package
CC=${CROSS}gcc AR=${CROSS}ar RANLIB=${CROSS}ranlib CFLAGS="-Os -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft" \
	./configure --target=arm-linux-musleabi --prefix="$DEST" --syslibdir="$DEST/lib" >/dev/null
make -j"$(nproc 2>/dev/null || echo 2)" AR=${CROSS}ar RANLIB=${CROSS}ranlib > "$W/build.log" 2>&1 ||
	{ tail -20 "$W/build.log" >&2; echo "build-musl: make failed" >&2; exit 1; }
rm -rf "$DEST"
make install AR=${CROSS}ar RANLIB=${CROSS}ranlib >/dev/null
# the wrapper names the cross compiler by default (musl's own default is the host gcc of the configure run)
sed -i "s|\${REALGCC:-[^}]*}|\${REALGCC:-${CROSS}gcc}|" "$DEST/bin/musl-gcc"
kernel_headers
touch "$DEST/.musl-$VER"
echo "musl $VER: $DEST"
