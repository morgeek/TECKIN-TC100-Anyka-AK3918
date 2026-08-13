# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.6.2] — 2026-08-11

Closes the last MQTT gap: Home Assistant can now **control** the camera, not just
watch it. Everything below is verified on both live cameras.

### Added
- **Forged SUBSCRIBE — inbound HA → camera commands work.** `subscribe_once_command()`
  now builds the MQTT 3.1.1 CONNECT + SUBSCRIBE frames in shell, pipes them to
  `nc`, and decodes the reply stream (read as decimal bytes via `od -An -tu1`,
  since busybox awk has no `strtonum()`). Verified end-to-end: publishing
  `{"cmd":"front_led","value":"on"}` yields
  `{"command":"front_led","status":"applied","ok":1,"source":"mqtt"}` on
  `<root>/command/result`, on both cameras independently.
  - Beyond the feature, this **frees CPU**: the old curl path failed on every
    attempt (`rc=28`), leaving a hung 10 s process every ~32 s, forever.
  - The curl implementation is kept as `subscribe_once_command_curl()` and stays
    reachable via `MQTT_FORGE_SUBSCRIBE=0` — disabled, not deleted.

### Fixed
- **Cameras listened on a shared command topic (regression from 1.6.1).** 1.6.1
  derived `MQTT_CLIENT_ID` and `MQTT_TOPIC_ROOT` from the hostname, but
  `MQTT_TOPIC_COMMAND` is written out explicitly in `mqtt.conf`, so it stayed at
  `teckin/tc100/command`: each camera published under its own root while every
  camera listened on the *same* topic — the exact collision 1.6.1 set out to fix.
  The command topic is now re-derived alongside the root whenever it still matches
  a shipped default; a genuinely custom topic is preserved.
- **`is_truthy` was out of scope in `mqtt-bridge.sh`.** The bridge's helper is
  `is_truthy_local`; `is_truthy` only exists in `autorun.sh`. Calling it failed
  silently and always took the fallback branch — the same "call something that
  isn't there, fail quietly" pattern as the `tr` family of bugs.

### Changed
- **HA "Live" camera entity is off by default** (`MQTT_HA_CAMERA_ENTITY_ENABLE=0`).
  Its discovery config points at `snapshot/last_path`, which carries a filesystem
  *path*, while HA's MQTT camera platform expects the image *bytes* — the entity
  could never render. Publishing the JPEG over MQTT instead would cost tens of KB
  per snapshot on a 33 MB device, so the supported route stays RTSP/go2rtc. The
  entity is disabled, not removed: set the flag to `1` to publish it again.

### Notes
- Command delivery is polled in ~12 s windows, so a QoS 0 message published
  between windows is missed. Publish **retained** for guaranteed delivery, then
  clear the retained value so the command is not replayed on the next subscribe.

---

## [1.7.1] — 2026-08-13

### Fixed
- **Dashboard liveview and snapshots were blank on every camera.** `/bin/timeout` on this firmware is the pre-2014 busybox variant, which wants `timeout -t SECS CMD`. Given the modern `timeout SECS CMD` it tries to exec the *duration* as the command:

      timeout 5 /mnt/bin/getimage  ->  timeout: can't execute '5': No such file or directory

  Inside a redirect that failure is silent, so `currentpic.cgi` returned HTTP 200 with `Content-Type: image/jpeg` and **zero bytes** — the browser simply showed nothing. `getimage` itself was fine all along (57 KB JPEG when run directly).

  A `timeout()` shim now routes to `busybox timeout` (whose applet accepts the modern form) from `func.cgi` and `common_functions.sh`, covering `action.cgi`, `state.cgi` and `clip_thumb.cgi`. `currentpic.cgi` is deliberately standalone — it sits on the liveview hot path and sources neither — so it carries its own copy. Verified on both cameras: a real 1280×720 JPEG is served again.

  Same shape as the `tr` class of bug, with a twist worth remembering: the binary **exists and is on `PATH`**, so a `command -v` check passes. Only its *behaviour* differs, which is why the shim probes with `timeout 1 true` instead.

### Notes
- The firmware version shown on the HA device page comes from the **retained** discovery config, which is only republished when the bridge starts. Deploying a new `VERSION` therefore does not update Home Assistant on its own — restart `mqtt-bridge` (or reboot) to refresh it. If HA still shows the old value afterwards, reload the MQTT integration; HA caches device metadata in its own registry.

---

## [1.7.0] — 2026-08-13

Validated on one camera (IPCAMERA1) before propagating; the second unit stays on
1.6.3 as a control until this is signed off.

### Added
- **Persistent MQTT listener — commands from Home Assistant are no longer lost.** The bridge used to subscribe in ~12 s windows, so a QoS 0 command published between windows was silently dropped and latency was 0–30 s (the README told users to publish *retained* and then clear the topic to work around it). One connection is now held open — CONNECT + SUBSCRIBE once, PINGREQ to keep it — and decoded frames are dispatched by the main loop. Verified on hardware with a **non-retained** command, the exact case that previously could not work: `{"cmd":"front_led","value":"on"}` was executed.

  Two device constraints shaped the design and are worth recording:
  - `od` **block-buffers its pipe output**, so the obvious `nc | od | awk` live pipeline delivers nothing until the connection closes (measured: 50 bytes sent, awk saw them only at stream end). `nc` therefore writes the raw stream to a file and the main loop decodes the increment — `od` flushes because it exits each pass.
  - The decoder resumes on an exact frame boundary and reports how many bytes it consumed, so a frame split across two passes is reassembled rather than lost. Covered by a split-frame test.

  The listener recycles its connection hourly (`MQTT_LISTENER_MAX_PINGS`) to bound the raw capture file. `MQTT_PERSISTENT_SUBSCRIBE=0` restores the previous windowed behaviour; nothing was deleted.

### Performance
- **`state.cgi` `json_escape` no longer forks for the common case.** It ran `printf | sed` — a fork+exec pair — for each of ~80 values per statusline poll, though hostnames, profile names and paths contain neither backslash nor quote. A pure-shell `case` guard now handles those; `sed` is spawned only when escaping is genuinely needed. Output verified byte-identical across backslash/quote/empty edge cases. Warm statusline: **~1.0 s → ~0.83 s**.
- **`health-probe.sh` gates the expensive deep probes behind a pidfile check.** `rtsp-h26x` and `onvif` both carry a pidfile *and* a costly probe (an RTSP DESCRIBE measured at ~1.2 s). A dead process is now reported `stopped` without paying for a network round-trip that could only confirm it. A live process still gets the full deep check, so a hung-but-running daemon is still detected.

### Notes
- The persistent listener trades roughly **1–1.5 MB of resident memory** (a held `nc` plus its shell) for the loss of the connect/teardown churn every ~13 s. On a 33 MB device that is a real trade, not a free win — set `MQTT_PERSISTENT_SUBSCRIBE=0` if memory matters more than command latency on a given unit.
- **Watchdog consolidation was evaluated and deliberately not done.** Measured cost of the current design: 504 KB per `service-watchdog.sh`, 1 008 KB for the two running instances, waking once per 60 s. Merging them into a single supervisor would mean moving per-service reboot-escalation state out into files (POSIX sh has no arrays) inside the one component that can reboot the device. ~500 KB does not justify that risk.

---

## [1.6.3] — 2026-08-11

### Fixed
- **The dashboard reported the front/red LED state from configuration, not from the hardware.** `state.cgi` read `get_cfg FRONT_LED 0` / `RED_LED`, but those keys were **absent from `boot.conf.dist`** — and therefore from every camera's live `boot.conf` — so the lookup always fell through to the default `0`. The UI showed "off" permanently while the LED was physically lit, on every camera. Verified on both units: `blue_led/brightness=1` and `controlscripts/front-led status` → `ON`, while the dashboard insisted it was off.

  Both LEDs are now read from `/sys/class/leds/*/brightness`, matching what `mqtt-bridge.sh` already did and what `controlscripts/front-led status` reports — one source of truth, so the whole class of drift becomes impossible. Confirmed on hardware: lighting the LED now flips the reported value to `1`, which the old code could never do.

  This mattered because the LED can be changed without the config ever being rewritten — by the motion blink, an MQTT command, or a controlscript — so configuration records *intent*, never *reality*.

### Changed
- **`initialize_gpio()` applies the configured LED intent at boot** instead of unconditionally forcing both LEDs off. `FRONT_LED` / `RED_LED` are now declared in `boot.conf.dist` (both `0`), so out-of-the-box behaviour is unchanged — but a camera deliberately left with its LED lit now survives a reboot, and what boot applies agrees with what `state.cgi` reports.

---

## [1.6.1] — 2026-08-11

Multi-camera follow-up to 1.6.0's MQTT publishing: two cameras seeded from the
same image no longer collide as one device in Home Assistant.

### Added
- **MQTT identity derives from the hostname.** `mqtt-bridge.sh` now sets
  `MQTT_CLIENT_ID` and `MQTT_TOPIC_ROOT` from a slug of the device hostname when
  they are still at a shipped default (empty / `tc100-camera` / `teckin-tc100`).
  Naming a camera `IPCAMERA1` vs `IPCAMERA2` is then the single action that gives
  each its own topic root, `uniq_id` prefix and HA device — no more two
  publishers fighting over `teckin/tc100`. Verified on both cameras: roots
  `ipcamera1` / `ipcamera2`, distinct HA devices.
- **Firmware version on the HA device page.** The discovery device dict now
  carries `"sw"` read from `/mnt/VERSION` (HA merges device info across a
  device's entities, so it's set on the CPU sensor). Verified: `"sw":"v1.6.1"`.

### Changed
- **`config/hostname.conf.dist` no longer ships a specific device name.** It held
  the literal `Anyka`; replaced with a neutral `TC100-CAMERA` default plus a note
  that each camera needs a unique hostname (which now also drives MQTT identity).
- **`tools/deploy-full.sh`** usage example uses `<camera-ip>` instead of a real
  LAN address.

### Notes
- The inbound command path (HA → camera) still uses `curl` for SUBSCRIBE and
  times out (`rc=28`); only the publish path was reforged. Camera → HA discovery,
  telemetry and availability all work.
- Upgrading from a pre-1.6.1 topic root leaves the old retained discovery under
  `homeassistant/.../teckin-tc100` as a ghost device in HA. Clear it by
  publishing empty retained payloads to those `.../config` topics (done for the
  two live cameras this release), or delete the stale device in HA.

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
