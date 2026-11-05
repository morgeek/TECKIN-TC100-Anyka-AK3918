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

# Item 36, the day's index for the recordings timeline (the page draws it; here one stat, one date and one awk):
#   {"seg":S,"files":[{"t":"HH-MM-SS","x":"mp4","d":D,"kb":K,"e":[on,off,...]},...]}
# t = start (local time, from the name), d = seconds until the file's last write (its mtime; -1 when that does not
# fit: clock or time zone changed, file still open long ago), e = event spans in seconds from the file start, from
# the recorder's .evt marker ("on S" / "off S" lines; -1 = until the end of the file; [] = an old empty marker; no
# "e" = no event), seg = REC_SEGMENT_SEC.
rec_day_index() {
  ( cd "$DCIM_FOLDER" 2>/dev/null || { echo '{"seg":300,"files":[]}'; exit 0; }
    _now=$(date '+%s %H %M %S')
    stat -c '%n %Y %s' "$1"_??-??-??.* 2>/dev/null | awk -v now="$_now" -v conf=/mnt/config/boot.conf '
      BEGIN {
        seg = 300
        while ((getline l < conf) > 0) if (l ~ /^REC_SEGMENT_SEC=[0-9]+/) { sub(/^REC_SEGMENT_SEC=/, "", l); seg = l + 0 }
        close(conf)
        if (seg < 10) seg = 300
        split(now, n, " "); off = (n[2] * 3600 + n[3] * 60 + n[4]) - (n[1] % 86400)
        if (off > 50400) off -= 86400; if (off < -50400) off += 86400
      }
      {
        name = $1; base = substr(name, 1, 19); x = substr(name, 21)
        if (length(name) < 23 || substr(name, 20, 1) != ".") next
        if (x == "evt") { evt[base] = name; evs[base] = $3; next }
        if (x != "mp4" && x != "mkv") next
        t = substr(base, 12, 8); st = substr(t, 1, 2) * 3600 + substr(t, 4, 2) * 60 + substr(t, 7, 2)
        end = ($2 + off) % 86400; if (end < 0) end += 86400; if (end < st) end += 86400
        d = end - st; if (d < 0 || d > seg + 120) d = -1
        nf++; fb[nf] = base; ft[nf] = t; fx[nf] = x; fd[nf] = d; fk[nf] = int(($3 + 1023) / 1024)
      }
      END {
        printf "{\"seg\":%d,\"files\":[", seg
        for (i = 1; i <= nf; i++) {
          printf "%s{\"t\":\"%s\",\"x\":\"%s\",\"d\":%d,\"kb\":%d", (i > 1 ? "," : ""), ft[i], fx[i], fd[i], fk[i]
          b = fb[i]
          if (b in evt) {
            e = ""; on = -2; c = 0
            if (evs[b] > 0) {
              while ((getline l < evt[b]) > 0 && c < 64) {
                c++
                if (split(l, w, " ") != 2 || w[2] !~ /^[0-9]+$/) continue
                if (w[1] == "on" && on < -1) on = w[2] + 0
                else if (w[1] == "off" && on > -2) { e = e (e == "" ? "" : ",") on "," (w[2] + 0); on = -2 }
              }
              close(evt[b])
            }
            if (on > -2) e = e (e == "" ? "" : ",") on ",-1"
            printf ",\"e\":[%s]", e
          }
          printf "}"
        }
        printf "]}\n"
      }' )
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
          case "$fullpath" in *.mp4|*.mkv) rm -f "${fullpath%.*}.jpg" "${fullpath%.*}.evt" ;; esac
          rm -f "$fullpath" && echo '{"ok":true}' || echo '{"ok":false,"error":"delete failed"}'
        else
          echo '{"ok":false,"error":"file not found"}'
        fi
      fi
    ;;

    disk_usage)
      # Returns SD card usage stats for the recordings area
      _total=0; _used=0; _avail=0; _pct=0
      # the file system that holds the recordings: the SD card (/mnt/DCIM may be a link to it; in flash mode /mnt
      # itself is the small read-only system, which df /mnt reported instead of the card)
      _dir="$DCIM_FOLDER/"; [ -d "$_dir" ] || _dir=/mnt/sd/
      set -- $(df -kP "$_dir" 2>/dev/null | tail -n 1)
      case "$2:$3:$4" in *[!0-9:]*|::*) ;; *)
        _total="$2"; _used="$3"; _avail="$4"; _pct="${5%%%}"; case "$_pct" in ''|*[!0-9]*) _pct=0 ;; esac ;;
      esac
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

    day_index)
      dateVal="${F_date##*/}"
      case "$dateVal" in
        [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) rec_day_index "$dateVal" ;;
        *) echo '{"seg":300,"files":[]}' ;;
      esac
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
      echo "Unsupported command"	# the value is not printed back: a crafted link would run script in the page
   ;;
  esac
fi
