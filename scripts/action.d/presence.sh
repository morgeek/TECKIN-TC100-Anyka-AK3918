# shellcheck shell=sh
# action.cgi commands: owner-configured presence profiles.
# Sourced only after action.cgi has applied its rate limit, audit and CSRF checks.

case "$F_cmd" in
    presence_info)
      sh /mnt/scripts/presence-mode.sh info
      ;;
    presence_apply)
      sh /mnt/scripts/presence-mode.sh apply "$F_mode"
      ;;
    presence_profiles_save)
      sh /mnt/scripts/presence-mode.sh configure \
        "$F_profile" "$F_privacy" "$F_motion" "$F_recording" "$F_notifications"
      ;;
esac
