#!/usr/bin/env bats

setup() {
  rm -f /tmp/EXPLOIT
  rm -f tests/tmp_webcontrols.conf
}

@test "camcontrols writes safe config (no command execution when sourced)" {
  # simulate malicious controls value that tries to break out of quotes and run commands
  raw='A"; touch /tmp/EXPLOIT; #'
  # URL-encode the payload
  payload=$(printf '%s' "$raw" | od -An -t x1 | tr -s ' ' | sed 's/ /%/g' | tr '[:lower:]' '[:upper:]')
  # Build query string
  QUERY_STRING="controls=${payload}&cmd=setsettings"

  # Parse into F_* variables using our safe func.cgi
  unset REQUEST_METHOD
  . ./www/cgi-bin/func.cgi

  # Run camcontrols.cgi, overriding the config path to a test file
  ENABLED_CONTROLS_CONFIG="tests/tmp_webcontrols.conf" ./www/cgi-bin/camcontrols.cgi

  # Now source the created config file - if it's unsafe it would execute touch /tmp/EXPLOIT
  [ ! -f /tmp/EXPLOIT ]

  # The variable should be present and equal to the original raw value
  . tests/tmp_webcontrols.conf
  [ "${ENABLED_CAM_CONTROL_SWITCHES}" = "$raw" ]
}
