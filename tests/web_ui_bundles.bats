#!/usr/bin/env bats

@test "status.cgi references external bundle when present" {
  run ./www/cgi-bin/status.cgi
  [ "$status" -eq 0 ]
  echo "$output" | grep -q '<script src="/scripts/status.bundle.min.js"></script>'
}

@test "scripts.cgi references external bundle when present" {
  run ./www/cgi-bin/scripts.cgi
  [ "$status" -eq 0 ]
  echo "$output" | grep -q '<script src="/scripts/scripts.bundle.min.js"></script>'
}
