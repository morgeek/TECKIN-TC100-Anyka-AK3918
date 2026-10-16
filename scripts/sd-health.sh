#!/bin/sh
# sd-health.sh — is the SD card still trustworthy?
#
# A failing card does not stop working at once: writes come back with zeroed
# or garbled pages and the kernel logs "mmcblk0: timed out" / FAT errors,
# while reads of older files still work (2026-10-13 and 2026-10-16 on a test
# camera). This makes it visible before the card holds the only copy of
# something.
#
#   sd-health.sh check          kernel log + mount state, no write
#   sd-health.sh check --test   also write 256 KB, flush, read it back
#   sd-health.sh status         print the last result (key=value lines)
#
# Result in /tmp/sd-health (state=, errors=, readonly=, test=, test_ts=,
# mount=), read by state.cgi (status line), the web page and mqtt-bridge.sh
# (Home Assistant "SD Card Problem"). state is one of:
#   none      no card in the slot
#   unused    a card, not mounted (flash mode, recording off)
#   ok
#   errors    the kernel logged card or file system errors since boot
#   readonly  the file system was remounted read-only (errors=remount-ro)
#   failing   the write test read back different data: replace the card
# The test runs at most once a day (and after each boot) from web-guard.sh.

OUT="${SDH_OUT:-/tmp/sd-health}"
PROC_MOUNTS="${SDH_MOUNTS:-/proc/mounts}"
DEV="${SDH_DEV:-/dev/mmcblk0}"
STORAGE_FILE="${TC100_STORAGE_FILE:-/tmp/tc100-storage}"
DMESG="${SDH_DMESG:-dmesg}"
PATTERN='mmcblk[0-9].*(timed out|command error|error -|card status)|FAT-fs .*error|exFAT.*error|I/O error.*mmcblk|get_card_status wait too long'

_sdh_get() { sed -n "s/^$1=//p" "$OUT" 2>/dev/null | head -n 1; }

sdh_check()
{
    _test=""; [ "$1" = --test ] && _test=1
    _mp=""; _ro=0
    if [ "$(cat "$STORAGE_FILE" 2>/dev/null)" = flash ]; then _want="${SDH_FLASH_MP:-/mnt/sd}"; else _want="${SDH_SD_MP:-/mnt}"; fi
    while read -r _d _m _fs _o _r; do
        case "$_d" in "$DEV"*) ;; *) continue ;; esac
        [ "$_m" = "$_want" ] || continue
        _mp="$_m"
        case ",$_o," in *,ro,*) _ro=1 ;; esac
    done < "$PROC_MOUNTS"
    _err=$($DMESG 2>/dev/null | grep -c -E "$PATTERN")
    case "$_err" in ''|*[!0-9]*) _err=0 ;; esac
    # The kernel ring buffer rolls over: keep the highest count seen this boot.
    _prev=$(_sdh_get errors); case "$_prev" in ''|*[!0-9]*) _prev=0 ;; esac
    [ "$_prev" -gt "$_err" ] && _err=$_prev
    _t=$(_sdh_get test); _tts=$(_sdh_get test_ts)
    if [ -n "$_test" ] && [ -n "$_mp" ] && [ "$_ro" = 0 ]; then
        _f="$_mp/.tc100-sdtest"
        if dd if=/dev/urandom of=/tmp/.sdtest bs=1024 count=256 2>/dev/null; then
            _want_md5=$(md5sum /tmp/.sdtest | cut -d' ' -f1)
            cp /tmp/.sdtest "$_f" 2>/dev/null; sync
            echo 1 > /proc/sys/vm/drop_caches 2>/dev/null
            _got=$(md5sum "$_f" 2>/dev/null | cut -d' ' -f1)
            rm -f "$_f" /tmp/.sdtest; sync
            if [ "$_got" = "$_want_md5" ]; then _t=ok; else _t=bad; fi
            _tts=$(date +%s 2>/dev/null)
        fi
    fi
    if [ ! -b "$DEV" ] && [ -z "$_mp" ]; then _st=none
    elif [ -z "$_mp" ]; then _st=unused
    elif [ "$_t" = bad ]; then _st=failing
    elif [ "$_ro" = 1 ]; then _st=readonly
    elif [ "$_err" -gt 0 ]; then _st=errors
    else _st=ok; fi
    _old=$(_sdh_get state)
    { echo "state=$_st"; echo "errors=$_err"; echo "readonly=$_ro"; echo "test=$_t"
      echo "test_ts=$_tts"; echo "mount=$_mp"; } > "$OUT.tmp" && mv -f "$OUT.tmp" "$OUT"
    if [ "$_st" != "$_old" ]; then
        case "$_st" in
            failing|readonly|errors) logger -t tc100-event -p user.err "SD card: $_st (errors $_err, write test ${_t:-not run})" 2>/dev/null ;;
        esac
    fi
    echo "$_st"
}

case "${0##*/}" in
    sd-health.sh)
        case "$1" in
            check) sdh_check "$2" ;;
            status) cat "$OUT" 2>/dev/null ;;
            *) echo "usage: $0 check [--test] | status" >&2; exit 2 ;;
        esac ;;
esac
