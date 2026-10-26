# shellcheck shell=sh
# action.cgi commands: Network and Wi-Fi.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  case "$F_cmd" in

    set_network)
      hostname=$(printf '%s' "${F_hostname}" | sed 's/[^a-zA-Z0-9-]//g')
      rtsp_port=$(sanitize_int_range "${F_rtsp_port}" 1 65535 554)
      telnet_port=$(sanitize_int_range "${F_telnet_port}" 1 65535 23)
      
      [ -n "$hostname" ] && hostname "$hostname" && echo "$hostname" > /mnt/config/hostname.conf
      
      /mnt/bin/rwconf /mnt/config/rtspserver.conf w " " PORT "$rtsp_port"
      /mnt/bin/rwconf /mnt/config/telnetd.conf w " " TELNET_PORT "$telnet_port"
      
      if wants_json_response; then
        json_body_ok "Network settings updated. RTSP/Telnet restart scheduled."
      else
        echo "Network settings updated.<br/>"
      fi
    ;;

    conf_dns)
        # Validate: must be empty or a dotted-quad IPv4 address
        validate_ip_or_empty() {
            addr="$1"
            [ -z "$addr" ] && return 0
            printf '%s' "$addr" | awk -F. 'NF==4 && $1+0==$1 && $2+0==$2 && $3+0==$3 && $4+0==$4 &&
                $1>=0 && $1<=255 && $2>=0 && $2<=255 && $3>=0 && $3<=255 && $4>=0 && $4<=255
                {exit 0} {exit 1}'
        }
        dns_primary="$F_dns_primary"
        dns_secondary="$F_dns_secondary"
        if ! validate_ip_or_empty "$dns_primary"; then
            if wants_json_response; then
              json_body_err "INVALID_DNS" "Invalid primary DNS address: $dns_primary"
            else
              log_event "error" "network" "Invalid primary DNS address: $dns_primary"
              echo "ERROR: invalid primary DNS address '$dns_primary'"
            fi
        elif ! validate_ip_or_empty "$dns_secondary"; then
            if wants_json_response; then
              json_body_err "INVALID_DNS" "Invalid secondary DNS address: $dns_secondary"
            else
              log_event "error" "network" "Invalid secondary DNS address: $dns_secondary"
              echo "ERROR: invalid secondary DNS address '$dns_secondary'"
            fi
        else
            rewrite_config /mnt/config/dns.conf DNS_PRIMARY "$dns_primary"
            rewrite_config /mnt/config/dns.conf DNS_SECONDARY "$dns_secondary"
            # Apply immediately to /etc/resolv.conf
            {
                [ -n "$dns_primary" ] && echo "nameserver $dns_primary"
                [ -n "$dns_secondary" ] && echo "nameserver $dns_secondary"
            } > /etc/resolv.conf
            if wants_json_response; then
              json_body_ok "DNS updated. Primary: ${dns_primary:-none} Secondary: ${dns_secondary:-none}. Reboot to make permanent."
            else
              echo "DNS updated. Primary: ${dns_primary:-none} Secondary: ${dns_secondary:-none}. Reboot to make permanent."
            fi
        fi
    ;;

    conf_static_ip)
        validate_ip_or_empty() {
            addr="$1"
            [ -z "$addr" ] && return 0
            printf '%s' "$addr" | awk -F. 'NF==4 && $1+0==$1 && $2+0==$2 && $3+0==$3 && $4+0==$4 &&
                $1>=0 && $1<=255 && $2>=0 && $2<=255 && $3>=0 && $3<=255 && $4>=0 && $4<=255
                {exit 0} {exit 1}'
        }
        ip_mode="$F_ip_mode"
        static_ip="$F_static_ip"
        static_netmask="$F_static_netmask"
        static_gateway="$F_static_gateway"
        case "$ip_mode" in
            static|dhcp) ;;
            *) ip_mode="dhcp" ;;
        esac
        if [ "$ip_mode" = "static" ]; then
            if [ -z "$static_ip" ] || ! validate_ip_or_empty "$static_ip"; then
                log_event "error" "network" "Invalid static IP address: $static_ip"
                echo "ERROR: invalid static IP '$static_ip'"
            elif ! validate_ip_or_empty "$static_netmask"; then
                log_event "error" "network" "Invalid netmask: $static_netmask"
                echo "ERROR: invalid netmask '$static_netmask'"
            elif ! validate_ip_or_empty "$static_gateway"; then
                log_event "error" "network" "Invalid gateway: $static_gateway"
                echo "ERROR: invalid gateway '$static_gateway'"
            else
                install_config /mnt/config/network.conf
                rewrite_config /mnt/config/network.conf IP_MODE "static"
                rewrite_config /mnt/config/network.conf STATIC_IP "$static_ip"
                rewrite_config /mnt/config/network.conf STATIC_NETMASK "${static_netmask:-255.255.255.0}"
                rewrite_config /mnt/config/network.conf STATIC_GATEWAY "$static_gateway"
                echo "Static IP saved: $static_ip / ${static_netmask:-255.255.255.0} gateway ${static_gateway:-none}. Reboot to apply."
            fi
        else
            install_config /mnt/config/network.conf
            rewrite_config /mnt/config/network.conf IP_MODE "dhcp"
            echo "DHCP mode saved. Reboot to apply."
        fi
    ;;

    wifi_scan)
        if wants_json_response; then
          json_body_err "FORMAT_NOT_SUPPORTED" "wifi_scan command does not support JSON format"
        else
          scan_out=""
          command -v iwlist >/dev/null 2>&1 && scan_out="$(iwlist wlan0 scan 2>/dev/null)"
          # Linux 6.6 has no wireless-tools: same text shape from iw, or from wpa_supplicant's own scan
          if [ -z "$scan_out" ] && command -v iw >/dev/null 2>&1; then
              scan_out="$(iw dev wlan0 scan 2>/dev/null | awk '
                  /^BSS / { if (n++) print ""; print "Cell " n " - Address: " substr($2, 1, 17); print "Encryption key:off" }
                  /^[ \t]*signal:/ { print "Signal level=" $2 }
                  /^[ \t]*SSID:/ { s = $0; sub(/^[ \t]*SSID: ?/, "", s); print "ESSID:\"" s "\"" }
                  /^[ \t]*(RSN|WPA):|capability:.*Privacy/ { print "Encryption key:on" }')"
          fi
          if [ -z "$scan_out" ] && command -v wpa_cli >/dev/null 2>&1; then
              wpa_cli -i wlan0 scan >/dev/null 2>&1; sleep 4
              scan_out="$(wpa_cli -i wlan0 scan_results 2>/dev/null | awk -F'\t' 'NR > 1 && NF >= 4 {
                  print "Cell " NR " - Address: " $1; print "Signal level=" $3
                  print ($4 ~ /WPA|WEP|RSN|SAE/) ? "Encryption key:on" : "Encryption key:off"; print "ESSID:\"" $5 "\"" }')"
          fi
          if [ -z "$scan_out" ]; then
              echo "<p class='help'>Scan failed or no results. Ensure WiFi is up.</p>"
          else
              # SSIDs come from any neighbour: HTML-escaped before display.
              rows="$(printf '%s\n' "$scan_out" | awk '
                  function esc(t) { gsub(/&/, "\\&amp;", t); gsub(/</, "\\&lt;", t); gsub(/>/, "\\&gt;", t); gsub(/"/, "\\&quot;", t); gsub(/\047/, "\\&#39;", t); return t }
                  function row() {
                      name = (ssid == "") ? "(hidden)" : esc(ssid)
                      printf "<tr class=\"wifi-pick\" data-ssid=\"%s\"><td>%s</td><td>%s</td><td>%s</td></tr>\n", (ssid == "" ? "" : esc(ssid)), name, (rssi != "" ? esc(rssi) : "n/a"), enc
                  }
                  /Cell [0-9]+ - Address:/ {
                      if (ssid != "" || rssi != "") row()
                      ssid = ""; rssi = ""; enc = "No"
                  }
                  /ESSID:/ {
                      n = split($0, a, "\""); ssid = (n >= 2) ? a[2] : ""
                  }
                  /Encryption key:on/  { enc = "Yes" }
                  /Encryption key:off/ { enc = "No"  }
                  /Signal level=/ {
                      sub(/.*Signal level=/, ""); sub(/[[:space:]].*/, ""); rssi = $0
                  }
                  /Extra:rssi=/ {
                      sub(/.*Extra:rssi=/, ""); sub(/[[:space:]].*/, ""); rssi = $0
                  }
                  END { if (rssi != "" || ssid != "") row() }
              ')"
              if [ -z "$rows" ]; then
                  echo "<p class='help'>No networks found.</p>"
              else
                  printf "<table class='table is-fullwidth is-hoverable is-size-7'><thead><tr><th>SSID</th><th>Quality</th><th>Encrypted</th></tr></thead><tbody>%s</tbody></table>\n" "$rows"
              fi
          fi
        fi
    ;;

    wifi_get_ssid)
        # Ask the interface, not a file. The camera often carries no
        # wpa_supplicant.conf at all (the firmware holds credentials in flash),
        # and after a wpa_cli reconfigure the file can disagree with the network
        # actually joined. Files are only a last resort.
        _ssid=""
        if command -v wpa_cli >/dev/null 2>&1; then
            # Take the ssid line only — `wpa_cli status` also prints `passphrase=`.
            _ssid="$(wpa_cli -i wlan0 status 2>/dev/null | awk '/^ssid=/ { print substr($0, 6); exit }')"
        fi
        if [ -z "$_ssid" ] && command -v iwconfig >/dev/null 2>&1; then
            _ssid="$(iwconfig wlan0 2>/dev/null | awk -F'"' '/ESSID:"/ { print $2; exit }')"
        fi
        if [ -z "$_ssid" ] && command -v iw >/dev/null 2>&1; then
            _ssid="$(iw dev wlan0 link 2>/dev/null | awk '/^[ \t]*SSID:/ { sub(/^[ \t]*SSID: ?/, ""); print; exit }')"
        fi
        if [ -z "$_ssid" ]; then
            for _wpa_conf in "$WIFI_CONFIG_PATH" /mnt/config/wpa_supplicant.conf /etc/wpa_supplicant.conf; do
                [ -f "$_wpa_conf" ] || continue
                _ssid="$(awk -F'"' '/^[ \t]*ssid=/ { print $2; exit }' "$_wpa_conf")"
                [ -n "$_ssid" ] && break
            done
        fi
        _ssid_safe="$(printf '%s' "$_ssid" | sed 's/\\/\\\\/g; s/"/\\"/g')"
        printf '{"status":"success","ssid":"%s"}\n' "$_ssid_safe"
    ;;

    wifi_set_config)
        # Must be the very path autorun.sh passes to `wpa_supplicant -c`, or
        # `wpa_cli reconfigure` below re-reads the old file and the change is
        # silently discarded — and the new one is never used at boot either.
        _wpa_conf="$WIFI_CONFIG_PATH"
        _wifi66=0
        if [ -f /mnt/v3/linux66-sd/wifi-apply ] && [ -x /usr/sbin/httpd ]; then
            # Linux 6.6: the boot reads config/wpa_supplicant.conf (kept in the flash settings or on the card)
            _wifi66=1
            _wpa_conf=/mnt/config/wpa_supplicant.conf
            [ -f "$_wpa_conf" ] || { [ -f /etc/wpa_supplicant.conf ] && cp /etc/wpa_supplicant.conf "$_wpa_conf"; }
        # From flash /mnt is in RAM: the file lives in jffs2, /mnt points to it.
        elif [ "$(cat /tmp/tc100-storage 2>/dev/null)" = flash ]; then
            _wpa_conf=/etc/jffs2/tc100/wpa_supplicant.conf
            [ -L "$WIFI_CONFIG_PATH" ] || { rm -f "$WIFI_CONFIG_PATH"; ln -s "$_wpa_conf" "$WIFI_CONFIG_PATH"; }
        fi
        _ssid="$(printf '%s' "${F_ssid:-}" | awk '{ gsub(/["\\]/, ""); print }' | cut -c1-32)"
        _psk="$(printf '%s' "${F_psk:-}" | awk '{ gsub(/["\\]/, ""); print }' | cut -c1-63)"
        _ssid_len="$(printf '%s' "$_ssid" | wc -c)"
        _psk_len="$(printf '%s' "$_psk" | wc -c)"
        if [ "$_ssid_len" -lt 1 ]; then
            json_body_err "INVALID_SSID" "SSID must be 1-32 characters"
        elif [ "$_psk_len" -lt 8 ]; then
            json_body_err "INVALID_PSK" "PSK must be at least 8 characters"
        else
            # scripts/wifi-txt.sh writes the new network first and keeps the
            # ones already in the file as a fallback (priority 1): a wrong
            # password does not take the camera off the network it was on.
            _wd="/tmp/wifi-set.$$"; mkdir -p "$_wd"
            printf 'SSID=%s\nPASSWORD=%s\n' "$_ssid" "$_psk" > "$_wd/wifi.txt"
            if ! sh /mnt/scripts/wifi-txt.sh apply "$_wd/wifi.txt" "$_wpa_conf" /etc/jffs2/anyka_cfg.ini >/dev/null 2>&1; then
                rm -rf "$_wd"
                json_body_err "WRITE_ERROR" "Failed to write WiFi configuration"
                exit 0
            fi
            rm -rf "$_wd"
            if [ "$_wifi66" = 1 ]; then
                ( sh /mnt/v3/linux66-sd/wifi-apply 2 </dev/null >/dev/null 2>&1 & )
            else
                command -v wpa_cli >/dev/null 2>&1 && wpa_cli -i wlan0 reconfigure >/dev/null 2>&1 || true
            fi
            json_body_ok "WiFi configuration updated for SSID: $_ssid. Reconnecting..."
        fi
    ;;
  esac
