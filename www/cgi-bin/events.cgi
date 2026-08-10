#!/bin/sh
# events.cgi — returns recent structured events as a JSON array.
# GET /cgi-bin/events.cgi?limit=50
# Response: JSON array of event objects from /tmp/events.jsonl

. /mnt/www/cgi-bin/func.cgi
rate_limit_check 10 60

echo "Content-type: application/json"
echo "Pragma: no-cache"
echo "Cache-Control: no-store, no-cache"
echo ""

. /mnt/scripts/event-logger.sh

limit="${F_limit:-50}"
case "$limit" in ''|*[!0-9]*) limit=50 ;; esac
[ "$limit" -gt 200 ] && limit=200

get_recent_events "$limit"
