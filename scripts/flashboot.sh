#!/bin/sh
# flashboot.sh — start the firmware from the camera's flash when the SD card
# carries no firmware (no /mnt/wifitest, or no card at all).
#
# Called by /usr/sbin/service.sh of the flash /usr image (src/flash/build-usr.sh)
# instead of the vendor cloud app. It rebuilds the SD card layout, so the
# firmware runs unchanged:
#
#   /mnt                     tmpfs, 4 MB cap (logs, runtime files; RAM, lost at reboot)
#   /mnt/{bin,lib,scripts,controlscripts,www,sounds}   bind of /usr/tc100/* (read-only)
#   /mnt/autorun.sh, VERSION from /usr/tc100
#   /mnt/config              bind of /etc/jffs2/tc100/config (flash, kept across reboots)
#
# /mnt/config only holds the live configuration; the *.dist templates and
# other read-only files are symlinks to /usr/tc100/config, made here when
# missing, so they cost no space in the 500 KB jffs2 partition. The autostart
# directory is copied once (the Services page adds and removes files in it).
#
# In flash mode the web server runs over HTTP (the flash lighttpd has no TLS)
# and the Wi-Fi client is wpa_supplicant 2.11: boot.conf gets WEB_MODE=http
# and WIFI_CLIENT=new. /tmp/tc100-storage reads "flash".
#
# A card with the firmware (/mnt/wifitest) always wins: service.sh never
# calls this script then.

T="${FLASHBOOT_CODE:-/usr/tc100}"
P="${FLASHBOOT_PERSIST:-/etc/jffs2/tc100}"
M="${FLASHBOOT_MNT:-/mnt}"
LOG="${FLASHBOOT_LOG:-/tmp/log/flashboot.log}"
CFG="$P/config"
STATE="${FLASHBOOT_STATE:-/tmp/tc100-storage}"

mkdir -p "${LOG%/*}" 2>/dev/null
log() { echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$LOG"; }

rescue()
{
    log "rescue: $*; telnetd on port 23"
    telnetd -p 23 2>/dev/null
    exit 1
}

[ -x "$T/autorun.sh" ] && [ -d "$T/bin" ] && [ -d "$T/scripts" ] || rescue "no firmware in $T"

# An SD card without the firmware is mounted on /mnt by service.sh: leave it
# out of the way (the firmware would take it for its own card).
if grep -q " $M vfat " /proc/mounts 2>/dev/null || grep -q " $M exfat " /proc/mounts 2>/dev/null; then
    umount "$M" 2>/dev/null || log "could not unmount the SD card from $M"
fi
mount -t tmpfs -o size=4m,mode=0755 tmpfs "$M" || rescue "tmpfs on $M failed"

for d in bin lib scripts controlscripts www sounds; do
    [ -d "$T/$d" ] || continue
    mkdir -p "$M/$d"
    mount -o bind "$T/$d" "$M/$d" || rescue "bind $d failed"
done
ln -s "$T/autorun.sh" "$M/autorun.sh"
cp "$T/VERSION" "$M/VERSION" 2>/dev/null
mkdir -p "$M/log" "$M/DCIM"

# Persistent configuration in jffs2.
mkdir -p "$CFG" || rescue "no $CFG"
[ -d "$CFG/autostart" ] || cp -a "$T/config/autostart" "$CFG/autostart"
for f in "$T"/config/*; do
    [ -f "$f" ] || continue
    n="${f##*/}"
    [ -e "$CFG/$n" ] || [ -L "$CFG/$n" ] || ln -s "$f" "$CFG/$n"
done
[ -f "$CFG/boot.conf" ] || cp "$T/config/boot.conf.dist" "$CFG/boot.conf"
# Rewrite only when a value differs: every write wears the flash.
set_key()
{
    grep -q "^$1=$2\$" "$CFG/boot.conf" 2>/dev/null && return 0
    if grep -q "^$1=" "$CFG/boot.conf" 2>/dev/null; then
        sed -i "s|^$1=.*|$1=$2|" "$CFG/boot.conf"
    else
        echo "$1=$2" >> "$CFG/boot.conf"
    fi
    log "boot.conf: $1=$2"
}
set_key WEB_MODE http
set_key WIFI_CLIENT new
mkdir -p "$M/config"
mount -o bind "$CFG" "$M/config" || rescue "bind config failed"

echo flash > "$STATE"
log "flash mode: firmware $(cat "$T/VERSION" 2>/dev/null) from $T, config in $CFG"
"$M/autorun.sh" &
