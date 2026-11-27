#!/bin/sh
# libFuzzer harnesses for the network parsers of the camera's daemons (stream [up-fuzz], docs/linux-port/upgrade-3.2/fuzz.md).
# Host only (x86, clang -fsanitize=fuzzer,address,undefined), never part of the camera image.
#   sh tests/fuzz/run.sh [-t SECONDS] [-j JOBS] [-o OUTDIR] [-b] [-k] [TARGET...]
#     -t   seconds each target runs (default 60)           -j  targets built and run at once (default 4)
#     -o   work directory (default tests/fuzz/out)         -b  build only (the smoke test of the harnesses)
#     -k   keep OUTDIR/<target>/corpus of an earlier run (the inputs it found) next to the seeds
#   TARGET: one of the names below; none = all. A crash input is left in OUTDIR/<target>/crash-*, the exit status is 1.
# The seed corpus of tests/fuzz/corpus/<target>/ is copied to OUTDIR/<target>/corpus first, so that the repository's seeds are
# never changed by a run; what a run finds stays in OUTDIR. A crash input is minimised by hand (docs/linux-port/upgrade-3.2/fuzz.md).
set -u
cd "$(dirname "$0")/../.."
SECS=60; JOBS=4; OUT=tests/fuzz/out; BUILD_ONLY=0; KEEP=0
while getopts t:j:o:bk o; do
	case $o in t) SECS=$OPTARG ;; j) JOBS=$OPTARG ;; o) OUT=$OPTARG ;; b) BUILD_ONLY=1 ;; k) KEEP=1 ;; *) exit 2 ;; esac
done
shift $((OPTIND - 1))
CC=${CC:-clang}
SAN="-fsanitize=fuzzer,address,undefined -fno-sanitize-recover=undefined -fno-sanitize=alignment"
CF="-g -O1 -fno-stack-protector -fno-omit-frame-pointer -Wall -Wno-unused-function -Wno-unused-variable -Wno-unused-but-set-variable -Wno-unused-parameter -Wno-format-truncation -Wno-pointer-sign -Wno-macro-redefined"
RT=src/tc100rtsp
RTSRC="$RT/rec.c $RT/mp4box.c $RT/aacenc.c $RT/livemp4.c $RT/talk.c $RT/alisten.c $RT/acap.c $RT/adsp.c $RT/aec.c $RT/apb.c"
RTF="-DTC100_HOST_TEST -I$RT/../jpegenc -I$RT/../h265enc -std=gnu11 -U_FORTIFY_SOURCE"

# name | sources | flags | dictionary
TARGETS="mdns|tests/fuzz/fuzz_mdns.c||
whep_stun|tests/fuzz/fuzz_whep.c|-DMODE_STUN|
whep_sdp|tests/fuzz/fuzz_whep.c|-DMODE_SDP|whep_sdp
whep_hello|tests/fuzz/fuzz_whep.c|-DMODE_HELLO|
whep_misc|tests/fuzz/fuzz_whep.c|-DMODE_MISC|
mqttd|tests/fuzz/fuzz_mqttd.c||mqttd
rtsp_req|tests/fuzz/fuzz_rtsp.c $RTSRC|-DMODE_REQ $RTF -ldl -lpthread -lm|rtsp
rtsp_auth|tests/fuzz/fuzz_rtsp.c $RTSRC|-DMODE_AUTH $RTF -ldl -lpthread -lm|rtsp
rtsp_talk|tests/fuzz/fuzz_rtsp.c $RTSRC|-DMODE_TALK $RTF -ldl -lpthread -lm|
onvif_soap|tests/fuzz/fuzz_onvif.c|-DMODE_SOAP|onvif
onvif_http|tests/fuzz/fuzz_onvif.c|-DMODE_HTTP|onvif
onvif_wsd|tests/fuzz/fuzz_onvif.c|-DMODE_WSD|onvif
httpfront|tests/fuzz/fuzz_httpfront.c||http"

want() { [ $# -eq 0 ] && return 0; for w in $WANT; do [ "$w" = "$1" ] && return 0; done; return 1; }
WANT="$*"
mkdir -p "$OUT/bin"
build_one() {
	t=$1
	line=$(echo "$TARGETS" | grep "^$t|")
	src=$(echo "$line" | cut -d'|' -f2); flags=$(echo "$line" | cut -d'|' -f3)
	# shellcheck disable=SC2086
	if eval "$CC $SAN $CF $flags -Itests/fuzz $src -o $OUT/bin/$t" >"$OUT/bin/$t.log" 2>&1; then
		echo "built   $t"
	else
		echo "BUILD FAILED $t"; tail -30 "$OUT/bin/$t.log"; return 1
	fi
}
list=""; fail=0; running=0; pids=""
for t in $(echo "$TARGETS" | cut -d'|' -f1); do
	[ -z "$WANT" ] || want "$t" || continue
	list="$list $t"
	build_one "$t" &
	pids="$pids $!"; running=$((running + 1))
	if [ "$running" -ge "$JOBS" ]; then for p in $pids; do wait "$p" || fail=1; done; pids=""; running=0; fi
done
for p in $pids; do wait "$p" || fail=1; done
[ "$fail" = 0 ] || exit 1
[ "$BUILD_ONLY" = 1 ] && exit 0

run_one() {
	t=$1
	line=$(echo "$TARGETS" | grep "^$t|"); dict=$(echo "$line" | cut -d'|' -f4)
	d=$OUT/$t
	if [ "$KEEP" = 1 ]; then rm -f "$d"/crash-* "$d"/timeout-* "$d"/oom-* "$d"/leak-*; else rm -rf "$d"; fi
	mkdir -p "$d/corpus"
	[ -d "tests/fuzz/corpus/$t" ] && cp tests/fuzz/corpus/"$t"/* "$d/corpus/" 2>/dev/null
	D=""; [ -n "$dict" ] && D="-dict=tests/fuzz/$dict.dict"
	# -rss_limit_mb: the daemons keep a few MB of statics; -timeout: a hang is a finding (the daemons have a 2 to 5 s read timeout)
	"$OUT/bin/$t" -seed="${FUZZ_SEED:-1}" -max_total_time="$SECS" -timeout=10 -rss_limit_mb=2048 -max_len=16384 -print_final_stats=1 $D \
		-artifact_prefix="$d/" "$d/corpus" >"$d/log" 2>&1
	rc=$?
	if [ $rc -ne 0 ] || ls "$d"/crash-* "$d"/timeout-* "$d"/oom-* "$d"/leak-* >/dev/null 2>&1; then
		echo "CRASH   $t (exit $rc): $(ls "$d" | grep -E '^(crash|timeout|oom|leak)-' | tr '\n' ' ')"
		tail -25 "$d/log"
		return 1
	fi
	echo "ok      $t: $(grep -E 'stat::number_of_executed_units' "$d/log" | awk '{print $2}') runs, $(grep -E '^#[0-9]+.*(DONE|Done)' "$d/log" | tail -1 | grep -oE 'cov: [0-9]+ ft: [0-9]+ corp: [0-9]+' | tail -1)"
	return 0
}

echo "== fuzz: ${SECS}s per target, $JOBS at once"
rc=0; running=0; pids=""
for t in $list; do
	run_one "$t" &
	pids="$pids $!"
	running=$((running + 1))
	if [ "$running" -ge "$JOBS" ]; then	# a batch: wait for all of it
		for p in $pids; do wait "$p" || rc=1; done
		pids=""; running=0
	fi
done
for p in $pids; do wait "$p" || rc=1; done
[ $rc = 0 ] && echo "== fuzz: ok" || echo "== fuzz: CRASH (inputs in $OUT/*/)"
exit $rc
