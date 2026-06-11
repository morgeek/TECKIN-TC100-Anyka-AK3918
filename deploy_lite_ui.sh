#!/bin/bash
# Deployment Script for Elite Lite UI
# Usage: CAM_HOST=192.168.1.24 CAM_PASS=secret ./deploy_lite_ui.sh

HOST="${CAM_HOST:-192.168.1.24}"
USER="${CAM_USER:-root}"
PASS="${CAM_PASS:-}"
REMOTE_PATH="/mnt/www"

if [ -z "$PASS" ]; then
    echo "❌ Set CAM_PASS (and optionally CAM_HOST/CAM_USER) before running." >&2
    exit 1
fi

echo "🚀 Starting Deployment to $HOST..."

# Upload new/modified files
echo "📡 Uploading index.html..."
curl -u $USER:$PASS -T www/index.html ftp://$HOST$REMOTE_PATH/index.html

echo "📡 Uploading lite-ui.css..."
curl -u $USER:$PASS -T www/css/lite-ui.css ftp://$HOST$REMOTE_PATH/css/lite-ui.css

# Cleanup legacy files
echo "🧹 Cleaning up legacy files..."
FILES_TO_DELETE=(
    "css/bulma.1.0.2.min.css"
    "css/ui-modern.min.css"
    "css/ui-modern.css"
    "css/bulma-badge.1.0.1.min.css"
    "css/bulma-divider.min.css"
    "css/bulma-quickview.1.0.1.min.css"
    "css/bulma-switch.1.0.1.min.css"
)

for file in "${FILES_TO_DELETE[@]}"; do
    echo "  - Removing $file..."
    curl -u $USER:$PASS -X "DELE $REMOTE_PATH/$file" ftp://$HOST/ > /dev/null 2>&1
done

echo "✅ Deployment Complete!"
