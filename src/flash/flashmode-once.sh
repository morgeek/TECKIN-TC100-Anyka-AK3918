#!/bin/sh
# ONE-SHOT flash-mode boot with the card still inserted, for checking a camera
# before its SD card is removed. Install as /etc/jffs2/tc100/boot.sh (chmod
# 755) and rename /mnt/wifitest to /mnt/wifitest.off, then reboot: the card
# hook is restored first, so the next boot is a normal SD boot again; without
# network 6 min after boot, it reboots.
L=/tmp/log/fbtest.log
mkdir -p /tmp/log
echo "flashmode-once start uptime $(cut -d' ' -f1 /proc/uptime)" >> $L
[ -d /mnt/wifitest.off ] && mv /mnt/wifitest.off /mnt/wifitest
rm -f /etc/jffs2/tc100/boot.sh
sync
echo "sd hook restored: $(ls -d /mnt/wifitest 2>&1)" >> $L
( sleep 360
  gw=$(route -n | awk '$1=="0.0.0.0" {print $2; exit}')
  if [ -n "$gw" ] && ping -c 2 -W 3 "$gw" >/dev/null 2>&1; then echo "network ok (gw $gw)" >> $L
  else echo "no network, reboot" >> $L; sync; reboot; fi ) &
exec /usr/tc100/scripts/flashboot.sh
