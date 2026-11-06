#!/bin/sh
# Build www/css/ui.pico.min.css (Pico CSS + pico-shim.css + ui.css in one file, the sheet of index.html) and
# stamp its ?v= in www/index.html. The regression tests run --check: edit the sources, run this, commit all.
#   src/webui/build-css.sh [--check]
set -eu
exec node "$(dirname "$0")/build-css.mjs" "$@"
