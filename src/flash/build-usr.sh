#!/bin/sh
# Build a replacement for flash partition C (/usr, mtd6) from the camera's own
# /usr (extracted from a flash dump: unsquashfs of mtd6) — no vendor binary is
# stored in this repository.
#
# What changes compared with the vendor /usr (everything else is copied as is,
# byte for byte):
#   - removed: the cloud application and what only it uses (anyka_ipc,
#     hostapd, test/demo programs except ak_ao_demo/ak_ai_demo, libapp_*,
#     libzbar, libwolfmqtt, libiconv/iconv, voice prompts *.mp3, nooie tools,
#     ca.crt.pem). The SD firmware never runs them (stop_cloud, WIFI_TEST).
#   - sbin/service.sh: the SD card keeps priority — with /mnt/wifitest on the
#     card the boot is exactly the vendor one (the SD firmware starts). Only
#     without it, instead of the cloud app: /etc/jffs2/tc100/boot.sh if
#     present (writable, no reflash needed), else a rescue telnetd on port 23.
#   - added: /usr/tc100 (bin, lib, VERSION) — HTTP-only binaries for a future
#     firmware run from flash; nothing uses them yet.
#
# Usage: src/flash/build-usr.sh <vendor-usr-dir> <tc100-dir> <out.img>
# The result must fit mtd6: 0x3B6000 = 3,891,200 bytes (checked).
set -eu
SRC=$1; TC=$2; OUT=$3
MAX=3891200
[ -x "$SRC/sbin/service.sh" ] && [ -f "$SRC/modules/8188fu.ko" ] || { echo "not a vendor /usr: $SRC" >&2; exit 1; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
cp -a "$SRC" "$W/usr"
cd "$W/usr"
for b in bin/ak_*_demo bin/ak_lib_version; do
  case "$b" in bin/ak_ao_demo|bin/ak_ai_demo) ;; *) rm -f "$b" ;; esac
done
rm -f bin/anyka_ipc bin/hostapd bin/ca.crt.pem bin/get_nooie_uid bin/set_nooie_ssid \
      bin/iconv lib/libiconv.so lib/libapp_*.so lib/libzbar.so* lib/libwolfmqtt.so* share/*.mp3

# service.sh: replace the cloud start of the normal (non-test) branch.
python3 - sbin/service.sh <<'PY'
import sys
p = sys.argv[1]
s = open(p, 'rb').read()
old = (b'\t\tdaemon\n\t\techo 1 > /sys/class/leds/red_led/brightness\n'
       b'\t\t/usr/sbin/anyka_ipc.sh start \n')
new = (b'\t\t# TC100: no SD firmware (/mnt/wifitest) on this boot. Instead of the\n'
       b'\t\t# cloud app: /etc/jffs2/tc100/boot.sh if present, else a rescue telnetd.\n'
       b'\t\techo 1 > /sys/class/leds/red_led/brightness\n'
       b'\t\tif [ -x /etc/jffs2/tc100/boot.sh ]; then\n'
       b'\t\t\t/etc/jffs2/tc100/boot.sh &\n'
       b'\t\telse\n'
       b'\t\t\ttelnetd -p 23\n'
       b'\t\tfi\n')
if s.count(old) != 1:
    sys.exit('service.sh: expected block not found exactly once')
open(p, 'wb').write(s.replace(old, new))
PY
sh -n sbin/service.sh

mkdir -p tc100
cp -a "$TC/bin" "$TC/lib" tc100/
[ -f "$TC/VERSION" ] && cp "$TC/VERSION" tc100/
chmod -R 755 tc100/bin tc100/lib
cd "$W"
mksquashfs usr "$OUT" -comp xz -b 131072 -noappend -no-xattrs -quiet >/dev/null
size=$(stat -c %s "$OUT")
if [ "$size" -gt "$MAX" ]; then echo "error: $OUT is $size bytes, mtd6 holds $MAX" >&2; rm -f "$OUT"; exit 1; fi
echo "$OUT: $size of $MAX bytes ($((MAX - size)) free), md5 $(md5sum "$OUT" | cut -d' ' -f1)"
