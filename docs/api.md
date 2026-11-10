# TECKIN TC100 CGI API Reference

**Base URL:** `http://192.168.1.50/cgi-bin/` (plain HTTP only: 3.0 has no TLS; put a reverse proxy in front if you need HTTPS)

**Authentication:** HTTP Basic Auth (busybox httpd, user `root`, the camera password) — default `root:pass`. With no camera password set yet (before the setup wizard) the pages are open.

**CSRF:** All state-changing requests require the header `X-CSRF-Token: <token>`.
Fetch the token from `state.cgi?cmd=statusline` → field `csrf_token` (a per-boot hex string stored at `/tmp/csrf_token` on the camera).
Read-only endpoints and a small set of explicitly whitelisted action commands are exempt.

**Content negotiation:** Most endpoints that can return JSON do so when the request carries `Accept: application/json`.
Endpoints that return HTML (noted below) ignore that header.

---

## GET /cgi-bin/state.cgi

Read-only telemetry and configuration queries. No CSRF required.
Query string parameter: `cmd=<name>` (and optional per-command parameters).

### cmd=statusline

Returns a JSON object with the current system status line, including the CSRF token.

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `cpu` | string | CPU usage percentage |
| `ram` | string | RAM usage summary |
| `sd` | string | SD card usage summary |
| `perfprofile` | string | Active performance profile (`balanced`, `low-cpu`, `rtsp-only`) |
| `lum` | string | Current luminance reading |
| `awb` | string | Current white-balance reading |
| `ui_ultralite_mode` | string | `1` if ultra-lite UI is active |
| `web_mode` | string | `full`, `http`, `ultra-lite`, or `off` |
| `security_hardening_mode` | string | `1` if hardening is enabled |
| `mqtt_enabled` | string | `1` if MQTT bridge is active |
| `mqtt_last_pub_ts` | string | Unix timestamp of last MQTT publish |
| `mqtt_last_pub_ok` | string | `1` if last publish succeeded |
| `mqtt_refused` | number | CONNACK code of the last refused connection (4 bad user name or password, 5 not authorized), `0` otherwise |
| `default_password_active` | string | `1` if factory default password is still in use |
| `csrf_token` | string | Per-boot CSRF token — use as `X-CSRF-Token` header |
| `update_available` | string | `1` if an update is available |
| `update_latest_version` | string | Latest available version string |

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=statusline \
  -H "Accept: application/json"
```

---

### cmd=hostname

Returns the camera hostname as plain text (one line).

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=hostname
```

---

### cmd=lumawb

Returns two lines of plain text: current luminance value, then current AWB value.

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=lumawb
```

---

### cmd=sysusage

Returns a plain text system usage summary (CPU, RAM, uptime).

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=sysusage
```

---

### cmd=perfprofile

Returns the active performance profile name as plain text (`balanced`, `low-cpu`, or `rtsp-only`).

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=perfprofile
```

---

### cmd=healthsnapshot

Returns a comprehensive JSON health snapshot (cached for 3 seconds). Includes chip temperature, power telemetry, RTSP and ONVIF state, uptime, SD card read-only flag, and a copy of `csrf_token`.

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=healthsnapshot \
  -H "Accept: application/json"
```

---

### cmd=fullconfig

Returns a large JSON object with all configuration values across all UI tabs (video streams, audio, ISP, network, MQTT, automation, etc.). Intended for the frontend settings panels.

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=fullconfig \
  -H "Accept: application/json"
```

---

### cmd=integrationtest

Runs live integration probes (RTSP DESCRIBE, ONVIF health, MQTT publish, snapshot check) and returns a JSON object:

```json
{
  "overall_status": "ok|warn|error",
  "rtsp":   { "ok": true,  "detail": "..." },
  "onvif":  { "ok": false, "detail": "..." },
  "mqtt":   { "ok": true,  "detail": "..." },
  "snapshot": { "ok": true, "detail": "..." }
}
```

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=integrationtest \
  -H "Accept: application/json"
```

---

### cmd=integrationmanifest

Returns a large JSON manifest with all service URLs, RTSP/MQTT/ONVIF configuration, ready-to-paste Frigate YAML snippets, and Home Assistant discovery info.

**Optional parameter:**

| Parameter | Values | Description |
|---|---|---|
| `redact` | `1` | Redact credentials from the output |

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=integrationmanifest&redact=1" \
  -H "Accept: application/json"
```

---

### cmd=get_events

Returns a JSON array of recent system events from the event log.

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `since` | (none) | Unix timestamp; return only events after this time |
| `limit` | 50 | Maximum events to return (max 200) |

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=get_events&limit=100" \
  -H "Accept: application/json"
```

---

### cmd=list_presets

Returns a JSON array of saved SmartVBR/stream preset names stored in `/mnt/config/presets/`.

```sh
curl http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=list_presets \
  -H "Accept: application/json"
```

---

### cmd=load_preset

Loads a named preset and returns its stored values as `{"preset":{...}}`.

**Parameters:**

| Parameter | Required | Description |
|---|---|---|
| `name` | yes | Preset name (alphanumeric, `_`, `-`) |

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=load_preset&name=my_preset" \
  -H "Accept: application/json"
```

---

## POST/GET /cgi-bin/action.cgi

State-changing endpoint. All commands require `X-CSRF-Token` unless noted otherwise.

**Rate limits:**
- `reboot`, `shutdown`: 3 calls per 300 seconds
- All other commands: 20 calls per 60 seconds

**Exempt from CSRF** (read-only or safe): `showlog`, `get_ptt_vol`, `get_ptt_status`, `wifi_scan`, `wifi_get_ssid`

All commands are audited to `/tmp/log/audit.log`.

---

### cmd=showlog *(read-only, no CSRF)*

Returns an HTML `<pre>` block with recent log contents.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `logname` | `1` | System log (`/var/log/messages`) |
| `logname` | `2` | Kernel ring buffer (`dmesg`) |
| `logname` | `3` | Video server log (`/tmp/logs/tc100_rtsp.log`) |

**Response:** `text/html`

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=showlog&logname=1"
```

---

### cmd=clearlog

Clears the specified log file.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `logname` | `1`, `2`, `3` | Same as `showlog` |

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=clearlog&logname=1" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=set_video_params

Applies video encoder parameters to one or both RTSP streams and schedules an RTSP server restart. Geometry and codec values are normalized to encoder-safe combinations.

**Parameters (all optional — pass only what you want to change):**

| Parameter | Description |
|---|---|
| `stream` | Target stream index: `0` (main) or `1` (sub) |
| `video_size0` | Main stream size: `1920x1080` (default) or `1280x720` (the whole picture scaled down by the ISP; needs a kernel with `ak39_vi.main_scale`, 3.0.1-rc27 or later, else 1080p is kept). Stored as `[0] mainres` (`720` / `1080`) of `rtspserver.conf` |
| `video_size1` | Sub stream resolution, e.g. `352x200` |
| `fps0` / `fps1` | Frame rate 1–25 |
| `brbitrate0` | Main bitrate kbps (64–12000) |
| `brbitrate1` | Sub bitrate kbps (64–4000) |
| `video_codec0` / `video_codec1` | `0`=H.264, `2`=H.265 |
| `goplen0` / `goplen1` | GOP length 1–120 |
| `vbr0` | Active global bitrate mode, accepted with `stream=0`: `0`=CBR or `1`=VBR; applies to both streams unless `RTSP_VBR_SUB` overrides the sub-stream in `rtsp.env` |
| `smart0` | Accepted with `stream=0`. Global mode: `0`=off, `1`=LTR, `2`=variable GOP; applies to both streams unless overridden by `RTSP_SMART_SUB` in `rtsp.env`; requires VBR. Mode 1 needs the 12 MB encoder pool. Mode 2 requires `RTSP_SMART_FORCE=1` and is unsafe on this camera. |
| `video_format0` / `video_format1`, `smartmode0` / `smartmode1` | Legacy parameters retained for older clients; ignored by the free RTSP encoder |
| `minqp0` / `minqp1` | Minimum QP 1–51 |
| `maxqp0` / `maxqp1` | Maximum QP 1–51 |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_video_params" \
  --data-urlencode "video_size0=1280x720" \
  --data-urlencode "fps0=20" \
  --data-urlencode "video_codec0=0"
```

---

### cmd=set_video_size

Full video parameter replacement for both streams. Supersedes `set_video_params` for bulk updates. Applies geometry normalization and codec profile validation; rolls back automatically if the new stream fails health checks.

**Parameters:**

| Parameter | Description |
|---|---|
| `video_size0` | Main resolution `WxH` (normalized to safe H.264/H.265 dimensions) |
| `video_size1` | Sub resolution `WxH` |
| `video_codec0` / `video_codec1` | `0`=H.264, `2`=H.265 |
| `codec_profile0` / `codec_profile1` | Codec profile (sanitized per codec) |
| `fps0` / `fps1` | Frame rate 1–25 |
| `brbitrate0` | Main bitrate kbps (64–12000, default 2000) |
| `brbitrate1` | Sub bitrate kbps (64–4000, default 300) |
| `vbr0` | Active global bitrate mode: `0`=CBR or `1`=VBR; omitted means keep the current setting |
| `smart0` | Active global Smart mode: `0`=off, `1`=LTR, `2`=variable GOP; omitted means keep the current setting |
| `video_format0` / `video_format1`, `smartmode0` / `smartmode1` | Legacy parameters retained for older clients; ignored by the free RTSP encoder |
| `goplen0` / `goplen1` | GOP length 1–120 |
| `minqp0` / `minqp1` | Minimum QP 1–51 |
| `maxqp0` / `maxqp1` | Maximum QP 1–51 |
| `smartgoplen*`, `smartquality*`, `smartstatic*`, `maxkbps*`, `targetkbps*` | Legacy tuning metadata kept for configuration compatibility; these `rtspserver.conf` fields do not tune the free encoder. Expert Smart tuning uses `RTSP_SMART_GOP`, `RTSP_SMART_Q`, and `RTSP_SMART_V` in `rtsp.env` |
| `videouser` / `videopassword` | RTSP credentials (URL-encoded) |
| `videoport` | RTSP port 1–65535 |

**Response:** HTML — notes any normalization that was applied; confirms rollback if health check fails.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_video_size" \
  --data-urlencode "video_size0=1920x1080" \
  --data-urlencode "video_codec0=0" \
  --data-urlencode "fps0=15" \
  --data-urlencode "brbitrate0=2000"
```

---

### cmd=conf_audioin

Configures audio input (microphone) and schedules an RTSP restart.

**Parameters:**

| Parameter | Range | Description |
|---|---|---|
| `samplerate` | 8000–48000 | Audio sample rate (Hz) |
| `audioinVol` | 0–12 | Microphone gain |
| `audioCodec0` | 0–18 | Audio codec index for stream 0 |
| `audioCodec1` | — | Audio codec index for stream 1 |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_audioin" \
  --data-urlencode "samplerate=16000" \
  --data-urlencode "audioinVol=6" \
  --data-urlencode "audioCodec0=0"
```

---

### cmd=isp_pro

Applies ISP (image signal processor) parameters immediately via `setconf`.

**Parameters:**

| Parameter | Description |
|---|---|
| `daynightlum` | Luma threshold to switch day→night |
| `daynightawb` | AWB threshold to switch day→night |
| `nightdaylum` | Luma threshold to switch night→day |
| `nightdayawb` | AWB threshold to switch night→day |
| `osdenabled` | `1`/`0` — enable OSD overlay |
| `osdtext` | OSD text string |
| `osdfontsize0` | OSD font size for stream 0 |
| `osdx0` / `osdy0` | OSD X/Y position for stream 0 |
| `osdalpha` | OSD transparency (0–255) |
| `frontcolor` | OSD foreground color (hex) |
| `backcolor` | OSD background color (hex) |
| `edgecolor` | OSD edge/shadow color (hex) |
| `imageFlip` | `0`=normal, `1`=flip horizontal, `2`=flip vertical, `3`=rotate 180° |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=isp_pro" \
  --data-urlencode "imageFlip=0" \
  --data-urlencode "osdenabled=1" \
  --data-urlencode "osdtext=CAM-01"
```

---

### cmd=osd

Configures OSD (on-screen display) overlay for both streams.

**Parameters:**

| Parameter | Description |
|---|---|
| `OSDenable` | `1`/`0` |
| `osdtext` | Display text |
| `frontcolor` | Foreground color (hex) |
| `backcolor` | Background color (hex) |
| `edgecolor` | Edge color (hex) |
| `alpha` | Transparency |
| `OSDSize0` / `OSDSize1` | Font size for stream 0 / 1 |
| `posx0` / `posy0` | Position for stream 0 |
| `posx1` / `posy1` | Position for stream 1 |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=osd" \
  --data-urlencode "OSDenable=1" \
  --data-urlencode "osdtext=FrontDoor"
```

---

### cmd=image-flip

Sets the image flip/rotation mode immediately.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `flipValue` | `0` | Normal |
| `flipValue` | `1` | Horizontal flip |
| `flipValue` | `2` | Vertical flip |
| `flipValue` | `3` | 180° rotation |

**Response:** HTML or JSON

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=image-flip" \
  --data-urlencode "flipValue=3"
```

---

### cmd=set_network

Updates hostname, RTSP port, and Telnet port.

**Parameters:**

| Parameter | Range | Description |
|---|---|---|
| `hostname` | alphanumeric+hyphen | Camera hostname |
| `rtsp_port` | 1–65535 | RTSP server port (default 554) |
| `telnet_port` | 1–65535 | Telnet server port (default 23) |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_network" \
  --data-urlencode "hostname=tc100-front" \
  --data-urlencode "rtsp_port=554"
```

---

### cmd=set_reboot_schedule

Configures an optional daily/weekly scheduled reboot via cron.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `reboot_enable` | `1`/`0` | Enable scheduled reboot |
| `reboot_hour` | 0–23 | Hour of reboot (default 4) |
| `reboot_min` | 0–59 | Minute of reboot (default 0) |
| `reboot_dow` | `*`, `0`–`6`, `1-5`, `0,6` | Day(s) of week (`*`=daily, `1-5`=weekdays, `0,6`=weekends) |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_reboot_schedule" \
  --data-urlencode "reboot_enable=1" \
  --data-urlencode "reboot_hour=3" \
  --data-urlencode "reboot_min=30" \
  --data-urlencode "reboot_dow=*"
```

---

### cmd=set_advanced_tuning

Configures advanced system parameters: web UI mode, security hardening, NTP, and the memory guard daemon thresholds.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `lightweight_mode` | `1`/`0` | Enable lightweight boot profile |
| `ui_ultralite_mode` | `1`/`0` | Switch frontend to ultra-lite HTML mode |
| `security_hardening_mode` | `1`/`0` | Enable security hardening (blocks Telnet/FTP) |
| `enable_ntp` | `1`/`0` | Enable NTP time sync at boot |
| `ntp_one_shot` | `1`/`0` | Run a one-shot NTP sync now |
| `mem_guard_enable` | `1`/`0` | Enable memory guard daemon |
| `mem_guard_interval_seconds` | integer | Poll interval (seconds) |
| `mem_guard_warn_kb` | integer | Warn threshold (free KB) |
| `mem_guard_critical_kb` | integer | Critical threshold (free KB) |
| `mem_guard_recovery_margin_kb` | integer | Recovery margin (KB) |
| `mem_guard_warn_hits` | integer | Consecutive hits before warn action |
| `mem_guard_critical_hits` | integer | Consecutive hits before critical action |
| `mem_guard_cooldown_seconds` | integer | Cooldown between recovery actions |
| `mem_guard_emergency_kb` | integer | Emergency threshold triggering hard recovery |
| `mem_guard_drop_caches` | `1`/`0` | Drop kernel caches on recovery |
| `rtsp_healthcheck_timeout_seconds` | integer | RTSP health probe timeout |
| `onvif_healthcheck_timeout_seconds` | integer | ONVIF health probe timeout |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_advanced_tuning" \
  --data-urlencode "mem_guard_enable=1" \
  --data-urlencode "mem_guard_warn_kb=8192" \
  --data-urlencode "mem_guard_critical_kb=4096"
```

---

### cmd=wifi_set_country

Sets the Wi-Fi 2-letter ISO regulatory country code (e.g. `FR`, `US`, `DE`). Updates `WIFI_COUNTRY` in `boot.conf` and applies regulatory domain limits at runtime.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `country` | `[A-Z]{2}` | 2-letter country code |

**Response:** JSON / HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=wifi_set_country" \
  --data-urlencode "country=FR"
```

---

### cmd=wifi_country_info

*(read-only, no CSRF)* The Wi-Fi country of `boot.conf` (`WIFI_COUNTRY`, empty = world rules), the one the kernel
applies now (`"00"` = world rules) and whether the regulatory database is present.

**Response (JSON):**
```json
{"status":"success","country":"FR","effective":"FR","regdb":1}
```

---

### cmd=wifi_rescue_info *(read-only, no CSRF)*

The rescue access point (`scripts/wifi-rescue.sh`): whether it is enabled (`WIFI_RESCUE`), up now, its name and
password, and its address. The response carries the access point password: do not log it.

**Response (JSON):** `{"status":"success","enabled":1,"ap":0,"ssid":"...","psk":"...","address":"10.42.0.1"}`

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=wifi_rescue_info"
```

---

### cmd=set_performance_profile

Switches the active performance profile. Triggers an automatic health-checked rollback if the stream fails within the probe window.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `performance_profile` | `balanced` | Default — all services, dual stream |
| `performance_profile` | `low-cpu` | Reduced services, conservative encoding |
| `performance_profile` | `rtsp-only` | Strips all non-RTSP services |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_performance_profile" \
  --data-urlencode "performance_profile=low-cpu"
```

---

### cmd=set_stream_topology

Sets which streams and audio tracks the RTSP server exposes. Applies with rollback on health check failure.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `stream_topology` | `dual-audio` | Main + sub streams, both with audio |
| `stream_topology` | `dual-no-audio` | Main + sub, no audio |
| `stream_topology` | `main-audio` | Main stream only, with audio |
| `stream_topology` | `main-only` | Main stream only, no audio |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_stream_topology" \
  --data-urlencode "stream_topology=dual-audio"
```

---

### cmd=set_onvif_stream_policy

Controls which RTSP stream ONVIF reports as primary/secondary.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `onvif_stream_policy` | `main-primary` | Main=profile 1, Sub=profile 2 |
| `onvif_stream_policy` | `sub-primary` | Sub=profile 1, Main=profile 2 |
| `onvif_stream_policy` | `sub-only` | ONVIF exposes sub stream only |
| `onvif_stream_policy` | `main-only` | ONVIF exposes main stream only |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_onvif_stream_policy" \
  --data-urlencode "onvif_stream_policy=main-primary"
```

---

### cmd=set_rtsp_preset

Applies predefined bitrate presets to both streams.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `preset` | `full` | High-quality bitrates |
| `preset` | `medium` | Balanced bitrates |
| `preset` | `low` | Low-bandwidth bitrates |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_rtsp_preset" \
  --data-urlencode "preset=medium"
```

---

### cmd=set_rtsp_quality_profile

Applies a named RTSP quality profile that sets codec, resolution, bitrate, and QP ranges.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `rtsp_quality_profile` | `max-quality-h264` | Best H.264 quality |
| `rtsp_quality_profile` | `max-quality-hevc` | Best H.265 quality |
| `rtsp_quality_profile` | `max-main-h264` | Maximum resolution H.264 |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_rtsp_quality_profile" \
  --data-urlencode "rtsp_quality_profile=max-quality-h264"
```

---

### cmd=set_client_profile

Applies a named compatibility preset optimized for a specific NVR or integration client.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `client_profile` | `universal-h264` | Broad compatibility H.264 |
| `client_profile` | `frigate-light-ak3918` | Frigate léger pour AK3918 : H.265 720p/12 fps + détection H.265 360p/8 fps |
| `client_profile` | `frigate-balanced` | Frigate balanced (recommended) |
| `client_profile` | `frigate-low-bandwidth` | Frigate low-bandwidth |
| `client_profile` | `frigate-quality` | Frigate high-quality |
| `client_profile` | `hybrid-hevc-main` | H.265 main + H.264 sub |
| `client_profile` | `legacy-main-only` | Single H.264 stream for legacy NVRs |
| `client_profile` | `nvr-low-cpu` | Low-CPU NVR mode |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_client_profile" \
  --data-urlencode "client_profile=frigate-balanced"
```

---

### cmd=save_known_good_profile

Saves a snapshot of the current RTSP configuration and stream state as the "known-good" baseline (used by `restore_known_good_profile` for safe rollback).

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=save_known_good_profile"
```

---

### cmd=restore_known_good_profile

Restores the RTSP configuration from the last saved known-good snapshot and restarts the stream.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=restore_known_good_profile"
```

---

### cmd=rtsp_server_info *(read-only, no CSRF)*

State of the RTSP server `tc100_rtsp`: sub-stream and two-way audio switches (`boot.conf`), port, number of established
client connections, idle frame rate and whether motion detection is running.

**Response (JSON):**
```json
{"ok":true,"server":"tc100_rtsp","substream":1,"talk":1,"port":554,"clients":0,"idle_fps":0,"idle_after":10,"motion_detection":0}
```

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=rtsp_server_info"
```

---

### cmd=set_rtsp_server

Settings -> Video switches, saved to `boot.conf`. Changing the sub-stream restarts the stream (about 2 s later);
two-way audio and idle frame rate are read live.

**Parameters:**

| Parameter | Description |
|---|---|
| `rtsp_substream` | `1`/`0` - 640x360 sub-stream (`RTSP_SUBSTREAM`) |
| `rtsp_talk` | `1`/`0` - two-way audio, ONVIF backchannel (`RTSP_LITE_TALK`) |
| `rtsp_idle_fps` | 0-24 - lower frame rate while nothing moves, 0 = off (`IDLE_FPS`); written only when sent |
| `rtsp_idle_after` | 1-3600 - seconds without motion before the lower rate (`IDLE_AFTER`, default 10) |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_rtsp_server" \
  --data-urlencode "rtsp_substream=1" \
  --data-urlencode "rtsp_talk=1" \
  --data-urlencode "rtsp_idle_fps=5" \
  --data-urlencode "rtsp_idle_after=10"
```

---

### cmd=set_frigate_live

Saves the link of the "smooth live view" to this camera in Frigate's own page (`config/frigate_live.conf`). An empty
`frigate_url` removes the link. When `frigate_camera` is empty the camera looks it up in Frigate's `/api/config` by its IP.

**Parameters:**

| Parameter | Description |
|---|---|
| `frigate_url` | Frigate address, e.g. `http://192.168.1.20:5000` (`http://` added when missing) |
| `frigate_camera` | Frigate camera name: letters, digits, `-`, `_` |

**Response:** HTML text (`Smooth live view: ...`), or JSON `INVALID_VALUE` on a bad address or name

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_frigate_live" \
  --data-urlencode "frigate_url=http://192.168.1.20:5000" \
  --data-urlencode "frigate_camera=tc100"
```

---

### cmd=set_mqtt_config

Configures the MQTT bridge. Changes take effect after an async MQTT service restart.

**Parameters:**

| Parameter | Description |
|---|---|
| `mqtt_enable` | `1`/`0` — enable MQTT bridge |
| `mqtt_host` | Broker hostname or IP |
| `mqtt_port` | Broker port (default 1883) |
| `mqtt_user` | Broker username |
| `mqtt_password` | Broker password |
| `mqtt_client_id` | MQTT client identifier |
| `mqtt_topic_root` | Root topic prefix (e.g. `homeassistant/camera/tc100`) |
| `mqtt_topic_command` | Command topic suffix |
| `mqtt_qos` | QoS level 0–2 |
| `mqtt_health_interval_seconds` | Health publish interval |
| `ha_discovery_enable` | `1`/`0` — enable HA discovery |
| `ha_discovery_prefix` | HA discovery prefix (default `homeassistant`) |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_mqtt_config" \
  --data-urlencode "mqtt_enable=1" \
  --data-urlencode "mqtt_host=192.168.1.2" \
  --data-urlencode "mqtt_port=1883" \
  --data-urlencode "ha_discovery_enable=1"
```

---

### cmd=refresh_ha_discovery

Republishes Home Assistant MQTT discovery messages immediately.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=refresh_ha_discovery"
```

---

### cmd=pair_home_assistant

One-click pairing with a Home Assistant MQTT broker. Writes MQTT config, optionally applies a stream profile, and optionally enables MQTT autostart.

**Parameters:**

| Parameter | Description |
|---|---|
| `ha_broker_host` | HA MQTT broker IP or hostname |
| `ha_broker_port` | Broker port (default 1883) |
| `ha_user` | Broker username |
| `ha_password` | Broker password |
| `ha_client_id` | Client identifier |
| `ha_topic_root` | MQTT topic root |
| `ha_discovery_prefix` | HA discovery prefix |
| `ha_profile` | Optional client preset to apply (see `set_client_profile` values) |
| `ha_enable_onvif` | `1`/`0` — enable ONVIF after pairing |
| `ha_enable_mqtt_autostart` | `1`/`0` — start MQTT bridge at boot |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=pair_home_assistant" \
  --data-urlencode "ha_broker_host=192.168.1.2" \
  --data-urlencode "ha_profile=frigate-balanced" \
  --data-urlencode "ha_enable_mqtt_autostart=1"
```

---

### cmd=set_led_config

Saves LED enable/disable preferences to `/mnt/config/boot.conf`.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `led_front` | `1`/`0` | Front activity LED |
| `led_red` | `1`/`0` | Red status LED |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_led_config" \
  --data-urlencode "led_front=1" \
  --data-urlencode "led_red=0"
```

---

### cmd=hw_state *(read-only, no CSRF)*

Live state of the parts the Hardware test page shows (`www/hardware.html`): the blue and red LEDs, the IR LEDs, the
IR-cut filter (`1` = in, day), whether the automatic day/night runs, the microphone level in dBFS (only while the sound
detection writes it, less than 10 s old) and the reset button (`true` = pressed). `null` when the camera cannot tell.

**Response (JSON):**
```json
{"ok":true,"front_led":false,"red_led":false,"ir_led":false,"ir_cut":1,"auto_daynight":true,"sound_db":-48,"button":false}
```

---

### cmd=front_led_on / cmd=front_led_off

Immediately turns the front activity LED on or off.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=front_led_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=red_led_on / cmd=red_led_off

Immediately turns the red status LED on or off.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=red_led_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=ir_led_on / cmd=ir_led_off

Immediately turns the infrared LED on or off.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=ir_led_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=ir_cut_on / cmd=ir_cut_off

Activates or deactivates the IR-cut filter (switches between color and night-vision mode).

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=ir_cut_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=night-mode-on / cmd=night-mode-off

Switches the camera to night (IR) mode or back to day mode.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=night-mode-on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=auto_night_mode_start / cmd=auto_night_mode_stop

Starts or stops the automatic day/night detection service.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=auto_night_mode_start" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=toggle-rtsp-nightvision-on / cmd=toggle-rtsp-nightvision-off

Toggles night-vision mode on the RTSP stream (IR illumination + IR-cut state) without changing the auto-detection daemon.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=toggle-rtsp-nightvision-on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=rtsp-log-on / cmd=rtsp-log-off

Enables or disables verbose RTSP server logging.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=rtsp-log-on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=motion_detection_on / cmd=motion_detection_off

Starts or stops the motion detection service.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=motion_detection_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=conf_motiondetect

Sets motion detection sensitivity and optional LED blink on motion.

**Parameters:**

| Parameter | Description |
|---|---|
| `mdsens` | Sensitivity level (passed directly to `setconf` and `rtspserver.conf`) |
| `motionBlink` | `1`/`0` — blink red LED on motion |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_motiondetect" \
  --data-urlencode "mdsens=50" \
  --data-urlencode "motionBlink=1"
```

---

### cmd=md_zones_info *(read-only, no CSRF)*

The saved motion zones (`config/motion_zones.conf`, up to 4 rectangles `x1,y1,x2,y2` that motion detection ignores), their
names, whether motion detection is on, and what the detector got at its last start.

**Response (JSON):**
```json
{"ok":true,"zones":["0,0,20,30"],"names":["tree"],"enabled":1,"detector":{"grid":"...","ignored":2,"result":"..."}}
```

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=md_zones_info"
```

---

### cmd=motion_heatmap *(read-only, no CSRF)*

Motion events per hour over the last 24 hours (from `scripts/motion-heatmap.sh`; all zeros when the script is absent).

**Response (JSON):** `{"ok":true,"current_hour":14,"total_24h":37,"hourly":[...24 numbers...]}`

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=motion_heatmap"
```

---

### cmd=events_info *(read-only, no CSRF)*

The alert settings of Settings -> Events as JSON: `notify` (`config/notify.conf`: webhook, Ntfy, Telegram switch, snapshot
attachment, cooldown, event list), `tamper` (`config/tamper.conf` and whether tamper is active now) and `sound` (Vox and
alarm options of `config/sound_detection.conf`). Secrets are never sent back: only `ntfy_auth_set` and `telegram_ready`.

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=events_info"
```

---

### cmd=set_notify_config

Saves the alert channels to `config/notify.conf`. Validated: webhook and Ntfy server must start with `http://` or
`https://` and hold no spaces or quotes; Ntfy topic is letters, digits, `-` and `_` (64 at most); a channel cannot be
enabled without its address or topic.

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `webhook_enable` | `0` | `1`/`0` |
| `webhook_url` | empty | Webhook address |
| `webhook_method` | `POST` | `POST` or `PUT` |
| `ntfy_enable` | `0` | `1`/`0` |
| `ntfy_url` | `https://ntfy.sh` | Ntfy server |
| `ntfy_topic` | empty | Ntfy topic |
| `ntfy_priority` | `default` | `min`, `low`, `default`, `high`, `urgent` |
| `ntfy_auth` | empty | Ntfy access token; empty keeps the saved one, `-` removes it |
| `telegram_notify_enable` | `0` | Send alerts through the Telegram bot (`set_telegram_config`) |
| `notify_attach_snapshot` | `0` | Attach a picture |
| `notify_cooldown` | `15` | Seconds between two alerts, 0-3600 |
| `notify_event_motion`, `notify_event_sound`, `notify_event_tamper` | `0` | Events that raise an alert |

**Response:** JSON (`Alerts saved.`) or `INVALID_VALUE`

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_notify_config" \
  --data-urlencode "ntfy_enable=1" \
  --data-urlencode "ntfy_topic=mycam" \
  --data-urlencode "notify_event_motion=1" \
  --data-urlencode "notify_attach_snapshot=1" \
  --data-urlencode "notify_cooldown=30"
```

---

### cmd=set_tamper_config

Tamper (covered or moved lens) detection, saved to `config/tamper.conf`. Turning it on or off registers or removes the
`tamper-detect` housekeeper job at once.

**Parameters:**

| Parameter | Default | Range | Description |
|---|---|---|---|
| `tamper_enable` | `0` | `1`/`0` | |
| `tamper_hold` | `6` | 2-120 | Seconds the condition must last |
| `tamper_drop_pct` | `50` | 10-90 | Picture size drop (percent) that counts |
| `tamper_luma_min` | `15` | 0-100 | Brightness below which the lens counts as covered |

**Response:** JSON

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_tamper_config" \
  --data-urlencode "tamper_enable=1" \
  --data-urlencode "tamper_hold=6"
```

---

### cmd=set_sound_options

Vox (baby monitor) and alarm-sound tracking options, saved to `config/sound_detection.conf`; they act while sound
detection is on (`set_sound_detection`). No restart needed.

**Parameters:**

| Parameter | Default | Range | Description |
|---|---|---|---|
| `vox_mode` | `0` | `1`/`0` | Vox mode |
| `vox_hold` | `5` | 1-600 | Seconds to hold after the last sound |
| `alarm_detect` | `0` | `1`/`0` | Recognise alarm sounds |
| `alarm_hold` | `15` | 5-120 | Seconds |
| `min_loud` | `1` | 1-10 | Seconds a sound must last |

**Response:** JSON

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_sound_options" \
  --data-urlencode "vox_mode=1" \
  --data-urlencode "vox_hold=5"
```

---

### cmd=service_trim_on / cmd=service_trim_off

Stops (trim) or re-enables all non-essential services to free resources. Useful for temporary CPU/RAM relief without a full profile change.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=service_trim_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=set_http_password

Sets the web login password (busybox httpd, user `root`): `scripts/common_functions.sh` `http_password` runs `v3/linux66-sd/web-auth`, which rewrites `/etc/httpd.conf` (MD5 crypt hash when httpd can make one). It applies at once and does not touch `config/user.pwd`, RTSP, FTP or telnet; use `set_all_password` for those too.

**Parameters (one required):**

| Parameter | Description |
|---|---|
| `password` | New password |
| `httppassword` | Alternative parameter name for new password |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_http_password" \
  --data-urlencode "password=mynewpass"
```

---

### cmd=set_all_password

Sets one password for the web interface, the system `root` account, RTSP, FTP and telnet (writes `config/user.pwd` and `rtspserver.conf`, restarts FTP, telnet and RTSP). Refused: fewer than 4 characters, or spaces, quotes, `%`, `$`, backquote or backslash.

**Parameters (one required):**

| Parameter | Description |
|---|---|
| `password` | New password |
| `allpassword` | Alternative parameter name |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_all_password" \
  --data-urlencode "password=newunifiedpass"
```

---

### cmd=set_telnet

Sets the Telnet port. Blocked when security hardening mode is active.

**Parameters:**

| Parameter | Description |
|---|---|
| `telnetport` | Port number |

**Response:** JSON or HTML

---

### cmd=set_ftp

Sets the FTP port. Blocked when security hardening mode is active.

**Parameters:**

| Parameter | Description |
|---|---|
| `ftpport` | Port number |

**Response:** JSON or HTML

---

### cmd=settz

Sets the timezone, NTP server, and hostname. Returns HTML.

**Parameters:**

| Parameter | Description |
|---|---|
| `ntp_srv` | NTP server hostname or IP |
| `tz` | POSIX timezone string (e.g. `CET-1CEST,M3.5.0,M10.5.0/3`) |
| `hostname` | Camera hostname |

**Response:** HTML only

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=settz" \
  --data-urlencode "ntp_srv=pool.ntp.org" \
  --data-urlencode "tz=CET-1CEST,M3.5.0,M10.5.0/3" \
  --data-urlencode "hostname=tc100"
```

---

### cmd=audio_test

Plays a test tone through the camera speaker.

**Parameters:**

| Parameter | Description |
|---|---|
| `audioSource` | Audio source identifier |
| `audiotestVol` | Volume 0–100 |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=audio_test" \
  --data-urlencode "audiotestVol=80"
```

---

### cmd=set_telegram_config

Configures the Telegram bot notification integration.

**Parameters:**

| Parameter | Description |
|---|---|
| `telegram_enable` | `1`/`0` |
| `telegram_token` | Bot API token |
| `telegram_chat_id` | Target chat ID |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_telegram_config" \
  --data-urlencode "telegram_enable=1" \
  --data-urlencode "telegram_token=123456:ABC..." \
  --data-urlencode "telegram_chat_id=-100123456"
```

---

### cmd=set_syslog_config

Configures remote syslog forwarding.

**Parameters:**

| Parameter | Description |
|---|---|
| `syslog_enable` | `1`/`0` |
| `syslog_host` | Remote syslog server IP or hostname |
| `syslog_port` | UDP port (default 514) |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_syslog_config" \
  --data-urlencode "syslog_enable=1" \
  --data-urlencode "syslog_host=192.168.1.10" \
  --data-urlencode "syslog_port=514"
```

---

### cmd=conf_ptt

Sets the push-to-talk speaker volume.

**Parameters:**

| Parameter | Range | Description |
|---|---|---|
| `audiooutVol` | 0–100 | Output volume (stored in `pttvolume.conf`) |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_ptt" \
  --data-urlencode "audiooutVol=75"
```

---

### cmd=get_ptt_vol *(read-only, no CSRF)*

Returns the current push-to-talk volume setting.

**Response:** JSON or plain text — `{"volume": N}`

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=get_ptt_vol"
```

---

### cmd=get_ptt_status *(read-only, no CSRF)*

Returns the PTT backend status (whether the patched `/mnt/bin/ak_ao_ptt` player is available and idle/busy).

**Response:** JSON or plain text

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=get_ptt_status"
```

---

### cmd=play_sound

Plays a built-in clip (`sounds/<name>.pcm`, looked up in `/mnt/sounds/`) through the speaker, in the background
(`scripts/speaker-play.sh`). The name is stripped to letters, digits, `_` and `-`.

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `sound` | `chime` | Clip name without extension (`chime`, `siren`, `alert`, `startup`, ...) |
| `volume` | `90` | 0-100 |

**Response:** JSON or HTML. Error code `SOUND_NOT_FOUND` when the clip or the speaker script is missing.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=play_sound" \
  --data-urlencode "sound=chime" \
  --data-urlencode "volume=80"
```

---

### cmd=set_sound_detection

Turns the microphone sound detection on or off and sets its trigger level (`config/sound_detection.conf`).

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `sound_det_enable` | `0` | `1`/`0` |
| `sound_det_threshold` | `-24` | Trigger level in dBFS |
| `sound_det_interval` | `2` | Check interval, 1-300 s |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_sound_detection" \
  --data-urlencode "sound_det_enable=1" \
  --data-urlencode "sound_det_threshold=-24" \
  --data-urlencode "sound_det_interval=2"
```

---

### cmd=set_local_recording

Local backup recording to the SD card (`tc100_rtsp`), saved to `boot.conf`; `tc100_rtsp` reads it live (no restart).

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `rec_local` | `0` | `1`/`0` (`REC_LOCAL`) |
| `rec_when` | `offline` | `always`, `motion` or `offline` (no RTSP client) |
| `rec_stream` | `main` | `main` or `sub` |
| `rec_segment_min` | `5` | Segment length in minutes, 1-60 |
| `rec_reserve_mb` | `256` | Free space kept on the card, 32-8192 MB |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_local_recording" \
  --data-urlencode "rec_local=1" \
  --data-urlencode "rec_when=motion" \
  --data-urlencode "rec_stream=main" \
  --data-urlencode "rec_segment_min=5" \
  --data-urlencode "rec_reserve_mb=256"
```

---

### cmd=local_rec_status *(read-only, no CSRF)*

Local recording settings and live state (state, current file, files, free MB, RTSP client, storage `sd`/`flash`, card present, paused).

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=local_rec_status"
```

---

### cmd=sd_card_info *(read-only, no CSRF)*

Describes the SD card (via `v3/linux66-sd/sdinfo-sd.sh`): `present`, `id`, `size_mb`, `fs`, `kind`, `mounted`, `free_mb`,
`prompt`, `health`, `rec_local`, `storage`.

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=sd_card_info"
```

---

### cmd=sd_card_mount / cmd=sd_card_check / cmd=sd_card_repair

`sd_card_mount` mounts a card inserted after boot on `/mnt/sd` (JSON ok, or `SD_MOUNT` when it has boot files or no
FAT32/exFAT file system). `sd_card_check` and `sd_card_repair` run `scripts/sd-diag.sh check|repair` and return its output.
CSRF required.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=sd_card_mount"
```

---

### cmd=local_rec_eject / cmd=local_rec_resume

Pauses local recording and releases the card so it can be removed (`eject`), or takes it back (`resume`), through
`scripts/rec-storage.sh`. **Response:** JSON ok, or `REC_STORAGE` with the script's message. CSRF required.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=local_rec_eject"
```

---

### cmd=conf_dns

Sets DNS resolver addresses. Applied immediately to `/etc/resolv.conf` (permanent after reboot via `dns.conf`).

**Parameters:**

| Parameter | Description |
|---|---|
| `dns_primary` | Primary DNS (dotted-quad IPv4, or empty to clear) |
| `dns_secondary` | Secondary DNS (dotted-quad IPv4, or empty to clear) |

**Response:** JSON or HTML — error codes: `INVALID_DNS`

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_dns" \
  --data-urlencode "dns_primary=1.1.1.1" \
  --data-urlencode "dns_secondary=8.8.8.8"
```

---

### cmd=conf_static_ip

Sets the IP addressing mode. Takes effect after reboot.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `ip_mode` | `dhcp` | Use DHCP (default) |
| `ip_mode` | `static` | Use static IP |
| `static_ip` | dotted-quad | Static IP address (required if `ip_mode=static`) |
| `static_netmask` | dotted-quad | Subnet mask (default `255.255.255.0`) |
| `static_gateway` | dotted-quad | Default gateway |

**Response:** HTML — error codes: invalid IP/netmask/gateway

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_static_ip" \
  --data-urlencode "ip_mode=static" \
  --data-urlencode "static_ip=192.168.1.50" \
  --data-urlencode "static_netmask=255.255.255.0" \
  --data-urlencode "static_gateway=192.168.1.1"
```

---

### cmd=wifi_scan *(read-only, no CSRF)*

Scans for nearby Wi-Fi networks and returns an HTML table (`<table>`) with SSID, signal level, and encryption status. Does not support JSON response format.

**Response:** HTML table fragment

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=wifi_scan"
```

---

### cmd=wifi_get_ssid *(read-only, no CSRF)*

Returns the currently configured Wi-Fi SSID from `wpa_supplicant.conf`.

**Response:** `{"status":"success","ssid":"<name>"}`

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=wifi_get_ssid"
```

---

### cmd=wifi_set_config

Writes a new `wpa_supplicant.conf` with the supplied SSID and PSK, then calls `wpa_cli reconfigure` to reconnect.

**Parameters:**

| Parameter | Constraints | Description |
|---|---|---|
| `ssid` | 1–32 chars, no `"` or `\` | Wi-Fi SSID |
| `psk` | 8–63 chars, no `"` or `\` | WPA2 pre-shared key |

**Response:** `{"status":"success","message":"..."}` or error code `INVALID_SSID`, `INVALID_PSK`, `WRITE_ERROR`

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=wifi_set_config" \
  --data-urlencode "ssid=MyNetwork" \
  --data-urlencode "psk=MyPassphrase"
```

---

### cmd=save_preset

Saves a named UI/stream preset as a JSON file in `/mnt/config/presets/`. Maximum 10 presets.

**Parameters:**

| Parameter | Constraints | Description |
|---|---|---|
| `name` | alphanumeric, `_`, `-` | Preset name |
| `data` | JSON string | Preset payload (opaque to backend) |

**Response:** JSON `{"status":"success","message":"..."}` or error codes: `INVALID_PRESET`, `INVALID_NAME`, `PRESET_LIMIT`

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=save_preset" \
  --data-urlencode "name=night_frigate" \
  --data-urlencode 'data={"fps":15,"bitrate":1500}'
```

---

### cmd=delete_preset

Deletes a named preset file from `/mnt/config/presets/`.

**Parameters:**

| Parameter | Constraints | Description |
|---|---|---|
| `name` | alphanumeric, `_`, `-` | Preset name to delete |

**Response:** JSON or error codes: `INVALID_PRESET`, `INVALID_NAME`, `PRESET_NOT_FOUND`

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=delete_preset" \
  --data-urlencode "name=night_frigate"
```

---

### cmd=clear_mem

Drops Linux kernel page/slab caches (`echo 3 > /proc/sys/vm/drop_caches`).

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=clear_mem" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=reboot

Reboots the camera. Publishes an MQTT event before rebooting. Rate limited: 3 per 300 s.

**Response:** JSON or HTML (response may not be received if connection drops before reboot)

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=reboot" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=shutdown

Halts the camera (`/sbin/halt`). Rate limited: 3 per 300 s.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=shutdown" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=complete_setup_wizard

Applies the first-boot wizard choices: sets password, applies a compatibility profile, sets timezone/NTP, and marks the wizard as done.

**Parameters:**

| Parameter | Description |
|---|---|
| `wizard_password` | New root/HTTP password |
| `wizard_profile` | Client preset name (see `set_client_profile` values) |
| `wizard_tz` | Timezone POSIX string |
| `wizard_ntp_srv` | NTP server address |
| `wizard_hostname` | Camera hostname |
| `wizard_enable_ntp` | `1`/`0` |

**Response:** HTML only

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=complete_setup_wizard" \
  --data-urlencode "wizard_password=securepass" \
  --data-urlencode "wizard_profile=frigate-balanced" \
  --data-urlencode "wizard_tz=CET-1CEST,M3.5.0,M10.5.0/3" \
  --data-urlencode "wizard_ntp_srv=pool.ntp.org" \
  --data-urlencode "wizard_enable_ntp=1"
```

---

### cmd=wizard_reset

Resets the setup wizard state, causing the wizard to appear on next page load.

**Response:** `{"status":"success","message":"..."}`

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=wizard_reset" \
  -H "X-CSRF-Token: <token>"
```

---

## Live image tuning (`isp_tune`)

Requires `ISP_TUNE=1` in `boot.conf`. The tuning runs inside `tc100_rtsp`, which reads
`/mnt/config/isp_tune.conf` every 2 s and applies it through the ISP (`/dev/isp_char`), so values take effect
within ~2 s without restarting the stream (`POWER_HZ` and the privacy masks apply whatever `ISP_TUNE` is).

### GET /cgi-bin/state.cgi?cmd=isp_tune&format=json

```json
{"enabled":1,
 "conf":{"BRIGHTNESS":30,"CONTRAST":0,"SATURATION":0,"SHARPNESS":0,"DENOISE":0,"HUE":0,"POWER_HZ":null,"EXPOSURE_MAX_PCT":null},
 "applied":{"BRIGHTNESS":30,"CONTRAST":0,"SATURATION":0,"SHARPNESS":0,"DENOISE":0,"HUE":0,"POWER_HZ":50,"EXPOSURE_MAX_PCT":0,"EXPOSURE_NOW":1125}}
```

`conf` is `/mnt/config/isp_tune.conf`; `applied` is what the camera reports
(`/var/run/isp_tune.status`), `null` until the video server has started.

### POST /cgi-bin/action.cgi?cmd=isp_tune

CSRF required. Fields: `isp_enable` (switching it restarts RTSP once),
`isp_brightness`, `isp_contrast`, `isp_saturation`, `isp_sharpness`, `isp_denoise`, `isp_hue`
(−50..50, 0 = sensor ISP value), `isp_power_hz` (empty, 50, 60),
`isp_exposure_max_pct` (0 = no cap, else 10..100). Any invalid field rejects the
whole request (`{"ok":false,"code":"INVALID_VALUE"}`).

Privacy masks (Settings → Privacy & overlay) post `isp_mask_form=1`, `isp_mask1`..`isp_mask4`
(`x1,y1,x2,y2` in percent, empty = none) and `isp_mask_color` (`black|gray|white`). A request
without `isp_enable` and `isp_brightness` (the mask form) leaves the tuning switch alone, and the
masks apply whether or not `ISP_TUNE` is on.

### MQTT

Retained state on `<root>/isp/state` (same JSON as above). Commands on the
command topic: `{"cmd":"isp_brightness","value":"20"}` (also `isp_contrast`,
`isp_saturation`, `isp_sharpness`, `isp_hue`, `isp_exposure_max_pct`,
`isp_power_hz` with `unchanged|50|60`) and `{"cmd":"isp_tune","value":"on|off"}`.
Home Assistant discovery creates six `number` sliders and an `Image Tuning` switch
(entity category: config). The `Anti-flicker` select of 2.x is not announced on 3.0 (anti-flicker is applied
again from 3.0.1-rc9 on, test queue R9-03; the entity comes back once that passes); `isp_power_hz` works.

---

## GET /cgi-bin/currentpic.cgi

Returns a current JPEG snapshot from the camera sensor.

- No parameters.
- Response: `image/jpeg`
- Cached for 2 seconds (configurable via `CURRENTPIC_CACHE_TTL_SECONDS`). A lock prevents concurrent capture stampede.
- Uses the `/mnt/bin/getimage` binary (timeout 5 s).

```sh
curl -o snapshot.jpg http://root:pass@192.168.1.50/cgi-bin/currentpic.cgi
```

---

## GET /cgi-bin/health.cgi

Returns a JSON health summary for all services, cached for the configured snapshot interval plus 15 seconds (75 seconds by default).

**Response:**
```json
{
  "ok": true,
  "ts": 1700000000,
  "services": {
    "rtsp-h26x": "running",
    "onvif": "running",
    "motion-detection": "running",
    "sound-detection": "stopped",
    "mqtt-bridge": "running",
    "auto-night-detection": "running",
    "memory-guard": "running",
    "ftp-server": "running",
    "telnet-server": "running",
    "syslog-forward": "stopped",
    "telegram-bot": "stopped"
  },
  "service_restarts": { "rtsp-h26x": 0, "..." : 0 },
  "system": {
    "mem_total_kb": 65536,
    "mem_free_kb": 12288,
    "mem_avail_kb": 18432,
    "load1": "0.45",
    "uptime_sec": 86400
  }
}
```

```sh
curl http://root:pass@192.168.1.50/cgi-bin/health.cgi \
  -H "Accept: application/json"
```

---

## GET /cgi-bin/events.cgi

Returns a JSON array of recent system events from the event logger.

**Parameters:**

| Parameter | Default | Max | Description |
|---|---|---|---|
| `limit` | 50 | 200 | Number of events to return |

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/events.cgi?limit=100"
```

---

## GET /cgi-bin/savedlogs.cgi

The logs of the previous boots that `scripts/log-persist.sh` copied to the SD card (`/mnt/sd/logs/boot-NNNN`).
Without parameters: a JSON array, newest boot first, each `{"boot","current","saved","why","files":[{"name","size"}]}`.
With `boot=boot-0007&file=dmesg.log`: that file as a text download (names are checked).

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/savedlogs.cgi"
```

---

## GET /cgi-bin/state.cgi?cmd=daynight&format=json

Automatic day / night settings and the live reading: `source` (`luma`, `ae` or `isp`), the thresholds
(`luma_night`, `luma_day`, `ae_night_above`, `ae_day_below`), `night_hold`, `day_hold`, `auto`, `night`, the picture
`luma`, and when `/tmp/cam_ae` exists (`ae_available`) `lumi`, `exp_time`, `a_gain`, `d_gain`, `isp_d_gain`, `dark_flag`
and `index` (`exp_time * a_gain/256 * d_gain/256 * isp_d_gain/256`).

---

## GET /cgi-bin/motionevents.cgi

Returns a JSON list of motion detection events with snapshot and clip paths.

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `limit` | 20 | Number of events (1–200) |
| `type` | (all) | Filter: `motion_on` or `motion_off` |

**Response:**
```json
{
  "items": [
    {
      "ts": 1700000000,
      "time_utc": "2023-11-14T12:00:00Z",
      "type": "motion_on",
      "snapshot": "/mnt/snapshots/snap_1700000000.jpg",
      "clip": "/mnt/DCIM/clip_1700000000.mp4",
      "detail": ""
    }
  ],
  "count": 1,
  "latest_thumbnail": "cgi-bin/motionthumb.cgi"
}
```

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/motionevents.cgi?limit=10&type=motion_on"
```

---

## GET /cgi-bin/motionthumb.cgi

Returns a JPEG thumbnail of the latest (or a specific) motion snapshot.

**Parameters:**

| Parameter | Description |
|---|---|
| `file` | (optional) Filename within `motion_save_dir`. Omit for the latest. |

- Response: `image/jpeg` or `404` if no snapshot exists.
- Resolution order: `file` param → `/tmp/motion-last-snapshot.path` → event log → filesystem scan.

```sh
curl -o motion.jpg http://root:pass@192.168.1.50/cgi-bin/motionthumb.cgi
```

---

## Recording thumbnails

The recorder writes a JPEG next to each clip (`/DCIM/<date>/<clip>.jpg`), served as a plain file: the Recordings
page shows it as the poster of the clip. (`clip_thumb.cgi`, which extracted a frame with ffmpeg, was removed in
rc32: ffmpeg is not on 3.0.)

---

## GET /cgi-bin/viewrecords.cgi

Manages video clip records on the SD card.

### cmd=list_dates

Returns a JSON array of date folders in `/mnt/DCIM`.

```json
[{"date":"20231114"},{"date":"20231115"}]
```

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/viewrecords.cgi?F_cmd=list_dates"
```

### cmd=list_records

Returns a JSON array of clip filenames for a given date.

**Parameters:**

| Parameter | Description |
|---|---|
| `F_date` | Date string (e.g. `20231114`) |

```json
[{"record":"clip_001.mp4"},{"record":"clip_002.mp4"}]
```

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/viewrecords.cgi?F_cmd=list_records&F_date=20231114"
```

### cmd=remove_record

Deletes a specific clip file. Rate limited: 10 per 60 s.

**Parameters:**

| Parameter | Description |
|---|---|
| `F_record` | Filename (basename only, alphanumeric+`._-`) |

**Response:** `{"ok":true}` or `{"ok":false,"error":"..."}` — error values: `invalid filename`, `file not found`, `delete failed`

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/viewrecords.cgi?F_cmd=remove_record&F_record=clip_001.mp4"
```

### cmd=disk_usage

Returns SD card disk usage stats for `/mnt`.

```json
{"total_kb":15728640,"used_kb":2097152,"avail_kb":13631488,"percent":13}
```

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/viewrecords.cgi?F_cmd=disk_usage"
```

---

## GET/POST /cgi-bin/camcontrols.cgi

Since 1.8.3-rc1, `setsettings`, `on` and `off` require POST with `X-CSRF-Token`; GET mutations return 405.

Manages camera controlscripts (on/off service toggles).

### cmd=getcontrols *(read-only)*

Returns a JSON array of all available controls.

```json
[{"id":"telegram-bot","name":"Telegram Bot"},{"id":"recording","name":"Recording"}]
```

### cmd=getallstate *(read-only)*

Returns a JSON array of all controls with their current state (`ON`/`OFF`).

### cmd=getstate *(read-only)*

Returns the state of a single control.

**Parameters:** `control=<script-id>`

**Response:** `ON` or `OFF` (plain text)

### cmd=getsettings *(read-only)*

Returns an HTML fragment with checkbox inputs for each controlscript.

### cmd=on / cmd=off

Starts or stops a controlscript service.

**Parameters:** `control=<script-id>` (CSRF required)

**Response:** HTML

### cmd=setsettings

Saves updated control settings to `webcontrols.conf`.

**Parameters:** `controls=<...>` (CSRF required)

**Response:** HTML

```sh
# Start recording
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/camcontrols.cgi?cmd=on&control=recording" \
  -H "X-CSRF-Token: <token>"
```

---

## GET/POST /cgi-bin/scripts.cgi

Since 1.8.3-rc1, service start/stop and autostart changes require POST with `X-CSRF-Token`; GET mutations return 405.

Manages autostart scripts and daemons.

**Without `F_script`:** Returns an HTML table of all services with start/stop buttons and autostart toggles.

**With `F_script=<name>` parameter:**

### F_script — allstates *(read-only)*

Returns a JSON array (cached 4 s) of all services:

```json
{
  "status": "ok",
  "services": [
    {
      "script": "mqtt-bridge",
      "state": "running",
      "running": 1,
      "has_start": 1,
      "has_stop": 1,
      "has_status": 1,
      "autostart_enabled": 1,
      "uptime_s": 3600
    }
  ]
}
```

### F_script — state *(read-only)*

Returns the same per-service object for the script named in `F_script`.

### F_script — view *(read-only)*

Returns the script source as HTML.

### F_script — start / stop

Starts or stops the named script. CSRF required.

### F_script — enable / disable

Adds or removes the script from the autostart sequence. CSRF required.

```sh
# Start mqtt-bridge
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/scripts.cgi?F_script=mqtt-bridge&cmd=start" \
  -H "X-CSRF-Token: <token>"
```

---

## GET /cgi-bin/sysusageinfo.cgi

Returns an HTML page with memory snapshot, CPU counters, process list, and recent events. Loads additional data client-side from `health.cgi` and `events.cgi`.

```sh
curl http://root:pass@192.168.1.50/cgi-bin/sysusageinfo.cgi
```

---

## GET /cgi-bin/network.cgi

Returns an HTML page with: network summary, open ports, interfaces, routes, DNS config, listening sockets, connections, and DNS/static-IP/WiFi configuration forms.

The embedded forms submit to `action.cgi?cmd=conf_dns`, `action.cgi?cmd=conf_static_ip`, and `action.cgi?cmd=wifi_scan`.

```sh
curl http://root:pass@192.168.1.50/cgi-bin/network.cgi
```

---

## GET /cgi-bin/devinfo.cgi

Returns an HTML page with device summary, runtime info, bootloader version/cmdline, CPU information, and binary versions.

```sh
curl http://root:pass@192.168.1.50/cgi-bin/devinfo.cgi
```

---

## GET /cgi-bin/disk.cgi

Returns an HTML page with disk space, I/O stats, mount info, SD card health (from sysfs), and a disk usage growth forecast.

```sh
curl http://root:pass@192.168.1.50/cgi-bin/disk.cgi
```

---

## POST /cgi-bin/upload_audio.cgi

Plays audio through the camera speaker (push-to-talk).

- Method: `POST` only
- Rate limit: 5 per 60 s
- Body: raw PCM — **Int16 LE, mono, 8 kHz**. Must be an even byte count.
- Max body size: 524 288 bytes (512 KB / ~32 s of audio)
- CSRF required (`X-CSRF-Token` header), like every mutating endpoint
- Plays via ALSA (`aplay`) through `scripts/speaker-play.sh`: raw PCM Int16 LE mono 8 kHz sent to the DAC/amplifier. RTSP streaming continues in parallel without interruption.
- Volume is read from `/mnt/config/pttvolume.conf` (0–100)
- Concurrent playbacks are locked via `/tmp/speaker-play.lock`; busy uploads return `BUSY` (429).

**Response:** Plain text `OK`, or one of:

| Code | Meaning |
|---|---|
| `METHOD_NOT_ALLOWED` | Not a POST request |
| `PTT_BIN_MISSING` | `/mnt/bin/ak_ao_ptt` not found (stock `ak_ao_demo` missing or MD5 mismatch at boot) |
| `INVALID_CONTENT_LENGTH` | Missing or non-numeric Content-Length |
| `EMPTY_INPUT` | Zero bytes received |
| `INVALID_PCM` | Odd byte count (not valid Int16) |
| `TOO_LARGE` | Body exceeds 512 KB |
| `READ_FAILED` | The PCM body could not be read |
| `BUSY` | Another PTT playback is in progress (429) |
| `AUDIO_DEVICE_BUSY` | RTSP could not be stopped to free the codec (503) |

```sh
# Record 3 s of PCM and send it to the speaker
sox -n -r 8000 -c 1 -e signed -b 16 /tmp/ptt.raw synth 3 sine 1000
curl -X POST http://root:pass@192.168.1.50/cgi-bin/upload_audio.cgi \
  -H "X-CSRF-Token: $TOKEN" \
  --data-binary @/tmp/ptt.raw \
  -H "Content-Type: application/octet-stream"
```

---

## GET/POST /cgi-bin/config_exchange.cgi

The configuration export/import format to share between cameras: a `.json` file. The full backup of one camera is a
`.tar.gz` (`cmd=archive` / `cmd=restore` below; `conf-export.cgi` and `conf-import.cgi` of earlier versions are gone).
CSRF is required for import, restore and push; export and archive are read-only. Rate limit: 10 per 60 s.

The document is built from, and read by, one table in `config_exchange.cgi` (`_ce_row_table`), so what a camera exports
another camera imports. Top-level keys: `format`, `version`, `includes_secrets`, `boot`, `video`, `audio`, `osd`,
`daynight`, `isp`, `mqtt`, `recording`, `system`, `services`, `tamper`, `notify`, `telegram`, `syslog`, `peripherals`,
`wifi_rescue`, and, only with `include_secrets=1`, `secrets` (Wi-Fi networks `secrets.wifi[]`, `camera_password`,
`mqtt_user`, `mqtt_password`, `telegram_token`, `telegram_chat_id`, `wifi_rescue_psk`) plus `notify.ntfy_auth`,
`notify.ntfy_topic` and `notify.webhook_url` (a webhook URL or an ntfy topic can act as a password).

For RTSP, `video.main.vbr` and `video.main.smart` are the active global encoder controls. They apply to both streams by
default; `RTSP_VBR_SUB` and `RTSP_SMART_SUB` in `/mnt/config/rtsp.env` are explicit sub-stream overrides. The exported
`format`, `smartmode`, and Smart tuning fields remain for compatibility and do not control the free RTSP encoder. The
advanced Smart call tuning comes from `RTSP_SMART_GOP`, `RTSP_SMART_Q`, and `RTSP_SMART_V` in `rtsp.env`. The pilot
metadata for these settings is in [`config/parameter-catalog.json`](../config/parameter-catalog.json).

### cmd=export

Returns the configuration as a downloadable JSON file.

| Parameter | Values | Description |
|---|---|---|
| `include_secrets` | `1`/`0` (default `0`) | `0`: no Wi-Fi, no passwords, no tokens (safe to share between cameras). `1`: full restore file |

- Response: `application/json` with `Content-Disposition: attachment` (`tc100_config_<date>[_with_secrets].json`)

```sh
curl -o config.json \
  "http://root:pass@192.168.1.50/cgi-bin/config_exchange.cgi?cmd=export&include_secrets=1"
```

### cmd=import

Imports a JSON configuration object. Values are type/range checked (several config files are sourced by shell scripts,
so nothing with shell metacharacters is accepted) in isolated copies, then all changed files are committed together. Any
write or readback failure restores the originals. A successful change triggers an asynchronous RTSP and MQTT restart.
The camera password (`secrets.camera_password`) is applied afterwards the way the Settings password change does (web UI,
RTSP, FTP, telnet); a changed Wi-Fi list is applied with `wifi-apply`.

- Method: `POST`, JSON body, max 64 KB
- Response includes `applied`, `changed_files`, `skipped`, and `transactional: true`
- Parameters (query string):

| Parameter | Values | Description |
|---|---|---|
| `exclude_network` | `1`/`0` | Skip network-related keys (address, host names, ports, MQTT topic, flip) |
| `exclude_credentials` | `1`/`0` | Skip the secrets |

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/config_exchange.cgi?cmd=import&exclude_credentials=1" \
  -H "X-CSRF-Token: <token>" \
  -H "Content-Type: application/json" \
  -d @config.json
```

### cmd=archive

The full backup of this camera: every file of `config/` that differs from the shipped defaults (passwords, Wi-Fi, ssh
keys, presets, zones included), the same set the flash slots keep (`v3/linux66-sd/cfg-persist archive`). Keep it private.

- Response: `application/gzip`, `Content-Disposition: attachment` (`tc100_<host>_config_<date>.tar.gz`); JSON
  `NOTHING_TO_SAVE` when nothing differs from the defaults

### cmd=restore

Restores an archive of `cmd=archive`: only regular files and directories under `config/` with plain names
(`[A-Za-z0-9._-]`), at most 256 KB packed and 1 MB unpacked. Each non-empty file is validated as for an import and all are
written as one transaction (any failure restores the originals); empty files are markers. The Wi-Fi, the password, the
Wi-Fi country and the RTSP / MQTT services are applied at once; ssh keys and the host name at the next restart. It brings
back the identity of the camera (name, address): to configure another camera use the JSON export or `cmd=push`.

- Method: `POST`, body = the `.tar.gz` (`Content-Type: application/gzip`), CSRF
- Response: `{"ok":true,"files":N,"changed_files":N,...}` or `INVALID_SIZE` / `INVALID_ARCHIVE` / `TRANSACTION_FAILED`

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/config_exchange.cgi?cmd=restore" \
  -H "X-CSRF-Token: <token>" -H "Content-Type: application/gzip" --data-binary @backup.tar.gz
```

### cmd=push

Sends this camera's settings to another camera (server side, with curl; the browser cannot do it because of CORS).
Always without secrets and with `exclude_network=1&exclude_credentials=1`. Form body (`application/x-www-form-urlencoded`):
`target` (address of the other camera), `user`, `password` (its web login). The target's CSRF token is read from its
`statusline.cgi` first.

```sh
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/config_exchange.cgi?cmd=push" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "target=http://192.168.1.51" --data-urlencode "user=root" --data-urlencode "password=<password>"
```

---

## GET/POST /cgi-bin/configeditor.cgi

In-browser editor for individual config files.

### GET ?file=\<name\>

Returns the file content as JSON.

**Allowed files:** `boot.conf`, `mqtt.conf`, `rtspserver.conf`, `recording.conf`, `onvif.conf`, `hostname.conf`, `ntp_srv.conf`, `timezone.conf`, `telegram.conf`, `dns.conf`, `motion.conf`, `pttvolume.conf`

**Response:**
```json
{
  "ok": true,
  "file": "boot.conf",
  "source": "config",
  "content": "KEY=value\n..."
}
```

(`source` is `config` if the live file exists, `dist` if serving the `.dist` template)

### POST ?cmd=save&file=\<name\>

Saves new content to the config file. CSRF required. Rate limit: 5 per 60 s.

- Body: raw text content of the file

**Response:**
```json
{"ok": true, "file": "boot.conf", "message": "Saved."}
```

```sh
# Read
curl "http://root:pass@192.168.1.50/cgi-bin/configeditor.cgi?file=boot.conf" \
  -H "Accept: application/json"

# Save
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/configeditor.cgi?cmd=save&file=boot.conf" \
  -H "X-CSRF-Token: <token>" \
  --data-binary @boot.conf
```

---

## GET /cgi-bin/wizard.cgi

### GET ?check

Returns whether the first-boot wizard should be displayed.

**Response:** `{"first_boot": true}` or `{"first_boot": false}`

### GET (no parameters)

Returns the HTML 4-step setup wizard page.

### POST

Applies the wizard choices. No CSRF required (first-boot context, password not yet set).

**Parameters:**

| Parameter | Description |
|---|---|
| `profile` | Compatibility preset name (see `set_client_profile`) |
| `security` | Security mode flag |
| `mqtt_host` | MQTT broker IP |
| `mqtt_port` | MQTT broker port |
| `mqtt_user` | MQTT username |
| `mqtt_pass` | MQTT password |

**Response:** `{"ok": true}` or `{"ok": false, "error": "..."}` (JSON)

```sh
curl "http://root:pass@192.168.1.50/cgi-bin/wizard.cgi?check"
```

---

## GET /cgi-bin/dumpbootloader.cgi

Downloads the raw bootloader flash partition as a binary file.

- GET only; no CSRF (privileged read-only operation)
- Response: `application/x-binary`, filename `bootloader.bin`
- Uses `dd if=/dev/mtd0`

```sh
curl -o bootloader.bin http://root:pass@192.168.1.50/cgi-bin/dumpbootloader.cgi
```

---

## Notes

## Other CGIs

Short entries for the CGIs the sections above do not cover. Headers are read from the scripts in `www/cgi-bin/`;
all of them sit behind the web login. "CSRF" means the `X-CSRF-Token` header described above.

### GET /cgi-bin/audio_stream.cgi[?type=mic]

The microphone as an endless WAV stream (8 kHz, mono, 16 bit), for "Listen" on the main page. At most 60 s and 3
listeners. The sound comes from `tc100_rtsp` through a FIFO in `/tmp/tc100_listen/`; if `tc100_rtsp` is not running
the script reads the microphone with `arecord` when nothing else holds it. Answers `audio/wav`; 503 with a text
reason when listening is not possible (no capture device, too many listeners, microphone in use). A HEAD request only
tells whether listening is possible (200 or 503).

### GET /cgi-bin/dash.cgi

Raw counters for the dashboard graphs (polled every 5 s by the page, which turns them into rates). Answer
(`application/json`): `{"up":s,"load":"x","cpu":[7 /proc/stat counters],"mem":[total_kB,available_kB],"iface":"wlan0","net":[rx_bytes,tx_bytes],"wifi":[quality,dBm],"rtsp_clients":N,"sd_health":"state"}`;
the `wifi` entries are `null` when unknown. No parameters, no CSRF.

### GET /cgi-bin/inventory.cgi[?full=1]

Read-only hardware inventory of the camera (made at each start by `v3/install/inventory.sh`) and the board profile it
matched, as `text/plain`, to paste in a GitHub issue "Hardware inventory". `full=1` runs the full inventory, which
adds the md5 of U-Boot and reads 228 KiB of the slow flash (about 15 s).

### GET /cgi-bin/live.cgi[?info=1]

The live video as fragmented MP4 (`video/mp4`) for the "Video" mode of the live view (Media Source Extensions); at
most 2 viewers, 10 minutes each. `?info=1` answers JSON `{"ok":1,"stream":"sub","codec":"avc1.42c01e","width":640,"height":360}`.
Errors are JSON `{"ok":0,"error":"..."}`: 415 neither stream is H.264, 503 `tc100_rtsp` not running, the video is
starting, or two viewers already. A HEAD request only tells whether the video is possible. The stream is the 640x360
sub-stream when it is H.264, else the main stream when it is H.264.

### GET /cgi-bin/metrics.cgi

Prometheus text exposition (version 0.0.4); `/metrics` redirects here (`httpfront`). Metrics:
`tc100_uptime_seconds`, `tc100_memory_{total,free,available}_bytes`, `tc100_load{1,5,15}`,
`tc100_network_{receive,transmit}_{bytes,drops}_total`, `tc100_wifi_link_quality`, `tc100_wifi_signal_dbm`,
`tc100_rtsp_*` (viewers, capture fps, main / sub kbps, clients playing, dropped frames), `tc100_motion_active`,
`tc100_tamper_active`, `tc100_vox_active`, `tc100_sensor_luma`, `tc100_audio_level_dbfs`, `tc100_sdcard_*` (present,
size, free) and `tc100_info`.

### GET/POST /cgi-bin/sounds.cgi

The speaker's sounds. Built-in clips are in `/mnt/sounds`; custom ones go to the SD card (`/mnt/sd/tc100-3/sounds`),
and a custom clip with a built-in name replaces it. Clips are raw 8 kHz mono signed 16-bit little-endian PCM (the
Settings page converts any file the browser decodes), 30 s at most (480000 bytes), even length, up to 32 files.

| Request | Description |
|---|---|
| `GET ?cmd=list` | `{"ok":true,"sd":true,"boot":{"on":1,"name":"startup_complete"},"sounds":[{"name":"chime","builtin":1,"custom":0,"bytes":16800},...]}` |
| `POST ?cmd=upload&name=NAME` | body: the PCM; NAME is 1-32 of `A-Z a-z 0-9 _ -` |
| `POST ?cmd=delete&name=NAME` | removes the custom clip (the built-in one of that name is used again) |
| `POST ?cmd=play&name=NAME` | plays it at the push-to-talk volume |
| `POST ?cmd=playnow` | body: the PCM; played once from RAM and deleted, no card needed, nothing kept |
| `POST ?cmd=boot&name=NAME` or `name=0` | startup sound: `BOOT_SOUND=1` and `BOOT_SOUND_NAME=NAME`, or `BOOT_SOUND=0` (silent) |

Answers are JSON `{"ok":true,...}` or `{"ok":false,"error":"..."}` with a status (400, 411, 413...). The POST
commands (`upload`, `delete`, `play`, `boot`, `playnow`) go through `mutation_guard` (`func.cgi`), which checks the
CSRF token (`csrf_guard`), and a rate limit (20 a minute).

### GET /cgi-bin/stability.cgi

Downloads `tc100-stability.csv` (`text/csv`): `timestamp,uptime_s,load1,mem_available_kb,unhealthy_services`, written
by `health-snapshot.sh` (on the card when one is mounted, else in `/mnt/log`), followed by the samples of the last
hour still in RAM. No parameters.

### GET/POST /cgi-bin/update.cgi

Firmware update (Settings, Update & backup). POSTs need CSRF; answers are JSON.

| Request | Description |
|---|---|
| `GET ?cmd=status` | `{"ok":true,"current":"3.0.1-rcNN","state":"idle\|staged\|installing","staged":"...","kind":"linux66","message":"..."}` |
| `POST ?cmd=upload` | raw body = `tc100-<version>-update.tar` (12 MiB at most), unpacked as it arrives (card if present, else RAM) and checked; only in flash mode |
| `POST ?cmd=install` | applies the staged package in the background (`v3/install/update66.sh apply`); the camera restarts |
| `POST ?cmd=discard` | drops the uploaded package |
| `POST ?cmd=rollback` | not supported on 3.0 (`unsupported`): install the previous package |

Errors: `csrf_invalid`, `sd_mode`, `size`, `space`, `memory`, `upload`, `invalid`, `state`, `busy`.

### GET/POST/DELETE /cgi-bin/whep.cgi

WHEP endpoint of the WebRTC live view; it forwards to `tc100-whep` on 127.0.0.1:8889.

| Request | Description |
|---|---|
| `GET` | `{"viewers":N,"max":M,...}`; 503 `{"enabled":0}` when the daemon does not run (`WHEP=0` in `boot.conf`) |
| `POST` | body = SDP offer (12000 bytes at most, else 413); answers 201 + SDP answer + `Location: /cgi-bin/whep.cgi?stop=ID` (also 400, 415, 429, 500, 503; 502 when the daemon fails) |
| `POST ?stop=ID` or `DELETE ?stop=ID` | ends that viewer (ID is 16 hex characters); 200, or 404 for an unknown viewer |

### GET/POST /cgi-bin/flashinstall.cgi

Installs the card system to the flash (Settings, Update & backup, Install to flash). POSTs need CSRF; answers are JSON.

| Request | Description |
|---|---|
| `GET ?cmd=status` | `{"ok":true,"linux66":1,"state":"flash\|ready66\|blocked\|running\|installed","running":0,"log":"..."}` |
| `POST ?cmd=install` | runs `v3/install/install66.sh` in the background; the camera restarts from its flash at the end. Errors: `busy`, `state` (the check failed), `csrf_invalid` |

### GET /cgi-bin/cpuprofile.cgi?sec=10[&threads=1]

Manual diagnostic tool, not used by the web pages: `text/plain` report of where the CPU goes
(`scripts/cpu-profile.sh`), `sec` 3-30 s (default 10), `threads=1` per thread. One run at a time ("a profile is
already running"). Read-only.

### Response format selection

All endpoints that support both HTML and JSON responses check whether the request includes `Accept: application/json`. If so, they return JSON. Otherwise they return HTML fragments (suitable for injection into the dashboard UI). The curl examples above use `-H "Accept: application/json"` where applicable.

### CSRF workflow

```sh
# 1. Fetch CSRF token
TOKEN=$(curl -s -H "Accept: application/json" \
  http://root:pass@192.168.1.50/cgi-bin/state.cgi?cmd=statusline \
  | sed 's/.*"csrf_token":"\([^"]*\)".*/\1/')

# 2. Use it on every state-changing request
curl -X POST "http://root:pass@192.168.1.50/cgi-bin/action.cgi?cmd=reboot" \
  -H "X-CSRF-Token: $TOKEN"
```

### Platform & performance notes (AK3918)

The camera is a single-core ARM (Anyka AK3918) with ~33 MB RAM, so the CGI layer
is written to minimise `fork`/`exec`. A few behaviours are worth knowing when
consuming this API:

- **`health.cgi` is served from a cache.** The `health-snapshot` daemon rebuilds
  `/tmp/health_snapshot.cache` at the configured interval (60 s by default); `health.cgi`
  serves it for that interval plus 15 s
  before rebuilding inline. Service state can therefore lag reality by up to that
  window. Both paths use the shared fork-free prober `scripts/health-probe.sh`
  (pidfile checks via shell builtins; only deep/composite services exec their
  controlscript). When testing a `health.cgi` change, delete the cache file first
  — a stale entry is indistinguishable from a fix that did not take.

- **`statusline` caches its usage metrics** (`/tmp/state_usage.cache`, 2 s TTL) and
  the perf profile (5 s). The `csrf_token` it returns is generated on first call
  if absent, so a fresh client's first `statusline` poll always yields a usable
  token — no bootstrap lock-out.

- **Poll gently.** A CGI request costs about 0.3–1 s on this CPU (each one starts a shell); do not poll
  faster than once every few seconds. There is no TLS in 3.0, so no handshake cost.

- **MQTT is published by forging packets**, not via a client library. `curl`'s
  `mqtt://` sends SUBSCRIBE rather than PUBLISH on this device, so
  `mqtt-bridge.sh` builds the MQTT 3.1.1 CONNECT/PUBLISH/DISCONNECT frames in
  shell and pipes them to `nc`. Published at QoS 0; the retain flag is honoured
  (HA discovery and availability topics are retained). `statusline` exposes
  `mqtt_last_pub_ok` (1/0/-1) so the UI can show publish health.

- **`tr(1)`**: absent on the 2.x firmware (the CGIs carry a shim); the 3.0 busybox has the applet (to check on a camera).
  It affects CGI internals, not this API's request/response contract.
