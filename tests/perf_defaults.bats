#!/usr/bin/env bats

@test "detection monitor default interval is 3" {
  run grep -n 'MONITOR_TIMEOUT_SECONDS' scripts/detection-monitor.sh
  [ "$status" -eq 0 ]
  echo "$output" | grep -q '\${MONITOR_TIMEOUT_SECONDS:-3}'
}

@test "service watchdog check timeout default is 30" {
  run grep -n 'CHECK_TIMEOUT_SECONDS' scripts/service-watchdog.sh
  [ "$status" -eq 0 ]
  echo "$output" | grep -q '\${CHECK_TIMEOUT_SECONDS:-30}'
}

@test "netmon default ping interval is 60" {
  run grep -n '^PINGINTERVAL=' config/netmon.conf.dist
  [ "$status" -eq 0 ]
  echo "$output" | grep -q 'PINGINTERVAL=60'
}
