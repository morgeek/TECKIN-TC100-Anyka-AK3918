#!/bin/sh
# JSON configuration export/import with strict validation and an all-or-rollback commit.

# Keep the raw JSON body available to this CGI; func.cgi otherwise consumes POST data.
FUNC_CGI_SKIP_BODY=1
export FUNC_CGI_SKIP_BODY
if [ -r /mnt/www/cgi-bin/func.cgi ]; then
  . /mnt/www/cgi-bin/func.cgi
else
  . ./func.cgi
fi

if [ -r "${CONFIG_TX_LIB:-/mnt/scripts/config-transaction.sh}" ]; then
  . "${CONFIG_TX_LIB:-/mnt/scripts/config-transaction.sh}"
elif [ -r ../../scripts/config-transaction.sh ]; then
  . ../../scripts/config-transaction.sh
else
  json_error "Configuration validator is unavailable" "service_unavailable" 503
  exit 0
fi

rate_limit_check 10 60
CONFIG_ROOT="${TC_CONFIG_ROOT:-/mnt/config}"
JQ_BIN="${JQ_BIN:-/mnt/bin/jq}"
[ -x "$JQ_BIN" ] || JQ_BIN="$(command -v jq 2>/dev/null)"

output_json_header() {
  echo "Content-type: application/json"
  echo "Pragma: no-cache"
  echo "Cache-Control: no-store, no-cache"
}

_ce_cleanup() {
  rm -rf "${_ce_json:-}" "${_ce_rows:-}" "${_ce_stage:-}" "${_ce_backup:-}" 2>/dev/null || true
}

_ce_fail() {
  _ce_message="$1"; _ce_code="${2:-INVALID_CONFIG}"
  _ce_cleanup
  json_body_err "$_ce_code" "$_ce_message"
  exit 0
}

_ce_truthy() {
  case "$1" in 1|true|on|yes|enabled) echo 1 ;; *) echo 0 ;; esac
}

_ce_add_file() {
  case " $_ce_files " in *" $1 "*) ;; *) _ce_files="$_ce_files $1" ;; esac
}

_ce_prepare_file() {
  _ce_rel="$1"; _ce_dest="$_ce_stage/$_ce_rel"
  [ -f "$_ce_dest" ] && return 0
  mkdir -p "${_ce_dest%/*}" || return 1
  if [ -f "$CONFIG_ROOT/$_ce_rel" ]; then
    cp "$CONFIG_ROOT/$_ce_rel" "$_ce_dest"
  elif [ -f "$CONFIG_ROOT/${_ce_rel}.dist" ]; then
    cp "$CONFIG_ROOT/${_ce_rel}.dist" "$_ce_dest"
  else
    case "$_ce_rel" in hostname.conf|timezone.conf|ntp_srv.conf) : > "$_ce_dest" ;; *) return 1 ;; esac
  fi
}

_ce_build_rows() {
  "$JQ_BIN" -r '
    def row($f;$m;$s;$k;$t;$c;$v):
      if $v == null then empty else [$f,$m,$s,$k,$t,$c,($v|tostring|@uri)] | join("|") end;
    row("boot.conf";"flat";"root";"WEB_MODE";"web_mode";"network";.boot.web_mode),
    row("boot.conf";"flat";"root";"STREAM_TOPOLOGY";"topology";"general";.boot.topology),
    row("boot.conf";"flat";"root";"ULTRALITE_HTTP_PORT";"port";"network";.boot.ultralite_port),
    row("boot.conf";"flat";"root";"LIGHTWEIGHT_MODE";"bool";"general";.boot.lightweight_mode),
    row("boot.conf";"flat";"root";"SECURITY_HARDENING_MODE";"bool";"general";.boot.security_hardening),
    row("service_trim.conf";"flat";"root";"SERVICE_TRIM";"bool";"general";.boot.service_trim),

    row("rtspserver.conf";"ini";"root";"PORT";"port";"network";.video.rtsp_port),
    row("rtspserver.conf";"ini";"0";"codec";"video_codec";"general";.video.main.codec),
    row("rtspserver.conf";"ini";"0";"profile";"profile";"general";.video.main.profile),
    row("rtspserver.conf";"ini";"0";"width";"width";"general";.video.main.width),
    row("rtspserver.conf";"ini";"0";"height";"height";"general";.video.main.height),
    row("rtspserver.conf";"ini";"0";"fps";"fps";"general";.video.main.fps),
    row("rtspserver.conf";"ini";"0";"bps";"bitrate";"general";.video.main.bitrate),
    row("rtspserver.conf";"ini";"0";"goplen";"gop";"general";.video.main.gop),
    row("rtspserver.conf";"ini";"0";"brmode";"bool";"general";.video.main.format),
    row("rtspserver.conf";"ini";"0";"minqp";"qp";"general";.video.main.minqp),
    row("rtspserver.conf";"ini";"0";"maxqp";"qp";"general";.video.main.maxqp),
    row("rtspserver.conf";"ini";"0";"smartmode";"bool";"general";.video.main.smartmode),
    row("rtspserver.conf";"ini";"0";"smartgoplen";"gop";"general";.video.main.smartgoplen),
    row("rtspserver.conf";"ini";"0";"smartquality";"smartquality";"general";.video.main.smartquality),
    row("rtspserver.conf";"ini";"0";"smartstatic";"smartstatic";"general";.video.main.smartstatic),
    row("rtspserver.conf";"ini";"0";"maxkbps";"bitrate";"general";.video.main.maxkbps),
    row("rtspserver.conf";"ini";"0";"targetkbps";"bitrate";"general";.video.main.targetkbps),
    row("rtspserver.conf";"ini";"1";"codec";"video_codec";"general";.video.sub.codec),
    row("rtspserver.conf";"ini";"1";"profile";"profile";"general";.video.sub.profile),
    row("rtspserver.conf";"ini";"1";"width";"width";"general";.video.sub.width),
    row("rtspserver.conf";"ini";"1";"height";"height";"general";.video.sub.height),
    row("rtspserver.conf";"ini";"1";"fps";"fps";"general";.video.sub.fps),
    row("rtspserver.conf";"ini";"1";"bps";"bitrate";"general";.video.sub.bitrate),
    row("rtspserver.conf";"ini";"1";"goplen";"gop";"general";.video.sub.gop),
    row("rtspserver.conf";"ini";"1";"brmode";"bool";"general";.video.sub.format),
    row("rtspserver.conf";"ini";"1";"minqp";"qp";"general";.video.sub.minqp),
    row("rtspserver.conf";"ini";"1";"maxqp";"qp";"general";.video.sub.maxqp),
    row("rtspserver.conf";"ini";"1";"smartmode";"bool";"general";.video.sub.smartmode),
    row("rtspserver.conf";"ini";"1";"smartgoplen";"gop";"general";.video.sub.smartgoplen),
    row("rtspserver.conf";"ini";"1";"smartquality";"smartquality";"general";.video.sub.smartquality),
    row("rtspserver.conf";"ini";"1";"smartstatic";"smartstatic";"general";.video.sub.smartstatic),
    row("rtspserver.conf";"ini";"1";"maxkbps";"bitrate";"general";.video.sub.maxkbps),
    row("rtspserver.conf";"ini";"1";"targetkbps";"bitrate";"general";.video.sub.targetkbps),
    row("rtspserver.conf";"ini";"root";"imageflip";"flip";"general";.video.flip),
    row("rtspserver.conf";"ini";"root";"RTSPLOGENABLED";"bool";"general";.video.rtsp_log),

    row("rtspserver.conf";"ini";"root";"samplerate";"samplerate";"general";.audio.samplerate),
    row("rtspserver.conf";"ini";"root";"volume";"volume";"general";.audio.volume),
    row("rtspserver.conf";"ini";"2";"codec";"codec";"general";.audio.codec_main),
    row("rtspserver.conf";"ini";"3";"codec";"codec";"general";.audio.codec_sub),

    row("rtspserver.conf";"ini";"root";"daynightlum";"lum";"general";.isp.daynight_lum),
    row("rtspserver.conf";"ini";"root";"daynightawb";"awb";"general";.isp.daynight_awb),
    row("rtspserver.conf";"ini";"root";"nightdaylum";"lum";"general";.isp.nightday_lum),
    row("rtspserver.conf";"ini";"root";"nightdayawb";"awb";"general";.isp.nightday_awb),
    row("rtspserver.conf";"ini";"root";"osdenabled";"bool";"general";.osd.enabled),
    row("rtspserver.conf";"ini";"root";"osdtext";"osd_text";"general";.osd.text),
    row("rtspserver.conf";"ini";"root";"osdalpha";"color";"general";.osd.alpha),
    row("rtspserver.conf";"ini";"0";"osdfontsize";"fontsize";"general";.osd.fontsize0),
    row("rtspserver.conf";"ini";"root";"osdfrontcolor";"color";"general";.osd.frontcolor),
    row("rtspserver.conf";"ini";"root";"osdbackcolor";"color";"general";.osd.backcolor),
    row("rtspserver.conf";"ini";"root";"osdedgecolor";"color";"general";.osd.edgecolor),
    row("rtspserver.conf";"ini";"0";"osdx";"coordinate";"general";.osd.x0),
    row("rtspserver.conf";"ini";"0";"osdy";"coordinate";"general";.osd.y0),

    row("mqtt.conf";"flat";"root";"MQTT_ENABLE";"bool";"general";.mqtt.enabled),
    row("mqtt.conf";"flat";"root";"MQTT_HOST";"host";"network";.mqtt.host),
    row("mqtt.conf";"flat";"root";"MQTT_PORT";"port";"network";.mqtt.port),
    row("mqtt.conf";"flatq";"root";"MQTT_USER";"credential_optional";"credential";.mqtt.user),
    row("mqtt.conf";"flat";"root";"MQTT_TOPIC_ROOT";"topic";"general";.mqtt.topic_root),
    row("mqtt.conf";"flat";"root";"MQTT_HA_DISCOVERY_ENABLE";"bool";"general";.mqtt.discovery),
    row("mqtt.conf";"flat";"root";"MQTT_HA_DISCOVERY_PREFIX";"topic";"general";.mqtt.discovery_prefix),

    row("recording.conf";"flat";"root";"rec_postrecord_sec";"record_post";"general";.recording.postrec),
    row("recording.conf";"flat";"root";"rec_file_duration_sec";"record_duration";"general";.recording.maxduration),
    row("recording.conf";"flat";"root";"rec_reserverd_disk_mb";"disk_mb";"general";.recording.reserved_mb),
    row("recording.conf";"flat";"root";"rec_motion_activated";"bool";"general";.recording.motion_activated),

    row("hostname.conf";"single";"root";"value";"hostname";"network";.system.hostname),
    row("timezone.conf";"single";"root";"value";"timezone";"network";.system.timezone),
    row("ntp_srv.conf";"single";"root";"value";"host";"network";.system.ntp_server),
    row("boot.conf";"flat";"root";"REBOOT_SCHEDULE_ENABLE";"bool";"general";.system.reboot_schedule.enable),
    row("boot.conf";"flat";"root";"REBOOT_SCHEDULE_HOUR";"hour";"general";.system.reboot_schedule.hour),
    row("boot.conf";"flat";"root";"REBOOT_SCHEDULE_MINUTE";"minute";"general";.system.reboot_schedule.min),
    row("boot.conf";"flat";"root";"REBOOT_SCHEDULE_WEEKDAY";"weekday";"general";.system.reboot_schedule.dow),

    row("telnetd.conf";"flat";"root";"TELNET_PORT";"port";"network";.services.telnet_port),
    row("sound_detection.conf";"flat";"root";"ENABLE";"bool";"general";.services.sound_det_enable),
    row("sound_detection.conf";"flat";"root";"THRESHOLD";"sound_threshold";"general";.services.sound_det_threshold),
    row("sound_detection.conf";"flat";"root";"INTERVAL";"sound_interval";"general";.services.sound_det_interval),
    row("rtspserver.conf";"ini";"root";"mdsens";"motion_sens";"general";.services.motion_sens),
    row("motion.conf";"flat";"root";"motion_trigger_led";"bool";"general";.services.motion_led),

    row("telegram.conf";"flat";"root";"TELEGRAM_ENABLE";"bool";"general";.telegram.enabled),
    row("telegram.conf";"flatq";"root";"apiToken";"credential_optional";"credential";.telegram.token),
    row("telegram.conf";"flatq";"root";"userChatId";"credential_optional";"credential";.telegram.chat_id),
    row("boot.conf";"flat";"root";"SYSLOG_ENABLE";"bool";"general";.syslog.enabled),
    row("boot.conf";"flat";"root";"SYSLOG_HOST";"host_optional";"network";.syslog.host),
    row("boot.conf";"flat";"root";"SYSLOG_PORT";"port";"network";.syslog.port),
    row("boot.conf";"flat";"root";"FRONT_LED";"bool";"general";.peripherals.led_front),
    row("boot.conf";"flat";"root";"RED_LED";"bool";"general";.peripherals.led_red),
    row("boot.conf";"flat";"root";"PRIVACY_MODE";"bool";"general";.peripherals.privacy)
  ' "$_ce_json" > "$_ce_rows"
}

_ce_import() {
  _ce_cl="${CONTENT_LENGTH:-0}"
  case "$_ce_cl" in ''|*[!0-9]*) _ce_fail "Invalid content length" "INVALID_PAYLOAD" ;; esac
  [ "$_ce_cl" -gt 0 ] || _ce_fail "No JSON data received" "EMPTY_PAYLOAD"
  [ "$_ce_cl" -le 65536 ] || _ce_fail "JSON configuration exceeds 64 KB" "PAYLOAD_TOO_LARGE"
  [ -n "$JQ_BIN" ] && [ -x "$JQ_BIN" ] || _ce_fail "JSON parser is unavailable" "SERVICE_UNAVAILABLE"

  _ce_json="/tmp/config-import.$$.json"
  _ce_rows="/tmp/config-import.$$.rows"
  _ce_stage="/tmp/config-import-stage.$$"
  _ce_backup="/tmp/config-import-rollback.$$"
  mkdir -p "$_ce_stage" || _ce_fail "Cannot allocate import staging area" "STAGING_FAILED"
  head -c "$_ce_cl" > "$_ce_json" 2>/dev/null
  _ce_got="$(wc -c < "$_ce_json" 2>/dev/null)"
  set -- $_ce_got; _ce_got="${1:-0}"
  [ "$_ce_got" = "$_ce_cl" ] || _ce_fail "Incomplete JSON upload" "INCOMPLETE_PAYLOAD"
  "$JQ_BIN" -e 'type == "object"' "$_ce_json" >/dev/null 2>&1 || _ce_fail "Malformed JSON configuration" "INVALID_JSON"
  _ce_build_rows || _ce_fail "Unsupported JSON values" "INVALID_JSON"

  _ce_exclude_network="$(_ce_truthy "${F_exclude_network:-0}")"
  _ce_exclude_credentials="$(_ce_truthy "${F_exclude_credentials:-0}")"
  _ce_files=""; _ce_values=0; _ce_skipped=0
  while IFS='|' read -r _ce_rel _ce_mode _ce_section _ce_key _ce_type _ce_category _ce_encoded; do
    [ -n "$_ce_rel" ] || continue
    if { [ "$_ce_category" = network ] && [ "$_ce_exclude_network" = 1 ]; } || { [ "$_ce_category" = credential ] && [ "$_ce_exclude_credentials" = 1 ]; }; then
      _ce_skipped=$((_ce_skipped + 1)); continue
    fi
    _ce_value="$(urldecode "$_ce_encoded")"
    tc_normalize_and_validate "$_ce_type" "$_ce_value" || _ce_fail "Invalid value for ${_ce_rel}:${_ce_key}" "VALIDATION_FAILED"
    _ce_value="$TC_NORMALIZED_VALUE"
    _ce_prepare_file "$_ce_rel" || _ce_fail "Missing base configuration: $_ce_rel" "CONFIG_NOT_FOUND"
    case "$_ce_mode" in
      flat) tc_set_flat "$_ce_stage/$_ce_rel" "$_ce_key" "$_ce_value" ;;
      flatq) tc_set_flat "$_ce_stage/$_ce_rel" "$_ce_key" "'$_ce_value'" ;;
      ini) tc_set_ini "$_ce_stage/$_ce_rel" "$_ce_section" "$_ce_key" "$_ce_value" ;;
      single) printf '%s\n' "$_ce_value" > "$_ce_stage/$_ce_rel" ;;
      *) false ;;
    esac || _ce_fail "Cannot stage ${_ce_rel}:${_ce_key}" "STAGING_FAILED"
    _ce_add_file "$_ce_rel"
    _ce_values=$((_ce_values + 1))
  done < "$_ce_rows"

  [ "$_ce_values" -gt 0 ] || _ce_fail "No applicable configuration values found" "EMPTY_CONFIG"
  tc_commit_config_files "$_ce_stage" "$CONFIG_ROOT" "$_ce_backup" "$_ce_files" || _ce_fail "Import rejected (${TC_CONFIG_ERROR:-transaction failed}); active configuration was preserved" "TRANSACTION_FAILED"
  _ce_changed="$TC_COMMIT_COUNT"
  _ce_cleanup

  if [ "$_ce_changed" -gt 0 ]; then
    (
      sleep 2
      [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x restart >/dev/null 2>&1 || true
      [ -x /mnt/controlscripts/mqtt-bridge ] && /mnt/controlscripts/mqtt-bridge restart >/dev/null 2>&1 || true
    ) >/dev/null 2>&1 &
  fi
  printf '{"ok":true,"applied":%d,"changed_files":%d,"skipped":%d,"transactional":true}\n' "$_ce_values" "$_ce_changed" "$_ce_skipped"
}

case "$F_cmd" in
  export)
    _ce_now="$(date +%Y%m%d_%H%M%S)"
    output_json_header
    echo "Content-Disposition: attachment; filename=tc100_config_${_ce_now}.json"
    echo ""
    QUERY_STRING="cmd=fullconfig" F_cmd="fullconfig" sh ./state.cgi | sed '1,/^$/d'
    ;;
  import)
    mutation_guard
    output_json_header
    echo ""
    _ce_import
    ;;
  *)
    output_json_header
    echo ""
    json_body_err "UNKNOWN_COMMAND" "Command '$F_cmd' not recognized"
    ;;
esac
