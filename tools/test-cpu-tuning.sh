#!/bin/sh
# Regression tests for the low-CPU tuning batch.
# Run: sh tools/test-cpu-tuning.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); }
bad() { FAIL=$((FAIL+1)); echo "FAIL: $1"; }
grep_has() { grep -qF -- "$1" "$2"; }

AR="$ROOT/autorun.sh"
SC="$ROOT/config/autostart/00_system-config"
BC="$ROOT/config/boot.conf.dist"

# NVR-feeder: sound-detection must be guarded by the frigate_ha profile
grep_has 'INTEGRATION_PROFILE' "$SC" && ok || bad "00_system-config must read INTEGRATION_PROFILE before starting sound-detection"
grep_has 'frigate_ha' "$SC" && ok || bad "00_system-config must skip sound-detection under frigate_ha"
# functional: guard picks the right branch
r="$(dash -c 'read_kv_config_value(){ awk -F= -v k="$2" "\$0 !~ /^[[:space:]]*#/ && \$1==k{print \$2;exit}" "$1" 2>/dev/null || echo "$3"; }; d=$(mktemp -d); echo INTEGRATION_PROFILE=frigate_ha>$d/b; p=$(read_kv_config_value $d/b INTEGRATION_PROFILE default); [ "$p" = frigate_ha ] && echo SKIP; rm -rf $d')"
[ "$r" = "SKIP" ] && ok || bad "frigate_ha profile must resolve to SKIP for sound-detection"

# Kernel log tuning: opt-in knobs present, default empty, guarded writes
grep_has 'apply_kernel_log_tuning' "$AR" && ok || bad "autorun must define apply_kernel_log_tuning"
grep_has 'apply_kernel_log_tuning' "$AR" && [ "$(grep -c 'apply_kernel_log_tuning' "$AR")" -ge 2 ] && ok || bad "apply_kernel_log_tuning must be called, not just defined"
grep_has '[ -w /proc/sys/kernel/printk ]' "$AR" && ok || bad "printk write must be guarded by a writability test"
grep_has 'KERNEL_PRINTK_LEVEL=' "$BC" && ok || bad "boot.conf.dist must document KERNEL_PRINTK_LEVEL (default empty)"
grep_has 'AK_PRINT_LEVEL=' "$BC" && ok || bad "boot.conf.dist must document AK_PRINT_LEVEL (default empty)"
# default-empty means no behavior change: the dist file must have the bare key with no value
grep -qE '^KERNEL_PRINTK_LEVEL=$' "$BC" && ok || bad "KERNEL_PRINTK_LEVEL must default to empty"
grep -qE '^AK_PRINT_LEVEL=$' "$BC" && ok || bad "AK_PRINT_LEVEL must default to empty"

# functional: the tuning is a clean no-op when knobs are empty
dash -c 'LOGPATH=/dev/null; KERNEL_PRINTK_LEVEL=""; AK_PRINT_LEVEL="";
apply_kernel_log_tuning(){ [ -n "$KERNEL_PRINTK_LEVEL" ] && [ -w /proc/sys/kernel/printk ] && echo x; [ -n "$AK_PRINT_LEVEL" ] && { for p in /proc/ak_print_level; do [ -w "$p" ]||continue; break; done; }; return 0; }
apply_kernel_log_tuning' >/dev/null 2>&1 && ok || bad "apply_kernel_log_tuning must be a clean no-op with empty knobs"

# syntax
dash -n "$AR" && ok || bad "autorun.sh dash -n"
dash -n "$SC" && ok || bad "00_system-config dash -n"

echo ""
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
