#!/bin/sh
# isp-stat-dump.sh [ADDR] [WORDS] [OUT]   read the ISP statistics DMA area (test queue R12-09), read only
#   ADDR   physical address from dmesg "ak39_isp2: statistics DMA area at 0x...", found there when not given
#   WORDS  32-bit words to read (default 1200 = the 4800-byte area)
#   OUT    file for "index value" lines (default /tmp/isp-stat-<seconds>.txt)
# Two dumps taken with different light (lamp on / off, hand over the lens) and compared with
#   awk 'NR==FNR{a[$1]=$2;next} a[$1]!=$2' dump1 dump2
# show which words the ISP really updates: the white balance counts are the block that moves with the colour of the
# light. Only reads memory (devmem without a value); nothing is written.
A=${1:-$(dmesg 2>/dev/null | sed -n 's/.*statistics DMA area at \(0x[0-9a-f]*\).*/\1/p' | tail -n 1)}
N=${2:-1200}
OUT=${3:-/tmp/isp-stat-$(date +%s).txt}
case "$A" in 0x[0-9a-fA-F]*) ;; *) echo "isp-stat-dump: no address (dmesg line missing: kernel older than rc13?)" >&2; exit 1 ;; esac
case "$N" in ''|*[!0-9]*) N=1200 ;; esac
[ "$N" -le 1200 ] || N=1200
: > "$OUT" || exit 1
i=0
while [ "$i" -lt "$N" ]; do
	printf '%d %s\n' "$i" "$(devmem $((A + i * 4)) 32)" >> "$OUT"
	i=$((i + 1))
done
echo "$OUT"
