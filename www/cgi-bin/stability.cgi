#!/bin/sh
. /mnt/www/cgi-bin/func.cgi
printf 'Content-Type: text/csv\r\n'
printf 'Cache-Control: no-store\r\n'
printf 'Content-Disposition: attachment; filename="tc100-stability.csv"\r\n\r\n'
if [ -r /mnt/log/stability.csv ]; then
  cat /mnt/log/stability.csv
else
  printf 'timestamp,uptime_s,load1,mem_available_kb,unhealthy_services\n'
fi
