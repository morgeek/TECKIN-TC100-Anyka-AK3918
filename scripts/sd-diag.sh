#!/bin/sh
# sd-diag.sh: Auto-diagnostic & non-destructive check/repair for SD storage
# Usage:
#   sd-diag.sh check    -> Run quick health check and test write speed; the error count comes from /tmp/sd-health
#   sd-diag.sh repair   -> Unmount /mnt/sd safely, run filesystem check if tool available, or remount rw
#                          (refused when the card is mounted read-write and holds the running firmware)
#   sd-diag.sh status   -> Output JSON status of last diagnostic
# v3/linux66-sd/sdinfo-sd.sh is the only scanner of the kernel log for card errors and the only writer of
# /tmp/sd-health; this script runs it and reads the result, so the panel and the diagnostic always agree.

STATUS_FILE="${SDD_STATUS_FILE:-/tmp/sd-diag.status}"
MNT_SD="${SDD_MNT:-/mnt/sd}"
DEV="${SDD_DEV:-/dev/mmcblk0p1}"
[ -n "$SDD_DEV" ] || [ -b "$DEV" ] || DEV="/dev/mmcblk0"
# R14: where repair mounts the card read-only to look for boot files when it is not mounted at /mnt/sd
RO_MNT="${SDD_RO_MNT:-/tmp/sd-diag.ro}"
REC_STORAGE="${SDD_REC_STORAGE:-/mnt/scripts/rec-storage.sh}"
# the files that make the vendor boot use a card (same list as rec-storage.sh _mount_card, which refuses such a card):
# never check nor write such a card
SD_BOOT_FILES="wifitest uImage uimage root.sqsh4 usr.sqsh4 usr.jffs2"
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

# R14: the first boot file found in directory $1 (a card carrying one is a boot / install card: refused)
boot_file_in() {
  for _bf in $SD_BOOT_FILES; do
    [ -e "$1/$_bf" ] && { echo "$_bf"; return 0; }
  done
  return 1
}

# R14: is the card a boot card? Looks at /mnt/sd when the card is mounted there, else mounts it read-only on RO_MNT.
# Prints the boot file found; returns 1 when the card has none (or cannot be mounted: nothing to protect then).
card_boot_file() {
  if grep -qE " $MNT_SD (vfat|exfat) " "$PROC_MOUNTS" 2>/dev/null; then
    boot_file_in "$MNT_SD"; return
  fi
  mkdir -p "$RO_MNT" 2>/dev/null
  ${SDD_MOUNT:-mount} -t vfat -o ro "$DEV" "$RO_MNT" 2>/dev/null || ${SDD_MOUNT:-mount} -t exfat -o ro "$DEV" "$RO_MNT" 2>/dev/null || return 1
  _cbf="$(boot_file_in "$RO_MNT")"; _cbr=$?
  ${SDD_UMOUNT:-umount} "$RO_MNT" 2>/dev/null
  [ "$_cbr" = 0 ] && echo "$_cbf"
  return $_cbr
}

# little-endian unsigned integer of $2 bytes at offset $1 of the card's first sector
bs_le() {
  dd if="$DEV" bs=1 skip="$1" count="$2" 2>/dev/null | od -An -v -tu1 | {
    _v=0; _m=1
    for _b in $(cat); do _v=$((_v + _b * _m)); _m=$((_m * 256)); done
    echo "$_v"
  }
}

# R14: memory fsck.fat needs, in KB: 12 bytes per cluster (its FAT copy, 8 bytes an entry, and the owner of each
# cluster, 4). A 64 GB card (32 KB clusters, 2 M clusters) needs about 24 MB: on the .24 (rc28/rc29) fsck.fat was
# OOM-killed at every boot. Prints nothing for a card without a FAT file system (exFAT, unreadable).
fsck_need_kb() {
  case "$(dd if="$DEV" bs=1 skip=3 count=5 2>/dev/null)" in EXFAT) return 1 ;; esac
  [ "$(bs_le 510 2)" = 43605 ] || return 1		# 0x55 0xAA
  _bps="$(bs_le 11 2)"; _spc="$(bs_le 13 1)"
  _tot="$(bs_le 19 2)"; [ "$_tot" -gt 0 ] 2>/dev/null || _tot="$(bs_le 32 4)"
  case "$_bps" in 512|1024|2048|4096) ;; *) return 1 ;; esac
  [ "$_spc" -gt 0 ] 2>/dev/null && [ "$_tot" -gt 0 ] 2>/dev/null || return 1
  echo $(( _tot / _spc * 12 / 1024 + 1024 ))
}

mem_available_kb() {
  if [ -n "$SDD_MEMAVAIL_KB" ]; then echo "$SDD_MEMAVAIL_KB"; return; fi
  while read -r _mk _mv _; do [ "$_mk" = MemAvailable: ] && { echo "$_mv"; return; }; done < /proc/meminfo
  echo 0
}

repair_result() {	# state message: written for the Recording page (sd_card_info "diag"), printed for the button
  printf '{"ok":%s,"state":"%s","message":"%s","timestamp":%s}\n' "$1" "$2" "$3" "$(date +%s 2>/dev/null || echo 0)" > "$STATUS_FILE"
  cat "$STATUS_FILE"
}

repair() {
  if card_runs_firmware; then
    echo '{"ok":false,"state":"refused","message":"The card is mounted read-write and holds the running firmware: a file system check would corrupt it. Boot the camera from its flash, or check the card on a computer."}'
    return 1
  fi
  # (a) R14: a boot / install card (the owner's way back) is never checked nor written; the recorder refuses it anyway
  if _bf="$(card_boot_file)"; then
    repair_result false refused "Boot or install card ($_bf at its root): not repaired, not used for recordings."
    return 1
  fi
  # (b) R14: fsck.fat keeps the whole FAT in memory; not enough of it (MemAvailable minus 8 MB): mount the card as it
  # is (Linux mounts a FAT left dirty) and say so on the Recording page
  _need="$(fsck_need_kb)"
  _avail="$(mem_available_kb)"
  _fsck=1
  if [ -z "$_need" ]; then
    _fsck=0; _res=remounted		# exFAT or no FAT boot sector: fsck.fat cannot check it
  elif [ "$_need" -gt $((_avail - 8192)) ]; then
    _fsck=0; _res=dirty-not-checked
  fi

  # Safe non-destructive recovery / remount:
  # 1. Pause local recording if active
  [ -x "$REC_STORAGE" ] && "$REC_STORAGE" eject >/dev/null 2>&1
  sleep 1

  # 2. fsck.fat (or dosfsck) when there is room; (c) it is the one the OOM killer takes, never tc100_rtsp
  if [ "$_fsck" = 1 ]; then
    _res="remounted"
    if command -v fsck.fat >/dev/null 2>&1; then
      ( echo 1000 > /proc/self/oom_score_adj; exec fsck.fat -a -w "$DEV" ) >/dev/null 2>&1 && _res="fsck_repaired" || _res="fsck_failed"
    elif command -v dosfsck >/dev/null 2>&1; then
      ( echo 1000 > /proc/self/oom_score_adj; exec dosfsck -a -w "$DEV" ) >/dev/null 2>&1 && _res="fsck_repaired" || _res="fsck_failed"
    else
      # Fallback when fsck binary is not present in rootfs: remount rw safely
      mount -o remount,rw "$MNT_SD" 2>/dev/null || true
    fi
  fi

  # 3. Remount & resume, (d) after a failed or killed fsck too
  [ -x "$REC_STORAGE" ] && "$REC_STORAGE" resume >/dev/null 2>&1

  if [ "$_res" = dirty-not-checked ]; then
    repair_result true dirty-not-checked "Card not checked (not enough memory for a $((_need / 1024)) MB check): it is used as it is. Check the card on a computer."
    return 0
  fi
  # Re-evaluate (check refreshes /tmp/sd-health through sdinfo-sd.sh)
  check
}

case "$1" in
  check) check ;;
  repair) repair ;;
  status) status ;;
  *) echo "Usage: $0 {check|repair|status}" >&2; exit 1 ;;
esac
