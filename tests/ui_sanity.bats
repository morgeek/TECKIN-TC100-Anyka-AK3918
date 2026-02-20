#!/usr/bin/env bats

@test "index footer markup does not contain stray closing anchor before sysusage" {
  run grep -n '</a><em id="sysusage"' www/index.html
  [ "$status" -ne 0 ]
}

@test "sysusage widget is rendered in main live view shell" {
  run grep -n '<div class="sysusage-wrap">' www/index.html
  [ "$status" -eq 0 ]

  run grep -n '<em id="sysusage">' www/index.html
  [ "$status" -eq 0 ]
}

@test "theme selector is not in footer anymore" {
  run grep -n '<span>Theme</span>' www/index.html
  [ "$status" -ne 0 ]
}

@test "information links are present in menu and route to settings sections" {
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

  run grep -n 'class="navbar-item onsettings"' www/index.html
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
