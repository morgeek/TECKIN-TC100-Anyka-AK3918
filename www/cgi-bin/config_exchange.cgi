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
JSONFLAT="${JSONFLAT:-/mnt/scripts/jsonflat.awk}"

output_json_header() {
  echo "Content-type: application/json"
  echo "Pragma: no-cache"
  echo "Cache-Control: no-store, no-cache"
}

_ce_cleanup() {
  rm -rf "${_ce_json:-}" "${_ce_flat:-}" "${_ce_rows:-}" "${_ce_stage:-}" "${_ce_backup:-}" 2>/dev/null || true
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

# value of NAME in the url-encoded form read from the request body (_ce_form) -> _ce_fv
_ce_form_get() {
  _ce_fv=""
  _ce_oifs="$IFS"; IFS='&'
  set -f
  for _ce_pair in $_ce_form; do
    case "$_ce_pair" in "$1="*) _ce_fv="${_ce_pair#*=}" ;; esac
  done
  set +f
  IFS="$_ce_oifs"
  _ce_fv="$(urldecode "$_ce_fv")"
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
    case "$_ce_rel" in hostname.conf|timezone.conf|ntp_srv.conf|daynight.conf) : > "$_ce_dest" ;; *) return 1 ;; esac
  fi
}

# The one table of the configuration exchange (export AND import read it), one declaration per value:
#   row(file;mode;section;key;validation type;category;.json.path)
#   mode: flat (KEY=value), flatq (KEY='value'), flatd (KEY="value"), ini ([section] key=value),
#         single (a file holding one value), password (config/user.pwd: applied like the web UI password change),
#         wifi (config/wpa_supplicant.conf: section = network index, key = ssid | psk)
#   category: network (per-camera identity: left out by exclude_network=1), credential (secrets: only exported
#         with include_secrets=1, left out of an import by exclude_credentials=1), general
# The import reads the document flattened by scripts/jsonflat.awk (no jq on the flash firmware); a path that is
# absent or null is skipped. Every value goes through tc_normalize_and_validate (scripts/config-transaction.sh):
# several of these files are sourced by shell scripts, so nothing with shell metacharacters gets in.
_ce_row_table() {
  cat <<'ROWS'
    row("boot.conf";"flat";"root";"STREAM_TOPOLOGY";"topology";"general";.boot.topology),
    row("boot.conf";"flat";"root";"LIGHTWEIGHT_MODE";"bool";"general";.boot.lightweight_mode),
    row("boot.conf";"flat";"root";"SECURITY_HARDENING_MODE";"bool";"general";.boot.security_hardening),
    row("service_trim.conf";"flat";"root";"SERVICE_TRIM";"bool";"general";.boot.service_trim),
    row("boot.conf";"flat";"root";"BOOT_GUARD";"bool";"general";.boot.boot_guard),
    row("boot.conf";"flat";"root";"LOG_PERSIST";"bool";"general";.boot.log_persist),
    row("boot.conf";"flat";"root";"LOG_PERSIST_MIN";"persist_min";"general";.boot.log_persist_min),
    row("boot.conf";"flat";"root";"WIFI_QUALITY";"bool";"general";.boot.wifi_quality),
    row("boot.conf";"flat";"root";"WIFI_COUNTRY";"country_optional";"general";.boot.wifi_country),
    row("boot.conf";"flat";"root";"ISP_TUNE";"bool";"general";.boot.isp_tune),

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
    row("rtspserver.conf";"ini";"root";"imageflip";"flip";"network";.video.flip),
    row("rtspserver.conf";"ini";"root";"RTSPLOGENABLED";"bool";"general";.video.rtsp_log),

    row("rtspserver.conf";"ini";"root";"samplerate";"samplerate";"general";.audio.samplerate),
    row("rtspserver.conf";"ini";"root";"volume";"volume";"general";.audio.volume),
    row("rtspserver.conf";"ini";"2";"codec";"codec";"general";.audio.codec_main),
    row("rtspserver.conf";"ini";"3";"codec";"codec";"general";.audio.codec_sub),

    row("rtspserver.conf";"ini";"root";"osdenabled";"bool";"general";.osd.enabled),
    row("rtspserver.conf";"ini";"root";"osdtext";"osd_text";"general";.osd.text),
    row("rtspserver.conf";"ini";"root";"osdalpha";"color";"general";.osd.alpha),
    row("rtspserver.conf";"ini";"0";"osdfontsize";"fontsize";"general";.osd.fontsize0),
    row("rtspserver.conf";"ini";"root";"osdfrontcolor";"color";"general";.osd.frontcolor),
    row("rtspserver.conf";"ini";"root";"osdbackcolor";"color";"general";.osd.backcolor),
    row("rtspserver.conf";"ini";"root";"osdedgecolor";"color";"general";.osd.edgecolor),
    row("rtspserver.conf";"ini";"0";"osdx";"coordinate";"general";.osd.x0),
    row("rtspserver.conf";"ini";"0";"osdy";"coordinate";"general";.osd.y0),

    row("daynight.conf";"flat";"root";"LUMA_NIGHT";"u:0:255";"general";.daynight.luma_night),
    row("daynight.conf";"flat";"root";"LUMA_DAY";"u:0:255";"general";.daynight.luma_day),
    row("daynight.conf";"flat";"root";"DAYNIGHT_SOURCE";"dn_source";"general";.daynight.source),
    row("daynight.conf";"flat";"root";"AE_NIGHT_ABOVE";"u:1:999999999";"general";.daynight.ae_night_above),
    row("daynight.conf";"flat";"root";"AE_DAY_BELOW";"u:0:999999999";"general";.daynight.ae_day_below),
    row("daynight.conf";"flat";"root";"NIGHT_HOLD";"u:1:3600";"general";.daynight.night_hold),
    row("daynight.conf";"flat";"root";"DAY_HOLD";"u:1:3600";"general";.daynight.day_hold),
    row("daynight.conf";"flat";"root";"VENDOR_NIGHT_LUM";"u:1:999999";"general";.daynight.vendor_night_lum),
    row("daynight.conf";"flat";"root";"VENDOR_DAY_LUM";"u:0:999999";"general";.daynight.vendor_day_lum),
    row("daynight.conf";"flat";"root";"IR_LED_MAX_ON";"u:0:172800";"general";.daynight.ir_led_max_on),
    row("daynight.conf";"flat";"root";"NIGHT_STYLE";"bool";"general";.daynight.night_style),
    row("daynight.conf";"flat";"root";"LOWLIGHT_FPS";"bool";"general";.daynight.lowlight_fps),
    row("daynight.conf";"flat";"root";"IR_LED_MODE";"ir_led_mode";"general";.daynight.ir_led_mode),

    row("isp_tune.conf";"flat";"root";"BRIGHTNESS";"isp_effect";"general";.isp.brightness),
    row("isp_tune.conf";"flat";"root";"CONTRAST";"isp_effect";"general";.isp.contrast),
    row("isp_tune.conf";"flat";"root";"SATURATION";"isp_effect";"general";.isp.saturation),
    row("isp_tune.conf";"flat";"root";"SHARPNESS";"isp_effect";"general";.isp.sharpness),
    row("isp_tune.conf";"flat";"root";"HUE";"isp_effect";"general";.isp.hue),
    row("isp_tune.conf";"flat";"root";"POWER_HZ";"isp_power_hz";"general";.isp.power_hz),
    row("isp_tune.conf";"flat";"root";"EXPOSURE_MAX_PCT";"isp_exposure_pct";"general";.isp.exposure_max_pct),
    row("isp_tune.conf";"flat";"root";"MASK_COLOR";"isp_mask_color";"general";.isp.mask_color),
    row("isp_tune.conf";"flat";"root";"MASK1";"isp_mask";"general";.isp.mask1),
    row("isp_tune.conf";"flat";"root";"MASK2";"isp_mask";"general";.isp.mask2),
    row("isp_tune.conf";"flat";"root";"MASK3";"isp_mask";"general";.isp.mask3),
    row("isp_tune.conf";"flat";"root";"MASK4";"isp_mask";"general";.isp.mask4),

    row("mqtt.conf";"flat";"root";"MQTT_ENABLE";"bool";"general";.mqtt.enabled),
    row("mqtt.conf";"flat";"root";"MQTT_HOST";"host";"network";.mqtt.host),
    row("mqtt.conf";"flat";"root";"MQTT_PORT";"port";"network";.mqtt.port),
    row("mqtt.conf";"flat";"root";"MQTT_TOPIC_ROOT";"topic";"network";.mqtt.topic_root),
    row("mqtt.conf";"flat";"root";"MQTT_HA_DISCOVERY_ENABLE";"bool";"general";.mqtt.discovery),
    row("mqtt.conf";"flat";"root";"MQTT_HA_DISCOVERY_PREFIX";"topic";"general";.mqtt.discovery_prefix),
    row("mqtt.conf";"flat";"root";"MQTT_SNAPSHOT_ON_EVENT";"bool";"general";.mqtt.snapshot_on_event),
    row("mqtt.conf";"flat";"root";"MQTT_SNAPSHOT_COOLDOWN_SECONDS";"u:1:3600";"general";.mqtt.snapshot_cooldown_sec),

    row("boot.conf";"flat";"root";"REC_LOCAL";"bool";"general";.recording.local),
    row("boot.conf";"flat";"root";"REC_WHEN";"rec_when";"general";.recording.when),
    row("boot.conf";"flat";"root";"REC_STREAM";"rec_stream";"general";.recording.stream),
    row("boot.conf";"flat";"root";"REC_SEGMENT_SEC";"u:30:3600";"general";.recording.segment_sec),
    row("boot.conf";"flat";"root";"REC_RESERVE_MB";"u:16:65535";"general";.recording.reserve_mb),
    row("boot.conf";"flat";"root";"REC_POSTROLL_SEC";"u:0:3600";"general";.recording.postroll_sec),
    row("boot.conf";"flat";"root";"REC_OFFLINE_SEC";"u:0:3600";"general";.recording.offline_sec),
    row("boot.conf";"flat";"root";"REC_CLIENT";"ipv4_optional";"network";.recording.client),
    row("boot.conf";"flat";"root";"REC_RING_KB";"u:128:8192";"general";.recording.ring_kb),
    row("boot.conf";"flat";"root";"REC_AUDIO";"bool";"general";.recording.audio),

    row("hostname.conf";"single";"root";"value";"hostname";"network";.system.hostname),
    row("timezone.conf";"single";"root";"value";"timezone";"network";.system.timezone),
    row("ntp_srv.conf";"single";"root";"value";"host";"network";.system.ntp_server),
    row("boot.conf";"flat";"root";"REBOOT_SCHEDULE_ENABLE";"bool";"general";.system.reboot_schedule.enable),
    row("boot.conf";"flat";"root";"REBOOT_SCHEDULE_HOUR";"hour";"general";.system.reboot_schedule.hour),
    row("boot.conf";"flat";"root";"REBOOT_SCHEDULE_MINUTE";"minute";"general";.system.reboot_schedule.min),
    row("boot.conf";"flat";"root";"REBOOT_SCHEDULE_WEEKDAY";"weekday";"general";.system.reboot_schedule.dow),

    row("telnetd.conf";"flat";"root";"TELNET_PORT";"port";"network";.services.telnet_port),
    row("sound_detection.conf";"flat";"root";"ENABLE";"bool";"general";.services.sound_det_enable),
    row("sound_detection.conf";"flat";"root";"THRESHOLD_DB";"sound_db";"general";.services.sound_det_threshold),
    row("sound_detection.conf";"flat";"root";"INTERVAL";"sound_interval";"general";.services.sound_det_interval),
    row("sound_detection.conf";"flat";"root";"MIN_LOUD_SECONDS";"u:1:10";"general";.services.sound_det_min_loud),
    row("sound_detection.conf";"flat";"root";"VOX_MODE";"bool";"general";.services.vox_mode),
    row("sound_detection.conf";"flat";"root";"VOX_HOLD_SECONDS";"u:1:3600";"general";.services.vox_hold),
    row("sound_detection.conf";"flat";"root";"ALARM_DETECT";"bool";"general";.services.alarm_detect),
    row("sound_detection.conf";"flat";"root";"ALARM_HOLD_SECONDS";"u:1:3600";"general";.services.alarm_hold),
    row("rtspserver.conf";"ini";"root";"mdsens";"motion_sens";"general";.services.motion_sens),
    row("motion.conf";"flat";"root";"motion_trigger_led";"bool";"general";.services.motion_led),
    row("motion.conf";"flat";"root";"motion_best_shot";"bool";"general";.services.motion_best_shot),

    row("tamper.conf";"flat";"root";"ENABLE";"bool";"general";.tamper.enabled),
    row("tamper.conf";"flat";"root";"TAMPER_HOLD_SEC";"u:1:600";"general";.tamper.hold_sec),
    row("tamper.conf";"flat";"root";"TAMPER_JPEG_DROP_PCT";"u:1:100";"general";.tamper.jpeg_drop_pct),
    row("tamper.conf";"flat";"root";"TAMPER_LUMA_MIN";"u:0:255";"general";.tamper.luma_min),

    row("notify.conf";"flat";"root";"WEBHOOK_ENABLE";"bool";"general";.notify.webhook_enabled),
    row("notify.conf";"flatd";"root";"WEBHOOK_URL";"url_optional";"credential";.notify.webhook_url),
    row("notify.conf";"flatd";"root";"WEBHOOK_METHOD";"http_method";"general";.notify.webhook_method),
    row("notify.conf";"flat";"root";"NTFY_ENABLE";"bool";"general";.notify.ntfy_enabled),
    row("notify.conf";"flatd";"root";"NTFY_URL";"url_optional";"general";.notify.ntfy_url),
    row("notify.conf";"flatd";"root";"NTFY_TOPIC";"ntfy_topic";"credential";.notify.ntfy_topic),
    row("notify.conf";"flatd";"root";"NTFY_PRIORITY";"ntfy_priority";"general";.notify.ntfy_priority),
    row("notify.conf";"flatd";"root";"NTFY_AUTH";"ntfy_auth";"credential";.notify.ntfy_auth),
    row("notify.conf";"flat";"root";"TELEGRAM_NOTIFY_ENABLE";"bool";"general";.notify.telegram_enabled),
    row("notify.conf";"flat";"root";"NOTIFY_ATTACH_SNAPSHOT";"bool";"general";.notify.attach_snapshot),
    row("notify.conf";"flat";"root";"NOTIFY_COOLDOWN_SECONDS";"u:0:86400";"general";.notify.cooldown_sec),
    row("notify.conf";"flatd";"root";"NOTIFY_EVENTS";"events";"general";.notify.events),

    row("telegram.conf";"flat";"root";"TELEGRAM_ENABLE";"bool";"general";.telegram.enabled),
    row("boot.conf";"flat";"root";"SYSLOG_ENABLE";"bool";"general";.syslog.enabled),
    row("boot.conf";"flat";"root";"SYSLOG_HOST";"host_optional";"network";.syslog.host),
    row("boot.conf";"flat";"root";"SYSLOG_PORT";"port";"network";.syslog.port),
    row("boot.conf";"flat";"root";"FRONT_LED";"bool";"general";.peripherals.led_front),
    row("boot.conf";"flat";"root";"RED_LED";"bool";"general";.peripherals.led_red),

    row("boot.conf";"flat";"root";"WIFI_RESCUE";"bool";"general";.wifi_rescue.enabled),
    row("boot.conf";"flat";"root";"WIFI_RESCUE_AFTER_MIN";"u:2:1440";"general";.wifi_rescue.after_min),
    row("boot.conf";"flat";"root";"WIFI_RESCUE_MANUAL_MIN";"u:1:1440";"general";.wifi_rescue.manual_min),
    row("boot.conf";"flatd";"root";"WIFI_RESCUE_SSID";"rescue_ssid_optional";"network";.wifi_rescue.ssid),

    row("mqtt.conf";"flatq";"root";"MQTT_USER";"credential_optional";"credential";.secrets.mqtt_user),
    row("mqtt.conf";"flatq";"root";"MQTT_PASSWORD";"credential_optional";"credential";.secrets.mqtt_password),
    row("telegram.conf";"flatq";"root";"apiToken";"credential_optional";"credential";.secrets.telegram_token),
    row("telegram.conf";"flatq";"root";"userChatId";"credential_optional";"credential";.secrets.telegram_chat_id),
    row("boot.conf";"flatd";"root";"WIFI_RESCUE_PSK";"rescue_psk_optional";"credential";.secrets.wifi_rescue_psk),
    row("user.pwd";"password";"root";"password";"password";"credential";.secrets.camera_password),
    row("wpa_supplicant.conf";"wifi";"0";"ssid";"wifi_ssid";"credential";.secrets.wifi[0].ssid),
    row("wpa_supplicant.conf";"wifi";"0";"psk";"wifi_psk";"credential";.secrets.wifi[0].psk),
    row("wpa_supplicant.conf";"wifi";"1";"ssid";"wifi_ssid";"credential";.secrets.wifi[1].ssid),
    row("wpa_supplicant.conf";"wifi";"1";"psk";"wifi_psk";"credential";.secrets.wifi[1].psk),
    row("wpa_supplicant.conf";"wifi";"2";"ssid";"wifi_ssid";"credential";.secrets.wifi[2].ssid),
    row("wpa_supplicant.conf";"wifi";"2";"psk";"wifi_psk";"credential";.secrets.wifi[2].psk),
    row("wpa_supplicant.conf";"wifi";"3";"ssid";"wifi_ssid";"credential";.secrets.wifi[3].ssid),
    row("wpa_supplicant.conf";"wifi";"3";"psk";"wifi_psk";"credential";.secrets.wifi[3].psk)
ROWS
}

_ce_build_rows() {
  _ce_row_table | LC_ALL=C awk -F '\t' '
    BEGIN { for (i = 1; i < 256; i++) ord[sprintf("%c", i)] = i }
    function unesc(v,   o, i, c, n) {
      o = ""
      for (i = 1; i <= length(v); i++) {
        c = substr(v, i, 1)
        if (c == "\\") { n = substr(v, i + 1, 1); i++
          if (n == "n") c = "\n"; else if (n == "t") c = "\t"; else c = n }
        o = o c
      }
      return o
    }
    function uri(v,   o, i, c) {
      o = ""
      for (i = 1; i <= length(v); i++) {
        c = substr(v, i, 1)
        if (c ~ /[A-Za-z0-9_.~-]/) o = o c; else o = o sprintf("%%%02X", ord[c])
      }
      return o
    }
    # Numbers as jq prints them: 1.5e3 -> 1500, 8.0 -> 8.
    function num(v,   n) { n = v + 0; if (n == int(n) && n < 1e15 && n > -1e15) return sprintf("%d", n); return v }
    NR == FNR { if ($2 != "z") val[$1] = ($2 == "n") ? num($3) : unesc($3); next }
    /row\(/ {
      line = $0; sub(/^[^(]*\(/, "", line); sub(/\),?[ \t]*$/, "", line)
      n = split(line, a, ";"); path = a[n]
      for (i = 1; i < n; i++) gsub(/"/, "", a[i])
      if (path in val) print a[1] "|" a[2] "|" a[3] "|" a[4] "|" a[5] "|" a[6] "|" uri(val[path])
    }
  ' "$_ce_flat" - > "$_ce_rows"
}

# Export: the document is built from the same table the import reads, so what is exported can be imported.
# Values come from /mnt/config (a key missing there falls back to the .dist file; a key found nowhere is left out).
# include_secrets=1 (F_include_secrets) adds the rows of category credential.
_ce_export() {
  _ce_row_table | LC_ALL=C awk -v root="$CONFIG_ROOT" -v inc="$(_ce_truthy "${F_include_secrets:-0}")" '
    function strip(v) {
      if (length(v) >= 2 && ((substr(v, 1, 1) == "\"" && substr(v, length(v), 1) == "\"") || (substr(v, 1, 1) == "\047" && substr(v, length(v), 1) == "\047")))
        v = substr(v, 2, length(v) - 2)
      return v
    }
    function have(f,   l, r) { r = (getline l < f); close(f); return r >= 0 }
    function read_flat(f, key,   line, found, v) {
      found = 0
      while ((getline line < f) > 0) {
        sub(/^[ \t]+/, "", line)
        if (substr(line, 1, 1) == "#") continue
        if (index(line, key "=") == 1) { v = substr(line, length(key) + 2); found = 1 }
      }
      close(f)
      if (found) { val = strip(v); return 1 }
      return 0
    }
    function read_ini(f, sec, key,   line, cur, found, v) {
      cur = "root"; found = 0
      while ((getline line < f) > 0) {
        if (line ~ /^\[[0-9]+\][ \t]*$/) { cur = line; gsub(/^\[|\][ \t]*$/, "", cur); continue }
        sub(/^[ \t]+/, "", line)
        if (substr(line, 1, 1) == "#") continue
        if (cur == sec && index(line, key "=") == 1) { v = substr(line, length(key) + 2); found = 1 }
      }
      close(f)
      if (found) { val = strip(v); return 1 }
      return 0
    }
    function read_single(f,   line) {
      while ((getline line < f) > 0) {
        if (line ~ /^[ \t]*($|#)/) continue
        val = line; close(f); return 1
      }
      close(f); return 0
    }
    function read_first(f,   line) {
      if ((getline line < f) > 0) { val = line; close(f); return 1 }
      close(f); return 0
    }
    function wifi_parse(f,   line, inb, s, p, k, v, hs, hp) {
      wifi_n = 0; inb = 0
      while ((getline line < f) > 0) {
        if (line ~ /^[ \t]*network=\{/) { inb = 1; s = ""; p = ""; k = ""; hs = 0; hp = 0; continue }
        if (inb && line ~ /^[ \t]*\}/) {
          inb = 0
          if (hs && (hp || k == "NONE") && wifi_n < 4) { wifi_ssid[wifi_n] = s; wifi_psk[wifi_n] = hp ? p : ""; wifi_n++ }
          continue
        }
        if (!inb) continue
        v = line; sub(/^[ \t]+/, "", v)
        if (v ~ /^ssid="/) { s = v; sub(/^ssid="/, "", s); sub(/"[ \t]*$/, "", s); hs = 1 }
        else if (v ~ /^psk="/) { p = v; sub(/^psk="/, "", p); sub(/"[ \t]*$/, "", p); hp = 1 }
        else if (v ~ /^key_mgmt=/) { k = v; sub(/^key_mgmt=/, "", k); sub(/[ \t]*$/, "", k) }
      }
      close(f)
      wifi_done = 1
    }
    function lookup(f, mode, sec, key,   lf, df, ok) {
      lf = root "/" f; df = lf ".dist"
      if (mode == "password") return read_first(lf)
      if (mode == "wifi") {
        if (!wifi_done) wifi_parse(lf)
        if (sec + 0 >= wifi_n) return 0
        val = (key == "ssid") ? wifi_ssid[sec + 0] : wifi_psk[sec + 0]
        return 1
      }
      ok = 0
      if (have(lf)) {
        if (mode == "single") ok = read_single(lf)
        else if (mode == "ini") ok = read_ini(lf, sec, key)
        else ok = read_flat(lf, key)
      }
      if (!ok && have(df)) {
        if (mode == "single") ok = read_single(df)
        else if (mode == "ini") ok = read_ini(df, sec, key)
        else ok = read_flat(df, key)
      }
      return ok
    }
    function jstr(v,   o, i, c) {
      o = ""
      for (i = 1; i <= length(v); i++) {
        c = substr(v, i, 1)
        if (c == "\\") o = o "\\\\"
        else if (c == "\"") o = o "\\\""
        else if (c == "\t") o = o "\\t"
        else if (c < " ") continue
        else o = o c
      }
      return "\"" o "\""
    }
    BEGIN { n = 0; wifi_done = 0; wifi_n = 0 }
    /row\(/ {
      line = $0; sub(/^[^(]*\(/, "", line); sub(/\),?[ \t]*$/, "", line)
      m = split(line, a, ";"); path = a[m]
      for (i = 1; i < m; i++) gsub(/"/, "", a[i])
      if (a[6] == "credential" && inc != 1) next
      if (!lookup(a[1], a[2], a[3], a[4])) next
      v = val; t = a[5]
      if (t == "bool") {
        lv = tolower(v)
        if (lv == "1" || lv == "true" || lv == "on" || lv == "yes" || lv == "enabled") j = "1"
        else if (lv == "0" || lv == "false" || lv == "off" || lv == "no" || lv == "disabled") j = "0"
        else next
      } else if (t ~ /^(topology|onvif_policy|hostname|host|host_optional|topic|topic_optional|identifier|timezone|safe_text|safe_text_optional|credential|credential_optional|osd_text|weekday|rec_when|rec_stream|dn_source|ir_led_mode|ipv4_optional|http_method|ntfy_priority|ntfy_topic|events|url|url_optional|ntfy_auth|password|wifi_ssid|wifi_psk|rescue_ssid_optional|rescue_psk_optional|country_optional|isp_mask|isp_mask_color)$/) {
        j = jstr(v)
      } else if (v ~ /^-?[0-9]+$/) {
        j = sprintf("%d", v + 0)
      } else if (v == "" && t ~ /^(isp_effect|isp_power_hz|isp_exposure_pct)$/) {
        j = "\"\""
      } else next
      n++; E_path[n] = path; E_val[n] = j
    }
    END {
      out = "{\"format\":\"tc100-config\",\"version\":1,\"includes_secrets\":" (inc == 1 ? "true" : "false")
      cnt[0] = 1; pn = 0
      for (e = 1; e <= n; e++) {
        np = split(E_path[e], seg, ".")
        mm = 0
        for (i = 2; i <= np; i++) {
          sg = seg[i]
          if (i == np) { leaf = sg; break }
          if (match(sg, /\[[0-9]+\]$/)) {
            mm++; lab[mm] = substr(sg, 1, RSTART - 1); typ[mm] = "a"
            mm++; lab[mm] = substr(sg, RSTART + 1, RLENGTH - 2); typ[mm] = "e"
          } else { mm++; lab[mm] = sg; typ[mm] = "o" }
        }
        c = 0
        while (c < mm && c < pn && lab[c + 1] == plab[c + 1] && typ[c + 1] == ptyp[c + 1]) c++
        for (i = pn; i > c; i--) out = out (ptyp[i] == "a" ? "]" : "}")
        for (i = c + 1; i <= mm; i++) {
          if (cnt[i - 1]++) out = out ","
          cnt[i] = 0
          if (typ[i] == "o") out = out "\"" lab[i] "\":{"
          else if (typ[i] == "a") out = out "\"" lab[i] "\":["
          else out = out "{"
        }
        if (cnt[mm]++) out = out ","
        out = out "\"" leaf "\":" E_val[e]
        pn = mm
        for (i = 1; i <= mm; i++) { plab[i] = lab[i]; ptyp[i] = typ[i] }
      }
      for (i = pn; i >= 1; i--) out = out (ptyp[i] == "a" ? "]" : "}")
      printf "%s}\n", out
    }
  '
}

# wpa_supplicant.conf from the staged .wifi.<index>.ssid / .psk values (first = preferred); the whole list is
# replaced, the way an export of the same camera lists it. Returns 1 when a psk has no ssid or nothing is left.
_ce_build_wpa() {
  _bw_out="$_ce_stage/wpa_supplicant.conf"
  ( umask 077; printf 'ctrl_interface=/var/run/wpa_supplicant\nctrl_interface_group=0\nap_scan=1\n' > "$_bw_out" ) || return 1
  _bw_i=0; _bw_n=0
  while [ "$_bw_i" -le 3 ]; do
    _bw_s="$_ce_stage/.wifi.$_bw_i.ssid"; _bw_p="$_ce_stage/.wifi.$_bw_i.psk"
    if [ -f "$_bw_s" ]; then
      IFS= read -r _bw_ssid < "$_bw_s"
      _bw_psk=""
      [ -f "$_bw_p" ] && IFS= read -r _bw_psk < "$_bw_p"
      {
        printf 'network={\n\tssid="%s"\n\tscan_ssid=1\n' "$_bw_ssid"
        if [ -n "$_bw_psk" ]; then printf '\tkey_mgmt=WPA-PSK\n\tpsk="%s"\n' "$_bw_psk"; else printf '\tkey_mgmt=NONE\n'; fi
        printf '\tpriority=%d\n}\n' $((4 - _bw_i))
      } >> "$_bw_out" || return 1
      _bw_n=$((_bw_n + 1))
    elif [ -f "$_bw_p" ]; then
      return 1
    fi
    _bw_i=$((_bw_i + 1))
  done
  [ "$_bw_n" -gt 0 ]
}

_ce_import() {
  _ce_cl="${CONTENT_LENGTH:-0}"
  case "$_ce_cl" in ''|*[!0-9]*) _ce_fail "Invalid content length" "INVALID_PAYLOAD" ;; esac
  [ "$_ce_cl" -gt 0 ] || _ce_fail "No JSON data received" "EMPTY_PAYLOAD"
  [ "$_ce_cl" -le 65536 ] || _ce_fail "JSON configuration exceeds 64 KB" "PAYLOAD_TOO_LARGE"
  [ -r "$JSONFLAT" ] || _ce_fail "JSON parser is unavailable" "SERVICE_UNAVAILABLE"

  _ce_json="/tmp/config-import.$$.json"
  _ce_flat="/tmp/config-import.$$.flat"
  _ce_rows="/tmp/config-import.$$.rows"
  _ce_stage="/tmp/config-import-stage.$$"
  _ce_backup="/tmp/config-import-rollback.$$"
  mkdir -p "$_ce_stage" || _ce_fail "Cannot allocate import staging area" "STAGING_FAILED"
  head -c "$_ce_cl" > "$_ce_json" 2>/dev/null
  _ce_got="$(wc -c < "$_ce_json" 2>/dev/null)"
  set -- $_ce_got; _ce_got="${1:-0}"
  [ "$_ce_got" = "$_ce_cl" ] || _ce_fail "Incomplete JSON upload" "INCOMPLETE_PAYLOAD"
  LC_ALL=C awk -v require=object -f "$JSONFLAT" "$_ce_json" > "$_ce_flat" 2>/dev/null || _ce_fail "Malformed JSON configuration" "INVALID_JSON"
  _ce_build_rows || _ce_fail "Unsupported JSON values" "INVALID_JSON"

  _ce_exclude_network="$(_ce_truthy "${F_exclude_network:-0}")"
  _ce_exclude_credentials="$(_ce_truthy "${F_exclude_credentials:-0}")"
  _ce_files=""; _ce_values=0; _ce_skipped=0; _ce_wifi=0; _ce_pw=0; _ce_wifi_changed=0; _ce_pw_value=""
  while IFS='|' read -r _ce_rel _ce_mode _ce_section _ce_key _ce_type _ce_category _ce_encoded; do
    [ -n "$_ce_rel" ] || continue
    if { [ "$_ce_category" = network ] && [ "$_ce_exclude_network" = 1 ]; } || { [ "$_ce_category" = credential ] && [ "$_ce_exclude_credentials" = 1 ]; }; then
      _ce_skipped=$((_ce_skipped + 1)); continue
    fi
    _ce_value="$(urldecode "$_ce_encoded")"
    tc_normalize_and_validate "$_ce_type" "$_ce_value" || _ce_fail "Invalid value for ${_ce_rel}:${_ce_key}" "VALIDATION_FAILED"
    _ce_value="$TC_NORMALIZED_VALUE"
    case "$_ce_mode" in
      wifi)
        # collected here, written as one wpa_supplicant.conf after the loop
        printf '%s\n' "$_ce_value" > "$_ce_stage/.wifi.$_ce_section.$_ce_key" || _ce_fail "Cannot stage ${_ce_rel}" "STAGING_FAILED"
        _ce_wifi=1; _ce_values=$((_ce_values + 1)); continue ;;
      password)
        # not a file of the transaction: applied after the commit, the way the web UI does it
        ( umask 077; printf '%s\n' "$_ce_value" > "$_ce_stage/.password" ) || _ce_fail "Cannot stage ${_ce_rel}" "STAGING_FAILED"
        _ce_pw=1; _ce_values=$((_ce_values + 1)); continue ;;
    esac
    _ce_prepare_file "$_ce_rel" || _ce_fail "Missing base configuration: $_ce_rel" "CONFIG_NOT_FOUND"
    # flat / ini values are queued per file and applied in one pass after the loop (tc_apply_edits)
    _ce_edits="$_ce_stage/.edits.${_ce_rel//\//_}"
    case "$_ce_mode" in
      flat) printf 'flat\t\t%s\t%s\n' "$_ce_key" "$_ce_value" >> "$_ce_edits" ;;
      flatd) printf 'flat\t\t%s\t"%s"\n' "$_ce_key" "$_ce_value" >> "$_ce_edits" ;;
      flatq) printf "flat\t\t%s\t'%s'\n" "$_ce_key" "$_ce_value" >> "$_ce_edits" ;;
      ini) printf 'ini\t%s\t%s\t%s\n' "$_ce_section" "$_ce_key" "$_ce_value" >> "$_ce_edits" ;;
      single) printf '%s\n' "$_ce_value" > "$_ce_stage/$_ce_rel" ;;
      *) false ;;
    esac || _ce_fail "Cannot stage ${_ce_rel}:${_ce_key}" "STAGING_FAILED"
    _ce_add_file "$_ce_rel"
    _ce_values=$((_ce_values + 1))
  done < "$_ce_rows"

  for _ce_f in $_ce_files; do
    _ce_edits="$_ce_stage/.edits.${_ce_f//\//_}"
    [ -f "$_ce_edits" ] || continue
    tc_apply_edits "$_ce_stage/$_ce_f" "$_ce_edits" || _ce_fail "Cannot stage ${_ce_f}" "STAGING_FAILED"
    rm -f "$_ce_edits"
  done

  [ "$_ce_values" -gt 0 ] || _ce_fail "No applicable configuration values found" "EMPTY_CONFIG"
  if [ "$_ce_wifi" = 1 ]; then
    _ce_build_wpa || _ce_fail "Invalid Wi-Fi network list" "VALIDATION_FAILED"
    _ce_add_file wpa_supplicant.conf
    cmp -s "$_ce_stage/wpa_supplicant.conf" "$CONFIG_ROOT/wpa_supplicant.conf" 2>/dev/null || _ce_wifi_changed=1
  fi
  if [ "$_ce_pw" = 1 ]; then
    IFS= read -r _ce_pw_value < "$_ce_stage/.password"
    _ce_pw_cur=""
    [ -f "$CONFIG_ROOT/user.pwd" ] && IFS= read -r _ce_pw_cur < "$CONFIG_ROOT/user.pwd"
    [ "$_ce_pw_cur" = "$_ce_pw_value" ] && _ce_pw_value=""
  fi
  _ce_wc() { [ -f /mnt/scripts/wifi-country.sh ] && WC_CONF="$CONFIG_ROOT/boot.conf" sh /mnt/scripts/wifi-country.sh get 2>/dev/null; }
  _ce_wc_before="$(_ce_wc)"
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
  if [ "$_ce_wifi_changed" = 1 ] && [ -f /mnt/v3/linux66-sd/wifi-apply ]; then
    # the new network list is used now (the page has its answer first)
    ( sh /mnt/v3/linux66-sd/wifi-apply 5 </dev/null >/dev/null 2>&1 & )
  fi
  if [ -f /mnt/scripts/wifi-country.sh ] && [ "$(_ce_wc)" != "$_ce_wc_before" ]; then
    # the Wi-Fi rules of the new country (boot.conf WIFI_COUNTRY), now and without reconnecting
    ( sh /mnt/scripts/wifi-country.sh apply </dev/null >/dev/null 2>&1 & )
  fi
  if [ -n "$_ce_pw_value" ] && [ -r /mnt/scripts/common_functions.sh ]; then
    # the camera password: the web UI, the shell, RTSP, FTP and telnet, as the Settings password change does
    (
      sleep 3
      . /mnt/scripts/common_functions.sh
      all_password "$_ce_pw_value"
      restart_service_if_need /mnt/controlscripts/ftp-server
      restart_service_if_need /mnt/controlscripts/telnet-server
      [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x restart
    ) >/dev/null 2>&1 &
  fi
  printf '{"ok":true,"applied":%d,"changed_files":%d,"skipped":%d,"transactional":true}\n' "$_ce_values" "$_ce_changed" "$_ce_skipped"
}

# Restore an archive of cmd=archive (POST body = the .tar.gz, at most 256 KB): only regular files and directories
# under config/ with plain names, at most 1 MB unpacked; every non-empty file is validated as for an import
# (tc_validate_candidate) and all are written as one transaction; empty files are markers (.wizard3_done...).
# For this camera after a reinstall: it brings back its name, its address and its ssh keys too (another camera: the
# JSON export / push, which leave the identity out).
_ce_restore() {
  _rs="/tmp/ce-restore.$$"
  _rs_fail() { rm -rf "$_rs"; json_body_err "$1" "$2"; }
  rm -rf "$_rs"; mkdir -p "$_rs/x" || { json_body_err "STAGING_FAILED" "Cannot prepare the restore"; return; }
  _rs_cl="${CONTENT_LENGTH:-0}"
  case "$_rs_cl" in ''|*[!0-9]*) _rs_cl=0 ;; esac
  if [ "$_rs_cl" -le 0 ] || [ "$_rs_cl" -gt 262144 ]; then _rs_fail "INVALID_SIZE" "The archive must be 1 byte to 256 KB"; return; fi
  head -c "$_rs_cl" > "$_rs/a.tgz" 2>/dev/null
  if ! gunzip -c "$_rs/a.tgz" > "$_rs/a.tar" 2>/dev/null || ! tar -tvf "$_rs/a.tar" > "$_rs/list" 2>/dev/null; then
    _rs_fail "INVALID_ARCHIVE" "Not a configuration archive of this camera (.tar.gz)"; return
  fi
  # regular files or directories only (no link, no device), names under config/, nothing above it, 1 MB in all
  if ! awk '{ if ($1 !~ /^[-d]/) exit 1; n = $NF
              if (n !~ /^config(\/[A-Za-z0-9._-]+)*\/?$/ || n ~ /(^|\/)\.\.?(\/|$)/) exit 1; t += $3 }
            END { if (NR == 0 || t > 1048576) exit 1 }' "$_rs/list"; then
    _rs_fail "INVALID_ARCHIVE" "The archive holds something else than configuration files"; return
  fi
  if ! (cd "$_rs/x" && tar -xf "$_rs/a.tar") 2>/dev/null || [ ! -d "$_rs/x/config" ]; then
    _rs_fail "INVALID_ARCHIVE" "The archive could not be unpacked"; return
  fi
  _rs_files=""; _rs_marks=""
  for _rs_f in $(cd "$_rs/x/config" && find . -type f | sed 's|^\./||' | sort); do
    if [ -s "$_rs/x/config/$_rs_f" ]; then _rs_files="$_rs_files $_rs_f"; else _rs_marks="$_rs_marks $_rs_f"; fi
  done
  [ -n "$_rs_files$_rs_marks" ] || { _rs_fail "EMPTY_CONFIG" "The archive holds no file"; return; }
  _rs_wpa_old="$(md5sum < "$CONFIG_ROOT/wpa_supplicant.conf" 2>/dev/null)"
  _rs_pw_old="$(md5sum < "$CONFIG_ROOT/user.pwd" 2>/dev/null)"
  _ce_wc() { [ -f /mnt/scripts/wifi-country.sh ] && WC_CONF="$CONFIG_ROOT/boot.conf" sh /mnt/scripts/wifi-country.sh get 2>/dev/null; }
  _rs_wc_old="$(_ce_wc)"
  if [ -n "$_rs_files" ] && ! tc_commit_config_files "$_rs/x/config" "$CONFIG_ROOT" "$_rs/backup" "$_rs_files"; then
    _rs_fail "TRANSACTION_FAILED" "Restore refused (${TC_CONFIG_ERROR:-transaction failed}); the configuration is unchanged"; return
  fi
  _rs_changed="${TC_COMMIT_COUNT:-0}"
  for _rs_f in $_rs_marks; do mkdir -p "$CONFIG_ROOT/$(dirname "$_rs_f")" && : > "$CONFIG_ROOT/$_rs_f"; done
  rm -rf "$_rs"
  # what can be applied without a restart: the services, the Wi-Fi, the password, the Wi-Fi country
  (
    sleep 2
    [ -x /mnt/controlscripts/rtsp-h26x ] && /mnt/controlscripts/rtsp-h26x restart >/dev/null 2>&1
    [ -x /mnt/controlscripts/mqtt-bridge ] && /mnt/controlscripts/mqtt-bridge restart >/dev/null 2>&1
  ) >/dev/null 2>&1 &
  [ "$(md5sum < "$CONFIG_ROOT/wpa_supplicant.conf" 2>/dev/null)" = "$_rs_wpa_old" ] || \
    { [ -f /mnt/v3/linux66-sd/wifi-apply ] && ( sh /mnt/v3/linux66-sd/wifi-apply 5 </dev/null >/dev/null 2>&1 & ); }
  if [ "$(md5sum < "$CONFIG_ROOT/user.pwd" 2>/dev/null)" != "$_rs_pw_old" ] && [ -r /mnt/scripts/common_functions.sh ]; then
    _rs_pw=""; IFS= read -r _rs_pw < "$CONFIG_ROOT/user.pwd"
    ( sleep 3; . /mnt/scripts/common_functions.sh; all_password "$_rs_pw" ) >/dev/null 2>&1 &
  fi
  [ "$(_ce_wc)" = "$_rs_wc_old" ] || ( sh /mnt/scripts/wifi-country.sh apply </dev/null >/dev/null 2>&1 & )
  printf '{"ok":true,"files":%d,"changed_files":%d,"note":"ssh keys and the host name take effect at the next restart"}\n' \
    "$(echo $_rs_files $_rs_marks | wc -w)" "$_rs_changed"
}

case "$F_cmd" in
  archive)
    # The full backup of this camera: every setting changed from the shipped defaults, secrets and ssh keys
    # included, as the flash slots keep them (v3/linux66-sd/cfg-persist archive). A GET like export: another site
    # cannot read the answer.
    _ce_ar="/tmp/ce-archive.$$.tgz"
    if sh /mnt/v3/linux66-sd/cfg-persist archive > "$_ce_ar" 2>/dev/null && [ -s "$_ce_ar" ]; then
      _ce_host="$(hostname 2>/dev/null | tr -cd 'A-Za-z0-9-')"
      echo "Content-Type: application/gzip"
      echo "Content-Disposition: attachment; filename=tc100_${_ce_host:-camera}_config_$(date +%Y%m%d_%H%M%S).tar.gz"
      echo "Content-Length: $(wc -c < "$_ce_ar")"
      echo "Cache-Control: no-store"
      echo ""
      cat "$_ce_ar"
    else
      output_json_header
      echo ""
      json_body_err "NOTHING_TO_SAVE" "Nothing differs from the shipped settings yet"
    fi
    rm -f "$_ce_ar"
    ;;
  restore)
    mutation_guard
    output_json_header
    echo ""
    _ce_restore
    ;;
  export)
    _ce_now="$(date +%Y%m%d_%H%M%S)"
    output_json_header
    _ce_tag=""
    [ "$(_ce_truthy "${F_include_secrets:-0}")" = 1 ] && _ce_tag="_with_secrets"
    echo "Content-Disposition: attachment; filename=tc100_config_${_ce_now}${_ce_tag}.json"
    echo ""
    _ce_export
    ;;
  import)
    mutation_guard
    output_json_header
    echo ""
    _ce_import
    ;;
  push)
    mutation_guard
    output_json_header
    echo ""
    # func.cgi did not read the body (FUNC_CGI_SKIP_BODY): the push form is read here (target, user, password)
    _ce_form=""
    _ce_pl="${CONTENT_LENGTH:-0}"
    case "$_ce_pl" in ''|*[!0-9]*) _ce_pl=0 ;; esac
    [ "$_ce_pl" -le 4096 ] || _ce_pl=4096
    [ "$_ce_pl" -gt 0 ] && _ce_form="$(head -c "$_ce_pl" 2>/dev/null)"
    _ce_form_get target; _target="$_ce_fv"
    _ce_form_get user; _push_user="$_ce_fv"
    _ce_form_get password; _push_password="$_ce_fv"
    case "$_target" in
      http://*|https://*) ;;
      *) _target="http://$_target" ;;
    esac
    _target="${_target%/}"

    # Validate target host/IP format (IPv4 or hostname:port)
    _thost="$(printf '%s' "$_target" | sed -E 's#^https?://([^/:]+).*#\1#')"
    case "$_thost" in
      ''|*[!a-zA-Z0-9.-]*)
        json_body_err "INVALID_TARGET" "Invalid target address"
        exit 0
        ;;
    esac

    _curl_bin="/mnt/bin/curl"
    [ -x "$_curl_bin" ] || _curl_bin="$(command -v curl 2>/dev/null || echo "")"
    if [ -z "$_curl_bin" ]; then
      json_body_err "CURL_UNAVAILABLE" "curl binary not found"
      exit 0
    fi

    # Export the shareable settings (no secrets) to a temporary JSON buffer
    _push_tmp="/tmp/ce_push_$$.json"
    # never with secrets: no Wi-Fi, no passwords, no tokens leave this camera by a push
    F_include_secrets=0
    _ce_export > "$_push_tmp" 2>/dev/null

    # Credentials of the target camera, as ONE curl argument each (a space or a '*' in the password must not split
    # it into extra curl options). Never logged, never echoed back.
    set --
    if [ -n "$_push_user" ] || [ -n "$_push_password" ]; then
      set -- -u "${_push_user}:${_push_password}"
    fi

    # The target camera checks a per-boot CSRF token on a mutation: read it first (statusline.cgi, a GET)
    _tok_resp="$("$_curl_bin" -s -S -m 10 "$@" "$_target/cgi-bin/statusline.cgi" 2>&1)"
    _tok_ret=$?
    case "$_tok_resp" in
      *'401 Unauthorized'*|*'Unauthorized'*)
        rm -f "$_push_tmp" 2>/dev/null
        printf '{"ok":false,"error":"The target camera refused the user or password"}\n'
        exit 0 ;;
    esac
    _tok="$(printf '%s' "$_tok_resp" | sed -n 's/.*"csrf_token":"\([0-9a-fA-F]*\)".*/\1/p' | head -n 1)"
    if [ "$_tok_ret" -ne 0 ] || [ -z "$_tok" ]; then
      rm -f "$_push_tmp" 2>/dev/null
      printf '{"ok":false,"error":"The target camera did not answer (code %d) or is not a TC100 with a recent firmware"}\n' "$_tok_ret"
      exit 0
    fi

    # Target URL with exclusion parameters (the target keeps its own network identity and credentials)
    _dest_url="$_target/cgi-bin/config_exchange.cgi?cmd=import&exclude_network=1&exclude_credentials=1"
    _resp="$("$_curl_bin" -s -S -m 20 "$@" -H "X-CSRF-Token: $_tok" -H "Content-Type: application/json" --data-binary "@$_push_tmp" "$_dest_url" 2>&1)"
    _ret=$?
    rm -f "$_push_tmp" 2>/dev/null

    if [ "$_ret" -eq 0 ] && [ -n "$_resp" ]; then
      printf '%s\n' "$_resp"
    else
      printf '{"ok":false,"error":"Push failed (code %d)"}\n' "$_ret"
    fi
    ;;
  *)
    output_json_header
    echo ""
    json_body_err "UNKNOWN_COMMAND" "Command '$F_cmd' not recognized"
    ;;
esac
