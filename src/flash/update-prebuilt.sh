#!/bin/sh
# Refresh src/flash/prebuilt/: the stripped binaries the flash /usr image
# carries (stage-tc100.sh). Run after rebuilding curl (src/curl/build.sh) or
# lighttpd (TLS=mbedtls NO_PCRE=1 src/lighttpd/build.sh), or after a change
# of bin/v4l2rtspserver or the live555 / libmpi_venc_ex libraries.
# Usage: STRIP=<arm-anykav200-linux-uclibcgnueabi-strip> src/flash/update-prebuilt.sh <curl-notls> <lighttpd-mbedtls>
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
: "${STRIP:?set STRIP to the arm-anykav200-linux-uclibcgnueabi-strip path}"
pre="$root/src/flash/prebuilt"
mkdir -p "$pre"
"$STRIP" --strip-unneeded -o "$pre/curl" "$1"
"$STRIP" --strip-unneeded -o "$pre/lighttpd" "$2"
"$STRIP" --strip-unneeded -o "$pre/v4l2rtspserver" "$root/bin/v4l2rtspserver"
for l in libBasicUsageEnvironment.so libUsageEnvironment.so libgroupsock.so libliveMedia.so libmpi_venc_ex.so; do
  "$STRIP" --strip-unneeded -o "$pre/$l" "$root/lib/$l"
done
chmod 755 "$pre"/*
ls -l "$pre"
