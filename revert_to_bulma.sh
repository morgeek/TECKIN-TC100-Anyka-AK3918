#!/bin/bash
# Restoration Script: Revert to Bulma Build
# Usage: CAM_HOST=192.168.1.24 CAM_PASS=secret ./revert_to_bulma.sh

HOST="${CAM_HOST:-192.168.1.24}"
USER="${CAM_USER:-root}"
PASS="${CAM_PASS:-}"
REMOTE_PATH="/mnt/www"

if [ -z "$PASS" ]; then
    echo "❌ Set CAM_PASS (and optionally CAM_HOST/CAM_USER) before running." >&2
    exit 1
fi

echo "⏪ Starting Reversion to Bulma build on $HOST..."

# Upload original index.html
echo "📡 Restoring index.html..."
curl -u $USER:$PASS -T www/index.html ftp://$HOST$REMOTE_PATH/index.html

# Upload original CSS files
echo "📡 Restoring Bulma & Modern CSS files..."
FILES_TO_RESTORE=(
    "css/bulma.1.0.2.min.css"
    "css/ui-modern.min.css"
    "css/ui-modern.css"
    "css/bulma-badge.1.0.1.min.css"
    "css/bulma-divider.min.css"
    "css/bulma-quickview.1.0.1.min.css"
    "css/bulma-switch.1.0.1.min.css"
)

for file in "${FILES_TO_RESTORE[@]}"; do
    echo "  + Restoring $file..."
    curl -u $USER:$PASS -T "www/$file" ftp://$HOST$REMOTE_PATH/$file
done

# Cleanup the modernization attempt
echo "🧹 Removing lite-ui attempt..."
curl -u $USER:$PASS -X "DELE $REMOTE_PATH/css/lite-ui.css" ftp://$HOST/ > /dev/null 2>&1

echo "✅ Restoration Complete. Bulma build is back!"
