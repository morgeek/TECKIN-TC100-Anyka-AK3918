#!/bin/sh
# wifi-txt.sh — Wi-Fi settings from a wifi.txt file at the root of the SD card.
#
#   wifi-txt.sh apply <wifi.txt> <wpa_supplicant.conf> [anyka_cfg.ini]
#
# wifi.txt (any editor, Windows line endings accepted):
#   SSID=MyNetwork
#   PASSWORD=my password        (8-63 characters; empty or absent = open network)
#
# Writes <wpa_supplicant.conf> (the file the firmware connects with; the
# networks it held before stay in it as a fallback), then
# replaces wifi.txt with wifi-applied.txt, which keeps the network name and the
# date but not the password: the card does not carry it afterwards.
# Exit 0 applied, 1 no file, 2 invalid file (renamed wifi-invalid.txt, with
# the reason, so it is not tried at every boot).
#
# Called at boot before the Wi-Fi starts: by scripts/flashboot.sh from flash
# (the conf is kept in jffs2), and by autorun.sh from the SD card.

_wt_log() { logger -t tc100-event -p user.warn "wifi.txt: $*" 2>/dev/null; echo "wifi.txt: $*"; }

wt_apply()
{
    _src="$1"; _out="$2"
    [ -f "$_src" ] || return 1
    _dir="${_src%/*}"
    _ssid=""; _psk=""; _have_psk=0
    while IFS= read -r _l || [ -n "$_l" ]; do
        _l="${_l%"$(printf '\r')"}"
        case "$_l" in ''|'#'*) continue ;; esac
        _k="${_l%%=*}"; _v="${_l#*=}"
        [ "$_k" = "$_l" ] && continue
        _k="$(echo "$_k" | awk '{ gsub(/^[ \t]+|[ \t]+$/, ""); print toupper($0) }')"
        # Surrounding quotes are optional.
        case "$_v" in \"*\") _v="${_v#\"}"; _v="${_v%\"}" ;; esac
        case "$_k" in
            SSID) _ssid="$_v" ;;
            PASSWORD|PSK|PASS|KEY) _psk="$_v"; _have_psk=1 ;;
        esac
    done < "$_src"
    _why=""
    _sl=${#_ssid}; _pl=${#_psk}
    if [ "$_sl" -lt 1 ] || [ "$_sl" -gt 32 ]; then _why="SSID must be 1-32 characters"
    elif [ "$_have_psk" = 1 ] && [ "$_pl" -gt 0 ] && { [ "$_pl" -lt 8 ] || [ "$_pl" -gt 63 ]; }; then _why="PASSWORD must be 8-63 characters"
    else
        case "$_ssid$_psk" in *\"*|*\\*) _why="no \" or \\ in the SSID or password" ;; esac
    fi
    if [ -n "$_why" ]; then
        { echo "Not applied: $_why"; echo "Fix it and save the file again as wifi.txt."; } > "$_dir/wifi-invalid.txt"
        rm -f "$_src"; sync
        _wt_log "invalid ($_why), renamed wifi-invalid.txt"
        return 2
    fi
    _tmp="$_out.tmp.$$"
    {
        printf 'ctrl_interface=/var/run/wpa_supplicant\n'
        printf 'ctrl_interface_group=0\n'
        printf 'ap_scan=1\n'
        printf 'network={\n'
        printf '\tssid="%s"\n' "$_ssid"
        printf '\tscan_ssid=1\n'
        if [ "$_pl" -gt 0 ]; then
            printf '\tkey_mgmt=WPA-PSK\n'
            printf '\tpsk="%s"\n' "$_psk"
        else
            printf '\tkey_mgmt=NONE\n'
        fi
        printf '\tpriority=2\n'
        printf '}\n'
        # The networks of the previous file stay as a fallback (priority 1):
        # a typo in wifi.txt does not take the camera off the old network.
        [ -f "$_out" ] && awk -v new="$_ssid" '
            /^[ \t]*network=\{/ { inb = 1; blk = ""; ss = "" }
            inb { line = $0
                  if (line ~ /^[ \t]*priority=/) next
                  if (line ~ /^[ \t]*ssid="/) { ss = line; sub(/^[ \t]*ssid="/, "", ss); sub(/"[ \t]*$/, "", ss) }
                  if (line ~ /^[ \t]*\}/) { if (ss != new && ss != "") printf "%s\tpriority=1\n}\n", blk; inb = 0; next }
                  blk = blk line "\n" }' "$_out"
        # First file: the network the vendor setup connects to (anyka_cfg.ini,
        # [wireless] ssid/password) is the fallback.
        if [ ! -f "$_out" ] && [ -n "$3" ] && [ -r "$3" ]; then
            awk -v new="$_ssid" '
                function val(s) { sub(/^[^=]*=[ \t]*/, "", s); sub(/[ \t]*;.*$/, "", s); gsub(/"/, "", s)
                                  gsub(/\001/, "=", s); gsub(/\002/, ";", s); gsub(/\003/, "\"", s); gsub(/\005/, " ", s); return s }
                /^\[/ { w = ($0 ~ /^\[wireless\]/) }
                w && /^ssid[ \t]*=/ { ss = val($0) }
                w && /^password[ \t]*=/ { pw = val($0) }
                END { if (ss != "" && ss != new && ss !~ /["\\]/ && pw !~ /["\\]/) {
                        printf "network={\n\tssid=\"%s\"\n\tscan_ssid=1\n", ss
                        if (length(pw) >= 8) printf "\tkey_mgmt=WPA-PSK\n\tpsk=\"%s\"\n", pw
                        else printf "\tkey_mgmt=NONE\n"
                        printf "\tpriority=1\n}\n" } }' "$3"
        fi
    } > "$_tmp" && chmod 600 "$_tmp" && mv -f "$_tmp" "$_out" || { rm -f "$_tmp"; _wt_log "could not write $_out"; return 2; }
    { echo "Applied $(date '+%Y-%m-%d %H:%M' 2>/dev/null): network \"$_ssid\"."
      echo "The password was removed from the card. To change the Wi-Fi again,"
      echo "write a new wifi.txt (SSID=... and PASSWORD=... lines)."; } > "$_dir/wifi-applied.txt"
    rm -f "$_src"; sync
    _wt_log "Wi-Fi set to \"$_ssid\""
    return 0
}

case "${0##*/}" in
    wifi-txt.sh)
        case "$1" in
            apply) wt_apply "$2" "$3" "$4" ;;
            *) echo "usage: $0 apply <wifi.txt> <wpa_supplicant.conf>" >&2; exit 2 ;;
        esac ;;
esac
