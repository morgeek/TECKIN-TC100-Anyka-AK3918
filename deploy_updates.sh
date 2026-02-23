#!/bin/bash
# Deployment script for ISP Pro Mode and Sound Detection updates
# Usage: ./deploy_updates.sh [CAMERA_IP]

HOST="${1:-192.168.1.77}"
PORT="2121"
USER="root"
PASS="pass"

echo "=== Deploying Updates to $HOST:$PORT ==="

BASE="ftp://$USER:$PASS@$HOST:$PORT/mnt"

# List of files to push: [local_path] [remote_path]
FILES=(
    "www/cgi-bin/status.cgi" "www/cgi-bin/status.cgi"
    "www/cgi-bin/action.cgi" "www/cgi-bin/action.cgi"
    "www/scripts/status.cgi.js" "www/scripts/status.cgi.js"
    "controlscripts/sound-detection" "controlscripts/sound-detection"
    "scripts/common_functions.sh" "scripts/common_functions.sh"
    "config/autostart/00_system-config" "config/autostart/00_system-config"
)

for ((i=0; i<${#FILES[@]}; i+=2)); do
    LOCAL="${FILES[$i]}"
    REMOTE="${FILES[$i+1]}"
    echo "Pushing $LOCAL -> $REMOTE..."
    curl -T "$LOCAL" "$BASE/$REMOTE" || echo "Failed to push $LOCAL"
done

echo ""
echo "=== Finalizing ==="
echo "Note: Some changes like Sound Detection daemon and shared functions require a reboot."
echo "You can reboot via the Web UI or run: curl \"http://$HOST/cgi-bin/action.cgi?cmd=reboot\""
echo "=== Done ==="
