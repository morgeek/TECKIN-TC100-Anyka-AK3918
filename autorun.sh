#!/bin/sh
export LD_LIBRARY_PATH='/mnt/lib/:/lib/:/usr/lib/'

CONFIGPATH="/mnt/config"
LOGDIR="/mnt/log"
LOGPATH="$LOGDIR/startup.log"

## Load some common functions:
. /mnt/scripts/common_functions.sh

# Mount bind to extended busybox.
mount -o bind /mnt/bin/busybox /bin/busybox

install_config $CONFIGPATH/rtspserver.conf
install_config $CONFIGPATH/boot.conf
install_config $CONFIGPATH/service_trim.conf

DEFAULT_LIGHTWEIGHT_DENYLIST="01_system-emergency-telnet 02_system-webserver auto-night-detection blue-led"

init_log()
{
    if [ ! -d $LOGDIR ]; then
        mkdir -p $LOGDIR
    fi
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
    : "${RTSP_SUBSTREAM:=1}"
    : "${RTSP_AUDIO:=1}"
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
    : "${MEM_GUARD_SOFT_SERVICES:=network-monitor auto-night-detection blue-led}"
    : "${MEM_GUARD_CRITICAL_SERVICES:=ftp-server telnet-server timelapse recording motion-detection}"

    if is_truthy "$SERVICE_TRIM"; then
        AUTOSTART_ALLOWLIST="$SERVICE_TRIM_ALLOWLIST"
        AUTOSTART_DENYLIST=""
    fi

    if is_truthy "$MEM_GUARD_ENABLE" && [ -n "$AUTOSTART_ALLOWLIST" ]; then
        if ! list_contains "memory-guard" $AUTOSTART_ALLOWLIST; then
            AUTOSTART_ALLOWLIST="$AUTOSTART_ALLOWLIST memory-guard"
        fi
    fi

    echo "Boot config: lightweight=$LIGHTWEIGHT_MODE lowcpu=$LOW_CPU_PROFILE lowram=$LOW_RAM_PROFILE memguard=$MEM_GUARD_ENABLE watchdog=$ENABLE_WATCHDOG ntp=$ENABLE_NTP crond=$ENABLE_CROND autostart=$ENABLE_AUTOSTART" >> $LOGPATH
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
    busybox watchdog -t 2 -T 5 /dev/watchdog
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

    # Unmonut RAM disk
    /bin/umount /dev/loop0
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
        udhcpc_status=$(udhcpc -i wlan0 -p /var/network/udhcpc.pid -b -x hostname:"$(hostname)")
        echo "udhcpc: $udhcpc_status" >> $LOGPATH
    else
        echo "Use Anyka default WIFI setup" >> $LOGPATH
        /usr/sbin/wifi_station.sh start
        /usr/sbin/wifi_station.sh connect
    fi
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
        busybox ntpd -q -n -p "$ntp_srv"
    else
        busybox ntpd -p "$ntp_srv"
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
*/15    *       *       *       *       busybox run-parts ${CRONPERIODIC}/15min
0       *       *       *       *       busybox run-parts ${CRONPERIODIC}/hourly
0       2       *       *       *       busybox run-parts ${CRONPERIODIC}/daily
0       3       *       *       6       busybox run-parts ${CRONPERIODIC}/weekly
0       5       1       *       *       busybox run-parts ${CRONPERIODIC}/monthly
EOF
      echo "Created cron directories and standard interval jobs" >> $LOGPATH
    fi
    busybox crond -c ${CONFIGPATH}/cron/crontabs
}

initialize_gpio()
{
    ir_led off
    ir_cut on
    blue_led off
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

init_password()
{
    pass=$(cat /mnt/config/user.pwd)
    all_password "$pass"
}

##############################################################
init_password
init_log
load_boot_config
echo "--------Starting Hacks--------" >> $LOGPATH
stop_cloud
enable_hardware_watchdog
init_network
sync_time
init_crond
initialize_gpio
init_rtsp_params
apply_low_cpu_profile
run_autostart_scripts
echo "$(date)" >> $LOGPATH
sleep 3
sync
echo 3 > /proc/sys/vm/drop_caches
echo "--------Starting Hacks Finished!--------" >> $LOGPATH
