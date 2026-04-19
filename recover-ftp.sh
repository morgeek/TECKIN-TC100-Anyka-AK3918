#!/bin/bash
IP="192.168.1.24"
PASS="pass"

echo "Waiting for $IP to respond..."
while ! ping -c 1 -W 1 $IP > /dev/null 2>&1; do
    sleep 0.5
done
echo "Camera is up! Sending recovery payload..."

# Try configeditor to inject umount/mv payload (loop until success or timeout)
echo "Attempting to inject payload into boot.conf..."
for i in {1..20}; do
  echo "Web attempt $i..."
  if curl -s -k -u root:$PASS -X POST "https://$IP/cgi-bin/configeditor.cgi?cmd=save&file=boot.conf" \
       -d "umount /bin/busybox; /bin/busybox mv /mnt/bin/busybox.old /mnt/bin/busybox; /bin/busybox chmod +x /mnt/bin/busybox; /mnt/controlscripts/ftp-server start" | grep -q '"ok":true'; then
    echo "Payload injected successfully!"
    break
  fi
  sleep 1
done

# Try starting FTP anyway
curl -s -k -u root:$PASS "https://$IP/cgi-bin/scripts.cgi?cmd=enable&script=ftp-server"
curl -s -k -u root:$PASS "https://$IP/cgi-bin/scripts.cgi?cmd=start&script=ftp-server"

echo "Done. Waiting 5s for FTP to start..."
sleep 5
curl -v -P - ftp://root:$PASS@$IP:2121/mnt/ 2>&1 | head -n 20
