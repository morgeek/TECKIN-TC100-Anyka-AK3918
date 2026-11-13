#!/bin/sh
# service-switch.sh — ONE switch per service (sourced, no fork): the key of a settings file that turns the service on.
# The boot (v3/autorun-linux66.sh), the Services page "Boot" toggle (www/cgi-bin/scripts.cgi), the Settings forms and
# the status lines all read or write that key; config/autostart/<service> is not used for these services (an old
# file there is ignored). Services that are not listed here keep the autostart file as their switch.
#   svc_switch NAME        -> 0 and SW_FILE SW_KEY SW_DEF set when NAME has a key; 1 otherwise
#   svc_on NAME            -> 0 when the key says on (missing key: SW_DEF)
#   svc_set NAME 0|1       -> writes the key (appended when missing)
# SW_CONF_DIR changes /mnt/config (tests).

svc_switch()
{
  _sw_d=${SW_CONF_DIR:-/mnt/config}
  case "$1" in
    sound-detection)  SW_FILE=$_sw_d/sound_detection.conf; SW_KEY=ENABLE; SW_DEF=0 ;;
    syslog-forward)   SW_FILE=$_sw_d/boot.conf; SW_KEY=SYSLOG_ENABLE; SW_DEF=0 ;;
    recording)        SW_FILE=$_sw_d/boot.conf; SW_KEY=REC_LOCAL; SW_DEF=0 ;;
    memory-guard)     SW_FILE=$_sw_d/boot.conf; SW_KEY=MEM_GUARD_ENABLE; SW_DEF=0 ;;
    wifi-rescue)      SW_FILE=$_sw_d/boot.conf; SW_KEY=WIFI_RESCUE; SW_DEF=1 ;;
    whep)             SW_FILE=$_sw_d/boot.conf; SW_KEY=WHEP; SW_DEF=1 ;;
    mqtt-bridge)      SW_FILE=$_sw_d/mqtt.conf; SW_KEY=MQTT_ENABLE; SW_DEF=0 ;;
    telegram-bot)     SW_FILE=$_sw_d/telegram.conf; SW_KEY=TELEGRAM_ENABLE; SW_DEF=0 ;;
    motion-detection) SW_FILE=$_sw_d/rtspserver.conf; SW_KEY=mdenabled; SW_DEF=0 ;;
    *) return 1 ;;
  esac
  return 0
}

# value of KEY in FILE (last line wins, one pair of quotes removed), or $3
# Optional $4=var stores result in _sw_v without printing.
svc_kv()
{
  _sw_v=
  if [ -r "$1" ]; then
    while IFS= read -r _sw_l || [ -n "$_sw_l" ]; do
      case "$_sw_l" in "$2="*) _sw_v=${_sw_l#*=} ;; esac
    done < "$1"
  fi
  _sw_v=${_sw_v#[\"\']}; _sw_v=${_sw_v%[\"\']}
  [ -n "$_sw_v" ] || _sw_v=$3
  [ "${4:-}" = "var" ] || printf '%s' "$_sw_v"
}

svc_on()
{
  svc_switch "$1" || return 1
  svc_kv "$SW_FILE" "$SW_KEY" "$SW_DEF" var
  case "$_sw_v" in 1|true|yes|on|enabled) return 0 ;; esac
  return 1
}

svc_set()
{
  svc_switch "$1" || return 1
  case "$2" in 1) _sw_n=1 ;; *) _sw_n=0 ;; esac
  [ -f "$SW_FILE" ] || { [ -f "$SW_FILE.dist" ] && cp "$SW_FILE.dist" "$SW_FILE"; } || : > "$SW_FILE"
  if grep -q "^$SW_KEY=" "$SW_FILE" 2>/dev/null; then
    sed "s|^$SW_KEY=.*|$SW_KEY=$_sw_n|" "$SW_FILE" > "$SW_FILE.tmp.$$" && mv -f "$SW_FILE.tmp.$$" "$SW_FILE"
  else
    printf '%s=%s\n' "$SW_KEY" "$_sw_n" >> "$SW_FILE"
  fi
}
