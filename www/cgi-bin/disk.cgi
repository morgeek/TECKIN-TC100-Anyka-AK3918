#!/bin/sh

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""
source ./func.cgi
PATH="/bin:/sbin:/usr/bin:/usr/sbin"

df_text="$(df -h 2>/dev/null)"
iostat_text="$(iostat -d -k 2>/dev/null)"
mount_text="$(mount 2>/dev/null)"

root_usage="$(printf '%s\n' "$df_text" | awk '$NF=="/"{print $5; exit}')"
[ -n "$root_usage" ] || root_usage="n/a"
filesystem_count="$(printf '%s\n' "$df_text" | awk 'NR>1{count++} END{print count+0}')"
mount_count="$(printf '%s\n' "$mount_text" | awk 'NF{count++} END{print count+0}')"
mmc_mount="$(printf '%s\n' "$mount_text" | awk '/mmcblk/{print $3 " (" $1 ")"; exit}')"
[ -n "$mmc_mount" ] || mmc_mount="n/a"

# SD card health from sysfs
MMC_BLOCK="/sys/block/mmcblk0"
mmc_name="n/a"
mmc_type="n/a"
mmc_size_mb="n/a"
mmc_read_ios="n/a"
mmc_write_ios="n/a"
mmc_io_errors="n/a"
mmc_health_note=""

if [ -d "$MMC_BLOCK" ]; then
    # Card identity
    if [ -r "$MMC_BLOCK/device/name" ]; then
        mmc_name="$(cat "$MMC_BLOCK/device/name" 2>/dev/null)"
    fi
    if [ -r "$MMC_BLOCK/device/type" ]; then
        mmc_type="$(cat "$MMC_BLOCK/device/type" 2>/dev/null)"
    fi

    # Size in MB (sectors are 512 bytes)
    if [ -r "$MMC_BLOCK/size" ]; then
        sectors="$(cat "$MMC_BLOCK/size" 2>/dev/null)"
        case "$sectors" in
            ''|*[!0-9]*) ;;
            *) mmc_size_mb="$(awk "BEGIN{printf \"%.0f\", $sectors/2048}") MB" ;;
        esac
    fi

    # I/O statistics from /sys/block/mmcblk0/stat
    # Fields: read_ios read_merges read_sectors read_ticks write_ios write_merges write_sectors write_ticks in_flight io_ticks time_in_queue
    if [ -r "$MMC_BLOCK/stat" ]; then
        stat_line="$(cat "$MMC_BLOCK/stat" 2>/dev/null)"
        mmc_read_ios="$(printf '%s' "$stat_line" | awk '{print $1+0}')"
        mmc_write_ios="$(printf '%s' "$stat_line" | awk '{print $5+0}')"
        in_flight="$(printf '%s' "$stat_line" | awk '{print $9+0}')"
        [ "$in_flight" = "0" ] && mmc_io_errors="none detected" || mmc_io_errors="$in_flight in-flight"
    fi

    # eMMC wear/health (may not exist on removable SD cards)
    if [ -r "$MMC_BLOCK/device/life_time" ]; then
        life_time="$(cat "$MMC_BLOCK/device/life_time" 2>/dev/null)"
        mmc_health_note="eMMC life_time: $life_time"
    fi
    if [ -r "$MMC_BLOCK/device/pre_eol_info" ]; then
        eol="$(cat "$MMC_BLOCK/device/pre_eol_info" 2>/dev/null)"
        case "$eol" in
            0x00|00) mmc_health_note="${mmc_health_note:+$mmc_health_note | }EOL: Normal" ;;
            0x01|01) mmc_health_note="${mmc_health_note:+$mmc_health_note | }EOL: Warning (>80% worn)" ;;
            0x02|02) mmc_health_note="${mmc_health_note:+$mmc_health_note | }EOL: Urgent (>90% worn)" ;;
            *)        mmc_health_note="${mmc_health_note:+$mmc_health_note | }EOL: $eol" ;;
        esac
    fi
    [ -n "$mmc_health_note" ] || mmc_health_note="n/a (standard SD — no wear counters)"
else
    mmc_health_note="mmcblk0 not found in sysfs"
fi

cat << EOF
<div class='info-grid'>
    <div class='info-side'>
        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3s-3.6 3-8 3s-8-1.3-8-3zM4 12c0 1.7 3.6 3 8 3s8-1.3 8-3M4 17c0 1.7 3.6 3 8 3s8-1.3 8-3'/></svg><span>Disk Summary</span></span></p></header>
            <div class='card-content'>
                Root usage:
                <pre class='info-pre'>$root_usage</pre>
                Filesystems:
                <pre class='info-pre'>$filesystem_count</pre>
                Mount points:
                <pre class='info-pre'>$mount_count</pre>
                SD mount:
                <pre class='info-pre'>$mmc_mount</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M5 19h14M7 15l3-3l3 2l4-5'/></svg><span>Disk IO Snapshot (kB)</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre'>$iostat_text</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M5 4h14a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM9 9h.01M12 4v6'/></svg><span>SD Card Health</span></span></p></header>
            <div class='card-content'>
                Card name:
                <pre class='info-pre'>$mmc_name</pre>
                Card type:
                <pre class='info-pre'>$mmc_type</pre>
                Card size:
                <pre class='info-pre'>$mmc_size_mb</pre>
                Total read I/Os:
                <pre class='info-pre'>$mmc_read_ios</pre>
                Total write I/Os:
                <pre class='info-pre'>$mmc_write_ios</pre>
                In-flight / errors:
                <pre class='info-pre'>$mmc_io_errors</pre>
                Wear / EOL info:
                <pre class='info-pre'>$mmc_health_note</pre>
            </div>
        </div>
    </div>

    <div class='info-main'>
        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3s-3.6 3-8 3s-8-1.3-8-3zM4 12c0 1.7 3.6 3 8 3s8-1.3 8-3M4 17c0 1.7 3.6 3 8 3s8-1.3 8-3'/></svg><span>Disk Space Information</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>$df_text</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M3 7h7l2 2h9v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/></svg><span>Mounts</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>$mount_text</pre>
            </div>
        </div>
    </div>
</div>

</body>
</html>
EOF
