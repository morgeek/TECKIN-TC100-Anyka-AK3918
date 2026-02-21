#!/bin/sh

echo "Content-type: text/html"
echo "Pragma: no-cache"
echo "Cache-Control: max-age=0, no-store, no-cache"
echo ""

. /mnt/scripts/common_functions.sh
install_config /mnt/config/recording.conf
install_config /mnt/config/boot.conf
install_config /mnt/config/service_trim.conf

# shellcheck disable=SC1090
if [ -f /mnt/config/boot.conf ]; then
  . /mnt/config/boot.conf
fi
# shellcheck disable=SC1090
if [ -f /mnt/config/service_trim.conf ]; then
  . /mnt/config/service_trim.conf
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
ENABLE_NTP="${ENABLE_NTP:-1}"
NTP_ONE_SHOT="${NTP_ONE_SHOT:-0}"
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
for flag_name in LIGHTWEIGHT_MODE UI_ULTRALITE_MODE ENABLE_NTP NTP_ONE_SHOT MEM_GUARD_ENABLE MEM_GUARD_DROP_CACHES
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

cat << EOF
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
                    <p class="help">Applies grouped CPU-saving settings. Reboot recommended for full profile effect.</p>
                </div>
                <div class="field">
                    <div class="control">
                        <button id="performanceProfileSubmit" class="button is-primary" type="submit">Apply</button>
                    </div>
                </div>
            </div>
        </div>
    </form>
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
            <p class="help">Reboot recommended after changing boot modes (Lightweight/NTP) for full effect.</p>
        </form>
    </div>
</div>

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
                                    <option value="1024x576"  $(if [ "$width0" == "960" ];  then echo selected; fi) >1024x576</option>
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

IP=$(ifconfig wlan0 |grep "inet addr" |awk '{print $2}' |awk -F: '{print $2}')
echo "<p>Path to main feed : <a href='rtsp://$IP:$RTSP_PORT/video0_unicast'>rtsp://$IP:$RTSP_PORT/video0_unicast</a></p>"
echo "<p>Path to sub feed : <a href='rtsp://$IP:$RTSP_PORT/video1_unicast'>rtsp://$IP:$RTSP_PORT/video1_unicast</a></p>"
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


<!-- OSD -->
<div class='card status_card'>
    <header class='card-header'><p class='card-header-title'>OSD Display</p></header>
    <div class='card-content'>
        <form id="formOSD" action="cgi-bin/action.cgi?cmd=osd" method="post">

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Enable Text</label>
                </div>
                <div class="field-body">
                    <div class="field is-grouped">
                        <p class="control">
                            <input type="checkbox" name="OSDenable" value="enabled" $(if [ "$osdenabled" == "1" ]; then echo checked; fi) />
                        </p>
                        <p class="control">
                            <input class="input is-fullwidth" id="osdtext" name="osdtext" type="text" size="25" value="$(read_config rtspserver.conf osdtext)"/>
                            <span class="help">
                                Enter time-variables in <a href="http://strftime.org/" target="_blank">strftime</a> format
                            </span>
                        </p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">OSD Front Color</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="frontcolor">
                                <option value="1" $(if [ $osdfrontcolor -eq 1 ]; then echo selected; fi)>White</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">OSD Back Color</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="backcolor">
                                <option value="0" $(if [ $osdbackcolor -eq 0 ]; then echo selected; fi)>Transparent</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">OSD Edge Color</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <div class="control">
                            <div class="select is-fullwidth">
                                <select name="edgecolor">
                                <option value="2" $(if [ $osdedgecolor -eq 2 ]; then echo selected; fi)>Black</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">OSD Transparency</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                                 <input class="input is-fullwidth" id="OSDAlpha" name="OSDAlpha" type="number" size="4" value="$osdalpha"/>
                        </p>
                    </div>
                </div>
            </div>

            <div class="is-divider" data-content="Main stream"></div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">OSD Text Size</label>
                </div>
                <div class="field-body">
                    <div class="select is-fullwidth">
                        <select name="OSDSize0">
                            <option value="16"  $(if [ "$osdfontsize0" == "16" ]; then echo selected; fi)>16</option>
                            <option value="32"  $(if [ "$osdfontsize0" == "32" ]; then echo selected; fi)>32</option>
                            <option value="48"  $(if [ "$osdfontsize0" == "48" ]; then echo selected; fi)>48</option>
                            <option value="64"  $(if [ "$osdfontsize0" == "64" ]; then echo selected; fi)>64</option>
                            <option value="96"  $(if [ "$osdfontsize0" == "96" ]; then echo selected; fi)>96</option>
                        </select>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">X Position</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                            <input class="input is-fullwidth" id="posx0" name="posx0" type="number" size="6" value="$osdx0"/>
                        </p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Y Position</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                            <input class="input is-fullwidth" id="posy0" name="posy0" type="number" size="6" value="$osdy0"/>
                        </p>
                    </div>
                </div>
            </div>

            <div class="is-divider" data-content="Sub stream"></div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">OSD Text Size</label>
                </div>
                <div class="field-body">
                    <div class="select is-fullwidth">
                        <select name="OSDSize1">
                            <option value="16"  $(if [ "$osdfontsize1" == "16" ]; then echo selected; fi)>16</option>
                            <option value="32"  $(if [ "$osdfontsize1" == "32" ]; then echo selected; fi)>32</option>
                            <option value="48"  $(if [ "$osdfontsize1" == "48" ]; then echo selected; fi)>48</option>
                            <option value="64"  $(if [ "$osdfontsize1" == "64" ]; then echo selected; fi)>64</option>
                            <option value="96"  $(if [ "$osdfontsize1" == "96" ]; then echo selected; fi)>96</option>
                        </select>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">X Position</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                            <input class="input is-fullwidth" id="posx1" name="posx1" type="number" size="6" value="$osdx1"/>
                        </p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                    <label class="label">Y Position</label>
                </div>
                <div class="field-body">
                    <div class="field">
                        <p class="control">
                            <input class="input is-fullwidth" id="posy1" name="posy1" type="number" size="6" value="$osdy1"/>
                        </p>
                    </div>
                </div>
            </div>

            <div class="field is-horizontal">
                <div class="field-label is-normal">
                </div>
                <div class="field-body">
                    <div class="field">
                    <div class="control">
                        <input id="osdSubmit" class="button is-primary" type="submit" value="Set" />
                    </div>
                    </div>
                </div>
            </div>
        </form>
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
