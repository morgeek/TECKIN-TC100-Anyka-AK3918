#!/bin/sh
# sd-diag.sh: Auto-diagnostic & non-destructive check/repair for SD storage
# Usage:
#   sd-diag.sh check    -> Run quick health check and test write speed; the error count comes from /tmp/sd-health
#   sd-diag.sh repair   -> Unmount /mnt/sd safely, run filesystem check if tool available, or remount rw
#                          (refused when the card is mounted read-write and holds the running firmware)
#   sd-diag.sh status   -> Output JSON status of last diagnostic
# v3/linux66-sd/sdinfo-sd.sh is the only scanner of the kernel log for card errors and the only writer of
# /tmp/sd-health; this script runs it and reads the result, so the panel and the diagnostic always agree.

STATUS_FILE="/tmp/sd-diag.status"
MNT_SD="/mnt/sd"
DEV="/dev/mmcblk0p1"
[ -b "$DEV" ] || DEV="/dev/mmcblk0"
SDINFO="${SDD_SDINFO:-/mnt/v3/linux66-sd/sdinfo-sd.sh}"
HEALTH="${SDD_HEALTH:-/tmp/sd-health}"
PROC_MOUNTS="${SDD_PROC_MOUNTS:-/proc/mounts}"
# fsck.fat comes with the user space (ext/bin, item 41); the web server's environment may not have it on PATH
PATH="/mnt/ext/bin:$PATH"

status() {
  if [ -r "$STATUS_FILE" ]; then
    cat "$STATUS_FILE"
  else
    echo '{"ok":true,"state":"idle","errors":0,"write_speed_kb":0,"message":"No diagnostic run yet"}'
  fi
}

# refresh /tmp/sd-health through sdinfo-sd.sh, then read state and errors from it
read_health() {
  [ -f "$SDINFO" ] && sh "$SDINFO" >/dev/null 2>&1
  _hstate=nocard; _herrs=0
  if [ -r "$HEALTH" ]; then
    while IFS='=' read -r _k _v; do
      case "$_k" in state) _hstate="$_v" ;; errors) _herrs="$_v" ;; esac
    done < "$HEALTH"
  fi
  case "$_herrs" in ''|*[!0-9]*) _herrs=0 ;; esac
  case "$_hstate" in ''|*[!a-z]*) _hstate=nocard ;; esac
}

check() {
  read_health
  _errs=$_herrs
  _ro=0
  [ "$_hstate" = readonly ] && _ro=1

  # Benchmark write speed with a safe 512KB temporary block
  _wspeed=0
  _target=""
  if [ "$_ro" = 0 ] && [ "$_hstate" != nocard ] && [ -d "$MNT_SD" ]; then
    _target="$MNT_SD/.sd_test_$$"
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

  _state="$_hstate"
  [ "$_ro" -eq 1 ] && _state="readonly"

  printf '{"ok":true,"state":"%s","errors":%d,"readonly":%d,"write_speed_kb":%d,"timestamp":%s}\n' \
    "$_state" "$_errs" "$_ro" "$_wspeed" "$(date +%s 2>/dev/null || echo 0)" > "$STATUS_FILE"
  cat "$STATUS_FILE"
}

# The card is mounted read-write and the camera runs from it (SD / trial mode: no /tmp/flashmode): never fsck it.
card_runs_firmware() {
  [ -f "${SDD_FLASHMODE:-/tmp/flashmode}" ] && return 1
  while read -r _d _mp _fs _opt _rest; do
    case "$_mp $_fs" in
      "/mnt/sd vfat"|"/mnt/sd exfat"|"/mnt vfat"|"/mnt exfat")
        case ",$_opt," in *,ro,*) ;; *) return 0 ;; esac ;;
    esac
  done < "$PROC_MOUNTS"
  return 1
}

repair() {
  if card_runs_firmware; then
    echo '{"ok":false,"state":"refused","message":"The card is mounted read-write and holds the running firmware: a file system check would corrupt it. Boot the camera from its flash, or check the card on a computer."}'
    return 1
  fi
  # Safe non-destructive recovery / remount:
  # 1. Pause local recording if active
  [ -x /mnt/scripts/rec-storage.sh ] && /mnt/scripts/rec-storage.sh eject >/dev/null 2>&1
  sleep 1

  _res="remounted"
  # 2. Check if dosfsck / fsck.fat exists
  if command -v fsck.fat >/dev/null 2>&1; then
    fsck.fat -a -w "$DEV" >/dev/null 2>&1 && _res="fsck_repaired" || _res="fsck_failed"
  elif command -v dosfsck >/dev/null 2>&1; then
    dosfsck -a -w "$DEV" >/dev/null 2>&1 && _res="fsck_repaired" || _res="fsck_failed"
  else
    # Fallback when fsck binary is not present in rootfs: remount rw safely
    mount -o remount,rw "$MNT_SD" 2>/dev/null || true
  fi

  # 3. Remount & resume
  [ -x /mnt/scripts/rec-storage.sh ] && /mnt/scripts/rec-storage.sh resume >/dev/null 2>&1

  # Re-evaluate (check refreshes /tmp/sd-health through sdinfo-sd.sh)
  check
}

case "$1" in
  check) check ;;
  repair) repair ;;
  status) status ;;
  *) echo "Usage: $0 {check|repair|status}" >&2; exit 1 ;;
esac
