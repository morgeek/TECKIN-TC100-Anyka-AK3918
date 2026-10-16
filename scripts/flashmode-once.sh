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
  if [ -n "$gw" ] && ping -c 2 -W 3 "$gw" >/dev/null 2>&1; then r="network ok (gw $gw)"; else r="no network"; fi
  echo "$r" >> $L
  # A few KB kept in flash for a look after the next (SD) boot.
  { echo "$r"; cat $L; tail -n 40 /tmp/log/startup.log 2>/dev/null; tail -n 20 /tmp/log/flashboot.log 2>/dev/null
    tail -n 10 /var/log/lighttpd-error.log 2>/dev/null; netstat -ltn 2>/dev/null; ps 2>/dev/null | head -n 60
  } > /etc/jffs2/tc100/flashmode-diag.txt 2>&1; sync
  case "$r" in no*) reboot ;; esac ) &
# Card installs (scripts/flash-install.sh): a line in the card's status file.
[ -d /mnt/tc100-flash ] && echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) test boot from flash started" >> /mnt/tc100-flash/STATUS.txt && sync
exec /usr/tc100/scripts/flashboot.sh
