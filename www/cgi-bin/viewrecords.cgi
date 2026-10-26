#!/bin/sh

. /mnt/www/cgi-bin/func.cgi

DCIM_FOLDER="/mnt/DCIM"

# Rate-limit and CSRF-guard destructive operations (before headers)
case "$F_cmd" in
  remove_record) rate_limit_check 10 60; mutation_guard ;;
esac

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

# Recordings: YYYY-MM-DD_HH-MM-SS.mp4 (3.0 recorder, fragmented MP4) or .mkv (older recorders), newest first.
#   rec_dates          one YYYY-MM-DD per line
#   rec_files DATE     HH-MM-SS.mp4 / .mkv of that day
rec_dates() {
  for _f in "$DCIM_FOLDER"/????-??-??_??-??-??.mp4 "$DCIM_FOLDER"/????-??-??_??-??-??.mkv; do
    [ -f "$_f" ] || continue
    _f="${_f##*/}"; echo "${_f%%_*}"
  done | sort -r | awk '!seen[$0]++'
}
rec_files() {
  for _f in "$DCIM_FOLDER/$1"_??-??-??.mp4 "$DCIM_FOLDER/$1"_??-??-??.mkv; do
    [ -f "$_f" ] || continue
    _f="${_f##*/}"; echo "${_f#*_}"
  done | sort -r
}

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
          # the picture the 3.0 recorder writes next to each file goes with it
          case "$fullpath" in *.mp4|*.mkv) rm -f "${fullpath%.*}.jpg" ;; esac
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
      files="$(rec_dates)"
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
      case "$dateVal" in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) files="$(rec_files "$dateVal")" ;; *) files="" ;; esac
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
