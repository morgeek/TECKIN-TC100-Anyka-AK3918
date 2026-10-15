#!/bin/sh
# Build lib/libtc100fix.so with the Anyka uClibc toolchain
# (https://github.com/ricardojlrufino/arm-anykav200-crosstool, gcc 4.8.5 /
# uClibc 0.9.33.2 — the same toolchain that built the camera kernel).
# The toolchain binaries are 32-bit x86: on a 64-bit Debian/Ubuntu host run
#   dpkg --add-architecture i386 && apt-get install libc6:i386 zlib1g:i386
#
# Usage: CROSS=/path/to/arm-anykav200-crosstool/usr/bin/arm-anykav200-linux-uclibcgnueabi- src/tc100fix/build.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
: "${CROSS:?set CROSS to the arm-anykav200-linux-uclibcgnueabi- prefix}"

"${CROSS}gcc" -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -Os \
    -fPIC -shared -Wall -Wextra -Werror \
    -o "$root/lib/libtc100fix.so" "$here/tc100fix.c" "$here/isp_tune.c" "$here/od.c" "$here/rec.c" -ldl -lpthread -lm -lrt
"${CROSS}strip" --strip-unneeded "$root/lib/libtc100fix.so"
md5sum "$root/lib/libtc100fix.so"
