#!/usr/bin/env bats
# Ensure index.html no longer includes global jQuery or legacy index fallback

@test "index.html does not include jquery" {
  run grep -n "jquery-3.3.1.min.js" www/index.html || true
  [ "$status" -ne 0 ]
}

@test "index.html does not include legacy index.html.js fallback" {
  run grep -n "index.html.js" www/index.html || true
  [ "$status" -ne 0 ]
}
