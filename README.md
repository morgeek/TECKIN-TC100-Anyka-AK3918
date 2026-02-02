# TECKIN TC100 Anyka AK3918 camera hacks

Hacks for p2p-only camera that allow you to use rtsp/web-interface/ftp and other functions.

**NOTE: this hack doesn't modify or upgrade firmware - you can restore the original state of the camera at any time (hack work only with MicroSD-card!).**

Supported camera model: **Teckin TC100 / Teckin Click** with Anyka AK3918 v300 CPU
![Teckin TC100](/media/TeckinTC100.jpg)

* https://www.teckinhome.com/products/teckin-tc100-wi-fi-smart-home-security-camera

## How to install
1. Prepare an MicroSD-card with FAT32 filesystem and allocation unit size 32K (16K and smaller unit size may running system into unstable condition)
2. Copy all data to MicroSD-card
3. Connect the camera to your WiFI network through Teckin app (Android/IOS). See IP-address of the camera in your WiFi-router settings (required to connect via http/rtsp).
4. Place MicroSD-card in camera 
5. Reboot camera
   
Now you can connect to the camera via browser (**https://CAMERA-IP**), get RTSP-stream, download/upload files via FTP and many other things.
**When hack is enabled, default Teckin cloud function will not be available.**

## How to uninstall
To disable hacks: just remove MicroSD-card and reboot camera.

## Misc
* Default camera **login/password: root/pass**
* Change password for http/rtsp/ftp/telnet in web interface settings
* Main stream rtsp url: **rtsp://CAMERA-IP:554/video0_unicast**
* Sub stream rtsp url:  **rtsp://CAMERA-IP:554/video1_unicast**
* Support ONVIF-discovery
* Support loop video recording to MicroSD
* Support H264/H265
* Support audio
* Manual connection to WiFi network (without Teckin cloud app): create file **wpa_supplicant.conf** in MicroSD-card and reboot.
  See file content example in **wpa_supplicant.conf.dist** file: change ssid and psk to your WiFi name and password.

## Lightweight mode
To reduce CPU/RAM usage on the camera, configure `/mnt/config/boot.conf` (copied from `config/boot.conf.dist` on first boot):

* Set `LIGHTWEIGHT_MODE=1` to apply lightweight defaults (disables NTP daemon, crond, and skips non-essential autostart scripts).
* Use `AUTOSTART_ALLOWLIST` to run only specific autostart scripts (e.g. `00_system-config rtsp-h26x`).
* Use `AUTOSTART_DENYLIST` to skip specific scripts (e.g. web UI, ONVIF, LEDs).
* Set `LOW_CPU_PROFILE=1` for a very low CPU RTSP profile (lower resolution/fps/bitrate, optional substream/audio/OSD/motion/jpeg disable). Set `LOW_CPU_DISABLE_SUBSTREAM=0` or `LOW_CPU_DISABLE_AUDIO=0` to keep them on.
* Control RTSP streams directly with `RTSP_SUBSTREAM` and `RTSP_AUDIO`.

All settings live in `config/boot.conf.dist` for reference.

Example low-CPU boot config:

```
LIGHTWEIGHT_MODE=1
LOW_CPU_PROFILE=1
AUTOSTART_ALLOWLIST="00_system-config rtsp-h26x"
```

## Low-CPU web UI
If you only need the web UI occasionally, reduce webserver CPU overhead via `WEB_MODE` in `/mnt/config/boot.conf`:

* `WEB_MODE=http` disables TLS and HTTPS redirect (lower CPU, but no encryption).
* `WEB_MODE=off` disables the webserver entirely.

## RTSP presets
The web UI includes RTSP presets (Full, Medium, Low) with FPS capped at 25. Use them to quickly tune image quality vs CPU.

## Service trim switch
The Status page includes a "Service trim" switch that keeps only RTSP + ONVIF at boot. It disables non-essential services and reduces CPU usage.
