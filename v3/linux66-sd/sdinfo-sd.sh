#!/bin/sh
# Fill /tmp/sd-card (read by action.cgi sd_card_info and the status line) and /tmp/sd-health from the card at
# /mnt/sd (flash mode: video storage only; SD mode: the card is also mounted at /mnt). Called by
# action.d/storage.sh and once a minute by scripts/web-guard.sh.
S=/sys/block/mmcblk0
if ! [ -b /dev/mmcblk0 ] || [ "$(cat $S/size 2>/dev/null || echo 0)" = 0 ]; then
  printf 'present=0\nkind=none\nmounted=0\nprompt=0\n' > /tmp/sd-card
  rm -f /tmp/sd-health
  exit 0
fi
size=$(( $(cat $S/size) / 2048 ))
id=$(cat $S/device/cid 2>/dev/null); [ -n "$id" ] || id="size$(cat $S/size)"
m=0; free=""; kind=blank; health=""; fs=""
while read -r _d _mp _fs _opt _rest; do
  case "$_mp $_fs" in
    "/mnt/sd vfat"|"/mnt/sd exfat"|"/mnt vfat")
      m=1; kind=data; fs=$_fs
      case ",$_opt," in *,ro,*) health=readonly ;; *) health=ok ;; esac ;;
  esac
done < /proc/mounts
if [ "$m" = 1 ]; then
  free=$(df -k /mnt/sd 2>/dev/null | awk 'NR>1{print int($4/1024); exit}')
  [ -n "$(ls -A /mnt/sd 2>/dev/null | grep -v '^sd$' | head -n 1)" ] || kind=empty
  [ -f /tmp/flashmode ] || kind=sdmode   # SD mode: the card carries the firmware
fi
printf 'present=1\nid=%s\nsize_mb=%s\nfs=%s\nkind=%s\nmounted=%s\nfree_mb=%s\nprompt=0\n' "$id" "$size" "$fs" "$kind" "$m" "$free" > /tmp/sd-card.tmp &&
  mv -f /tmp/sd-card.tmp /tmp/sd-card
if [ -n "$health" ]; then echo "state=$health" > /tmp/sd-health; else rm -f /tmp/sd-health; fi
exit 0
