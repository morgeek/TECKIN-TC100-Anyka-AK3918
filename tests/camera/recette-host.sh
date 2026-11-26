#!/bin/sh
# recette-host.sh: the acceptance bench run from the tester's machine (Linux or macOS: sh, ssh, scp, curl, nc;
# optional ffprobe, avahi-browse, mosquitto_pub / mosquitto_sub).
#
# TEST TOOL, kept in tests/camera/, never part of a build. It does three things:
#   1. the checks that must come from another LAN address (HTTP 431, wrong-login lockout, RTSP SETUP 404, a client that
#      stops reading, ONVIF without auth, ffprobe of the two streams, mDNS, the retained MQTT command, two MQTT events);
#   2. copies recette.sh to the camera (ssh and cat: the cameras have no scp) and starts it DETACHED (results in a folder
#      on the camera), so the checks that cut the Wi-Fi do not stop it; it polls until the bench writes its done file;
#   3. fetches the results of both parts (ssh and cat) and prints one summary.
#
#   sh recette-host.sh --list                                   the host checks (ID check host)
#   sh recette-host.sh --dry-run --camera IP [--only IDS]        what would run, no connection at all
#   RECETTE_PASS=... sh recette-host.sh --camera IP [--only IDS] [--disruptive] [--wifi]
#
# Environment (never written to the repository, never printed):
#   RECETTE_PASS          the camera's web / RTSP password (root). Without it the password checks are SKIPped.
#   RECETTE_CAMERA_USER   ssh user, default root (ssh key or agent: no password is asked here)
#   RECETTE_SSH_OPTS      extra ssh options for every ssh call of this script, split on spaces (no spaces inside a
#                         value), for example "-i /home/me/.ssh/cam_key -o IdentitiesOnly=yes -o UserKnownHostsFile=/home/me/.ssh/cam_hosts"
#   RECETTE_ONVIF_PORT    default 8081 (onvif.conf ONVIF_PORT)
#   RECETTE_MQTT_HOST, RECETTE_MQTT_PORT (1883), RECETTE_MQTT_USER, RECETTE_MQTT_PASS, RECETTE_MQTT_ROOT
#                         the broker and the topic root of the camera (its MQTT_ROOT). Without host and root: SKIP.
#   RECETTE_IDLE_S        idle seconds before each ffprobe open in W3-ZERO, default 60
#   RECETTE_LOCK_WAIT_S   wait after the 10 wrong logins, default 310 (the lock lasts 300 s)
#   RECETTE_TIMEOUT_S     how long to wait for the camera's bench, default 14400
#   RECETTE_OUT           local folder for the results, default ./recette-results-<date>
#   RECETTE_CAMERA_ARGS   extra arguments for recette.sh (for example RECETTE_KILLS=10 is an env of the camera run:
#                         use "RECETTE_KILLS=10 RECETTE_WIFI_CYCLES=3" to shorten a run)
# Lockout: the wrong-login check locks this machine's address for 5 minutes only; the camera's own calls (127.0.0.1)
# are never locked, and the check proves that during the lock.

HERE=$(cd "$(dirname "$0")" && pwd)
MODE=run; ONLY=; DISRUPT=0; WIFI=0; CAM=${RECETTE_CAMERA:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --list) MODE=list ;;
    --dry-run) MODE=dry ;;
    --camera) shift; CAM=$1 ;;
    --only) shift; ONLY=$1 ;;
    --disruptive) DISRUPT=1 ;;
    --wifi) WIFI=1 ;;
    --out) shift; RECETTE_OUT=$1 ;;
    *) echo "usage: sh recette-host.sh [--list | --dry-run] --camera IP [--only IDS] [--disruptive] [--wifi] [--out DIR]" >&2; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------------------------------------------------------
# host check table: ID|check|function|needs   (the order of the run; the lockout last: it locks this address)
# ---------------------------------------------------------------------------------------------------------------
HOST_CHECKS='AUDIT-1116-NET|web-431|h_web_431|password
AUDIT-1116-NET|web-no-431|h_web_no_431|password
AUDIT-1116-NET|onvif-no-auth|h_onvif_no_auth|
AUDIT-1116-RTSP|setup-track-404|h_setup_404|password
AUDIT-1116-RTSP|tcp-stall-close|h_tcp_stall|password
CLEANUP-1124|video-main-sub|h_video|password
SMALL-B-1124|mdns-txt|h_mdns|
W3-ZERO|open-time|h_open_time|password
R3-MQTT|retained-command|h_mqtt_retained|mqtt
SMALL-A-1124|mqtt-two-events|h_mqtt_two|mqtt
AUDIT-1116-NET|lockout-10|h_lockout|password'

selected() {
  [ -z "$ONLY" ] && return 0
  case ",$ONLY," in *",$1,"*) return 0 ;; esac
  return 1
}

if [ "$MODE" = list ]; then
  printf '%s\n' "$HOST_CHECKS" | while IFS='|' read -r id name fn needs; do echo "$id $name host"; done
  exit 0
fi

if [ "$MODE" = dry ]; then
  printf '%s\n' "$HOST_CHECKS" | while IFS='|' read -r id name fn needs; do
    selected "$id" || continue
    echo "DRY $id $name host"
  done
  "$HERE/recette.sh" --dry-run ${ONLY:+--only "$ONLY"} | sed 's/^DRY /DRY camera /'
  exit 0
fi

[ -n "$CAM" ] || { echo "--camera IP (or RECETTE_CAMERA) is required" >&2; exit 2; }
CUSER=${RECETTE_CAMERA_USER:-root}
ONVIF_PORT=${RECETTE_ONVIF_PORT:-8081}
RUNSTAMP=$(date +%Y%m%d-%H%M%S)
OUTD=${RECETTE_OUT:-./recette-results-$RUNSTAMP}
mkdir -p "$OUTD" || exit 1
HOSTRES=$OUTD/host-results.txt
: > "$HOSTRES"
TMPD=$(mktemp -d 2>/dev/null || mktemp -d -t recette)
chmod 700 "$TMPD"
CFG=$TMPD/curl.cfg
RUN=/tmp/recette-$RUNSTAMP
SSHO="-o BatchMode=yes -o ConnectTimeout=10 ${RECETTE_SSH_OPTS:-}"
MYIP=
PASS_OK=0; [ -n "${RECETTE_PASS:-}" ] && PASS_OK=1

cleanup() {
  if [ "${RETAINED_SET:-0}" = 1 ]; then mosquitto_pub -t "${CMD_TOPIC:-}" -r -n >/dev/null 2>&1; fi
  rm -rf "$TMPD"
  [ -n "${NCPID:-}" ] && kill -CONT "$NCPID" 2>/dev/null && kill "$NCPID" 2>/dev/null
  true
}
trap cleanup EXIT INT TERM

# ssh_cam: no stdin (-n), so a check never eats the lines of the table it runs from; ssh_cam_in keeps stdin for the
# calls that send input (password file, curl config, MQTT script)
ssh_cam() { ssh -n $SSHO "$CUSER@$CAM" "$@"; }
ssh_cam_in() { ssh $SSHO "$CUSER@$CAM" "$@"; }

hres() {
  _line="RESULT $1 $2 $3 $(echo "$4" | tr '\n\r' '  ')"
  echo "$_line"
  echo "$_line" >> "$HOSTRES"
  RESN=$((RESN + 1))
}

# curl config with the camera password (umask 077, deleted at exit); the wrong logins are not secret
mk_cfg() {
  _pw=$(printf '%s' "${RECETTE_PASS:-}" | sed 's/\\/\\\\/g; s/"/\\"/g')
  ( umask 077; printf 'user = "root:%s"\nsilent\n' "$_pw" > "$CFG" )
}

# mask: the password replaced by *** in a text, as a fixed string (no regex: the password may hold any character)
mask() {
  awk -v p="${RECETTE_PASS:-}" '{ if (p == "") { print; next } out = ""; s = $0
    while ((i = index(s, p)) > 0) { out = out substr(s, 1, i - 1) "***"; s = substr(s, i + length(p)) }
    print out s }'
}

basic_auth() { printf 'root:%s' "${RECETTE_PASS:-}" | base64 | tr -d '\n'; }

# rtsp_send FILE: one RTSP exchange over a TCP connection, the request text on stdin of nc
rtsp_exchange() { nc -w 4 "$CAM" 554; }

h_web_431() {
  pad=$(head -c 5000 /dev/zero | tr '\0' a)
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "X-Pad: $pad" -u root:recette-wrong "http://$CAM/x")
  if [ "$code" = 431 ]; then hres AUDIT-1116-NET web-431 PASS "5000-byte header: HTTP 431"
  else hres AUDIT-1116-NET web-431 FAIL "HTTP $code for a 5000-byte header (431 expected; WEB_LOCKOUT=1?)"; fi
}

h_web_no_431() {
  [ "$PASS_OK" = 1 ] || { hres AUDIT-1116-NET web-no-431 SKIP "RECETTE_PASS not set"; return; }
  mk_cfg
  cookie=$(head -c 3000 /dev/zero | tr '\0' x)
  code=$(curl -s -K "$CFG" -o /dev/null -w '%{http_code}' -H "Cookie: c=$cookie" "http://$CAM/cgi-bin/state.cgi?cmd=daynight")
  if [ "$code" = 200 ]; then hres AUDIT-1116-NET web-no-431 PASS "3000-byte Cookie header with the right login: HTTP 200"
  else hres AUDIT-1116-NET web-no-431 FAIL "HTTP $code with a 3000-byte Cookie (200 expected)"; fi
}

h_onvif_no_auth() {
  body='<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><tds:GetDeviceInformation xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/></s:Body></s:Envelope>'
  resp=$(curl -s -m 10 -X POST -H 'Content-Type: application/soap+xml; charset=utf-8' --data "$body" "http://$CAM:$ONVIF_PORT/onvif/device_service")
  case "$resp" in
    *NotAuthorized*) hres AUDIT-1116-NET onvif-no-auth PASS "GetDeviceInformation without a token: NotAuthorized" ;;
    *GetDeviceInformationResponse*) hres AUDIT-1116-NET onvif-no-auth SKIP "ONVIF answers without a token: no ONVIF password set" ;;
    *) hres AUDIT-1116-NET onvif-no-auth FAIL "no SOAP answer on port $ONVIF_PORT (got ${#resp} bytes)" ;;
  esac
}

h_setup_404() {
  [ "$PASS_OK" = 1 ] || { hres AUDIT-1116-RTSP setup-track-404 SKIP "RECETTE_PASS not set"; return; }
  auth=$(basic_auth)
  desc=$(printf 'DESCRIBE rtsp://%s:554/video0 RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\nAuthorization: Basic %s\r\n\r\n' "$CAM" "$auth" | rtsp_exchange)
  case "$desc" in
    *'RTSP/1.0 200'*) ;;
    *) hres AUDIT-1116-RTSP setup-track-404 FAIL "DESCRIBE: $(echo "$desc" | head -n 1)"; return ;;
  esac
  case "$desc" in
    *'m=audio'*) hres AUDIT-1116-RTSP setup-track-404 SKIP "the audio track is on: the 404 case needs RTSP_AUDIO off (owner setting)"; return ;;
  esac
  r2=$(printf 'SETUP rtsp://%s:554/video0/track2 RTSP/1.0\r\nCSeq: 2\r\nTransport: RTP/AVP;unicast;client_port=5000-5001\r\nAuthorization: Basic %s\r\n\r\n' "$CAM" "$auth" | rtsp_exchange)
  r3=$(printf 'SETUP rtsp://%s:554/video0/track3 RTSP/1.0\r\nCSeq: 3\r\nTransport: RTP/AVP;unicast;client_port=5002-5003\r\nAuthorization: Basic %s\r\n\r\n' "$CAM" "$auth" | rtsp_exchange)
  s2=$(echo "$r2" | head -n 1 | tr -d '\r'); s3=$(echo "$r3" | head -n 1 | tr -d '\r')
  case "$s2 $s3" in
    *'404'*'404'*) hres AUDIT-1116-RTSP setup-track-404 PASS "SETUP track2: $s2; track3: $s3" ;;
    *) hres AUDIT-1116-RTSP setup-track-404 FAIL "SETUP track2: '$s2'; track3: '$s3' (404 expected with audio and talk off)" ;;
  esac
}

h_tcp_stall() {
  [ "$PASS_OK" = 1 ] || { hres AUDIT-1116-RTSP tcp-stall-close SKIP "RECETTE_PASS not set"; return; }
  command -v mkfifo >/dev/null 2>&1 || { hres AUDIT-1116-RTSP tcp-stall-close SKIP "no mkfifo"; return; }
  MYIP=$(ssh_cam 'echo $SSH_CLIENT' 2>/dev/null | cut -d' ' -f1)
  [ -n "$MYIP" ] || { hres AUDIT-1116-RTSP tcp-stall-close SKIP "cannot read this host's address from SSH_CLIENT"; return; }
  auth=$(basic_auth)
  fifo=$TMPD/rtsp.fifo; out=$TMPD/rtsp.out
  mkfifo "$fifo"; : > "$out"
  nc "$CAM" 554 < "$fifo" > "$out" 2>/dev/null &
  NCPID=$!
  exec 7> "$fifo"
  printf 'DESCRIBE rtsp://%s:554/video0 RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\nAuthorization: Basic %s\r\n\r\n' "$CAM" "$auth" >&7
  sleep 2
  printf 'SETUP rtsp://%s:554/video0/track1 RTSP/1.0\r\nCSeq: 2\r\nTransport: RTP/AVP/TCP;unicast;interleaved=0-1\r\nAuthorization: Basic %s\r\n\r\n' "$CAM" "$auth" >&7
  sleep 2
  sess=$(sed -n 's/^Session: *\([^;[:space:]]*\).*/\1/p' "$out" | tail -n 1 | tr -d '\r')
  if [ -z "$sess" ]; then
    exec 7>&-; kill "$NCPID" 2>/dev/null; NCPID=
    hres AUDIT-1116-RTSP tcp-stall-close FAIL "no Session in SETUP's answer"; return
  fi
  printf 'PLAY rtsp://%s:554/video0 RTSP/1.0\r\nCSeq: 3\r\nSession: %s\r\nAuthorization: Basic %s\r\n\r\n' "$CAM" "$sess" "$auth" >&7
  sleep 3
  before=$(ssh_cam "netstat -tn 2>/dev/null | grep ':554 ' | grep '$MYIP:' | grep -c ESTABLISHED")
  kill -STOP "$NCPID" 2>/dev/null
  sleep 40
  after=$(ssh_cam "netstat -tn 2>/dev/null | grep ':554 ' | grep '$MYIP:' | grep -c ESTABLISHED")
  kill -CONT "$NCPID" 2>/dev/null; exec 7>&-; kill "$NCPID" 2>/dev/null; NCPID=
  if [ "${before:-0}" -ge 1 ] && [ "${after:-1}" = 0 ]; then
    hres AUDIT-1116-RTSP tcp-stall-close PASS "a client that stopped reading for 40 s: connection gone (before $before, after $after)"
  else
    hres AUDIT-1116-RTSP tcp-stall-close FAIL "connections from this host before $before, after 40 s $after (netstat missing or the stall close did not happen)"
  fi
}

h_video() {
  command -v ffprobe >/dev/null 2>&1 || { hres CLEANUP-1124 video-main-sub SKIP "no ffprobe on this machine"; return; }
  [ "$PASS_OK" = 1 ] || { hres CLEANUP-1124 video-main-sub SKIP "RECETTE_PASS not set"; return; }
  main=$(ffprobe -nostdin -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 "rtsp://root:$RECETTE_PASS@$CAM:554/video0" 2>&1 | mask | head -n 1)
  sub=$(ffprobe -nostdin -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 "rtsp://root:$RECETTE_PASS@$CAM:554/video1" 2>&1 | mask | head -n 1)
  case "$main" in *,*,*) ;; *) hres CLEANUP-1124 video-main-sub FAIL "main stream: $main"; return ;; esac
  case "$sub" in *,*,*) hres CLEANUP-1124 video-main-sub PASS "main $main; sub $sub (640x360 when RTSP_SUBSTREAM is on)" ;;
    *) hres CLEANUP-1124 video-main-sub SKIP "main $main; sub stream not answering: $sub" ;; esac
}

h_mdns() {
  command -v avahi-browse >/dev/null 2>&1 || { hres SMALL-B-1124 mdns-txt SKIP "no avahi-browse on this machine (Linux: avahi-utils)"; return; }
  txt=$(avahi-browse -rtp -t _rtsp._tcp 2>/dev/null | grep 'fw=' | head -n 1)
  case "$txt" in
    *model=*load=*rssi=*) hres SMALL-B-1124 mdns-txt PASS "TXT has model, fw, load, rssi" ;;
    *) hres SMALL-B-1124 mdns-txt FAIL "no _rtsp._tcp record with model/fw/load/rssi (MDNS_INFO=1?)" ;;
  esac
}

h_open_time() {
  command -v ffprobe >/dev/null 2>&1 || { hres W3-ZERO open-time SKIP "no ffprobe on this machine"; return; }
  [ "$PASS_OK" = 1 ] || { hres W3-ZERO open-time SKIP "RECETTE_PASS not set"; return; }
  _idle=${RECETTE_IDLE_S:-60}; times=; bad=0; _ot_n=0
  while [ "$_ot_n" -lt 5 ]; do
    _ot_n=$((_ot_n + 1)); sleep "$_idle"
    t0=$(date +%s)
    ffprobe -nostdin -v error -rtsp_transport tcp -select_streams v:0 -read_intervals '%+#1' -show_entries frame=pict_type -of csv=p=0 "rtsp://root:$RECETTE_PASS@$CAM:554/video0" >/dev/null 2>&1 || bad=$((bad + 1))
    t1=$(date +%s)
    times="$times $((t1 - t0))s"
  done
  if [ "$bad" = 0 ]; then hres W3-ZERO open-time PASS "5 opens after $_idle s idle, PLAY to first frame:$times (whole seconds; compare with the old build)"
  else hres W3-ZERO open-time FAIL "$bad of 5 opens gave no frame; times:$times"; fi
}

# mq_setup: the broker settings go to a mosquitto options file in a mode-700 folder (XDG_CONFIG_HOME), not to argv.
# The file holds one command-line option per line, with its dash (-h, -p, -u, -P), as mosquitto 2.x reads them from
# $XDG_CONFIG_HOME/mosquitto_pub and mosquitto_sub. A password with spaces does not fit this format: use a plain one.
# The folder is removed at exit.
mq_setup() {
  MQX=$TMPD/xdg; mkdir -p "$MQX/"; chmod 700 "$MQX"
  umask 077
  {
    printf '%s\n' "-h $RECETTE_MQTT_HOST"
    printf '%s\n' "-p ${RECETTE_MQTT_PORT:-1883}"
    [ -n "${RECETTE_MQTT_USER:-}" ] && printf '%s\n' "-u $RECETTE_MQTT_USER"
    [ -n "${RECETTE_MQTT_PASS:-}" ] && printf '%s\n' "-P $RECETTE_MQTT_PASS"
  } > "$MQX/mosquitto_pub"
  cp "$MQX/mosquitto_pub" "$MQX/mosquitto_sub"
  chmod 600 "$MQX/mosquitto_pub" "$MQX/mosquitto_sub"
  XDG_CONFIG_HOME=$MQX; export XDG_CONFIG_HOME
}

h_mqtt_retained() {
  if [ -z "${RECETTE_MQTT_HOST:-}" ] || [ -z "${RECETTE_MQTT_ROOT:-}" ] || ! command -v mosquitto_pub >/dev/null 2>&1; then
    hres R3-MQTT retained-command SKIP "needs RECETTE_MQTT_HOST, RECETTE_MQTT_ROOT and mosquitto_pub"; return
  fi
  mq_setup
  CMD_TOPIC=$RECETTE_MQTT_ROOT/command; RES_TOPIC=$RECETTE_MQTT_ROOT/command/result
  # 1. a retained harmless command. From here the retained message is cleared on any exit (cleanup).
  RETAINED_SET=1
  mosquitto_pub -t "$CMD_TOPIC" -r -m '{"cmd":"snapshot"}'
  # 2. the result subscription starts BEFORE the bridge restart: a result for the retained command must be caught
  mosquitto_sub -t "$RES_TOPIC" -v -W 40 > "$TMPD/res1.out" 2>/dev/null &
  SUB1=$!
  sleep 2
  before=$(ssh_cam "grep -c 'retained command ignored' /tmp/log/mqtt-bridge.log 2>/dev/null")
  ssh_cam '/mnt/controlscripts/mqtt-bridge restart' >/dev/null 2>&1
  wait "$SUB1" 2>/dev/null
  got=$(cat "$TMPD/res1.out" 2>/dev/null)
  after=$(ssh_cam "grep -c 'retained command ignored' /tmp/log/mqtt-bridge.log 2>/dev/null")
  delta=$(( ${after:-0} - ${before:-0} ))
  # 3. a live (not retained) command runs at once
  mosquitto_sub -t "$RES_TOPIC" -C 1 -W 15 > "$TMPD/live.out" 2>/dev/null &
  SUB2=$!
  sleep 1
  mosquitto_pub -t "$CMD_TOPIC" -m '{"cmd":"snapshot"}'
  wait "$SUB2" 2>/dev/null
  live=$(cat "$TMPD/live.out" 2>/dev/null)
  # 4. clear the retained message
  mosquitto_pub -t "$CMD_TOPIC" -r -n
  RETAINED_SET=0
  if [ -z "$got" ] && [ "$delta" -ge 1 ] && [ -n "$live" ]; then
    hres R3-MQTT retained-command PASS "retained snapshot not run (ignored lines +$delta), no result for it, live snapshot answered, retained message cleared"
  else
    hres R3-MQTT retained-command FAIL "result after the retained command: '${got:-none}'; ignored lines +${delta}; live answer: '${live:-none}'"
  fi
}

h_mqtt_two() {
  if [ -z "${RECETTE_MQTT_HOST:-}" ] || [ -z "${RECETTE_MQTT_ROOT:-}" ] || ! command -v mosquitto_sub >/dev/null 2>&1; then
    hres SMALL-A-1124 mqtt-two-events SKIP "needs RECETTE_MQTT_HOST, RECETTE_MQTT_ROOT and mosquitto_sub"; return
  fi
  mq_setup
  mosquitto_sub -t "$RECETTE_MQTT_ROOT/recette/r5/#" -v -W 30 > "$TMPD/r5.out" 2>/dev/null &
  SUBPID=$!
  sleep 2
  ssh_cam_in 'sh -s' <<'REMOTE' >"$TMPD/r5.remote" 2>&1
grep -q '^MQTT_ENABLE=1' /mnt/config/mqtt.conf 2>/dev/null || { echo "MQTT_OFF"; exit 0; }
P=$(head -c 2500 /dev/zero | tr '\0' a)
/mnt/scripts/mqtt-bridge.sh publish recette/r5/a "{\"r5\":\"a\",\"p\":\"$P\"}" 0 &
/mnt/scripts/mqtt-bridge.sh publish recette/r5/b "{\"r5\":\"b\",\"p\":\"$P\"}" 0 &
wait
echo "PUBLISHED"
REMOTE
  wait "$SUBPID" 2>/dev/null
  if grep -q MQTT_OFF "$TMPD/r5.remote" 2>/dev/null; then hres SMALL-A-1124 mqtt-two-events SKIP "MQTT_ENABLE is not 1 on the camera"; return; fi
  a=$(grep -c 'r5":"a' "$TMPD/r5.out"); b=$(grep -c 'r5":"b' "$TMPD/r5.out")
  if [ "${a:-0}" -ge 1 ] && [ "${b:-0}" -ge 1 ]; then hres SMALL-A-1124 mqtt-two-events PASS "both events of 2.5 KB reached the broker at once (a=$a, b=$b)"
  else hres SMALL-A-1124 mqtt-two-events FAIL "events seen at the broker: a=${a:-0}, b=${b:-0}"; fi
}

h_lockout() {
  [ "$PASS_OK" = 1 ] || { hres AUDIT-1116-NET lockout-10 SKIP "RECETTE_PASS not set"; return; }
  mk_cfg
  url="http://$CAM/cgi-bin/state.cgi?cmd=daynight"
  base=$(curl -s -K "$CFG" -o /dev/null -w '%{http_code}' "$url")
  _lk_n=0; wrong=
  while [ "$_lk_n" -lt 10 ]; do
    _lk_n=$((_lk_n + 1))
    c=$(curl -s -o /dev/null -w '%{http_code}' -u "root:recette-wrong-$_lk_n" "$url"); wrong="$wrong $c"
  done
  locked=$(curl -s -K "$CFG" -o /dev/null -w '%{http_code}' "$url")
  # the camera's own call (127.0.0.1) is never locked: the right login from inside the camera, during the lock
  cp "$CFG" "$TMPD/lock.cfg"
  inside=$(ssh_cam_in 'umask 077; f=/tmp/recette-lock.cfg; cat > $f; curl -s -K $f -o /dev/null -w %{http_code} "http://127.0.0.1/cgi-bin/state.cgi?cmd=daynight"; rm -f $f' < "$TMPD/lock.cfg" 2>/dev/null)
  sleep "${RECETTE_LOCK_WAIT_S:-310}"
  after=$(curl -s -K "$CFG" -o /dev/null -w '%{http_code}' "$url")
  ev="baseline $base; 10 wrong logins:$wrong; right login from this host during the lock: $locked; from the camera (127.0.0.1): $inside; after the wait: $after"
  if [ "$base" = 200 ] && [ "$locked" != 200 ] && [ "$inside" = 200 ] && [ "$after" = 200 ]; then
    hres AUDIT-1116-NET lockout-10 PASS "$ev"
  else
    hres AUDIT-1116-NET lockout-10 FAIL "$ev (WEB_LOCKOUT=1 expected; the lock is 10 in 300 s)"
  fi
}

# ---------------------------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------------------------
RESN=0
echo "== recette-host: camera $CAM, results in $OUTD"
if ! ssh_cam 'echo ok' >/dev/null 2>&1; then
  echo "camera $CAM not reachable over ssh (key, address, LAN): camera checks cannot run" >&2
  hres RECETTE-BENCH preflight FAIL "ssh to $CAM failed"
  exit 1
fi

# the host checks, in the order of the table (the lockout is last)
printf '%s\n' "$HOST_CHECKS" > "$TMPD/host.txt"
while IFS='|' read -r id name fn needs <&3; do
  selected "$id" || continue
  "$fn"
done 3< "$TMPD/host.txt"

# the bench on the camera, detached
if ssh_cam 'true'; then
  # the camera has no scp (Dropbear): the file goes over ssh, read from stdin by cat
  ssh_cam_in 'umask 022; cat > /tmp/recette.sh' < "$HERE/recette.sh" || { hres RECETTE-BENCH copy FAIL "copy of recette.sh over ssh failed"; }
  if [ "$PASS_OK" = 1 ]; then
    printf '%s\n' "$RECETTE_PASS" | ssh_cam_in 'umask 077; cat > /tmp/recette.pass'
  fi
  args=
  [ -n "$ONLY" ] && args="$args --only $ONLY"
  [ "$DISRUPT" = 1 ] && args="$args --disruptive"
  [ "$WIFI" = 1 ] && args="$args --wifi"
  ssh_cam "mkdir -p $RUN; cd /tmp; ${RECETTE_CAMERA_ARGS:-} nohup sh /tmp/recette.sh --out $RUN $args </dev/null >$RUN/console.txt 2>&1 &" \
    || hres RECETTE-BENCH start FAIL "could not start the bench"
  echo "== bench started on the camera: $RUN (detached; polling every 60 s)"
  waited=0; limit=${RECETTE_TIMEOUT_S:-14400}
  while [ "$waited" -lt "$limit" ] && [ "$waited" -lt 86400 ]; do
    sleep 60; waited=$((waited + 60))
    if ssh_cam "test -f $RUN/done" 2>/dev/null; then break; fi
    n=$(ssh_cam "grep -c RESULT $RUN/results.txt 2>/dev/null" 2>/dev/null)
    echo "   ... $waited s, camera results so far: ${n:-?}"
  done
  if ssh_cam "test -f $RUN/done" 2>/dev/null; then
    # fetched with cat over ssh (no scp on the camera); a file that is missing is reported, not a fatal error
    for f in results.txt recette.log summary.txt; do
      ssh_cam "cat $RUN/$f" > "$OUTD/$f" 2>/dev/null || { rm -f "$OUTD/$f"; echo "could not fetch $RUN/$f" >&2; }
    done
    echo "== camera bench finished; files in $OUTD"
  else
    hres RECETTE-BENCH finished FAIL "no done file after $limit s; results so far are on the camera in $RUN"
    echo "bench still running or stopped: $RUN on the camera" >&2
  fi
  ssh_cam 'rm -f /tmp/recette.pass' >/dev/null 2>&1
fi

echo
echo "== recette summary: host checks (this machine) and camera checks"
cat "$HOSTRES"
[ -f "$OUTD/results.txt" ] && grep '^RESULT ' "$OUTD/results.txt"
# the counts are the RESULT lines by their status field (field 4), the same rule as the bench's own summary
set -- $(cat "$HOSTRES" "$OUTD/results.txt" 2>/dev/null | awk '$1 == "RESULT" { c[$4]++ } END { printf "%d %d %d", c["PASS"] + 0, c["FAIL"] + 0, c["SKIP"] + 0 }')
P=$1; F=$2; S=$3
echo "PASS $P  FAIL $F  SKIP $S   (results: $OUTD)"
[ "$F" = 0 ] && exit 0 || exit 1
