#!/bin/sh
# supervisor.sh: shared by controlscripts/auto-night-detection and controlscripts/button-actions.
#
# SUPERVISOR_IMPL=c in config/boot.conf (default sh) runs the day/night loop and the reset button loop as two jobs of
# ONE small C process, tc100-supervisord (src/supervisord), instead of two resident busybox shells
# (scripts/auto-night-daemon.sh and scripts/button-watch.sh, which stay as they are: the default and the fallback).
# A job is switched on by a flag file ($SV_RUN/tc100-sv.night, tc100-sv.button); the daemon runs while one exists and
# exits when none is left. Both control scripts keep their own pid file: with the C daemon it holds the daemon's pid.
#
# Fallback to the shell loops (sv_start returns 1, the control script then starts its shell loop as before):
#   - SUPERVISOR_IMPL is not c, or the binary is missing or not executable;
#   - the daemon is gone while a job flag still exists (it died): the marker $SV_RUN/tc100-supervisord.failed keeps the
#     shell loops in use until the next boot; the restarter (a housekeeper watch of the service, see below) runs the
#     control script's "start", which finds the dead daemon, sets the marker and starts the shell loop;
#   - the daemon did not come up within a few seconds, or the button job refused (no GPIO): this job only.
# Without the housekeeper (HOUSEKEEPER=0) nothing restarts a dead daemon, as nothing restarted a dead shell loop before.

SV_BIN="${SV_BIN:-/mnt/tc100test/tc100-supervisord}"
SV_RUN="${SV_RUN:-/var/run}"
SV_BOOTCONF="${SV_BOOTCONF:-/mnt/config/boot.conf}"
SV_HK="${SV_HK:-/mnt/scripts/housekeeper.sh}"

# 0 when boot.conf asks for the C daemon (the last SUPERVISOR_IMPL line counts, quotes allowed)
sv_conf_c()
{
  [ -r "$SV_BOOTCONF" ] || return 1
  _sv_v=
  while IFS='=' read -r _sv_k _sv_x; do [ "$_sv_k" = SUPERVISOR_IMPL ] && _sv_v=$_sv_x; done < "$SV_BOOTCONF"
  case "$_sv_v" in c|'c'|"c") return 0 ;; esac
  return 1
}

# pid of the live daemon
sv_daemon_pid()
{
  _sv_p=
  [ -r "$SV_RUN/tc100-supervisord.pid" ] && read -r _sv_p _ < "$SV_RUN/tc100-supervisord.pid" 2>/dev/null
  case "$_sv_p" in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$_sv_p" 2>/dev/null || return 1
  # a zombie (killed, not reaped yet) is not a daemon: state field of /proc/PID/stat
  if [ -r "/proc/$_sv_p/stat" ]; then read -r _sv_a _sv_b _sv_s _ < "/proc/$_sv_p/stat" 2>/dev/null; [ "$_sv_s" != Z ] || return 1; fi
  echo "$_sv_p"
}

# 0 when JOB (night|button) is served by the C daemon right now (flag and live daemon)
sv_job_active()
{
  [ -e "$SV_RUN/tc100-sv.$1" ] && [ -n "$(sv_daemon_pid)" ]
}

# sv_start JOB PIDFILE SERVICE: 0 = the C daemon serves JOB (PIDFILE has its pid), 1 = the caller starts its shell loop
sv_start()
{
  [ -x "$SV_BIN" ] && [ ! -e "$SV_RUN/tc100-supervisord.failed" ] && sv_conf_c || return 1
  _sv_job=$1; _sv_pf=$2; _sv_svc=$3
  _sv_alive="$(sv_daemon_pid)"
  if [ -z "$_sv_alive" ] && { [ -e "$SV_RUN/tc100-sv.night" ] || [ -e "$SV_RUN/tc100-sv.button" ]; }; then
    # a flag without a daemon: it died. The shell loops take over until the next boot.
    : > "$SV_RUN/tc100-supervisord.failed"
    rm -f "$SV_RUN/tc100-sv.night" "$SV_RUN/tc100-sv.button" "$SV_RUN/tc100-supervisord.pid"
    logger -t tc100-v3 "tc100-supervisord died: shell loops for the rest of this boot" 2>/dev/null
    return 1
  fi
  : > "$SV_RUN/tc100-sv.$_sv_job" || return 1
  if [ -z "$_sv_alive" ]; then
    rm -f "$SV_RUN/tc100-supervisord.pid"
    ( exec "$SV_BIN" ) </dev/null >/dev/null 2>&1 &
    _sv_n=0
    while [ "$_sv_n" -lt 30 ] && [ -z "$(sv_daemon_pid)" ]; do sleep 0.1 2>/dev/null || sleep 1; _sv_n=$((_sv_n + 1)); done
    _sv_alive="$(sv_daemon_pid)"
    if [ -z "$_sv_alive" ]; then
      rm -f "$SV_RUN/tc100-sv.$_sv_job"
      : > "$SV_RUN/tc100-supervisord.failed"
      return 1
    fi
  fi
  sleep 1   # the daemon looks at its flags every second: a refused button job (no GPIO) removes its flag
  if [ ! -e "$SV_RUN/tc100-sv.$_sv_job" ]; then
    return 1
  fi
  _sv_alive="$(sv_daemon_pid)"
  if [ -z "$_sv_alive" ]; then
    rm -f "$SV_RUN/tc100-sv.night" "$SV_RUN/tc100-sv.button"
    : > "$SV_RUN/tc100-supervisord.failed"
    return 1
  fi
  echo "$_sv_alive" > "$_sv_pf"
  # the restarter: the housekeeper checks the pid file of the service every minute without a fork (no-op without it)
  [ -n "$_sv_svc" ] && [ -f "$SV_HK" ] && sh "$SV_HK" watch-add "$_sv_svc" "$SV_RUN/$_sv_svc-watch.pid" </dev/null >/dev/null 2>&1
  return 0
}

# sv_stop JOB PIDFILE SERVICE: switch JOB off; the daemon leaves when no job is left
sv_stop()
{
  rm -f "$SV_RUN/tc100-sv.$1" "$2"
  [ -n "$3" ] && [ -f "$SV_HK" ] && sh "$SV_HK" watch-del "$3" </dev/null >/dev/null 2>&1
  if [ ! -e "$SV_RUN/tc100-sv.night" ] && [ ! -e "$SV_RUN/tc100-sv.button" ]; then
    _sv_p="$(sv_daemon_pid)" && kill "$_sv_p" 2>/dev/null
  fi
  return 0
}
