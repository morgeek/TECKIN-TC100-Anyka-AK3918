#!/bin/sh
# The ONE reader of the Wi-Fi signal. Source it, then call (no fork):
#   wifi_signal_read [any]
# Sets WIFI_DBM   signal level in dBm (-110..-1), empty when unknown. The RTL8188FU driver reports -256 for "no
#                 reading" and 0 on an idle interface: both are "unknown", never a level.
#      WIFI_QUAL  link quality, a number (0-100 scale of the driver), empty when unknown
#      WIFI_IF    the interface the values come from
# Reads wlan0 of /proc/net/wireless; "any" falls back to the first interface with a non-zero link quality (the idle
# AP interface wlan1 is all zeros). Returns 1 when no interface was found. Test hook: WIFI_PROC_FILE (a file instead
# of /proc/net/wireless).
# Used by wifi-quality.sh, mqtt-bridge.sh, www/cgi-bin/{dash,metrics,statelib}.cgi. Each caller decides how
# "unknown" is printed (JSON null, Prometheus: no sample).
wifi_signal_read() {
  WIFI_DBM=""; WIFI_QUAL=""; WIFI_IF=""
  _ws_src="${WIFI_PROC_FILE:-/proc/net/wireless}"
  [ -r "$_ws_src" ] || return 1
  while read -r _ws_if _ws_st _ws_lk _ws_lv _ws_rest; do
    case "$_ws_if" in *:) ;; *) continue ;; esac
    _ws_if="${_ws_if%:}"
    _ws_lk="${_ws_lk%%.*}"; _ws_lv="${_ws_lv%%.*}"
    case "$_ws_lk" in ''|*[!0-9]*) _ws_lk="" ;; esac
    if [ "$_ws_if" != wlan0 ]; then
      [ "$1" = any ] && [ -z "$WIFI_IF" ] && [ -n "$_ws_lk" ] && [ "$_ws_lk" -gt 0 ] || continue
    fi
    WIFI_IF="$_ws_if"; WIFI_QUAL="$_ws_lk"; WIFI_DBM=""
    case "$_ws_lv" in -[0-9]|-[0-9][0-9]|-10[0-9]|-110) WIFI_DBM="$_ws_lv" ;; esac
    [ "$_ws_if" = wlan0 ] && break
  done < "$_ws_src"
  [ -n "$WIFI_IF" ]
}
