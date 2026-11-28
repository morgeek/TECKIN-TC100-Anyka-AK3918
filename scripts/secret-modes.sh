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
SECRET_FILES="user.pwd rtspserver.conf mqtt.conf wpa_supplicant.conf telegram.conf notify.conf https-key.pem"

# The service users (PRIVDROP=1, config/boot.conf.dist), uid and gid fixed (v3/buildroot/board/tc100/users.table has the
# same numbers; the daemons are started with the numbers, so a base image without the users still works, only without the
# names in ps). Each dropped daemon keeps only its own group:
#   tc100svc 1001 (svc): tc100-onvifd and tc100-whep, which read the camera password and the RTSP settings;
#   tc100net 1002 (net): tc100-mdnsd and tc100-logfwd, which read no secret and so get no group on any secret file.
TC100_SVC_UID=1001
TC100_SVC_GID=1001
TC100_NET_UID=1002
TC100_NET_GID=1002
# What the "svc" daemons must read again after the drop: tc100-onvifd (every 2 s) and tc100-whep (every request) read the
# camera password and the RTSP settings. They are mode 640 with the svc group while PRIVDROP is on, 600 root otherwise.
SERVICE_SECRETS="user.pwd rtspserver.conf"

# privdrop_enabled [CONFDIR]: PRIVDROP of CONFDIR/boot.conf (the one source of the switch); on unless 0 / no / off / false.
# Read as the other boot.conf switches are: quotes, a trailing comment and blanks are accepted (PRIVDROP=0 # why, PRIVDROP='0').
privdrop_enabled() {
  _pd_v=$(sed -n "s/^PRIVDROP=[\"']\{0,1\}\([^\"' 	#]*\).*\$/\1/p" "${1:-/mnt/config}/boot.conf" 2>/dev/null | tail -n 1)
  case "$_pd_v" in 0|no|off|false) return 1 ;; esac
  return 0
}

# privdrop_harden: what root shares with the dropped daemons, made safe before any of them runs [audit 3.2]. Called by
# autorun (step 0c, every boot with PRIVDROP on) and by privdrop_opt (a daemon started after PRIVDROP was set to 1 without
# a reboot). Root alone runs scripts here; the dropped daemons only read in /tmp (rec_control, wifi-signal.avg) and
# never create a file there. So /tmp and /dev/shm become root-only (0755): a daemon taken over cannot pre-create
# /tmp/upd66 or /tmp/update66 (and swap what the web update runs or writes), nor plant /tmp/update66.failed, .staged,
# .sig or cfg-persist.lock. The kernel's link protections are turned on as well (defence in depth). Always succeeds;
# PRIVDROP=0 does not undo it (root only needs nothing more).
privdrop_harden() {
  # the real folders only on the camera (it always has /mnt/config): a build host running the tests is never touched
  [ -n "${TC100_PRIVDROP_FS:-}${TC100_PRIVDROP_DIRS:-}" ] || [ -d /mnt/config ] || return 0
  _ph_fs=${TC100_PRIVDROP_FS:-/proc/sys/fs}
  echo 1 > "$_ph_fs/protected_symlinks" 2>/dev/null
  echo 1 > "$_ph_fs/protected_hardlinks" 2>/dev/null
  echo 1 > "$_ph_fs/protected_fifos" 2>/dev/null
  echo 2 > "$_ph_fs/protected_regular" 2>/dev/null
  for _ph_d in ${TC100_PRIVDROP_DIRS:-/tmp /dev/shm}; do
    [ -d "$_ph_d" ] && [ ! -L "$_ph_d" ] && chown 0:0 "$_ph_d" 2>/dev/null && chmod 0755 "$_ph_d" 2>/dev/null
  done
  return 0
}

# privdrop_opt [svc|net]: "-D uid:gid" of the service user the daemon runs as (default svc), nothing when PRIVDROP=0.
# Always succeeds. It first sets the modes of /mnt/config (TC100_CONFIG_DIR moves it, for the tests), so that a service
# restarted after PRIVDROP was changed (no reboot) finds its files readable.
privdrop_opt() {
  secret_modes_fix "${TC100_CONFIG_DIR:-/mnt/config}"
  privdrop_enabled "${TC100_CONFIG_DIR:-/mnt/config}" || return 0
  # the camera itself only: a test (TC100_CONFIG_DIR set) must never make the /tmp of the build host root-only
  [ -n "${TC100_CONFIG_DIR:-}" ] || privdrop_harden
  case "$1" in
    net) printf '%s' "-D $TC100_NET_UID:$TC100_NET_GID" ;;
    *) printf '%s' "-D $TC100_SVC_UID:$TC100_SVC_GID" ;;
  esac
  return 0
}

# secret_file_attrs TEMP FINAL: owner, group and mode of TEMP, a file about to be renamed over FINAL: call it BEFORE the
# rename, so the file never exists with the wrong attributes (a reader polling in between would see an unreadable
# password file). A secret file of the list gets the mode of its policy (secret_modes_fix); any other file keeps what the
# file it replaces has. Failures are ignored (a FAT card has no owners).
secret_file_attrs() {
  [ -f "$1" ] || return 0
  _sa_name="${2##*/}"; _sa_dir="${2%/*}"
  case " $SECRET_FILES " in
    *" $_sa_name "*)
      _sa_want=600; _sa_grp=
      if privdrop_enabled "$_sa_dir"; then
        case " $SERVICE_SECRETS " in *" $_sa_name "*) _sa_want=640; _sa_grp=$TC100_SVC_GID ;; esac
      fi
      [ -z "$_sa_grp" ] || chown "0:$_sa_grp" "$1" 2>/dev/null
      chmod "$_sa_want" "$1" 2>/dev/null ;;
    *)
      if [ -f "$2" ]; then
        _sa_o=$(stat -c '%u:%g %a' "$2" 2>/dev/null) || return 0
        chown "${_sa_o% *}" "$1" 2>/dev/null
        chmod "${_sa_o#* }" "$1" 2>/dev/null
      fi ;;
  esac
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
