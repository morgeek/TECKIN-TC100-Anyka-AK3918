#!/bin/sh
# flash-install.sh — install the firmware into the camera's flash from the SD
# card, so that the camera runs without a card (README "Install to flash").
#
# Everything goes through the folder tc100-flash/ at the root of the card,
# in three steps:
#
#   1. On the camera (SD card with this firmware + an empty tc100-flash/):
#      "prepare" checks that the flash is the one this procedure is made for
#      and copies the camera's original /usr partition to the card
#      (usr-stock.img, camera.txt). Read-only for the flash.
#   2. On a computer: src/flash/build-flash-kit.sh <card> builds usr.img (the
#      original /usr minus the cloud app, plus this firmware) and code.bin
#      from usr-stock.img. Nothing from the camera vendor is ever published.
#   3. On the camera again: "install" (at boot, before any video service
#      runs) checks everything again, copies the settings into the flash,
#      writes /usr and the code zone, reads both back, then reboots once into
#      the flash firmware with the card still in (a test boot that puts the
#      card back in charge for the boot after). When the web page shows the
#      FLASH badge, power off, take the card out, power on.
#
# autorun.sh calls "flash-install.sh boot" after stopping the cloud app.
# Progress and errors: tc100-flash/STATUS.txt on the card.
#
#   flash-install.sh boot       prepare or install, whichever is due
#   flash-install.sh prepare    step 1 now
#   flash-install.sh install    step 3 now (refused while /usr is in use)
#   flash-install.sh status     state for the web page (one line)

CARD="${FI_CARD:-/mnt}"
K="${FI_DIR:-$CARD/tc100-flash}"
PROC_MTD="${FI_PROC_MTD:-/proc/mtd}"
MTD="${FI_MTD:-/dev/mtd}"
SCRIPTS="${FI_SCRIPTS:-/mnt/scripts}"
JFFS="${FI_JFFS:-/etc/jffs2/tc100}"
STORAGE_FILE="${TC100_STORAGE_FILE:-/tmp/tc100-storage}"
PROC="${FI_PROC:-/proc}"
USR="${FI_USR:-/usr}"
# /usr (mtd6) of TECKIN TC100 vendor firmware V1.1.41 — what build-usr.sh is
# tested on. Any other: refused unless tc100-flash/ALLOW-OTHER-USR exists.
STOCK_USR_MD5="${FI_STOCK_USR_MD5:-def1ea44addd7a73d613d8169b395447}"
MTD_TABLE='mtd0: 00800000 00001000 "spi0.0"
mtd1: 00200000 00001000 "KERNEL"
mtd2: 00001000 00001000 "MAC"
mtd3: 00001000 00001000 "ENV"
mtd4: 00180000 00001000 "A"
mtd5: 0007d000 00001000 "B"
mtd6: 003b6000 00001000 "C"'
USR_BYTES=3891200
ZONE_START=1441792            # 0x160000: the kernel must end before it

_fi_say() { echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$K/STATUS.txt"; echo "flash-install: $*"; logger -t tc100-event "flash-install: $*" 2>/dev/null; }
_fi_md5() { md5sum "$1" 2>/dev/null | cut -d' ' -f1; }
_fi_mtd_md5() { dd if="$MTD$1" bs=4096 ${2:+count=$2} 2>/dev/null | md5sum | cut -d' ' -f1; }

# Checks shared by both steps. Sets FI_WHY on failure.
fi_check_flash()
{
    FI_WHY=""
    [ "$(cat "$STORAGE_FILE" 2>/dev/null)" = flash ] && { FI_WHY="the camera is already running from flash (use Settings → Update for code updates)"; return 1; }
    [ "$(grep '^mtd' "$PROC_MTD" 2>/dev/null)" = "$MTD_TABLE" ] || { FI_WHY="the flash partitions are not the ones of a TECKIN TC100 (8 MB, 7 partitions)"; return 1; }
    # uImage header: magic 27 05 19 56, data size big-endian at offset 12.
    set -- $(dd if="${MTD}1" bs=64 count=1 2>/dev/null | od -An -tu1 -v)
    [ "$1 $2 $3 $4" = "39 5 25 86" ] || { FI_WHY="no kernel image at the start of the KERNEL partition"; return 1; }
    _ksize=$(( ${13} * 16777216 + ${14} * 65536 + ${15} * 256 + ${16} + 64 ))
    [ "$_ksize" -lt "$ZONE_START" ] || { FI_WHY="the kernel ($_ksize bytes) overlaps the code zone"; return 1; }
    # Code zone: blank, or a code package already (re-install).
    _z="$(dd if="${MTD}1" bs=4096 skip=352 count=1 2>/dev/null | head -c 11)"
    if [ "$_z" != "TC100CODE 1" ]; then
        _ff=$(dd if="${MTD}1" bs=4096 skip=352 count=160 2>/dev/null | od -An -v -tx1 | grep -v -c '^ *\(ff \)*ff *$')
        [ "$_ff" = 0 ] || { FI_WHY="the end of the KERNEL partition is not empty (unknown content: not touched)"; return 1; }
    fi
    return 0
}

fi_prepare()
{
    mkdir -p "$K"
    fi_check_flash || { _fi_say "PREPARE REFUSED: $FI_WHY"; return 1; }
    _cur="$(_fi_mtd_md5 6)"
    if [ "$_cur" != "$STOCK_USR_MD5" ] && [ ! -e "$K/ALLOW-OTHER-USR" ]; then
        if dd if="${MTD}6" bs=4096 count=1 2>/dev/null | head -c 4 | grep -q hsqs && [ -e "$USR/tc100/VERSION" ]; then
            _fi_say "PREPARE REFUSED: /usr in flash is already this firmware's; keep the usr-stock.img made the first time and run build-flash-kit.sh with it"
        else
            _fi_say "PREPARE REFUSED: /usr in flash ($_cur) is not the TC100 V1.1.41 one this procedure was tested with (create tc100-flash/ALLOW-OTHER-USR to try anyway)"
        fi
        return 1
    fi
    _fi_say "prepare: flash checked, copying the original /usr (3.7 MB)…"
    dd if="${MTD}6" of="$K/usr-stock.img.tmp" bs=4096 2>/dev/null && sync
    [ "$(_fi_md5 "$K/usr-stock.img.tmp")" = "$_cur" ] || { rm -f "$K/usr-stock.img.tmp"; _fi_say "PREPARE FAILED: the copy on the card differs from the flash (card?)"; return 1; }
    mv -f "$K/usr-stock.img.tmp" "$K/usr-stock.img"
    echo "$_cur" > "$K/usr-stock.img.md5"
    { echo "camera=TECKIN TC100"
      echo "usr_md5=$_cur"
      echo "kernel_md5=$(_fi_mtd_md5 1 352)"
      echo "rootfs_md5=$(_fi_mtd_md5 4)"
      echo "firmware=$(cat "$CARD/VERSION" 2>/dev/null)"
      echo "date=$(date '+%Y-%m-%d %H:%M' 2>/dev/null)"; } > "$K/camera.txt"
    sync
    _fi_say "prepare: DONE. Next: take the card out and run src/flash/build-flash-kit.sh on a computer (README)."
}

# Settings of the SD firmware → jffs2 (only the first time; flash mode reads
# them from there). Certificate: the flash web server needs an ECDSA one.
fi_copy_settings()
{
    [ -d "$JFFS/config" ] && { _fi_say "install: settings already in flash, kept"; return 0; }
    mkdir -p "$JFFS/config" || return 1
    for f in "$CARD"/config/* "$CARD"/config/.wizard_done; do
        [ -e "$f" ] || continue
        n="${f##*/}"
        case "$n" in *.dist|*.pre-migrate|*.expired|*.bak*|*-bak|openssl.cnf|packages.lock|ssl|.lkg|lighttpd.conf|lighttpd.http.conf) continue ;; esac
        cp -a "$f" "$JFFS/config/" || return 1
    done
    rm -f "$JFFS/config/autostart/recording"
    [ -d "$JFFS/config/autostart" ] && [ ! -e "$JFFS/config/autostart/button-actions" ] && \
        printf '#!/bin/sh\n/mnt/controlscripts/button-actions\n' > "$JFFS/config/autostart/button-actions"
    chmod 755 "$JFFS"/config/autostart/* 2>/dev/null
    export LD_LIBRARY_PATH="$CARD/lib:/lib:/usr/lib"
    # openssl has a hardcoded config path that does not exist on the camera.
    [ -f "$CARD/config/openssl.cnf" ] && export OPENSSL_CONF="$CARD/config/openssl.cnf"
    if [ -s "$JFFS/config/lighttpd.pem" ] && ! "$CARD/bin/openssl" pkey -in "$JFFS/config/lighttpd.pem" -noout -text 2>/dev/null | grep -q 'ASN1 OID'; then
        rm -f "$JFFS/config/lighttpd.pem"
    fi
    if [ ! -s "$JFFS/config/lighttpd.pem" ]; then
        "$CARD/bin/openssl" req -new -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
            -keyout "$JFFS/config/lighttpd.pem" -out "$JFFS/config/lighttpd.pem" -days 3650 -nodes \
            -subj "/C=DE/ST=Mars/L=HellasPlanitia/O=TC100/OU=camera/CN=TC100" >/dev/null 2>&1 \
            && chmod 400 "$JFFS/config/lighttpd.pem" && _fi_say "install: new ECDSA certificate for HTTPS"
    fi
    [ -f "$CARD/wpa_supplicant.conf" ] && cp "$CARD/wpa_supplicant.conf" "$JFFS/wpa_supplicant.conf" && chmod 600 "$JFFS/wpa_supplicant.conf"
    sync
    _fi_say "install: settings copied into the flash ($(du -sk "$JFFS" | cut -f1) KB)"
}

fi_install()
{
    fi_check_flash || { _fi_say "INSTALL REFUSED: $FI_WHY"; return 1; }
    for f in usr.img usr.img.md5 code.bin camera.txt; do
        [ -s "$K/$f" ] || { _fi_say "INSTALL REFUSED: tc100-flash/$f missing (run build-flash-kit.sh)"; return 1; }
    done
    _want="$(sed -n 's/^usr_md5=//p' "$K/camera.txt")"
    _cur="$(_fi_mtd_md5 6)"
    # The /usr copied by prepare, or this firmware's (a later /usr update
    # built from the same original).
    if [ "$_cur" != "$_want" ] && ! { [ -e "$USR/tc100/VERSION" ] && [ "$(cat "$K/usr-stock.img.md5" 2>/dev/null)" = "$_want" ]; }; then
        _fi_say "INSTALL REFUSED: /usr in flash ($_cur) is not the one copied by prepare ($_want): another camera's card?"; return 1
    fi
    read -r _img_md5 _rest < "$K/usr.img.md5"
    [ "$(_fi_md5 "$K/usr.img")" = "$_img_md5" ] || { _fi_say "INSTALL REFUSED: usr.img is damaged (md5)"; return 1; }
    [ "$(wc -c < "$K/usr.img")" -le "$USR_BYTES" ] || { _fi_say "INSTALL REFUSED: usr.img is too big"; return 1; }
    sh "$SCRIPTS/flash-code.sh" check "$K/code.bin" >/dev/null 2>&1 || { _fi_say "INSTALL REFUSED: code.bin is not a valid code package"; return 1; }
    # Nothing may run from /usr, or read a file in it, while it is rewritten:
    # at boot the vendor service.sh (a script in /usr/sbin) is still running
    # for a few seconds after it started this firmware, so wait for it.
    _fi_busy()
    {
        _busy=""
        for p in "$PROC"/[0-9]*; do
            [ "${p##*/}" = "$$" ] && continue
            if grep -q " $USR/" "$p/maps" 2>/dev/null || ls -l "$p/fd/" 2>/dev/null | grep -q -e "-> $USR/"; then
                _busy="$_busy $(cat "$p/comm" 2>/dev/null)"
            fi
        done
        [ -n "$_busy" ]
    }
    _w=0
    while _fi_busy && [ "$_w" -lt "${FI_BUSY_WAIT:-60}" ]; do sleep 2; _w=$((_w + 2)); done
    [ -z "$_busy" ] || { _fi_say "INSTALL REFUSED: programs use /usr:$_busy (install runs at boot)"; return 1; }
    _fi_df="$(df -k "${JFFS%/*}" 2>/dev/null | awk 'NR == 2 { print $4 }')"
    [ "${_fi_df:-0}" -ge 150 ] || [ -d "$JFFS/config" ] || { _fi_say "INSTALL REFUSED: not enough room in the settings partition (${_fi_df} KB)"; return 1; }

    _fi_say "install: checks passed, copying settings"
    # The original /usr this camera's images are built from: system packages
    # (scripts/usr-update.sh) must come from the same one.
    mkdir -p "$JFFS" && echo "$_want" > "$JFFS/usr-stock.md5"
    fi_copy_settings || { _fi_say "INSTALL FAILED: could not copy the settings (nothing written to /usr)"; return 1; }
    _fi_say "install: writing /usr (about 30 s)…"
    if ! sh "$SCRIPTS/flash-usr.sh" "$K/usr.img" "$_img_md5"; then
        _fi_say "INSTALL FAILED while writing /usr: $(tail -n 1 /tmp/flash.log 2>/dev/null). The card keeps the camera working; retry, or restore with usr-stock.img (README)."
        return 2
    fi
    _fi_say "install: /usr written and checked; writing the code zone"
    if ! _out="$(sh "$SCRIPTS/flash-code.sh" write "$K/code.bin" 2>&1)"; then
        _fi_say "INSTALL: code zone not written ($_out); the camera will use the code in /usr"
    fi
    mv -f "$K/usr.img" "$K/usr.img.installed"
    # Test boot from flash with the card still in (scripts/flashmode-once.sh).
    cp "$SCRIPTS/flashmode-once.sh" "$JFFS/boot.sh" && chmod 755 "$JFFS/boot.sh"
    [ -d "$CARD/wifitest" ] && mv "$CARD/wifitest" "$CARD/wifitest.off"
    sync
    _fi_say "install: DONE — rebooting into the flash firmware for a test. When the web page shows the FLASH badge: power off, take the card out, power on."
    [ -n "$FI_NO_REBOOT" ] && return 0
    reboot
    sleep 60
}

fi_status()
{
    if [ "$(cat "$STORAGE_FILE" 2>/dev/null)" = flash ]; then echo "flash"
    elif [ ! -d "$K" ]; then echo "none"
    elif [ -s "$K/usr.img" ]; then echo "ready"
    elif [ -s "$K/usr.img.installed" ]; then echo "installed"
    elif [ -s "$K/usr-stock.img" ]; then echo "prepared"
    else echo "empty"; fi
}

fi_boot()
{
    [ -d "$K" ] || return 0
    case "$(fi_status)" in
        empty) fi_prepare ;;
        ready) fi_install ;;
        installed)
            # Back on the card after the test boot: report how it went.
            if grep -q "confirmed" "$JFFS/log/code-updates.log" 2>/dev/null; then
                [ -e "$K/.reported" ] || { _fi_say "the test boot from flash worked: power off, take the card out, power on"; : > "$K/.reported"; }
            fi ;;
    esac
}

case "${0##*/}" in
    flash-install.sh)
        case "$1" in
            boot) fi_boot ;;
            prepare) fi_prepare ;;
            install) fi_install ;;
            status) fi_status ;;
            *) echo "usage: $0 boot | prepare | install | status" >&2; exit 2 ;;
        esac ;;
esac
