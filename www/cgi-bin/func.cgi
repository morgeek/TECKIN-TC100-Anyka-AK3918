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
    printf '%b' "${url_encoded//%/\\x}"
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
