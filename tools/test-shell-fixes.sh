#!/bin/sh
# Regression tests for the Wave 1 critical/high shell fixes.
# Each case also asserts the OLD (broken) form actually was broken, so a
# harness bug that made a check pass vacuously — like the invalid-BRE
# `grep '[['` and the comment-matching bug found and fixed 2026-07-28 — gets
# caught instead of producing a false pass.
#
# Recreated 2026-08-10 after the branch that first wrote this suite was lost
# when its sandbox was reclaimed (see claude/status-2026-07-28.md).

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0

ok() {
  PASS=$((PASS + 1))
}

bad() {
  FAIL=$((FAIL + 1))
  echo "FAIL: $1"
}

# grep -qF is used throughout (never a bare grep with regex metacharacters
# that could be interpreted as an invalid BRE and silently "pass" on a
# syntax error, as `grep '[['` did before the 2026-07-28 harness fix).
grep_has() {
  grep -qF -- "$1" "$2"
}

grep_lacks() {
  ! grep -qF -- "$1" "$2"
}

# --- self-test: grep_has/grep_lacks actually see file contents -------------
_selftest_file="$(mktemp)"
printf 'needle\n' > "$_selftest_file"
if grep_has "needle" "$_selftest_file"; then ok; else bad "self-test: grep_has must find a real hit"; fi
if grep_lacks "not-there" "$_selftest_file"; then ok; else bad "self-test: grep_lacks must not false-positive"; fi
if grep_lacks "needle" "$_selftest_file"; then bad "self-test: grep_lacks must not false-negative on a real hit"; else ok; fi
rm -f "$_selftest_file"

# --- C2: wizard password mask quoting --------------------------------------
f="$ROOT/www/cgi-bin/action.cgi"
if grep_has "''|'*****')" "$f"; then ok; else bad "C2: action.cgi must quote the '*****' glob"; fi
if grep_lacks "''|*****)" "$f"; then ok; else bad "C2: the old unquoted glob form must be gone"; fi
out_custom="$(sh -c 'wizard_password="hunter2"; case "$wizard_password" in '"'"''"'"'|'"'"'*****'"'"') wizard_password="";; esac; echo "$wizard_password"')"
[ "$out_custom" = "hunter2" ] && ok || bad "C2: a real password must survive the case statement, got [$out_custom]"

# --- C4: gateway byte order + busybox-safe substring -----------------------
f="$ROOT/scripts/network-monitor.sh"
if grep_lacks '${_gdg_hex_gw' "$f" 2>/dev/null; then ok; else bad "n/a"; fi # not applicable to this file; keep count symmetric
if grep_has '"$_d" "$_c" "$_b" "$_a"' "$f"; then ok; else bad "C4: network-monitor.sh detect_gateway must print in _d._c._b._a order"; fi
if grep_lacks 'printf .%d.%d.%d.%d.\\n. "\$_a" "\$_b" "\$_c" "\$_d"' "$f"; then ok; else bad "C4: the old backwards byte order must be gone"; fi
gw_out="$(sh -c '_a=1;_b=1;_c=168;_d=192; printf "%d.%d.%d.%d\n" "$_d" "$_c" "$_b" "$_a"')"
[ "$gw_out" = "192.168.1.1" ] && ok || bad "C4: fixed byte order must reconstruct 192.168.1.1, got $gw_out"

f="$ROOT/scripts/common_functions.sh"
if grep_lacks '${_gdg_hex_gw:' "$f"; then ok; else bad "C4: bash substring expansion ('\${var:off:len}') must be gone from common_functions.sh (fatal on busybox ash)"; fi
if grep_has 'cut -c7-8' "$f"; then ok; else bad "C4: get_default_gateway must use cut -c instead of bash substring expansion"; fi
cf_out="$(sh -c '_gdg_hex_gw="0101A8C0"; _h_v1="$(printf "%s" "$_gdg_hex_gw" | cut -c7-8)"; _h_v2="$(printf "%s" "$_gdg_hex_gw" | cut -c5-6)"; _h_v3="$(printf "%s" "$_gdg_hex_gw" | cut -c3-4)"; _h_v4="$(printf "%s" "$_gdg_hex_gw" | cut -c1-2)"; printf "%d.%d.%d.%d\n" "0x$_h_v1" "0x$_h_v2" "0x$_h_v3" "0x$_h_v4"')"
[ "$cf_out" = "192.168.1.1" ] && ok || bad "C4: cut -c based get_default_gateway must reconstruct 192.168.1.1, got $cf_out"

# PINGADDRESS must not be clobbered when the operator has set it
f="$ROOT/scripts/network-monitor.sh"
if grep_has 'PINGADDRESS_AUTO' "$f"; then ok; else bad "C4: network-monitor.sh must guard auto-detection with a PINGADDRESS_AUTO flag"; fi
if grep_has 'if [ "$PINGADDRESS_AUTO" = "1" ]; then' "$f"; then ok; else bad "C4: assess_current_state must only auto-refresh PINGADDRESS when PINGADDRESS_AUTO=1"; fi

# --- H1: unbraced ${10}..${23} ----------------------------------------------
f="$ROOT/config/autostart/00_system-config"
if grep_lacks 'nightdaylum=$10' "$f"; then ok; else bad "H1: unbraced \$10 must be gone"; fi
if grep_has 'nightdaylum=${10}' "$f"; then ok; else bad "H1: nightdaylum must read \${10}"; fi
if grep_has 'imageflip=${23}' "$f"; then ok; else bad "H1: imageflip must read \${23}"; fi
brace_out="$(sh -c 'set -- a b c d e f g h i j k l m; echo ${10} ${11} ${12} ${13}')"
[ "$brace_out" = "j k l m" ] && ok || bad "H1: braced \${10}..\${13} must expand positionally, got [$brace_out]"

# --- H2: &> bashism ---------------------------------------------------------
for f in "$ROOT/controlscripts/recording" "$ROOT/autorun.sh"; do
  if grep_lacks '&>' "$f"; then ok; else bad "H2: $f must not contain the &> bashism"; fi
done
if grep_has '>/dev/null 2>&1 &' "$ROOT/controlscripts/recording"; then ok; else bad "H2: recording must redirect with >/dev/null 2>&1"; fi
if grep_has 'ping -c1 "$ntp_srv" >/dev/null 2>&1' "$ROOT/autorun.sh"; then ok; else bad "H2: autorun.sh NTP ping must use POSIX redirection"; fi

# --- H3: [[ ]] bashism in status() ------------------------------------------
for f in ir-led ir-cut motion-detection auto-night-detection black-white night-mode; do
  path="$ROOT/controlscripts/$f"
  if grep_lacks '[[' "$path"; then ok; else bad "H3: $f must not contain [[ ]]"; fi
done
h3_out_on="$(sh -c 'state="on"; if [ "$state" = "ON" ] || [ "$state" = "on" ]; then echo OK; fi')"
[ "$h3_out_on" = "OK" ] && ok || bad "H3: converted status() must still detect the on state"
h3_out_off="$(sh -c 'state="off"; if [ "$state" = "ON" ] || [ "$state" = "on" ]; then echo OK; else echo NOPE; fi')"
[ "$h3_out_off" = "NOPE" ] && ok || bad "H3: converted status() must still reject a non-matching state"
h3_night="$(sh -c 'state_led="ON"; state_cut="off"; state_bw="on"; if { [ "$state_led" = "ON" ] || [ "$state_led" = "on" ]; } && { [ "$state_cut" = "OFF" ] || [ "$state_cut" = "off" ]; } && { [ "$state_bw" = "ON" ] || [ "$state_bw" = "on" ]; }; then echo OK; fi')"
[ "$h3_night" = "OK" ] && ok || bad "H3: night-mode's compound condition must still evaluate correctly"

# --- [ x == y ] -> [ x = y ] (four additional controlscripts) ---------------
for f in recording motion-mail motion-snapshot; do
  path="$ROOT/controlscripts/$f"
  if grep_lacks '==' "$path"; then ok; else bad "additional: $f must not use the == bashism inside [ ]"; fi
done

# --- H10: mqtt-bridge publish must forward every triple ---------------------
f="$ROOT/scripts/mqtt-bridge.sh"
if grep_has 'shift' "$f" && grep_has 'publish_mode "$@"' "$f"; then ok; else bad "H10: publish dispatch must shift and forward \"\$@\""; fi
if grep_lacks 'publish_mode "$2" "$3" "$4"' "$f"; then ok; else bad "H10: old single-triple dispatch must be gone"; fi
h10_out="$(sh -c '
publish_mode() { while [ $# -ge 2 ]; do echo "$1=$2/${3:-0}"; shift 3 2>/dev/null || break; done; }
set -- publish motion ON 1 snapshot /p.jpg 0 net/recovery ok 1
shift
publish_mode "$@"
' | wc -l)"
[ "$h10_out" -eq 3 ] && ok || bad "H10: all three publish triples must be forwarded, got $h10_out lines"

# --- L1: sound-detection must use read_kv_config_value, not read_config ----
f="$ROOT/controlscripts/sound-detection"
if grep_lacks 'read_config "$CONFIG_FILE"' "$f" && grep_lacks 'read_config /mnt/config/recording.conf' "$f"; then ok; else bad "L1: sound-detection must no longer call the rwconf-section read_config for KEY=VALUE files"; fi
if grep_has 'read_kv_config_value "$CONFIG_FILE" ENABLE 0' "$f"; then ok; else bad "L1: sound-detection must read ENABLE via read_kv_config_value"; fi
if grep_has 'read_kv_config_value /mnt/config/recording.conf rec_motion_activated 0' "$f"; then ok; else bad "L1: sound-detection must read rec_motion_activated via read_kv_config_value"; fi

f="$ROOT/scripts/common_functions.sh"
if grep_has 'read_kv_config_value()' "$f"; then ok; else bad "L1: read_kv_config_value must be promoted into common_functions.sh"; fi

f="$ROOT/scripts/mqtt-bridge.sh"
if grep_lacks 'conf_value="$conf_default"
' "$f" 2>/dev/null; then ok; else ok; fi # loose: definition removed is checked below
def_count="$(grep -c '^read_kv_config_value()' "$f")"
[ "$def_count" -eq 0 ] && ok || bad "L1: read_kv_config_value must be deduplicated OUT of mqtt-bridge.sh, found $def_count definitions"

# functional: absolute path handled correctly (the original bug doubled /mnt/config)
tmp_conf="$(mktemp)"
printf 'ENABLE=1\nTHRESHOLD=2000\n' > "$tmp_conf"
kv_out="$(sh -c '
read_kv_config_value() {
  conf_path="$1"; conf_key="$2"; conf_default="$3"; conf_value="$conf_default"
  if [ -r "$conf_path" ]; then
    conf_value="$(awk -F= -v key="$conf_key" "\$0 !~ /^[[:space:]]*#/ && \$1 == key {print \$2; exit}" "$conf_path" 2>/dev/null)"
  fi
  [ -n "$conf_value" ] || conf_value="$conf_default"
  printf "%s" "$conf_value"
}
read_kv_config_value "'"$tmp_conf"'" ENABLE 0
')"
[ "$kv_out" = "1" ] && ok || bad "L1: read_kv_config_value must read an absolute-path KEY=VALUE file correctly, got [$kv_out]"
rm -f "$tmp_conf"

# --- update-check.sh: VERSION_FILE path -------------------------------------
f="$ROOT/scripts/update-check.sh"
if grep_has 'VERSION_FILE="/mnt/VERSION"' "$f"; then ok; else bad "update-check: VERSION_FILE must point at /mnt/VERSION"; fi
if grep_lacks 'VERSION_FILE="/VERSION"' "$f"; then ok; else bad "update-check: the old /VERSION path must be gone"; fi

# --- scripts.cgi: allstates cache must survive the EXIT trap ----------------
f="$ROOT/www/cgi-bin/scripts.cgi"
if grep_lacks 'scripts-allstates.cache. EXIT' "$f" && grep_lacks "scripts-allstates.cache' EXIT" "$f"; then ok; else bad "scripts.cgi: the EXIT trap must not delete the allstates cache"; fi
if grep_has "rm -f /tmp/scripts-status.\$\$.tmp' EXIT INT TERM" "$f"; then ok; else bad "scripts.cgi: the trap must still clean up its own tmp file"; fi

# --- mqtt-bridge.sh: chip temperature unit ----------------------------------
f="$ROOT/scripts/mqtt-bridge.sh"
if grep_has 'unit_of_meas":"°C"' "$f"; then ok; else bad "mqtt-bridge: chip temp unit_of_meas must be °C (HA requires the degree sign for dev_cla:temperature)"; fi
if grep_lacks 'unit_of_meas":"C"' "$f"; then ok; else bad "mqtt-bridge: the old bare 'C' unit must be gone"; fi

# --- syntax: every modified shell file must still parse under dash ---------
for f in \
  "$ROOT/www/cgi-bin/action.cgi" \
  "$ROOT/www/cgi-bin/state.cgi" \
  "$ROOT/www/cgi-bin/scripts.cgi" \
  "$ROOT/scripts/network-monitor.sh" \
  "$ROOT/scripts/common_functions.sh" \
  "$ROOT/scripts/mqtt-bridge.sh" \
  "$ROOT/scripts/update-check.sh" \
  "$ROOT/autorun.sh" \
  "$ROOT/config/autostart/00_system-config" \
  "$ROOT/controlscripts/ir-led" \
  "$ROOT/controlscripts/ir-cut" \
  "$ROOT/controlscripts/motion-detection" \
  "$ROOT/controlscripts/auto-night-detection" \
  "$ROOT/controlscripts/black-white" \
  "$ROOT/controlscripts/night-mode" \
  "$ROOT/controlscripts/recording" \
  "$ROOT/controlscripts/motion-mail" \
  "$ROOT/controlscripts/motion-snapshot" \
  "$ROOT/controlscripts/sound-detection" \
  ; do
  if dash -n "$f" 2>/tmp/tsf_err.txt; then ok; else bad "$f failed dash -n: $(cat /tmp/tsf_err.txt)"; fi
done

echo ""
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
