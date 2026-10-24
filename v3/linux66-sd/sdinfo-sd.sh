#!/bin/sh
# SD-boot stack: fill /tmp/sd-card (read by action.cgi sd_card_info) from the mounted card.
# scripts/sd-card.sh of the original firmware only works when booted from flash.
S=/sys/block/mmcblk0
[ -b /dev/mmcblk0 ] && [ "$(cat $S/size 2>/dev/null || echo 0)" != 0 ] || { printf 'present=0\nkind=none\nmounted=0\nprompt=0\n' > /tmp/sd-card; exit 0; }
size=$(( $(cat $S/size) / 2048 ))
id=$(cat $S/device/cid 2>/dev/null); [ -n "$id" ] || id="size$(cat $S/size)"
m=0; free=""
if grep -q ' /mnt vfat \| /mnt/sd vfat ' /proc/mounts; then
  m=1; free=$(df -k /mnt 2>/dev/null | awk 'NR>1{print int($4/1024); exit}')
fi
printf 'present=1\nid=%s\nsize_mb=%s\nfs=vfat\nkind=data\nmounted=%s\nfree_mb=%s\nprompt=0\n' "$id" "$size" "$m" "$free" > /tmp/sd-card.tmp && mv -f /tmp/sd-card.tmp /tmp/sd-card
