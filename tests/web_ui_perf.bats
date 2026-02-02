#!/usr/bin/env bats

@test "status.js includes scheduleStatusReload function" {
  run grep -n "function scheduleStatusReload" www/scripts/status.cgi.js
  [ "$status" -eq 0 ]
}

@test "status.js uses scheduleStatusReload in forms" {
  run grep -n "scheduleStatusReload(5000)" www/scripts/status.cgi.js
  [ "$status" -eq 0 ]
}

@test "lighttpd.conf contains security headers" {
  run grep -n "X-Content-Type-Options" config/lighttpd.conf.dist
  [ "$status" -eq 0 ]
  run grep -n "Content-Security-Policy" config/lighttpd.conf.dist
  [ "$status" -eq 0 ]
}

@test "lighttpd.conf sets cache control for static assets" {
  run grep -n "Cache-Control" config/lighttpd.conf.dist
  [ "$status" -eq 0 ]
}
