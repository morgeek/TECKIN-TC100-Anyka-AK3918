#!/bin/sh
# Shrink a /usr/tc100 staging directory (src/flash/stage-tc100.sh) before it
# becomes a code package or a system image: the flash code zone is 640 KB.
#
#   shell scripts and CGIs   comments and indentation removed by shfmt -mn
#                            (a real parser: here-documents, quotes and
#                            strings are kept as they are)
#   www/**/*.js, *.css       minified by esbuild
#
# Measured on 2.1.6: code zone 487 KB -> about 410 KB.
# Every file is checked after the change; a file that fails keeps its
# original content.
#
# Shell scripts are only minified when CAMERA_SH is set: the camera's own
# shell, e.g. the vendor busybox 1.24.1 ash of the rootfs run with qemu:
#   CAMERA_SH="qemu-arm -L <rootfs> <rootfs>/bin/busybox sh"
# That old ash misparses some files depending on where its 8 KB read buffer
# ends: with the spaces gone, ";th|en" split across a buffer boundary made the
# minified autorun.sh unparsable, and a camera booted without network (2.1.7
# test, 2026-10-18; it rolled back by itself). A newer busybox on the build
# host accepts those files, so only the camera's shell is a valid check.
# node --check validates the minified web scripts.
# config/ (the .dist templates users read) is left alone.
# Without the tools nothing changes (a message says so): the staged tree stays
# the readable source.
#
# Tools (pinned versions used for the releases):
#   SHFMT=shfmt (mvdan/sh v3.8.0)   ESBUILD=esbuild (npm esbuild 0.23.1)
#
# Usage: src/flash/minify.sh <staging-dir>
set -u
dir=$1
SHFMT=${SHFMT:-shfmt}
ESBUILD=${ESBUILD:-esbuild}
if command -v busybox >/dev/null 2>&1; then SHCHECK="busybox sh -n"; else SHCHECK="sh -n"; fi
tmp=$(mktemp); trap 'rm -f "$tmp" "$tmp.2" "$tmp.js"' EXIT
before=$(du -sk "$dir" | cut -f1)
sh_n=0; sh_kept=0; js_n=0; js_kept=0

if [ -z "${CAMERA_SH:-}" ]; then
  echo "minify: CAMERA_SH not set, shell scripts left as they are" >&2
elif command -v "$SHFMT" >/dev/null 2>&1; then
  for f in $(find "$dir/autorun.sh" "$dir/scripts" "$dir/controlscripts" "$dir/config/autostart" "$dir/www/cgi-bin" -type f 2>/dev/null); do
    case "$f" in *.sh|*.cgi|*/autorun.sh) ;; *) head -c 12 "$f" | grep -q '^#!/bin/' || continue ;; esac
    # POSIX first; busybox ash also has ${v//a/b}, which needs the bash parser.
    if "$SHFMT" -ln posix -mn "$f" > "$tmp" 2>/dev/null || "$SHFMT" -ln bash -mn "$f" > "$tmp" 2>/dev/null; then
      # keep the interpreter line (shfmt drops it with the comments)
      if head -n 1 "$f" | grep -q '^#!' && ! head -n 1 "$tmp" | grep -q '^#!'; then
        { head -n 1 "$f"; cat "$tmp"; } > "$tmp.2" && mv "$tmp.2" "$tmp"
      fi
      if $SHCHECK "$tmp" 2>/dev/null && $CAMERA_SH -n "$tmp" >/dev/null 2>&1; then
        cat "$tmp" > "$f"; sh_n=$((sh_n + 1)); continue
      fi
    fi
    sh_kept=$((sh_kept + 1))
  done
else
  echo "minify: $SHFMT not found, shell scripts left as they are" >&2
fi

if command -v "$ESBUILD" >/dev/null 2>&1; then
  for f in $(find "$dir/www" -type f \( -name '*.js' -o -name '*.css' \) 2>/dev/null); do
    case "$f" in *.min.css) continue ;; esac     # already minified upstream (bulma)
    if "$ESBUILD" --minify --log-level=error "$f" > "$tmp" 2>/dev/null && [ -s "$tmp" ]; then
      case "$f" in
        *.js) cp "$tmp" "$tmp.js"   # node --check wants a .js name
              if command -v node >/dev/null 2>&1 && ! node --check "$tmp.js" >/dev/null 2>&1; then js_kept=$((js_kept + 1)); continue; fi ;;
      esac
      cat "$tmp" > "$f"; js_n=$((js_n + 1))
    else
      js_kept=$((js_kept + 1))
    fi
  done
else
  echo "minify: $ESBUILD not found, web scripts left as they are" >&2
fi
echo "minify: $sh_n shell files ($sh_kept kept), $js_n js/css files ($js_kept kept), ${before} KB -> $(du -sk "$dir" | cut -f1) KB"
