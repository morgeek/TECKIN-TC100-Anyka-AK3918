#!/bin/sh
# Build a replacement for flash partition C (/usr, mtd6) from the camera's own
# /usr (extracted from a flash dump: unsquashfs of mtd6) — no vendor binary is
# stored in this repository.
#
# hostapd is kept: scripts/wifi-rescue.sh runs the rescue access point with it.
#
# What changes compared with the vendor /usr (everything else is copied as is,
# byte for byte):
#   - removed: the cloud application and what only it uses (anyka_ipc,
#     test/demo programs except ak_ao_demo/ak_ai_demo, libapp_*,
#     libzbar, libwolfmqtt, libiconv/iconv, voice prompts *.mp3, nooie tools,
#     ca.crt.pem, daemon, cmd_serverd, ccli), vendor libraries no process
#     loads, USB gadget modules and unused vendor tools. The SD firmware never
#     runs them (stop_cloud, WIFI_TEST).
#   - sbin/service.sh: the SD card keeps priority — with /mnt/wifitest on the
#     card the boot is exactly the vendor one (the SD firmware starts). Only
#     without it, instead of the cloud app: /etc/jffs2/tc100/boot.sh if
#     present (writable, no reflash needed), else a rescue telnetd on port 23.
#   - added: /usr/tc100 (bin, lib, VERSION) — HTTP-only binaries for a future
#     firmware run from flash; nothing uses them yet.
#
# <tc100-dir> is made by src/flash/stage-tc100.sh. VENDOR_WPA=wrapper replaces
# the vendor wpa_supplicant 0.8 by a wrapper around 2.11 (needed for room once
# the firmware code is in /usr/tc100).
#
# Usage: [VENDOR_WPA=wrapper] src/flash/build-usr.sh <vendor-usr-dir> <tc100-dir> <out.img>
# The result must fit mtd6: 0x3B6000 = 3,891,200 bytes (checked).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$1" && pwd); TC=$(cd "$2" && pwd)
case "$3" in /*) OUT=$3 ;; *) OUT=$(pwd)/$3 ;; esac
MAX=3891200
[ -x "$SRC/sbin/service.sh" ] && [ -f "$SRC/modules/8188fu.ko" ] || { echo "not a vendor /usr: $SRC" >&2; exit 1; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
cp -a "$SRC" "$W/usr"
cd "$W/usr"
for b in bin/ak_*_demo bin/ak_lib_version; do
  case "$b" in bin/ak_ao_demo|bin/ak_ai_demo) ;; *) rm -f "$b" ;; esac
done
rm -f bin/anyka_ipc bin/ca.crt.pem bin/get_nooie_uid bin/set_nooie_ssid \
      bin/iconv lib/libiconv.so lib/libapp_*.so lib/libzbar.so* lib/libwolfmqtt.so* share/*.mp3
# Never loaded on the camera (no process maps them; only disk_repair, itself
# unused, needs two of them), USB gadget/burn modules, vendor tools nothing
# here runs (daemon and cmd_serverd: cloud watchdog and command server).
rm -f lib/libmpi_adec.so lib/libmpi_aed.so lib/libmpi_muxer.so lib/libmpi_venc.so \
      lib/libplat_ats.so lib/libplat_drv.so lib/libplat_its.so lib/libplat_tw.so \
      modules/g_file_storage.ko modules/g_mass_storage.ko modules/udc.ko \
      modules/usbburn.ko modules/ak_videobuf_block.ko \
      bin/wpa_passphrase bin/get_device_id bin/top_thread bin/daemon bin/getconf \
      bin/ldd bin/cmd_serverd bin/ccli bin/disk_repair
# VENDOR_WPA=wrapper: the vendor wpa_supplicant 0.8 (164 KB) becomes a wrapper
# running 2.11 from /usr/tc100 (src/flash/wpa_supplicant-wrapper.sh).
if [ "${VENDOR_WPA:-keep}" = wrapper ]; then
  [ -x "$TC/bin/wpa_supplicant" ] || { echo "no $TC/bin/wpa_supplicant for the wrapper" >&2; exit 1; }
  cp "$here/wpa_supplicant-wrapper.sh" bin/wpa_supplicant
  chmod 755 bin/wpa_supplicant
fi

# service.sh: replace the cloud start of the normal (non-test) branch.
python3 - sbin/service.sh <<'PY'
import sys
p = sys.argv[1]
s = open(p, 'rb').read()
old = (b'\t\tdaemon\n\t\techo 1 > /sys/class/leds/red_led/brightness\n'
       b'\t\t/usr/sbin/anyka_ipc.sh start \n')
new = (b'\t\t# TC100: no firmware on the SD card (/mnt/wifitest) on this boot: run\n'
       b'\t\t# the firmware from flash instead of the cloud app. A writable\n'
       b'\t\t# /etc/jffs2/tc100/boot.sh (tests) wins over /usr/tc100/scripts/flashboot.sh;\n'
       b'\t\t# without either, a rescue telnetd.\n'
       b'\t\techo 1 > /sys/class/leds/red_led/brightness\n'
       b'\t\tTC100_FLASH=1\n'
       b'\t\tif [ -x /etc/jffs2/tc100/boot.sh ]; then\n'
       b'\t\t\t/etc/jffs2/tc100/boot.sh &\n'
       b'\t\telif [ -x /usr/tc100/scripts/flashboot.sh ]; then\n'
       b'\t\t\t/usr/tc100/scripts/flashboot.sh &\n'
       b'\t\telse\n'
       b'\t\t\tTC100_FLASH=0\n'
       b'\t\t\ttelnetd -p 23\n'
       b'\t\tfi\n')
# The vendor network manager would fight the firmware's own Wi-Fi setup.
old2 = b'[ $AGING_TEST = 0 ];then\n\t\techo "start net service......"'
new2 = b'[ $AGING_TEST = 0 ] && [ "${TC100_FLASH:-0}" = 0 ];then\n\t\techo "start net service......"'
if s.count(old2) != 1:
    sys.exit('service.sh: net_manage block not found exactly once')
s = s.replace(old2, new2)
if s.count(old) != 1:
    sys.exit('service.sh: expected block not found exactly once')
open(p, 'wb').write(s.replace(old, new))
PY
sh -n sbin/service.sh

mkdir -p tc100
cp -a "$TC/." tc100/
chmod -R 755 tc100/bin tc100/lib
cd "$W"
mksquashfs usr "$OUT" -comp xz -b 131072 -noappend -no-xattrs -quiet >/dev/null
size=$(stat -c %s "$OUT")
if [ "$size" -gt "$MAX" ]; then echo "error: $OUT is $size bytes, mtd6 holds $MAX" >&2; rm -f "$OUT"; exit 1; fi
echo "$OUT: $size of $MAX bytes ($((MAX - size)) free), md5 $(md5sum "$OUT" | cut -d' ' -f1)"
