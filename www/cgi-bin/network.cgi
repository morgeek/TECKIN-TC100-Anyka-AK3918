#!/bin/sh

. /mnt/www/cgi-bin/func.cgi
rate_limit_check 30 60

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""
PATH="/bin:/sbin:/usr/bin:/usr/sbin:/mnt/bin:/mnt/sbin"
NETSTAT_LISTEN_MAX_LINES=220
NETSTAT_CONNECTIONS_MAX_LINES=320

if [ -r /mnt/scripts/common_functions.sh ]; then
  . /mnt/scripts/common_functions.sh
fi

if type install_config >/dev/null 2>&1; then
  install_config /mnt/config/boot.conf
  install_config /mnt/config/rtspserver.conf
  install_config /mnt/config/onvif.conf
  install_config /mnt/config/ftp.conf
  install_config /mnt/config/telnetd.conf
  install_config /mnt/config/dns.conf
fi

DNS_PRIMARY=""
DNS_SECONDARY=""
if [ -f /mnt/config/dns.conf ]; then
  . /mnt/config/dns.conf 2>/dev/null
fi

IP_MODE="dhcp"
STATIC_IP=""
STATIC_NETMASK="255.255.255.0"
STATIC_GATEWAY=""
if type install_config >/dev/null 2>&1; then
  install_config /mnt/config/network.conf
fi
if [ -f /mnt/config/network.conf ]; then
  . /mnt/config/network.conf 2>/dev/null
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
  value="$(printf '%s' "$value" | sed 's/\r//g; s/^[[:space:]]*//; s/[[:space:]]*$//')"
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

to_lower_ascii() {
  printf '%s' "$1" | awk '{print tolower($0)}'
}

is_truthy_local() {
  token="$(printf '%s' "$1" | sed 's/\r//g; s/^[[:space:]]*//; s/[[:space:]]*$//')"
  token="$(to_lower_ascii "$token")"
  case "$token" in
    1|true|on|yes|enabled) return 0 ;;
    *) return 1 ;;
  esac
}

with_timeout() {
  _wt_secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$_wt_secs" "$@"
    return
  fi
  if [ -x /mnt/bin/busybox ] && /mnt/bin/busybox timeout --help >/dev/null 2>&1; then
    /mnt/bin/busybox timeout "$_wt_secs" "$@"
    return
  fi
  "$@"
}

capture_limited_output() {
  max_lines="$1"
  shift
  "$@" 2>/dev/null | awk -v max="$max_lines" '
    NR <= max {
      print
      next
    }
    NR == (max + 1) {
      printf "... (truncated to %d lines)\n", max
      exit
    }
  '
}

normalize_web_mode() {
  mode="$(printf '%s' "$1" | sed 's/\r//g; s/^[[:space:]]*//; s/[[:space:]]*$//')"
  mode="$(to_lower_ascii "$mode")"
  case "$mode" in
    ultralite) mode="ultra-lite" ;;
  esac
  case "$mode" in
    full|http|ultra-lite|off) ;;
    *) mode="full" ;;
  esac
  printf '%s\n' "$mode"
}

LISTEN_TCP="$(with_timeout 5 netstat -lnt 2>/dev/null)"
if [ -z "$LISTEN_TCP" ]; then
  LISTEN_TCP="$(with_timeout 5 netstat -ln 2>/dev/null)"
fi
if [ -z "$LISTEN_TCP" ] && [ -r /proc/net/tcp ]; then
  # Build a netstat-like line set from /proc/net/tcp so is_port_open_tcp awk still works
  LISTEN_TCP="$(awk '
    function h2d(h,   v,i,c) {
      v=0; for(i=1;i<=length(h);i++) {
        c=substr(h,i,1)
        if(c>="0"&&c<="9") v=v*16+c-"0"
        else if(c>="a"&&c<="f") v=v*16+(c-"a")+10
        else if(c>="A"&&c<="F") v=v*16+(c-"A")+10
      }; return v
    }
    NR>1 && $4=="0A" {
      split($2,la,":")
      printf "tcp 0 0 0.0.0.0:%d 0.0.0.0:* LISTEN\n", h2d(la[2])
    }
  ' /proc/net/tcp 2>/dev/null)"
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

web_mode="$(normalize_web_mode "$(read_cfg boot.conf WEB_MODE full)")"
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

# ── interfaces ────────────────────────────────────────────────────────────────
interfaces_text="$(with_timeout 5 ifconfig 2>/dev/null)"
if [ -z "$interfaces_text" ]; then
  interfaces_text="$(with_timeout 5 ip addr 2>/dev/null)"
fi
if [ -z "$interfaces_text" ] && [ -r /proc/net/dev ]; then
  interfaces_text="$(cat /proc/net/dev 2>/dev/null)"
fi
# append wireless info if available (errors suppressed)
_wifi_text="$(with_timeout 3 iwconfig 2>/dev/null)"
[ -n "$_wifi_text" ] && interfaces_text="${interfaces_text}
--- wireless ---
${_wifi_text}"

# ── routes ────────────────────────────────────────────────────────────────────
routes_text="$(with_timeout 5 route 2>/dev/null)"
if [ -z "$routes_text" ]; then
  routes_text="$(with_timeout 5 ip route 2>/dev/null)"
fi
if [ -z "$routes_text" ] && [ -r /proc/net/route ]; then
  routes_text="$(awk '
    function h2d(h,   v,i,c) {
      v=0; for(i=1;i<=length(h);i++) {
        c=substr(h,i,1)
        if(c>="0"&&c<="9") v=v*16+c-"0"
        else if(c>="a"&&c<="f") v=v*16+(c-"a")+10
        else if(c>="A"&&c<="F") v=v*16+(c-"A")+10
      }; return v
    }
    function hexip(s) {
      return h2d(substr(s,7,2))"."h2d(substr(s,5,2))"."h2d(substr(s,3,2))"."h2d(substr(s,1,2))
    }
    NR==1 { printf "%-8s %-16s %-16s %-6s %-16s\n","Iface","Destination","Gateway","Flags","Mask"; next }
    { printf "%-8s %-16s %-16s %-6s %-16s\n",$1,hexip($2),hexip($3),$4,hexip($8) }
  ' /proc/net/route 2>/dev/null)"
fi

# ── dns ───────────────────────────────────────────────────────────────────────
dns_text="$(cat /etc/resolv.conf 2>/dev/null)"

# ── helper: decode /proc/net/tcp or /proc/net/udp ────────────────────────────
_proc_net_to_text() {
  _pn_file="$1"
  _pn_proto="$2"
  [ -r "$_pn_file" ] || return
  awk -v proto="$_pn_proto" '
    function h2d(h,   v,i,c) {
      v=0; for(i=1;i<=length(h);i++) {
        c=substr(h,i,1)
        if(c>="0"&&c<="9") v=v*16+c-"0"
        else if(c>="a"&&c<="f") v=v*16+(c-"a")+10
        else if(c>="A"&&c<="F") v=v*16+(c-"A")+10
      }; return v
    }
    function hexip(s) {
      return h2d(substr(s,7,2))"."h2d(substr(s,5,2))"."h2d(substr(s,3,2))"."h2d(substr(s,1,2))
    }
    function st2s(st) {
      if(st=="01") return "ESTABLISHED"
      if(st=="02") return "SYN_SENT"
      if(st=="03") return "SYN_RECV"
      if(st=="04") return "FIN_WAIT1"
      if(st=="05") return "FIN_WAIT2"
      if(st=="06") return "TIME_WAIT"
      if(st=="07") return "CLOSE"
      if(st=="08") return "CLOSE_WAIT"
      if(st=="09") return "LAST_ACK"
      if(st=="0A") return "LISTEN"
      if(st=="0B") return "CLOSING"
      return st
    }
    NR==1 { printf "%-5s %-21s %-21s %s\n","Proto","Local","Remote","State"; next }
    {
      split($2,la,":"); split($3,ra,":")
      printf "%-5s %-21s %-21s %s\n", proto,
        hexip(la[1])":"h2d(la[2]),
        hexip(ra[1])":"h2d(ra[2]),
        st2s($4)
    }
  ' "$_pn_file" 2>/dev/null
}

# ── listening sockets ─────────────────────────────────────────────────────────
listen_text="$(capture_limited_output "$NETSTAT_LISTEN_MAX_LINES" with_timeout 5 netstat -ln 2>/dev/null)"
if [ -z "$listen_text" ]; then
  listen_text="$(capture_limited_output "$NETSTAT_LISTEN_MAX_LINES" with_timeout 5 ss -ln 2>/dev/null)"
fi
if [ -z "$listen_text" ]; then
  _tcp_l="$(_proc_net_to_text /proc/net/tcp tcp | awk '$4=="LISTEN"')"
  _udp_l="$(_proc_net_to_text /proc/net/udp udp)"
  listen_text="${_tcp_l}
${_udp_l}"
fi

# ── connections ───────────────────────────────────────────────────────────────
connections_text="$(capture_limited_output "$NETSTAT_CONNECTIONS_MAX_LINES" with_timeout 5 netstat 2>/dev/null)"
if [ -z "$connections_text" ]; then
  connections_text="$(capture_limited_output "$NETSTAT_CONNECTIONS_MAX_LINES" with_timeout 5 ss 2>/dev/null)"
fi
if [ -z "$connections_text" ]; then
  connections_text="$(_proc_net_to_text /proc/net/tcp tcp)"
fi

primary_ip="$(printf '%s\n' "$interfaces_text" | sed -n -e 's/.*inet addr:\([0-9.]*\).*/\1/p' -e 's/^[[:space:]]*inet \([0-9.]*\).*/\1/p' | grep -v '^127\.' | head -n 1)"
[ -n "$primary_ip" ] || primary_ip="n/a"

default_gateway="$(printf '%s\n' "$routes_text" | awk '$1=="default" || $1=="0.0.0.0"{print $2; exit}')"
[ -n "$default_gateway" ] || default_gateway="n/a"

dns_servers="$(printf '%s\n' "$dns_text" | awk '
  /^nameserver[[:space:]]+/ {
    if (out != "") {
      out = out " "
    }
    out = out $2
  }
  END { print out }
')"
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

<div class='card status_card info-card mt-card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M12 3v6M5 21h14M6 9h12M7 15h10'/></svg><span>DNS Configuration</span></span></p></header>
    <div class='card-content'>
        <p class='help mb-help'>Override the DHCP-assigned DNS servers. Leave blank to use DHCP DNS. Changes take effect immediately and persist across reboots.</p>
        <div class='field is-horizontal'>
            <div class='field-label is-normal'><label class='label' for='dns_primary_input'>Primary DNS</label></div>
            <div class='field-body'>
                <div class='field'>
                    <input class='input' type='text' id='dns_primary_input' placeholder='e.g. 1.1.1.1' maxlength='15' value='$DNS_PRIMARY'>
                </div>
            </div>
        </div>
        <div class='field is-horizontal'>
            <div class='field-label is-normal'><label class='label' for='dns_secondary_input'>Secondary DNS</label></div>
            <div class='field-body'>
                <div class='field'>
                    <input class='input' type='text' id='dns_secondary_input' placeholder='e.g. 1.0.0.1 (optional)' maxlength='15' value='$DNS_SECONDARY'>
                </div>
            </div>
        </div>
        <div class='field is-horizontal'>
            <div class='field-label'></div>
            <div class='field-body'>
                <div class='field'>
                    <button class='button is-primary' id='dns_save_btn' type='button' onclick='saveDns()'>Save DNS</button>
                    <span id='dns_save_status' class='save-status-label'></span>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
function saveDns() {
    var p = document.getElementById('dns_primary_input').value.trim();
    var s = document.getElementById('dns_secondary_input').value.trim();
    var statusEl = document.getElementById('dns_save_status');
    var btn = document.getElementById('dns_save_btn');
    btn.disabled = true;
    statusEl.textContent = 'Saving...';
    fetch('cgi-bin/action.cgi?cmd=conf_dns&dns_primary=' + encodeURIComponent(p) + '&dns_secondary=' + encodeURIComponent(s))
        .then(function(r) { return r.text(); })
        .then(function(t) {
            statusEl.textContent = t.trim();
            btn.disabled = false;
        })
        .catch(function(e) {
            statusEl.textContent = 'Error: ' + e;
            btn.disabled = false;
        });
}
</script>


<div class='card status_card info-card mt-card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M12 2a10 10 0 1 1 0 20A10 10 0 0 1 12 2zm0 4v4l3 3'/></svg><span>IP Configuration</span></span></p></header>
    <div class='card-content'>
        <p class='help mb-help'>Switch between DHCP and a fixed static IP. Changes take effect after reboot.</p>
        <div class='field'>
            <label class='radio'><input type='radio' name='ip_mode' id='ip_mode_dhcp' value='dhcp' $([ "${IP_MODE:-dhcp}" != "static" ] && echo "checked")> DHCP (automatic)</label>
            &nbsp;&nbsp;
            <label class='radio'><input type='radio' name='ip_mode' id='ip_mode_static' value='static' $([ "${IP_MODE:-dhcp}" = "static" ] && echo "checked")> Static IP</label>
        </div>
        <div id='static_ip_fields' class='$([ "${IP_MODE:-dhcp}" != "static" ] && echo "is-hidden")'>
            <div class='field is-horizontal mt-section'>
                <div class='field-label is-normal'><label class='label' for='static_ip_input'>IP Address</label></div>
                <div class='field-body'><div class='field'>
                    <input class='input' type='text' id='static_ip_input' placeholder='e.g. 192.168.1.100' maxlength='15' value='$STATIC_IP'>
                </div></div>
            </div>
            <div class='field is-horizontal'>
                <div class='field-label is-normal'><label class='label' for='static_netmask_input'>Netmask</label></div>
                <div class='field-body'><div class='field'>
                    <input class='input' type='text' id='static_netmask_input' placeholder='e.g. 255.255.255.0' maxlength='15' value='${STATIC_NETMASK:-255.255.255.0}'>
                </div></div>
            </div>
            <div class='field is-horizontal'>
                <div class='field-label is-normal'><label class='label' for='static_gateway_input'>Gateway</label></div>
                <div class='field-body'><div class='field'>
                    <input class='input' type='text' id='static_gateway_input' placeholder='e.g. 192.168.1.1' maxlength='15' value='$STATIC_GATEWAY'>
                </div></div>
            </div>
        </div>
        <div class='field mt-section'>
            <button class='button is-primary' id='ip_save_btn' type='button' onclick='saveIpConfig()'>Save IP Config</button>
            <span id='ip_save_status' class='save-status-label'></span>
        </div>
    </div>
</div>

<div class='card status_card info-card mt-card'>
    <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M5 12.5C5 9 8 6 12 6s7 3 7 6.5M8 15c0-2.2 1.8-4 4-4s4 1.8 4 4M12 19h.01'/></svg><span>WiFi Networks</span></span></p></header>
    <div class='card-content'>
        <button class='button is-light' id='wifi_scan_btn' type='button' onclick='doWifiScan()'>Scan</button>
        <span class='help help-inline'>Scans for nearby WiFi networks. Takes 3-5 seconds.</span>
        <div id='wifi_scan_results' class='mt-section'></div>
    </div>
</div>

<script>
document.querySelectorAll('input[name="ip_mode"]').forEach(function(r) {
    r.addEventListener('change', function() {
        document.getElementById('static_ip_fields').style.display =
            (this.value === 'static') ? '' : 'none';
    });
});
function saveIpConfig() {
    var mode = document.querySelector('input[name="ip_mode"]:checked').value;
    var ip   = document.getElementById('static_ip_input').value.trim();
    var mask = document.getElementById('static_netmask_input').value.trim();
    var gw   = document.getElementById('static_gateway_input').value.trim();
    var statusEl = document.getElementById('ip_save_status');
    var btn = document.getElementById('ip_save_btn');
    btn.disabled = true;
    statusEl.textContent = 'Saving...';
    var url = 'cgi-bin/action.cgi?cmd=conf_static_ip&ip_mode=' + encodeURIComponent(mode) +
              '&static_ip=' + encodeURIComponent(ip) +
              '&static_netmask=' + encodeURIComponent(mask) +
              '&static_gateway=' + encodeURIComponent(gw);
    fetch(url)
        .then(function(r) { return r.text(); })
        .then(function(t) { statusEl.textContent = t.replace('<hr/>', '').trim(); btn.disabled = false; })
        .catch(function(e) { statusEl.textContent = 'Error: ' + e; btn.disabled = false; });
}
function doWifiScan() {
    var btn = document.getElementById('wifi_scan_btn');
    var results = document.getElementById('wifi_scan_results');
    btn.disabled = true;
    btn.textContent = 'Scanning...';
    results.innerHTML = '';
    fetch('cgi-bin/action.cgi?cmd=wifi_scan')
        .then(function(r) { return r.text(); })
        .then(function(t) {
            results.innerHTML = t.replace('<hr/>', '').trim();
            btn.disabled = false;
            btn.textContent = 'Scan';
        })
        .catch(function(e) {
            results.innerHTML = 'Scan failed: ' + e;
            btn.disabled = false;
            btn.textContent = 'Scan';
        });
}
</script>
EOF
