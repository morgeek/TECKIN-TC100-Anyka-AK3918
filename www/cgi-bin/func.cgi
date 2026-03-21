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
