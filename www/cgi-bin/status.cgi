#!/bin/sh

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

. /mnt/scripts/common_functions.sh
install_config /mnt/config/recording.conf
install_config /mnt/config/boot.conf
install_config /mnt/config/service_trim.conf
install_config /mnt/config/mqtt.conf

# shellcheck disable=SC1090
if [ -f /mnt/config/boot.conf ]; then
  . /mnt/config/boot.conf
fi
# shellcheck disable=SC1090
if [ -f /mnt/config/service_trim.conf ]; then
  . /mnt/config/service_trim.conf
fi
# shellcheck disable=SC1090
if [ -f /mnt/config/mqtt.conf ]; then
  . /mnt/config/mqtt.conf
fi
SERVICE_TRIM="${SERVICE_TRIM:-0}"
LOW_CPU_PROFILE="${LOW_CPU_PROFILE:-0}"
RTSP_SUBSTREAM="${RTSP_SUBSTREAM:-1}"
RTSP_AUDIO="${RTSP_AUDIO:-1}"
ONVIF_STREAM_POLICY="${ONVIF_STREAM_POLICY:-main-primary}"
WEB_MODE="${WEB_MODE:-full}"
ULTRALITE_HTTP_PORT="${ULTRALITE_HTTP_PORT:-80}"
LIGHTWEIGHT_MODE="${LIGHTWEIGHT_MODE:-0}"
UI_ULTRALITE_MODE="${UI_ULTRALITE_MODE:-0}"
SECURITY_HARDENING_MODE="${SECURITY_HARDENING_MODE:-0}"
ENABLE_NTP="${ENABLE_NTP:-1}"
NTP_ONE_SHOT="${NTP_ONE_SHOT:-0}"
REBOOT_SCHEDULE_ENABLE="${REBOOT_SCHEDULE_ENABLE:-0}"
REBOOT_SCHEDULE_MINUTE="${REBOOT_SCHEDULE_MINUTE:-0}"
REBOOT_SCHEDULE_HOUR="${REBOOT_SCHEDULE_HOUR:-4}"
REBOOT_SCHEDULE_WEEKDAY="${REBOOT_SCHEDULE_WEEKDAY:-*}"
MEM_GUARD_ENABLE="${MEM_GUARD_ENABLE:-0}"
MEM_GUARD_INTERVAL_SECONDS="${MEM_GUARD_INTERVAL_SECONDS:-20}"
MEM_GUARD_WARN_KB="${MEM_GUARD_WARN_KB:-8192}"
MEM_GUARD_CRITICAL_KB="${MEM_GUARD_CRITICAL_KB:-4096}"
MEM_GUARD_RECOVERY_MARGIN_KB="${MEM_GUARD_RECOVERY_MARGIN_KB:-1536}"
MEM_GUARD_WARN_HITS="${MEM_GUARD_WARN_HITS:-2}"
MEM_GUARD_CRITICAL_HITS="${MEM_GUARD_CRITICAL_HITS:-1}"
MEM_GUARD_COOLDOWN_SECONDS="${MEM_GUARD_COOLDOWN_SECONDS:-120}"
MEM_GUARD_EMERGENCY_KB="${MEM_GUARD_EMERGENCY_KB:-2048}"
MEM_GUARD_DROP_CACHES="${MEM_GUARD_DROP_CACHES:-1}"
RTSP_HEALTHCHECK_TIMEOUT_SECONDS="${RTSP_HEALTHCHECK_TIMEOUT_SECONDS:-4}"
ONVIF_HEALTHCHECK_TIMEOUT_SECONDS="${ONVIF_HEALTHCHECK_TIMEOUT_SECONDS:-4}"
MQTT_ENABLE="${MQTT_ENABLE:-0}"
MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
MQTT_PORT="${MQTT_PORT:-1883}"
MQTT_USER="${MQTT_USER:-}"
MQTT_PASSWORD="${MQTT_PASSWORD:-}"
MQTT_CLIENT_ID="${MQTT_CLIENT_ID:-tc100-camera}"
MQTT_TOPIC_ROOT="${MQTT_TOPIC_ROOT:-tc100/camera}"
MQTT_TOPIC_COMMAND="${MQTT_TOPIC_COMMAND:-}"
MQTT_QOS="${MQTT_QOS:-0}"
MQTT_HEALTH_INTERVAL_SECONDS="${MQTT_HEALTH_INTERVAL_SECONDS:-120}"
MQTT_COMMAND_WAIT_SECONDS="${MQTT_COMMAND_WAIT_SECONDS:-12}"
MQTT_COMMAND_REPEAT_WINDOW_SECONDS="${MQTT_COMMAND_REPEAT_WINDOW_SECONDS:-20}"
MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS="${MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS:-2}"
MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS="${MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS:-20}"
MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER="${MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER:-2}"
MQTT_HA_DISCOVERY_ENABLE="${MQTT_HA_DISCOVERY_ENABLE:-1}"
MQTT_HA_DISCOVERY_PREFIX="${MQTT_HA_DISCOVERY_PREFIX:-homeassistant}"
POWER_ESTIMATE_ENABLE="${POWER_ESTIMATE_ENABLE:-0}"
POWER_ESTIMATE_BASE_MW="${POWER_ESTIMATE_BASE_MW:-1700}"
POWER_ESTIMATE_CPU_SCALE_MW="${POWER_ESTIMATE_CPU_SCALE_MW:-500}"
POWER_ESTIMATE_IR_LED_MW="${POWER_ESTIMATE_IR_LED_MW:-700}"
POWER_SENSOR_PATH="${POWER_SENSOR_PATH:-auto}"
SETUP_WIZARD_DONE="${SETUP_WIZARD_DONE:-0}"

case "$WEB_MODE" in
  full|http|ultra-lite|ultralite|off) ;;
  *) WEB_MODE="full" ;;
esac
if [ "$WEB_MODE" = "ultralite" ]; then
  WEB_MODE="ultra-lite"
fi
case "$ULTRALITE_HTTP_PORT" in
  ''|*[!0-9]*) ULTRALITE_HTTP_PORT=80 ;;
esac
if [ "$ULTRALITE_HTTP_PORT" -lt 1 ] || [ "$ULTRALITE_HTTP_PORT" -gt 65535 ]; then
  ULTRALITE_HTTP_PORT=80
fi
for flag_name in LIGHTWEIGHT_MODE UI_ULTRALITE_MODE SECURITY_HARDENING_MODE ENABLE_NTP NTP_ONE_SHOT REBOOT_SCHEDULE_ENABLE MEM_GUARD_ENABLE MEM_GUARD_DROP_CACHES MQTT_ENABLE MQTT_HA_DISCOVERY_ENABLE POWER_ESTIMATE_ENABLE SETUP_WIZARD_DONE
do
  eval "flag_value=\${$flag_name}"
  case "$flag_value" in
    1|true|on|yes|enabled) eval "$flag_name=1" ;;
    *) eval "$flag_name=0" ;;
  esac
done
case "$MEM_GUARD_INTERVAL_SECONDS" in
  ''|*[!0-9]*) MEM_GUARD_INTERVAL_SECONDS=20 ;;
esac
if [ "$MEM_GUARD_INTERVAL_SECONDS" -lt 5 ] || [ "$MEM_GUARD_INTERVAL_SECONDS" -gt 600 ]; then
  MEM_GUARD_INTERVAL_SECONDS=20
fi
case "$MEM_GUARD_WARN_KB" in
  ''|*[!0-9]*) MEM_GUARD_WARN_KB=8192 ;;
esac
if [ "$MEM_GUARD_WARN_KB" -lt 2048 ] || [ "$MEM_GUARD_WARN_KB" -gt 65535 ]; then
  MEM_GUARD_WARN_KB=8192
fi
case "$MEM_GUARD_CRITICAL_KB" in
  ''|*[!0-9]*) MEM_GUARD_CRITICAL_KB=4096 ;;
esac
if [ "$MEM_GUARD_CRITICAL_KB" -lt 1024 ] || [ "$MEM_GUARD_CRITICAL_KB" -gt 65535 ]; then
  MEM_GUARD_CRITICAL_KB=4096
fi
if [ "$MEM_GUARD_CRITICAL_KB" -ge "$MEM_GUARD_WARN_KB" ]; then
  MEM_GUARD_CRITICAL_KB=$((MEM_GUARD_WARN_KB / 2))
  if [ "$MEM_GUARD_CRITICAL_KB" -lt 1024 ]; then
    MEM_GUARD_CRITICAL_KB=1024
  fi
fi
case "$MEM_GUARD_RECOVERY_MARGIN_KB" in
  ''|*[!0-9]*) MEM_GUARD_RECOVERY_MARGIN_KB=1536 ;;
esac
if [ "$MEM_GUARD_RECOVERY_MARGIN_KB" -lt 256 ] || [ "$MEM_GUARD_RECOVERY_MARGIN_KB" -gt 32768 ]; then
  MEM_GUARD_RECOVERY_MARGIN_KB=1536
fi
case "$MEM_GUARD_WARN_HITS" in
  ''|*[!0-9]*) MEM_GUARD_WARN_HITS=2 ;;
esac
if [ "$MEM_GUARD_WARN_HITS" -lt 1 ] || [ "$MEM_GUARD_WARN_HITS" -gt 10 ]; then
  MEM_GUARD_WARN_HITS=2
fi
case "$MEM_GUARD_CRITICAL_HITS" in
  ''|*[!0-9]*) MEM_GUARD_CRITICAL_HITS=1 ;;
esac
if [ "$MEM_GUARD_CRITICAL_HITS" -lt 1 ] || [ "$MEM_GUARD_CRITICAL_HITS" -gt 10 ]; then
  MEM_GUARD_CRITICAL_HITS=1
fi
case "$MEM_GUARD_COOLDOWN_SECONDS" in
  ''|*[!0-9]*) MEM_GUARD_COOLDOWN_SECONDS=120 ;;
esac
if [ "$MEM_GUARD_COOLDOWN_SECONDS" -lt 10 ] || [ "$MEM_GUARD_COOLDOWN_SECONDS" -gt 3600 ]; then
  MEM_GUARD_COOLDOWN_SECONDS=120
fi
case "$MEM_GUARD_EMERGENCY_KB" in
  ''|*[!0-9]*) MEM_GUARD_EMERGENCY_KB=2048 ;;
esac
if [ "$MEM_GUARD_EMERGENCY_KB" -lt 512 ] || [ "$MEM_GUARD_EMERGENCY_KB" -gt 32768 ]; then
  MEM_GUARD_EMERGENCY_KB=2048
fi
if [ "$MEM_GUARD_EMERGENCY_KB" -ge "$MEM_GUARD_CRITICAL_KB" ]; then
  MEM_GUARD_EMERGENCY_KB=$((MEM_GUARD_CRITICAL_KB / 2))
  if [ "$MEM_GUARD_EMERGENCY_KB" -lt 512 ]; then
    MEM_GUARD_EMERGENCY_KB=512
  fi
fi
case "$RTSP_HEALTHCHECK_TIMEOUT_SECONDS" in
  ''|*[!0-9]*) RTSP_HEALTHCHECK_TIMEOUT_SECONDS=4 ;;
esac
if [ "$RTSP_HEALTHCHECK_TIMEOUT_SECONDS" -lt 2 ] || [ "$RTSP_HEALTHCHECK_TIMEOUT_SECONDS" -gt 30 ]; then
  RTSP_HEALTHCHECK_TIMEOUT_SECONDS=4
fi
case "$ONVIF_HEALTHCHECK_TIMEOUT_SECONDS" in
  ''|*[!0-9]*) ONVIF_HEALTHCHECK_TIMEOUT_SECONDS=4 ;;
esac
if [ "$ONVIF_HEALTHCHECK_TIMEOUT_SECONDS" -lt 2 ] || [ "$ONVIF_HEALTHCHECK_TIMEOUT_SECONDS" -gt 30 ]; then
  ONVIF_HEALTHCHECK_TIMEOUT_SECONDS=4
fi
case "$REBOOT_SCHEDULE_MINUTE" in
  ''|*[!0-9]*) REBOOT_SCHEDULE_MINUTE=0 ;;
esac
if [ "$REBOOT_SCHEDULE_MINUTE" -lt 0 ] || [ "$REBOOT_SCHEDULE_MINUTE" -gt 59 ]; then
  REBOOT_SCHEDULE_MINUTE=0
fi
case "$REBOOT_SCHEDULE_HOUR" in
  ''|*[!0-9]*) REBOOT_SCHEDULE_HOUR=4 ;;
esac
if [ "$REBOOT_SCHEDULE_HOUR" -lt 0 ] || [ "$REBOOT_SCHEDULE_HOUR" -gt 23 ]; then
  REBOOT_SCHEDULE_HOUR=4
fi
case "$REBOOT_SCHEDULE_WEEKDAY" in
  '*'|0|1|2|3|4|5|6|1-5|0,6) ;;
  *) REBOOT_SCHEDULE_WEEKDAY='*' ;;
esac
case "$MQTT_PORT" in
  ''|*[!0-9]*) MQTT_PORT=1883 ;;
esac
if [ "$MQTT_PORT" -lt 1 ] || [ "$MQTT_PORT" -gt 65535 ]; then
  MQTT_PORT=1883
fi
case "$MQTT_QOS" in
  ''|*[!0-9]*) MQTT_QOS=0 ;;
esac
if [ "$MQTT_QOS" -lt 0 ] || [ "$MQTT_QOS" -gt 2 ]; then
  MQTT_QOS=0
fi
case "$MQTT_HEALTH_INTERVAL_SECONDS" in
  ''|*[!0-9]*) MQTT_HEALTH_INTERVAL_SECONDS=120 ;;
esac
if [ "$MQTT_HEALTH_INTERVAL_SECONDS" -lt 10 ] || [ "$MQTT_HEALTH_INTERVAL_SECONDS" -gt 86400 ]; then
  MQTT_HEALTH_INTERVAL_SECONDS=120
fi
case "$MQTT_COMMAND_WAIT_SECONDS" in
  ''|*[!0-9]*) MQTT_COMMAND_WAIT_SECONDS=12 ;;
esac
if [ "$MQTT_COMMAND_WAIT_SECONDS" -lt 3 ] || [ "$MQTT_COMMAND_WAIT_SECONDS" -gt 120 ]; then
  MQTT_COMMAND_WAIT_SECONDS=12
fi
case "$MQTT_COMMAND_REPEAT_WINDOW_SECONDS" in
  ''|*[!0-9]*) MQTT_COMMAND_REPEAT_WINDOW_SECONDS=20 ;;
esac
if [ "$MQTT_COMMAND_REPEAT_WINDOW_SECONDS" -lt 0 ] || [ "$MQTT_COMMAND_REPEAT_WINDOW_SECONDS" -gt 600 ]; then
  MQTT_COMMAND_REPEAT_WINDOW_SECONDS=20
fi
case "$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS" in
  ''|*[!0-9]*) MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS=2 ;;
esac
if [ "$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS" -lt 1 ] || [ "$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS" -gt 60 ]; then
  MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS=2
fi
case "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" in
  ''|*[!0-9]*) MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS=20 ;;
esac
if [ "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" -lt 1 ] || [ "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" -gt 600 ]; then
  MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS=20
fi
if [ "$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" -lt "$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS" ]; then
  MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS"
fi
case "$MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER" in
  ''|*[!0-9]*) MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER=2 ;;
esac
if [ "$MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER" -lt 1 ] || [ "$MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER" -gt 5 ]; then
  MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER=2
fi
MQTT_HA_DISCOVERY_PREFIX="$(printf '%s' "$MQTT_HA_DISCOVERY_PREFIX" | sed 's#[^A-Za-z0-9._/-]##g; s#^/*##; s#/*$##')"
if [ -z "$MQTT_HA_DISCOVERY_PREFIX" ]; then
  MQTT_HA_DISCOVERY_PREFIX="homeassistant"
fi
case "$POWER_ESTIMATE_BASE_MW" in
  ''|*[!0-9]*) POWER_ESTIMATE_BASE_MW=1700 ;;
esac
if [ "$POWER_ESTIMATE_BASE_MW" -lt 500 ] || [ "$POWER_ESTIMATE_BASE_MW" -gt 10000 ]; then
  POWER_ESTIMATE_BASE_MW=1700
fi
case "$POWER_ESTIMATE_CPU_SCALE_MW" in
  ''|*[!0-9]*) POWER_ESTIMATE_CPU_SCALE_MW=500 ;;
esac
if [ "$POWER_ESTIMATE_CPU_SCALE_MW" -lt 0 ] || [ "$POWER_ESTIMATE_CPU_SCALE_MW" -gt 5000 ]; then
  POWER_ESTIMATE_CPU_SCALE_MW=500
fi
case "$POWER_ESTIMATE_IR_LED_MW" in
  ''|*[!0-9]*) POWER_ESTIMATE_IR_LED_MW=700 ;;
esac
if [ "$POWER_ESTIMATE_IR_LED_MW" -lt 0 ] || [ "$POWER_ESTIMATE_IR_LED_MW" -gt 5000 ]; then
  POWER_ESTIMATE_IR_LED_MW=700
fi
case "$POWER_SENSOR_PATH" in
  ''|auto)
    POWER_SENSOR_PATH="auto"
    ;;
  /*)
    POWER_SENSOR_PATH="$(printf '%s' "$POWER_SENSOR_PATH" | sed 's#[^A-Za-z0-9._/-]##g')"
    [ -n "$POWER_SENSOR_PATH" ] || POWER_SENSOR_PATH="auto"
    ;;
  *)
    POWER_SENSOR_PATH="auto"
    ;;
esac

if [ -z "$MQTT_TOPIC_COMMAND" ]; then
  MQTT_TOPIC_COMMAND="${MQTT_TOPIC_ROOT}/command"
fi

if [ "$SERVICE_TRIM" = "1" ]; then
  PERFORMANCE_PROFILE="rtsp-only"
elif [ "$LOW_CPU_PROFILE" = "1" ]; then
  PERFORMANCE_PROFILE="low-cpu"
else
  PERFORMANCE_PROFILE="balanced"
fi

case "$ONVIF_STREAM_POLICY" in
  main-primary|sub-primary|sub-only|main-only) ;;
  *) ONVIF_STREAM_POLICY="main-primary" ;;
esac

if [ "$RTSP_SUBSTREAM" = "1" ] && [ "$RTSP_AUDIO" = "1" ]; then
  STREAM_TOPOLOGY="dual-audio"
elif [ "$RTSP_SUBSTREAM" = "1" ] && [ "$RTSP_AUDIO" = "0" ]; then
  STREAM_TOPOLOGY="dual-no-audio"
elif [ "$RTSP_SUBSTREAM" = "0" ] && [ "$RTSP_AUDIO" = "1" ]; then
  STREAM_TOPOLOGY="main-audio"
else
  STREAM_TOPOLOGY="main-only"
fi

IFS=" "
set -- $(/mnt/bin/rwconf /mnt/config/recording.conf r " " rec_motion_activated " " rec_postrecord_sec " " rec_file_duration_sec " " rec_reserverd_disk_mb)
rec_motion_activated=$1
rec_postrecord_sec=$2
rec_file_duration_sec=$3
rec_reserverd_disk_mb=$4

set -- $(/mnt/bin/rwconf /mnt/config/timelapse.conf r " " TIMELAPSE_INTERVAL " " TIMELAPSE_DURATION)
TIMELAPSE_INTERVAL=$1
TIMELAPSE_DURATION=$2

set -- $(/mnt/bin/rwconf /mnt/config/rtspserver.conf r " " osdfrontcolor " " osdbackcolor " " osdedgecolor \
    0 codec 0 profile 0 width 0 brmode 1 codec 1 profile 1 width 1 brmode " " samplerate \
    2 codec 2 samplerate 3 codec 3 samplerate " " PORT 0 fps 0 bps 0 goplen 0 minqp 0 maxqp \
    1 fps 1 bps 1 goplen 1 minqp 1 maxqp " " volume " " imageflip " " RTSPLOGENABLED \
    " " nightdayawb " " nightdaylum " " daynightawb " " daynightlum " " osdenabled " " osdalpha \
    0 osdfontsize 1 osdfontsize 0 osdx 0 osdy 1 osdx 1 osdy \
    0 smartmode 0 smartgoplen 0 smartquality 0 smartstatic 0 maxkbps 0 targetkbps \
    1 smartmode 1 smartgoplen 1 smartquality 1 smartstatic 1 maxkbps 1 targetkbps \
    " " mdsens)

osdfrontcolor=$1
osdbackcolor=$2
osdedgecolor=$3
codec0=$4
profile0=$5
width0=$6
brmode0=$7
codec1=$8
profile1=$9
width1=$10
brmode1=$11
samplerate=$12
codec2=$13
samplerate2=$14
codec3=$15
samplerate3=$16
RTSP_PORT=$17
fps0=$18
bps0=$19
goplen0=$20
minqp0=$21
maxqp0=$22
fps1=$23
bps1=$24
goplen1=$25
minqp1=$26
maxqp1=$27
volume=$28
imageflip=$29
RTSPLOGENABLED=$30
nightdayawb=$31
nightdaylum=$32
daynightawb=$33
daynightlum=$34
osdenabled=$35
osdalpha=$36
osdfontsize0=$37
osdfontsize1=$38
osdx0=$39
osdy0=$40
osdx1=$41
osdy1=$42
smartmode0=$43
smartgoplen0=$44
smartquality0=$45
smartstatic0=$46
maxkbps0=$47
targetkbps0=$48
smartmode1=$49
smartgoplen1=$50
smartquality1=$51
smartstatic1=$52
maxkbps1=$53
targetkbps1=$54
mdsens=$55

TELNET_PORT=$(read_config telnetd.conf TELNET_PORT)
motion_trigger_led=$(read_config motion.conf motion_trigger_led)

# Sound Detection Config
install_config /mnt/config/sound_detection.conf
SOUND_DET_ENABLE=$(read_config sound_detection.conf ENABLE 0)
SOUND_DET_THRESHOLD=$(read_config sound_detection.conf THRESHOLD 1500)
SOUND_DET_INTERVAL=$(read_config sound_detection.conf INTERVAL 5)

DEFAULT_USERNAME="root"
DEFAULT_PASSWORD="pass"
DEFAULT_HTTP_HASH="1d06b7785388de1501e8d57847540f6d"
default_password_active=0
default_password_reason=""

rtsp_username="$(read_config rtspserver.conf USERNAME)"
rtsp_password="$(read_config rtspserver.conf USERPASSWORD)"
if [ "$rtsp_username" = "$DEFAULT_USERNAME" ] && [ "$rtsp_password" = "$DEFAULT_PASSWORD" ]; then
  default_password_active=1
  default_password_reason="${default_password_reason} RTSP"
fi

http_hash="$(awk -F: 'NR==1{gsub(/\r/,"",$3); print $3; exit}' /mnt/config/lighttpd.user 2>/dev/null)"
if [ "$http_hash" = "$DEFAULT_HTTP_HASH" ]; then
  default_password_active=1
  default_password_reason="${default_password_reason} HTTP"
fi

if [ -r /mnt/config/user.pwd ]; then
  read -r all_services_password < /mnt/config/user.pwd
  if [ "$all_services_password" = "$DEFAULT_PASSWORD" ]; then
    default_password_active=1
    default_password_reason="${default_password_reason} all-services"
  fi
fi

default_password_reason="$(echo "$default_password_reason" | sed 's/^ *//')"
setup_wizard_needed=0
if [ "$default_password_active" -eq 1 ] || [ "$SETUP_WIZARD_DONE" != "1" ]; then
  setup_wizard_needed=1
fi

KNOWN_GOOD_STREAM_FILE="/mnt/config/snapshots/stream.known-good.conf"
known_good_snapshot_available=0
known_good_snapshot_ts=""
known_good_snapshot_reason=""
if [ -r "$KNOWN_GOOD_STREAM_FILE" ]; then
  known_good_snapshot_ts="$(awk -F= '/^TS=/{print $2; exit}' "$KNOWN_GOOD_STREAM_FILE" 2>/dev/null)"
  known_good_snapshot_reason="$(awk -F= '/^REASON=/{print substr($0, index($0, "=")+1); exit}' "$KNOWN_GOOD_STREAM_FILE" 2>/dev/null)"
  known_good_snapshot_available=1
fi

CAMERA_IP=$(cat /tmp/camera_ip.txt 2>/dev/null)
[ -n "$CAMERA_IP" ] || CAMERA_IP=$(ifconfig wlan0 2>/dev/null | awk '/inet addr:/{split($2,a,":");print a[2];exit}')
[ -n "$CAMERA_IP" ] || CAMERA_IP="CAMERA-IP"

mount|grep "/mmcblk"|grep "rw,">/dev/null

if [ $? == 1 ]; then

cat << EOF
  <!-- sdcard warning -->
  <article class="message is-warning">
    <div class="message-header">
      <p>Warning</p>
      <button class="delete" aria-label="delete"></button>
    </div>
    <div class="message-body">
      Your sdcard is mounted read-only. Settings can't be saved.
      <br>
      <p>Please try rebooting.</a></p>
    </div>
  </article>
  <!-- end sdcard warning -->
EOF

fi

if [ "$default_password_active" -eq 1 ]; then
cat << EOF
  <article class="message is-danger">
    <div class="message-header">
      <p>Security warning</p>
    </div>
    <div class="message-body">
      Default credentials are still active ($default_password_reason). Change password now in this section.
    </div>
  </article>
EOF
fi

cat << EOF
<!-- Setup Wizard -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Setup Wizard</p></header>
    <div class='card-content'>
        $(if [ "$setup_wizard_needed" -eq 1 ]; then
            echo "<article class=\"message is-warning\"><div class=\"message-header\"><p>Action required</p></div><div class=\"message-body\">Complete this wizard to lock in safe defaults for password, compatibility preset, timezone/NTP, and verification links.</div></article>";
          else
            echo "<article class=\"message is-success\"><div class=\"message-header\"><p>Completed</p></div><div class=\"message-body\">Setup wizard has been completed. You can rerun it anytime to update baseline settings.</div></article>";
          fi)
        <form id="formSetupWizard" action="cgi-bin/action.cgi?cmd=complete_setup_wizard" method="post">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="wizard_password">New password</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="wizard_password" name="wizard_password" type="password" placeholder="Required while defaults are active" />
                        </div>
                        <p class="help">If defaults are still active, password change is mandatory.</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="wizard_profile">Compatibility preset</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select id="wizard_profile" name="wizard_profile">
                                    <option value="universal-h264">Universal H264 (recommended)</option>
                                    <option value="ha-frigate">HA Frigate (detection friendly)</option>
                                    <option value="hybrid-hevc-main">Hybrid HEVC main + H264 sub</option>
                                    <option value="legacy-main-only">Legacy main-only H264</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="wizard_tz">Timezone</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="wizard_tz" name="wizard_tz" type="text" value="$(cat /mnt/config/timezone.conf 2>/dev/null)" />
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="wizard_ntp_srv" name="wizard_ntp_srv" type="text" value="$(cat /mnt/config/ntp_srv.conf 2>/dev/null)" />
                        </div>
                        <p class="help">NTP server</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="wizard_hostname">Hostname</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="wizard_hostname" name="wizard_hostname" type="text" value="$(hostname)" />
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="wizard_enable_ntp" value="0" />
                            <input class="switch" id="wizard_enable_ntp" name="wizard_enable_ntp" type="checkbox" value="1" $(if [ "$ENABLE_NTP" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="wizard_enable_ntp">Enable NTP sync</label>
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="setupWizardSubmit" class="button is-primary" type="submit">Complete wizard</button>
                        </div>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal"></div>
                <div class="field-body">
                    <div class="field">
                        <p class="help">Wizard applies password (when needed), compatibility preset, timezone/NTP, and marks setup complete.</p>
                    </div>
                </div>
            </div>
        </form>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Quick checks</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="buttons">
                        <a class="button is-light" href="rtsp://$CAMERA_IP:$RTSP_PORT/video0_unicast" target="_blank" rel="noopener">RTSP main</a>
                        $(if [ "$RTSP_SUBSTREAM" = "1" ]; then
                            echo "<a class=\"button is-light\" href=\"rtsp://$CAMERA_IP:$RTSP_PORT/video1_unicast\" target=\"_blank\" rel=\"noopener\">RTSP sub</a>";
                          else
                            echo "<a class=\"button is-light\" href=\"rtsp://$CAMERA_IP:$RTSP_PORT/unicast\" target=\"_blank\" rel=\"noopener\">RTSP main-only</a>";
                          fi)
                        <a class="button is-light" href="/onvif/device_service" target="_blank" rel="noopener">ONVIF endpoint</a>
                        <a class="button is-light" href="cgi-bin/currentpic.cgi" target="_blank" rel="noopener">Snapshot</a>
                    </div>
                    <p class="help">Use these links to quickly confirm RTSP/ONVIF/snapshot availability after setup.</p>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Date -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>System</p></header>
    <div class='card-content'>
    <div class="field is-horizontal">
        <div class="field-label is-normal">
            <label class="label">Service trim</label>
        </div>
        <div class="field-body">
            <div class="field">
                <div class="control">
                    <input class="switch" name="serviceTrim" id="serviceTrim" type="checkbox" $(if [ "$SERVICE_TRIM" -eq 1 > /dev/null 2>&1 ]; then echo "checked"; fi)>
                    <label class="label" for="serviceTrim">RTSP + ONVIF only (reboot for full effect)</label>
                </div>
            </div>
        </div>
    </div>
    <form id="formPerformanceProfile" action="cgi-bin/action.cgi?cmd=set_performance_profile" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="performance_profile">Performance profile</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <div class="select is-fullwidth">
                            <select id="performance_profile" name="performance_profile">
                                <option value="balanced" $(if [ "$PERFORMANCE_PROFILE" = "balanced" ]; then echo selected; fi)>Balanced</option>
                                <option value="low-cpu" $(if [ "$PERFORMANCE_PROFILE" = "low-cpu" ]; then echo selected; fi)>Low CPU</option>
                                <option value="rtsp-only" $(if [ "$PERFORMANCE_PROFILE" = "rtsp-only" ]; then echo selected; fi)>RTSP + ONVIF only</option>
                            </select>
                        </div>
                    </div>
                    <p class="help">Applies grouped CPU-saving settings. Low CPU keeps dual RTSP endpoints on safe geometry; reboot recommended for full profile effect.</p>
                </div>
                <div class="field">
                    <div class="control">
                        <button id="performanceProfileSubmit" class="button is-primary" type="submit">Apply</button>
                    </div>
                </div>
            </div>
        </div>
    </form>
    <div class="field is-horizontal">
        <div class="field-label is-normal">
            <label class="label">Memory Management</label>
        </div>
        <div class="field-body">
            <div class="field">
                <div class="control">
                    <button id="btnFreeRam" class="button is-warning is-light">Free System RAM</button>
                </div>
                <p class="help">Clears OS file/node caches. Safe to run anytime to relieve memory pressure.</p>
            </div>
        </div>
    </div>
    <form id="formWebMode" action="cgi-bin/action.cgi?cmd=set_web_mode" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="web_mode">Web server mode</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <div class="select is-fullwidth">
                            <select id="web_mode" name="web_mode">
                                <option value="full" $(if [ "$WEB_MODE" = "full" ]; then echo selected; fi)>Full HTTPS (default)</option>
                                <option value="http" $(if [ "$WEB_MODE" = "http" ]; then echo selected; fi)>HTTP only</option>
                                <option value="ultra-lite" $(if [ "$WEB_MODE" = "ultra-lite" ]; then echo selected; fi)>Ultra-lite BusyBox HTTP</option>
                                <option value="off" $(if [ "$WEB_MODE" = "off" ]; then echo selected; fi)>Off</option>
                            </select>
                        </div>
                    </div>
                    <p class="help">Use ultra-lite to minimize web CPU/RAM usage. ONVIF web endpoint follows this mode.</p>
                </div>
                <div class="field web-port-field">
                    <div class="control">
                        <input class="input" id="ultralite_http_port" name="ultralite_http_port" type="number" min="1" max="65535" value="$ULTRALITE_HTTP_PORT">
                    </div>
                    <p class="help">Ultra-lite HTTP port (only used when mode is ultra-lite).</p>
                </div>
                <div class="field">
                    <div class="control">
                        <button id="webModeSubmit" class="button is-primary" type="submit">Apply</button>
                    </div>
                </div>
            </div>
        </div>
    </form>
    <form id="formStreamTopology" action="cgi-bin/action.cgi?cmd=set_stream_topology" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="stream_topology">Stream topology</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <div class="select is-fullwidth">
                            <select id="stream_topology" name="stream_topology">
                                <option value="dual-audio" $(if [ "$STREAM_TOPOLOGY" = "dual-audio" ]; then echo selected; fi)>Dual stream + audio</option>
                                <option value="dual-no-audio" $(if [ "$STREAM_TOPOLOGY" = "dual-no-audio" ]; then echo selected; fi)>Dual stream, audio off</option>
                                <option value="main-audio" $(if [ "$STREAM_TOPOLOGY" = "main-audio" ]; then echo selected; fi)>Main stream + audio</option>
                                <option value="main-only" $(if [ "$STREAM_TOPOLOGY" = "main-only" ]; then echo selected; fi)>Main stream only</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div class="field">
                    <div class="control">
                        <button id="streamTopologySubmit" class="button is-primary" type="submit">Apply</button>
                    </div>
                </div>
            </div>
        </div>
    </form>
    <form id="formOnvifPolicy" action="cgi-bin/action.cgi?cmd=set_onvif_stream_policy" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="onvif_stream_policy">ONVIF stream policy</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <div class="select is-fullwidth">
                            <select id="onvif_stream_policy" name="onvif_stream_policy">
                                <option value="main-primary" $(if [ "$ONVIF_STREAM_POLICY" = "main-primary" ]; then echo selected; fi)>Main primary (default)</option>
                                <option value="sub-primary" $(if [ "$ONVIF_STREAM_POLICY" = "sub-primary" ]; then echo selected; fi)>Substream primary</option>
                                <option value="sub-only" $(if [ "$ONVIF_STREAM_POLICY" = "sub-only" ]; then echo selected; fi)>Substream only (lowest ONVIF load)</option>
                                <option value="main-only" $(if [ "$ONVIF_STREAM_POLICY" = "main-only" ]; then echo selected; fi)>Main only</option>
                            </select>
                        </div>
                    </div>
                    <p class="help">Use substream policy to keep ONVIF clients off the main stream.</p>
                </div>
                <div class="field">
                    <div class="control">
                        <button id="onvifPolicySubmit" class="button is-primary" type="submit">Apply</button>
                    </div>
                </div>
            </div>
        </div>
    </form>
    <div class="field is-horizontal">
        <div class="field-label is-normal">
            <label class="label">Theme</label>
        </div>
        <div class="field-body">
            <div class="field">
                <div class="control">
                    <div class="theme-switcher">
                        <button id="theme_choice_0" class="button theme_choice" type="button" data-css="css/bulma.0.6.2.min.css" data-theme="0">Light</button>
                        <button id="theme_choice_1" class="button theme_choice" type="button" data-css="css/bulmaswatch.min.css" data-theme="1">Dark</button>
                    </div>
                </div>
                <p class="help">Theme moved here to keep the live screen focused.</p>
            </div>
        </div>
    </div>
    <form id="tzForm" action="cgi-bin/action.cgi?cmd=settz" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="tz">Timezone</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="tz" name="tz" type="text" size="25" value="$(cat /mnt/config/timezone.conf)" />
                    </div>
                    <p>$(date)</p>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="ntp_srv">NTP Server</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="ntp_srv" name="ntp_srv" type="text" size="25" value="$(cat /mnt/config/ntp_srv.conf)" />
                    </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="hostname">Hostname</label>
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input class="input" id="hostname" name="hostname" type="text" size="15" value="$(hostname)" />
                </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input id="tzSubmit" class="button is-primary" type="submit" value="Set" />
                </div>
                </div>
            </div>
        </div>
    </form>
    </div>
</div>


<!-- Advanced tuning -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Advanced Tuning</p></header>
    <div class='card-content'>
        <form id="formAdvancedTuning" action="cgi-bin/action.cgi?cmd=set_advanced_tuning" method="post">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Boot modes</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="lightweight_mode" value="0" />
                            <input class="switch" name="lightweight_mode" id="lightweight_mode" type="checkbox" value="1" $(if [ "$LIGHTWEIGHT_MODE" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="lightweight_mode">Lightweight mode</label>
                        </div>
                        <div class="control">
                            <input type="hidden" name="ui_ultralite_mode" value="0" />
                            <input class="switch" name="ui_ultralite_mode" id="ui_ultralite_mode" type="checkbox" value="1" $(if [ "$UI_ULTRALITE_MODE" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="ui_ultralite_mode">Ultra-lite UI mode (min web CPU)</label>
                        </div>
                        <div class="control">
                            <input type="hidden" name="enable_ntp" value="0" />
                            <input class="switch" name="enable_ntp" id="enable_ntp" type="checkbox" value="1" $(if [ "$ENABLE_NTP" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="enable_ntp">Enable NTP sync</label>
                        </div>
                        <div class="control">
                            <input type="hidden" name="ntp_one_shot" value="0" />
                            <input class="switch" name="ntp_one_shot" id="ntp_one_shot" type="checkbox" value="1" $(if [ "$NTP_ONE_SHOT" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="ntp_one_shot">NTP one-shot at boot</label>
                        </div>
                        <div class="control">
                            <input type="hidden" name="security_hardening_mode" value="0" />
                            <input class="switch" name="security_hardening_mode" id="security_hardening_mode" type="checkbox" value="1" $(if [ "$SECURITY_HARDENING_MODE" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="security_hardening_mode">Security hardening mode (force HTTPS, disable FTP/Telnet)</label>
                        </div>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Memory guard</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="mem_guard_enable" value="0" />
                            <input class="switch" name="mem_guard_enable" id="mem_guard_enable" type="checkbox" value="1" $(if [ "$MEM_GUARD_ENABLE" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="mem_guard_enable">Enable memory guard daemon</label>
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mem_guard_interval_seconds" name="mem_guard_interval_seconds" type="number" min="5" max="600" value="$MEM_GUARD_INTERVAL_SECONDS" />
                        </div>
                        <p class="help">Check interval (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mem_guard_warn_kb" name="mem_guard_warn_kb" type="number" min="2048" max="65535" value="$MEM_GUARD_WARN_KB" />
                        </div>
                        <p class="help">Warn threshold (kB)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mem_guard_critical_kb" name="mem_guard_critical_kb" type="number" min="1024" max="65535" value="$MEM_GUARD_CRITICAL_KB" />
                        </div>
                        <p class="help">Critical threshold (kB)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mem_guard_emergency_kb" name="mem_guard_emergency_kb" type="number" min="512" max="32768" value="$MEM_GUARD_EMERGENCY_KB" />
                        </div>
                        <p class="help">Emergency threshold (kB)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mem_guard_recovery_margin_kb" name="mem_guard_recovery_margin_kb" type="number" min="256" max="32768" value="$MEM_GUARD_RECOVERY_MARGIN_KB" />
                        </div>
                        <p class="help">Recovery margin before counters reset (kB)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mem_guard_warn_hits" name="mem_guard_warn_hits" type="number" min="1" max="10" value="$MEM_GUARD_WARN_HITS" />
                        </div>
                        <p class="help">Warn hits before action</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mem_guard_critical_hits" name="mem_guard_critical_hits" type="number" min="1" max="10" value="$MEM_GUARD_CRITICAL_HITS" />
                        </div>
                        <p class="help">Critical hits before heavy action</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mem_guard_cooldown_seconds" name="mem_guard_cooldown_seconds" type="number" min="10" max="3600" value="$MEM_GUARD_COOLDOWN_SECONDS" />
                        </div>
                        <p class="help">Action cooldown (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="mem_guard_drop_caches" value="0" />
                            <input class="switch" name="mem_guard_drop_caches" id="mem_guard_drop_caches" type="checkbox" value="1" $(if [ "$MEM_GUARD_DROP_CACHES" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="mem_guard_drop_caches">Allow cache drop under critical pressure</label>
                        </div>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Healthcheck timeouts</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="rtsp_healthcheck_timeout_seconds" name="rtsp_healthcheck_timeout_seconds" type="number" min="2" max="30" value="$RTSP_HEALTHCHECK_TIMEOUT_SECONDS" />
                        </div>
                        <p class="help">RTSP watchdog timeout (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="onvif_healthcheck_timeout_seconds" name="onvif_healthcheck_timeout_seconds" type="number" min="2" max="30" value="$ONVIF_HEALTHCHECK_TIMEOUT_SECONDS" />
                        </div>
                        <p class="help">ONVIF watchdog timeout (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="advancedTuningSubmit" class="button is-primary" type="submit">Apply</button>
                        </div>
                    </div>
                </div>
            </div>
            <p class="help">Reboot recommended after changing boot modes (Lightweight/NTP/Security hardening) for full effect.</p>
        </form>
</div>
</div>

<!-- Scheduled Reboot -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Scheduled Reboot</p></header>
    <div class='card-content'>
        <form id="formRebootSchedule" action="cgi-bin/action.cgi?cmd=set_reboot_schedule" method="post">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Enable</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="reboot_schedule_enable" value="0" />
                            <input class="switch" id="reboot_schedule_enable" name="reboot_schedule_enable" type="checkbox" value="1" $(if [ "$REBOOT_SCHEDULE_ENABLE" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="reboot_schedule_enable">Enable scheduled reboot cron task</label>
                        </div>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="reboot_schedule_hour">Schedule</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="reboot_schedule_hour" name="reboot_schedule_hour" type="number" min="0" max="23" value="$REBOOT_SCHEDULE_HOUR" />
                        </div>
                        <p class="help">Hour (0-23)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="reboot_schedule_minute" name="reboot_schedule_minute" type="number" min="0" max="59" value="$REBOOT_SCHEDULE_MINUTE" />
                        </div>
                        <p class="help">Minute (0-59)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select id="reboot_schedule_weekday" name="reboot_schedule_weekday">
                                    <option value="*" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "*" ]; then echo "selected"; fi)>Every day</option>
                                    <option value="1-5" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "1-5" ]; then echo "selected"; fi)>Weekdays (Mon-Fri)</option>
                                    <option value="0,6" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "0,6" ]; then echo "selected"; fi)>Weekend (Sun/Sat)</option>
                                    <option value="0" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "0" ]; then echo "selected"; fi)>Sunday</option>
                                    <option value="1" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "1" ]; then echo "selected"; fi)>Monday</option>
                                    <option value="2" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "2" ]; then echo "selected"; fi)>Tuesday</option>
                                    <option value="3" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "3" ]; then echo "selected"; fi)>Wednesday</option>
                                    <option value="4" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "4" ]; then echo "selected"; fi)>Thursday</option>
                                    <option value="5" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "5" ]; then echo "selected"; fi)>Friday</option>
                                    <option value="6" $(if [ "$REBOOT_SCHEDULE_WEEKDAY" = "6" ]; then echo "selected"; fi)>Saturday</option>
                                </select>
                            </div>
                        </div>
                        <p class="help">Day pattern</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="rebootScheduleSubmit" class="button is-primary" type="submit">Apply</button>
                        </div>
                    </div>
                </div>
            </div>
            <p class="help">This creates a managed cron entry. When enabled, crond is auto-enabled in boot config if needed.</p>
            <p class="help">Current expression: <code>$REBOOT_SCHEDULE_MINUTE $REBOOT_SCHEDULE_HOUR * * $REBOOT_SCHEDULE_WEEKDAY</code></p>
        </form>
    </div>
</div>

<!-- MQTT Bridge -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>MQTT Bridge</p></header>
    <div class='card-content'>
        <form id="formMqttConfig" action="cgi-bin/action.cgi?cmd=set_mqtt_config" method="post">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Enable</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="mqtt_enable" value="0" />
                            <input class="switch" id="mqtt_enable" name="mqtt_enable" type="checkbox" value="1" $(if [ "$MQTT_ENABLE" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="mqtt_enable">Publish health/events and accept command topic actions</label>
                        </div>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="mqtt_host">Broker</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_host" name="mqtt_host" type="text" value="$MQTT_HOST" />
                        </div>
                        <p class="help">Host/IP of your local broker.</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_port" name="mqtt_port" type="number" min="1" max="65535" value="$MQTT_PORT" />
                        </div>
                        <p class="help">Port (default 1883)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_qos" name="mqtt_qos" type="number" min="0" max="2" value="$MQTT_QOS" />
                        </div>
                        <p class="help">QoS (0..2)</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="mqtt_user">Auth</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_user" name="mqtt_user" type="text" value="$MQTT_USER" />
                        </div>
                        <p class="help">Username (optional)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_password" name="mqtt_password" type="password" value="$MQTT_PASSWORD" />
                        </div>
                        <p class="help">Password (optional)</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="mqtt_client_id">Topics</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_client_id" name="mqtt_client_id" type="text" value="$MQTT_CLIENT_ID" />
                        </div>
                        <p class="help">Client ID</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_topic_root" name="mqtt_topic_root" type="text" value="$MQTT_TOPIC_ROOT" />
                        </div>
                        <p class="help">Topic root, example: tc100/camera</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_topic_command" name="mqtt_topic_command" type="text" value="$MQTT_TOPIC_COMMAND" />
                        </div>
                        <p class="help">Command topic (empty = &lt;root&gt;/command)</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Intervals</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_health_interval_seconds" name="mqtt_health_interval_seconds" type="number" min="10" max="86400" value="$MQTT_HEALTH_INTERVAL_SECONDS" />
                        </div>
                        <p class="help">Health publish interval (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_command_wait_seconds" name="mqtt_command_wait_seconds" type="number" min="3" max="120" value="$MQTT_COMMAND_WAIT_SECONDS" />
                        </div>
                        <p class="help">Command poll timeout (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_command_repeat_window_seconds" name="mqtt_command_repeat_window_seconds" type="number" min="0" max="600" value="$MQTT_COMMAND_REPEAT_WINDOW_SECONDS" />
                        </div>
                        <p class="help">Duplicate command suppression window (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="mqttConfigSubmit" class="button is-primary" type="submit">Apply</button>
                        </div>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Retry backoff</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_subscribe_backoff_initial_seconds" name="mqtt_subscribe_backoff_initial_seconds" type="number" min="1" max="60" value="$MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS" />
                        </div>
                        <p class="help">Initial retry delay after subscribe failure (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_subscribe_backoff_max_seconds" name="mqtt_subscribe_backoff_max_seconds" type="number" min="1" max="600" value="$MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS" />
                        </div>
                        <p class="help">Maximum retry delay (seconds)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_subscribe_backoff_multiplier" name="mqtt_subscribe_backoff_multiplier" type="number" min="1" max="5" value="$MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER" />
                        </div>
                        <p class="help">Retry growth factor per failure</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Home Assistant</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="mqtt_ha_discovery_enable" value="0" />
                            <input class="switch" id="mqtt_ha_discovery_enable" name="mqtt_ha_discovery_enable" type="checkbox" value="1" $(if [ "$MQTT_HA_DISCOVERY_ENABLE" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="mqtt_ha_discovery_enable">Enable HA MQTT Discovery (retained topics)</label>
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="mqtt_ha_discovery_prefix" name="mqtt_ha_discovery_prefix" type="text" value="$MQTT_HA_DISCOVERY_PREFIX" />
                        </div>
                        <p class="help">Discovery prefix (default <code>homeassistant</code>)</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Power</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="power_estimate_enable" value="0" />
                            <input class="switch" id="power_estimate_enable" name="power_estimate_enable" type="checkbox" value="1" $(if [ "$POWER_ESTIMATE_ENABLE" = "1" ]; then echo "checked"; fi) />
                            <label class="label" for="power_estimate_enable">Enable estimated power draw (CPU-safe)</label>
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="power_estimate_base_mw" name="power_estimate_base_mw" type="number" min="500" max="10000" value="$POWER_ESTIMATE_BASE_MW" />
                        </div>
                        <p class="help">Base power (mW)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="power_estimate_cpu_scale_mw" name="power_estimate_cpu_scale_mw" type="number" min="0" max="5000" value="$POWER_ESTIMATE_CPU_SCALE_MW" />
                        </div>
                        <p class="help">CPU scaling at 100% load (mW)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="power_estimate_ir_led_mw" name="power_estimate_ir_led_mw" type="number" min="0" max="5000" value="$POWER_ESTIMATE_IR_LED_MW" />
                        </div>
                        <p class="help">IR LED add-on (mW)</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="power_sensor_path" name="power_sensor_path" type="text" value="$POWER_SENSOR_PATH" />
                        </div>
                        <p class="help">Voltage sensor path (<code>auto</code> or absolute path)</p>
                    </div>
                </div>
            </div>
            <p class="help">MQTT commands currently supported: <code>reboot</code>, <code>snapshot</code>, <code>profile:&lt;balanced|low-cpu|rtsp-only&gt;</code>.</p>
            <p class="help">Power draw is estimated unless measured with an external USB meter.</p>
        </form>
        <div class="is-divider" data-content="Home Assistant pairing"></div>
        <form id="formHomeAssistantPair" action="cgi-bin/action.cgi?cmd=pair_home_assistant" method="post">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="ha_broker_host">Broker</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="ha_broker_host" name="ha_broker_host" type="text" value="$MQTT_HOST" />
                        </div>
                        <p class="help">Home Assistant MQTT broker host/IP.</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="ha_broker_port" name="ha_broker_port" type="number" min="1" max="65535" value="$MQTT_PORT" />
                        </div>
                        <p class="help">Broker port (default 1883).</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select id="ha_profile" name="ha_profile">
                                    <option value="ha-frigate">HA Frigate (recommended)</option>
                                    <option value="universal-h264">Universal H264</option>
                                    <option value="hybrid-hevc-main">Hybrid HEVC main + H264 sub</option>
                                    <option value="legacy-main-only">Legacy main-only H264</option>
                                </select>
                            </div>
                        </div>
                        <p class="help">Stream compatibility preset to apply.</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="ha_user">Auth and topics</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="ha_user" name="ha_user" type="text" value="$MQTT_USER" />
                        </div>
                        <p class="help">MQTT username (optional).</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="ha_password" name="ha_password" type="password" value="$MQTT_PASSWORD" />
                        </div>
                        <p class="help">MQTT password (optional).</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="ha_client_id" name="ha_client_id" type="text" value="$MQTT_CLIENT_ID" />
                        </div>
                        <p class="help">MQTT client ID.</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="ha_topic_root" name="ha_topic_root" type="text" value="$MQTT_TOPIC_ROOT" />
                        </div>
                        <p class="help">Topic root (for example <code>tc100/camera</code>).</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="ha_discovery_prefix" name="ha_discovery_prefix" type="text" value="$MQTT_HA_DISCOVERY_PREFIX" />
                        </div>
                        <p class="help">Discovery prefix (default <code>homeassistant</code>).</p>
                    </div>
                </div>
            </div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Service policy</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input type="hidden" name="ha_enable_onvif" value="0" />
                            <input class="switch" id="ha_enable_onvif" name="ha_enable_onvif" type="checkbox" value="1" checked />
                            <label class="label" for="ha_enable_onvif">Enable ONVIF service/autostart</label>
                        </div>
                        <div class="control">
                            <input type="hidden" name="ha_enable_mqtt_autostart" value="0" />
                            <input class="switch" id="ha_enable_mqtt_autostart" name="ha_enable_mqtt_autostart" type="checkbox" value="1" checked />
                            <label class="label" for="ha_enable_mqtt_autostart">Enable MQTT bridge autostart</label>
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="haPairSubmit" class="button is-primary" type="submit">Pair with Home Assistant</button>
                        </div>
                    </div>
                </div>
            </div>
            <p class="help">This one-click action configures MQTT discovery, applies the selected RTSP/ONVIF profile, ensures autostart, and runs RTSP/ONVIF/MQTT health checks.</p>
        </form>
    </div>
</div>

<!-- HA / Frigate integration pack -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>HA / Frigate Integration Pack</p></header>
    <div class='card-content'>
        <p>Generated from the current live config so you can paste the camera into Frigate or Home Assistant without reconstructing URLs and MQTT topics by hand.</p>
        <div class="buttons">
            <a class="button is-light" href="cgi-bin/state.cgi?cmd=integrationmanifest" target="_blank" rel="noopener">Open integration manifest (JSON)</a>
        </div>
        <div class="field">
            <label class="label" for="integrationSummarySnippet">Endpoint summary</label>
            <div class="control">
                <textarea class="textarea" id="integrationSummarySnippet" rows="8" readonly>Loading integration summary...</textarea>
            </div>
            <p class="help">Quick operator view of the active RTSP, ONVIF, HTTP, and MQTT endpoints.</p>
            <div class="buttons mt-2">
                <button class="button is-light" type="button" data-copy-target="integrationSummarySnippet">Copy summary</button>
            </div>
        </div>
        <div class="field">
            <label class="label" for="frigateConfigSnippet">Frigate config snippet</label>
            <div class="control">
                <textarea class="textarea" id="frigateConfigSnippet" rows="14" readonly>Loading Frigate snippet...</textarea>
            </div>
            <p class="help">Uses the main stream for recording and the substream for detection when available.</p>
            <div class="buttons mt-2">
                <button class="button is-light" type="button" data-copy-target="frigateConfigSnippet">Copy Frigate YAML</button>
            </div>
        </div>
        <div class="field">
            <label class="label" for="homeAssistantIntegrationNotes">Home Assistant notes</label>
            <div class="control">
                <textarea class="textarea" id="homeAssistantIntegrationNotes" rows="12" readonly>Loading Home Assistant notes...</textarea>
            </div>
            <p class="help">Includes ONVIF settings, MQTT discovery details, and the most useful local URLs.</p>
            <div class="buttons mt-2">
                <button class="button is-light" type="button" data-copy-target="homeAssistantIntegrationNotes">Copy HA notes</button>
            </div>
        </div>
        <div class="field">
            <label class="label" for="integrationSelfTestResult">Integration self-test</label>
            <div class="buttons">
                <button id="integrationSelfTestRun" class="button is-primary is-light" type="button">Run self-test</button>
                <a class="button is-light" href="cgi-bin/state.cgi?cmd=integrationtest" target="_blank" rel="noopener">Open self-test JSON</a>
                <button class="button is-light" type="button" data-copy-target="integrationSelfTestResult">Copy self-test</button>
            </div>
            <div class="control">
                <textarea class="textarea" id="integrationSelfTestResult" rows="10" readonly>Click "Run self-test" to verify RTSP, ONVIF, MQTT publish, and local snapshot capture.</textarea>
            </div>
            <p class="help">Runs on demand so the page does not publish MQTT probes or re-check services every time Status reloads.</p>
        </div>
    </div>
</div>

<!-- Motion event API -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Motion Event API</p></header>
    <div class='card-content'>
        <p>Use these local endpoints for Home Assistant automations and dashboards:</p>
        <ul>
            <li><a href="cgi-bin/motionevents.cgi?limit=20" target="_blank">Recent events JSON</a> (<code>cgi-bin/motionevents.cgi?limit=20</code>)</li>
            <li><a href="cgi-bin/motionthumb.cgi" target="_blank">Latest motion thumbnail</a> (<code>cgi-bin/motionthumb.cgi</code>)</li>
        </ul>
        <p class="help">`motionevents.cgi` supports <code>limit</code> and optional <code>type</code> filter. `motionthumb.cgi` supports optional <code>file</code> from the motion snapshot folder.</p>
    </div>
</div>

EOF


cat << EOF
<!-- All services Password -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>HTTP/RTSP/Telnet Password</p></header>
    <div class='card-content'>
        <form id="allPasswordForm" action="cgi-bin/action.cgi?cmd=set_all_password" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Username</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" type="text" size="12" value="root" disabled/>
                    </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">New Password</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="allpassword" name="allpassword" type="password" size="12" value="*****"/>
                    </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input id="allpwSubmit" class="button is-primary" type="submit" value="Set" />
                </div>
                </div>
            </div>
        </div>
        </form>
    </div>
</div>


<!-- HTTP Password -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>HTTP Password</p></header>
    <div class='card-content'>
        <form id="passwordForm" action="cgi-bin/action.cgi?cmd=set_http_password" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Username</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" type="text" size="12" value="root" disabled/>
                    </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">New Password</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="httppassword" name="httppassword" type="password" size="12" value="*****"/>
                    </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input id="pwSubmit" class="button is-primary" type="submit" value="Set" />
                </div>
                </div>
            </div>
        </div>
        </form>
    </div>
</div>


<!-- Telnet -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Telnet Server</p></header>
    <div class='card-content'>
    <form id="telnetForm" action="cgi-bin/action.cgi?cmd=set_telnet" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="telnetport">Port</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="telnetport" name="telnetport" type="number" size="12" value="$TELNET_PORT"/>
                    </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input id="telnetSubmit" class="button is-primary" type="submit" value="Set" />
                </div>
                </div>
            </div>
        </div>
    </form>
    </div>
</div>

<!-- FTP -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>FTP Server</p></header>
    <div class='card-content'>
    <form id="ftpForm" action="cgi-bin/action.cgi?cmd=set_ftp" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label" for="ftpport">Port</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="ftpport" name="ftpport" type="number" size="12" value="$(read_config ftp.conf PORT)"/>
                    </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input id="ftpSubmit" class="button is-primary" type="submit" value="Set" />
                </div>
                </div>
            </div>
        </div>
    </form>
    </div>
</div>

<script>
    function call(url){
            var xhr = new XMLHttpRequest();
            xhr.open('GET', url, true);
            xhr.send();
    }

</script>



<!-- Video settings -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Video Settings</p></header>
    <div class='card-content'>
        <form id="formRtspPreset" action="cgi-bin/action.cgi?cmd=set_rtsp_preset" method="post">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">RTSP Preset</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="preset">
                                    <option value="full">Full (fps max 25)</option>
                                    <option value="medium">Medium (fps max 25)</option>
                                    <option value="low">Low (fps max 25)</option>
                                </select>
                            </div>
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="presetSubmit" class="button is-primary" type="submit">Apply preset</button>
                        </div>
                    </div>
                </div>
            </div>
        </form>
        <form id="formRtspQualityProfile" action="cgi-bin/action.cgi?cmd=set_rtsp_quality_profile" method="post">
            <div class="is-divider" data-content="High-quality presets"></div>
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">RTSP quality profile</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="rtsp_quality_profile">
                                    <option value="max-quality-h264">Max quality 1080p H264 (recommended)</option>
                                    <option value="max-quality-hevc">Max quality 1080p H265/HEVC</option>
                                    <option value="max-main-h264">Max quality main-only H264</option>
                                </select>
                            </div>
                        </div>
                        <p class="help">Predefined high-resolution stream tuning. Use H264 for widest VLC/NVR compatibility.</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="rtspQualityProfileSubmit" class="button is-primary" type="submit">Apply quality profile</button>
                        </div>
                    </div>
                </div>
            </div>
        </form>
        <form id="formClientProfilePreset" action="cgi-bin/action.cgi?cmd=set_client_profile" method="post">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Compatibility preset</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="client_profile">
                                    <option value="universal-h264">Universal H264 (recommended)</option>
                                    <option value="ha-frigate">HA Frigate (detection friendly)</option>
                                    <option value="hybrid-hevc-main">Hybrid HEVC main + H264 sub</option>
                                    <option value="legacy-main-only">Legacy main-only H264</option>
                                </select>
                            </div>
                        </div>
                        <p class="help">Four one-click ONVIF/RTSP profiles tuned for client compatibility and safe stream topology.</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="clientProfileSubmit" class="button is-primary" type="submit">Apply compatibility preset</button>
                        </div>
                    </div>
                </div>
            </div>
        </form>
        <div class="is-divider" data-content="Safety snapshots"></div>
        <p class="help">
            $(if [ "$known_good_snapshot_available" -eq 1 ]; then
                echo "Known-good snapshot available (ts=${known_good_snapshot_ts}, reason=${known_good_snapshot_reason}).";
              else
                echo "No known-good snapshot saved yet.";
              fi)
        </p>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Known-good actions</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="buttons">
                        <form id="formKnownGoodSave" action="cgi-bin/action.cgi?cmd=save_known_good_profile" method="post">
                            <button class="button is-link" type="submit">Save known-good snapshot</button>
                        </form>
                        <form id="formKnownGoodRestore" action="cgi-bin/action.cgi?cmd=restore_known_good_profile" method="post">
                            <button class="button is-warning" type="submit">Restore known-good snapshot</button>
                        </form>
                    </div>
                    <p class="help">Save after a stable image profile. Restore if a later change causes stream issues.</p>
                </div>
            </div>
        </div>
        <div class="is-divider" data-content="Advanced manual settings"></div>
        <form id="formResolution" action="cgi-bin/action.cgi?cmd=set_video_size" method="post">
                <div class="field is-horizontal">
                    <div class="field-label is-normal">
                        <label class="label" for="videouser">RTSP username</label>
                    </div>
                    <div class="field-body">
                        <div class="field">
                            <div class="control">
                                <input class="input" id="videouser" name="videouser" type="text" size="12" value="$(read_config rtspserver.conf USERNAME)" />
                            </div>
                        </div>
                    </div>
                </div>

                <div class="field is-horizontal">
                    <div class="field-label is-normal">
                        <label class="label" for="videopassword">RTSP password</label>
                    </div>
                    <div class="field-body">
                        <div class="field">
                            <div class="control">
                                <input class="input" id="videopassword" name="videopassword" type="password" size="12" value="$(read_config rtspserver.conf USERPASSWORD)" />
                            </div>
                        </div>
                    </div>
                </div>

                <div class="field is-horizontal">
                    <div class="field-label is-normal">
                        <label class="label" for="videoport">RTSP port</label>
                    </div>
                    <div class="field-body">
                        <div class="field">
                            <div class="control">
                                <input class="input" id="videoport" name="videoport" type="number" size="12" value=$RTSP_PORT placeholder="554"/>
                            </div>
                        </div>
                    </div>
                </div>

<!-- RTSP MAIN STREAM -->
            <div class="is-divider" data-content="Main stream"></div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Codec</label>
                 </div>
                 <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="video_codec0">
                                    <option value="0" $(if [ "$codec0" == "0" ]; then echo selected; fi)>H264</option>
                                    <option value="2" $(if [ "$codec0" == "2" ]; then echo selected; fi)>H265</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Profile</label>
                 </div>
                 <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="codec_profile0">
                                    <option value="0" $(if [ "$profile0" == "0" ]; then echo selected; fi)>Main</option>
                                    <option value="1" $(if [ "$profile0" == "1" ]; then echo selected; fi)>High</option>
                                    <option value="2" $(if [ "$profile0" == "2" ]; then echo selected; fi)>Base</option>
                                    <option value="3" $(if [ "$profile0" == "3" ]; then echo selected; fi)>Main (H265)</option>
                                    <option value="4" $(if [ "$profile0" == "4" ]; then echo selected; fi)>Main Still (H265)</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Video Size</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="video_size0">
                                    <option value="1024x576"  $(if [ "$width0" == "1024" ]; then echo selected; fi) >1024x576</option>
                                    <option value="1280x720"  $(if [ "$width0" == "1280" ]; then echo selected; fi) >1280x720</option>
                                    <option value="1600x904"  $(if [ "$width0" == "1600" ]; then echo selected; fi) >1600x904</option>
                                    <option value="1920x1080" $(if [ "$width0" == "1920" ]; then echo selected; fi) >1920x1080</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Video format</label>
                 </div>
                 <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="video_format0">
                                    <option value="0" $(if [ "$brmode0" == "0" ]; then echo selected; fi)>CBR</option>
                                    <option value="1" $(if [ "$brmode0" == "1" ]; then echo selected; fi)>VBR</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-body">
                    <div class="field-label is-normal">
                        <label class="label">FPS</label>
                    </div>
                    <div class="field-body">
                        <div class="field">
                            <div class="control">
                                <input class="input" id="fps0" name="fps0" type="text" size="12" value="$fps0" placeholder="25"/>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Bitrate(kb/s)</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="brbitrate0" name="brbitrate0" type="text" size="12" value="$bps0"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">GOP</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="goplen0" name="goplen0" type="text" size="12" value="$goplen0" placeholder="50"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">MinQP</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="minqp0" name="minqp0" type="text" size="12" value="$minqp0" placeholder="20"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">MaxQP</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="maxqp0" name="maxqp0" type="text" size="12" value="$maxqp0" placeholder="51"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Smart</label>
                 </div>
                 <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="smartmode0">
                                    <option value="0" $(if [ "$smartmode0" == "0" ]; then echo selected; fi)>OFF</option>
                                    <option value="1" $(if [ "$smartmode0" == "1" ]; then echo selected; fi)>LTR</option>
                                    <option value="2" $(if [ "$smartmode0" == "2" ]; then echo selected; fi)>GOP len</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Smart GOP</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="smartgoplen0" name="smartgoplen0" type="number" size="12" value="$smartgoplen0" placeholder="300"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Smart Quality</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="smartquality0" name="smartquality0" type="number" size="3" min="1" max="100" value="$smartquality0" placeholder="100"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Smart static</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="smartstatic0" name="smartstatic0" type="number" size="12" value="$smartstatic0" placeholder="550"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Max bitrate(kb/s)</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="maxkbps0" name="maxkbps0" type="number" size="12" value="$maxkbps0" placeholder="1000"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Target bitrate(kb/s)</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="targetkbps0" name="targetkbps0" type="number" size="12" value="$targetkbps0" placeholder="600"/>
                        </div>
                    </div>
                </div>
            </div>


<!-- RTSP SUB STREAM -->
            <div class="is-divider" data-content="Sub stream"></div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Codec</label>
                 </div>
                 <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="video_codec1">
                                    <option value="0" $(if [ "$codec1" == "0" ]; then echo selected; fi)>H264</option>
                                    <option value="2" $(if [ "$codec1" == "2" ]; then echo selected; fi)>H265</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Profile</label>
                 </div>
                 <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="codec_profile1">
                                    <option value="0" $(if [ "$profile1" == "0" ]; then echo selected; fi)>Main</option>
                                    <option value="1" $(if [ "$profile1" == "1" ]; then echo selected; fi)>High</option>
                                    <option value="2" $(if [ "$profile1" == "2" ]; then echo selected; fi)>Base</option>
                                    <option value="3" $(if [ "$profile1" == "3" ]; then echo selected; fi)>Main (H265)</option>
                                    <option value="4" $(if [ "$profile1" == "4" ]; then echo selected; fi)>Main Still (H265)</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Video Size</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="video_size1">
                                    <option value="352x200"   $(if [ "$width1" == "352" ];  then echo selected; fi) >352x200</option>
                                    <option value="640x360"   $(if [ "$width1" == "640" ];  then echo selected; fi) >640x360</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Video format</label>
                 </div>
                 <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="video_format1">
                                    <option value="0" $(if [ "$brmode1" == "0" ]; then echo selected; fi)>CBR</option>
                                    <option value="1" $(if [ "$brmode1" == "1" ]; then echo selected; fi)>VBR</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-body">
                    <div class="field-label is-normal">
                        <label class="label">FPS</label>
                    </div>
                    <div class="field-body">
                        <div class="field">
                            <div class="control">
                                <input class="input" id="fps1" name="fps1" type="text" size="12" value="$fps1" placeholder="25"/>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Bitrate(kb/s)</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="brbitrate1" name="brbitrate1" type="text" size="12" value="$bps1"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">GOP</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="goplen1" name="goplen1" type="text" size="12" value="$goplen1" placeholder="50"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">MinQP</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="minqp1" name="minqp1" type="text" size="12" value="$minqp1" placeholder="20"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">MaxQP</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="maxqp1" name="maxqp1" type="text" size="12" value="$maxqp1" placeholder="51"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Smart</label>
                 </div>
                 <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="smartmode1">
                                    <option value="0" $(if [ "$smartmode1" == "0" ]; then echo selected; fi)>OFF</option>
                                    <option value="1" $(if [ "$smartmode1" == "1" ]; then echo selected; fi)>LTR</option>
                                    <option value="2" $(if [ "$smartmode1" == "2" ]; then echo selected; fi)>GOP len</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Smart GOP</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="smartgoplen1" name="smartgoplen1" type="number" size="12" value="$smartgoplen1" placeholder="300"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Smart Quality</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="smartquality1" name="smartquality1" type="number" size="3" min="1" max="100" value="$smartquality1" placeholder="100"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Smart static</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="smartstatic1" name="smartstatic1" type="number" size="12" value="$smartstatic1" placeholder="550"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Max bitrate(kb/s)</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="maxkbps1" name="maxkbps1" type="number" size="12" value="$maxkbps1" placeholder="500"/>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">VBR Target bitrate(kb/s)</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="targetkbps1" name="targetkbps1" type="number" size="12" value="$targetkbps1" placeholder="300"/>
                        </div>
                    </div>
                </div>
            </div>


            <div class="field is-horizontal">
                <div class="field-label is-normal">
                </div>
                <div class="field-body">
                    <div class="field">
                    <div class="control">
                        <input id="resSubmit" class="button is-primary" type="submit" value="Set" />
                    </div>
                    </div>
                </div>
            </div>
        </form>
    </div>
</div>


<!-- Audio Settings -->
<div class='card status_card'>
    <header class='card-header'>
        <p class='card-header-title'>Audio Settings</p>
    </header>
    <div class='card-content'>
        <form id="formaudioin" action="cgi-bin/action.cgi?cmd=conf_audioin" method="post">

                    <div class="field is-horizontal">
                        <div class="field-label is-normal">
                            <label class="label">Sample rate</label>
                        </div>
                        <div class="field-body">
                                <div class="select is-fullwidth">
                                    <select name="samplerate">
                                           <option value="8000"  $(if [ "$samplerate" == "8000" ]; then echo selected; fi)>8000</option>
                                           <option value="16000" $(if [ "$samplerate" == "16000" ]; then echo selected; fi)>16000</option>
                                           <option value="24000" $(if [ "$samplerate" == "24000" ]; then echo selected; fi)>24000</option>
                                           <option value="32000" $(if [ "$samplerate" == "32000" ]; then echo selected; fi)>32000</option>
                                    </select>
                                </div>
                        </div>
                    </div>

                    <div class="field is-horizontal">
                        <div class="field-label is-normal">
                            <label class="label">Mic sensitivity</label>
                        </div>
                        <div class="field-body">
                            <p class="control">
                                <div class="double">
                                    <input class="slider is-fullwidth" name="audioinVol" step="1" min="0" max="12" value="$volume" type="range">
                                </div>
                            </p>
                        </div>
                    </div>

<!-- RTSP MAIN STREAM -->
                    <div class="is-divider" data-content="Main stream"></div>

                    <div class="field is-horizontal">
                        <div class="field-label is-normal">
                            <label class="label">Audio codec</label>
                        </div>

                        <div class="field-body">
                            <div class="select is-fullwidth">
                                <select name="audioCodec0">
                                        0    AK_AUDIO_TYPE_UNKNOWN,
                                        4    AK_AUDIO_TYPE_AAC,
                                        6    AK_AUDIO_TYPE_PCM,
                                       17    AK_AUDIO_TYPE_PCM_ALAW,
                                       18    AK_AUDIO_TYPE_PCM_ULAW,

                                        <option value="0"  $(if [ "$codec2" == "0" ]; then echo selected; fi)>OFF</option>
                                        <option value="4"  $(if [ "$codec2" == "4" ]; then echo selected; fi)>AAC</option>
                                        <option value="6"  $(if [ "$codec2" == "6" ]; then echo selected; fi)>PCM</option>
                                        <option value="17" $(if [ "$codec2" == "17" ]; then echo selected; fi)>ALAW</option>
                                        <option value="18" $(if [ "$codec2" == "18" ]; then echo selected; fi)>ULAW</option>
                                </select>
                            </div>
                        </div>
                    </div>
                    
    <!-- RTSP SUB STREAM -->
                    <div class="is-divider" data-content="Sub stream"></div>

                    <div class="field is-horizontal">
                        <div class="field-label is-normal">
                            <label class="label">Audio codec</label>
                        </div>

                        <div class="field-body">
                            <div class="select is-fullwidth">
                                <select name="audioCodec1">
                                        <option value="0"  $(if [ "$codec3" == "0" ]; then echo selected; fi)>OFF</option>
                                        <option value="4"  $(if [ "$codec3" == "4" ]; then echo selected; fi)>AAC</option>
                                        <option value="6"  $(if [ "$codec3" == "6" ]; then echo selected; fi)>PCM</option>
                                        <option value="17" $(if [ "$codec3" == "17" ]; then echo selected; fi)>ALAW</option>
                                        <option value="18" $(if [ "$codec3" == "18" ]; then echo selected; fi)>ULAW</option>
                                </select>
                            </div>
                        </div>
                    </div>
            
             <div class="field is-horizontal">
                <div class="field-label is-normal">
                </div>
                <div class="field-body">
                    <div class="field">
                    <div class="control">
                        <input id="audioinSubmit" class="button is-primary" type="submit" value="Set" />
                    </div>
                    </div>
                </div>
            </div>
        </form>
    </div>
</div>

<!-- RTSP/Misc -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>RTSP/Misc</p>
    </header>
    <div class='card-content'>

        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Image flip</label>
            </div>
            <div class="field-body">
                <div class="select is-fullwidth">
                    <select name="imageFlip" id="imageFlip">
                        <option value="0"  $(if [ "$imageflip" == "0" ]; then echo selected; fi)>Disabled</option>
                        <option value="1"  $(if [ "$imageflip" == "1" ]; then echo selected; fi)>Flip</option>
                        <option value="2"  $(if [ "$imageflip" == "2" ]; then echo selected; fi)>Mirror</option>
                        <option value="3"  $(if [ "$imageflip" == "3" ]; then echo selected; fi)>Flip and Mirror</option>
                    </select>
                </div>
            </div>
        </div>

        <div class="field is-horizontal">
            <div class="field-label is-normal"></div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="switch" name="enable_rtsp_log" id="enable_rtsp_log" type="checkbox"
                                    $(if [ "$RTSPLOGENABLED" -ne 0 > /dev/null 2>&1 ]; then echo "checked"; fi)>
                                    <label class="label" for="enable_rtsp_log">Enable RTSP server log</label>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- H264 RTSP -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>RTSP stream address</p></header>
    <div class='card-content'>
EOF

PATH="/bin:/sbin:/usr/bin:/media/mmcblk0p2/data/bin:/media/mmcblk0p2/data/sbin:/media/mmcblk0p2/data/usr/bin"

IP="$CAMERA_IP"
echo "<p>Path to main feed : <a href='rtsp://$IP:$RTSP_PORT/video0_unicast'>rtsp://$IP:$RTSP_PORT/video0_unicast</a></p>"
if [ "$RTSP_SUBSTREAM" = "1" ]; then
echo "<p>Path to sub feed : <a href='rtsp://$IP:$RTSP_PORT/video1_unicast'>rtsp://$IP:$RTSP_PORT/video1_unicast</a></p>"
else
echo "<p>Substream is disabled by current stream topology/profile.</p>"
echo "<p>Main-only fallback path (firmware dependent): <a href='rtsp://$IP:$RTSP_PORT/unicast'>rtsp://$IP:$RTSP_PORT/unicast</a></p>"
fi
cat << EOF
    </div>
</div>

<!-- Recording -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Recording</p>
    <p class="help">MKV video files saved in DCIM folder on microSD card</p>
    </header>
    <div class='card-content'>
    <form id="formRecording" action="cgi-bin/action.cgi?cmd=conf_recording" method="post">

        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Postrecord</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <p class="control">
                        <input class="input" id="postrec" name="postrec" type="number" size="2" min="0" max="60" value="$rec_postrecord_sec"/>
                    </p>
                    <p class="help">seconds, after motion is ended</p>
                </div>
            </div>
        </div>

        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Max file duration</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <p class="control">
                        <input class="input" id="maxduration" name="maxduration" type="number" size="3" min="10" max="600" value="$rec_file_duration_sec"/>
                    </p>
                    <p class="help">seconds</p>
                </div>
            </div>
        </div>

        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Reserved free disk space</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <p class="control">
                        <input class="input" id="diskspace" name="diskspace" type="number" size="10" min="0" value="$rec_reserverd_disk_mb"/>
                    </p>
                    <p class="help">megabytes, can be zero to disable removal of old files</p>
                </div>
            </div>
        </div>

        <div class="field is-horizontal">
            <div class="field-label is-normal"></div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="switch" name="motion_act" id="motion_act" type="checkbox"
                                    $(if [ $rec_motion_activated -eq 1 ]; then echo "checked"; fi)>
                                    <label class="label" for="motion_act">Record only when motion detected</label>
                    </div>
                </div>
            </div>
        </div>

        <div class="field is-horizontal">
            <div class="field-label is-normal">
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input id="recSubmit" class="button is-primary" type="submit" value="Set" />
                </div>
                </div>
            </div>
        </div>
        </form>
    </div>
</div>


<!-- Timelapse -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Timelapse</p></header>
    <div class='card-content'>
        <form id="formTimelapse" action="cgi-bin/action.cgi?cmd=conf_timelapse" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Interval</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="tlinterval" name="tlinterval" type="text" size="5" value="$TIMELAPSE_INTERVAL"/> seconds
                    </div>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Duration</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="tlduration" name="tlduration" type="text" size="5" value="$TIMELAPSE_DURATION"/> minutes
                    </div>
                    <p class="help">Set to 0 for unlimited</p>
                </div>
            </div>
        </div>
        <div class="field is-horizontal">
            <div class="field-label is-normal">
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input id="tlSubmit" class="button is-primary" type="submit" value="Set" />
                </div>
                </div>
            </div>
        </div>
        </form>
    </div>
</div>


<!-- Day/Night detection -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Day/Night auto detection</p></header>

    <div class='card-content'>
        <form id="formDayNight" action="cgi-bin/action.cgi?cmd=conf_autodaynight" method="post">

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Night-to-Day AWB</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                                 <input class="input is-fullwidth" id="ndawb" name="ndawb" type="number" size="4" value="$nightdayawb"/>
                                 <label class="labelAWB"></label>
                        </p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Night-to-Day Lum</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                                 <input class="input is-fullwidth" id="ndlum" name="ndlum" type="number" size="4" value="$nightdaylum"/>
                                 <label class="labelLum"></label>
                        </p>
                    </div>
                </div>
            </div>

            <br>
            When current AWB > 'Night-to-Day AWB' and current Lum < 'Night-to-Day Lum' then switch to DAY mode.

            <div class="is-divider"></div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Day-to-Night AWB</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                                 <input class="input is-fullwidth" id="dnawb" name="dnawb" type="number" size="4" value="$daynightawb"/>
                                 <label class="labelAWB"></label>
                        </p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Day-to-Night Lum</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                                 <input class="input is-fullwidth" id="dnlum" name="dnlum" type="number" size="4" value="$daynightlum"/>
                                 <label class="labelLum"></label>
                        </p>
                    </div>
                </div>
            </div>
            <br>
            When current AWB < 'Day-to-Night AWB' and current Lum > 'Day-to-Night Lum' then switch to NIGHT mode.
            <div class="is-divider"></div>


            <div class="field is-horizontal">
                <div class="field-label is-normal">
                </div>
                <div class="field-body">
                    <div class="field">
                    <div class="control">
                        <input id="autodaynightSubmit" class="button is-primary" type="submit" value="Set" />
                    </div>
                    </div>
                </div>
            </div>
        </form>
    </div>
</div>


<!-- ISP Pro Mode & Advanced OSD -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>ISP Pro Mode & OSD</p></header>
    <div class='card-content'>
        <form id="formISPPro" action="cgi-bin/action.cgi?cmd=isp_pro" method="post">
            <div class="is-divider" data-content="Day / Night Switching Thresholds"></div>
            <p class="help mb-3">Fine-tune when the camera switches between day and night modes based on light levels (Luminance) and White Balance (AWB).</p>
            
            <div class="field is-horizontal">
                <div class="field-label is-normal"><label class="label">Day &rarr; Night</label></div>
                <div class="field-body">
                    <div class="field">
                        <div class="control"><input class="input" name="daynightlum" type="number" value="$daynightlum" min="0" max="20000"></div>
                        <p class="help">Luminance (Lower = Darker). Current: <span class="labelLum">...</span></p>
                    </div>
                    <div class="field">
                        <div class="control"><input class="input" name="daynightawb" type="number" value="$daynightawb" min="0" max="500000"></div>
                        <p class="help">AWB Threshold. Current: <span class="labelAWB">...</span></p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal"><label class="label">Night &rarr; Day</label></div>
                <div class="field-body">
                    <div class="field">
                        <div class="control"><input class="input" name="nightdaylum" type="number" value="$nightdaylum" min="0" max="20000"></div>
                        <p class="help">Luminance (Higher = Brighter). Current: <span class="labelLum">...</span></p>
                    </div>
                    <div class="field">
                        <div class="control"><input class="input" name="nightdayawb" type="number" value="$nightdayawb" min="0" max="500000"></div>
                        <p class="help">AWB Threshold. Current: <span class="labelAWB">...</span></p>
                    </div>
                </div>
            </div>

            <div class="is-divider" data-content="Advanced OSD Styling"></div>
            
            <div class="field is-horizontal">
                <div class="field-label is-normal"><label class="label">Display</label></div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="switch" id="osdenabled" name="osdenabled" type="checkbox" value="1" $(if [ "$osdenabled" = "1" ]; then echo "checked"; fi)>
                            <label class="label" for="osdenabled">Show OSD Text</label>
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" name="osdtext" type="text" value="$osdtext" placeholder="%H:%M:%S %d.%m.%Y">
                        </div>
                        <p class="help">Text or strftime variables.</p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal"><label class="label">Colors</label></div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="frontcolor">
                                    <option value="0" $(if [ "$osdfrontcolor" = "0" ]; then echo selected; fi)>Black</option>
                                    <option value="1" $(if [ "$osdfrontcolor" = "1" ]; then echo selected; fi)>White</option>
                                    <option value="2" $(if [ "$osdfrontcolor" = "2" ]; then echo selected; fi)>Red</option>
                                    <option value="3" $(if [ "$osdfrontcolor" = "3" ]; then echo selected; fi)>Green</option>
                                    <option value="4" $(if [ "$osdfrontcolor" = "4" ]; then echo selected; fi)>Blue</option>
                                    <option value="5" $(if [ "$osdfrontcolor" = "5" ]; then echo selected; fi)>Cyan</option>
                                    <option value="6" $(if [ "$osdfrontcolor" = "6" ]; then echo selected; fi)>Yellow</option>
                                </select>
                            </div>
                        </div>
                        <p class="help">Foreground</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="backcolor">
                                    <option value="0" $(if [ "$osdbackcolor" = "0" ]; then echo selected; fi)>Transparent</option>
                                    <option value="1" $(if [ "$osdbackcolor" = "1" ]; then echo selected; fi)>Black</option>
                                    <option value="2" $(if [ "$osdbackcolor" = "2" ]; then echo selected; fi)>White</option>
                                </select>
                            </div>
                        </div>
                        <p class="help">Background</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="edgecolor">
                                    <option value="0" $(if [ "$osdedgecolor" = "0" ]; then echo selected; fi)>None</option>
                                    <option value="1" $(if [ "$osdedgecolor" = "1" ]; then echo selected; fi)>White</option>
                                    <option value="2" $(if [ "$osdedgecolor" = "2" ]; then echo selected; fi)>Black</option>
                                </select>
                            </div>
                        </div>
                        <p class="help">Edge / Shadow</p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal"><label class="label">Layout</label></div>
                <div class="field-body">
                    <div class="field">
                        <div class="control"><input class="input" name="osdalpha" type="number" value="$osdalpha" min="0" max="255"></div>
                        <p class="help">Alpha (0-255)</p>
                    </div>
                    <div class="field">
                        <div class="control"><input class="input" name="osdfontsize0" type="number" value="$osdfontsize0" min="8" max="128"></div>
                        <p class="help">Size (Main)</p>
                    </div>
                    <div class="field">
                        <div class="control"><input class="input" name="osdx0" type="number" value="$osdx0"></div>
                        <p class="help">X (Main)</p>
                    </div>
                    <div class="field">
                        <div class="control"><input class="input" name="osdy0" type="number" value="$osdy0"></div>
                        <p class="help">Y (Main)</p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal"></div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <button id="ispSubmit" class="button is-primary" type="submit">Apply ISP & OSD Settings</button>
                        </div>
                    </div>
                </div>
            </div>
        </form>
    </div>
</div>

<!-- Sound Detection -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Sound Detection (Beta)</p></header>
    <div class='card-content'>
        <form id="formSoundDetection" action="cgi-bin/action.cgi?cmd=conf_sounddetect" method="post">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Detection</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="switch" id="sound_det_enable" name="sound_det_enable" type="checkbox" value="1" $(if [ "$SOUND_DET_ENABLE" = "1" ]; then echo "checked"; fi)>
                            <label class="label" for="sound_det_enable">Enable Sound-Triggered Events</label>
                        </div>
                    </div>
                    <div class="field">
                        <div class="control">
                            <input class="input" id="sound_det_threshold" name="sound_det_threshold" type="number" value="$SOUND_DET_THRESHOLD" min="100" max="10000">
                        </div>
                        <p class="help">Sensitivity Threshold (Lower = More Sensitive)</p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Cooldown</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="sound_det_interval" name="sound_det_interval" type="number" value="$SOUND_DET_INTERVAL" min="1" max="300">
                        </div>
                        <p class="help">Seconds between triggers</p>
                    </div>
                    <div class="field">
                        <div class="control">
                            <button id="soundSubmit" class="button is-primary" type="submit">Set Sound Detection</button>
                        </div>
                    </div>
                </div>
            </div>
        </form>
        <p class="help mt-3">Triggered events will publish to MQTT as <code>&lt;root&gt;/sound</code> and start a recording if enabled.</p>
    </div>
</div>


<!-- Motion detection -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Motion Detection</p></header>
    <div class='card-content'>
        <form id="formMotionDetection" action="cgi-bin/action.cgi?cmd=conf_motiondetect" method="post">
        <div class="field is-horizontal">
            <div class="field-label is-normal">
                <label class="label">Sensitivity</label>
            </div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="input" id="mdsens" name="mdsens" type="number" size="3" min="1" max="100" value="$mdsens"/>
                    </div>
                </div>
            </div>
        </div>

        <div class="field is-horizontal">
            <div class="field-label is-normal"></div>
            <div class="field-body">
                <div class="field">
                    <div class="control">
                        <input class="switch" name="motionBlink" id="motionBlink" type="checkbox" $(if [ "$motion_trigger_led" == "true" ]; then echo "checked"; fi) >
                         <label class="label" for="motionBlink">Blink red led when motion detected</label>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="field is-horizontal">
            <div class="field-label is-normal">
            </div>
            <div class="field-body">
                <div class="field">
                <div class="control">
                    <input id="mdsensSubmit" class="button is-primary" type="submit" value="Set" />
                </div>
                </div>
            </div>
        </div>
        </form>
    </div>
</div>

<!-- Config backup and health snapshot -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Config Backup & Health</p></header>
    <div class='card-content'>
        <p class="help">On-demand tools only. No background daemon or polling is added.</p>
        <div class="buttons">
            <a class="button is-link" href="cgi-bin/configbackup.cgi?cmd=download" target="_blank" rel="noopener">Download config backup</a>
            <a class="button is-light" href="cgi-bin/state.cgi?cmd=healthsnapshot" target="_blank" rel="noopener">Open health snapshot (JSON)</a>
        </div>

        <form id="formConfigRestore" action="cgi-bin/configbackup.cgi?cmd=restore" method="post" target="_blank">
            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label" for="archive_path">Restore archive path</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="input" id="archive_path" name="archive_path" type="text" value="/tmp/config-backup.tar.gz" />
                        </div>
                        <p class="help">Upload a backup archive to /tmp first (FTP/SCP), then restore here.</p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal"></div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <input class="switch" name="restart_services" id="restart_services" type="checkbox" value="1" checked />
                            <label class="label" for="restart_services">Restart RTSP/ONVIF after restore</label>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal"></div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <button class="button is-primary" type="submit">Restore config archive</button>
                        </div>
                    </div>
                </div>
            </div>
        </form>
    </div>
</div>

<!-- Audio / Image -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>Tests</p></header>
    <div class='card-content'>

        <div class="columns">
        <div class="column">
            <label>Image</label>
            <div class="buttons">
                <a class="button is-link" href='cgi-bin/currentpic.cgi' target='_blank'>Get</a>
            </div>
        </div>

        </div>
    </div>
</div>

EOF
# Prefer external bundled/minified script to reduce server CPU and allow client caching
if [ -f /mnt/www/scripts/status.bundle.min.js ]; then
  echo "<script src=\"/scripts/status.bundle.min.js\"></script>"
else
  echo "<script src=\"/scripts/status.cgi.js\"></script>"
fi
