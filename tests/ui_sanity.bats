#!/usr/bin/env bats

@test "index footer markup does not contain stray closing anchor before sysusage" {
  run grep -n '</a><em id="sysusage"' www/index.html
  [ "$status" -ne 0 ]
}

@test "sysusage widget is rendered in fixed navbar shell" {
  run grep -n 'class="navbar-item nav-sysusage-wrap"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n '<em id="sysusage">' www/index.html
  [ "$status" -eq 0 ]
}

@test "performance profile badge is rendered in fixed navbar shell" {
  run grep -n 'class="navbar-item nav-perfprofile-wrap"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n '<em id="perfprofile">' www/index.html
  [ "$status" -eq 0 ]
}

@test "self-test badge is removed from fixed navbar shell" {
  run grep -n 'class="navbar-item nav-selftest-wrap"' www/index.html
  [ "$status" -ne 0 ]

  run grep -n '<em id="streamselftest">' www/index.html
  [ "$status" -ne 0 ]
}

@test "theme selector is not in footer anymore" {
  run grep -n '<span>Theme</span>' www/index.html
  [ "$status" -ne 0 ]
}

@test "index lazy-loads settings css extensions" {
  run grep -n "bulma-switch.1.0.1.min.css" www/index.html
  [ "$status" -ne 0 ]

  run grep -n "bulma-divider.min.css" www/index.html
  [ "$status" -ne 0 ]

  run grep -n "ensureSettingsStylesLoaded" www/scripts/index.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "settings/services/camera/info links are present in menu and route correctly" {
  run grep -n 'id="status".*data-target="cgi-bin/status.cgi".*data-force-reload="1"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="services".*data-target="cgi-bin/scripts.cgi"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="camfunctions".*data-target="cgi-bin/camcontrols.cgi?cmd=getsettings"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="sysusageinfo"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="network"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="disk"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="devinfo"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="logs"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="sysusageinfo".*data-target="cgi-bin/sysusageinfo.cgi"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="network".*data-target="cgi-bin/network.cgi"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="disk".*data-target="cgi-bin/disk.cgi"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="devinfo".*data-target="cgi-bin/devinfo.cgi"' www/index.html
  [ "$status" -eq 0 ]

  run grep -n 'id="logs".*data-target="logs.html"' www/index.html
  [ "$status" -eq 0 ]
}

@test "footer removed from index page" {
  run grep -n '<footer class="footer">' www/index.html
  [ "$status" -ne 0 ]
}

@test "services autostart switch uses change event and rollback on failure" {
  run grep -n "addEventListener('change'" www/scripts/scripts.cgi.js
  [ "$status" -eq 0 ]

  run grep -n "desiredState" www/scripts/scripts.cgi.js
  [ "$status" -eq 0 ]
}

@test "services page supports embedded refresh host" {
  run grep -n "embeddedServices" www/scripts/scripts.cgi.js
  [ "$status" -eq 0 ]
}

@test "services page uses one-row-per-service table layout with hover hints" {
  run grep -n "services-table" www/cgi-bin/scripts.cgi
  [ "$status" -eq 0 ]

  run grep -n "Service name and current runtime state" www/cgi-bin/scripts.cgi
  [ "$status" -eq 0 ]

  run grep -n "Start, stop, or run this service now" www/cgi-bin/scripts.cgi
  [ "$status" -eq 0 ]

  run grep -n "Enable or disable automatic startup when the camera boots" www/cgi-bin/scripts.cgi
  [ "$status" -eq 0 ]

  run grep -n "script_action_toggle" www/cgi-bin/scripts.cgi
  [ "$status" -eq 0 ]

  run grep -n "title='Enable or disable autorun for this service'" www/cgi-bin/scripts.cgi
  [ "$status" -eq 0 ]
}

@test "view records actions use semantic disabled buttons" {
  run grep -n '<button id="dwbtn"' www/view_records.html
  [ "$status" -eq 0 ]

  run grep -n '<button id="rmbtn"' www/view_records.html
  [ "$status" -eq 0 ]
}

@test "camera controls save button uses a stable id targeted by js" {
  run grep -n "saveCamControlsBtn" www/cgi-bin/camcontrols.cgi
  [ "$status" -eq 0 ]

  run grep -n "saveCamControlsBtn" www/scripts/camcontrols.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "status page supports compact basic/all settings view mode" {
  run grep -n "statusViewMode" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "status-collapsed" www/css/ui-modern.css
  [ "$status" -eq 0 ]
}

@test "status page has lightweight organizer with quick-nav and filter" {
  run grep -n "statusOrganizer" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "statusFilterInput" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "statusQuickNav" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "ui css stays in lightweight mode without blur/animation effects" {
  run grep -n "backdrop-filter" www/css/ui-modern.css
  [ "$status" -ne 0 ]

  run grep -n "@keyframes" www/css/ui-modern.css
  [ "$status" -ne 0 ]
}

@test "index bundle has no dead push-to-talk hooks" {
  run grep -n "pushToTalk" www/scripts/index.bundle.min.js
  [ "$status" -ne 0 ]

  run grep -n "btn-ptt" www/scripts/index.bundle.min.js
  [ "$status" -ne 0 ]
}

@test "index bundle has no dead direct navigation hooks" {
  run grep -n "\\.direct" www/scripts/index.bundle.min.js
  [ "$status" -ne 0 ]
}

@test "status template no longer carries large commented TODO feature blocks" {
  run grep -n "TODO: uncomment when implemented" www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]
}

@test "status template avoids invalid self-closing non-void tags" {
  run grep -nE '<(div|label)\\b[^>]*\\/>' www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]
}

@test "status bundle uses lazy embedded panel loading hooks" {
  run grep -n "data-panel-url" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "loadVisibleEmbeddedPanels" www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "system settings include performance profile form" {
  run grep -n 'id="formPerformanceProfile".*set_performance_profile' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n '"formPerformanceProfile"' www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "system settings include web mode form" {
  run grep -n 'id="formWebMode".*set_web_mode' www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]

  run grep -n '"formWebMode"' www/scripts/status.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "system settings no longer include stream self-test form" {
  run grep -n 'id="formStreamSelfTest".*run_stream_self_test' www/cgi-bin/status.cgi
  [ "$status" -ne 0 ]

  run grep -n '"formStreamSelfTest"' www/scripts/status.bundle.min.js
  [ "$status" -ne 0 ]
}

@test "action.cgi supports performance profile, web mode and debounced stream restarts" {
  run grep -n "set_performance_profile" www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n "set_web_mode" www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n "schedule_service_restart" www/cgi-bin/action.cgi
  [ "$status" -eq 0 ]

  run grep -n "run_stream_self_test" www/cgi-bin/action.cgi
  [ "$status" -ne 0 ]
}

@test "live preview uses adaptive cpu-aware throttling" {
  run grep -n "setAdaptiveLivePreviewProfile" www/scripts/index.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "currentpicoptim.cgi" www/scripts/index.bundle.min.js
  [ "$status" -eq 0 ]
}

@test "state.cgi exposes statusline command and index bundle polls it" {
  run grep -n "statusline)" www/cgi-bin/state.cgi
  [ "$status" -eq 0 ]

  run grep -n "streamselftest" www/cgi-bin/state.cgi
  [ "$status" -ne 0 ]

  run grep -n "cmd=statusline" www/scripts/index.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "cmd=perfprofile" www/scripts/index.bundle.min.js
  [ "$status" -eq 0 ]

  run grep -n "setStreamSelfTestBadge" www/scripts/index.bundle.min.js
  [ "$status" -ne 0 ]
}
