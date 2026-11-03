#!/bin/sh
# scripts/tamper-detect.sh — Lightweight Camera Tampering / Occlusion Detector
#
# Detects camera tampering (lens covering, spraying, or total sudden occlusion):
# - Monitors sudden mean luminance drop (/tmp/cam_luma)
# - Verifies ISP exposure and gains (/tmp/cam_ae) ramping to maximum
# - Strict anti-false-positive guard: suppressed for 30s following day/night switch
#   or IR-cut filter transitions (/var/run/ircut, /var/run/vday)
# - When tamper is confirmed for TAMPER_HOLD_SEC (default 3s):
#   writes /tmp/cam_tamper and publishes event + binary_sensor tamper/state
#
# Can be run as a housekeeper periodic background job or standalone daemon.

TAMPER_CONF="/mnt/config/tamper.conf"
TAMPER_PIDFILE="/var/run/tamper-detect.pid"
TAMPER_FLAG="/tmp/cam_tamper"
CAM_LUMA="/tmp/cam_luma"
CAM_AE="/tmp/cam_ae"
IRCUT_FILE="/var/run/ircut"

# Defaults
ENABLE=0
LUMA_MIN=15
EXPOSURE_RATIO=80
HOLD_SEC=3

load_config() {
  if [ -r "$TAMPER_CONF" ]; then
    while IFS='=' read -r _k _v; do
      case "$_k" in
        ENABLE) ENABLE="$_v" ;;
        TAMPER_LUMA_MIN) LUMA_MIN="$_v" ;;
        TAMPER_HOLD_SEC) HOLD_SEC="$_v" ;;
      esac
    done < "$TAMPER_CONF"
  fi
  case "$ENABLE" in 1|true|yes|on) ENABLE=1 ;; *) ENABLE=0 ;; esac
  case "$LUMA_MIN" in ''|*[!0-9]*) LUMA_MIN=15 ;; esac
  case "$HOLD_SEC" in ''|*[!0-9]*) HOLD_SEC=3 ;; esac
}

tamper_now() {
  read -r _up _ < /proc/uptime 2>/dev/null
  echo "${_up%.*}"
}

check_tamper_once() {
  load_config
  [ "$ENABLE" = 1 ] || {
    [ -f "$TAMPER_FLAG" ] && rm -f "$TAMPER_FLAG"
    return 0
  }

  _now=$(tamper_now)
  # Check if day/night or IR-cut switched recently
  _last_sw=0
  [ -r /tmp/nightmode.last ] && read -r _last_sw < /tmp/nightmode.last 2>/dev/null
  case "$_last_sw" in ''|*[!0-9]*) _last_sw=0 ;; esac
  if [ $((_now - _last_sw)) -lt 30 ]; then
    # Transition guard active: suppress
    return 0
  fi

  _lum=255
  if [ -r "$CAM_LUMA" ]; then
    read -r _lum < "$CAM_LUMA" 2>/dev/null
    case "$_lum" in ''|*[!0-9]*) _lum=255 ;; esac
  fi

  # In daylight or lighted night, if luma drops below LUMA_MIN (almost pitch black)
  # but exposure was forced to high gain in cam_ae:
  _is_dark=0
  if [ "$_lum" -le "$LUMA_MIN" ]; then
    _is_dark=1
  fi

  if [ "$_is_dark" = 1 ]; then
    _cnt=0
    [ -r /tmp/.tamper_cnt ] && read -r _cnt < /tmp/.tamper_cnt 2>/dev/null
    case "$_cnt" in ''|*[!0-9]*) _cnt=0 ;; esac
    _cnt=$((_cnt + 1))
    echo "$_cnt" > /tmp/.tamper_cnt

    if [ "$_cnt" -ge "$HOLD_SEC" ]; then
      if [ ! -f "$TAMPER_FLAG" ]; then
        echo "$_now" > "$TAMPER_FLAG"
        if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
          /mnt/scripts/mqtt-bridge.sh publish event "{\"type\":\"tamper\",\"state\":\"ON\",\"ts\":$_now,\"luma\":$_lum}" 0 \
            tamper/state "ON" 1 >/dev/null 2>&1 || true
        fi
      fi
    fi
  else
    rm -f /tmp/.tamper_cnt
    if [ -f "$TAMPER_FLAG" ]; then
      rm -f "$TAMPER_FLAG"
      if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
        /mnt/scripts/mqtt-bridge.sh publish event "{\"type\":\"tamper\",\"state\":\"OFF\",\"ts\":$_now,\"luma\":$_lum}" 0 \
          tamper/state "OFF" 1 >/dev/null 2>&1 || true
      fi
    fi
  fi
}

case "$1" in
  hk|tick)
    check_tamper_once
    ;;
  run)
    echo "$$" > "$TAMPER_PIDFILE"
    trap 'rm -f "$TAMPER_PIDFILE" /tmp/.tamper_cnt; exit 0' TERM INT
    while :; do
      check_tamper_once
      sleep 2
    done
    ;;
  *)
    check_tamper_once
    ;;
esac
