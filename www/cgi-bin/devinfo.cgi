#!/bin/sh

source ./func.cgi
source /mnt/scripts/common_functions.sh

now_epoch_safe() {
  # Prefer pure /proc arithmetic (btime + uptime) — no process fork
  btime="$(awk '/^btime / {print $2; exit}' /proc/stat 2>/dev/null)"
  up="$(cut -d'.' -f1 /proc/uptime 2>/dev/null)"
  case "$btime" in ''|*[!0-9]*) btime=0 ;; esac
  case "$up" in ''|*[!0-9]*) up=0 ;; esac
  if [ "$btime" -gt 0 ] 2>/dev/null && [ "$up" -gt 0 ] 2>/dev/null; then
    echo $((btime + up))
    return
  fi
  # fallback: spawn date if /proc data unavailable
  ts="$(date +%s 2>/dev/null)"
  case "$ts" in
    ''|*[!0-9]*) echo "0" ;;
    *) echo "$ts" ;;
  esac
}

uptime_seconds_safe() {
  if [ ! -r /proc/uptime ]; then
    echo "0"
    return
  fi
  up="$(cut -d'.' -f1 /proc/uptime 2>/dev/null)"
  case "$up" in
    ''|*[!0-9]*)
      echo "0"
      ;;
    *)
      echo "$up"
      ;;
  esac
}

format_epoch() {
  epoch="$1"
  if [ "$epoch" -le 0 ] 2>/dev/null; then
    echo "n/a"
    return
  fi

  formatted="$(date -d "@$epoch" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null)"
  if [ -z "$formatted" ] && [ -x /mnt/bin/busybox ]; then
    formatted="$(/mnt/bin/busybox date -d "@$epoch" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null)"
  fi
  if [ -z "$formatted" ] && [ -x /bin/busybox ]; then
    formatted="$(/bin/busybox date -d "@$epoch" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null)"
  fi
  [ -z "$formatted" ] && formatted="epoch $epoch"
  echo "$formatted"
}

format_uptime() {
  total="$1"
  if [ "$total" -le 0 ] 2>/dev/null; then
    echo "n/a"
    return
  fi

  days=$((total / 86400))
  rem=$((total % 86400))
  hours=$((rem / 3600))
  rem=$((rem % 3600))
  mins=$((rem / 60))
  secs=$((rem % 60))
  printf '%dd %02dh %02dm %02ds' "$days" "$hours" "$mins" "$secs"
}


last_boot_epoch="$(awk '/^btime / {print $2; exit}' /proc/stat 2>/dev/null)"
case "$last_boot_epoch" in
  ''|*[!0-9]*)
    last_boot_epoch="0"
    ;;
esac
if [ "$last_boot_epoch" -le 0 ] 2>/dev/null; then
  now_epoch="$(now_epoch_safe)"
  uptime_secs="$(uptime_seconds_safe)"
  if [ "$now_epoch" -gt 0 ] 2>/dev/null && [ "$uptime_secs" -gt 0 ] 2>/dev/null; then
    last_boot_epoch=$((now_epoch - uptime_secs))
  fi
fi

uptime_secs="$(uptime_seconds_safe)"
last_boot_text="$(format_epoch "$last_boot_epoch")"
uptime_text="$(format_uptime "$uptime_secs")"
binary_versions_text="$(cat /tmp/devinfo_binary_versions.txt 2>/dev/null)"
[ -n "$binary_versions_text" ] || binary_versions_text="$(build_binary_versions_block)"
release_text="$(cat /usr/local/factory_fw_version 2>/dev/null)"
[ -n "$release_text" ] || release_text="n/a"
system_text="$(uname -a 2>/dev/null)"
[ -n "$system_text" ] || system_text="n/a"
cpu_text="$(cat /proc/cpuinfo 2>/dev/null)"
[ -n "$cpu_text" ] || cpu_text="n/a"
clock_text="$(run_strings /tmp/start_message | grep -m1 "clocks:" 2>/dev/null)"
[ -n "$clock_text" ] || clock_text="n/a"
bootloader_text="$(cat /tmp/devinfo_bootloader.txt 2>/dev/null)"
[ -n "$bootloader_text" ] || bootloader_text="$(run_strings /dev/mtd0 | grep -m1 'U-Boot 2' 2>/dev/null)"
[ -n "$bootloader_text" ] || bootloader_text="n/a"
cmdline_text="$(cat /proc/cmdline 2>/dev/null)"
[ -n "$cmdline_text" ] || cmdline_text="n/a"

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

cat << EOF
<div class='info-grid'>
    <div class='info-side'>
        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M8 4h8a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM10 17h4'/></svg><span>Device Summary</span></span></p></header>
            <div class='card-content'>
                Release:
                <pre class='info-pre'>${release_text}</pre>
                Kernel:
                <pre class='info-pre'>${system_text}</pre>
                Clocks:
                <pre class='info-pre'>${clock_text}</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M12 4a8 8 0 1 1-8 8 8 8 0 0 1 8-8zm1 4h-2v5h5v-2h-3z'/></svg><span>Runtime</span></span></p></header>
            <div class='card-content'>
                Last reboot:
                <pre class='info-pre'>${last_boot_text} (epoch ${last_boot_epoch})</pre>
                Uptime:
                <pre class='info-pre'>${uptime_text} (${uptime_secs}s)</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7h16v10H4zM8 11h8M8 14h5M7 7V5M17 7V5'/></svg><span>Bootloader</span></span></p></header>
            <div class='card-content'>
                Version:
                <pre class='info-pre'>${bootloader_text}</pre>
                CMD line:
                <pre class='info-pre'>${cmdline_text}</pre>
                <a target="_blank" href="cgi-bin/dumpbootloader.cgi">Download Bootloader</a>
            </div>
        </div>
    </div>

    <div class='info-main'>
        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M8 8h8v8H8zM4 10h2M4 14h2M18 10h2M18 14h2M10 4v2M14 4v2M10 18v2M14 18v2'/></svg><span>CPU Information</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>${cpu_text}</pre>
            </div>
        </div>

        <div class='card status_card info-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M12 3 2 9l10 6 10-6-10-6zm0 8.7L6.3 9 12 5.3 17.7 9 12 11.7zM4 13l8 4.8 8-4.8v2.3L12 20 4 15.3V13z'/></svg><span>Binary Versions</span></span></p></header>
            <div class='card-content'>
                <pre class='info-pre info-pre-scroll'>${binary_versions_text}</pre>
            </div>
        </div>
    </div>
</div>

</body>
</html>
EOF
