#!/usr/bin/env bats
# Ensure camcontrols CGI was updated to prefer external bundle

@test "camcontrols.cgi prefers bundle if present" {
  run grep -n "camcontrols.bundle.min.js" www/cgi-bin/camcontrols.cgi
  [ "$status" -eq 0 ]
}
