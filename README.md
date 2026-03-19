# TECKIN TC100 Anyka AK3918 reversible camera hacks
This is a fork from : https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks
Supported model: **Teckin TC100 / Teckin Click** (CPU Anyka AK3918 v300)
AI used : GeminiPro 3.1 for UI, Claude and CODEX 5.3 for the heavy lifting

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
- UI, svg icons, smaller footprint
- Setup Wizard
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

## Unfinished 
- Push-To-Talk (PTT)
- UI enhancements still needed
