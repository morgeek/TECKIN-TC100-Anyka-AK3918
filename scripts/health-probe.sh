#!/bin/sh
# health-probe.sh — shared service prober for health.cgi and health-snapshot.sh.
#
# Probing every service by exec'ing its controlscript costs a shell spawn plus
# a 21 KB common_functions.sh source per service — ~10 s of CPU per sweep on
# the AK3918, and the snapshot daemon pays that sweep every 30 s. Most
# controlscripts' status() boils down to "pidfile alive?", which this prober
# replicates fork-free: read and kill -0 are ash builtins.
#
# The controlscript is still exec'd for:
#   - rtsp-h26x, onvif    deep health (RTSP DESCRIBE / GOP stall, ONVIF probe)
#   - motion-detection, auto-night-detection
#                         composite state (config flag, ISP register)
#   - any service missing from the map, so future additions degrade to the
#     slow-but-correct path instead of misreporting
#
# Keep the map in sync with the PIDFILE= lines in controlscripts/*.
#
# A service that is not running because it is switched off is "disabled", not "stopped": "stopped" counts as a
# restart in health.cgi's history and as a problem in the pages. Switched off = its settings key is off
# (scripts/service-switch.sh, one switch per service), or, for the services without a key, no config/autostart entry.
[ -r "${HP_SWITCH_SH:-/mnt/scripts/service-switch.sh}" ] && . "${HP_SWITCH_SH:-/mnt/scripts/service-switch.sh}"
_pf_wanted() {
  if command -v svc_switch >/dev/null 2>&1 && svc_switch "$1"; then svc_on "$1"; return; fi
  case "$1" in
    rtsp-h26x|health-snapshot) return 0 ;;                   # always started at boot
    auto-night-detection)                                    # daynight=3 (manual day / night) is its off switch
      _pf_dn=""; [ -r "${HP_CONF_DIR:-/mnt/config}/rtspserver.conf" ] && while IFS='=' read -r _pf_k _pf_v; do
        [ "$_pf_k" = daynight ] && { _pf_dn=$_pf_v; break; }; done < "${HP_CONF_DIR:-/mnt/config}/rtspserver.conf"
      [ "$_pf_dn" != 3 ]; return ;;
  esac
  [ -e "${HP_CONF_DIR:-/mnt/config}/autostart/$1" ]
}
_pf_down() {
  if _pf_wanted "$_pf_svc"; then echo "stopped"; else echo "disabled"; fi
}

probe_service_fast() {
  _pf_svc="$1"
  _pf_script="/mnt/controlscripts/$_pf_svc"
  [ -x "$_pf_script" ] || { echo "absent"; return; }

  _pf_file=""
  case "$_pf_svc" in
    sound-detection) _pf_file="/var/run/sound-detection.pid" ;;
    mqtt-bridge)     _pf_file="/var/run/mqtt-bridge.pid" ;;
    memory-guard)    _pf_file="/var/run/memory-guard.pid" ;;
    ftp-server)      _pf_file="/var/run/ftp-server.pid" ;;
    telnet-server)   _pf_file="/var/run/telnet-server.pid" ;;
    syslog-forward)  _pf_file="/var/run/syslog-forward.pid" ;;
    telegram-bot)    _pf_file="/var/run/telegram-bot.pid" ;;
    health-snapshot) _pf_file="/var/run/health-snapshot.pid" ;;
    button-actions)  _pf_file="/var/run/button-watch.pid" ;;
    wifi-rescue)     _pf_file="/var/run/wifi-rescue.pid" ;;
    mdns)            _pf_file="/var/run/mdns.pid" ;;
    whep)            _pf_file="/var/run/whep.pid" ;;
    auto-night-detection)
      [ -f /var/run/auto-night-detection.pid ] && _pf_file="/var/run/auto-night-detection.pid" ;;
    motion-detection)
      # no /tmp/tc100_md = motion detection off (the default): that is what "setconf -g p" and the controlscript report
      # as stopped, so do not exec the controlscript (shell + common_functions.sh) to be told so
      [ -e /tmp/tc100_md ] || { _pf_down; return; }
      _pf_file="/var/run/detection-monitor.pid" ;;
  esac

  if [ -n "$_pf_file" ]; then
    _pf_pid=""
    [ -f "$_pf_file" ] && read -r _pf_pid _ < "$_pf_file" 2>/dev/null
    case "$_pf_pid" in
      ''|*[!0-9]*) _pf_down ;;
      *) if kill -0 "$_pf_pid" 2>/dev/null; then echo "running"; else _pf_down; fi ;;
    esac
    return
  fi

  # Deep or composite services: exec the controlscript, same contract as the
  # historical probe (health -> ok:/warn:, else status output non-empty).
  #
  # Cheap gate first: rtsp-h26x and onvif carry a pidfile AND an expensive probe
  # (an RTSP DESCRIBE costs ~1.2 s here). If the process is plainly dead there is
  # nothing to interrogate, so skip straight to "stopped" instead of paying for a
  # network round-trip that can only confirm it. A live process still gets the
  # full deep check, so a hung-but-running daemon is still caught.
  case "$_pf_svc" in
    rtsp-h26x) _pf_gate="/var/run/v4l2rtspserver.pid" ;;
    onvif)     _pf_gate="/var/run/onvif.pid" ;;
    *)         _pf_gate="" ;;
  esac
  if [ -n "$_pf_gate" ]; then
    _pf_gpid=""
    [ -f "$_pf_gate" ] && read -r _pf_gpid _ < "$_pf_gate" 2>/dev/null
    case "$_pf_gpid" in
      ''|*[!0-9]*) _pf_down; return ;;
      *) kill -0 "$_pf_gpid" 2>/dev/null || { _pf_down; return ; } ;;
    esac
  fi

  # The RTSP DESCRIBE of rtsp-h26x takes ~1.2 s of the single-threaded server: while the last deep check said "running",
  # only every HP_DEEP_EVERY-th probe (default 6: every 30 min at the snapshot interval of 5 min) repeats it, the others
  # answer from the pid check above. After a failure it is repeated at every probe. State: "<probes since> <verdict>".
  _pf_df="${HP_DEEP_FILE:-/tmp/health_rtsp_deep}"
  if [ "$_pf_svc" = rtsp-h26x ]; then
    _pf_dn=0; _pf_dv=""
    [ -r "$_pf_df" ] && read -r _pf_dn _pf_dv < "$_pf_df" 2>/dev/null
    case "$_pf_dn" in ''|*[!0-9]*) _pf_dn=0 ;; esac
    if [ "$_pf_dv" = running ] && [ "$_pf_dn" -lt "${HP_DEEP_EVERY:-6}" ]; then
      echo "$((_pf_dn + 1)) running" > "$_pf_df" 2>/dev/null
      echo "running"; return
    fi
  fi

  _pf_out="$("$_pf_script" health 2>/dev/null)"
  _pf_rc=$?
  case "$_pf_svc" in
    rtsp-h26x|onvif)
      if [ "$_pf_rc" -ne 0 ]; then
        [ "$_pf_svc" = rtsp-h26x ] && echo "0 unhealthy" > "$_pf_df" 2>/dev/null
        echo "unhealthy"; return
      fi ;;
  esac
  [ "$_pf_svc" = rtsp-h26x ] && echo "1 running" > "$_pf_df" 2>/dev/null
  case "$_pf_out" in
    ok:*)   echo "running" ;;
    warn:*) _pf_down ;;
    *)
      _pf_out="$("$_pf_script" status 2>/dev/null)"
      if [ -n "$_pf_out" ]; then echo "running"; else _pf_down; fi
      ;;
  esac
}
