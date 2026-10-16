#!/bin/sh
# Step 2 of the install to flash (README "Install to flash"): on a computer,
# turn the original /usr copied by the camera (tc100-flash/usr-stock.img on
# the SD card, step 1) into the images the camera installs at its next boot
# (step 3):
#   tc100-flash/usr.img (+ .md5)   the original /usr minus the cloud app,
#                                  plus this firmware (src/flash/build-usr.sh)
#   tc100-flash/code.bin           this firmware's code for the code zone
#   tc100-flash/tc100-system-<v>.tar  both, for a camera already running
#                                  from flash (Settings → Update & backup)
#
# Needs: squashfs-tools with xz (unsquashfs, mksquashfs), python3.
#   Debian/Ubuntu/WSL: sudo apt install squashfs-tools python3
#   macOS:             brew install squashfs
# Run from this repository (git clone or the source archive of a release):
#   src/flash/build-flash-kit.sh /path/to/the/sd/card
# Nothing is sent anywhere; the vendor files stay on your card and computer.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
[ $# -eq 1 ] || { echo "usage: $0 <sd-card mount point>" >&2; exit 2; }
K="$1/tc100-flash"
md5of() { (md5sum "$1" 2>/dev/null || md5 -r "$1") | cut -d' ' -f1; }
die() { echo "error: $*" >&2; exit 1; }

for t in unsquashfs mksquashfs python3; do
  command -v "$t" >/dev/null 2>&1 || die "$t is missing (see the top of this script)"
done
[ -s "$K/usr-stock.img" ] && [ -s "$K/camera.txt" ] || \
  die "no $K/usr-stock.img: put the card in the camera first (step 1 copies it)"
want=$(sed -n 's/^usr_md5=//p' "$K/camera.txt")
[ "$(md5of "$K/usr-stock.img")" = "$want" ] || die "usr-stock.img does not match camera.txt (copy damaged?)"

W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
echo "1/4 extracting the camera's original /usr"
unsquashfs -n -no-xattrs -d "$W/vendor" "$K/usr-stock.img" >/dev/null 2>&1 || \
  unsquashfs -no-xattrs -d "$W/vendor" "$K/usr-stock.img" >/dev/null || die "unsquashfs failed (xz support?)"
echo "2/4 assembling the firmware"
sh "$here/stage-tc100.sh" "$W/tc100" >/dev/null
echo "3/4 building usr.img"
VENDOR_WPA=wrapper sh "$here/build-usr.sh" "$W/vendor" "$W/tc100" "$W/usr.img"
echo "4/4 building code.bin"
sh "$here/build-code.sh" "$W/tc100" "$W/code.bin"
cp "$W/usr.img" "$K/usr.img.tmp" && mv -f "$K/usr.img.tmp" "$K/usr.img"
echo "$(md5of "$K/usr.img")  usr.img" > "$K/usr.img.md5"
cp "$W/code.bin" "$K/code.bin"
rm -f "$K/usr.img.installed" "$K/.reported"
# The same /usr and code as one file, for a camera that already runs from
# flash: Settings → Update & backup takes it without the card.
ver=$(head -n 1 "$root/VERSION")
rm -f "$K"/tc100-system-*.tar
cp "$root/VERSION" "$W/VERSION"; cp "$K/camera.txt" "$W/camera.txt"; cp "$K/usr.img.md5" "$W/usr.img.md5"
(cd "$W" && COPYFILE_DISABLE=1 tar -cf "$K/tc100-system-$ver.tar" usr.img usr.img.md5 code.bin camera.txt VERSION)
sync
echo
echo "Ready: $K/usr.img and code.bin ($(cat "$root/VERSION"))."
echo "Eject the card, put it back in the camera and power it on: it installs"
echo "itself (about 1 minute), restarts from its flash, and shows the FLASH badge"
echo "in its web page. Then power it off, take the card out, power it on."
echo
echo "Already running from flash? Upload $K/tc100-system-$ver.tar"
echo "in Settings > Update & backup instead (no card needed)."
