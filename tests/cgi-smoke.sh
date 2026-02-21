#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
CGI_DIR="$ROOT_DIR/www/cgi-bin"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

require_contains() {
  haystack="$1"
  needle="$2"
  label="$3"
  printf '%s' "$haystack" | rg -q --fixed-strings "$needle" || fail "$label (missing: $needle)"
}

run_cgi_get() {
  script_name="$1"
  query_string="$2"
  (
    cd "$CGI_DIR"
    REQUEST_METHOD="GET" QUERY_STRING="$query_string" sh "./$script_name"
  )
}

echo "[1/5] Syntax checks"
for path in \
  "$ROOT_DIR/scripts/service-watchdog.sh" \
  "$ROOT_DIR/controlscripts/onvif" \
  "$CGI_DIR/func.cgi" \
  "$CGI_DIR/state.cgi" \
  "$CGI_DIR/configbackup.cgi"
do
  sh -n "$path" || fail "sh -n failed for $path"
done

echo "[2/5] state.cgi unsupported command path"
out="$(run_cgi_get state.cgi 'cmd=doesnotexist' 2>/dev/null)"
require_contains "$out" "Unsupported command" "state.cgi unsupported command response"

echo "[3/5] state.cgi perfprofile and statusline/healthsnapshot"
perf_out="$(run_cgi_get state.cgi 'cmd=perfprofile' 2>/dev/null)"
case "$perf_out" in
  *balanced*|*low-cpu*|*rtsp-only*) ;;
  *) fail "state.cgi perfprofile response not recognized" ;;
esac
statusline_out="$(run_cgi_get state.cgi 'cmd=statusline' 2>/dev/null)"
require_contains "$statusline_out" "\"chip_temp_text\"" "statusline missing chip_temp_text"
require_contains "$statusline_out" "\"chip_temp_c\"" "statusline missing chip_temp_c"
health_out="$(run_cgi_get state.cgi 'cmd=healthsnapshot' 2>/dev/null)"
require_contains "$health_out" "\"rtsp\"" "healthsnapshot missing rtsp key"
require_contains "$health_out" "\"onvif\"" "healthsnapshot missing onvif key"
require_contains "$health_out" "\"uptime_seconds\"" "healthsnapshot missing uptime"
require_contains "$health_out" "\"chip_temp_text\"" "healthsnapshot missing chip_temp_text"

echo "[4/5] configbackup.cgi usage response"
usage_out="$(run_cgi_get configbackup.cgi '' 2>/dev/null)"
require_contains "$usage_out" "cmd=download" "configbackup usage output"

echo "[5/5] configbackup.cgi restore validation"
invalid_restore_out="$(run_cgi_get configbackup.cgi 'cmd=restore&archive_path=../../bad.tar.gz' 2>/dev/null)"
require_contains "$invalid_restore_out" "Invalid archive path" "configbackup invalid path validation"

echo "All CGI smoke tests passed."
