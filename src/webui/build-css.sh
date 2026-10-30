#!/bin/sh
# Build www/css/ui.bundle.min.css (bulma purged + ui-modern + ui.css in one file, as index.html loaded them) and
# stamp its ?v= in www/index.html. The regression tests run --check: edit the sources, run this, commit all.
#   src/webui/build-css.sh [--check]
set -eu
exec node "$(dirname "$0")/build-css.mjs" "$@"
