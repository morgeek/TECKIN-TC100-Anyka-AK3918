# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.3.0] — 2026-06-25

### Added
- **First-boot wizard** (`wizard.cgi`) — guided 3- or 4-step setup on first insert of a fresh SD card: profile selection, security (password + HTTPS), MQTT (frigate_ha profile only), and summary with one-click apply.
- **MQTT step in wizard** — host, port, user, password fields; skipped automatically when profile ≠ `frigate_ha`; dynamic step bar adjusts dot count accordingly.
- **WiFi reconfiguration** (Network tab) — reads current SSID from `wpa_supplicant.conf`, form to update SSID + PSK, live `wpa_cli reconfigure` trigger; warns about connection interruption.
- **Wizard reset** (System tab) — button to delete `.wizard_done` and re-run the setup wizard; confirmation required.
- **Config export** (`conf-export.cgi`) — downloads `boot.conf` + `mqtt.conf` as a single versioned `.conf` file.
- **Config import** (`conf-import.cgi`) — uploads a previously exported file, validates the magic header, filters keys against an allowlist (60+ boot keys, 12 MQTT keys), writes atomically; CSRF-protected.
- **RTSP pipeline optimizations for `frigate_ha` profile** — GOP length tuning, keyframe interval alignment, reduced VBR overhead for Frigate's segment ingestion.
- **Frigate HA daemon denylist** — when `INTEGRATION_PROFILE=frigate_ha`, autorun.sh automatically excludes telegram-bot, timelapse, syslog-forward, sound-detection, ftp-server, telnet-server, and recording from autostart (3–6 MB RAM freed).
- **state.cgi profile-aware skipping** — with `frigate_ha` profile, sections for disabled daemons (telegram, timelapse, syslog, recording) are skipped to reduce per-call shell overhead (~900 calls/hour at 4 s polling).
- **MQTT health interval raised** — default `MQTT_HEALTH_INTERVAL_SECONDS` changed from 120 s to 300 s (transparent to HA, which uses LWT for availability).
- **Memory-guard interval raised** — default `MEM_GUARD_INTERVAL_SECONDS` changed from 20 s to 60 s when fewer daemons are running under `frigate_ha`.
- **CGI API reference** (`docs/api.md`) — 2 200-line reference documenting all 25+ endpoints: method, parameters, JSON response schema, and curl examples. Includes full CSRF workflow section.
- **`csrfFetch` exposed on `window.EliteUI`** — inline scripts in `settings.html` can now call `window.EliteUI.csrfFetch()` for CSRF-aware requests without duplicating the token logic.
- **Claude Code tooling** — project-local skills (`/deploy`, `/commit`, `/validate-cgi`, `/healthcheck`, `/camera-probe`, `/camera-logs`) and sub-agents (`shell-reviewer`, `security-reviewer`, `frontend-reviewer`, `code-reviewer`); PostToolUse hook auto-rebuilds `www/` on frontend edits.

### Changed
- `action.cgi` — three new commands: `wifi_get_ssid` (read-only, CSRF-exempt), `wifi_set_config`, `wizard_reset`.
- `deploy` skill — now diffs from `.claude/.last-deploy-sha` instead of `HEAD` so committed-but-undeployed files are always included.

### Fixed
- `wizard.cgi` — `applyConfig()` now checks `response.ok === true` before showing the success screen; previously any HTTP 200 was treated as success.
- `wizard.cgi` — MQTT user/password sanitized with `tr -cd` before writing to config (downstream sourcing safety).
- `wizard.cgi` — `renderSummary()` now escapes MQTT fields with `esc()` before inserting into `innerHTML`.
- `conf-import.cgi` — `set_conf()` escapes backslashes via `sed` before passing values to `awk -v` to prevent `\n`/`\t` expansion.
- `conf-import.cgi` — uses `expr` for arithmetic throughout (no `$((...))` bash-ism).
- `action.cgi` `wifi_set_config` — temp file cleaned on `mv` failure to avoid leaving stale files on FAT32.
- `action.cgi` `wifi_get_ssid` — uses `[ \t]` in awk instead of `[[:space:]]` for Busybox compatibility.

---

## [1.2.0] — 2025 — *Elite Edition*

### Added
- Full rewrite of the web dashboard as a single-page tabbed UI (Dashboard, Video, ISP, Automation, Network, System) using Bulma 1.0.2.
- 100% custom SVG iconography — no icon font CDN dependency.
- **Elite Optimization Presets** — one-click tuning for `Frigate Balanced`, `Universal H264`, and `Maximum Performance`.
- **Safety Snapshot** — save and restore "Known-Good" configuration checkpoints.
- **Privacy Shield / Stealth Mode** — one-click isolation of all outbound traffic paths.
- **CPU scaler** daemon — dynamically adjusts stream resolution/fps under load.
- **Service watchdog** — monitors RTSP and ONVIF processes; auto-restarts with backoff, alerts via MQTT.
- **RTSP deep health check** — detects GOP stalls, not just process liveness.
- **MQTT bridge** (`mqtt-bridge.sh`) — structured telemetry, motion events, system health; Home Assistant MQTT discovery.
- **Firmware update checker** — semantic version comparison against remote manifest, shown as dashboard notification.
- **SD write preflight** — checks available space and write speed before starting recording or timelapse.
- **Log-level filtering** — configurable verbosity per daemon without restarting.
- **Configuration editor** (`configeditor.cgi`) — in-browser editing of raw `.conf` files with validation.
- **Config profiles** (`config_exchange.cgi`) — save, load, and share named configuration presets.
- **CSRF protection** — per-boot token, enforced on all mutating CGI commands; read-only commands explicitly whitelisted.
- Zero-fork state polling — replaced shell `date` subprocesses with an inline ISO 8601 formatter in awk.
- Frontend source-of-truth enforced: `frontend/src/` → `www/` via `npm run build:web`; `npm run check:web` is a CI gate.

---

## [1.1.x] — Legacy

- Two-way audio (listen + PTT via HTTPS mic API).
- Timelapse studio with schedule management.
- Telegram bot daemon for motion notifications.
- Remote Syslog forwarding.
- LED granular control (front activity LED + IR LEDs).
- ONVIF support.
- Memory guard daemon (OOM prevention, configurable thresholds).
- Storage cleanup daemon (auto-prune recordings at threshold).
- FTP server controlscript.
- Email notifications (sendPictureMail).
- Night mode auto-detection daemon.

---

## [1.0.0] — Initial release

- Cloud-free MicroSD boot.
- RTSP streaming via `v4l2rtspserver`.
- lighttpd web server with CGI.
- Motion detection integration.
- Basic web UI.
