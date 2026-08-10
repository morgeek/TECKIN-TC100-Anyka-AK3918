#!/bin/sh
# Regression tests for the Wave 2 hardening fixes. Functional where possible
# (source the real code and assert behavior), structural otherwise.
# Run under dash: sh tools/test-wave2-fixes.sh

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); }
bad() { FAIL=$((FAIL+1)); echo "FAIL: $1"; }
grep_has() { grep -qF -- "$1" "$2"; }
grep_lacks() { ! grep -qF -- "$1" "$2"; }

# ---- self-test ----
_st="$(mktemp)"; printf 'x\n' > "$_st"
grep_has "x" "$_st" && ok || bad "self-test grep_has"
grep_lacks "y" "$_st" && ok || bad "self-test grep_lacks"
rm -f "$_st"

# ---- func.cgi: the lockout escape bug (formerly inserted literal backslashes) ----
# func.cgi's parser uses ${var//x/y}, a bash/busybox-ash-with-ASH_BASH_COMPAT
# feature that dash lacks — so the functional round-trip is exercised under bash
# (a faithful proxy for the device's busybox ash) when available. The structural
# grep checks below run regardless.
FUNC="$ROOT/www/cgi-bin/func.cgi"
if command -v bash >/dev/null 2>&1; then
  out="$(REQUEST_METHOD=GET QUERY_STRING='password=MyP%40ss%282026%29%3B%7C%26%3C%3E' bash -c ". $FUNC >/dev/null 2>&1; printf '%s' \"\$F_password\"")"
  [ "$out" = 'MyP@ss(2026);|&<>' ] && ok || bad "func.cgi lockout: password round-trip should be literal, got [$out]"
  case "$out" in *\\*) bad "func.cgi lockout: value must not contain a backslash [$out]" ;; *) ok ;; esac
  # The eval must still be safe: a backtick / $() substitution must NOT execute.
  out2="$(REQUEST_METHOD=GET QUERY_STRING='x=%60id%60_%24%28id%29' bash -c ". $FUNC >/dev/null 2>&1; printf '%s' \"\$F_x\"")"
  case "$out2" in *uid=*) bad "func.cgi: command substitution executed! [$out2]" ;; *) ok ;; esac
else
  echo "NOTE: bash not available — skipping func.cgi functional round-trip (structural checks still run)"
fi
grep_lacks 'esc_value="${esc_value//;/' "$FUNC" && ok || bad "func.cgi: the bogus ';' surgical escape must be gone"
grep_lacks 'esc_value="${esc_value//(/' "$FUNC" && ok || bad "func.cgi: the bogus '(' surgical escape must be gone"

# ---- C1: body-only JSON helpers exist and emit no header block ----
grep_has 'json_body_ok()' "$FUNC" && ok || bad "C1: json_body_ok helper must exist"
grep_has 'json_body_err()' "$FUNC" && ok || bad "C1: json_body_err helper must exist"
ACT="$ROOT/www/cgi-bin/action.cgi"
[ "$(grep -c 'json_response "success"' "$ACT")" -eq 0 ] && ok || bad "C1: no json_response \"success\" call should remain in action.cgi"
[ "$(grep -c 'json_body_ok ' "$ACT")" -gt 25 ] && ok || bad "C1: json_body_ok calls should be present in action.cgi"
# Body helpers must NOT emit HTTP headers.
ho="$(REQUEST_METHOD=GET QUERY_STRING='' dash -c ". $FUNC >/dev/null 2>&1; json_body_ok 'hi'")"
case "$ho" in *Status:*|*Content-type*) bad "C1: json_body_ok leaked HTTP headers into body" ;; *) ok ;; esac

# ---- C3: conf_recording values validated via sanitizers ----
grep_has 'motion_act="$(normalize_bool' "$ACT" && ok || bad "C3: motion_act must go through normalize_bool"
grep_has 'postrec="$(sanitize_int_range' "$ACT" && ok || bad "C3: postrec must go through sanitize_int_range"
grep_lacks 'postrec=$(printf' "$ACT" && ok || bad "C3: raw printf assignment of postrec must be gone"
# Functional: an injection payload must be reduced to a safe integer/fallback.
inj="$(dash -c '
sanitize_int_range() { v="$1";mn="$2";mx="$3";fb="$4"; case "$v" in ""|*[!0-9]*) v="$fb";; esac; [ "$v" -lt "$mn" ] && v="$mn"; [ "$v" -gt "$mx" ] && v="$mx"; echo "$v"; }
sanitize_int_range "5
EVIL=\`id\`" 0 3600 8')"
[ "$inj" = "8" ] && ok || bad "C3: injection payload must collapse to the fallback, got [$inj]"

# ---- H9: action.cgi calls csrf_guard; state.cgi bootstraps the token ----
grep_has 'csrf_guard' "$ACT" && ok || bad "H9: action.cgi must call csrf_guard"
grep_has '/tmp/csrf_token' "$ROOT/www/cgi-bin/state.cgi" && ok || bad "H9: state.cgi must handle the csrf token"
grep_has 'if [ ! -s /tmp/csrf_token ]' "$ROOT/www/cgi-bin/state.cgi" && ok || bad "H9: state.cgi must generate the token when missing"

# ---- load_preset path traversal (state.cgi) ----
ST="$ROOT/www/cgi-bin/state.cgi"
grep_has '*[!A-Za-z0-9_-]*' "$ST" && ok || bad "load_preset: must validate preset name with a char-class case"
# Functional: the validation idiom must reject a traversal name and accept a good one.
rej="$(dash -c 'n="../../../tmp/x"; case "$n" in ""|*[!A-Za-z0-9_-]*) echo REJECT;; *) echo OK;; esac')"
[ "$rej" = "REJECT" ] && ok || bad "load_preset: traversal name must be rejected, got [$rej]"
acc="$(dash -c 'n="my_preset-1"; case "$n" in ""|*[!A-Za-z0-9_-]*) echo REJECT;; *) echo OK;; esac')"
[ "$acc" = "OK" ] && ok || bad "load_preset: valid name must be accepted, got [$acc]"

# ---- preset name validation switched off grep -qE (busybox-safe) ----
grep_lacks "grep -qE '^[a-zA-Z0-9_-]" "$ACT" && ok || bad "preset: grep -qE must be replaced by a case idiom"
[ "$(grep -c '_preset_name_bad' "$ACT")" -ge 2 ] && ok || bad "preset: both save/delete must use the case idiom"

# ---- basename -s removed from state.cgi (busybox has no -s) ----
grep_lacks 'basename -s .json' "$ST" && ok || bad "state.cgi: basename -s must be gone"

# ---- mqtt-bridge: HA switch names via case, not GNU sed \\u ----
MQ="$ROOT/scripts/mqtt-bridge.sh"
grep_lacks 's/\\b./\\u&/g' "$MQ" && ok || bad "mqtt-bridge: GNU sed \\u title-casing must be gone"
grep_has 'name_suffix="IR LED"' "$MQ" && ok || bad "mqtt-bridge: fixed friendly names must be used"
grep_has 'unit_of_meas":"°C"' "$MQ" && ok || bad "mqtt-bridge: chip temp unit must be °C"
# log rotation present now
grep_has 'tail -n 100 "$LOGPATH"' "$MQ" && ok || bad "mqtt-bridge: log_msg must rotate the log"

# ---- storage-cleanup: LOGMAX after boot.conf, spin fixed ----
SC="$ROOT/scripts/storage-cleanup.sh"
grep_has 'oldest entry' "$SC" && ok || bad "storage-cleanup: recent-oldest branch must break (not spin)"
# LOGMAX assignment must appear AFTER the boot.conf source line
_bc_line="$(grep -n '\. "\$CONFIGPATH/boot.conf"' "$SC" | head -1 | cut -d: -f1)"
_lm_line="$(grep -n 'LOGMAX="\${STORAGE_CLEANUP_LOG_MAX_BYTES' "$SC" | head -1 | cut -d: -f1)"
[ -n "$_bc_line" ] && [ -n "$_lm_line" ] && [ "$_lm_line" -gt "$_bc_line" ] && ok || bad "storage-cleanup: LOGMAX must be assigned after boot.conf is sourced ($_lm_line vs $_bc_line)"

# ---- config-validator: WEB_MODE=off accepted ----
grep_has 'full http ultra-lite off' "$ROOT/scripts/config-validator.sh" && ok || bad "config-validator: WEB_MODE must allow 'off'"

# ---- syntax: all touched shell files parse under dash ----
for f in "$ROOT/www/cgi-bin/action.cgi" "$ROOT/www/cgi-bin/func.cgi" "$ROOT/www/cgi-bin/state.cgi" \
         "$ROOT/scripts/mqtt-bridge.sh" "$ROOT/scripts/storage-cleanup.sh" "$ROOT/scripts/config-validator.sh"; do
  dash -n "$f" 2>/tmp/w2_err.txt && ok || bad "$f dash -n: $(cat /tmp/w2_err.txt)"
done

echo ""
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
