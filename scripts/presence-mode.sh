#!/bin/sh
# Presence profiles are explicit presets over existing settings. The profile
# file holds the preset values and selected mode; live privacy, motion and
# recording values stay in their existing configuration files.

if [ -z "$PRESENCE_CONFIG" ]; then PRESENCE_CONFIG=/mnt/config/presence.conf; fi
if [ -z "$PRESENCE_DEFAULTS" ]; then PRESENCE_DEFAULTS=/mnt/config/presence.conf.dist; fi
if [ -z "$PRESENCE_LOCK" ]; then PRESENCE_LOCK=/tmp/tc100-presence.lock; fi

[ -r /mnt/scripts/common_functions.sh ] && . /mnt/scripts/common_functions.sh

presence_read_file()
{
  [ -r "$1" ] || return 0
  awk -F= -v key="$2" '$1 == key { value = substr($0, index($0, "=") + 1) } END { print value }' "$1" 2>/dev/null
}

presence_read()
{
  _pr_value="$(presence_read_file "$PRESENCE_CONFIG" "$1")"
  if [ -z "$_pr_value" ]; then _pr_value="$(presence_read_file "$PRESENCE_DEFAULTS" "$1")"; fi
  [ -n "$_pr_value" ] || _pr_value="$2"
  printf '%s' "$_pr_value"
}

presence_bool()
{
  case "$1" in 1|true|yes|on|enabled) printf 1 ;; *) printf 0 ;; esac
}

presence_profile_prefix()
{
  case "$1" in
    present) printf PRESENT ;;
    away) printf AWAY ;;
    night) printf NIGHT ;;
    *) return 1 ;;
  esac
}

presence_profile_value()
{
  _pr_prefix="$(presence_profile_prefix "$1")" || return 1
  _pr_suffix="$(printf '%s' "$2" | tr '[:lower:]' '[:upper:]')"
  case "$_pr_suffix" in CONFIGURED|PRIVACY|MOTION|RECORDING|NOTIFICATIONS) ;; *) return 1 ;; esac
  presence_read "PRESENCE_${_pr_prefix}_${_pr_suffix}" 0
}

presence_valid_mode()
{
  case "$1" in present|away|night|custom) return 0 ;; *) return 1 ;; esac
}

presence_unlock()
{
  rmdir "$PRESENCE_LOCK" 2>/dev/null || true
  trap - 0 HUP INT TERM
}

presence_lock()
{
  mkdir "$PRESENCE_LOCK" 2>/dev/null || return 1
  trap 'rmdir "$PRESENCE_LOCK" 2>/dev/null || true' 0 HUP INT TERM
}

presence_current()
{
  _pr_mode="$(presence_read PRESENCE_MODE custom)"
  presence_valid_mode "$_pr_mode" || _pr_mode=custom
  case "$_pr_mode" in custom) printf '%s\n' custom; return 0 ;; esac
  [ -d "$PRESENCE_LOCK" ] && { printf '%s\n' "$_pr_mode"; return 0; }

  if [ "$(presence_profile_value "$_pr_mode" configured)" != 1 ]; then
    _pr_mismatch=1
  else
    _pr_mismatch=0
    for _pr_action in privacy motion recording; do
      _pr_want="$(presence_profile_value "$_pr_mode" "$_pr_action")"
      case "$_pr_action" in
        privacy) _pr_got="$(presence_bool "$(presence_read_file /mnt/config/boot.conf PRIVACY_SCREEN)")" ;;
        motion) _pr_got="$(presence_bool "$(presence_read_file /mnt/config/rtspserver.conf mdenabled)")" ;;
        recording) _pr_got="$(presence_bool "$(presence_read_file /mnt/config/boot.conf REC_LOCAL)")" ;;
      esac
      [ "$_pr_want" = "$_pr_got" ] || _pr_mismatch=1
    done
  fi
  if [ "$_pr_mismatch" = 1 ]; then
    if command -v rewrite_config >/dev/null 2>&1 && [ -f "$PRESENCE_CONFIG" ]; then
      rewrite_config "$PRESENCE_CONFIG" PRESENCE_MODE custom >/dev/null 2>&1 || true
    fi
    _pr_mode=custom
  fi
  printf '%s\n' "$_pr_mode"
}

presence_mark_custom()
{
  [ -d "$PRESENCE_LOCK" ] && return 0
  _pr_mode="$(presence_read PRESENCE_MODE custom)"
  case "$_pr_mode" in
    present|away|night)
      if [ -f "$PRESENCE_CONFIG" ] && command -v rewrite_config >/dev/null 2>&1; then
        rewrite_config "$PRESENCE_CONFIG" PRESENCE_MODE custom >/dev/null 2>&1 || return 1
      fi ;;
  esac
  return 0
}

presence_info()
{
  _pr_mode="$(presence_current)"
  printf '{"ok":true,"mode":"%s","profiles":{' "$_pr_mode"
  _pr_sep=""
  for _pr_profile in present away night; do
    printf '%s"%s":{"configured":%s,"privacy":%s,"motion":%s,"recording":%s,"notifications":%s}' \
      "$_pr_sep" "$_pr_profile" \
      "$(presence_bool "$(presence_profile_value "$_pr_profile" configured)")" \
      "$(presence_bool "$(presence_profile_value "$_pr_profile" privacy)")" \
      "$(presence_bool "$(presence_profile_value "$_pr_profile" motion)")" \
      "$(presence_bool "$(presence_profile_value "$_pr_profile" recording)")" \
      "$(presence_bool "$(presence_profile_value "$_pr_profile" notifications)")"
    _pr_sep=","
  done
  printf '}}\n'
}

presence_fail()
{
  printf '{"ok":false,"error":"%s"}\n' "$1"
  return 1
}

presence_configure()
{
  _pr_profile="$1"; _pr_privacy="$2"; _pr_motion="$3"; _pr_recording="$4"; _pr_notifications="$5"
  _pr_prefix="$(presence_profile_prefix "$_pr_profile")" || { presence_fail invalid_profile; return 1; }
  for _pr_bit in "$_pr_privacy" "$_pr_motion" "$_pr_recording" "$_pr_notifications"; do
    case "$_pr_bit" in 0|1) ;; *) presence_fail invalid_value; return 1 ;; esac
  done
  _pr_was_mode="$(presence_read PRESENCE_MODE custom)"
  _pr_profile_changed=0
  [ "$(presence_profile_value "$_pr_profile" configured)" = 1 ] || _pr_profile_changed=1
  [ "$(presence_profile_value "$_pr_profile" privacy)" = "$_pr_privacy" ] || _pr_profile_changed=1
  [ "$(presence_profile_value "$_pr_profile" motion)" = "$_pr_motion" ] || _pr_profile_changed=1
  [ "$(presence_profile_value "$_pr_profile" recording)" = "$_pr_recording" ] || _pr_profile_changed=1
  [ "$(presence_profile_value "$_pr_profile" notifications)" = "$_pr_notifications" ] || _pr_profile_changed=1
  install_config "$PRESENCE_CONFIG" || { presence_fail config_unavailable; return 1; }
  presence_lock || { presence_fail busy; return 1; }
  _pr_tmp="${PRESENCE_CONFIG}.tmp.$$"
  if ! cp "$PRESENCE_CONFIG" "$_pr_tmp"; then presence_unlock; presence_fail save_failed; return 1; fi
  rewrite_config "$_pr_tmp" "PRESENCE_${_pr_prefix}_PRIVACY" "$_pr_privacy" &&
  rewrite_config "$_pr_tmp" "PRESENCE_${_pr_prefix}_MOTION" "$_pr_motion" &&
  rewrite_config "$_pr_tmp" "PRESENCE_${_pr_prefix}_RECORDING" "$_pr_recording" &&
  rewrite_config "$_pr_tmp" "PRESENCE_${_pr_prefix}_NOTIFICATIONS" "$_pr_notifications" &&
  rewrite_config "$_pr_tmp" "PRESENCE_${_pr_prefix}_CONFIGURED" 1 || {
    rm -f "$_pr_tmp"; presence_unlock; presence_fail save_failed; return 1;
  }
  mv -f "$_pr_tmp" "$PRESENCE_CONFIG" || {
    rm -f "$_pr_tmp"; presence_unlock; presence_fail save_failed; return 1;
  }
  sync
  presence_unlock
  # Editing the selected preset does not silently apply it. Reconcile the label
  # to custom if its new values differ from what is currently running.
  if [ "$_pr_was_mode" = "$_pr_profile" ] && [ "$_pr_profile_changed" = 1 ]; then
    presence_mark_custom
  else
    presence_current >/dev/null
  fi
  printf '{"ok":true,"profile":"%s","saved":true}\n' "$_pr_profile"
}

presence_apply()
{
  _pr_mode="$1"
  presence_valid_mode "$_pr_mode" || { presence_fail invalid_mode; return 1; }
  install_config "$PRESENCE_CONFIG" || { presence_fail config_unavailable; return 1; }
  presence_lock || { presence_fail busy; return 1; }

  if [ "$_pr_mode" = custom ]; then
    rewrite_config "$PRESENCE_CONFIG" PRESENCE_MODE custom || {
      presence_unlock; presence_fail save_failed; return 1;
    }
    presence_unlock
    printf '{"ok":true,"mode":"custom"}\n'
    return 0
  fi

  [ "$(presence_profile_value "$_pr_mode" configured)" = 1 ] || {
    presence_unlock; presence_fail profile_not_configured; return 1;
  }
  _pr_privacy="$(presence_profile_value "$_pr_mode" privacy)"
  _pr_motion="$(presence_profile_value "$_pr_mode" motion)"
  _pr_recording="$(presence_profile_value "$_pr_mode" recording)"

  if [ "$_pr_privacy" = 1 ]; then
    /mnt/controlscripts/privacy start || { presence_unlock; presence_fail privacy_failed; return 1; }
  else
    /mnt/controlscripts/privacy stop || { presence_unlock; presence_fail privacy_failed; return 1; }
  fi
  if [ "$_pr_motion" = 1 ]; then
    /mnt/controlscripts/motion-detection start || { presence_unlock; presence_fail motion_failed; return 1; }
  else
    /mnt/controlscripts/motion-detection stop || { presence_unlock; presence_fail motion_failed; return 1; }
  fi
  if [ "$_pr_recording" = 1 ]; then
    /mnt/controlscripts/recording start || { presence_unlock; presence_fail recording_failed; return 1; }
  else
    /mnt/controlscripts/recording stop || { presence_unlock; presence_fail recording_failed; return 1; }
  fi
  rewrite_config "$PRESENCE_CONFIG" PRESENCE_MODE "$_pr_mode" || {
    presence_unlock; presence_fail save_failed; return 1;
  }
  presence_unlock
  printf '{"ok":true,"mode":"%s"}\n' "$_pr_mode"
}

presence_notifications_allowed()
{
  _pr_mode="$(presence_current)"
  case "$_pr_mode" in
    present|away|night) presence_profile_value "$_pr_mode" notifications | presence_bool ;;
    *) printf 1 ;;
  esac
}

case "$1" in
  info) presence_info ;;
  current) presence_current ;;
  manual) presence_mark_custom ;;
  notifications) presence_notifications_allowed ;;
  configure) shift; presence_configure "$@" ;;
  apply) shift; presence_apply "$@" ;;
  *) presence_fail invalid_command ;;
esac
