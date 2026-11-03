#!/bin/sh
# scripts/tamper-detect.sh — Lightweight Camera Tampering / Occlusion Detector
#
# Detects camera tampering (lens covering, spraying, or total sudden occlusion):
# - Does NOT rely solely on /tmp/cam_luma because the ISP's auto-exposure (AE)
#   boosts dark pictures back to ~127 in daylight.
# - Combines:
#   1. Sudden drop in image entropy/detail: JPEG file size (/tmp/currentpic.cache.jpg)
#      dropping by >= 40-50% compared to baseline.
#   2. Concomitant surge in ISP exposure time & analog/digital gains (/tmp/cam_ae).
#   3. Direct low luma detection (for night or dark transitions).
# - Strict anti-false-positive guard:
#   - Suppressed for 30s following day/night switch or IR-cut filter transitions.
#   - Suppressed if camera is in night mode without IR LED ("behind glass" mode)
#     in pitch black to avoid false triggers when looking out into total darkness.
# - Confirmed when conditions hold continuously for TAMPER_HOLD_SEC (default 6s).
# - Publishes event + binary_sensor tamper/state via MQTT bridge and notification.

BOOT_CONF="/mnt/config/boot.conf"
TAMPER_CONF="/mnt/config/tamper.conf"
TAMPER_PIDFILE="/var/run/tamper-detect.pid"
TAMPER_FLAG="/tmp/cam_tamper"
CAM_LUMA="/tmp/cam_luma"
CAM_AE="/tmp/cam_ae"
JPEG_CACHE="/tmp/currentpic.cache.jpg"
BASELINE_FILE="/tmp/.tamper_base_jpg"

# Defaults
ENABLE=0
HOLD_SEC=6
LUMA_MIN=15
JPEG_DROP_PCT=50

load_config() {
  # tamper.conf is the one place of these settings (scripts/migrate-switches.sh moved the TAMPER_* of boot.conf)
  if [ -r "$TAMPER_CONF" ]; then
    while IFS='=' read -r _k _v; do
      case "$_k" in
        ENABLE) [ -n "$_v" ] && ENABLE="$_v" ;;
        TAMPER_HOLD_SEC) [ -n "$_v" ] && HOLD_SEC="$_v" ;;
        TAMPER_LUMA_MIN) [ -n "$_v" ] && LUMA_MIN="$_v" ;;
        TAMPER_JPEG_DROP_PCT) [ -n "$_v" ] && JPEG_DROP_PCT="$_v" ;;
      esac
    done < "$TAMPER_CONF"
  fi
  case "$ENABLE" in 1|true|yes|on) ENABLE=1 ;; *) ENABLE=0 ;; esac
  case "$HOLD_SEC" in ''|*[!0-9]*) HOLD_SEC=6 ;; esac
  case "$LUMA_MIN" in ''|*[!0-9]*) LUMA_MIN=15 ;; esac
  case "$JPEG_DROP_PCT" in ''|*[!0-9]*) JPEG_DROP_PCT=50 ;; esac
}

tamper_now() {
  read -r _up _ < /proc/uptime 2>/dev/null
  echo "${_up%.*}"
}

check_tamper_once() {
  load_config
  [ "$ENABLE" = 1 ] || {
    [ -f "$TAMPER_FLAG" ] && rm -f "$TAMPER_FLAG"
    rm -f /tmp/.tamper_cnt "$BASELINE_FILE"
    return 0
  }

  _now=$(tamper_now)

  # 1. Day/Night transition guard (suppress for 30s)
  _last_sw=0
  [ -r /tmp/nightmode.last ] && read -r _last_sw < /tmp/nightmode.last 2>/dev/null
  case "$_last_sw" in ''|*[!0-9]*) _last_sw=0 ;; esac
  if [ $((_now - _last_sw)) -ge 0 ] && [ $((_now - _last_sw)) -lt 30 ]; then
    rm -f /tmp/.tamper_cnt
    return 0
  fi

  # 2. Behind glass mode guard: if night mode active with IR off in a pitch black room
  if [ -r /tmp/nightmode ] && [ "$(cat /tmp/nightmode 2>/dev/null)" = "night" ]; then
    _irled="auto"
    [ -r /mnt/config/daynight.conf ] && _irled=$(grep '^IR_LED_MODE=' /mnt/config/daynight.conf 2>/dev/null | cut -d= -f2)
    if [ "$_irled" = "off" ]; then
      # Night without IR illumination: legitimate darkness, avoid false positive
      rm -f /tmp/.tamper_cnt
      return 0
    fi
  fi

  # 3. Read current sensors and indicators
  _lum=255
  if [ -r "$CAM_LUMA" ]; then
    read -r _lum < "$CAM_LUMA" 2>/dev/null
    case "$_lum" in ''|*[!0-9]*) _lum=255 ;; esac
  fi

  _exp_time=0; _a_gain=0
  if [ -r "$CAM_AE" ]; then
    read -r _lumi _exp_time _a_gain _d_gain _rest < "$CAM_AE" 2>/dev/null
    case "$_exp_time" in ''|*[!0-9]*) _exp_time=0 ;; esac
    case "$_a_gain" in ''|*[!0-9]*) _a_gain=0 ;; esac
  fi

  # JPEG byte size (proxy for image spatial frequency / detail)
  _jpg_sz=0
  if [ -r "$JPEG_CACHE" ]; then
    _jpg_sz=$(wc -c < "$JPEG_CACHE" 2>/dev/null || echo 0)
    case "$_jpg_sz" in ''|*[!0-9]*) _jpg_sz=0 ;; esac
  fi

  # Maintain running baseline for JPEG size when not in tampering condition
  _base_sz=0
  [ -r "$BASELINE_FILE" ] && read -r _base_sz < "$BASELINE_FILE" 2>/dev/null
  case "$_base_sz" in ''|*[!0-9]*) _base_sz=0 ;; esac

  _is_tampered=0

  # Case A: Pitch black condition (e.g. night or dark covering)
  if [ "$_lum" -le "$LUMA_MIN" ]; then
    _is_tampered=1
  # Case B: Daylight covering (auto-exposure compensates luma to ~120-128, but
  # image details vanish -> JPEG size collapses by >= 40-50% while AE gain surges)
  elif [ "$_base_sz" -gt 20000 ] && [ "$_jpg_sz" -gt 0 ]; then
    _drop_ratio=$(( _jpg_sz * 100 / _base_sz ))
    if [ "$_drop_ratio" -le "$JPEG_DROP_PCT" ] && [ "$_exp_time" -ge 600 ]; then
      _is_tampered=1
    fi
  fi

  # Update baseline only when scene is stable and not in tamper state
  if [ "$_is_tampered" = 0 ] && [ "$_jpg_sz" -gt 15000 ]; then
    if [ "$_base_sz" -eq 0 ]; then
      echo "$_jpg_sz" > "$BASELINE_FILE"
    else
      # Exponential moving average: 80% old + 20% new
      _new_base=$(( (_base_sz * 8 + _jpg_sz * 2) / 10 ))
      echo "$_new_base" > "$BASELINE_FILE"
    fi
  fi

  # 4. Debounce and alert state machine
  if [ "$_is_tampered" = 1 ]; then
    _cnt=0
    [ -r /tmp/.tamper_cnt ] && read -r _cnt < /tmp/.tamper_cnt 2>/dev/null
    case "$_cnt" in ''|*[!0-9]*) _cnt=0 ;; esac
    _cnt=$((_cnt + 2))
    echo "$_cnt" > /tmp/.tamper_cnt

    if [ "$_cnt" -ge "$HOLD_SEC" ]; then
      if [ ! -f "$TAMPER_FLAG" ]; then
        echo "$_now" > "$TAMPER_FLAG"
        if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
          /mnt/scripts/mqtt-bridge.sh publish event "{\"type\":\"tamper\",\"state\":\"ON\",\"ts\":$_now,\"luma\":$_lum,\"jpg_size\":$_jpg_sz}" 0 \
            tamper/state "ON" 1 >/dev/null 2>&1 || true
        fi
        if [ -x /mnt/scripts/notify.sh ]; then
          /mnt/scripts/notify.sh tamper "Camera occlusion / tamper detected (luma: $_lum, size: ${_jpg_sz}B)" "" "$_lum" >/dev/null 2>&1 &
        fi
      fi
    fi
  else
    rm -f /tmp/.tamper_cnt
    if [ -f "$TAMPER_FLAG" ]; then
      rm -f "$TAMPER_FLAG"
      if [ -x /mnt/scripts/mqtt-bridge.sh ]; then
        /mnt/scripts/mqtt-bridge.sh publish event "{\"type\":\"tamper\",\"state\":\"OFF\",\"ts\":$_now,\"luma\":$_lum,\"jpg_size\":$_jpg_sz}" 0 \
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
