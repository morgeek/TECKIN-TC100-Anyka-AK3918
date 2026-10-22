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

# Runtime libraries copied from the toolchain that nothing here uses (our own binaries are static).
rm -f "$T"/usr/lib/libgfortran.so* "$T"/usr/lib/libquadmath.so* "$T"/usr/lib/libgomp.so* \
      "$T"/usr/lib/libitm.so* "$T"/usr/lib/libssp.so* "$T"/usr/lib/libstdc++.so* \
      "$T"/lib/libgfortran.so* "$T"/lib/libstdc++.so* 2>/dev/null || true
# The CA bundle is installed once (etc/ssl/certs); drop the second copy.
rm -rf "$T"/usr/share/ca-certificates
# Drop libraries no other file refers to (e.g. libnl-route, only a dependency of the full libnl).
for l in libnl-route-3 libnl-nf-3 libnl-cli-3 libnl-idiag-3; do
  for f in "$T"/usr/lib/$l.so*; do
    [ -e "$f" ] || continue
    if ! grep -rl --exclude="$l.so*" "$l.so" "$T"/usr "$T"/lib 2>/dev/null | grep -q .; then rm -f "$T"/usr/lib/$l.so*; fi
  done
done
