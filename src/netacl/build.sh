#!/bin/sh
# Build lib/libnetacl.so with the Anyka uClibc toolchain (src/netacl/netacl.c).
# Host build for the tests: gcc -shared -fPIC -o x.so netacl.c -ldl
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
: "${CROSS:?set CROSS to the arm-anykav200-linux-uclibcgnueabi- prefix}"
"${CROSS}gcc" -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -Os -fPIC -shared -Wall -Wextra -Werror \
    -o "$root/lib/libnetacl.so" "$here/netacl.c" -ldl
"${CROSS}strip" --strip-unneeded "$root/lib/libnetacl.so"
md5sum "$root/lib/libnetacl.so"
