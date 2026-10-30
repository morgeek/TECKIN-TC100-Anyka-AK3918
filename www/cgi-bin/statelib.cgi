#!/bin/sh
# Helpers shared by state.cgi and statusline.cgi: everything the status line (the poll of every open page) needs.
# Sourced, never run. statusline.cgi sources only this file (not func.cgi, not state.cgi): keep it small.
# conf_get is the same function as in func.cgi (tests/test_statusline.py checks that they stay identical).

# tr(1) shim, as in func.cgi: busybox ships the applet without a symlink on the CGI PATH.
if ! command -v tr >/dev/null 2>&1; then
    tr() { busybox tr "$@"; }
fi

# conf_get VAR FILE KEY DEFAULT: read one key of a key=value file into a variable, without a subshell.
conf_get() {
  _cg_val="$4"
  if [ -r "$2" ]; then
    while IFS= read -r _cg_line; do
      case "$_cg_line" in
        ''|'#'*) continue ;;
        "$3"=*) _cg_val="${_cg_line#*=}"; break ;;
      esac
    done < "$2"
  fi
  eval "$1=\$_cg_val"
}

USAGE_CACHE_FILE="/tmp/state_usage.cache"
USAGE_CACHE_TTL_SECONDS=2
CPU_USAGE_STATE_FILE="/tmp/state_cpu_usage.state"
CPU_USAGE_MIN_DELTA_TICKS=20
PERFPROFILE_CACHE_FILE="/tmp/state_perfprofile.cache"
PERFPROFILE_CACHE_TTL_SECONDS=5
PWD_CACHE_FILE="/tmp/state_pwd.cache"
PWD_CACHE_TTL_SECONDS=120

_SCRIPT_BTIME=0
_read_script_btime() {
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _SCRIPT_BTIME="$_v" && break
  done < /proc/stat
}
_read_now_ts() {
  [ "$_SCRIPT_BTIME" -gt 0 ] || _read_script_btime
  read -r _rnt_up _ < /proc/uptime
  now_ts=$((_SCRIPT_BTIME + ${_rnt_up%.*}))
  [ "$now_ts" -gt 0 ] || now_ts=0
}

get_current_cpu_usage_fast() {
  cpu_active_prev=0
  cpu_total_prev=0
  cpu_util_prev=0
  case "$CPU_USAGE_MIN_DELTA_TICKS" in
    ''|*[!0-9]*) CPU_USAGE_MIN_DELTA_TICKS=20 ;;
  esac
  [ "$CPU_USAGE_MIN_DELTA_TICKS" -lt 1 ] && CPU_USAGE_MIN_DELTA_TICKS=1

  if [ -f "$CPU_USAGE_STATE_FILE" ]; then
    read -r cpu_active_prev cpu_total_prev cpu_util_prev < "$CPU_USAGE_STATE_FILE"
    case "$cpu_active_prev" in ''|*[!0-9]*) cpu_active_prev=0 ;; esac
    case "$cpu_total_prev" in ''|*[!0-9]*) cpu_total_prev=0 ;; esac
    case "$cpu_util_prev" in ''|*[!0-9]*) cpu_util_prev=0 ;; esac
  fi

  # /proc/stat layout:
  # cpu user nice system idle iowait irq softirq steal guest guest_nice
  read -r _ user nice system idle iowait irq softirq steal _ _ < /proc/stat
  cpu_active_cur=$((user + nice + system + irq + softirq + steal))
  cpu_total_cur=$((cpu_active_cur + idle + iowait))

  delta_total=$((cpu_total_cur - cpu_total_prev))
  delta_active=$((cpu_active_cur - cpu_active_prev))

  if [ "$cpu_total_prev" -le 0 ] || [ "$delta_total" -lt 0 ]; then
    printf '%s %s %s\n' "$cpu_active_cur" "$cpu_total_cur" 0 > "$CPU_USAGE_STATE_FILE"
    cpu_util=0
    echo "0"
    return
  fi

  if [ "$delta_total" -lt "$CPU_USAGE_MIN_DELTA_TICKS" ]; then
    # Calls happened too close together; keep previous stable sample.
    cpu_util="$cpu_util_prev"
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
  printf '%s %s %s\n' "$cpu_active_cur" "$cpu_total_cur" "$cpu_util" > "$CPU_USAGE_STATE_FILE"
  echo "$cpu_util"
}

get_memory_usage_fast() {
  mem_total=0
  mem_available=0
  mem_free=0
  mem_buffers=0
  mem_cached=0
  mem_sreclaimable=0
  mem_shmem=0

  while IFS=' ' read -r key value _; do
    case "$key" in
      MemTotal:)
        mem_total="$value"
        ;;
      MemAvailable:)
        mem_available="$value"
        ;;
      MemFree:)
        mem_free="$value"
        ;;
      Buffers:)
        mem_buffers="$value"
        ;;
      Cached:)
        mem_cached="$value"
        ;;
      SReclaimable:)
        mem_sreclaimable="$value"
        ;;
      Shmem:)
        mem_shmem="$value"
        ;;
    esac
    if [ "$mem_total" -gt 0 ] && [ "$mem_available" -gt 0 ]; then
      break
    fi
  done < /proc/meminfo

  if [ "$mem_available" -le 0 ]; then
    mem_available=$((mem_free + mem_buffers + mem_cached + mem_sreclaimable - mem_shmem))
    if [ "$mem_available" -lt 0 ]; then
      mem_available=0
    fi
  fi
  if [ "$mem_available" -gt "$mem_total" ]; then
    mem_available="$mem_total"
  fi

  mem_used=$((mem_total - mem_available))
}

compute_usage_metrics() {
  get_current_cpu_usage_fast >/dev/null    # sets cpu_util (no subshell)
  cpu="$cpu_util"
  get_memory_usage_fast
  ram_percent=0
  if [ "$mem_total" -gt 0 ]; then
    ram_percent=$((100 * mem_used / mem_total))
    if [ "$ram_percent" -lt 0 ]; then
      ram_percent=0
    elif [ "$ram_percent" -gt 100 ]; then
      ram_percent=100
    fi
  fi
}

load_cached_usage_metrics() {
  [ -f "$USAGE_CACHE_FILE" ] || return 1

  cached_ts=0
  cached_cpu=0
  cached_mem_used=0
  cached_mem_total=0
  cached_ram_percent=0

  read -r cached_ts cached_cpu cached_mem_used cached_mem_total cached_ram_percent < "$USAGE_CACHE_FILE" || return 1

  for value in "$cached_ts" "$cached_cpu" "$cached_mem_used" "$cached_mem_total" "$cached_ram_percent"; do
    case "$value" in
      ''|*[!0-9]*)
        return 1
        ;;
    esac
  done

  _read_now_ts
  [ "$now_ts" -gt 0 ] || return 1
  [ "$cached_ts" -le "$now_ts" ] || return 1

  age=$((now_ts - cached_ts))
  [ "$age" -le "$USAGE_CACHE_TTL_SECONDS" ] || return 1

  cpu="$cached_cpu"
  mem_used="$cached_mem_used"
  mem_total="$cached_mem_total"
  ram_percent="$cached_ram_percent"
  return 0
}

save_cached_usage_metrics() {
  _read_now_ts
  [ "$now_ts" -gt 0 ] || return 0
  printf '%s %s %s %s %s\n' "$now_ts" "$cpu" "$mem_used" "$mem_total" "$ram_percent" > "$USAGE_CACHE_FILE"
}

load_or_compute_usage_metrics() {
  if load_cached_usage_metrics; then
    return 0
  fi
  compute_usage_metrics
  save_cached_usage_metrics
}

# Escapes backslash and double-quote for embedding in JSON.
#
# Fast path first: almost every value here (hostnames, profile names, paths,
# IPs) contains neither character, and this is called ~80 times per statusline
# poll — each `printf | sed` being a fork+exec pair on a 400 MHz core. The case
# test is pure shell, so the common path now costs nothing; sed is spawned only
# for the rare value that genuinely needs escaping. Output is identical.
# json_esc_to VAR VALUE: json_escape into a variable; forks only when the
# value holds a backslash or a double quote (almost never on the status line).
json_esc_to() {
  case "$2" in
    *\\*|*\"*) eval "$1=\$(json_escape \"\$2\")" ;;
    *) eval "$1=\$2" ;;
  esac
}

json_escape() {
  case "$1" in
    *\\*|*\"*) printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' ;;
    *) printf '%s' "$1" ;;
  esac
}

load_lum_awb() {
  lum_value=""
  awb_value=""

  if [ -r /var/run/lum ]; then
    read -r lum_value < /var/run/lum
  elif [ -r /tmp/cam_luma ]; then
    read -r lum_value < /tmp/cam_luma
  fi
  if [ -r /var/run/awb ]; then
    read -r awb_value < /var/run/awb
  fi
}

get_ui_ultralite_mode() {
  ui_mode=0
  conf_get WEB_MODE_VALUE /mnt/config/boot.conf WEB_MODE full
  conf_get UI_ULTRALITE_MODE_VALUE /mnt/config/boot.conf UI_ULTRALITE_MODE 0

  case "$WEB_MODE_VALUE" in
    ultra-lite|ultralite)
      ui_mode=1
      ;;
  esac

  case "$UI_ULTRALITE_MODE_VALUE" in
    1|true|on|yes|enabled)
      ui_mode=1
      ;;
  esac
}

get_security_and_mqtt_flags() {
  security_hardening_mode=0
  mqtt_enabled=0
  mqtt_discovery=0
  mqtt_last_pub_ts=0
  mqtt_last_pub_ok=-1
  mqtt_refused=0

  conf_get security_raw /mnt/config/boot.conf SECURITY_HARDENING_MODE 0
  case "$security_raw" in
    1|true|on|yes|enabled)
      security_hardening_mode=1
      ;;
  esac

  conf_get mqtt_raw /mnt/config/mqtt.conf MQTT_ENABLE 0
  case "$mqtt_raw" in
    1|true|on|yes|enabled)
      mqtt_enabled=1
      ;;
  esac

  conf_get mqtt_discovery_raw /mnt/config/mqtt.conf MQTT_HA_DISCOVERY_ENABLE 1
  case "$mqtt_discovery_raw" in
    1|true|on|yes|enabled)
      mqtt_discovery=1
      ;;
  esac

  if [ -f /tmp/mqtt_last_pub.status ]; then
    _mq_code=
    read -r _mq_ts _mq_result _mq_code < /tmp/mqtt_last_pub.status
    case "$_mq_ts" in ''|*[!0-9]*) _mq_ts=0 ;; esac
    case "$_mq_result" in
      ok)   mqtt_last_pub_ok=1 ;;
      fail) mqtt_last_pub_ok=0
            case "$_mq_code" in [1-5]) mqtt_refused=$_mq_code ;; esac ;;
    esac
    mqtt_last_pub_ts="$_mq_ts"
  fi
}

compute_perf_profile() {
  conf_get LOW_CPU_PROFILE /mnt/config/boot.conf LOW_CPU_PROFILE 0
  conf_get SERVICE_TRIM /mnt/config/service_trim.conf SERVICE_TRIM 0

  if [ "${SERVICE_TRIM:-0}" = "1" ]; then
    profile="rtsp-only"
  elif [ "${LOW_CPU_PROFILE:-0}" = "1" ]; then
    profile="low-cpu"
  else
    profile="balanced"
  fi
}

load_cached_perf_profile() {
  [ -f "$PERFPROFILE_CACHE_FILE" ] || return 1

  cached_ts=0
  cached_profile=""
  read -r cached_ts cached_profile < "$PERFPROFILE_CACHE_FILE" || return 1
  case "$cached_ts" in
    ''|*[!0-9]*)
      return 1
      ;;
  esac
  case "$cached_profile" in
    balanced|low-cpu|rtsp-only) ;;
    *)
      return 1
      ;;
  esac

  _read_now_ts
  [ "$now_ts" -gt 0 ] || return 1
  [ "$cached_ts" -le "$now_ts" ] || return 1
  age=$((now_ts - cached_ts))
  [ "$age" -le "$PERFPROFILE_CACHE_TTL_SECONDS" ] || return 1

  profile="$cached_profile"
  return 0
}

save_cached_perf_profile() {
  _read_now_ts
  [ "$now_ts" -gt 0 ] || return 0
  printf '%s %s\n' "$now_ts" "$profile" > "$PERFPROFILE_CACHE_FILE"
}

get_perf_profile() {
  if load_cached_perf_profile; then
    echo "$profile"
    return 0
  fi
  compute_perf_profile
  save_cached_perf_profile
  echo "$profile"
}

# get_wifi_quality — Wi-Fi link quality (0-100) for the dashboard gauge, read
# from /proc/net/wireless with the shell only (this runs on every statusline
# poll). The RTL8188FU reports "link" and "level" on a 0-100 scale, e.g.
#   wlan0: 0000   86.   78.    0. ...   (iwconfig: Link Quality=86/100)
# wlan1 is the idle AP interface (all zeros). Prefers wlan0, otherwise the
# first interface with a non-zero link. Sets wifi_qual_json ("null" when no
# wireless link) and wifi_iface_json.
get_wifi_quality() {
  wifi_qual_json="null"
  wifi_iface_json=""
  _gwq_src="${WIFI_PROC_FILE:-/proc/net/wireless}"
  [ -r "$_gwq_src" ] || return 0
  _gwq_best=""
  _gwq_iface=""
  while read -r _gwq_if _gwq_status _gwq_link _gwq_rest; do
    case "$_gwq_if" in *:) ;; *) continue ;; esac
    _gwq_if="${_gwq_if%:}"
    _gwq_link="${_gwq_link%%.*}"
    case "$_gwq_link" in ''|*[!0-9]*) continue ;; esac
    [ "$_gwq_link" -gt 0 ] || continue
    if [ "$_gwq_if" = "wlan0" ] || [ -z "$_gwq_best" ]; then
      _gwq_best="$_gwq_link"
      _gwq_iface="$_gwq_if"
      [ "$_gwq_if" = "wlan0" ] && break
    fi
  done < "$_gwq_src"
  [ -n "$_gwq_best" ] || return 0
  [ "$_gwq_best" -gt 100 ] && _gwq_best=100
  wifi_qual_json="$_gwq_best"
  wifi_iface_json="$_gwq_iface"
}

get_sd_usage() {
  sd_used_kb=0
  sd_total_kb=0
  sd_percent=0
  # Firmware from flash (scripts/flashboot.sh): /mnt is a RAM disk, no card.
  storage_json=sd
  if [ -r /tmp/tc100-storage ]; then
    read -r storage_json < /tmp/tc100-storage
    case "$storage_json" in flash) return 0 ;; *) storage_json=sd ;; esac
  elif [ -f /tmp/flashmode ]; then
    storage_json=flash
    # flash mode: a card, when there is one, is the video storage at /mnt/sd
    _sd_vfat=0
    while read -r _m_dev _m_mp _m_fs _m_rest; do
      case "$_m_mp $_m_fs" in "/mnt/sd vfat"|"/mnt/sd exfat") _sd_vfat=1; break ;; esac
    done < /proc/mounts
    [ "$_sd_vfat" = 1 ] || return 0
  fi
  _sd_dir=/mnt/sd

  # df output: Filesystem 1K-blocks Used Available Use% Mounted
  # BusyBox df may omit header or use slightly different columns; parse by mount point.
  while read -r _fs _total _used _avail _pct _mp _rest; do
    case "$_mp" in
      /mnt|/mnt/|/mnt/sd)
        case "$_total" in ''|*[!0-9]*) continue ;; esac
        case "$_used"  in ''|*[!0-9]*) continue ;; esac
        sd_total_kb="$_total"
        sd_used_kb="$_used"
        # _pct may be "72%" — strip trailing %
        _pct_num="${_pct%%%}"
        case "$_pct_num" in ''|*[!0-9]*) _pct_num=0 ;; esac
        sd_percent="$_pct_num"
        break
        ;;
    esac
  done <<EOF
$(df -k "$_sd_dir" 2>/dev/null | tail -n +2)
EOF
}

# Sets default_password_active (0/1) without a subshell; cached 120 s.
compute_default_password_flag() {
  if [ -f "$PWD_CACHE_FILE" ]; then
    read -r cached_ts cached_val < "$PWD_CACHE_FILE"
    _read_now_ts
    case "$cached_ts$cached_val" in ''|*[!0-9]*) ;; *)
      if [ "$now_ts" -gt 0 ] && [ "$cached_ts" -le "$now_ts" ] && [ $((now_ts - cached_ts)) -le "$PWD_CACHE_TTL_SECONDS" ]; then
        default_password_active="$cached_val"
        return 0
      fi ;;
    esac
  fi

  default_active=0
  default_hash="1d06b7785388de1501e8d57847540f6d"

  conf_get rtsp_username /mnt/config/rtspserver.conf USERNAME root
  conf_get rtsp_password /mnt/config/rtspserver.conf USERPASSWORD pass
  if [ "$rtsp_username" = "root" ] && [ "$rtsp_password" = "pass" ]; then
    default_active=1
  fi

  http_hash=""
  if [ -r /mnt/config/lighttpd.user ]; then
    IFS=: read -r _ _ http_hash < /mnt/config/lighttpd.user
    case "$http_hash" in *[!0-9a-fA-F]) http_hash="${http_hash%?}" ;; esac   # trailing CR
    if [ "$http_hash" = "$default_hash" ]; then
      default_active=1
    fi
  fi

  if [ -r /mnt/config/user.pwd ]; then
    read -r all_services_password < /mnt/config/user.pwd
    if [ "$all_services_password" = "pass" ]; then
      default_active=1
    fi
  fi

  default_password_active="$default_active"
  _read_now_ts; printf '%s %s\n' "$now_ts" "$default_active" > "$PWD_CACHE_FILE"
}

statusline_json() {
  # Polled by every open page: shell built-ins only, no subshell on the
  # usual path (each fork costs ~10 ms of the 400 MHz CPU).
  load_or_compute_usage_metrics
  load_cached_perf_profile || { compute_perf_profile; save_cached_perf_profile; }
  load_lum_awb
  get_ui_ultralite_mode
  get_security_and_mqtt_flags
  get_sd_usage
  get_wifi_quality
  compute_default_password_flag
  case "$default_password_active" in 0|1) ;; *) default_password_active=0 ;; esac
  json_esc_to profile_json "$profile"
  json_esc_to lum_json "$lum_value"
  json_esc_to awb_json "$awb_value"
  json_esc_to web_mode_json "$WEB_MODE_VALUE"
  csrf_token=""
  # Ensure a CSRF token exists so the client ALWAYS receives one on its first
  # statusline poll. Without this, if no CGI had called csrf_guard since boot
  # the token file would be absent, the client would hold no token, and the
  # first authenticated POST (now that action.cgi enforces CSRF) would 403 —
  # a bootstrap lock-out. Generating it here (once, when missing) closes that.
  if [ ! -s /tmp/csrf_token ]; then
      if [ -r /dev/urandom ]; then
          _stt="$(head -c 16 /dev/urandom | hexdump -e '16/1 "%02x"' 2>/dev/null)"
      fi
      [ -n "$_stt" ] || _stt="$(date +%s%N | md5sum | cut -c1-32)"
      printf '%s' "$_stt" > /tmp/csrf_token 2>/dev/null || true
  fi
  if [ -r /tmp/csrf_token ]; then
      read -r csrf_token < /tmp/csrf_token
      # Strip any non-hex characters for safety (only forks if there are any)
      case "$csrf_token" in *[!0-9a-fA-F]*) csrf_token="$(printf '%s' "$csrf_token" | tr -cd '0-9a-fA-F')" ;; esac
  fi
  # Update notifier integration. Parsed with the shell, not jq: this runs on
  # every statusline poll and each jq spawn costs ~0.3 s on the AK3918 (two
  # calls dominated the whole request). The file is a flat one-line object
  # written by update-check.sh, so a single read + case-match suffices.
  update_available=0
  update_latest="n/a"
  if [ -r /tmp/update_status.json ]; then
      read -r _upd_line < /tmp/update_status.json
      case "$_upd_line" in *'"update_available":1'*) update_available=1 ;; esac
      # extract latest_version="..."; strip everything around the quoted value
      _upd_lv="${_upd_line#*\"latest_version\":\"}"
      case "$_upd_lv" in
        "$_upd_line") ;;                    # key absent → leave n/a
        *) _upd_lv="${_upd_lv%%\"*}"; [ -n "$_upd_lv" ] && update_latest="$_upd_lv" ;;
      esac
  fi
  json_esc_to update_latest_json "$update_latest"

  # Firmware version for the UI topbar chip. Read with the `read` builtin
  # (no fork) since this runs on every hot statusline poll.
  current_version="n/a"
  if [ -r /mnt/VERSION ]; then
      read -r current_version < /mnt/VERSION
      [ -n "$current_version" ] || current_version="n/a"
  fi
  json_esc_to current_version_json "$current_version"

  # Smooth live view link (Settings → Frigate live view), read builtin only.
  frigate_live=""
  if [ -r /mnt/config/frigate_live.conf ]; then
      _fl_url=""; _fl_cam=""
      while IFS='=' read -r _fl_k _fl_v; do
          case "$_fl_k" in FRIGATE_URL) _fl_url="$_fl_v" ;; FRIGATE_CAMERA) _fl_cam="$_fl_v" ;; esac
      done < /mnt/config/frigate_live.conf
      case "$_fl_url$_fl_cam" in *[!A-Za-z0-9.:/_-]*) _fl_url="" ;; esac
      [ -n "$_fl_url" ] && frigate_live="${_fl_url}/${_fl_cam:+#$_fl_cam}"
  fi

  # SD card health (v3/linux66-sd/sdinfo-sd.sh).
  sd_health=""
  if [ -r /tmp/sd-health ]; then
      while IFS='=' read -r _sh_k _sh_v; do [ "$_sh_k" = state ] && sd_health="$_sh_v"; done < /tmp/sd-health
  fi
  case "$sd_health" in *[!a-z]*) sd_health="" ;; esac
  # SD card (v3/linux66-sd/sdinfo-sd.sh): what it is, and whether the
  # web page should ask what to do with it (sd_prompt = the card's id).
  sd_card=""; sd_prompt=""
  if [ -r /tmp/sd-card ]; then
      _sc_p=0; _sc_id=""
      while IFS='=' read -r _sc_k _sc_v; do
          case "$_sc_k" in kind) sd_card="$_sc_v" ;; prompt) _sc_p="$_sc_v" ;; id) _sc_id="$_sc_v" ;; esac
      done < /tmp/sd-card
      [ "$_sc_p" = 1 ] && sd_prompt="$_sc_id"
  fi
  case "$sd_card" in *[!a-z]*) sd_card="" ;; esac
  case "$sd_prompt" in *[!0-9a-zA-Z]*) sd_prompt="" ;; esac
  web_fallback=""; [ -r /tmp/web-fallback ] && read -r web_fallback < /tmp/web-fallback
  case "$web_fallback" in http) ;; *) web_fallback="" ;; esac
  # the page shows when the last save of the settings to the flash failed (v3/linux66-sd/cfg-persist status file)
  platform=linux66
  cfg_save=""; cfg_save_msg=""
  if [ -r /tmp/cfg-persist.status ]; then
      while IFS='=' read -r _cp_k _cp_v; do
          case "$_cp_k" in state) cfg_save="$_cp_v" ;; msg) cfg_save_msg="$_cp_v" ;; esac
      done < /tmp/cfg-persist.status
  fi
  case "$cfg_save" in *[!a-z_]*) cfg_save="" ;; esac
  json_esc_to cfg_save_msg_json "$cfg_save_msg"
  cam_hostname=""
  [ -r /proc/sys/kernel/hostname ] && read -r cam_hostname < /proc/sys/kernel/hostname
  [ -n "$cam_hostname" ] || cam_hostname="tc100"
  json_esc_to cam_hostname_json "$cam_hostname"

  echo "{\"sysusage\":\"CPU: $cpu% RAM: $mem_used/$mem_total kB\",\"cpu\":$cpu,\"ram_used_kb\":$mem_used,\"ram_total_kb\":$mem_total,\"ram_percent\":$ram_percent,\"sd_used_kb\":$sd_used_kb,\"sd_total_kb\":$sd_total_kb,\"sd_percent\":$sd_percent,\"perfprofile\":\"$profile_json\",\"lum\":\"$lum_json\",\"awb\":\"$awb_json\",\"ui_ultralite_mode\":$ui_mode,\"web_mode\":\"$web_mode_json\",\"security_hardening_mode\":$security_hardening_mode,\"mqtt_enabled\":$mqtt_enabled,\"mqtt_last_pub_ts\":$mqtt_last_pub_ts,\"mqtt_last_pub_ok\":$mqtt_last_pub_ok,\"mqtt_refused\":$mqtt_refused,\"default_password_active\":$default_password_active,\"csrf_token\":\"$csrf_token\",\"update_available\":$update_available,\"update_latest_version\":\"$update_latest_json\",\"current_version\":\"$current_version_json\",\"wifi_qual\":$wifi_qual_json,\"wifi_iface\":\"$wifi_iface_json\",\"frigate_live\":\"$frigate_live\",\"storage\":\"${storage_json:-sd}\",\"sd_health\":\"$sd_health\",\"sd_card\":\"$sd_card\",\"sd_prompt\":\"$sd_prompt\",\"web_fallback\":\"$web_fallback\",\"platform\":\"$platform\",\"cfg_save\":\"$cfg_save\",\"cfg_save_msg\":\"$cfg_save_msg_json\",\"hostname\":\"$cam_hostname_json\"}"
}
