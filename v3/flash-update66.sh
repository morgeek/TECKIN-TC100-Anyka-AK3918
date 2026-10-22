#!/bin/sh
# Write the Linux 6.6 kernel or root filesystem to the SPI NOR flash from Linux 6.6.
# NOT TESTED ON HARDWARE. Dry run by default: nothing is written without --write.
#
#   flash-update66.sh kernel|rootfs IMAGE [--md5 MD5] [--write] [--backup-dir DIR]
#
# Safety rules (the stock update path has none of them):
#   - only the kernel and rootfs partitions can be targeted; U-Boot, table, MAC, ENV never
#   - the image must fit its partition (sector-rounded), and its md5 must match when given
#   - the partition is dumped to the backup dir (default: the SD card) before it is touched
#   - the write is verified by reading the flash back; any difference is reported loudly
#   - needs the mtd partitions to be writable (device tree without read-only, driver write path)
set -eu
PART=${1:?usage: flash-update66.sh kernel|rootfs IMAGE [--md5 MD5] [--write] [--backup-dir DIR]}
IMG=${2:?image}
shift 2
MD5= ; DO=0 ; BK=/mnt/sd/flash-backup
while [ $# -gt 0 ]; do
  case $1 in
    --md5) MD5=$2; shift ;;
    --write) DO=1 ;;
    --backup-dir) BK=$2; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
case $PART in kernel|rootfs) ;; *) echo "only 'kernel' or 'rootfs' may be written" >&2; exit 2 ;; esac

DEV=$(awk -v n="\"$PART\"" '$4==n {sub(":","",$1); print $1}' /proc/mtd)
[ -n "$DEV" ] || { echo "no mtd partition named $PART (see /proc/mtd)" >&2; exit 1; }
SIZE=$(awk -v n="\"$PART\"" '$4==n {print strtonum("0x"$2)}' /proc/mtd 2>/dev/null || true)
[ -n "$SIZE" ] || SIZE=$(( 0x$(awk -v n="\"$PART\"" '$4==n {print $2}' /proc/mtd) ))
IMGSZ=$(wc -c < "$IMG")
ERASE=4096
NEED=$(( (IMGSZ + ERASE - 1) / ERASE * ERASE ))
echo "partition $PART = /dev/$DEV, $SIZE bytes; image $IMGSZ bytes ($NEED in sectors)"
[ "$NEED" -le "$SIZE" ] || { echo "DOES NOT FIT" >&2; exit 1; }
if [ -n "$MD5" ]; then
  got=$(md5sum "$IMG" | cut -d' ' -f1)
  [ "$got" = "$MD5" ] || { echo "md5 mismatch: $got != $MD5" >&2; exit 1; }
fi
mkdir -p "$BK"
BKF=$BK/$PART-$(date +%Y%m%d-%H%M%S).bin
echo "backing up the partition to $BKF"
dd if=/dev/${DEV/mtd/mtdblock} of="$BKF" bs=4096 2>/dev/null || cat /dev/${DEV/mtd/mtdblock} > "$BKF"
[ "$(wc -c < "$BKF")" -eq "$SIZE" ] || { echo "backup has the wrong size" >&2; exit 1; }
echo "backup md5: $(md5sum "$BKF" | cut -d' ' -f1)"
if [ "$DO" != 1 ]; then echo "dry run: nothing written (add --write)"; exit 0; fi

echo "WRITING $PART: do not power off"
flashcp -v "$IMG" "/dev/$DEV"
echo "verifying"
dd if=/dev/${DEV/mtd/mtdblock} bs=$ERASE count=$(( NEED / ERASE )) 2>/dev/null | head -c "$IMGSZ" | md5sum | cut -d' ' -f1 > /tmp/flash.md5
want=$(md5sum "$IMG" | cut -d' ' -f1)
if [ "$(cat /tmp/flash.md5)" = "$want" ]; then echo "OK: $PART written and verified"; else
  echo "VERIFY FAILED: flash differs from the image. Restore $BKF with: flashcp $BKF /dev/$DEV" >&2; exit 1; fi
