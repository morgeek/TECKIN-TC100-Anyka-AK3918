#!/bin/sh
# check-needed.sh ROOT DIR[:DIR...]
#   Fails (exit 1) when a dynamically linked ELF file under ROOT has a NEEDED library (readelf -d) that is not an existing
#   file in one of the DIRs (the musl loader's search path of that image, as absolute paths; a symbolic link must
#   resolve). Used at build time by v3/build-rootfs66.sh (the initramfs: /lib and /usr/lib, because what leaves it through
#   v3/initramfs-prune.txt is not there for the rescue mode, which runs before the user space is mounted) and by
#   v3/build-stack.sh (the user space: its own ext/lib and lib, and the libraries the initramfs keeps), so a prune
#   entry or a base image change cannot leave wpa_supplicant, BusyBox or a daemon without a library.
#   Environment: READELF (default readelf, or arm-linux-gnueabi-readelf when that is the only one), CHECK_SKIP (relative
#   paths under ROOT that are not checked, space separated: the stock uClibc helper bin/busybox of the SD hook).
set -eu
ROOT=${1:?usage: check-needed.sh ROOT DIR[:DIR...]}
DIRS=${2:?usage: check-needed.sh ROOT DIR[:DIR...]}
RE=${READELF:-}
if [ -z "$RE" ]; then
	if command -v readelf >/dev/null 2>&1; then RE=readelf; else RE=arm-linux-gnueabi-readelf; fi
fi
command -v "$RE" >/dev/null 2>&1 || { echo "check-needed: no $RE" >&2; exit 1; }
SKIP=" ${CHECK_SKIP:-} "
bad=0; nelf=0; nneed=0
list=$(mktemp); trap 'rm -f "$list"' EXIT
(cd "$ROOT" && find . -type f ! -path './lib/modules/*' ! -path './lib/firmware/*' ! -name '*.o' | sed 's|^\./||' | LC_ALL=C sort) > "$list"
while IFS= read -r f; do
	case "$SKIP" in *" $f "*) continue ;; esac
	[ "$(head -c 4 "$ROOT/$f" 2>/dev/null | tail -c 3)" = ELF ] || continue
	nelf=$((nelf + 1))
	for n in $("$RE" -d "$ROOT/$f" 2>/dev/null | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p'); do
		nneed=$((nneed + 1))
		found=0
		oldifs=$IFS; IFS=:
		for d in $DIRS; do [ -f "$d/$n" ] && { found=1; break; }; done
		IFS=$oldifs
		[ "$found" = 1 ] || { echo "check-needed: $f needs $n, which is not in $DIRS" >&2; bad=$((bad + 1)); }
	done
done < "$list"
echo "check-needed: $nelf ELF files, $nneed NEEDED entries, $bad unresolved (searched $DIRS)"
[ "$bad" = 0 ] || exit 1
