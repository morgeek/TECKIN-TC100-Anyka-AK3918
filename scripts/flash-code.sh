#!/bin/sh
# flash-code.sh — the firmware's code zone in the free end of the KERNEL flash
# partition (mtd1), for the firmware run from flash (scripts/flashboot.sh).
#
# mtd1 is 2 MB; the kernel (U-Boot reads only its size from the partition
# table, 0x15aca0 on the TC100) ends before 0x15b000. The zone starts at
# 0x160000 and runs to the end of the partition (640 KB):
#
#   0x160000  4 KB header, text:  TC100CODE 1 / size N / md5 M / version V
#   0x161000  squashfs (xz) of autorun.sh VERSION scripts controlscripts www
#             sounds config — the code updated most often
#
# The binaries stay in /usr/tc100 (mtd6), which also carries a full copy of
# the code: when the zone is absent or does not match its md5 (empty flash,
# an interrupted write, U-Boot's SD recovery erasing the partition),
# flashboot.sh uses that copy. A failed code update therefore never stops
# the camera from starting.
#
#   flash-code.sh status            valid <version> | none | bad <reason>
#   flash-code.sh check <file>      verify a code package (header + md5 + size)
#   flash-code.sh write <file>      write it to the zone, read it back (3 tries);
#                                   refuses unless mtd1 is the 2 MB "KERNEL"
#                                   partition, and checks that the kernel area
#                                   reads the same before and after
#   flash-code.sh mount <dir>       read-only mount of a valid zone on <dir>
#   flash-code.sh clear             blank the header: back to the code in /usr
#   flash-code.sh history           installs, confirmations and rollbacks
#
# Built by src/flash/build-code.sh. Uses only the rootfs BusyBox applets
# (dd, md5sum, losetup, mount), never the firmware's own binaries.

MTD_CHAR="${FC_MTD_CHAR:-/dev/mtd1}"
MTD_BLOCK="${FC_MTD_BLOCK:-/dev/mtdblock1}"
PROC_MTD="${FC_PROC_MTD:-/proc/mtd}"
LOG="${FC_LOG:-/tmp/log/flash-code.log}"
# A freshly written zone stays "pending" until flashboot.sh confirms that the
# camera came back with it (network + web server); a second boot without that
# confirmation puts the built-in code back. History kept in jffs2.
PENDING="${FC_PENDING:-/etc/jffs2/tc100/code-pending}"
HISTORY="${FC_HISTORY:-/etc/jffs2/tc100/log/code-updates.log}"
BS=4096
ZONE_BLOCK=352                # 0x160000 / 4096
KERNEL_BLOCKS=352             # everything before the zone
ZONE_MAX_BLOCKS=160           # 0x200000 - 0x160000 = 640 KB
DATA_MAX=$(( (ZONE_MAX_BLOCKS - 1) * BS ))

_fc_log() { mkdir -p "${LOG%/*}" 2>/dev/null; echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$LOG"; }

# _fc_header <source> <skip-blocks> -> sets FC_SIZE FC_MD5 FC_VERSION, 0 if well-formed
_fc_header()
{
    FC_SIZE=""; FC_MD5=""; FC_VERSION=""
    # The text ends with a newline, then zero padding: head stops before it
    # (no tr on the camera).
    _h="$(dd if="$1" bs=$BS skip="$2" count=1 2>/dev/null | head -n 4)" || return 1
    [ "$(printf '%s\n' "$_h" | sed -n 1p)" = "TC100CODE 1" ] || return 1
    FC_SIZE="$(printf '%s\n' "$_h" | sed -n 's/^size \([0-9][0-9]*\)$/\1/p')"
    FC_MD5="$(printf '%s\n' "$_h" | sed -n 's/^md5 \([0-9a-f]\{32\}\)$/\1/p')"
    FC_VERSION="$(printf '%s\n' "$_h" | sed -n 's/^version \([A-Za-z0-9._-]\{1,40\}\)$/\1/p')"
    [ -n "$FC_SIZE" ] && [ -n "$FC_MD5" ] && [ "$FC_SIZE" -gt 0 ] && [ "$FC_SIZE" -le "$DATA_MAX" ]
}

# _fc_data_md5 <source> <skip-blocks> <bytes>
_fc_data_md5()
{
    _n=$(( ($3 + BS - 1) / BS ))
    dd if="$1" bs=$BS skip=$(( $2 + 1 )) count="$_n" 2>/dev/null | head -c "$3" | md5sum | cut -d' ' -f1
}

fc_status()
{
    _fc_header "$MTD_CHAR" "$ZONE_BLOCK" || { echo none; return 1; }
    [ "$(_fc_data_md5 "$MTD_CHAR" "$ZONE_BLOCK" "$FC_SIZE")" = "$FC_MD5" ] || { echo "bad md5"; return 2; }
    echo "valid ${FC_VERSION:-unknown}"
}

fc_check()
{
    [ -r "$1" ] || { echo "no file $1"; return 1; }
    _fc_header "$1" 0 || { echo "not a code package"; return 1; }
    _len=$(wc -c < "$1")
    [ "$_len" -ge $(( BS + FC_SIZE )) ] && [ "$_len" -le $(( ZONE_MAX_BLOCKS * BS )) ] || { echo "bad length $_len"; return 1; }
    [ "$(_fc_data_md5 "$1" 0 "$FC_SIZE")" = "$FC_MD5" ] || { echo "md5 mismatch"; return 1; }
    echo "ok ${FC_VERSION:-unknown} $FC_SIZE"
}

fc_write()
{
    fc_check "$1" >/dev/null || { _fc_log "write refused: $(fc_check "$1")"; echo "refused: $(fc_check "$1")"; return 1; }
    grep -q '^mtd1: 00200000 00001000 "KERNEL"$' "$PROC_MTD" || { _fc_log "write refused: mtd1 is not the 2 MB KERNEL partition"; echo "refused: partition"; return 1; }
    _blocks=$(( ($(wc -c < "$1") + BS - 1) / BS ))
    [ "$_blocks" -le "$ZONE_MAX_BLOCKS" ] || { echo "refused: too big"; return 1; }
    _want="$(dd if="$1" bs=$BS count="$_blocks" conv=sync 2>/dev/null | md5sum | cut -d' ' -f1)"
    _kern="$(dd if="$MTD_CHAR" bs=$BS count=$KERNEL_BLOCKS 2>/dev/null | md5sum | cut -d' ' -f1)"
    _fc_log "write $1: $_blocks blocks at block $ZONE_BLOCK, version $FC_VERSION, kernel area $_kern"
    _try=1
    while [ "$_try" -le 3 ]; do
        dd if="$1" of="$MTD_BLOCK" bs=$BS seek=$ZONE_BLOCK count="$_blocks" conv=sync,notrunc 2>>"$LOG"
        # sync alone leaves blocks behind while the zone is mounted (measured:
        # read-back mismatches only then): flush and drop the block device's
        # buffers before reading the flash back.
        sync; blockdev --flushbufs "$MTD_BLOCK" 2>/dev/null; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
        _got="$(dd if="$MTD_CHAR" bs=$BS skip=$ZONE_BLOCK count="$_blocks" 2>/dev/null | md5sum | cut -d' ' -f1)"
        [ "$_got" = "$_want" ] && break
        _fc_log "write $_try: read back $_got, expected $_want"
        _try=$(( _try + 1 ))
    done
    _kern2="$(dd if="$MTD_CHAR" bs=$BS count=$KERNEL_BLOCKS 2>/dev/null | md5sum | cut -d' ' -f1)"
    if [ "$_kern2" != "$_kern" ]; then
        _fc_log "KERNEL AREA CHANGED: $_kern -> $_kern2"; echo "error: kernel area changed"; return 3
    fi
    [ "$_got" = "$_want" ] || { _fc_log "write failed after 3 tries"; echo "error: read back differs"; return 2; }
    _fc_log "write ok ($FC_VERSION)"
    mkdir -p "${PENDING%/*}" "${HISTORY%/*}" 2>/dev/null
    echo "$FC_VERSION 0" > "$PENDING"
    fc_history "installed $FC_VERSION (pending confirmation)"
    sync
    echo "ok $FC_VERSION"
}

# fc_history <text>: one line in the update history (last 40 kept).
fc_history()
{
    mkdir -p "${HISTORY%/*}" 2>/dev/null
    echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$HISTORY"
    if [ "$(wc -l < "$HISTORY" 2>/dev/null)" -gt 40 ] 2>/dev/null; then
        tail -n 40 "$HISTORY" > "$HISTORY.tmp" && mv -f "$HISTORY.tmp" "$HISTORY"
    fi
}

fc_clear()
{
    grep -q '^mtd1: 00200000 00001000 "KERNEL"$' "$PROC_MTD" || { echo "refused: partition"; return 1; }
    _kern="$(dd if="$MTD_CHAR" bs=$BS count=$KERNEL_BLOCKS 2>/dev/null | md5sum | cut -d' ' -f1)"
    dd if=/dev/zero of="$MTD_BLOCK" bs=$BS seek=$ZONE_BLOCK count=1 conv=notrunc 2>>"$LOG"
    sync
    [ "$(dd if="$MTD_CHAR" bs=$BS count=$KERNEL_BLOCKS 2>/dev/null | md5sum | cut -d' ' -f1)" = "$_kern" ] || { _fc_log "KERNEL AREA CHANGED by clear"; echo "error: kernel area changed"; return 3; }
    _fc_header "$MTD_CHAR" "$ZONE_BLOCK" && { echo "error: header still there"; return 2; }
    _fc_log "code zone cleared"
    rm -f "$PENDING"
    fc_history "${FC_CLEAR_REASON:-cleared}: built-in code"
    sync
    echo ok
}

fc_mount()
{
    fc_status >/dev/null || return 1
    _dev="$(losetup -f 2>/dev/null)" || return 1
    [ -n "$_dev" ] || return 1
    losetup -r -o $(( (ZONE_BLOCK + 1) * BS )) "$_dev" "$MTD_BLOCK" 2>/dev/null || return 1
    mkdir -p "$2"
    if ! mount -t squashfs -o ro "$_dev" "$2" 2>/dev/null; then
        losetup -d "$_dev" 2>/dev/null; return 1
    fi
    [ -x "$2/autorun.sh" ] && [ -d "$2/scripts" ] || { umount "$2"; losetup -d "$_dev" 2>/dev/null; return 1; }
}

case "${0##*/}" in
    flash-code.sh)
        case "$1" in
            status) fc_status ;;
            check) fc_check "$2" ;;
            write) fc_write "$2" ;;
            mount) fc_mount "$1" "$2" ;;
            clear) fc_clear ;;
            history) cat "$HISTORY" 2>/dev/null ;;
            *) echo "usage: $0 status | check <file> | write <file> | mount <dir> | clear" >&2; exit 2 ;;
        esac ;;
esac
