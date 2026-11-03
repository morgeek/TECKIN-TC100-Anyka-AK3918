#!/bin/sh
. /mnt/www/cgi-bin/func.cgi
printf 'Content-Type: text/csv\r\n'
printf 'Cache-Control: no-store\r\n'
printf 'Content-Disposition: attachment; filename="tc100-stability.csv"\r\n\r\n'
# the card (scripts/health-snapshot.sh writes there when one is mounted), else RAM
if [ -r /mnt/sd/logs/stability.csv ]; then
  cat /mnt/sd/logs/stability.csv
elif [ -r /mnt/log/stability.csv ]; then
  cat /mnt/log/stability.csv
else
  printf 'timestamp,uptime_s,load1,mem_available_kb,unhealthy_services\n'
fi
# Samples of the last hour are still in RAM (health-snapshot.sh batches the
# SD writes).
cat /tmp/log/stability.pending 2>/dev/null
exit 0
