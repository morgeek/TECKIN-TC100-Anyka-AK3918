#!/bin/sh
# restore-stock.sh [--check] [FLASH-STOCK.BIN]   put the stock TECKIN firmware back into the flash.
#
# Run from the 3.0 trial mode on the SD card (Linux 6.6 started from tc100test/c66.img), over ssh or telnet, or by
# auto-install.sh when RESTAURER.txt is at the root of the card.
# Writes back, from the 8 MiB copy the stock-firmware hook saved (tc100-3/backup/flash-stock.bin), the areas 3.0
# uses: kernel (0x39000, 2 MiB) and initrd + stack + vendor (0x23b000-0x7ee000, the stock A, B and C partitions),
# and erases the settings slots cfga / cfgb (blank in the stock flash). U-Boot, mac and env are not touched: the
# 3.0 boot commands stay in the U-Boot environment but do nothing any more (flashcheck no longer finds an xz image,
# so boot_normal starts the stock firmware), and the 3.0 card still starts the trial mode.
# The copy must be this camera's: its U-Boot and mac areas (never written by 3.0) must equal the flash.
# --check: only the checks of the copy (size, md5, this camera), nothing written; prints "ok ..." and exits 0.
CHECK=; [ "$1" = --check ] && { CHECK=1; shift; }
F=${1:-/mnt/sd/tc100-3/backup/flash-stock.bin}
FLASHW=/mnt/v3/linux66-sd/flashw
W=/mnt/sd/tc100-3/restore
fail() { echo "restore-stock: $*"; exit 1; }
find_mtd() { for d in /sys/class/mtd/mtd[0-9]*; do case $d in *ro) continue;; esac; [ "$(cat $d/name)" = "$1" ] && { echo "${d##*/}"; return 0; }; done; return 1; }
md5() { md5sum | cut -d' ' -f1; }
[ -f /tmp/linux66 ] && [ ! -f /tmp/flashmode ] || fail "run it from the 3.0 trial mode on the SD card"
[ -f "$F" ] || fail "$F not found"
[ "$(wc -c < "$F")" -eq 8388608 ] || fail "$F is not an 8 MiB flash copy"
[ -f "$F.md5" ] || fail "$F.md5 not found (the hook writes it next to the copy)"
sum=$(md5 < "$F"); [ "$sum" = "$(cut -d' ' -f1 "$F.md5")" ] || fail "$F does not match its md5"
for p in boot:0:57 mac:569:1; do	# name:first 4 KiB sector:sectors
	n=${p%%:*}; r=${p#*:}
	m=$(find_mtd $n) || fail "the running kernel has no '$n' flash partition"
	[ "$(dd if=/dev/${m}ro bs=4096 2>/dev/null | md5)" = "$(dd if="$F" bs=4096 skip=${r%:*} count=${r#*:} 2>/dev/null | md5)" ] ||
		fail "the $n area of $F is not this camera's: it is the copy of another camera"
done
[ -n "$CHECK" ] && { echo "ok: tc100-3/backup/flash-stock.bin, md5 $sum, U-Boot and mac of this camera"; exit 0; }
mkdir -p "$W"
cut_part() { dd if="$F" of="$W/$1.bin" bs=4096 skip=$(( $2 / 4096 )) count=$(( $3 / 4096 )) 2>/dev/null; }
cut_part kernel 0x39000 0x200000
cut_part initrd 0x23b000 0x200000
cut_part stack 0x43b000 0x2b3000
cut_part vendor 0x6ee000 0x100000
dd if=/dev/zero bs=4096 count=9 2>/dev/null | tr '\000' '\377' > "$W/blank.bin"
[ "$(wc -c < "$W/blank.bin")" -eq 36864 ] || fail "could not make the blank slot image"
echo "Writing the stock firmware back (about 10 minutes). Do not unplug the camera."
for p in kernel stack vendor initrd; do
	FLASHW_ALLOW="kernel initrd stack vendor" sh $FLASHW -m "$(md5sum < "$W/$p.bin" | cut -d' ' -f1)" "$p" "$W/$p.bin" || fail "writing $p failed (the 3.0 card still starts the camera)"
done
for p in cfga cfgb; do sh $FLASHW "$p" "$W/blank.bin" || echo "restore-stock: $p not erased (harmless)"; done
rm -rf "$W"
echo "Done. Take the card out and restart the camera: it starts its stock firmware."
