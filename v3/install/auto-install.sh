#!/bin/sh
# auto-install.sh   first start of 3.0 from the card: install to the flash by itself when the camera passes every
#                   check, or put the original system back when the owner asks for it with a file on the card.
#
# Run in the background by v3/autorun-linux66.sh (step 12f), in trial mode only (Linux 6.6 started from the card,
# never from the flash). From files at the root of the card:
#   (none)         right after the stock-firmware hook (tc100-3/stage1.done), on a camera whose flash still holds the
#                  system it had before 3.0: the camera is checked, then installed to the flash (install66.sh run)
#                  and restarts from it. No web page and no Wi-Fi needed. Once per card (tc100-3/auto-install.tried).
#   ESSAI.txt      (or TRIAL.txt) keep the trial mode: nothing is written ("Install to flash" of the web page later).
#   RESTAURER.txt  (or RESTORE.txt) put back the system the camera had before 3.0 from the copy the hook made
#                  (tc100-3/backup/flash-stock.bin, restore-stock.sh), then start it.
# Before the flash is written, every check must pass; any doubt: nothing is written, red LED, the reason in
# tc100-3/STATUS.txt, and the camera stays in trial mode (it works from the card, the web page can retry):
#   - the copy of the original flash is on the card, 8 MiB, matches its md5 read again now (the card kept it across
#     the restart), and its U-Boot and mac areas are this camera's (restore-stock.sh --check): the way back exists;
#   - install66.sh check: the kernel's flash layout, the package files and their md5, the board profile with the
#     sensor id and the flash chip id, the sensor tuning, the vendor libraries;
#   - the picture: the video server runs and the image processor delivers frames (/tmp/cam_luma renewed) for 30 s.
# A flash that already holds 3.0 (an xz image in "initrd": a test card booted by hand, a reinstall) is never
# written here: that is the web update's job.
C=${AI_CARD:-/mnt/sd}
K=$C/tc100-3
V=${AI_V3:-/mnt/v3}
LOG=$K/STATUS.txt
WAIT=${AI_WAIT:-30}

say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; echo "auto-install: $*" > /dev/console 2>/dev/null; sync; }
led() { [ -w /sys/class/leds/$1/brightness ] && echo $2 > /sys/class/leds/$1/brightness; } 2>/dev/null
BLINK=/tmp/auto-install.blink
blink_start() { : > $BLINK; ( while [ -f $BLINK ]; do led blue_led 1; sleep 1; led blue_led 0; sleep 1; done ) </dev/null >/dev/null 2>&1 & }
blink_stop() { rm -f $BLINK; sleep 2; }
stop() { say "NOT INSTALLED: $*"; say "Nothing was written to the flash: the camera stays in trial mode (from the card); the web page, Settings -> Update & backup -> Install to flash, can try again."
	blink_stop; led blue_led 0; led red_led 1; exit 1; }
card_file() { for f in "$@"; do [ -e "$C/$f" ] && { echo "$f"; return 0; }; done; return 1; }
find_mtd() { for d in /sys/class/mtd/mtd[0-9]*; do case $d in *ro) continue;; esac; [ "$(cat $d/name)" = "$1" ] && { echo "${d##*/}"; return 0; }; done; return 1; }
# 3.0 in the flash already: U-Boot's flashcheck looks for the same xz magic at the start of "initrd"
flash_has_30() { m=$(find_mtd initrd) && [ "$(dd if=/dev/${m}ro bs=6 count=1 2>/dev/null | od -An -tx1 | awk '{ for (i = 1; i <= NF; i++) h = h $i } END { print h }')" = fd377a585a00 ]; }

# "auto-install.sh pending": exits 0 when this start will install or restore (autorun keeps the chime for the end)
first_install() { [ -f "$K/stage1.done" ] && ! flash_has_30 && [ ! -e "$K/auto-install.tried" ]; }

[ -f /tmp/linux66 ] && [ ! -f /tmp/flashmode ] || exit 1
grep -q " $C vfat " /proc/mounts || exit 1
if [ "$1" = pending ]; then
	card_file RESTAURER.txt RESTORE.txt >/dev/null && exit 0
	card_file ESSAI.txt TRIAL.txt >/dev/null && exit 1
	first_install; exit
fi
mkdir -p "$K"

# the way back, asked for by the owner
if r=$(card_file RESTAURER.txt RESTORE.txt); then
	mv -f "$C/$r" "$C/${r%.txt}.done"; sync		# once, even if the camera restarts in the middle
	say "$r found: putting back the system the camera had before 3.0 (about 10 minutes, do not unplug)"
	blink_start
	if sh $V/install/restore-stock.sh >> "$LOG" 2>&1; then
		mv -f "$C/tc100test/c66.img" "$C/tc100test/c66.img.off" 2>/dev/null
		for f in stage1.done auto-install.tried; do [ -e "$K/$f" ] && mv -f "$K/$f" "$K/$f.restored"; done
		sync
		say "RESTORED: restarting into the system the camera had before 3.0. Take the card out (or rename its wifitest folder): with it, the stock firmware runs the card's install hook again instead of its app."
		blink_stop; led blue_led 1; sleep 2; reboot
	else
		say "RESTORE FAILED (see above): the card still starts 3.0; the copy is tc100-3/backup/flash-stock.bin"
		blink_stop; led red_led 1
	fi
	exit 0
fi

first_install || exit 0	# not a card fresh from the stock-firmware hook, 3.0 already in the flash, or tried once
if t=$(card_file ESSAI.txt TRIAL.txt); then
	say "$t found: trial mode kept, nothing written to the flash. To install: Settings -> Update & backup -> Install to flash, or remove $t and restart."
	: > "$K/auto-install.tried"; sync
	exit 0
fi

say "3.0 install, step 2 (from the card): checking the camera before writing to the flash"
blink_start
date > "$K/auto-install.tried"; sync
r=$(sh $V/install/restore-stock.sh --check 2>&1) || stop "the copy of the original flash cannot be used as the way back: $r"
say "way back: $r"
r=$(sh $V/install/install66.sh check 2>&1) || stop "$r"
mark=/tmp/auto-install.mark; : > $mark
sleep "$WAIT"
pidof tc100_rtsp >/dev/null || stop "the video server is not running (no picture: see the Logs page)"
[ -n "$(find /tmp/cam_luma -newer $mark 2>/dev/null)" ] || stop "the image processor sends no picture"
rm -f $mark
say "all checks passed: installing to the flash (about 10 minutes, do not unplug; progress in tc100-3/install66.log)"
sh $V/install/install66.sh run >> "$LOG" 2>&1	# restarts from the flash at the end
say "INSTALL FAILED (tc100-3/install66.log). The card still starts the camera (trial mode); U-Boot, its environment and mac were not written. Retry from the web page, or RESTAURER.txt on the card puts back the original system."
blink_stop; led blue_led 0; led red_led 1
exit 1
