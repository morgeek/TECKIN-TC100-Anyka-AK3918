#!/bin/sh
# ONE-SHOT test of the flash mode (no SD firmware) on a test camera, 2026-10-15.
# Run by /usr/sbin/service.sh because /mnt/wifitest was renamed wifitest.off.
# First thing: make the next boot a normal SD boot and remove this script.
L=/tmp/log/fbtest.log
mkdir -p /tmp/log
echo "fbtest start uptime $(cut -d' ' -f1 /proc/uptime)" >> $L
[ -d /mnt/wifitest.off ] && mv /mnt/wifitest.off /mnt/wifitest
rm -f /etc/jffs2/tc100/boot.sh
sync
echo "sd hook restored: $(ls -d /mnt/wifitest 2>&1)" >> $L

# No network 6 min from now: reboot (normal SD boot).
( sleep 360
  gw=$(route -n | awk '$1=="0.0.0.0" {print $2; exit}')
  if [ -n "$gw" ] && ping -c 2 -W 3 "$gw" >/dev/null 2>&1; then
      echo "fbtest: network ok (gw $gw)" >> $L
  else
      echo "fbtest: no network, reboot" >> $L; sync; reboot
  fi ) &

# This service.sh (first flash image) also starts the vendor network manager.
( i=0; while [ $i -lt 30 ]; do killall net_manage.sh 2>/dev/null; i=$((i + 1)); sleep 1; done ) &

# Test image from the card (the second flash /usr, not written yet).
mkdir -p /tmp/sd
mount -t vfat /dev/mmcblk0p1 /tmp/sd || { echo "fbtest: no sd at /tmp/sd" >> $L; telnetd -p 23; exit 1; }
md5=$(md5sum /tmp/sd/flashtest/usr-v2.img | cut -d' ' -f1)
echo "fbtest: image md5 $md5" >> $L
[ "$md5" = "$(cat /tmp/sd/flashtest/usr-v2.img.md5)" ] || { echo "fbtest: bad image" >> $L; telnetd -p 23; exit 1; }
mount -t squashfs -o loop,ro /tmp/sd/flashtest/usr-v2.img /usr || { echo "fbtest: mount failed" >> $L; telnetd -p 23; exit 1; }

# One-time copy of the SD card configuration into jffs2.
if [ ! -d /etc/jffs2/tc100/config ]; then
    mkdir -p /etc/jffs2/tc100/config
    for f in /tmp/sd/config/*; do
        n=${f##*/}
        case "$n" in *.dist|*.pre-migrate|*.expired|lighttpd.pem*|openssl.cnf|packages.lock|ssl) continue ;; esac
        cp -a "$f" /etc/jffs2/tc100/config/
    done
    [ -f /tmp/sd/config/.wizard_done ] && cp /tmp/sd/config/.wizard_done /etc/jffs2/tc100/config/
    sync
    echo "fbtest: config copied ($(du -sk /etc/jffs2/tc100/config | cut -f1) KB)" >> $L
fi
echo "fbtest: starting flashboot" >> $L
exec /usr/tc100/scripts/flashboot.sh
