#!/bin/sh
# imgcheck.sh: checks of the kernel and initrd images, sourced by update66.sh (web update) and install66.sh (SD install).
# A kernel that does not start cannot be put right from Linux (U-Boot always loads the kernel partition, the initramfs
# never runs), so both paths refuse a bad image here, before anything is erased. BusyBox ash.
#   kernel_load_max          smallest byte count of the kernel partition that this camera's U-Boot reads
#   kernel_img_check FILE    a uImage (bootm), complete (data size of its header), not larger than kernel_load_max
#   initrd_img_check FILE    the size the boot commands load (initrd=0x81000000,2012654) and an xz image
# the check functions print the reason and return 1 when the image is refused.

# smallest number of bytes of the kernel partition that this camera's U-Boot reads ("sf read 0x82000000 0x39000 SIZE" in
# its environment, read-only here): 0x200000 for the card install, 0x1ce000 for the hand-made commands of 2026-10-24
kernel_load_max() {
	for d in /sys/class/mtd/mtd[0-9]*; do
		case $d in *ro) continue;; esac
		[ "$(cat $d/name)" = env ] || continue
		tr '\000' '\n' < /dev/${d##*/}ro 2>/dev/null | sed -n 's/.*sf read 0x82000000 0x39000 \(0x[0-9a-fA-F]*\).*/\1/p' |
			while read h; do echo $((h)); done | sort -n | head -n 1 | grep .
		return
	done
	return 1
}

initrd_img_check() {
	[ "$(wc -c < "$1")" -eq 2012654 ] || { echo "$(basename "$1") has not the size the boot commands load"; return 1; }
	head -c 6 "$1" | od -An -tx1 | grep -q 'fd 37 7a 58 5a 00' || { echo "$(basename "$1") is not an xz image"; return 1; }
	return 0
}

kernel_img_check() {
	ks=$(wc -c < "$1")
	head -c 4 "$1" | od -An -tx1 | grep -q '27 05 19 56' || { echo "$(basename "$1") is not a U-Boot kernel image (uImage)"; return 1; }
	kd=$(dd if="$1" bs=1 skip=12 count=4 2>/dev/null | od -An -tu1 | awk '{ print (($1 * 256 + $2) * 256 + $3) * 256 + $4 }')
	case "$kd" in ''|*[!0-9]*) echo "$(basename "$1"): unreadable uImage header"; return 1 ;; esac
	[ $((kd + 64)) -le "$ks" ] || { echo "$(basename "$1") is cut short ($ks bytes, its header announces $((kd + 64)))"; return 1; }
	kl=$(kernel_load_max) && [ "$ks" -gt "$kl" ] && { echo "$(basename "$1") ($ks bytes) is larger than the $kl bytes this camera's start commands read from the flash: it would not start"; return 1; }
	return 0
}
