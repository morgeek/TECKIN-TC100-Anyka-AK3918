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

_ev_kv() { _ev_v="$(read_kv_config_value "$1" "$2" "$3")"; _ev_v="${_ev_v#\"}"; _ev_v="${_ev_v%\"}"; printf '%s' "$_ev_v"; }
_ev_b() { case "$1" in 1|true|yes|on) echo 1 ;; *) echo 0 ;; esac; }
_ev_fail() { json_body_err "INVALID_VALUE" "$1"; }

  case "$F_cmd" in

    events_info)
      N=/mnt/config/notify.conf; T=/mnt/config/tamper.conf; S=/mnt/config/sound_detection.conf
      _ev_auth=0; [ -n "$(_ev_kv $N NTFY_AUTH '')" ] && _ev_auth=1
      _ev_tg=0; [ -n "$(_ev_kv /mnt/config/telegram.conf apiToken '')" ] && _ev_tg=1
      _ev_ta=0; [ -f /tmp/cam_tamper ] && grep -q 1 /tmp/cam_tamper 2>/dev/null && _ev_ta=1
      printf '{"ok":true,"notify":{"webhook_enable":%s,"webhook_url":"%s","webhook_method":"%s","ntfy_enable":%s,"ntfy_url":"%s","ntfy_topic":"%s","ntfy_priority":"%s","ntfy_auth_set":%s,"telegram_enable":%s,"telegram_ready":%s,"attach":%s,"cooldown":%s,"events":"%s"},' \
        "$(_ev_b "$(_ev_kv $N WEBHOOK_ENABLE 0)")" "$(json_escape "$(_ev_kv $N WEBHOOK_URL '')")" "$(json_escape "$(_ev_kv $N WEBHOOK_METHOD POST)")" \
        "$(_ev_b "$(_ev_kv $N NTFY_ENABLE 0)")" "$(json_escape "$(_ev_kv $N NTFY_URL https://ntfy.sh)")" "$(json_escape "$(_ev_kv $N NTFY_TOPIC '')")" \
        "$(json_escape "$(_ev_kv $N NTFY_PRIORITY default)")" "$_ev_auth" "$(_ev_b "$(_ev_kv $N TELEGRAM_NOTIFY_ENABLE 0)")" "$_ev_tg" \
        "$(_ev_b "$(_ev_kv $N NOTIFY_ATTACH_SNAPSHOT 1)")" "$(sanitize_int_range "$(_ev_kv $N NOTIFY_COOLDOWN_SECONDS 15)" 0 3600 15)" \
        "$(json_escape "$(_ev_kv $N NOTIFY_EVENTS 'motion sound tamper')")"
      printf '"tamper":{"enable":%s,"hold":%s,"drop_pct":%s,"luma_min":%s,"active":%s},' \
        "$(_ev_b "$(_ev_kv $T ENABLE 0)")" "$(sanitize_int_range "$(_ev_kv $T TAMPER_HOLD_SEC 6)" 2 120 6)" \
        "$(sanitize_int_range "$(_ev_kv $T TAMPER_JPEG_DROP_PCT 50)" 10 90 50)" "$(sanitize_int_range "$(_ev_kv $T TAMPER_LUMA_MIN 15)" 0 100 15)" "$_ev_ta"
      printf '"sound":{"enable":%s,"vox_mode":%s,"vox_hold":%s,"alarm_detect":%s,"alarm_hold":%s,"min_loud":%s}}\n' \
        "$(_ev_b "$(_ev_kv $S ENABLE 0)")" "$(_ev_b "$(_ev_kv $S VOX_MODE 0)")" "$(sanitize_int_range "$(_ev_kv $S VOX_HOLD_SECONDS 5)" 1 600 5)" \
        "$(_ev_b "$(_ev_kv $S ALARM_DETECT 0)")" "$(sanitize_int_range "$(_ev_kv $S ALARM_HOLD_SECONDS 15)" 5 120 15)" \
        "$(sanitize_int_range "$(_ev_kv $S MIN_LOUD_SECONDS 1)" 1 10 1)"
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
