#!/bin/sh
# Source: http://isquared.nl/blog/2008/11/01/Bourne-Bash-Shell-CGI-Scripts/

_DEBUG_=

if [ "${REQUEST_METHOD}" = "POST" ]
then
  POST_QUERY_STRING=`dd bs=1 count=${CONTENT_LENGTH} 2>/dev/null`
  if [ "${QUERY_STRING}" != "" ]
  then
      QUERY_STRING=${POST_QUERY_STRING}"&"${QUERY_STRING}
  else
      QUERY_STRING=${POST_QUERY_STRING}"&"
  fi
fi

#echo "Content-type: text/plain"; echo

# Safe parsing of QUERY_STRING -> sets vars named F_<param>
# Rules:
#  - only allow parameter names matching [A-Za-z0-9_]
#  - url-decode values
#  - escape dangerous characters before assignment to avoid command substitution
urldecode() {
    url_encoded="${1//+/ }"
    decoded=""
    while [ -n "$url_encoded" ]
    do
      case "$url_encoded" in
        %[0-9A-Fa-f][0-9A-Fa-f]*)
          hex="${url_encoded#%}"
          hex="${hex%"${hex#??}"}"
          decoded="${decoded}$(printf '%b' "\\x${hex}")"
          url_encoded="${url_encoded#???}"
          ;;
        %*)
          decoded="${decoded}%"
          url_encoded="${url_encoded#?}"
          ;;
        *)
          c="${url_encoded%"${url_encoded#?}"}"
          decoded="${decoded}${c}"
          url_encoded="${url_encoded#?}"
          ;;
      esac
    done
    printf '%s' "$decoded"
}

_IFS=${IFS}; IFS='&'
for _VAR in ${QUERY_STRING}
do
  [ -z "${_VAR}" ] && continue

  if [ ${_DEBUG_} ]
  then
      echo _VAR: ${_VAR}
      echo -n variable: `echo ${_VAR} | cut -d= -f1`" "
      echo value: `echo ${_VAR} | cut -d= -f2`
  fi

  name="${_VAR%%=*}"
  raw_value="${_VAR#*=}"

  # validate name (allow only alnum and underscore)
  case "${name}" in
    ''|*[!A-Za-z0-9_]* )
      # ignore suspicious parameter name
      continue
      ;;
  esac

  value="$(urldecode "${raw_value}")"

  # escape characters that could lead to evaluation during eval
  esc_value="${value//\\/\\\\}"
  esc_value="${esc_value//\"/\\\"}"
  esc_value="${esc_value//\`/\\\`}"
  esc_value="${esc_value//\$/\\\$}"

  # assign to F_<name> variable (name already validated)
  eval "F_${name}=\"${esc_value}\""

  if [ ${_DEBUG_} ]
  then
      echo "--- EXIT ---"
  fi
done
IFS=${_IFS}
unset _IFS _VAR name raw_value value esc_value

if [ ${_DEBUG_} ]
then
  echo query string: ${QUERY_STRING}
  echo post-part of query string: ${POST_QUERY_STRING}
fi

# JSON API Response Helpers
# Unified JSON response envelope for CGI endpoints
# Usage: json_response <data> [status_code]
# Or: json_error <error_message> [error_code] [status_code]

# Response status codes
JSON_OK="ok"
JSON_ERROR_INVALID_REQUEST="invalid_request"
JSON_ERROR_NOT_FOUND="not_found"
JSON_ERROR_SERVER_ERROR="server_error"
JSON_ERROR_PERMISSION_DENIED="permission_denied"
JSON_ERROR_RATE_LIMITED="rate_limited"
JSON_ERROR_SERVICE_UNAVAILABLE="service_unavailable"

# Escape JSON string values
json_escape() {
  # Fast path for simple strings
  case "$1" in
    *[\"\\]*)
      # Need escaping
      printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\n/\\n/g; s/\r/\\r/g; s/\t/\\t/g'
      ;;
    *)
      printf '%s' "$1"
      ;;
  esac
}

# Generate JSON response
json_response() {
  local data="$1"
  local status_code="${2:-200}"
  local timestamp=$(date +%s 2>/dev/null || echo "0")

  echo "Status: $status_code"
  echo "Content-type: application/json"
  echo "Cache-Control: no-cache, no-store"
  echo "Pragma: no-cache"
  echo ""

  printf '{"ok":true,"data":%s,"error":null,"code":"%s","timestamp":%d}\n' \
    "$data" "$JSON_OK" "$timestamp"
}

# Generate JSON error response
json_error() {
  local error_message="$1"
  local error_code="${2:-$JSON_ERROR_SERVER_ERROR}"
  local status_code="${3:-500}"
  local timestamp=$(date +%s 2>/dev/null || echo "0")

  echo "Status: $status_code"
  echo "Content-type: application/json"
  echo "Cache-Control: no-cache, no-store"
  echo "Pragma: no-cache"
  echo ""

  printf '{"ok":false,"data":null,"error":"%s","code":"%s","timestamp":%d}\n' \
    "$(json_escape "$error_message")" "$error_code" "$timestamp"
}

# Check if client requested JSON format
wants_json_response() {
  [ "${F_format}" = "json" ] || [ "${HTTP_ACCEPT:-}" = "application/json" ]
}

# rate_limit_check — call BEFORE any output headers have been emitted.
# Limits a single REMOTE_ADDR to at most RL_MAX_REQUESTS per RL_WINDOW_SECONDS.
# Defaults: 10 requests per 60 seconds.
# On limit exceeded: emits 429 JSON response and exits.
# Usage: rate_limit_check [max_requests] [window_seconds]
rate_limit_check() {
  _rl_max="${1:-10}"
  _rl_win="${2:-60}"
  _rl_dir="/tmp/ratelimit"
  _rl_ip="${REMOTE_ADDR:-unknown}"
  # Sanitize IP to safe filename characters (alnum, dot, colon, underscore)
  _rl_ip="$(printf '%s' "$_rl_ip" | tr -cd 'A-Za-z0-9._:-' | cut -c1-64)"
  [ -z "$_rl_ip" ] && _rl_ip="unknown"

  # Ensure directory exists
  [ -d "$_rl_dir" ] || mkdir -p "$_rl_dir" 2>/dev/null || return 0

  # Purge stale files older than 2× the window (best-effort, non-blocking)
  find "$_rl_dir" -maxdepth 1 -type f -name '*' 2>/dev/null | while read -r _stale; do
    _st_ws=0; _st_cnt=0
    read -r _st_ws _st_cnt < "$_stale" 2>/dev/null || true
    case "$_st_ws" in ''|*[!0-9]*) _st_ws=0 ;; esac
    if [ $((_rl_now - _st_ws)) -gt $((_rl_win * 2)) ] 2>/dev/null; then
      rm -f "$_stale" 2>/dev/null || true
    fi
  done

  _rl_file="$_rl_dir/$_rl_ip"

  # Read current btime + uptime for fork-free epoch
  _rl_btime=0
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _rl_btime="$_v" && break
  done < /proc/stat
  read -r _rl_up _ < /proc/uptime
  _rl_now=$((_rl_btime + ${_rl_up%.*}))

  _rl_window_start=0
  _rl_count=0
  if [ -f "$_rl_file" ]; then
    read -r _rl_window_start _rl_count < "$_rl_file" 2>/dev/null || true
    case "$_rl_window_start" in ''|*[!0-9]*) _rl_window_start=0 ;; esac
    case "$_rl_count" in ''|*[!0-9]*) _rl_count=0 ;; esac
  fi

  # If outside window, reset
  _rl_elapsed=$((_rl_now - _rl_window_start))
  if [ "$_rl_elapsed" -ge "$_rl_win" ] || [ "$_rl_elapsed" -lt 0 ]; then
    _rl_window_start="$_rl_now"
    _rl_count=0
  fi

  _rl_count=$((_rl_count + 1))
  printf '%s %s\n' "$_rl_window_start" "$_rl_count" > "$_rl_file" 2>/dev/null || true

  if [ "$_rl_count" -gt "$_rl_max" ]; then
    echo "Status: 429 Too Many Requests"
    echo "Content-Type: application/json"
    echo "Cache-Control: no-store, no-cache"
    echo "Pragma: no-cache"
    echo "Retry-After: $_rl_win"
    echo ""
    printf '{"ok":false,"error":"Rate limit exceeded. Try again later.","code":"rate_limited"}\n'
    exit 0
  fi
}

# csrf_guard — call BEFORE any output headers have been emitted.
# If the per-boot CSRF token in /tmp/csrf_token doesn't match the
# X-CSRF-Token request header, emits a 403 JSON response and exits.
# When no token exists yet (very early boot), silently passes through.
csrf_guard() {
  _cg_stored=""
  if [ -r /tmp/csrf_token ]; then
    read -r _cg_stored < /tmp/csrf_token
    _cg_stored="$(printf '%s' "$_cg_stored" | tr -cd '0-9a-fA-F')"
  fi
  [ -z "$_cg_stored" ] && return 0  # no token generated yet, skip
  _cg_header="$(printf '%s' "${HTTP_X_CSRF_TOKEN:-}" | tr -cd '0-9a-fA-F')"
  if [ "$_cg_header" != "$_cg_stored" ]; then
    echo "Status: 403 Forbidden"
    echo "Content-Type: application/json"
    echo "Cache-Control: no-store, no-cache"
    echo "Pragma: no-cache"
    echo ""
    printf '{"ok":false,"error":"CSRF token missing or invalid. Reload the page.","code":"permission_denied"}\n'
    exit 0
  fi
}

# audit_log_event — append a timestamped entry to /tmp/log/audit.log (fork-free).
# Usage: audit_log_event <action> [detail]
# Safe to call before or after response headers — writes only to the log file.
audit_log_event() {
  _ale_action="${1:-?}"
  _ale_detail="${2:-}"
  _ale_dir="/tmp/log"
  _ale_file="$_ale_dir/audit.log"
  _ale_max=65536
  [ -d "$_ale_dir" ] || mkdir -p "$_ale_dir" 2>/dev/null || return 0
  if [ -f "$_ale_file" ]; then
    _ale_sz="$(wc -c < "$_ale_file" 2>/dev/null)"; case "$_ale_sz" in ''|*[!0-9]*) _ale_sz=0 ;; esac
    if [ "$_ale_sz" -gt "$_ale_max" ]; then
      tail -n 100 "$_ale_file" > "${_ale_file}.tmp" 2>/dev/null && mv "${_ale_file}.tmp" "$_ale_file" 2>/dev/null || true
    fi
  fi
  _ale_btime=0
  while read -r _k _v _; do [ "$_k" = "btime" ] && _ale_btime="$_v" && break; done < /proc/stat
  read -r _ale_up _ < /proc/uptime
  _ale_ts=$((_ale_btime + ${_ale_up%.*}))
  _ale_ip="${REMOTE_ADDR:-unknown}"
  if [ -n "$_ale_detail" ]; then
    printf '%s action=%s ip=%s detail=%s\n' "$_ale_ts" "$_ale_action" "$_ale_ip" "$_ale_detail" >> "$_ale_file" 2>/dev/null || true
  else
    printf '%s action=%s ip=%s\n' "$_ale_ts" "$_ale_action" "$_ale_ip" >> "$_ale_file" 2>/dev/null || true
  fi
}
