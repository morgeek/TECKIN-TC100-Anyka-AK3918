#!/bin/sh
# Build bin/wpa_supplicant (wpa_supplicant 2.11, BSD licence, w1.fi) for the
# camera with the Anyka uClibc toolchain (see src/tc100fix/build.sh for the
# host setup). Wireless extensions only (the RTL8188FU driver has no
# nl80211), internal crypto (no OpenSSL dependency), no WPS/EAP/P2P.
#
# Usage: CROSS=/path/to/arm-anykav200-linux-uclibcgnueabi- src/wpa_supplicant/build.sh [wpa_supplicant-2.11.tar.gz]
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
: "${CROSS:?set CROSS to the arm-anykav200-linux-uclibcgnueabi- prefix}"
tarball=${1:-wpa_supplicant-2.11.tar.gz}
sha=912ea06f74e30a8e36fbb68064d6cdff218d8d591db0fc5d75dee6c81ac7fc0a
[ -r "$tarball" ] || curl -fsSLo "$tarball" https://w1.fi/releases/wpa_supplicant-2.11.tar.gz
echo "$sha  $tarball" | sha256sum -c -
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
tar -xzf "$tarball" -C "$tmp"
cd "$tmp"/wpa_supplicant-2.11/wpa_supplicant
cp "$here/wpa_supplicant.config" .config
CFLAGS="-Os -march=armv5te -mtune=arm926ej-s -MMD -Wall" make -j"$(nproc)" CC="${CROSS}gcc" wpa_supplicant >/dev/null
"${CROSS}strip" -o "$root/bin/wpa_supplicant" wpa_supplicant
md5sum "$root/bin/wpa_supplicant"
