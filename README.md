# TECKIN TC100 / Anyka AK3918 — Firmware Extension

> **1.8.4** — the code now runs from a read-only, checksummed image on the SD card; firmware updates from the web UI (only changed files written, rollback); a French / English interface; Home Assistant diagnostics (Wi-Fi, memory, SD card, sound level); SD-card wear cut down (only important events are written); G.711 audio and run-time fixes for the vendor RTSP server (`libtc100fix.so`); a fix for Frigate losing the cameras several times an hour; an optional up-to-date Wi-Fi client. Everything verified on two cameras. See [CHANGELOG.md](CHANGELOG.md).

**Version 1.8.4** — *Frigate & Home Assistant Edition*

Cloud-free, MicroSD-based firmware extension for the **Teckin TC100 / Teckin Click** (CPU Anyka AK3918 v300). Optimized for direct Frigate + Home Assistant integration without any cloud dependency.

---

## Highlights

- **Read-only firmware image** — `bin lib scripts controlscripts www` run from `firmware.sqfs`, loop-mounted read-only and md5-checked after each boot; the normal files on the card stay underneath as the fallback. A FAT corruption caused by recordings or logs can no longer damage the code.
- **Firmware update from the web UI** — upload a package in Settings → Firmware update: every file is checked against its md5, only the changed ones are written, the previous ones are kept for a one-click rollback.
- **Offline by design** — nothing needs the internet; the GitHub release check is off unless `UPDATE_CHECK=1`.
- **French / English interface** — FR/EN switch in the top bar, kept per browser.
- **First-boot wizard** — guided setup for profile, security, WiFi, and MQTT on a fresh SD card.
- **Working MQTT publishing** — the bridge forges MQTT packets and pipes them to `nc`, because this device's `curl` cannot PUBLISH. HA discovery, telemetry and availability all reach the broker.
- **Multi-camera by hostname** — MQTT identity (client id, topic root, HA device) is derived from the hostname, so two cameras from the same image show up as two distinct devices in Home Assistant. The firmware version appears on the HA device page.
- **Home Assistant diagnostics** — Wi-Fi signal and drops, refused connections, available memory, sound level, light level, night mode, SD card state, as discovered entities.
- **Tabbed Elite Dashboard** — single-page UI (Dashboard, Video, ISP, Automation, Network, System) built on Bulma 1.0.2, with a working light/dark theme toggle.
- **Frigate HA profile** — auto-disables unused daemons (3–6 MB RAM freed), RTSP pipeline tuned for Frigate segment ingestion, MQTT discovery for Home Assistant.
- **Privacy Shield** — one-click Stealth Mode that severs all outbound traffic.
- **Safety Snapshots** — save and restore known-good configuration checkpoints before tuning experiments.
- **Transactional config import/restore** — validate complete candidates in `/tmp`, then commit all files together with automatic rollback on write or verification failure.
- **WiFi reconfiguration** — update SSID and PSK from the Network tab without touching the SD card.
- **Full legacy parity** — LED controls, Telegram bot, Timelapse, Syslog forwarding, email notifications all preserved.

---

## Features

### Video & Streaming
- RTSP main + sub streams via `v4l2rtspserver`; ONVIF compatible.
- Optimization presets: `Frigate Light AK3918` (recommended), `Frigate Balanced`, `Frigate Quality`, `Universal H264`, `Hybrid HEVC/264`.
- Run-time fixes for the vendor RTSP server through `lib/libtc100fix.so` (LD_PRELOAD): optional fixed frame rate, microphone off when no audio is served, live image tuning (brightness, contrast, 3D noise reduction…), slower day/night polling (-2 % CPU), ISP statistics for a future lens-covered alert.
- "Smooth live" button: opens the camera in Frigate's live view (go2rtc restream, no extra load on the camera); the camera's name in Frigate is found automatically.
- RTSP deep health check (detects GOP stalls, not just process liveness).
- CPU scaler — auto-adjusts resolution/fps under load.

### Home Assistant / Frigate
- `INTEGRATION_PROFILE=frigate_ha` trims autostart to only what Frigate needs.
- MQTT bridge with structured telemetry, motion events, and HA MQTT discovery.
  Both directions are forged in shell and piped to `nc` — the platform `curl`
  cannot do MQTT on this firmware.
- **Two-way control**: HA can drive the camera (LEDs, profile, snapshot, motion
  toggle…) by publishing to `<topic-root>/command`; results come back on
  `<topic-root>/command/result` and `.../last_result` (retained).
- **Per-camera identity from the hostname.** When `MQTT_CLIENT_ID` / `MQTT_TOPIC_ROOT`
  are left at their defaults, the bridge derives them from a slug of the hostname
  (`IPCAMERA1` → topic root `ipcamera1`, HA device `IPCAMERA1`). Give each camera a
  unique hostname and two units stop colliding as one HA device.
- Firmware version is reported on the HA device page (`sw` in the discovery device block).
- Integration manifest via `state.cgi?cmd=integrationmanifest` (ready-to-paste Frigate YAML).
- MQTT publishes go through the bridge's persistent connection when it is up (no new TCP connection per message).
- Diagnostics in `<topic-root>/health` with HA discovery entities (see Highlights).
- Service watchdog with auto-restart, backoff, and MQTT alerts.
- Commands are received over a **persistent** subscription, so ordinary
  (non-retained) QoS 0 publishes from HA are picked up — no need to publish
  retained and clear the topic afterwards, as earlier versions required.
  Set `MQTT_PERSISTENT_SUBSCRIBE=0` to fall back to the old windowed polling
  (lower memory, but commands sent between windows are lost).

### Security & Privacy
- HTTPS (self-signed) — required for PTT mic API.
- CSRF protection on all mutating endpoints; per-boot token.
- Security hardening mode (disable telnet, restrict CGI surface).
- Privacy Shield: one-click isolation of all outbound paths.
- Password change and HTTPS toggle from the wizard and System tab.
- Optional Wi-Fi client `wpa_supplicant` 2.11 (`WIFI_CLIENT=new` in `boot.conf`) instead of the vendor 0.8.x from 2013; falls back to the vendor client if it has not connected within 60 s.

### System Management
- **First-boot wizard** (`/cgi-bin/wizard.cgi`) — 3 or 4 steps depending on profile.
- **WiFi reconfiguration** — reads the live SSID from the interface (`wpa_cli` /
  `iwconfig`, not a config file that may not exist), writes the credentials to the
  path `autorun.sh` actually reads, and triggers a live `wpa_cli reconfigure`.
- **Per-camera hostname** — set in the wizard or Network tab; drives the MQTT/HA identity.
- **Config export/import** — `conf-export.cgi` / `conf-import.cgi` with key allowlist validation.
- **Wizard reset** — System tab button to re-run setup from scratch.
- Memory guard daemon — OOM prevention with configurable warn/critical/emergency thresholds.
- Storage cleanup daemon — auto-prune recordings at configurable disk threshold.
- **Firmware update** (Settings → Firmware update, `scripts/fw-update.sh`): verified package, delta install, rollback, web server config checked before reboot.
- Release check against GitHub — off by default (`UPDATE_CHECK=1` to enable).
- **SD card wear**: syslog filtered to notice level and above, kept in RAM; important lines (FAT/MMC errors, OOM, crashes, `tc100-event`) copied to `/mnt/log/important.log` every 5 min; health samples written once an hour; `noatime`.
- Reboot history with the reason of each restart (Device Info).
- SD write preflight — checks free space and write speed before recording/timelapse.

### UI & Performance
- French / English interface (`www/scripts/i18n.js`, dictionary in `www/i18n/fr.js`); defaults to the browser language.
- Light/dark theme toggle that actually re-themes the UI (keyed on `data-theme`,
  resolved in JS, stamped before first paint so there's no light flash).
- Tuned for the AK3918 (single core, ~33 MB RAM): fork-free service probing
  (`scripts/health-probe.sh`), HTTP keep-alive (avoids an RSA handshake per poll),
  NTP clock step before the web server starts (no boot-time graceful restart), and
  a `jq`-free statusline hot path. See `docs/api.md` → *Platform & performance notes*.

### Audio
- Two-way audio: live listen + PTT (hold-to-talk via browser mic — requires HTTPS).
- PTT works on the TC100 speaker. The AK3918 has a single exclusive audio codec
  device, so while a clip plays the RTSP stream is paused (a few seconds) and
  restarted automatically afterwards; Frigate/go2rtc simply reconnect.
- Audio clip upload and playback.
- Main stream audio in G.711 A-law by default (AAC cost ~8 % CPU).
- Sound detection with a real level meter in dBFS (threshold `THRESHOLD_DB`, default -24), measured inside the RTSP server at no extra cost.

### Notifications & Monitoring
- Telegram bot daemon for motion events.
- Email notifications (sendPictureMail).
- Remote syslog forwarding over UDP (e.g. Synology Log Center: Log Receiving, BSD format, UDP 514).
- Health snapshot — periodic system state capture for diagnostics.
- Network monitor daemon.

### Automation
- Timelapse studio with schedule management.
- Motion schedule (arm/disarm on a cron schedule).
- Night mode auto-detection.
- LED granular control (front activity LED + IR LEDs independently).

---

## Installation

1. Format MicroSD as FAT32 (32 KB allocation size recommended) or exFAT.
2. Copy repository contents to the card root. To also get the read-only image,
   build it (`src/release/build-image.sh`, needs `squashfs-tools`) and copy
   `dist/firmware.sqfs` and `dist/firmware.sqfs.md5` to the card root; without
   them the camera simply runs from the copied files. Cameras already running
   1.8.x are updated from Settings → Firmware update with a package built by
   `src/release/build-update.sh` (it includes the image).
3. Create `wpa_supplicant.conf` from `wpa_supplicant.conf.dist` and set your Wi-Fi SSID/PSK.
4. Insert card into camera and power on.
5. Open `https://CAMERA-IP` in a browser — the first-boot wizard will appear automatically.
   - The camera gets its address from your router (DHCP) · Default credentials: `root` / `pass` (change them)
   - Give each camera a **unique hostname** in the wizard — it names the HA device
     and MQTT topic root.

> Live config holding secrets (`config/mqtt.conf`, `config/user.pwd`,
> `wpa_supplicant.conf`) is git-ignored; only the `*.dist` templates are tracked.
> Seed your credentials into the live copies on the SD card, not into the templates.

---

## Home Assistant / Frigate Quick Start

1. In the wizard (or Network tab), select profile `frigate_ha` and configure MQTT host/credentials.
2. **Give the camera a unique hostname** (wizard or Network tab) — this is what
   names its HA device and MQTT topic root. With more than one camera, use a
   distinct name each (e.g. `IPCAMERA1`, `IPCAMERA2`), or they merge into one HA device.
3. Restart the camera — MQTT discovery publishes entities to HA automatically, and
   the HA device page shows the firmware version.
4. RTSP streams (the v4l2rtspserver mountpoints are `video0_unicast` /
   `video1_unicast`, not `stream0`/`stream1`):
   - Main (recording): `rtsp://CAMERA-IP:554/video0_unicast`
   - Sub (detection): `rtsp://CAMERA-IP:554/video1_unicast`
5. Fetch a ready-to-paste Frigate config (go2rtc restream, current Frigate
   schema): `GET /cgi-bin/state.cgi?cmd=frigateyaml` (add `&redact=1` to share it
   without credentials). The raw machine-readable manifest is still available at
   `GET /cgi-bin/state.cgi?cmd=integrationmanifest`.
6. **Still image in HA at zero camera cost** — add a *Generic Camera*
   integration (Settings → Devices & Services → Add → Generic Camera) with:
   - Still image URL: `https://CAMERA-IP/cgi-bin/currentpic.cgi`
   - Basic auth `root` / your password · SSL verification off (self-signed cert)

   HA pulls a JPEG on demand and the camera's built-in 2 s snapshot cache
   absorbs the polling. This replaces the MQTT camera entity, which is disabled
   by default because HA's MQTT camera expects image *bytes* while the bridge
   publishes a file *path* (`MQTT_HA_CAMERA_ENTITY_ENABLE=1 `re-enables it).
   For live video use the RTSP/go2rtc streams above.

> **Upgrading a camera that was already paired to HA?** Changing the topic root
> (default → hostname-derived) leaves the old retained discovery behind as a ghost
> device. Delete the stale device in HA, or clear the old
> `homeassistant/…/<old-id>/…/config` topics with empty retained payloads.

---

## CGI API

Full reference in [`docs/api.md`](docs/api.md) — covers all 25+ endpoints with method, parameters, JSON response schema, and curl examples.

Key endpoints:

| Endpoint | Purpose |
|----------|---------|
| `state.cgi?cmd=all` | Full system state snapshot |
| `action.cgi?cmd=<cmd>` | All mutating commands (CSRF required) |
| `health.cgi` | Lightweight liveness check |
| `wizard.cgi` | First-boot setup wizard |
| `conf-export.cgi` | Download config backup |
| `conf-import.cgi` | Upload and apply config backup |

---

## Known issues

All the issues found during the August 2026 hardware bring-up have been fixed and
verified on live cameras (PTT since 1.8.3). Kept here for the record; see `CHANGELOG.md` for detail.

| Symptom | Cause | Status |
|---------|-------|--------|
| SD card turned read-only during an update, files full of garbage | writes on the card sometimes come out with a run of zeroed pages under memory pressure; the update extracted the whole 16 MB package to compare checksums. Every written file is now checked against its md5 and rewritten, only changed files are extracted, and the code runs from a checksummed read-only image | Mitigated 1.8.4 |
| Frigate/go2rtc lost the camera 30–50 times an hour (`i/o timeout`) | `tcp_tw_recycle=1` dropped SYNs from clients behind NAT/Docker; now 0 | Fixed 1.8.4 |
| Browser warns on HTTPS; `sslv3 alert certificate unknown` in the lighttpd log | the self-signed cert was issued for 365 days and only regenerated when *missing*, so any camera past its first year served an expired certificate. It is now also regenerated when `openssl x509 -checkend 0` fails, is valid 10 years, and uses ECDSA P-256 (handshake ~0.09 s vs ~0.14 s for the RSA-1024 it replaces) | Fixed 1.8.1 |
| HA "Live" camera entity shows nothing | it points at `snapshot/last_path`, a file PATH, while HA's MQTT camera expects image BYTES. Entity now off by default (`MQTT_HA_CAMERA_ENTITY_ENABLE=1` to re-enable); use the RTSP/go2rtc stream instead | Disabled 1.6.2 |
| Dashboard liveview / snapshot blank | `/bin/timeout` is the pre-2014 busybox variant wanting `-t SECS`; `timeout 5 getimage` exec'd the duration and failed silently, so `currentpic.cgi` served a 0-byte JPEG | Fixed 1.7.1 |
| Push-to-talk is silent | two causes: `v4l2rtspserver` holds the exclusive codec device `/dev/akpcm_cdev1`, and the TC100 amplifier enable is active-low while stock `ak_ao_demo` drives it the other way. PTT now pauses RTSP only for the clip, and plays through `/mnt/bin/ak_ao_ptt`, an MD5-guarded copy of `ak_ao_demo` with the two speaker-control instructions flipped (the stock binary is untouched) — see CHANGELOG 1.8.3-rc8 → rc10 | Fixed 1.8.3 |
| Inbound HA → camera commands time out | the SUBSCRIBE path used `curl`, which can't do MQTT here; it is now forged like the publish path | Fixed 1.6.2 |
| Cameras listened on a shared command topic | 1.6.1 re-derived the topic root but left `MQTT_TOPIC_COMMAND` at its written-out default, so every camera received every camera's commands | Fixed 1.6.2 |
| Two cameras merged into one HA device | shared default `MQTT_CLIENT_ID` / topic root; identity now derives from the hostname | Fixed 1.6.1 |
| Firmware version not shown in HA | discovery device block now carries `sw` from `/mnt/VERSION` | Fixed 1.6.1 |
| Config import silently did nothing | `conf-import.cgi` used bare `tr -d '\r'` with no shim — emptied the upload | Fixed 1.6.1 |
| MQTT never reached the broker | `curl --upload-file` sends `SUBSCRIBE` not `PUBLISH` on curl 8.1.2; the bridge now forges the MQTT packets and pipes them to `nc` | Fixed 1.6.0 |
| WiFi SSID blank / reconfig ignored | read a `wpa_supplicant.conf` that need not exist; write path disagreed with `autorun.sh` | Fixed 1.5.0 |
| Dashboard buttons fail with 403 | `csrf_guard()` filtered tokens through `tr`, absent on the device — both sides collapsed to empty | Fixed 1.4.0 |
| `health.cgi` output rejected by parsers | `/proc/meminfo` values pad with multiple spaces; only one was stripped | Fixed 1.4.0 |
| First-boot wizard stuck on "Réessayer" | Same missing `tr` broke POST body parsing | Fixed 1.4.0 |

A bare `tr` in camera-side shell without the `busybox` shim in scope was the root
cause behind most of the above — see the platform note below before adding one.

A boot-time probe (`scripts/capability-check.sh`) tests these tools by **behaviour** rather than presence —
`command -v` passes for `timeout`, which exists but wants the old `-t SECS` syntax. Its verdict appears under
`capabilities` in `health.cgi`, separating `shimmed` (expected here) from `failed` (genuinely broken).

### Platform constraint: `tr(1)` is not available

The camera's busybox includes the `tr` applet but ships no symlink for it, and `/mnt/bin` is not on the CGI `PATH`
(`/sbin:/usr/sbin:/bin:/usr/bin`). Any `tr` invocation fails with `tr: not found` (exit 127) and, in a command
substitution, silently yields an empty string — so the failure surfaces as bad data rather than an error.

`awk`, `sed`, `cut`, `grep`, `head`, `sort` and `od` are all present. Use `awk` for character filtering
(`gsub(/[^…]/, "")` replaces `tr -cd`) and for field splitting (`BEGIN { RS = "&" }` replaces `tr '&' '\n'`).

CGIs that source `func.cgi` (19 of them) and daemons that source `scripts/common_functions.sh` (including
`autorun.sh` and `mqtt-bridge.sh`) get a `tr()` shell function that falls back to `busybox tr`, so existing `tr`
calls there work. Fully standalone scripts — e.g. `wizard.cgi`, which sources neither — must avoid `tr` themselves.
Prefer awk regardless: the shim still pays one `busybox` exec per call, which matters in loops (see
`load_conf_file` in `state.cgi`).

When testing a `health.cgi` change, clear `/tmp/health_snapshot.cache` first: responses are cached for the snapshot interval plus 15 s (75 s by default), and a
stale entry looks exactly like a fix that did not take.

---

## Repository Structure

This repository is the runtime payload: copy its contents to the SD card root.

```
autorun.sh          Boot entry point
VERSION             Firmware version string
bin/                Prebuilt ARM binaries (busybox, curl, lighttpd, …)
lib/                Shared libraries
www/                Web UI + CGI endpoints (www/cgi-bin/ are shell scripts)
scripts/            Autonomous daemons and one-shot scripts
controlscripts/     On/off toggles for daemons (called with on|off)
config/             Config templates (*.conf.dist) and autostart scripts
config/autostart/   Boot scripts executed in numeric order by autorun.sh
sounds/             Alert/notification audio
docs/               API reference and project documentation
src/                Build sources: libtc100fix shim (src/tc100fix), lighttpd,
                    wpa_supplicant 2.11 (src/wpa_supplicant), release packages
                    and read-only image (src/release), web UI tools (src/webui:
                    Bulma purge, untranslated strings check)
tests/              Regression tests (python3 -m unittest tests.test_regressions)
```

Generated, not in git: `firmware.sqfs` (+ `.md5`) at the card root, from
`src/release/build-image.sh`. Binaries are built with the Anyka uClibc toolchain
(`arm-anykav200-crosstool`); most of `bin/` comes from
[anyka-software](https://github.com/ThatUsernameAlreadyExist/anyka-software), and
`v4l2rtspserver` from
[anyka-v4l2rtspserver](https://github.com/ThatUsernameAlreadyExist/anyka-v4l2rtspserver)
(both public domain).

The web assets under `www/` are prebuilt and served as-is.

---

*LAN-only. No cloud required. Privacy by default.*
