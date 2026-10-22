#!/bin/sh
# Run by Buildroot on the target tree ($1).  Keeps the image small and credential-free.
set -eu
T=$1
rm -rf "$T"/usr/share/man "$T"/usr/share/doc "$T"/usr/share/info "$T"/usr/include "$T"/usr/lib/pkgconfig
rm -f "$T"/usr/bin/aserver "$T"/usr/bin/alsaucm 2>/dev/null || true
mkdir -p "$T"/mnt/sd "$T"/opt/v3
# no password, no Wi-Fi credentials in the base image: S39tc100 sets them at boot
sed -i 's|^root:[^:]*:|root:*:|' "$T"/etc/shadow
: > "$T"/etc/wpa_supplicant.conf
