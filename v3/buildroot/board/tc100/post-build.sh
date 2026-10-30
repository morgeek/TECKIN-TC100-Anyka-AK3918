#!/bin/sh
# Run by Buildroot on the target tree ($1).  Keeps the image small and credential-free.
set -eu
T=$1
rm -rf "$T"/usr/share/man "$T"/usr/share/doc "$T"/usr/share/info "$T"/usr/include "$T"/usr/lib/pkgconfig
rm -f "$T"/usr/bin/aserver "$T"/usr/bin/alsaucm 2>/dev/null || true
# PCI sound card configurations (272 KB; the camera has one fixed codec) and the sample hostapd.conf (128 KB;
# wifi-rescue.sh writes its own).  libgcc_s is needed by no binary of the image (readelf -d), only C++ and unwinding.
rm -rf "$T"/usr/share/alsa/cards "$T"/etc/hostapd.conf
rm -f "$T"/lib/libgcc_s.so* 2>/dev/null || true
mkdir -p "$T"/mnt/sd "$T"/opt/v3
# no password, no Wi-Fi credentials in the base image: S39tc100 sets them at boot
sed -i 's|^root:[^:]*:|root:*:|' "$T"/etc/shadow
: > "$T"/etc/wpa_supplicant.conf

# Runtime libraries copied from the toolchain that nothing here uses (our own binaries are static).
rm -f "$T"/usr/lib/libgfortran.so* "$T"/usr/lib/libquadmath.so* "$T"/usr/lib/libgomp.so* \
      "$T"/usr/lib/libitm.so* "$T"/usr/lib/libssp.so* "$T"/usr/lib/libstdc++.so* \
      "$T"/lib/libgfortran.so* "$T"/lib/libstdc++.so* 2>/dev/null || true
# The CA bundle is installed once (etc/ssl/certs); drop the second copy.
rm -rf "$T"/usr/share/ca-certificates
# etc/ssl/certs: only the bundle is read (curl, v3/build-stack.sh); the 140 single certificates and their hash links are not
find "$T"/etc/ssl/certs -mindepth 1 ! -name ca-certificates.crt -delete 2>/dev/null || true
# Drop libraries no other file refers to (e.g. libnl-route, only a dependency of the full libnl).
# (dependents first: libnl-cli and -nf need libnl-route, so route goes last)
for l in libnl-cli-3 libnl-nf-3 libnl-idiag-3 libnl-xfrm-3 libnl-route-3; do
  for f in "$T"/usr/lib/$l.so*; do
    [ -e "$f" ] || continue
    if ! grep -rl --exclude="$l.so*" --exclude="*.la" --exclude="*.pc" "$l.so" "$T"/usr "$T"/lib 2>/dev/null | grep -q .; then rm -f "$T"/usr/lib/$l.so*; fi
  done
done
