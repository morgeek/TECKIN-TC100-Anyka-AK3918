#!/bin/sh

# This file is supposed to bundle some frequently used functions
# so they can be easily improved in one place and be reused all over the place

BUSYBOX_BIN=""

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
  bb_path="$(get_busybox_bin)"
  "$bb_path" "$@"
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

  if grep -q "^[[:space:]]*${cfg_key}=" "$cfg_path"; then
    # Escape replacement-sensitive characters for sed.
    esc_value=$(printf '%s' "$new_value" | sed 's/[\\&|]/\\&/g')
    sed -i -e "/^[[:space:]]*#/! s|^[[:space:]]*${cfg_key}=.*|${cfg_key}=${esc_value}|" "$cfg_path"
  else
    printf '%s=%s\n' "$cfg_key" "$new_value" >> "$cfg_path"
  fi
}

install_config()
{
  cfg_path=$1
  if [ ! -f "$cfg_path" ]; then
			cp "$cfg_path.dist" "$cfg_path" > /dev/null 2>&1
	fi
}


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
    #echo 1 > /sys/user-gpio/ir-led
    /mnt/bin/setconf -k g -v 1
    ;;
  off)
    #echo 0 > /sys/user-gpio/ir-led
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
#/sys/user-gpio/gpio-ircut_a
#/sys/user-gpio/gpio-ircut_b
ir_cut(){
  case "$1" in
  on)
    #echo 1 > /sys/user-gpio/gpio-ircut_b
    #echo 0 > /sys/user-gpio/gpio-ircut_a
    #sleep 1
    #echo 0 > /sys/user-gpio/gpio-ircut_b
    #echo "1" > /var/run/ircut
    /mnt/bin/setconf -k e -v 1
    ;;
  off)
    #echo 1 > /sys/user-gpio/gpio-ircut_a
    #echo 0 > /sys/user-gpio/gpio-ircut_b
    #sleep 1
    #echo 0 > /sys/user-gpio/gpio-ircut_a
    #echo "0" > /var/run/ircut
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


# Control the http server
http_server(){
  WEB_MODE="full"
  ULTRALITE_HTTP_PORT="80"
  if [ -f /mnt/config/boot.conf ]; then
    # shellcheck disable=SC1090
    . /mnt/config/boot.conf
  fi
  case "$1" in
  on)
    if [ "$WEB_MODE" = "ultra-lite" ] || [ "$WEB_MODE" = "ultralite" ]; then
      run_busybox httpd -p "${ULTRALITE_HTTP_PORT:-80}" -h /mnt/www
    else
      /mnt/bin/lighttpd -f /mnt/config/lighttpd.conf
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
      /mnt/bin/lighttpd -f /mnt/config/lighttpd.conf
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
  # Set recording flag
  run_busybox flock -x /tmp/rec_control echo "1" > /tmp/rec_control
}

deactivate_motion_recording()
{
  # Reset recording flag
  run_busybox flock -x /tmp/rec_control echo "0" > /tmp/rec_control
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


# Reboot the System
reboot_system() {
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
    while IFS=' :' read -r key val _; do
        if [ "$key" = "MemTotal" ]; then
            echo "$val"
            return
        fi
    done < /proc/meminfo
}

restart_service_if_need()
{
    service_path="$1"
    service_status="$("$service_path" status 2>/dev/null)"
    if [ -n "$service_status" ]; then
        $service_path stop > /dev/null 2>&1
        $service_path start > /dev/null 2>&1
    fi
}

start_service_if_need()
{
    service_path="$1"
    status=$("$service_path" status)
    if [ $? -ne 0 -o -z "$status" ]; then
        $service_path start > /dev/null 2>&1
    fi
}

all_password()
{
    DEFAULT_LOGIN="root"
    echo -e "$1\n$1" | passwd > /dev/null 2>&1
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

    if [ $led_status == "ON" ]; then
      led on $led_type
    fi

    if [ $off_led_status == "ON" ]; then
      led on $off_led_type
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
