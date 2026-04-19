#!/bin/sh

. /mnt/www/cgi-bin/func.cgi

DCIM_FOLDER="/mnt/DCIM"

# Rate-limit only destructive operations (before headers)
case "$F_cmd" in
  remove_record) rate_limit_check 10 60 ;;
esac

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

sanitize_record_name() {
  # Strip path components and allow only safe filename characters
  _rn="${1##*/}"
  case "$_rn" in
    *[!A-Za-z0-9._-]*|..|.)
      echo ""
      return 1
      ;;
  esac
  echo "$_rn"
}

if [ -n "$F_cmd" ]; then
  case "$F_cmd" in
    remove_record)
      record="$(sanitize_record_name "${F_record}")"
      if [ -z "$record" ]; then
        echo '{"ok":false,"error":"invalid filename"}'
      else
        fullpath="${DCIM_FOLDER}/${record}"
        if [ -f "$fullpath" ]; then
          rm -f "$fullpath" && echo '{"ok":true}' || echo '{"ok":false,"error":"delete failed"}'
        else
          echo '{"ok":false,"error":"file not found"}'
        fi
      fi
    ;;

    disk_usage)
      # Returns SD card usage stats for the recordings area
      _total=0; _used=0; _avail=0; _pct=0
      while read -r _fs _t _u _a _p _mp _rest; do
        case "$_mp" in /mnt|/mnt/)
          case "$_t" in ''|*[!0-9]*) continue ;; esac
          _total="$_t"; _used="$_u"; _avail="$_a"
          _pct_raw="${_p%%%}"; case "$_pct_raw" in ''|*[!0-9]*) _pct_raw=0 ;; esac
          _pct="$_pct_raw"
          break
        ;; esac
      done <<EOF
$(df -k /mnt 2>/dev/null | tail -n +2)
EOF
      printf '{"total_kb":%s,"used_kb":%s,"avail_kb":%s,"percent":%s}\n' \
        "$_total" "$_used" "$_avail" "$_pct"
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
