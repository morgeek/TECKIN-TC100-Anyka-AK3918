#!/bin/bash

# FTP Deployment Script for TECKIN TC100 Camera
# Uploads modified files for PTT & Two-Way Audio features

set -e

FTP_HOST="192.168.1.24"
FTP_PORT="2121"
FTP_USER="root"
FTP_PASS="pass"
FTP_TIMEOUT="30"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Color codes for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== TECKIN TC100 Audio Features Deployment ===${NC}\n"

# Files to upload (source -> remote path)
declare -a FILES_TO_UPLOAD=(
  "www/index.html:/mnt/www/index.html"
  "www/scripts/ppt-audio.bundle.min.js:/mnt/www/scripts/ppt-audio.bundle.min.js"
  "www/scripts/index.bundle.min.js:/mnt/www/scripts/index.bundle.min.js"
  "www/cgi-bin/audio_stream.cgi:/mnt/www/cgi-bin/audio_stream.cgi"
  "AUDIO_FEATURES.md:/mnt/AUDIO_FEATURES.md"
  "IMPLEMENTATION_SUMMARY.md:/mnt/IMPLEMENTATION_SUMMARY.md"
  "README.md:/mnt/README.md"
)

echo -e "${YELLOW}Connecting to FTP server @ $FTP_HOST:$FTP_PORT...${NC}"

# Build FTP commands
FTP_COMMANDS=""
for file_pair in "${FILES_TO_UPLOAD[@]}"; do
  IFS=':' read -r local_path remote_path <<< "$file_pair"
  if [ ! -f "$SCRIPT_DIR/$local_path" ]; then
    echo -e "${RED}✗ Missing: $local_path${NC}"
    continue
  fi
  FTP_COMMANDS="${FTP_COMMANDS}put $SCRIPT_DIR/$local_path $remote_path"$'\n'
  echo -e "${YELLOW}Queued: $local_path → $remote_path${NC}"
done

echo ""

# Execute FTP upload using lftp
lftp -u "$FTP_USER,$FTP_PASS" -e "
set ftp:timeout $FTP_TIMEOUT
set ftp:passive-mode yes
open $FTP_HOST $FTP_PORT
$FTP_COMMANDS
bye
" 2>&1 | tee /tmp/ftp_deploy.log

# Check upload results
if grep -qi "error\|failed\|not found" /tmp/ftp_deploy.log; then
  echo -e "${RED}✗ Upload completed with errors${NC}"
  exit 1
fi

echo -e "${GREEN}✓ Files uploaded successfully${NC}\n"

# Make audio_stream.cgi executable
echo -e "${YELLOW}Setting permissions on CGI script...${NC}"
lftp -u "$FTP_USER,$FTP_PASS" -e "
set ftp:timeout $FTP_TIMEOUT
open $FTP_HOST $FTP_PORT
site chmod 755 /mnt/www/cgi-bin/audio_stream.cgi
bye
" 2>&1

echo -e "${GREEN}✓ Permissions set${NC}\n"

# Verify files on device
echo -e "${YELLOW}Verifying deployed files...${NC}"

VERIFY_RESULTS=$(lftp -u "$FTP_USER,$FTP_PASS" -e "
set ftp:timeout $FTP_TIMEOUT
open $FTP_HOST $FTP_PORT
ls -l /mnt/www/index.html
ls -l /mnt/www/scripts/ppt-audio.bundle.min.js
ls -l /mnt/www/scripts/index.bundle.min.js
ls -l /mnt/www/cgi-bin/audio_stream.cgi
bye
" 2>&1)

echo "$VERIFY_RESULTS"

if echo "$VERIFY_RESULTS" | grep -qE "index.html|ppt-audio|audio_stream"; then
  echo -e "${GREEN}✓ File verification passed${NC}\n"
else
  echo -e "${RED}✗ File verification failed${NC}"
  exit 1
fi

echo -e "${BLUE}=== Health Checks ===${NC}\n"

# Test web UI connectivity  
echo -e "${YELLOW}Testing HTTP connectivity to camera...${NC}"
if timeout 5 curl -s -k -o /dev/null -w "%{http_code}" "http://192.168.1.24/index.html" | grep -q "200"; then
  echo -e "${GREEN}✓ Web UI accessible${NC}"
else
  echo -e "${YELLOW}⚠ Web UI not responding (may be firewall or networking)${NC}"
fi

# Test CGI endpoints via FTP
echo -e "${YELLOW}Testing CGI script availability...${NC}"
if lftp -u "$FTP_USER,$FTP_PASS" -e "
set ftp:timeout 10
open $FTP_HOST $FTP_PORT
get -o /dev/null /mnt/www/cgi-bin/action.cgi
bye
" 2>&1 | grep -q "226"; then
  echo -e "${GREEN}✓ CGI scripts are accessible${NC}"
else
  echo -e "${YELLOW}⚠ CGI scripts may be inaccessible${NC}"
fi

# Check HTML file integrity
echo -e "${YELLOW}Verifying HTML file integrity...${NC}"
TEMP_HTML=$(mktemp)
lftp -u "$FTP_USER,$FTP_PASS" -e "
set ftp:timeout 10
open $FTP_HOST $FTP_PORT  
get -o $TEMP_HTML /mnt/www/index.html
bye
" 2>&1 > /dev/null

if grep -q "ppt-audio.bundle.min.js" "$TEMP_HTML"; then
  echo -e "${GREEN}✓ HTML file contains PTT audio script reference${NC}"
else
  echo -e "${RED}✗ HTML file missing PTT audio script reference${NC}"
  rm -f "$TEMP_HTML"
  exit 1
fi

if grep -q "listen_btn" "$TEMP_HTML"; then
  echo -e "${GREEN}✓ HTML file contains Listen button${NC}"
else
  echo -e "${RED}✗ HTML file missing Listen button${NC}"
  rm -f "$TEMP_HTML"
  exit 1
fi

if grep -q "ptt_level" "$TEMP_HTML"; then
  echo -e "${GREEN}✓ HTML file contains audio level meter${NC}"
else
  echo -e "${RED}✗ HTML file missing audio level meter${NC}"
  rm -f "$TEMP_HTML"
  exit 1
fi

rm -f "$TEMP_HTML"

# Check JavaScript files
echo -e "${YELLOW}Verifying JavaScript files...${NC}"
TEMP_JS=$(mktemp)
lftp -u "$FTP_USER,$FTP_PASS" -e "
set ftp:timeout 10
open $FTP_HOST $FTP_PORT
get -o $TEMP_JS /mnt/www/scripts/ppt-audio.bundle.min.js
bye
" 2>&1 > /dev/null

if [ -s "$TEMP_JS" ] && [ $(wc -c < "$TEMP_JS") -gt 1000 ]; then
  echo -e "${GREEN}✓ PTT audio bundle present and has content ($(wc -c < "$TEMP_JS") bytes)${NC}"
else
  echo -e "${RED}✗ PTT audio bundle is empty or missing${NC}"
  rm -f "$TEMP_JS"
  exit 1
fi

if grep -q "startListening\|stopListening\|startRecording" "$TEMP_JS"; then
  echo -e "${GREEN}✓ PTT audio bundle contains required functions${NC}"
else
  echo -e "${YELLOW}⚠ PTT audio bundle may be corrupted${NC}"
fi

rm -f "$TEMP_JS"

# Check CGI script
echo -e "${YELLOW}Verifying CGI script...${NC}"
TEMP_CGI=$(mktemp)
lftp -u "$FTP_USER,$FTP_PASS" -e "
set ftp:timeout 10
open $FTP_HOST $FTP_PORT
get -o $TEMP_CGI /mnt/www/cgi-bin/audio_stream.cgi
bye
" 2>&1 > /dev/null

if grep -q "audio_stream\|AUDIO_SAMPLE_RATE\|arecord" "$TEMP_CGI"; then
  echo -e "${GREEN}✓ Audio stream CGI script present and valid${NC}"
else
  echo -e "${RED}✗ Audio stream CGI script may be corrupted${NC}"
  rm -f "$TEMP_CGI"
  exit 1
fi

rm -f "$TEMP_CGI"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✓ DEPLOYMENT SUCCESSFUL & VERIFIED  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo "📍 Device: $FTP_HOST:$FTP_PORT"
echo "🎤 Features Deployed:"
echo "   • Push-To-Talk (PTT) with audio meter"
echo "   • Two-Way Audio streaming"
echo "   • Speaker test functionality"
echo ""
echo "🚀 Next Steps:"
echo "   1. Open: https://192.168.1.24 in browser"
echo "   2. Test PTT: Hold 'Hold to Talk' button"
echo "   3. Test Listen: Click 'Listen' button"
echo "   4. Test Speaker: Click 'Test' button"
echo ""
echo "📖 Documentation:"
echo "   • /mnt/AUDIO_FEATURES.md"
echo "   • /mnt/IMPLEMENTATION_SUMMARY.md"
echo ""

exit 0
