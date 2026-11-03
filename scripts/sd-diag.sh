#!/bin/sh
# sd-diag.sh: Auto-diagnostic & non-destructive check/repair for SD storage
# Usage:
#   sd-diag.sh check    -> Run quick health check, test read/write speed and inspect dmesg errors
#   sd-diag.sh repair   -> Unmount /mnt/sd safely, run filesystem check if tool available, or remount rw
#   sd-diag.sh status   -> Output JSON status of last diagnostic

STATUS_FILE="/tmp/sd-diag.status"
MNT_SD="/mnt/sd"
DEV="/dev/mmcblk0p1"
[ -b "$DEV" ] || DEV="/dev/mmcblk0"

status() {
  if [ -r "$STATUS_FILE" ]; then
    cat "$STATUS_FILE"
  else
    echo '{"ok":true,"state":"idle","errors":0,"write_speed_kb":0,"message":"No diagnostic run yet"}'
  fi
}

check() {
  _errs=$(dmesg 2>/dev/null | grep -c -E 'FAT-fs .*error|exFAT.*error|I/O error.*mmcblk|mmcblk0.*(timeout|error)|get_card_status wait too long')
  case "$_errs" in ''|*[!0-9]*) _errs=0 ;; esac

  _ro=0
  if grep -qE " $MNT_SD (vfat|exfat) " /proc/mounts 2>/dev/null; then
    grep -E " $MNT_SD (vfat|exfat) " /proc/mounts | grep -q ",ro," && _ro=1
  fi

  # Benchmark write speed with a safe 512KB temporary block
  _wspeed=0
  _target=""
  if [ "$_ro" = 0 ] && [ -d "$MNT_SD" ]; then
    _target="$MNT_SD/.sd_test_$$"
  elif [ -d "/mnt/records" ]; then
    _target="/mnt/records/.sd_test_$$"
  fi

  if [ -n "$_target" ]; then
    _t_start=$(date +%s 2>/dev/null || echo 0)
    if dd if=/dev/zero of="$_target" bs=64k count=8 2>/dev/null; then
      sync
      _t_end=$(date +%s 2>/dev/null || echo 0)
      _dur=$((_t_end - _t_start))
      [ "$_dur" -le 0 ] && _dur=1
      # 512 KB in _dur seconds -> KB/s
      _wspeed=$((512 / _dur))
      rm -f "$_target" 2>/dev/null
    else
      _ro=1
    fi
  fi

  _state="ok"
  [ "$_errs" -gt 0 ] && _state="errors"
  [ "$_ro" -eq 1 ] && _state="readonly"

  printf '{"ok":true,"state":"%s","errors":%d,"readonly":%d,"write_speed_kb":%d,"timestamp":%s}\n' \
    "$_state" "$_errs" "$_ro" "$_wspeed" "$(date +%s 2>/dev/null || echo 0)" > "$STATUS_FILE"
  cat "$STATUS_FILE"
}

repair() {
  # Safe non-destructive repair/recovery:
  # 1. Pause local recording if active
  [ -x /mnt/scripts/rec-storage.sh ] && /mnt/scripts/rec-storage.sh eject >/dev/null 2>&1
  sleep 1

  _res="repaired"
  # 2. Check if dosfsck / fsck.fat exists
  if command -v fsck.fat >/dev/null 2>&1; then
    fsck.fat -a -w "$DEV" >/dev/null 2>&1 || _res="fsck_failed"
  elif command -v dosfsck >/dev/null 2>&1; then
    dosfsck -a -w "$DEV" >/dev/null 2>&1 || _res="fsck_failed"
  fi

  # 3. Remount
  [ -x /mnt/scripts/rec-storage.sh ] && /mnt/scripts/rec-storage.sh resume >/dev/null 2>&1
  sh /mnt/v3/linux66-sd/sdinfo-sd.sh >/dev/null 2>&1

  # Re-evaluate
  check
}

case "$1" in
  check) check ;;
  repair) repair ;;
  status) status ;;
  *) echo "Usage: $0 {check|repair|status}" >&2; exit 1 ;;
esac
