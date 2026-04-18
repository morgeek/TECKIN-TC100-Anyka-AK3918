#!/bin/sh
export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'

CONFIGPATH="/mnt/config"
LOGDIR="/tmp/log"
LOGPATH="$LOGDIR/startup.log"
RUNTIME_BUSYBOX="/mnt/bin/busybox"
SYSTEM_BUSYBOX="/bin/busybox"
BOOT_BUSYBOX="$SYSTEM_BUSYBOX"

## Load some common functions:
. /mnt/scripts/common_functions.sh

install_config $CONFIGPATH/rtspserver.conf
install_config $CONFIGPATH/boot.conf
install_config $CONFIGPATH/service_trim.conf
install_config $CONFIGPATH/packages.lock

DEFAULT_LIGHTWEIGHT_DENYLIST="01_system-emergency-telnet 02_system-webserver auto-night-detection front-led"

init_log()
{
    if [ ! -d $LOGDIR ]; then
        mkdir -p $LOGDIR
    fi
}

log_boot()
{
    echo "$1" >> $LOGPATH
}

ensure_runtime_symlink()
{
    link_path="$1"
    target_path="$2"

    if [ ! -e "$target_path" ]; then
        log_boot "Self-heal skipped: missing target $target_path"
        return 1
    fi

    if [ -L "$link_path" ]; then
        current_target="$(readlink "$link_path" 2>/dev/null)"
        if [ "$current_target" = "$target_path" ]; then
            return 0
        fi
    elif [ -e "$link_path" ]; then
        log_boot "Self-heal skipped: $link_path exists and is not a symlink"
        return 1
    fi

    rm -f "$link_path" 2>/dev/null
    if ln -s "$target_path" "$link_path" 2>/dev/null; then
        log_boot "Self-heal: linked $link_path -> $target_path"
        return 0
    fi

    log_boot "Self-heal failed: unable to link $link_path -> $target_path"
    return 1
}

select_boot_busybox()
{
    BOOT_BUSYBOX="$SYSTEM_BUSYBOX"

    if [ -x "$RUNTIME_BUSYBOX" ]; then
        if mount | grep -F "on $SYSTEM_BUSYBOX " | grep -F "$RUNTIME_BUSYBOX " > /dev/null 2>&1; then
            log_boot "BusyBox bind already active: $RUNTIME_BUSYBOX -> $SYSTEM_BUSYBOX"
            return 0
        fi
        if mount -o bind "$RUNTIME_BUSYBOX" "$SYSTEM_BUSYBOX" > /dev/null 2>&1; then
            log_boot "BusyBox bind mounted: $RUNTIME_BUSYBOX -> $SYSTEM_BUSYBOX"
            return 0
        fi
        log_boot "BusyBox bind mount failed, falling back to system busybox"
    else
        log_boot "Extended busybox missing at $RUNTIME_BUSYBOX, using system busybox"
    fi

    if [ -x "$SYSTEM_BUSYBOX" ]; then
        BOOT_BUSYBOX="$SYSTEM_BUSYBOX"
        return 0
    fi

    if command -v busybox > /dev/null 2>&1; then
        BOOT_BUSYBOX="$(command -v busybox)"
        log_boot "Using busybox from PATH: $BOOT_BUSYBOX"
        return 0
    fi

    log_boot "Warning: busybox not found; watchdog/ntp/cron applets may fail"
    return 1
}

self_heal_runtime()
{
    # Some upgraded bundles include versioned libs only; recreate SONAME links when safe.
    ensure_runtime_symlink /mnt/lib/libcurl.so.4 /mnt/lib/libcurl.so.4.8.0
    select_boot_busybox
}

is_truthy()
{
    case "$1" in
        1|true|yes|on|enable|enabled) return 0 ;;
        *) return 1 ;;
    esac
}

list_contains()
{
    needle="$1"
    shift
    for item in $*; do
        if [ "$item" = "$needle" ]; then
            return 0
        fi
    done
    return 1
}

sanitize_weekday_expr()
{
    case "$1" in
        '*'|0|1|2|3|4|5|6|1-5|0,6) echo "$1" ;;
        *) echo "*" ;;
    esac
}

load_boot_config()
{
    # shellcheck disable=SC1090
    if [ -f "$CONFIGPATH/boot.conf" ]; then
        . "$CONFIGPATH/boot.conf"
    fi
    # shellcheck disable=SC1090
    if [ -f "$CONFIGPATH/service_trim.conf" ]; then
        . "$CONFIGPATH/service_trim.conf"
    fi

    LIGHTWEIGHT_MODE="${LIGHTWEIGHT_MODE:-0}"

    if [ "$LIGHTWEIGHT_MODE" = "1" ]; then
        : "${ENABLE_NTP:=0}"
        : "${NTP_ONE_SHOT:=1}"
        : "${ENABLE_CROND:=0}"
        : "${LOW_CPU_PROFILE:=1}"
        : "${LOW_RAM_PROFILE:=1}"
        if [ -z "${AUTOSTART_ALLOWLIST+x}" ] && [ -z "${AUTOSTART_DENYLIST+x}" ]; then
            AUTOSTART_DENYLIST="$DEFAULT_LIGHTWEIGHT_DENYLIST"
        fi
    fi

    : "${LOW_CPU_PROFILE:=0}"
    if is_truthy "$LOW_CPU_PROFILE"; then
        : "${LOW_CPU_DISABLE_SUBSTREAM:=1}"
        : "${LOW_CPU_DISABLE_AUDIO:=1}"
        : "${LOW_CPU_DISABLE_MOTION:=1}"
        : "${LOW_CPU_DISABLE_OSD:=1}"
        : "${LOW_CPU_DISABLE_JPEG:=1}"

        : "${LOW_CPU_MAIN_WIDTH:=640}"
        : "${LOW_CPU_MAIN_HEIGHT:=360}"
        : "${LOW_CPU_MAIN_FPS:=10}"
        : "${LOW_CPU_MAIN_BPS:=600}"
        : "${LOW_CPU_MAIN_GOPLEN:=30}"
        : "${LOW_CPU_MAIN_MAXKBPS:=800}"
        : "${LOW_CPU_MAIN_TARGETKBPS:=500}"

        : "${LOW_CPU_SUB_WIDTH:=320}"
        : "${LOW_CPU_SUB_HEIGHT:=180}"
        : "${LOW_CPU_SUB_FPS:=4}"
        : "${LOW_CPU_SUB_BPS:=150}"
        : "${LOW_CPU_SUB_GOPLEN:=16}"
        : "${LOW_CPU_SUB_MAXKBPS:=200}"
        : "${LOW_CPU_SUB_TARGETKBPS:=150}"

        if is_truthy "$LOW_CPU_DISABLE_SUBSTREAM"; then
            RTSP_SUBSTREAM=0
        fi
        if is_truthy "$LOW_CPU_DISABLE_AUDIO"; then
            RTSP_AUDIO=0
        fi
    fi

    : "${LOW_RAM_PROFILE:=0}"
    if is_truthy "$LOW_RAM_PROFILE"; then
        : "${MEM_GUARD_ENABLE:=1}"
        : "${ENABLE_CROND:=0}"
    fi

    : "${ENABLE_WATCHDOG:=1}"
    : "${ENABLE_NTP:=1}"
    : "${NTP_ONE_SHOT:=0}"
    : "${ENABLE_CROND:=1}"
    : "${ENABLE_AUTOSTART:=1}"
    : "${REBOOT_SCHEDULE_ENABLE:=0}"
    : "${REBOOT_SCHEDULE_MINUTE:=0}"
    : "${REBOOT_SCHEDULE_HOUR:=4}"
    : "${REBOOT_SCHEDULE_WEEKDAY:=*}"
    : "${RTSP_SUBSTREAM:=1}"
    : "${RTSP_AUDIO:=1}"
    : "${WEB_MODE:=full}"
    : "${SECURITY_HARDENING_MODE:=0}"
    : "${AUTOSTART_ALLOWLIST:=}"
    : "${AUTOSTART_DENYLIST:=}"
    : "${SERVICE_TRIM:=0}"
    : "${SERVICE_TRIM_ALLOWLIST:=00_system-config 02_system-webserver rtsp-h26x onvif memory-guard}"
    : "${MEM_GUARD_ENABLE:=0}"
    : "${MEM_GUARD_INTERVAL_SECONDS:=20}"
    : "${MEM_GUARD_WARN_KB:=8192}"
    : "${MEM_GUARD_CRITICAL_KB:=4096}"
    : "${MEM_GUARD_COOLDOWN_SECONDS:=120}"
    : "${MEM_GUARD_DROP_CACHES:=1}"
    : "${MEM_GUARD_SOFT_SERVICES:=network-monitor auto-night-detection}"
    : "${MEM_GUARD_CRITICAL_SERVICES:=ftp-server telnet-server timelapse recording motion-detection}"
    : "${STORAGE_CLEANUP_ENABLE:=0}"
    : "${STORAGE_CLEANUP_THRESHOLD:=90}"
    : "${STORAGE_CLEANUP_TARGET:=85}"
    : "${STORAGE_CLEANUP_DCIM_PATH:=/mnt/DCIM}"
    : "${SYSLOG_ENABLE:=0}"
    : "${SYSLOG_HOST:=}"
    : "${SYSLOG_PORT:=514}"

    if is_truthy "$REBOOT_SCHEDULE_ENABLE" && ! is_truthy "$ENABLE_CROND"; then
        ENABLE_CROND=1
        rewrite_config "$CONFIGPATH/boot.conf" ENABLE_CROND 1
    fi

    if is_truthy "$SERVICE_TRIM"; then
        AUTOSTART_ALLOWLIST="$SERVICE_TRIM_ALLOWLIST"
        AUTOSTART_DENYLIST=""
    fi

    if is_truthy "$MEM_GUARD_ENABLE" && [ -n "$AUTOSTART_ALLOWLIST" ]; then
        if ! list_contains "memory-guard" $AUTOSTART_ALLOWLIST; then
            AUTOSTART_ALLOWLIST="$AUTOSTART_ALLOWLIST memory-guard"
        fi
    fi

    if is_truthy "$SECURITY_HARDENING_MODE"; then
        if [ "$WEB_MODE" != "full" ]; then
            WEB_MODE="full"
            rewrite_config "$CONFIGPATH/boot.conf" WEB_MODE full
        fi
        if [ -z "$AUTOSTART_ALLOWLIST" ] && ! list_contains "ftp-server" $AUTOSTART_DENYLIST; then
            AUTOSTART_DENYLIST="$AUTOSTART_DENYLIST ftp-server telnet-server"
        fi
    fi

    echo "Boot config: lightweight=$LIGHTWEIGHT_MODE lowcpu=$LOW_CPU_PROFILE lowram=$LOW_RAM_PROFILE memguard=$MEM_GUARD_ENABLE security_hardening=$SECURITY_HARDENING_MODE watchdog=$ENABLE_WATCHDOG ntp=$ENABLE_NTP crond=$ENABLE_CROND autostart=$ENABLE_AUTOSTART" >> $LOGPATH
}

enable_hardware_watchdog()
{
    if ! is_truthy "$ENABLE_WATCHDOG"; then
        echo "Hardware watchdog disabled by boot config" >> $LOGPATH
        return 0
    fi
    # A Watchdog Timer is a hardware circuit that can reset the
    # camera system in case of a software fault.
    # This script will notify the kernel watchdog driver via the
    # /dev/watchdog special device file that userspace is still alive, at
    # regular intervals.
    # When such a notification occurs, the driver will
    # usually tell the hardware watchdog that everything is in order, and
    # that the watchdog should wait for yet another little while to reset
    # the camera. If userspace fails (system hang, RAM error, kernel bug), the
    # notifications cease to occur, and the hardware watchdog will reset the
    # camera (causing a reboot) after the timeout occurs.
    #
    # To disable watchdog use:
    #       echo 'V'>/dev/watchdog
    #       echo 'V'>/dev/watchdog0
    # Start watchdog (notify every 2 seconds, reboot if no notification in 5 seconds)
    "$BOOT_BUSYBOX" watchdog -t 2 -T 5 /dev/watchdog
    echo "Enabling hardware watchdog" >> $LOGPATH
}

stop_cloud()
{
    echo "Stopping cloud apps and configs" >> $LOGPATH
    # Graceful stop of cloud server processes (avoid SIGKILL unless necessary)
    pids="$(ps | awk '/[c]md_server/ {print $1}')"
    if [ -n "$pids" ]; then
        echo "Stopping cmd_server PIDs: $pids" >> $LOGPATH
        for pid in $pids; do
            kill "$pid" 2>/dev/null || true
        done
        sleep 3
        for pid in $pids; do
            if kill -0 "$pid" 2>/dev/null; then
                echo "Killing unresponsive PID $pid" >> $LOGPATH
                kill -9 "$pid" 2>/dev/null || true
            fi
        done
    fi

    # Unmount RAM disk
    if /bin/umount /dev/loop0 2>/dev/null; then
        : # success
    else
        echo "WARNING: Failed to unmount /dev/loop0" >> "$LOGPATH"
    fi
    rm -f -r /tmp/ramdisk
    rm -f /tmp/zero

    # Disable core dumps
    echo "|/bin/false" > /proc/sys/kernel/core_pattern

    # Set min free reserve bytes
    echo 1024 > /proc/sys/vm/min_free_kbytes
}

init_network()
{
    install_config $CONFIGPATH/hostname.conf
    hostname -F $CONFIGPATH/hostname.conf

    insmod /usr/modules/otg-hs.ko
    sleep 1
    insmod /usr/modules/8188fu.ko
    echo "0" > /sys/module/8188fu/parameters/rtw_drv_log_level

    i=0
    while [ $i -lt 3 ]
    do
        if [ -d "/sys/class/net/wlan0" ];then
            break
        else
            sleep 1
            i=`expr $i + 1`
        fi
    done

    ifconfig wlan0 up

    WIFI_CONFIG="/mnt/wpa_supplicant.conf"
    if [ -f "$WIFI_CONFIG" ]; then
        echo "Use manual WIFI setup" >> $LOGPATH
        mkdir /var/network
        wpa_supplicant_status="$(wpa_supplicant -B -i wlan0 -c $WIFI_CONFIG -P /var/run/wpa_supplicant.pid)"
        echo "wpa_supplicant: $wpa_supplicant_status" >> $LOGPATH
        install_config $CONFIGPATH/network.conf
        . $CONFIGPATH/network.conf 2>/dev/null
        if [ "${IP_MODE:-dhcp}" = "static" ] && [ -n "$STATIC_IP" ]; then
            echo "init_network: applying static IP $STATIC_IP" >> $LOGPATH
            ifconfig wlan0 "$STATIC_IP" netmask "${STATIC_NETMASK:-255.255.255.0}"
            [ -n "$STATIC_GATEWAY" ] && route add default gw "$STATIC_GATEWAY" wlan0
        else
            udhcpc_status=$(udhcpc -i wlan0 -p /var/network/udhcpc.pid -b -x hostname:"$(hostname)")
            echo "udhcpc: $udhcpc_status" >> $LOGPATH
        fi
    else
        echo "Use Anyka default WIFI setup" >> $LOGPATH
        /usr/sbin/wifi_station.sh start
        /usr/sbin/wifi_station.sh connect
    fi
}

cache_camera_ip()
{
    ip="$(ifconfig wlan0 2>/dev/null | awk '/inet addr:/{split($2,a,":");print a[2];exit}')"
    if [ -n "$ip" ]; then
        echo "$ip" > /tmp/camera_ip.txt
        echo "cache_camera_ip: cached $ip" >> $LOGPATH
    fi
}

apply_custom_dns()
{
    install_config $CONFIGPATH/dns.conf
    . $CONFIGPATH/dns.conf

    if [ -z "$DNS_PRIMARY" ]; then
        return 0
    fi

    # Validate: must look like an IPv4 address (4 dotted octets)
    valid_ip() {
        printf '%s' "$1" | awk -F. 'NF==4 && $1+0==$1 && $2+0==$2 && $3+0==$3 && $4+0==$4 &&
            $1>=0 && $1<=255 && $2>=0 && $2<=255 && $3>=0 && $3<=255 && $4>=0 && $4<=255
            {exit 0} {exit 1}'
    }

    if ! valid_ip "$DNS_PRIMARY"; then
        echo "apply_custom_dns: invalid DNS_PRIMARY '$DNS_PRIMARY', skipping" >> $LOGPATH
        return 0
    fi

    {
        echo "nameserver $DNS_PRIMARY"
        if [ -n "$DNS_SECONDARY" ] && valid_ip "$DNS_SECONDARY"; then
            echo "nameserver $DNS_SECONDARY"
        fi
    } > /etc/resolv.conf

    echo "apply_custom_dns: set primary=$DNS_PRIMARY secondary=${DNS_SECONDARY:-none}" >> $LOGPATH
}

sync_time()
{
    if ! is_truthy "$ENABLE_NTP"; then
        echo "NTP sync disabled by boot config" >> $LOGPATH
        return 0
    fi
    install_config $CONFIGPATH/ntp_srv.conf
    ntp_srv="$(cat "$CONFIGPATH/ntp_srv.conf")"
    timeout -t 30 sh -c "until ping -c1 \"$ntp_srv\" &>/dev/null; do sleep 3; done";
    if is_truthy "$NTP_ONE_SHOT"; then
        "$BOOT_BUSYBOX" ntpd -q -n -p "$ntp_srv"
    else
        "$BOOT_BUSYBOX" ntpd -p "$ntp_srv"
    fi
}

init_crond()
{
    if ! is_truthy "$ENABLE_CROND"; then
        echo "Crond disabled by boot config" >> $LOGPATH
        return 0
    fi
    # Create crontab dir and start crond.
    if [ ! -d ${CONFIGPATH}/cron ]; then
      mkdir -p ${CONFIGPATH}/cron/crontabs
      CRONPERIODIC="${CONFIGPATH}/cron/periodic"
      mkdir -p ${CRONPERIODIC}/15min \
               ${CRONPERIODIC}/hourly \
               ${CRONPERIODIC}/daily \
               ${CRONPERIODIC}/weekly \
               ${CRONPERIODIC}/monthly
      cat > ${CONFIGPATH}/cron/crontabs/root <<EOF
# min   hour    day     month   weekday command
*/15    *       *       *       *       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/15min
0       *       *       *       *       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/hourly
0       2       *       *       *       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/daily
0       3       *       *       6       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/weekly
0       5       1       *       *       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/monthly
EOF
      echo "Created cron directories and standard interval jobs" >> $LOGPATH
    fi
    CRON_ROOT="${CONFIGPATH}/cron/crontabs/root"
    CRONPERIODIC="${CONFIGPATH}/cron/periodic"
    if [ ! -f "$CRON_ROOT" ]; then
      cat > "$CRON_ROOT" <<EOF
# min   hour    day     month   weekday command
*/15    *       *       *       *       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/15min
0       *       *       *       *       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/hourly
0       2       *       *       *       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/daily
0       3       *       *       6       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/weekly
0       5       1       *       *       ${BOOT_BUSYBOX} run-parts ${CRONPERIODIC}/monthly
EOF
    fi

    sched_enable=0
    if is_truthy "$REBOOT_SCHEDULE_ENABLE"; then
      sched_enable=1
    fi
    sched_minute="${REBOOT_SCHEDULE_MINUTE:-0}"
    sched_hour="${REBOOT_SCHEDULE_HOUR:-4}"
    sched_weekday="$(sanitize_weekday_expr "${REBOOT_SCHEDULE_WEEKDAY:-*}")"
    case "$sched_minute" in
      ''|*[!0-9]*) sched_minute=0 ;;
    esac
    case "$sched_hour" in
      ''|*[!0-9]*) sched_hour=4 ;;
    esac
    if [ "$sched_minute" -lt 0 ] || [ "$sched_minute" -gt 59 ]; then
      sched_minute=0
    fi
    if [ "$sched_hour" -lt 0 ] || [ "$sched_hour" -gt 23 ]; then
      sched_hour=4
    fi

    CRON_TMP="/tmp/root.crontab.$$.$(date +%s)"
    awk '
      BEGIN { skip=0 }
      /^# BEGIN TC100 MANAGED REBOOT$/ { skip=1; next }
      /^# END TC100 MANAGED REBOOT$/ { skip=0; next }
      skip==0 { print }
    ' "$CRON_ROOT" > "$CRON_TMP" 2>/dev/null || cp "$CRON_ROOT" "$CRON_TMP"

    {
      echo "# BEGIN TC100 MANAGED REBOOT"
      if [ "$sched_enable" = "1" ]; then
        echo "${sched_minute} ${sched_hour} * * ${sched_weekday} /sbin/reboot >/dev/null 2>&1"
      else
        echo "# disabled"
      fi
      echo "# END TC100 MANAGED REBOOT"
    } >> "$CRON_TMP"

    mv "$CRON_TMP" "$CRON_ROOT"

    # Motion arm/disarm schedule
    ms_enable=0
    if is_truthy "$MOTION_SCHEDULE_ENABLE"; then ms_enable=1; fi
    ms_arm_min="${MOTION_ARM_MINUTE:-0}"
    ms_arm_hr="${MOTION_ARM_HOUR:-8}"
    ms_disarm_min="${MOTION_DISARM_MINUTE:-0}"
    ms_disarm_hr="${MOTION_DISARM_HOUR:-22}"
    ms_weekday="$(sanitize_weekday_expr "${MOTION_SCHEDULE_WEEKDAY:-*}")"
    case "$ms_arm_min"    in ''|*[!0-9]*) ms_arm_min=0    ;; esac
    case "$ms_arm_hr"     in ''|*[!0-9]*) ms_arm_hr=8     ;; esac
    case "$ms_disarm_min" in ''|*[!0-9]*) ms_disarm_min=0 ;; esac
    case "$ms_disarm_hr"  in ''|*[!0-9]*) ms_disarm_hr=22 ;; esac
    if [ "$ms_arm_min"    -lt 0 ] || [ "$ms_arm_min"    -gt 59 ]; then ms_arm_min=0;    fi
    if [ "$ms_arm_hr"     -lt 0 ] || [ "$ms_arm_hr"     -gt 23 ]; then ms_arm_hr=8;     fi
    if [ "$ms_disarm_min" -lt 0 ] || [ "$ms_disarm_min" -gt 59 ]; then ms_disarm_min=0; fi
    if [ "$ms_disarm_hr"  -lt 0 ] || [ "$ms_disarm_hr"  -gt 23 ]; then ms_disarm_hr=22; fi

    CRON_TMP="/tmp/root.crontab.motion.$$"
    awk '
      BEGIN { skip=0 }
      /^# BEGIN TC100 MANAGED MOTION$/ { skip=1; next }
      /^# END TC100 MANAGED MOTION$/ { skip=0; next }
      skip==0 { print }
    ' "$CRON_ROOT" > "$CRON_TMP" 2>/dev/null || cp "$CRON_ROOT" "$CRON_TMP"

    {
      echo "# BEGIN TC100 MANAGED MOTION"
      if [ "$ms_enable" = "1" ]; then
        echo "${ms_arm_min} ${ms_arm_hr} * * ${ms_weekday} /mnt/scripts/motion-schedule.sh arm"
        echo "${ms_disarm_min} ${ms_disarm_hr} * * ${ms_weekday} /mnt/scripts/motion-schedule.sh disarm"
      else
        echo "# disabled"
      fi
      echo "# END TC100 MANAGED MOTION"
    } >> "$CRON_TMP"

    mv "$CRON_TMP" "$CRON_ROOT"

    # Storage auto-cleanup schedule (runs hourly if enabled)
    CRON_TMP="/tmp/root.crontab.storage.$$"
    awk '
      BEGIN { skip=0 }
      /^# BEGIN TC100 MANAGED STORAGE$/ { skip=1; next }
      /^# END TC100 MANAGED STORAGE$/ { skip=0; next }
      skip==0 { print }
    ' "$CRON_ROOT" > "$CRON_TMP" 2>/dev/null || cp "$CRON_ROOT" "$CRON_TMP"
    {
      echo "# BEGIN TC100 MANAGED STORAGE"
      if is_truthy "${STORAGE_CLEANUP_ENABLE:-0}"; then
        echo "0 * * * * /mnt/scripts/storage-cleanup.sh >/dev/null 2>&1"
      else
        echo "# disabled"
      fi
      echo "# END TC100 MANAGED STORAGE"
    } >> "$CRON_TMP"
    mv "$CRON_TMP" "$CRON_ROOT"

    "$BOOT_BUSYBOX" crond -c ${CONFIGPATH}/cron/crontabs
    if [ "$sched_enable" = "1" ]; then
      echo "Scheduled reboot cron active: ${sched_minute} ${sched_hour} * * ${sched_weekday}" >> $LOGPATH
    fi
    if [ "$ms_enable" = "1" ]; then
      echo "Scheduled motion arm cron: ${ms_arm_min} ${ms_arm_hr} * * ${ms_weekday}" >> $LOGPATH
      echo "Scheduled motion disarm cron: ${ms_disarm_min} ${ms_disarm_hr} * * ${ms_weekday}" >> $LOGPATH
    fi
}

initialize_gpio()
{
    ir_led off
    ir_cut on
    front_led off
    red_led off
}

init_rtsp_params()
{
    # Set default value (will be overrided if need by autostart scripts)
    motion_detection off
    # Disable virtual memory over commit check: required for running scripts when motion detected.
    # Without this 'system()' call in rtsp server fails with not enough memory error (fork() cannot allocate virtual memory).
    echo 1 > /proc/sys/vm/overcommit_memory
}

apply_low_cpu_profile()
{
    if ! is_truthy "$LOW_CPU_PROFILE"; then
        return 0
    fi

    echo "Applying low CPU RTSP profile" >> $LOGPATH

    install_config $CONFIGPATH/rtspserver.conf

    if is_truthy "$LOW_CPU_DISABLE_MOTION"; then
        /mnt/bin/rwconf $CONFIGPATH/rtspserver.conf w " " mdenabled 0
    fi

    if is_truthy "$LOW_CPU_DISABLE_OSD"; then
        /mnt/bin/rwconf $CONFIGPATH/rtspserver.conf w " " osdenabled 0
    fi

    if is_truthy "$LOW_CPU_DISABLE_JPEG"; then
        /mnt/bin/rwconf $CONFIGPATH/rtspserver.conf w " " jpegstream 0
    fi

    if is_truthy "$LOW_CPU_DISABLE_AUDIO"; then
        /mnt/bin/rwconf $CONFIGPATH/rtspserver.conf w 2 codec 0 3 codec 0
    fi

    /mnt/bin/rwconf $CONFIGPATH/rtspserver.conf w \
        0 width      "$LOW_CPU_MAIN_WIDTH" \
        0 height     "$LOW_CPU_MAIN_HEIGHT" \
        0 fps        "$LOW_CPU_MAIN_FPS" \
        0 bps        "$LOW_CPU_MAIN_BPS" \
        0 goplen     "$LOW_CPU_MAIN_GOPLEN" \
        0 maxkbps    "$LOW_CPU_MAIN_MAXKBPS" \
        0 targetkbps "$LOW_CPU_MAIN_TARGETKBPS"

    /mnt/bin/rwconf $CONFIGPATH/rtspserver.conf w \
        1 width      "$LOW_CPU_SUB_WIDTH" \
        1 height     "$LOW_CPU_SUB_HEIGHT" \
        1 fps        "$LOW_CPU_SUB_FPS" \
        1 bps        "$LOW_CPU_SUB_BPS" \
        1 goplen     "$LOW_CPU_SUB_GOPLEN" \
        1 maxkbps    "$LOW_CPU_SUB_MAXKBPS" \
        1 targetkbps "$LOW_CPU_SUB_TARGETKBPS"

    # Apply conservative background intervals in low-CPU mode.
    install_config "$CONFIGPATH/mqtt.conf"
    mqtt_health_interval="$(awk -F= '$1=="MQTT_HEALTH_INTERVAL_SECONDS"{print $2; exit}' "$CONFIGPATH/mqtt.conf" 2>/dev/null)"
    case "$mqtt_health_interval" in
        ''|*[!0-9]*) mqtt_health_interval=120 ;;
    esac
    if [ "$mqtt_health_interval" -lt 120 ]; then
        rewrite_config "$CONFIGPATH/mqtt.conf" MQTT_HEALTH_INTERVAL_SECONDS 120
    fi

    mqtt_health_slow_ttl="$(awk -F= '$1=="MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS"{print $2; exit}' "$CONFIGPATH/mqtt.conf" 2>/dev/null)"
    case "$mqtt_health_slow_ttl" in
        ''|*[!0-9]*) mqtt_health_slow_ttl=180 ;;
    esac
    if [ "$mqtt_health_slow_ttl" -lt 180 ]; then
        rewrite_config "$CONFIGPATH/mqtt.conf" MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS 180
    fi

    if [ ! -f "$CONFIGPATH/sound_detection.conf" ]; then
        {
            echo "ENABLE=0"
            echo "THRESHOLD=1500"
            echo "INTERVAL=10"
        } > "$CONFIGPATH/sound_detection.conf"
    fi
    sound_interval="$(awk -F= '$1=="INTERVAL"{print $2; exit}' "$CONFIGPATH/sound_detection.conf" 2>/dev/null)"
    case "$sound_interval" in
        ''|*[!0-9]*) sound_interval=10 ;;
    esac
    if [ "$sound_interval" -lt 10 ]; then
        rewrite_config "$CONFIGPATH/sound_detection.conf" INTERVAL 10
    fi
}

run_autostart_scripts()
{
    echo "Autostart..." >> $LOGPATH
    if ! is_truthy "$ENABLE_AUTOSTART"; then
        echo "Autostart disabled by boot config" >> $LOGPATH
        return 0
    fi
    for i in /mnt/config/autostart/*; do
        [ -e "$i" ] || continue
        script_name="$(basename "$i")"
        if is_truthy "$SECURITY_HARDENING_MODE"; then
            case "$script_name" in
                ftp-server|telnet-server)
                    echo "Skip $script_name (security hardening)" >> $LOGPATH
                    continue
                    ;;
            esac
        fi
        if [ -n "$AUTOSTART_ALLOWLIST" ]; then
            if ! list_contains "$script_name" $AUTOSTART_ALLOWLIST; then
                echo "Skip $script_name (not in allowlist)" >> $LOGPATH
                continue
            fi
        elif [ -n "$AUTOSTART_DENYLIST" ]; then
            if list_contains "$script_name" $AUTOSTART_DENYLIST; then
                echo "Skip $script_name (denylist)" >> $LOGPATH
                continue
            fi
        fi
        echo "Run $i" >> $LOGPATH
        $i
    done
}

enforce_security_hardening_runtime()
{
    if ! is_truthy "$SECURITY_HARDENING_MODE"; then
        return 0
    fi

    echo "Applying security hardening runtime policy" >> $LOGPATH
    rewrite_config "$CONFIGPATH/boot.conf" SECURITY_HARDENING_MODE 1
    rewrite_config "$CONFIGPATH/boot.conf" WEB_MODE full

    for svc in ftp-server telnet-server; do
        if [ -x "/mnt/controlscripts/$svc" ]; then
            /mnt/controlscripts/$svc stop >/dev/null 2>&1 || true
        fi
        rm -f "/mnt/config/autostart/$svc" >/dev/null 2>&1 || true
    done
}

start_syslog_forwarding()
{
    if ! is_truthy "${SYSLOG_ENABLE:-0}"; then
        return 0
    fi
    if [ -z "$SYSLOG_HOST" ]; then
        echo "start_syslog_forwarding: SYSLOG_HOST not set, skipping" >> "$LOGPATH"
        return 0
    fi
    _syslog_port="${SYSLOG_PORT:-514}"
    case "$_syslog_port" in
        ''|*[!0-9]*) _syslog_port=514 ;;
    esac

    # Try busybox syslogd with -R for remote forwarding.
    # -n runs in foreground (we background it ourselves), -R sends to remote host.
    if "$BOOT_BUSYBOX" syslogd --help 2>&1 | grep -q '\-R'; then
        # Kill any existing local syslogd
        killall syslogd 2>/dev/null || true
        sleep 1
        "$BOOT_BUSYBOX" syslogd -R "${SYSLOG_HOST}:${_syslog_port}" &
        echo "start_syslog_forwarding: syslogd -R ${SYSLOG_HOST}:${_syslog_port}" >> "$LOGPATH"
    else
        # Fallback: send the startup log as a one-shot UDP syslog message via logger -n
        if "$BOOT_BUSYBOX" logger --help 2>&1 | grep -q '\-n'; then
            "$BOOT_BUSYBOX" logger -n "$SYSLOG_HOST" -P "$_syslog_port" \
                -t "tc100" "Camera boot complete — $(cat /tmp/camera_ip.txt 2>/dev/null)" \
                >/dev/null 2>&1 || true
            echo "start_syslog_forwarding: sent boot notice via logger to ${SYSLOG_HOST}:${_syslog_port}" >> "$LOGPATH"
        else
            echo "start_syslog_forwarding: busybox syslogd -R and logger -n not available" >> "$LOGPATH"
        fi
    fi
}

generate_csrf_token()
{
    # Per-boot random token for CSRF protection.
    # Written to /tmp (tmpfs, lost on reboot) — authenticated clients get it via state.cgi.
    _csrf_token=""
    if [ -r /proc/sys/kernel/random/uuid ]; then
        _csrf_token="$(tr -d '-\n' < /proc/sys/kernel/random/uuid 2>/dev/null)"
    fi
    if [ -z "$_csrf_token" ]; then
        # Fallback: mix PID + btime + uptime + /dev/urandom
        _csrf_btime=0
        while read -r _k _v _; do
            [ "$_k" = "btime" ] && _csrf_btime="$_v" && break
        done < /proc/stat
        read -r _csrf_up _ < /proc/uptime
        _csrf_rand="$(head -c 8 /dev/urandom 2>/dev/null | od -An -tx1 | tr -d ' \n')"
        _csrf_token="$(printf '%s%s%s%s' "$$" "$_csrf_btime" "${_csrf_up%.*}" "$_csrf_rand" \
            | md5sum 2>/dev/null | awk '{print $1}')"
    fi
    if [ -n "$_csrf_token" ]; then
        printf '%s' "$_csrf_token" > /tmp/csrf_token
        echo "CSRF token generated" >> "$LOGPATH"
    else
        echo "CSRF token generation failed" >> "$LOGPATH"
    fi
}

publish_boot_event()
{
    if [ ! -x /mnt/scripts/mqtt-bridge.sh ]; then
        return 0
    fi
    # Compute timestamp without fork: btime + uptime_secs
    _pb_btime=0
    while read -r _k _v _; do
        [ "$_k" = "btime" ] && _pb_btime="$_v" && break
    done < /proc/stat
    read -r _pb_up _ < /proc/uptime
    _pb_ts=$((_pb_btime + ${_pb_up%.*}))
    _pb_uptime="${_pb_up%.*}"
    _pb_ip=""
    if [ -f /tmp/camera_ip.txt ]; then
        _pb_ip="$(head -n 1 /tmp/camera_ip.txt 2>/dev/null)"
    fi
    # Publish in background after a short delay so the MQTT bridge has time to connect
    (
        sleep 8
        _payload=$(printf '{"ts":%s,"type":"boot","ip":"%s","uptime_seconds":%s,"source":"autorun"}' \
            "$_pb_ts" "$_pb_ip" "$_pb_uptime")
        /mnt/scripts/mqtt-bridge.sh publish event "$_payload" 0 >/dev/null 2>&1 || true
    ) &
}

start_mqtt_bridge_if_enabled()
{
    install_config "$CONFIGPATH/mqtt.conf"

    mqtt_enable=0
    # shellcheck disable=SC1090
    if [ -f "$CONFIGPATH/mqtt.conf" ]; then
        . "$CONFIGPATH/mqtt.conf"
        mqtt_enable="${MQTT_ENABLE:-0}"
    fi

    if ! is_truthy "$mqtt_enable"; then
        return 0
    fi

    if [ -x /mnt/controlscripts/mqtt-bridge ]; then
        /mnt/controlscripts/mqtt-bridge start >/dev/null 2>&1 || true
        echo "MQTT bridge start requested (MQTT_ENABLE=1)" >> "$LOGPATH"
    fi
}

init_password()
{
    pass=$(cat /mnt/config/user.pwd)
    all_password "$pass"
}

preflight_checks()
{
    local _ok=1

    # 1. /mnt must be readable and contain our expected structure
    if [ ! -d /mnt/bin ] || [ ! -d /mnt/scripts ] || [ ! -d /mnt/www ]; then
        echo "PREFLIGHT FAIL: /mnt does not appear to be a valid TC100 SD card mount" >> "$LOGPATH"
        _ok=0
    fi

    # 2. Key binaries must be executable
    for _bin in /mnt/bin/busybox /mnt/bin/v4l2rtspserver /mnt/bin/rwconf /mnt/bin/getflag; do
        if [ ! -x "$_bin" ]; then
            echo "PREFLIGHT WARN: binary not executable: $_bin" >> "$LOGPATH"
        fi
    done

    # 3. /tmp must be writable (tmpfs should always be mounted)
    if ! touch /tmp/.preflight_check 2>/dev/null; then
        echo "PREFLIGHT FAIL: /tmp is not writable" >> "$LOGPATH"
        _ok=0
    else
        rm -f /tmp/.preflight_check
    fi

    # 4. Check minimum free space on /mnt (warn if < 4 MB)
    _mnt_avail_kb=0
    _mnt_avail_kb="$(df -k /mnt 2>/dev/null | awk 'NR==2{print $4}')"
    case "$_mnt_avail_kb" in ''|*[!0-9]*) _mnt_avail_kb=0 ;; esac
    if [ "$_mnt_avail_kb" -lt 4096 ]; then
        echo "PREFLIGHT WARN: /mnt has less than 4 MB free ($_mnt_avail_kb kB) — logs/recordings may fail" >> "$LOGPATH"
    fi

    # 5. Reinstall any zero-byte config files from their .dist templates
    for _conf in boot.conf rtspserver.conf; do
        _dst="$CONFIGPATH/$_conf"
        _src="$CONFIGPATH/${_conf}.dist"
        if [ -f "$_dst" ] && [ ! -s "$_dst" ] && [ -f "$_src" ]; then
            echo "PREFLIGHT: $_dst is empty — reinstalling from $_src" >> "$LOGPATH"
            cp "$_src" "$_dst" 2>/dev/null || true
        fi
    done

    if [ "$_ok" -eq 1 ]; then
        echo "PREFLIGHT OK" >> "$LOGPATH"
    fi
}

##############################################################
init_log
preflight_checks
self_heal_runtime
init_password
load_boot_config
# Validate config values early — logs to /tmp/log/config-validator.log, never fatal.
[ -x /mnt/scripts/config-validator.sh ] && /mnt/scripts/config-validator.sh &
echo "--------Starting Hacks--------" >> $LOGPATH
stop_cloud
enable_hardware_watchdog
init_network
cache_camera_ip
apply_custom_dns
sync_time
init_crond
initialize_gpio
init_rtsp_params
apply_low_cpu_profile
run_autostart_scripts
enforce_security_hardening_runtime
start_syslog_forwarding
generate_csrf_token
start_mqtt_bridge_if_enabled
publish_boot_event
echo "$(date)" >> $LOGPATH
(build_devinfo_cache && echo "build_devinfo_cache: done" >> $LOGPATH) &
sleep 3
sync
echo 3 > /proc/sys/vm/drop_caches
echo "--------Starting Hacks Finished!--------" >> $LOGPATH
