#!/bin/sh
# collect-vendor.sh SRC DEST   copy the camera's own vendor libraries that the 3.0 firmware needs
# collect-vendor.sh -c SRC     only check that SRC has them all
#   SRC   a root to search (/ under the stock firmware, or a folder that already holds them, e.g. /mnt/lib)
#   DEST  folder that receives them, each under the name programs ask for (plain files: a FAT card has no links)
# These files are not free and are never published: the 3.0 firmware takes them from the camera it runs on.
# Runs under the stock firmware's old busybox too (no tr, no readlink -f). Exit 1 when one is missing.
CHECK=; [ "$1" = -c ] && { CHECK=1; shift; }
SRC=${1:?usage: collect-vendor.sh SRC DEST | -c SRC}
DEST=${2:-}
[ -n "$CHECK$DEST" ] || { echo "usage: collect-vendor.sh SRC DEST | -c SRC"; exit 2; }
# uClibc runtime of the stock toolchain, then the encoder control libraries
VENDOR_LIBS="ld-uClibc.so.0 libc.so.0 libdl.so.0 libm.so.0 libpthread.so.0 librt.so.0 libgcc_s.so.1 libstdc++.so.6
libakv_encode.so libplat_common.so libplat_drv.so libplat_ipcsrv.so libplat_thread.so libplat_venc_cb.so"
[ -n "$CHECK" ] || mkdir -p "$DEST" || exit 1
# the same files under their full names (a FAT card holds no links, so older cards have only these)
alt() {
	case "$1" in
	ld-uClibc.so.0) echo ld-uClibc-0.9.33.2.so ;;
	libc.so.0) echo libuClibc-0.9.33.2.so ;;
	libstdc++.so.6) echo libstdc++.so.6.0.19 ;;
	esac
}
miss=
for n in $VENDOR_LIBS; do
	ok=
	for d in "$SRC" "$SRC/lib" "$SRC/usr/lib" "$SRC/usr/local/lib"; do
		for f in $n $(alt $n); do
			[ -f "$d/$f" ] || continue
			if [ -n "$CHECK" ]; then ok=1
			else cp "$d/$f" "$DEST/$n.tmp" && mv -f "$DEST/$n.tmp" "$DEST/$n" && ok=1
			fi
			break
		done
		[ -n "$ok" ] && break
	done
	[ -n "$ok" ] || miss="$miss $n"
done
[ -z "$miss" ] || { echo "collect-vendor: missing:$miss"; exit 1; }
exit 0
