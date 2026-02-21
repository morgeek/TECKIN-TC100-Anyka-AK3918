# TECKIN TC100 Anyka AK3918 camera hacks
Based on the great work from:
https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks

This project keeps the original non-destructive MicroSD hack approach and adds a lighter, faster web UI plus extra RAM/CPU-saving controls.

**Important:** this hack does not modify or upgrade firmware. Remove the MicroSD card and reboot to return to factory behavior.

Supported model: **Teckin TC100 / Teckin Click** (Anyka AK3918 v300)
![Teckin TC100](/media/TeckinTC100.jpg)

Reference product page:
* https://www.teckinhome.com/products/teckin-tc100-wi-fi-smart-home-security-camera

## Main features
* Local web UI (default HTTPS) with no cloud dependency !
* RTSP streaming:
  * Main: `rtsp://CAMERA-IP:554/video0_unicast`
  * Sub: `rtsp://CAMERA-IP:554/video1_unicast`
* ONVIF discovery + stream profile policy controls, 2 cameras working with Home Assistant.
* H.264 / H.265 support
* Audio support
* FTP / telnet / motion detection / recording / timelapse controls
* CPU-aware controls:
  * Stream topology selector
  * RTSP presets (Full / Medium / Low, FPS capped at 25)
  * Service trim mode
  * Boot-time lightweight, low-CPU, and low-RAM profiles

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
* CPU and RAM usage badges are always visible in the top bar.
* Performance profile badge is always visible in the top bar.
* Theme selector is in **Settings -> System**.
* **Services** is a dedicated menu entry; camera control selection is available from the Services page.
* Services page uses a compact table view (Title, Start/Stop, Autorun at boot, View) with hover hints.
* Services state probing is lazy-loaded per row to avoid startup CPU spikes when opening Services.
* Information pages are available from the **Information** menu:
  * System Usage
  * Device Info
  * Network & DNS
  * Disk & Mounts
  * Logs
* Settings page supports **Basic/All** density mode and collapsible cards.
* Settings now include a one-click **Performance profile** selector (Balanced / Low CPU / RTSP+ONVIF only).
* Settings now include **Web server mode** control (`full` / `http` / `ultra-lite` / `off`) with ultra-lite port input.
* Settings now include an **Advanced Tuning** section for boot-level controls (Lightweight mode, Ultra-lite UI mode, NTP behavior, memory guard thresholds, RTSP/ONVIF watchdog timeouts).
* Settings include a **Config Backup & Health** card:
  * download `/mnt/config` backup archive on demand
  * restore from an uploaded `/tmp/*.tar.gz` archive (optional RTSP/ONVIF restart)
  * open one-shot health snapshot JSON (`state.cgi?cmd=healthsnapshot`)

## Performance and CPU tuning
Boot-time tuning is controlled by `/mnt/config/boot.conf` (created from `config/boot.conf.dist` on first boot).

### Lightweight mode
* `LIGHTWEIGHT_MODE=1`:
  * disables NTP daemon and crond by default
  * enables one-shot NTP by default
  * enables low-CPU profile defaults
  * can apply autostart denylist defaults

* `UI_ULTRALITE_MODE=1`:
  * pauses live preview by default and requires manual resume
  * increases UI polling intervals and disables costly snapshot optimization fallback
  * minimizes web UI CPU overhead while keeping controls available

### Low CPU profile
* `LOW_CPU_PROFILE=1` applies conservative RTSP defaults.
* Optional disables:
  * `LOW_CPU_DISABLE_SUBSTREAM`
  * `LOW_CPU_DISABLE_AUDIO`
  * `LOW_CPU_DISABLE_MOTION`
  * `LOW_CPU_DISABLE_OSD`
  * `LOW_CPU_DISABLE_JPEG`
* Resolution/FPS/bitrate overrides are available via `LOW_CPU_MAIN_*` and `LOW_CPU_SUB_*` variables in `config/boot.conf.dist`.

### Low RAM profile
* `LOW_RAM_PROFILE=1` enables memory-saving defaults and starts the memory guard.
* `MEM_GUARD_ENABLE=1` runs `/mnt/controlscripts/memory-guard`:
  * checks `MemAvailable` every `MEM_GUARD_INTERVAL_SECONDS`
  * uses hit counters (`MEM_GUARD_WARN_HITS`, `MEM_GUARD_CRITICAL_HITS`) to avoid noisy one-shot spikes
  * at `MEM_GUARD_WARN_KB`, stops soft non-essential services
  * at `MEM_GUARD_CRITICAL_KB`, also stops heavier services
  * at `MEM_GUARD_EMERGENCY_KB`, can apply emergency service stops and cache drop
  * resets pressure counters only after memory recovers above `MEM_GUARD_WARN_KB + MEM_GUARD_RECOVERY_MARGIN_KB`
* Tune service lists with:
  * `MEM_GUARD_SOFT_SERVICES`
  * `MEM_GUARD_CRITICAL_SERVICES`
  * `MEM_GUARD_EMERGENCY_SERVICES`

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
* `LOW_RAM_PROFILE=1`
* `SERVICE_TRIM=1`
* Keep only one browser tab open to the UI (live snapshot requests are the main web-side load).

When `LOW_CPU_PROFILE` or `SERVICE_TRIM` is active, the UI automatically slows polling/live-preview cadence to reduce CGI/webserver load.
The UI also applies dynamic throttling from live CPU/RAM pressure (high usage increases polling/live-preview intervals automatically).
`state.cgi` uses short-lived cache files in `/tmp` and now returns an enriched `statusline` payload (CPU/RAM/profile/LUM/AWB/UI mode) so the frontend can use fewer CGI requests.

### Other low-load defaults
* Motion monitor default interval: `MONITOR_TIMEOUT_SECONDS=6`
* RTSP/ONVIF watchdog check interval default: `CHECK_TIMEOUT_SECONDS=60`
* RTSP/ONVIF watchdog mode defaults: `RTSP_WATCHDOG_MODE=status`, `ONVIF_WATCHDOG_MODE=status`
* ONVIF health hardening defaults:
  * `ONVIF_STARTUP_GRACE_SECONDS=20`
  * `ONVIF_HEALTHCHECK_RETRIES=2`
  * `ONVIF_RTSP_DEPENDENCY_MODE=status`
* Watchdog log rotation defaults:
  * `WATCHDOG_LOG_MAX_BYTES=262144`
  * `WATCHDOG_LOG_BACKUPS=2`
* Chip temperature (if kernel exposes a readable sensor):
  * `CHIP_TEMP_SOURCE_PATH=auto` (or explicit path like `/sys/class/thermal/thermal_zone0/temp`)
  * `CHIP_TEMP_RAW_DIVISOR=auto` (set `1000` for millidegree sources, `1` for direct Celsius)
* Network monitor default ping interval: `PINGINTERVAL=120`
* Telegram bot supports long-poll tuning:
  * `TELEGRAM_LONG_POLL_TIMEOUT_SECONDS`
  * `TELEGRAM_IDLE_SLEEP_SECONDS`
  * `TELEGRAM_ERROR_BACKOFF_SECONDS`

## OSD note
Preferred OSD time format uses `%` placeholders, e.g.:
* `%H:%M:%S .%m.%Y`

Legacy `\\x`-style patterns are sanitized automatically at RTSP service start.

## Developer checks
Run local CGI smoke tests before deploying UI/CGI changes:
* `tests/cgi-smoke.sh`

## Vendor binaries notes
Reverse-engineering notes for closed binaries are documented in:
* `docs/vendor-binaries-reverse-engineering.md`
