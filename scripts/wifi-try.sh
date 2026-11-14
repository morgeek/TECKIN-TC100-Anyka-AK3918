#!/bin/sh
# wifi-try.sh — test an rtl8xxxu runtime module parameter with automatic
# revert if the default gateway becomes unreachable or the change is not
# confirmed before the safety window expires. Never toggles wlan0 down/up.
#
# Usage:
#   wifi-try.sh <ampdu_rx=0|1|ampdu_tx=0|1|tx_atten=0..30> [window_s]   (default 120s, 10..600)
#   wifi-try.sh confirm                                   keep current change
#   wifi-try.sh revert                                    restore previous now
#   wifi-try.sh status                                    show trial state
#
# ampdu_tx only affects new TX BlockAck sessions, so the script asks
# wpa_supplicant for a reassociation (wpa_cli reassociate, no interface
# down/up) after applying it and after every revert.

SYS="${WT_SYS:-/sys/module/rtl8xxxu/parameters}"
STATE="${WT_STATE:-/tmp/wifi-try}"
WR_RUN="${WT_WR_RUN:-/tmp/wifi-rescue}"
POLL_S="${WT_POLL_S:-5}"

_wt_log() {
    command -v logger >/dev/null 2>&1 && logger -t wifi-try "$1"
    return 0
}

_wt_first() {
    _f1=
    [ -r "$1" ] && read -r _f1 < "$1"
    return 0
}

_wt_rescue_ap() {
    _wt_first "$WR_RUN/hostapd.pid"
    [ -n "$_f1" ] && kill -0 "$_f1" 2>/dev/null
}

_wt_active_pid() {
    _wt_first "$STATE/pid"
    [ -n "$_f1" ] && kill -0 "$_f1" 2>/dev/null
}

_wt_gateway() {
    _gw=
    if [ -n "$WT_GW" ]; then
        _gw=$WT_GW
        return 0
    fi
    if [ -n "$WT_ROUTE_FILE" ]; then
        [ -r "$WT_ROUTE_FILE" ] || return 0
        while read -r _rd _rg _; do
            [ "$_rd" = 0.0.0.0 ] && { _gw=$_rg; break; }
        done < "$WT_ROUTE_FILE"
        return 0
    fi
    [ -r /proc/net/route ] || return 0
    while read -r _ri _rd _rg _; do
        [ "$_rd" = 00000000 ] || continue
        case "$_rg" in
            [0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]) ;;
            *) continue ;;
        esac
        _o3=${_rg#??}; _o3=${_o3%????}
        _o2=${_rg#????}; _o2=${_o2%??}
        _gw="$((0x${_rg#??????})).$((0x$_o2)).$((0x$_o3)).$((0x${_rg%??????}))"
        break
    done < /proc/net/route
}

_wt_ping() {
    [ -n "$_gw" ] || return 1
    ${WT_PING:-ping} -c 1 -W 3 "$_gw" >/dev/null 2>&1
}

_wt_reassoc() {
    # $1 = parameter name; only ampdu_tx needs it (existing sessions stay)
    [ "$1" = ampdu_tx ] || return 0
    PATH="$PATH:/mnt/ext/bin" ${WT_WPA_CLI:-wpa_cli} -i "${WT_IFACE:-wlan0}" reassociate >/dev/null 2>&1
    return 0
}

_wt_clear_state() {
    rm -f "$STATE/pid" "$STATE/prev" "$STATE/key" "$STATE/target" "$STATE/confirm" 2>/dev/null
}

_wt_validate_kv() {
    case "$1" in
        *=*) ;;
        *) return 1 ;;
    esac
    _key=${1%%=*}
    _val=${1#*=}
    case "$_key" in
        ampdu_rx|ampdu_tx)
            case "$_val" in 0|1) return 0 ;; *) return 1 ;; esac
            ;;
        tx_atten)
            case "$_val" in ''|*[!0-9]*) return 1 ;; esac
            [ "$_val" -ge 0 ] && [ "$_val" -le 30 ]
            return $?
            ;;
        *) return 1 ;;
    esac
}

case "${1:-}" in
    status)
        if _wt_active_pid; then
            _pid=$_f1
            _wt_first "$STATE/key"; _k=$_f1
            _wt_first "$STATE/target"; _v=$_f1
            _wt_first "$STATE/prev"; _p=$_f1
            if [ -f "$STATE/confirm" ]; then
                echo "confirmed $_k=$_v prev=$_p pid=$_pid"
            else
                echo "pending $_k=$_v prev=$_p pid=$_pid"
            fi
        else
            echo "inactive"
        fi
        exit 0
        ;;
    confirm)
        if ! _wt_active_pid && [ ! -r "$STATE/prev" ]; then
            echo "wifi-try: no pending trial" >&2
            exit 1
        fi
        mkdir -p "$STATE" 2>/dev/null
        : > "$STATE/confirm"
        if ! _wt_active_pid; then
            _wt_clear_state
        fi
        echo "confirmed"
        exit 0
        ;;
    revert)
        if _wt_active_pid; then
            kill "$_f1" 2>/dev/null
        fi
        _wt_first "$STATE/key"; _k=$_f1
        _wt_first "$STATE/prev"; _p=$_f1
        if [ -n "$_k" ] && [ -r "$STATE/prev" ] && [ -w "$SYS/$_k" ]; then
            printf '%s\n' "$_p" > "$SYS/$_k" || {
                echo "wifi-try: failed to restore $_k" >&2
                exit 1
            }
            _wt_reassoc "$_k"
            _wt_log "manual revert $_k=$_p"
        fi
        _wt_clear_state
        echo "reverted"
        exit 0
        ;;
esac

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "usage: wifi-try.sh <ampdu_rx=0|1|ampdu_tx=0|1|tx_atten=0..30> [window_s]" >&2
    exit 2
fi

if ! _wt_validate_kv "$1"; then
    echo "wifi-try: unsupported parameter or value '$1'" >&2
    exit 2
fi

_win="${2:-120}"
case "$_win" in ''|*[!0-9]*) echo "wifi-try: invalid window '$_win'" >&2; exit 2 ;; esac
if [ "$_win" -lt 10 ] || [ "$_win" -gt 600 ]; then
    echo "wifi-try: window must be 10..600s" >&2
    exit 2
fi

case "$POLL_S" in ''|*[!0-9]*) POLL_S=5 ;; esac
_step="${WT_STEP_S:-$POLL_S}"
case "$_step" in ''|*[!0-9]*|0) _step=5 ;; esac

if _wt_rescue_ap; then
    echo "wifi-try: refused while rescue AP is active" >&2
    exit 1
fi

if _wt_active_pid; then
    echo "wifi-try: trial already running (pid $_f1)" >&2
    exit 1
fi

_sysfile="$SYS/$_key"
if [ ! -r "$_sysfile" ] || [ ! -w "$_sysfile" ]; then
    echo "wifi-try: sysfs parameter unreadable/unwritable: $_sysfile" >&2
    exit 1
fi

_wt_gateway
if ! _wt_ping; then
    echo "wifi-try: router unreachable before change (${_gw:-no gateway})" >&2
    exit 1
fi

_wt_first "$_sysfile"
_prev=$_f1

mkdir -p "$STATE" 2>/dev/null || exit 1
rm -f "$STATE/confirm" 2>/dev/null
printf '%s\n' "$_prev" > "$STATE/prev" || exit 1
printf '%s\n' "$_key" > "$STATE/key" || exit 1
printf '%s\n' "$_val" > "$STATE/target" || exit 1

if ! printf '%s\n' "$_val" > "$_sysfile"; then
    _wt_clear_state
    echo "wifi-try: failed to write $_sysfile" >&2
    exit 1
fi
_wt_reassoc "$_key"
_wt_log "trying $_key=$_val (prev=$_prev window=${_win}s gw=$_gw)"

(
    trap '' HUP
    _elapsed=0
    _misses=0
    while [ "$_elapsed" -lt "$_win" ]; do
        ${WT_SLEEP:-sleep} "$POLL_S"
        _elapsed=$((_elapsed + _step))
        if [ -f "$STATE/confirm" ]; then
            _wt_log "confirmed $_key=$_val"
            _wt_clear_state
            exit 0
        fi
        if _wt_ping; then
            _misses=0
        else
            _misses=$((_misses + 1))
            if [ "$_misses" -ge 3 ]; then
                printf '%s\n' "$_prev" > "$_sysfile" 2>/dev/null
                _wt_reassoc "$_key"
                _wt_log "reverted $_key=$_prev after 3 gateway misses"
                _wt_clear_state
                exit 0
            fi
        fi
    done
    if [ -f "$STATE/confirm" ]; then
        _wt_log "confirmed $_key=$_val"
    else
        printf '%s\n' "$_prev" > "$_sysfile" 2>/dev/null
        _wt_reassoc "$_key"
        _wt_log "reverted $_key=$_prev after ${_win}s without confirm"
    fi
    _wt_clear_state
    exit 0
) </dev/null >/dev/null 2>&1 &

echo "$!" > "$STATE/pid"
echo "applied $_key=$_val (prev=$_prev window=${_win}s)"
