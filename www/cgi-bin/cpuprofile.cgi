#!/bin/sh
# cpuprofile.cgi?sec=10&threads=1 : read-only diagnostic, where the CPU goes (scripts/cpu-profile.sh)
echo "Content-type: text/plain"; echo "Cache-Control: no-store"; echo ""
sec=10; mode=
case "$QUERY_STRING" in *threads=1*) mode=threads ;; esac
case "$QUERY_STRING" in *sec=[0-9]*) sec=${QUERY_STRING#*sec=}; sec=${sec%%&*}; case "$sec" in ''|*[!0-9]*) sec=10 ;; esac ;; esac
[ "$sec" -lt 3 ] && sec=3; [ "$sec" -gt 30 ] && sec=30
[ -e /tmp/cpuprof.lock ] && { echo "a profile is already running"; exit 0; }
: > /tmp/cpuprof.lock; trap 'rm -f /tmp/cpuprof.lock' EXIT
/bin/sh /mnt/scripts/cpu-profile.sh "$sec" $mode
