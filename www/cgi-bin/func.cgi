#!/bin/sh
# Source: http://isquared.nl/blog/2008/11/01/Bourne-Bash-Shell-CGI-Scripts/

if [ "${REQUEST_METHOD}" = "POST" ]
then
  # Validate CONTENT_LENGTH before reading; cap at 64 KB to prevent RAM exhaustion.
  _cl="${CONTENT_LENGTH:-0}"
  case "$_cl" in ''|*[!0-9]*) _cl=0 ;; esac
  [ "$_cl" -gt 65536 ] && _cl=65536
  POST_QUERY_STRING="$(head -c "$_cl" 2>/dev/null)"
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
  # surgical hardening: escape characters that enable command chaining/redirection
  esc_value="${esc_value//;/\\;}"
  esc_value="${esc_value//|/\\|}"
  esc_value="${esc_value//&/\\&}"
  esc_value="${esc_value//(/\\(}"
  esc_value="${esc_value//)/\\)}"
  esc_value="${esc_value//</\\<}"
  esc_value="${esc_value//>/\\>}"

  # assign to F_<name> variable (name already validated)
  eval "F_${name}=\"${esc_value}\""
done
IFS=${_IFS}
unset _IFS _VAR name raw_value value esc_value

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
  # Use awk for correct multi-char escaping on BusyBox sed (sed \n/\t in patterns is unreliable).
  # awk processes line-by-line; NR>1 inserts \n between lines for embedded newlines.
  printf '%s' "$1" | awk '
    NR > 1 { printf "\\n" }
    { gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); gsub(/\t/, "\\t"); gsub(/\r/, "\\r"); printf "%s", $0 }
  '
}

# Generate JSON response
json_response() {
  local data="$1"
  local status_code="${2:-200}"
  local _jr_btime=0 _jr_up="" _jr_ts=0
  while read -r _k _v _; do [ "$_k" = "btime" ] && _jr_btime="$_v" && break; done < /proc/stat
  read -r _jr_up _ < /proc/uptime 2>/dev/null || true
  local timestamp=$((_jr_btime + ${_jr_up%.*}))

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
  local _je_btime=0 _je_up="" _je_ts=0
  while read -r _k _v _; do [ "$_k" = "btime" ] && _je_btime="$_v" && break; done < /proc/stat
  read -r _je_up _ < /proc/uptime 2>/dev/null || true
  local timestamp=$((_je_btime + ${_je_up%.*}))

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

# Config install cache: skip expensive install_config() when configs unchanged
# Checks mtime of .dist vs .conf to decide if install_config is needed
# Usage: install_config_cached <config_file>
install_config_cached() {
  _icc_conf="$1"
  _icc_dist="${_icc_conf}.dist"
  [ -f "$_icc_dist" ] || return 0
  [ -f "$_icc_conf" ] || { install_config "$_icc_conf"; return 0; }
  _icc_dist_mtime="$(stat -c %Y "$_icc_dist" 2>/dev/null || stat -f %m "$_icc_dist" 2>/dev/null)"
  _icc_conf_mtime="$(stat -c %Y "$_icc_conf" 2>/dev/null || stat -f %m "$_icc_conf" 2>/dev/null)"
  case "$_icc_dist_mtime:$_icc_conf_mtime" in
    ''|*[!0-9:]*)
      install_config "$_icc_conf"
      ;;
    *)
      [ "$_icc_dist_mtime" -le "$_icc_conf_mtime" ] || install_config "$_icc_conf"
      ;;
  esac
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

  # Compute fork-free epoch FIRST so it is available for the purge loop below.
  _rl_btime=0
  while read -r _k _v _; do
    [ "$_k" = "btime" ] && _rl_btime="$_v" && break
  done < /proc/stat
  read -r _rl_up _ < /proc/uptime
  _rl_now=$((_rl_btime + ${_rl_up%.*}))

  # Purge stale files older than 2× the window.
  # Use a for-glob loop (not find|while) so _rl_now is visible without a subshell.
  for _rl_stale in "$_rl_dir"/*; do
    [ -f "$_rl_stale" ] || continue
    _st_ws=0
    read -r _st_ws _ < "$_rl_stale" 2>/dev/null || true
    case "$_st_ws" in ''|*[!0-9]*) _st_ws=0 ;; esac
    if [ $((_rl_now - _st_ws)) -gt $((_rl_win * 2)) ] 2>/dev/null; then
      rm -f "$_rl_stale" 2>/dev/null || true
    fi
  done

  _rl_file="$_rl_dir/$_rl_ip"

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
  if [ -z "$_cg_stored" ]; then
    # Token not yet written. Pass during early boot (<60s uptime); deny after that.
    _cg_up=0; read -r _cg_up _ < /proc/uptime 2>/dev/null || true; _cg_up="${_cg_up%.*}"
    case "$_cg_up" in ''|*[!0-9]*) _cg_up=0 ;; esac
    if [ "$_cg_up" -lt 60 ]; then
      logger -t cgi-recovery "CSRF guard bypassed for endpoint ${REQUEST_URI:-unknown} (early-boot window)"
      return 0
    fi
    echo "Status: 403 Forbidden"
    echo "Content-Type: application/json"
    echo "Cache-Control: no-store, no-cache"
    echo "Pragma: no-cache"
    echo ""
    printf '{"ok":false,"error":"CSRF token unavailable. Reload the page.","code":"permission_denied"}\n'
    exit 0
  fi
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
