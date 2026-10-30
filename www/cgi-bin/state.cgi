#!/bin/sh

# A very light-weight interface just for responsive ui to get states

. /mnt/www/cgi-bin/func.cgi
. /mnt/www/cgi-bin/statelib.cgi

# Set content type based on requested format
if wants_json_response; then
  echo "Content-type: application/json"
else
  echo "Content-type: text/plain"
fi
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""


_format_iso8601_utc() {
  _ts="$1"
  _sec_in_day=$((_ts % 86400))
  _days=$((_ts / 86400))
  _hr=$((_sec_in_day / 3600))
  _min=$(((_sec_in_day % 3600) / 60))
  _sec=$((_sec_in_day % 60))
  _q=$((_days / 36524))
  _r=$((_days % 36524))
  _y=$((1970 + _q * 100))
  _q=$((_r / 1461))
  _r=$((_r % 1461))
  _y=$((_y + _q * 4))
  if [ "$_q" -lt 25 ]; then
    _q=$((_r / 365))
    [ "$_q" -gt 3 ] && _q=3
    _r=$((_r - _q * 365))
    _y=$((_y + _q))
  else
    _r=$((_r - 1461))
    _y=$((_y + 4))
  fi
  if [ $(((_y % 4 == 0 && _y % 100 != 0) || _y % 400 == 0)) -eq 1 ]; then
    _month_days="31 29 31 30 31 30 31 31 30 31 30 31"
  else
    _month_days="31 28 31 30 31 30 31 31 30 31 30 31"
  fi
  _m=0
  for _days_in_m in $_month_days; do
    _m=$((_m + 1))
    if [ "$_r" -lt "$_days_in_m" ]; then
      break
    fi
    _r=$((_r - _days_in_m))
  done
  _d=$((_r + 1))
  printf '%04d-%02d-%02dT%02d:%02d:%02dZ' "$_y" "$_m" "$_d" "$_hr" "$_min" "$_sec"
}







# Load configs into shell variables in one pass per file to save IO/forks.
load_conf_file() {
  _lcf_path="$1"
  [ -f "$_lcf_path" ] || return 1
  _lcf_section=""
  while IFS='=' read -r _lcf_k _lcf_v || [ -n "$_lcf_k" ]; do
    case "$_lcf_k" in
      '['*']')
        _lcf_section="${_lcf_k#?}"
        _lcf_section="${_lcf_section%?}"
        case "$_lcf_section" in ''|*[!A-Za-z0-9_]*) _lcf_section="!" ;; esac
        continue ;;
      ''|'#'*|';'*|*[!A-Za-z0-9_]*) continue ;;
    esac
    [ "$_lcf_section" != "!" ] || continue
    if [ -n "$_lcf_section" ]; then
      _lcf_key="${_lcf_section}_${_lcf_k}"
    else
      _lcf_key="$_lcf_k"
    fi
    # Values remain data. Only validated keys/section names enter the eval syntax.
    eval "C_${_lcf_key}=\"\$_lcf_v\""
  done < "$_lcf_path"
}

# Read one-line configuration files such as hostname/timezone/NTP without
# treating their value as a key=value assignment.
read_single_config() {
  _rsc_file="$1"; _rsc_default="$2"; _rsc_value=""
  if [ -r "$_rsc_file" ]; then
    while IFS= read -r _rsc_line || [ -n "$_rsc_line" ]; do
      case "$_rsc_line" in ''|'#'*) continue ;; esac
      _rsc_value="$_rsc_line"
      break
    done < "$_rsc_file"
  fi
  [ -n "$_rsc_value" ] || _rsc_value="$_rsc_default"
  printf '%s\n' "$_rsc_value"
}

# Helper to get the loaded value or default
get_cfg() {
  eval "_gc_val=\"\$C_$1\""
  if [ -z "$_gc_val" ]; then
    echo "$2"
  else
    echo "$_gc_val"
  fi
}

normalize_web_mode_value() {
  case "$1" in
    ultra-lite|ultralite)
      echo "ultra-lite"
      ;;
    full|http|off)
      echo "$1"
      ;;
    *)
      echo "full"
      ;;
  esac
}

detect_primary_ip() {
  primary_ip=""
  if [ -r /tmp/camera_ip.txt ]; then
    read -r primary_ip < /tmp/camera_ip.txt
  fi
  if [ -z "$primary_ip" ]; then
    primary_ip="$(ifconfig 2>/dev/null | awk '
      /inet addr:[0-9]/ {
        split($2, a, ":")
        if (a[2] !~ /^127\./) {
          print a[2]
          exit
        }
      }
      /inet [0-9]/ {
        if ($2 !~ /^127\./) {
          print $2
          exit
        }
      }
    ')"
  fi
  [ -n "$primary_ip" ] || primary_ip="CAMERA-IP"
}

truthy_flag() {
  case "$1" in
    1|true|on|yes|enabled)
      echo "1"
      ;;
    *)
      echo "0"
      ;;
  esac
}

userinfo_safe() {
  case "$1" in
    ''|*[!A-Za-z0-9._~-]*)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

prepare_rtsp_auth_template() {
  url_user="$1"
  url_password="$2"
  rtsp_url_auth_embedded=0
  rtsp_url_auth_warning=""
  rtsp_url_auth_prefix=""

  if [ -n "$url_user" ] || [ -n "$url_password" ]; then
    if userinfo_safe "$url_user" && userinfo_safe "$url_password"; then
      rtsp_url_auth_prefix="${url_user}:${url_password}@"
      rtsp_url_auth_embedded=1
    else
      rtsp_url_auth_prefix="USERNAME:PASSWORD@"
      rtsp_url_auth_warning="RTSP credentials contain URL-sensitive characters; replace USERNAME/PASSWORD or percent-encode them in client configs."
    fi
  fi
}

build_rtsp_url_template() {
  url_host="$1"
  url_port="$2"
  url_path="$3"
  printf 'rtsp://%s%s:%s/%s' "$rtsp_url_auth_prefix" "$url_host" "$url_port" "$url_path"
}

build_web_base_url() {
  web_mode_value="$1"
  web_host="$2"
  ultralite_port_value="$3"

  web_enabled=1
  web_scheme="https"
  web_port=443
  web_base_url=""

  case "$web_mode_value" in
    full)
      web_scheme="https"
      web_port=443
      ;;
    http)
      web_scheme="http"
      web_port=80
      ;;
    ultra-lite)
      web_scheme="http"
      web_port="$ultralite_port_value"
      ;;
    off)
      web_enabled=0
      web_scheme=""
      web_port=0
      ;;
    *)
      web_scheme="https"
      web_port=443
      ;;
  esac

  if [ "$web_enabled" = "1" ]; then
    case "${web_scheme}:${web_port}" in
      https:443|http:80)
        web_base_url="${web_scheme}://${web_host}"
        ;;
      *)
        web_base_url="${web_scheme}://${web_host}:${web_port}"
        ;;
    esac
  fi
}

rtsp_describe_local_ok() {
  describe_path="$1"
  describe_port="$2"
  describe_timeout="$5"

  # The bundled curl cannot load libcurl from the CGI environment and its RTSP
  # build sends OPTIONS even when asked for DESCRIBE. Probe the endpoint with a
  # tiny raw request instead. A 401 challenge is a valid response when Digest
  # authentication is enabled; an unauthenticated endpoint must return SDP.
  describe_uri="rtsp://127.0.0.1:${describe_port}/${describe_path}"
  describe_reply="$(printf 'DESCRIBE %s RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\n\r\n' "$describe_uri" \
    | nc -w "$describe_timeout" 127.0.0.1 "$describe_port" 2>/dev/null)" || return 1
  case "$describe_reply" in
    *'RTSP/1.0 401 Unauthorized'*) return 0 ;;
    *'RTSP/1.0 200 OK'*'m=video'*) return 0 ;;
    *) return 1 ;;
  esac
}

slugify_value() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g; s/__*/_/g; s/^_//; s/_$//'
}


sanitize_int() {
  raw="$1"
  fallback="$2"
  case "$raw" in
    ''|*[!0-9]*)
      echo "$fallback"
      ;;
    *)
      echo "$raw"
      ;;
  esac
}

codec_name() {
  case "$1" in
    2)
      echo "H265"
      ;;
    0)
      echo "H264"
      ;;
    *)
      echo "unknown"
      ;;
  esac
}

# Dashboard cards: ~150 forks when built from scratch (df, wpa_cli|awk, per-partition reads, json_escape), and the page
# asks every minute. The finished JSON is kept in /tmp (line 1 = uptime seconds when built, line 2 = hostname, line 3 =
# the JSON) for DASHINFO_CACHE_TTL_SECONDS, and dropped at once when a file it is made of is newer than the cache
# (stream settings, host name, Wi-Fi, firmware version) or when the host name changed (read from /proc, no fork).
DASHINFO_CACHE_FILE="/tmp/state_dashinfo.cache"
DASHINFO_CACHE_TTL_SECONDS=300

dashinfo_compute() {
    load_conf_file /mnt/config/rtspserver.conf
    read_rtsp_stream_summary
    detect_primary_ip
    get_sd_usage
    _di_host=""; read -r _di_host < /proc/sys/kernel/hostname 2>/dev/null
    _di_kern=""; read -r _di_kern < /proc/sys/kernel/osrelease 2>/dev/null
    _di_mac=""; read -r _di_mac 2>/dev/null < /sys/class/net/wlan0/address
    _di_ver=""; read -r _di_ver < /mnt/VERSION 2>/dev/null
    # Flash and card usage. In flash mode the card (if any) is on /mnt/sd.
    _di_sdmp=/mnt; [ "${storage_json:-sd}" = flash ] && _di_sdmp=/mnt/sd
    _di_jt=0; _di_ju=0; _di_st=0; _di_su=0
    while read -r _fs _t _u _a _p _mp _rest; do
      case "$_t$_u" in ''|*[!0-9]*) continue ;; esac
      case "$_mp" in
        /etc/jffs2) _di_jt=$_t; _di_ju=$_u ;;
        "$_di_sdmp")
          if [ "$_mp" = "/mnt/sd" ] && [ "$_fs" = "tmpfs" ]; then continue; fi
          _di_st=$_t; _di_su=$_u ;;
      esac
    done <<EOF_DF
$(df -k 2>/dev/null)
EOF_DF
    # Linux 6.6 flash mode uses cfga/cfgb (36 KB each) instead of /etc/jffs2
    if [ "$_di_jt" -eq 0 ] && [ -f /tmp/flashmode ]; then
      for _dm in /sys/class/mtd/mtd[0-9]*; do
        case "$_dm" in *ro) continue ;; esac
        _nm=""; read -r _nm < "$_dm/name" 2>/dev/null
        [ "$_nm" = "cfga" ] || continue
        _csz=""; read -r _csz < "$_dm/size" 2>/dev/null
        case "$_csz" in [0-9]*) _di_jt=$(( _csz / 1024 )) ;; esac
        _chdr="$(dd if=/dev/${_dm##*/}ro bs=1 count=64 2>/dev/null | tr '\000\377' '  ')"
        _clen="$(printf '%s' "$_chdr" | awk '$1=="TC1CFG"{print int(($3+64+1023)/1024); exit}')"
        case "$_clen" in [0-9]*) _di_ju="$_clen" ;; esac
        break
      done
    fi
    # Detailed SPI flash breakdown for the Dashboard Storage card (in KB)
    _di_flash_json="null"
    if [ -d /sys/class/mtd/mtd0 ]; then
      _fp_list=""
      _ftot_kb=0
      _fused_kb=0
      for _dm in /sys/class/mtd/mtd[0-9]*; do
        case "$_dm" in *ro) continue ;; esac
        [ -r "$_dm/size" ] || continue
        _m="${_dm##*/}"
        _nm=""; read -r _nm < "$_dm/name" 2>/dev/null
        _sz=""; read -r _sz < "$_dm/size" 2>/dev/null
        case "$_sz" in ''|*[!0-9]*) continue ;; esac
        _used="$_sz"
        case "$_nm" in
          kernel)
            _khex="$(dd if=/dev/${_m}ro bs=1 skip=12 count=4 2>/dev/null | od -An -tx1 | tr -d ' \n')"
            case "$_khex" in [0-9a-fA-F][0-9a-fA-F]*) _ksz=$(( 0x$_khex + 64 )); [ "$_ksz" -gt 64 ] && [ "$_ksz" -le "$_sz" ] && _used="$_ksz" ;; esac
            ;;
          initrd)
            _icmd="$(sed -n 's/.*initrd=0x[0-9a-fA-F]*,\([0-9][0-9]*\).*/\1/p' /proc/cmdline 2>/dev/null)"
            case "$_icmd" in [0-9]*) [ "$_icmd" -gt 0 ] && [ "$_icmd" -le "$_sz" ] && _used="$_icmd" ;; esac
            ;;
          stack)
            _shex="$(dd if=/dev/${_m}ro bs=1 skip=40 count=4 2>/dev/null | od -An -tx1 | awk '{print $4$3$2$1}')"
            case "$_shex" in [0-9a-fA-F][0-9a-fA-F]*) _ssz=$(( (0x$_shex + 4095) / 4096 * 4096 )); [ "$_ssz" -gt 0 ] && [ "$_ssz" -le "$_sz" ] && _used="$_ssz" ;; esac
            ;;
          cfga|cfgb)
            _chdr="$(dd if=/dev/${_m}ro bs=1 count=64 2>/dev/null | tr '\000\377' '  ')"
            _clen="$(printf '%s' "$_chdr" | awk '$1=="TC1CFG"{print $3+64; exit}')"
            case "$_clen" in [0-9]*) [ "$_clen" -gt 0 ] && [ "$_clen" -le "$_sz" ] && _used="$_clen" ;; *) _used=0 ;; esac
            ;;
        esac
        _sz_kb=$(( _sz / 1024 ))
        _us_kb=$(( (_used + 512) / 1024 ))
        [ "$_us_kb" -gt "$_sz_kb" ] && _us_kb="$_sz_kb"
        _ftot_kb=$(( _ftot_kb + _sz_kb ))
        _fused_kb=$(( _fused_kb + _us_kb ))
        json_esc_to _nm_j "$_nm"
        _item="{\"name\":\"$_nm_j\",\"size_kb\":$_sz_kb,\"used_kb\":$_us_kb}"
        _fp_list="${_fp_list:+${_fp_list},}${_item}"
      done
      _di_flash_json="$(printf '{"total_kb":%d,"used_kb":%d,"parts":[%s]}' "$_ftot_kb" "$_fused_kb" "$_fp_list")"
    fi
    _di_ssid=""
    if command -v wpa_cli >/dev/null 2>&1; then
      _di_ssid="$(wpa_cli -i wlan0 status 2>/dev/null | awk -F= '$1 == "ssid" { print $2; exit }')"
    fi
    [ -z "$_di_ssid" ] && [ -r /etc/wpa_supplicant.conf ] && _di_ssid="$(sed -n 's/^[[:space:]]*ssid="\([^"]*\)".*/\1/p' /etc/wpa_supplicant.conf 2>/dev/null | head -n 1)"
    json_esc_to _j_host "$_di_host"; json_esc_to _j_ip "$primary_ip"; json_esc_to _j_mac "$_di_mac"
    json_esc_to _j_kern "$_di_kern"; json_esc_to _j_ver "$_di_ver"; json_esc_to _j_ssid "$_di_ssid"
    printf '{"hostname":"%s","ip":"%s","mac":"%s","kernel":"%s","firmware":"%s","storage":"%s","soc":"Anyka AK3918EV300","sensor":"SOI JXF23","wifi_chip":"Realtek RTL8188FU","ssid":"%s","rtsp_port":%s,"main":{"codec":"%s","width":%s,"height":%s,"fps":%s,"kbps":%s},"sub":{"codec":"%s","width":%s,"height":%s,"fps":%s,"kbps":%s},"jffs":[%s,%s],"sd":[%s,%s],"flash":%s}\n' \
      "$_j_host" "$_j_ip" "$_j_mac" "$_j_kern" "$_j_ver" "${storage_json:-sd}" "$_j_ssid" "$rtsp_port" \
      "$codec0_name" "$width0" "$height0" "$fps0" "$bps0" "$codec1_name" "$width1" "$height1" "$fps1" "$bps1" \
      "$_di_jt" "$_di_ju" "$_di_st" "$_di_su" "$_di_flash_json"
}

dashinfo_cached() {
  _dc_up=0; read -r _dc_up _ < /proc/uptime 2>/dev/null; _dc_up="${_dc_up%.*}"
  case "$_dc_up" in ''|*[!0-9]*) _dc_up=0 ;; esac
  _dc_host=""; read -r _dc_host < /proc/sys/kernel/hostname 2>/dev/null
  if [ -f "$DASHINFO_CACHE_FILE" ]; then
    _dc_ts=""; _dc_chost=""; _dc_json=""
    { read -r _dc_ts; read -r _dc_chost; read -r _dc_json; } < "$DASHINFO_CACHE_FILE"
    case "$_dc_ts" in ''|*[!0-9]*) _dc_ts="" ;; esac
    if [ -n "$_dc_ts" ] && [ -n "$_dc_json" ] && [ "$_dc_chost" = "$_dc_host" ] &&
       [ "$_dc_up" -ge "$_dc_ts" ] && [ $((_dc_up - _dc_ts)) -lt "$DASHINFO_CACHE_TTL_SECONDS" ]; then
      _dc_stale=0
      for _dc_f in /mnt/config/rtspserver.conf /mnt/config/hostname.conf /mnt/config/boot.conf /etc/wpa_supplicant.conf \
          /mnt/VERSION /tmp/flashmode /tmp/tc100-storage /tmp/camera_ip.txt; do
        [ "$_dc_f" -nt "$DASHINFO_CACHE_FILE" ] && { _dc_stale=1; break; }
      done
      if [ "$_dc_stale" = 0 ]; then
        printf '%s\n' "$_dc_json"
        return 0
      fi
    fi
  fi
  _dc_json="$(dashinfo_compute)"
  printf '%s\n' "$_dc_json"
  case "$_dc_json" in
    '{"hostname":'*)
      { printf '%s\n%s\n%s\n' "$_dc_up" "$_dc_host" "$_dc_json" > "$DASHINFO_CACHE_FILE.$$" &&
        mv "$DASHINFO_CACHE_FILE.$$" "$DASHINFO_CACHE_FILE"; } 2>/dev/null || rm -f "$DASHINFO_CACHE_FILE.$$" 2>/dev/null ;;
  esac
}

service_state_json() {
  service_script="$1"
  service_state="stopped"
  service_pid=0
  service_status="$("$service_script" status 2>/dev/null)"
  if [ -n "$service_status" ]; then
    service_state="running"
    service_pid="$(printf '%s' "$service_status" | sed -n 's/.*PID:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -n 1)"
    service_pid="$(sanitize_int "$service_pid" 0)"
  fi
  service_state_escaped="$(json_escape "$service_state")"
  printf '{"state":"%s","pid":%s}' "$service_state_escaped" "$service_pid"
}

# cfg_int VAR KEY DEFAULT: get_cfg + sanitize_int into a variable, without the two subshells (read_rtsp_stream_summary
# calls it 33 times, each camera page poll). Same result: an empty or non-numeric value gives the default.
cfg_int() {
  eval "_ci_val=\"\$C_$2\""
  case "$_ci_val" in ''|*[!0-9]*) _ci_val="$3" ;; esac
  eval "$1=\"\$_ci_val\""
}

# codec_name without a subshell: codec_name_to VAR CODE
codec_name_to() {
  case "$2" in 2) eval "$1=H265" ;; 0) eval "$1=H264" ;; *) eval "$1=unknown" ;; esac
}

read_rtsp_stream_summary() {
    # Main Stream [0]
    cfg_int codec0 0_codec 2
    cfg_int width0 0_width 1280
    cfg_int height0 0_height 720
    cfg_int fps0 0_fps 16
    cfg_int bps0 0_bps 1000
    cfg_int profile0 0_profile 3
    cfg_int goplen0 0_goplen 50
    cfg_int brmode0 0_brmode 1
    cfg_int minqp0 0_minqp 20
    cfg_int maxqp0 0_maxqp 51
    cfg_int smartmode0 0_smartmode 1
    cfg_int smartgoplen0 0_smartgoplen 0
    cfg_int smartquality0 0_smartquality 100
    cfg_int smartstatic0 0_smartstatic 500
    cfg_int maxkbps0 0_maxkbps 1500
    cfg_int targetkbps0 0_targetkbps 1200

    # Sub Stream [1]
    cfg_int codec1 1_codec 0
    cfg_int width1 1_width 640
    cfg_int height1 1_height 360
    cfg_int fps1 1_fps 8
    cfg_int bps1 1_bps 250
    cfg_int profile1 1_profile 0
    cfg_int goplen1 1_goplen 32
    cfg_int brmode1 1_brmode 1
    cfg_int minqp1 1_minqp 20
    cfg_int maxqp1 1_maxqp 51
    cfg_int smartmode1 1_smartmode 1
    cfg_int smartgoplen1 1_smartgoplen 0
    cfg_int smartquality1 1_smartquality 50
    cfg_int smartstatic1 1_smartstatic 150
    cfg_int maxkbps1 1_maxkbps 450
    cfg_int targetkbps1 1_targetkbps 400

    # tc100_rtsp encodes 1920x1080 and 640x360 at 15 frames per second whatever the file says (codec and bit rate
    # are taken from it): report what the streams really are (dashboard, Frigate YAML, HA manifest).
    # The frame rate is one setting for both streams: 10, 12, 15, 20 or 25 (Settings -> Streams & audio), else 15.
    width0=1920; height0=1080; width1=640; height1=360
    case "$fps0" in 10|12|15|20|25) ;; *) fps0=15 ;; esac
    fps1=$fps0

    codec_name_to codec0_name "$codec0"
    codec_name_to codec1_name "$codec1"

    cfg_int rtsp_port PORT 554
}

last_watchdog_event_json() {
  event=""
  if [ -r /tmp/log/service-watchdog.log ]; then
    event="$(tail -n 1 /tmp/log/service-watchdog.log 2>/dev/null)"
  fi
  event_escaped="$(json_escape "$event")"
  printf '%s' "$event_escaped"
}




read_chip_temperature() {
  chip_temp_raw=""
  chip_temp_c=""
  chip_temp_json="null"
  chip_temp_text="n/a"

  temp_source_path="$(read_conf_value /mnt/config/boot.conf CHIP_TEMP_SOURCE_PATH auto)"
  temp_raw_divisor="$(read_conf_value /mnt/config/boot.conf CHIP_TEMP_RAW_DIVISOR auto)"

  temp_candidates=""
  case "$temp_source_path" in
    ''|auto)
      temp_candidates="/sys/class/thermal/thermal_zone0/temp /sys/class/thermal/thermal_zone1/temp /sys/devices/virtual/thermal/thermal_zone0/temp /proc/temperature /tmp/chip_temp"
      ;;
    *)
      temp_candidates="$temp_source_path"
      ;;
  esac

  for candidate in $temp_candidates; do
    [ -r "$candidate" ] || continue
    read -r raw_value < "$candidate"
    raw_value="$(sanitize_int "$raw_value" 0)"
    if [ "$raw_value" -gt 0 ]; then
      chip_temp_raw="$raw_value"
      break
    fi
  done

  if [ -n "$chip_temp_raw" ]; then
    case "$temp_raw_divisor" in
      ''|auto)
        if [ "$chip_temp_raw" -ge 10000 ]; then
          temp_raw_divisor=1000
        elif [ "$chip_temp_raw" -le 125 ]; then
          temp_raw_divisor=1
        else
          temp_raw_divisor=0
        fi
        ;;
      *)
        temp_raw_divisor="$(sanitize_int "$temp_raw_divisor" 0)"
        ;;
    esac

    if [ "$temp_raw_divisor" -gt 0 ]; then
      chip_temp_c=$((chip_temp_raw / temp_raw_divisor))
    fi
  fi

  if [ -n "$chip_temp_c" ] && [ "$chip_temp_c" -ge 0 ] && [ "$chip_temp_c" -le 125 ]; then
    chip_temp_text="${chip_temp_c}C"
    chip_temp_json="$chip_temp_c"
  fi
}

read_power_telemetry() {
  power_sensor_path_cfg="$(read_conf_value /mnt/config/mqtt.conf POWER_SENSOR_PATH auto)"
  power_estimate_enable_raw="$(read_conf_value /mnt/config/mqtt.conf POWER_ESTIMATE_ENABLE 0)"
  power_estimate_base_mw="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf POWER_ESTIMATE_BASE_MW 1700)" 1700)"
  power_estimate_cpu_scale_mw="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf POWER_ESTIMATE_CPU_SCALE_MW 500)" 500)"
  power_estimate_ir_led_mw="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf POWER_ESTIMATE_IR_LED_MW 700)" 700)"

  if [ "$power_estimate_base_mw" -lt 0 ]; then
    power_estimate_base_mw=0
  fi
  if [ "$power_estimate_cpu_scale_mw" -lt 0 ]; then
    power_estimate_cpu_scale_mw=0
  fi
  if [ "$power_estimate_ir_led_mw" -lt 0 ]; then
    power_estimate_ir_led_mw=0
  fi

  case "$power_estimate_enable_raw" in
    1|true|on|yes|enabled)
      power_estimate_enabled=1
      ;;
    *)
      power_estimate_enabled=0
      ;;
  esac

  case "$power_sensor_path_cfg" in
    ''|auto)
      power_sensor_candidates="/sys/kernel/ain/bat /sys/kernel/ain/ain0 /sys/kernel/ain/ain1"
      ;;
    /*)
      power_sensor_candidates="$power_sensor_path_cfg"
      ;;
    *)
      power_sensor_candidates="/sys/kernel/ain/bat /sys/kernel/ain/ain0 /sys/kernel/ain/ain1"
      ;;
  esac

  power_sensor_raw=""
  power_sensor_path=""
  power_voltage_mv=0

  for candidate in $power_sensor_candidates; do
    [ -r "$candidate" ] || continue
    read -r raw_value < "$candidate"
    raw_value="$(sanitize_int "$raw_value" 0)"
    if [ "$raw_value" -le 0 ]; then
      continue
    fi
    power_sensor_raw="$raw_value"
    power_sensor_path="$candidate"
    break
  done

  if [ -n "$power_sensor_raw" ]; then
    if [ "$power_sensor_raw" -ge 2500 ] && [ "$power_sensor_raw" -le 20000 ]; then
      power_voltage_mv="$power_sensor_raw"
    elif [ "$power_sensor_raw" -ge 2500000 ] && [ "$power_sensor_raw" -le 20000000 ]; then
      power_voltage_mv=$((power_sensor_raw / 1000))
    fi
  fi

  power_voltage_mv_json="null"
  power_voltage_text="n/a"
  if [ "$power_voltage_mv" -gt 0 ]; then
    power_voltage_mv_json="$power_voltage_mv"
    volts_centiv=$(((power_voltage_mv + 5) / 10))
    volts_whole=$((volts_centiv / 100))
    volts_frac=$((volts_centiv % 100))
    power_voltage_text="$(printf '%s.%02sV' "$volts_whole" "$volts_frac")"
  fi

  power_sensor_raw_json="null"
  if [ -n "$power_sensor_raw" ]; then
    power_sensor_raw_json="$power_sensor_raw"
  fi
  if [ -n "$power_sensor_path" ]; then
    power_sensor_path_json="$(json_escape "$power_sensor_path")"
  else
    power_sensor_path_json="n/a"
  fi

  power_estimated_mw_json="null"
  power_estimated_text="n/a"
  power_estimated_current_ma_json="null"

  if [ "$power_estimate_enabled" -eq 1 ]; then
    cpu_for_power="$(sanitize_int "$cpu" 0)"
    if [ "$cpu_for_power" -lt 0 ]; then
      cpu_for_power=0
    elif [ "$cpu_for_power" -gt 100 ]; then
      cpu_for_power=100
    fi

    power_estimated_mw=$((power_estimate_base_mw + (cpu_for_power * power_estimate_cpu_scale_mw / 100)))
    ir_led_state=0
    if [ -r /sys/class/leds/ir/brightness ]; then
      read -r ir_led_raw < /sys/class/leds/ir/brightness
      ir_led_state="$(sanitize_int "$ir_led_raw" 0)"
    elif [ -r /sys/user-gpio/ir-led ]; then
      read -r ir_led_raw < /sys/user-gpio/ir-led
      ir_led_state="$(sanitize_int "$ir_led_raw" 0)"
    fi
    if [ "$ir_led_state" -eq 1 ]; then
      power_estimated_mw=$((power_estimated_mw + power_estimate_ir_led_mw))
    fi
    if [ "$power_estimated_mw" -lt 0 ]; then
      power_estimated_mw=0
    fi

    power_estimated_mw_json="$power_estimated_mw"
    est_tenths_w=$(((power_estimated_mw + 50) / 100))
    est_w_whole=$((est_tenths_w / 10))
    est_w_frac=$((est_tenths_w % 10))
    power_estimated_text="$(printf '%s.%sW est' "$est_w_whole" "$est_w_frac")"

    if [ "$power_voltage_mv" -gt 0 ]; then
      power_estimated_current_ma=$((power_estimated_mw * 1000 / power_voltage_mv))
      power_estimated_current_ma_json="$power_estimated_current_ma"
    fi
  fi
}





# get_live_gateway — default route gateway from /proc/net/route, shell only.
# The dashboard's "Gateway" used to come from a DEFAULT_GATEWAY config key that
# nothing ever writes, so it always showed 0.0.0.0. Prints "n/a" without one.
get_live_gateway() {
  _glg_src="${ROUTE_PROC_FILE:-/proc/net/route}"
  _glg_hex=""
  if [ -r "$_glg_src" ]; then
    while read -r _glg_if _glg_dst _glg_gw _glg_rest; do
      [ "$_glg_dst" = "00000000" ] || continue
      case "$_glg_gw" in [0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]) ;; *) continue ;; esac
      [ "$_glg_gw" = "00000000" ] && continue
      _glg_hex="$_glg_gw"
      break
    done < "$_glg_src"
  fi
  if [ -z "$_glg_hex" ]; then
    echo "n/a"
    return 0
  fi
  # Little-endian hex: 0101A8C0 -> 192.168.1.1
  _glg_a="${_glg_hex#??????}"
  _glg_b="${_glg_hex#????}"; _glg_b="${_glg_b%??}"
  _glg_c="${_glg_hex#??}"; _glg_c="${_glg_c%????}"
  _glg_d="${_glg_hex%??????}"
  printf '%d.%d.%d.%d\n' "0x$_glg_a" "0x$_glg_b" "0x$_glg_c" "0x$_glg_d"
}



read_reboot_epoch() {
  reboot_epoch=0

  [ "$_SCRIPT_BTIME" -gt 0 ] || _read_script_btime
  if [ "$_SCRIPT_BTIME" -gt 0 ]; then
    reboot_epoch="$_SCRIPT_BTIME"
  fi

  if [ "$reboot_epoch" -le 0 ] && [ -r /proc/uptime ]; then
    read -r uptime_raw _ < /proc/uptime
    uptime_seconds_fallback="${uptime_raw%.*}"
    uptime_seconds_fallback="$(sanitize_int "$uptime_seconds_fallback" 0)"
    _read_now_ts
    if [ "$now_ts" -gt 0 ] && [ "$uptime_seconds_fallback" -gt 0 ]; then
      reboot_epoch=$((now_ts - uptime_seconds_fallback))
    fi
  fi
}


default_password_active_flag() {
  compute_default_password_flag
  echo "$default_password_active"
}

if [ -n "$F_cmd" ]; then
  case "$F_cmd" in
  hostname)
    if [ -r /proc/sys/kernel/hostname ]; then
      cat /proc/sys/kernel/hostname
    else
      hostname
    fi
    ;;

  daynight)
    # Settings -> Day/night: the automatic switching settings and the live reading (picture luminance, ISP exposure
    # state of /tmp/cam_ae and the exposure index the ae source compares; the formula is that of
    # scripts/auto-night-daemon.sh dn_index) so that the thresholds can be set from what the camera sees.
    load_conf_file /mnt/config/daynight.conf
    _dn_src="$C_DAYNIGHT_SOURCE"; case "$_dn_src" in ae|isp) ;; *) _dn_src=luma ;; esac
    _dn_luma=""; [ -r /tmp/cam_luma ] && read -r _dn_luma < /tmp/cam_luma
    _dn_ae=0; _dn_idx=null; _dn_l=null; _dn_e=null; _dn_a=null; _dn_d=null; _dn_i=null; _dn_k=null
    if [ -r /tmp/cam_ae ]; then
      read -r _l _e _a _d _i _k < /tmp/cam_ae
      case "$_l $_e $_a $_d $_i $_k" in
        *[!0-9\ ]*|*"  "*|" "*|*" ") ;;
        *)
          if [ -n "$_k" ] && [ "${#_e}" -le 9 ] && [ "${#_a}" -le 9 ] && [ "${#_d}" -le 9 ] && [ "${#_i}" -le 9 ]; then
            _dn_ae=1; _dn_l=$_l; _dn_e=$_e; _dn_a=$_a; _dn_d=$_d; _dn_i=$_i; _dn_k=$_k
            _dn_idx=$(( _e * _a / 256 )); _dn_idx=$(( _dn_idx * _d / 256 )); _dn_idx=$(( _dn_idx * _i / 256 ))
          fi ;;
      esac
    fi
    _dn_cut=1; [ -r /var/run/ircut ] && { read -r _dn_c < /var/run/ircut; [ "$_dn_c" = 0 ] && _dn_cut=0; }
    # first "daynight=" line of rtspserver.conf (3 = manual night): read in the shell, no sed|head
    _dn_auto=1
    if [ -r /mnt/config/rtspserver.conf ]; then
      while IFS='=' read -r _dn_k0 _dn_m; do
        [ "$_dn_k0" = daynight ] || continue
        [ "$_dn_m" = 3 ] && _dn_auto=0
        break
      done < /mnt/config/rtspserver.conf
    fi
    cfg_int _dn_ln LUMA_NIGHT 40; cfg_int _dn_ld LUMA_DAY 100
    cfg_int _dn_an AE_NIGHT_ABOVE 4000; cfg_int _dn_ad AE_DAY_BELOW 1000
    cfg_int _dn_nh NIGHT_HOLD 10; cfg_int _dn_dh DAY_HOLD 60
    case "$_dn_luma" in ''|*[!0-9]*) _dn_luma=null ;; esac
    printf '{"source":"%s","luma_night":%s,"luma_day":%s,"ae_night_above":%s,"ae_day_below":%s,"night_hold":%s,"day_hold":%s,"auto":%s,"night":%s,"luma":%s,"ae_available":%s,"lumi":%s,"exp_time":%s,"a_gain":%s,"d_gain":%s,"isp_d_gain":%s,"dark_flag":%s,"index":%s}\n' \
      "$_dn_src" "$_dn_ln" "$_dn_ld" "$_dn_an" "$_dn_ad" "$_dn_nh" "$_dn_dh" \
      "$_dn_auto" "$((1 - _dn_cut))" "$_dn_luma" "$_dn_ae" "$_dn_l" "$_dn_e" "$_dn_a" "$_dn_d" "$_dn_i" "$_dn_k" "$_dn_idx"
    ;;

  lumawb)
    load_lum_awb
    echo "$lum_value"
    echo "$awb_value"
    ;;

  sysusage)
    load_or_compute_usage_metrics
    echo "CPU: $cpu% RAM: $mem_used/$mem_total kB"
    ;;

  statusline)
    # Kept for old pages and scripts; the UI polls cgi-bin/statusline.cgi (same JSON).
    statusline_json
    ;;

  integrationtest)
    detect_primary_ip
    if [ -r /proc/sys/kernel/hostname ]; then
      read -r test_hostname < /proc/sys/kernel/hostname
    else
      test_hostname="$(hostname 2>/dev/null)"
    fi
    [ -n "$test_hostname" ] || test_hostname="TC100 Camera"

    read_rtsp_stream_summary
    rtsp_username_test="$(read_conf_value /mnt/config/rtspserver.conf USERNAME root)"
    rtsp_password_test="$(read_conf_value /mnt/config/rtspserver.conf USERPASSWORD pass)"
    rtsp_substream_enabled_test="$(truthy_flag "$(read_conf_value /mnt/config/boot.conf RTSP_SUBSTREAM 1)")"
    rtsp_timeout_test="$(sanitize_int "$(read_conf_value /mnt/config/boot.conf RTSP_HEALTHCHECK_TIMEOUT_SECONDS 4)" 4)"
    if [ "$rtsp_timeout_test" -lt 2 ] || [ "$rtsp_timeout_test" -gt 30 ]; then
      rtsp_timeout_test=4
    fi
    onvif_port_test="$(sanitize_int "$(read_conf_value /mnt/config/onvif.conf ONVIF_PORT 8081)" 8081)"
    if [ "$onvif_port_test" -lt 1 ] || [ "$onvif_port_test" -gt 65535 ]; then
      onvif_port_test=8081
    fi
    mqtt_enabled_test="$(truthy_flag "$(read_conf_value /mnt/config/mqtt.conf MQTT_ENABLE 0)")"
    mqtt_topic_root_test="$(read_conf_value /mnt/config/mqtt.conf MQTT_TOPIC_ROOT tc100/camera)"
    mqtt_broker_host_test="$(read_conf_value /mnt/config/mqtt.conf MQTT_HOST 127.0.0.1)"
    mqtt_broker_port_test="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf MQTT_PORT 1883)" 1883)"
    if [ "$mqtt_broker_port_test" -lt 1 ] || [ "$mqtt_broker_port_test" -gt 65535 ]; then
      mqtt_broker_port_test=1883
    fi

    rtsp_main_status="fail"
    rtsp_main_detail="RTSP service is not running."
    if [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x status >/dev/null 2>&1; then
      if [ -x /mnt/bin/curl ]; then
        if rtsp_describe_local_ok "video0_unicast" "$rtsp_port" "$rtsp_username_test" "$rtsp_password_test" "$rtsp_timeout_test"; then
          rtsp_main_status="ok"
          rtsp_main_detail="RTSP endpoint responded for video0_unicast."
        else
          rtsp_main_status="fail"
          rtsp_main_detail="RTSP endpoint did not respond for video0_unicast."
        fi
      else
        rtsp_main_status="ok"
        rtsp_main_detail="RTSP service is running; DESCRIBE skipped because curl is unavailable."
      fi
    fi

    rtsp_sub_status="disabled"
    rtsp_sub_detail="Substream disabled by RTSP_SUBSTREAM=0."
    if [ "$rtsp_substream_enabled_test" = "1" ]; then
      rtsp_sub_status="fail"
      rtsp_sub_detail="RTSP substream check failed because RTSP service is not running."
      if [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x status >/dev/null 2>&1; then
        if [ -x /mnt/bin/curl ]; then
          if rtsp_describe_local_ok "video1_unicast" "$rtsp_port" "$rtsp_username_test" "$rtsp_password_test" "$rtsp_timeout_test"; then
            rtsp_sub_status="ok"
            rtsp_sub_detail="RTSP endpoint responded for video1_unicast."
          else
            rtsp_sub_status="fail"
            rtsp_sub_detail="RTSP endpoint did not respond for video1_unicast."
          fi
        else
          rtsp_sub_status="ok"
          rtsp_sub_detail="RTSP service is running; substream DESCRIBE skipped because curl is unavailable."
        fi
      fi
    fi

    onvif_status="disabled"
    onvif_detail="ONVIF service is not running."
    if [ -x /mnt/controlscripts/onvif ] && /mnt/controlscripts/onvif status >/dev/null 2>&1; then
      if /mnt/controlscripts/onvif health >/dev/null 2>&1; then
        onvif_status="ok"
        onvif_detail="ONVIF service is healthy on port ${onvif_port_test}."
      else
        onvif_status="fail"
        onvif_detail="ONVIF health check failed on port ${onvif_port_test}."
      fi
    fi

    mqtt_status="disabled"
    mqtt_detail="MQTT bridge disabled in config."
    if [ "$mqtt_enabled_test" = "1" ]; then
      if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
        _read_now_ts
        mqtt_selftest_payload="$(printf '{"ts":%s,"type":"integration_selftest","origin":"state.cgi"}' "$now_ts")"
        if /mnt/scripts/mqtt-bridge.sh publish selftest "$mqtt_selftest_payload" 0 >/dev/null 2>&1; then
          mqtt_status="ok"
          mqtt_detail="Published self-test payload to ${mqtt_topic_root_test}/selftest via ${mqtt_broker_host_test}:${mqtt_broker_port_test}."
        else
          mqtt_status="fail"
          mqtt_detail="MQTT publish failed to ${mqtt_broker_host_test}:${mqtt_broker_port_test}."
        fi
      else
        mqtt_status="fail"
        mqtt_detail="MQTT bridge helper script is missing."
      fi
    fi

    snapshot_status="fail"
    snapshot_detail="Snapshot capture failed."
    _read_now_ts
    snapshot_tmp="/tmp/integration-selftest.$$.$now_ts.jpg"
    # take_snapshot: the picture tc100_rtsp keeps
    if ( . /mnt/scripts/common_functions.sh; take_snapshot "$snapshot_tmp" ); then
      snapshot_status="ok"
      snapshot_detail="Local snapshot capture succeeded."
    else
      snapshot_status="fail"
      snapshot_detail="tc100_rtsp made no picture."
    fi
    rm -f "$snapshot_tmp" >/dev/null 2>&1 || true

    overall_status="ok"
    overall_ok=1
    for integration_test_status in "$rtsp_main_status" "$rtsp_sub_status" "$onvif_status" "$mqtt_status" "$snapshot_status"; do
      if [ "$integration_test_status" = "fail" ]; then
        overall_status="fail"
        overall_ok=0
        break
      fi
      if [ "$integration_test_status" = "disabled" ] && [ "$overall_status" = "ok" ]; then
        overall_status="warn"
      fi
    done

    _read_now_ts
    test_time_utc="$(_format_iso8601_utc "$now_ts")"
    test_time_utc_json="$(json_escape "$test_time_utc")"
    test_hostname_json="$(json_escape "$test_hostname")"
    primary_ip_json="$(json_escape "$primary_ip")"
    overall_status_json="$(json_escape "$overall_status")"
    rtsp_main_status_json="$(json_escape "$rtsp_main_status")"
    rtsp_main_detail_json="$(json_escape "$rtsp_main_detail")"
    rtsp_sub_status_json="$(json_escape "$rtsp_sub_status")"
    rtsp_sub_detail_json="$(json_escape "$rtsp_sub_detail")"
    onvif_status_json="$(json_escape "$onvif_status")"
    onvif_detail_json="$(json_escape "$onvif_detail")"
    mqtt_status_json="$(json_escape "$mqtt_status")"
    mqtt_detail_json="$(json_escape "$mqtt_detail")"
    snapshot_status_json="$(json_escape "$snapshot_status")"
    snapshot_detail_json="$(json_escape "$snapshot_detail")"

    printf '{"timestamp_utc":"%s","hostname":"%s","primary_ip":"%s","overall_status":"%s","overall_ok":%s,"tests":{"rtsp_main":{"status":"%s","detail":"%s"},"rtsp_sub":{"status":"%s","detail":"%s"},"onvif":{"status":"%s","detail":"%s"},"mqtt_publish":{"status":"%s","detail":"%s"},"snapshot":{"status":"%s","detail":"%s"}}}\n' \
      "$test_time_utc_json" "$test_hostname_json" "$primary_ip_json" "$overall_status_json" "$overall_ok" \
      "$rtsp_main_status_json" "$rtsp_main_detail_json" \
      "$rtsp_sub_status_json" "$rtsp_sub_detail_json" \
      "$onvif_status_json" "$onvif_detail_json" \
      "$mqtt_status_json" "$mqtt_detail_json" \
      "$snapshot_status_json" "$snapshot_detail_json"
    ;;

  integrationmanifest)
    if [ -r /proc/sys/kernel/hostname ]; then
      read -r manifest_hostname < /proc/sys/kernel/hostname
    else
      manifest_hostname="$(hostname 2>/dev/null)"
    fi
    [ -n "$manifest_hostname" ] || manifest_hostname="TC100 Camera"
    manifest_redact="$(truthy_flag "$F_redact")"

    detect_primary_ip

    manifest_camera_slug="$(slugify_value "$manifest_hostname")"
    [ -n "$manifest_camera_slug" ] || manifest_camera_slug="$(slugify_value "$(read_conf_value /mnt/config/mqtt.conf MQTT_CLIENT_ID tc100-camera)")"
    [ -n "$manifest_camera_slug" ] || manifest_camera_slug="tc100_camera"

    manifest_web_mode="$(normalize_web_mode_value "$(read_conf_value /mnt/config/boot.conf WEB_MODE full)")"
    manifest_ultralite_http_port="$(sanitize_int "$(read_conf_value /mnt/config/boot.conf ULTRALITE_HTTP_PORT 80)" 80)"
    if [ "$manifest_ultralite_http_port" -lt 1 ] || [ "$manifest_ultralite_http_port" -gt 65535 ]; then
      manifest_ultralite_http_port=80
    fi
    build_web_base_url "$manifest_web_mode" "$primary_ip" "$manifest_ultralite_http_port"

    web_snapshot_url=""
    web_healthsnapshot_url=""
    web_manifest_url=""
    web_motion_events_url=""
    web_motion_thumbnail_url=""
    if [ "$web_enabled" = "1" ]; then
      web_snapshot_url="${web_base_url}/cgi-bin/currentpic.cgi"
      web_healthsnapshot_url="${web_base_url}/cgi-bin/state.cgi?cmd=healthsnapshot"
      web_manifest_url="${web_base_url}/cgi-bin/state.cgi?cmd=integrationmanifest"
      web_motion_events_url="${web_base_url}/cgi-bin/motionevents.cgi?limit=20"
      web_motion_thumbnail_url="${web_base_url}/cgi-bin/motionthumb.cgi"
    fi

    read_rtsp_stream_summary
    rtsp_username="$(read_conf_value /mnt/config/rtspserver.conf USERNAME root)"
    rtsp_password="$(read_conf_value /mnt/config/rtspserver.conf USERPASSWORD pass)"
    rtsp_substream_enabled="$(truthy_flag "$(read_conf_value /mnt/config/boot.conf RTSP_SUBSTREAM 1)")"
    rtsp_audio_enabled="$(truthy_flag "$(read_conf_value /mnt/config/boot.conf RTSP_AUDIO 1)")"
    onvif_stream_policy_value="$(read_conf_value /mnt/config/boot.conf ONVIF_STREAM_POLICY main-primary)"
    rtsp_manifest_username="$rtsp_username"
    rtsp_manifest_password="$rtsp_password"
    if [ "$manifest_redact" = "1" ]; then
      rtsp_auth_embedded=0
      if [ -n "$rtsp_username" ] || [ -n "$rtsp_password" ]; then
        rtsp_manifest_username="USERNAME"
        rtsp_manifest_password=""
        rtsp_url_auth_prefix="USERNAME:PASSWORD@"
        rtsp_auth_warning="Credentials omitted from redacted manifest; replace USERNAME/PASSWORD in client configs."
      else
        rtsp_manifest_username=""
        rtsp_manifest_password=""
        rtsp_url_auth_prefix=""
        rtsp_auth_warning=""
      fi
    else
      prepare_rtsp_auth_template "$rtsp_username" "$rtsp_password"
      rtsp_auth_embedded="$rtsp_url_auth_embedded"
      rtsp_auth_warning="$rtsp_url_auth_warning"
    fi
    rtsp_main_url="$(build_rtsp_url_template "$primary_ip" "$rtsp_port" "video0_unicast")"
    rtsp_sub_url=""
    if [ "$rtsp_substream_enabled" = "1" ]; then
      rtsp_sub_url="$(build_rtsp_url_template "$primary_ip" "$rtsp_port" "video1_unicast")"
    fi

    frigate_record_url="$rtsp_main_url"
    frigate_detect_url="$rtsp_main_url"
    frigate_detect_source="main"
    if [ "$rtsp_substream_enabled" = "1" ] && [ -n "$rtsp_sub_url" ]; then
      frigate_detect_url="$rtsp_sub_url"
      frigate_detect_source="sub"
    fi

    onvif_port="$(sanitize_int "$(read_conf_value /mnt/config/onvif.conf ONVIF_PORT 8081)" 8081)"
    if [ "$onvif_port" -lt 1 ] || [ "$onvif_port" -gt 65535 ]; then
      onvif_port=8081
    fi
    onvif_device_service_url="http://${primary_ip}:${onvif_port}/onvif/device_service"

    mqtt_enabled_flag="$(truthy_flag "$(read_conf_value /mnt/config/mqtt.conf MQTT_ENABLE 0)")"
    mqtt_broker_host="$(read_conf_value /mnt/config/mqtt.conf MQTT_HOST 127.0.0.1)"
    mqtt_broker_port="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf MQTT_PORT 1883)" 1883)"
    if [ "$mqtt_broker_port" -lt 1 ] || [ "$mqtt_broker_port" -gt 65535 ]; then
      mqtt_broker_port=1883
    fi
    mqtt_username="$(read_conf_value /mnt/config/mqtt.conf MQTT_USER "")"
    mqtt_password="$(read_conf_value /mnt/config/mqtt.conf MQTT_PASSWORD "")"
    mqtt_manifest_username="$mqtt_username"
    mqtt_manifest_password="$mqtt_password"
    if [ "$manifest_redact" = "1" ]; then
      mqtt_manifest_username=""
      mqtt_manifest_password=""
    fi
    mqtt_client_id="$(read_conf_value /mnt/config/mqtt.conf MQTT_CLIENT_ID tc100-camera)"
    mqtt_topic_root="$(read_conf_value /mnt/config/mqtt.conf MQTT_TOPIC_ROOT tc100/camera)"
    mqtt_command_topic="$(read_conf_value /mnt/config/mqtt.conf MQTT_TOPIC_COMMAND "")"
    [ -n "$mqtt_command_topic" ] || mqtt_command_topic="${mqtt_topic_root}/command"
    mqtt_discovery_enabled="$(truthy_flag "$(read_conf_value /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_ENABLE 1)")"
    mqtt_discovery_prefix="$(read_conf_value /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_PREFIX homeassistant)"
    mqtt_availability_topic="${mqtt_topic_root}/availability"
    mqtt_health_topic="${mqtt_topic_root}/health"
    mqtt_motion_state_topic="${mqtt_topic_root}/motion/state"
    mqtt_event_topic="${mqtt_topic_root}/event"
    mqtt_snapshot_last_path_topic="${mqtt_topic_root}/snapshot/last_path"
    mqtt_integration_manifest_topic="${mqtt_topic_root}/integration/manifest"
    mqtt_integration_selftest_topic="${mqtt_topic_root}/integration/selftest"
    mqtt_command_result_topic="${mqtt_topic_root}/command/result"
    mqtt_command_last_result_topic="${mqtt_topic_root}/command/last_result"
    mqtt_repair_last_result_topic="${mqtt_topic_root}/repair/last_result"

    _read_now_ts
    manifest_time_utc="$(_format_iso8601_utc "$now_ts")"
    manifest_time_utc_json="$(json_escape "$manifest_time_utc")"
    manifest_hostname_json="$(json_escape "$manifest_hostname")"
    manifest_camera_slug_json="$(json_escape "$manifest_camera_slug")"
    primary_ip_json="$(json_escape "$primary_ip")"
    web_mode_json="$(json_escape "$manifest_web_mode")"
    web_base_url_json="$(json_escape "$web_base_url")"
    web_snapshot_url_json="$(json_escape "$web_snapshot_url")"
    web_healthsnapshot_url_json="$(json_escape "$web_healthsnapshot_url")"
    web_manifest_url_json="$(json_escape "$web_manifest_url")"
    web_motion_events_url_json="$(json_escape "$web_motion_events_url")"
    web_motion_thumbnail_url_json="$(json_escape "$web_motion_thumbnail_url")"
    rtsp_username_json="$(json_escape "$rtsp_manifest_username")"
    rtsp_password_json="$(json_escape "$rtsp_manifest_password")"
    rtsp_auth_warning_json="$(json_escape "$rtsp_auth_warning")"
    rtsp_main_url_json="$(json_escape "$rtsp_main_url")"
    rtsp_sub_url_json="$(json_escape "$rtsp_sub_url")"
    codec0_json="$(json_escape "$codec0_name")"
    codec1_json="$(json_escape "$codec1_name")"
    frigate_record_url_json="$(json_escape "$frigate_record_url")"
    frigate_detect_url_json="$(json_escape "$frigate_detect_url")"
    frigate_detect_source_json="$(json_escape "$frigate_detect_source")"
    onvif_device_service_url_json="$(json_escape "$onvif_device_service_url")"
    onvif_stream_policy_json="$(json_escape "$onvif_stream_policy_value")"
    mqtt_broker_host_json="$(json_escape "$mqtt_broker_host")"
    mqtt_username_json="$(json_escape "$mqtt_manifest_username")"
    mqtt_password_json="$(json_escape "$mqtt_manifest_password")"
    mqtt_client_id_json="$(json_escape "$mqtt_client_id")"
    mqtt_topic_root_json="$(json_escape "$mqtt_topic_root")"
    mqtt_command_topic_json="$(json_escape "$mqtt_command_topic")"
    mqtt_discovery_prefix_json="$(json_escape "$mqtt_discovery_prefix")"
    mqtt_availability_topic_json="$(json_escape "$mqtt_availability_topic")"
    mqtt_health_topic_json="$(json_escape "$mqtt_health_topic")"
    mqtt_motion_state_topic_json="$(json_escape "$mqtt_motion_state_topic")"
    mqtt_event_topic_json="$(json_escape "$mqtt_event_topic")"
    mqtt_snapshot_last_path_topic_json="$(json_escape "$mqtt_snapshot_last_path_topic")"
    mqtt_integration_manifest_topic_json="$(json_escape "$mqtt_integration_manifest_topic")"
    mqtt_integration_selftest_topic_json="$(json_escape "$mqtt_integration_selftest_topic")"
    mqtt_command_result_topic_json="$(json_escape "$mqtt_command_result_topic")"
    mqtt_command_last_result_topic_json="$(json_escape "$mqtt_command_last_result_topic")"
    mqtt_repair_last_result_topic_json="$(json_escape "$mqtt_repair_last_result_topic")"

    printf '{"generated_at_utc":"%s","hostname":"%s","camera_slug":"%s","primary_ip":"%s","web":{"mode":"%s","enabled":%s,"base_url":"%s","snapshot_url":"%s","healthsnapshot_url":"%s","integration_manifest_url":"%s","motion_events_url":"%s","motion_thumbnail_url":"%s"},"rtsp":{"username":"%s","password":"%s","port":%s,"auth_embedded":%s,"auth_warning":"%s","audio_enabled":%s,"substream_enabled":%s,"main":{"path":"video0_unicast","url":"%s","codec":"%s","width":%s,"height":%s,"fps":%s},"sub":{"path":"video1_unicast","url":"%s","codec":"%s","width":%s,"height":%s,"fps":%s},"frigate":{"record_url":"%s","detect_url":"%s","detect_source":"%s"}},"onvif":{"port":%s,"device_service_url":"%s","stream_policy":"%s"},"mqtt":{"enabled":%s,"broker_host":"%s","broker_port":%s,"username":"%s","password":"%s","client_id":"%s","discovery_enabled":%s,"discovery_prefix":"%s","topic_root":"%s","command_topic":"%s","availability_topic":"%s","health_topic":"%s","motion_state_topic":"%s","event_topic":"%s","snapshot_last_path_topic":"%s","integration_manifest_topic":"%s","integration_selftest_topic":"%s","command_result_topic":"%s","command_last_result_topic":"%s","repair_last_result_topic":"%s"}}\n' \
      "$manifest_time_utc_json" "$manifest_hostname_json" "$manifest_camera_slug_json" "$primary_ip_json" \
      "$web_mode_json" "$web_enabled" "$web_base_url_json" "$web_snapshot_url_json" "$web_healthsnapshot_url_json" "$web_manifest_url_json" "$web_motion_events_url_json" "$web_motion_thumbnail_url_json" \
      "$rtsp_username_json" "$rtsp_password_json" "$rtsp_port" "$rtsp_auth_embedded" "$rtsp_auth_warning_json" "$rtsp_audio_enabled" "$rtsp_substream_enabled" \
      "$rtsp_main_url_json" "$codec0_json" "$width0" "$height0" "$fps0" \
      "$rtsp_sub_url_json" "$codec1_json" "$width1" "$height1" "$fps1" \
      "$frigate_record_url_json" "$frigate_detect_url_json" "$frigate_detect_source_json" \
      "$onvif_port" "$onvif_device_service_url_json" "$onvif_stream_policy_json" \
      "$mqtt_enabled_flag" "$mqtt_broker_host_json" "$mqtt_broker_port" "$mqtt_username_json" "$mqtt_password_json" "$mqtt_client_id_json" "$mqtt_discovery_enabled" "$mqtt_discovery_prefix_json" "$mqtt_topic_root_json" "$mqtt_command_topic_json" "$mqtt_availability_topic_json" "$mqtt_health_topic_json" "$mqtt_motion_state_topic_json" "$mqtt_event_topic_json" "$mqtt_snapshot_last_path_topic_json" "$mqtt_integration_manifest_topic_json" "$mqtt_integration_selftest_topic_json" "$mqtt_command_result_topic_json" "$mqtt_command_last_result_topic_json" "$mqtt_repair_last_result_topic_json"
    ;;

  healthsnapshot)
    HEALTH_SNAP_CACHE="/tmp/health_snapshot.cache"
    HEALTH_SNAP_TTL=3
    _read_now_ts
    _hs_now="$now_ts"
    _hs_cached=""
    if [ -f "$HEALTH_SNAP_CACHE" ]; then
      { read -r _hs_snap_ts; read -r _hs_cached; } < "$HEALTH_SNAP_CACHE" 2>/dev/null || true
      case "$_hs_snap_ts" in ''|*[!0-9]*) _hs_snap_ts=0 ;; esac
      [ $((_hs_now - _hs_snap_ts)) -lt "$HEALTH_SNAP_TTL" ] && [ -n "$_hs_cached" ] || _hs_cached=""
    fi
    if [ -n "$_hs_cached" ]; then
      printf '%s\n' "$_hs_cached"
    else
    # Load all configs needed for a full state overview
    load_conf_file /mnt/config/boot.conf
    load_conf_file /mnt/config/service_trim.conf
    load_conf_file /mnt/config/rtspserver.conf
    load_conf_file /mnt/config/mqtt.conf
    load_conf_file /mnt/config/recording.conf
    load_conf_file /mnt/config/sound_detection.conf

    load_or_compute_usage_metrics
    profile="$(get_perf_profile)"
    load_lum_awb
    get_ui_ultralite_mode
    get_security_and_mqtt_flags
    read_chip_temperature
    read_power_telemetry
    read_reboot_epoch
    default_password_active="$(default_password_active_flag)"
    default_password_active="$(sanitize_int "$default_password_active" 0)"
    read_rtsp_stream_summary

    if [ -r /proc/sys/kernel/hostname ]; then
      read -r health_hostname < /proc/sys/kernel/hostname
    else
      health_hostname="$(hostname 2>/dev/null)"
    fi
    health_hostname_json="$(json_escape "$health_hostname")"

    health_time_utc="$(_format_iso8601_utc "$_hs_now")"
    health_time_utc_json="$(json_escape "$health_time_utc")"

    uptime_seconds=0
    if [ -r /proc/uptime ]; then
      read -r uptime_raw _ < /proc/uptime
      uptime_seconds="${uptime_raw%.*}"
      uptime_seconds="$(sanitize_int "$uptime_seconds" 0)"
    fi

    profile_json="$(json_escape "$profile")"
    lum_json="$(json_escape "$lum_value")"
    awb_json="$(json_escape "$awb_value")"
    chip_temp_text_json="$(json_escape "$chip_temp_text")"
    power_voltage_text_json="$(json_escape "$power_voltage_text")"
    power_estimated_text_json="$(json_escape "$power_estimated_text")"
    web_mode_json="$(json_escape "$(get_cfg WEB_MODE full)")"
    codec0_json="$(json_escape "$codec0_name")"
    codec1_json="$(json_escape "$codec1_name")"
    watchdog_json="$(last_watchdog_event_json)"

    rtsp_state_json="$(service_state_json /mnt/controlscripts/rtsp-h26x)"
    onvif_state_json="$(service_state_json /mnt/controlscripts/onvif)"

    # SD Card Read-Only check
    sd_readonly=1
    if mount | grep "/mmcblk" | grep -q "rw,"; then
      sd_readonly=0
    fi

    # CSRF Token
    csrf_token=""
    if [ -r /tmp/csrf_token ]; then
        read -r csrf_token < /tmp/csrf_token
        csrf_token="$(printf '%s' "$csrf_token" | tr -cd '0-9a-fA-F')"
    fi

    _hs_result="{\"timestamp_utc\":\"$health_time_utc_json\",\"hostname\":\"$health_hostname_json\",\"uptime_seconds\":$uptime_seconds,\"sysusage\":\"CPU: $cpu% RAM: $mem_used/$mem_total kB\",\"cpu\":$cpu,\"ram_used_kb\":$mem_used,\"ram_total_kb\":$mem_total,\"ram_percent\":$ram_percent,\"chip_temp_c\":$chip_temp_json,\"chip_temp_text\":\"$chip_temp_text_json\",\"perfprofile\":\"$profile_json\",\"lum\":\"$lum_json\",\"awb\":\"$awb_json\",\"ui_ultralite_mode\":$ui_mode,\"web_mode\":\"$web_mode_json\",\"security_hardening_mode\":$security_hardening_mode,\"mqtt_enabled\":$mqtt_enabled,\"mqtt_discovery_enabled\":$mqtt_discovery,\"reboot_epoch\":$reboot_epoch,\"default_password_active\":$default_password_active,\"sd_readonly\":$sd_readonly,\"csrf_token\":\"$csrf_token\",\"power_voltage_mv\":$power_voltage_mv_json,\"power_voltage_text\":\"$power_voltage_text_json\",\"power_sensor_raw\":$power_sensor_raw_json,\"power_sensor_path\":\"$power_sensor_path_json\",\"power_estimate_enabled\":$power_estimate_enabled,\"power_estimated_mw\":$power_estimated_mw_json,\"power_estimated_text\":\"$power_estimated_text_json\",\"power_estimated_current_ma\":$power_estimated_current_ma_json,\"rtsp\":{\"service\":$rtsp_state_json,\"port\":$rtsp_port,\"main\":{\"path\":\"video0_unicast\",\"codec\":\"$codec0_json\",\"width\":$width0,\"height\":$height0,\"fps\":$fps0},\"sub\":{\"path\":\"video1_unicast\",\"codec\":\"$codec1_json\",\"width\":$width1,\"height\":$height1,\"fps\":$fps1}},\"onvif\":{\"service\":$onvif_state_json},\"last_watchdog_event\":\"$watchdog_json\"}"
    { printf '%s\n' "$_hs_now"; printf '%s\n' "$_hs_result"; } > "$HEALTH_SNAP_CACHE" 2>/dev/null || true
    printf '%s\n' "$_hs_result"
    fi
    ;;

  isp_tune)
    # Live image tuning: configured values, ISP_TUNE flag and what the
    # tc100_rtsp reports as applied (/var/run/isp_tune.status).
    . /mnt/scripts/isp-tune.sh
    isp_tune_json
    ;;

  dashinfo)
    # What changes rarely, for the dashboard cards (read once a minute); answered from dashinfo_cached.
    dashinfo_cached
    ;;

  fullconfig)
    # This command returns ALL configurable values for the UI to populate its tabs.
    # It avoids multiple requests and keeps everything in sync.
    load_conf_file /mnt/config/boot.conf
    _iprofile="$(get_cfg INTEGRATION_PROFILE default)"
    load_conf_file /mnt/config/rtspserver.conf
    load_conf_file /mnt/config/mqtt.conf
    load_conf_file /mnt/config/service_trim.conf
    fullconfig_hostname="$(read_single_config /mnt/config/hostname.conf TC100-CAMERA)"
    fullconfig_timezone="$(read_single_config /mnt/config/timezone.conf UTC+0)"
    fullconfig_ntp="$(read_single_config /mnt/config/ntp_srv.conf pool.ntp.org)"
    load_conf_file /mnt/config/motion.conf
    load_conf_file /mnt/config/daynight.conf   # 3.0 day/night thresholds (luminance)
    load_conf_file /mnt/config/telnetd.conf
    # Sound detection runs in every profile since 1.8.4 (the level is
    # measured inside the RTSP server): the Settings switch showed "off" on
    # frigate_ha cameras where it was on.
    load_conf_file /mnt/config/sound_detection.conf
    if [ "$_iprofile" != "frigate_ha" ]; then
      load_conf_file /mnt/config/recording.conf
      load_conf_file /mnt/config/telegram.conf
    fi
    
    read_rtsp_stream_summary
    detect_primary_ip
    
    # ISP / OSD Specifics
    osdenabled="$(truthy_flag "$(get_cfg osdenabled 0)")"
    osdtext_raw="$(get_cfg osdtext "")"
    osdtext_json="$(json_escape "$osdtext_raw")"
    
    # Audio specifics
    samplerate="$(get_cfg samplerate 8000)"
    audio_vol="$(get_cfg volume 8)"
    
    # MQTT particulars
    mqtt_enabled="$(truthy_flag "$(get_cfg MQTT_ENABLE 0)")"
    mqtt_discovery="$(truthy_flag "$(get_cfg MQTT_HA_DISCOVERY_ENABLE 1)")"
    
    # Reboot epoch calculation (needed for uptime display)
    read_reboot_epoch
    
    # System info
    if [ -r /proc/sys/kernel/hostname ]; then
      read -r health_hostname < /proc/sys/kernel/hostname
    else
      health_hostname="$(hostname 2>/dev/null)"
    fi

    # Peripheral & Specialized status.
    # LEDs are read from sysfs, NOT from boot.conf: the config records the last
    # requested INTENT, while the LED can be changed by motion blink, an MQTT
    # command or a controlscript without the config ever being rewritten. Worse,
    # FRONT_LED/RED_LED were absent from boot.conf.dist, so get_cfg fell through
    # to 0 and the dashboard reported "off" permanently while the LED was lit.
    # mqtt-bridge.sh already reads sysfs — this makes the web UI agree with it
    # and with `controlscripts/front-led status`. Any non-"1" brightness (the
    # panel supports 0..255) is reported as off, matching led() in
    # common_functions.sh.
    front_led_state=0
    if [ -r /sys/class/leds/blue_led/brightness ]; then
      read -r _led_raw < /sys/class/leds/blue_led/brightness 2>/dev/null
      [ "$_led_raw" = "1" ] && front_led_state=1
    elif [ -r /sys/class/leds/blue/brightness ]; then
      read -r _led_raw < /sys/class/leds/blue/brightness 2>/dev/null
      [ "$_led_raw" = "1" ] && front_led_state=1
    fi
    red_led_state=0
    if [ -r /sys/class/leds/red_led/brightness ]; then
      read -r _led_raw < /sys/class/leds/red_led/brightness 2>/dev/null
      [ "$_led_raw" = "1" ] && red_led_state=1
    elif [ -r /sys/class/leds/red/brightness ]; then
      read -r _led_raw < /sys/class/leds/red/brightness 2>/dev/null
      [ "$_led_raw" = "1" ] && red_led_state=1
    fi
    syslog_enabled="$(truthy_flag "$(get_cfg SYSLOG_ENABLE 0)")"
    telegram_enabled="$(truthy_flag "$(get_cfg TELEGRAM_ENABLE 0)")"
    privacy_enabled="$(truthy_flag "$(get_cfg PRIVACY_MODE 0)")"
    
    # Feature blocks
    printf '{"boot":{"web_mode":"%s","perf_profile":"%s","service_trim":%s,"topology":"%s","ultralite_port":%s,"lightweight_mode":%s,"security_hardening":%s},"video":{"rtsp_port":%s,"main":{"codec":%s,"profile":%s,"width":%s,"height":%s,"fps":%s,"bitrate":%s,"gop":%s,"format":"%s","minqp":%s,"maxqp":%s,"smartmode":%s,"smartgoplen":%s,"smartquality":%s,"smartstatic":%s,"maxkbps":%s,"targetkbps":%s},"sub":{"codec":%s,"profile":%s,"width":%s,"height":%s,"fps":%s,"bitrate":%s,"gop":%s,"format":"%s","minqp":%s,"maxqp":%s,"smartmode":%s,"smartgoplen":%s,"smartquality":%s,"smartstatic":%s,"maxkbps":%s,"targetkbps":%s},"flip":%s,"rtsp_log":%s},"audio":{"samplerate":%s,"volume":%s,"codec_main":%s,"codec_sub":%s,"mic_sens":%s},"isp":{"daynight_lum":%s,"daynight_awb":%s,"nightday_lum":%s,"nightday_awb":%s},"osd":{"enabled":%s,"text":"%s","alpha":%s,"fontsize0":%s,"frontcolor":%s,"backcolor":%s,"edgecolor":%s,"x0":%s,"y0":%s},"mqtt":{"enabled":%s,"host":"%s","port":%s,"user":"%s","topic_root":"%s","discovery":%s,"discovery_prefix":"%s"},"recording":{"postrec":%s,"maxduration":%s,"reserved_mb":%s,"motion_activated":%s},"system":{"hostname":"%s","timezone":"%s","ntp_server":"%s","setup_wizard_done":%s,"gateway":"%s","reboot_schedule":{"enable":%s,"hour":%s,"min":%s,"dow":"%s"},"mem_guard":{"enable":%s,"warn_kb":%s,"crit_kb":%s,"interval":%s,"hits_warn":%s,"hits_crit":%s,"cooldown":%s}},"timelapse":{"interval":%s,"duration":%s},"services":{"telnet_port":%s,"sound_det_enable":%s,"sound_det_threshold":%s,"sound_det_interval":%s,"motion_sens":%s,"motion_led":%s},"telegram":{"enabled":%s,"token":"%s","chat_id":"%s"},"syslog":{"enabled":%s,"host":"%s","port":%s},"frigate":{"url":"%s","camera":"%s"},"peripherals":{"led_front":%s,"led_red":%s,"privacy":%s}}\n' \
      "$(json_escape "$(get_cfg WEB_MODE full)")" "$(get_perf_profile)" "$(truthy_flag "$(get_cfg SERVICE_TRIM 0)")" "$(json_escape "$(get_cfg STREAM_TOPOLOGY dual)")" "$(sanitize_int "$(get_cfg ULTRALITE_HTTP_PORT 80)" 80)" "$(truthy_flag "$(get_cfg LIGHTWEIGHT_MODE 0)")" "$(truthy_flag "$(get_cfg SECURITY_HARDENING_MODE 0)")" \
      "$rtsp_port" \
      "$codec0" "$profile0" "$width0" "$height0" "$fps0" "$bps0" "$goplen0" "$brmode0" "$minqp0" "$maxqp0" "$smartmode0" "$smartgoplen0" "$smartquality0" "$smartstatic0" "$maxkbps0" "$targetkbps0" \
      "$codec1" "$profile1" "$width1" "$height1" "$fps1" "$bps1" "$goplen1" "$brmode1" "$minqp1" "$maxqp1" "$smartmode1" "$smartgoplen1" "$smartquality1" "$smartstatic1" "$maxkbps1" "$targetkbps1" \
      "$(sanitize_int "$(get_cfg imageflip 0)" 0)" "$(truthy_flag "$(get_cfg RTSPLOGENABLED 0)")" \
      "$samplerate" "$audio_vol" "$(sanitize_int "$(get_cfg 2_codec 4)" 4)" "$(sanitize_int "$(get_cfg 3_codec 4)" 4)" "$audio_vol" \
      "$(sanitize_int "$(get_cfg LUMA_NIGHT 40)" 40)" "$(sanitize_int "$(get_cfg daynightawb 100000)" 100000)" "$(sanitize_int "$(get_cfg LUMA_DAY 100)" 100)" "$(sanitize_int "$(get_cfg nightdayawb 50000)" 50000)" \
      "$osdenabled" "$osdtext_json" "$(sanitize_int "$(get_cfg osdalpha 128)" 128)" "$(sanitize_int "$(get_cfg 0_osdfontsize 24)" 24)" "$(sanitize_int "$(get_cfg osdfrontcolor 1)" 1)" "$(sanitize_int "$(get_cfg osdbackcolor 0)" 0)" "$(sanitize_int "$(get_cfg osdedgecolor 2)" 2)" "$(sanitize_int "$(get_cfg 0_osdx 10)" 10)" "$(sanitize_int "$(get_cfg 0_osdy 10)" 10)" \
      "$mqtt_enabled" "$(json_escape "$(get_cfg MQTT_HOST 127.0.0.1)")" "$(sanitize_int "$(get_cfg MQTT_PORT 1883)" 1883)" "$(json_escape "$(get_cfg MQTT_USER "")")" "$(json_escape "$(get_cfg MQTT_TOPIC_ROOT tc100/camera)")" "$mqtt_discovery" "$(json_escape "$(get_cfg MQTT_HA_DISCOVERY_PREFIX homeassistant)")" \
      "$(sanitize_int "$(get_cfg rec_postrecord_sec 10)" 10)" "$(sanitize_int "$(get_cfg rec_file_duration_sec 60)" 60)" "$(sanitize_int "$(get_cfg rec_reserverd_disk_mb 1024)" 1024)" "$(truthy_flag "$(get_cfg rec_motion_activated 0)")" \
      "$(json_escape "$fullconfig_hostname")" "$(json_escape "$fullconfig_timezone")" "$(json_escape "$fullconfig_ntp")" "$(truthy_flag "$(get_cfg SETUP_WIZARD_DONE 0)")" "$(json_escape "$(get_live_gateway)")" "$(truthy_flag "$(get_cfg REBOOT_SCHEDULE_ENABLE 0)")" "$(sanitize_int "$(get_cfg REBOOT_SCHEDULE_HOUR 4)" 4)" "$(sanitize_int "$(get_cfg REBOOT_SCHEDULE_MINUTE 0)" 0)" "$(json_escape "$(get_cfg REBOOT_SCHEDULE_WEEKDAY "*")")" \
      "$(truthy_flag "$(get_cfg MEM_GUARD_ENABLE 0)")" "$(sanitize_int "$(get_cfg MEM_GUARD_WARN_KB 6144)" 6144)" "$(sanitize_int "$(get_cfg MEM_GUARD_CRITICAL_KB 3072)" 3072)" "$(sanitize_int "$(get_cfg MEM_GUARD_INTERVAL_SECONDS 20)" 20)" "$(sanitize_int "$(get_cfg MEM_GUARD_WARN_HITS 2)" 2)" "$(sanitize_int "$(get_cfg MEM_GUARD_CRITICAL_HITS 1)" 1)" "$(sanitize_int "$(get_cfg MEM_GUARD_COOLDOWN_SECONDS 120)" 120)" \
      "$(sanitize_int "$(get_cfg tlinterval 10)" 10)" "$(sanitize_int "$(get_cfg tlduration 0)" 0)" \
      "$(sanitize_int "$(get_cfg TELNET_PORT 23)" 23)" "$(truthy_flag "$(get_cfg ENABLE 0)")" "$(_st_db="$(get_cfg THRESHOLD_DB -24)"; case "$_st_db" in -[0-9]|-[0-9][0-9]|0) echo "$_st_db" ;; *) echo -24 ;; esac)" "$(sanitize_int "$(get_cfg INTERVAL 2)" 5)" "$(sanitize_int "$(get_cfg mdsens 50)" 50)" "$(truthy_flag "$(get_cfg motion_trigger_led 0)")" \
      "$telegram_enabled" "$(json_escape "$(get_cfg apiToken "")")" "$(json_escape "$(get_cfg userChatId "")")" \
      "$syslog_enabled" "$(json_escape "$(get_cfg SYSLOG_HOST "")")" "$(sanitize_int "$(get_cfg SYSLOG_PORT 514)" 514)" \
      "$(json_escape "$(read_conf_value /mnt/config/frigate_live.conf FRIGATE_URL "")")" "$(json_escape "$(read_conf_value /mnt/config/frigate_live.conf FRIGATE_CAMERA "")")" \
      "$front_led_state" "$red_led_state" "$privacy_enabled"
    ;;

  perfprofile)
    get_perf_profile
    ;;

  get_events)
    # Source event logger
    . /mnt/scripts/event-logger.sh

    since_param="${F_since:-0}"
    limit_param="${F_limit:-50}"

    # Validate parameters
    since_param="$(sanitize_int "$since_param" 0)"
    limit_param="$(sanitize_int "$limit_param" 50)"
    if [ "$limit_param" -gt 200 ]; then
      limit_param=200
    fi

    get_events_since "$since_param" "$limit_param"
    ;;

  list_presets)
    presets_dir="/mnt/config/presets"
    mkdir -p "$presets_dir"

    if wants_json_response; then
      printf '{"presets":['
      first=1
      for preset_file in "$presets_dir"/*.json; do
        [ -f "$preset_file" ] || continue
        if [ "$first" = "1" ]; then
          first=0
        else
          printf ','
        fi
        preset_name=$(basename "$preset_file" .json)
        printf '{"name":"'
        json_escape "$(basename "$preset_file" .json)"
        printf '"}'
      done
      printf ']}'
    else
      # busybox basename has no -s flag; iterate and strip the suffix per file.
      for _pf in "$presets_dir"/*.json; do
        [ -f "$_pf" ] || continue
        basename "$_pf" .json
      done
    fi
    ;;

  load_preset)
    preset_name="${F_name:-}"
    presets_dir="/mnt/config/presets"

    if [ -z "$preset_name" ]; then
      if wants_json_response; then
        json_error "INVALID_PRESET" "Preset name required"
      else
        echo "ERROR: Preset name required"
      fi
    # SECURITY: validate the name before building a path, exactly like
    # save_preset/delete_preset do. Without this, name=../../../tmp/update_status
    # reads /mnt/config/presets/../../../tmp/update_status.json — an arbitrary
    # file read outside the presets directory. Fork-free case idiom (busybox-safe,
    # no grep -E) — rejects empty and anything with a char outside [A-Za-z0-9_-],
    # which blocks '/' and '.'.
    else
      case "$preset_name" in
        ''|*[!A-Za-z0-9_-]*)
          if wants_json_response; then
            json_error "INVALID_NAME" "Invalid preset name"
          else
            echo "ERROR: Invalid preset name"
          fi
          preset_name="" ;;
      esac
    fi
    if [ -n "$preset_name" ]; then
      preset_file="$presets_dir/$preset_name.json"
      if [ -f "$preset_file" ]; then
        if wants_json_response; then
          printf '{"preset":'
          cat "$preset_file"
          printf '}'
        else
          cat "$preset_file"
        fi
      else
        if wants_json_response; then
          json_error "PRESET_NOT_FOUND" "Preset '$preset_name' not found"
        else
          echo "ERROR: Preset '$preset_name' not found"
        fi
      fi
    fi
    ;;

  frigateyaml)
    # Ready-to-paste Frigate config. Defaults to a go2rtc restream because the
    # AK3918 tolerates very few concurrent RTSP clients — one restream feeds
    # Frigate's detect + record + live view over a single connection to the
    # camera. Targets the current Frigate schema (0.14+): explicit
    # detect.enabled, role-split ffmpeg inputs, and NONE of the deprecated
    # record.retain.days / record.events keys (those are hard config-load
    # failures now). Use cmd=frigateyaml&redact=1 to blank credentials for sharing.
    fy_redact="$(truthy_flag "$F_redact")"
    if [ -r /proc/sys/kernel/hostname ]; then
      read -r fy_hostname < /proc/sys/kernel/hostname
    else
      fy_hostname="$(hostname 2>/dev/null)"
    fi
    [ -n "$fy_hostname" ] || fy_hostname="tc100-camera"
    fy_slug="$(slugify_value "$fy_hostname")"
    [ -n "$fy_slug" ] || fy_slug="tc100_camera"

    detect_primary_ip
    read_rtsp_stream_summary
    fy_user="$(read_conf_value /mnt/config/rtspserver.conf USERNAME root)"
    fy_pass="$(read_conf_value /mnt/config/rtspserver.conf USERPASSWORD pass)"
    fy_sub_enabled="$(truthy_flag "$(read_conf_value /mnt/config/boot.conf RTSP_SUBSTREAM 1)")"

    if [ "$fy_redact" = "1" ]; then
      fy_auth="USERNAME:PASSWORD@"
    elif [ -n "$fy_user" ]; then
      fy_auth="${fy_user}:${fy_pass}@"
    else
      fy_auth=""
    fi

    if [ "$fy_sub_enabled" = "1" ]; then
      fy_detect_w="$width1"; fy_detect_h="$height1"; fy_detect_source_fps="$fps1"
      fy_detect_stream="${fy_slug}_sub"
    else
      fy_detect_w="$width0"; fy_detect_h="$height0"; fy_detect_source_fps="$fps0"
      fy_detect_stream="$fy_slug"
    fi
    # Frigate recommends 5 fps for object detection.
    fy_detect_fps="$fy_detect_source_fps"
    [ "$fy_detect_fps" -gt 5 ] && fy_detect_fps=5

    fy_mqtt_enabled="$(truthy_flag "$(read_conf_value /mnt/config/mqtt.conf MQTT_ENABLE 0)")"
    fy_mqtt_host="$(read_conf_value /mnt/config/mqtt.conf MQTT_HOST 127.0.0.1)"
    fy_mqtt_port="$(sanitize_int "$(read_conf_value /mnt/config/mqtt.conf MQTT_PORT 1883)" 1883)"
    fy_mqtt_user="$(read_conf_value /mnt/config/mqtt.conf MQTT_USER "")"

    printf '# Frigate config for %s (%s)\n' "$fy_hostname" "$fy_slug"
    printf '# Generated by TC100 state.cgi?cmd=frigateyaml. Merge these sections\n'
    printf '# into your Frigate config.yml. Requires Frigate 0.14+.\n'
    printf '#\n'
    printf '# Streams: main=video0_unicast (%sx%s@%s, %s), sub=video1_unicast (%sx%s@%s, %s), substream_enabled=%s\n' \
      "$width0" "$height0" "$fps0" "$(codec_name "$codec0")" "$width1" "$height1" "$fps1" "$(codec_name "$codec1")" "$fy_sub_enabled"
    if [ "$fy_redact" = "1" ]; then
      printf '# NOTE: credentials redacted — replace USERNAME/PASSWORD below.\n'
    fi
    printf '\n'

    # mqtt section (only meaningful if the camera's MQTT bridge is enabled)
    printf 'mqtt:\n'
    if [ "$fy_mqtt_enabled" = "1" ]; then
      printf '  enabled: true\n'
      printf '  host: %s\n' "$fy_mqtt_host"
      printf '  port: %s\n' "$fy_mqtt_port"
      if [ -n "$fy_mqtt_user" ] && [ "$fy_redact" != "1" ]; then
        printf '  user: %s\n' "$fy_mqtt_user"
        printf '  # password: <set in your Frigate secrets>\n'
      fi
    else
      printf '  enabled: false\n'
    fi
    printf '\n'

    # go2rtc restream
    printf 'go2rtc:\n'
    printf '  streams:\n'
    printf '    %s:\n' "$fy_slug"
    printf '      - rtsp://%s%s:%s/video0_unicast#backchannel=0\n' "$fy_auth" "$primary_ip" "$rtsp_port"
    if [ "$fy_sub_enabled" = "1" ]; then
      printf '    %s_sub:\n' "$fy_slug"
      printf '      - rtsp://%s%s:%s/video1_unicast#backchannel=0\n' "$fy_auth" "$primary_ip" "$rtsp_port"
    fi
    printf '\n'

    # camera
    printf 'cameras:\n'
    printf '  %s:\n' "$fy_slug"
    printf '    enabled: true\n'
    printf '    ffmpeg:\n'
    printf '      inputs:\n'
    printf '        - path: rtsp://127.0.0.1:8554/%s\n' "$fy_slug"
    printf '          input_args: preset-rtsp-restream\n'
    if [ "$fy_sub_enabled" = "1" ]; then
      printf '          roles: [record]\n'
      printf '        - path: rtsp://127.0.0.1:8554/%s_sub\n' "$fy_slug"
      printf '          input_args: preset-rtsp-restream\n'
      printf '          roles: [detect]\n'
    else
      # No sub-stream: one input carries both roles. Detecting on the full-res
      # main stream is heavier — enabling RTSP_SUBSTREAM is recommended.
      printf '          roles: [record, detect]\n'
    fi
    printf '    detect:\n'
    printf '      enabled: true\n'
    printf '      width: %s\n' "$fy_detect_w"
    printf '      height: %s\n' "$fy_detect_h"
    printf '      fps: %s\n' "$fy_detect_fps"
    printf '    live:\n'
    printf '      streams:\n'
    printf '        Main Stream: %s\n' "$fy_slug"
    if [ "$fy_sub_enabled" = "1" ]; then
      printf '        Sub Stream: %s_sub\n' "$fy_slug"
    fi
    printf '    record:\n'
    printf '      enabled: true\n'
    if [ "$(codec_name "$codec0")" = "H265" ]; then
      printf '      apple_compatibility: true\n'
    fi
    printf '      # Current Frigate schema (0.14+): event-based retention lives\n'
    printf '      # under alerts/detections, NOT the deprecated record.retain.days.\n'
    printf '      alerts:\n'
    printf '        retain:\n'
    printf '          days: 14\n'
    printf '      detections:\n'
    printf '        retain:\n'
    printf '          days: 14\n'
    printf '    snapshots:\n'
    printf '      enabled: true\n'
    printf '    objects:\n'
    printf '      track:\n'
    printf '        - person\n'
    ;;

  *)
    echo "Unsupported command '$F_cmd'"
    ;;
  esac
  fi

exit 0
