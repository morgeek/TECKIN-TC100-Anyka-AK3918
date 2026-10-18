#!/bin/sh
# sd-card.sh — the SD card when the firmware runs from flash: what is on it,
# automatic mounting for the recordings, and formatting from the web page.
#
# Only from flash (scripts/flashboot.sh): from an SD card the card *is* the
# firmware, so it is never formatted or remounted here.
#
#   sd-card.sh tick           every minute (web-guard.sh): notices a card put
#                             in or taken out; a usable card (FAT32/exFAT, no
#                             boot files, no card errors) is mounted on /mnt/sd
#                             when SD_AUTOMOUNT=1 (default)
#   sd-card.sh inspect        look at the card now, write and print the state
#   sd-card.sh status         print the last state (key=value lines)
#   sd-card.sh format         erase the card: one FAT32 partition, label TC100,
#                             then mount it (runs in the background; progress
#                             in /tmp/sd-format: state=running|done|error)
#   sd-card.sh ack <id>       the user answered the "card inserted" question
#                             for this card: do not ask again
#
# State (/tmp/sd-card): present= id= size_mb= fs=vfat|exfat|none
# kind=kit|data|empty|blank|errors|none mounted=0|1 free_mb= prompt=0|1
#   kit     the SD-card firmware or install kit (wifitest/, firmware.sqfs...):
#           never mounted (the vendor boot would start from it otherwise)
#   data    a usable card with files     empty   a usable card, no files
#   blank   no FAT32/exFAT file system (new card, other format)
#   errors  the kernel logged card errors: mounting it can block the system

CONF="${SDC_BOOT_CONF:-/mnt/config/boot.conf}"
ACK="${SDC_ACK:-/mnt/config/sd-card.ack}"
OUT="${SDC_OUT:-/tmp/sd-card}"
FMT="${SDC_FMT:-/tmp/sd-format}"
DEV="${SDC_DEV:-/dev/mmcblk0}"
SYSB="${SDC_SYSBLOCK:-/sys/block/mmcblk0}"
MNT="${REC_SD_MOUNT:-/mnt/sd}"
PROBE="${SDC_PROBE:-/tmp/sdprobe}"
STORAGE_FILE="${TC100_STORAGE_FILE:-/tmp/tc100-storage}"
PROC_MOUNTS="${SDC_MOUNTS:-/proc/mounts}"
REC="${SDC_REC:-/mnt/scripts/rec-storage.sh}"
DMESG="${SDC_DMESG:-dmesg}"
FDISK="${SDC_FDISK:-fdisk}"
MKFS="${SDC_MKFS:-mkfs.vfat}"
ERRPAT='mmcblk[0-9].*(timed out|command error|card status)|get_card_status wait too long|I/O error.*mmcblk'
BOOTFILES="wifitest wifitest.off firmware.sqfs uImage uimage root.sqsh4 usr.sqsh4 usr.jffs2 tc100-flash"

_flash() { [ "$(cat "$STORAGE_FILE" 2>/dev/null)" = flash ]; }
_kv() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" "$CONF" 2>/dev/null | tail -n 1; }
_get() { sed -n "s/^$1=//p" "$OUT" 2>/dev/null | head -n 1; }
_mounted() { grep -q " $MNT " "$PROC_MOUNTS" 2>/dev/null; }

# (tests: SDC_ANYFILE=1 accepts plain files for the block devices)
_isblk() { [ -b "$1" ] || { [ -n "${SDC_ANYFILE:-}" ] && [ -f "$1" ]; }; }
_present() { _isblk "$DEV" && [ "$(cat "$SYSB/size" 2>/dev/null || echo 0)" != 0 ]; }

_card_id()
{
    _i="$(cat "$SYSB/device/cid" 2>/dev/null)"
    [ -n "$_i" ] || _i="$(cat "$SYSB/device/serial" 2>/dev/null)"
    case "$_i" in *[!0-9a-fA-Fx]*|'') _i="size$(cat "$SYSB/size" 2>/dev/null)" ;; esac
    echo "$_i"
}

# The partition the card is used through: the first one, or the whole card.
_part() { if _isblk "${DEV}p1"; then echo "${DEV}p1"; else echo "$DEV"; fi; }

# File system from the boot sector, without mounting.
_fs()
{
    _b="$(dd if="$1" bs=512 count=1 2>/dev/null | dd bs=1 skip=3 count=8 2>/dev/null)"
    [ "$_b" = "EXFAT   " ] && { echo exfat; return; }
    _b="$(dd if="$1" bs=512 count=1 2>/dev/null | dd bs=1 skip=82 count=5 2>/dev/null)"
    [ "$_b" = "FAT32" ] && { echo vfat; return; }
    _b="$(dd if="$1" bs=512 count=1 2>/dev/null | dd bs=1 skip=54 count=3 2>/dev/null)"
    [ "$_b" = "FAT" ] && { echo vfat; return; }
    echo none
}

_card_errors() { [ "$($DMESG 2>/dev/null | grep -c -E "$ERRPAT")" != 0 ]; }

_acked() { grep -qx "$1" "$ACK" 2>/dev/null; }

sdc_inspect()
{
    if ! _present; then
        printf 'present=0\nkind=none\nmounted=0\nprompt=0\n' > "$OUT.tmp"; mv -f "$OUT.tmp" "$OUT"; cat "$OUT"; return 0
    fi
    _id="$(_card_id)"
    _size=$(( $(cat "$SYSB/size" 2>/dev/null || echo 0) / 2048 ))
    _p="$(_part)"; _fsn="$(_fs "$_p")"
    _kind=blank; _free=""
    if _card_errors; then
        _kind=errors
    elif _mounted; then
        _kind=data
    elif [ "$_fsn" != none ]; then
        mkdir -p "$PROBE"
        if mount -t "$_fsn" -o ro "$_p" "$PROBE" 2>/dev/null; then
            _kind=empty
            for _e in "$PROBE"/* "$PROBE"/.[!.]*; do
                [ -e "$_e" ] || continue
                case "${_e##*/}" in "System Volume Information"|.Trashes|.fseventsd|.Spotlight-V100|._*) continue ;; esac
                _kind=data
            done
            for _bf in $BOOTFILES; do [ -e "$PROBE/$_bf" ] && _kind=kit; done
            umount "$PROBE" 2>/dev/null
        fi
    fi
    _m=0; _mounted && _m=1
    if [ "$_m" = 1 ]; then
        _free="$(df -k "$MNT" 2>/dev/null | awk 'NR > 1 { print int($4 / 1024); exit }')"
    fi
    _prompt=1; _acked "$_id" && _prompt=0
    {
        echo "present=1"; echo "id=$_id"; echo "size_mb=$_size"; echo "fs=$_fsn"; echo "kind=$_kind"
        echo "mounted=$_m"; echo "free_mb=$_free"; echo "prompt=$_prompt"
    } > "$OUT.tmp"
    mv -f "$OUT.tmp" "$OUT"
    cat "$OUT"
}

sdc_mount()
{
    case "$(_get kind)" in data|empty) ;; *) return 1 ;; esac
    _mounted && return 0
    sh "$REC" mount >/dev/null 2>&1
}

sdc_tick()
{
    _flash || return 0
    if ! _present; then
        if [ "$(_get present)" = 1 ]; then
            # Taken out: let go of the mount, the device is gone.
            _mounted && umount -l "$MNT" 2>/dev/null
            logger -t tc100-event -p user.notice "SD card removed" 2>/dev/null
        fi
        [ "$(_get present)" = 0 ] || printf 'present=0\nkind=none\nmounted=0\nprompt=0\n' > "$OUT"
        return 0
    fi
    [ "$(_get present)" = 1 ] && [ "$(_get id)" = "$(_card_id)" ] && return 0
    # A card put in (or another one).
    sleep "${SDC_SETTLE:-2}"
    sdc_inspect >/dev/null
    logger -t tc100-event -p user.notice "SD card inserted: $(_get size_mb) MB, $(_get kind)" 2>/dev/null
    case "$(_kv SD_AUTOMOUNT)" in 0|no|off|false) ;; *) sdc_mount && sdc_inspect >/dev/null ;; esac
}

_fmt_state() { printf 'state=%s\nmsg=%s\nts=%s\n' "$1" "$2" "$(date +%s 2>/dev/null)" > "$FMT"; }

sdc_format_run()
{
    _fmt_state running "Preparing"
    sh "$REC" eject >/dev/null 2>&1
    for _m in $(awk -v d="$DEV" 'index($1, d) == 1 { print $2 }' "$PROC_MOUNTS" 2>/dev/null); do
        umount "$_m" 2>/dev/null || { _fmt_state error "The card is in use ($_m)"; return 1; }
    done
    _fmt_state running "Writing the partition table"
    # Old partition table and file system signatures out of the way.
    dd if=/dev/zero of="$DEV" bs=1024 count=1024 conv=notrunc 2>/dev/null; sync
    # One primary FAT32 (LBA) partition from 4 MB (erase-block aligned) to the end.
    printf 'o\nn\np\n1\n8192\n\nt\nc\nw\n' | $FDISK -u "$DEV" >/dev/null 2>&1
    ${SDC_BLOCKDEV:-blockdev} --rereadpt "$DEV" 2>/dev/null
    _i=0; while ! _isblk "${DEV}p1" && [ $_i -lt 10 ]; do sleep 1; _i=$((_i + 1)); done
    _isblk "${DEV}p1" || { _fmt_state error "No partition after writing the table"; return 1; }
    _fmt_state running "Creating the file system (FAT32)"
    if ! $MKFS -n TC100 "${DEV}p1" >/dev/null 2>&1; then
        _fmt_state error "mkfs.vfat failed"; return 1
    fi
    sync
    sdc_inspect >/dev/null
    if sh "$REC" mount >/dev/null 2>&1; then
        mkdir -p "$MNT/records" 2>/dev/null
        sh "$REC" resume >/dev/null 2>&1
    fi
    sdc_inspect >/dev/null
    logger -t tc100-event -p user.notice "SD card formatted (FAT32, $(_get size_mb) MB)" 2>/dev/null
    _fmt_state done "Formatted: FAT32, $(_get size_mb) MB"
}

sdc_format()
{
    _flash || { echo "refused: the camera runs from the SD card"; return 1; }
    _present || { echo "refused: no card"; return 1; }
    _card_errors && { echo "refused: the kernel reported card errors, replace the card"; return 1; }
    [ "$(sed -n 's/^state=//p' "$FMT" 2>/dev/null)" = running ] && { echo "refused: already running"; return 1; }
    [ $(( $(cat "$SYSB/size" 2>/dev/null || echo 0) / 2048 )) -ge 64 ] || { echo "refused: card too small"; return 1; }
    _fmt_state running "Starting"
    ( trap '' HUP; sdc_format_run ) </dev/null >/dev/null 2>&1 &
    echo "started"
}

sdc_ack()
{
    case "$1" in ''|*[!0-9a-zA-Z]*) return 1 ;; esac
    _acked "$1" && return 0
    { [ -f "$ACK" ] && tail -n 7 "$ACK"; echo "$1"; } > "$ACK.tmp" && mv -f "$ACK.tmp" "$ACK"
    sed -i 's/^prompt=.*/prompt=0/' "$OUT" 2>/dev/null
}

case "${0##*/}" in
    sd-card.sh)
        case "$1" in
            tick) sdc_tick ;;
            inspect) _flash && sdc_inspect ;;
            status) cat "$OUT" 2>/dev/null; [ -r "$FMT" ] && sed 's/^/format_/' "$FMT" ;;
            mount) sdc_mount ;;
            format) sdc_format ;;
            ack) sdc_ack "$2" ;;
            *) echo "usage: $0 tick | inspect | status | mount | format | ack <id>" >&2; exit 2 ;;
        esac ;;
esac
