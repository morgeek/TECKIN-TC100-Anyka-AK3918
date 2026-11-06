#!/bin/sh
# build-stack.sh: the free user space of the 3.0 firmware, from git and the CI build products only.
#
#   v3/build-stack.sh PACK BASE.cpio.gz OUT
#     PACK  folder with the binaries CI compiles: tc100_rtsp, libakuio.so, httpfront, tc100-mdnsd, tc100-mqttd, tc100-onvifd, tc100-supervisord (optional)
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
# the built-in speaker clips as G.711 A-law, half the size (audit 2026-11-06 S7, owner); speaker-play.sh plays both
python3 scripts/pcm2alaw.py "$T/sounds"
mkdir -p "$T/v3/linux66-sd" "$T/config"
cp v3/autorun-linux66.sh v3/selftest66.sh "$T/v3/"
for f in v3/linux66-sd/*; do
	case "${f##*/}" in README.md) continue ;; esac
	cp "$f" "$T/v3/linux66-sd/"
done
[ -d v3/install ] && cp -r v3/install "$T/v3/"
cp -r v3/board "$T/v3/"	# board profiles, chosen at each start (v3/install/hwcheck.sh)
cp config/*.dist "$T/config/"	# the sensor tuning comes from the camera (v3/install)
cp -r config/autostart "$T/config/"
rm -f "$T/config/autostart/ftp-server"
# free uClibc programs of the repo that the 6.6 system uses (run with the camera's own uClibc, see vendor)
mkdir -p "$T/bin" "$T/lib" "$T/tc100test"
for b in busybox isp_flip monvifd rwconf setconf tc100-logfwd telegram; do
	[ -f "bin/$b" ] || { echo "build-stack: bin/$b missing (rwconf and isp_flip are built from src/ by the release build: make -C src/rwconf, see build-kernel-linux66.yml)"; exit 1; }
	cp "bin/$b" "$T/bin/"
done
cp lib/libnetacl.so "$T/lib/"	# the encoder API library comes from the camera too (collect-vendor.sh)
# what CI compiles
cp "$PACK/tc100_rtsp" "$PACK/libakuio.so" "$PACK/httpfront" "$PACK/tc100-mdnsd" "$PACK/tc100-mqttd" "$PACK/tc100-onvifd" "$T/tc100test/"
[ -f "$PACK/tc100-supervisord" ] && cp "$PACK/tc100-supervisord" "$T/tc100test/"
cp v3/linux66-sd/rtsp-launch.sh "$T/tc100test/"
find "$T" \( -name '*.bak*' -o -name '*.orig' -o -name '._*' \) -exec rm -f {} +
# JavaScript and the inline <script>/<style> of the pages minified in this tree only (audit 2026-11-06 S5, owner: not
# the shell, which stays readable over ssh; git keeps the readable files). src/webui/minify.mjs needs esbuild
# (npm install --prefix src/webui): MINIFY_WWW=1 (the CI) makes it mandatory; otherwise a build without it ships the
# files as they are, which work the same, only bigger.
if command -v node >/dev/null 2>&1; then
	node src/webui/minify.mjs "$T/www" && mrc=0 || mrc=$?
else
	echo "build-stack: no node" >&2; mrc=3
fi
if [ "$mrc" != 0 ]; then
	[ "$mrc" = 3 ] && [ "${MINIFY_WWW:-auto}" != 1 ] || { echo "build-stack: web minification failed ($mrc)" >&2; exit 1; }
	echo "build-stack: web files not minified (no esbuild)" >&2
fi
# the big files every page load fetches also as .gz: busybox httpd (FEATURE_HTTPD_GZIP) sends the .gz to browsers that
# accept gzip (about a quarter of the bytes over Wi-Fi) and the plain file otherwise, so a file without .gz still works.
# Only these five (audit 2026-11-06 S1b, owner): a .gz does not compress again in the xz squashfs, and the .gz of
# every page was ~287 KB of the image; the small pages and scripts go plain.
GZ_WWW="scripts/index.bundle.min.js settings.html css/ui.pico.min.css scripts/view_records.bundle.min.js i18n/fr.js"
for f in $GZ_WWW; do
	[ -f "$T/www/$f" ] || { echo "build-stack: www/$f missing (GZ_WWW)" >&2; exit 1; }
	gzip -9 -k -n "$T/www/$f"
done

# 2. Free tools of the Buildroot base that the initramfs leaves out (v3/initramfs-prune.txt), with the libraries
#    they need that the initramfs does not have, and the CA bundle for curl
mkdir "$W/base"; cd "$W/base"
gzip -dc "$BASE" | cpio -idu --quiet --no-absolute-filenames 'bin/*' 'sbin/*' 'usr/*' 'lib/*' 'etc/ssl/*' 2>/dev/null || true
pruned() { grep -vE '^(#|$)' "$REPO/v3/initramfs-prune.txt" | grep -qxF "$1"; }
find_lib() { for d in lib usr/lib; do [ -e "$d/$1" ] && { echo "$d/$1"; return 0; }; done; return 1; }
mkdir -p "$T/ext/bin" "$T/ext/lib" "$T/ext/etc/ssl/certs"
: > "$W/libs"
for b in usr/bin/curl usr/sbin/iw usr/sbin/wpa_cli usr/sbin/hostapd usr/bin/mksquashfs \
	usr/bin/aplay usr/bin/arecord usr/bin/amixer usr/sbin/dropbear; do
	[ -f "$b" ] || { echo "build-stack: $b missing from the base" >&2; exit 1; }
	cp -L "$b" "$T/ext/bin/"
	echo "$b" >> "$W/todo"
done
# fsck.fat (dosfstools, item 41): optional, the base of an older CI run may not have it yet
for b in sbin/fsck.fat usr/sbin/fsck.fat; do
	[ -f "$b" ] && { cp -L "$b" "$T/ext/bin/"; echo "$b" >> "$W/todo"; break; }
done
# tc100-whep (item 35, WebRTC gateway, ~45 KB; built by Buildroot against the system mbedTLS, which is already in ext/lib
# for curl): optional, the base of an older CI run does not have it. Off at run time (boot.conf WHEP=0).
[ -f usr/bin/tc100-whep ] && { cp -L usr/bin/tc100-whep "$T/ext/bin/"; echo usr/bin/tc100-whep >> "$W/todo"; }
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
# ALSA configuration (the initramfs links /usr/share/alsa to /mnt/ext/share/alsa); alsactl init files, ucm and topology
# are not used (no alsactl, no UCM on this sound chip). Of cards/ only aliases.conf: alsa.conf includes it, and without
# it every "-c 0" (amixer -c 0, card names) fails with "cannot stat cards/aliases.conf" (rc7 on IPCAM2). The base image
# drops cards/ (v3/buildroot post-build.sh); then its working part is written here: the four includes at its end define
# sysdefault, dmix and dsnoop (checked against alsa-lib 1.2: same result as the full file); the aliases of PC sound
# cards are not needed
mkdir -p "$T/ext/share/alsa/cards"
for d in usr/share/alsa/*; do
	case "${d##*/}" in init|cards|ucm|ucm2|topology) continue ;; esac
	cp -rL "$d" "$T/ext/share/alsa/"
done
if [ -s usr/share/alsa/cards/aliases.conf ]; then
	cp -L usr/share/alsa/cards/aliases.conf "$T/ext/share/alsa/cards/"
else
	printf '%s\n' '# cards/aliases.conf of alsa-lib without the aliases of PC sound cards (v3/build-stack.sh)' \
		'<confdir:ctl/default.conf>' '<confdir:pcm/default.conf>' '<confdir:pcm/dmix.conf>' '<confdir:pcm/dsnoop.conf>' \
		> "$T/ext/share/alsa/cards/aliases.conf"
fi
for f in ext/bin/aplay ext/bin/arecord ext/bin/amixer ext/bin/dropbear ext/lib/libasound.so.2 ext/share/alsa/alsa.conf \
	ext/share/alsa/cards/aliases.conf ext/share/alsa/ctl/default.conf ext/share/alsa/pcm/default.conf \
	ext/share/alsa/pcm/dmix.conf ext/share/alsa/pcm/dsnoop.conf; do
	[ -s "$T/$f" ] || { echo "build-stack: $f missing from the tree" >&2; exit 1; }
done
cd "$REPO"
# scripts call /mnt/bin/curl: a wrapper (a FAT card cannot hold links). No jq any more (audit 2026-11-06 S1: the two
# scripts that used it read JSON with scripts/jsonflat.awk; jq, libjq and oniguruma were ~110-240 KB of the image)
for b in curl; do printf '#!/bin/sh\nexec /mnt/ext/bin/%s "$@"\n' $b > "$T/bin/$b"; done
chmod -R a+rX "$T"; chmod 755 "$T"/bin/* "$T"/ext/bin/* "$T"/tc100test/tc100_rtsp "$T"/tc100test/httpfront "$T"/tc100test/tc100-mdnsd "$T"/tc100test/tc100-mqttd "$T"/tc100test/tc100-onvifd; [ -f "$T/tc100test/tc100-supervisord" ] && chmod 755 "$T/tc100test/tc100-supervisord"

# 3. The flash image. Left out of it (they stay in the tree, which is the SD card package):
#    - ext/bin/mksquashfs: only the install uses it, and it runs from the card
#    - bin/busybox, the uClibc busybox of the 2.x era (1.1 MB): it is the stock firmware's helper of the SD hook;
#      on 3.0 /mnt/bin/busybox becomes a link to the system busybox, which has every applet the scripts call
#      (tests/test_flash_image.py checks the list)
#    - build and development files that never run on the camera
#    - the 1 kHz test tones sounds/test-1k-m*.pcm (bench only: scripts/generate_sounds.py, and the SD card package)
#    - the style sheets www/css/bulma.1.0.2.purged.min.css, ui-modern.min.css and ui.css: they are
#      the sources of css/ui.bundle.min.css, which is the only one a page loads (the wizard has its own styles);
#      likewise pico-2.0.6.min.css (Pico CSS as published) and pico-shim.css, the sources of css/ui.pico.min.css (the Pico look, item 50)
#    - bin/monvifd, the closed 2.x ONVIF daemon (233 KB, ~70 KB in the image): tc100-onvifd replaces it (audit 2026-11-06
#      S3, owner); it stays in the SD package, where controlscripts/onvif still starts it on ONVIF_IMPL=monvifd
# 128 KiB blocks: a page read from the flash decompresses half as much as with 256 KiB, and the kernel's squashfs
# caches (data, fragment, xz dictionary: one block each) take about 384 KB less RAM; about 45 KB more flash
# (2026-10-30: 2,240,512 B against 2,195,456; lzo 2.96 MB and lz4 3.2-3.9 MB do not fit the 2.83 MB partition)
# -Xbcj arm (item 54): xz also tries the ARM branch filter on every block and keeps it where the block is smaller
# (the ELF programs); the kernel decodes it (CONFIG_XZ_DEC_ARM, CONFIG_XZ_DEC_BCJ) with no extra memory.
# SQFS_BCJ=none builds without it.
case "${SQFS_BCJ:-arm}" in none) bcj= ;; *) bcj="-Xbcj ${SQFS_BCJ:-arm}" ;; esac
# shellcheck disable=SC2086
mksquashfs "$T" "$OUT/stack.sqfs" -comp xz $bcj -b 128K -noappend -all-root -quiet \
	-p "bin/busybox s 777 0 0 /bin/busybox" \
	-e ext/bin/mksquashfs bin/busybox scripts/build-kernel-docker.sh scripts/flash_budget.py scripts/generate_sounds.py scripts/pcm2alaw.py \
	scripts/collect-platform-dump.sh v3/install/envtool.c v3/install/RELEASE-NOTES.md v3/install/README-SD.txt \
	v3/install/LISEZ-MOI.txt v3/install/LISEZ-MOI-INVENTAIRE.txt v3/install/stock-hook.sh \
	sounds/test-1k-m6.pcm sounds/test-1k-m12.pcm sounds/test-1k-m20.pcm \
	www/css/bulma.1.0.2.purged.min.css www/css/ui-modern.min.css www/css/ui.css \
	www/css/pico-2.0.6.min.css www/css/pico-shim.css \
	bin/monvifd
n=$(wc -c < "$OUT/stack.sqfs")
( cd "$OUT" && md5sum stack.sqfs > stack.sqfs.md5 )
echo "stack.sqfs: $n bytes (partition $STACK_MAX)"
du -sk "$T"/* | sort -rn | head -12
[ "$n" -le "$STACK_MAX" ] || { echo "build-stack: stack.sqfs does not fit the stack partition" >&2; exit 1; }
