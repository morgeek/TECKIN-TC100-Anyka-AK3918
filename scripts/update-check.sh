#!/bin/sh
# update-check.sh — Secure HTTPS check for new releases on GitHub.

VERSION_FILE="/VERSION"
CACHE_FILE="/tmp/update_status.json"
CACHE_TTL=86400 # 24 hours
CACERT="/mnt/config/ssl/cacert/cacert.pem"
REPO="morgeek/TECKIN-TC100-Anyka-AK3918"
GITHUB_API="https://api.github.com/repos/$REPO/releases/latest"

CURL="/mnt/bin/curl"
JQ="/mnt/bin/jq"

# 1. Check if check is forced or cache is expired
if [ -f "$CACHE_FILE" ]; then
    _now=$(date +%s)
    _stat=$(stat -c %Y "$CACHE_FILE")
    _age=$((_now - _stat))
    if [ "$_age" -lt "$CACHE_TTL" ] && [ "$1" != "--force" ]; then
        exit 0
    fi
fi

# 2. Identify current version
if [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(cat "$VERSION_FILE" | tr -d ' \n\r')
else
    # Fallback if VERSION file is missing
    CURRENT_VERSION="v0.0.0"
fi

# 3. Fetch latest release from GitHub
# We use a custom User-Agent as required by GitHub API.
# We use --cacert for secure, verified HTTPS connectivity.
_response=$( "$CURL" -s -H "User-Agent: Elite-TC100-Updater" \
             --cacert "$CACERT" \
             "$GITHUB_API" 2>/dev/null )

if [ $? -ne 0 ] || [ -z "$_response" ]; then
    # Silent failure to avoid bothering isolated users
    exit 1
fi

# 4. Parse tag_name
LATEST_TAG=$(echo "$_response" | "$JQ" -r '.tag_name' 2>/dev/null)

if [ -z "$LATEST_TAG" ] || [ "$LATEST_TAG" = "null" ]; then
    exit 1
fi

# 5. Compare and Save Status
UPDATE_AVAILABLE=0
if [ "$LATEST_TAG" != "$CURRENT_VERSION" ]; then
    # Simple check for now: if the strings are different, an update is available.
    # In a more advanced version, we could do semantic version comparison.
    UPDATE_AVAILABLE=1
fi

# Output JSON to cache file
printf '{"update_available":%s,"latest_version":"%s","current_version":"%s","last_check":%s}\n' \
    "$UPDATE_AVAILABLE" "$LATEST_TAG" "$CURRENT_VERSION" "$(date +%s)" > "$CACHE_FILE"

exit 0
