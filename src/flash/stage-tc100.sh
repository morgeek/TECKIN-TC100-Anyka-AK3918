#!/bin/sh
# Assemble /usr/tc100 for the flash /usr image (src/flash/build-usr.sh) from
# the firmware in this repository, as installed on the cameras:
#   bin, lib       minus TLS (openssl, libssl, libcrypto), libcurl (curl is
#                  static), libjq/libiconv (unused: jq is static), ONVIF
#                  (monvifd), internet-only or SD-only tools (telegram,
#                  ffmpeg-min-recorder, min-recorder-list); curl replaced by
#                  the HTTP-only build, lighttpd by the mbedTLS one (no PCRE)
#   code           autorun.sh VERSION scripts controlscripts www sounds config
#                  (config without ssl/)
#
# Usage: src/flash/stage-tc100.sh <out-dir> [<curl-notls> <lighttpd>]
#   Without arguments (the normal case, also on a computer without the camera
#   toolchain), the stripped binaries in src/flash/prebuilt/ are used: the
#   exact files running on the cameras (src/flash/update-prebuilt.sh makes
#   them). With STRIP=<arm strip> and the two binaries, everything is
#   stripped here instead (developers rebuilding curl or lighttpd).
# Works from a git checkout or from an unpacked source archive.
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
out=$1
pre="$root/src/flash/prebuilt"
rm -rf "$out"; mkdir -p "$out"
cd "$root"
list() {
  if git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files -- autorun.sh VERSION bin lib scripts controlscripts www sounds config
  else
    find autorun.sh VERSION bin lib scripts controlscripts www sounds config -type f | sed 's#^\./##'
  fi
}
list |
  grep -v -E '^config/ssl/|^bin/(openssl|monvifd|telegram|jq|ffmpeg-min-recorder|min-recorder-list|curl|lighttpd)$|^lib/(libssl|libcrypto|libcurl|libjq|libiconv|libpcre2)' |
while IFS= read -r f; do
  mkdir -p "$out/$(dirname "$f")"; cp -p "$f" "$out/$f"
done
if [ $# -ge 3 ]; then
  : "${STRIP:?set STRIP to the arm-anykav200-linux-uclibcgnueabi-strip path}"
  cp "$2" "$out/bin/curl"; cp "$3" "$out/bin/lighttpd"
  for f in "$out"/bin/* "$out"/lib/*; do
    file -b "$f" | grep -q ELF && "$STRIP" --strip-unneeded "$f"
  done
else
  # Stripped copies (debug symbols take ~1 MB the flash does not have).
  for f in "$pre"/*; do
    case "${f##*/}" in lib*) cp "$f" "$out/lib/${f##*/}" ;; *) cp "$f" "$out/bin/${f##*/}" ;; esac
  done
fi
# autorun.sh runs autostart entries directly: they must be executable (on the
# SD card FAT makes every file executable, in a squashfs only the mode counts).
chmod -R 755 "$out/bin" "$out/lib" "$out/scripts" "$out/controlscripts" "$out/autorun.sh" "$out/config/autostart"
echo "$out: $(find "$out" -type f | wc -l | tr -d ' ') files, $(du -sk "$out" | cut -f1) KB"
