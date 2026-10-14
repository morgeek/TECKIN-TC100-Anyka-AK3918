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

# One load line: "uptime" also prints the load average, which duplicated
# the /proc/loadavg line below it.
read -r load1 load5 load15 load_tasks _ < /proc/loadavg 2>/dev/null
read -r up_s _ < /proc/uptime 2>/dev/null
up_s="${up_s%.*}"; case "$up_s" in ''|*[!0-9]*) up_s=0 ;; esac
up_d=$((up_s / 86400)); up_h=$((up_s % 86400 / 3600)); up_m=$((up_s % 3600 / 60))
if [ "$up_d" -gt 0 ]; then uptime_line="${up_d}d ${up_h}h ${up_m}m"; else uptime_line="${up_h}h ${up_m}m"; fi

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

# kB -> "12.3 MB"
mb() { awk -v k="$1" 'BEGIN { printf "%.1f MB", k / 1024 }'; }
mem_avail_pct=0
[ "$mem_total" -gt 0 ] 2>/dev/null && mem_avail_pct=$((100 * mem_available / mem_total))
cpu_busy_pct=0
[ "$cpu_total" -gt 0 ] 2>/dev/null && cpu_busy_pct=$((100 * cpu_active / cpu_total))

cat << EOF
<div class='sysusage-grid'>
    <div class='sysusage-side'>
        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'>System</p></header>
            <div class='card-content'>
                <dl class='v2-facts'>
                    <dt>Up for</dt><dd>$uptime_line</dd>
                    <dt>Load (1, 5, 15 min)</dt><dd>$load1 &nbsp; $load5 &nbsp; $load15</dd>
                    <dt>CPU busy since boot</dt><dd>$cpu_busy_pct %</dd>
                    <dt>Processes</dt><dd>$proc_count</dd>$([ -n "$cpu_temp" ] && echo "
                    <dt>Chip temperature</dt><dd>$cpu_temp</dd>")
                </dl>
            </div>
        </div>

        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'>Memory</p></header>
            <div class='card-content'>
                <dl class='v2-facts'>
                    <dt>Available</dt><dd>$(mb "$mem_available") of $(mb "$mem_total") ($mem_avail_pct %)</dd>
                    <dt>Used by programs</dt><dd>$(mb "$mem_used")</dd>
                    <dt>Cache (reclaimable)</dt><dd>$(mb "$mem_cached_total")</dd>
                    <dt>Open files</dt><dd>$open_files</dd>
                </dl>
            </div>
        </div>

    </div>

    <div class='sysusage-main'>
        <div class='card status_card sysusage-card sysusage-process-card'>
            <details class='v2-procs'>
                <summary>Running processes ($proc_count)</summary>
                <pre class='sysusage-pre sysusage-process-pre'>$(ps)</pre>
            </details>
        </div>

        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2M9 5h6M9 12h6M9 16h4'/></svg><span>Recent events</span></span></p></header>
            <div class='card-content' id='recent_events_body'><em class='text-muted'>Loading events...</em></div>
        </div>
        <div class='card status_card sysusage-card'>
            <header class='card-header'><p class='card-header-title'><span class='title-with-icon'><svg class='title-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M9 12l2 2l4-4M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z'/></svg><span>Services</span></span></p></header>
            <div class='card-content' id='svc_health_body'><em class='text-muted'>Loading service health...</em></div>
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
      var keys = Object.keys(svcs).filter(function(k){ return svcs[k] !== 'absent'; }).sort();
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
