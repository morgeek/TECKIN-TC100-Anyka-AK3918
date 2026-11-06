#!/bin/sh
# rec-storage.sh — where the local backup recording (tc100_rtsp, src/tc100rtsp/rec.c)
# writes, and safe removal of the card.
#
#   rec-storage.sh dir      print the recording directory, mounting the card
#                           first when running from flash; nothing (exit 1)
#                           when there is no usable card
#   rec-storage.sh eject    pause the recording, flush, unmount (flash mode):
#                           the card can then be taken out
#   rec-storage.sh resume   mount again and resume
#   rec-storage.sh mount    mount the card (flash mode) without touching the recorder
#   rec-storage.sh status   the recorder's status lines
#
# SD mode: the card is /mnt itself, recordings go to /mnt/DCIM.
# Flash mode: the card (first FAT32/exFAT partition, or the whole card) is mounted on
# /mnt/sd, recordings go to /mnt/sd/DCIM. The card must not carry the files
# that make the vendor boot use it (wifitest/, or uImage / root.sqsh4 /
# usr.sqsh4 / usr.jffs2 at its root): those are refused, not mounted.

STORAGE_FILE="${TC100_STORAGE_FILE:-/tmp/tc100-storage}"
MNT_SD="${REC_SD_MOUNT:-/mnt/sd}"
STATUS="${TC100FIX_REC_STATUS:-/var/run/tc100rec}"
SD_DIR="${REC_SD_DIR:-/mnt/DCIM}"
DEVS="${REC_SD_DEVS:-/dev/mmcblk0p1 /dev/mmcblk0}"
PROC_MOUNTS="${REC_PROC_MOUNTS:-/proc/mounts}"

# 3.0 (Linux 6.6) in flash mode (/tmp/flashmode): the card is the video storage at /mnt/sd; without one, a
# 16 KiB RAM placeholder is mounted there (nothing can be recorded into RAM), put back after an eject.
L66=0; [ -f "${REC_L66_FLAG:-/tmp/linux66}" ] && L66=1
_flash() { [ "$(cat "$STORAGE_FILE" 2>/dev/null)" = flash ] || { [ "$L66" = 1 ] && [ -f "${REC_FLASHMODE_FLAG:-/tmp/flashmode}" ]; }; }

# the files that make the vendor boot use a card (same list as scripts/sd-diag.sh): such a card is refused
SD_BOOT_FILES="wifitest uImage uimage root.sqsh4 usr.sqsh4 usr.jffs2"
_boot_file() { for _bad in $SD_BOOT_FILES; do [ -e "$MNT_SD/$_bad" ] && { echo "$_bad"; return 0; }; done; return 1; }

# a usable card is mounted: a FAT/exFAT file system without boot files (R25: a boot card mounted by an earlier call
# counted as mounted and was used)
_mounted()
{
    if [ "$L66" = 1 ]; then grep -qE " $MNT_SD (vfat|exfat) " "$PROC_MOUNTS" 2>/dev/null && ! _boot_file >/dev/null
    else grep -q " $MNT_SD " "$PROC_MOUNTS" 2>/dev/null; fi
}

_placeholder() { [ "$L66" = 1 ] && ! grep -q " $MNT_SD " "$PROC_MOUNTS" 2>/dev/null && mount -t tmpfs -o size=16k tmpfs "$MNT_SD" 2>/dev/null; return 0; }

# R25 (IPCAM1, rc31): a refused card stayed mounted read-write. Now: one caller at a time (lock), the card is mounted
# READ-ONLY first and switched to read-write only once it is known to carry no boot file, and a refused card that
# cannot be unmounted (busy) is at least remounted read-only and reported in /tmp/sd-diag.status.
_refuse_card()
{
    logger -t tc100-rec "card refused: it carries $1 (boot files)" 2>/dev/null
    if umount "$MNT_SD" 2>/dev/null || { mount -o remount,ro "$MNT_SD" 2>/dev/null; sleep 1; umount "$MNT_SD" 2>/dev/null; }; then
        _placeholder
    else
        mount -o remount,ro "$MNT_SD" 2>/dev/null
        printf '{"ok":false,"state":"refused","message":"Boot or install card (%s at its root): not used for recordings; it could not be unmounted and stays mounted read-only."}\n' \
            "$1" > "${REC_DIAG_STATUS:-/tmp/sd-diag.status}" 2>/dev/null
        logger -t tc100-rec "refused card busy: left mounted read-only" 2>/dev/null
    fi
}

_mount_card_locked()
{
    if grep -qE " $MNT_SD (vfat|exfat) " "$PROC_MOUNTS" 2>/dev/null; then
        _bf=$(_boot_file) || return 0                      # mounted and usable
        _refuse_card "$_bf"; return 1                      # mounted by someone, but a boot card
    fi
    [ "$L66" = 1 ] || { grep -q " $MNT_SD " "$PROC_MOUNTS" 2>/dev/null && return 0; }
    mkdir -p "$MNT_SD" 2>/dev/null
    [ "$L66" = 1 ] && umount "$MNT_SD" 2>/dev/null   # the RAM placeholder
    for _d in $DEVS; do
        [ -b "$_d" ] || continue
        # (no check here: a full fsck at every remount costs minutes and MB; scripts/sd-diag.sh repair does it on demand
        # or at boot with SD_AUTO_REPAIR=1, item 41)
        # FAT32 (cards up to 32 GB) or exFAT (larger cards, as formatted out of the box); read-only until checked
        if mount -t vfat -o ro,noatime,nodiratime,shortname=mixed "$_d" "$MNT_SD" 2>/dev/null ||
           mount -t exfat -o ro,noatime "$_d" "$MNT_SD" 2>/dev/null; then
            if _bf=$(_boot_file); then
                _refuse_card "$_bf"; return 1
            fi
            mount -o remount,rw "$MNT_SD" 2>/dev/null || logger -t tc100-rec "card left read-only: remount rw failed" 2>/dev/null
            [ "$L66" = 1 ] && mkdir -p "$MNT_SD/DCIM" 2>/dev/null
            return 0
        fi
    done
    _placeholder
    return 1
}

_mount_card()
{
    _lk="${REC_LOCK:-/tmp/rec-storage.lock}"; _lw=0
    while ! mkdir "$_lk" 2>/dev/null; do
        # a holder that died leaves the lock: taken over after 60 s
        [ -n "$(find "$_lk" -maxdepth 0 -mmin +1 2>/dev/null)" ] && { rmdir "$_lk" 2>/dev/null; continue; }
        _lw=$((_lw + 1)); [ "$_lw" -ge 30 ] && return 1
        sleep 1
    done
    _mount_card_locked; _mrc=$?
    rmdir "$_lk" 2>/dev/null
    return $_mrc
}

rs_dir()
{
    if _flash; then
        _mount_card || return 1
        _dir="$MNT_SD/DCIM"
    else
        _dir="$SD_DIR"
    fi
    mkdir -p "$_dir" 2>/dev/null || return 1
    echo "$_dir"
}

rs_eject()
{
    : > "$STATUS.pause"
    _i=0
    while [ $_i -lt 10 ]; do
        grep -q '^state=\(paused\|waiting\|no-card\|error\)' "$STATUS" 2>/dev/null && break
        sleep 1; _i=$((_i + 1))
    done
    sync
    if _flash && _mounted; then
        umount "$MNT_SD" || { echo "busy"; return 1; }
        _placeholder
    fi
    echo "ok: the card can be removed"
}

rs_resume()
{
    if _flash; then _mount_card || { echo "no card"; return 1; }; fi
    rm -f "$STATUS.pause"
    echo ok
}

case "${0##*/}" in
    rec-storage.sh)
        case "$1" in
            dir) rs_dir ;;
            eject) rs_eject ;;
            resume) rs_resume ;;
            mount) if _flash; then _mount_card || exit 1; fi ;;
            status) cat "$STATUS" 2>/dev/null; [ -f "$STATUS.pause" ] && echo "paused=1" ;;
            *) echo "usage: $0 dir | eject | resume | mount | status" >&2; exit 2 ;;
        esac ;;
esac
