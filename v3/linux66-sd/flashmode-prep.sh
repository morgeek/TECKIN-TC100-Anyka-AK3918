#!/bin/sh
# flashmode-prep.sh: user space from the SPI flash. Called by the initramfs boot script (S39tc100) when the system runs in
# "flash mode" (kernel command line flashroot=1, or the file tc100test/flashmode on the card for tests).
# Before: the squashfs of the user space is mounted read-only at /rom; the SD card, if any, is mounted at /mnt/sd.
# After:  /mnt is a small RAM disk holding links to /rom (bin lib scripts controlscripts www v3 tc100test) and the
#         writable settings (/mnt/config, restored from the flash slots cfga/cfgb and saved back when they change);
#         the card (optional, video storage only) is back at /mnt/sd, and /mnt/DCIM points to it.
R=/rom
log() { echo "[flashmode] $*" > /dev/console; }
mkdir -p /tmp/cardmnt
CARD=0; if grep -q ' /mnt/sd vfat ' /proc/mounts; then mount --move /mnt/sd /tmp/cardmnt && CARD=1; fi
mount -t tmpfs -o size=6m,mode=755 tmpfs /mnt || { log "cannot create /mnt"; exit 1; }
for d in bin lib scripts controlscripts www v3 tc100test; do [ -e $R/$d ] && ln -s $R/$d /mnt/$d; done
cp $R/VERSION /mnt/VERSION 2>/dev/null
mkdir -p /mnt/config; cp -a $R/config/. /mnt/config/ 2>/dev/null
[ -f /mnt/config/boot.conf ] || { [ -f /mnt/config/boot.conf.dist ] && cp /mnt/config/boot.conf.dist /mnt/config/boot.conf; }
CFG=/mnt/config sh $R/v3/linux66-sd/cfg-persist restore
( CFG=/mnt/config exec sh $R/v3/linux66-sd/cfg-persist daemon ) </dev/null >/dev/null 2>&1 &
mkdir -p /mnt/sd
if [ $CARD = 1 ]; then
  mount --move /tmp/cardmnt /mnt/sd
  mkdir -p /mnt/sd/DCIM /mnt/sd/records 2>/dev/null
  log "SD card kept for video storage (/mnt/sd)"
else
  mount -t tmpfs -o size=16k tmpfs /mnt/sd    # no card: nothing can be recorded into RAM
  log "no SD card: no video storage"
fi
ln -s /mnt/sd/DCIM /mnt/DCIM
touch /tmp/flashmode
log "user space from flash ($(cat /mnt/VERSION 2>/dev/null))"
