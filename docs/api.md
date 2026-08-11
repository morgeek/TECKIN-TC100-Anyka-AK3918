# TECKIN TC100 CGI API Reference

**Base URL:** `http://192.168.1.24/cgi-bin/` (or `https://` when TLS is enabled)

**Authentication:** HTTP Basic Auth — default `root:pass`.

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
| `default_password_active` | string | `1` if factory default password is still in use |
| `csrf_token` | string | Per-boot CSRF token — use as `X-CSRF-Token` header |
| `update_available` | string | `1` if an update is available |
| `update_latest_version` | string | Latest available version string |

```sh
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=statusline \
  -H "Accept: application/json"
```

---

### cmd=hostname

Returns the camera hostname as plain text (one line).

```sh
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=hostname
```

---

### cmd=lumawb

Returns two lines of plain text: current luminance value, then current AWB value.

```sh
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=lumawb
```

---

### cmd=sysusage

Returns a plain text system usage summary (CPU, RAM, uptime).

```sh
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=sysusage
```

---

### cmd=perfprofile

Returns the active performance profile name as plain text (`balanced`, `low-cpu`, or `rtsp-only`).

```sh
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=perfprofile
```

---

### cmd=healthsnapshot

Returns a comprehensive JSON health snapshot (cached for 3 seconds). Includes chip temperature, power telemetry, RTSP and ONVIF state, uptime, SD card read-only flag, and a copy of `csrf_token`.

```sh
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=healthsnapshot \
  -H "Accept: application/json"
```

---

### cmd=fullconfig

Returns a large JSON object with all configuration values across all UI tabs (video streams, audio, ISP, network, MQTT, automation, etc.). Intended for the frontend settings panels.

```sh
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=fullconfig \
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
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=integrationtest \
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
curl "http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=integrationmanifest&redact=1" \
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
curl "http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=get_events&limit=100" \
  -H "Accept: application/json"
```

---

### cmd=list_presets

Returns a JSON array of saved SmartVBR/stream preset names stored in `/mnt/config/presets/`.

```sh
curl http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=list_presets \
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
curl "http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=load_preset&name=my_preset" \
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
| `logname` | `3` | v4l2rtspserver log |

**Response:** `text/html`

```sh
curl "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=showlog&logname=1"
```

---

### cmd=clearlog

Clears the specified log file.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `logname` | `1`, `2`, `3` | Same as `showlog` |

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=clearlog&logname=1" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=set_video_params

Applies video encoder parameters to one or both RTSP streams and schedules an RTSP server restart. Geometry and codec values are normalized to encoder-safe combinations.

**Parameters (all optional — pass only what you want to change):**

| Parameter | Description |
|---|---|
| `stream` | Target stream index: `0` (main) or `1` (sub) |
| `video_size0` | Main stream resolution, e.g. `1280x720` |
| `video_size1` | Sub stream resolution, e.g. `352x200` |
| `fps0` / `fps1` | Frame rate 1–25 |
| `brbitrate0` | Main bitrate kbps (64–12000) |
| `brbitrate1` | Sub bitrate kbps (64–4000) |
| `video_codec0` / `video_codec1` | `0`=H.264, `2`=H.265 |
| `goplen0` / `goplen1` | GOP length 1–120 |
| `video_format0` / `video_format1` | Bitrate mode: `CBR` or `VBR` |
| `minqp0` / `minqp1` | Minimum QP 1–51 |
| `maxqp0` / `maxqp1` | Maximum QP 1–51 |
| `smartmode0` / `smartmode1` | SmartVBR mode |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_video_params" \
  --data-urlencode "video_size0=1280x720" \
  --data-urlencode "fps0=20" \
  --data-urlencode "video_codec0=0"
```

---

### cmd=set_video_size

Full video parameter replacement for both streams. Supersedes `set_video_params` for bulk updates. Applies geometry normalization, codec profile validation, and SmartVBR clamping; rolls back automatically if the new stream fails health checks.

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
| `video_format0` / `video_format1` | Bitrate mode (`CBR`/`VBR`) |
| `goplen0` / `goplen1` | GOP length 1–120 |
| `minqp0` / `minqp1` | Minimum QP 1–51 |
| `maxqp0` / `maxqp1` | Maximum QP 1–51 |
| `smartmode0` / `smartmode1` | SmartVBR mode |
| `smartgoplen0` / `smartgoplen1` | SmartVBR GOP length 1–600 |
| `smartquality0` / `smartquality1` | SmartVBR quality target 1–100 |
| `smartstatic0` / `smartstatic1` | SmartVBR static scene threshold 0–1000 |
| `maxkbps0` / `maxkbps1` | SmartVBR max kbps |
| `targetkbps0` / `targetkbps1` | SmartVBR target kbps |
| `videouser` / `videopassword` | RTSP credentials (URL-encoded) |
| `videoport` | RTSP port 1–65535 |

**Response:** HTML — notes any normalization that was applied; confirms rollback if health check fails.

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=isp_pro" \
  --data-urlencode "imageFlip=0" \
  --data-urlencode "osdenabled=1" \
  --data-urlencode "osdtext=CAM-01"
```

---

### cmd=conf_autodaynight

Sets the auto day/night mode thresholds and applies them immediately.

**Parameters:**

| Parameter | Description |
|---|---|
| `dnlum` | Day-to-night luminance threshold |
| `dnawb` | Day-to-night AWB threshold |
| `ndlum` | Night-to-day luminance threshold |
| `ndawb` | Night-to-day AWB threshold |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_autodaynight" \
  --data-urlencode "dnlum=60" \
  --data-urlencode "dnawb=100" \
  --data-urlencode "ndlum=100" \
  --data-urlencode "ndawb=150"
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_advanced_tuning" \
  --data-urlencode "mem_guard_enable=1" \
  --data-urlencode "mem_guard_warn_kb=8192" \
  --data-urlencode "mem_guard_critical_kb=4096"
```

---

### cmd=set_web_mode

Switches the web server mode. Changes take effect after a reboot.

**Parameters:**

| Parameter | Values | Description |
|---|---|---|
| `web_mode` | `full` | HTTPS on port 443 (default) |
| `web_mode` | `http` | HTTP on port 80 |
| `web_mode` | `ultra-lite` | Minimal busybox httpd frontend |
| `web_mode` | `off` | Disable web server |
| `ultralite_http_port` | 1–65535 | Port for `ultra-lite` mode (default 80) |

**Response:** HTML only

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_web_mode" \
  --data-urlencode "web_mode=http"
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
| `client_profile` | `frigate-balanced` | Frigate balanced (recommended) |
| `client_profile` | `frigate-low-bandwidth` | Frigate low-bandwidth |
| `client_profile` | `frigate-quality` | Frigate high-quality |
| `client_profile` | `hybrid-hevc-main` | H.265 main + H.264 sub |
| `client_profile` | `legacy-main-only` | Single H.264 stream for legacy NVRs |
| `client_profile` | `nvr-low-cpu` | Low-CPU NVR mode |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_client_profile" \
  --data-urlencode "client_profile=frigate-balanced"
```

---

### cmd=save_known_good_profile

Saves a snapshot of the current RTSP configuration and stream state as the "known-good" baseline (used by `restore_known_good_profile` for safe rollback).

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=save_known_good_profile"
```

---

### cmd=restore_known_good_profile

Restores the RTSP configuration from the last saved known-good snapshot and restarts the stream.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=restore_known_good_profile"
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_led_config" \
  --data-urlencode "led_front=1" \
  --data-urlencode "led_red=0"
```

---

### cmd=front_led_on / cmd=front_led_off

Immediately turns the front activity LED on or off.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=front_led_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=red_led_on / cmd=red_led_off

Immediately turns the red status LED on or off.

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=red_led_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=ir_led_on / cmd=ir_led_off

Immediately turns the infrared LED on or off.

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=ir_led_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=ir_cut_on / cmd=ir_cut_off

Activates or deactivates the IR-cut filter (switches between color and night-vision mode).

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=ir_cut_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=night-mode-on / cmd=night-mode-off

Switches the camera to night (IR) mode or back to day mode.

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=night-mode-on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=auto_night_mode_start / cmd=auto_night_mode_stop

Starts or stops the automatic day/night detection service.

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=auto_night_mode_start" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=toggle-rtsp-nightvision-on / cmd=toggle-rtsp-nightvision-off

Toggles night-vision mode on the RTSP stream (IR illumination + IR-cut state) without changing the auto-detection daemon.

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=toggle-rtsp-nightvision-on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=rtsp-log-on / cmd=rtsp-log-off

Enables or disables verbose RTSP server logging.

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=rtsp-log-on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=motion_detection_on / cmd=motion_detection_off

Starts or stops the motion detection service.

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=motion_detection_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=motion_detection_mail_on / cmd=motion_detection_mail_off

Enables or disables email notification on motion events (writes `sendemail` to `motion.conf`).

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=motion_detection_mail_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=motion_detection_snapshot_on / cmd=motion_detection_snapshot_off

Enables or disables saving JPEG snapshots on motion events (writes `save_snapshot` to `motion.conf`).

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=motion_detection_snapshot_on" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_motiondetect" \
  --data-urlencode "mdsens=50" \
  --data-urlencode "motionBlink=1"
```

---

### cmd=service_trim_on / cmd=service_trim_off

Stops (trim) or re-enables all non-essential services to free resources. Useful for temporary CPU/RAM relief without a full profile change.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=service_trim_on" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=set_http_password

Sets the lighttpd HTTP Basic Auth password.

**Parameters (one required):**

| Parameter | Description |
|---|---|
| `password` | New password |
| `httppassword` | Alternative parameter name for new password |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_http_password" \
  --data-urlencode "password=mynewpass"
```

---

### cmd=set_all_password

Sets the HTTP password AND restarts FTP, Telnet, and RTSP servers with the new credentials.

**Parameters (one required):**

| Parameter | Description |
|---|---|
| `password` | New password |
| `allpassword` | Alternative parameter name |

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=set_syslog_config" \
  --data-urlencode "syslog_enable=1" \
  --data-urlencode "syslog_host=192.168.1.10" \
  --data-urlencode "syslog_port=514"
```

---

### cmd=enable_privacy_shield

Activates Privacy Shield: immediately stops Telegram bot, syslog-forward, mqtt-bridge, ftp-server, and telnet-server, and sets `PRIVACY_MODE=1` in boot config.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=enable_privacy_shield" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=conf_timelapse

Configures timelapse capture interval and duration.

**Parameters:**

| Parameter | Description |
|---|---|
| `tlinterval` | Capture interval in seconds (numeric) |
| `tlduration` | Total capture duration in minutes (numeric) |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_timelapse" \
  --data-urlencode "tlinterval=5" \
  --data-urlencode "tlduration=60"
```

---

### cmd=conf_recording

Configures motion-triggered recording behavior.

**Parameters:**

| Parameter | Description |
|---|---|
| `motion_act` | `1`/`0` — trigger recording on motion |
| `postrec` | Post-event recording duration (seconds) |
| `maxduration` | Maximum clip file duration (seconds) |
| `diskspace` | Reserved free disk space (MB) before stopping |

**Response:** HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_recording" \
  --data-urlencode "motion_act=1" \
  --data-urlencode "postrec=10" \
  --data-urlencode "maxduration=300" \
  --data-urlencode "diskspace=500"
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=conf_ptt" \
  --data-urlencode "audiooutVol=75"
```

---

### cmd=get_ptt_vol *(read-only, no CSRF)*

Returns the current push-to-talk volume setting.

**Response:** JSON or plain text — `{"volume": N}`

```sh
curl "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=get_ptt_vol"
```

---

### cmd=get_ptt_status *(read-only, no CSRF)*

Returns the PTT backend status (whether the `ak_ao_demo` binary is available and idle/busy).

**Response:** JSON or plain text

```sh
curl "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=get_ptt_status"
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=wifi_scan"
```

---

### cmd=wifi_get_ssid *(read-only, no CSRF)*

Returns the currently configured Wi-Fi SSID from `wpa_supplicant.conf`.

**Response:** `{"status":"success","ssid":"<name>"}`

```sh
curl "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=wifi_get_ssid"
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
  -H "X-CSRF-Token: <token>" \
  --data-urlencode "cmd=delete_preset" \
  --data-urlencode "name=night_frigate"
```

---

### cmd=clear_mem

Drops Linux kernel page/slab caches (`echo 3 > /proc/sys/vm/drop_caches`).

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=clear_mem" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=reboot

Reboots the camera. Publishes an MQTT event before rebooting. Rate limited: 3 per 300 s.

**Response:** JSON or HTML (response may not be received if connection drops before reboot)

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=reboot" \
  -H "X-CSRF-Token: <token>"
```

---

### cmd=shutdown

Halts the camera (`/sbin/halt`). Rate limited: 3 per 300 s.

**Response:** JSON or HTML

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=shutdown" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi" \
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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=wizard_reset" \
  -H "X-CSRF-Token: <token>"
```

---

## GET /cgi-bin/currentpic.cgi

Returns a current JPEG snapshot from the camera sensor.

- No parameters.
- Response: `image/jpeg`
- Cached for 2 seconds (configurable via `CURRENTPIC_CACHE_TTL_SECONDS`). A lock prevents concurrent capture stampede.
- Uses the `/mnt/bin/getimage` binary (timeout 5 s).

```sh
curl -o snapshot.jpg http://root:pass@192.168.1.24/cgi-bin/currentpic.cgi
```

---

## GET /cgi-bin/health.cgi

Returns a JSON health summary for all services, cached for 45 seconds.

**Response:**
```json
{
  "ok": true,
  "ts": 1700000000,
  "services": {
    "rtsp-h26x": "running",
    "onvif": "running",
    "recording": "stopped",
    "motion-detection": "running",
    "motion-snapshot": "stopped",
    "sound-detection": "stopped",
    "mqtt-bridge": "running",
    "network-monitor": "running",
    "auto-night-detection": "running",
    "memory-guard": "running",
    "timelapse": "stopped",
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
curl http://root:pass@192.168.1.24/cgi-bin/health.cgi \
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
curl "http://root:pass@192.168.1.24/cgi-bin/events.cgi?limit=100"
```

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
curl "http://root:pass@192.168.1.24/cgi-bin/motionevents.cgi?limit=10&type=motion_on"
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
curl -o motion.jpg http://root:pass@192.168.1.24/cgi-bin/motionthumb.cgi
```

---

## GET /cgi-bin/clip_thumb.cgi

Returns a JPEG thumbnail extracted from the first keyframe of a video clip.

**Parameters:**

| Parameter | Constraints | Description |
|---|---|---|
| `path` | Relative to `/mnt/DCIM` | Clip file path |
| `size` | 64–1920 (default 320) | Thumbnail width (px) |

- Cached for 300 seconds.
- Supported formats: `mp4`, `mkv`, `avi`, `ts`, `mov`, `h264`, `h265`
- Uses `ffmpeg` to extract first keyframe.

**Error responses:**

| HTTP status | Code | Condition |
|---|---|---|
| 400 | `MISSING_PATH` | `path` parameter not supplied |
| 400 | `INVALID_PATH` | Path traversal or illegal characters |
| 400 | `UNSUPPORTED_FORMAT` | File extension not in allowed list |
| 404 | `NOT_FOUND` | File does not exist |
| 503 | `NO_FFMPEG` | `ffmpeg` not available on camera |
| 500 | `THUMB_FAILED` | ffmpeg failed to extract frame |

```sh
curl -o thumb.jpg "http://root:pass@192.168.1.24/cgi-bin/clip_thumb.cgi?path=20231114/clip.mp4&size=320"
```

---

## GET /cgi-bin/viewrecords.cgi

Manages video clip records on the SD card.

### cmd=list_dates

Returns a JSON array of date folders in `/mnt/DCIM`.

```json
[{"date":"20231114"},{"date":"20231115"}]
```

```sh
curl "http://root:pass@192.168.1.24/cgi-bin/viewrecords.cgi?F_cmd=list_dates"
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
curl "http://root:pass@192.168.1.24/cgi-bin/viewrecords.cgi?F_cmd=list_records&F_date=20231114"
```

### cmd=remove_record

Deletes a specific clip file. Rate limited: 10 per 60 s.

**Parameters:**

| Parameter | Description |
|---|---|
| `F_record` | Filename (basename only, alphanumeric+`._-`) |

**Response:** `{"ok":true}` or `{"ok":false,"error":"..."}` — error values: `invalid filename`, `file not found`, `delete failed`

```sh
curl "http://root:pass@192.168.1.24/cgi-bin/viewrecords.cgi?F_cmd=remove_record&F_record=clip_001.mp4"
```

### cmd=disk_usage

Returns SD card disk usage stats for `/mnt`.

```json
{"total_kb":15728640,"used_kb":2097152,"avail_kb":13631488,"percent":13}
```

```sh
curl "http://root:pass@192.168.1.24/cgi-bin/viewrecords.cgi?F_cmd=disk_usage"
```

---

## GET/POST /cgi-bin/camcontrols.cgi

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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/camcontrols.cgi?cmd=on&control=recording" \
  -H "X-CSRF-Token: <token>"
```

---

## GET/POST /cgi-bin/scripts.cgi

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
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/scripts.cgi?F_script=mqtt-bridge&cmd=start" \
  -H "X-CSRF-Token: <token>"
```

---

## GET /cgi-bin/sysusageinfo.cgi

Returns an HTML page with memory snapshot, CPU counters, process list, and recent events. Loads additional data client-side from `health.cgi` and `events.cgi`.

```sh
curl http://root:pass@192.168.1.24/cgi-bin/sysusageinfo.cgi
```

---

## GET /cgi-bin/network.cgi

Returns an HTML page with: network summary, open ports, interfaces, routes, DNS config, listening sockets, connections, and DNS/static-IP/WiFi configuration forms.

The embedded forms submit to `action.cgi?cmd=conf_dns`, `action.cgi?cmd=conf_static_ip`, and `action.cgi?cmd=wifi_scan`.

```sh
curl http://root:pass@192.168.1.24/cgi-bin/network.cgi
```

---

## GET /cgi-bin/devinfo.cgi

Returns an HTML page with device summary, runtime info, bootloader version/cmdline, CPU information, and binary versions.

```sh
curl http://root:pass@192.168.1.24/cgi-bin/devinfo.cgi
```

---

## GET /cgi-bin/disk.cgi

Returns an HTML page with disk space, I/O stats, mount info, SD card health (from sysfs), and a disk usage growth forecast.

```sh
curl http://root:pass@192.168.1.24/cgi-bin/disk.cgi
```

---

## POST /cgi-bin/upload_audio.cgi

Plays audio through the camera speaker (push-to-talk).

- Method: `POST` only
- Rate limit: 5 per 60 s
- Body: raw PCM — **Int16 LE, mono, 8 kHz**. Must be an even byte count.
- Max body size: 524 288 bytes (512 KB / ~32 s of audio)
- No CSRF required (treated as a media upload, not a config change)
- Uses `/usr/bin/ak_ao_demo` for playback; volume is read from `/mnt/config/pttvolume.conf` (0–100 → mapped to 0–6 for `ak_ao_demo`)

**Response:** Plain text `OK`, or one of:

| Code | Meaning |
|---|---|
| `METHOD_NOT_ALLOWED` | Not a POST request |
| `PTT_BIN_MISSING` | `ak_ao_demo` not found |
| `INVALID_CONTENT_LENGTH` | Missing or non-numeric Content-Length |
| `EMPTY_INPUT` | Zero bytes received |
| `INVALID_PCM` | Odd byte count (not valid Int16) |
| `TOO_LARGE` | Body exceeds 512 KB |
| `BUSY` | Another PTT playback is in progress |

```sh
# Record 3 s of PCM and send it to the speaker
sox -n -r 8000 -c 1 -e signed -b 16 /tmp/ptt.raw synth 3 sine 1000
curl -X POST http://root:pass@192.168.1.24/cgi-bin/upload_audio.cgi \
  --data-binary @/tmp/ptt.raw \
  -H "Content-Type: application/octet-stream"
```

---

## GET /cgi-bin/audio_stream.cgi

Streams live microphone audio as WAV.

- Method: `GET` only
- Response: `audio/wav` — WAV header followed by raw PCM (16 kHz, mono, 16-bit)
- Maximum 2 concurrent clients; 300 s per-session timeout
- Uses `arecord` internally

**Error codes (plain text, no WAV header):**

| Code | Meaning |
|---|---|
| `METHOD_NOT_ALLOWED` | Not a GET |
| `AUDIO_CAPTURE_UNAVAILABLE` | `arecord` not available |
| `TOO_MANY_CLIENTS` | 2 sessions already active |
| `UNABLE_TO_CREATE_SESSION` | Session slot allocation failed |
| `FIFO_CREATION_FAILED` | Internal FIFO pipe error |

```sh
curl http://root:pass@192.168.1.24/cgi-bin/audio_stream.cgi -o stream.wav
```

---

## GET /cgi-bin/configbackup.cgi

### cmd=download

Downloads a tar.gz archive of `/mnt/config/`.

- Response: `application/gzip`, filename `camera-config-<TIMESTAMP>.tar.gz`
- No CSRF required (read-only download)

```sh
curl -o backup.tar.gz \
  "http://root:pass@192.168.1.24/cgi-bin/configbackup.cgi?cmd=download"
```

### cmd=restore

Restores configuration from a previously uploaded tar.gz. CSRF required.

**Parameters:**

| Parameter | Description |
|---|---|
| `archive_path` | Path to archive file on camera (must be `/tmp/*.tar.gz`) |
| `restart_services` | `1`/`0` — restart services after restore |

- Validates: path must be `/tmp/`, max 16 MB, all entries must be under `config/`
- Creates a rollback archive before applying
- Response: HTML

```sh
# Upload the archive first via upload_backup.cgi, then:
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/configbackup.cgi?cmd=restore&archive_path=/tmp/backup.tar.gz&restart_services=1" \
  -H "X-CSRF-Token: <token>"
```

---

## POST /cgi-bin/upload_backup.cgi

Accepts a raw tar.gz backup archive upload and delegates to `configbackup.cgi?cmd=restore`.

- Method: `POST` only
- CSRF required
- Rate limit: 2 per 300 s
- Body: raw binary `tar.gz`, max 16 MB
- Parameter: `restart_services` (`1`/`0`)

```sh
curl -X POST http://root:pass@192.168.1.24/cgi-bin/upload_backup.cgi \
  -H "X-CSRF-Token: <token>" \
  --data-binary @backup.tar.gz \
  -H "Content-Type: application/octet-stream"
```

---

## GET/POST /cgi-bin/config_exchange.cgi

CSRF required for all commands. Rate limit: 10 per 60 s.

### cmd=export

Returns the full camera configuration as a downloadable JSON file (same data as `state.cgi?cmd=fullconfig`).

- Response: `application/json` with `Content-Disposition: attachment`

```sh
curl -o config.json \
  "http://root:pass@192.168.1.24/cgi-bin/config_exchange.cgi?cmd=export" \
  -H "X-CSRF-Token: <token>"
```

### cmd=import

Imports a JSON configuration object. Applies values via `rwconf`. Triggers async RTSP and MQTT restart.

- Method: `POST`, JSON body
- Parameters (query string or JSON):

| Parameter | Values | Description |
|---|---|---|
| `exclude_network` | `1`/`0` | Skip network-related keys |
| `exclude_credentials` | `1`/`0` | Skip password/credential keys |

```sh
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/config_exchange.cgi?cmd=import&exclude_credentials=1" \
  -H "X-CSRF-Token: <token>" \
  -H "Content-Type: application/json" \
  -d @config.json
```

---

## GET /cgi-bin/conf-export.cgi

Exports `boot.conf` and `mqtt.conf` as a single plain-text file with a magic header.

- GET only, no CSRF (read-only)
- Response: `text/plain`, filename `tc100-config-<TIMESTAMP>.conf`
- Format: `## tc100-boot-mqtt-export v1` header, then `##[SECTION:boot.conf]##` block, then `##[SECTION:mqtt.conf]##` block

```sh
curl -o settings.conf http://root:pass@192.168.1.24/cgi-bin/conf-export.cgi
```

---

## POST /cgi-bin/conf-import.cgi

Imports a `conf-export` format file, updating only allowlisted keys in `boot.conf` and `mqtt.conf`.

- Method: `POST` only
- CSRF required (`X-CSRF-Token` header)
- Body: raw text (`Content-Type: text/plain`), max 128 KB
- Must begin with `## tc100-boot-mqtt-export v1` magic header
- Only keys in the BOOT_KEYS or MQTT_KEYS allowlists are applied; all others are silently skipped

**Allowlisted boot.conf keys include** (non-exhaustive): `LIGHTWEIGHT_MODE`, `ENABLE_NTP`, `NTP_ONE_SHOT`, `WEB_MODE`, `SECURITY_HARDENING_MODE`, `MEM_GUARD_*`, `REBOOT_SCHEDULE_*`, `RTSP_SUBSTREAM`, `RTSP_AUDIO`, `ONVIF_STREAM_POLICY`, `INTEGRATION_PROFILE`, `MQTT_ENABLE`, and others.

**Allowlisted mqtt.conf keys**: `MQTT_ENABLE`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`, `MQTT_CLIENT_ID`, `MQTT_TOPIC_ROOT`, `MQTT_TOPIC_COMMAND`, `MQTT_QOS`, `MQTT_HEALTH_INTERVAL_SECONDS`, `MQTT_DISCOVERY_ENABLE`, `MQTT_DISCOVERY_PREFIX`.

**Response:**
```json
{"ok": true, "applied": 12, "skipped": 3}
```

Error responses:
```json
{"ok": false, "error": "csrf_invalid", "message": "CSRF token invalid — reload the page."}
{"ok": false, "error": "invalid_format", "message": "Not a valid TC100 config export file."}
{"ok": false, "error": "config_not_found", "message": "Cannot locate boot.conf or mqtt.conf on SD card."}
```

```sh
curl -X POST http://root:pass@192.168.1.24/cgi-bin/conf-import.cgi \
  -H "X-CSRF-Token: <token>" \
  -H "Content-Type: text/plain" \
  --data-binary @settings.conf
```

---

## GET/POST /cgi-bin/configeditor.cgi

In-browser editor for individual config files.

### GET ?file=\<name\>

Returns the file content as JSON.

**Allowed files:** `boot.conf`, `mqtt.conf`, `rtspserver.conf`, `recording.conf`, `onvif.conf`, `hostname.conf`, `ntp_srv.conf`, `timezone.conf`, `telegram.conf`, `netmon.conf`, `dns.conf`, `motion.conf`, `timelapse.conf`, `pttvolume.conf`

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
curl "http://root:pass@192.168.1.24/cgi-bin/configeditor.cgi?file=boot.conf" \
  -H "Accept: application/json"

# Save
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/configeditor.cgi?cmd=save&file=boot.conf" \
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
curl "http://root:pass@192.168.1.24/cgi-bin/wizard.cgi?check"
```

---

## GET /cgi-bin/dumpbootloader.cgi

Downloads the raw bootloader flash partition as a binary file.

- GET only; no CSRF (privileged read-only operation)
- Response: `application/x-binary`, filename `bootloader.bin`
- Uses `dd if=/dev/mtd0`

```sh
curl -o bootloader.bin http://root:pass@192.168.1.24/cgi-bin/dumpbootloader.cgi
```

---

## Notes

### Response format selection

All endpoints that support both HTML and JSON responses check whether the request includes `Accept: application/json`. If so, they return JSON. Otherwise they return HTML fragments (suitable for injection into the dashboard UI). The curl examples above use `-H "Accept: application/json"` where applicable.

### CSRF workflow

```sh
# 1. Fetch CSRF token
TOKEN=$(curl -s -H "Accept: application/json" \
  http://root:pass@192.168.1.24/cgi-bin/state.cgi?cmd=statusline \
  | sed 's/.*"csrf_token":"\([^"]*\)".*/\1/')

# 2. Use it on every state-changing request
curl -X POST "http://root:pass@192.168.1.24/cgi-bin/action.cgi?cmd=reboot" \
  -H "X-CSRF-Token: $TOKEN"
```

### Platform & performance notes (AK3918)

The camera is a single-core ARM (Anyka AK3918) with ~33 MB RAM, so the CGI layer
is written to minimise `fork`/`exec`. A few behaviours are worth knowing when
consuming this API:

- **`health.cgi` is served from a cache.** The `health-snapshot` daemon rebuilds
  `/tmp/health_snapshot.cache` every ~30 s; `health.cgi` serves it for up to 45 s
  before rebuilding inline. Service state can therefore lag reality by up to that
  window. Both paths use the shared fork-free prober `scripts/health-probe.sh`
  (pidfile checks via shell builtins; only deep/composite services exec their
  controlscript). When testing a `health.cgi` change, delete the cache file first
  — a stale entry is indistinguishable from a fix that did not take.

- **`statusline` caches its usage metrics** (`/tmp/state_usage.cache`, 2 s TTL) and
  the perf profile (5 s). The `csrf_token` it returns is generated on first call
  if absent, so a fresh client's first `statusline` poll always yields a usable
  token — no bootstrap lock-out.

- **HTTP keep-alive is 45 s / 500 requests.** Polling clients should reuse the
  connection: on this CPU a fresh TLS handshake costs up to several seconds,
  versus ~0.3–1 s for a request on an established connection.

- **MQTT is published by forging packets**, not via a client library. `curl`'s
  `mqtt://` sends SUBSCRIBE rather than PUBLISH on this device, so
  `mqtt-bridge.sh` builds the MQTT 3.1.1 CONNECT/PUBLISH/DISCONNECT frames in
  shell and pipes them to `nc`. Published at QoS 0; the retain flag is honoured
  (HA discovery and availability topics are retained). `statusline` exposes
  `mqtt_last_pub_ok` (1/0/-1) so the UI can show publish health.

- **`tr(1) is absent`** on the device — see the README's platform section. It
  affects CGI internals, not this API's request/response contract.
