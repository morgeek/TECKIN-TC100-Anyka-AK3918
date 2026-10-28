#!/bin/sh
# cpu-profile.sh [seconds] [threads]
# Per-process (and with "threads" per-thread) CPU use over a window, from /proc/<pid>/stat deltas.
# Pure shell (busybox), no ps/top: the profiler must not be the load it measures. Output sorted, top 15.
SEC=${1:-10}; MODE=$2
snap() {  # prints "<id> <name> <ticks> [<tid>]" per task
  for d in /proc/[0-9]*; do
    p=${d#/proc/}
    if [ "$MODE" = threads ]; then set -- $d/task/*; else set -- $d; fi
    for t in "$@"; do
      [ -r $t/stat ] || continue
      read -r line < $t/stat 2>/dev/null || continue
      id=${t##*/}; rest=${line#*) }; name=${line#*(}; name=${name%)*}
      set -- $rest              # state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt utime stime
      echo "$p/$id $name $(( ${12} + ${13} ))"
      set -- $d
    done
  done
}
read -r _ u n s i w q sq _ < /proc/stat; T0=$((u+n+s+i+w+q+sq)); I0=$((i+w))
snap > /tmp/cpuprof.0
sleep "$SEC"
read -r _ u n s i w q sq _ < /proc/stat; T1=$((u+n+s+i+w+q+sq)); I1=$((i+w))
snap > /tmp/cpuprof.1
DT=$((T1-T0)); [ "$DT" -gt 0 ] || DT=1
echo "window ${SEC}s, busy $(( (DT-(I1-I0))*100/DT )) % of one core"
awk -v dt="$DT" 'NR==FNR{a[$1]=$3; next} {d=$3-a[$1]; if(d>0) printf "%5.1f %% %s (%s)\n", d*100/dt, $2, $1}' /tmp/cpuprof.0 /tmp/cpuprof.1 | sort -rn | head -n 15
rm -f /tmp/cpuprof.0 /tmp/cpuprof.1
