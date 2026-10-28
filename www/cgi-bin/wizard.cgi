#!/bin/sh
# wizard.cgi — First-boot configuration wizard
# GET ?check  → JSON {"first_boot":true|false}
# GET ?info   → JSON {"storage","ssid","flash","card"} for the wizard page
# GET         → wizard HTML. Steps: language + Wi-Fi, profile, web access,
#               Frigate/MQTT (frigate_ha only), local recording, install to
#               flash (SD card mode only), summary
# POST        → apply choices, write boot.conf + mqtt.conf (+ Wi-Fi,
#               frigate_live.conf), mark done. Accepted only while the wizard
#               is pending (first boot or Settings → System → run the wizard).

FIRST_BOOT_FLAG="${WZ_FIRST_BOOT_FLAG:-/tmp/.first_boot}"
CONFIG="${WZ_CONFIG:-/mnt/config}"
CARD="${WZ_CARD:-/mnt}"
SCRIPTS="${WZ_SCRIPTS:-/mnt/scripts}"
STORAGE_FILE="${TC100_STORAGE_FILE:-/tmp/tc100-storage}"
# its own "done" marker: settings brought over from 2.x carry .wizard_done, the 3.0 wizard still runs once
WIZARD_DONE_FILE="$CONFIG/.wizard3_done"
BOOT_CONF="$CONFIG/boot.conf"
MQTT_CONF="$CONFIG/mqtt.conf"
MQTT_CONF_DIST="$CONFIG/mqtt.conf.dist"
# flash mode: set by v3/linux66-sd/flashmode-prep.sh
STORAGE="sd"; { [ -f "${WZ_FLASHMODE:-/tmp/flashmode}" ] || [ "$(cat "$STORAGE_FILE" 2>/dev/null)" = flash ]; } && STORAGE="flash"
# The boot reads config/wpa_supplicant.conf (flash settings or card); v3/linux66-sd/wifi-apply uses it at once.
WIFI_CONF="${WZ_WIFI_CONF:-$CONFIG/wpa_supplicant.conf}"
# the one-click install from the trial mode on the card
INSTALL66="$CARD/v3/install/install66.sh"

json_str() { printf '%s' "$1" | awk '{ gsub(/[\\"]/, ""); gsub(/[\001-\037]/, ""); printf "%s", $0 }'; }

# Rewrite KEY=value in a shell config file; appends if key absent.
set_conf() {
    _sc_file="$1" _sc_key="$2" _sc_val="$3"
    [ -f "$_sc_file" ] || return 1
    _sc_tmp="${_sc_file}.wztmp.$$"
    awk -v k="$_sc_key" -v v="$_sc_val" '
        BEGIN { FS="="; found=0 }
        $1 == k { print k "=" v; found=1; next }
        { print $0 }
        END { if (!found) print k "=" v }
    ' "$_sc_file" > "$_sc_tmp" && mv "$_sc_tmp" "$_sc_file"
}

# URL-decode a percent-encoded string (pure awk, no subprocess).
urldecode() {
    printf '%s' "$1" | awk '
    {
        n = length($0); out = ""
        for (i = 1; i <= n; i++) {
            c = substr($0, i, 1)
            if (c == "+") { out = out " "; continue }
            if (c == "%" && i+2 <= n) {
                h = substr($0, i+1, 2)
                if (h ~ /^[0-9A-Fa-f][0-9A-Fa-f]$/) {
                    d = 0
                    for (j = 1; j <= 2; j++) {
                        x = substr(h, j, 1)
                        if (x ~ /[0-9]/) v = x + 0
                        else if (x ~ /[a-f]/) v = index("abcdef", x) + 9
                        else v = index("ABCDEF", x) + 9
                        d = d * 16 + v
                    }
                    out = out sprintf("%c", d); i += 2; continue
                }
            }
            out = out c
        }
        printf "%s", out
    }'
}

# Parse one field from a URL-encoded body string.
# tr(1) is absent on this device: busybox carries the applet but ships no
# symlink for it, and /mnt/bin is not on the CGI PATH. Splitting on "&" is
# therefore done with awk's record separator instead.
get_field() {
    printf '%s' "$1" | awk -v k="$2" '
        BEGIN { RS = "&" }
        index($0, k "=") == 1 { print substr($0, length(k) + 2); exit }
    '
}

# ── router ────────────────────────────────────────────────────────────────────

METHOD="${REQUEST_METHOD:-GET}"
QUERY="${QUERY_STRING:-}"

# ?check — first-boot status probe (called by index.html on every load)
case "$QUERY" in
    *check*)
        echo "Content-Type: application/json"
        echo ""
        if [ -f "$FIRST_BOOT_FLAG" ]; then
            echo '{"first_boot":true}'
        else
            echo '{"first_boot":false}'
        fi
        exit 0
        ;;
    *info*)
        echo "Content-Type: application/json"
        echo ""
        _ssid=""
        command -v wpa_cli >/dev/null 2>&1 && _ssid="$(wpa_cli -i wlan0 status 2>/dev/null | awk '/^ssid=/ { print substr($0, 6); exit }')"
        [ -z "$_ssid" ] && command -v iw >/dev/null 2>&1 && _ssid="$(iw dev wlan0 link 2>/dev/null | awk '/^[ 	]*SSID:/ { sub(/^[ 	]*SSID: ?/, ""); print; exit }')"
        [ -z "$_ssid" ] && command -v iwconfig >/dev/null 2>&1 && _ssid="$(iwconfig wlan0 2>/dev/null | awk -F'"' '/ESSID:"/ { print $2; exit }')"
        _why=""
        if [ "$STORAGE" = flash ]; then _flash=installed
        elif [ -e /tmp/install66.running ]; then _flash=installing
        else _why="$(sh "$INSTALL66" check 2>&1)"; [ "$_why" = ok ] && { _flash=ready66; _why=""; } || _flash=blocked
        fi
        # A card the recorder can use: SD mode = the card itself; from flash,
        # a card in the slot (mounted by scripts/rec-storage.sh when needed).
        _card=0
        if [ "$STORAGE" = sd ]; then _card=1
        elif [ -b /dev/mmcblk0 ]; then _card=1; fi
        printf '{"first_boot":%s,"storage":"%s","ssid":"%s","flash":"%s","card":%s,"flash_reason":"%s"}\n' \
            "$([ -f "$FIRST_BOOT_FLAG" ] && echo true || echo false)" "$STORAGE" "$(json_str "$_ssid")" "${_flash:-none}" "$_card" \
            "$(json_str "$_why")"
        exit 0
        ;;
esac

# POST — apply wizard answers
if [ "$METHOD" = "POST" ]; then
    # Only accept POST while the wizard is actually pending (first boot, or
    # after an explicit wizard_reset). Prevents a stray/replayed POST from
    # silently re-applying settings once setup is complete.
    if [ ! -f "$FIRST_BOOT_FLAG" ]; then
        echo "Content-Type: application/json"
        echo ""
        echo '{"ok":false,"error":"wizard_already_completed"}'
        exit 0
    fi

    _cl="${CONTENT_LENGTH:-0}"
    case "$_cl" in ''|*[!0-9]*) _cl=0 ;; esac
    [ "$_cl" -gt 8192 ] && _cl=8192
    _body="$(head -c "$_cl" 2>/dev/null)"

    _profile="$(get_field "$_body" profile)"
    _mqtt_host_raw="$(get_field "$_body" mqtt_host)"
    _mqtt_port_raw="$(get_field "$_body" mqtt_port)"
    _mqtt_user_raw="$(get_field "$_body" mqtt_user)"
    _mqtt_pass_raw="$(get_field "$_body" mqtt_pass)"
    _wifi_ssid_raw="$(get_field "$_body" wifi_ssid)"
    _wifi_pass_raw="$(get_field "$_body" wifi_pass)"
    _frigate_raw="$(get_field "$_body" frigate_url)"
    _rec="$(get_field "$_body" rec)"
    _flash_inst="$(get_field "$_body" flash_install)"
    _password_raw="$(get_field "$_body" password)"

    echo "Content-Type: application/json"
    echo ""

    if [ -z "$_profile" ]; then
        echo '{"ok":false,"error":"missing_params"}'
        exit 0
    fi

    # Allowlist validation
    case "$_profile" in
        standalone|frigate_ha|nvr) ;;
        *) echo '{"ok":false,"error":"invalid_profile"}'; exit 0 ;;
    esac
    case "$_rec" in ''|keep|off|offline|always) ;; *) echo '{"ok":false,"error":"invalid_rec"}'; exit 0 ;; esac

    # Frigate address (optional): same rule as Settings → Integrations.
    _frigate="$(urldecode "$_frigate_raw" | awk 'NR == 1 { gsub(/[ \t\r]/, ""); print }')"
    _frigate="${_frigate%/}"
    if [ -n "$_frigate" ]; then
        case "$_frigate" in http://*|https://*) ;; *) _frigate="http://$_frigate" ;; esac
        case "${_frigate#*://}" in
            ''|*[!A-Za-z0-9.:/_-]*) echo '{"ok":false,"error":"invalid_frigate_url"}'; exit 0 ;;
        esac
    fi

    # Wi-Fi (optional): checked before anything is written. Applied through
    # scripts/wifi-txt.sh like a wifi.txt on the card: the current networks
    # stay in the file as a fallback, so a typo cannot take the camera off
    # the network it is on. Used from the next restart.
    _wifi_ssid="$(urldecode "$_wifi_ssid_raw" | awk 'NR == 1 { sub(/\r$/, ""); print }')"
    _wifi_pass="$(urldecode "$_wifi_pass_raw" | awk 'NR == 1 { sub(/\r$/, ""); print }')"
    _wifi=unchanged
    if [ -n "$_wifi_ssid" ]; then
        _wl=${#_wifi_ssid}; _pl=${#_wifi_pass}
        if [ "$_wl" -gt 32 ] || { [ "$_pl" -gt 0 ] && { [ "$_pl" -lt 8 ] || [ "$_pl" -gt 63 ]; }; }; then
            echo '{"ok":false,"error":"invalid_wifi"}'; exit 0
        fi
        case "$_wifi_ssid$_wifi_pass" in *\"*|*\\*) echo '{"ok":false,"error":"invalid_wifi"}'; exit 0 ;; esac
    fi

    # New camera password (3.0 wizard, optional): same rules as Settings → System → Password.
    _password="$(urldecode "$_password_raw" | awk 'NR == 1 { sub(/\r$/, ""); print }')"
    if [ -n "$_password" ]; then
        case "$_password" in
            *[\"\'\$\`\\\ %]*|*"$(printf '\t')"*) echo '{"ok":false,"error":"invalid_password"}'; exit 0 ;;
        esac
        [ ${#_password} -lt 4 ] && { echo '{"ok":false,"error":"invalid_password"}'; exit 0; }
    fi

    # Decode and sanitize MQTT fields (awk, not tr -cd — see get_field above)
    _mqtt_host="$(urldecode "$_mqtt_host_raw" | awk '{ gsub(/[^a-zA-Z0-9.:_-]/, ""); print }')"
    _mqtt_port="$(urldecode "$_mqtt_port_raw" | awk '{ gsub(/[^0-9]/, ""); print }')"
    _mqtt_user="$(urldecode "$_mqtt_user_raw" | awk '{ gsub(/[^a-zA-Z0-9._@!#%^*()=+-]/, ""); print }')"
    _mqtt_pass="$(urldecode "$_mqtt_pass_raw" | awk '{ gsub(/[^a-zA-Z0-9._@!#%^*()=+-]/, ""); print }')"

    case "$_mqtt_port" in
        ''|*[!0-9]*) _mqtt_port=1883 ;;
    esac
    [ "$_mqtt_port" -lt 1 ]     && _mqtt_port=1
    [ "$_mqtt_port" -gt 65535 ] && _mqtt_port=65535

    # Apply profile
    case "$_profile" in
        frigate_ha)
            set_conf "$BOOT_CONF" INTEGRATION_PROFILE frigate_ha
            set_conf "$BOOT_CONF" MQTT_ENABLE 1
            ;;
        *)
            set_conf "$BOOT_CONF" INTEGRATION_PROFILE default
            set_conf "$BOOT_CONF" MQTT_ENABLE 0
            ;;
    esac

    # Web access: plain HTTP with a login (all busybox httpd offers)
    set_conf "$BOOT_CONF" WEB_MODE http
    set_conf "$BOOT_CONF" SECURITY_HARDENING_MODE 0

    # Apply MQTT broker settings (frigate_ha only)
    if [ "$_profile" = "frigate_ha" ] && [ -n "$_mqtt_host" ]; then
        if [ ! -f "$MQTT_CONF" ] && [ -f "$MQTT_CONF_DIST" ]; then
            cp "$MQTT_CONF_DIST" "$MQTT_CONF" 2>/dev/null || true
        fi
        if [ -f "$MQTT_CONF" ]; then
            set_conf "$MQTT_CONF" MQTT_ENABLE 1
            set_conf "$MQTT_CONF" MQTT_HOST "$_mqtt_host"
            set_conf "$MQTT_CONF" MQTT_PORT "$_mqtt_port"
            set_conf "$MQTT_CONF" MQTT_USER "$_mqtt_user"
            set_conf "$MQTT_CONF" MQTT_PASSWORD "$_mqtt_pass"
        fi
    fi

    # Frigate address: smooth live link + who the backup recording watches.
    if [ -n "$_frigate" ]; then
        # Keep the Frigate camera name already found for the same address.
        _fcam=""
        [ "$(awk -F= '$1 == "FRIGATE_URL" { print substr($0, 13) }' "$CONFIG/frigate_live.conf" 2>/dev/null)" = "$_frigate" ] &&
            _fcam="$(awk -F= '$1 == "FRIGATE_CAMERA" { print $2 }' "$CONFIG/frigate_live.conf" 2>/dev/null)"
        printf 'FRIGATE_URL=%s\nFRIGATE_CAMERA=%s\n' "$_frigate" "$_fcam" > "$CONFIG/frigate_live.conf.tmp" &&
            mv -f "$CONFIG/frigate_live.conf.tmp" "$CONFIG/frigate_live.conf"
    fi

    # Local backup recording on the SD card (src/tc100fix/rec.c).
    case "$_rec" in
        off) set_conf "$BOOT_CONF" REC_LOCAL 0 ;;
        offline|always) set_conf "$BOOT_CONF" REC_LOCAL 1; set_conf "$BOOT_CONF" REC_WHEN "$_rec" ;;
    esac

    if [ -n "$_wifi_ssid" ]; then
        _wd="/tmp/wizard-wifi.$$"; mkdir -p "$_wd"
        { printf 'SSID=%s\n' "$_wifi_ssid"; [ -n "$_wifi_pass" ] && printf 'PASSWORD=%s\n' "$_wifi_pass"; } > "$_wd/wifi.txt"
        [ ! -f "$WIFI_CONF" ] && [ -f /etc/wpa_supplicant.conf ] && cp /etc/wpa_supplicant.conf "$WIFI_CONF"
        if sh "$SCRIPTS/wifi-txt.sh" apply "$_wd/wifi.txt" "$WIFI_CONF" /etc/jffs2/anyka_cfg.ini >/dev/null 2>&1; then
            _wifi=applied
            [ -f "$CARD/v3/linux66-sd/wifi-apply" ] && ( sh "$CARD/v3/linux66-sd/wifi-apply" 5 </dev/null >/dev/null 2>&1 & )
        else
            _wifi=failed
        fi
        rm -rf "$_wd"
    fi

    _flash=no
    # One click: install to flash from the trial mode once the settings above are written
    # (install66.sh copies them from the card into the flash settings slots at its end).
    if [ "$_flash_inst" = 1 ] && [ "$STORAGE" = sd ] && [ ! -e /tmp/install66.running ] &&
       [ "$(sh "$INSTALL66" check 2>&1)" = ok ]; then
        : > /tmp/install66.running
        ( trap '' HUP; sleep 8; sh "$INSTALL66" run; rm -f /tmp/install66.running ) </dev/null >/dev/null 2>&1 &
        _flash=installing
    fi

    # New password last: the browser has to sign in again afterwards.
    _pw=unchanged
    if [ -n "$_password" ]; then
        if sh -c '. /mnt/scripts/common_functions.sh && all_password "$1"' _ "$_password" >/dev/null 2>&1; then
            _pw=changed
            ( sleep 3; sh /mnt/controlscripts/rtsp-h26x restart ) </dev/null >/dev/null 2>&1 &
        else
            _pw=failed
        fi
    fi

    touch "$WIZARD_DONE_FILE" 2>/dev/null || true
    rm -f "$FIRST_BOOT_FLAG" 2>/dev/null || true

    printf '{"ok":true,"wifi":"%s","flash":"%s","password":"%s"}\n' "$_wifi" "$_flash" "$_pw"
    exit 0
fi

# GET — serve wizard HTML
echo "Content-Type: text/html; charset=utf-8"
echo ""
cat << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TC100 — Initial setup</title>
<link rel="stylesheet" href="/css/bulma.1.0.2.purged.min.css?v=1.8.4">
<script src="/scripts/i18n.js?v=2.1.2-i18n1"></script>
<style>
*, *::before, *::after { box-sizing: border-box; }

body {
    background: #0d0f1a;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 1.25rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #e2e8f0;
}

.wz-shell {
    background: #131624;
    border: 1px solid #1e2235;
    border-radius: 20px;
    padding: 2.25rem 2rem 2rem;
    width: 100%;
    max-width: 660px;
    box-shadow: 0 32px 80px rgba(0,0,0,0.6);
}

.wz-header {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    margin-bottom: 2rem;
}
.wz-logo-ring {
    width: 34px; height: 34px;
    background: linear-gradient(135deg, #6d58f5 0%, #9b6dff 100%);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.wz-title    { font-size: 1rem; font-weight: 700; letter-spacing: .06em; color: #e2e8f0; }
.wz-subtitle { margin-left: auto; font-size: 0.72rem; color: #4b5563; letter-spacing: .04em; text-transform: uppercase; }

/* ── Step bar ────────────────────────────────────── */
.wz-steps { display: flex; align-items: center; margin-bottom: 2rem; min-height: 30px; }
.wz-dot {
    width: 30px; height: 30px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.72rem; font-weight: 700;
    flex-shrink: 0;
    transition: background .25s, color .25s;
}
.wz-dot.active  { background: #6d58f5; color: #fff; }
.wz-dot.done    { background: #16a34a; color: #fff; }
.wz-dot.pending { background: #1e2235; color: #4b5563; }
.wz-line { flex: 1; height: 2px; background: #1e2235; transition: background .35s; }
.wz-line.done { background: #16a34a; }

/* ── Step panels ─────────────────────────────────── */
.wz-panel { display: none; }
.wz-panel.active { display: block; }

.wz-step-title  { font-size: 1.2rem; font-weight: 700; color: #f1f5f9; margin-bottom: .3rem; }
.wz-step-hint   { font-size: 0.82rem; color: #6b7280; margin-bottom: 1.4rem; }

/* ── Choice cards ────────────────────────────────── */
.wz-card {
    display: flex; align-items: center; gap: 1rem;
    padding: 1rem 1.125rem;
    background: #191c2e;
    border: 2px solid #1e2235;
    border-radius: 12px;
    cursor: pointer;
    margin-bottom: 0.625rem;
    transition: border-color .18s, background .18s, box-shadow .18s;
    user-select: none;
}
.wz-card:hover   { border-color: #4b3fd4; background: #1c1f35; }
.wz-card.selected {
    border-color: #6d58f5; background: #1a1730;
    box-shadow: 0 0 0 1px #6d58f5, 0 4px 24px rgba(109,88,245,.18);
}
.wz-icon {
    width: 42px; height: 42px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.wz-card-body  { flex: 1; min-width: 0; }
.wz-card-title { font-size: .92rem; font-weight: 600; color: #e2e8f0; margin-bottom: .15rem; display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.wz-card-desc  { font-size: .78rem; color: #6b7280; line-height: 1.4; }
.wz-check {
    width: 20px; height: 20px; border-radius: 50%;
    border: 2px solid #2d3456;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    transition: background .18s, border-color .18s;
}
.wz-card.selected .wz-check { background: #6d58f5; border-color: #6d58f5; }

/* ── Badges ──────────────────────────────────────── */
.badge {
    display: inline-block; padding: .15rem .5rem;
    border-radius: 5px; font-size: .68rem; font-weight: 700; line-height: 1.5;
}
.badge-green  { background: rgba(22,163,74,.18);  color: #4ade80; }
.badge-purple { background: rgba(109,88,245,.18); color: #a78bfa; }
.badge-amber  { background: rgba(217,119,6,.18);  color: #fbbf24; }
.badge-slate  { background: rgba(71,85,105,.2);   color: #94a3b8; }

/* ── MQTT form ───────────────────────────────────── */
.wz-field { margin-bottom: 1rem; }
.wz-label {
    display: block;
    font-size: 0.78rem; font-weight: 500;
    color: #94a3b8; margin-bottom: 0.35rem;
    letter-spacing: .03em;
}
.wz-label .opt { color: #4b5563; font-weight: 400; }
.wz-input {
    width: 100%;
    background: #0d0f1a;
    border: 1px solid #2d3456;
    border-radius: 8px;
    padding: .6rem .875rem;
    font-size: .875rem;
    color: #e2e8f0;
    outline: none;
    transition: border-color .15s, box-shadow .15s;
}
.wz-input:focus  { border-color: #6d58f5; box-shadow: 0 0 0 3px rgba(109,88,245,.15); }
.wz-input::placeholder { color: #4b5563; }
.wz-row-2 { display: grid; grid-template-columns: 1fr 110px; gap: .75rem; }
.wz-row-eq { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
.wz-note {
    font-size: .75rem; color: #4b5563;
    background: #0d0f1a; border: 1px solid #1e2235;
    border-radius: 8px; padding: .625rem .875rem;
    margin-top: 1.25rem; line-height: 1.5;
}

/* ── Nav ─────────────────────────────────────────── */
.wz-nav {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 1.625rem;
}
.btn-primary {
    background: #6d58f5; color: #fff; border: none;
    border-radius: 8px; padding: .6rem 1.375rem;
    font-size: .875rem; font-weight: 600;
    cursor: pointer; display: inline-flex; align-items: center; gap: .45rem;
    transition: background .15s, opacity .15s;
}
.btn-primary:hover:not(:disabled) { background: #5b47e0; }
.btn-primary:disabled { opacity: .4; cursor: not-allowed; }
.btn-ghost {
    background: transparent; color: #6b7280; border: none;
    font-size: .82rem; cursor: pointer; padding: .5rem .25rem;
    transition: color .15s;
}
.btn-ghost:hover { color: #e2e8f0; }

/* ── Summary ─────────────────────────────────────── */
.wz-summary {
    background: #0d0f1a; border: 1px solid #1e2235;
    border-radius: 10px; overflow: hidden; margin-bottom: 1.5rem;
}
.wz-summary-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: .75rem 1rem; font-size: .83rem;
    border-bottom: 1px solid #1a1d2e;
}
.wz-summary-row:last-child { border-bottom: none; }
.wz-summary-key { color: #6b7280; }

/* ── Success ─────────────────────────────────────── */
.wz-success { display: none; text-align: center; padding: 1.5rem 0 1rem; }
.wz-success-ring {
    width: 68px; height: 68px; border-radius: 50%;
    background: rgba(22,163,74,.12); border: 2px solid rgba(22,163,74,.25);
    display: flex; align-items: center; justify-content: center;
    margin: 0 auto 1.25rem;
}
.wz-success-title { font-size: 1.05rem; font-weight: 700; color: #f1f5f9; margin-bottom: .35rem; }
.wz-success-sub   { font-size: .83rem; color: #6b7280; }

.wz-lang { display: flex; gap: .5rem; margin-bottom: 1.1rem; }
.wz-lang-btn {
    background: #191c2e; color: #94a3b8; border: 1px solid #2d3456; border-radius: 8px;
    padding: .4rem .9rem; font-size: .82rem; cursor: pointer;
}
.wz-lang-btn.is-on { border-color: #6d58f5; color: #e2e8f0; background: #1a1730; }
.wz-field-err { color: #f87171; font-size: .78rem; min-height: 1em; }
.wz-success-sub + .wz-success-sub { margin-top: .5rem; }

@keyframes wz-spin { to { transform: rotate(360deg); } }
.wz-spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,.3); border-top-color: #fff;
    border-radius: 50%; animation: wz-spin .65s linear infinite;
    display: inline-block;
}
</style>
</head>

<body>
<div class="wz-shell">

  <!-- Header -->
  <div class="wz-header">
    <div class="wz-logo-ring">
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
        <circle cx="10" cy="10" r="9" stroke="rgba(255,255,255,.25)" stroke-width="1.5"/>
        <circle cx="10" cy="10" r="4.5" fill="white" opacity=".9"/>
        <circle cx="10" cy="10" r="2" fill="#6d58f5"/>
      </svg>
    </div>
    <span class="wz-title">TC100 ELITE</span>
    <span class="wz-subtitle">Initial setup</span>
  </div>

  <!-- Step bar (rendered by JS) -->
  <div class="wz-steps" id="wzStepBar"></div>

  <!-- ── Language + Wi-Fi ───────────────────────── -->
  <div class="wz-panel active" id="wp-start">
    <div class="wz-step-title">Language and Wi-Fi</div>
    <div class="wz-step-hint">Everything chosen here can be changed later in Settings.</div>
    <div class="wz-lang" translate="no">
      <button type="button" class="wz-lang-btn" data-lang="en" onclick="setLang('en')">English</button>
      <button type="button" class="wz-lang-btn" data-lang="fr" onclick="setLang('fr')">Français</button>
    </div>
    <div class="wz-card" data-val="keep" data-group="wifi" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(109,88,245,.12)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M2 9a15 15 0 0 1 20 0"/><circle cx="12" cy="19.5" r="1" fill="#a78bfa" stroke="none"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Keep the current Wi-Fi network</div>
        <div class="wz-card-desc"><span id="wzSsidNow">…</span></div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-card" data-val="change" data-group="wifi" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(109,88,245,.12)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Use another Wi-Fi network</div>
        <div class="wz-card-desc">Used from the next restart. The current network is kept as a fallback, so a typo does not take the camera offline.</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div id="wzWifiForm" style="display:none">
      <div class="wz-row-eq">
        <div class="wz-field">
          <label class="wz-label" for="wzWifiSsid">Network name (SSID)</label>
          <input class="wz-input" id="wzWifiSsid" type="text" maxlength="32" autocomplete="off" spellcheck="false" oninput="checkStart()">
        </div>
        <div class="wz-field">
          <label class="wz-label" for="wzWifiPass">Password</label>
          <input class="wz-input" id="wzWifiPass" type="password" maxlength="63" autocomplete="new-password" oninput="checkStart()">
        </div>
      </div>
      <div class="wz-field-err" id="wzWifiErr"></div>
    </div>
    <div class="wz-nav">
      <span></span>
      <button class="btn-primary" id="wbtn-start" disabled onclick="goNext()">Next <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><line x1="3" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><polyline points="8,4 11,7 8,10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
  </div>

  <!-- ── Profile ────────────────────────────────── -->
  <div class="wz-panel" id="wp-profile">
    <div class="wz-step-title">Integration profile</div>
    <div class="wz-step-hint">How will this camera be used?</div>
    <div class="wz-card" data-val="standalone" data-group="profile" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(109,88,245,.12)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Standalone</div>
        <div class="wz-card-desc">Independent local camera — full dashboard and all features</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-card" data-val="frigate_ha" data-group="profile" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(22,163,74,.12)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/><polyline points="7.5,10 10.5,13 16.5,7" stroke-width="2.2"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Frigate + Home Assistant <span class="badge badge-green">Recommended</span></div>
        <div class="wz-card-desc">Delegates detection, recording and alerts to Frigate — minimal footprint</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-card" data-val="nvr" data-group="profile" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(217,119,6,.12)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="12" rx="2" ry="2"/><path d="M15 9.5l5 2.5-5 2.5V9.5z"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Third-party NVR</div>
        <div class="wz-card-desc">Blue Iris, Synology Surveillance, iSpy — direct RTSP streams without MQTT</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-nav">
      <button class="btn-ghost" onclick="goBack()">← Back</button>
      <button class="btn-primary" id="wbtn-profile" disabled onclick="goNext()">Next <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><line x1="3" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><polyline points="8,4 11,7 8,10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
  </div>

  <!-- ── Web access ─────────────────────────────── -->
  <div class="wz-panel" id="wp-security">
    <div class="wz-step-title">Camera password</div>
    <div class="wz-step-hint">One password for the user root: web interface, RTSP, FTP and telnet. The default one (pass) is known to everybody: choose your own. Leave empty to keep the current one.</div>
    <div class="wz-field">
      <label class="wz-label" for="wzPw1">New password for root</label>
      <input class="wz-input" id="wzPw1" type="password" maxlength="64" autocomplete="new-password" oninput="checkPw()">
    </div>
    <div class="wz-field">
      <label class="wz-label" for="wzPw2">Same password again</label>
      <input class="wz-input" id="wzPw2" type="password" maxlength="64" autocomplete="new-password" oninput="checkPw()">
    </div>
    <div class="wz-step-hint" id="wzPwErr" style="color:#f87171"></div>
    <div class="wz-nav">
      <button class="btn-ghost" onclick="goBack()">← Back</button>
      <button class="btn-primary" id="wbtn-security" onclick="goNext()">Next <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><line x1="3" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><polyline points="8,4 11,7 8,10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
  </div>

  <!-- ── Frigate + MQTT (frigate_ha only) ───────── -->
  <div class="wz-panel" id="wp-mqtt">
    <div class="wz-step-title">Frigate and Home Assistant</div>
    <div class="wz-step-hint">Connection to the Home Assistant broker (Mosquitto or another broker)</div>
    <div class="wz-row-2">
      <div class="wz-field">
        <label class="wz-label" for="wzMqttHost">Broker host</label>
        <input class="wz-input" id="wzMqttHost" type="text" placeholder="192.168.1.10" autocomplete="off" spellcheck="false" oninput="mqttHostChanged()">
      </div>
      <div class="wz-field">
        <label class="wz-label" for="wzMqttPort">Port</label>
        <input class="wz-input" id="wzMqttPort" type="text" value="1883" placeholder="1883" autocomplete="off">
      </div>
    </div>
    <div class="wz-row-eq">
      <div class="wz-field">
        <label class="wz-label" for="wzMqttUser">Username <span class="opt">(optional)</span></label>
        <input class="wz-input" id="wzMqttUser" type="text" placeholder="homeassistant" autocomplete="off">
      </div>
      <div class="wz-field">
        <label class="wz-label" for="wzMqttPass">Password <span class="opt">(optional)</span></label>
        <input class="wz-input" id="wzMqttPass" type="password" placeholder="••••••••" autocomplete="new-password">
      </div>
    </div>
    <div class="wz-field">
      <label class="wz-label" for="wzFrigateUrl">Frigate address <span class="opt">(optional)</span></label>
      <input class="wz-input" id="wzFrigateUrl" type="text" placeholder="http://192.168.1.20:5000" autocomplete="off" spellcheck="false">
    </div>
    <div class="wz-note">
      Home Assistant finds the camera by itself (MQTT discovery). The Frigate address adds a link to Frigate's smooth live view and tells the backup recording which machine to watch. A Frigate configuration ready to paste is in Tools → Diagnostics.
    </div>
    <div class="wz-nav">
      <button class="btn-ghost" onclick="goBack()">← Back</button>
      <button class="btn-primary" id="wbtn-mqtt" disabled onclick="goNext()">Next <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><line x1="3" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><polyline points="8,4 11,7 8,10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
  </div>

  <!-- ── Local recording ────────────────────────── -->
  <div class="wz-panel" id="wp-rec">
    <div class="wz-step-title">Recording on the SD card</div>
    <div class="wz-step-hint">The camera can keep its own copy of the video, in MP4 files of 5 minutes (no re-encoding, about 4 % CPU while recording).</div>
    <div class="wz-card" data-val="offline" data-group="rec" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(22,163,74,.12)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4" fill="#4ade80" stroke="none"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">When Frigate stops receiving the video <span class="badge badge-green">Recommended</span></div>
        <div class="wz-card-desc">Records only while the network or Frigate is down, plus a few seconds before and after: no gap in the recordings</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-card" data-val="always" data-group="rec" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(217,119,6,.12)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="12" cy="12" r="3" fill="#fbbf24" stroke="none"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Always</div>
        <div class="wz-card-desc">Continuous recording; the oldest files are deleted when the card is full</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-card" data-val="off" data-group="rec" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(71,85,105,.2)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="5.6" y1="5.6" x2="18.4" y2="18.4"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Off</div>
        <div class="wz-card-desc">Nothing is written to the card</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-note" id="wzRecNote" style="display:none">No SD card in the camera: recording starts once a card is inserted (FAT32 or exFAT).</div>
    <div class="wz-nav">
      <button class="btn-ghost" onclick="goBack()">← Back</button>
      <button class="btn-primary" id="wbtn-rec" disabled onclick="goNext()">Next <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><line x1="3" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><polyline points="8,4 11,7 8,10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
  </div>

  <!-- ── Install to flash (SD card mode only) ───── -->
  <div class="wz-panel" id="wp-flash">
    <div class="wz-step-title">Run without the SD card</div>
    <div class="wz-step-hint">This camera can now run the firmware from its own memory. The whole original flash is already saved on the card (tc100-3/backup).</div>
    <div class="wz-card" data-val="prepare" data-group="flash" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(22,163,74,.12)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Install into the camera now</div>
        <div class="wz-card-desc">One click: after the settings are applied, the camera writes the firmware into its memory (about 10 minutes, every part saved on the card first and read back), then restarts from it. The card then only holds recordings.</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-card" data-val="later" data-group="flash" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(71,85,105,.2)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M9 6v3M12 6v3M15 7v2"/></svg></div>
      <div class="wz-card-body">
        <div class="wz-card-title">Not now</div>
        <div class="wz-card-desc">Keep running from the SD card. This can be done any time from Settings → Update & backup.</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>
    <div class="wz-nav">
      <button class="btn-ghost" onclick="goBack()">← Back</button>
      <button class="btn-primary" id="wbtn-flash" disabled onclick="goNext()">Next <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><line x1="3" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><polyline points="8,4 11,7 8,10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
  </div>

  <!-- ── Summary ────────────────────────────────── -->
  <div class="wz-panel" id="wp-summary">
    <div class="wz-step-title">Summary</div>
    <div class="wz-step-hint">Review before applying. Everything can be changed later from the dashboard.</div>
    <div class="wz-summary" id="wzSummary"></div>
    <div class="wz-field-err" id="wzApplyErr"></div>
    <div class="wz-nav">
      <button class="btn-ghost" onclick="goBack()">← Back</button>
      <button class="btn-primary" id="wbtnApply" onclick="applyConfig()">Apply and start <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><line x1="3" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><polyline points="8,4 11,7 8,10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
  </div>

  <!-- ── Success ───────────────────────────────── -->
  <div class="wz-success" id="wzSuccess">
    <div class="wz-success-ring">
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
        <polyline points="5,14 11,20 23,8" stroke="#4ade80" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <div class="wz-success-title">Configuration applied</div>
    <div class="wz-success-sub" id="wzSuccessNote"></div>
    <div class="wz-success-sub">Redirecting in <span id="wzCountdown">5</span> s…</div>
  </div>

</div>

<script>
var wz = { wifi: null, profile: null, rec: null, flash: null };
var info = { storage: 'sd', ssid: '', flash: 'none', card: 1, flash_reason: '' };

var LABEL = {
    profile:  { standalone: 'Standalone', frigate_ha: 'Frigate + Home Assistant', nvr: 'Third-party NVR' },
    rec:      { offline: 'When Frigate stops receiving the video', always: 'Always', off: 'Off' },
    flash:    { prepare: 'Install now', later: 'Not now' }
};
var CHECK_SVG = '<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
var ARROW_SVG = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><line x1="3" y1="7" x2="11" y2="7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><polyline points="8,4 11,7 8,10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
var current = 'start';

function byId(id) { return document.getElementById(id); }
function flashStep() { return info.storage === 'sd' && info.flash === 'ready66'; }
// the access step sets the camera password (busybox httpd has no HTTPS); empty = keep the current one
function pwError() {
    var a = byId('wzPw1').value, b = byId('wzPw2').value;
    if (!a && !b) return '';
    if (/["'\\$`%\s]/.test(a)) return 'No spaces, quotes, %, $, ` or \\ in the password.';
    if (a.length < 4) return 'At least 4 characters.';
    if (a !== b) return 'The two passwords differ.';
    return '';
}
function checkPw() {
    var e = pwError();
    byId('wzPwErr').textContent = e;
    byId('wbtn-security').disabled = e !== '';
}
function panels() {
    var p = ['start', 'profile', 'security'];
    if (wz.profile === 'frigate_ha') p.push('mqtt');
    p.push('rec');
    if (flashStep()) p.push('flash');
    p.push('summary');
    return p;
}

function renderStepBar() {
    var p = panels(), at = p.indexOf(current), html = '', i, state;
    for (i = 0; i < p.length; i++) {
        state = i < at ? 'done' : (i === at ? 'active' : 'pending');
        html += '<div class="wz-dot ' + state + '">' + (state === 'done' ? CHECK_SVG : (i + 1)) + '</div>';
        if (i < p.length - 1) html += '<div class="wz-line' + (i < at ? ' done' : '') + '"></div>';
    }
    byId('wzStepBar').innerHTML = html;
}

function show(id) {
    var all = document.querySelectorAll('.wz-panel'), i;
    for (i = 0; i < all.length; i++) all[i].classList.remove('active');
    byId('wp-' + id).classList.add('active');
    current = id;
    renderStepBar();
    if (id === 'summary') renderSummary();
    window.scrollTo(0, 0);
}
function goNext() { var p = panels(); show(p[p.indexOf(current) + 1]); }
function goBack() { var p = panels(); show(p[Math.max(0, p.indexOf(current) - 1)]); }

function pick(el) {
    var group = el.getAttribute('data-group'), val = el.getAttribute('data-val');
    var cards = document.querySelectorAll('.wz-card[data-group="' + group + '"]'), i;
    for (i = 0; i < cards.length; i++) cards[i].classList.remove('selected');
    el.classList.add('selected');
    wz[group] = val;
    if (group === 'wifi') { byId('wzWifiForm').style.display = val === 'change' ? '' : 'none'; checkStart(); return; }
    var btn = byId('wbtn-' + group);
    if (btn) btn.disabled = false;
    if (group === 'profile') {
        // Recording when Frigate is down only makes sense with Frigate.
        if (!wz.rec) preselect('rec', val === 'frigate_ha' ? 'offline' : 'off');
        renderStepBar();
    }
}
function preselect(group, val) {
    var el = document.querySelector('.wz-card[data-group="' + group + '"][data-val="' + val + '"]');
    if (el) pick(el);
}

function wifiError() {
    if (wz.wifi !== 'change') return '';
    var s = byId('wzWifiSsid').value, p = byId('wzWifiPass').value;
    if (!s) return ' ';
    if (s.length > 32) return 'The network name is at most 32 characters.';
    if (p && (p.length < 8 || p.length > 63)) return 'The password must be 8 to 63 characters (empty for an open network).';
    if (/["\\]/.test(s + p)) return 'The network name and password cannot contain " or \\.';
    return '';
}
function checkStart() {
    var e = wifiError();
    byId('wzWifiErr').textContent = e.trim();
    byId('wbtn-start').disabled = !wz.wifi || e !== '';
}

function mqttHostChanged() {
    byId('wbtn-mqtt').disabled = byId('wzMqttHost').value.trim() === '';
}

function setLang(l) {
    try { window.localStorage.setItem('tc100_lang', l); } catch (e) { /* storage blocked */ }
    if ((document.documentElement.lang || 'en') !== l) location.reload();
}

function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function badge(cls, text) { return '<span class="badge ' + cls + '">' + text + '</span>'; }

function renderSummary() {
    var rows = [], host = byId('wzMqttHost').value.trim(), port = byId('wzMqttPort').value.trim() || '1883';
    var fr = byId('wzFrigateUrl').value.trim();
    rows.push(['Wi-Fi', wz.wifi === 'change' ? badge('badge-amber', esc(byId('wzWifiSsid').value) + ' (next restart)') : badge('badge-slate', esc(info.ssid || 'Unchanged'))]);
    rows.push(['Profile', badge('badge-purple', LABEL.profile[wz.profile])]);
    rows.push(['Password', byId('wzPw1').value ? badge('badge-green', 'New password') : badge('badge-amber', 'Unchanged')]);
    if (wz.profile === 'frigate_ha') {
        rows.push(['Broker MQTT', badge('badge-green', esc(host) + ' : ' + esc(port))]);
        if (fr) rows.push(['Frigate', badge('badge-green', esc(fr))]);
    } else {
        rows.push(['MQTT', badge('badge-slate', 'Disabled')]);
    }
    rows.push(['Recording', badge(wz.rec === 'off' ? 'badge-slate' : 'badge-green', LABEL.rec[wz.rec])]);
    if (flashStep()) rows.push(['Install to flash', badge(wz.flash === 'prepare' ? 'badge-green' : 'badge-slate', LABEL.flash[wz.flash])]);
    if (info.storage === 'flash') rows.push(['Firmware', badge('badge-green', 'Running from flash')]);
    var html = '', r;
    for (r = 0; r < rows.length; r++) {
        html += '<div class="wz-summary-row"><span class="wz-summary-key">' + rows[r][0] + '</span><span>' + rows[r][1] + '</span></div>';
    }
    byId('wzSummary').innerHTML = html;
}

var ERRORS = {
    invalid_wifi: 'The Wi-Fi network name or password is not valid.',
    invalid_frigate_url: 'The Frigate address must look like http://192.168.1.20:5000.',
    invalid_password: 'The new password is not valid (at least 4 characters, no spaces, quotes, %, $, ` or \\).',
    wizard_already_completed: 'The setup was already completed (reload the page).'
};

function applyConfig() {
    var btn = byId('wbtnApply');
    btn.disabled = true;
    btn.innerHTML = '<span class="wz-spinner"></span> Applying…';
    byId('wzApplyErr').textContent = '';
    var f = function(k, v) { return '&' + k + '=' + encodeURIComponent(v); };
    var body = 'profile=' + encodeURIComponent(wz.profile) + f('rec', wz.rec || 'keep');
    if (wz.wifi === 'change') body += f('wifi_ssid', byId('wzWifiSsid').value) + f('wifi_pass', byId('wzWifiPass').value);
    if (wz.profile === 'frigate_ha') {
        body += f('mqtt_host', byId('wzMqttHost').value.trim()) + f('mqtt_port', byId('wzMqttPort').value.trim() || '1883') +
                f('mqtt_user', byId('wzMqttUser').value.trim()) + f('mqtt_pass', byId('wzMqttPass').value) +
                f('frigate_url', byId('wzFrigateUrl').value.trim());
    }
    if (flashStep() && wz.flash === 'prepare') body += f('flash_install', '1');
    if (byId('wzPw1').value) body += f('password', byId('wzPw1').value);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/cgi-bin/wizard.cgi', true);
    xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) return;
        var d = null;
        if (xhr.status === 200) { try { d = JSON.parse(xhr.responseText); } catch (e) {} }
        if (d && d.ok) { showSuccess(d); return; }
        btn.disabled = false;
        btn.innerHTML = 'Retry ' + ARROW_SVG;
        byId('wzApplyErr').textContent = (d && ERRORS[d.error]) || 'The camera did not accept the settings.';
    };
    xhr.send(body);
}

function showSuccess(d) {
    var all = document.querySelectorAll('.wz-panel'), i;
    for (i = 0; i < all.length; i++) all[i].classList.remove('active');
    byId('wzStepBar').style.display = 'none';
    byId('wzSuccess').style.display = 'block';
    var notes = [];
    if (d.wifi === 'applied') notes.push('The new Wi-Fi network is used from the next restart.');
    if (d.wifi === 'failed') notes.push('The Wi-Fi settings could not be saved; the camera stays on its current network.');
    if (d.flash === 'installing') notes.push('The firmware is being written into the camera\'s memory (about 10 minutes, do not unplug it); the camera then restarts from it and the card is only used for recordings. Progress: Settings → Update & backup.');
    if (d.password === 'changed') notes.push('The password is changed: sign in again as root with the new one (also in the RTSP addresses of Frigate or your NVR).');
    if (d.password === 'failed') notes.push('The password could not be changed: Settings → System → Password.');
    byId('wzSuccessNote').textContent = notes.join(' ');
    var n = notes.length ? 8 : 5, el = byId('wzCountdown');
    el.textContent = n;
    var timer = setInterval(function() {
        n -= 1; el.textContent = n;
        if (n <= 0) { clearInterval(timer); window.location.replace('/'); }
    }, 1000);
}

(function init() {
    var l = document.documentElement.lang || 'en', b = document.querySelectorAll('.wz-lang-btn'), i;
    for (i = 0; i < b.length; i++) if (b[i].getAttribute('data-lang') === l) b[i].classList.add('is-on');
    preselect('flash', 'later');
    renderStepBar();
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/cgi-bin/wizard.cgi?info', true);
    xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) return;
        try { var d = JSON.parse(xhr.responseText); if (d) info = d; } catch (e) {}
        byId('wzSsidNow').textContent = info.ssid ? 'Connected to ' + info.ssid : 'Settings stored in the camera';
        byId('wzRecNote').style.display = info.card ? 'none' : '';
        preselect('wifi', 'keep');
        renderStepBar();
    };
    xhr.send();
})();
</script>
</body>
</html>
HTMLEOF
