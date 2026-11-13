# shellcheck shell=sh
# action.cgi commands: alerts and event detectors that had no page before (Settings -> Events).
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF, audit log) and helpers; F_* are the request
# fields. notify.conf and sound_detection.conf are sourced or parsed by shell scripts: every value written here is
# checked against a strict character set first (no quote, $, backquote, backslash, semicolon or space where the
# script would not expect it).
#   events_info          (read only) notify.conf, tamper.conf and the Vox / alarm part of sound_detection.conf as JSON;
#                        the Ntfy access token is never sent back, only whether one is set
#   set_notify_config    Ntfy, webhook, Telegram alerts, events, cooldown, picture  -> config/notify.conf
#   set_tamper_config    tamper detection on/off and its limits                     -> config/tamper.conf (its one place)
#   set_sound_options    Vox (babyphone) and alarm sound tracking                   -> config/sound_detection.conf

_ev_clean_val() {
  _ev_v="$1"
  while :; do
    case "$_ev_v" in
      ' '*|'	'*) _ev_v="${_ev_v#?}" ;;
      *' '|*'	') _ev_v="${_ev_v%?}" ;;
      *) break ;;
    esac
  done
  case "$_ev_v" in
    \"*\") _ev_v="${_ev_v#\"}"; _ev_v="${_ev_v%\"}" ;;
    \'*\') _ev_v="${_ev_v#\'}"; _ev_v="${_ev_v%\'}" ;;
  esac
  [ -n "$_ev_v" ] || _ev_v="$2"
}
_ev_bool_to() {
  case "$2" in 1|true|yes|on) eval "$1=1" ;; *) eval "$1=0" ;; esac
}
_ev_int_to() {
  _ev_iv="$2"
  case "$_ev_iv" in ''|*[!0-9]*|??????????*) _ev_iv="$5" ;; esac
  while [ "${#_ev_iv}" -gt 1 ] && [ "${_ev_iv#0}" != "$_ev_iv" ]; do _ev_iv="${_ev_iv#0}"; done
  [ "$_ev_iv" -lt "$3" ] && _ev_iv="$3"
  [ "$_ev_iv" -gt "$4" ] && _ev_iv="$4"
  eval "$1=\$_ev_iv"
}
_ev_j_to() {
  case "$2" in
    *\\*|*\"*) eval "$1=\$(json_escape \"\$2\")" ;;
    *) eval "$1=\$2" ;;
  esac
}
_ev_fail() { json_body_err "INVALID_VALUE" "$1"; }

  case "$F_cmd" in

    events_info)
      N=/mnt/config/notify.conf; T=/mnt/config/tamper.conf; S=/mnt/config/sound_detection.conf
      _ev_wh_en=0; _ev_wh_url=""; _ev_wh_m=POST
      _ev_nt_en=0; _ev_nt_url="https://ntfy.sh"; _ev_nt_top=""; _ev_nt_pri=default; _ev_nt_auth=""
      _ev_tg_en=0; _ev_att=1; _ev_cool=15; _ev_evs="motion sound tamper"
      _ev_seen=" "
      if [ -r "$N" ]; then
        while IFS= read -r _ev_l || [ -n "$_ev_l" ]; do
          while :; do case "$_ev_l" in ' '*|'	'*) _ev_l="${_ev_l#?}" ;; *) break ;; esac; done
          case "$_ev_l" in ''|'#'*) continue ;; esac
          _ev_k="${_ev_l%%=*}"
          [ "$_ev_k" != "$_ev_l" ] || continue
          case "$_ev_seen" in *" n:$_ev_k "*) continue ;; esac
          _ev_seen="${_ev_seen}n:$_ev_k "
          case "$_ev_k" in
            WEBHOOK_ENABLE) _ev_clean_val "${_ev_l#*=}" 0; _ev_wh_en="$_ev_v" ;;
            WEBHOOK_URL) _ev_clean_val "${_ev_l#*=}" ""; _ev_wh_url="$_ev_v" ;;
            WEBHOOK_METHOD) _ev_clean_val "${_ev_l#*=}" POST; _ev_wh_m="$_ev_v" ;;
            NTFY_ENABLE) _ev_clean_val "${_ev_l#*=}" 0; _ev_nt_en="$_ev_v" ;;
            NTFY_URL) _ev_clean_val "${_ev_l#*=}" "https://ntfy.sh"; _ev_nt_url="$_ev_v" ;;
            NTFY_TOPIC) _ev_clean_val "${_ev_l#*=}" ""; _ev_nt_top="$_ev_v" ;;
            NTFY_PRIORITY) _ev_clean_val "${_ev_l#*=}" default; _ev_nt_pri="$_ev_v" ;;
            NTFY_AUTH) _ev_clean_val "${_ev_l#*=}" ""; _ev_nt_auth="$_ev_v" ;;
            TELEGRAM_NOTIFY_ENABLE) _ev_clean_val "${_ev_l#*=}" 0; _ev_tg_en="$_ev_v" ;;
            NOTIFY_ATTACH_SNAPSHOT) _ev_clean_val "${_ev_l#*=}" 1; _ev_att="$_ev_v" ;;
            NOTIFY_COOLDOWN_SECONDS) _ev_clean_val "${_ev_l#*=}" 15; _ev_cool="$_ev_v" ;;
            NOTIFY_EVENTS) _ev_clean_val "${_ev_l#*=}" "motion sound tamper"; _ev_evs="$_ev_v" ;;
          esac
        done < "$N"
      fi
      _ev_auth=0; [ -n "$_ev_nt_auth" ] && _ev_auth=1
      _ev_tg=0
      if [ -r /mnt/config/telegram.conf ]; then
        while IFS= read -r _ev_l || [ -n "$_ev_l" ]; do
          while :; do case "$_ev_l" in ' '*|'	'*) _ev_l="${_ev_l#?}" ;; *) break ;; esac; done
          case "$_ev_l" in ''|'#'*) continue ;; apiToken=*) _ev_clean_val "${_ev_l#*=}" ""; [ -n "$_ev_v" ] && _ev_tg=1; break ;; esac
        done < /mnt/config/telegram.conf
      fi
      _ev_ta=0
      if [ -r /tmp/cam_tamper ]; then
        while IFS= read -r _ev_l || [ -n "$_ev_l" ]; do
          case "$_ev_l" in *1*) _ev_ta=1; break ;; esac
        done < /tmp/cam_tamper
      fi
      _ev_t_en=0; _ev_t_hold=6; _ev_t_drop=50; _ev_t_lum=15
      if [ -r "$T" ]; then
        while IFS= read -r _ev_l || [ -n "$_ev_l" ]; do
          while :; do case "$_ev_l" in ' '*|'	'*) _ev_l="${_ev_l#?}" ;; *) break ;; esac; done
          case "$_ev_l" in ''|'#'*) continue ;; esac
          _ev_k="${_ev_l%%=*}"
          [ "$_ev_k" != "$_ev_l" ] || continue
          case "$_ev_seen" in *" t:$_ev_k "*) continue ;; esac
          _ev_seen="${_ev_seen}t:$_ev_k "
          case "$_ev_k" in
            ENABLE) _ev_clean_val "${_ev_l#*=}" 0; _ev_t_en="$_ev_v" ;;
            TAMPER_HOLD_SEC) _ev_clean_val "${_ev_l#*=}" 6; _ev_t_hold="$_ev_v" ;;
            TAMPER_JPEG_DROP_PCT) _ev_clean_val "${_ev_l#*=}" 50; _ev_t_drop="$_ev_v" ;;
            TAMPER_LUMA_MIN) _ev_clean_val "${_ev_l#*=}" 15; _ev_t_lum="$_ev_v" ;;
          esac
        done < "$T"
      fi
      _ev_s_en=0; _ev_s_vox=0; _ev_s_vh=5; _ev_s_al=0; _ev_s_ah=15; _ev_s_ml=1
      if [ -r "$S" ]; then
        while IFS= read -r _ev_l || [ -n "$_ev_l" ]; do
          while :; do case "$_ev_l" in ' '*|'	'*) _ev_l="${_ev_l#?}" ;; *) break ;; esac; done
          case "$_ev_l" in ''|'#'*) continue ;; esac
          _ev_k="${_ev_l%%=*}"
          [ "$_ev_k" != "$_ev_l" ] || continue
          case "$_ev_seen" in *" s:$_ev_k "*) continue ;; esac
          _ev_seen="${_ev_seen}s:$_ev_k "
          case "$_ev_k" in
            ENABLE) _ev_clean_val "${_ev_l#*=}" 0; _ev_s_en="$_ev_v" ;;
            VOX_MODE) _ev_clean_val "${_ev_l#*=}" 0; _ev_s_vox="$_ev_v" ;;
            VOX_HOLD_SECONDS) _ev_clean_val "${_ev_l#*=}" 5; _ev_s_vh="$_ev_v" ;;
            ALARM_DETECT) _ev_clean_val "${_ev_l#*=}" 0; _ev_s_al="$_ev_v" ;;
            ALARM_HOLD_SECONDS) _ev_clean_val "${_ev_l#*=}" 15; _ev_s_ah="$_ev_v" ;;
            MIN_LOUD_SECONDS) _ev_clean_val "${_ev_l#*=}" 1; _ev_s_ml="$_ev_v" ;;
          esac
        done < "$S"
      fi
      _ev_bool_to _ev_wh_en "$_ev_wh_en"
      _ev_j_to _ev_wh_url_j "$_ev_wh_url"
      _ev_j_to _ev_wh_m_j "$_ev_wh_m"
      _ev_bool_to _ev_nt_en "$_ev_nt_en"
      _ev_j_to _ev_nt_url_j "$_ev_nt_url"
      _ev_j_to _ev_nt_top_j "$_ev_nt_top"
      _ev_j_to _ev_nt_pri_j "$_ev_nt_pri"
      _ev_bool_to _ev_tg_en "$_ev_tg_en"
      _ev_bool_to _ev_att "$_ev_att"
      _ev_int_to _ev_cool "$_ev_cool" 0 3600 15
      _ev_j_to _ev_evs_j "$_ev_evs"
      _ev_bool_to _ev_t_en "$_ev_t_en"
      _ev_int_to _ev_t_hold "$_ev_t_hold" 2 120 6
      _ev_int_to _ev_t_drop "$_ev_t_drop" 10 90 50
      _ev_int_to _ev_t_lum "$_ev_t_lum" 0 100 15
      _ev_bool_to _ev_s_en "$_ev_s_en"
      _ev_bool_to _ev_s_vox "$_ev_s_vox"
      _ev_int_to _ev_s_vh "$_ev_s_vh" 1 600 5
      _ev_bool_to _ev_s_al "$_ev_s_al"
      _ev_int_to _ev_s_ah "$_ev_s_ah" 5 120 15
      _ev_int_to _ev_s_ml "$_ev_s_ml" 1 10 1
      printf '{"ok":true,"notify":{"webhook_enable":%s,"webhook_url":"%s","webhook_method":"%s","ntfy_enable":%s,"ntfy_url":"%s","ntfy_topic":"%s","ntfy_priority":"%s","ntfy_auth_set":%s,"telegram_enable":%s,"telegram_ready":%s,"attach":%s,"cooldown":%s,"events":"%s"},' \
        "$_ev_wh_en" "$_ev_wh_url_j" "$_ev_wh_m_j" "$_ev_nt_en" "$_ev_nt_url_j" "$_ev_nt_top_j" "$_ev_nt_pri_j" "$_ev_auth" "$_ev_tg_en" "$_ev_tg" "$_ev_att" "$_ev_cool" "$_ev_evs_j"
      printf '"tamper":{"enable":%s,"hold":%s,"drop_pct":%s,"luma_min":%s,"active":%s},' \
        "$_ev_t_en" "$_ev_t_hold" "$_ev_t_drop" "$_ev_t_lum" "$_ev_ta"
      printf '"sound":{"enable":%s,"vox_mode":%s,"vox_hold":%s,"alarm_detect":%s,"alarm_hold":%s,"min_loud":%s}}\n' \
        "$_ev_s_en" "$_ev_s_vox" "$_ev_s_vh" "$_ev_s_al" "$_ev_s_ah" "$_ev_s_ml"
    ;;

    set_notify_config)
      N=/mnt/config/notify.conf
      install_config "$N"
      [ -f "$N" ] || : > "$N"
      _wh_on="$(normalize_bool "${F_webhook_enable:-0}")"
      _wh_url="${F_webhook_url:-}"
      _wh_m="$(printf '%s' "${F_webhook_method:-POST}" | tr 'a-z' 'A-Z')"
      _nt_on="$(normalize_bool "${F_ntfy_enable:-0}")"
      _nt_url="${F_ntfy_url:-https://ntfy.sh}"; _nt_url="${_nt_url%/}"
      _nt_topic="${F_ntfy_topic:-}"
      _nt_prio="${F_ntfy_priority:-default}"
      _nt_auth="${F_ntfy_auth:-}"
      _tg_on="$(normalize_bool "${F_telegram_notify_enable:-0}")"
      _att="$(normalize_bool "${F_notify_attach_snapshot:-0}")"
      _cool="$(sanitize_int_range "${F_notify_cooldown:-15}" 0 3600 15)"
      _evs=""
      [ "$(normalize_bool "${F_notify_event_motion:-0}")" = 1 ] && _evs="motion"
      [ "$(normalize_bool "${F_notify_event_sound:-0}")" = 1 ] && _evs="${_evs:+$_evs }sound"
      [ "$(normalize_bool "${F_notify_event_tamper:-0}")" = 1 ] && _evs="${_evs:+$_evs }tamper"
      # URLs: http(s), host and path characters only (sourced inside double quotes by notify.sh)
      _ev_url_ok() { case "$1" in '') return 0 ;; http://*|https://*) ;; *) return 1 ;; esac
                     case "$1" in *[!A-Za-z0-9._~:/?#@%=\&+-]*) return 1 ;; esac; [ "${#1}" -le 300 ]; }
      _ev_url_ok "$_wh_url" || { _ev_fail "The webhook address must start with http:// or https:// and hold no spaces or quotes."; return 0 2>/dev/null || exit 0; }
      _ev_url_ok "$_nt_url" || { _ev_fail "The Ntfy server must start with http:// or https:// and hold no spaces or quotes."; return 0 2>/dev/null || exit 0; }
      case "$_wh_m" in POST|PUT) ;; *) _wh_m=POST ;; esac
      case "$_nt_topic" in *[!A-Za-z0-9_-]*) _ev_fail "The Ntfy topic may hold letters, digits, - and _ only."; return 0 2>/dev/null || exit 0 ;; esac
      [ "${#_nt_topic}" -le 64 ] || { _ev_fail "The Ntfy topic is too long (64 characters at most)."; return 0 2>/dev/null || exit 0; }
      case "$_nt_prio" in min|low|default|high|urgent) ;; *) _nt_prio=default ;; esac
      case "$_nt_auth" in *[!A-Za-z0-9\ ._~+/=-]*) _ev_fail "The Ntfy access token holds characters that are not allowed."; return 0 2>/dev/null || exit 0 ;; esac
      [ "$_wh_on" = 1 ] && [ -z "$_wh_url" ] && { _ev_fail "Enter the webhook address to enable it."; return 0 2>/dev/null || exit 0; }
      [ "$_nt_on" = 1 ] && [ -z "$_nt_topic" ] && { _ev_fail "Enter the Ntfy topic to enable it."; return 0 2>/dev/null || exit 0; }
      rewrite_config "$N" WEBHOOK_ENABLE "$_wh_on"
      rewrite_config "$N" WEBHOOK_URL "\"$_wh_url\""
      rewrite_config "$N" WEBHOOK_METHOD "\"$_wh_m\""
      rewrite_config "$N" NTFY_ENABLE "$_nt_on"
      rewrite_config "$N" NTFY_URL "\"$_nt_url\""
      rewrite_config "$N" NTFY_TOPIC "\"$_nt_topic\""
      rewrite_config "$N" NTFY_PRIORITY "\"$_nt_prio\""
      # the token is a secret: an empty field keeps the saved one, "-" removes it
      if [ "$_nt_auth" = "-" ]; then rewrite_config "$N" NTFY_AUTH '""'
      elif [ -n "$_nt_auth" ]; then rewrite_config "$N" NTFY_AUTH "\"$_nt_auth\""; fi
      rewrite_config "$N" TELEGRAM_NOTIFY_ENABLE "$_tg_on"
      rewrite_config "$N" NOTIFY_ATTACH_SNAPSHOT "$_att"
      rewrite_config "$N" NOTIFY_COOLDOWN_SECONDS "$_cool"
      rewrite_config "$N" NOTIFY_EVENTS "\"$_evs\""
      sh /mnt/scripts/presence-mode.sh manual
      json_body_ok "Alerts saved."
    ;;

    set_tamper_config)
      T=/mnt/config/tamper.conf
      install_config "$T"
      [ -f "$T" ] || : > "$T"
      _t_on="$(normalize_bool "${F_tamper_enable:-0}")"
      rewrite_config "$T" ENABLE "$_t_on"
      rewrite_config "$T" TAMPER_HOLD_SEC "$(sanitize_int_range "${F_tamper_hold:-6}" 2 120 6)"
      rewrite_config "$T" TAMPER_JPEG_DROP_PCT "$(sanitize_int_range "${F_tamper_drop_pct:-50}" 10 90 50)"
      rewrite_config "$T" TAMPER_LUMA_MIN "$(sanitize_int_range "${F_tamper_luma_min:-15}" 0 100 15)"
      # the job runs from the housekeeper (as v3/autorun-linux66.sh registers it at boot): on at once, off at once
      if [ "$_t_on" = 1 ]; then
        sh /mnt/scripts/housekeeper.sh job add tamper-detect bg 2 5 /var/run/tamper-detect.pid \
          sh /mnt/scripts/tamper-detect.sh hk </dev/null >/dev/null 2>&1 || true
      else
        sh /mnt/scripts/housekeeper.sh job del tamper-detect </dev/null >/dev/null 2>&1 || true
        rm -f /tmp/cam_tamper
      fi
      json_body_ok "Tamper detection saved."
    ;;

    set_sound_options)
      S=/mnt/config/sound_detection.conf
      install_config "$S"
      [ -f "$S" ] || : > "$S"
      rewrite_config "$S" VOX_MODE "$(normalize_bool "${F_vox_mode:-0}")"
      rewrite_config "$S" VOX_HOLD_SECONDS "$(sanitize_int_range "${F_vox_hold:-5}" 1 600 5)"
      rewrite_config "$S" ALARM_DETECT "$(normalize_bool "${F_alarm_detect:-0}")"
      rewrite_config "$S" ALARM_HOLD_SECONDS "$(sanitize_int_range "${F_alarm_hold:-15}" 5 120 15)"
      rewrite_config "$S" MIN_LOUD_SECONDS "$(sanitize_int_range "${F_min_loud:-1}" 1 10 1)"
      # the sound detection daemon reads its file at every check: nothing to restart
      json_body_ok "Sound options saved (they work while sound detection is on)."
    ;;

  esac
