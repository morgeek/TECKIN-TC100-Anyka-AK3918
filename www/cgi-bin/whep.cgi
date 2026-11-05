#!/bin/sh
# whep.cgi: the WHEP endpoint of the WebRTC live view (item 35), behind the same login as the web page (the web server
# authenticates every /cgi-bin/ request). It only forwards to tc100-whep, which listens on 127.0.0.1:8889 (the browser
# never reaches the daemon directly).
#   GET    /cgi-bin/whep.cgi                answers {"viewers":N,"max":M,...} when the daemon runs, 503 {"enabled":0} when
#                                            it does not (boot.conf WHEP=0): the page asks this before trying WebRTC
#   POST   /cgi-bin/whep.cgi                body = SDP offer, answer 201 + SDP answer + Location (WHEP, RFC 9725)
#   POST   /cgi-bin/whep.cgi?stop=ID      ends that viewer (the busybox web server answers no DELETE, the page uses this)
#   DELETE /cgi-bin/whep.cgi?stop=ID      the same, for WHEP clients that can send it
# The Location header is /cgi-bin/whep.cgi?stop=ID, so a client that sends DELETE to it works whichever way it is reached.
PORT=8889
BASE="http://127.0.0.1:$PORT"
CURL=/mnt/ext/bin/curl
[ -x "$CURL" ] || CURL=curl
T=/tmp/whep-cgi.$$
trap 'rm -f "$T".*' EXIT

reply()	# status reason content-type body
{
  printf 'Status: %s %s\r\nContent-Type: %s\r\nCache-Control: no-store\r\n\r\n%s\n' "$1" "$2" "$3" "$4"
  exit 0
}

# the daemon runs: its pid file names a live process (shell built-ins only, this is polled)
_pid=""
[ -r /var/run/whep.pid ] && read -r _pid < /var/run/whep.pid 2>/dev/null
case "$_pid" in ''|*[!0-9]*) reply 503 "Service Unavailable" application/json '{"enabled":0}' ;; esac
kill -0 "$_pid" 2>/dev/null || reply 503 "Service Unavailable" application/json '{"enabled":0}'

case "$QUERY_STRING" in
  stop=*)
    _id=${QUERY_STRING#stop=}
    case "$_id" in *[!0-9a-f]*|'') reply 400 "Bad Request" text/plain "bad viewer id" ;; esac
    [ "${#_id}" = 16 ] || reply 400 "Bad Request" text/plain "bad viewer id"
    case "$REQUEST_METHOD" in POST|DELETE) ;; *) reply 405 "Method Not Allowed" text/plain "POST or DELETE" ;; esac
    "$CURL" -s -m 10 -o /dev/null -w '%{http_code}' -X DELETE "$BASE/whep/$_id" > "$T.code" 2>/dev/null
    read -r _c < "$T.code" 2>/dev/null
    case "$_c" in 200) reply 200 OK text/plain "" ;; 404) reply 404 "Not Found" text/plain "no such viewer" ;; *) reply 502 "Bad Gateway" text/plain "whep daemon" ;; esac
    ;;
esac

case "$REQUEST_METHOD" in
  GET|HEAD)
    "$CURL" -s -m 5 -o "$T.body" "$BASE/status" 2>/dev/null || reply 503 "Service Unavailable" application/json '{"enabled":0}'
    read -r _j < "$T.body" 2>/dev/null
    reply 200 OK application/json "$_j"
    ;;
  POST)
    _cl=${CONTENT_LENGTH:-0}
    case "$_cl" in ''|*[!0-9]*) reply 400 "Bad Request" text/plain "no body" ;; esac
    # a browser offer is bigger than it looks: Chrome 157 (video + audio, recvonly, host candidates) is 7607 bytes; the
    # former limit of 6000 answered 413 and the page fell back to MP4 at once (tester, IPCAM2, rc28). Same limit as
    # tc100-whep (WH_MAX_OFFER).
    { [ "$_cl" -gt 0 ] && [ "$_cl" -le 12000 ]; } || reply 413 "Payload Too Large" text/plain "offer too large"
    # exactly Content-Length bytes: the web server keeps the connection open, EOF never comes
    head -c "$_cl" > "$T.in"
    "$CURL" -s -m 25 -D "$T.hdr" -o "$T.body" -H 'Content-Type: application/sdp' --data-binary "@$T.in" "$BASE/whep" 2>/dev/null \
      || reply 502 "Bad Gateway" text/plain "whep daemon"
    read -r _st _code _reason < "$T.hdr"
    case "$_code" in 201|400|415|429|500|503) ;; *) reply 502 "Bad Gateway" text/plain "whep daemon" ;; esac
    _loc=""
    while IFS= read -r _l; do
      case "$_l" in [Ll]ocation:*) _loc=${_l#*: }; _loc=${_loc%"$(printf '\r')"} ;; esac
    done < "$T.hdr"
    printf 'Status: %s %s\r\n' "$_code" "${_reason%"$(printf '\r')"}"
    if [ "$_code" = 201 ]; then
      printf 'Content-Type: application/sdp\r\n'
      case "$_loc" in /whep/*) printf 'Location: /cgi-bin/whep.cgi?stop=%s\r\n' "${_loc#/whep/}" ;; esac
    else
      printf 'Content-Type: text/plain\r\n'
    fi
    printf 'Cache-Control: no-store\r\n\r\n'
    cat "$T.body"
    ;;
  *)
    reply 405 "Method Not Allowed" text/plain "GET, POST or DELETE"
    ;;
esac
exit 0
