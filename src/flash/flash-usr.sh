#!/bin/sh
# Write a new /usr image to mtd6 ("C") and verify it by reading the flash back.
# Usage: flash-usr.sh <image> <md5> ; log in /tmp/flash.log, result line last.
IMG=$1; WANT=$2; LOG=/tmp/flash.log
log() { echo "$(date '+%H:%M:%S') $*" >> $LOG; }
: > $LOG
grep -q '^mtd6: 003b6000 00001000 "C"$' /proc/mtd || { log "ABORT: mtd6 is not C/0x3b6000"; exit 1; }
size=$(stat -c %s "$IMG" 2>/dev/null || wc -c < "$IMG")
[ "$size" -gt 0 ] && [ "$size" -le 3891200 ] && [ $((size % 4096)) -eq 0 ] || { log "ABORT: bad size $size"; exit 1; }
got=$(md5sum "$IMG" | cut -d' ' -f1)
[ "$got" = "$WANT" ] || { log "ABORT: image md5 $got != $WANT"; exit 1; }
blocks=$((size / 4096))
log "image ok: $size bytes, $blocks blocks"
try=1
while [ $try -le 3 ]; do
    log "write $try start"
    dd if="$IMG" of=/dev/mtdblock6 bs=4096 2>>$LOG; rc=$?
    sync
    log "write $try end rc=$rc"
    back=$(dd if=/dev/mtd6 bs=4096 count=$blocks 2>/dev/null | md5sum | cut -d' ' -f1)
    if [ "$back" = "$WANT" ]; then log "RESULT: OK readback $back"; exit 0; fi
    log "readback $back differs"
    try=$((try + 1))
done
log "RESULT: FAILED after 3 writes"
exit 2
