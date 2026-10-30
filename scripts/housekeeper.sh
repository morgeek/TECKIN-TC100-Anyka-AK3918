#!/bin/sh
# housekeeper.sh: ONE resident loop for the slow periodic jobs (a busybox ash costs 150-300 KB resident and a wake-up
# of its own, each).
#
# Built-in jobs (the checks of scripts/web-guard.sh, sourced here; its "run" loop is the HOUSEKEEPER=0 way):
#   web      every 60 s: a web port listens (else restart httpfront once, then the rescue telnet; closes it again)
#   net      every 60 s: net-guard.sh once, every 3rd minute while the gateway answers, every minute after a failure
#   sd       every 60 s: sdinfo-sd.sh when the card changed, every 10th minute otherwise
# Jobs the control scripts and boot script register (they live in /tmp/housekeeper/jobs, so they vanish at reboot):
#   health-snapshot     scripts/health-snapshot.sh once      every HEALTH_SNAPSHOT_INTERVAL_SECONDS (300)
#   log-persist         scripts/log-persist.sh hk            first after 120 s, then LOG_PERSIST_MIN minutes (10)
#   watch-<service>     scripts/service-watchdog.sh --tick   every CHECK_TIMEOUT_SECONDS (60): rtsp-h26x, mqtt-bridge...
# Kept out on purpose: button-watch.sh (reset/reboot path), auto-night-daemon.sh (2-8 s), the MQTT bridge, telegram-bot,
# getty, and v3/linux66-sd/cfg-persist (the only writer of the flash settings: left exactly as it is).
#
# The tick: the loop sleeps in `read -t N` on a FIFO (no fork; sleep when the shell cannot) until the next job is due,
# at most HK_MAXWAIT (30) s. Writing to the FIFO wakes it at once (job add/del). A job is never run twice at the same
# time and never holds the others up:
#   fn   a shell function of this process (cheap, never waits: the checks of web-guard)
#   bg   a command run in a background process, one at a time per name; a run still going when the job is due again
#        is skipped (a hung SD card stalls df/ls, ping takes seconds)
#   wd   a service watchdog: the pid file check of onvif/mqtt-bridge/rtsp-h26x is done here without a fork; anything
#        else, and every failure, runs `service-watchdog.sh --tick` as a bg job (counters in /tmp/watchdog-state)
# The Services page, health-probe.sh and the control scripts read pid files: a job with a pid file gets the housekeeper's
# own pid in it while the job is registered, removed when it is not, so "pid alive" stays true exactly while the job runs.
#
#   housekeeper.sh start | stop | run | active | status
#   housekeeper.sh job add NAME KIND PERIOD FIRST PIDFILE|- COMMAND...   (kind fn|bg|wd; wd: "SERVICE_SCRIPT NEED MODE [VAR=N...]")
#   housekeeper.sh job del NAME | job list | job has NAME
#   housekeeper.sh watch-add SERVICE PIDFILE [TIMEOUT] [NEED_REBOOT] [MODE]   (CHECK_TIMEOUT_SECONDS and WATCHDOG_* of the
#                                                                           environment go with it) | watch-del SERVICE
# Exit status of job add / watch-add: 1 when the housekeeper is not running (callers then start their own daemon).
# HOUSEKEEPER=0 in /mnt/config/boot.conf: the boot script does not start this and everything runs as separate daemons.

HK_DIR=${HK_DIR:-/tmp/housekeeper}
HK_JOBS=$HK_DIR/jobs
HK_FIFO=$HK_DIR/wake
HK_PIDFILE=${HK_PIDFILE:-/var/run/housekeeper.pid}
HK_CLOCK=${HK_CLOCK:-/proc/uptime}
HK_MAXWAIT=${HK_MAXWAIT:-30}
HK_SCRIPTS=${HK_SCRIPTS:-/mnt/scripts}
HK_WDSTATE=${HK_WDSTATE:-/tmp/watchdog-state}
HK_RUNDIR=${HK_RUNDIR:-/var/run}
HK_WAITMODE=${HK_WAITMODE:-}

# seconds of the clock (uptime) -> hk_t
hk_now() { _hk_up=; read -r _hk_up _ < "$HK_CLOCK" 2>/dev/null; hk_t=${_hk_up%.*}; case "$hk_t" in ''|*[!0-9]*) hk_t=0 ;; esac; }
# a job name as a variable name suffix -> _hk_v
hk_var() { _hk_v=$1; while :; do case $_hk_v in *-*) _hk_v=${_hk_v%%-*}_${_hk_v#*-} ;; *) break ;; esac; done; }
hk_pid() { _hk_p=; [ -r "$HK_PIDFILE" ] && read -r _hk_p _ < "$HK_PIDFILE" 2>/dev/null; case "$_hk_p" in ''|*[!0-9]*) _hk_p= ;; esac; }
hk_active() { hk_pid; [ -n "$_hk_p" ] && kill -0 "$_hk_p" 2>/dev/null; }
# a process that is running (a zombie child is reaped and counts as gone)
hk_alive()
{
    [ -n "$1" ] && [ -r "/proc/$1/stat" ] || return 1
    read -r _hk_al < "/proc/$1/stat" 2>/dev/null || return 1
    _hk_al=${_hk_al##*) }
    [ "${_hk_al%% *}" != Z ] && return 0
    wait "$1" 2>/dev/null
    return 1
}
hk_wake() { [ -p "$HK_FIFO" ] && echo w 1<>"$HK_FIFO" 2>/dev/null; return 0; }

# hk_write_spec NAME KIND PERIOD FIRST PIDFILE CMD (atomic; the nonce makes the loop treat it as a new job)
hk_write_spec()
{
    _hk_n=$1; _hk_kd=$2; _hk_pe=$3; _hk_fi=$4; _hk_pf=$5; shift 5
    mkdir -p "$HK_JOBS" "$HK_DIR/run" "$HK_DIR/state" "$HK_DIR/period" 2>/dev/null
    _hk_nonce=; read -r _hk_nonce _ < "$HK_CLOCK" 2>/dev/null
    echo "$$.${_hk_nonce:-0}.${HK_SEQ:=0} $_hk_kd $_hk_pe $_hk_fi $_hk_pf $*" > "$HK_JOBS/.$_hk_n.tmp" 2>/dev/null &&
        mv -f "$HK_JOBS/.$_hk_n.tmp" "$HK_JOBS/$_hk_n"
    HK_SEQ=$((HK_SEQ + 1))
    rm -f "$HK_DIR/period/$_hk_n"
    hk_pid
    [ "$_hk_pf" != - ] && [ -n "$_hk_p" ] && echo "$_hk_p" > "$_hk_pf" 2>/dev/null
    return 0
}

hk_valid_name() { case "$1" in ''|*[!A-Za-z0-9_-]*|-*|.*) return 1 ;; esac; return 0; }
hk_num() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; return 0; }

hk_job_add()
{
    hk_valid_name "$1" || { echo "bad job name" >&2; return 2; }
    case "$2" in fn|bg|wd) ;; *) echo "bad kind" >&2; return 2 ;; esac
    hk_num "$3" && [ "$3" -ge 1 ] || { echo "bad period" >&2; return 2; }
    hk_num "$4" || { echo "bad first delay" >&2; return 2; }
    [ -n "$5" ] && [ -n "$6" ] || { echo "usage: job add NAME KIND PERIOD FIRST PIDFILE|- COMMAND..." >&2; return 2; }
    hk_active || return 1
    hk_write_spec "$@"
    hk_wake
}

# job del: unregister, stop the run that is going (not the one that calls this: HK_JOB), drop the pid file
hk_job_del()
{
    hk_valid_name "$1" || return 2
    [ -f "$HK_JOBS/$1" ] || return 1
    _hk_x=; _hk_pf=-; read -r _hk_x _hk_x _hk_x _hk_x _hk_pf _hk_x < "$HK_JOBS/$1" 2>/dev/null
    rm -f "$HK_JOBS/$1" "$HK_DIR/period/$1" "$HK_DIR/state/$1"
    _hk_rp=; [ -r "$HK_DIR/run/$1" ] && read -r _hk_rp < "$HK_DIR/run/$1"
    rm -f "$HK_DIR/run/$1"
    if [ "$HK_JOB" != "$1" ] && hk_alive "$_hk_rp"; then kill "$_hk_rp" 2>/dev/null; fi
    [ -n "$_hk_pf" ] && [ "$_hk_pf" != - ] && rm -f "$_hk_pf"
    hk_wake
    return 0
}

# a service watchdog for the control scripts: watch-add SERVICE PIDFILE [TIMEOUT] [NEED_REBOOT] [MODE]
hk_watch_add()
{
    _hk_s=${1##*/}; _hk_pf=$2; _hk_to=${3:-${CHECK_TIMEOUT_SECONDS:-60}}; _hk_nr=${4:-0}; _hk_md=${5:-status}
    hk_valid_name "$_hk_s" && [ -n "$_hk_pf" ] || return 2
    case "$_hk_to" in ''|*[!0-9]*) _hk_to=60 ;; esac
    [ "$_hk_to" -lt 5 ] && _hk_to=5
    case "$_hk_nr" in 0|1) ;; *) _hk_nr=0 ;; esac
    _hk_env=
    for _hk_k in WATCHDOG_LOG_MAX_BYTES WATCHDOG_LOG_BACKUPS WATCHDOG_NO_REBOOT_BASE_DELAY_SECONDS \
                 WATCHDOG_NO_REBOOT_BACKOFF_STEP_SECONDS WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS; do
        eval "_hk_val=\${$_hk_k:-}"
        case "$_hk_val" in ''|*[!0-9]*) ;; *) _hk_env="$_hk_env $_hk_k=$_hk_val" ;; esac
    done
    hk_job_add "watch-$_hk_s" wd "$_hk_to" "$_hk_to" "$_hk_pf" "/mnt/controlscripts/$_hk_s $_hk_nr $_hk_md$_hk_env"
}

# ---------------------------------------------------------------- the loop

# run a command in a background process, one at a time per NAME (hk_bg NAME CMD ARGS..., a function or a program);
# 0 = started, 1 = the previous run is still going
hk_bg()
{
    _hk_bn=$1; shift; hk_var "$_hk_bn"; _hk_bv=$_hk_v
    eval "_hk_bp=\$HKP_$_hk_bv"
    if hk_alive "$_hk_bp"; then
        eval "HKSK_$_hk_bv=\$((\${HKSK_$_hk_bv:-0} + 1))"
        return 1
    fi
    ( HK_JOB=$_hk_bn; export HK_JOB; "$@" ) </dev/null >/dev/null 2>&1 &
    eval "HKP_$_hk_bv=$!"
    echo "$!" > "$HK_DIR/run/$_hk_bn" 2>/dev/null
    return 0
}
# the same for a program: it becomes the process (so job del can stop it); hk_bgx NAME PROGRAM ARGS...
hk_bgx()
{
    _hk_bn=$1; shift; hk_var "$_hk_bn"; _hk_bv=$_hk_v
    eval "_hk_bp=\$HKP_$_hk_bv"
    if hk_alive "$_hk_bp"; then
        eval "HKSK_$_hk_bv=\$((\${HKSK_$_hk_bv:-0} + 1))"
        return 1
    fi
    ( HK_JOB=$_hk_bn; export HK_JOB; exec "$@" ) </dev/null >/dev/null 2>&1 &
    eval "HKP_$_hk_bv=$!"
    echo "$!" > "$HK_DIR/run/$_hk_bn" 2>/dev/null
    return 0
}

# wd job, "SERVICE NEED MODE [VAR=N...]": success of a pid file service without a fork, anything else through a tick
hk_wd()
{
    _hk_wn=$1; shift
    set -f; set -- $*; set +f
    _hk_svc=$1; _hk_nd=$2; _hk_md=$3
    if [ "$_hk_md" = status ]; then
        _hk_wpf=
        case "${_hk_svc##*/}" in    # the same pid files as service_is_healthy() in service-watchdog.sh
            onvif)       _hk_wpf=$HK_RUNDIR/onvif.pid ;;
            mqtt-bridge) _hk_wpf=$HK_RUNDIR/mqtt-bridge.pid ;;
            rtsp-h26x)   _hk_wpf=$HK_RUNDIR/v4l2rtspserver.pid ;;
        esac
        if [ -n "$_hk_wpf" ]; then
            _hk_wpid=; [ -r "$_hk_wpf" ] && read -r _hk_wpid _ < "$_hk_wpf" 2>/dev/null
            case "$_hk_wpid" in ''|*[!0-9]*) ;; *)
                if kill -0 "$_hk_wpid" 2>/dev/null; then
                    # same counters as the success branch of wd_step() in service-watchdog.sh
                    _hk_sf="$HK_WDSTATE/${_hk_svc##*/}"
                    _hk_e=0; _hk_s=0; _hk_d=-; _hk_l=0
                    [ -r "$_hk_sf" ] && read -r _hk_e _hk_s _hk_d _hk_l < "$_hk_sf" 2>/dev/null
                    case "$_hk_e$_hk_s$_hk_l" in ''|*[!0-9]*) _hk_e=0; _hk_s=0; _hk_l=0 ;; esac
                    _hk_s=$((_hk_s + 1))
                    [ "$_hk_s" -gt 10 ] && _hk_d=-
                    [ "$_hk_s" -gt 30 ] && { _hk_s=0; _hk_e=0; }
                    [ -d "$HK_WDSTATE" ] || mkdir -p "$HK_WDSTATE" 2>/dev/null
                    echo "$_hk_e $_hk_s $_hk_d $_hk_l" > "$_hk_sf" 2>/dev/null
                    return 0
                fi ;;
            esac
        fi
    fi
    shift 3
    hk_bgx "$_hk_wn" env HK_JOB="$_hk_wn" HK_WDSTATE="$HK_WDSTATE" CHECK_TIMEOUT_SECONDS="${_hk_wto:-60}" "$@" \
        sh "$HK_SCRIPTS/service-watchdog.sh" --tick "$_hk_svc" "$_hk_nd" "$_hk_md"
}

# one pass over the jobs: run those that are due; sets _hk_next to the time of the next one
hk_tick()
{
    hk_now
    _hk_next=$((hk_t + HK_MAXWAIT))
    for _hk_f in "$HK_JOBS"/*; do
        [ -f "$_hk_f" ] || continue
        _hk_name=${_hk_f##*/}
        _hk_nonce=; _hk_kind=; _hk_period=60; _hk_first=0; _hk_cmd=
        read -r _hk_nonce _hk_kind _hk_period _hk_first _hk_pf _hk_cmd < "$_hk_f" 2>/dev/null || continue
        hk_num "$_hk_period" && [ "$_hk_period" -ge 1 ] || _hk_period=60
        hk_num "$_hk_first" || _hk_first=0
        hk_var "$_hk_name"; _hk_k=$_hk_v
        eval "_hk_seen=\$HKS_$_hk_k"
        if [ "$_hk_nonce" != "$_hk_seen" ]; then
            eval "HKS_$_hk_k=\$_hk_nonce; HKD_$_hk_k=$((hk_t + _hk_first))"
        fi
        eval "_hk_due=\$HKD_$_hk_k"
        if [ "$hk_t" -ge "$_hk_due" ]; then
            case "$_hk_kind" in
                fn) eval "$_hk_cmd" ;;
                bg) set -f; set -- $_hk_cmd; set +f; hk_bgx "$_hk_name" "$@" ;;
                wd) _hk_wto=$_hk_period; hk_wd "$_hk_name" "$_hk_cmd" ;;
            esac
            # a job may set its next period itself (log-persist: LOG_PERSIST_MIN is read at every cycle)
            if [ -r "$HK_DIR/period/$_hk_name" ]; then
                _hk_ov=; read -r _hk_ov _ < "$HK_DIR/period/$_hk_name" 2>/dev/null
                hk_num "$_hk_ov" && [ "$_hk_ov" -ge 1 ] && _hk_period=$_hk_ov
            fi
            eval "HKD_$_hk_k=$((hk_t + _hk_period)); HKN_$_hk_k=\$((\${HKN_$_hk_k:-0} + 1))"
            eval "echo \"last=$hk_t next=$((hk_t + _hk_period)) runs=\$HKN_$_hk_k skipped=\${HKSK_$_hk_k:-0}\" > \"$HK_DIR/state/$_hk_name\" 2>/dev/null"
            eval "_hk_due=\$HKD_$_hk_k"
        fi
        [ "$_hk_due" -lt "$_hk_next" ] && _hk_next=$_hk_due
    done
    return 0
}

hk_wait() { if [ "$HK_WAITMODE" = fifo ]; then read -t "$1" _hk_x <> "$HK_FIFO" 2>/dev/null; else sleep "$1"; fi; }

hk_core_jobs()
{
    [ -r "$HK_SCRIPTS/web-guard.sh" ] || return 0
    . "$HK_SCRIPTS/web-guard.sh"
    hk_write_spec web fn "${WG_INTERVAL:-60}" "${WG_FIRST:-60}" - wg_hk_web
    hk_write_spec net fn "${WG_INTERVAL:-60}" "${WG_FIRST:-60}" - wg_hk_net
    hk_write_spec sd fn "${WG_INTERVAL:-60}" "${WG_FIRST:-60}" - wg_hk_sd
}

hk_run()
{
    mkdir -p "$HK_JOBS" "$HK_DIR/run" "$HK_DIR/state" "$HK_DIR/period" 2>/dev/null
    echo $$ > "$HK_PIDFILE" 2>/dev/null
    echo -300 > /proc/$$/oom_score_adj 2>/dev/null   # a daemon this small is not the one to kill
    trap 'rm -f "$HK_PIDFILE" "$HK_FIFO"; exit 0' TERM INT
    hk_core_jobs
    # the pid files of jobs registered before this (re)start
    for _hk_f in "$HK_JOBS"/*; do
        [ -f "$_hk_f" ] || continue
        _hk_pf=-; read -r _hk_x _hk_x _hk_x _hk_x _hk_pf _hk_x < "$_hk_f" 2>/dev/null
        [ "$_hk_pf" != - ] && [ -n "$_hk_pf" ] && echo $$ > "$_hk_pf" 2>/dev/null
    done
    rm -f "$HK_FIFO"
    if ! mkfifo "$HK_FIFO" 2>/dev/null; then
        HK_WAITMODE=sleep
    elif [ -z "$HK_WAITMODE" ]; then
        # does read -t really wait on this shell? (the first wait must last; else sleep)
        HK_WAITMODE=sleep
        hk_now; _hk_t0=$hk_t
        read -t 2 _hk_x <> "$HK_FIFO" 2>/dev/null
        hk_now
        [ $((hk_t - _hk_t0)) -ge 1 ] && HK_WAITMODE=fifo
    fi
    _hk_lt=-1; _hk_same=0
    while :; do
        hk_tick
        _hk_nap=$((_hk_next - hk_t))
        [ "$_hk_nap" -lt 1 ] && _hk_nap=1
        [ "$HK_WAITMODE" = sleep ] && [ "$_hk_nap" -gt 10 ] && _hk_nap=10   # no wake-up by FIFO: look at new jobs sooner
        hk_wait "$_hk_nap"
        # a read that returns at once, again and again, must not become a busy loop: fall back to sleep
        if [ "$HK_WAITMODE" = fifo ]; then
            hk_now
            if [ "$hk_t" = "$_hk_lt" ]; then _hk_same=$((_hk_same + 1)); else _hk_same=0; _hk_lt=$hk_t; fi
            [ "$_hk_same" -ge 30 ] && HK_WAITMODE=sleep
        fi
    done
}

hk_start()
{
    hk_active && return 0
    mkdir -p "$HK_JOBS" "$HK_DIR/run" "$HK_DIR/state" "$HK_DIR/period" 2>/dev/null
    ( exec sh "$0" run ) </dev/null >/dev/null 2>&1 &
    echo $! > "$HK_PIDFILE"      # at once: the next job add must find it (the loop writes the same number)
    return 0
}

hk_stop()
{
    hk_active || { rm -f "$HK_PIDFILE"; return 0; }
    kill "$_hk_p" 2>/dev/null
    _hk_i=0
    while [ "$_hk_i" -lt 5 ] && hk_alive "$_hk_p"; do sleep 1; _hk_i=$((_hk_i + 1)); done
    kill -9 "$_hk_p" 2>/dev/null
    rm -f "$HK_PIDFILE" "$HK_FIFO"
    return 0
}

hk_status()
{
    hk_active || return 1
    echo "PID: $_hk_p"
    for _hk_f in "$HK_JOBS"/*; do
        [ -f "$_hk_f" ] || continue
        _hk_name=${_hk_f##*/}
        _hk_x=; _hk_kind=; _hk_period=; read -r _hk_x _hk_kind _hk_period _hk_x < "$_hk_f" 2>/dev/null
        _hk_st=; [ -r "$HK_DIR/state/$_hk_name" ] && read -r _hk_st < "$HK_DIR/state/$_hk_name"
        _hk_rp=; [ -r "$HK_DIR/run/$_hk_name" ] && read -r _hk_rp < "$HK_DIR/run/$_hk_name"
        _hk_run=; hk_alive "$_hk_rp" && _hk_run=" running=$_hk_rp"
        echo "$_hk_name kind=$_hk_kind period=$_hk_period $_hk_st$_hk_run"
    done
    return 0
}

if [ -z "$HK_TEST_SOURCE" ]; then
    case "$1" in
        start) hk_start ;;
        stop) hk_stop ;;
        run) hk_run ;;
        active) hk_active ;;
        status) hk_status ;;
        job)
            case "$2" in
                add) shift 2; hk_job_add "$@" ;;
                del) hk_job_del "$3" ;;
                has) [ -f "$HK_JOBS/$3" ] ;;
                list) for _hk_f in "$HK_JOBS"/*; do [ -f "$_hk_f" ] && echo "${_hk_f##*/}"; done; exit 0 ;;
                *) echo "usage: $0 job add|del|has|list ..." >&2; exit 2 ;;
            esac ;;
        watch-add) shift; hk_active || exit 1; hk_watch_add "$@" ;;
        watch-del) hk_job_del "watch-${2##*/}" ;;
        *) echo "usage: $0 start | stop | run | active | status | job add|del|has|list | watch-add | watch-del" >&2; exit 2 ;;
    esac
fi
