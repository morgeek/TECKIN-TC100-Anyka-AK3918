#!/bin/sh
# savedlogs.cgi: the logs of the previous boots that scripts/log-persist.sh copied to the SD card.
#   GET /cgi-bin/savedlogs.cgi                       JSON list of the saved boots, newest first
#   GET /cgi-bin/savedlogs.cgi?boot=boot-0007&file=dmesg.log     one file (text; names are checked)
# The Logs page shows the list and downloads the files.

. /mnt/www/cgi-bin/func.cgi
rate_limit_check 30 60

case "$F_boot" in
  '')
    echo "Content-type: application/json"
    echo "Pragma: no-cache"
    echo "Cache-Control: no-store, no-cache"
    echo ""
    sh /mnt/scripts/log-persist.sh list 2>/dev/null || echo "[]"
    ;;
  *)
    case "$F_boot" in boot-[0-9][0-9][0-9][0-9]) ;; *) F_boot="" ;; esac
    case "$F_file" in ''|*[!A-Za-z0-9._-]*|.*) F_file="" ;; esac
    if [ -z "$F_boot" ] || [ -z "$F_file" ]; then
      echo "Status: 400 Bad Request"
      echo "Content-type: text/plain"
      echo ""
      echo "bad request"
      exit 0
    fi
    echo "Content-type: text/plain; charset=utf-8"
    echo "Content-Disposition: attachment; filename=\"${F_boot}-${F_file}\""
    echo "Cache-Control: no-store, no-cache"
    echo ""
    sh /mnt/scripts/log-persist.sh cat "$F_boot" "$F_file" 2>&1
    ;;
esac
