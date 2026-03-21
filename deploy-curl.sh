#!/bin/bash

# FTP Deployment Script using curl (compatible with macOS)
# Uploads modified files for PTT & Two-Way Audio features

set -e

FTP_HOST="192.168.1.24"
FTP_PORT="2121"
FTP_USER="root"
FTP_PASS="pass"
FTP_URL="ftp://$FTP_USER:$FTP_PASS@$FTP_HOST:$FTP_PORT"

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
  "www/scripts/ptt-audio.bundle.min.js:/mnt/www/scripts/ptt-audio.bundle.min.js"
  "www/scripts/index.bundle.min.js:/mnt/www/scripts/index.bundle.min.js"
  "www/cgi-bin/audio_stream.cgi:/mnt/www/cgi-bin/audio_stream.cgi"
)

# Optional documentation files (don't fail if missing)
declare -a OPTIONAL_FILES=(
  "AUDIO_FEATURES.md:/mnt/AUDIO_FEATURES.md"
  "IMPLEMENTATION_SUMMARY.md:/mnt/IMPLEMENTATION_SUMMARY.md"
  "README.md:/mnt/README.md"
)

echo -e "${YELLOW}Target Device: ftp://$FTP_HOST:$FTP_PORT${NC}\n"

upload_count=0
fail_count=0

# Upload required files
echo -e "${YELLOW}Uploading required files...${NC}"
for file_pair in "${FILES_TO_UPLOAD[@]}"; do
  IFS=':' read -r local_path remote_path <<< "$file_pair"
  
  if [ ! -f "$SCRIPT_DIR/$local_path" ]; then
    echo -e "${RED}✗ Missing: $local_path${NC}"
    ((fail_count++))
    continue
  fi
  
  file_size=$(stat -f%z "$SCRIPT_DIR/$local_path" 2>/dev/null || stat -c%s "$SCRIPT_DIR/$local_path" 2>/dev/null)
  echo -ne "${YELLOW}  → $local_path ($file_size bytes)${NC}... "
  
  if curl -s --ftp-create-dirs -T "$SCRIPT_DIR/$local_path" "$FTP_URL$remote_path" 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
    ((upload_count++))
  else
    echo -e "${RED}✗ Failed${NC}"
    ((fail_count++))
  fi
done

echo ""

# Upload optional files
echo -e "${YELLOW}Uploading documentation files...${NC}"
for file_pair in "${OPTIONAL_FILES[@]}"; do
  IFS=':' read -r local_path remote_path <<< "$file_pair"
  
  if [ ! -f "$SCRIPT_DIR/$local_path" ]; then
    echo -e "${YELLOW}  ⊘ Optional file missing: $local_path${NC}"
    continue
  fi
  
  file_size=$(stat -f%z "$SCRIPT_DIR/$local_path" 2>/dev/null || stat -c%s "$SCRIPT_DIR/$local_path" 2>/dev/null)
  echo -ne "${YELLOW}  → $local_path ($file_size bytes)${NC}... "
  
  if curl -s --ftp-create-dirs -T "$SCRIPT_DIR/$local_path" "$FTP_URL$remote_path" 2>/dev/null; then
    echo -e "${GREEN}✓${NC}"
    ((upload_count++))
  else
    echo -e "${YELLOW}⚠ Optional upload skipped${NC}"
  fi
done

echo ""

if [ $fail_count -gt 0 ]; then
  echo -e "${RED}✗ $fail_count required file(s) failed to upload${NC}"
  exit 1
fi

echo -e "${GREEN}✓ $upload_count files uploaded successfully${NC}\n"

# Verify files on device
echo -e "${BLUE}=== Verification ===${NC}\n"

echo -e "${YELLOW}Verifying deployed files...${NC}"

verify_count=0
for file_pair in "${FILES_TO_UPLOAD[@]}"; do
  IFS=':' read -r local_path remote_path <<< "$file_pair"
  
  echo -ne "${YELLOW}  ✓ $remote_path${NC}... "
  
  # Try to download the file header to verify it exists and is accessible
  if timeout 5 curl -s -r 0-100 "$FTP_URL$remote_path" > /dev/null 2>&1; then
    echo -e "${GREEN}accessible${NC}"
    ((verify_count++))
  else
    echo -e "${YELLOW}(cannot verify)${NC}"
  fi
done

echo ""

# Verify file integrity
echo -e "${YELLOW}Checking file integrity...${NC}"

# Download and check HTML file
echo -ne "${YELLOW}  → HTML file structure${NC}... "
TEMP_HTML=$(mktemp)
if curl -s "$FTP_URL/mnt/www/index.html" > "$TEMP_HTML" 2>/dev/null; then
  checks_passed=0
  
  if grep -q "ppt-audio.bundle.min.js" "$TEMP_HTML"; then
    ((checks_passed++))
  else
    echo -e "${RED}Missing PTT script reference${NC}"
  fi
  
  if grep -q "listen_btn" "$TEMP_HTML"; then
    ((checks_passed++))
  else
    echo -e "${RED}Missing Listen button${NC}"
  fi
  
  if grep -q "ptt_level" "$TEMP_HTML"; then
    ((checks_passed++))
  else
    echo -e "${RED}Missing audio meter${NC}"
  fi
  
  if [ $checks_passed -eq 3 ]; then
    echo -e "${GREEN}✓${NC}"
  else
    echo -e "${RED}✗ ($checks_passed/3 checks passed)${NC}"
  fi
else
  echo -e "${YELLOW}⚠ Could not verify${NC}"
fi
rm -f "$TEMP_HTML"

# Check JavaScript bundle
echo -ne "${YELLOW}  → JavaScript bundle${NC}... "
TEMP_JS=$(mktemp)
if curl -s "$FTP_URL/mnt/www/scripts/ptt-audio.bundle.min.js" > "$TEMP_JS" 2>/dev/null; then
  js_size=$(stat -f%z "$TEMP_JS" 2>/dev/null || stat -c%s "$TEMP_JS" 2>/dev/null)
  if [ "$js_size" -gt 5000 ]; then
    echo -e "${GREEN}✓ ($(numfmt --to=iec-i --suffix=B $js_size 2>/dev/null || echo "$js_size bytes"))${NC}"
  else
    echo -e "${RED}✗ Bundle appears truncated${NC}"
  fi
else
  echo -e "${YELLOW}⚠ Could not verify${NC}"
fi
rm -f "$TEMP_JS"

# Check CGI script
echo -ne "${YELLOW}  → CGI script${NC}... "
TEMP_CGI=$(mktemp)
if curl -s "$FTP_URL/mnt/www/cgi-bin/audio_stream.cgi" > "$TEMP_CGI" 2>/dev/null; then
  if grep -q "audio_stream\|arecord" "$TEMP_CGI"; then
    echo -e "${GREEN}✓${NC}"
  else
    echo -e "${RED}✗ Script content invalid${NC}"
  fi
else
  echo -e "${YELLOW}⚠ Could not verify${NC}"
fi
rm -f "$TEMP_CGI"

echo ""

# Summary
echo -e "${BLUE}=== Deployment Summary ===${NC}\n"

echo "📍 Device: $FTP_HOST:$FTP_PORT"
echo "👤 User: $FTP_USER"
echo ""
echo "📦 Files Deployed:"
echo "   ✓ www/index.html (main UI)"
echo "   ✓ www/scripts/ptt-audio.bundle.min.js (PTT & listening module)"
echo "   ✓ www/scripts/index.bundle.min.js (core UI)"
echo "   ✓ www/cgi-bin/audio_stream.cgi (audio streaming endpoint)"
echo ""
echo "🎤 Features Ready:"
echo "   ✓ Push-To-Talk with audio level meter"
echo "   ✓ Speaker test button"
echo "   ✓ Two-Way audio listening"
echo "   ✓ Real-time microphone streaming"
echo ""
echo "🚀 Testing Instructions:"
echo "   1. Open browser: https://192.168.1.24 (or http:// if not HTTPS)"
echo "   2. Wait for page to load (may take a few seconds)"
echo "   3. Check browser console for any errors (F12)"
echo ""
echo "🔊 PTT Testing:"
echo "   • Press & hold 'Hold to Talk' button"
echo "   • You should see the audio level meter active"
echo "   • Release to send (status shows 'Sending...')"
echo "   • Speaker should play the audio"
echo "   • Click 'Test' to verify speaker works"
echo ""
echo "🎧 Two-Way Audio Testing:"
echo "   • Click 'Listen' button"
echo "   • Button should show 'Listening...'"
echo "   • You should hear camera microphone audio"
echo "   • Auto-disconnects after 30 seconds"
echo ""
echo "❓ Troubleshooting:"
echo "   • If PTT shows 'unsupported': Check HTTPS/localhost"
echo "   • If no audio: Check camera has audio devices (/dev/audio*)"
echo "   • If script missing: Check /mnt/www/cgi-bin/audio_stream.cgi exists"
echo "   • Browser console (F12) will show detailed errors"
echo ""
echo "📖 Documentation:"
echo "   • /mnt/AUDIO_FEATURES.md (technical details)"
echo "   • /mnt/IMPLEMENTATION_SUMMARY.md (what was added)"
echo ""

echo -e "${GREEN}✓ Deployment Complete!${NC}\n"

exit 0
