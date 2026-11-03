#!/bin/sh
# Fill /tmp/sd-card (read by action.cgi sd_card_info and the status line) and /tmp/sd-health from the card at
# /mnt/sd (flash mode: video storage only; SD mode: the card is also mounted at /mnt). Called by
# action.d/storage.sh and once a minute by scripts/web-guard.sh.
# (shell built-ins where possible: web-guard.sh runs this whenever the card state changes, the status line reads the result)
S=/sys/block/mmcblk0
ssz=0; [ -r $S/size ] && read -r ssz < $S/size
if ! [ -b /dev/mmcblk0 ] || [ "$ssz" = 0 ]; then
  printf 'present=0\nkind=none\nmounted=0\nprompt=0\n' > /tmp/sd-card
  rm -f /tmp/sd-health
  exit 0
fi
size=$(( ssz / 2048 ))
id=""; [ -r $S/device/cid ] && read -r id < $S/device/cid; [ -n "$id" ] || id="size$ssz"
m=0; free=""; kind=blank; health=""; fs=""
while read -r _d _mp _fs _opt _rest; do
  case "$_mp $_fs" in
    "/mnt/sd vfat"|"/mnt/sd exfat"|"/mnt vfat")
      m=1; kind=data; fs=$_fs
      case ",$_opt," in *,ro,*) health=readonly ;; *) health=ok ;; esac ;;
  esac
done < /proc/mounts
if [ "$m" = 1 ]; then
  # free space: 4th column of the first data line of df (MB); one df, no awk
  free=""; _n=0
  while read -r _dv _dt _du _da _rest; do
    _n=$((_n + 1)); [ "$_n" -gt 1 ] || continue
    case "$_da" in ''|*[!0-9]*) ;; *) free=$((_da / 1024)) ;; esac
    break
  done <<EOF_DF
$(df -k /mnt/sd 2>/dev/null)
EOF_DF
  # anything on the card besides the "sd" folder (the alias of the SD mode)? ls -A | grep | head, in the shell
  kind=empty
  for _f in /mnt/sd/* /mnt/sd/.[!.]* /mnt/sd/..?*; do
    [ -e "$_f" ] || [ -L "$_f" ] || continue
    [ "${_f##*/}" = sd ] && continue
    kind=data; break
  done
  [ -f /tmp/flashmode ] || kind=sdmode   # SD mode: the card carries the firmware
fi
printf 'present=1\nid=%s\nsize_mb=%s\nfs=%s\nkind=%s\nmounted=%s\nfree_mb=%s\nprompt=0\n' "$id" "$size" "$fs" "$kind" "$m" "$free" > /tmp/sd-card.tmp &&
  mv -f /tmp/sd-card.tmp /tmp/sd-card
# THE one scanner of the kernel log for card errors (FAT, I/O, card status) and the one writer of /tmp/sd-health:
# state=ok | errors (the kernel logged card errors since boot) | readonly, errors=<count>, readonly=0|1.
# Everybody else only reads it (status line, dashboard, Disk page, mqtt-bridge.sh, log-persist.sh, scripts/sd-diag.sh).
errs=0
if [ -n "$health" ]; then
  errs=$(dmesg 2>/dev/null | grep -c -E 'FAT-fs .*error|exFAT.*error|I/O error.*mmcblk|mmcblk0.*(timeout|error)|get_card_status wait too long')
  case "$errs" in ''|*[!0-9]*) errs=0 ;; esac
  [ "$health" = ok ] && [ "$errs" -gt 0 ] && health=errors
  printf 'state=%s\nerrors=%s\nreadonly=%s\n' "$health" "$errs" "$([ "$health" = readonly ] && echo 1 || echo 0)" > /tmp/sd-health.tmp &&
    mv -f /tmp/sd-health.tmp /tmp/sd-health
else
  rm -f /tmp/sd-health
fi
exit 0
