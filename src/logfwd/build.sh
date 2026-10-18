#!/bin/sh
# Build bin/tc100-logfwd with the Anyka uClibc toolchain (same as
# src/tc100fix/build.sh). Host build for the tests: gcc -o x tc100-logfwd.c
#
# Usage: CROSS=/path/to/arm-anykav200-crosstool/usr/bin/arm-anykav200-linux-uclibcgnueabi- src/logfwd/build.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
: "${CROSS:?set CROSS to the arm-anykav200-linux-uclibcgnueabi- prefix}"

"${CROSS}gcc" -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -Os -Wall -Wextra -Werror \
    -o "$root/bin/tc100-logfwd" "$here/tc100-logfwd.c"
"${CROSS}strip" --strip-unneeded "$root/bin/tc100-logfwd"
md5sum "$root/bin/tc100-logfwd"
