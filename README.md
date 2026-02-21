# TECKIN TC100 Anyka AK3918 camera hacks
Based on the great work from:
https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks

This project keeps the original non-destructive MicroSD hack approach and adds a lighter, faster web UI plus extra CPU-saving controls.

**Important:** this hack does not modify or upgrade firmware. Remove the MicroSD card and reboot to return to factory behavior.

Supported model: **Teckin TC100 / Teckin Click** (Anyka AK3918 v300)
![Teckin TC100](/media/TeckinTC100.jpg)

Reference product page:
* https://www.teckinhome.com/products/teckin-tc100-wi-fi-smart-home-security-camera

## Main features
* Local web UI (default HTTPS) with no cloud dependency
* RTSP streaming:
  * Main: `rtsp://CAMERA-IP:554/video0_unicast`
  * Sub: `rtsp://CAMERA-IP:554/video1_unicast`
* ONVIF discovery + stream profile policy controls
* H.264 / H.265 support
* Audio support
* FTP / telnet / motion detection / recording / timelapse controls
* CPU-aware controls:
  * Stream topology selector
  * RTSP presets (Full / Medium / Low, FPS capped at 25)
  * Service trim mode
  * Boot-time lightweight and low-CPU profiles

## Installation
1. Prepare a MicroSD card as FAT32 with 32K allocation unit size.
2. Copy repository contents to the MicroSD card.
3. Create `wpa_supplicant.conf` from `wpa_supplicant.conf.dist` and set your Wi-Fi SSID/PSK.
4. Insert MicroSD card into the camera.
5. Reboot the camera.
6. Open:
  * `https://CAMERA-IP` (default, `WEB_MODE=full`)
  * default credentials: `root/pass`

When this hack is active, Teckin cloud features are not used !

## Uninstall
Remove the MicroSD card and reboot.

## Access and credentials
* Default login/password: `root/pass`
* Password changes for HTTP/RTSP/FTP/Telnet are available in the web UI settings.

## Current web UI behavior
* Live view includes pause/resume and snapshot.
* CPU/RAM usage badge is always visible in the top bar.
* Performance profile badge is always visible in the top bar.
* Theme selector is in **Settings -> System**.
* **Services** and **Camera Functions** are available as dedicated menu entries.
* Services page uses a compact table view (Title, Start/Stop, Autorun at boot, View) with hover hints.
* Information pages are available from the **Information** menu:
  * System Usage
  * Device Info
  * Network & DNS
  * Disk & Mounts
  * Logs
* Settings page supports **Basic/All** density mode and collapsible cards.
* Settings now include a one-click **Performance profile** selector (Balanced / Low CPU / RTSP+ONVIF only).
* Settings now include **Web server mode** control (`full` / `http` / `ultra-lite` / `off`) with ultra-lite port input.

## Performance and CPU tuning
Boot-time tuning is controlled by `/mnt/config/boot.conf` (created from `config/boot.conf.dist` on first boot).

### Lightweight mode
* `LIGHTWEIGHT_MODE=1`:
  * disables NTP daemon and crond by default
  * enables one-shot NTP by default
  * enables low-CPU profile defaults
  * can apply autostart denylist defaults

### Low CPU profile
* `LOW_CPU_PROFILE=1` applies conservative RTSP defaults.
* Optional disables:
  * `LOW_CPU_DISABLE_SUBSTREAM`
  * `LOW_CPU_DISABLE_AUDIO`
  * `LOW_CPU_DISABLE_MOTION`
  * `LOW_CPU_DISABLE_OSD`
  * `LOW_CPU_DISABLE_JPEG`
* Resolution/FPS/bitrate overrides are available via `LOW_CPU_MAIN_*` and `LOW_CPU_SUB_*` variables in `config/boot.conf.dist`.

### Stream topology (web UI)
In **Settings -> System -> Stream topology**:
* `Dual stream + audio` (`RTSP_SUBSTREAM=1`, `RTSP_AUDIO=1`)
* `Dual stream, audio off` (`RTSP_SUBSTREAM=1`, `RTSP_AUDIO=0`)
* `Main stream + audio` (`RTSP_SUBSTREAM=0`, `RTSP_AUDIO=1`)
* `Main stream only` (`RTSP_SUBSTREAM=0`, `RTSP_AUDIO=0`)

Applying topology restarts RTSP and ONVIF services.

### ONVIF stream policy (web UI)
In **Settings -> System -> ONVIF stream policy**:
* `main-primary` (default)
* `sub-primary`
* `sub-only`
* `main-only`

ONVIF identity metadata is configured in `/mnt/config/onvif.conf`:
* `VENDOR_NAME`, `HW_NAME`, `DEVICE_LOCATION`, `DEVICE_NAME`, `DEVICE_MODEL`

### Service trim (web UI)
The **Service trim** switch sets `/mnt/config/service_trim.conf` and keeps only a small autostart allowlist (RTSP/ONVIF/web essentials), reducing CPU load.

### Web server mode
Set in `/mnt/config/boot.conf`:
* `WEB_MODE=full` (default HTTPS + redirect)
* `WEB_MODE=http` (HTTP only, lower CPU, no TLS)
* `WEB_MODE=ultra-lite` (BusyBox `httpd`, lowest web CPU/RAM, no lighttpd auth/TLS layer)
* `WEB_MODE=off` (web server disabled)
* Optional for ultra-lite: `ULTRALITE_HTTP_PORT=80`

### Maximum web CPU savings
For minimum web stack overhead while keeping core camera functionality:
* `WEB_MODE=ultra-lite`
* `LOW_CPU_PROFILE=1`
* `SERVICE_TRIM=1`
* Keep only one browser tab open to the UI (live snapshot requests are the main web-side load).

When `LOW_CPU_PROFILE` or `SERVICE_TRIM` is active, the UI now automatically slows polling/live-preview cadence to reduce CGI/webserver load.

### Other low-load defaults
* Motion monitor default interval: `MONITOR_TIMEOUT_SECONDS=6`
* RTSP/ONVIF watchdog check interval default: `CHECK_TIMEOUT_SECONDS=60`
* Network monitor default ping interval: `PINGINTERVAL=120`
* Telegram bot supports long-poll tuning:
  * `TELEGRAM_LONG_POLL_TIMEOUT_SECONDS`
  * `TELEGRAM_IDLE_SLEEP_SECONDS`
  * `TELEGRAM_ERROR_BACKOFF_SECONDS`

## OSD note
Preferred OSD time format uses `%` placeholders, e.g.:
* `%H:%M:%S .%m.%Y`

Legacy `\\x`-style patterns are sanitized automatically at RTSP service start.

## Vendor binaries notes
Reverse-engineering notes for closed binaries are documented in:
* `docs/vendor-binaries-reverse-engineering.md`
