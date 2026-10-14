#!/bin/sh
# rofs.sh — run the firmware code from a read-only image (firmware.sqfs).
#
# The code directories (bin lib scripts controlscripts www) normally live as
# hundreds of files on the SD card's FAT/exFAT file system, next to the logs,
# recordings and configs that are written all day. A FAT corruption (seen on
# hardware 2026-10-13) can then damage the code itself. With an image:
#
#   * the code is one squashfs file, written only by an update and checked
#     against its md5 (firmware.sqfs.md5) in the background after each boot;
#   * at boot it is loop-mounted read-only and bind-mounted over the FAT code
#     directories, which stay underneath, untouched, as the fallback;
#   * the FAT copies are still kept up to date by updates, through a second
#     view of the card without the overlays (FAT_VIEW below).
#
# The image is skipped (FAT copies used, as before) when: it is missing, its
# VERSION differs from /mnt/VERSION (stale image after a manual copy or a
# rollback), boot.conf has FIRMWARE_IMAGE=0, RECOVERY mode is on, or the
# mount fails. A corrupt image found by "verify" is renamed .bad, so the next
# boot uses the FAT copies.
#
#   rofs.sh mount     boot: apply a pending update (.new), mount, overlay
#   rofs.sh verify    md5 check of the mounted image (low priority, after boot)
#   rofs.sh status    one line: active|inactive <reason>
#
# Runs before the extended busybox is bind-mounted: vendor busybox applets only.

SD="${ROFS_SD:-/mnt}"
IMAGE="$SD/firmware.sqfs"
RUN="${ROFS_RUN:-/tmp/rofs}"
IMG_MNT="$RUN/img"
FAT_VIEW="$RUN/fat"
STATUS="$RUN/status"
LOG="${ROFS_LOG:-/tmp/log/rofs.log}"
DIRS="bin lib scripts controlscripts www"

_rofs_log() { mkdir -p "${LOG%/*}" 2>/dev/null; echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$LOG"; }
_rofs_first() { _rf=""; [ -r "$1" ] && read -r _rf _rfr < "$1"; printf '%s' "$_rf"; }
_rofs_status() { mkdir -p "$RUN" 2>/dev/null; echo "$*" > "$STATUS"; _rofs_log "$*"; }

# rofs_active -> 0 when the image is mounted and overlaid.
rofs_active() { [ "$(_rofs_first "$STATUS")" = active ]; }

_rofs_conf_enabled()
{
    _v="$(awk -F= '$0 !~ /^[[:space:]]*#/ && $1 == "FIRMWARE_IMAGE" {print $2; exit}' \
        "$SD/config/boot.conf" 2>/dev/null)"
    case "$_v" in 0|false|no|off|disable|disabled) return 1 ;; esac
    return 0
}

# An update writes the new image as firmware.sqfs.new (the running one is in
# use by the loop device and must not be replaced under it); swap it in here,
# before anything is mounted. The previous image is kept as .old (rollback).
_rofs_apply_pending()
{
    [ -f "$IMAGE.new" ] || return 0
    [ -f "$IMAGE" ] && mv -f "$IMAGE" "$IMAGE.old"
    if mv -f "$IMAGE.new" "$IMAGE"; then
        _rofs_log "applied pending image $(_rofs_first "$IMAGE.md5")"
    fi
    sync
}

rofs_mount()
{
    rofs_active && return 0
    # At boot /tmp/log does not exist yet, and a failed "2>>$LOG" redirection
    # means the command is not run at all.
    mkdir -p "${LOG%/*}" "$RUN" 2>/dev/null
    if [ -f "$SD/RECOVERY" ]; then _rofs_status "inactive recovery_mode"; return 0; fi
    _rofs_apply_pending
    if [ ! -f "$IMAGE" ]; then _rofs_status "inactive no_image"; return 0; fi
    if ! _rofs_conf_enabled; then _rofs_status "inactive disabled"; return 0; fi

    mkdir -p "$IMG_MNT" "$FAT_VIEW" || { _rofs_status "inactive no_tmp"; return 1; }
    if ! mount -t squashfs -o loop,ro "$IMAGE" "$IMG_MNT" 2>>"$LOG"; then
        _rofs_status "inactive mount_failed"; return 1
    fi
    _iv="$(_rofs_first "$IMG_MNT/VERSION")"; _sv="$(_rofs_first "$SD/VERSION")"
    if [ -z "$_iv" ] || [ "$_iv" != "$_sv" ]; then
        umount "$IMG_MNT" 2>/dev/null
        _rofs_status "inactive version_mismatch image=$_iv sd=$_sv"; return 0
    fi
    for _d in $DIRS; do
        [ -d "$IMG_MNT/$_d" ] && [ -d "$SD/$_d" ] && continue
        umount "$IMG_MNT" 2>/dev/null
        _rofs_status "inactive missing_dir $_d"; return 1
    done
    # The FAT view first: a plain (non-recursive) bind of the card, taken
    # before the overlays exist, so it always shows the FAT copies.
    if ! mount -o bind "$SD" "$FAT_VIEW" 2>>"$LOG"; then
        umount "$IMG_MNT" 2>/dev/null
        _rofs_status "inactive fat_view_failed"; return 1
    fi
    _done=""
    for _d in $DIRS; do
        if mount -o bind "$IMG_MNT/$_d" "$SD/$_d" 2>>"$LOG"; then
            _done="$_d $_done"
        else
            for _u in $_done; do umount "$SD/$_u" 2>/dev/null; done
            umount "$FAT_VIEW" 2>/dev/null; umount "$IMG_MNT" 2>/dev/null
            _rofs_status "inactive bind_failed $_d"; return 1
        fi
    done
    # Smoke test through the overlay: a binary and a library must load (an
    # image built without exec bits once made every /mnt/bin program fail
    # with "Permission denied").
    if ! "$SD/bin/busybox" true 2>>"$LOG" || [ ! -x "$SD/bin/v4l2rtspserver" ] ||
       [ ! -r "$SD/scripts/common_functions.sh" ]; then
        for _u in $_done; do umount "$SD/$_u" 2>/dev/null; done
        umount "$FAT_VIEW" 2>/dev/null; umount "$IMG_MNT" 2>/dev/null
        _rofs_status "inactive smoke_test_failed"; return 1
    fi
    _rofs_status "active $_iv"
}

# Background integrity check of the image in use (it is read in full, ~4 s of
# CPU on this SoC, so it runs once, niced, after the boot settles).
rofs_verify()
{
    rofs_active || return 0
    _want="$(_rofs_first "$IMAGE.md5")"
    if [ -z "$_want" ]; then _rofs_log "verify: no $IMAGE.md5, skipped"; return 0; fi
    _got="$(md5sum "$IMAGE" 2>/dev/null)"; _got="${_got%% *}"
    if [ "$_got" = "$_want" ]; then
        echo "verified" > "$RUN/verified"
        _rofs_log "verify: ok $_got"
        return 0
    fi
    _rofs_log "verify: MISMATCH got=$_got want=$_want; image renamed .bad, FAT copies used from next boot"
    logger -t tc100-event -p user.err "firmware image corrupt (md5 $_got != $_want), FAT fallback at next boot" 2>/dev/null
    mv -f "$IMAGE" "$IMAGE.bad" 2>/dev/null
    echo "corrupt" > "$RUN/verified"
    sync
    return 1
}

case "${0##*/}" in
    rofs.sh)
        case "$1" in
            mount) rofs_mount ;;
            verify) rofs_verify ;;
            status) [ -r "$STATUS" ] && cat "$STATUS" || echo "inactive not_run" ;;
            *) echo "usage: $0 mount|verify|status" >&2; exit 2 ;;
        esac ;;
esac
