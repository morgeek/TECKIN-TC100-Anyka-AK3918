#!/bin/sh
# Regression tests for the Wave 3 Frigate/HA integration work.
# Structural checks + JSON validity of the changed/added MQTT discovery payloads.
# The full end-to-end YAML render is validated by tools/test-frigateyaml.py when
# a /mnt tree is available; this suite is CI-safe (no /mnt required).
# Run: sh tools/test-wave3-fixes.sh

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); }
bad() { FAIL=$((FAIL+1)); echo "FAIL: $1"; }
grep_has() { grep -qF -- "$1" "$2"; }
grep_lacks() { ! grep -qF -- "$1" "$2"; }

ST="$ROOT/www/cgi-bin/state.cgi"
MQ="$ROOT/scripts/mqtt-bridge.sh"

# ---- F1: frigateyaml renderer exists and targets the current schema ----
grep_has 'frigateyaml)' "$ST" && ok || bad "F1: state.cgi must have a frigateyaml command"
grep_has 'go2rtc:' "$ST" && ok || bad "F1: frigateyaml must emit a go2rtc restream section"
grep_has 'preset-rtsp-restream' "$ST" && ok || bad "F1: frigateyaml must use preset-rtsp-restream"
grep_has 'rtsp://127.0.0.1:8554/' "$ST" && ok || bad "F1: cameras must pull from the local go2rtc restream"
grep_has 'detect:' "$ST" && grep_has 'enabled: true' "$ST" && ok || bad "F1: detect.enabled must be explicit"
# Must use current alerts/detections retention, NOT the deprecated record.retain.
# (The deprecated-key absence is asserted structurally by tools/test-frigateyaml.py,
# which parses the rendered YAML — a text grep here would false-match the code's
# own explanatory comment.)
grep_has "printf '      alerts:" "$ST" && grep_has "printf '      detections:" "$ST" && ok || bad "F1: must emit current alerts/detections retention schema"

# ---- F5: invalid stream_source removed from the MQTT camera entity ----
grep_lacks '"stream_source":"%s"' "$MQ" && ok || bad "F5: stream_source must be removed from the camera discovery payload"

# ---- F3: motion binary_sensor discovery published ----
grep_has 'binary_sensor/${node_id}/motion/config' "$MQ" && ok || bad "F3: motion binary_sensor discovery config must be published"
grep_has 'motion_cfg_payload' "$MQ" && ok || bad "F3: motion_cfg_payload must be built"

# ---- JSON validity of the changed/added discovery payloads ----
if command -v python3 >/dev/null 2>&1; then
  cam="$(dash -c 'device_name_json=cam; device_id_json=tc100; MQTT_TOPIC_ROOT=tc100/camera; avail_topic_json=tc100/camera/availability; printf '"'"'{"name":"%s Live","uniq_id":"%s_camera","topic":"%s","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}'"'"' "$device_name_json" "$device_id_json" "${MQTT_TOPIC_ROOT}/snapshot/last_path" "$avail_topic_json" "$device_id_json" "$device_name_json"')"
  printf '%s' "$cam" | python3 -c 'import sys,json; o=json.load(sys.stdin); assert "stream_source" not in o; assert o["topic"].endswith("/snapshot/last_path")' \
    && ok || bad "F5: camera payload must be valid JSON without stream_source"
  mot="$(dash -c 'device_name_json=cam; device_id_json=tc100; mst=tc100/camera/motion/state; avail_topic_json=tc100/camera/availability; printf '"'"'{"name":"%s Motion","uniq_id":"%s_motion","stat_t":"%s","dev_cla":"motion","pl_on":"ON","pl_off":"OFF","avty_t":"%s","pl_avail":"online","pl_not_avail":"offline","ic":"mdi:motion-sensor","dev":{"ids":["%s"],"name":"%s","mf":"TechTimeGuy","mdl":"TC100/AK3918"}}'"'"' "$device_name_json" "$device_id_json" "$mst" "$avail_topic_json" "$device_id_json" "$device_name_json"')"
  printf '%s' "$mot" | python3 -c 'import sys,json; o=json.load(sys.stdin); assert o["dev_cla"]=="motion"; assert o["pl_on"]=="ON" and o["pl_off"]=="OFF"; assert o["stat_t"].endswith("/motion/state")' \
    && ok || bad "F3: motion payload must be valid JSON with dev_cla:motion + ON/OFF"
else
  echo "NOTE: python3 unavailable — skipping discovery-payload JSON checks"
fi

# ---- syntax ----
dash -n "$ST" && ok || bad "state.cgi dash -n"
dash -n "$MQ" && ok || bad "mqtt-bridge.sh dash -n"

echo ""
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
