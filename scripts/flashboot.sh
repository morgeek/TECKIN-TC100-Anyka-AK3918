#!/bin/sh
# flashboot.sh — start the firmware from the camera's flash when the SD card
# carries no firmware (no /mnt/wifitest, or no card at all).
#
# Called by /usr/sbin/service.sh of the flash /usr image (src/flash/build-usr.sh)
# instead of the vendor cloud app. It rebuilds the SD card layout, so the
# firmware runs unchanged:
#
#   /mnt                     tmpfs, 4 MB cap (logs, runtime files; RAM, lost at reboot)
#   /mnt/{bin,lib}           bind of /usr/tc100/* (read-only)
#   /mnt/{scripts,controlscripts,www,sounds}, autorun.sh, VERSION
#                            from the code zone (flash-code.sh) when valid,
#                            else from /usr/tc100 — mounted on /tmp/tc100code
#   /mnt/config              bind of /etc/jffs2/tc100/config (flash, kept across reboots)
#
# /mnt/config only holds the live configuration; the *.dist templates and
# other read-only files are symlinks to /usr/tc100/config, made here when
# missing, so they cost no space in the 500 KB jffs2 partition. The autostart
# directory is copied once (the Services page adds and removes files in it).
#
# In flash mode the Wi-Fi client is wpa_supplicant 2.11 (boot.conf gets
# WIFI_CLIENT=new) and the web server's TLS is mbedTLS (lighttpd.flash.conf,
# HTTPS with the certificate in /mnt/config/lighttpd.pem, HTTP when there is
# none). /tmp/tc100-storage reads "flash".
#
# A card with the firmware (/mnt/wifitest) always wins: service.sh never
# calls this script then.

T="${FLASHBOOT_CODE:-/usr/tc100}"
# Where the code is taken from: the code zone of the KERNEL partition when it
# is valid (scripts/flash-code.sh, updated without touching /usr), else the
# copy in /usr/tc100. Binaries (bin, lib) always come from /usr/tc100.
C="${FLASHBOOT_CODEROOT:-/tmp/tc100code}"
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

mkdir -p "$C"
# A code update not yet confirmed (flash-code.sh write): first boot with it ->
# count it and confirm below once network and web server are up; already
# counted -> it did not come back last time: built-in code again.
PENDING="${FLASHBOOT_PENDING:-$P/code-pending}"
confirm=0
if [ "${FLASHBOOT_ZONE:-1}" = 1 ] && [ -f "$PENDING" ]; then
    read -r p_ver p_boots < "$PENDING"
    if [ "${p_boots:-0}" -ge 1 ]; then
        log "code $p_ver not confirmed after its first boot: back to the built-in code"
        logger -t tc100-event -p user.err "code update $p_ver not confirmed: rolled back to the built-in code" 2>/dev/null
        FC_CLEAR_REASON="rolled back $p_ver (not confirmed)" sh "$T/scripts/flash-code.sh" clear >/dev/null 2>&1
        rm -f "$PENDING"
    else
        echo "$p_ver 1" > "$PENDING"; confirm=1
    fi
fi
if [ "${FLASHBOOT_ZONE:-1}" = 1 ] && [ -x "$T/scripts/flash-code.sh" ] && sh "$T/scripts/flash-code.sh" mount "$C"; then
    log "code from the code zone: $(sh "$T/scripts/flash-code.sh" status)"
else
    [ "${FLASHBOOT_ZONE:-1}" = 1 ] && log "code zone: $(sh "$T/scripts/flash-code.sh" status 2>/dev/null); code from $T"
    mount -o bind "$T" "$C" || rescue "bind code failed"
fi
for d in bin lib; do
    [ -d "$T/$d" ] || continue
    mkdir -p "$M/$d"
    mount -o bind "$T/$d" "$M/$d" || rescue "bind $d failed"
done
for d in scripts controlscripts www sounds; do
    [ -d "$C/$d" ] || continue
    mkdir -p "$M/$d"
    mount -o bind "$C/$d" "$M/$d" || rescue "bind $d failed"
done
ln -s "$C/autorun.sh" "$M/autorun.sh"
cp "$C/VERSION" "$M/VERSION" 2>/dev/null
mkdir -p "$M/log" "$M/DCIM"

# Persistent configuration in jffs2.
mkdir -p "$CFG" || rescue "no $CFG"
[ -d "$CFG/autostart" ] || cp -a "$C/config/autostart" "$CFG/autostart"
chmod 755 "$CFG"/autostart/* 2>/dev/null
# The 0?_system-* boot scripts are firmware code, not a user choice: always
# the image's version (a copy brought from an SD card may be older). The
# other entries are the Services page's on/off switches and stay as they are.
for f in "$C"/config/autostart/0?_system-*; do
    [ -f "$f" ] || continue
    n="$CFG/autostart/${f##*/}"
    [ -L "$n" ] && [ "$(readlink "$n")" = "$f" ] && continue
    rm -f "$n"; ln -s "$f" "$n"
done
for f in "$C"/config/*; do
    [ -f "$f" ] || continue
    n="$CFG/${f##*/}"
    if [ -L "$n" ]; then
        [ "$(readlink "$n")" = "$f" ] && continue
        rm -f "$n"          # a link made by an older layout
    fi
    [ -e "$n" ] || ln -s "$f" "$n"
done
[ -f "$CFG/boot.conf" ] || cp "$C/config/boot.conf.dist" "$CFG/boot.conf"
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
set_key WIFI_CLIENT new
mkdir -p "$M/config"
mount -o bind "$CFG" "$M/config" || rescue "bind config failed"

echo flash > "$STATE"
if [ "$confirm" = 1 ]; then
    ( n=0
      while [ "$n" -lt "${FLASHBOOT_CONFIRM_TRIES:-30}" ]; do
          sleep "${FLASHBOOT_CONFIRM_STEP:-10}"; n=$((n + 1))
          netstat -ltn 2>/dev/null | grep -qE ':(443|80) ' || continue
          gw="$(route -n 2>/dev/null | awk '$1 == "0.0.0.0" {print $2; exit}')"
          [ -n "$gw" ] && ping -c 1 -W 3 "$gw" >/dev/null 2>&1 || continue
          rm -f "$PENDING"
          log "code $p_ver confirmed (network and web server up)"
          h="${FLASHBOOT_HISTORY:-$P/log/code-updates.log}"; mkdir -p "${h%/*}"
          echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) confirmed $p_ver" >> "$h"; sync
          exit 0
      done
      log "code $p_ver: no network or web server in time, reboot (built-in code next)"
      sync; ${FLASHBOOT_REBOOT:-reboot} ) </dev/null >/dev/null 2>&1 &
fi
log "flash mode: firmware $(cat "$C/VERSION" 2>/dev/null), binaries from $T, config in $CFG"
"$M/autorun.sh" &
