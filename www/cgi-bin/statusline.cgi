#!/bin/sh

# The status line, polled by every open page (a few times a minute): the same JSON as state.cgi?cmd=statusline,
# without parsing state.cgi (1500 lines) and func.cgi (450 lines, time zone, query parsing) on every request.
# It sources only statelib.cgi, which state.cgi sources too (so `cmd=statusline` of state.cgi stays identical).
# Like state.cgi it takes no parameter, has no rate limit and no CSRF check (the web server does the
# authentication, the response carries the CSRF token the page needs for its POSTs).

. /mnt/www/cgi-bin/statelib.cgi

echo "Content-type: application/json"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

statusline_json

exit 0
