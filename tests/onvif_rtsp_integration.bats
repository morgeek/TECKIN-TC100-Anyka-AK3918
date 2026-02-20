#!/usr/bin/env bats

@test "onvif script advertises second stream with vcb2/fps2" {
  run grep -n "vcb2 .*fps2" controlscripts/onvif
  [ "$status" -eq 0 ]
}

@test "onvif script derives web protocol from WEB_MODE" {
  run grep -n 'WEB_MODE="full"' controlscripts/onvif
  [ "$status" -eq 0 ]

  run grep -n 'WEB_PROTO="https"' controlscripts/onvif
  [ "$status" -eq 0 ]

  run grep -n 'if \[ "\$WEB_MODE" = "http" \]' controlscripts/onvif
  [ "$status" -eq 0 ]
}

@test "onvif script supports disabling substream advertisement" {
  run grep -n 'if \[ "\$RTSP_SUBSTREAM" = "1" \]' controlscripts/onvif
  [ "$status" -eq 0 ]

  run grep -n 'ONVIF_STREAM2_ARGS="-en2 0"' controlscripts/onvif
  [ "$status" -eq 0 ]
}

@test "onvif script supports stream policy engine" {
  run grep -n 'ONVIF_STREAM_POLICY' controlscripts/onvif
  [ "$status" -eq 0 ]

  run grep -n 'sub-primary' controlscripts/onvif
  [ "$status" -eq 0 ]

  run grep -n 'sub-only' controlscripts/onvif
  [ "$status" -eq 0 ]
}

@test "rtsp script exposes health probe and no-reboot watchdog mode" {
  run grep -n 'service-watchdog.sh /mnt/controlscripts/rtsp-h26x 0 health' controlscripts/rtsp-h26x
  [ "$status" -eq 0 ]

  run grep -n 'DESCRIBE' controlscripts/rtsp-h26x
  [ "$status" -eq 0 ]
}
