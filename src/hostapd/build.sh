#!/bin/sh
# Build bin/hostapd-rtw: hostapd for the camera's Realtek USB Wi-Fi (RTL8188FU),
# which only speaks the old wireless-extensions interface (no nl80211): the
# Realtek "rtl871xdrv" driver of hostapd 0.8.x_rtw. Used by the Wi-Fi rescue
# access point (scripts/wifi-rescue.sh) when the system image has no
# /usr/bin/hostapd (the flash /usr drops the vendor copy to save space).
#
# Source: github.com/jenssegers/RTL8188-hostapd (Realtek's hostapd
# 0.8.x_rtw_r7475, BSD licence, see its COPYING), pinned commit below.
# Minimal build (src/hostapd/hostapd.config): rtl871xdrv, WPA2-PSK with the
# internal crypto, 802.11n; no RADIUS, EAP or WPS.
#
# Usage: CROSS=/path/to/arm-anykav200-linux-uclibcgnueabi- src/hostapd/build.sh [workdir]
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
: "${CROSS:?set CROSS to the arm-anykav200-linux-uclibcgnueabi- prefix}"
REPO=https://github.com/jenssegers/RTL8188-hostapd.git
COMMIT=44d73276cb59bf58c700b70f2237ffb440b94ec3
work=${1:-$(mktemp -d)}
[ -d "$work/src/.git" ] || git clone -q "$REPO" "$work/src"
git -C "$work/src" checkout -q "$COMMIT"
cp "$here/hostapd.config" "$work/src/hostapd/.config"
make -C "$work/src/hostapd" clean >/dev/null
CFLAGS="-Os -march=armv5te -mtune=arm926ej-s -MMD -Wall" CC="${CROSS}gcc" make -C "$work/src/hostapd" -j4 hostapd >/dev/null
"${CROSS}strip" -o "$root/bin/hostapd-rtw" "$work/src/hostapd/hostapd"
chmod 755 "$root/bin/hostapd-rtw"
md5sum "$root/bin/hostapd-rtw"
