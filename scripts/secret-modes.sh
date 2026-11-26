#!/bin/sh
# Secret files of the settings folder (/mnt/config, or /mnt/sd/config): mode 600, owner only [secmode].
# Sourced, never run: v3/autorun-linux66.sh (every boot), v3/linux66-sd/cfg-persist (after a restore) and
# www/cgi-bin/config_exchange.cgi (after a settings import). A restore or an old in-place write keeps the mode of the file
# it came from (644, or 755 under umask 022); the readers all run as root, so this is defence in depth.
# Only chmod: no file is written and no mtime changes, and a file already at 600 is not touched at all, so a boot with the
# modes right changes nothing that cfg-persist could see (it compares content and mtimes, not modes).
# A missing file is skipped; a chmod that fails (a FAT card has no modes) is ignored.
# The list: every file of config/ that holds a password, a token or a Wi-Fi key. Add a name here, nowhere else.
SECRET_FILES="user.pwd rtspserver.conf mqtt.conf wpa_supplicant.conf telegram.conf notify.conf"

secret_modes_fix() {
  [ -n "$1" ] || return 0
  for _sm_f in $SECRET_FILES; do
    _sm_p="$1/$_sm_f"
    [ -f "$_sm_p" ] || continue
    _sm_m=$(stat -c %a "$_sm_p" 2>/dev/null) || continue
    [ "$_sm_m" = 600 ] && continue
    chmod 600 "$_sm_p" 2>/dev/null
  done
  return 0
}
