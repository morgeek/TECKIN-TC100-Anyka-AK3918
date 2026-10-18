#!/bin/sh
# Build bin/tc100-button with the Anyka uClibc toolchain. Host build for the
# tests: gcc -o x tc100-button.c
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
: "${CROSS:?set CROSS to the arm-anykav200-linux-uclibcgnueabi- prefix}"
"${CROSS}gcc" -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -Os -Wall -Wextra -Werror \
    -o "$root/bin/tc100-button" "$here/tc100-button.c"
"${CROSS}strip" --strip-unneeded "$root/bin/tc100-button"
md5sum "$root/bin/tc100-button"
