#!/bin/sh
# Item 35: the WHEP daemon against a real WebRTC client (aiortc), inside a container (run by
# `sh tests/docker/local-ci.sh whep` and by the CI job "whep-interop"). Builds mbedTLS 2.28.9 the way the base image
# does (default configuration + MBEDTLS_SSL_DTLS_SRTP), the daemon against it with -Wall -Wextra -Werror, runs the host
# unit tests, then tests/whep_interop.py: a fake RTSP source (H.264 from aiortc's own encoder, PCMA), the daemon, and
# aiortc as the browser. Needs: gcc, make, python3-pip, bzip2, curl (python:3.12-bookworm has them), network access.
set -eu
REPO=$(cd "$(dirname "$0")/../.." && pwd)
W=${WHEP_WORK:-/tmp/whep-work}
MB=2.28.9
mkdir -p "$W"; cd "$W"
if [ ! -f "mbedtls-$MB/library/libmbedtls.a" ]; then
	rm -rf "mbedtls-$MB"
	curl -sfL --retry 3 "https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-$MB/mbedtls-$MB.tar.bz2" | tar xj
	cd "mbedtls-$MB"
	python3 scripts/config.py set MBEDTLS_SSL_DTLS_SRTP
	python3 scripts/config.py set MBEDTLS_SSL_EXPORT_KEYS 2>/dev/null || true
	make -s -j"$(nproc)" lib >/dev/null
fi
cd "$W"
gcc -O2 -Wall -Wextra -Werror -Wno-unused-function -o whep_test "$REPO/src/whep/whep_test.c"
./whep_test
gcc -Os -Wall -Wextra -Werror -I "mbedtls-$MB/include" -o tc100-whep "$REPO/src/whep/tc100_whep.c" \
	-L "mbedtls-$MB/library" -lmbedtls -lmbedx509 -lmbedcrypto
strip tc100-whep
echo "tc100-whep (host build, stripped, bytes): $(wc -c < tc100-whep)"
pip install -q aiortc 2>&1 | tail -2
cd "$REPO"
WHEP_DEBUG="${WHEP_DEBUG:-}" WHEP_BIN="$W/tc100-whep" LD_LIBRARY_PATH="$W/mbedtls-$MB/library" python3 tests/whep_interop.py -v
