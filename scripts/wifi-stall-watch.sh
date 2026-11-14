#!/bin/sh
# [wifi-counters] One line per second while a Wi-Fi TX stall is running (WIFI-STALL-01, test kernel with patches
# 0020 / 0021; on other kernels the counters that do not exist are skipped).
#   sh /mnt/sd/wifi-stall-watch.sh [seconds] [interface]   (default: until Ctrl-C, wlan0)
#   sh wifi-stall-watch.sh 600 > /tmp/stall.txt &
# Columns: time, tx / rx packets per second (interface statistics), USB interrupts per second, then the read-only
# counters of rtl8xxxu (tx_urb_free tx_urb_min txq_stops txq_wakes tx_urb_err tx_last_ms rx_urb_lost rx_urb_alive)
# and of the Anyka host controller (bulk_out_nak bulk_in_nak bulk_out_oldest_ms bulk_in_oldest_ms). Read-only: nothing is written.
# Reading traps: every interface down/up kills the anchored URBs, so rx_urb_lost rises by up to 32 and tx_urb_err by the
# in-flight count: deltas across an interface restart are not stall evidence. tx_last_ms is 0 until the first TX
# completion after the start. bulk_in_oldest_ms only means "time since the last received frame" (RX URBs stay queued),
# large on a quiet link; bulk_out_oldest_ms is the one that shows a stuck transmit.
# Meaning of the patterns: docs/linux-port/test-queue.md, WIFI-STALL-01, step "counters".
N=${1:-0}
IF=${2:-wlan0}
SYS=${WATCH_SYS:-/sys}		# the two roots can be moved for the tests
PROC=${WATCH_PROC:-/proc}
RTL=$SYS/module/rtl8xxxu/parameters
HCD=$SYS/module/otg_hs/parameters
RTL_NAMES="tx_urb_free tx_urb_min txq_stops txq_wakes tx_urb_err tx_last_ms rx_urb_lost rx_urb_alive"
HCD_NAMES="bulk_out_nak bulk_in_nak bulk_out_oldest_ms bulk_in_oldest_ms"
ST=$SYS/class/net/$IF/statistics

num() { # first line of a file, or nothing when the file is missing
	[ -r "$1" ] && read -r v < "$1" && echo "$v"
}

usb_irq() { # sum of the per-CPU counts of the line(s) of the USB controller in $PROC/interrupts
	awk '/usb|otg/ { for (i = 2; i <= NF && $i ~ /^[0-9]+$/; i++) s += $i } END { print s + 0 }' $PROC/interrupts 2>/dev/null
}

ptx=$(num $ST/tx_packets); prx=$(num $ST/rx_packets); pirq=$(usb_irq)
i=0
while :; do
	sleep 1
	tx=$(num $ST/tx_packets); rx=$(num $ST/rx_packets); irq=$(usb_irq)
	line="$(date +%T) tx/s=$((${tx:-0} - ${ptx:-0})) rx/s=$((${rx:-0} - ${prx:-0})) irq/s=$((irq - pirq))"
	ptx=$tx; prx=$rx; pirq=$irq
	for n in $RTL_NAMES; do
		v=$(num $RTL/$n); [ -n "$v" ] && line="$line $n=$v"
	done
	for n in $HCD_NAMES; do
		v=$(num $HCD/$n); [ -n "$v" ] && line="$line $n=$v"
	done
	echo "$line"
	i=$((i + 1))
	[ "$N" -gt 0 ] && [ "$i" -ge "$N" ] && break
done
exit 0
