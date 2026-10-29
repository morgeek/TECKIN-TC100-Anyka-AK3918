#!/bin/sh
# hwcheck.sh INVENTORY [BOARD_DIR]   which board profile is this camera?
#
# Compares an inventory (v3/install/inventory.sh output) with each v3/board/*.conf. Prints "board=<file name>" and
# exits 0 for the first profile that matches, or prints "unknown: <what differs>" and exits 1. Read-only.
#   sensor  the id logged by the 3.0 kernel when there is one (SENSOR_ID), else the stock sensor module
#           (STOCK_SENSOR_MODULE): the stock kernel's log does not keep the id
#   Wi-Fi   USB vendor:product (WIFI_USB)
#   flash   size (FLASH_SIZE), and the JEDEC id or part name when the kernel reports them (FLASH_JEDEC, FLASH_NAME);
#           HWCHECK_FLASH_ID=1 (the flash install, on Linux 6.6) also refuses a chip the kernel did not identify
INV=${1:?usage: hwcheck.sh INVENTORY [BOARD_DIR]}
BD=${2:-$(cd "$(dirname "$0")/../board" 2>/dev/null && pwd)}
# an applet missing from the camera's own busybox: the card's busybox (bin/busybox, 1.35) has them all
for a in sed awk tr md5sum cut grep head tail readlink; do
	command -v $a >/dev/null 2>&1 && continue
	for b in /mnt/bin/busybox /mnt/sd/bin/busybox; do [ -x $b ] && { eval "$a() { $b $a \"\$@\"; }"; break; }; done
done
iv() { sed -n "s/^$1=//p" "$INV" | head -n 1; }
bv() { sed -n "s/^$1=//p" "$2" | head -n 1; }
[ -r "$INV" ] || { echo "unknown: no inventory ($INV)"; exit 1; }
sid=$(iv sensor_id); smod=$(iv sensor_module); wifi=$(iv wifi_usb)
fsz=$(iv flash_size); fj=$(iv flash_jedec); fn=$(iv flash_name)
why=
for f in "$BD"/*.conf; do
	[ -f "$f" ] || continue
	b=${f##*/}; b=${b%.conf}; r=
	if [ -n "$sid" ] && [ "$sid" != unknown ]; then
		[ "$sid" = "$(bv SENSOR_ID "$f")" ] || r="$r sensor $sid"
	elif [ -n "$smod" ] && [ "$smod" != unknown ]; then
		[ "$smod" = "$(bv STOCK_SENSOR_MODULE "$f")" ] || r="$r sensor module $smod"
	else r="$r sensor not identified"; fi
	echo " $wifi " | grep -q " $(bv WIFI_USB "$f") " || r="$r Wi-Fi $wifi"
	[ "$fsz" = "$(bv FLASH_SIZE "$f")" ] || r="$r flash size $fsz"
	if [ -n "$fj$fn" ] && [ "$fj" != unknown -o "$fn" != unknown ]; then
		[ "$fj" = "$(bv FLASH_JEDEC "$f")" ] || [ "$(echo "$fn" | awk '{ print tolower($0) }')" = "$(bv FLASH_NAME "$f")" ] || r="$r flash chip $fj $fn"
	elif [ -n "$HWCHECK_FLASH_ID" ]; then r="$r flash chip not identified"
	fi
	[ -z "$r" ] && { echo "board=$b"; exit 0; }
	why="$why [$b:$r]"
done
[ -n "$why" ] || why=" no board profile in $BD"
echo "unknown:$why"
exit 1
