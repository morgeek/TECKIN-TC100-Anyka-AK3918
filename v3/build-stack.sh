#!/bin/sh
# build-stack.sh: the free user space of the 3.0 firmware, from git and the CI build products only.
#
#   v3/build-stack.sh PACK BASE.cpio.gz OUT
#     PACK  folder with the binaries CI compiles: tc100_rtsp, libakuio.so, httpfront
#     BASE  our Buildroot base root filesystem (artifact tc100-base-rootfs)
#     OUT   gets tree/ (the user space as plain files, also what goes on the SD card) and stack.sqfs (+ .md5),
#           the image of the flash partition "stack"
#
# No vendor file goes in: the uClibc runtime and the encoder libraries come from the user's own camera at install
# time (partition "vendor", or lib/ on the card; see v3/install/). Every file is a plain file (no symbolic links),
# so the same tree can be copied to a FAT card. Needs: cpio, gzip, xz, mksquashfs, and readelf (READELF, default
# arm-linux-gnueabi-readelf).
set -eu
PACK=${1:?usage: build-stack.sh PACK BASE.cpio.gz OUT}
BASE=${2:?base rootfs}
OUT=${3:?output folder}
REPO=$(cd "$(dirname "$0")/.." && pwd)
READELF=${READELF:-arm-linux-gnueabi-readelf}
STACK_MAX=${STACK_MAX:-2830336}		# partition "stack": 0x2b3000 bytes
case "$BASE" in /*) ;; *) BASE=$PWD/$BASE ;; esac
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
T=$OUT/tree; rm -rf "$T"; mkdir -p "$T"

# 1. From git: web UI, scripts, services, defaults, sounds, the 6.6 glue and the install / update tools
cd "$REPO"
cp -r www scripts controlscripts sounds VERSION "$T"/
mkdir -p "$T/v3/linux66-sd" "$T/config"
cp v3/autorun-linux66.sh v3/selftest66.sh "$T/v3/"
for f in v3/linux66-sd/*; do
	case "${f##*/}" in README.md) continue ;; esac
	cp "$f" "$T/v3/linux66-sd/"
done
[ -d v3/install ] && cp -r v3/install "$T/v3/"
cp -r v3/board "$T/v3/"	# board profiles, chosen at each start (v3/install/hwcheck.sh)
cp config/*.dist config/openssl.cnf "$T/config/"	# the sensor tuning comes from the camera (v3/install)
cp -r config/autostart "$T/config/"
rm -f "$T/config/autostart/ftp-server"
# free uClibc programs of the repo that the 6.6 system uses (run with the camera's own uClibc, see vendor)
mkdir -p "$T/bin" "$T/lib" "$T/tc100test"
for b in busybox getflag getimage isp_flip monvifd rwconf setconf tc100-logfwd telegram; do cp "bin/$b" "$T/bin/"; done
cp lib/libnetacl.so "$T/lib/"	# the encoder API library comes from the camera too (collect-vendor.sh)
# what CI compiles
cp "$PACK/tc100_rtsp" "$PACK/libakuio.so" "$PACK/httpfront" "$T/tc100test/"
cp v3/linux66-sd/rtsp-launch.sh "$T/tc100test/"
find "$T" \( -name '*.bak*' -o -name '*.orig' -o -name '._*' \) -exec rm -f {} +
# web pages, styles and scripts also as .gz: busybox httpd (FEATURE_HTTPD_GZIP) sends those to browsers that accept
# gzip, about a quarter of the bytes over Wi-Fi (the CGI answers are not concerned)
find "$T/www" -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.svg' \) -size +1k -exec gzip -9 -k -n {} \;

# 2. Free tools of the Buildroot base that the initramfs leaves out (v3/initramfs-prune.txt), with the libraries
#    they need that the initramfs does not have, and the CA bundle for curl
mkdir "$W/base"; cd "$W/base"
gzip -dc "$BASE" | cpio -idu --quiet --no-absolute-filenames 'bin/*' 'sbin/*' 'usr/*' 'lib/*' 'etc/ssl/*' 2>/dev/null || true
pruned() { grep -vE '^(#|$)' "$REPO/v3/initramfs-prune.txt" | grep -qxF "$1"; }
find_lib() { for d in lib usr/lib; do [ -e "$d/$1" ] && { echo "$d/$1"; return 0; }; done; return 1; }
mkdir -p "$T/ext/bin" "$T/ext/lib" "$T/ext/etc/ssl/certs"
: > "$W/libs"
for b in usr/bin/curl usr/bin/jq usr/sbin/iw usr/sbin/wpa_cli usr/sbin/hostapd usr/bin/mksquashfs; do
	[ -f "$b" ] || { echo "build-stack: $b missing from the base" >&2; exit 1; }
	cp -L "$b" "$T/ext/bin/"
	echo "$b" >> "$W/todo"
done
while [ -s "$W/todo" ]; do
	f=$(head -n 1 "$W/todo"); sed -i 1d "$W/todo"
	for n in $($READELF -d "$f" 2>/dev/null | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p'); do
		grep -qxF "$n" "$W/libs" && continue
		echo "$n" >> "$W/libs"
		p=$(find_lib "$n") || { echo "build-stack: library $n not in the base" >&2; exit 1; }
		echo "$p" >> "$W/todo"
		# a library the initramfs keeps is found in /lib or /usr/lib on the camera; the others go to ext/lib
		real=$(readlink -f "$p"); rel=${real#$W/base/}
		if pruned "$p" || pruned "$rel"; then cp -L "$p" "$T/ext/lib/$n"; fi
	done
done
cp -L etc/ssl/certs/ca-certificates.crt "$T/ext/etc/ssl/certs/"
cd "$REPO"
# scripts call /mnt/bin/curl and /mnt/bin/jq: wrappers (a FAT card cannot hold links)
for b in curl jq; do printf '#!/bin/sh\nexec /mnt/ext/bin/%s "$@"\n' $b > "$T/bin/$b"; done
chmod -R a+rX "$T"; chmod 755 "$T"/bin/* "$T"/ext/bin/* "$T"/tc100test/tc100_rtsp "$T"/tc100test/httpfront

# 3. The flash image
# mksquashfs only serves the install, which runs from the card: it stays in the tree (SD), not in the flash image
mksquashfs "$T" "$OUT/stack.sqfs" -comp xz -b 256K -noappend -all-root -quiet -e ext/bin/mksquashfs
n=$(wc -c < "$OUT/stack.sqfs")
( cd "$OUT" && md5sum stack.sqfs > stack.sqfs.md5 )
echo "stack.sqfs: $n bytes (partition $STACK_MAX)"
du -sk "$T"/* | sort -rn | head -12
[ "$n" -le "$STACK_MAX" ] || { echo "build-stack: stack.sqfs does not fit the stack partition" >&2; exit 1; }
