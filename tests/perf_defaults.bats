#!/usr/bin/env bats

@test "detection monitor default interval is 6" {
  run grep -n 'MONITOR_TIMEOUT_SECONDS' scripts/detection-monitor.sh
  [ "$status" -eq 0 ]
  echo "$output" | grep -q '\${MONITOR_TIMEOUT_SECONDS:-6}'
}

@test "service watchdog check timeout default is 60" {
  run grep -n 'CHECK_TIMEOUT_SECONDS' scripts/service-watchdog.sh
  [ "$status" -eq 0 ]
  echo "$output" | grep -q '\${CHECK_TIMEOUT_SECONDS:-60}'
}

@test "netmon default ping interval is 120" {
  run grep -n '^PINGINTERVAL=' config/netmon.conf.dist
  [ "$status" -eq 0 ]
  echo "$output" | grep -q 'PINGINTERVAL=120'
}

@test "action supports stream topology cpu saver command" {
  run grep -n 'set_stream_topology)' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n 'rewrite_config /mnt/config/boot.conf RTSP_SUBSTREAM' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n 'rewrite_config /mnt/config/boot.conf RTSP_AUDIO' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]
}

@test "action validates telnet and ftp ports" {
  run grep -n "Invalid telnet port. Allowed range is 1-65535." www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n '\"\\$telnetport\" -lt 1' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n "Invalid ftp port. Allowed range is 1-65535." www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n '\"\\$ftpport\" -lt 1' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]
}

@test "rewrite_config handles key/value updates safely" {
  run grep -n 'case \"\\$cfg_key\"' scripts/common_functions.sh
  [ "$status" -eq 0 ]

  run grep -n "esc_value=.*sed 's/\\[" scripts/common_functions.sh
  [ "$status" -eq 0 ]

  run grep -nF "printf '%s=%s\\n'" scripts/common_functions.sh
  [ "$status" -eq 0 ]
}

@test "action supports ONVIF stream policy command" {
  run grep -n 'set_onvif_stream_policy)' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n 'rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]
}

@test "action no longer exposes ONVIF/RTSP self-test command" {
  run grep -n 'run_stream_self_test)' www/cgi-bin/action.cgi
  [ "$status" -ne 0 ]

  run grep -n 'apply_stream_safe_fallback_profile' www/cgi-bin/action.cgi
  [ "$status" -ne 0 ]

  run grep -n 'RTSP_SUBSTREAM 0' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n 'ONVIF_STREAM_POLICY main-only' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]
}

@test "status page exposes stream topology form" {
  run grep -n 'formStreamTopology' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n 'name=\"stream_topology\"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]
}

@test "status page exposes ONVIF stream policy form" {
  run grep -n 'formOnvifPolicy' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n 'name=\"onvif_stream_policy\"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]
}

@test "status page no longer exposes stream self-test form" {
  run grep -n 'formStreamSelfTest' www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]

  run grep -n 'name=\"auto_fallback\"' www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]
}

@test "status page no longer embeds services/camera controls/information panels" {
  run grep -n 'id="embeddedServices"' www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]

  run grep -n 'id="embeddedCamControls"' www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]

  run grep -n 'id="embeddedSysUsageInfo"' www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]

  run grep -n 'id="embeddedLogs"' www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]
}

@test "status bundle binds stream topology form" {
  run grep -n "formStreamTopology" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "formOnvifPolicy" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "formStreamSelfTest" www/scripts/status.bundle.min.js
  [ "$status" -ne 0 ]
}

@test "status bundle loads embedded settings panels" {
  run grep -n "initEmbeddedSettingsPanels" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "embeddedSysUsageInfo" www/scripts/status.bundle.min.js
  [ "$status" -ne 0 ]

  run grep -n "embeddedServices" www/scripts/status.bundle.min.js
  [ "$status" -ne 0 ]
}

@test "state endpoint stays lightweight and avoids heavy helper sourcing" {
  run grep -n 'source /mnt/scripts/common_functions.sh' www/cgi-bin/state.cgi
  [ "$status" -ne 0 ]

  run grep -n 'get_current_cpu_usage_fast' www/cgi-bin/state.cgi
  [ "$status" -eq 0 ]

  run grep -n 'get_memory_usage_fast' www/cgi-bin/state.cgi
  [ "$status" -eq 0 ]
}

@test "state endpoint supports legacy kernel memory fallback without MemAvailable" {
  run grep -n 'MemFree:' www/cgi-bin/state.cgi
  [ "$status" -eq 0 ]

  run grep -n 'SReclaimable:' www/cgi-bin/state.cgi
  [ "$status" -eq 0 ]

  run grep -n 'mem_available=$((mem_free + mem_buffers + mem_cached + mem_sreclaimable - mem_shmem))' www/cgi-bin/state.cgi
  [ "$status" -eq 0 ]
}

@test "index bundle adapts polling cadence for low-cpu profiles" {
  run grep -n "tuneUiPollIntervals" www/scripts/index.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "currentPerfProfileToken" www/scripts/index.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "osd action handles unchecked checkbox safely" {
  run grep -n 'osd_enabled=' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n 'osdenabled \"\\$osd_enabled\"' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n '\${F_osdtext//%/\\\\x}' www/cgi-bin/action.cgi
  [ "$status" -ne 0 ]
}

@test "boot config exposes low-ram memory guard defaults" {
  run grep -n '^LOW_RAM_PROFILE=0' config/boot.conf.dist
  [ "$status" -eq 0 ]

  run grep -n '^MEM_GUARD_ENABLE=0' config/boot.conf.dist
  [ "$status" -eq 0 ]

  run grep -n '^MEM_GUARD_WARN_KB=' config/boot.conf.dist
  [ "$status" -eq 0 ]
}

@test "performance profile wiring toggles memory guard settings" {
  run grep -n 'LOW_RAM_PROFILE 1' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n 'MEM_GUARD_ENABLE 1' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n 'MEM_GUARD_ENABLE 0' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]
}

@test "sysusage endpoint avoids heavy mpstat top and lsof calls" {
  run grep -n 'mpstat -A' www/cgi-bin/sysusageinfo.cgi
  [ "$status" -ne 0 ]

  run grep -n 'top -n 1' www/cgi-bin/sysusageinfo.cgi
  [ "$status" -ne 0 ]

  run grep -n 'busybox lsof' www/cgi-bin/sysusageinfo.cgi
  [ "$status" -ne 0 ]

  run grep -n '/proc/meminfo' www/cgi-bin/sysusageinfo.cgi
  [ "$status" -eq 0 ]
}

@test "memory guard service is available in controlscripts and autostart" {
  run test -f controlscripts/memory-guard
  [ "$status" -eq 0 ]

  run grep -n '/mnt/controlscripts/memory-guard' config/autostart/memory-guard
  [ "$status" -eq 0 ]
}

@test "memory guard uses MemAvailable fallback metrics" {
  run grep -n '^mem_available_kb()' controlscripts/memory-guard
  [ "$status" -eq 0 ]

  run grep -n 'MemFree:' controlscripts/memory-guard
  [ "$status" -eq 0 ]

  run grep -n 'fallback = mem_free + mem_buffers + mem_cached + mem_sreclaimable - mem_shmem' controlscripts/memory-guard
  [ "$status" -eq 0 ]
}
