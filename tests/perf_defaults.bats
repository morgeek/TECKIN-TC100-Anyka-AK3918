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

@test "action supports ONVIF stream policy command" {
  run grep -n 'set_onvif_stream_policy)' www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n 'rewrite_config /mnt/config/boot.conf ONVIF_STREAM_POLICY' www/cgi-bin/action.cgi
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

@test "status page embeds services and camera controls panels" {
  run grep -n 'id="embeddedServices"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n 'id="embeddedCamControls"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]
}

@test "status page embeds information panels" {
  run grep -n 'id="embeddedSysUsageInfo"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n 'id="embeddedDeviceInfo"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n 'id="embeddedNetworkInfo"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n 'id="embeddedDiskInfo"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n 'id="embeddedLogs"' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]
}

@test "status bundle binds stream topology form" {
  run grep -n "formStreamTopology" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "formOnvifPolicy" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "status bundle loads embedded settings panels" {
  run grep -n "initEmbeddedSettingsPanels" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "embeddedSysUsageInfo" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "embeddedLogs" www/scripts/status.bundle.min.js
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
