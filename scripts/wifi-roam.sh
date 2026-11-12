#!/bin/sh
# wifi-roam.sh — leave a weak access point for a much better one of the same network (item 40 of the implementer list).
#
# With repeaters or a mesh (one SSID, several BSSIDs) a station tends to stay on the access point it first joined
# ("sticky client") even when another one is far better. Every minute (housekeeper job "wifi-roam", registered by
# v3/autorun-linux66.sh when boot.conf WIFI_ROAM=1): when the signal (scripts/wifi-signal.sh) has been below
# ROAM_BELOW (-75 dBm) at two checks in a row, a scan; an access point of the same SSID at least ROAM_BETTER (15) dB
# stronger gets a `wpa_cli roam <bssid>` (wpa_supplicant moves without pinning the BSSID); then nothing for 10 minutes.
#
#   wifi-roam.sh once     one check (the job)
WR_STATE="${WRO_STATE:-/tmp/wifi-roam}"
WPA_CLI="${WRO_WPA_CLI:-wpa_cli}"
BELOW="${ROAM_BELOW:--75}"
BETTER="${ROAM_BETTER:-15}"
HOLD="${ROAM_HOLD:-600}"
[ -d "$WR_STATE" ] || mkdir -p "$WR_STATE" 2>/dev/null

log() { logger -t tc100-event -p user.notice "wifi-roam: $*" 2>/dev/null; }

[ "$1" = once ] || { echo "usage: wifi-roam.sh once" >&2; exit 2; }
if [ -n "$WRO_NOW" ]; then t=$WRO_NOW; else t=; read -r t _ < /proc/uptime; t=${t%%.*}; fi	# no fork: this runs every minute
last=0; [ -r "$WR_STATE/last" ] && read -r last < "$WR_STATE/last"
case "$last" in ''|*[!0-9]*) last=0 ;; esac
[ "$last" -gt 0 ] && [ $((t - last)) -lt "$HOLD" ] && exit 0

if [ -n "$WRO_DBM" ]; then WIFI_DBM="$WRO_DBM"
else WIFI_DBM=; . /mnt/scripts/wifi-signal.sh 2>/dev/null && wifi_signal_read; fi
case "$WIFI_DBM" in ''|*[!0-9-]*) [ -e "$WR_STATE/weak" ] && rm -f "$WR_STATE/weak"; exit 0 ;; esac
if [ "$WIFI_DBM" -ge "$BELOW" ]; then [ -e "$WR_STATE/weak" ] && rm -f "$WR_STATE/weak"; exit 0; fi
weak=0; [ -r "$WR_STATE/weak" ] && read -r weak < "$WR_STATE/weak"
case "$weak" in ''|*[!0-9]*) weak=0 ;; esac
weak=$((weak + 1)); echo "$weak" > "$WR_STATE/weak"
[ "$weak" -ge 2 ] || exit 0

st=$($WPA_CLI -i wlan0 status 2>/dev/null)
cur=$(printf '%s\n' "$st" | sed -n 's/^bssid=//p' | tr 'A-F' 'a-f')
ssid=$(printf '%s\n' "$st" | sed -n 's/^ssid=//p')
[ -n "$cur" ] && [ -n "$ssid" ] || exit 0
$WPA_CLI -i wlan0 scan >/dev/null 2>&1
sleep "${WRO_SCAN_WAIT:-5}"
# scan_results: "bssid / frequency / signal level / flags / ssid", tab separated, after a header line
best=$($WPA_CLI -i wlan0 scan_results 2>/dev/null | awk -F'\t' -v s="$ssid" -v cur="$cur" -v need=$((WIFI_DBM + BETTER)) '
  NR > 1 && $5 == s && tolower($1) != cur && $3 + 0 >= need && (b == "" || $3 + 0 > bs) { b = tolower($1); bs = $3 + 0 }
  END { if (b != "") print b, bs }')
echo 0 > "$WR_STATE/weak"
[ -n "$best" ] || { log "weak signal ($WIFI_DBM dBm) on $cur, no access point of \"$ssid\" ${BETTER} dB better"; exit 0; }
set -- $best
log "weak signal ($WIFI_DBM dBm) on $cur: roaming to $1 ($2 dBm)"
$WPA_CLI -i wlan0 roam "$1" >/dev/null 2>&1
echo "$t" > "$WR_STATE/last"
exit 0
