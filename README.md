# TECKIN TC100 Anyka AK3918 reversible camera hacks
This is a fork from : https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks
Supported model: **Teckin TC100 / Teckin Click** (CPU Anyka AK3918 v300)

This is a trimmed, essentials-only version focused on runtime camera operation from MicroSD.
No firmware flashing is performed! 

## What is kept from the original project
- Boot/runtime core: `autorun.sh`, `bin/`, `lib/`, `config/`, `scripts/`, `controlscripts/`, `www/`
- AI Enhanced Local web UI (HTTP/HTTPS depending on config)
- RTSP (`video0_unicast`, `video1_unicast`)
- ONVIF
- Core camera controls and services albeit enhanced.

## What is added :
- Massive CPU/RAM optimization, memory leaks or CPU spikes on a small CPU is not fun.
- Beter UI
- Setup Wizard
- MQTT Support

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
- UI Polishing
