#!/bin/sh


. /mnt/www/cgi-bin/func.cgi
rate_limit_check 30 60

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

cpu_temp=""
for _tz in /sys/class/thermal/thermal_zone*/temp; do
  [ -f "$_tz" ] || continue
  _raw="$(cat "$_tz" 2>/dev/null)"
  if [ -n "$_raw" ] && [ "$_raw" -gt 0 ] 2>/dev/null; then
    cpu_temp="$((_raw / 1000)).$(( (_raw % 1000) / 100 ))°C"
    break
  fi
done

cat << EOF
<div class='sysusage-grid'>
    <div class='sysusage-side'>
        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M4 18h16M7 14l3-3l3 2l4-5'/></svg><span>Quick System Summary</span></span></p></header>
            <div class='card-content'>
                <pre class='sysusage-pre'>Uptime: $uptime_line
Load avg: $loadavg
Processes: $proc_count
Open files: $open_files</pre>
            </div>
        </div>

        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M8 8h8v8H8zM4 10h2M4 14h2M18 10h2M18 14h2M10 4v2M14 4v2M10 18v2M14 18v2'/></svg><span>Memory Snapshot</span></span></p></header>
            <div class='card-content'>
                <pre class='sysusage-pre'>MemTotal: ${mem_total} kB
MemAvailable: ${mem_available} kB
MemUsed(approx): ${mem_used} kB
Cache+Buffers+SReclaimable: ${mem_cached_total} kB</pre>
            </div>
        </div>

        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M12 3v3M12 18v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M3 12h3M18 12h3M4.9 19.1L7 17M17 7l2.1-2.1M12 8a4 4 0 1 1 0 8'/></svg><span>CPU Counters</span></span></p></header>
            <div class='card-content'>
                <pre class='sysusage-pre'>Active ticks: $cpu_active
Total ticks: $cpu_total
Snapshot source: /proc/stat$([ -n "$cpu_temp" ] && echo "
Temperature: $cpu_temp")</pre>
            </div>
        </div>

        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M9 12l2 2l4-4M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z'/></svg><span>Service Health</span></span></p></header>
            <div class='card-content' id='svc_health_body'><em class='text-muted'>Loading service health...</em></div>
        </div>
    </div>

    <div class='sysusage-main'>
        <div class='card status_card sysusage-card sysusage-process-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M8 7h12M8 12h12M8 17h12M4 7h.01M4 12h.01M4 17h.01'/></svg><span>Process List (light)</span></span></p></header>
            <div class='card-content'>
                <pre class='sysusage-pre sysusage-process-pre'>$(ps)</pre>
            </div>
        </div>

        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2M9 5h6M9 12h6M9 16h4'/></svg><span>Recent Events</span></span></p></header>
            <div class='card-content' id='recent_events_body'><em class='text-muted'>Loading events...</em></div>
        </div>
    </div>
</div>
<script>
(function(){
  var body = document.getElementById('svc_health_body');
  if (!body) return;
  fetch('cgi-bin/health.cgi', {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      var svcs = d.services || {};
      var rst  = d.service_restarts || {};
      var keys = Object.keys(svcs).sort();
      if (!keys.length) { body.innerHTML = '<em>No services found</em>'; return; }
      var rows = keys.map(function(svc){
        var st = svcs[svc];
        var rc = rst[svc] || 0;
        var stClass = st === 'running' ? 'svc-cell-running' : (st === 'absent' ? 'svc-cell-absent' : 'svc-cell-stopped');
        var badge = '';
        if (rc > 0) {
          var bClass = rc > 3 ? 'badge-high' : 'badge-warn';
          badge = '<span class="svc-restart-badge '+bClass+'">'+rc+' restart'+(rc===1?'':'s')+'</span>';
        }
        return '<tr><td class="'+stClass+'">'+svc+'</td>'
             + '<td class="'+stClass+'">'+st+'</td>'
             + '<td>'+badge+'</td></tr>';
      });
      body.innerHTML = '<table class="svc-health-table">'
        + '<thead><tr><th>Service</th><th>Status</th><th>Restarts</th></tr></thead>'
        + '<tbody>'+rows.join('')+'</tbody></table>';
    })
    .catch(function(){ body.innerHTML = '<em class="text-error">Health data unavailable</em>'; });
})();
</script>
<script>
(function(){
  var evBody = document.getElementById('recent_events_body');
  if (!evBody) return;
  fetch('cgi-bin/events.cgi?limit=40', {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(events){
      if (!Array.isArray(events) || !events.length) {
        evBody.innerHTML = '<em class="text-muted">No events recorded yet</em>';
        return;
      }
      var rows = events.slice().reverse().map(function(ev){
        var ts  = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : '?';
        var lvl = String(ev.level || 'info');
        var cat = String(ev.category || '');
        var msg = String(ev.message || '');
        return '<tr>'
          + '<td class="evt-ts">'+ts+'</td>'
          + '<td class="evt-lvl evt-lvl-'+lvl+'">'+lvl+'</td>'
          + '<td class="evt-cat">'+cat+'</td>'
          + '<td class="evt-msg">'+msg+'</td></tr>';
      });
      evBody.innerHTML = '<table class="evt-table">'
        + '<thead><tr><th>Time</th><th>Level</th><th>Category</th><th>Message</th></tr></thead>'
        + '<tbody>'+rows.join('')+'</tbody></table>';
    })
    .catch(function(){ evBody.innerHTML = '<em class="text-error">Event log unavailable</em>'; });
})();
</script>
EOF
