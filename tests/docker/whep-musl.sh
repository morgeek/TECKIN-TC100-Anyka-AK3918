#!/bin/sh
# tc100-whep compiled with musl, the C library of the camera's user space, against Mbed TLS 3.6.7 (3.6 LTS) with DTLS-SRTP:
# the daemon is a Buildroot package built only in the 40-minute base image build, and the interop test uses glibc,
# which lets a missing header through (a struct timeval broke the base build of 43efa80). Runs in alpine (musl).
#   docker run --rm -v "$PWD:/src:ro" alpine:3.20 sh /src/tests/docker/whep-musl.sh
set -e
. /src/.github/ci-pins.sh
MB=$MBEDTLS_VERSION
apk add -q build-base curl >/dev/null
cd /tmp
fetch_sha256 "$MBEDTLS_SHA256" "mbedtls-$MB.tar.bz2" "$MBEDTLS_URL"
tar xjf "mbedtls-$MB.tar.bz2"
cd "mbedtls-$MB"
sed -i 's|^//#define MBEDTLS_SSL_DTLS_SRTP|#define MBEDTLS_SSL_DTLS_SRTP|' include/mbedtls/mbedtls_config.h
make -j"$(nproc)" lib >/dev/null
cd /tmp
gcc -Os -Wall -Wextra -Werror -I "mbedtls-$MB/include" -o tc100-whep /src/src/whep/tc100_whep.c \
	-L "mbedtls-$MB/library" -lmbedtls -lmbedx509 -lmbedcrypto
ls -l tc100-whep
echo "whep-musl: ok"
