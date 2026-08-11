# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.6.0] — 2026-08-11

The headline: **MQTT actually publishes now** — the camera's whole reason to
speak MQTT (Home Assistant discovery, telemetry, motion events) worked for the
first time on hardware this release.

### Added / Fixed — MQTT publishing
- **`mqtt-bridge.sh` — messages are finally delivered.** `curl --upload-file mqtt://…` never published on this device's curl 8.1.2 (it sent SUBSCRIBE, not PUBLISH). `mqtt_publish_raw()` now forges the MQTT 3.1.1 CONNECT + PUBLISH(QoS0) + DISCONNECT packets in pure ash — `printf` is a builtin and emits `\xNN` bytes including NUL — and pipes them to `nc`. Success is confirmed by the broker's CONNACK in nc's reply. Verified end-to-end against the live broker: HA discovery config topics, health, availability and events all arrive; `mqtt_last_pub_ok` flips to 1. QoS is 0 (no packet-id/PUBACK bookkeeping in shell); the retain flag is preserved, which is what discovery and availability need.

### Performance
- **`state.cgi` statusline drops two `jq` forks.** The update-notifier read `/tmp/update_status.json` via two `jq` invocations, ~0.3 s each on the AK3918 and the dominant per-poll cost. Replaced with a single `read` + shell parameter expansion (the file is a flat one-line object).
- **NTP steps the clock before the web server starts.** In daemon mode `sync_time` ran a bare `ntpd -p` that forks and returns immediately, then makes its first step ~30–40 s later — after lighttpd is up. The jump tripped lighttpd's "clock jumped" graceful restart, dropping every keep-alive connection and stamping early logs with 1970 dates. A bounded (`busybox timeout 15`) one-shot step now runs first, then the disciplining daemon.

### Fixed
- **`conf-import.cgi` — latent `tr` bug (same class as 1.4.0/1.5.0).** This CGI sources neither `func.cgi` nor `common_functions.sh`, so it has no `tr()` shim, yet it used bare `tr`: `tr -d '\r'` on the uploaded body would have emptied it (silent no-op import), and the CSRF token strip would have collapsed both sides and bypassed the check. Rewritten in awk. Exercised end-to-end on hardware (export → import round-trip applies 92 keys; malformed input rejected).

### CI
- **`tr(1)` lint added to `.github/workflows/test.yml`.** Shim-aware: a bare `tr` fails CI unless the file has the `tr()`→`busybox tr` shim in scope (defines it, or sources `func.cgi`/`common_functions.sh`). This is the guard that would have caught all five `tr` bugs before they shipped.

### Tooling
- **`tools/deploy-full.sh` rewritten** around the failures observed during the 2026-08-11 deploy to the first camera (each one hit on real hardware):
  - Binaries (`bin/*`, `lib/*`) identical to the camera's copy are skipped by size comparison; differing ones are refused with a clear list unless `--force-binaries`. This is what prevents the ETXTBSY write onto a running daemon's binary that killed lighttpd mid-deploy.
  - Everything is batched — one curl invocation carries many URLs, so the camera's slow FTP login (~7 s on one unit, ~19 s on the other) is paid ~15 times instead of ~500. Preflight timeouts raised accordingly (the second camera's FTP accepts too slowly for the old 15 s cap).
  - The backup phase downloads only files that actually exist remotely (from a batched directory scan) — the old per-file loop burned a 20 s timeout per missing file, an hour on a fresh camera.
  - The health probe authenticates; unauthenticated, it read the 401 page and rolled back healthy deploys.
  - Upload success is established by re-listing the tree and comparing sizes — curl with several URLs only reports the last transfer's status. Failed files are retried individually.
  - No more `SITE CHMOD` (answers 500 on this ftpd; exec bits come from the vfat mount options).
  - A final `RESULT: exit N (reason)` line survives pipelines that mask the exit code.

---

## [1.5.0] — 2026-08-11

Performance release, driven by on-device measurements (AK3918, 33 MB RAM, CPU at
74% baseline). Every number below was measured on hardware before and after.

### Performance
- **Shared fork-free service prober** (`scripts/health-probe.sh`) — health.cgi and the health-snapshot daemon probed ~20 services by exec'ing each controlscript (a shell spawn + 21 KB `common_functions.sh` source per service): ~10 s of CPU per sweep, paid every 30 s by the daemon — roughly a third of the CPU budget spent on monitoring alone. The prober replicates the pidfile checks with ash builtins (`read` + `kill -0`, zero forks: 12 probes in 0.16 s) and still execs the controlscript for deep or composite services (rtsp-h26x RTSP DESCRIBE/GOP, onvif, motion-detection, motion-snapshot, auto-night-detection — 2.6 s). Sweep: ~10 s → ~2.8 s. Unknown services fall back to the slow-but-correct exec path.
- **lighttpd keep-alive raised to 45 s idle / 500 requests** (`lighttpd*.conf.dist` + live conf). The dashboard polls every 20 s but lighttpd's default idle is 5 s, so **every poll paid a full RSA handshake** — measured 0.2 s unloaded to 4.8 s under load, against 0.3–1.0 s for the same request on a reused connection. An idle connection costs a few KB of RAM; the handshake costs CPU. Note `install_config` never re-seeds an existing conf, so the live `/mnt/config/lighttpd.conf` was patched directly as well.
- **`state.cgi` `load_conf_file` no longer forks per config key** — the `$(printf | tr -cd)` key sanitizer ran once per line of every conf file loaded; replaced by a pure-shell `case` guard that outright rejects malformed keys (also stricter for the `eval` it protects).

### Fixed
- **health-snapshot daemon rewrote invalid JSON every 30 s** — it carried the same one-space meminfo bug fixed in health.cgi in 1.4.0, and since the daemon owns the cache, the 1.4.0 fix only held until the next refresh. Both paths now agree.
- **`tr` audit outside the CGI layer** (same missing-binary failure mode as 1.4.0):
  - `common_functions.sh` now carries the `tr()` → `busybox tr` shim, covering `autorun.sh` (boot-time CSRF token generation silently produced "", masked by func.cgi's lazy regen) and `mqtt-bridge.sh` (HA discovery node_id, and inbound command normalization — subscribe works even though publish is broken, so commands from HA hit these paths).
  - `update-check.sh` — version comparison fed empty strings to the badge logic; rewritten in awk.
  - `motion-event.sh` — event-log sanitizer emitted empty descriptions; rewritten in awk.

---

## [1.4.0] — 2026-08-11

Minor rather than patch: the theme toggle goes from inert to functional, which is
a visible behaviour change. Everything else here is a fix for a defect that made
a shipped 1.3.0 feature unusable on real hardware.

### Changed
- **Theme switching now actually works, and the dark palette matches the wizard.** `index.html` had a working toggle writing `data-theme` to `<html>` and persisting it, but `ui-modern.css` keyed its dark rules off `@media (prefers-color-scheme: dark)` and contained zero `[data-theme]` selectors — so pressing the toggle only swapped the icon. The three media blocks are now `:root[data-theme="dark"]` rules (56 selectors), the theme is resolved in JS (stored choice, else OS preference) and stamped in `<head>` before any stylesheet so no light frame paints, and the dark palette was remapped from its blue tones to the wizard's violet/indigo: background `#0d0f1a`, surfaces `#131624`, text `#e2e8f0`, accent `#6d58f5`. Only `index.html` needed the change — the other five HTML files are fragments injected into it and inherit the attribute.
  - `--ui-muted` is `#8a93a6` rather than the wizard's `#6b7280`: the wizard uses it for short card descriptions, but the dashboard uses it for table headers and dense rows, where `#6b7280` on `#0d0f1a` sits at the edge of the 4.5:1 contrast floor.

### Fixed
- **`action.cgi` `wifi_get_ssid` returned an empty SSID.** It read `/mnt/config/wpa_supplicant.conf`, a path that need not exist — this camera carries no `wpa_supplicant.conf` at all, the credentials live in flash. It now queries the interface first (`wpa_cli -i wlan0 status`, then `iwconfig wlan0`), falling back to the config files. Only the `ssid=` line is taken: `wpa_cli status` also prints `passphrase=` in the clear.
- **`action.cgi` `wifi_set_config` wrote to a file nothing reads.** It wrote `/mnt/config/wpa_supplicant.conf` and then called `wpa_cli reconfigure`, but `autorun.sh` starts `wpa_supplicant -c /mnt/wpa_supplicant.conf` — so the reconnect re-read the old file and the new credentials were used neither immediately nor at the next boot. Both commands now share a `WIFI_CONFIG_PATH` constant pinned to `autorun.sh`'s path.
- **`wizard.cgi` — the first-boot wizard could never complete on real hardware.** `get_field()` split the POST body with `tr '&' '\n'`, but `tr(1)` does not exist on the camera: busybox carries the applet without shipping a symlink for it, and `/mnt/bin` is not on the CGI `PATH` (`/sbin:/usr/sbin:/bin:/usr/bin`). Every field parsed as empty, so the handler always returned `{"ok":false,"error":"missing_params"}` and the UI showed only a bare "Réessayer" button. Splitting is now done with awk's record separator (`RS="&"`).
- **`wizard.cgi` — MQTT field sanitizers replaced.** The four `tr -cd` filters added in 1.3.0 were dead for the same reason; they now use `awk gsub()` with the equivalent negated character classes.

- **`func.cgi` — the dashboard was read-only: every mutating request returned 403.** `csrf_guard()` filtered both the stored token and the `X-CSRF-Token` header through `tr -cd` (lines 302, 322). Both sides collapsed to an empty string, the stored token was regenerated on each call, and the comparison could never match; `state.cgi` handed the browser an empty `csrf_token` for the same reason. Rather than patch each call site, a `tr()` shell function now routes to `busybox tr` when no `tr` binary is on `PATH`. It is defined at the top of `func.cgi`, which all 19 CGIs source, so every `tr` call in the CGI layer is repaired at once — including the WiFi SSID/PSK filters in `action.cgi` (lines 3176–3177), which silently blanked both fields.
- **`health.cgi` — emitted invalid JSON.** `/proc/meminfo` pads its values with several spaces, but line 62 stripped only one (`${_mv# }`), so `${_mv%% *}` yielded an empty string and the output contained `"mem_total_kb":,`. Values are now taken by word-splitting, which is padding-agnostic. Note `mem_avail_kb` legitimately reports `0`: this kernel's `/proc/meminfo` has no `MemAvailable` line.

### Known issues — verified on hardware, not yet fixed

- **`mqtt-bridge.sh` — no message is ever published.** `mqtt_publish_raw()` publishes with `curl --upload-file`, but curl 8.1.2 on this device sends `CONNECT` followed by `SUBSCRIBE`, never `PUBLISH` — confirmed against an instrumented broker, with both a stdin pipe and a real file, with and without credentials. The bridge's `rc=28` timeouts are this, not a broker or credential problem. Fixing it means replacing the publish mechanism, not tuning the config.
- `conf-import.cgi` and `configeditor.cgi` also call `tr`; they source `func.cgi` so the shim covers them, but their code paths have not been exercised on hardware.

### Tooling notes
- `tools/deploy-full.sh` — three defects hit during a live deploy: it overwrites binaries without stopping the daemons using them (`ETXTBSY`, which killed lighttpd mid-deploy), its `health.cgi` probe sends no credentials so it always reads the 401 body as a failure, and piping the script into `tail` masks its exit code. A caller that checks `$?` on the pipeline sees `0` for a failed deploy.
- Camera-side backups pulled by that script (`backup-<ip>-<timestamp>/`) are now git-ignored.

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
