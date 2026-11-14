#!/bin/sh
# supportbundle.cgi: one-click anonymous diagnostics bundle (item 61.2)
if [ -r /mnt/www/cgi-bin/func.cgi ]; then
  . /mnt/www/cgi-bin/func.cgi
elif [ -r "${0%/*}/func.cgi" ]; then
  . "${0%/*}/func.cgi"
fi

SB_PROC_DIR="${SB_PROC_DIR:-/proc}"
SB_SYS_DIR="${SB_SYS_DIR:-/sys}"
SB_TMP_DIR="${SB_TMP_DIR:-/tmp}"
SB_VAR_DIR="${SB_VAR_DIR:-/var}"
SB_CONFIG_DIR="${SB_CONFIG_DIR:-/mnt/config}"
SB_MNT_LOG_DIR="${SB_MNT_LOG_DIR:-/mnt/log}"

W=$(mktemp -d "${SB_TMP_DIR}/support.XXXXXX")
ARCHIVE_PATH="${W}.tar.gz"
trap 'rm -rf "$W" "$ARCHIVE_PATH"' EXIT

mkdir -p "$W/logs" "$W/system" "$W/config"

# 1. System state, kernel, proc & driver sysfs parameters
uname -a > "$W/system/uname.txt" 2>/dev/null
uptime > "$W/system/uptime.txt" 2>/dev/null
for _sb_pair in \
  "meminfo:meminfo.txt" \
  "cmdline:cmdline.txt" \
  "mtd:mtd.txt" \
  "interrupts:interrupts.txt" \
  "net/wireless:net-wireless.txt" \
  "net/snmp:net-snmp.txt"; do
  _sb_src="$SB_PROC_DIR/${_sb_pair%%:*}"
  _sb_dst="$W/system/${_sb_pair#*:}"
  [ -r "$_sb_src" ] && cat "$_sb_src" > "$_sb_dst" 2>/dev/null
done
ps aux > "$W/system/ps.txt" 2>/dev/null
df -h > "$W/system/df.txt" 2>/dev/null
dmesg | tail -n 250 > "$W/logs/dmesg.txt" 2>/dev/null

: > "$W/system/driver-params.txt"
for _sb_p in \
  "$SB_SYS_DIR/module/anyka/parameters/core_pll" \
  "$SB_SYS_DIR/module/anyka/parameters/asic_hz" \
  "$SB_SYS_DIR/module/ak_isp/parameters/awb_live" \
  "$SB_SYS_DIR/module/ak39_vi/parameters/nr3d" \
  "$SB_SYS_DIR/module/ak39_vi/parameters/nr3d_overflow" \
  "$SB_SYS_DIR/module/ak39_vi/parameters/sub_channel" \
  "$SB_SYS_DIR/module/ak39_vi/parameters/main_scale" \
  "$SB_SYS_DIR/module/rtl8xxxu/parameters/ampdu_rx" \
  "$SB_SYS_DIR/module/rtl8xxxu/parameters/tx_atten"; do
  if [ -r "$_sb_p" ]; then
    IFS= read -r _sb_v < "$_sb_p" 2>/dev/null || _sb_v=""
    printf '%s=%s\n' "$_sb_p" "$_sb_v" >> "$W/system/driver-params.txt"
  fi
done

# 2. Logs & runtime diagnostic snapshots
for _sb_log in \
  "$SB_VAR_DIR/log/messages" \
  "$SB_VAR_DIR/run/tc100_rtsp.stat" \
  "$SB_TMP_DIR/logs/tc100_rtsp.log" \
  "$SB_TMP_DIR/logs/daynight.log" \
  "$SB_CONFIG_DIR/log/daynight-last.log" \
  "$SB_CONFIG_DIR/overclock.state" \
  "$SB_CONFIG_DIR/log/overclock.log" \
  "$SB_TMP_DIR/logs/overclock-samples.log" \
  "$SB_TMP_DIR/log/audit.log" \
  "$SB_TMP_DIR/logs/audit.log" \
  "$SB_TMP_DIR/log/service-watchdog.log" \
  "$SB_TMP_DIR/log/mqtt-bridge.log" \
  "$SB_TMP_DIR/log/nightmode.log" \
  "$SB_TMP_DIR/log/stability.pending" \
  "$SB_CONFIG_DIR/log/reboot-history.log" \
  "$SB_MNT_LOG_DIR/reboot-history.log" \
  "$SB_TMP_DIR/reboot-history.log" \
  "$SB_TMP_DIR/boot-milestones.txt" \
  "$SB_CONFIG_DIR/log/boot-milestones.log" \
  "$SB_TMP_DIR/wifi-quality" \
  "$SB_TMP_DIR/wifi-quality.log" \
  "$SB_TMP_DIR/cam_awb" \
  "$SB_TMP_DIR/last-reboot-reason" \
  "$SB_TMP_DIR/safemode"; do
  [ -f "$_sb_log" ] || continue
  _sb_bn="${_sb_log##*/}"
  [ -e "$W/logs/$_sb_bn" ] || cp "$_sb_log" "$W/logs/$_sb_bn" 2>/dev/null
done

# 3. Anonymised config (strip passwords, psks, keys, tokens, auth headers, webhook/upload URLs & chat IDs)
for _sb_cfg in "$SB_CONFIG_DIR"/*.conf; do
  [ -f "$_sb_cfg" ] || continue
  _sb_n="${_sb_cfg##*/}"
  sed -E \
    -e 's/^([[:space:]]*([A-Za-z0-9_]*([Pp][Aa][Ss][Ss]([Ww][Oo][Rr][Dd])?|[Pp][Ww][Dd]|[Tt][Oo][Kk][Ee][Nn]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Aa][Uu][Tt][Hh]|[Pp][Ss][Kk]|[Kk][Ee][Yy])|api[Tt]oken|user[Cc]hat[Ii]d|WEBHOOK_URL|NOTIFY_UPLOAD_URL|NTFY_TOPIC|wep_key[0-3])[[:space:]]*=[[:space:]]*).*/\1"********"/' \
    -e 's#(https?://)[^/@[:space:]]+:[^/@[:space:]]+@#\1***:***@#g' \
    "$_sb_cfg" > "$W/config/$_sb_n" 2>/dev/null
done

ARCHIVE_NAME="tc100-support-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$ARCHIVE_PATH" -C "$W" . 2>/dev/null

printf 'Content-Type: application/gzip\r\n'
printf 'Cache-Control: no-store\r\n'
printf 'Content-Disposition: attachment; filename="%s"\r\n\r\n' "$ARCHIVE_NAME"
cat "$ARCHIVE_PATH" 2>/dev/null
exit 0
