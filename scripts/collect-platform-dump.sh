#!/bin/sh
# collect-platform-dump.sh — READ-ONLY inventory of the stock TC100 platform.
#
# Gathers everything needed to analyse (and eventually replace) the vendor
# firmware: raw SPI-flash partitions, the vendor rootfs (/etc, /usr, /lib, ...),
# kernel/board facts from /proc and /sys, and checksums of the vendor libraries.
#
# Safety contract:
#   - never writes to flash: MTD devices are only ever opened as `dd if=`;
#   - never calls fw_setenv, flash_erase, flashcp, nandwrite, mtd_debug write;
#   - writes only under $DUMP_ROOT on the SD card (default /mnt/dump);
#   - aborts before reading anything if the SD card lacks free space.
#
# Usage (telnet/SSH on the camera):
#   sh /mnt/scripts/collect-platform-dump.sh            # full dump
#   sh /mnt/scripts/collect-platform-dump.sh --no-flash # skip raw MTD images
#   sh /mnt/scripts/collect-platform-dump.sh --dry-run  # print plan only
#
# Then fetch /mnt/dump/<host>-<stamp>.tar over FTP.
# (The camera busybox has no gzip applet, so nothing here is compressed.)
#
# Test hooks: PROC_DIR, SYS_DIR, DEV_DIR, FS_ROOT and DUMP_ROOT may be
# overridden so the script can run against a fake tree on a build host.

PROC_DIR="${PROC_DIR:-/proc}"
SYS_DIR="${SYS_DIR:-/sys}"
DEV_DIR="${DEV_DIR:-/dev}"
FS_ROOT="${FS_ROOT:-}"
DUMP_ROOT="${DUMP_ROOT:-/mnt/dump}"
MIN_FREE_KB="${MIN_FREE_KB:-40960}"

if [ -x /mnt/bin/busybox ]; then BB=/mnt/bin/busybox
elif command -v busybox >/dev/null 2>&1; then BB=busybox
else BB=""
fi
bb() { if [ -n "$BB" ]; then "$BB" "$@"; else "$@"; fi; }

DO_FLASH=1
DRY_RUN=0
for _arg in "$@"; do
    case "$_arg" in
        --no-flash) DO_FLASH=0 ;;
        --dry-run)  DRY_RUN=1 ;;
        -h|--help)  bb sed -n '2,24p' "$0"; exit 0 ;;
        *) echo "unknown option: $_arg" >&2; exit 2 ;;
    esac
done

_host="$(bb hostname 2>/dev/null)"
[ -n "$_host" ] || _host="tc100"
_stamp="$(bb date +%Y%m%d-%H%M%S 2>/dev/null)"
[ -n "$_stamp" ] || _stamp="nodate"
OUT="$DUMP_ROOT/$_host-$_stamp"

say() { echo "[dump] $*"; }
run() {
    # run <outfile> <cmd...> : capture stdout+stderr, never fail the script
    _of="$1"; shift
    if [ "$DRY_RUN" = 1 ]; then say "would run: $* > $_of"; return 0; fi
    "$@" > "$OUT/$_of" 2>&1 || echo "(exit $?)" >> "$OUT/$_of"
}
copy_file() {
    # copy_file <src> <dest-name>
    [ -r "$1" ] || return 0
    if [ "$DRY_RUN" = 1 ]; then say "would copy: $1"; return 0; fi
    bb cat "$1" > "$OUT/$2" 2>/dev/null || true
}

# ---------------------------------------------------------------- preflight
_dump_parent="$DUMP_ROOT"
[ -d "$_dump_parent" ] || _dump_parent="$(bb dirname "$DUMP_ROOT")"
_free_kb="$(bb df -k "$_dump_parent" 2>/dev/null | bb awk 'NR==2 {print $4}')"
case "$_free_kb" in ''|*[!0-9]*) _free_kb=0 ;; esac
say "output: $OUT"
say "free on SD: ${_free_kb} KiB (need ${MIN_FREE_KB})"
if [ "$_free_kb" -lt "$MIN_FREE_KB" ]; then
    say "ABORT: not enough free space on the SD card"
    exit 3
fi
if [ "$DRY_RUN" = 0 ]; then
    bb mkdir -p "$OUT/proc" "$OUT/sys" "$OUT/flash" "$OUT/fs" || { say "ABORT: cannot create $OUT"; exit 3; }
fi

# ---------------------------------------------------------------- kernel / board facts
say "collecting /proc facts"
for _f in cpuinfo cmdline version mtd partitions modules meminfo iomem interrupts \
          devices filesystems mounts misc cpu/alignment buddyinfo zoneinfo; do
    _name="$(echo "$_f" | bb sed 's#/#_#g')"
    copy_file "$PROC_DIR/$_f" "proc/$_name"
done
if [ -r "$PROC_DIR/config.gz" ]; then
    copy_file "$PROC_DIR/config.gz" "proc/config.gz"
fi
for _f in "$PROC_DIR"/ak_* "$PROC_DIR"/driver/*; do
    [ -f "$_f" ] || continue
    copy_file "$_f" "proc/$(bb basename "$_f")"
done

say "collecting runtime state"
run uname.txt        bb uname -a
run ps.txt           bb ps
run dmesg.txt        bb dmesg
run df.txt           bb df -k
run ifconfig.txt     bb ifconfig -a
run lsmod.txt        bb cat "$PROC_DIR/modules"
run busybox-sys.txt  /bin/busybox
run dev-list.txt     bb ls -la "$DEV_DIR"
run sys-gpio.txt     bb ls -laR "$SYS_DIR/user-gpio" "$SYS_DIR/class/gpio"
run sys-class.txt    bb ls -la "$SYS_DIR/class"
run sys-modules.txt  bb ls "$SYS_DIR/module"
run sys-mtd.txt      bb ls -laR "$SYS_DIR/class/mtd"
run i2c.txt          bb ls -laR "$SYS_DIR/bus/i2c/devices"
run usb.txt          bb ls -laR "$SYS_DIR/bus/usb/devices"
run video4linux.txt  bb ls -laR "$SYS_DIR/class/video4linux"
run sound.txt        bb ls -laR "$SYS_DIR/class/sound"
for _p in "$SYS_DIR"/module/*/parameters/*; do
    [ -r "$_p" ] || continue
    if [ "$DRY_RUN" = 1 ]; then continue; fi
    echo "$_p=$(bb cat "$_p" 2>/dev/null)" >> "$OUT/sys/module-parameters.txt"
done
if command -v fw_printenv >/dev/null 2>&1; then
    run uboot-env.txt fw_printenv
fi

# ---------------------------------------------------------------- raw flash (read-only)
if [ "$DO_FLASH" = 1 ] && [ -r "$PROC_DIR/mtd" ]; then
    say "reading MTD partitions (read-only)"
    # /proc/mtd lines look like: mtd0: 00040000 00010000 "uboot"
    bb awk -F'[: ]+' '/^mtd[0-9]+/ {gsub(/"/, "", $4); gsub(/[^A-Za-z0-9_.-]/, "_", $4); print $1, $2, $4}' "$PROC_DIR/mtd" |
    while read -r _mtd _size _label; do
        _src="$DEV_DIR/$_mtd"
        [ -c "$_src" ] || _src="$DEV_DIR/${_mtd}ro"
        [ -e "$_src" ] || { say "skip $_mtd (no device node)"; continue; }
        _dst="$OUT/flash/${_mtd}_${_label}.bin"
        if [ "$DRY_RUN" = 1 ]; then say "would dd if=$_src of=$_dst (size 0x$_size)"; continue; fi
        say "dd $_mtd ($_label, 0x$_size)"
        bb dd if="$_src" of="$_dst" bs=64k 2>"$OUT/flash/${_mtd}.dd.log" || say "dd $_mtd failed (see log)"
    done
fi

# ---------------------------------------------------------------- vendor filesystem
say "archiving vendor filesystem"
for _d in etc usr lib bin sbin; do
    [ -d "$FS_ROOT/$_d" ] || continue
    if [ "$DRY_RUN" = 1 ]; then say "would tar $FS_ROOT/$_d"; continue; fi
    ( cd "$FS_ROOT/" && bb tar -cf "$OUT/fs/$_d.tar" "$_d" ) 2>"$OUT/fs/$_d.tar.log" || say "tar $_d had errors (see log)"
done
for _f in var/log/messages var/log/messages.0 tmp/log/startup.log; do
    copy_file "$FS_ROOT/$_f" "fs/$(echo "$_f" | bb sed 's#/#_#g')"
done

# ---------------------------------------------------------------- vendor library fingerprints
if [ "$DRY_RUN" = 0 ]; then
    say "fingerprinting vendor libraries and modules"
    for _f in "$FS_ROOT"/usr/lib/*.so* "$FS_ROOT"/lib/*.so* "$FS_ROOT"/usr/modules/*.ko \
              "$FS_ROOT"/usr/bin/* "$FS_ROOT"/usr/sbin/* "$FS_ROOT"/etc/jffs2/*; do
        [ -f "$_f" ] || continue
        bb md5sum "$_f" >> "$OUT/fingerprints.md5" 2>/dev/null
    done
    for _f in "$FS_ROOT"/usr/lib/libplat_*.so "$FS_ROOT"/usr/lib/libmpi_*.so "$FS_ROOT"/usr/lib/libakispsdk.so; do
        [ -f "$_f" ] || continue
        echo "== $_f" >> "$OUT/lib-versions.txt"
        bb strings "$_f" 2>/dev/null | bb grep -E 'V[0-9]+\.[0-9]+\.[0-9]+|ak_vi_set_switch_fps_enable' >> "$OUT/lib-versions.txt"
    done
fi

# ---------------------------------------------------------------- manifest + archive
if [ "$DRY_RUN" = 1 ]; then say "dry run complete"; exit 0; fi
( cd "$OUT" && bb find . -type f ! -name MANIFEST.md5 | while read -r _mf; do bb md5sum "$_mf"; done > MANIFEST.md5 ) 2>/dev/null
_archive="$DUMP_ROOT/$_host-$_stamp.tar"
( cd "$DUMP_ROOT" && bb tar -cf "$_archive" "$_host-$_stamp" ) && bb sync
say "done: $_archive ($(bb du -k "$_archive" 2>/dev/null | bb awk '{print $1}') KiB)"
say "fetch it over FTP, then delete $OUT and the archive from the card"
