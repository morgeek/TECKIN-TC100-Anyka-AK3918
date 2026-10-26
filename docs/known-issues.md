# Known issues and platform notes

Moved out of the README in 2.0.0. History of every fix: [CHANGELOG.md](../CHANGELOG.md).

## 3.0 (Linux 6.6)

The 3.0 flash build has known gaps, listed feature by feature in
[linux-port/feature-audit-2026-10-26.md](linux-port/feature-audit-2026-10-26.md). The ones that matter most: the web
interface has no login on 6.6 (keep the camera on a trusted network), a Wi-Fi change made from the web page or the
wizard is not kept after a restart (edit `/mnt/config/wpa_supplicant.conf` from a shell instead: `cfg-persist`
saves it to flash, and it takes priority over a copy on the card), the IR-cut filter
may not move, and there is no RTSP sub-stream.

## Lite RTSP server (2.1.9)

- **TCP only.** RTP goes over the RTSP connection; a client asking for UDP gets 461 and retries over TCP (go2rtc, ffmpeg, Frigate, VLC do).
- **The vendor server still runs**, on `RTSP_VENDOR_PORT` (8555), because it drives the encoders, the day/night switch, the OSD and the motion detection. Nothing should connect to it.
- **Fallback.** If the lite server has not opened the RTSP port within 30 s of a start, `rtsp-h26x` gives the port back to the vendor server until the next reboot (`/tmp/rtsp-lite-fallback`; saving the RTSP server card clears it).
- **Two-way audio** plays only G.711 8 kHz (what go2rtc sends). The push-to-talk of the web page still pauses the stream while it plays.
- **Status:** `/var/run/tc100rtsp` (every 10 s): clients, skipped frames per client, sound, talk.

## Remote syslog (2.1.5)

BusyBox `syslogd -R` forwards every message it receives *before* applying its
own `-l` level and `-f` rules, which only filter the local file
(sysklogd/syslogd.c). With remote syslog on, a NAS therefore received the
kernel and daemon info/debug lines as well, and each burst line by line. From
2.1.5 syslogd only writes the local log (`/var/log/messages`, notice and above
plus logins) and `tc100-logfwd` forwards that file: one copy of a repeated
message per minute (numbers ignored, so `sjf:4619178` and `sjf:4619188` are one
message) followed by "last message repeated N times", and 60 lines a minute at
most.

A NAS rule that sends an e-mail for each received error doubles every camera
error with its own "Failed to send email" entry when its mail settings are
wrong (Synology Log Center: check the notification rule and the SMTP account).

## Reading the camera logs (2.1.2)

Logs of two cameras over a day (2026-10-16) showed that almost every line marked
"error" or "critical" was not a fault:

| What you see | What it is |
|---|---|
| `kern.err kernel: reg0x40, read:0x89`, `f22_set_power_on`, `akisp_init`, `2lane thssettle` | the sensor driver dumping its registers each time the video starts, at error priority |
| `user.emerg … encode frame type=1`, `group_type=1, index=…`, `sensor fps switch 25 to 10` | the vendor encoder library at emergency priority, at stream start and whenever a frame takes more than ~100 ms to encode. Silenced from 2.1.3 (vendor print level 1, errors only); it was flooding a remote syslog server and its email alerts |
| `user.err … ak_cmd_register_module … no server was register` | the vendor library looking for the cloud command server, which is not run |
| `user.emerg … [wait_move_stable:193] not stable` | vendor image library message every ~15 min, no effect seen |
| `RTW: …` (≈130 lines at boot) | Wi-Fi driver banner |
| `rfkill: Cannot get wiphy`, `ioctl[SIOCSIWENCODEEXT]: Invalid argument` | wpa_supplicant with the vendor driver's old interface; the camera connects anyway |
| `MTLS … fatal alert message was received from our peer` | a browser refusing the self-signed certificate until it is accepted |

The Logs page now reads the priority that syslog lines carry instead of guessing
from words, and shows these as "Vendor" instead of errors. Real faults stay
errors: SD card timeouts (`mmcblk0: timed out…`, `get_card_status wait too long`),
out of memory, kernel oops.

Found at the same time and fixed in 2.1.2:

- **Clock**: only the RTSP server had a time zone (and on a camera left on the
  template, the whole commented file as its `TZ`), so kernel and vendor lines
  in the same log were two hours apart and cron ran on UTC. `TZ` is now read
  properly and exported for every program from the start. The template's
  example was also wrong: in POSIX, Paris is `CET-1CEST,M3.5.0,M10.5.0/3`,
  not `UTC+1`.
- **False boot warnings** from flash: "/mnt has less than 4 MB free" (a RAM
  disk by design), "Self-heal skipped: missing libcurl" (not shipped) and
  "lighttpd.conf rejected" (the SD-card web config, not used from flash).
- **Sudden restarts**: on a camera with a failing SD card, the kernel's card
  driver busy-waits (`get_card_status wait too long`) until the hardware
  watchdog resets the camera — about every 1–4 hours that day. The reboot
  history now records the card state with each heartbeat (every 5 minutes from
  flash) and names it as the likely cause; web updates are recorded as
  requested restarts instead of "UNEXPECTED".

## Fixed issues (2026 bring-up)

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

