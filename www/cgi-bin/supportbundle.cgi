#!/bin/sh
# supportbundle.cgi: one-click anonymous diagnostics bundle (item 61.2)
. /mnt/www/cgi-bin/func.cgi

W=$(mktemp -d /tmp/support.XXXXXX)
trap 'rm -rf "$W"' EXIT

mkdir -p "$W/logs" "$W/system" "$W/config"

# 1. System state & kernel
uname -a > "$W/system/uname.txt" 2>/dev/null
uptime > "$W/system/uptime.txt" 2>/dev/null
cat /proc/meminfo > "$W/system/meminfo.txt" 2>/dev/null
cat /proc/cmdline > "$W/system/cmdline.txt" 2>/dev/null
cat /proc/mtd > "$W/system/mtd.txt" 2>/dev/null
cat /proc/interrupts > "$W/system/interrupts.txt" 2>/dev/null
ps aux > "$W/system/ps.txt" 2>/dev/null
df -h > "$W/system/df.txt" 2>/dev/null
dmesg | tail -n 250 > "$W/logs/dmesg.txt" 2>/dev/null

# 2. Logs
for log in /var/log/messages /tmp/logs/tc100_rtsp.log /tmp/reboot-history.log /tmp/logs/audit.log /var/run/tc100_rtsp.stat; do
  [ -f "$log" ] && cp "$log" "$W/logs/" 2>/dev/null
done

# 3. Anonymised config (strip passwords, keys, tokens)
for cfg in /mnt/config/*.conf; do
  [ -f "$cfg" ] || continue
  n=${cfg##*/}
  sed -E 's/(PASSWORD|PWD|TOKEN|KEY|PASS|SECRET)=.*/\1="********"/' "$cfg" > "$W/config/$n" 2>/dev/null
done

ARCHIVE="/tmp/tc100-support-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$ARCHIVE" -C "$W" . 2>/dev/null

printf 'Content-Type: application/gzip\r\n'
printf 'Cache-Control: no-store\r\n'
printf 'Content-Disposition: attachment; filename="%s"\r\n\r\n' "${ARCHIVE##*/}"
cat "$ARCHIVE" 2>/dev/null
rm -f "$ARCHIVE"
exit 0
