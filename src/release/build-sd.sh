#!/bin/sh
# Build the content of a new SD card: everything the camera needs at the card
# root, ready to copy onto a freshly formatted FAT32 card.
#
#   wifitest/wifi_test.sh   boot hook: the vendor /usr/sbin/service.sh sees
#                           /mnt/wifitest, skips the cloud app and runs it;
#                           it starts /mnt/autorun.sh
#   the git-tracked payload (as in an update package) + firmware.sqfs
#   SD-CARD.txt             how to format the card and bring the settings over
#
# No live configuration is included: the camera creates it from the *.dist
# templates at first boot (wizard), or it comes from a config backup.
#
# Usage: src/release/build-sd.sh [output-dir]
# Default: dist/tc100-sd-<VERSION>/ and dist/tc100-sd-<VERSION>.zip (if zip exists)
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
ver=$(cat VERSION)
out=${1:-dist/tc100-sd-$ver}
case "$out" in /*) ;; *) out="$root/$out" ;; esac
rm -rf "$out"
mkdir -p "$out"
git ls-files -- autorun.sh VERSION README.md wpa_supplicant.conf.dist wifitest \
    bin lib www scripts controlscripts config sounds |
while IFS= read -r f; do
  mkdir -p "$out/$(dirname "$f")"
  cp -p "$f" "$out/$f"
done
mkdir -p "$out/log"
if command -v mksquashfs >/dev/null 2>&1; then
  sh src/release/build-image.sh "$out" >/dev/null
else
  echo "note: mksquashfs missing, no firmware.sqfs (the camera runs from the copied files)" >&2
fi

# Safety checks. These names at the card root make the vendor boot reflash
# the camera (U-Boot / update_check.sh).
for n in uimage uImage root.sqsh4 usr.sqsh4 usr.jffs2 update usbnet agingtest; do
  [ ! -e "$out/$n" ] || { echo "error: $n must not be on the card root" >&2; exit 1; }
done
[ -x "$out/wifitest/wifi_test.sh" ] || { echo "error: no boot hook" >&2; exit 1; }
for s in config/mqtt.conf config/user.pwd config/lighttpd.pem wpa_supplicant.conf; do
  [ ! -e "$out/$s" ] || { echo "error: live config $s in the kit" >&2; exit 1; }
done

cat > "$out/SD-CARD.txt" <<TXT
TC100 firmware $ver - content of a new SD card

1. Format the card: FAT32, MBR partition table, 32 KB clusters.
   macOS (replace diskN, check it with "diskutil list" first):
     diskutil eraseDisk FAT32 TC100 MBRFormat /dev/diskN
     diskutil unmountDisk /dev/diskN
     sudo newfs_msdos -F 32 -c 64 -v TC100 /dev/rdiskNs1
   Windows: format as FAT32, allocation unit 32 KB (cards over 32 GB need
   a third-party tool, or use a 8-32 GB card).
2. Copy everything in this folder to the card root (wifitest/ included).
   On macOS, then run: dot_clean -m /Volumes/TC100   (removes the ._ files)
3. Settings from the old card (pick one):
   a. before the swap, Settings > Backup > download the configuration backup,
      and after the first boot of the new card restore it from the same tab;
   b. or copy the old card's config/ folder onto the new card (replace).
   Wi-Fi: the camera keeps using the network stored in its flash memory, no
   file needed (only create wpa_supplicant.conf from wpa_supplicant.conf.dist
   if you want to set it from the card).
4. Insert the card, power on, open https://CAMERA-IP (root / pass on a new
   configuration: change them in the wizard).

Never put files named uimage, root.sqsh4, usr.sqsh4 or usr.jffs2 on the card
root: the camera would try to reflash itself.
TXT

if command -v zip >/dev/null 2>&1; then
  rm -f "$out.zip"
  (cd "$out" && zip -qr -X "$out.zip" .)
  echo "$out.zip: $(wc -c < "$out.zip") bytes"
fi
echo "$out: version $ver, $(find "$out" -type f | wc -l) files"
