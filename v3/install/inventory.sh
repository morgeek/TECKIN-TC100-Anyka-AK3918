#!/bin/sh
# inventory.sh [--quick]   READ-ONLY hardware inventory of a TECKIN TC100, printed on stdout.
#
# Runs on the stock firmware (Linux 3.4, from the SD card hook), on the 2.x firmware and on 3.0 (Linux 6.6).
# It never writes anything: the flash is only read with "dd if=", nothing is loaded, set or started.
#
# Output: "key=value" lines (what hwcheck.sh compares with the board profiles in v3/board/), then raw sections
# for whoever reads the report. Values that cannot be read are "unknown".
#   --quick  skips the md5 of U-Boot and of the stock partitions (on Linux 6.6 the flash is read slowly, about
#            a minute per MiB); used at each start of 3.0 to choose the board profile.
#
# Nothing personal goes into the report: no MAC address (the "mac" partition is never read), no Wi-Fi settings,
# and the U-Boot environment is printed with its addresses, serial numbers and keys hidden.
# Test hooks: PROC, SYS and DEV may point at a fake tree.
PROC=${PROC:-/proc}; SYS=${SYS:-/sys}; DEV=${DEV:-/dev}
QUICK=0; [ "$1" = --quick ] && QUICK=1
# an applet missing from the camera's own busybox: the card's busybox (bin/busybox, 1.35) has them all
for a in sed awk tr md5sum cut grep head tail readlink; do
	command -v $a >/dev/null 2>&1 && continue
	for b in /mnt/bin/busybox /mnt/sd/bin/busybox; do [ -x $b ] && { eval "$a() { $b $a \"\$@\"; }"; break; }; done
done
TR=tr; command -v tr >/dev/null 2>&1 || type tr 2>/dev/null | grep -q function || TR=
first() { while read -r l; do [ -n "$l" ] && { echo "$l"; return; }; done; echo unknown; }
mtd_by_name() {	# mtd_by_name NAME... -> /dev/mtdN of the first partition with one of these names
	for n in "$@"; do
		d=$(awk -v n="\"$n\"" '$4 == n { sub(":", "", $1); print $1; exit }' $PROC/mtd 2>/dev/null)
		[ -n "$d" ] && { echo $DEV/$d; return 0; }
	done
	return 1
}
md5_of() { dd if="$1" bs=4096 ${2:+count=$2} 2>/dev/null | md5sum | cut -d' ' -f1; }

# --- system
kern=$(cat $PROC/sys/kernel/osrelease 2>/dev/null | first)
case "$kern" in
	3.4*) fw=stock; [ -e /usr/tc100/VERSION ] && fw="2.x $(head -n 1 /usr/tc100/VERSION)" ;;
	6.*) fw="3.0 $(head -n 1 /mnt/VERSION 2>/dev/null)" ;;
	*) fw=unknown ;;
esac
echo "inventory_version=1"
echo "firmware=$fw"
echo "kernel=$kern"
echo "board=$(sed -n 's/^Hardware[[:space:]]*:[[:space:]]*//p' $PROC/cpuinfo 2>/dev/null | first)"
echo "cpu=$(sed -n 's/^Processor[[:space:]]*:[[:space:]]*//p; s/^model name[[:space:]]*:[[:space:]]*//p' $PROC/cpuinfo 2>/dev/null | first)"
echo "ram_kb=$(awk '$1 == "MemTotal:" { print $2 }' $PROC/meminfo 2>/dev/null | first)"
echo "cmdline_mem=$($TR ' ' '\n' < $PROC/cmdline 2>/dev/null | sed -n 's/^mem=//p' | first)"

# --- flash: whole chip size from the partition table (the stock one has a whole-chip "spi0.0" entry; the 3.0 one
#     covers the chip with its partitions)
# hex sizes by hand: not every awk reads "0x..." numbers
fsize=$(awk 'function hex(s,  i, c, n) { n = 0; s = tolower(s)
		for (i = 1; i <= length(s); i++) { c = index("0123456789abcdef", substr(s, i, 1)); if (!c) break; n = n * 16 + c - 1 }
		return n }
	NR > 1 { s = hex($2); if ($4 == "\"spi0.0\"") w = s; t += s }
	END { if (w) printf "%d\n", w; else if (t) printf "%d\n", t }' $PROC/mtd 2>/dev/null)
echo "flash_size=${fsize:-unknown}"
echo "flash_erase=$(awk 'NR == 2 { print $3 }' $PROC/mtd 2>/dev/null | first)"
N=$SYS/bus/spi/devices/spi0.0/spi-nor
echo "flash_jedec=$(cat $N/jedec_id 2>/dev/null | first)"
fname=$(cat $N/partname 2>/dev/null)
[ -n "$fname" ] || fname=$(dmesg 2>/dev/null | sed -n 's/.*spi0\.0: \([A-Za-z0-9_-]*\) (\([0-9]*\) Kbytes).*/\1/p' | head -n 1)
echo "flash_name=$(echo "$fname" | first)"

# --- Wi-Fi: the USB device on the camera's only USB port (hubs and root hubs left out)
wifi=; for d in $SYS/bus/usb/devices/*; do
	[ -r $d/idVendor ] || continue
	case "$(cat $d/bDeviceClass 2>/dev/null)" in 09) continue ;; esac
	v=$(cat $d/idVendor); p=$(cat $d/idProduct 2>/dev/null)
	[ "$v" = 1d6b ] && continue
	wifi="$wifi $v:$p"
done
echo "wifi_usb=$(echo $wifi | first)"
drv=; for i in $SYS/class/net/wlan*; do [ -e $i/device/driver ] && { drv=$(readlink $i/device/driver); drv=${drv##*/}; break; }; done
[ -n "$drv" ] || drv=$(awk '$1 ~ /^(8188fu|8188eu|8189es|8189fs|rtl8xxxu|ssv6x5x|atbm.*|xr819.*)$/ { print $1; exit }' $PROC/modules 2>/dev/null)
echo "wifi_driver=$(echo "$drv" | first)"

# --- sensor: the 3.0 kernel logs the id it matched; the stock kernel only shows its sensor module (its log is
#     flooded by USB messages), and the tuning file names say which sensor the vendor set up
echo "sensor_id=$(dmesg 2>/dev/null | sed -n 's/.*sensor id \(0x[0-9a-fA-F]*\).*/\1/p; s/.*Probing Sensor ID: \(0x[0-9a-fA-F]*\).*/\1/p' | tail -n 1 | first)"
echo "sensor_module=$(awk '$1 ~ /^sensor_/ { print $1; exit }' $PROC/modules 2>/dev/null | first)"
isp=; for d in /etc/jffs2 /usr/local /usr/etc /etc/config /vendor /mnt/config /lib/firmware/anyka; do
	for f in $d/isp_*.conf $d/isp.conf; do [ -f "$f" ] && isp="$isp ${f##*/}"; done
done
echo "isp_conf=$(echo $isp | first)"

# --- U-Boot
B=$(mtd_by_name spi0.0 boot)
ub=unknown	# 228 KiB to read: skipped by --quick (slow on Linux 6.6)
[ $QUICK = 0 ] && [ -n "$B" ] && [ -n "$TR" ] && ub=$(dd if=$B bs=4096 count=57 2>/dev/null | $TR -c '[:print:]' '\n' | grep '^U-Boot 20' | head -n 1 | first)
echo "uboot_version=$ub"
if [ $QUICK = 0 ] && [ -n "$B" ]; then
	echo "uboot_md5=$(md5_of $B 57)"
	A=$(mtd_by_name A) && echo "stock_rootfs_md5=$(md5_of $A)"
	U=$(mtd_by_name C) && echo "stock_usr_md5=$(md5_of $U)"
fi
E=$(mtd_by_name ENV env)
echo "env_bootcmd=$( { [ -n "$E" ] && [ -n "$TR" ] && dd if=$E bs=4 skip=1 count=1023 2>/dev/null | $TR '\0' '\n' | sed -n 's/^bootcmd=//p'; } | first)"

# --- raw sections
echo
echo "## /proc/mtd"; cat $PROC/mtd 2>/dev/null
echo "## /proc/cmdline"; cat $PROC/cmdline 2>/dev/null
echo "## /proc/modules"; cut -d' ' -f1 $PROC/modules 2>/dev/null
echo "## USB devices"
for d in $SYS/bus/usb/devices/*; do [ -r $d/idVendor ] && echo "${d##*/} $(cat $d/idVendor):$(cat $d/idProduct 2>/dev/null) $(cat $d/product 2>/dev/null)"; done
echo "## LEDs"; ls $SYS/class/leds 2>/dev/null
echo "## GPIO chips"; for g in $SYS/class/gpio/gpiochip*; do [ -e $g/base ] && echo "${g##*/} base $(cat $g/base) ngpio $(cat $g/ngpio 2>/dev/null) $(cat $g/label 2>/dev/null)"; done
echo "## I2C devices"; for d in $SYS/bus/i2c/devices/*; do [ -e "$d" ] && echo "${d##*/} $(cat $d/name 2>/dev/null)"; done
echo "## U-Boot environment (addresses, serial numbers and keys hidden)"
[ -n "$E" ] && [ -n "$TR" ] && dd if=$E bs=4 skip=1 count=1023 2>/dev/null | $TR '\0' '\n' | $TR -cd '[:print:]\n' | awk -F= 'NF < 2 { exit }
	{ k = tolower($1) }
	k ~ /(ethaddr|mac|serial|sn$|uid|pass|key|token|secret|ipaddr|serverip|gatewayip)/ { print $1 "=<hidden>"; next } { print }'
exit 0
