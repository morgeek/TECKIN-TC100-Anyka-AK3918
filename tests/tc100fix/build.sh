#!/bin/sh
# Build the ARM test fixtures for test_tc100fix_* (needs the Anyka toolchain).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
: "${CROSS:?set CROSS to the arm-anykav200-linux-uclibcgnueabi- prefix}"
"${CROSS}gcc" -march=armv5te -Os -fPIC -shared -o "$here/libfakevendor.so" "$here/fakevendor.c"
"${CROSS}gcc" -march=armv5te -Os -o "$here/driver" "$here/driver.c" -L"$here" -lfakevendor
"${CROSS}gcc" -march=armv5te -Os -fPIC -shared -o "$here/libplat_vpss.so" "$here/fakevpss.c"
"${CROSS}gcc" -march=armv5te -Os -o "$here/ispdriver" "$here/ispdriver.c" -L"$here" -lfakevendor -lplat_vpss
