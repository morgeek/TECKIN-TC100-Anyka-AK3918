# TECKIN TC100 Anyka AK3918 reversible camera hacks
This is a fork from : https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks
Supported model: **Teckin TC100 / Teckin Click** (CPU Anyka AK3918 v300)
AI used

This is a trimmed, essentials-only version focused on runtime camera operation from MicroSD.
No firmware flashing is performed! 

## What is kept from the original project
- Boot/runtime core: `autorun.sh`, `bin/`, `lib/`, `config/`, `scripts/`, `controlscripts/`, `www/`
- AI Enhanced Local web UI (HTTP/HTTPS depending on config)
- RTSP (`video0_unicast`, `video1_unicast`)
- ONVIF /Frigate and HomeAssistant friendly
- Core camera controls and services enhanced.

## What is added :
- Massive CPU/RAM optimization
- UI, SVG icons, updated bulma, smaller footprint
- Setup Wizardyes
- MQTT Support
- MQTT subscribe retry backoff controls in UI (low-overhead broker outage handling)

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
- Use the `Home Assistant pairing` action in the web UI with the `HA Frigate` preset for the safest default stream layout.
- After pairing, open the `HA / Frigate Integration Pack` section in the Status page or fetch `cgi-bin/state.cgi?cmd=integrationmanifest` to get the live RTSP URLs, ONVIF endpoint, MQTT topics, and a generated Frigate snippet.
- Use `cgi-bin/state.cgi?cmd=integrationtest` or the `Run self-test` button in that same section to verify RTSP main/sub, ONVIF, MQTT publish, and local snapshot capture from the camera itself.
- Stream/profile changes now run an automatic post-apply self-test and roll back to the pre-change or known-good snapshot if blocking RTSP/ONVIF checks fail.
- Regenerate or re-open that manifest after changing RTSP, ONVIF, credentials, or MQTT settings so your pasted config stays in sync with the camera.
- The MQTT bridge now publishes retained integration topics at `<MQTT_TOPIC_ROOT>/integration/manifest` and `<MQTT_TOPIC_ROOT>/integration/selftest`; the MQTT manifest is intentionally redacted so RTSP and broker secrets are not broadcast over MQTT.
- Home Assistant MQTT discovery now exposes integration status sensors plus buttons to refresh the integration manifest and run the integration self-test from HA.

## Web workflow
- Frontend source now lives in `frontend/src/`.
- Run `npm run build:web` to sync frontend source into the shipped files under `www/`.
- Run `npm run check:web` to detect drift between tracked source files and deployable web assets.
- This first-pass workflow is intentionally zero-dependency and offline-friendly: it keeps a clear source of truth before introducing minifiers or a heavier bundler.

## Unfinished 
- Push-To-Talk (PTT)
- UI enhancements still needed
