#!/bin/sh
# sd-format.sh — Safe in-camera formatting of microSD cards to FAT32 (audit 2026-11-06, F4).
# Usage: sd-format.sh [format]
# Formats the microSD card partition as FAT32 (32 KB cluster size, label TC100_SD).
# Safety rules (AGENTS.md):
#   - Refuses if the camera is currently running from the SD card.
#   - Refuses if the card carries boot/install files (wifitest, uImage, flash-stock.bin).
#   - Pauses local recording and unmounts cleanly before writing.
#   - Remounts and recreates /mnt/sd/DCIM on success.

MNT_SD="/mnt/sd"
REC_STORAGE="/mnt/scripts/rec-storage.sh"

find_card_dev() {
  if [ -b /dev/mmcblk0p1 ]; then
    echo "/dev/mmcblk0p1"
  elif [ -b /dev/mmcblk0 ]; then
    echo "/dev/mmcblk0"
  else
    return 1
  fi
}

card_runs_firmware() {
  grep -qE ' /mnt (vfat|exfat) ' /proc/mounts 2>/dev/null && return 0
  grep -qE ' / (vfat|exfat) ' /proc/mounts 2>/dev/null && return 0
  [ ! -f /tmp/flashmode ] && [ "$(cat /tmp/tc100-storage 2>/dev/null)" != flash ]
}

card_boot_file() {
  for f in wifitest uImage uimage root.sqsh4 usr.sqsh4 usr.jffs2 tc100test; do
    if [ -e "$MNT_SD/$f" ]; then
      echo "$f"
      return 0
    fi
  done
  return 1
}

format_card() {
  if card_runs_firmware; then
    printf '{"ok":false,"error":"The camera is currently running from this SD card: formatting is refused."}\n'
    return 1
  fi

  DEV=$(find_card_dev)
  if [ -z "$DEV" ]; then
    printf '{"ok":false,"error":"No microSD card block device detected."}\n'
    return 1
  fi

  # Check for boot/stock files before touching anything
  if _bf="$(card_boot_file)"; then
    printf '{"ok":false,"error":"MicroSD card contains boot or firmware files (%s): formatting is refused to prevent data loss."}\n' "$_bf"
    return 1
  fi

  # Check if mkfs tool is available
  MKFS_BIN=""
  for cmd in mkfs.fat mkdosfs /mnt/ext/bin/mkfs.fat /mnt/ext/bin/mkdosfs; do
    if command -v "$cmd" >/dev/null 2>&1; then
      MKFS_BIN="$cmd"
      break
    elif [ -x "$cmd" ]; then
      MKFS_BIN="$cmd"
      break
    fi
  done

  if [ -z "$MKFS_BIN" ]; then
    printf '{"ok":false,"error":"Formatting utility (mkfs.fat) is not installed in user space."}\n'
    return 1
  fi

  # Pause recording and unmount
  [ -x "$REC_STORAGE" ] && "$REC_STORAGE" eject >/dev/null 2>&1
  sleep 1
  umount "$MNT_SD" 2>/dev/null || true
  sleep 1

  # Format with 32 KB clusters (-s 64 for 512B sectors) and label
  _out=$("$MKFS_BIN" -F 32 -s 64 -n "TC100_SD" "$DEV" 2>&1)
  _rc=$?

  # Remount
  if [ -x "$REC_STORAGE" ]; then
    "$REC_STORAGE" mount >/dev/null 2>&1 || "$REC_STORAGE" resume >/dev/null 2>&1
  else
    mount -t vfat -o noatime,nodiratime,utf8 "$DEV" "$MNT_SD" 2>/dev/null || true
  fi

  # Recreate DCIM directory
  [ -d "$MNT_SD" ] && mkdir -p "$MNT_SD/DCIM" 2>/dev/null || true

  if [ $_rc -eq 0 ]; then
    printf '{"ok":true,"message":"MicroSD card successfully formatted as FAT32."}\n'
    return 0
  else
    printf '{"ok":false,"error":"Formatting failed (code %d): %s"}\n' "$_rc" "$_out"
    return 1
  fi
}

case "$1" in
  format|'')
    format_card
    ;;
  *)
    echo "Usage: $0 format" >&2
    exit 1
    ;;
esac
