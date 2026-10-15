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
# For the /usr image in the camera's flash (no room for OpenSSL's 1.5 MB),
# into $OUT instead of bin/lighttpd:
#   NO_TLS=1      HTTP only (default OUT: <workdir>/lighttpd-notls)
#   TLS=mbedtls   mod_mbedtls with mbedTLS 3.6.2 linked statically, reduced to
#                 a TLS 1.2 ECDHE-ECDSA server (mbedtls-tc100-config.h), +107 KB
#                 compressed; mod_mbedtls-mbedtls3.patch fixes two crashes of
#                 lighttpd 1.4.69 with mbedTLS 3 (default OUT: <workdir>/lighttpd-mbedtls)
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

NO_TLS=${NO_TLS:-0}; TLS=${TLS:-openssl}
MBED=OFF; EXTRA_CFLAGS=""; EXTRA_LDFLAGS=""
(cd lighttpd && git checkout -q -- src/mod_mbedtls.c)
if [ "$NO_TLS" = 1 ]; then
  grep -v mod_openssl "$here/plugin-static.h" > lighttpd/src/plugin-static.h
  SSL=OFF; OUT=${OUT:-$W/lighttpd-notls}
elif [ "$TLS" = mbedtls ]; then
  V=3.6.2; SHA=8b54fb9bcf4d5a7078028e0520acddefb7900b3e66fec7f7175bb5b7d85ccdca
  [ -f mbedtls-$V.tar.bz2 ] || curl -sSL -o mbedtls-$V.tar.bz2 \
    https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-$V/mbedtls-$V.tar.bz2
  echo "$SHA  mbedtls-$V.tar.bz2" | sha256sum -c - >/dev/null
  rm -rf mbedtls-$V && tar xjf mbedtls-$V.tar.bz2
  # The reduced configuration replaces the default one, for the library and
  # for mod_mbedtls alike.
  cp "$here/mbedtls-tc100-config.h" mbedtls-$V/include/mbedtls/mbedtls_config.h
  make -s -C mbedtls-$V/library CC=${X}gcc AR=${X}ar \
    CFLAGS="-Os -std=gnu99 -march=armv5te -mtune=arm926ej-s -ffunction-sections -fdata-sections" \
    static >/dev/null 2>&1
  mkdir -p "$P/mbedtls/lib" && cp -r mbedtls-$V/include/mbedtls mbedtls-$V/include/psa "$P/include/"
  cp mbedtls-$V/library/libmbed*.a "$P/mbedtls/lib/"
  (cd lighttpd && patch -s -p1 < "$here/mod_mbedtls-mbedtls3.patch")
  sed 's/PLUGIN_INIT(mod_openssl)/PLUGIN_INIT(mod_mbedtls)/' "$here/plugin-static.h" > lighttpd/src/plugin-static.h
  SSL=OFF; MBED=ON; OUT=${OUT:-$W/lighttpd-mbedtls}
  EXTRA_CFLAGS="-ffunction-sections -fdata-sections"
  EXTRA_LDFLAGS="-L$P/mbedtls/lib -Wl,--gc-sections"
else
  cp "$here/plugin-static.h" lighttpd/src/plugin-static.h
  SSL=ON; OUT=$root/bin/lighttpd
fi
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
set(CMAKE_C_FLAGS "-Os -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft $EXTRA_CFLAGS" CACHE STRING "")
set(CMAKE_EXE_LINKER_FLAGS "$EXTRA_LDFLAGS" CACHE STRING "")
TCF
rm -rf build && mkdir build
(cd build && PKG_CONFIG_LIBDIR="$P/lib/pkgconfig" PKG_CONFIG_PATH= cmake -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$W/toolchain.cmake" -DCMAKE_BUILD_TYPE=MinSizeRel \
  -DCMAKE_SKIP_RPATH=ON -DBUILD_STATIC=ON \
  -DWITH_OPENSSL=$SSL -DWITH_PCRE2=ON -DWITH_ZLIB=ON \
  -DWITH_MBEDTLS=$MBED -DHAVE_LIBMEDCRYPTO=1 -DHAVE_LIBMEDX509=1 -DHAVE_LIBMBEDX509=1 \
  -DZLIB_LIBRARY="$P/lib/libz.a" -DZLIB_INCLUDE_DIR="$P/include" \
  -DOPENSSL_ROOT_DIR="$P" -DOPENSSL_INCLUDE_DIR="$P/include" \
  -DOPENSSL_SSL_LIBRARY="$P/lib/libssl.so" -DOPENSSL_CRYPTO_LIBRARY="$P/lib/libcrypto.so" \
  ../lighttpd >/dev/null && ninja lighttpd >/dev/null)

cp build/build/lighttpd "$OUT"
"${X}strip" "$OUT"
md5sum "$OUT"
