#!/bin/sh
# perf-baseline.sh [seconds]: one reference profile of the camera, the same for every build (default 60 s).
# CPU split from /proc/stat (user, system, irq, softirq, idle), interrupts per second per source (/proc/interrupts:
# the USB host of the Wi-Fi, the ISP, the encoder...), Wi-Fi bytes per second, memory, and the last STAT lines of
# tc100_rtsp. Nothing resident, nothing written but stdout. Run it with one RTSP client connected, the same scene.
S=${1:-60}
case "$S" in ''|*[!0-9]*) S=60 ;; esac
IF=${PB_IF:-wlan0}

cpu() { read -r _c u n s i w q sq _r < /proc/stat; echo "$u $n $s $i ${w:-0} ${q:-0} ${sq:-0}"; }
net() {
	while read -r l; do
		case "$l" in "$IF":*) set -- ${l#*:}; echo "$1 $9"; return ;; esac
	done < /proc/net/dev
	echo "0 0"
}
irqs() {	# "name total" per line of /proc/interrupts (all CPUs summed; one CPU here)
	while read -r n c rest; do
		case "$n" in *:) ;; *) continue ;; esac
		case "$c" in ''|*[!0-9]*) continue ;; esac
		set -- $rest; d=${n%:}
		echo "$d $c ${*}"
	done < /proc/interrupts
}

set -- $(cpu); u0=$1 n0=$2 s0=$3 i0=$4 w0=$5 q0=$6 sq0=$7
set -- $(net); rx0=$1 tx0=$2
irqs > /tmp/.pb.irq0
sleep "$S"
set -- $(cpu); u1=$1 n1=$2 s1=$3 i1=$4 w1=$5 q1=$6 sq1=$7
set -- $(net); rx1=$1 tx1=$2
irqs > /tmp/.pb.irq1

tot=$(( (u1-u0) + (n1-n0) + (s1-s0) + (i1-i0) + (w1-w0) + (q1-q0) + (sq1-sq0) ))
[ "$tot" -gt 0 ] || tot=1
pc() { echo "$(( $1 * 1000 / tot / 10 )).$(( $1 * 1000 / tot % 10 ))"; }
echo "== perf-baseline $S s ($(cat /mnt/VERSION 2>/dev/null || echo ?), $(date '+%F %T'))"
echo "cpu %: user $(pc $((u1-u0+n1-n0))) system $(pc $((s1-s0))) irq $(pc $((q1-q0))) softirq $(pc $((sq1-sq0))) iowait $(pc $((w1-w0))) idle $(pc $((i1-i0)))"
echo "$IF: tx $(( (tx1-tx0) / S )) B/s, rx $(( (rx1-rx0) / S )) B/s"
echo "interrupts per second (sources that fired):"
while read -r d c rest; do
	c0=0
	while read -r d0 x _; do [ "$d0" = "$d" ] && { c0=$x; break; }; done < /tmp/.pb.irq0
	r=$(( (c - c0) / S ))
	[ "$r" -gt 0 ] && printf '  %6d/s  %s %s\n' "$r" "$d" "$rest"
done < /tmp/.pb.irq1
rm -f /tmp/.pb.irq0 /tmp/.pb.irq1
while read -r k v _; do
	case "$k" in MemAvailable:|CmaFree:|Slab:) echo "$k $v kB" ;; esac
done < /proc/meminfo
grep STAT /tmp/logs/tc100_rtsp.log 2>/dev/null | tail -n 2
