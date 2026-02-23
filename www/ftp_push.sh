#!/bin/bash
HOST="192.168.1.77"
PORT="2121"
USER="root"
PASS="pass"

echo "=== Pushing files via curl to $HOST:$PORT ==="

BASE="ftp://$USER:$PASS@$HOST:$PORT/mnt/www"

curl -T index.html "$BASE/index.html"
curl -T css/ui-modern.css "$BASE/css/ui-modern.css"
curl -T scripts/index.html.js "$BASE/scripts/index.html.js"
curl -T scripts/index.bundle.min.js "$BASE/scripts/index.bundle.min.js"

echo "=== Done ==="
