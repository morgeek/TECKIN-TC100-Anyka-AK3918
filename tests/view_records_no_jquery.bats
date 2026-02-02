#!/usr/bin/env bats
# Ensure view_records.html no longer uses jQuery selectors

@test "view_records.html has no jQuery dollar usage" {
  run grep -n "\$\(" www/view_records.html || true
  [ "$status" -ne 0 ]
}
