# TECKIN TC100 / Anyka AK3918 — Firmware Extension
**Version 1.6.0** — *Frigate & Home Assistant Edition*

Cloud-free, MicroSD-based firmware extension for the **Teckin TC100 / Teckin Click** (CPU Anyka AK3918 v300). Optimized for direct Frigate + Home Assistant integration without any cloud dependency.

---

## Highlights

- **First-boot wizard** — guided setup for profile, security, WiFi, and MQTT on a fresh SD card.
- **Tabbed Elite Dashboard** — single-page UI (Dashboard, Video, ISP, Automation, Network, System) built on Bulma 1.0.2 with custom SVG icons.
- **Frigate HA profile** — auto-disables unused daemons (3–6 MB RAM freed), RTSP pipeline tuned for Frigate segment ingestion, MQTT discovery for Home Assistant.
- **Privacy Shield** — one-click Stealth Mode that severs all outbound traffic.
- **Safety Snapshots** — save and restore known-good configuration checkpoints before tuning experiments.
- **Config export / import** — download or restore `boot.conf` + `mqtt.conf` as a single versioned file.
- **WiFi reconfiguration** — update SSID and PSK from the Network tab without touching the SD card.
- **Full legacy parity** — LED controls, Telegram bot, Timelapse, Syslog forwarding, email notifications all preserved.

---

## Features

### Video & Streaming
- RTSP main + sub streams via `v4l2rtspserver`; ONVIF compatible.
- Optimization presets: `Frigate Balanced`, `Universal H264`, `Maximum Performance`.
- RTSP deep health check (detects GOP stalls, not just process liveness).
- CPU scaler — auto-adjusts resolution/fps under load.

### Home Assistant / Frigate
- `INTEGRATION_PROFILE=frigate_ha` trims autostart to only what Frigate needs.
- MQTT bridge with structured telemetry, motion events, and HA MQTT discovery.
- Integration manifest via `state.cgi?cmd=integrationmanifest` (ready-to-paste Frigate YAML).
- Service watchdog with auto-restart, backoff, and MQTT alerts.

### Security & Privacy
- HTTPS (self-signed) — required for PTT mic API.
- CSRF protection on all mutating endpoints; per-boot token.
- Security hardening mode (disable telnet, restrict CGI surface).
- Privacy Shield: one-click isolation of all outbound paths.
- Password change and HTTPS toggle from the wizard and System tab.

### System Management
- **First-boot wizard** (`/cgi-bin/wizard.cgi`) — 3 or 4 steps depending on profile.
- **WiFi reconfiguration** — live `wpa_cli reconfigure` after applying new credentials.
- **Config export/import** — `conf-export.cgi` / `conf-import.cgi` with key allowlist validation.
- **Wizard reset** — System tab button to re-run setup from scratch.
- Memory guard daemon — OOM prevention with configurable warn/critical/emergency thresholds.
- Storage cleanup daemon — auto-prune recordings at configurable disk threshold.
- Firmware update checker — semantic version comparison against remote manifest.
- SD write preflight — checks free space and write speed before recording/timelapse.

### Audio
- Two-way audio: live listen + PTT (hold-to-talk via browser mic — requires HTTPS).
- Audio clip upload and playback.

### Notifications & Monitoring
- Telegram bot daemon for motion events.
- Email notifications (sendPictureMail).
- Remote Syslog forwarding.
- Health snapshot — periodic system state capture for diagnostics.
- Network monitor daemon.

### Automation
- Timelapse studio with schedule management.
- Motion schedule (arm/disarm on a cron schedule).
- Night mode auto-detection.
- LED granular control (front activity LED + IR LEDs independently).

---

## Installation

1. Format MicroSD as FAT32 (32 KB allocation size recommended).
2. Copy repository contents to the card root.
3. Create `wpa_supplicant.conf` from `wpa_supplicant.conf.dist` and set your Wi-Fi SSID/PSK.
4. Insert card into camera and power on.
5. Open `https://CAMERA-IP` in a browser — the first-boot wizard will appear automatically.
   - Default IP: `192.168.1.24` · Default credentials: `root` / `pass`

---

## Home Assistant / Frigate Quick Start

1. In the wizard (or Network tab), select profile `frigate_ha` and configure MQTT host/credentials.
2. Restart the camera — MQTT discovery publishes entities to HA automatically.
3. RTSP streams (the v4l2rtspserver mountpoints are `video0_unicast` /
   `video1_unicast`, not `stream0`/`stream1`):
   - Main (recording): `rtsp://CAMERA-IP:554/video0_unicast`
   - Sub (detection): `rtsp://CAMERA-IP:554/video1_unicast`
4. Fetch a ready-to-paste Frigate config (go2rtc restream, current Frigate
   schema): `GET /cgi-bin/state.cgi?cmd=frigateyaml` (add `&redact=1` to share it
   without credentials). The raw machine-readable manifest is still available at
   `GET /cgi-bin/state.cgi?cmd=integrationmanifest`.

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
verified on two live cameras. Kept here for the record; see `CHANGELOG.md` for detail.

| Symptom | Cause | Status |
|---------|-------|--------|
| MQTT never reached the broker | `curl --upload-file` sends `SUBSCRIBE` not `PUBLISH` on curl 8.1.2; the bridge now forges the MQTT packets and pipes them to `nc` | Fixed 1.6.0 |
| WiFi SSID blank / reconfig ignored | read a `wpa_supplicant.conf` that need not exist; write path disagreed with `autorun.sh` | Fixed 1.5.0 |
| Dashboard buttons fail with 403 | `csrf_guard()` filtered tokens through `tr`, absent on the device — both sides collapsed to empty | Fixed 1.4.0 |
| `health.cgi` output rejected by parsers | `/proc/meminfo` values pad with multiple spaces; only one was stripped | Fixed 1.4.0 |
| First-boot wizard stuck on "Réessayer" | Same missing `tr` broke POST body parsing | Fixed 1.4.0 |

A CI lint (`.github/workflows/test.yml`) now fails the build on any bare `tr` in
camera-side shell without the `busybox` shim in scope — the root cause behind
most of the above.

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

When testing a `health.cgi` change, clear `/tmp/health_snapshot.cache` first: responses are cached for 45 s and a
stale entry looks exactly like a fix that did not take.

---

## Development Workflow

```bash
# After any JS or CSS edit:
npm run build:web

# Verify no drift (CI gate):
npm run check:web
```

Source lives in `frontend/src/` — **never edit `www/scripts/` or `www/css/ui-modern.min.css` directly.**

### Claude Code skills (project-local)

| Skill | Usage |
|-------|-------|
| `/deploy [ip]` | FTP upload of changed files to camera |
| `/commit` | Stage and commit with project conventions |
| `/healthcheck [ip]` | Ping + health.cgi status summary |
| `/camera-probe <endpoint> [ip]` | Test a CGI endpoint on live hardware |
| `/camera-logs [type] [lines] [ip]` | Fetch camera logs via FTP |
| `/validate-cgi [path]` | Review a CGI script for correctness |

---

## Repository Structure

```
www/cgi-bin/        CGI endpoints (shell, executable)
frontend/src/       Frontend source (JS, CSS) — edit here
www/scripts/        Built frontend assets — do not edit directly
scripts/            Autonomous daemons and one-shot scripts
controlscripts/     On/off toggles for daemons (called with on|off)
config/             Config templates (*.conf.dist) and autostart scripts
config/autostart/   Boot scripts executed in numeric order by autorun.sh
docs/               API reference and project documentation
```

---

*LAN-only. No cloud required. Privacy by default.*
