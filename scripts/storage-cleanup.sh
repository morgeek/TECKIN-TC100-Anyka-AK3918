#!/bin/sh
# storage-cleanup.sh — Delete oldest recordings when SD card exceeds a usage threshold.
# Runs hourly via cron (managed by init_crond in autorun.sh).
# Config is read from /mnt/config/boot.conf.
#
# Variables (with defaults):
#   STORAGE_CLEANUP_ENABLE=0          — set to 1 to enable
#   STORAGE_CLEANUP_THRESHOLD=90      — delete when usage % >= this
#   STORAGE_CLEANUP_TARGET=85         — stop deleting when usage drops below this
#   STORAGE_CLEANUP_DCIM_PATH=/mnt/DCIM — directory tree to clean
#   STORAGE_CLEANUP_LOG_MAX_BYTES=65536 — rotate log at this size
#
# Flags:
#   --dryrun  — log what would be deleted without actually removing anything

. /mnt/scripts/common_functions.sh

DRYRUN=0
for _arg in "$@"; do
  case "$_arg" in --dryrun|--dry-run) DRYRUN=1 ;; esac
done

CONFIGPATH="/mnt/config"
LOGPATH="/tmp/log/storage-cleanup.log"
# LOGMAX is assigned AFTER boot.conf is sourced (below); assigning it here would
# lock in the default before the operator's STORAGE_CLEANUP_LOG_MAX_BYTES is read.

_sc_log() {
    if [ ! -d /tmp/log ]; then
        mkdir -p /tmp/log 2>/dev/null || true
    fi
    # Rotate if too large
    if [ -f "$LOGPATH" ]; then
        size="$(wc -c < "$LOGPATH" 2>/dev/null)"
        case "$size" in
            ''|*[!0-9]*) ;;
            *) [ "$size" -gt "$LOGMAX" ] && mv "$LOGPATH" "${LOGPATH}.1" 2>/dev/null || true ;;
        esac
    fi
    read -r _sc_up _ < /proc/uptime
    printf '@%s %s\n' "${_sc_up%.*}" "$1" >> "$LOGPATH"
}

_sc_disk_pct() {
    df /mnt 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5); print $5+0}'
}

install_config "$CONFIGPATH/boot.conf"
if [ -f "$CONFIGPATH/boot.conf" ]; then
    # shellcheck disable=SC1090
    . "$CONFIGPATH/boot.conf"
fi

STORAGE_CLEANUP_ENABLE="${STORAGE_CLEANUP_ENABLE:-0}"
STORAGE_CLEANUP_THRESHOLD="${STORAGE_CLEANUP_THRESHOLD:-90}"
STORAGE_CLEANUP_TARGET="${STORAGE_CLEANUP_TARGET:-85}"
STORAGE_CLEANUP_DCIM_PATH="${STORAGE_CLEANUP_DCIM_PATH:-/mnt/DCIM}"
# Now that boot.conf has been sourced, honor the operator's log-size tunable.
LOGMAX="${STORAGE_CLEANUP_LOG_MAX_BYTES:-65536}"
case "$LOGMAX" in ''|*[!0-9]*) LOGMAX=65536 ;; esac

case "$STORAGE_CLEANUP_ENABLE" in
    1|true|yes|on|enable|enabled) ;;
    *) [ "$DRYRUN" = "1" ] || exit 0 ;;
esac

# Validate numeric config
case "$STORAGE_CLEANUP_THRESHOLD" in
    ''|*[!0-9]*) STORAGE_CLEANUP_THRESHOLD=90 ;;
esac
case "$STORAGE_CLEANUP_TARGET" in
    ''|*[!0-9]*) STORAGE_CLEANUP_TARGET=85 ;;
esac
if [ "$STORAGE_CLEANUP_THRESHOLD" -gt 99 ]; then STORAGE_CLEANUP_THRESHOLD=99; fi
if [ "$STORAGE_CLEANUP_TARGET" -ge "$STORAGE_CLEANUP_THRESHOLD" ]; then
    STORAGE_CLEANUP_TARGET=$((STORAGE_CLEANUP_THRESHOLD - 5))
fi

pct="$(_sc_disk_pct)"
case "$pct" in
    ''|*[!0-9]*) exit 0 ;;
esac

if [ "$pct" -lt "$STORAGE_CLEANUP_THRESHOLD" ]; then
    exit 0
fi

if [ "$DRYRUN" = "1" ]; then
    _sc_log "DRYRUN: SD at ${pct}% >= threshold ${STORAGE_CLEANUP_THRESHOLD}% — would start cleanup (target ${STORAGE_CLEANUP_TARGET}%)"
else
    _sc_log "SD at ${pct}% >= threshold ${STORAGE_CLEANUP_THRESHOLD}% — starting cleanup (target ${STORAGE_CLEANUP_TARGET}%)"
fi

if [ ! -d "$STORAGE_CLEANUP_DCIM_PATH" ]; then
    _sc_log "ERROR: DCIM path '$STORAGE_CLEANUP_DCIM_PATH' not found"
    exit 1
fi

deleted=0
rounds=0

while true; do
    rounds=$((rounds + 1))
    if [ "$rounds" -gt 100 ]; then
        _sc_log "WARNING: hit round limit (100), stopping"
        break
    fi

    pct="$(_sc_disk_pct)"
    case "$pct" in
        ''|*[!0-9]*) break ;;
    esac
    if [ "$pct" -lt "$STORAGE_CLEANUP_TARGET" ]; then
        break
    fi

    # Find oldest entry (file or directory) under DCIM, sorted oldest-first
    # ls -1t lists newest first, tail gives the oldest
    oldest="$(ls -1t "$STORAGE_CLEANUP_DCIM_PATH" 2>/dev/null | tail -n 1)"
    if [ -z "$oldest" ]; then
        _sc_log "No more entries in $STORAGE_CLEANUP_DCIM_PATH — disk is still at ${pct}%"
        break
    fi

    target_path="$STORAGE_CLEANUP_DCIM_PATH/$oldest"

    # Skip entries modified within the last minute — likely still being written to.
    # `oldest` is the entry with the OLDEST mtime, so if IT is recent then every
    # remaining entry is too. Break instead of `continue`: continuing would re-pick
    # the same oldest entry every round and spin all 100 rounds (df+ls+find forks)
    # deleting nothing on a 400MHz core.
    if [ -n "$(find "$target_path" -maxdepth 0 -mmin -1 2>/dev/null)" ]; then
      _sc_log "SKIP: oldest entry $target_path modified recently — nothing safe to delete yet"
      break
    fi

    if [ -d "$target_path" ]; then
        if [ "$DRYRUN" = "1" ]; then
            _sc_log "DRYRUN: would remove directory $target_path"
            deleted=$((deleted + 1))
        else
            rm -rf "$target_path" 2>/dev/null && deleted=$((deleted + 1)) || {
                _sc_log "ERROR: failed to remove directory $target_path"
                break
            }
        fi
    elif [ -f "$target_path" ]; then
        if [ "$DRYRUN" = "1" ]; then
            _sc_log "DRYRUN: would remove file $target_path"
            deleted=$((deleted + 1))
        else
            rm -f "$target_path" 2>/dev/null && deleted=$((deleted + 1)) || {
                _sc_log "ERROR: failed to remove file $target_path"
                break
            }
        fi
    else
        break
    fi
    # In dryrun mode each "deletion" doesn't actually free space, so
    # the disk percentage never drops — break after logging all candidates.
    if [ "$DRYRUN" = "1" ]; then
        pct=$((pct - 1))
    fi
done

pct="$(_sc_disk_pct)"
if [ "$DRYRUN" = "1" ]; then
    _sc_log "DRYRUN: would remove $deleted item(s) (SD actually at ${pct}%)"
else
    _sc_log "Done: removed $deleted item(s), SD now at ${pct}%"
fi
