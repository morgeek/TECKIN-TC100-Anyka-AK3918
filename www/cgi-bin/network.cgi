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

# ?part=settings: only the DNS / IP / Wi-Fi scan cards (Settings → Network);
# ?part=diag: only the read-only network state (Tools → Diagnostics). Without
# it, both (older links). The settings part skips common_functions.sh and probes.
NET_PART=all
case "&${QUERY_STRING:-}&" in
  *"&part=settings&"*) NET_PART=settings ;;
  *"&part=diag&"*) NET_PART=diag ;;
esac

DNS_PRIMARY=""
DNS_SECONDARY=""
[ ! -f /mnt/config/dns.conf ] && [ -f /mnt/config/dns.conf.dist ] && cp /mnt/config/dns.conf.dist /mnt/config/dns.conf 2>/dev/null || true
if [ -f /mnt/config/dns.conf ]; then
  . /mnt/config/dns.conf 2>/dev/null
fi

IP_MODE="dhcp"
STATIC_IP=""
STATIC_NETMASK="255.255.255.0"
STATIC_GATEWAY=""
[ ! -f /mnt/config/network.conf ] && [ -f /mnt/config/network.conf.dist ] && cp /mnt/config/network.conf.dist /mnt/config/network.conf 2>/dev/null || true
if [ -f /mnt/config/network.conf ]; then
  . /mnt/config/network.conf 2>/dev/null
fi

print_net_settings() {
cat << EOF
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
    window.EliteUI.csrfFetch('cgi-bin/action.cgi?cmd=conf_dns&dns_primary=' + encodeURIComponent(p) + '&dns_secondary=' + encodeURIComponent(s))
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
    window.EliteUI.csrfFetch(url)
        .then(function(r) { return r.text(); })
        .then(function(t) { statusEl.textContent = t.replace('<hr/>', '').trim(); btn.disabled = false; })
        .catch(function(e) { statusEl.textContent = 'Error: ' + e; btn.disabled = false; });
}
</script>
EOF
}

if [ "$NET_PART" = settings ]; then
  print_net_settings
  exit 0
fi

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

read_cfg_to() {
  _rc_out="$1"
  _rc_conf="$2"
  _rc_key="$3"
  _rc_fallback="$4"

  _rc_value=""
  if [ -r "/mnt/config/$_rc_conf" ]; then
    while IFS= read -r _rc_l || [ -n "$_rc_l" ]; do
      case "$_rc_l" in
        \[*\]) break ;;
        "${_rc_key}="*) _rc_value="${_rc_l#*=}" ;;
      esac
    done < "/mnt/config/$_rc_conf"
  fi
  if [ -z "$_rc_value" ] && type read_config >/dev/null 2>&1; then
    _rc_value="$(read_config "$_rc_conf" "$_rc_key" 2>/dev/null)"
  fi
  while :; do
    case "$_rc_value" in
      [[:space:]]*) _rc_value="${_rc_value#?}" ;;
      *[[:space:]]) _rc_value="${_rc_value%?}" ;;
      *) break ;;
    esac
  done
  [ -n "$_rc_value" ] || _rc_value="$_rc_fallback"
  eval "$_rc_out=\$_rc_value"
}

read_cfg() {
  read_cfg_to _rc_res "$1" "$2" "$3"
  printf '%s\n' "$_rc_res"
}

sanitize_port_to() {
  _sp_out="$1"
  _sp_val="$2"
  _sp_fallback="$3"
  case "$_sp_val" in
    ''|*[!0-9]*) _sp_val="$_sp_fallback" ;;
  esac
  if [ "$_sp_val" -lt 1 ] || [ "$_sp_val" -gt 65535 ]; then
    _sp_val="$_sp_fallback"
  fi
  eval "$_sp_out=\$_sp_val"
}

sanitize_port() {
  sanitize_port_to _sp_res "$1" "$2"
  printf '%s\n' "$_sp_res"
}

to_lower_ascii() {
  case "$1" in
    *[A-Z]*) printf '%s' "$1" | awk '{print tolower($0)}' ;;
    *) printf '%s' "$1" ;;
  esac
}

is_truthy_local() {
  _itl="$1"
  while :; do
    case "$_itl" in
      [[:space:]]*) _itl="${_itl#?}" ;;
      *[[:space:]]) _itl="${_itl%?}" ;;
      *) break ;;
    esac
  done
  case "$_itl" in
    1|[tT][rR][uU][eE]|[oO][nN]|[yY][eE][sS]|[eE][nN][aA][bB][lL][eE]|[eE][nN][aA][bB][lL][eE][dD]) return 0 ;;
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

LISTEN_TCP=""
if [ ! -r /proc/net/tcp ]; then
  LISTEN_TCP="$(with_timeout 5 netstat -lnt 2>/dev/null)"
  if [ -z "$LISTEN_TCP" ]; then
    LISTEN_TCP="$(with_timeout 5 netstat -ln 2>/dev/null)"
  fi
fi

is_port_open_tcp() {
  port="$1"
  case "$port" in ''|*[!0-9]*) return 1 ;; esac
  if [ -r /proc/net/tcp ] || [ -r /proc/net/tcp6 ]; then
    for _pn_f in /proc/net/tcp /proc/net/tcp6; do
      [ -r "$_pn_f" ] || continue
      while read -r _pn_sl _pn_loc _pn_rem _pn_st _pn_rest; do
        [ "$_pn_st" = "0A" ] || continue
        _pn_p="${_pn_loc##*:}"
        case "$_pn_p" in ''|*[!0-9A-Fa-f]*) continue ;; esac
        [ "$((0x$_pn_p))" -eq "$port" ] 2>/dev/null && return 0
      done < "$_pn_f"
    done
    return 1
  fi
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
    _epr_badge="<span class='services-status-tag is-running'>OPEN</span>"
  else
    _epr_badge="<span class='services-status-tag is-stopped'>CLOSED</span>"
  fi

  expected_label="optional"
  if [ "$expected" = "1" ]; then
    expected_label="expected"
  elif [ "$expected" = "0" ]; then
    expected_label="disabled"
  fi

  open_ports_rows="${open_ports_rows}<tr><td>${service_name}</td><td>${port}/tcp</td><td>${_epr_badge}</td><td>${expected_label}</td><td>${note}</td></tr>
"
}

read_cfg_to _nc_v rtspserver.conf PORT 554; sanitize_port_to rtsp_port "$_nc_v" 554
read_cfg_to _nc_v onvif.conf ONVIF_PORT 8081; sanitize_port_to onvif_port "$_nc_v" 8081
read_cfg_to _nc_v ftp.conf PORT 21; sanitize_port_to ftp_port "$_nc_v" 21
read_cfg_to _nc_v telnetd.conf TELNET_PORT 23; sanitize_port_to telnet_port "$_nc_v" 23
read_cfg_to security_hardening_mode boot.conf SECURITY_HARDENING_MODE 0

# The camera serves the web UI over plain HTTP on port 80 only (HTTPS: reverse proxy on the owner network).
http_port=80
http_expected=1
http_note="Web UI (plain HTTP)"

# A port is "expected" open only when its service starts at boot; otherwise
# it is "optional" (ONVIF/FTP/Telnet were always "expected", so a stopped
# optional service read as a fault).
onvif_expected=""; [ -e "/mnt/config/autostart/onvif" ] && onvif_expected=1
ftp_expected=""; [ -e "/mnt/config/autostart/ftp-server" ] && ftp_expected=1
telnet_expected=""; [ -e "/mnt/config/autostart/telnet-server" ] && telnet_expected=1
ftp_note="File transfer service"
telnet_note="Shell access service"
if is_truthy_local "$security_hardening_mode"; then
  ftp_expected=0
  telnet_expected=0
  ftp_note="Blocked by SECURITY_HARDENING_MODE=1"
  telnet_note="Blocked by SECURITY_HARDENING_MODE=1"
fi

open_ports_rows=""
emit_port_row "HTTP web UI" "$http_port" "$http_expected" "$http_note"
emit_port_row "RTSP" "$rtsp_port" 1 "Main/sub streams"
emit_port_row "ONVIF" "$onvif_port" "$onvif_expected" "NVR/Home Assistant discovery"
emit_port_row "FTP" "$ftp_port" "$ftp_expected" "$ftp_note"
emit_port_row "Telnet" "$telnet_port" "$telnet_expected" "$telnet_note"

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
# -n: numeric. Without it the gateway showed as "lan.home" and the reverse
# DNS lookups could stall the page.
routes_text="$(with_timeout 5 route -n 2>/dev/null)"
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

# route prints "0.0.0.0 <gw>", ip route "default via <gw>"; the /proc/net/route fallback above
# prints "<iface> 0.0.0.0 <gw>".
default_gateway="$(printf '%s\n' "$routes_text" | awk '$1=="default"{for(i=2;i<NF;i++) if($i=="via"){print $(i+1); exit} print $2; exit} $1=="0.0.0.0"{print $2; exit} $2=="0.0.0.0" && $3!="0.0.0.0"{print $3; exit}')"
[ -n "$default_gateway" ] || default_gateway="n/a"

dns_servers=""
if [ -n "$dns_text" ]; then
  _dn_old_ifs="$IFS"
  IFS='
'
  for _dn_l in $dns_text; do
    IFS="$_dn_old_ifs"
    set -- $_dn_l
    if [ "$1" = "nameserver" ] && [ -n "$2" ]; then
      dns_servers="${dns_servers:+${dns_servers} }$2"
    fi
    IFS='
'
  done
  IFS="$_dn_old_ifs"
fi
[ -n "$dns_servers" ] || dns_servers="n/a"

listen_tcp_count=0
if [ -r /proc/net/tcp ]; then
  while read -r _pn_sl _pn_loc _pn_rem _pn_st _pn_rest; do
    [ "$_pn_st" = "0A" ] && listen_tcp_count=$((listen_tcp_count + 1))
  done < /proc/net/tcp
  if [ -r /proc/net/tcp6 ]; then
    while read -r _pn_sl _pn_loc _pn_rem _pn_st _pn_rest; do
      [ "$_pn_st" = "0A" ] && listen_tcp_count=$((listen_tcp_count + 1))
    done < /proc/net/tcp6
  fi
elif [ -n "$LISTEN_TCP" ]; then
  listen_tcp_count="$(printf '%s\n' "$LISTEN_TCP" | awk '$1 ~ /^tcp/{count++} END{print count+0}')"
fi

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

EOF
[ "$NET_PART" = diag ] || print_net_settings
