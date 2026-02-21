#!/bin/sh


source ./func.cgi


echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

mem_total=0
mem_available=0
mem_free=0
mem_cached=0
mem_buffers=0
mem_sreclaimable=0
mem_shmem=0

while IFS=' ' read -r key value _; do
  case "$key" in
    MemTotal:) mem_total="$value" ;;
    MemAvailable:) mem_available="$value" ;;
    MemFree:) mem_free="$value" ;;
    Cached:) mem_cached="$value" ;;
    Buffers:) mem_buffers="$value" ;;
    SReclaimable:) mem_sreclaimable="$value" ;;
    Shmem:) mem_shmem="$value" ;;
  esac
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
mem_cached_total=$((mem_cached + mem_buffers + mem_sreclaimable))

proc_count=0
for proc_dir in /proc/[0-9]*; do
  [ -d "$proc_dir" ] || continue
  proc_count=$((proc_count + 1))
done

open_files="n/a"
if read -r open_alloc _ open_max < /proc/sys/fs/file-nr 2>/dev/null; then
  open_files="${open_alloc}/${open_max}"
fi

loadavg="$(cat /proc/loadavg 2>/dev/null)"
uptime_line="$(uptime)"

read -r _ cpu_user cpu_nice cpu_system cpu_idle cpu_iowait cpu_irq cpu_softirq cpu_steal _ _ < /proc/stat
cpu_active=$((cpu_user + cpu_nice + cpu_system + cpu_irq + cpu_softirq + cpu_steal))
cpu_total=$((cpu_active + cpu_idle + cpu_iowait))

cat << EOF
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Quick System Summary</p></header>
    <div class='card-content'>
        <pre>Uptime: $uptime_line
Load avg: $loadavg
Processes: $proc_count
Open files: $open_files</pre>
    </div>
</div>

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Memory Snapshot</p></header>
    <div class='card-content'>
        <pre>MemTotal: ${mem_total} kB
MemAvailable: ${mem_available} kB
MemUsed(approx): ${mem_used} kB
Cache+Buffers+SReclaimable: ${mem_cached_total} kB</pre>
    </div>
</div>

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>CPU Counters</p></header>
    <div class='card-content'>
        <pre>Active ticks: $cpu_active
Total ticks: $cpu_total
Snapshot source: /proc/stat</pre>
    </div>
</div>

<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Process List (light)</p></header>
    <div class='card-content'>
        <pre>$(ps)</pre>
    </div>
</div>
EOF
