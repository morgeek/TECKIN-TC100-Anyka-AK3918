#!/bin/sh
# wifi-rescue.sh — rescue Wi-Fi access point when the camera loses its Wi-Fi.
#
# The RTL8188FU driver has a second interface (wlan1) next to the station
# (wlan0). When wlan0 stays without a working link for WIFI_RESCUE_AFTER_MIN
# minutes, hostapd (the vendor build, rtl871xdrv) starts an access point on
# wlan1 and udhcpd hands out 10.42.0.10-50: the web interface is then at
# https://10.42.0.1 to fix the Wi-Fi settings. The station keeps trying in
# the background; the access point stops once the link has been back for a
# minute and no device is using it.
#
#   wifi-rescue.sh run              the watcher (controlscripts/wifi-rescue)
#   wifi-rescue.sh start-ap [why]   start now (reset button held 3-7 s), for at
#                                   least WIFI_RESCUE_MANUAL_MIN minutes
#   wifi-rescue.sh stop-ap          stop now
#   wifi-rescue.sh status           ap=0|1, ssid, password
#
# 3.0 (Linux 6.6, /tmp/linux66): rtl8xxxu has one interface. The access point takes wlan0 itself
# (hostapd nl80211 + busybox udhcpd, web interface at http://10.42.0.1): the station is stopped meanwhile.
# The access point stays up WIFI_RESCUE_MANUAL_MIN minutes (and while a device uses it), then the station
# tries again (v3/linux66-sd/wifi-apply) for WIFI_RESCUE_AFTER_MIN minutes before the next access point.
# Saving Wi-Fi settings in the web page (wifi-apply) also ends the access point.
#
# boot.conf: WIFI_RESCUE=1, WIFI_RESCUE_AFTER_MIN=10, WIFI_RESCUE_MANUAL_MIN=15,
# WIFI_RESCUE_SSID (default TC100-<last 4 hex of the MAC>), WIFI_RESCUE_PSK
# (default: generated once, 12 characters, kept in the persistent config and
# shown in Settings), WIFI_RESCUE_CHANNEL (used when the station is not
# associated, default 6). WPA2-PSK only, never an open network.

CONF="${WR_BOOT_CONF:-/mnt/config/boot.conf}"
AP_IP=10.42.0.1
RUN="${WR_RUN:-/tmp/wifi-rescue}"
STA="${WR_STA:-wlan0}"
L66=0; [ -f "${WR_L66_FLAG:-/tmp/linux66}" ] && L66=1
if [ "$L66" = 1 ]; then AP="${WR_AP:-wlan0}"; else AP="${WR_AP:-wlan1}"; fi
# The vendor hostapd (SD-card firmware), else the one built from source
# (src/hostapd) that the code package carries: the flash /usr has none.
# 3.0: the hostapd (nl80211) of the flash image, on PATH (/mnt/ext/bin).
HOSTAPD="${WR_HOSTAPD:-}"
if [ -z "$HOSTAPD" ] && [ "$L66" = 1 ]; then
    HOSTAPD="$(command -v hostapd 2>/dev/null)"
    [ -n "$HOSTAPD" ] || HOSTAPD=/mnt/ext/bin/hostapd
fi
if [ -z "$HOSTAPD" ]; then
    for HOSTAPD in /usr/bin/hostapd /tmp/tc100code/bin/hostapd-rtw /mnt/bin/hostapd-rtw; do
        [ -x "$HOSTAPD" ] && break
    done
fi
WEB_URL="https://$AP_IP"; [ "$L66" = 1 ] && WEB_URL="http://$AP_IP"
SYS_NET="${WR_SYS_NET:-/sys/class/net}"
PROC_ARP="${WR_PROC_ARP:-/proc/net/arp}"
STEP="${WR_STEP:-30}"

_wr_kv() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" "$CONF" 2>/dev/null | tail -n 1; }
_wr_log() { logger -t tc100-event -p user.warn "wifi-rescue: $*" 2>/dev/null; echo "$(date '+%F %T' 2>/dev/null) $*" >> "$RUN/log"; }

# Persistent password file: jffs2 when running from flash, else the SD config.
_wr_pskfile()
{
    if [ "$(cat "${TC100_STORAGE_FILE:-/tmp/tc100-storage}" 2>/dev/null)" = flash ]; then
        echo "${WR_PSK_FILE:-/etc/jffs2/tc100/config/wifi_rescue.psk}"
    else
        echo "${WR_PSK_FILE:-/mnt/config/wifi_rescue.psk}"
    fi
}

wr_psk()
{
    _p="$(_wr_kv WIFI_RESCUE_PSK)"
    if [ "${#_p}" -ge 8 ] && [ "${#_p}" -le 63 ]; then echo "$_p"; return; fi
    _f="$(_wr_pskfile)"
    read -r _p < "$_f" 2>/dev/null
    if [ "${#_p}" -lt 8 ]; then
        # 12 characters, no look-alikes (0/O, 1/l/I)
        _p="$(dd if=/dev/urandom bs=48 count=1 2>/dev/null | od -An -v -tu1 | awk '
            BEGIN { c = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789" }
            { for (i = 1; i <= NF && n < 12; i++) if ($i < 4 * 56) { s = s substr(c, $i % 56 + 1, 1); n++ } }
            END { print s }')"
        [ "${#_p}" -eq 12 ] || return 1
        mkdir -p "${_f%/*}" 2>/dev/null
        ( umask 077; echo "$_p" > "$_f" )
    fi
    echo "$_p"
}

wr_ssid()
{
    _s="$(_wr_kv WIFI_RESCUE_SSID)"
    if [ -z "$_s" ]; then
        read -r _mac < "$SYS_NET/$STA/address" 2>/dev/null
        _m="${_mac#??:??:??:??:}"; _m="${_m%%:*}${_m#*:}"
        _s="TC100-$(echo "$_m" | awk '{ print toupper($0) }')"
    fi
    echo "$_s"
}

_wr_carrier() { _c=0; read -r _c < "$SYS_NET/$STA/carrier" 2>/dev/null; [ "$_c" = 1 ]; }

_wr_gw() { route -n 2>/dev/null | awk '$1 == "0.0.0.0" && $NF != "'"$AP"'" { print $2; exit }'; }

# Link usable: associated and the gateway answers.
wr_link_ok()
{
    _wr_carrier || return 1
    _g="$(_wr_gw)"
    [ -n "$_g" ] || return 1
    ping -c 1 -W 3 "$_g" >/dev/null 2>&1
}

_wr_channel()
{
    if _wr_carrier; then
        _f="$(iwconfig "$STA" 2>/dev/null | sed -n 's/.*Frequency[:=]\([0-9.]*\).*/\1/p')"
        case "$_f" in
            2.412) echo 1; return ;; 2.417) echo 2; return ;; 2.422) echo 3; return ;;
            2.427) echo 4; return ;; 2.432) echo 5; return ;; 2.437) echo 6; return ;;
            2.442) echo 7; return ;; 2.447) echo 8; return ;; 2.452) echo 9; return ;;
            2.457) echo 10; return ;; 2.462) echo 11; return ;; 2.467) echo 12; return ;;
            2.472) echo 13; return ;;
        esac
    fi
    _c="$(_wr_kv WIFI_RESCUE_CHANNEL)"
    case "$_c" in [1-9]|1[0-3]) echo "$_c" ;; *) echo 6 ;; esac
}

wr_ap_up() { [ -f "$RUN/hostapd.pid" ] && kill -0 "$(cat "$RUN/hostapd.pid" 2>/dev/null)" 2>/dev/null; }

# Devices on the access point: neighbours seen on wlan1 (ARP complete).
wr_ap_clients() { awk -v d="$AP" '$6 == d && $3 == "0x2" { n++ } END { print n + 0 }' "$PROC_ARP" 2>/dev/null; }

wr_start_ap()
{
    wr_ap_up && return 0
    [ -x "$HOSTAPD" ] || { _wr_log "no hostapd ($HOSTAPD)"; return 1; }
    [ -d "$SYS_NET/$AP" ] || { _wr_log "no $AP interface"; return 1; }
    _psk="$(wr_psk)" || { _wr_log "no password"; return 1; }
    mkdir -p "$RUN"; chmod 700 "$RUN"
    _drv=rtl871xdrv; _wmm=wme_enabled
    if [ "$L66" = 1 ]; then
        # one interface: the station gives wlan0 to the access point
        _drv=nl80211; _wmm=wmm_enabled
        killall wpa_supplicant udhcpc 2>/dev/null
        sleep 1
        ip addr flush dev "$AP" 2>/dev/null
        ip link set "$AP" down 2>/dev/null
    fi
    ( umask 077; cat > "$RUN/hostapd.conf" <<EOF
interface=$AP
driver=$_drv
ctrl_interface=$RUN/ctrl
ssid=$(wr_ssid)
channel=$(_wr_channel)
hw_mode=g
ieee80211n=1
$_wmm=1
beacon_int=100
max_num_sta=4
ignore_broadcast_ssid=0
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=$_psk
EOF
    )
    cat > "$RUN/udhcpd.conf" <<EOF
start 10.42.0.10
end 10.42.0.50
interface $AP
max_leases 8
lease_file $RUN/udhcpd.leases
pidfile $RUN/udhcpd.pid
option subnet 255.255.255.0
option lease 3600
EOF
    : > "$RUN/udhcpd.leases"
    "$HOSTAPD" -B -P "$RUN/hostapd.pid" "$RUN/hostapd.conf" >> "$RUN/log" 2>&1
    sleep 2
    if ! wr_ap_up; then
        _wr_log "hostapd did not start"
        [ "$L66" = 1 ] && ( sh "${WR_WIFI_APPLY:-/mnt/v3/linux66-sd/wifi-apply}" 0 ) </dev/null >/dev/null 2>&1 &
        return 1
    fi
    ifconfig "$AP" "$AP_IP" netmask 255.255.255.0 up
    # Foreground + $!: busybox udhcpd did not write its pidfile on a TC100,
    # so stop-ap left it running.
    udhcpd -f "$RUN/udhcpd.conf" >> "$RUN/log" 2>&1 &
    echo $! > "$RUN/udhcpd.pid"
    date +%s > "$RUN/since"
    _wr_log "access point $(wr_ssid) up on channel $(sed -n 's/^channel=//p' "$RUN/hostapd.conf") (${1:-manual}), web at $WEB_URL"
}

wr_stop_ap()
{
    [ -f "$RUN/udhcpd.pid" ] && kill "$(cat "$RUN/udhcpd.pid")" 2>/dev/null
    # hostapd must exit cleanly (SIGTERM), or the driver keeps the AP half up.
    [ -f "$RUN/hostapd.pid" ] && kill "$(cat "$RUN/hostapd.pid")" 2>/dev/null
    sleep 2
    ifconfig "$AP" down 2>/dev/null
    rm -f "$RUN/hostapd.pid" "$RUN/udhcpd.pid" "$RUN/since" "$RUN/manual_until" "$RUN/hostapd.conf"
    _wr_log "access point down (${1:-manual})"
    # 3.0: wlan0 back to the station (wpa_supplicant, DHCP)
    if [ "$L66" = 1 ]; then
        ip addr flush dev "$AP" 2>/dev/null
        ( sh "${WR_WIFI_APPLY:-/mnt/v3/linux66-sd/wifi-apply}" 0 ) </dev/null >/dev/null 2>&1 &
    fi
}

# _wr_wait <seconds>: sleep without a fork (read on a private FIFO times out).
_wr_wait()
{
    if [ -p "$RUN/tick" ] && read -t "$1" _x <> "$RUN/tick" 2>/dev/null; then :; else
        [ -p "$RUN/tick" ] || sleep "$1"
    fi
}

wr_run()
{
    mkdir -p "$RUN"; chmod 700 "$RUN"
    [ -p "$RUN/tick" ] || mkfifo "$RUN/tick" 2>/dev/null
    _bad=0; _good=0
    _after=$(( $(_wr_kv WIFI_RESCUE_AFTER_MIN | awk '{ v = $1 + 0; print (v >= 2 ? v : 10) }') * 60 ))
    while :; do
        if wr_link_ok; then _good=$((_good + STEP)); _bad=0; else _bad=$((_bad + STEP)); _good=0; fi
        if wr_ap_up; then
            _now=$(date +%s); _mu=0; read -r _mu < "$RUN/manual_until" 2>/dev/null
            if [ "$L66" = 1 ]; then
                # no station while the access point has wlan0: after its window, retry the station
                [ "${_mu:-0}" -gt 0 ] || { _mu=$(( _now + $(_wr_kv WIFI_RESCUE_MANUAL_MIN | awk '{ v = $1 + 0; print (v >= 1 ? v : 15) }') * 60 )); echo "$_mu" > "$RUN/manual_until"; }
                if [ "${_now:-0}" -ge "$_mu" ] && [ "$(wr_ap_clients)" = 0 ]; then
                    wr_stop_ap "station retry"; _bad=0; _good=0
                fi
            elif [ "$_good" -ge 60 ] && [ "${_now:-0}" -ge "${_mu:-0}" ] && [ "$(wr_ap_clients)" = 0 ]; then
                wr_stop_ap "wifi back"
            fi
        elif [ "$_bad" -ge "$_after" ]; then
            wr_start_ap "no wifi for $((_bad / 60)) min" || _bad=0
        fi
        echo "ap=$(wr_ap_up && echo 1 || echo 0) link_bad_s=$_bad link_good_s=$_good" > "$RUN/state"
        _wr_wait "$STEP"
    done
}

case "${0##*/}" in
    wifi-rescue.sh)
        case "$1" in
            run) wr_run ;;
            start-ap)
                # The button only works with the feature on; "manual" (shell) always.
                if [ "${2:-manual}" != manual ] && [ "$(_wr_kv WIFI_RESCUE)" != 1 ]; then exit 3; fi
                mkdir -p "$RUN"
                echo $(( $(date +%s) + $(_wr_kv WIFI_RESCUE_MANUAL_MIN | awk '{ v = $1 + 0; print (v >= 1 ? v : 15) }') * 60 )) > "$RUN/manual_until"
                wr_start_ap "${2:-manual}" ;;
            stop-ap) wr_ap_up && wr_stop_ap "${2:-manual}" ;;
            status)
                echo "ap=$(wr_ap_up && echo 1 || echo 0)"
                echo "ssid=$(wr_ssid)"
                echo "psk=$(wr_psk)"
                echo "clients=$(wr_ap_clients)" ;;
            *) echo "usage: $0 run | start-ap [reason] | stop-ap | status" >&2; exit 2 ;;
        esac ;;
esac
