#!/bin/sh

# A very light-weight interface just for responsive ui to get states

source ./func.cgi

echo "Content-type: text"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

USAGE_CACHE_FILE="/tmp/state_usage.cache"
USAGE_CACHE_TTL_SECONDS=2
PERFPROFILE_CACHE_FILE="/tmp/state_perfprofile.cache"
PERFPROFILE_CACHE_TTL_SECONDS=5

now_epoch() {
  now_ts="$(date +%s 2>/dev/null)"
  case "$now_ts" in
    ''|*[!0-9]*)
      echo "0"
      ;;
    *)
      echo "$now_ts"
      ;;
  esac
}

get_current_cpu_usage_fast() {
  cpu_active_prev=0
  cpu_total_prev=0
  if [ -f /tmp/cpuact ]; then
    read -r cpu_active_prev < /tmp/cpuact
  fi
  if [ -f /tmp/cputot ]; then
    read -r cpu_total_prev < /tmp/cputot
  fi

  # /proc/stat layout:
  # cpu user nice system idle iowait irq softirq steal guest guest_nice
  read -r _ user nice system idle iowait irq softirq steal _ _ < /proc/stat
  cpu_active_cur=$((user + nice + system + irq + softirq + steal))
  cpu_total_cur=$((cpu_active_cur + idle + iowait))

  echo "$cpu_active_cur" > /tmp/cpuact
  echo "$cpu_total_cur" > /tmp/cputot

  delta_total=$((cpu_total_cur - cpu_total_prev))
  delta_active=$((cpu_active_cur - cpu_active_prev))
  if [ "$delta_total" -le 0 ]; then
    echo "0"
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
  cpu="$(get_current_cpu_usage_fast)"
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

  now_ts="$(now_epoch)"
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
  now_ts="$(now_epoch)"
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

read_conf_value() {
  conf_file="$1"
  conf_key="$2"
  conf_default="$3"
  conf_value="$conf_default"

  if [ -f "$conf_file" ]; then
    while IFS= read -r line; do
      case "$line" in
        ''|'#'*)
          continue
          ;;
      esac
      case "$line" in
        "$conf_key"=*)
          conf_value="${line#*=}"
          break
          ;;
      esac
    done < "$conf_file"
  fi

  echo "$conf_value"
}

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

load_lum_awb() {
  lum_value=""
  awb_value=""

  if [ -r /var/run/lum ]; then
    read -r lum_value < /var/run/lum
  fi
  if [ -r /var/run/awb ]; then
    read -r awb_value < /var/run/awb
  fi
}

get_ui_ultralite_mode() {
  ui_mode=0
  WEB_MODE_VALUE="$(read_conf_value /mnt/config/boot.conf WEB_MODE full)"
  UI_ULTRALITE_MODE_VALUE="$(read_conf_value /mnt/config/boot.conf UI_ULTRALITE_MODE 0)"

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

compute_perf_profile() {
  LOW_CPU_PROFILE="$(read_conf_value /mnt/config/boot.conf LOW_CPU_PROFILE 0)"
  SERVICE_TRIM="$(read_conf_value /mnt/config/service_trim.conf SERVICE_TRIM 0)"

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

  now_ts="$(now_epoch)"
  [ "$now_ts" -gt 0 ] || return 1
  [ "$cached_ts" -le "$now_ts" ] || return 1
  age=$((now_ts - cached_ts))
  [ "$age" -le "$PERFPROFILE_CACHE_TTL_SECONDS" ] || return 1

  profile="$cached_profile"
  return 0
}

save_cached_perf_profile() {
  now_ts="$(now_epoch)"
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

if [ -n "$F_cmd" ]; then
  case "$F_cmd" in
  hostname)
    if [ -r /proc/sys/kernel/hostname ]; then
      cat /proc/sys/kernel/hostname
    else
      hostname
    fi
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
    load_or_compute_usage_metrics
    profile="$(get_perf_profile)"
    load_lum_awb
    get_ui_ultralite_mode
    profile_json="$(json_escape "$profile")"
    lum_json="$(json_escape "$lum_value")"
    awb_json="$(json_escape "$awb_value")"
    web_mode_json="$(json_escape "$WEB_MODE_VALUE")"
    echo "{\"sysusage\":\"CPU: $cpu% RAM: $mem_used/$mem_total kB\",\"cpu\":$cpu,\"ram_used_kb\":$mem_used,\"ram_total_kb\":$mem_total,\"ram_percent\":$ram_percent,\"perfprofile\":\"$profile_json\",\"lum\":\"$lum_json\",\"awb\":\"$awb_json\",\"ui_ultralite_mode\":$ui_mode,\"web_mode\":\"$web_mode_json\"}"
    ;;

  perfprofile)
    get_perf_profile
    ;;
  *)
    echo "Unsupported command '$F_cmd'"
    ;;
  esac
  fi

exit 0
