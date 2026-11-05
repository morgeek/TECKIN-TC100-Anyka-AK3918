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
  [ "${#_tc_value}" -le 10 ] || return 1
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
    idle_fps) tc_uint_range "$_tc_value" 0 24 ;;
    idle_after) tc_uint_range "$_tc_value" 1 3600 ;;
    persist_min) tc_uint_range "$_tc_value" 1 1440 ;;
    width) tc_uint_range "$_tc_value" 160 1920 && [ $((_tc_value % 2)) -eq 0 ] ;;
    height) tc_uint_range "$_tc_value" 120 1080 && [ $((_tc_value % 2)) -eq 0 ] ;;
    mainres) case "$_tc_value" in 720|1080) ;; *) return 1 ;; esac ;;
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
    print_level) [ -z "$_tc_value" ] || tc_uint_range "$_tc_value" 0 9 ;;
    minute) tc_uint_range "$_tc_value" 0 59 ;;
    weekday) case "$_tc_value" in '*'|[0-6]|1-5|0,6) ;; *) return 1 ;; esac ;;
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
    sound_interval) tc_uint_range "$_tc_value" 1 300 ;;
    record_post) tc_uint_range "$_tc_value" 0 60 ;;
    record_duration) tc_uint_range "$_tc_value" 10 600 ;;
    disk_mb) tc_uint_range "$_tc_value" 0 65535 ;;
    positive_interval) tc_uint_range "$_tc_value" 1 86400 ;;
    qos) tc_uint_range "$_tc_value" 0 2 ;;
    nonnegative) tc_uint_range "$_tc_value" 0 9999999 ;;
    # Ranges written in the table itself: u:MIN:MAX (unsigned integer).
    u:*:*) _tc_r="${_tc_type#u:}"; tc_uint_range "$_tc_value" "${_tc_r%%:*}" "${_tc_r#*:}" ;;
    sound_db) case "$_tc_value" in 0|-[1-9]|-[1-8][0-9]|-90) ;; *) return 1 ;; esac ;;
    isp_effect)
      case "$_tc_value" in ''|0|[1-9]|-[1-9]|[1-4][0-9]|-[1-4][0-9]|50|-50) ;; *) return 1 ;; esac ;;
    isp_power_hz) case "$_tc_value" in ''|50|60|auto) ;; *) return 1 ;; esac ;;
    isp_exposure_pct) [ -z "$_tc_value" ] || tc_uint_range "$_tc_value" 10 100 ;;
    isp_mask_color) case "$_tc_value" in black|gray|white) ;; *) return 1 ;; esac ;;
    isp_mask)
      # x1,y1,x2,y2 in percent, x2 > x1 and y2 > y1; empty = no mask
      [ -z "$_tc_value" ] && return 0
      case "$_tc_value" in *[!0-9,]*) return 1 ;; esac
      _tc_ifs="$IFS"; IFS=,
      set -- $_tc_value
      IFS="$_tc_ifs"
      [ $# -eq 4 ] || return 1
      for _tc_n in "$@"; do
        [ -n "$_tc_n" ] && [ "${#_tc_n}" -le 3 ] && [ "$_tc_n" -le 100 ] || return 1
      done
      [ "$(($3 + 0))" -gt "$(($1 + 0))" ] && [ "$(($4 + 0))" -gt "$(($2 + 0))" ] ;;
    rec_when) case "$_tc_value" in always|motion|offline) ;; *) return 1 ;; esac ;;
    rec_stream) case "$_tc_value" in main|sub) ;; *) return 1 ;; esac ;;
    dn_source) case "$_tc_value" in luma|ae|isp|vendor) ;; *) return 1 ;; esac ;;
    ir_led_mode) case "$_tc_value" in off|force|auto) ;; *) return 1 ;; esac ;;
    http_method) case "$_tc_value" in POST|PUT) ;; *) return 1 ;; esac ;;
    ntfy_priority) case "$_tc_value" in min|low|default|high|urgent|max|[1-5]) ;; *) return 1 ;; esac ;;
    ntfy_topic)
      [ "${#_tc_value}" -le 64 ] || return 1
      case "$_tc_value" in *[!A-Za-z0-9_-]*) return 1 ;; esac ;;
    events)
      # a subset of the events notify.sh knows, separated by single spaces (empty = none)
      [ "${#_tc_value}" -le 64 ] || return 1
      case "$_tc_value" in *[!a-z\ ]*|' '*|*' '|*'  '*) return 1 ;; esac
      for _tc_w in $_tc_value; do
        case "$_tc_w" in motion|sound|tamper) ;; *) return 1 ;; esac
      done ;;
    ipv4_optional)
      [ -z "$_tc_value" ] && return 0
      case "$_tc_value" in *[!0-9.]*|.*|*.|*..*) return 1 ;; esac
      _tc_ifs="$IFS"; IFS=.
      set -- $_tc_value
      IFS="$_tc_ifs"
      [ $# -eq 4 ] || return 1
      for _tc_n in "$@"; do tc_uint_range "$_tc_n" 0 255 || return 1; done ;;
    url|url_optional)
      [ "$_tc_type" = url_optional ] && [ -z "$_tc_value" ] && return 0
      [ "${#_tc_value}" -le 200 ] || return 1
      case "$_tc_value" in http://?*|https://?*) ;; *) return 1 ;; esac
      case "$_tc_value" in *[!A-Za-z0-9._~:/?\&=%+@#,-]*) return 1 ;; esac ;;
    ntfy_auth)
      [ "${#_tc_value}" -le 200 ] || return 1
      case "$_tc_value" in *[\\\$\`\;\&\|\<\>\"\']*) return 1 ;; esac ;;
    password)
      # same rules as the web UI password change (action.d/system.sh set_all_password)
      [ "${#_tc_value}" -ge 4 ] && [ "${#_tc_value}" -le 128 ] || return 1
      case "$_tc_value" in *[\"\'\$\`\\\ %]*|*"$(printf '\t')"*) return 1 ;; esac ;;
    wifi_ssid)
      # a network name for wpa_supplicant.conf (a quoted string): no quote, no backslash
      [ "${#_tc_value}" -ge 1 ] && [ "${#_tc_value}" -le 32 ] || return 1
      case "$_tc_value" in *[\\\"]*) return 1 ;; esac ;;
    wifi_psk)
      # empty = open network
      [ -z "$_tc_value" ] && return 0
      [ "${#_tc_value}" -ge 8 ] && [ "${#_tc_value}" -le 63 ] || return 1
      case "$_tc_value" in *[\\\"]*) return 1 ;; esac ;;
    country_optional)
      # boot.conf WIFI_COUNTRY (scripts/wifi-country.sh): an ISO 3166 code, empty = the world rules
      case "$_tc_value" in ''|[A-Z][A-Z]) return 0 ;; esac
      return 1 ;;
    rescue_ssid_optional)
      # written inside "..." of the sourced boot.conf: nothing the shell would expand
      [ -z "$_tc_value" ] && return 0
      [ "${#_tc_value}" -le 32 ] || return 1
      case "$_tc_value" in *[\\\$\`\"\']*) return 1 ;; esac ;;
    rescue_psk_optional)
      [ -z "$_tc_value" ] && return 0
      [ "${#_tc_value}" -ge 8 ] && [ "${#_tc_value}" -le 63 ] || return 1
      case "$_tc_value" in *[\\\$\`\"\']*) return 1 ;; esac ;;
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

# tc_apply_edits FILE EDITS: applies, in ONE pass, a list of edits that tc_set_flat / tc_set_ini would apply one by one
# (each of those rewrites the whole file with its own awk: about 0.3 s per value on the camera, so a JSON import of
# ~120 values took 40 s). EDITS holds one edit per line: MODE<TAB>SECTION<TAB>KEY<TAB>VALUE, MODE flat or ini (SECTION
# is ignored for flat; root = before the first [N] header). Same result as the sequential calls: the first active line
# of a key gets the last value given, its other active lines are dropped, a missing key is added (ini: at the end of its
# section, root: before the first header). Values are printable text (tc_normalize_and_validate), so never hold a tab.
# A file gets flat edits or ini edits, not both for one key (the import table never mixes them in a file).
tc_apply_edits()
{
  _tc_file="$1"; _tc_tmp="${1}.set.$$"
  awk -v edits="$2" '
    BEGIN {
      n = 0
      while ((getline line < edits) > 0) {
        i = index(line, "\t"); m = substr(line, 1, i - 1); line = substr(line, i + 1)
        i = index(line, "\t"); s = substr(line, 1, i - 1); line = substr(line, i + 1)
        i = index(line, "\t"); k = substr(line, 1, i - 1); v = substr(line, i + 1)
        id = (m == "flat" ? "F" : "I" s) SUBSEP k
        if (!(id in val)) { n++; order[n] = id; ini[id] = (m != "flat"); sec[id] = s; key[id] = k }
        val[id] = v
      }
      close(edits)
      current = "root"
    }
    function add_missing(section,   j, id) {
      for (j = 1; j <= n; j++) {
        id = order[j]
        if (ini[id] && sec[id] == section && !done[id]) { print key[id] "=" val[id]; done[id] = 1 }
      }
    }
    /^\[[0-9]+\][[:space:]]*$/ {
      add_missing(current)
      current = $0; gsub(/^\[|\][[:space:]]*$/, "", current)
      print; next
    }
    $0 !~ /^[[:space:]]*#/ && match($0, /^[[:space:]]*[^=[:space:]]+=/) {
      k = substr($0, RSTART, RLENGTH - 1); sub(/^[[:space:]]*/, "", k)
      id = "F" SUBSEP k
      if (!(id in val)) id = "I" current SUBSEP k
      if (id in val) {
        if (!done[id]) print key[id] "=" val[id]
        done[id] = 1; next
      }
    }
    { print }
    END {
      add_missing(current)
      add_missing("root")
      for (j = 1; j <= n; j++) { id = order[j]; if (!ini[id] && !done[id]) print key[id] "=" val[id] }
    }
  ' "$_tc_file" > "$_tc_tmp" && mv "$_tc_tmp" "$_tc_file" || {
    rm -f "$_tc_tmp"; return 1;
  }
}

# Flat-key cache: tc_validate_candidate checks a file key by key (~90 tc_check_flat calls on boot.conf, two awk runs
# each: ~12 s of a JSON import on the camera). While a file is validated, its active KEY=value lines are read once
# (first line of each key, as the awk lookups below) and tc_has_flat / tc_read_flat answer from that, without a fork.
_tc_cache_file=""; _tc_cache=""
tc_flat_cache_load()
{
  _tc_cache_file="$1"
  _tc_cache="
$(awk -F= '$0 !~ /^[[:space:]]*#/ && !($1 in seen) {seen[$1]=1; k=$1; sub(/^[^=]*=/, ""); print k "=" $0}' "$1" 2>/dev/null)
"
  # the same for [N] sections (rtspserver.conf): one "[SECTION]KEY=value" line per first key of a section
  _tc_icache="
$(awk -F= '
    BEGIN { section="root" }
    /^\[[0-9]+\][[:space:]]*$/ { section=$0; gsub(/^\[|\][[:space:]]*$/, "", section); next }
    $0 !~ /^[[:space:]]*#/ && !((section, $1) in seen) { seen[section, $1]=1; k=$1; sub(/^[^=]*=/, ""); print "[" section "]" k "=" $0 }
  ' "$1" 2>/dev/null)
"
}

# tc_ini_value FILE SECTION KEY: TC_INI_VALUE = what tc_read_ini prints (no fork when FILE is cached); 1 when absent
tc_ini_value()
{
  if [ -n "$_tc_cache_file" ] && [ "$1" = "$_tc_cache_file" ]; then
    TC_INI_VALUE=""
    case "$_tc_icache" in
      *"
[$2]$3="*) TC_INI_VALUE="${_tc_icache#*"
[$2]$3="}"; TC_INI_VALUE="${TC_INI_VALUE%%"
"*}"; return 0 ;;
    esac
    return 1
  fi
  tc_has_ini "$1" "$2" "$3" || { TC_INI_VALUE=""; return 1; }
  TC_INI_VALUE="$(tc_read_ini "$1" "$2" "$3")"
}

tc_flat_cache_clear()
{
  _tc_cache_file=""; _tc_cache=""; _tc_icache=""
}

tc_read_flat()
{
  if [ -n "$_tc_cache_file" ] && [ "$1" = "$_tc_cache_file" ]; then
    case "$_tc_cache" in
      *"
$2="*) _tc_rf="${_tc_cache#*"
$2="}"; printf '%s\n' "${_tc_rf%%"
"*}" ;;
    esac
    return 0
  fi
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
  if [ -n "$_tc_cache_file" ] && [ "$1" = "$_tc_cache_file" ]; then
    case "$_tc_cache" in *"
$2="*) return 0 ;; esac
    return 1
  fi
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
  tc_ini_value "$1" "$2" "$3" || _tc_fail "$4:[$2].$3:missing"
}

# tc_flat_value FILE KEY: TC_FLAT_VALUE = what tc_read_flat prints, without a subshell when FILE is cached
tc_flat_value()
{
  if [ -n "$_tc_cache_file" ] && [ "$1" = "$_tc_cache_file" ]; then
    TC_FLAT_VALUE=""
    case "$_tc_cache" in
      *"
$2="*) TC_FLAT_VALUE="${_tc_cache#*"
$2="}"; TC_FLAT_VALUE="${TC_FLAT_VALUE%%"
"*}" ;;
    esac
    return 0
  fi
  TC_FLAT_VALUE="$(tc_read_flat "$1" "$2")"
}

tc_check_flat()
{
  tc_has_flat "$1" "$2" || return 0
  tc_flat_value "$1" "$2"; _tc_check_value="$TC_FLAT_VALUE"
  tc_strip_quotes "$_tc_check_value"
  tc_normalize_and_validate "$3" "$TC_UNQUOTED_VALUE" || _tc_fail "$4:$2"
}

tc_check_pair()
{
  # tc_check_pair FILE HIGH_KEY LOW_KEY LABEL: when both keys are set, HIGH must be greater than LOW
  tc_has_flat "$1" "$2" && tc_has_flat "$1" "$3" || return 0
  tc_flat_value "$1" "$2"; _tc_hi="$TC_FLAT_VALUE"; tc_flat_value "$1" "$3"; _tc_lo="$TC_FLAT_VALUE"
  case "$_tc_hi$_tc_lo" in *[!0-9]*) return 0 ;; esac
  [ -n "$_tc_hi" ] && [ -n "$_tc_lo" ] || return 0
  [ "$_tc_hi" -gt "$_tc_lo" ] || _tc_fail "$4:$2<=$3"
}

tc_check_ini()
{
  tc_ini_value "$1" "$2" "$3" || return 0
  _tc_check_value="$TC_INI_VALUE"
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
  tc_check_ini "$_tc_file" 0 mainres mainres "$_tc_label" || return 1   # main picture size (720p, item 8)
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
    tc_ini_value "$_tc_file" "$_tc_section" minqp; _tc_minqp="$TC_INI_VALUE"
    tc_ini_value "$_tc_file" "$_tc_section" maxqp; _tc_maxqp="$TC_INI_VALUE"
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
  # the flat-key cache only lives while this one file is validated
  [ -f "$2" ] && tc_flat_cache_load "$2"
  _tc_validate_candidate_body "$1" "$2"
  _tc_vc_rc=$?
  tc_flat_cache_clear
  return $_tc_vc_rc
}

_tc_validate_candidate_body()
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
    boot.conf|mqtt.conf|service_trim.conf|recording.conf|sound_detection.conf|daynight.conf|notify.conf|tamper.conf|isp_tune.conf|motion.conf|telegram.conf|telnetd.conf|ftp.conf|onvif.conf|network.conf|dns.conf|sendmail.conf|timelapse.conf|onvif_events.conf)
      /bin/sh -n "$_tc_file" >/dev/null 2>&1 || _tc_fail "$_tc_rel:shell_syntax" || return 1 ;;
  esac
  case "$_tc_rel" in
    boot.conf)
      tc_check_flat "$_tc_file" REBOOT_SCHEDULE_HOUR hour "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REBOOT_SCHEDULE_MINUTE minute "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REBOOT_SCHEDULE_WEEKDAY weekday "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" RTSP_SUBSTREAM bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" RTSP_AUDIO bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" RTSP_FPS_LOCK bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" RTSP_MIC_OFF_WHEN_NO_AUDIO bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" VENDOR_PRINT_LEVEL print_level "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" ISP_TUNE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" ONVIF_STREAM_POLICY onvif_policy "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_LOCAL bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_WHEN rec_when "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_STREAM rec_stream "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_SEGMENT_SEC u:30:3600 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_RESERVE_MB u:16:65535 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_POSTROLL_SEC u:0:3600 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_OFFLINE_SEC u:0:3600 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_CLIENT ipv4_optional "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_RING_KB u:128:8192 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_AUDIO bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" REC_KEEP_EVENTS bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" SD_AUTO_REPAIR bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NET_GUARD_SOFT bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" PRIVACY_SCREEN bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WIFI_RESCUE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WIFI_RESCUE_AFTER_MIN u:2:1440 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WIFI_RESCUE_MANUAL_MIN u:1:1440 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WIFI_RESCUE_SSID rescue_ssid_optional "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WIFI_RESCUE_PSK rescue_psk_optional "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" BOOT_GUARD bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" LOG_PERSIST bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" LOG_PERSIST_MIN persist_min "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WIFI_QUALITY bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WIFI_COUNTRY country_optional "$_tc_rel" || return 1 ;;
    mqtt.conf)
      tc_require_flat "$_tc_file" MQTT_ENABLE "$_tc_rel" || return 1
      tc_require_flat "$_tc_file" MQTT_PORT "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_PORT port "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_QOS qos "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_HEALTH_INTERVAL_SECONDS positive_interval "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_HA_DISCOVERY_ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_SNAPSHOT_ON_EVENT bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MQTT_SNAPSHOT_COOLDOWN_SECONDS u:1:3600 "$_tc_rel" || return 1 ;;
    recording.conf)
      tc_check_flat "$_tc_file" rec_motion_activated bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" rec_postrecord_sec record_post "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" rec_file_duration_sec record_duration "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" rec_reserverd_disk_mb disk_mb "$_tc_rel" || return 1 ;;
    sound_detection.conf)
      tc_check_flat "$_tc_file" ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" THRESHOLD sound_threshold "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" THRESHOLD_DB sound_db "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" INTERVAL sound_interval "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MIN_LOUD_SECONDS u:1:10 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" VOX_MODE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" VOX_HOLD_SECONDS u:1:3600 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" ALARM_DETECT bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" ALARM_HOLD_SECONDS u:1:3600 "$_tc_rel" || return 1 ;;
    daynight.conf)
      tc_check_flat "$_tc_file" LUMA_NIGHT u:0:255 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" LUMA_DAY u:0:255 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" DAYNIGHT_SOURCE dn_source "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" AE_NIGHT_ABOVE u:1:999999999 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" AE_DAY_BELOW u:0:999999999 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NIGHT_HOLD u:1:3600 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" DAY_HOLD u:1:3600 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" VENDOR_NIGHT_LUM u:1:999999 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" VENDOR_DAY_LUM u:0:999999 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" IR_LED_MAX_ON u:0:172800 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NIGHT_STYLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" LOWLIGHT_FPS bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" IR_LED_MODE ir_led_mode "$_tc_rel" || return 1
      # the day threshold must lie above the night one (the daemon would flap otherwise)
      tc_check_pair "$_tc_file" LUMA_DAY LUMA_NIGHT "$_tc_rel" || return 1
      tc_check_pair "$_tc_file" AE_NIGHT_ABOVE AE_DAY_BELOW "$_tc_rel" || return 1
      tc_check_pair "$_tc_file" VENDOR_NIGHT_LUM VENDOR_DAY_LUM "$_tc_rel" || return 1 ;;
    notify.conf)
      tc_check_flat "$_tc_file" WEBHOOK_ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WEBHOOK_URL url_optional "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" WEBHOOK_METHOD http_method "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NTFY_ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NTFY_URL url_optional "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NTFY_TOPIC ntfy_topic "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NTFY_PRIORITY ntfy_priority "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NTFY_AUTH ntfy_auth "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" TELEGRAM_NOTIFY_ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NOTIFY_ATTACH_SNAPSHOT bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NOTIFY_COOLDOWN_SECONDS u:0:86400 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" NOTIFY_EVENTS events "$_tc_rel" || return 1 ;;
    tamper.conf)
      tc_check_flat "$_tc_file" ENABLE bool "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" TAMPER_HOLD_SEC u:1:600 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" TAMPER_JPEG_DROP_PCT u:1:100 "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" TAMPER_LUMA_MIN u:0:255 "$_tc_rel" || return 1 ;;
    isp_tune.conf)
      for _tc_k in BRIGHTNESS CONTRAST SATURATION SHARPNESS HUE; do
        tc_check_flat "$_tc_file" "$_tc_k" isp_effect "$_tc_rel" || return 1
      done
      tc_check_flat "$_tc_file" POWER_HZ isp_power_hz "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" EXPOSURE_MAX_PCT isp_exposure_pct "$_tc_rel" || return 1
      tc_check_flat "$_tc_file" MASK_COLOR isp_mask_color "$_tc_rel" || return 1
      for _tc_k in MASK1 MASK2 MASK3 MASK4; do
        tc_check_flat "$_tc_file" "$_tc_k" isp_mask "$_tc_rel" || return 1
      done ;;
    wpa_supplicant.conf)
      # not sourced by a shell, but wpa_supplicant must still find at least one network
      grep -q '^[[:space:]]*ssid="' "$_tc_file" || _tc_fail "$_tc_rel:no_network" || return 1 ;;
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
