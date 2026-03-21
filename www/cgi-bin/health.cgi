#!/bin/sh
# health.cgi — Returns JSON snapshot of all service health statuses.
# GET /cgi-bin/health.cgi
# Response: {"ok":true,"ts":<epoch>,"services":{<name>:<status>,...},"system":{...}}
# Cached in /tmp/health_snapshot.cache for up to CACHE_TTL_SECONDS.
# Cache is invalidated by action.cgi when service topology changes.

CACHE_FILE="/tmp/health_snapshot.cache"
CACHE_TTL_SECONDS=10

echo "Content-type: application/json"
echo "Pragma: no-cache"
echo "Cache-Control: no-store, no-cache"
echo ""

# Fork-free epoch
_btime=0
while read -r _k _v _; do [ "$_k" = "btime" ] && _btime="$_v" && break; done < /proc/stat
read -r _up _ < /proc/uptime
_now=$((_btime + ${_up%.*}))

# Serve cache if fresh enough
if [ -f "$CACHE_FILE" ]; then
  _cache_ts=0
  read -r _cache_ts _ < "$CACHE_FILE" 2>/dev/null || true
  case "$_cache_ts" in ''|*[!0-9]*) _cache_ts=0 ;; esac
  _age=$((_now - _cache_ts))
  if [ "$_age" -ge 0 ] && [ "$_age" -lt "$CACHE_TTL_SECONDS" ]; then
    # Strip the leading timestamp line and serve the JSON body
    tail -n +2 "$CACHE_FILE" 2>/dev/null
    exit 0
  fi
fi

# Probe each service via the health subcommand (returns "ok:..." or "warn:...").
# Falls back to status for scripts that predate the health subcommand.
probe_service() {
  _svc="$1"
  _script="/mnt/controlscripts/$_svc"
  if [ ! -x "$_script" ]; then
    echo "absent"
    return
  fi
  _out="$("$_script" health 2>/dev/null)"
  case "$_out" in
    ok:*)   echo "running" ;;
    warn:*) echo "stopped" ;;
    *)
      # Legacy fallback: script lacks health subcommand, use status
      _out="$("$_script" status 2>/dev/null)"
      if [ -n "$_out" ]; then echo "running"; else echo "stopped"; fi
      ;;
  esac
}

# System stats
_memtotal=0; _memfree=0; _memavail=0
while IFS=: read -r _mk _mv _mu; do
  _mv="${_mv# }"; _mv="${_mv%% *}"
  case "$_mk" in
    MemTotal) _memtotal="$_mv" ;;
    MemFree)  _memfree="$_mv"  ;;
    MemAvailable) _memavail="$_mv" ;;
  esac
done < /proc/meminfo

_loadavg=""; read -r _loadavg _ < /proc/loadavg 2>/dev/null || true
_uptime_sec="${_up%.*}"

# Build service list: start with known core services, then add any extras from autostart/.
_core_svcs="rtsp-h26x onvif recording motion-detection motion-snapshot sound-detection mqtt-bridge network-monitor auto-night-detection memory-guard timelapse ftp-server telnet-server syslog-forward telegram-bot"
_extra_svcs=""
if [ -d /mnt/config/autostart ]; then
  for _as_f in /mnt/config/autostart/*; do
    [ -f "$_as_f" ] || continue
    _as_name="${_as_f##*/}"
    case " $_core_svcs " in
      *" $_as_name "*) ;;  # already in core list
      *) _extra_svcs="$_extra_svcs $_as_name" ;;
    esac
  done
fi

# Health history: record each service's status with a rolling counter in /tmp/health_history/
HEALTH_HISTORY_DIR="/tmp/health_history"
[ -d "$HEALTH_HISTORY_DIR" ] || mkdir -p "$HEALTH_HISTORY_DIR" 2>/dev/null || true

record_health_history() {
  _rh_svc="$1"; _rh_status="$2"
  _rh_file="${HEALTH_HISTORY_DIR}/${_rh_svc}"
  _rh_restarts=0; _rh_last_change=0
  [ -f "$_rh_file" ] && read -r _rh_restarts _rh_last_change _ < "$_rh_file" 2>/dev/null || true
  case "$_rh_restarts" in ''|*[!0-9]*) _rh_restarts=0 ;; esac
  case "$_rh_last_change" in ''|*[!0-9]*) _rh_last_change=0 ;; esac
  if [ "$_rh_status" = "stopped" ]; then
    _rh_restarts=$((_rh_restarts + 1))
    printf '%s %s\n' "$_rh_restarts" "$_now" > "$_rh_file" 2>/dev/null || true
  elif [ "$_rh_status" = "running" ] && [ "$_rh_restarts" -gt 0 ]; then
    # Reset hourly counter but keep the timestamp
    if [ "$_now" -gt 0 ] && [ "$_rh_last_change" -gt 0 ] && [ "$((_now - _rh_last_change))" -gt 3600 ]; then
      printf '0 %s\n' "$_now" > "$_rh_file" 2>/dev/null || true
    fi
  fi
  printf '%s' "$_rh_restarts"
}

# Build JSON — keep "services" as flat string map for backward compat;
# add "service_restarts" as a separate object for flap detection.
_sep=""
_svc_json=""
_rst_sep=""
_rst_json=""
for _svc in $_core_svcs $_extra_svcs; do
  _status="$(probe_service "$_svc")"
  _flaps="$(record_health_history "$_svc" "$_status")"
  _svc_json="${_svc_json}${_sep}\"${_svc}\":\"${_status}\""
  _rst_json="${_rst_json}${_rst_sep}\"${_svc}\":${_flaps}"
  _sep=","
  _rst_sep=","
done

_json="$(printf '{"ok":true,"ts":%s,"services":{%s},"service_restarts":{%s},"system":{"mem_total_kb":%s,"mem_free_kb":%s,"mem_avail_kb":%s,"load1":"%s","uptime_sec":%s}}' \
  "$_now" "$_svc_json" "$_rst_json" "$_memtotal" "$_memfree" "$_memavail" "$_loadavg" "$_uptime_sec")"

# Write cache: first line = timestamp, second line = JSON
printf '%s\n%s\n' "$_now" "$_json" > "$CACHE_FILE" 2>/dev/null || true
printf '%s\n' "$_json"
