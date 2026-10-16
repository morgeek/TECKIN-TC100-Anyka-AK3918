#!/bin/sh
# usr-update.sh — replace the flash /usr (mtd6) and the code zone from the
# running camera, without SD card and without telnet: Settings → Update &
# backup with a system package (tc100-system-<version>.tar, made on a
# computer by src/flash/build-flash-kit.sh from the camera's original /usr).
#
#   usr-update.sh check <dir>     the unpacked package: ok <version> | refused <reason>
#   usr-update.sh install <dir>   write it and reboot (run from a copy in RAM)
#
# In flash mode the firmware runs from /usr itself: the RTSP server, the web
# server, wpa_supplicant, syslogd, the watchdog feeder — every program started
# from /mnt/bin or /bin/busybox (a bind of /usr/tc100/bin/busybox) pages its
# code from mtd6. "install" therefore runs only rootfs programs (/bin and
# /sbin of partition A: tiny stubs on libbusybox in /lib), from a script
# copied to RAM, and:
#   1. replaces the watchdog feeder by a rootfs loop (the camera would reset
#      8 s after the feeder dies);
#   2. stops every process that maps mtd6 (TERM, then KILL), Wi-Fi included:
#      the page loses the camera for about two minutes;
#   3. writes /usr, flushes, reads it back from /dev/mtd6 (up to 5 writes);
#   4. writes the code zone (scripts/flash-code.sh; it boots "pending" and is
#      confirmed or rolled back like any code update);
#   5. with an SD card in the slot that carries the firmware boot hook
#      (wifitest/), sets up a one-shot boot from flash (flashmode-once.sh), so
#      the new /usr is what starts, not the card;
#   6. reboots.
# If /usr cannot be written back correctly, an SD card with the firmware
# (wifitest/) still starts the camera; without one, U-Boot's SD recovery.
# The package was checked before (check): same original /usr, image md5,
# squashfs with the expected files, valid code package.

MTD="${UU_MTD:-/dev/mtd}"
BLOCK6="${UU_BLOCK6:-/dev/mtdblock6}"
PROC="${UU_PROC:-/proc}"
PROC_MTD="${UU_PROC_MTD:-/proc/mtd}"
JFFS="${UU_JFFS:-/etc/jffs2/tc100}"
STORAGE_FILE="${TC100_STORAGE_FILE:-/tmp/tc100-storage}"
WD="${UU_WATCHDOG:-/dev/watchdog}"
MAPDEV="${UU_MAPDEV:-}"
CARD_DEV="${UU_CARD_DEV:-/dev/mmcblk0}"
STOCK_USR_MD5="${UU_STOCK_USR_MD5:-def1ea44addd7a73d613d8169b395447}"
USR_BYTES=3891200
MTD_C='mtd6: 003b6000 00001000 "C"'
PATH=/bin:/sbin
export PATH

_uu_md5() { md5sum "$1" 2>/dev/null | cut -d' ' -f1; }

uu_check()
{
    D="$1"
    [ "$(cat "$STORAGE_FILE" 2>/dev/null)" = flash ] || { echo "refused only from flash (from the SD card: README, Install to flash)"; return 1; }
    grep -q "^$MTD_C\$" "$PROC_MTD" 2>/dev/null || { echo "refused not the TC100 flash layout"; return 1; }
    for f in usr.img usr.img.md5 code.bin camera.txt VERSION; do
        [ -s "$D/$f" ] || { echo "refused $f missing"; return 1; }
    done
    read -r _v _r < "$D/VERSION"
    read -r _m _r < "$D/usr.img.md5"
    [ "$(_uu_md5 "$D/usr.img")" = "$_m" ] || { echo "refused usr.img damaged (md5)"; return 1; }
    _s=$(wc -c < "$D/usr.img")
    [ "$_s" -gt 0 ] && [ "$_s" -le "$USR_BYTES" ] && [ $((_s % 4096)) -eq 0 ] || { echo "refused usr.img size $_s"; return 1; }
    [ "$(dd if="$D/usr.img" bs=4 count=1 2>/dev/null)" = hsqs ] || { echo "refused usr.img is not a squashfs"; return 1; }
    _base=$(sed -n 's/^usr_md5=//p' "$D/camera.txt")
    _known=$(cat "$JFFS/usr-stock.md5" 2>/dev/null)
    [ "$_base" = "${_known:-$STOCK_USR_MD5}" ] || { echo "refused built from another original /usr ($_base)"; return 1; }
    _c=$(sh "${UU_FLASHCODE:-/mnt/scripts/flash-code.sh}" check "$D/code.bin" 2>/dev/null)
    case "$_c" in "ok $_v "*|"ok $_v") ;; *) echo "refused code.bin: ${_c:-invalid}"; return 1 ;; esac
    # The files a boot from flash needs must be in the image.
    if [ -z "$UU_NO_MOUNT" ]; then
        mkdir -p "$D/m"
        mount -t squashfs -o loop,ro "$D/usr.img" "$D/m" 2>/dev/null || { echo "refused usr.img does not mount"; return 1; }
        _miss=""
        for f in sbin/service.sh tc100/scripts/flashboot.sh tc100/bin/busybox tc100/bin/lighttpd tc100/bin/v4l2rtspserver tc100/VERSION; do
            [ -e "$D/m/$f" ] || _miss="$_miss $f"
        done
        _iv=$(cat "$D/m/tc100/VERSION" 2>/dev/null)
        umount "$D/m"; rmdir "$D/m"
        [ -z "$_miss" ] || { echo "refused missing in usr.img:$_miss"; return 1; }
        [ "$_iv" = "$_v" ] || { echo "refused usr.img is $_iv, package says $_v"; return 1; }
    fi
    : > "$D/ready"
    echo "ok $_v"
}

_uu_log() { echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$D/install.log"; }

# Processes running code from mtd6 (major 31 = mtdblock, minor 6).
_uu_users()
{
    for p in "$PROC"/[0-9]*; do
        _pid=${p##*/}
        { [ "$_pid" = "$$" ] || [ "$_pid" = "$_feeder" ] || [ "$_pid" = 1 ]; } && continue
        grep -q " $MAPDEV " "$p/maps" 2>/dev/null && echo "$_pid"
    done
}

uu_install()
{
    D="$1"
    [ -e "$D/ready" ] || { echo "not checked"; return 1; }
    read -r _v _r < "$D/VERSION"
    read -r _m _r < "$D/usr.img.md5"
    _blocks=$(( $(wc -c < "$D/usr.img") / 4096 ))
    if [ -z "$MAPDEV" ]; then
        _mm=$(cat /sys/class/block/mtdblock6/dev 2>/dev/null)
        MAPDEV=$(printf '%02x:%02x' "${_mm%%:*}" "${_mm##*:}")
    fi
    _uu_log "system $_v: start (map $MAPDEV)"
    sleep "${UU_GRACE:-2}"                      # let the web request finish
    # 1. Watchdog: the busybox feeder runs from mtd6. Each write below opens,
    #    pings and closes the device (no magic close: it keeps running).
    _feeder=""
    for p in "$PROC"/[0-9]*; do
        grep -q "watchdog" "$p/cmdline" 2>/dev/null && grep -q " $MAPDEV " "$p/maps" 2>/dev/null && _feeder_old="${p##*/}"
    done
    if [ -n "$_feeder_old" ]; then
        kill -9 "$_feeder_old" 2>/dev/null
        ( while :; do echo 1 > "$WD" 2>/dev/null; sleep 1; done ) </dev/null >/dev/null 2>&1 &
        _feeder=$!
        _uu_log "watchdog feeder $_feeder_old replaced by $_feeder"
    fi
    # 2. Stop everything that runs from /usr.
    _round=0
    while [ $_round -lt 6 ]; do
        _u=$(_uu_users)
        [ -z "$_u" ] && break
        _round=$((_round + 1))
        _uu_log "round $_round: stopping$(for x in $_u; do printf ' %s(%s)' "$x" "$(cat "$PROC/$x/comm" 2>/dev/null)"; done)"
        if [ $_round -le 2 ]; then kill $_u 2>/dev/null; sleep 3; else kill -9 $_u 2>/dev/null; sleep 1; fi
    done
    _u=$(_uu_users)
    if [ -n "$_u" ]; then
        _uu_log "ABORT: still running from /usr: $_u — nothing written, rebooting"
        _uu_finish; return 1
    fi
    # 3. /usr
    sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
    _ok=""; _i=1
    while [ $_i -le 5 ]; do
        dd if="$D/usr.img" of="$BLOCK6" bs=4096 conv=notrunc,fsync 2>/dev/null
        sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
        _back=$(dd if="${MTD}6" bs=4096 count=$_blocks 2>/dev/null | md5sum | cut -d' ' -f1)
        _uu_log "write $_i: read back $_back"
        [ "$_back" = "$_m" ] && { _ok=1; break; }
        _i=$((_i + 1))
    done
    if [ -z "$_ok" ]; then
        _uu_log "FAILED: /usr does not read back correctly after 5 writes"
        _uu_finish; return 2
    fi
    # 4. Code zone (pending until the camera comes back with it).
    _c=$(sh "$D/flash-code.sh" write "$D/code.bin" 2>&1)
    _uu_log "code zone: $_c"
    # Everything that matters is written: keep the log in flash before the
    # card step (a failing card can hang the kernel in its driver until the
    # hardware watchdog resets the camera — seen on a test camera).
    _uu_log "/usr and code written; card step next"
    cp "$D/install.log" "$JFFS/log/usr-update.log" 2>/dev/null; sync
    # 5. A card with the firmware hook would start instead: one boot from flash.
    uu_oneshot "$D/flashmode-once.sh" "$D/card"
    mkdir -p "$JFFS/log"
    echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) system $_v written (/usr $_m)" >> "$JFFS/log/code-updates.log"
    _uu_log "DONE: rebooting"
    _uu_finish
}

# With an SD card carrying the firmware boot hook (wifitest/) in the slot,
# the next boot would start the card firmware: set the hook aside for one
# boot from flash (flashmode-once.sh puts it back). Used after a system or a
# code update from flash.
uu_oneshot()
{
    _once="$1"; _mp="${2:-/tmp/uu-card}"
    [ -b "${CARD_DEV}p1" ] || [ -b "$CARD_DEV" ] || return 0
    [ -s "$_once" ] || return 1
    # Never mount a card known to misbehave (scripts/sd-health.sh, or card
    # errors in the kernel log): its driver can block the whole system.
    case "$(sed -n 's/^state=//p' "${SDH_OUT:-/tmp/sd-health}" 2>/dev/null)" in
        failing|errors|readonly) [ -n "$D" ] && _uu_log "SD card unreliable: not mounted"; return 1 ;;
    esac
    if dmesg 2>/dev/null | grep -q -E 'mmcblk[0-9].*(timed out|command error)|get_card_status wait too long'; then
        [ -n "$D" ] && _uu_log "SD card errors in the kernel log: not mounted"; return 1
    fi
    mkdir -p "$_mp"
    mount "${CARD_DEV}p1" "$_mp" 2>/dev/null || mount "$CARD_DEV" "$_mp" 2>/dev/null || return 1
    _r=0
    if [ -d "$_mp/wifitest" ]; then
        if cp "$_once" "$JFFS/boot.sh" && chmod 755 "$JFFS/boot.sh" && mv "$_mp/wifitest" "$_mp/wifitest.off"; then
            [ -n "$D" ] && _uu_log "SD card hook set aside for one boot from flash"
        else
            _r=1
        fi
    fi
    sync; umount "$_mp"
    return $_r
}

_uu_finish()
{
    cp "$D/install.log" "$JFFS/log/usr-update.log" 2>/dev/null
    sync
    if [ -n "$UU_NO_REBOOT" ]; then [ -n "$_feeder" ] && kill "$_feeder" 2>/dev/null; return 0; fi
    # Planned restart, for scripts/reboot-tracker.sh at the next boot.
    printf '%s|%s\n' "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)" "web: system update" > "$JFFS/log/.reboot-intent" 2>/dev/null; sync
    reboot -f
}

case "${0##*/}" in
    usr-update.sh)
        case "$1" in
            check) uu_check "$2" ;;
            install) uu_install "$2" ;;
            oneshot) uu_oneshot "$2" ;;
            *) echo "usage: $0 check <dir> | install <dir> | oneshot <flashmode-once.sh>" >&2; exit 2 ;;
        esac ;;
esac
