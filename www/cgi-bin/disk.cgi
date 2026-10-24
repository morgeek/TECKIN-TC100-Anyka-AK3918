#!/bin/sh

. /mnt/www/cgi-bin/func.cgi
rate_limit_check 30 60

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""
PATH="/bin:/sbin:/usr/bin:/usr/sbin"

# Disk growth forecasting: compare current usage % to a cached value from last hour.
DISK_USAGE_CACHE="/tmp/disk_usage.cache"
_disk_forecast=""
_btime=0
while read -r _k _v _; do [ "$_k" = "btime" ] && _btime="$_v" && break; done < /proc/stat
read -r _up _ < /proc/uptime
_now_ts=$((_btime + ${_up%.*}))
_mnt_pct="$(df /mnt 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5); print $5+0}')"
case "$_mnt_pct" in ''|*[!0-9]*) _mnt_pct="" ;; esac
if [ -n "$_mnt_pct" ]; then
    if [ -f "$DISK_USAGE_CACHE" ]; then
        read -r _cached_ts _cached_pct < "$DISK_USAGE_CACHE" 2>/dev/null || true
        case "$_cached_ts" in ''|*[!0-9]*) _cached_ts=0 ;; esac
        case "$_cached_pct" in ''|*[!0-9]*) _cached_pct="" ;; esac
        _age=$((_now_ts - _cached_ts))
        if [ "$_age" -ge 1800 ] && [ -n "$_cached_pct" ] && [ "$_mnt_pct" -gt "$_cached_pct" ]; then
            # Growth rate in percentage points per hour
            _growth_rate_x100=$(( (_mnt_pct - _cached_pct) * 360000 / _age ))
            if [ "$_growth_rate_x100" -gt 0 ]; then
                _remaining=$(( 100 - _mnt_pct ))
                _hours_left=$(( _remaining * 10000 / _growth_rate_x100 ))
                if [ "$_hours_left" -lt 24 ]; then
                    _disk_forecast="WARNING: SD card may fill within ${_hours_left}h at current growth rate"
                elif [ "$_hours_left" -lt 168 ]; then
                    _disk_days=$(( _hours_left / 24 ))
                    _disk_forecast="SD card may fill in ~${_disk_days} day(s) at current growth rate"
                else
                    _disk_forecast="Growth rate low — no fill risk detected in the next 7 days"
                fi
            fi
        fi
    fi
    # Update cache if absent or older than 1 hour
    if [ ! -f "$DISK_USAGE_CACHE" ] || [ "$(( _now_ts - $(awk '{print $1+0}' "$DISK_USAGE_CACHE" 2>/dev/null || echo 0) ))" -ge 3600 ]; then
        printf '%s %s\n' "$_now_ts" "$_mnt_pct" > "$DISK_USAGE_CACHE" 2>/dev/null || true
    fi
fi

df_text="$(df -h 2>/dev/null)"
iostat_text="$(iostat -d -k 2>/dev/null)"
mount_text="$(mount 2>/dev/null)"

# Single pass over df output: SD card usage + filesystem count. (The summary
# used to show the root filesystem, a read-only squashfs that is always 100 %
# full by design — an alarming number that meant nothing.)
eval "$(printf '%s\n' "$df_text" | awk '
  NR==1{next}
  {count++}
  $1 ~ /mmcblk/ && ($NF=="/mnt"||$NF=="/mnt/sd") && !sd {sd=$3 " used of " $2 " (" $5 ")"}
  END{
    printf "sd_usage=\"%s\"\n", (sd ? sd : "n/a")
    printf "filesystem_count=%d\n", count+0
  }
')"
# Single pass over mount output: mount count + mmc mount point
eval "$(printf '%s\n' "$mount_text" | awk '
  NF{count++}
  /mmcblk/ && !mmc{mmc=$3 " (" $1 ")"}
  END{
    printf "mount_count=%d\n", count+0
    if (mmc) printf "mmc_mount=\"%s\"\n", mmc
    else      printf "mmc_mount=n/a\n"
  }
')"

# SPI NOR Flash partition layout & payload usage (from /sys/class/mtd and binary headers)
flash_card_html=""
if [ -d /sys/class/mtd/mtd0 ]; then
    flash_tot=0
    flash_used_tot=0
    flash_map_segs=""
    flash_legend=""
    flash_rows=""
    for _d in /sys/class/mtd/mtd[0-9]*; do
        case "$_d" in *ro) continue ;; esac
        [ -r "$_d/size" ] || continue
        _sz="$(cat "$_d/size" 2>/dev/null)"
        case "$_sz" in ''|*[!0-9]*) continue ;; esac
        flash_tot=$((flash_tot + _sz))
    done
    [ "$flash_tot" -le 0 ] && flash_tot=8388608

    for _d in /sys/class/mtd/mtd[0-9]*; do
        case "$_d" in *ro) continue ;; esac
        [ -r "$_d/size" ] || continue
        _m="${_d##*/}"
        _name="$(cat "$_d/name" 2>/dev/null)"
        _sz="$(cat "$_d/size" 2>/dev/null)"
        _flags="$(cat "$_d/flags" 2>/dev/null)"
        _off="$(cat "$_d/offset" 2>/dev/null)"
        case "$_sz" in ''|*[!0-9]*) continue ;; esac
        case "$_off" in ''|*[!0-9]*) _off=0 ;; esac

        _ro="RO"
        [ $(( ${_flags:-0} & 0x400 )) -ne 0 ] 2>/dev/null && _ro="RW"

        _used="$_sz"
        _role="System partition"
        _color="#64748b"
        case "$_name" in
            boot)
                _color="#6366f1"
                _role="U-Boot bootloader"
                _used="$_sz"
                ;;
            kernel)
                _color="#3b82f6"
                _role="Linux 6.6 uImage + DTB"
                _khex="$(dd if=/dev/${_m}ro bs=1 skip=12 count=4 2>/dev/null | od -An -tx1 | tr -d ' \n')"
                case "$_khex" in [0-9a-fA-F][0-9a-fA-F]*)
                    _ksz=$(( 0x$_khex + 64 ))
                    [ "$_ksz" -gt 64 ] && [ "$_ksz" -le "$_sz" ] && _used="$_ksz"
                ;; esac
                ;;
            mac)
                _color="#a855f7"
                _role="Factory MAC address"
                ;;
            env)
                _color="#ec4899"
                _role="U-Boot environment"
                ;;
            initrd)
                _color="#06b6d4"
                _role="Initramfs (XZ RAM root)"
                _icmd="$(sed -n 's/.*initrd=0x[0-9a-fA-F]*,\([0-9][0-9]*\).*/\1/p' /proc/cmdline 2>/dev/null)"
                case "$_icmd" in [0-9]*) [ "$_icmd" -gt 0 ] && [ "$_icmd" -le "$_sz" ] && _used="$_icmd" ;; esac
                ;;
            stack)
                _color="#10b981"
                _role="User space SquashFS (/rom)"
                _shex="$(dd if=/dev/${_m}ro bs=1 skip=40 count=4 2>/dev/null | od -An -tx1 | awk '{print $4$3$2$1}')"
                case "$_shex" in [0-9a-fA-F][0-9a-fA-F]*)
                    _ssz=$(( 0x$_shex ))
                    # SquashFS is padded to 4K blocks
                    _ssz=$(( (_ssz + 4095) / 4096 * 4096 ))
                    [ "$_ssz" -gt 0 ] && [ "$_ssz" -le "$_sz" ] && _used="$_ssz"
                ;; esac
                ;;
            cfga|cfgb)
                _color="#f59e0b"
                _role="Persistent settings slot (${_name#cfg})"
                _chdr="$(dd if=/dev/${_m}ro bs=1 count=64 2>/dev/null | tr '\000\377' '  ')"
                _clen="$(printf '%s' "$_chdr" | awk '$1=="TC1CFG"{print $3+64; exit}')"
                case "$_clen" in [0-9]*) [ "$_clen" -gt 0 ] && [ "$_clen" -le "$_sz" ] && _used="$_clen" ;; *) _used=0 ;; esac
                ;;
        esac

        flash_used_tot=$((flash_used_tot + _used))
        _free=$((_sz - _used))
        [ "$_free" -lt 0 ] && _free=0
        _upct=$(( (_used * 100 + _sz / 2) / _sz ))
        [ "$_upct" -gt 100 ] && _upct=100

        # Proportion of the 8 MiB chip (in hundredths of a percent for CSS width, min 1.2% so tiny 4K partitions remain visible)
        _chip_bp=$(( _sz * 10000 / flash_tot ))
        _chip_pct="$(awk "BEGIN{w=$_chip_bp/100; if(w<1.2) w=1.2; printf \"%.2f\", w}")"
        _chip_real_pct="$(awk "BEGIN{printf \"%.2f\", $_sz*100/$flash_tot}")"

        _sz_fmt="$(awk "BEGIN{if($_sz>=1048576) printf \"%.2f MiB (%d KB)\", $_sz/1048576, $_sz/1024; else printf \"%d KB\", $_sz/1024}")"
        _used_fmt="$(awk "BEGIN{if($_used>=1048576) printf \"%.2f MiB\", $_used/1048576; else if($_used>=1024) printf \"%.1f KB\", $_used/1024; else printf \"%d B\", $_used}")"
        _free_fmt="$(awk "BEGIN{if($_free>=1048576) printf \"%.2f MiB\", $_free/1048576; else if($_free>=1024) printf \"%.1f KB\", $_free/1024; else printf \"%d B\", $_free}")"
        _off_hex="$(printf '0x%06X' "$_off")"

        flash_map_segs="${flash_map_segs}<div class='flash-seg' style='flex:${_chip_pct} 1 0%;background:${_color}' title='${_name} (${_m}): ${_sz_fmt} — ${_upct}% used (${_used_fmt} / ${_sz_fmt})'><span class='flash-seg-label'>${_name}</span></div>"
        flash_legend="${flash_legend}<span class='flash-leg-item'><i style='background:${_color}'></i><strong>${_name}</strong> <small>${_chip_real_pct}%</small></span>"
        flash_rows="${flash_rows}<tr>
            <td><span class='flash-dot' style='background:${_color}'></span><strong>${_name}</strong> <small class='text-muted'>(${_m})</small></td>
            <td><code>${_off_hex}</code></td>
            <td><span class='flash-mode-badge is-${_ro}'>${_ro}</span></td>
            <td>${_role}</td>
            <td class='num'>${_used_fmt} / ${_sz_fmt}</td>
            <td class='num'>${_free_fmt}</td>
            <td class='flash-bar-cell'>
                <div class='flash-part-bar' title='${_upct}% used'>
                    <div class='flash-part-fill' style='width:${_upct}%;background:${_color}'></div>
                </div>
                <span class='flash-pct-txt'>${_upct}%</span>
            </td>
        </tr>"
    done

    _tot_mb="$(awk "BEGIN{printf \"%.2f MiB\", $flash_tot/1048576}")"
    _used_mb="$(awk "BEGIN{printf \"%.2f MiB\", $flash_used_tot/1048576}")"
    _free_mb="$(awk "BEGIN{printf \"%.2f MiB\", ($flash_tot - $flash_used_tot)/1048576}")"
    _tot_pct=$(( (flash_used_tot * 100 + flash_tot / 2) / flash_tot ))

    flash_card_html="
        <div class='card status_card info-card'>
            <header class='card-header'>
                <p class='card-header-title'>
                    <span class='title-with-icon'>
                        <svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M6 4h12v16H6zM9 2v2M15 2v2M9 20v2M15 20v2M2 9h4M2 15h4M18 9h4M18 15h4'/></svg>
                        <span>SPI NOR Flash Layout (${_tot_mb} — ${_used_mb} used, ${_free_mb} free, ${_tot_pct}%)</span>
                    </span>
                </p>
            </header>
            <div class='card-content'>
                <div class='flash-map-bar' role='img' aria-label='SPI Flash partition proportions'>${flash_map_segs}</div>
                <div class='flash-legend'>${flash_legend}</div>
                <div class='table-container' style='margin-top:0.75rem'>
                    <table class='table is-fullwidth is-narrow flash-table'>
                        <thead>
                            <tr>
                                <th>Partition</th>
                                <th>Offset</th>
                                <th>Mode</th>
                                <th>Role</th>
                                <th>Payload / Size</th>
                                <th>Free</th>
                                <th>Fill</th>
                            </tr>
                        </thead>
                        <tbody>${flash_rows}</tbody>
                    </table>
                </div>
            </div>
        </div>"
fi

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
        # Single pass: read_ios (field 1), write_ios (field 5), in_flight (field 9)
        eval "$(printf '%s' "$stat_line" | awk '{
          printf "mmc_read_ios=%d\n",  $1+0
          printf "mmc_write_ios=%d\n", $5+0
          printf "in_flight=%d\n",     $9+0
        }')"
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
                SD card usage:
                <pre class='info-pre'>$sd_usage</pre>
                SD growth forecast:
                <pre class='info-pre'>${_disk_forecast:-collecting data...}</pre>
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
        ${flash_card_html}
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
