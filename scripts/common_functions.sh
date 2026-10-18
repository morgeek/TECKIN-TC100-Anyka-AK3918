#!/bin/sh

# This file is supposed to bundle some frequently used functions
# so they can be easily improved in one place and be reused all over the place

# tr(1) shim — same as func.cgi's. The camera's busybox carries the tr applet
# but ships no symlink for it, so a bare `tr` exits 127 and yields "" inside
# $(...): silent data corruption, not an error. Daemons sourcing this file get
# working tr calls; standalone scripts must define their own or avoid tr.
if ! command -v tr >/dev/null 2>&1; then
    tr() { busybox tr "$@"; }
fi

# timeout(1) shim — see func.cgi for the full story. /bin/timeout is the old
# busybox variant expecting `-t SECS`, so `timeout SECS CMD` silently fails to
# run CMD at all. Route through busybox, whose applet takes the modern form.
if ! timeout 1 true >/dev/null 2>&1; then
    # The busybox applet only finds CMD when it is given as a path ("timeout 5
    # ifconfig" failed with "can't execute 'ifconfig'", which is why the
    # Network page showed no IP and no gateway), so resolve bare names first.
    timeout() {
        _to_secs="$1"; shift
        case "$1" in
            */*|'') ;;
            *) _to_cmd="$(command -v "$1" 2>/dev/null)"
               case "$_to_cmd" in /*) shift; set -- "$_to_cmd" "$@" ;; esac ;;
        esac
        busybox timeout "$_to_secs" "$@"
    }
fi

BUSYBOX_BIN=""

_CF_BTIME=0
_cf_read_btime() {
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _CF_BTIME="$_v" && break
  done < /proc/stat
}
_cf_read_ts() {
  [ "$_CF_BTIME" -gt 0 ] || _cf_read_btime
  read -r _up _ < /proc/uptime
  _CF_TS=$((_CF_BTIME + ${_up%.*}))
}

get_busybox_bin()
{
  if [ -n "$BUSYBOX_BIN" ] && [ -x "$BUSYBOX_BIN" ]; then
    echo "$BUSYBOX_BIN"
    return 0
  fi

  if [ -x /mnt/bin/busybox ]; then
    BUSYBOX_BIN="/mnt/bin/busybox"
  elif [ -x /bin/busybox ]; then
    BUSYBOX_BIN="/bin/busybox"
  elif command -v busybox >/dev/null 2>&1; then
    BUSYBOX_BIN="$(command -v busybox)"
  else
    BUSYBOX_BIN="busybox"
  fi

  echo "$BUSYBOX_BIN"
}

run_busybox()
{
  # Use the cached global directly to avoid a subshell fork on every call.
  [ -n "$BUSYBOX_BIN" ] && [ -x "$BUSYBOX_BIN" ] || BUSYBOX_BIN="$(get_busybox_bin)"
  "$BUSYBOX_BIN" "$@"
}

# run_with_timeout <seconds> <cmd> [args...] — runs cmd under a timeout.
# Tries system timeout first, then busybox timeout, then runs directly.
run_with_timeout()
{
  _rwt_secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$_rwt_secs" "$@"
    return
  fi
  [ -n "$BUSYBOX_BIN" ] && [ -x "$BUSYBOX_BIN" ] || BUSYBOX_BIN="$(get_busybox_bin)"
  if "$BUSYBOX_BIN" timeout --help >/dev/null 2>&1; then
    "$BUSYBOX_BIN" timeout "$_rwt_secs" "$@"
    return
  fi
  "$@"
}

get_active_primary_ip()
{
  # High-speed path: use the boot-time cached IP if available.
  if [ -r /tmp/camera_ip.txt ]; then
    read -r _gai_ip < /tmp/camera_ip.txt
    if [ -n "$_gai_ip" ]; then
      printf '%s\n' "$_gai_ip"
      return 0
    fi
  fi

  # Fallback: Tries to find the IP assigned to the interface with the default route.
  # Use /proc/net/route to avoid 'route -n' fork.
  _gai_iface="wlan0"
  while read -r _iface _dest _gw _flags _ref _use _metric _mask _mtu _window _irtt; do
      if [ "$_dest" = "00000000" ] && [ "$_mask" = "00000000" ]; then
          _gai_iface="$_iface"
          break
      fi
  done < /proc/net/route

  _gai_ip="$(ifconfig "$_gai_iface" 2>/dev/null | sed -n -e 's/.*inet addr:\([0-9.]*\).*/\1/p' -e 's/^[[:space:]]*inet \([0-9.]*\).*/\1/p' | head -n 1)"

  if [ -z "$_gai_ip" ]; then
    # Global fallback: any non-loopback inet addr from any interface
    _gai_ip="$(ifconfig 2>/dev/null | sed -n -e 's/.*inet addr:\([0-9.]*\).*/\1/p' -e 's/^[[:space:]]*inet \([0-9.]*\).*/\1/p' | grep -v '^127\.' | head -n 1)"
  fi

  printf '%s\n' "${_gai_ip:-n/a}"
}

get_default_gateway()
{
  # Use /proc/net/route instead of route -n (saves 1 fork).
  # Gateway is column 3 (index 2 in hex).
  _gdg_hex_gw="00000000"
  while read -r _iface _dest _gw _flags _rest; do
      if [ "$_dest" = "00000000" ]; then
          _gdg_hex_gw="$_gw"
          break
      fi
  done < /proc/net/route

  if [ "$_gdg_hex_gw" = "00000000" ]; then
      printf 'n/a\n'
      return
  fi

  # Convert hex IP (little endian) to dotted decimal.
  # Hex: DDCBBAAA -> AAA.BBB.CCC.DDD
  # Use `cut -c` rather than bash substring expansion (${var:off:len}) — busybox
  # ash built without ASH_BASH_COMPAT dies with "Bad substitution" on that form,
  # which kills the whole calling script (mqtt-bridge.sh sources this file).
  _h_v1="$(printf '%s' "$_gdg_hex_gw" | cut -c7-8)"
  _h_v2="$(printf '%s' "$_gdg_hex_gw" | cut -c5-6)"
  _h_v3="$(printf '%s' "$_gdg_hex_gw" | cut -c3-4)"
  _h_v4="$(printf '%s' "$_gdg_hex_gw" | cut -c1-2)"
  printf '%d.%d.%d.%d\n' "0x$_h_v1" "0x$_h_v2" "0x$_h_v3" "0x$_h_v4"
}

get_wifi_signal_strength()
{
  # Extracts wireless telemetry directly from the kernel without grep/awk forks.
  _gwss_iface="wlan0"
  _gwss_qual=0
  _gwss_lvl=0

  while read -r _gif _status _link _level _noise _rest; do
      # Format: wlan0: 0000   44.  -66.  -256
      [ "${_gif%:}" = "$_gwss_iface" ] || continue
      
      # Strip trailing dots from link/level using shell parameter expansion
      _gwss_qual="${_link%.}"
      _gwss_lvl="${_level%.}"
      break
  done < /proc/net/wireless

  # Handle dBm offset (some drivers report level as unsigned level + 256)
  case "$_gwss_lvl" in
      ''|*[!0-9-]*) _gwss_lvl=0 ;;
  esac
  if [ "$_gwss_lvl" -gt 0 ] && [ "$_gwss_lvl" -le 256 ]; then
      _gwss_lvl=$((_gwss_lvl - 256))
  fi

  case "$_gwss_qual" in
      ''|*[!0-9]*) _gwss_qual=0 ;;
  esac
  printf '%s %s\n' "$_gwss_qual" "$_gwss_lvl"
}


# Replace the old value of a config_key at the cfg_path with new_value
# Don't rewrite commented lines
rewrite_config(){
  cfg_path="$1"
  cfg_key="$2"
  new_value="$3"

  # Keep key syntax strict to avoid malformed sed patterns.
  case "$cfg_key" in
    ''|*[!A-Za-z0-9_]*)
      return 1
      ;;
  esac

  if [ ! -f "$cfg_path" ]; then
    return 1
  fi

  _rc_found=0; _rc_changed=0
  while IFS= read -r _rc_line || [ -n "$_rc_line" ]; do
    # Match the same leading whitespace accepted by the replacement below.
    while :; do
      case "$_rc_line" in ' '*|"	"*) _rc_line="${_rc_line#?}" ;; *) break ;; esac
    done
    case "$_rc_line" in
      "$cfg_key"=*)
        _rc_found=1
        [ "${_rc_line#*=}" = "$new_value" ] || _rc_changed=1 ;;
    esac
  done < "$cfg_path"
  [ "$_rc_found" -eq 1 ] && [ "$_rc_changed" -eq 0 ] && return 0

  if grep -q "^[[:space:]]*${cfg_key}=" "$cfg_path"; then
    # Escape replacement-sensitive characters for sed.
    esc_value=$(printf '%s' "$new_value" | sed 's/[\\&|]/\\&/g')
    # Write to a temp file and rename so a power cut mid-write can never leave
    # a truncated config behind (FAT32 has no journal to recover from that).
    _rc_tmp="${cfg_path}.tmp.$$"
    if sed -e "/^[[:space:]]*#/! s|^[[:space:]]*${cfg_key}=.*|${cfg_key}=${esc_value}|" "$cfg_path" > "$_rc_tmp"; then
      mv "$_rc_tmp" "$cfg_path"
    else
      rm -f "$_rc_tmp" 2>/dev/null
      return 1
    fi
  else
    printf '%s=%s\n' "$cfg_key" "$new_value" >> "$cfg_path"
  fi
  # Flush FAT metadata promptly; config writes are rare so this is cheap.
  sync
}

install_config()
{
  cfg_path=$1
  if [ ! -f "$cfg_path" ]; then
    cp "$cfg_path.dist" "$cfg_path" > /dev/null 2>&1
  fi
}

# install_config_cached — use a builtin file check; no hash or per-boot marker.
# Used extensively in performance-critical CGI scripts.
install_config_cached()
{
  [ -f "$1" ] && return 0
  install_config "$1"
}


# read_config — reads a single key from an INI-style config file via the rwconf binary.
# Most scripts source config files directly; this helper is for rwconf INI-section format only.
read_config()
{
  cfg_path=/mnt/config/$1

  if [ -z "$3" ]; then
    section=" "
  else
    section=$3
  fi

  value=$(/mnt/bin/rwconf $cfg_path r "$section" $2)
  echo $value
}

# read_kv_config_value — reads a single KEY=VALUE line from a plain shell-style
# config file (an absolute path, NOT rwconf's INI format). Promoted here from
# mqtt-bridge.sh so every caller shares one implementation; do not reintroduce
# a copy in mqtt-bridge.sh.
read_kv_config_value()
{
  conf_path="$1"
  conf_key="$2"
  conf_default="$3"
  conf_value="$conf_default"

  if [ -r "$conf_path" ]; then
    conf_value="$(awk -F= -v key="$conf_key" '
      $0 !~ /^[[:space:]]*#/ && $1 == key {print $2; exit}
    ' "$conf_path" 2>/dev/null)"
  fi
  [ -n "$conf_value" ] || conf_value="$conf_default"
  printf '%s' "$conf_value"
}

publish_mqtt_event() {
  payload="$1"
  if [ -x /mnt/scripts/mqtt-bridge.sh ] && [ -n "$payload" ]; then
    /mnt/scripts/mqtt-bridge.sh publish event "$payload" 0 >/dev/null 2>&1 || true
  fi
}

# Control the led
led(){
  case "$1" in
  on)
    echo 1 > /sys/class/leds/$2/brightness
    ;;
  off)
    echo 0 > /sys/class/leds/$2/brightness
    ;;
  status)
    status=$(cat /sys/class/leds/$2/brightness)
    case $status in
      1)
        echo "ON"
        ;;
      0)
        echo "OFF"
      ;;
    esac
  esac
}

# Control the front LED (hardware node is still `blue_led`)
front_led(){
  led "$1" blue_led
}

# Control the red led
red_led(){
  led "$1" red_led
}

# Control the infrared led
ir_led(){
  case "$1" in
  on)
    /mnt/bin/setconf -k g -v 1
    ;;
  off)
    /mnt/bin/setconf -k g -v 0
    ;;
  status)
    status=$(cat /sys/user-gpio/ir-led)
    case $status in
      0)
        echo "OFF"
        ;;
      1)
        echo "ON"
      ;;
    esac
  esac
}

# Control the infrared filter
ir_cut(){
  case "$1" in
  on)
    /mnt/bin/setconf -k e -v 1
    ;;
  off)
    /mnt/bin/setconf -k e -v 0
    ;;
  status)
    status=$(cat /var/run/ircut)
    case $status in
      1)
        echo "ON"
        ;;
      0)
        echo "OFF"
      ;;
    esac
  esac
}


# _http_server_lighttpd — start lighttpd the way 02_system-webserver does.
# lighttpd needs /mnt/lib (libpcre2, libssl): started from a CGI or a service
# script without LD_LIBRARY_PATH it exits at once ("can't load library
# 'libpcre2-8.so.0'"), so a web-server restart used to leave the camera with
# no web UI until the next reboot. WEB_MODE=http uses the plain-HTTP config.
_http_server_lighttpd(){
  _hs_conf=/mnt/config/lighttpd.conf
  [ "$WEB_MODE" = "http" ] && _hs_conf=/mnt/config/lighttpd.http.conf
  # Firmware from flash: lighttpd has mbedTLS instead of OpenSSL, no PCRE and
  # no openssl tool to make a certificate. Only the flash templates match that
  # binary (a lighttpd.conf brought from an SD card may not even parse), and
  # HTTPS needs an existing certificate it can load (ECDSA). If lighttpd does
  # not come up with TLS, the plain HTTP template is used instead: a camera
  # without its web interface can only be fixed with a screwdriver.
  if [ "$(cat /tmp/tc100-storage 2>/dev/null)" = flash ]; then
    _hs_http=/mnt/config/lighttpd.flash-http.conf.dist
    if [ "$_hs_conf" = /mnt/config/lighttpd.conf ] && [ -s /mnt/config/lighttpd.pem ]; then
      LD_LIBRARY_PATH="/mnt/lib:/lib:/usr/lib" /mnt/bin/lighttpd -f /mnt/config/lighttpd.flash.conf.dist
      _hs_i=0
      while [ $_hs_i -lt 5 ]; do
        sleep 1; _hs_i=$((_hs_i + 1))
        port_listening 443 && return 0
      done
      logger -t tc100-event -p user.err "web server: HTTPS did not start (certificate?), falling back to HTTP" 2>/dev/null
      killall lighttpd 2>/dev/null; sleep 1
    fi
    LD_LIBRARY_PATH="/mnt/lib:/lib:/usr/lib" /mnt/bin/lighttpd -f "$_hs_http"
    return
  fi
  install_config "$_hs_conf"
  LD_LIBRARY_PATH="/mnt/lib:/lib:/usr/lib" /mnt/bin/lighttpd -f "$_hs_conf"
}

# Control the http server
http_server(){
  WEB_MODE="full"
  ULTRALITE_HTTP_PORT="80"
  if [ -f /mnt/config/boot.conf ]; then
    # shellcheck disable=SC1090
    . /mnt/config/boot.conf
  fi
  # lighttpd refuses to start if deflate.cache-dir is missing, and /tmp is
  # recreated on every boot.
  mkdir -p /tmp/lighttpd-deflate 2>/dev/null
  case "$1" in
  on)
    if [ "$WEB_MODE" = "ultra-lite" ] || [ "$WEB_MODE" = "ultralite" ]; then
      run_busybox httpd -p "${ULTRALITE_HTTP_PORT:-80}" -h /mnt/www
    else
      _http_server_lighttpd
    fi
    ;;
  off)
    killall lighttpd
    killall httpd
    ;;
  restart)
    killall lighttpd
    killall httpd
    if [ "$WEB_MODE" = "ultra-lite" ] || [ "$WEB_MODE" = "ultralite" ]; then
      run_busybox httpd -p "${ULTRALITE_HTTP_PORT:-80}" -h /mnt/www
    else
      _http_server_lighttpd
    fi
    ;;
  status)
    if pgrep lighttpd >/dev/null 2>&1 || pgrep httpd >/dev/null 2>&1
      then
        echo "ON"
    else
        echo "OFF"
    fi
    ;;
  esac
}

# Set a new http password
http_password(){
  user="root" # by default root until we have proper user management
  realm="all" # realm is defined in the lightppd.conf
  pass=$1
  hash=$(echo -n "$user:$realm:$pass" | md5sum | cut -b -32)
  echo "$user:$realm:$hash" > /mnt/config/lighttpd.user
}

# Control the RTSP h264 server
rtsp_h26x_server(){
  case "$1" in
  on)
    /mnt/controlscripts/rtsp-h26x start
    ;;
  off)
    /mnt/controlscripts/rtsp-h26x stop
    ;;
  status)
    status=$(/mnt/controlscripts/rtsp-h26x status 2>/dev/null)
    if [ -n "$status" ]
      then
        echo "ON"
    else
        echo "OFF"
    fi
    ;;
  esac
}

activate_motion_recording()
{
  # Set recording flag (single write is atomic for small data; native readers do not use flock)
  printf '1\n' > /tmp/rec_control
}

deactivate_motion_recording()
{
  # Reset recording flag (single write is atomic for small data; native readers do not use flock)
  printf '0\n' > /tmp/rec_control
}


# Control the motion detection function
motion_detection(){
  case "$1" in
  on)
    deactivate_motion_recording
    /mnt/bin/setconf -k p -v 1
    rewrite_config /mnt/config/rtspserver.conf mdenabled 1
    ;;
  off)
    /mnt/bin/setconf -k p -v -0
    rewrite_config /mnt/config/rtspserver.conf mdenabled 0
    deactivate_motion_recording
    ;;
  status)
    status=$(/mnt/bin/setconf -g p 2>/dev/null)
    case $status in
      0)
        echo "OFF"
        ;;
      *)
        echo "ON"
        ;;
    esac
  esac
}

# Control the motion detection mail function
motion_send_mail(){
  case "$1" in
  on)
    rewrite_config /mnt/config/motion.conf sendemail "true"
    ;;
  off)
    rewrite_config /mnt/config/motion.conf sendemail "false"
    ;;
  status)
    status=`awk '/sendemail/' /mnt/config/motion.conf |cut -f2 -d \=`
    case $status in
      false)
        echo "OFF"
        ;;
      true)
        echo "ON"
        ;;
    esac
  esac
}

black_white()
{
  case "$1" in
  on)
    /mnt/bin/setconf -k v -v 0
    ;;
  off)
    /mnt/bin/setconf -k v -v 1
    ;;
  status)
    status=$(cat /var/run/vday)
    case $status in
      0)
        echo "ON"
        ;;
      1)
        echo "OFF"
      ;;
    esac
  esac
}

# Control the night mode
night_mode(){
  case "$1" in
    on)
      /mnt/controlscripts/night-mode start
      ;;
    off)
      /mnt/controlscripts/night-mode stop
      ;;
    status)
      status=$(/mnt/controlscripts/night-mode status 2>/dev/null)
      if [ -n "$status" ]
      then
          echo "ON"
      else
          echo "OFF"
      fi
      ;;
    esac
}

# Control the auto night mode
auto_night_mode(){
  case "$1" in
    on)
      /mnt/controlscripts/auto-night-detection start
      ;;
    off)
      /mnt/controlscripts/auto-night-detection stop
      ;;
    status)
      status=$(/mnt/controlscripts/auto-night-detection status 2>/dev/null)
      if [ -n "$status" ]
      then
          echo "ON"
      else
          echo "OFF"
      fi
      ;;
    esac
}


# port_listening PORT -> 0 if a TCP socket is in LISTEN state on PORT
# (/proc/net/tcp, no fork). A pid that is alive is not enough: a recycled PID
# or a half-dead tcpsvd showed services as running with their port closed.
port_listening() {
  case "$1" in ''|*[!0-9]*) return 1 ;; esac
  _pl_hex="$(printf '%04X' "$1")"
  for _pl_f in /proc/net/tcp /proc/net/tcp6; do
    [ -r "$_pl_f" ] || continue
    while read -r _pl_sl _pl_local _pl_rem _pl_st _pl_rest; do
      [ "$_pl_st" = 0A ] || continue
      case "$_pl_local" in *":$_pl_hex") return 0 ;; esac
    done < "$_pl_f"
  done
  return 1
}

# Reboot the System
reboot_system() {
  /bin/sh /mnt/scripts/reboot-tracker.sh intent "${1:-reboot_system}" >/dev/null 2>&1
  /sbin/reboot
}

get_current_cpu_usage()
{
    cpu_state_file="${CPU_USAGE_STATE_FILE:-/tmp/cpu_usage_common.state}"
    cpu_min_delta_ticks="${CPU_USAGE_MIN_DELTA_TICKS:-20}"
    case "$cpu_min_delta_ticks" in
        ''|*[!0-9]*) cpu_min_delta_ticks=20 ;;
    esac
    [ "$cpu_min_delta_ticks" -lt 1 ] && cpu_min_delta_ticks=1

    cpu_active_prev=0
    cpu_total_prev=0
    cpu_util_prev=0
    if [ -f "$cpu_state_file" ]; then
        read -r cpu_active_prev cpu_total_prev cpu_util_prev < "$cpu_state_file"
        case "$cpu_active_prev" in ''|*[!0-9]*) cpu_active_prev=0 ;; esac
        case "$cpu_total_prev" in ''|*[!0-9]*) cpu_total_prev=0 ;; esac
        case "$cpu_util_prev" in ''|*[!0-9]*) cpu_util_prev=0 ;; esac
    fi

    read -r _ user nice system idle iowait irq softirq steal _ _ < /proc/stat

    cpu_active_cur=$((user + nice + system + irq + softirq + steal))
    cpu_total_cur=$((cpu_active_cur + idle + iowait))

    delta_total=$((cpu_total_cur - cpu_total_prev))
    delta_active=$((cpu_active_cur - cpu_active_prev))

    if [ "$cpu_total_prev" -le 0 ] || [ "$delta_total" -lt 0 ]; then
        printf '%s %s %s\n' "$cpu_active_cur" "$cpu_total_cur" 0 > "$cpu_state_file"
        echo "0"
        return
    fi

    if [ "$delta_total" -lt "$cpu_min_delta_ticks" ]; then
        # Reuse previous stable value when calls are too close together.
        echo "$cpu_util_prev"
        return
    fi

    if [ "$delta_active" -lt 0 ]; then
        delta_active=0
    fi
    cpu_util=$((100 * delta_active / delta_total))
    if [ "$cpu_util" -lt 0 ]; then
        cpu_util=0
    elif [ "$cpu_util" -gt 100 ]; then
        cpu_util=100
    fi

    printf '%s %s %s\n' "$cpu_active_cur" "$cpu_total_cur" "$cpu_util" > "$cpu_state_file"
    echo "$cpu_util"
}

get_current_memory_usage()
{
    # get used memory without buffers/cache by reading /proc/meminfo directly (saves 2 process forks)
    total=0; free=0; buffers=0; cached=0; srec=0
    while IFS=' :' read -r key val _; do
        case "$key" in
            MemTotal) total=$val ;;
            MemFree) free=$val ;;
            Buffers) buffers=$val ;;
            Cached) cached=$val ;;
            SReclaimable) srec=$val ;;
        esac
    done < /proc/meminfo
    # Return used memory in KB (mimicking old logic: total - free - buffers - cached)
    echo $((total - free - buffers - cached - srec))
}

get_mem_available_kb()
{
    # Return available memory in KB by reading /proc/meminfo directly.
    # Uses MemAvailable if present, otherwise fallbacks to MemFree + Buffers + Cached + SReclaimable.
    total=0; free=0; buffers=0; cached=0; srec=0; shmem=0; avail=0
    while IFS=' :' read -r key val _; do
        case "$key" in
            MemTotal) total=$val ;;
            MemAvailable) avail=$val ;;
            MemFree) free=$val ;;
            Buffers) buffers=$val ;;
            Cached) cached=$val ;;
            SReclaimable) srec=$val ;;
            Shmem) shmem=$val ;;
        esac
    done < /proc/meminfo

    if [ "$avail" -gt 0 ]; then
        echo "$avail"
    else
        echo $((free + buffers + cached + srec - shmem))
    fi
}

get_all_memory()
{
    # MemTotal is always the first line of /proc/meminfo — no loop needed.
    read -r _ val _ < /proc/meminfo
    printf '%s\n' "$val"
}

restart_service_if_need()
{
    service_path="$1"
    service_status="$("$service_path" status 2>/dev/null)"
    if [ -n "$service_status" ]; then
        "$service_path" stop > /dev/null 2>&1
        "$service_path" start > /dev/null 2>&1
    fi
}

start_service_if_need()
{
    service_path="$1"
    status=$("$service_path" status 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$status" ]; then
        "$service_path" start > /dev/null 2>&1
    fi
}

all_password()
{
    DEFAULT_LOGIN="root"
    printf '%s\n%s\n' "$1" "$1" | passwd > /dev/null 2>&1
    http_password $1
    rewrite_config /mnt/config/rtspserver.conf USERNAME "$DEFAULT_LOGIN"
    rewrite_config /mnt/config/rtspserver.conf USERPASSWORD "$1"
    echo "$1" > /mnt/config/user.pwd
}

# Input arg - file with PID
killpid()
{
  pid="$(cat "$1" 2>/dev/null)"
  if [ "$pid" ]; then
    kill "$pid"
    rm "$1" 1> /dev/null 2>&1
  fi
}

# killpid_graceful — send SIGTERM, wait up to N seconds, then SIGKILL if still alive.
# Usage: killpid_graceful <pidfile> [timeout_seconds]
killpid_graceful()
{
  _kpg_file="$1"
  _kpg_timeout="${2:-5}"
  _kpg_pid="$(cat "$_kpg_file" 2>/dev/null)"
  if [ -z "$_kpg_pid" ]; then
    rm -f "$_kpg_file" 2>/dev/null || true
    return 0
  fi
  # Send SIGTERM
  kill "$_kpg_pid" 2>/dev/null || true
  # Wait up to timeout for process to exit
  _kpg_waited=0
  while [ "$_kpg_waited" -lt "$_kpg_timeout" ]; do
    kill -0 "$_kpg_pid" 2>/dev/null || break
    sleep 1
    _kpg_waited=$((_kpg_waited + 1))
  done
  # Force kill if still running
  if kill -0 "$_kpg_pid" 2>/dev/null; then
    kill -9 "$_kpg_pid" 2>/dev/null || true
  fi
  rm -f "$_kpg_file" 2>/dev/null || true
}

# Input arg - file with PID
checkpid()
{
  pid="$(cat "$1" 2>/dev/null)"
  if ([ "$pid" ] && kill -0 "$pid" >/dev/null); then
    return 0
  else
    return 1
  fi
}

led_blink()
{
    blink_count=$1
    led_type=$2
    off_led_type=$3
    
    led_status=$(led status $led_type)
    off_led_status=$(led status $off_led_type)

    led off $off_led_type

    i=1
    while [ "$i" -le $blink_count ]; do
       led on $led_type
       sleep 0.25
       led off $led_type
       sleep 0.25
       i=$(( i + 1 ))
    done

    if [ "$led_status" = "ON" ]; then
      led on "$led_type"
    fi

    if [ "$off_led_status" = "ON" ]; then
      led on "$off_led_type"
    fi
}

front_led_blink()
{
  led_blink $1 blue_led red_led
}

red_led_blink()
{
  led_blink $1 red_led blue_led
}

run_strings() {
  target="$1"
  # Device files (e.g. /dev/mtd*) can block indefinitely — apply a timeout.
  case "$target" in
    /dev/*)
      if command -v strings >/dev/null 2>&1; then
        run_with_timeout 8 strings "$target" 2>/dev/null
        return
      fi
      if [ -x /mnt/bin/busybox ]; then
        run_with_timeout 8 /mnt/bin/busybox strings "$target" 2>/dev/null
        return
      fi
      if [ -x /bin/busybox ]; then
        run_with_timeout 8 /bin/busybox strings "$target" 2>/dev/null
      fi
      return
      ;;
  esac
  if command -v strings >/dev/null 2>&1; then
    strings "$target" 2>/dev/null
    return
  fi
  if [ -x /mnt/bin/busybox ]; then
    /mnt/bin/busybox strings "$target" 2>/dev/null
    return
  fi
  if [ -x /bin/busybox ]; then
    /bin/busybox strings "$target" 2>/dev/null
  fi
}

binary_version() {
  name="$1"
  path="/mnt/bin/$name"

  if [ ! -e "$path" ]; then
    echo "missing"
    return
  fi

  case "$name" in
    busybox)
      v="$("$path" 2>/dev/null | head -n 1)"
      [ -z "$v" ] && v="$(run_strings "$path" | grep -m1 'BusyBox v')"
      ;;
    curl)
      v="$(run_strings "$path" | grep -m1 -E '^curl [0-9]')"
      ;;
    jq)
      v="$("$path" --version 2>/dev/null | head -n 1)"
      ;;
    lighttpd)
      v="$(run_strings "$path" | grep -m1 -E 'lighttpd/[0-9]')"
      ;;
    openssl)
      v="$(run_strings "$path" | grep -m1 -E 'OpenSSL [0-9]')"
      ;;
    ffmpeg-min-recorder)
      v="$(run_strings "$path" | grep -m1 -E 'version [0-9]+\.[0-9]+\.[0-9]+')"
      ;;
    monvifd)
      v="$(run_strings "$path" | grep -m1 'Micro ONVIF discovery service')"
      ;;
    rwconf)
      v="$(run_strings "$path" | grep -m1 'Read/Write ini-file utility')"
      ;;
    min-recorder-list)
      v="$(run_strings "$path" | grep -m1 'Get list of video archive records')"
      ;;
    telegram)
      v="shell wrapper"
      ;;
    *)
      v=""
      ;;
  esac
  # strings(1) returns printf formats verbatim ("curl 8.1.2 (...) %s",
  # "%s version 2.1.3"): drop the placeholders.
  case "$v" in *%s*) v="$(printf '%s' "$v" | sed -e 's/ *%s *\([^ ]\)/ \1/g' -e 's/ *%s *$//' -e 's/^ *//')" ;; esac

  if [ -z "$v" ]; then
    if command -v cksum >/dev/null 2>&1; then
      v="checksum $(cksum "$path" 2>/dev/null | awk '{print $1}')"
    else
      v="version n/a"
    fi
  fi
  echo "$v"
}

build_binary_versions_block() {
  for n in busybox curl ffmpeg-min-recorder getflag getimage jq lighttpd min-recorder-list monvifd openssl rwconf setconf telegram v4l2rtspserver; do
    ver="$(binary_version "$n")"
    printf '%-20s %s\n' "$n" "$ver"
  done
}

build_devinfo_cache() {
  build_binary_versions_block > /tmp/devinfo_binary_versions.txt
  bl="$(run_strings /dev/mtd0 | grep -m1 'U-Boot 2' 2>/dev/null)"
  echo "${bl:-n/a}" > /tmp/devinfo_bootloader.txt
  # Write a timestamp so callers can check cache age.
  _cf_read_ts
  printf '%s\n' "$_CF_TS" > /tmp/devinfo_cache.ts 2>/dev/null || true
}

# devinfo_cache_fresh — returns 0 if cache files exist and are < TTL_SECONDS old.
# TTL defaults to 3600s (1h); binary versions on embedded devices rarely change.
devinfo_cache_fresh() {
  _dcf_ttl="${1:-3600}"
  [ -f /tmp/devinfo_binary_versions.txt ] || return 1
  [ -f /tmp/devinfo_cache.ts ] || return 1
  _dcf_ts=0; read -r _dcf_ts < /tmp/devinfo_cache.ts 2>/dev/null || true
  case "$_dcf_ts" in ''|*[!0-9]*) return 1 ;; esac
  _dcf_btime=0
  while read -r _k _v _; do [ "$_k" = "btime" ] && _dcf_btime="$_v" && break; done < /proc/stat
  read -r _dcf_up _ < /proc/uptime 2>/dev/null || true
  _dcf_now=$((_dcf_btime + ${_dcf_up%.*}))
  [ "$((_dcf_now - _dcf_ts))" -lt "$_dcf_ttl" ]
}

# ---------------------------------------------------------------------------
# System log. The vendor rc.local starts "syslogd -O /var/log/messages -s 200
# -b 3" (up to 800 KB of RAM) logging every priority; three quarters of it was
# a USB host controller kern.info line every ~15 s and crond's "USER root pid
# ... cmd" for each job. Keep notice and above, plus logins (auth.info), in
# RAM only; tc100_log_event / reboot-tracker.sh copy the few critical lines to
# the SD card. A remote host, when set, gets the same filtered stream.
# BusyBox writes a message no rule matched to the default file when its
# priority passes -l, hence "-l 6" as well (notice and above).
#   syslogd_start [HOST:PORT]   -> prints the new syslogd PID
# ---------------------------------------------------------------------------
SYSLOG_CONF_RUNTIME="/tmp/syslog.conf"
syslogd_start() {
  _sl_remote="$1"
  printf '%s\n' '# Generated by syslogd_start (scripts/common_functions.sh). RAM only.' \
    '*.notice;auth.*;authpriv.*	/var/log/messages' > "$SYSLOG_CONF_RUNTIME" 2>/dev/null || return 1
  # Stop every syslogd, whatever its argv[0] ("syslogd" for the vendor one,
  # "/bin/busybox syslogd" for one started by an older version of this code:
  # killall/pidof only match the first).
  _sl_list() { ps 2>/dev/null | awk '/[s]yslogd( |$)/ { print $1 }'; }
  # shellcheck disable=SC2046
  kill $(_sl_list) >/dev/null 2>&1
  _sl_i=0
  while [ -n "$(_sl_list)" ] && [ "$_sl_i" -lt 10 ]; do sleep 1; _sl_i=$((_sl_i + 1)); done
  # Run as "syslogd" so ps, pidof and killall name it properly.
  _sl_bin=/tmp/bin/syslogd
  mkdir -p /tmp/bin 2>/dev/null
  [ -x "$_sl_bin" ] || ln -sf /bin/busybox "$_sl_bin" 2>/dev/null || _sl_bin="/bin/busybox syslogd"
  # Remote host: busybox "syslogd -R" sends EVERY message (its -l and -f
  # filters only apply to the local file), so the remote server also got the
  # kernel/daemon info and debug lines. tc100-logfwd follows the filtered
  # local file instead and limits repeats and bursts (src/logfwd). Without
  # the binary (older /usr), -R as before.
  _sl_fwd=""
  for _f in /tmp/tc100code/bin/tc100-logfwd /mnt/bin/tc100-logfwd; do
    [ -x "$_f" ] && { _sl_fwd="$_f"; break; }
  done
  _fwd_list() { ps 2>/dev/null | awk '/[t]c100-logfwd( |$)/ { print $1 }'; }
  # shellcheck disable=SC2046
  kill $(_fwd_list) >/dev/null 2>&1
  if [ -n "$_sl_remote" ] && [ -z "$_sl_fwd" ]; then
    ( trap '' HUP; exec $_sl_bin -n -D -f "$SYSLOG_CONF_RUNTIME" -l 6 -s 128 -b 1 -R "$_sl_remote" -L ) </dev/null >/dev/null 2>&1 &
  else
    ( trap '' HUP; exec $_sl_bin -n -D -f "$SYSLOG_CONF_RUNTIME" -l 6 -s 128 -b 1 ) </dev/null >/dev/null 2>&1 &
  fi
  _sl_pid=$!
  if [ -n "$_sl_remote" ] && [ -n "$_sl_fwd" ]; then
    # -b: from the start of the log, so the boot messages also reach the
    # remote host (the file is new at each boot: tmpfs). Later restarts
    # would resend it: only when the log is young (first 10 min).
    _fwd_b=""; [ "$(cut -d. -f1 /proc/uptime 2>/dev/null)" -lt 600 ] 2>/dev/null && _fwd_b=-b
    ( trap '' HUP; exec "$_sl_fwd" -r "$_sl_remote" -f /var/log/messages $_fwd_b ) </dev/null >/dev/null 2>&1 &
    _sl_pid=$!
  fi
  # klogd stamps the kernel lines itself: the vendor one starts before the
  # time zone is known, so kernel lines were hours apart from the others.
  # Restart it with the current TZ (only when one is set).
  if [ -n "${TZ:-}" ]; then
    _kl_list() { ps 2>/dev/null | awk '/[k]logd( |$)/ { print $1 }'; }
    # shellcheck disable=SC2046
    kill $(_kl_list) >/dev/null 2>&1
    ( trap '' HUP; exec /bin/busybox klogd -n ) </dev/null >/dev/null 2>&1 &
  fi
  echo "$_sl_pid"
}

# Critical event worth keeping across reboots: goes to syslog with a tag that
# reboot-tracker.sh copies to /mnt/log/important.log (every 5 min, only when
# something new matched). Use for failures, not for routine activity.
tc100_log_event() {
  logger -t tc100-event -p user.err "$*" 2>/dev/null || true
}
