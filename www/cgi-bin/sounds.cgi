#!/bin/sh
# sounds.cgi: the speaker's sounds (item 48 of the implementer list). Built-in clips are in /mnt/sounds (flash);
# custom ones go to the SD card, /mnt/sd/tc100-3/sounds (SOUNDS_SD, common_functions.sh); a custom clip with the
# name of a built-in one replaces it everywhere (startup, siren: dashboard buttons, MQTT,
# startup). Clips are raw 8 kHz mono signed 16-bit little endian: Settings converts any file the browser decodes
# (WAV, MP3, OGG...) before sending it, so the camera only stores bytes.
#   GET  ?cmd=list               {"ok":true,"sd":true,"boot":{"on":1,"name":"startup"},
#                                 "sounds":[{"name":"siren","builtin":1,"custom":0,"bytes":32000},...]}
#   POST ?cmd=upload&name=NAME   body: the PCM (even length, 30 s at most); NAME: 1-32 of A-Z a-z 0-9 _ -
#   POST ?cmd=delete&name=NAME   removes the custom clip (a built-in one of that name is used again)
#   POST ?cmd=play&name=NAME     plays it at the push-to-talk volume
#   POST ?cmd=playnow            body: the PCM; played once from RAM and deleted (no card needed, nothing kept)
#   POST ?cmd=boot&name=NAME|0   startup sound: BOOT_SOUND=1 and BOOT_SOUND_NAME=NAME, or BOOT_SOUND=0 (silent)
FUNC_CGI_SKIP_BODY=1	# the upload body is PCM, not a form
. /mnt/www/cgi-bin/func.cgi
. /mnt/scripts/common_functions.sh

MAX_BYTES=480000	# 30 s
MAX_FILES=32
BOOT_CONF=/mnt/config/boot.conf

reply() { printf 'Status: %s\nContent-Type: application/json\nCache-Control: no-store\n\n%s\n' "$1" "$2"; }
fail() { reply "$1" "{\"ok\":false,\"error\":\"$2\"}"; exit 0; }
# a real card: the 16 KiB RAM placeholder that rec-storage.sh mounts on /mnt/sd without one is tmpfs, not a card
sd_ok() { grep -qE ' /mnt/sd (vfat|exfat) ' /proc/mounts 2>/dev/null; }
mem_kb() { awk '$1 == "MemAvailable:" { print $2 }' /proc/meminfo 2>/dev/null; }
# check_body: an even, non-empty body of 30 s at most (raw 8 kHz mono S16LE)
check_body() {
  case "$CONTENT_LENGTH" in ''|*[!0-9]*) fail "411 Length Required" "no length" ;; esac
  [ "$CONTENT_LENGTH" -gt 0 ] || fail "400 Bad Request" "empty"
  [ $((CONTENT_LENGTH % 2)) = 0 ] || fail "400 Bad Request" "not 16-bit PCM"
  [ "$CONTENT_LENGTH" -le $MAX_BYTES ] || fail "413 Payload Too Large" "30 seconds at most"
}

# one stat and one awk: built-in clips first, then the custom ones that are not also built in
sound_list() {
  _on=1; _bn=startup
  [ -r "$BOOT_CONF" ] && while IFS='=' read -r _k _v; do
    _v=${_v#\"}; _v=${_v%\"}
    case "$_k" in BOOT_SOUND) _on=$_v ;; BOOT_SOUND_NAME) _bn=$_v ;; esac
  done < "$BOOT_CONF"
  case "$_on" in 0|false|no|off|disabled) _on=0 ;; *) _on=1 ;; esac
  case "$_bn" in ''|*[!A-Za-z0-9_-]*) _bn=startup ;; esac
  _sd=false; sd_ok && _sd=true
  # built-in clips: NAME.alaw (one byte a sample, rc31) or NAME.pcm; "bytes" is the 16-bit size (seconds = bytes / 16000)
  stat -c '%n %s' /mnt/sounds/*.alaw /mnt/sounds/*.pcm "$SOUNDS_SD"/*.pcm 2>/dev/null | awk -v sd="$SOUNDS_SD/" -v on="$_on" -v bn="$_bn" -v card="$_sd" '
    {
      p = $1; n = p; sub(/.*\//, "", n); b = $2; if (sub(/\.alaw$/, "", n)) b = 2 * $2; else sub(/\.pcm$/, "", n)
      if (n !~ /^[A-Za-z0-9_-]+$/ || n ~ /^test-1k-/) next
      if (!(n in seen)) { seen[n] = 1; order[++c] = n }
      if (substr(p, 1, length(sd)) == sd) { cu[n] = 1; size[n] = b } else { bi[n] = 1; if (!(n in size)) size[n] = b }
    }
    END {
      printf "{\"ok\":true,\"sd\":%s,\"boot\":{\"on\":%d,\"name\":\"%s\"},\"sounds\":[", card, on, bn
      for (i = 1; i <= c; i++) {
        n = order[i]
        printf "%s{\"name\":\"%s\",\"builtin\":%d,\"custom\":%d,\"bytes\":%d}", (i > 1 ? "," : ""), n, (n in bi), (n in cu), size[n]
      }
      printf "]}"
    }'
}

cmd=${F_cmd:-list}
name=${F_name:-}
case "$cmd" in
  list) reply "200 OK" "$(sound_list)"; exit 0 ;;
  upload|delete|play|boot|playnow) mutation_guard; rate_limit_check 20 60 ;;
  *) fail "400 Bad Request" "unknown command" ;;
esac
if [ "$cmd" = playnow ] || { [ "$cmd" = boot ] && [ "$name" = 0 ]; }; then :; else
  case "$name" in ''|*[!A-Za-z0-9_-]*) fail "400 Bad Request" "name: 1 to 32 of A-Z a-z 0-9 _ -" ;; esac
  [ ${#name} -le 32 ] || fail "400 Bad Request" "name: 1 to 32 of A-Z a-z 0-9 _ -"
fi

case "$cmd" in
  upload)
    sd_ok || fail "409 Conflict" "no SD card"
    check_body
    mkdir -p "$SOUNDS_SD" 2>/dev/null || fail "500 Internal Server Error" "cannot create the folder on the card"
    if [ ! -f "$SOUNDS_SD/$name.pcm" ]; then
      set -- "$SOUNDS_SD"/*.pcm
      [ -e "$1" ] && [ $# -ge $MAX_FILES ] && fail "409 Conflict" "$MAX_FILES custom sounds at most"
    fi
    _tmp="$SOUNDS_SD/.$name.part"
    head -c "$CONTENT_LENGTH" > "$_tmp" 2>/dev/null
    _n=$(wc -c < "$_tmp" 2>/dev/null)
    if [ "${_n:-0}" != "$CONTENT_LENGTH" ]; then rm -f "$_tmp"; fail "400 Bad Request" "upload cut short"; fi
    mv -f "$_tmp" "$SOUNDS_SD/$name.pcm" || { rm -f "$_tmp"; fail "500 Internal Server Error" "cannot write to the card"; }
    sync
    audit_log_event sound_upload "$name $CONTENT_LENGTH"
    reply "200 OK" "{\"ok\":true,\"name\":\"$name\",\"bytes\":$CONTENT_LENGTH}"
    ;;
  delete)
    [ -f "$SOUNDS_SD/$name.pcm" ] || fail "404 Not Found" "no custom sound of that name"
    rm -f "$SOUNDS_SD/$name.pcm" || fail "500 Internal Server Error" "cannot delete"
    audit_log_event sound_delete "$name"
    reply "200 OK" '{"ok":true}'
    ;;
  play)
    _p=$(sound_path "$name") || fail "404 Not Found" "no sound of that name"
    [ -d /tmp/speaker-play.lock ] && fail "429 Too Many Requests" "the speaker is busy"
    _vol=$(head -n 1 /mnt/config/pttvolume.conf 2>/dev/null)
    case "$_vol" in ''|*[!0-9]*) _vol=90 ;; esac
    sh /mnt/scripts/speaker-play.sh "$_p" "$_vol" </dev/null >/dev/null 2>&1 &
    reply "200 OK" '{"ok":true}'
    ;;
  playnow)
    # no card (both cameras of the owner): the clip is played once from RAM, then deleted (owner, 2026-11-06)
    check_body
    [ -d /tmp/speaker-play.lock ] && fail "429 Too Many Requests" "the speaker is busy"
    _avail=$(mem_kb)
    case "$_avail" in ''|*[!0-9]*) _avail=0 ;; esac
    # the clip in /tmp (RAM) and 6 MB left for the streams
    [ "$_avail" -ge $((CONTENT_LENGTH / 1024 + 6144)) ] || fail "507 Insufficient Storage" "not enough free memory to play it now"
    _now="${SOUNDS_TMP:-/tmp}/sound-now.$$.pcm"
    head -c "$CONTENT_LENGTH" > "$_now" 2>/dev/null
    _n=$(wc -c < "$_now" 2>/dev/null)
    if [ "${_n:-0}" != "$CONTENT_LENGTH" ]; then rm -f "$_now"; fail "400 Bad Request" "upload cut short"; fi
    _vol=$(head -n 1 /mnt/config/pttvolume.conf 2>/dev/null)
    case "$_vol" in ''|*[!0-9]*) _vol=90 ;; esac
    ( sh /mnt/scripts/speaker-play.sh "$_now" "$_vol"; rm -f "$_now" ) </dev/null >/dev/null 2>&1 &
    audit_log_event sound_playnow "$CONTENT_LENGTH"
    reply "200 OK" "{\"ok\":true,\"kept\":false,\"bytes\":$CONTENT_LENGTH}"
    ;;
  boot)
    install_config "$BOOT_CONF"
    if [ "$name" = 0 ]; then
      rewrite_config "$BOOT_CONF" BOOT_SOUND 0
    else
      sound_path "$name" >/dev/null || fail "404 Not Found" "no sound of that name"
      grep -q '^BOOT_SOUND_NAME=' "$BOOT_CONF" 2>/dev/null || echo "BOOT_SOUND_NAME=startup" >> "$BOOT_CONF"
      grep -q '^BOOT_SOUND=' "$BOOT_CONF" 2>/dev/null || echo "BOOT_SOUND=1" >> "$BOOT_CONF"
      rewrite_config "$BOOT_CONF" BOOT_SOUND 1
      rewrite_config "$BOOT_CONF" BOOT_SOUND_NAME "$name"
    fi
    reply "200 OK" '{"ok":true}'
    ;;
esac
