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
#   - motion-detection, motion-snapshot, auto-night-detection
#                         composite state (config flag, ISP register)
#   - any service missing from the map, so future additions degrade to the
#     slow-but-correct path instead of misreporting
#
# Keep the map in sync with the PIDFILE= lines in controlscripts/*.

probe_service_fast() {
  _pf_svc="$1"
  _pf_script="/mnt/controlscripts/$_pf_svc"
  [ -x "$_pf_script" ] || { echo "absent"; return; }

  _pf_file=""
  case "$_pf_svc" in
    recording)       _pf_file="/var/run/recording.pid" ;;
    sound-detection) _pf_file="/var/run/sound-detection.pid" ;;
    mqtt-bridge)     _pf_file="/var/run/mqtt-bridge.pid" ;;
    network-monitor) _pf_file="/var/run/network-monitor.pid" ;;
    memory-guard)    _pf_file="/var/run/memory-guard.pid" ;;
    timelapse)       _pf_file="/var/run/timelapse.pid" ;;
    ftp-server)      _pf_file="/var/run/ftp-server.pid" ;;
    telnet-server)   _pf_file="/var/run/telnet-server.pid" ;;
    syslog-forward)  _pf_file="/var/run/syslog-forward.pid" ;;
    telegram-bot)    _pf_file="/var/run/telegram-bot.pid" ;;
    cpu-scaler)      _pf_file="/var/run/cpu-scaler.pid" ;;
    health-snapshot) _pf_file="/var/run/health-snapshot.pid" ;;
  esac

  if [ -n "$_pf_file" ]; then
    _pf_pid=""
    [ -f "$_pf_file" ] && read -r _pf_pid _ < "$_pf_file" 2>/dev/null
    case "$_pf_pid" in
      ''|*[!0-9]*) echo "stopped" ;;
      *) if kill -0 "$_pf_pid" 2>/dev/null; then echo "running"; else echo "stopped"; fi ;;
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
      ''|*[!0-9]*) echo "stopped"; return ;;
      *) kill -0 "$_pf_gpid" 2>/dev/null || { echo "stopped"; return ; } ;;
    esac
  fi

  _pf_out="$("$_pf_script" health 2>/dev/null)"
  case "$_pf_out" in
    ok:*)   echo "running" ;;
    warn:*) echo "stopped" ;;
    *)
      _pf_out="$("$_pf_script" status 2>/dev/null)"
      if [ -n "$_pf_out" ]; then echo "running"; else echo "stopped"; fi
      ;;
  esac
}
