# TECKIN TC100 Anyka AK3918 camera hacks
Supported model: **Teckin TC100 / Teckin Click** (CPU Anyka AK3918 v300)
![Teckin TC100](/media/TeckinTC100.jpg)

Reference product page:
* https://www.teckinhome.com/products/teckin-tc100-wi-fi-smart-home-security-camera
Based on the great work from:
https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks
AI DRIVEN : This project keeps the original non-destructive MicroSD hack approach and adds a lighter, faster web UI plus extra RAM/CPU-saving controls.
I've modded my cameras with an Aluminium Heatsink on top of the CPU !

**Important:** this hack does not modify or upgrade firmware! 
Remove the MicroSD card and reboot to return to factory behavior.

## Main features
* Local-only web UI (default HTTPS) with no cloud dependency.
* RTSP streaming:
  * Main: `rtsp://CAMERA-IP:554/video0_unicast`
  * Sub: `rtsp://CAMERA-IP:554/video1_unicast`
* ONVIF discovery plus stream profile policy controls (Home Assistant friendly, multi-camera ready).
* H.264 / H.265 support
* Audio support
* FTP / telnet / motion detection / recording / timelapse controls
* CPU-aware controls:
  * Stream topology selector
  * RTSP presets (Full / Medium / Low, FPS capped at 25)
  * Service trim mode
  * Boot-time lightweight, low-CPU, and low-RAM profiles
* MQTT bridge for local automations (publish health/events, receive commands)
* Motion Event API for Home Assistant (`motionevents.cgi` + `motionthumb.cgi`)
* Security hardening mode (force HTTPS + block FTP/Telnet)

## Network ports (cloud-free/local LAN)
Default and optional service ports used by this project:
* `443/tcp` HTTPS web UI (`WEB_MODE=full`, default).
* `80/tcp` HTTP web UI (`WEB_MODE=http` or `WEB_MODE=ultra-lite`; also used for HTTP->HTTPS redirect in full mode).
* `554/tcp` RTSP main/sub streams.
* `8081/tcp` ONVIF service endpoint (`ONVIF_PORT`, configurable in `onvif.conf`).
* `21/tcp` FTP service (optional, configurable in Settings).
* `23/tcp` Telnet service (optional, configurable in Settings).

Notes:
* FTP and Telnet may be closed depending on enabled services/profile.
* No cloud endpoint is required for operation; camera control and streaming stay on your local network.

## Installation
1. Prepare a MicroSD card as FAT32 with 32K allocation unit size.
2. Copy repository contents to the MicroSD card.
3. Create `wpa_supplicant.conf` from `wpa_supplicant.conf.dist` and set your Wi-Fi SSID/PSK.
4. Insert MicroSD card into the camera.
5. Reboot the camera.
6. Open:
  * `https://CAMERA-IP` (default, `WEB_MODE=full`)
  * default credentials: `root/pass` (change immediately after first login)

When this hack is active, Teckin cloud features are not used !

## Access and credentials
* Default login/password: `root/pass`
* Security: change the default password immediately after first login.
* Password changes for HTTP/RTSP/FTP/Telnet are available in the web UI settings.

## Uninstall
Remove the MicroSD card and reboot.
## Current web UI behavior
* Live view includes pause/resume and snapshot.
* CPU/RAM/temperature/power badges are visible in the top bar.
* Performance profile badge is always visible in the top bar.
* Last reboot badge is visible in the top bar.
* Theme selector is in **Settings -> System**.
* **Services** is a dedicated menu entry; camera control selection is available from the Services page.
* Services include color-coded runtime impact tags:
  * `Min` (green): low overhead
  * `Med` (amber): moderate overhead
  * `Heavy` (red): higher CPU/RAM usage when active
* Services state probing is lazy-loaded per row to avoid startup CPU spikes when opening Services.
* Information pages are available from the **Information** menu:
  * System Usage
  * Device Info (includes last reboot/uptime and `/mnt/bin` binary versions)
  * Network & DNS
  * Disk & Mounts
  * Logs
* Information pages now use a compact responsive split layout:
* Network & DNS page includes a live **Open Service Ports** table (runtime socket probe + configured expectation).
* Logs page now has integrated controls:
* Settings page supports **Basic/All** density mode and collapsible cards.
* Settings now include a one-click **Performance profile** selector (Balanced / Low CPU / RTSP+ONVIF only).
* Settings now include **Web server mode** control (`full` / `http` / `ultra-lite` / `off`) with ultra-lite port input.
* Settings now include **Client presets** for ONVIF/RTSP consumers:
  * HA Frigate
  * NVR low-CPU
  * High quality
* Settings now include an **Advanced Tuning** section for boot-level controls (Lightweight mode, Ultra-lite UI mode, NTP behavior, memory guard thresholds, RTSP/ONVIF watchdog timeouts).
* Settings now include an **MQTT Bridge** card to configure local broker/topic/intervals, Home Assistant discovery, and power telemetry/estimation behavior.
* Settings now include a **Motion Event API** card with direct links to local automation endpoints.
* Settings show a security warning in the password section when default credentials are still active.
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

### Security hardening mode
Set in `/mnt/config/boot.conf`:
* `SECURITY_HARDENING_MODE=1`:
  * forces `WEB_MODE=full` (HTTPS)
  * blocks FTP/Telnet changes via UI/API
  * skips FTP/Telnet autostart at boot
  * stops FTP/Telnet services at runtime when policy is applied

### Maximum web CPU savings
For minimum web stack overhead while keeping core camera functionality:
* `WEB_MODE=ultra-lite`
* `LOW_CPU_PROFILE=1`
* `LOW_RAM_PROFILE=1`
* `SERVICE_TRIM=1`
* Keep only one browser tab open to the UI (live snapshot requests are the main web-side load).

When `LOW_CPU_PROFILE` or `SERVICE_TRIM` is active, the UI automatically slows polling/live-preview cadence to reduce CGI/webserver load.
The UI also applies dynamic throttling from live CPU/RAM pressure (high usage increases polling/live-preview intervals automatically).
`state.cgi` uses short-lived cache files in `/tmp` and now returns an enriched `statusline` payload (CPU/RAM/profile/LUM/AWB/UI mode/reboot epoch) so the frontend can use fewer CGI requests.

### Runtime self-heal and fallbacks
* `autorun.sh` now performs a small runtime self-heal at boot:
  * recreates `/mnt/lib/libcurl.so.4 -> /mnt/lib/libcurl.so.4.8.0` symlink when missing
  * uses extended `/mnt/bin/busybox` if available, with safe fallback to `/bin/busybox`
* `scripts/common_functions.sh` now routes BusyBox calls through a fallback wrapper (`/mnt/bin/busybox` -> `/bin/busybox` -> PATH).

## Safe package upgrade workflow (step-by-step)
Use this workflow when upgrading files in `/mnt/bin` and `/mnt/lib`.
It is designed to keep rollback immediate if a package swap fails.

### Stage 1: baseline snapshot (already included in this repo)
Baseline references are in:
* `upgrade/stage-01-baseline/manifest.sha256`
* `upgrade/stage-01-baseline/versions.txt`
* `upgrade/stage-01-baseline/abi.txt`
* `upgrade/stage-01-baseline/fork-package-hashes-2026-02-22.txt`

On the camera, baseline lock file template is:
* `config/packages.lock.dist`
  * auto-installed as `/mnt/config/packages.lock` on boot

### Stage 2: preflight candidate bundle on host
Candidate bundle layout must be:
* `<bundle>/bin/...`
* `<bundle>/lib/...`

Run compatibility gate before upload:
* `./tools/check_bundle_compat.sh /path/to/bundle`

This blocks bundles that:
* are not ARM EABI5 ELF
* use a different dynamic loader than `/lib/ld-uClibc.so.0`
* introduce new runtime `NEEDED` dependencies vs baseline
* include unknown file names not present in current baseline

### Stage 3: backup + apply on camera
Script:
* `/mnt/scripts/pkg-upgrade-safe.sh`

Commands:
* backup only:
  * `/mnt/scripts/pkg-upgrade-safe.sh backup`
* apply bundle:
  * `/mnt/scripts/pkg-upgrade-safe.sh apply /mnt/upgrade-bundle`
* status:
  * `/mnt/scripts/pkg-upgrade-safe.sh status`

Automatic behavior:
* per-upgrade backup is written to `/mnt/backup/package-upgrades/<backup_id>/`
* touched file list is written to `manifest.txt`
* `/mnt/config/packages.lock` is regenerated after successful apply
* if apply fails, automatic rollback is attempted immediately

### Stage 4: rollback (if needed)
Use backup id from apply output:
* `/mnt/scripts/pkg-upgrade-safe.sh rollback <backup_id>`

### Stage 5: post-upgrade validation
Recommended checks:
* web UI loads and auth works (`https://CAMERA-IP`)
* RTSP main/sub stream open
* ONVIF discovery and profile responses
* logs in `/mnt/log/startup.log` and `/mnt/log/pkg-upgrade.log`

### Notes on available package sets
As of **February 22, 2026**, the known TECKIN/AK3918 forks ship the same `bin/` and `lib/` package hashes as this repo baseline.
So safe upgrades currently require a separately built and validated ARM/uClibc bundle.

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

## Home Assistant and local automation
This project is designed for cloud-free LAN control and HA-friendly integrations.

### ONVIF/RTSP one-click client presets
In **Settings -> Video Settings -> Client preset**, you can apply:
* `HA Frigate`:
  * dual stream enabled
  * audio off by default
  * ONVIF policy set to `sub-primary`
* `NVR low-CPU`:
  * low bitrate/fps defaults
  * main stream only
  * ONVIF policy set to `main-only`
* `High quality`:
  * higher bitrate/fps defaults
  * dual stream + audio
  * ONVIF policy set to `main-primary`

### Motion Event API (local HTTP/HTTPS)
* Recent motion events JSON:
  * `cgi-bin/motionevents.cgi?limit=20`
  * optional filter: `type=motion_on` or `type=motion_off`
* Latest motion thumbnail JPEG:
  * `cgi-bin/motionthumb.cgi`
  * optional: `file=<snapshot_filename.jpg>`

Motion events are logged to `/mnt/log/motion-events.log`.

### MQTT Bridge (local broker)
Config file: `/mnt/config/mqtt.conf` (template: `config/mqtt.conf.dist`)

When enabled (`MQTT_ENABLE=1`), the bridge publishes:
* `<MQTT_TOPIC_ROOT>/health` (periodic device health)
* `<MQTT_TOPIC_ROOT>/event` (reboot/profile/web-mode/motion and other events)
* `<MQTT_TOPIC_ROOT>/availability` (`online`/`offline`, retained)

Optional Home Assistant auto-discovery:
* Enable `MQTT_HA_DISCOVERY_ENABLE=1` (default) to publish retained discovery configs under:
  * `<MQTT_HA_DISCOVERY_PREFIX>/sensor/<node>/.../config`
  * `<MQTT_HA_DISCOVERY_PREFIX>/button/<node>/.../config`
* Exposed HA entities include CPU, RAM, chip temperature, input voltage, estimated power, reboot button, snapshot button.

Command topic:
* `<MQTT_TOPIC_COMMAND>` (or default `<MQTT_TOPIC_ROOT>/command`)

Supported command payloads:
* `reboot`
* `snapshot`
* `profile:balanced`
* `profile:low-cpu`
* `profile:rtsp-only`

Power draw note:
* On-device power is estimated from configurable model values (`POWER_ESTIMATE_*`) and optional voltage sensor input (`POWER_SENSOR_PATH`).
* For true measured watts/amps, use an external USB power meter.
