#!/bin/sh
# onvif-notify.sh — Send ONVIF WS-Notification motion event to subscriber URLs.
# Called by motion-event.sh when a motion_on or motion_off event fires.
# Usage: onvif-notify.sh <event_type> <ts_utc>
#   event_type : motion_on | motion_off
#   ts_utc     : ISO 8601 timestamp, e.g. 2024-01-15T12:00:00Z

EVENT_TYPE="${1:-motion_on}"
TS_UTC="${2:-1970-01-01T00:00:00Z}"

CONF_FILE="/mnt/config/onvif_events.conf"
[ -f "$CONF_FILE" ] && . "$CONF_FILE"

: "${ONVIF_EVENT_ENABLE:=0}"
: "${ONVIF_EVENT_SUBSCRIBERS:=}"
: "${ONVIF_EVENT_TIMEOUT:=5}"

case "$ONVIF_EVENT_ENABLE" in
  1|true|on|yes|enabled) ;;
  *) exit 0 ;;
esac

[ -n "$ONVIF_EVENT_SUBSCRIBERS" ] || exit 0

CURL_BIN="/mnt/bin/curl"
[ -x "$CURL_BIN" ] || exit 0

case "$EVENT_TYPE" in
  motion_on)  IS_MOTION="true"  ;;
  motion_off) IS_MOTION="false" ;;
  *)          exit 0 ;;
esac

# Sanitize timeout: digits only, fallback to 5
case "$ONVIF_EVENT_TIMEOUT" in
  ''|*[!0-9]*) ONVIF_EVENT_TIMEOUT=5 ;;
esac
[ "$ONVIF_EVENT_TIMEOUT" -lt 1 ] && ONVIF_EVENT_TIMEOUT=1
[ "$ONVIF_EVENT_TIMEOUT" -gt 30 ] && ONVIF_EVENT_TIMEOUT=30

# Build SOAP envelope — single-quoted heredoc avoids any shell expansion inside XML
SOAP_BODY="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<s:Envelope
    xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\"
    xmlns:wsnt=\"http://docs.oasis-open.org/wsn/b-2\"
    xmlns:wsa=\"http://www.w3.org/2005/08/addressing\"
    xmlns:tt=\"http://www.onvif.org/ver10/schema\"
    xmlns:tns1=\"http://www.onvif.org/ver10/topics\">
  <s:Header>
    <wsa:Action>http://docs.oasis-open.org/wsn/bw-2/NotificationConsumer/Notify</wsa:Action>
  </s:Header>
  <s:Body>
    <wsnt:Notify>
      <wsnt:NotificationMessage>
        <wsnt:Topic Dialect=\"http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet\">tns1:RuleEngine/CellMotionDetector/Motion</wsnt:Topic>
        <wsnt:Message>
          <tt:Message UtcTime=\"${TS_UTC}\" PropertyOperation=\"Changed\">
            <tt:Source>
              <tt:SimpleItem Name=\"VideoSourceConfigurationToken\" Value=\"VideoSourceToken\"/>
              <tt:SimpleItem Name=\"VideoAnalyticsConfigurationToken\" Value=\"VideoAnalyticsToken\"/>
              <tt:SimpleItem Name=\"Rule\" Value=\"MotionDetectorRule\"/>
            </tt:Source>
            <tt:Data>
              <tt:SimpleItem Name=\"IsMotion\" Value=\"${IS_MOTION}\"/>
            </tt:Data>
          </tt:Message>
        </wsnt:Message>
      </wsnt:NotificationMessage>
    </wsnt:Notify>
  </s:Body>
</s:Envelope>"

for url in $ONVIF_EVENT_SUBSCRIBERS; do
  [ -n "$url" ] || continue
  "$CURL_BIN" -s -S \
    --max-time "$ONVIF_EVENT_TIMEOUT" \
    -X POST \
    -H 'Content-Type: application/soap+xml; charset=utf-8' \
    -H 'SOAPAction: "http://docs.oasis-open.org/wsn/bw-2/NotificationConsumer/Notify"' \
    --data-raw "$SOAP_BODY" \
    "$url" >/dev/null 2>&1 || true
done

exit 0
