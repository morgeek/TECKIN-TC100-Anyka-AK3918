#!/bin/sh

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""
source ./func.cgi
PATH="/bin:/sbin:/usr/bin:/usr/sbin"

if [ -r /mnt/scripts/common_functions.sh ]; then
  . /mnt/scripts/common_functions.sh
fi

if type install_config >/dev/null 2>&1; then
  install_config /mnt/config/boot.conf
  install_config /mnt/config/rtspserver.conf
  install_config /mnt/config/onvif.conf
  install_config /mnt/config/ftp.conf
  install_config /mnt/config/telnetd.conf
fi

read_cfg() {
  conf="$1"
  key="$2"
  fallback="$3"

  value=""
  if type read_config >/dev/null 2>&1; then
    value="$(read_config "$conf" "$key" 2>/dev/null)"
  fi
  if [ -z "$value" ] && [ -r "/mnt/config/$conf" ]; then
    value="$(awk -F= -v key="$key" '$1==key{print $2; exit}' "/mnt/config/$conf" 2>/dev/null)"
  fi
  [ -n "$value" ] || value="$fallback"
  printf '%s\n' "$value"
}

sanitize_port() {
  value="$1"
  fallback="$2"
  case "$value" in
    ''|*[!0-9]*) value="$fallback" ;;
  esac
  if [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
    value="$fallback"
  fi
  printf '%s\n' "$value"
}

is_truthy_local() {
  case "$1" in
    1|true|on|yes|enabled) return 0 ;;
    *) return 1 ;;
  esac
}

LISTEN_TCP="$(netstat -lnt 2>/dev/null)"
if [ -z "$LISTEN_TCP" ]; then
  LISTEN_TCP="$(netstat -ln 2>/dev/null)"
fi

is_port_open_tcp() {
  port="$1"
  printf '%s\n' "$LISTEN_TCP" | awk -v port="$port" '
    $1 ~ /^tcp/ {
      local_addr=$4
      split(local_addr, parts, ":")
      if (parts[length(parts)] == port) {
        found=1
        exit
      }
    }
    END { exit(found ? 0 : 1) }
  '
}

status_badge() {
  if [ "$1" = "open" ]; then
    printf "<span class='services-status-tag is-running'>OPEN</span>"
  else
    printf "<span class='services-status-tag is-stopped'>CLOSED</span>"
  fi
}

emit_port_row() {
  service_name="$1"
  port="$2"
  expected="$3"
  note="$4"

  if is_port_open_tcp "$port"; then
    runtime_state="open"
  else
    runtime_state="closed"
  fi

  expected_label="optional"
  if [ "$expected" = "1" ]; then
    expected_label="expected"
  elif [ "$expected" = "0" ]; then
    expected_label="disabled"
  fi

  printf "<tr><td>%s</td><td>%s/tcp</td><td>%s</td><td>%s</td><td>%s</td></tr>\n" \
    "$service_name" "$port" "$(status_badge "$runtime_state")" "$expected_label" "$note"
}

web_mode="$(printf '%s' "$(read_cfg boot.conf WEB_MODE full)" | tr '[:upper:]' '[:lower:]')"
ultralite_http_port="$(sanitize_port "$(read_cfg boot.conf ULTRALITE_HTTP_PORT 80)" 80)"
rtsp_port="$(sanitize_port "$(read_cfg rtspserver.conf PORT 554)" 554)"
onvif_port="$(sanitize_port "$(read_cfg onvif.conf ONVIF_PORT 8081)" 8081)"
ftp_port="$(sanitize_port "$(read_cfg ftp.conf PORT 21)" 21)"
telnet_port="$(sanitize_port "$(read_cfg telnetd.conf TELNET_PORT 23)" 23)"
security_hardening_mode="$(read_cfg boot.conf SECURITY_HARDENING_MODE 0)"

http_port=80
http_expected=0
https_expected=0
http_note="HTTP UI disabled"
https_note="HTTPS UI disabled"

case "$web_mode" in
  full)
    http_port=80
    http_expected=1
    https_expected=1
    http_note="HTTP redirect endpoint (to HTTPS)"
    https_note="Main secure web UI"
    ;;
  http)
    http_port=80
    http_expected=1
    https_expected=0
    http_note="Main web UI (HTTP mode)"
    https_note="Disabled by WEB_MODE=http"
    ;;
  ultra-lite|ultralite)
    http_port="$ultralite_http_port"
    http_expected=1
    https_expected=0
    http_note="BusyBox ultra-lite web UI"
    https_note="Disabled by WEB_MODE=ultra-lite"
    ;;
  off)
    http_expected=0
    https_expected=0
    ;;
esac

ftp_expected=1
telnet_expected=1
ftp_note="File transfer service"
telnet_note="Shell access service"
if is_truthy_local "$security_hardening_mode"; then
  ftp_expected=0
  telnet_expected=0
  ftp_note="Blocked by SECURITY_HARDENING_MODE=1"
  telnet_note="Blocked by SECURITY_HARDENING_MODE=1"
fi

open_ports_rows="$(cat <<EOF
$(emit_port_row "HTTPS web UI" 443 "$https_expected" "$https_note")
$(emit_port_row "HTTP web UI" "$http_port" "$http_expected" "$http_note")
$(emit_port_row "RTSP" "$rtsp_port" 1 "Main/sub streams")
$(emit_port_row "ONVIF" "$onvif_port" 1 "NVR/Home Assistant discovery")
$(emit_port_row "FTP" "$ftp_port" "$ftp_expected" "$ftp_note")
$(emit_port_row "Telnet" "$telnet_port" "$telnet_expected" "$telnet_note")
EOF
)"

interfaces_text="$(ifconfig 2>/dev/null; iwconfig 2>/dev/null)"
routes_text="$(route 2>/dev/null)"
dns_text="$(cat /etc/resolv.conf 2>/dev/null)"
listen_text="$(netstat -l 2>/dev/null)"
connections_text="$(netstat 2>/dev/null)"

primary_ip="$(printf '%s\n' "$interfaces_text" | sed -n -e 's/.*inet addr:\([0-9.]*\).*/\1/p' -e 's/^[[:space:]]*inet \([0-9.]*\).*/\1/p' | grep -v '^127\.' | head -n 1)"
[ -n "$primary_ip" ] || primary_ip="n/a"

default_gateway="$(printf '%s\n' "$routes_text" | awk '$1=="default" || $1=="0.0.0.0"{print $2; exit}')"
[ -n "$default_gateway" ] || default_gateway="n/a"

dns_servers="$(printf '%s\n' "$dns_text" | awk '/^nameserver[[:space:]]+/{print $2}' | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
[ -n "$dns_servers" ] || dns_servers="n/a"

listen_tcp_count="$(printf '%s\n' "$LISTEN_TCP" | awk '$1 ~ /^tcp/{count++} END{print count+0}')"

cat << EOF

<div class='info-grid'>
    <div class='info-side'>
        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 12h6M14 12h6M10 8l4 4l-4 4'/></svg><span>Network Summary</span></span></p></header>
            <div class='card-content'>
                Primary IP:
                <pre class='info-pre'>$primary_ip</pre>
                Default gateway:
                <pre class='info-pre'>$default_gateway</pre>
                DNS servers:
                <pre class='info-pre'>$dns_servers</pre>
                Listening TCP sockets:
                <pre class='info-pre'>$listen_tcp_count</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M7 4h10v6H7zM12 10v10M9 16h6'/></svg><span>Open Service Ports</span></span></p></header>
            <div class='card-content'>
                <div class='info-table-wrap'>
                    <table class='table is-fullwidth is-hoverable services-table'>
                        <thead>
                            <tr>
                                <th>Service</th>
                                <th>Port</th>
                                <th>Runtime state</th>
                                <th>Configured</th>
                                <th>Notes</th>
                            </tr>
                        </thead>
                        <tbody>
                            $open_ports_rows
                        </tbody>
                    </table>
                </div>
                <p class='help'>Runtime state is probed from local listening TCP sockets (<code>netstat</code>).</p>
            </div>
        </div>
    </div>

    <div class='info-main'>
        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 12h6M14 12h6M10 8l4 4l-4 4'/></svg><span>Interfaces</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>$interfaces_text</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7h9M13 7l3-3M13 7l3 3M20 17H11M11 17l-3-3M11 17l-3 3'/></svg><span>Routes and DNS</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>$routes_text

--- /etc/resolv.conf ---
$dns_text</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M5 7h14M5 12h14M5 17h14'/></svg><span>Listening Sockets</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>$listen_text</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M9 12a3 3 0 0 1 3-3h3M15 12a3 3 0 0 1-3 3H9M7 9l-2 2l2 2M17 9l2 2l-2 2'/></svg><span>Connections</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>$connections_text</pre>
            </div>
        </div>
    </div>
</div>

</body>
</html>
EOF
