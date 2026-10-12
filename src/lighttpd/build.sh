#!/bin/sh
# Rebuild bin/lighttpd (1.4.69, static plugin set) with the Anyka uClibc
# toolchain (https://github.com/ricardojlrufino/arm-anykav200-crosstool).
#
# Plugins compiled in: see plugin-static.h. 1.8.4 adds mod_setenv, mod_expire,
# mod_deflate (with zlib linked statically: the camera has no libz),
# mod_access and mod_accesslog to the nine of the original binary.
# OpenSSL 3.1.0 and PCRE2 10.42 are linked dynamically against the copies
# already shipped in lib/ (only their headers are needed here).
#
# The toolchain binaries are 32-bit x86: on a 64-bit Debian/Ubuntu host run
#   dpkg --add-architecture i386 && apt-get install libc6:i386 zlib1g:i386
# Needs: git, cmake, ninja, perl (OpenSSL header generation).
#
# Usage: TC=/path/to/arm-anykav200-crosstool/usr src/lighttpd/build.sh [workdir]
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
: "${TC:?set TC to the arm-anykav200-crosstool/usr directory}"
W=${1:-/tmp/lighttpd-build}
X=$TC/bin/arm-anykav200-linux-uclibcgnueabi-
P=$W/prefix
# The toolchain's cc1 needs its own 32-bit libmpc/libgmp.
export LD_LIBRARY_PATH="$TC/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$W" "$P/include" "$P/lib/pkgconfig"
cd "$W"

clone() { [ -d "$2" ] || git clone -q --depth 1 -b "$3" "$1" "$2"; }
clone https://github.com/lighttpd/lighttpd1.4.git lighttpd lighttpd-1.4.69
clone https://github.com/madler/zlib.git zlib v1.3.1
clone https://github.com/openssl/openssl.git openssl openssl-3.1.0
clone https://github.com/PCRE2Project/pcre2.git pcre2 pcre2-10.42

# zlib, static
(cd zlib && CC=${X}gcc AR=${X}ar RANLIB=${X}ranlib \
  CFLAGS="-Os -march=armv5te -mtune=arm926ej-s -fPIC" \
  ./configure --static --prefix="$P" >/dev/null && make -s libz.a && make -s install >/dev/null)

# OpenSSL / PCRE2 headers matching lib/libssl.so.3, lib/libpcre2-8.so.0
(cd openssl && [ -f include/openssl/configuration.h ] || \
  { ./Configure linux-armv4 no-asm no-tests >/dev/null && make -s build_generated >/dev/null; })
cp -r openssl/include/openssl "$P/include/"
sed -e 's/@PCRE2_MAJOR@/10/;s/@PCRE2_MINOR@/42/;s/@PCRE2_PRERELEASE@//;s/@PCRE2_DATE@/2022-12-11/' \
  pcre2/src/pcre2.h.in > "$P/include/pcre2.h"
for l in libssl.so.3 libcrypto.so.3 libpcre2-8.so.0; do cp "$root/lib/$l" "$P/lib/"; done
ln -sf libssl.so.3 "$P/lib/libssl.so"; ln -sf libcrypto.so.3 "$P/lib/libcrypto.so"
ln -sf libpcre2-8.so.0 "$P/lib/libpcre2-8.so"
cat > "$P/lib/pkgconfig/libpcre2-8.pc" <<PC
Name: libpcre2-8
Description: pcre2 (camera copy)
Version: 10.42
Libs: -L$P/lib -lpcre2-8
Cflags: -I$P/include
PC

cp "$here/plugin-static.h" lighttpd/src/plugin-static.h
cat > toolchain.cmake <<TCF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_C_COMPILER ${X}gcc)
set(CMAKE_AR ${X}ar)
set(CMAKE_RANLIB ${X}ranlib)
set(CMAKE_FIND_ROOT_PATH $P $TC/arm-anykav200-linux-uclibcgnueabi/sysroot)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_C_FLAGS "-Os -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft" CACHE STRING "")
TCF
rm -rf build && mkdir build
(cd build && PKG_CONFIG_LIBDIR="$P/lib/pkgconfig" PKG_CONFIG_PATH= cmake -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$W/toolchain.cmake" -DCMAKE_BUILD_TYPE=MinSizeRel \
  -DCMAKE_SKIP_RPATH=ON -DBUILD_STATIC=ON \
  -DWITH_OPENSSL=ON -DWITH_PCRE2=ON -DWITH_ZLIB=ON \
  -DZLIB_LIBRARY="$P/lib/libz.a" -DZLIB_INCLUDE_DIR="$P/include" \
  -DOPENSSL_ROOT_DIR="$P" -DOPENSSL_INCLUDE_DIR="$P/include" \
  -DOPENSSL_SSL_LIBRARY="$P/lib/libssl.so" -DOPENSSL_CRYPTO_LIBRARY="$P/lib/libcrypto.so" \
  ../lighttpd >/dev/null && ninja lighttpd >/dev/null)

cp build/build/lighttpd "$root/bin/lighttpd"
"${X}strip" "$root/bin/lighttpd"
md5sum "$root/bin/lighttpd"
