#!/bin/sh
# Build an HTTP-only curl 8.1.2 (HTTP, MQTT, RTSP; no TLS, libcurl linked
# statically, only uClibc dynamic) with the Anyka uClibc toolchain. 330 KB
# instead of bin/curl + lib/libcurl.so.4.8.0 + libssl/libcrypto: meant for a
# /usr image in the camera's flash, where the 1.5 MB of OpenSSL does not fit.
# The SD-card firmware keeps bin/curl (HTTPS, Telegram).
#
# Covers what the firmware uses curl for: Frigate API and local CGI over
# HTTP, MQTT (mqtt-bridge), RTSP DESCRIBE (self-tests), ONVIF health check.
#
# Usage: TC=/path/to/arm-anykav200-crosstool/usr src/curl/build.sh [workdir]
# Output: <workdir>/curl-notls
set -eu
: "${TC:?set TC to the arm-anykav200-crosstool/usr directory}"
W=${1:-/tmp/curl-build}
X=$TC/bin/arm-anykav200-linux-uclibcgnueabi-
export LD_LIBRARY_PATH="$TC/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$W" && cd "$W"
V=8.1.2
SHA=31b1118eb8bfd43cd95d9a3f146f814ff874f6ed3999b29d94f4d1e7dbac5ef6
[ -f curl-$V.tar.xz ] || curl -sSL -o curl-$V.tar.xz \
  https://github.com/curl/curl/releases/download/curl-$(echo $V | tr . _)/curl-$V.tar.xz
echo "$SHA  curl-$V.tar.xz" | sha256sum -c -
rm -rf curl-$V && tar xf curl-$V.tar.xz
cd curl-$V
CC=${X}gcc AR=${X}ar RANLIB=${X}ranlib STRIP=${X}strip \
CFLAGS="-Os -march=armv5te -mtune=arm926ej-s -ffunction-sections -fdata-sections" \
LDFLAGS="-Wl,--gc-sections" ./configure --host=arm-linux-uclibcgnueabi --prefix=/usr \
  --disable-shared --enable-static --without-ssl --without-zlib --without-brotli \
  --without-zstd --without-libpsl --without-libidn2 --without-nghttp2 --without-libssh2 \
  --disable-ldap --disable-ldaps --disable-ftp --disable-file --disable-dict \
  --disable-gopher --disable-imap --disable-pop3 --disable-smtp --disable-smb \
  --disable-telnet --disable-tftp --enable-http --enable-mqtt --enable-rtsp \
  --disable-manual --disable-ntlm --disable-kerberos-auth --disable-negotiate-auth \
  --disable-alt-svc --disable-hsts --disable-cookies --disable-unix-sockets \
  --disable-docs --disable-threaded-resolver --enable-ipv6 >/dev/null
make -j"$(nproc)" -s curl_LDFLAGS=-all-static >/dev/null
cp src/curl "$W/curl-notls"
"${X}strip" "$W/curl-notls"
md5sum "$W/curl-notls"
