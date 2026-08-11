#!/bin/sh
# health-snapshot.sh — Background daemon that refreshes the health.cgi cache
# every HEALTH_SNAPSHOT_INTERVAL_SECONDS (default 30).
# This makes health.cgi instant: it always reads a pre-built cache file instead
# of running 15 blocking service probes per HTTP request.
#
# Started by the health-snapshot controlscript; PID written to /var/run/health-snapshot.pid.

CACHE_FILE="/tmp/health_snapshot.cache"
HEALTH_CGI="/mnt/www/cgi-bin/health.cgi"
INTERVAL="${HEALTH_SNAPSHOT_INTERVAL_SECONDS:-30}"
PIDFILE="/var/run/health-snapshot.pid"

case "$INTERVAL" in ''|*[!0-9]*) INTERVAL=30 ;; esac
[ "$INTERVAL" -lt 10 ] && INTERVAL=10
[ "$INTERVAL" -gt 300 ] && INTERVAL=300

echo "$$" > "$PIDFILE" 2>/dev/null || true
trap 'rm -f "$PIDFILE"; exit 0' TERM INT

_btime=0
_now() {
  if [ "$_btime" -le 0 ]; then
    while read -r _k _v _; do [ "$_k" = "btime" ] && _btime="$_v" && break; done < /proc/stat
  fi
  read -r _up _ < /proc/uptime
  _ts=$((_btime + ${_up%.*}))
}

probe_service() {
  _svc="$1"
  _script="/mnt/controlscripts/$_svc"
  [ -x "$_script" ] || { echo "absent"; return; }
  _out="$("$_script" health 2>/dev/null)"
  case "$_out" in
    ok:*)   echo "running" ;;
    warn:*) echo "stopped" ;;
    *)
      _out="$("$_script" status 2>/dev/null)"
      if [ -n "$_out" ]; then echo "running"; else echo "stopped"; fi
      ;;
  esac
}

# The exec-everything sweep above costs ~10 s of CPU on the AK3918 and this
# daemon used to pay it every cycle — a third of the CPU budget spent on
# monitoring alone. The shared prober keeps the pidfile checks fork-free and
# execs only the deep/composite services (see scripts/health-probe.sh).
if [ -r /mnt/scripts/health-probe.sh ]; then
  . /mnt/scripts/health-probe.sh
else
  probe_service_fast() { probe_service "$1"; }
fi

build_snapshot() {
  _now

  _memtotal=0; _memfree=0; _memavail=0
  while IFS=: read -r _mk _mv _mu; do
    # Same fix as health.cgi: /proc/meminfo pads with several spaces, stripping
    # one then cutting at the next produced "" and invalid JSON in the cache.
    _mnum=0
    for _mw in $_mv; do _mnum="$_mw"; break; done
    _mv="$_mnum"
    case "$_mk" in
      MemTotal)     _memtotal="$_mv" ;;
      MemFree)      _memfree="$_mv"  ;;
      MemAvailable) _memavail="$_mv" ;;
    esac
  done < /proc/meminfo
  read -r _loadavg _ < /proc/loadavg 2>/dev/null || true
  _uptime_sec="${_up%.*}"

  # Dynamic service list: hardcoded core + any extras from autostart/
  _core="rtsp-h26x onvif recording motion-detection motion-snapshot sound-detection mqtt-bridge network-monitor auto-night-detection memory-guard timelapse ftp-server telnet-server syslog-forward telegram-bot"
  _extra=""
  if [ -d /mnt/config/autostart ]; then
    for _f in /mnt/config/autostart/*; do
      [ -f "$_f" ] || continue
      _n="${_f##*/}"
      case " $_core " in *" $_n "*) ;; *) _extra="$_extra $_n" ;; esac
    done
  fi

  _sep=""; _svc_json=""; _rst_sep=""; _rst_json=""
  for _svc in $_core $_extra; do
    _status="$(probe_service_fast "$_svc")"
    _rfile="/tmp/health_history/${_svc}"
    _restarts=0
    [ -f "$_rfile" ] && read -r _restarts _ < "$_rfile" 2>/dev/null || true
    case "$_restarts" in ''|*[!0-9]*) _restarts=0 ;; esac
    _svc_json="${_svc_json}${_sep}\"${_svc}\":\"${_status}\""
    _rst_json="${_rst_json}${_rst_sep}\"${_svc}\":${_restarts}"
    _sep=","; _rst_sep=","
  done

  _json="$(printf '{"ok":true,"ts":%s,"services":{%s},"service_restarts":{%s},"system":{"mem_total_kb":%s,"mem_free_kb":%s,"mem_avail_kb":%s,"load1":"%s","uptime_sec":%s}}' \
    "$_ts" "$_svc_json" "$_rst_json" "$_memtotal" "$_memfree" "$_memavail" "$_loadavg" "$_uptime_sec")"

  # Atomic write: temp file + mv to prevent health.cgi reading a partial file.
  _tmp="${CACHE_FILE}.$$"
  printf '%s\n%s\n' "$_ts" "$_json" > "$_tmp" 2>/dev/null \
    && mv "$_tmp" "$CACHE_FILE" 2>/dev/null || rm -f "$_tmp" 2>/dev/null
}

# Build once immediately, then loop.
build_snapshot
while :; do
  sleep "$INTERVAL"
  build_snapshot
done
