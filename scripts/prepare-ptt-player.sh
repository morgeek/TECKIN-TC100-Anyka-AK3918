#!/bin/sh
SOURCE_BIN="${PTT_SOURCE_BIN:-/usr/bin/ak_ao_demo}"
DEST_BIN="${PTT_DEST_BIN:-/mnt/bin/ak_ao_ptt}"
EXPECTED_SOURCE_MD5="04b300db2de09f5fbbbef316b978a42e"
EXPECTED_DEST_MD5="50afb76d22a1341366306dccffd2d671"
md5_file() {
    if command -v md5sum >/dev/null 2>&1; then
        md5sum "$1" | awk '{print $1}'
    elif [ -x /mnt/bin/busybox ]; then
        /mnt/bin/busybox md5sum "$1" | awk '{print $1}'
    else
        return 1
    fi
}
[ -r "$SOURCE_BIN" ] || exit 1
source_md5="$(md5_file "$SOURCE_BIN")" || exit 1
[ "$source_md5" = "$EXPECTED_SOURCE_MD5" ] || exit 1
if [ -r "$DEST_BIN" ]; then
    dest_md5="$(md5_file "$DEST_BIN")" || dest_md5=""
    if [ "$dest_md5" = "$EXPECTED_DEST_MD5" ]; then
        chmod +x "$DEST_BIN" 2>/dev/null || true
        exit 0
    fi
fi
dest_dir="${DEST_BIN%/*}"
[ "$dest_dir" != "$DEST_BIN" ] || dest_dir=.
mkdir -p "$dest_dir" || exit 1
tmp_bin="${DEST_BIN}.tmp.$$"
trap 'rm -f "$tmp_bin"' EXIT INT TERM
cp "$SOURCE_BIN" "$tmp_bin" || exit 1
printf '\000\020\240\343' | dd of="$tmp_bin" bs=1 seek=3584 conv=notrunc 2>/dev/null || exit 1
printf '\001\020\240\343' | dd of="$tmp_bin" bs=1 seek=4208 conv=notrunc 2>/dev/null || exit 1
patched_md5="$(md5_file "$tmp_bin")" || exit 1
[ "$patched_md5" = "$EXPECTED_DEST_MD5" ] || exit 1
chmod 755 "$tmp_bin" || exit 1
mv "$tmp_bin" "$DEST_BIN" || exit 1
trap - EXIT INT TERM
exit 0
