# Comparison Report: Your Project vs ThatUsernameAlreadyExist Fork

Generated on: February 24, 2026

Compared sources:
- Local project: `/Users/keegrom/Downloads/TECKIN-TC100-Anyka-AK3918-camera-hacks-main`
  - Branch: `critical-fixes`
  - Commit: `136b3e1`
  - Note: this comparison includes your current uncommitted local changes.
- Reference project: `https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks`
  - Branch: `main`
  - Commit: `ee11e9d`

## Executive Summary
For real-world runtime operation on a constrained Anyka AK3918, your project is better (stability, CPU control, service orchestration, HA/MQTT integration).

The reference project is better for legacy extras and easier frontend hacking (more non-minified browser assets, bundled sample media, and some legacy helper endpoints).

## Quick Scorecard
| Area | Better | Why |
|---|---|---|
| Runtime stability on low CPU | Your project | Added memory guard/service trim/perf profile logic and reduced process pileups. |
| Home Assistant + MQTT integration | Your project | Dedicated MQTT bridge stack, discovery, command handling, and health/event publishing. |
| Security posture | Your project | Security hardening mode and runtime restrictions around risky services. |
| Operational observability | Your project | Motion event API + thumbnail endpoint + richer status/health flows. |
| Legacy diagnostics/helpers | Reference project | Has legacy endpoints like `getispinfo.cgi`, `getMotionInfo.cgi`, `currentpicoptim.cgi`. |
| Frontend debuggability | Reference project | Ships more editable/non-bundled JS (`index.html.js`, jQuery helpers, recorder scripts). |
| Bundled media/demo assets | Reference project | Includes `/media` sound files and image assets out of the box. |

## Quantitative Diff Snapshot
- Total files (tracked content): local `143`, reference `143`
- Common file paths: `119`
- Paths only in local: `24`
- Paths only in reference: `24`
- Common paths with different content: `42`
- Repo size on disk: local `32M`, reference `24M`

## Where Your Project Is Better
- Better low-CPU runtime controls and feature gating.
  - Examples: `controlscripts/memory-guard`, `config/service_trim.conf.dist`, `config/boot.conf.dist`, low-CPU profile logic in `autorun.sh`.
- Strong MQTT/HA integration.
  - Examples: `controlscripts/mqtt-bridge`, `scripts/mqtt-bridge.sh`, `config/mqtt.conf.dist`.
- Better event pipeline and API surfacing.
  - Examples: `scripts/motion-event.sh`, `www/cgi-bin/motionevents.cgi`, `www/cgi-bin/motionthumb.cgi`.
- More modern operational workflow in web UI.
  - Examples in `www/cgi-bin/status.cgi` and `www/cgi-bin/action.cgi`: setup wizard, compatibility presets, HA pairing, stream policy handling.
- Additional daemon hardening in your current tree.
  - Examples: `controlscripts/sound-detection`, `controlscripts/timelapse`, `scripts/timelapse.sh`, `controlscripts/network-monitor`, `scripts/detectionOn.sh`.

## Where Reference Project Is Better
- Better if you want legacy/stock-style web assets and raw JS editing.
  - It includes non-bundled scripts such as `www/scripts/index.html.js`, `www/scripts/jquery-3.3.1.min.js`, `www/scripts/audiocapture.js`.
- Includes built-in sample media and helper assets.
  - `/media/*.wav`, `/media/TeckinTC100.jpg`, plus CSS border image assets.
- Includes some older diagnostic/helper CGI endpoints that are missing in your trimmed tree.
  - `www/cgi-bin/getispinfo.cgi`, `www/cgi-bin/getMotionInfo.cgi`, `www/cgi-bin/currentpicoptim.cgi`, `www/cgi-bin/header.cgi`.
- Includes `wifitest/wifi_test.sh` for quick Wi-Fi checks.

## Local Follow-Up Recommendations From Comparison
- Fix stale audio test default in `www/cgi-bin/action.cgi`.
  - Current fallback is `/mnt/media/police.wav`, but your repo removed `/media`.
- Consider keeping source JS alongside bundles.
  - Right now only bundled/minified files are present for key pages, which slows future debugging.
- If needed, reintroduce selected legacy diagnostics (`getispinfo.cgi`, `getMotionInfo.cgi`) as optional tools.

## File Paths Only In Local
```text
config/autostart/memory-guard
config/boot.conf.dist
config/lighttpd.http.conf.dist
config/mqtt.conf.dist
config/packages.lock.dist
config/service_trim.conf.dist
controlscripts/memory-guard
controlscripts/mqtt-bridge
controlscripts/sound-detection
log/.gitignore
scripts/motion-event.sh
scripts/mqtt-bridge.sh
scripts/pkg-upgrade-safe.sh
www/cgi-bin/configbackup.cgi
www/cgi-bin/motionevents.cgi
www/cgi-bin/motionthumb.cgi
www/cgi-bin/upload_audio.cgi
www/css/pico.min.css
www/css/ui-modern.css
www/scripts/camcontrols.bundle.min.js
www/scripts/index.bundle.min.js
www/scripts/scripts.bundle.min.js
www/scripts/status.bundle.min.js
www/scripts/view_records.bundle.min.js
```

## File Paths Only In Reference
```text
media/README.md
media/TeckinTC100.jpg
media/combine.wav
media/manhack.wav
media/police.wav
media/radio.wav
media/scanner.wav
media/windchine.wav
wifitest/wifi_test.sh
www/cgi-bin/audioupload.cgi
www/cgi-bin/currentpicoptim.cgi
www/cgi-bin/getMotionInfo.cgi
www/cgi-bin/getispinfo.cgi
www/cgi-bin/header.cgi
www/css/border-anim-h.gif
www/css/border-anim-v.gif
www/css/border-h.gif
www/css/border-v.gif
www/scripts/audiocapture.js
www/scripts/audiorecorder.js
www/scripts/index.html.js
www/scripts/jquery-3.3.1.min.js
www/scripts/jquery.imgareaselect.pack.js
www/scripts/smoothie.js
```

## Common Paths With Different Content
```text
README.md
autorun.sh
config/autostart/00_system-config
config/autostart/02_system-webserver
config/lighttpd.conf.dist
config/netmon.conf.dist
config/onvif.conf.dist
config/telegram.conf.dist
controlscripts/front-led
controlscripts/network-monitor
controlscripts/onvif
controlscripts/recording
controlscripts/red-led
controlscripts/rtsp-h26x
controlscripts/timelapse
log/.gitignore
scripts/common_functions.sh
scripts/detection-monitor.sh
scripts/detectionOff.sh
scripts/detectionOn.sh
scripts/network-monitor.sh
scripts/service-watchdog.sh
scripts/telegram-bot-daemon.sh
scripts/timelapse.sh
wpa_supplicant.conf.dist
www/cgi-bin/action.cgi
www/cgi-bin/camcontrols.cgi
www/cgi-bin/devinfo.cgi
www/cgi-bin/disk.cgi
www/cgi-bin/func.cgi
www/cgi-bin/network.cgi
www/cgi-bin/scripts.cgi
www/cgi-bin/state.cgi
www/cgi-bin/status.cgi
www/cgi-bin/sysusageinfo.cgi
www/cgi-bin/viewrecords.cgi
www/index.html
www/logs.html
www/scripts/camcontrols.cgi.js
www/scripts/scripts.cgi.js
www/scripts/status.cgi.js
www/view_records.html
```
