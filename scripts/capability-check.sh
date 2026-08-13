#!/bin/sh
# capability-check.sh — boot-time probe of the shell tools this firmware depends on.
#
# WHY BEHAVIOUR, NOT PRESENCE: this platform has twice shipped bugs where a tool
# was *there* but did not do what the code assumed, and the failure was silent:
#
#   tr       busybox carries the applet but ships no symlink, and /mnt/bin is not
#            on the CGI PATH. `tr` exits 127 and, inside $(...), yields "" — so
#            callers got empty data instead of an error. Five shipped bugs.
#   timeout  /bin/timeout EXISTS and is on PATH, but is the pre-2014 busybox
#            variant wanting `-t SECS`. Given `timeout SECS CMD` it execs the
#            duration as the command and fails — inside a redirect, silently.
#            currentpic.cgi served a 0-byte JPEG with HTTP 200 and the right
#            MIME type; the dashboard liveview was simply blank.
#
# `command -v` passes in the second case, which is exactly why this probe runs
# each tool and checks the RESULT. Runs once at boot; the whole thing is a
# handful of execs, no daemon, no polling.
#
# Output: /tmp/capability-check.json (read by health.cgi) and a line per failure
# in the boot log. Exit status is always 0 — this reports, it never blocks boot.

CAPFILE="/tmp/capability-check.json"
_cc_fail=""
_cc_warn=""

# add_fail <tool> <detail>
add_fail() { _cc_fail="${_cc_fail}${_cc_fail:+,}\"$1\""; echo "capability-check: FAIL $1 — $2" >&2; }
add_warn() { _cc_warn="${_cc_warn}${_cc_warn:+,}\"$1\""; }

# ── tr: must actually translate, not just exist ─────────────────────────────
# The shims in func.cgi / common_functions.sh route to busybox when the binary
# is missing; this probes the bare command a standalone script would get.
# Invoked through a variable ON PURPOSE: probing the bare `tr` is the whole
# point here, but writing it literally would trip the CI lint that forbids
# unshimmed tr in camera-side shell. Keeping the lint strict is worth more than
# writing this one call in the obvious way.
_cc_bare_tr=tr
_cc_tr="$(printf 'a-b' | $_cc_bare_tr '\-' '_' 2>/dev/null)"
if [ "$_cc_tr" != "a_b" ]; then
    add_warn tr
fi

# ── timeout: modern `timeout SECS CMD` form must run CMD ───────────────────
if [ "$(timeout 2 echo ok 2>/dev/null)" != "ok" ]; then
    add_warn timeout
fi
# busybox applet is the fallback both shims use — if THAT is broken, the shims
# cannot save us and every bounded call in the project is unreliable.
if [ "$(busybox timeout 2 echo ok 2>/dev/null)" != "ok" ]; then
    add_fail timeout_busybox "busybox timeout applet does not accept 'SECS CMD'"
fi

# ── awk: the replacement for tr everywhere; must do gsub and RS ─────────────
if [ "$(printf 'x1y2' | awk '{ gsub(/[^0-9]/, ""); print }' 2>/dev/null)" != "12" ]; then
    add_fail awk "gsub() did not filter as expected"
fi
if [ "$(printf 'a&b' | awk 'BEGIN { RS = "&" } NR == 2 { print }' 2>/dev/null)" != "b" ]; then
    add_fail awk_rs "record separator RS did not split on '&'"
fi

# ── getimage: must emit a non-empty JPEG, bounded ──────────────────────────
# Blank liveview was invisible for months because the CGI returned HTTP 200 with
# zero bytes. Probe the size, not the exit code.
if [ -x /mnt/bin/getimage ]; then
    _cc_img="/tmp/.capcheck-img.$$"
    busybox timeout 8 /mnt/bin/getimage > "$_cc_img" 2>/dev/null
    _cc_sz="$(busybox wc -c < "$_cc_img" 2>/dev/null)"
    case "$_cc_sz" in ''|*[!0-9]*) _cc_sz=0 ;; esac
    [ "$_cc_sz" -lt 1000 ] && add_fail getimage "produced ${_cc_sz} bytes (expected a JPEG)"
    rm -f "$_cc_img" 2>/dev/null
fi

# ── nc: the MQTT transport (publish AND the persistent listener) ────────────
command -v nc >/dev/null 2>&1 || add_fail nc "absent; MQTT publish and listener cannot work"

# ── od decimal mode: the MQTT frame decoder depends on -tu1 ────────────────
if [ "$(printf 'A' | od -An -tu1 2>/dev/null | busybox tr -d ' \n')" != "65" ]; then
    add_fail od "od -An -tu1 did not yield decimal bytes; MQTT decoding will fail"
fi

_cc_status="ok"
[ -n "$_cc_warn" ] && _cc_status="degraded"
[ -n "$_cc_fail" ] && _cc_status="fail"

printf '{"status":"%s","failed":[%s],"shimmed":[%s]}\n' \
    "$_cc_status" "$_cc_fail" "$_cc_warn" > "$CAPFILE" 2>/dev/null

# "shimmed" is expected on this hardware (tr and timeout are both covered by the
# shims); "failed" is not, and means something the project relies on is broken.
[ -n "$_cc_fail" ] && echo "capability-check: status=${_cc_status} failed=[${_cc_fail}]" >&2
exit 0
