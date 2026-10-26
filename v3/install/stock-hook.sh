#!/bin/sh
# wifitest/wifi_test.sh of the 3.0 SD card: first start of a TECKIN TC100 that still runs its stock firmware.
#
# The stock firmware runs /mnt/wifitest/wifi_test.sh when that folder is on the card (a factory test hook) instead of
# the cloud app, with the card mounted at /mnt. This script, once:
#   1. checks that this is the camera the 3.0 firmware was made for (partition table, md5 of the stock /usr, and of
#      U-Boot and the stock root filesystem when tc100-3/known-stock.txt lists them), and that the U-Boot
#      environment reads correctly and has the stock "boot_normal" command;
#   2. saves the whole flash (8 MiB) on the card: tc100-3/backup/flash-stock.bin (read twice, md5 compared);
#   3. copies the camera's own vendor libraries (uClibc runtime, video encoder) into lib/ of the card: the 3.0
#      firmware needs them and they are never published;
#   4. adds the 3.0 boot commands to the U-Boot environment (tc100-3/envtool, environment backed up first):
#        bootcmd = run sdload sdboot; run flashcheck flashboot; run boot_normal
#      sdload/sdboot start Linux 6.6 from this card (tc100test/c66.img); flashcheck/flashboot start the 3.0 firmware
#      from the flash once it is installed there (they check that the "initrd" area holds an xz image, which the
#      stock firmware never has); boot_normal is the stock start, unchanged: without a card, or with a card without
#      tc100test/c66.img, the camera starts its stock firmware as before.
#   5. restarts: U-Boot then starts Linux 6.6 from the card (trial mode). Nothing else in the flash is written.
# Any doubt: nothing is written, the reason is in tc100-3/STATUS.txt, and the camera stays on its stock firmware
# (without the cloud app while this card is in). U-Boot itself is never written.
C=/mnt
K=$C/tc100-3
LOG=$K/STATUS.txt
MTD=/dev/mtd
MTD_TABLE='mtd0: 00800000 00001000 "spi0.0"
mtd1: 00200000 00001000 "KERNEL"
mtd2: 00001000 00001000 "MAC"
mtd3: 00001000 00001000 "ENV"
mtd4: 00180000 00001000 "A"
mtd5: 0007d000 00001000 "B"
mtd6: 003b6000 00001000 "C"'
INITRD_SIZE=2012654
BOOTARGS="initrd=0x81000000,$INITRD_SIZE console=ttySAK0,115200n8 mem=64M panic=10 ak_wdt_reboot=300 initcall_blacklist=gpio_keys_init oops=panic cma=18M root=/dev/ram0 rdinit=/init"

say() { echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$LOG"; sync; }
stop() { say "STOPPED: $*"; say "Nothing was written to the flash. The camera keeps its stock firmware."; exit 1; }
md5() { md5sum | cut -d' ' -f1; }

mkdir -p "$K/backup" || exit 1
say "3.0 install, step 1 (stock firmware): $(cat $C/VERSION 2>/dev/null)"
[ -f "$K/stage1.done" ] && stop "step 1 was already done ($K/stage1.done): the camera should start from the card. Check that tc100test/c66.img is on it."
for f in "$K/envtool" "$C/tc100test/c66.img" "$C/tc100test/c66rd.gz" "$C/v3/install/collect-vendor.sh"; do
	[ -f "$f" ] || stop "$f is missing from the card (copy the whole 3.0 package)"
done
for f in c66.img c66rd.gz; do
	want=$(cut -d' ' -f1 "$C/tc100test/$f.md5" 2>/dev/null)
	[ -n "$want" ] && [ "$(md5 < "$C/tc100test/$f")" = "$want" ] || stop "tc100test/$f does not match its md5 (copy it again)"
done
[ "$(wc -c < "$C/tc100test/c66rd.gz")" -eq $INITRD_SIZE ] || stop "tc100test/c66rd.gz is not $INITRD_SIZE bytes"

# 1. Is this the camera?
[ "$(grep '^mtd' /proc/mtd)" = "$MTD_TABLE" ] || stop "the flash partitions are not the ones of a TECKIN TC100 (8 MB, 7 partitions)"
uboot=$(dd if=${MTD}0 bs=4096 count=57 2>/dev/null | md5)
rootfs=$(dd if=${MTD}4 bs=4096 2>/dev/null | md5)
usr=$(dd if=${MTD}6 bs=4096 2>/dev/null | md5)
# /usr: the stock one, or the one the 2.x firmware put there when it was installed to flash (its own install
# checked the stock V1.1.41 /usr first and kept the vendor libraries in it)
usrkind=other
[ "$usr" = "$(awk '$1 == "usr" { print $2; exit }' "$K/known-stock.txt" 2>/dev/null)" ] && usrkind=stock
[ $usrkind = other ] && [ -e /usr/tc100/VERSION ] && [ "$(dd if=${MTD}6 bs=4 count=1 2>/dev/null)" = hsqs ] && usrkind="2.x $(cat /usr/tc100/VERSION)"
{ echo "uboot $uboot"; echo "rootfs $rootfs"; echo "usr $usr"; echo "usrkind $usrkind"; } > "$K/camera.txt"
say "camera: U-Boot $uboot, root $rootfs, /usr $usr ($usrkind)"
for k in uboot rootfs usr; do
	case "$k:$usrkind" in usr:2.x*) continue ;; esac
	want=$(awk -v k=$k '$1 == k { print $2; exit }' "$K/known-stock.txt" 2>/dev/null)
	eval got=\$$k
	[ -z "$want" ] && { say "note: no known $k md5 to compare with"; continue; }
	[ "$got" = "$want" ] && continue
	[ -e "$K/ALLOW-OTHER-STOCK" ] && { say "WARNING: $k differs from the tested camera, going on (ALLOW-OTHER-STOCK)"; continue; }
	stop "$k ($got) is not the one of the TECKIN TC100 firmware V1.1.41 this was tested with ($want). Create tc100-3/ALLOW-OTHER-STOCK on the card to try anyway (at your own risk)."
done
chmod 755 "$K/envtool"
"$K/envtool" show ${MTD}3 > "$K/env-stock.txt" 2>&1 || stop "the U-Boot environment does not read correctly: $(tail -n 1 "$K/env-stock.txt")"
grep -q '^boot_normal=' "$K/env-stock.txt" || stop "the U-Boot environment has no boot_normal command"
grep -q '^bootcmd=' "$K/env-stock.txt" || stop "the U-Boot environment has no bootcmd"

# 2. The whole flash on the card
say "saving the whole flash (8 MB, the system it runs now) to tc100-3/backup/flash-stock.bin..."
dd if=${MTD}0 of="$K/backup/flash-stock.bin" bs=65536 2>/dev/null && sync
a=$(md5 < "$K/backup/flash-stock.bin"); b=$(dd if=${MTD}0 bs=65536 2>/dev/null | md5)
[ "$a" = "$b" ] && [ "$(wc -c < "$K/backup/flash-stock.bin")" -eq 8388608 ] || stop "the flash copy on the card differs from the flash (card?)"
echo "$a  flash-stock.bin" > "$K/backup/flash-stock.bin.md5"
say "flash saved, md5 $a. KEEP IT: it is the way back to the system the camera had before 3.0 ($usrkind), and it holds vendor files: do not publish it."

# 3. Vendor libraries of this camera, for the 3.0 firmware
sh "$C/v3/install/collect-vendor.sh" / "$C/lib" >> "$LOG" 2>&1 || stop "the camera's libraries could not be copied to the card"
sync
say "vendor libraries copied to lib/"

# 3b. Settings and Wi-Fi of the system the camera runs now, so that the trial mode starts with them: the 2.x
#     firmware installed to flash keeps them in jffs2; the stock firmware has its Wi-Fi in anyka_cfg.ini.
#     Files already on the card win.
P=/etc/jffs2/tc100
mkdir -p "$C/config"
if [ -d "$P/config" ]; then
	for f in "$P"/config/* "$P"/config/.wizard_done; do
		[ -e "$f" ] || continue
		n=${f##*/}
		case "$n" in *.dist|*.pre-migrate|*.expired|*.bak*|*-bak|openssl.cnf|packages.lock|ssl|.lkg|lighttpd*) continue ;; esac
		[ -e "$C/config/$n" ] || cp -r "$f" "$C/config/" 2>/dev/null
	done
	say "settings of the 2.x firmware copied to config/"
fi
W=$C/config/wpa_supplicant.conf
if [ ! -f "$W" ]; then
	if [ -f "$P/wpa_supplicant.conf" ]; then cp "$P/wpa_supplicant.conf" "$W"
	elif [ -r /etc/jffs2/anyka_cfg.ini ]; then
		awk -f "$C/v3/install/anyka-wifi.awk" /etc/jffs2/anyka_cfg.ini > "$W.tmp" && mv "$W.tmp" "$W" || rm -f "$W.tmp"
	fi
	[ -f "$W" ] && chmod 600 "$W" && say "Wi-Fi settings of the camera copied to config/wpa_supplicant.conf"
fi
sync

# 4. Boot commands
grep -q '^flashcheck=' "$K/env-stock.txt" && say "note: 3.0 boot commands already present, written again"
"$K/envtool" set ${MTD}3 "$K/backup/env-stock.bin" \
	"sdload=fatload mmc 0 0x82000000 tc100test/c66.img; fatload mmc 0 0x81000000 tc100test/c66rd.gz" \
	"sdboot=setenv bootargs $BOOTARGS; bootm 0x82000000" \
	"flashcheck=sf probe 0:0 20000000 0; sf read 0x81000000 0x23b000 0x1ec000; mw.b 0x80800000 0xfd; mw.b 0x80800001 0x37; mw.b 0x80800002 0x7a; mw.b 0x80800003 0x58; mw.b 0x80800004 0x5a; mw.b 0x80800005 0x00; cmp.b 0x80800000 0x81000000 6" \
	"flashboot=sf read 0x82000000 0x39000 0x200000; setenv bootargs $BOOTARGS flashroot=1; bootm 0x82000000" \
	"bootcmd=run sdload sdboot; run flashcheck flashboot; run boot_normal" >> "$LOG" 2>&1
rc=$?
case $rc in
	0) ;;
	4) stop "the U-Boot environment could not be written; the original was put back (envtool $rc)" ;;
	5) say "FAILED: the U-Boot environment could not be written nor restored (envtool 5). U-Boot will use its built-in environment: the camera starts its stock firmware. Backup: tc100-3/backup/env-stock.bin"; exit 1 ;;
	*) stop "envtool failed ($rc)" ;;
esac
"$K/envtool" show ${MTD}3 > "$K/env-3.0.txt" 2>&1
date > "$K/stage1.done"; sync
say "step 1 DONE: restarting; the camera now starts the 3.0 firmware from this card (trial mode)."
sleep 2
reboot
