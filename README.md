# TECKIN TC100 Anyka AK3918 reversible camera hacks
This is a fork from : https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks
Supported model: **Teckin TC100 / Teckin Click** (CPU Anyka AK3918 v300)
AI used

This is a trimmed, essentials-only version focused on runtime camera operation from MicroSD.
No firmware flashing is performed! 

## What is kept from the original project
- Boot/runtime core: `autorun.sh`, `bin/`, `lib/`, `config/`, `scripts/`, `controlscripts/`, `www/`
- Local web UI (HTTP/HTTPS depending on config)
- RTSP (`video0_unicast`, `video1_unicast`)
- Core camera controls and services enhanced.

## What is added :
- Massive CPU/RAM optimization
- UI, SVG icons, updated bulma, smaller footprint
- Setup Wizard
- ONVIF /Frigate and HomeAssistant friendly
- MQTT Support
- MQTT subscribe retry backoff controls in UI (low-overhead broker outage handling)
- Complete Push-To-Talk (PTT) with audio level meter and test speaker button**
- Two-Way Audio streaming - listen to camera microphone in real-time**

## Installation
1. Format MicroSD as FAT32 (32K allocation size recommended).
2. Copy repository contents to the card.
3. Create `wpa_supplicant.conf` from `wpa_supplicant.conf.dist` and set Wi-Fi SSID/PSK.
4. Insert card into camera and reboot.
5. Open `https://CAMERA-IP` (or configured web mode/port).

Default credentials are `root/pass`; change password immediately.

## Uninstall
Remove MicroSD and reboot.

## Notes
- This project is local-LAN focused and does not require cloud services! Home Assistant friendly !
- If you want even smaller footprint, remove optional services in UI and disable autostart entries you do not use.

## Home Assistant / Frigate
- Use the `Home Assistant pairing` action in the web UI with the `Frigate balanced` preset for the safest default stream layout.
- Additional Frigate-oriented presets are available for `Frigate low-bandwidth` and `Frigate quality`, depending on whether you want lower LAN/storage load or better recording quality.
- After pairing, open the `HA / Frigate Integration Pack` section in the Status page or fetch `cgi-bin/state.cgi?cmd=integrationmanifest` to get the live RTSP URLs, ONVIF endpoint, MQTT topics, and a generated Frigate snippet.
- Use `cgi-bin/state.cgi?cmd=integrationtest` or the `Run self-test` button in that same section to verify RTSP main/sub, ONVIF, MQTT publish, and local snapshot capture from the camera itself.
- Stream/profile changes now run an automatic post-apply self-test and roll back to the pre-change or known-good snapshot if blocking RTSP/ONVIF checks fail.
- Regenerate or re-open that manifest after changing RTSP, ONVIF, credentials, or MQTT settings so your pasted config stays in sync with the camera.
- The MQTT bridge now publishes retained integration topics at `<MQTT_TOPIC_ROOT>/integration/manifest` and `<MQTT_TOPIC_ROOT>/integration/selftest`; the MQTT manifest is intentionally redacted so RTSP and broker secrets are not broadcast over MQTT.
- MQTT commands now also publish structured result payloads at `<MQTT_TOPIC_ROOT>/command/result`, `<MQTT_TOPIC_ROOT>/command/last_result`, and `<MQTT_TOPIC_ROOT>/repair/last_result`, so Home Assistant can react to actual repair outcomes instead of fire-and-forget button presses.
- Home Assistant MQTT discovery now exposes integration status sensors plus buttons to refresh the integration manifest and run the integration self-test from HA.
- Home Assistant MQTT discovery also exposes remote repair buttons for `repair_integration`, `restart_rtsp`, `restart_onvif`, `restart_network_monitor`, and `restart_mqtt_bridge`, plus sensors for the last command result and last repair result.
- Network monitoring now publishes retained telemetry at `<MQTT_TOPIC_ROOT>/network/state` with Wi-Fi, gateway, broker, and recovery metadata, and Home Assistant discovery exposes those signals as network-health entities.
- Broker failure is now treated separately from Wi‑Fi/gateway failure: the network monitor can restart the MQTT bridge when the LAN is healthy instead of bouncing `wlan0` or rebooting the camera.
- After Wi-Fi/gateway/broker recovery, the network monitor now runs a local `repair_integration` pass automatically so RTSP/ONVIF health and MQTT self-test state are refreshed without manual intervention.

## Web workflow
- Frontend source now lives in `frontend/src/`.
- Run `npm run build:web` to sync frontend source into the shipped files under `www/`.
- Run `npm run check:web` to detect drift between tracked source files and deployable web assets.
- This first-pass workflow is intentionally zero-dependency and offline-friendly: it keeps a clear source of truth before introducing minifiers or a heavier bundler.

## Audio Features

### Push-To-Talk (PTT)
- **Talk**: Hold the "Hold to Talk" button to record voice messages (400ms - 9s)
- **Visual Feedback**: Real-time audio level meter during recording
- **Test Speaker**: "Test" button verifies speaker is working
- **Volume Control**: Adjustable speaker output (0-100%)
- **Cross-Platform**: Works with touch, mouse, and keyboard (Space/Enter)
- **Requires**: HTTPS or localhost for microphone access (browser security policy)

### Two-Way Audio
- **Listen**: Click "Listen" to stream audio from camera microphone in real-time
- **Browser Playback**: Native HTML5 audio streaming
- **Auto-Disconnect**: Stops after 30 seconds to conserve resources
- **Status Feedback**: UI shows connection status
- **Requires**: Compatible audio capture binary on device (arecord/rec)

## Remaining Features
- UI/UX enhancements still needed for other areas
- Optional: Cloud backup integration