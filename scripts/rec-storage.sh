#!/bin/sh
# rec-storage.sh — where the local backup recording (libtc100fix, src/tc100fix/rec.c)
# writes, and safe removal of the card.
#
#   rec-storage.sh dir      print the recording directory, mounting the card
#                           first when running from flash; nothing (exit 1)
#                           when there is no usable card
#   rec-storage.sh eject    pause the recording, flush, unmount (flash mode):
#                           the card can then be taken out
#   rec-storage.sh resume   mount again and resume
#   rec-storage.sh status   the recorder's status lines
#
# SD mode: the card is /mnt itself, recordings go to /mnt/records.
# Flash mode: the card (first FAT32/exFAT partition, or the whole card) is mounted on
# /mnt/sd, recordings go to /mnt/sd/records. The card must not carry the files
# that make the vendor boot use it (wifitest/, or uImage / root.sqsh4 /
# usr.sqsh4 / usr.jffs2 at its root): those are refused, not mounted.

STORAGE_FILE="${TC100_STORAGE_FILE:-/tmp/tc100-storage}"
MNT_SD="${REC_SD_MOUNT:-/mnt/sd}"
STATUS="${TC100FIX_REC_STATUS:-/var/run/tc100rec}"
SD_DIR="${REC_SD_DIR:-/mnt/records}"
DEVS="${REC_SD_DEVS:-/dev/mmcblk0p1 /dev/mmcblk0}"
PROC_MOUNTS="${REC_PROC_MOUNTS:-/proc/mounts}"

_flash() { [ "$(cat "$STORAGE_FILE" 2>/dev/null)" = flash ]; }

_mounted() { grep -q " $MNT_SD " "$PROC_MOUNTS" 2>/dev/null; }

_mount_card()
{
    _mounted && return 0
    mkdir -p "$MNT_SD" 2>/dev/null
    for _d in $DEVS; do
        [ -b "$_d" ] || continue
        # FAT32 (cards up to 32 GB) or exFAT (larger cards, as formatted out of the box)
        if mount -t vfat -o rw,noatime,nodiratime,shortname=mixed "$_d" "$MNT_SD" 2>/dev/null ||
           mount -t exfat -o rw,noatime "$_d" "$MNT_SD" 2>/dev/null; then
            for _bad in wifitest uImage uimage root.sqsh4 usr.sqsh4 usr.jffs2; do
                if [ -e "$MNT_SD/$_bad" ]; then
                    umount "$MNT_SD" 2>/dev/null
                    logger -t tc100-rec "card refused: it carries $_bad (boot files)" 2>/dev/null
                    return 1
                fi
            done
            return 0
        fi
    done
    return 1
}

rs_dir()
{
    if _flash; then
        _mount_card || return 1
        _dir="$MNT_SD/records"
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
            status) cat "$STATUS" 2>/dev/null; [ -f "$STATUS.pause" ] && echo "paused=1" ;;
            *) echo "usage: $0 dir | eject | resume | status" >&2; exit 2 ;;
        esac ;;
esac
