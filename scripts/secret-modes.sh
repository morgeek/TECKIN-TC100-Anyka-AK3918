#!/bin/sh
# Secret files of the settings folder (/mnt/config, or /mnt/sd/config): mode 600, owner only [secmode]; and the service
# user of the privilege drop [up-privdrop].
# Sourced, never run: v3/autorun-linux66.sh (every boot), v3/linux66-sd/cfg-persist (after a restore),
# www/cgi-bin/config_exchange.cgi (after a settings import), scripts/common_functions.sh (all_password, privdrop_opt).
# A restore or an old in-place write keeps the mode of the file it came from (644, or 755 under umask 022); most readers
# run as root, so this is defence in depth.
# Only chmod / chgrp: no file is written and no mtime changes, and a file already right is not touched at all, so a boot
# with the modes right changes nothing that cfg-persist could see (it compares content and mtimes, not modes).
# A missing file is skipped; a chmod that fails (a FAT card has no modes) is ignored.
# The list: every file of config/ that holds a password, a token or a Wi-Fi key. Add a name here, nowhere else.
SECRET_FILES="user.pwd rtspserver.conf mqtt.conf wpa_supplicant.conf telegram.conf notify.conf"

# The service user (PRIVDROP=1, config/boot.conf.dist): tc100svc, uid and gid fixed (v3/buildroot/board/tc100/users.table has
# the same numbers; the daemons are started with the numbers, so a base image without the user still works, only without
# the name in ps). Daemons that give up root (tc100-onvifd, tc100-whep, tc100-mdnsd, tc100-logfwd) keep only this group.
TC100_SVC_UID=1001
TC100_SVC_GID=1001
# What the dropped daemons must read again after the drop: tc100-onvifd (every 2 s) and tc100-whep (every request) read the
# camera password and the RTSP settings. They are mode 640 with the service group while PRIVDROP is on, 600 root otherwise.
SERVICE_SECRETS="user.pwd rtspserver.conf"

# privdrop_enabled [CONFDIR]: PRIVDROP of CONFDIR/boot.conf (the one source of the switch); on unless 0 / no / off / false
privdrop_enabled() {
  _pd_v=$(sed -n 's/^PRIVDROP="\{0,1\}\([^" ]*\)"\{0,1\}[[:space:]]*$/\1/p' "${1:-/mnt/config}/boot.conf" 2>/dev/null | tail -n 1)
  case "$_pd_v" in 0|no|off|false) return 1 ;; esac
  return 0
}

# privdrop_opt: "-D uid:gid" for a daemon that supports it, nothing when PRIVDROP=0. Always succeeds. It first sets the
# modes of /mnt/config (TC100_CONFIG_DIR moves it, for the tests), so that a service restarted after PRIVDROP was changed (no reboot) finds its files readable.
privdrop_opt() {
  secret_modes_fix "${TC100_CONFIG_DIR:-/mnt/config}"
  privdrop_enabled "${TC100_CONFIG_DIR:-/mnt/config}" && printf '%s' "-D $TC100_SVC_UID:$TC100_SVC_GID"
  return 0
}

secret_modes_fix() {
  [ -n "$1" ] || return 0
  _sm_share=0
  privdrop_enabled "$1" && _sm_share=1
  for _sm_f in $SECRET_FILES; do
    _sm_p="$1/$_sm_f"
    [ -f "$_sm_p" ] || continue
    _sm_want=600; _sm_grp=
    if [ "$_sm_share" = 1 ]; then
      case " $SERVICE_SECRETS " in *" $_sm_f "*) _sm_want=640; _sm_grp=$TC100_SVC_GID ;; esac
    fi
    _sm_m=$(stat -c '%a %g' "$_sm_p" 2>/dev/null) || continue
    if [ -n "$_sm_grp" ]; then
      [ "$_sm_m" = "640 $_sm_grp" ] && continue
      chgrp "$_sm_grp" "$_sm_p" 2>/dev/null
    else
      [ "${_sm_m%% *}" = 600 ] && continue
    fi
    chmod "$_sm_want" "$_sm_p" 2>/dev/null
  done
  return 0
}
