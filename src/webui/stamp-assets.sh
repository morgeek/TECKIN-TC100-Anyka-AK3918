#!/bin/sh
# Stamp the ?v= of the scripts and style sheets the pages load with the first 8 hex digits of each file's md5, so that
# a browser never keeps an old copy after a firmware update. busybox httpd sends ETag and the .gz copies
# (FEATURE_HTTPD_ETAG / GZIP) but no Cache-Control; up to the rc31 it also sent Last-Modified, with which a browser
# reused a cached file for hours by heuristic (a new fr.js unseen behind "?v=2.1.2-i18n1"; index.html after the rc31
# update, R22). Since R22 there is no Last-Modified: pages are revalidated by ETag, and the stamps change the URLs.
#   src/webui/stamp-assets.sh [--check]
# Covers www/*.html, www/cgi-bin/wizard.cgi and www/cgi-bin/scripts.cgi (every "<path>.js?v=" / "<path>.css?v=" of a file under www/), and the
# French dictionary in www/scripts/i18n.js (it loads i18n/fr.js?v=VERSION). css/ui.pico.min.css keeps the stamp
# that src/webui/build-css.sh gives it. src/webui/build-index.sh runs this after building the bundle; the tests run
# --check: edit, build, stamp, commit all.
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
check=0; [ "${1:-}" = --check ] && check=1
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
stale=0
stamp() { md5sum < "$1" | cut -c1-8; }

# put NEW in place of OLD (or, with --check, report OLD as stale when they differ)
settle() {
  if cmp -s "$1" "$2"; then return 0; fi
  if [ $check = 1 ]; then echo "stale stamp: ${2#"$root"/}" >&2; stale=1; else cp "$1" "$2"; fi
}

# 1. the dictionary version inside i18n.js (stamped first: the pages stamp the new i18n.js)
mkdir -p "$tmp/www/scripts"
sed "s/^  var VERSION = \"[^\"]*\";/  var VERSION = \"$(stamp "$root/www/i18n/fr.js")\";/" "$root/www/scripts/i18n.js" \
  > "$tmp/www/scripts/i18n.js"

# 2. every versioned asset reference of the pages
for page in "$root"/www/*.html "$root/www/cgi-bin/wizard.cgi" "$root/www/cgi-bin/scripts.cgi"; do
  cp "$page" "$tmp/page"
  for ref in $(grep -o -E '[A-Za-z0-9_./-]+\.(js|css)\?v=[A-Za-z0-9._-]*' "$page" | sort -u); do
    path=${ref%%\?v=*}; rel=${path#/}
    case "$rel" in css/ui.pico.min.css) continue ;; esac
    if [ -f "$tmp/www/$rel" ]; then file="$tmp/www/$rel"; elif [ -f "$root/www/$rel" ]; then file="$root/www/$rel"; else continue; fi
    esc=$(printf '%s' "$path" | sed 's/[.[\*^$/]/\\&/g')
    sed "s/$esc?v=[A-Za-z0-9._-]*/$(printf '%s' "$path" | sed 's/[\/&]/\\&/g')?v=$(stamp "$file")/g" "$tmp/page" > "$tmp/page.new"
    mv "$tmp/page.new" "$tmp/page"
  done
  settle "$tmp/page" "$page"
done
settle "$tmp/www/scripts/i18n.js" "$root/www/scripts/i18n.js"
[ $stale = 0 ] || { echo "run src/webui/stamp-assets.sh" >&2; exit 1; }
