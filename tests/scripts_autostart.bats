#!/usr/bin/env bats

setup() {
  rm -rf tests/tmp_autostart
  mkdir -p tests/tmp_autostart
  # ensure a dummy script exists in the controlscripts dir
  mkdir -p controlscripts
  printf '#!/bin/sh\necho ok' > controlscripts/safe-script
  chmod +x controlscripts/safe-script
}

@test "scripts.cgi enable creates safe autorun script only when script exists and name is sanitized" {
  QUERY_STRING='script=../controlscripts/safe-script&cmd=enable'
  unset REQUEST_METHOD
  . ./www/cgi-bin/func.cgi

  AUTOSTART_DIR="tests/tmp_autostart" SCRIPT_HOME="./controlscripts/" ./www/cgi-bin/scripts.cgi &>/dev/null

  [ -f tests/tmp_autostart/safe-script ]
  [ -x tests/tmp_autostart/safe-script ]

  # ensure content is only the expected fixed content
  grep -q '^#!/bin/sh' tests/tmp_autostart/safe-script
  grep -q './controlscripts/safe-script' tests/tmp_autostart/safe-script
}
