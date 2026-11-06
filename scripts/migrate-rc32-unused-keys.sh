#!/bin/sh
# migrate-rc32-unused-keys.sh: once per camera (config/.migrated-rc32-unused-keys), the keys of /mnt/config/boot.conf that
# nothing reads on 3.0 (web UI audit 2026-11-06, U4: they came from the 2.x firmware: lighttpd / HTTPS modes, the CPU
# scaler, the vendor RTSP server, the "lite" RTSP tuning, the storage cleanup of 2.x) are COMMENTED OUT, never deleted:
#   KEY=value   ->   #[rc32: unused on 3.0] KEY=value
# so that the Configuration editor no longer offers them as settings and the old value stays readable (and can be put back
# by removing the prefix). RTSP_LITE_TALK is NOT in the list: tc100_rtsp, onvifd and Settings -> Audio read it.
# Each commented key is logged to config/migrations.log. config/boot.conf.dist does not hold these keys any more
# (LIGHTWEIGHT_MODE was the last one, removed with this script).
# MU_CONF_DIR changes /mnt/config (tests).
C=${MU_CONF_DIR:-/mnt/config}
[ -d "$C" ] || exit 0
[ -f "$C/.migrated-rc32-unused-keys" ] && exit 0
B=$C/boot.conf
n=0
if [ -f "$B" ]; then
  : > "$B.tmp.$$" || exit 0
  while IFS= read -r l || [ -n "$l" ]; do
    case "$l" in
      RTSP_LITE_TALK=*) printf '%s\n' "$l" ;;
      WEB_MODE=*|ULTRALITE_HTTP_PORT=*|UI_ULTRALITE_MODE=*|LIGHTWEIGHT_MODE=*|CPU_SCALER_*=*|RTSP_SERVER=*|RTSP_VENDOR_PORT=*|RTSP_LITE_*=*|RTSP_PROC_*=*|RTSP_FPS_LOCK=*|FIRMWARE_IMAGE=*|STORAGE_CLEANUP_*=*|TAMPER_DETECTION=*)
        printf '#[rc32: unused on 3.0] %s\n' "$l"
        printf '%s boot.conf: commented out %s\n' "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)" "${l%%=*}" >> "$C/migrations.log"
        n=$((n + 1)) ;;
      *) printf '%s\n' "$l" ;;
    esac
  done < "$B" > "$B.tmp.$$"
  if [ "$n" -gt 0 ]; then mv -f "$B.tmp.$$" "$B"; else rm -f "$B.tmp.$$"; fi
fi
[ "$n" -gt 0 ] && echo "[tc100-v3] boot.conf: $n key(s) without a reader on 3.0 commented out (config/migrations.log)" > /dev/console 2>/dev/null
: > "$C/.migrated-rc32-unused-keys"
exit 0
