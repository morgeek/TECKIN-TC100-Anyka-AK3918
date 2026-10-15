#!/bin/sh
# Assemble /usr/tc100 for the flash /usr image (src/flash/build-usr.sh) from
# the git-tracked firmware, HTTP-only:
#   bin, lib       minus TLS (openssl, libssl, libcrypto), libcurl (curl is
#                  static), libjq/libiconv (unused: jq is static), ONVIF
#                  (monvifd), internet-only or SD-only tools (telegram,
#                  ffmpeg-min-recorder, min-recorder-list); curl replaced by
#                  the HTTP-only build, lighttpd by the mbedTLS one; everything stripped
#   code           autorun.sh VERSION scripts controlscripts www sounds config
#                  (config without ssl/)
#
# Usage: STRIP=<cross-strip> src/flash/stage-tc100.sh <out-dir> <curl-notls> <lighttpd>
# <lighttpd>: TLS=mbedtls src/lighttpd/build.sh (HTTPS) or NO_TLS=1 (HTTP only).
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
out=$1; curl_bin=$2; lighttpd_bin=$3
: "${STRIP:?set STRIP to the arm-anykav200-linux-uclibcgnueabi-strip path}"
rm -rf "$out"; mkdir -p "$out"
cd "$root"
git ls-files -- autorun.sh VERSION bin lib scripts controlscripts www sounds config |
  grep -v -E '^config/ssl/|^bin/(openssl|monvifd|telegram|ffmpeg-min-recorder|min-recorder-list|curl|lighttpd)$|^lib/(libssl|libcrypto|libcurl|libjq|libiconv)' |
while IFS= read -r f; do
  mkdir -p "$out/$(dirname "$f")"; cp -p "$f" "$out/$f"
done
cp "$curl_bin" "$out/bin/curl"; cp "$lighttpd_bin" "$out/bin/lighttpd"
for f in "$out"/bin/* "$out"/lib/*; do
  file -b "$f" | grep -q ELF && "$STRIP" --strip-unneeded "$f"
done
chmod -R 755 "$out/bin" "$out/lib" "$out/scripts" "$out/controlscripts" "$out/autorun.sh"
echo "$out: $(find "$out" -type f | wc -l) files, $(du -sk "$out" | cut -f1) KB"
