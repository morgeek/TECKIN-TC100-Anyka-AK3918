#!/bin/sh

. /mnt/www/cgi-bin/func.cgi

DCIM_FOLDER="/mnt/DCIM"


echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

if [ -n "$F_cmd" ]; then
  case "$F_cmd" in
    remove_record)
      record="${F_record##*/}"
      fullpath=${DCIM_FOLDER}/${record}
      rm -f "$fullpath"
    ;;

    list_dates)
      echo "["
      sep=""
      files="$(/mnt/bin/min-recorder-list p $DCIM_FOLDER)"
      for file in $files; do
        printf '%s{"date":"%s"}\n' "$sep" "$file"
        sep=","
      done
      echo "]"
    ;;

    list_records)
      dateVal="${F_date##*/}"
      echo "["
      sep=""
      files="$(/mnt/bin/min-recorder-list p $DCIM_FOLDER f $dateVal)"
      for file in $files; do
        printf '%s{"record":"%s"}\n' "$sep" "$file"
        sep=","
      done
      echo "]"
    ;;

    *)
      echo "Unsupported command '$F_cmd'"
   ;;
  esac
fi
