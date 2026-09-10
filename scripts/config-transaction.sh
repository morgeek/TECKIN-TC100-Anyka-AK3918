#!/bin/sh
# Shared validation and transactional commit helpers for configuration imports.
# This file is sourced only for explicit import/restore operations; it adds no daemon.

TC_CONFIG_ROOT="${TC_CONFIG_ROOT:-/mnt/config}"
TC_CONFIG_ERROR=""
TC_COMMIT_COUNT=0

_tc_fail()
{
  TC_CONFIG_ERROR="$1"
  return 1
}

tc_uint_range()
{
  _tc_value="$1"; _tc_min="$2"; _tc_max="$3"
  case "$_tc_value" in ''|*[!0-9]*) return 1 ;; esac
  [ "$_tc_value" -ge "$_tc_min" ] && [ "$_tc_value" -le "$_tc_max" ]
}

tc_normalize_and_validate()
{
  _tc_type="$1"; _tc_value="$2"
  TC_NORMALIZED_VALUE="$_tc_value"
  case "$_tc_value" in *[![:print:]]*) return 1 ;; esac
  case "$_tc_type" in
    bool)
      case "$_tc_value" in
        1|true|on|yes|enabled) TC_NORMALIZED_VALUE=1 ;;
        0|false|off|no|disabled) TC_NORMALIZED_VALUE=0 ;;
        *) return 1 ;;
      esac ;;
    port) tc_uint_range "$_tc_value" 1 65535 ;;
    fps) tc_uint_range "$_tc_value" 1 30 ;;
    bitrate) tc_uint_range "$_tc_value" 32 8000 ;;
    gop) tc_uint_range "$_tc_value" 1 300 ;;
    width) tc_uint_range "$_tc_value" 160 1920 && [ $((_tc_value % 2)) -eq 0 ] ;;
    height) tc_uint_range "$_tc_value" 120 1080 && [ $((_tc_value % 2)) -eq 0 ] ;;
    codec) case "$_tc_value" in 0|2|4|17) ;; *) return 1 ;; esac ;;
    video_codec) case "$_tc_value" in 0|2) ;; *) return 1 ;; esac ;;
    profile) tc_uint_range "$_tc_value" 0 4 ;;
    qp) tc_uint_range "$_tc_value" 0 51 ;;
    smartquality) tc_uint_range "$_tc_value" 0 100 ;;
    smartstatic) tc_uint_range "$_tc_value" 0 2000 ;;
    smartgop) tc_uint_range "$_tc_value" 0 300 ;;
    samplerate) case "$_tc_value" in 8000|16000) ;; *) return 1 ;; esac ;;
    volume) tc_uint_range "$_tc_value" 0 10 ;;
    flip) tc_uint_range "$_tc_value" 0 3 ;;
    fontsize) tc_uint_range "$_tc_value" 8 128 ;;
    color) tc_uint_range "$_tc_value" 0 255 ;;
    coordinate) tc_uint_range "$_tc_value" 0 4096 ;;
    lum) tc_uint_range "$_tc_value" 0 65535 ;;
    awb) tc_uint_range "$_tc_value" 0 9999999 ;;
    hour) tc_uint_range "$_tc_value" 0 23 ;;
    minute) tc_uint_range "$_tc_value" 0 59 ;;
    weekday) case "$_tc_value" in '*'|[0-6]|1-5|0,6) ;; *) return 1 ;; esac ;;
    web_mode) case "$_tc_value" in full|http|ultra-lite|ultralite|off) ;; *) return 1 ;; esac ;;
    topology) case "$_tc_value" in dual|main-only|sub-only) ;; *) return 1 ;; esac ;;
    onvif_policy) case "$_tc_value" in main-primary|sub-primary|sub-only|main-only) ;; *) return 1 ;; esac ;;
    hostname)
      [ "${#_tc_value}" -le 63 ] || return 1
      case "$_tc_value" in ''|-*|*-|*[!A-Za-z0-9-]*) return 1 ;; esac ;;
    host)
      [ "${#_tc_value}" -le 253 ] || return 1
      case "$_tc_value" in ''|*[!A-Za-z0-9._:-]*) return 1 ;; esac ;;
    host_optional)
      [ -z "$_tc_value" ] && return 0
      tc_normalize_and_validate host "$_tc_value" ;;
    topic)
      [ "${#_tc_value}" -le 160 ] || return 1
      case "$_tc_value" in ''|*[#+]*|*[!A-Za-z0-9_./-]*) return 1 ;; esac ;;
    topic_optional)
      [ -z "$_tc_value" ] && return 0
      tc_normalize_and_validate topic "$_tc_value" ;;
    identifier)
      [ "${#_tc_value}" -le 96 ] || return 1
      case "$_tc_value" in ''|*[!A-Za-z0-9_.-]*) return 1 ;; esac ;;
    timezone)
      [ "${#_tc_value}" -le 64 ] || return 1
      case "$_tc_value" in ''|*[!A-Za-z0-9_+:/.-]*) return 1 ;; esac ;;
    safe_text)
      [ "${#_tc_value}" -le 128 ] || return 1
      case "$_tc_value" in *[\\\$\`\;\&\|\<\>\"\']*) return 1 ;; esac ;;
    credential)
      [ "${#_tc_value}" -le 128 ] || return 1
      case "$_tc_value" in ''|*[![:graph:]]*|*"'"*) return 1 ;; esac ;;
    credential_optional)
      [ -z "$_tc_value" ] && return 0
      tc_normalize_and_validate credential "$_tc_value" ;;
    safe_text_optional)
      [ -z "$_tc_value" ] && return 0
      tc_normalize_and_validate safe_text "$_tc_value" ;;
    osd_text)
      [ "${#_tc_value}" -le 80 ] || return 1
      case "$_tc_value" in *[\$\`\;\&\|\<\>\"\']*) return 1 ;; esac ;;
    motion_sens) tc_uint_range "$_tc_value" 0 100 ;;
    sound_threshold) tc_uint_range "$_tc_value" 100 10000 ;;
    sound_interval) tc_uint_range "$_tc_value" 2 300 ;;
    record_post) tc_uint_range "$_tc_value" 0 60 ;;
    record_duration) tc_uint_range "$_tc_value" 10 600 ;;
    disk_mb) tc_uint_range "$_tc_value" 0 65535 ;;
    positive_interval) tc_uint_range "$_tc_value" 1 86400 ;;
    qos) tc_uint_range "$_tc_value" 0 2 ;;
    nonnegative) tc_uint_range "$_tc_value" 0 9999999 ;;
    *) return 1 ;;
  esac
}

tc_strip_quotes()
{
  TC_UNQUOTED_VALUE="$1"
  case "$TC_UNQUOTED_VALUE" in
    \"*\") TC_UNQUOTED_VALUE="${TC_UNQUOTED_VALUE#\"}"; TC_UNQUOTED_VALUE="${TC_UNQUOTED_VALUE%\"}" ;;
    \'*\') TC_UNQUOTED_VALUE="${TC_UNQUOTED_VALUE#\'}"; TC_UNQUOTED_VALUE="${TC_UNQUOTED_VALUE%\'}" ;;
  esac
}

tc_set_flat()
{
  _tc_file="$1"; _tc_key="$2"; _tc_value="$3"; _tc_tmp="${1}.set.$$"
  awk -v key="$_tc_key" -v value="$_tc_value" '
    BEGIN { found=0 }
    $0 !~ /^[[:space:]]*#/ && $0 ~ "^[[:space:]]*" key "=" {
      if (!found) print key "=" value
      found=1; next
    }
    { print }
    END { if (!found) print key "=" value }
  ' "$_tc_file" > "$_tc_tmp" && mv "$_tc_tmp" "$_tc_file" || {
    rm -f "$_tc_tmp"; return 1;
  }
}

tc_set_ini()
{
  _tc_file="$1"; _tc_section="$2"; _tc_key="$3"; _tc_value="$4"; _tc_tmp="${1}.set.$$"
  awk -v target="$_tc_section" -v key="$_tc_key" -v value="$_tc_value" '
    BEGIN { current="root"; found=0; inserted=0 }
    /^\[[0-9]+\][[:space:]]*$/ {
      if (current == target && !found && !inserted) { print key "=" value; inserted=1 }
      current=$0; gsub(/^\[|\][[:space:]]*$/, "", current)
      print; next
    }
    current == target && $0 !~ /^[[:space:]]*#/ && $0 ~ "^[[:space:]]*" key "=" {
      if (!found) print key "=" value
      found=1; next
    }
    { print }
    END {
      if (current == target && !found && !inserted) print key "=" value
      else if (target == "root" && !found && !inserted) print key "=" value
    }
  ' "$_tc_file" > "$_tc_tmp" && mv "$_tc_tmp" "$_tc_file" || {
    rm -f "$_tc_tmp"; return 1;
  }
}

tc_read_flat()
{
  awk -F= -v key="$2" '$0 !~ /^[[:space:]]*#/ && $1 == key {sub(/^[^=]*=/, ""); print; exit}' "$1" 2>/dev/null
}

tc_read_ini()
{
  awk -F= -v target="$2" -v key="$3" '
    BEGIN { section="root" }
    /^\[[0-9]+\][[:space:]]*$/ { section=$0; gsub(/^\[|\][[:space:]]*$/, "", section); next }
    section == target && $0 !~ /^[[:space:]]*#/ && $1 == key {sub(/^[^=]*=/, ""); print; exit}
  ' "$1" 2>/dev/null
}

tc_has_flat()
{
  awk -F= -v key="$2" '$0 !~ /^[[:space:]]*#/ && $1 == key {found=1; exit} END {exit !found}' "$1" 2>/dev/null
}

tc_has_ini()
{
  awk -F= -v target="$2" -v key="$3" '
    BEGIN { section="root" }
    /^\[[0-9]+\][[:space:]]*$/ { section=$0; gsub(/^\[|\][[:space:]]*$/, "", section); next }
    section == target && $0 !~ /^[[:space:]]*#/ && $1 == key {found=1; exit}
    END {exit !found}
  ' "$1" 2>/dev/null
}

tc_require_flat()
{
  tc_has_flat "$1" "$2" || _tc_fail "$3:$2:missing"
}

tc_require_ini()
{
  tc_has_ini "$1" "$2" "$3" || _tc_fail "$4:[$2].$3:missing"
}

tc_check_flat()
{
  tc_has_flat "$1" "$2" || return 0
  _tc_check_value="$(tc_read_flat "$1" "$2")"
  tc_strip_quotes "$_tc_check_value"
  tc_normalize_and_validate "$3" "$TC_UNQUOTED_VALUE" || _tc_fail "$4:$2"
}

tc_check_ini()
{
  tc_has_ini "$1" "$2" "$3" || return 0
  _tc_check_value="$(tc_read_ini "$1" "$2" "$3")"
  tc_normalize_and_validate "$4" "$_tc_check_value" || _tc_fail "$5:[$2].$3"
}

tc_validate_rtsp()
{
  _tc_file="$1"; _tc_label="$2"
  awk '
    /^[[:space:]]*($|#)/ { next }
    /^\[[0-3]\][[:space:]]*$/ { next }
    /^[A-Za-z_][A-Za-z0-9_]*=.*/ { next }
    { exit 1 }
  ' "$_tc_file" || _tc_fail "$_tc_label:structure" || return 1
  tc_require_ini "$_tc_file" root PORT "$_tc_label" || return 1
  tc_check_ini "$_tc_file" root PORT port "$_tc_label" || return 1
  tc_check_ini "$_tc_file" root samplerate samplerate "$_tc_label" || return 1
  tc_check_ini "$_tc_file" root volume volume "$_tc_label" || return 1
  for _tc_section in 0 1; do
    tc_require_ini "$_tc_file" "$_tc_section" codec "$_tc_label" || return 1
    tc_require_ini "$_tc_file" "$_tc_section" width "$_tc_label" || return 1
    tc_require_ini "$_tc_file" "$_tc_section" height "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" codec video_codec "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" width width "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" height height "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" fps fps "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" bps bitrate "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" goplen gop "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" profile profile "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" brmode bool "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" minqp qp "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" maxqp qp "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" smartmode bool "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" smartgoplen smartgop "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" smartquality smartquality "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" smartstatic smartstatic "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" maxkbps bitrate "$_tc_label" || return 1
    tc_check_ini "$_tc_file" "$_tc_section" targetkbps bitrate "$_tc_label" || return 1
    _tc_minqp="$(tc_read_ini "$_tc_file" "$_tc_section" minqp)"
    _tc_maxqp="$(tc_read_ini "$_tc_file" "$_tc_section" maxqp)"
    [ -z "$_tc_minqp" ] || [ -z "$_tc_maxqp" ] || [ "$_tc_minqp" -le "$_tc_maxqp" ] || _tc_fail "$_tc_label:[$_tc_section].qp_order" || return 1
  done
  tc_check_ini "$_tc_file" root imageflip flip "$_tc_label" || return 1
  tc_check_ini "$_tc_file" root RTSPLOGENABLED bool "$_tc_label" || return 1
  tc_check_ini "$_tc_file" root mdsens motion_sens "$_tc_label" || return 1
  tc_check_ini "$_tc_file" root osdenabled bool "$_tc_label" || return 1
  tc_check_ini "$_tc_file" root osdalpha color "$_tc_label" || return 1
  tc_check_ini "$_tc_file" 2 codec codec "$_tc_label" || return 1
  tc_check_ini "$_tc_file" 3 codec codec "$_tc_label" || return 1
}

tc_validate_candidate()
{
  _tc_rel="$1"; _tc_file="$2"
  [ -f "$_tc_file" ] || _tc_fail "$_tc_rel:missing" || return 1
  _tc_size="$(wc -c < "$_tc_file" 2>/dev/null)"
  set -- $_tc_size; _tc_size="${1:-}"
  case "$_tc_size" in ''|*[!0-9]*) return 1 ;; esac
  [ "$_tc_size" -gt 0 ] || _tc_fail "$_tc_rel:empty" || return 1
  [ "$_tc_size" -le 262144 ] || _tc_fail "$_tc_rel:too_large" || return 1
  case "$_tc_rel" in
    rtspserver.conf) tc_validate_rtsp "$_tc_file" "$_tc_rel" || return 1 ;;
    boot.conf|mqtt.conf|service_trim.conf|recording.conf|sound_detection.conf|motion.conf|telegram.conf|telnetd.conf|ftp.conf|onvif.conf|network.conf|dns.conf|netmon.conf|sendmail.conf|timelapse.conf|onvif_events.conf)
      /bin/sh -n "$_tc_file" >/dev/null 2>&1 || _tc_fail "$_tc_rel:shell_syntax" || return 1 ;;
  esac
  case "$_tc_rel" in
    boot.conf)
      tc_require_flat "$_tc_file" WEB_MODE "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WEB_MODE web_mode "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" ULTRALITE_HTTP_PORT port "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REBOOT_SCHEDULE_HOUR hour "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REBOOT_SCHEDULE_MINUTE minute "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REBOOT_SCHEDULE_WEEKDAY weekday "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" RTSP_SUBSTREAM bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" RTSP_AUDIO bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" ONVIF_STREAM_POLICY onvif_policy "$_tc_rel" || return 1 ;;
    mqtt.conf)
      tc_require_flat "$_tc_file" MQTT_ENABLE "$_tc_rel" || return 1
      tc_require_flat "$_tc_file" MQTT_PORT "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_PORT port "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_QOS qos "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_HEALTH_INTERVAL_SECONDS positive_interval "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_HA_DISCOVERY_ENABLE bool "$_tc_rel" || return 1 ;;
    recording.conf)
      tc_check_flat "$_tc_file" rec_motion_activated bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" rec_postrecord_sec record_post "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" rec_file_duration_sec record_duration "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" rec_reserverd_disk_mb disk_mb "$_tc_rel" || return 1 ;;
    sound_detection.conf)
      tc_check_flat "$_tc_file" ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" THRESHOLD sound_threshold "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" INTERVAL sound_interval "$_tc_rel" || return 1 ;;
    telnetd.conf) tc_check_flat "$_tc_file" TELNET_PORT port "$_tc_rel" || return 1 ;;
    ftp.conf) tc_check_flat "$_tc_file" PORT port "$_tc_rel" || return 1 ;;
    onvif.conf) tc_check_flat "$_tc_file" ONVIF_PORT port "$_tc_rel" || return 1 ;;
    hostname.conf)
      _tc_single="$(awk '/^[[:space:]]*($|#)/ {next} {print; exit}' "$_tc_file")"
      tc_normalize_and_validate hostname "$_tc_single" || _tc_fail "$_tc_rel:value" || return 1 ;;
    timezone.conf)
      _tc_single="$(awk '/^[[:space:]]*($|#)/ {next} {print; exit}' "$_tc_file")"
      tc_normalize_and_validate timezone "$_tc_single" || _tc_fail "$_tc_rel:value" || return 1 ;;
    ntp_srv.conf)
      _tc_single="$(awk '/^[[:space:]]*($|#)/ {next} {print; exit}' "$_tc_file")"
      tc_normalize_and_validate host "$_tc_single" || _tc_fail "$_tc_rel:value" || return 1 ;;
  esac
  return 0
}

tc_rollback_config_files()
{
  _tc_backup="$1"; _tc_target="$2"
  [ -f "$_tc_backup/manifest" ] || return 1
  while IFS=' ' read -r _tc_state _tc_rel; do
    [ -n "$_tc_rel" ] || continue
    _tc_dest="$_tc_target/$_tc_rel"
    if [ "$_tc_state" = present ]; then
      _tc_parent="${_tc_rel%/*}"
      [ "$_tc_parent" = "$_tc_rel" ] && _tc_parent=""
      [ -z "$_tc_parent" ] || mkdir -p "$_tc_target/$_tc_parent" || return 1
      cp "$_tc_backup/files/$_tc_rel" "${_tc_dest}.tc100-rollback.$$" || return 1
      cmp -s "$_tc_backup/files/$_tc_rel" "${_tc_dest}.tc100-rollback.$$" || return 1
      mv -f "${_tc_dest}.tc100-rollback.$$" "$_tc_dest" || return 1
    else
      rm -f "$_tc_dest" || return 1
    fi
  done < "$_tc_backup/manifest"
  sync
}

tc_commit_config_files()
{
  _tc_stage="$1"; _tc_target="$2"; _tc_backup="$3"; _tc_files="$4"
  rm -rf "$_tc_backup"
  mkdir -p "$_tc_backup/files" || return 1
  : > "$_tc_backup/manifest" || return 1
  TC_COMMIT_COUNT=0

  # Validate the complete set before preparing any target-side file.
  for _tc_rel in $_tc_files; do
    tc_validate_candidate "$_tc_rel" "$_tc_stage/$_tc_rel" || return 1
  done

  for _tc_rel in $_tc_files; do
    _tc_dest="$_tc_target/$_tc_rel"
    if [ -f "$_tc_dest" ]; then
      _tc_parent="${_tc_rel%/*}"
      [ "$_tc_parent" = "$_tc_rel" ] && _tc_parent=""
      [ -z "$_tc_parent" ] || mkdir -p "$_tc_backup/files/$_tc_parent" || return 1
      cp "$_tc_dest" "$_tc_backup/files/$_tc_rel" || return 1
      printf 'present %s\n' "$_tc_rel" >> "$_tc_backup/manifest"
      if cmp -s "$_tc_stage/$_tc_rel" "$_tc_dest"; then continue; fi
    else
      printf 'absent %s\n' "$_tc_rel" >> "$_tc_backup/manifest"
    fi
    mkdir -p "${_tc_dest%/*}" || return 1
    if ! cp "$_tc_stage/$_tc_rel" "${_tc_dest}.tc100-new.$$" || ! cmp -s "$_tc_stage/$_tc_rel" "${_tc_dest}.tc100-new.$$"; then
      for _tc_cleanup_rel in $_tc_files; do rm -f "$_tc_target/${_tc_cleanup_rel}.tc100-new.$$"; done
      return 1
    fi
    TC_COMMIT_COUNT=$((TC_COMMIT_COUNT + 1))
  done
  sync

  for _tc_rel in $_tc_files; do
    _tc_dest="$_tc_target/$_tc_rel"
    [ -f "${_tc_dest}.tc100-new.$$" ] || continue
    if ! mv -f "${_tc_dest}.tc100-new.$$" "$_tc_dest"; then
      tc_rollback_config_files "$_tc_backup" "$_tc_target" >/dev/null 2>&1 || true
      for _tc_cleanup_rel in $_tc_files; do rm -f "$_tc_target/${_tc_cleanup_rel}.tc100-new.$$"; done
      return 1
    fi
  done
  sync

  for _tc_rel in $_tc_files; do
    cmp -s "$_tc_stage/$_tc_rel" "$_tc_target/$_tc_rel" || {
      tc_rollback_config_files "$_tc_backup" "$_tc_target" >/dev/null 2>&1 || true
      return 1
    }
  done
  return 0
}
