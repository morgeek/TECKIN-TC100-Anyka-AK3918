#!/usr/bin/env bats

@test "index.html references index bundle" {
  run grep -n "index.bundle.min.js" www/index.html
  [ "$status" -eq 0 ]
}

@test "index bundle defines scheduleRefreshLiveImage" {
  run grep -n "scheduleRefreshLiveImage" www/scripts/index.bundle.min.js
  [ "$status" -eq 0 ]
}
