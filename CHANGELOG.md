# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

## [3.0.1-rc33] - 2026-11-07

Major milestone release towards a 100% free firmware:
- **Free hardware video encoder (`src/h265enc/freeenc.h`, `RTSP_FREE_ENC=1`)**: live IDR + P stream encoding in H.265 (1080p)
  and H.264 (360p sub-stream) directly driving the ASIC core without loading vendor libraries (`libakv_encode`,
  `libmpi_venc_ex`, `libplat_*`). Decompiled command lists (`listgen.h`), computed work table (`worktab.h`), and built-in
  rate control. Validated on camera (43,000+ pictures without a single failure).
- **Daemon migration to system `musl` libc**: `tc100-logfwd`, `rwconf`, and `libnetacl-musl.so` run directly on the
  native musl C library.
- **MicroSD wear reduction & performance**: MP4 recording pre-allocation (`rec.c`, item 60.2) via `fallocate` /
  `posix_fadvise` preventing FAT fragmentation and I/O stalls.
- **Flash SPI savings**: `fr.js.gz` excluded from flash image (`v3/build-stack.sh`, item 60.1), saving ~40 KB of flash space
  as SquashFS XZ compresses the plain dictionary efficiently.
- **Web UI & Diagnostics**: cold Services scan acceleration via awk (`fd1ae6a`, R17), robust `wifi-diag` stall measurement
  (R27), safe refused boot card ejection (`dc6966c`, `d2ee15f`), and live FPS counter.


The rc31 (on both cameras since 2026-11-06 afternoon, md5 `5d9e83af`) plus, in one release asked by the owner
("corriger les problèmes rencontrés pour avoir une rc32 exploitable"):
- **Fixes found on the cameras by the tester**: `tc100-logfwd` no longer dies at its first line (no `sscanf` /
  `isdigit` through the glibc headers: the remote syslog never worked with the CI build, rc28-rc31), `libnetacl.so`
  without `__isoc23_strtol`, the CI refuses such names (`e5a1c05`, R23); browsers revalidate the pages after an update
  (R22); a refused boot card is never left mounted read-write, an older package is not offered as "staged" (R25, R26);
  no MP4 fallback request once WebRTC plays (R24).
- **One look and one ONVIF daemon**: Pico only (Classic removed), `tc100-onvifd` only (`[rc32-remove]`).
- **Web UI audit, the rest of R20** (D1-D6, U2, U4-U9) (`[ui-r20]`).
- **Time zone** step in the setup wizard and a zone list in Settings; **low-light frame rate** 10 / 15 / 20
  (`[tz-lowlight]`).
- **Faster pages and import**: short RAM caches for `state.cgi` (`fullconfig`, `daynight`, `isp_tune`) and the motion
  zones, emptied by every write; Services answers from a recent snapshot while it refreshes; no global `sync` nor
  rollback copy for unchanged files in a flash-mode import (R17, R7); RTSP expiry of idle clients logged (R10).
- **Optional, off by default**: a sender thread in `tc100_rtsp` (`RTSP_SENDER_THREAD=1`, R16); a manual test kernel
  with high-resolution timers (`[hrt-test]`, separate `-testkernel` package, not in this update).
- CI green again (`b82391c`). No default changed for an installed camera except the look (Pico was already the default).

## [3.0.1-rc31] - 2026-11-06

The rc30 (`9192813`, md5 `65e1cd70`, reviewed and archive-checked by the tester) plus the user-experience step and the
flash savings asked by the owner on 2026-11-06, each reviewed by the tester (test-queue 12:35 and 13:25):
- **Pico CSS look by default** (`[ux-pico]`): Pico 2.0.6 + a shim that draws the pages' Bulma classes; measured lighter
  and faster; the Classic look (Bulma) stays selectable in Settings -> System -> Appearance until the rc32 removes it.
- **Speaker sounds without an SD card** (`[ux-sounds]`): "Play now without saving"; the card is detected correctly.
- **Smaller flash image** (audit 2026-11-06, owner's choices): no jq (`[flash-nojq]`), no monvifd in the flash
  (`[flash-nomonvifd]`, `tc100-onvifd` runs for every config), `.gz` only for the five big web files (`[flash-gz]`),
  built-in sounds in A-law (`[flash-alaw]`), web JavaScript and inline scripts minified at build time
  (`[flash-minify]`; the shell stays readable).
- **Wi-Fi losses**: `scripts/wifi-diag.sh`, a read-only RAM logger that tells where the losses come from
  (`[wifi-diag]`).
- **Documentation**: user README and installation guide in English and French, Pico screenshots, the audit of
  2026-11-06 (`docs/linux-port/audit-2026-11-06.md`) and its corrections of stale docs.
Settings kept by the update (`/mnt/config`); no default changed except the look of the interface (Pico, per browser,
Classic still selectable). The web pages ship minified with esbuild 0.21.5 (build tool only; the Dependabot alert is
about esbuild's development server, which the project never runs).

## [3.0.1-rc30] - 2026-11-06

The rc29 (`769aa79`, on both cameras from the flash) plus the tester's fixes of the rc29 campaign and the implementer
items R19, R14, R18 and R20-U1/U3:
- `7e3b1c8` + `8845166`: the web update and the install halt `auto-night-detection`, `recording` and
  `motion-detection` instead of stopping them; the rc29 update had switched automatic day / night off on both cameras
  and local recording off on IPCAM1.
- `bf6d15c`: syslog works again with forwarding on (BusyBox of the base image built with `FEATURE_SYSLOGD_DUP` and
  `FEATURE_SYSLOGD_CFG`; `syslogd_start` falls back without `-D` / `-f`). The base image is rebuilt.
- R19: the memory guard halts these three services too (their `stop` writes a setting for good).
- R14: the SD auto-repair never checks nor writes a boot / install card, does not start `fsck.fat` without the memory it
  needs (the card is then used as it is and Settings -> Recording says it was not checked), lets the OOM killer take
  `fsck.fat` first, and mounts the card again after a failed check.
- R18: the reboot of a web update (and of an SD install, and of `update.cgi`) is recorded as intended in
  `reboot-history.log`.
- R20: no Shutdown entry in the menu any more (the camera stays off until unplugged); `LIGHTWEIGHT_MODE` is no longer
  written by Settings -> Performance and security.
No default changes: an update keeps `/mnt/config`.

## [3.0.1-rc29] - 2026-11-06

The rc28 (`8131144`, 7 h 43 on IPCAM2 without a restart, `dropped 0`, memory flat) plus the two WebRTC fixes found by
the tester with Chrome 157, which fell back to MP4 at once:
- `1749475`: a browser SDP offer is accepted up to 12000 bytes (`whep.cgi` and `tc100-whep`, was 6000; Chrome's is
  7607 bytes and got 413).
- `cfed960`: a DTLS ClientHello in several fragments (Chrome's DTLS 1.3 with an ML-KEM key share) is rebuilt by
  `tc100-whep` before mbedTLS 2.28, which failed with -0x7900; the handshake goes on in DTLS 1.2. New test
  `tests/whep_chrome_interop.py` (Playwright's Chromium, DTLS 1.2 and DTLS 1.3 + ML-KEM).
No setting changes: every default of the rc28 stays; an update keeps `/mnt/config` (ONVIF stays off until switched on
in Services).

## [3.0.1-rc28] - 2026-11-05

After the rc27 package (`8c2eaba`): the tester's rc27 fixes (`0bc967c` no libc variable in onvifd/supervisord,
`7618d73` WebRTC forwards full 1412-byte RTP packets), `[rc28-fixes]` R2-R7 (no RTSP pacing by default, `restart` in
every service script, WebRTC falls back to MP4 without a picture, ONVIF real frame rate, faster JSON import, libc import
check in CI), `[rc28-defaults]` (every coded feature on by default for a new install: C supervisor with sound
detection, C MQTT discovery, direct microphone, free ONVIF, WebRTC, AAC audio in SD recordings), free `rwconf`,
`tc100-logfwd` and `libnetacl.so` built in CI, `getflag`/`getimage` removed, native `dash.cgi`/`statusline` in
`httpfront`, front/back wiring test.

## [3.0.1-rc27] - 2026-11-05

Everything below, from the [Unreleased] entries of 2026-11-05 (56 commits after the rc26 package `e0020a5`): free ONVIF
daemon, WebRTC live view, C supervisor and C discovery (all off by default), audit fixes (LAN-only web and RTSP,
bounded httpfront, idle RTSP clients, web update retries without reboot, wizard CSRF), clean SD card at every restart,
`RTSP_PACING_US=100` by default, serial console off after 5 min, and the items 26-56 of the implementer list.

### Added
- **AAC sound in the SD recordings** (item 11, on by default for the rc28, `RTSP_REC_AAC=0` keeps A-law): a fixed-point
  AAC-LC encoder written for the project, so browsers play the recordings with sound; the RTSP stream stays G.711.
- **`tc100-logfwd` and `libnetacl.so` built by the CI** from their source (item 51), without the Anyka toolchain.
- **Status line answered by httpfront itself** (item 55, `HTTPFRONT_NATIVE=1`, off by default): the JSON every page
  polls, without starting httpd and a shell (7 ms instead of 93 ms under qemu); anything it cannot answer exactly
  goes to the CGI as before.
- **WebRTC live view** (item 35, `WHEP=1`, off by default): `tc100-whep` (WHEP, ICE-lite, DTLS-SRTP with the system
  mbedTLS, SRTP in plain C) relays the camera's RTP to the browser with about 150 ms of delay; the page tries it first
  and falls back to the MP4 live view on any failure. The base image now builds mbedTLS with DTLS-SRTP.
- **Home Assistant discovery in the C MQTT bridge** (item 55, `MQTT_DISCOVERY_IMPL=c`, off by default): the same
  topics and payloads byte for byte, without the ~120 subshells the script spends at each connection.
- **One C supervisor for day/night and the reset button** (items 52 / 55, `SUPERVISOR_IMPL=c`, off by default):
  `tc100-supervisord` (21 KB) replaces the two resident shell loops with the same decisions; the shell loops come back
  by themselves if it is missing, does not start or dies.
- **WebRTC, first step** (item 35): `src/whep/srtp.h`, the SRTP protection of WebRTC (AES-128-CM + HMAC-SHA1-80)
  without a library, checked with the published vectors, and `srtp-bench` in the CI test pack to measure its CPU
  cost on the camera before the gateway is built (`docs/linux-port/whep-design.md`).
- **Help tips in Settings** (item 44): a "?" next to 71 settings that had no explanation of their own; hovering shows
  what the setting does and its effect, a click or a tap shows it under the field. French with the rest of the page.
- **Memory forecast** (Settings → System → Memory, item 45): the free memory measured now, the largest programs
  (PSS from `smaps_rollup`, `action.cgi?cmd=mem_budget`, one `ps` and one `awk`), and a forecast as options are
  ticked: a running service gives back what it uses now, a stopped one costs an estimate measured on the TC100
  (MQTT bridge, ONVIF, mDNS, SSH, `arecord`, the recording pre-roll `REC_RING_KB`, 1080p against 720p). The gauge
  turns orange below 10 MB free and red below 6 MB. It changes nothing by itself.
- **Your own sounds** (Settings → Streams & audio → Sounds, item 48): play, add or delete the speaker's sounds and
  choose the startup sound (or silent). Any audio file the browser decodes (WAV, MP3, OGG...) is converted in the
  browser to the speaker's format (8 kHz mono 16-bit, 30 s at most) and stored on the SD card
  (`tc100-3/sounds/NAME.pcm`, `cgi-bin/sounds.cgi`); a sound named `chime`, `alert`, `siren` or `startup_complete`
  replaces the built-in one for the dashboard buttons, MQTT / Home Assistant and the startup (`BOOT_SOUND_NAME`).
- **Recordings timeline** (Recordings page, item 36): the day drawn in the browser from one small index
  (`viewrecords.cgi?cmd=day_index`: start, length and event spans of each file), each file at its real length, the
  motion and sound event spans in red, the playhead, zoom (24 h to 5 min, double-click); a click or a drag plays from
  that second (the same file is sought without reloading), the arrow keys step 10 s (Shift: 1 min). The recorder now
  writes the event times into the `.evt` marker (`on S` / `off S`); markers of older versions show the whole file in
  amber. A click on a motion event in the list now opens its day (the date format did not match) at its time.
- **Hardware test page** (Tools → Hardware test, `www/hardware.html`): the camera drawn from the front and the back;
  a click on a part tests it with the existing commands: picture and image processor values (lens), blue and red LEDs
  (on, off, blink), IR LEDs and IR-cut filter, microphone level meter, speaker chime, microSD card details, reset
  button shown pressed while it is down. One read-only state command, `action.cgi?cmd=hw_state`, read every 2 s while
  the page is open and visible.
- **Chime, alert and siren buttons** on the dashboard (next to Listen / Talk), at the speaker volume; the siren asks first.
- **Full backup of this camera** (Backup page): every setting changed from the shipped defaults, secrets, ssh keys,
  presets and zones included, in one `.tar.gz` (the same files the flash slots keep, `cfg-persist archive`), and its
  restore: only plain files under `config/`, each validated as for a JSON import, all written as one transaction.
- **Picture on events over MQTT** (`mqtt.conf` `MQTT_SNAPSHOT_ON_EVENT=1`, off by default): on motion, sound or tamper a
  fresh JPEG goes to `<topic root>/snapshot/image` (the Home Assistant camera entity, registered then) and a line to
  `<topic root>/snapshot/event`, at most one every `MQTT_SNAPSHOT_COOLDOWN_SECONDS` (10).
- **Metrics**: `http://<camera>/metrics` (redirect to `/cgi-bin/metrics.cgi`, the usual Prometheus path), plus the video
  server's capture rate, bit rates, playing clients and skipped frames (`/var/run/tc100_rtsp.stat`, every 5 s), the
  microSD card's presence, size and free space, and `tc100_info{version=...}`. No chip temperature: the kernel has no
  sensor driver for it.

- **720p main stream** (Settings → Main stream → Resolution, 1920x1080 or 1280x720): the whole picture scaled down by
  the image processor, not a corner of it (kernel patch 0016: the ISP crops the whole 1080p window and scales the main
  channel, as it does for the 640x360 sub-stream). Less than half the pixels: lower bit rate for the same quality,
  less encoder and network load, about 1.7 MB less per captured frame. Stored as `[0] mainres` of `rtspserver.conf`,
  1080 by default; the choice is greyed out on an older kernel, and `tc100_rtsp` keeps 1080p there (the read-only
  parameter `ak39_vi.main_scale` says the kernel scales).

- **Microphone without arecord, and sound processing** (`config/rtsp.env` switches, all off until checked on the
  camera): `RTSP_ALSA_DIRECT=1` reads the microphone with the kernel's ALSA ioctls inside `tc100_rtsp` (no `arecord`
  process, ~660 KB PSS, no pipe; back to `arecord` when the device does not open). `RTSP_AUDIO_HPF=1`: high-pass at
  150 Hz (mains hum -19 dB at 50 Hz, voice untouched). `RTSP_AUDIO_AGC=1`: room hiss lowered, a far voice raised up
  to +18 dB, loud sounds compressed instead of clipping. `RTSP_AUDIO_DUCK=1`: the microphone is muted while the
  speaker plays (no echo during two-way audio or push-to-talk). Fixed point, well under 1 % of the CPU; the sound
  detection still measures the unprocessed sound.
- **Test kernel with a bigger encoder pool on demand**: a manual run of the kernel workflow with `venc_pool=12M`
  (for the encoder's smart mode); pushes build the normal kernel.

- **Event clips kept first on a full card** (`boot.conf` `REC_KEEP_EVENTS=1`, off by default): a recording during
  which motion or a sound event was detected gets an empty `.evt` marker next to it; when space is needed the oldest
  recording without an event goes first, the event clips only when nothing else is left.

- **Anti-flicker from the Wi-Fi country** (Settings → Picture → Anti-flicker → Automatic, `POWER_HZ=auto`): 60 Hz for
  the countries on 60 Hz mains (most of the Americas, South Korea, Taiwan, the Philippines, Saudi Arabia), 50 Hz
  elsewhere; Japan (both) and an unset country keep the camera default. Applied without a restart, as 50 / 60.

- **Soft Wi-Fi repairs before the network reboot** (`boot.conf` `NET_GUARD_SOFT=1`, off by default): when the
  gateway stops answering while `wlan0` exists, the net guard tries a Wi-Fi reassociation after 2 min, applies the
  Wi-Fi settings again after 5 min and probes the USB Wi-Fi chip again after 8 min, each once per outage, before its
  reboot (`NET_GUARD_MIN`, 15 min).

- **Automatic bit rate** (`config/rtsp.env` `RTSP_ABR=1`, off until checked on the camera): when TCP clients have to
  skip frames (the Wi-Fi cannot carry the bit rate), the main stream's bit rate goes down 30 % (not below
  `RTSP_ABR_MIN`, a quarter of the setting by default), and back up by a tenth of the setting after 30 s without a
  skipped frame. Through the encoder library's `ak_venc_set_br`; its answers are logged, a refusal turns it off.

- **Motion from the encoder's frame sizes** (`config/rtsp.env` `RTSP_MD_ENC=1`, off until checked): a second
  detector next to the luma grid; in VBR, P frames several times bigger than their running mean (x2 to x6 with the
  sensitivity) three times in a row count as motion. No pixel read; the motion zones do not apply to it.

- **Day / night: at least 60 s between two switches** (`daynight.conf` `MIN_SWITCH`, 0 = no minimum): at dusk the
  IR LEDs light the scene and the picture-brightness source could switch back to day at once, the IR-cut clicking
  back and forth.

- **Clock from an HTTP Date header when NTP is blocked** (`scripts/time-fallback.sh`, `TIME_HTTP_FALLBACK=1`): while
  the clock is still in 1970 two minutes after boot, the `Date:` header of the router's own web page sets it (every
  5 min, 12 times at most). `TIME_HTTP_URLS` may add Internet addresses; by default nothing leaves the local network.
  ntpd keeps running and stays the reference.

- **Privacy mode** (Services page "Privacy Mode", MQTT / Home Assistant switch, `boot.conf` `PRIVACY_SCREEN`): black
  picture on every stream, snapshot and recording, silence instead of the microphone, no motion detection; kept over
  a restart.

- **`tc100-onvifd`** (`src/onvifd`): free ONVIF daemon to replace the closed `monvifd`. WS-Discovery (Probe,
  Resolve, Hello, Bye), Device, Media and Media2 services (profiles from `rtspserver.conf` and `boot.conf`, 1080p or
  720p, H.264 or H.265, optional sub-stream, stream and snapshot URIs, audio output and decoder configurations in the
  profile for two-way audio), Events service with PullPoint subscriptions (motion topics `VideoSource/MotionAlarm`
  and `RuleEngine/CellMotionDetector/Motion` from the motion state of `tc100_rtsp`, for the Home Assistant motion
  sensor), WS-Security login (digest or text) with the RTSP user and password, `TC100_NET_ALLOW` LAN filter, 46 KB.
  Off by default: `ONVIF_IMPL=c` in `onvif.conf` (monvifd stays the default until checked on the camera).

- **SD card clean after every restart** (item 41): at restart / power-off the init system calls `S39tc100 stop`
  before unmounting everything; it did nothing, so the recorder was still writing and the card stayed read-write:
  every boot found it "not properly unmounted". It now stops the recorder, syncs and remounts the card read-only
  (a card still busy is logged on itself, `tc100-3/shutdown.log`, with what held it). `fsck.fat` is in the user space
  now: the Repair button of the SD card page works, and `SD_AUTO_REPAIR=1` checks a card left dirty by a power cut
  a minute after boot. The `dosfsck -a` of `9623e94` (run at every remount, and never at boot) is removed.

- **Safety net for the logs in RAM** (`scripts/log-cap.sh`, housekeeper job every 10 min, `LOG_CAP_KB=64`): a log
  of `/tmp/log` or `/tmp/logs` that does not cap itself keeps its last 200 lines, rewritten in place so a program
  holding it open goes on writing into it.

- **Web login guessing limited** (`boot.conf` `WEB_LOCKOUT=1`, off until checked on the camera): 10 wrong logins
  from one address within 5 minutes close its web connections for 5 minutes (the camera itself never). `httpfront`
  checks the Basic login against `/etc/httpd.conf` itself (MD5 crypt, checked against glibc and OpenSSL), once per
  login; busybox httpd still answers every request. The kernel has no packet filter, so this replaces the iptables
  idea of the list.

- **Eco frame rate** (`boot.conf` `IDLE_WHEN`, item 31): the lower idle rate (`IDLE_FPS`) can now apply while nobody
  watches (`unwatched`: no RTSP client playing, no live view in a browser; the full rate as soon as one connects) or
  in night mode (`night`), not only while nothing moves (`still`, the default); a motion or sound event gives the full
  rate in every case.

- **Wi-Fi placement aid** (item 32): the dashboard shows the signal in colour (good from -60 dBm, fair down to -70,
  weak below); `WIFI_AIM=1` makes the blue front LED blink faster as the signal gets better for 5 minutes after boot,
  to aim the camera without a screen.

- **Pictures out of the camera on a serious alert** (`notify.conf`, item 34): a tamper alert now carries a fresh
  picture (it had none); `NOTIFY_BURST=N` sends N more pictures, one a second, for the events of `NOTIFY_BURST_EVENTS`
  (tamper by default) to Ntfy / Telegram; `NOTIFY_UPLOAD_URL` also PUTs every picture of the alert to a WebDAV folder
  or an upload address, so they survive a camera torn down or a card taken out. The Ntfy call no longer goes through
  `eval` (a message with a quote broke it).

- **mDNS services** (item 38, off by default): `MDNS_SERVICES=1` makes `tc100-mdnsd` answer the DNS-SD browse
  (`_http._tcp` port 80, `_rtsp._tcp` port 554 with `path=/video0_unicast`), so VLC, Home Assistant or a browser list
  the camera; `MDNS_INFO=1` adds the firmware version, the load and the Wi-Fi level to the TXT records. Question names
  with compression pointers are read now. Also fixed: the host name was read past its end when a query label was
  longer than it (found by AddressSanitizer in the host test).

- **Wi-Fi roaming between access points of one network** (`WIFI_ROAM=1`, off by default, item 40): below -75 dBm
  for 2 minutes the camera scans and roams (`wpa_cli roam`) to an access point of the same SSID at least 15 dB
  stronger, then waits 10 minutes before trying again.

- **Stealth boot** (`BOOT_STEALTH=1`, item 42): no startup chime, no LED aiming blinks, LEDs off while booting (from
  the start of the boot script; the kernel lights the blue LED for a few seconds before); the LED settings apply at
  the end of the boot. `BOOT_SOUND` is now in `boot.conf.dist` (it was read but undocumented).

- **Link test to the recorder** (Diagnostics → Link to the recorder, `action.cgi?cmd=nvr_latency`, item 43): ten
  pings to the Frigate address (else the recording client, else the router): loss, delay min / average / max and
  jitter, to tell a Wi-Fi or network problem from a camera one.

### Changed
- **Sound detection in the C supervisor** (third job of `tc100-supervisord`); the housekeeper and cfg-persist stay shell
  on purpose. **Free `rwconf`** built in CI (4.9 KB instead of the 31 KB 2.x binary); `getflag` and `getimage` (2.x shared
  memory, unused on 3.0) removed. **Dashboard poll answered by httpfront** (`dash.cgi`, same switch as the status line).
- **The new features are on by default** (owner, for the rc28): the C supervisor, the C MQTT discovery, the free ONVIF
  daemon, the WebRTC live view, the native status line, the microphone read by `tc100_rtsp` with its processing, the
  automatic bit rate, the motion from the encoder, soft Wi-Fi repairs, the web login lockout, mDNS services and
  information, event clips kept first, SD repair, Wi-Fi quality and roaming. Cameras already installed get them once
  through `scripts/migrate-rc28-defaults.sh` (a value chosen by someone stays); each keeps its own switch.
- **Serial console after 5 minutes** (item 56): the UART login prompt stops when nobody used it in the first 5 minutes
  (an open session is never cut); it stays on in safe mode or with `SERIAL_CONSOLE=on`. **VM tuning** for 64 MB
  (`VM_TUNE=1`: `vfs_cache_pressure` 150, dirty ratios 5 / 10). The encoder smart mode keys (`vbr`, `smart`) are now
  validated; the mode stays off until the item 9 kernel is tested.
- **Services page redesigned** (Tools → Services, item 46): three themed cards in a grid that uses the width of the
  screen (Core: video, web and system; Network and access; Integrations; then Other), one compact card per service
  with its CPU/RAM impact, state, Start/Stop, start at boot and source; one column on a phone. "Problems only" also
  hides a group left empty. The page's script URL is now stamped like the others (it kept a fixed `?v=`).
- **Texts brought up to date** (item 47): no lighttpd in the configuration editor, Device information shows the
  firmware version and where it runs (flash or SD card) instead of an always empty "vendor firmware" line, comments
  of the pages name the 3.0 programs; the memory forecast describes the memory guard as it works (off by default,
  6 MB and 3 MB stages).
- **Audit 2026-11-04, repository points** (item 51): `scripts/jsonflat.awk` gives the same output with busybox awk,
  mawk and gawk, and its test runs with each (D1); `SERVICE_TRIM` lives only in `service_trim.conf`, the dead
  `SD_AUTOMOUNT` and `SERVICE_TRIM_ALLOWLIST` and 16 keys of the vendor server in `rtspserver.conf.dist` are gone,
  `LOW_RAM_PROFILE` is documented (D5); the release build compiles `isp_flip` from its source, `CREDITS.md` names
  BusyBox (D3); a tag is published only when the CI of its commit passed (D4); `flash_budget.py` models the 3.0
  partitions of the device tree and a test keeps it, `STACK_MAX`, `KERNEL_MAX` and every `INITRD_SIZE` in step; a
  base image without `regulatory.db` stops the build (D6); the always-skipped 2.x recorder tests are removed (D7);
  the default-password check no longer reads the 2.x `lighttpd.user` (D9).
- **Smaller flash image** (item 54): `stack.sqfs` leaves out the 1 kHz test tones and the three style sheets
  `css/ui.bundle.min.css` is built from (and their `.gz`), about 65 KB; the setup wizard no longer loads Bulma (it
  only uses its own classes) and carries the few reset rules it relied on; xz uses the ARM branch filter
  (`-Xbcj arm`, `SQFS_BCJ=none` turns it off at build time).
- **Web pages load their scripts and styles as `?v=<md5>`** (`src/webui/stamp-assets.sh`, run by `build-index.sh`):
  a browser takes a new file at once after an update. The French dictionary and the main script were behind fixed
  version strings, so a browser could keep old copies for hours (busybox httpd sends ETag, Last-Modified and the
  `.gz` copies, but no Cache-Control).

### Security
- **Web update without automatic reboot after a failed write** (audit B1 + B3): up to 3 attempts per partition; after a
  final failure the camera stays up (web and ssh) with a message naming the partition, instead of rebooting into a
  possibly broken kernel or initramfs; `flashw -m` now checks the sum published in the package's `MD5SUMS`.
- **Setup wizard needs the CSRF token** (audit W4), and setting a password anywhere closes the first-install window.
- **MQTT bridge in C: no DNS lookup at every reconnection, long topics refused** (audit M1): a numeric broker address
  needs no lookup; a name is resolved once and again only after a failed connection (the lookup could freeze the
  loop for seconds); a topic over 65 535 bytes is refused instead of having its length truncated.
- **Secrets no longer in read-only answers** (audit W6): the rescue access point's password is sent only on request
  (Settings → Show, `wifi_rescue_info&reveal=1` with the page's CSRF token), and `state.cgi?cmd=fullconfig` no
  longer returns the Telegram token (`token_set` says one is saved; an empty field keeps it, `-` removes it).

### Fixed
- **From the rc27 test on a camera**: no RTSP pacing by default (it capped UDP clients and delayed the capture with
  the 100 Hz kernel); `restart` now works for the 15 service scripts that ignored it (a new Telegram token is taken at
  once, the service watchdog really restarts them); the WebRTC live view falls back to MP4 when sound arrives without
  a picture; ONVIF advertises the real frame rate (and 720p); the JSON import spends one subshell less per value; a
  build check refuses a libc variable in the programs linked to the stand-in libc (it crashed `tc100-onvifd`).
- **Front/back wiring** (item 57): the push-to-talk speaker test sent no CSRF token and was refused silently; the
  configuration export left out `WHEP_STREAM`, `SUPERVISOR_IMPL` and `SERIAL_CONSOLE`; a dead 2.x step was removed
  from the flash install card; `tests/test_wiring_e2e.py` now checks every page call against its CGI.
- The dashboard's Reboot showed "Command sent" and a red error while the camera restarted (a backspace byte in place
  of `\b` in the detection pattern).
- **Local network only applies again to the web page and RTSP** (`boot.conf` `NET_LAN_ONLY=1`, audit 2026-11-04 W2):
  since 3.0 the web server (`httpfront`, no C library) and `tc100_rtsp` did not use the 2.x filter library, so a port
  forwarded by the router by mistake reached the login. Both now close connections from outside the allowed networks
  themselves (same list: private networks, link-local, 100.64/10, `NET_ALLOW_EXTRA`; the camera itself always). ssh
  (dropbear) is still not filtered: the kernel has no packet filter.
- **Web server bounded** (audit R2): at most 16 connections at once and 8 from one address (then "503, retry in 2 s");
  a connection that sends nothing is closed after 2 s. It was never closed (the wait for the request line blocked), and
  each one kept a process.
- **RTSP slots cannot be held by idle connections** (audit R1): the 4 client slots stayed taken by TCP connections that
  sent nothing or only failed the password. Now: closed 30 s after connecting without an accepted request, 60 s idle
  without playing; when all 4 are taken, the one idle the longest that does not play makes room. A playing client is
  never closed this way. Also (R3): an empty URL in DESCRIBE, a session mixing TCP and UDP tracks (refused, 461), and
  OSD position values from `rtspserver.conf` are bounded.
- **MQTT bridge: no shell left as the daemon's parent** (`controlscripts/mqtt-bridge start`, ~200 KB PSS): the
  background subshell execs `nohup`, so the pid file holds the daemon from the start.
- **Web update** (`update66.sh`, audit B4, B6): it also stops the housekeeper (it restarted `tc100_rtsp` from the
  partition being erased, seen 2026-10-29) and the video service, saves the settings of the last 30 s and clears the
  boot counter before writing, and keeps the backups of the last two updates on the card (about 7 MB each, they
  were never removed). Without a card it says that nothing is saved.
- **Settings saved one at a time** (`cfg-persist save`, audit B5): two saves together could write the same flash slot
  and lose the newest settings or the boot counter.

## [3.0.1-rc26] - 2026-11-04

### Changed
- **`tc100-mqttd` supervision and PID tracking**: `controlscripts/mqtt-bridge` properly waits for and tracks the daemon's own PID file on start, and cleans up any duplicate instances on stop/restart, preventing client ID flapping on the broker.
- **Boot script**: `v3/S39tc100-linux66` starts `autorun-linux66.sh` with its input and output detached from the
  console. (Correction 2026-11-04, verification: this does not remove the shells that stay in memory; the
  `/etc/init.d/S39tc100 start` process that stays is the loop that restarts `getty` on the serial console, which is
  needed, and `controlscripts/mqtt-bridge start` still keeps a `sh` parent of the daemon. No memory was saved.)
- **Documentation refresh**: comprehensive updates across `docs/api.md`, `README.md`, `v3/install/RELEASE-NOTES.md` and `AGENTS.md` (mDNS, Wi-Fi country code, PTT ALSA player, and current kernel patch series status).
- **Owner validated**: native mDNS discovery (`<hostname>.local`) verified and confirmed functional from LAN.

## [3.0.1-rc25] - 2026-11-04

rc24 plus: the Wi-Fi country rules and an earlier Wi-Fi at boot, the MQTT bridge in C (off by default), the fixes of
the evening audit (RTSP buffer, script injection in web error pages, password in safe mode), the GPL-2.0 licence.
Kernel unchanged from rc23; the initramfs changes (regulatory database, boot script).

### Added
- **`tc100-mqttd`** (`src/mqttd`): the MQTT bridge as one small C process instead of four shell processes (about 5.7 MB
  together, the second-largest memory user after the video server). MQTT 3.1.1, one persistent connection with the
  retained Will, `online`/`offline` availability, keepalive, backoff and circuit breaker of `mqtt.conf`. The discovery
  payloads, health JSON, manifest and command results are still produced by `scripts/mqtt-bridge.sh` (same topics,
  byte for byte the same payloads, which the host tests compare); the daemon publishes them and runs the commands
  through that script as one argument, with a time limit. Off by default: set `MQTT_BRIDGE_IMPL=c` in
  `config/mqtt.conf` and restart the MQTT bridge service (`shell` is the default until the cameras pass the test; no
  binary installed means the shell bridge). The web UI status (`/tmp/mqtt_last_pub.status`, CONNACK diagnosis) and the
  health check work with both. Scripts that call `mqtt-bridge.sh publish` reach the running daemon through a FIFO
  instead of opening a connection each.
- `LICENSE`: the project's own code is under the GPL-2.0 (third-party code keeps its licence, `CREDITS.md`).
- **Wi-Fi rules per country**: the regulatory database (`regulatory.db`, Buildroot wireless-regdb) is in the
  initramfs, and Settings → Network → "Country (Wi-Fi rules)" (`WIFI_COUNTRY` in `boot.conf`, also in the JSON
  export / import) sets the country: wpa_supplicant starts with it, a change applies at once without reconnecting,
  and the rescue access point follows it. Empty = the world rules, as before.

### Changed
- **Wi-Fi up earlier at boot**: the boot script asks for the DHCP lease every second instead of every three (the
  first requests go out before the association), waits for `wlan0` in 0.2 s steps, and asks with the host name of the
  settings, so the services script
  no longer restarts `udhcpc` (which dropped the address until the new lease) on a camera with its own name.

### Fixed
- **RTSP server**: after an interleaved `$` frame the request buffer was not ended again, so a stale request end could
  be parsed past the received bytes and the buffer moved by a negative length (one connection, no password needed;
  audit 2026-11-04, H1).
- **Web pages**: three error pages printed the request back (a crafted link could run script in the camera's page),
  and the audit log stored the raw command name that `showlog` displayed; now nothing is printed back, the log keeps
  a command-name shape only and `showlog` escapes the logs (W1).
- A password exists before the web server starts on every boot path (safe mode, no video): the web interface was
  open without one (W5).
- Settings → Network → "Connect to this network" and "Restart the setup wizard" said "Error: Unexpected response"
  after a successful save (the page waited for `status: success`, the command answers `ok: true`).

## [3.0.1-rc24] - 2026-11-04

The audit fixes of the night of 2026-11-03/04, the tester's night findings on rc23 and plain HTTP only.
Kernel unchanged from rc23.

### Changed
- **Frigate configuration without the camera password**: `state.cgi?cmd=frigateyaml` writes
  `{FRIGATE_RTSP_PASSWORD}` in the stream addresses. A configuration pasted as is now needs that environment variable
  set to the camera password on the Frigate side (docker `-e`, compose `environment:`, or the add-on options).
- **Plain HTTP only on the camera** (port 80): the 2.x web modes and HTTPS leftovers are gone; HTTPS is done by a
  reverse proxy (README, "HTTPS with a reverse proxy").

### Fixed
- **Wi-Fi quality log frozen** (`wifi-quality.sh`): `iw` and `ping` run under `timeout`. The signal it records and
  shares with every page (`scripts/wifi-signal.sh`) is the access point's `beacon signal avg` (iw's `signal avg` of
  rtl8xxxu read -13 dBm where the beacons, /proc and the link rate gave about -50), else `/proc/net/wireless`.
- **Services switched off shown as stopped**: `health.cgi` says `disabled` and no longer counts them as restarts.
- **SD card "not properly unmounted"** after a deliberate reboot or a web update: the card is remounted read-only first.
- **Frame rate reported as 15 fps** in the Frigate configuration (`state.cgi?cmd=frigateyaml`), the Home Assistant
  integration manifest and the integration test while the camera ran at another rate: those three did not read
  `rtspserver.conf` before summing up the streams, and reported the defaults.
- **MQTT and Telegram settings could break their service**: a space, a quote or `$ ` \ ; & | < > ( )` in the MQTT
  user / password or the Telegram token / chat id was written as it was into a file that a shell script reads
  (a space broke the MQTT bridge, `$(...)` ran as a command). The settings page, the Home Assistant pairing and the
  Telegram settings now refuse those characters with a message; the setup wizard no longer keeps `( )`.
- **JSON configuration import took about 40 s** (the page could give up before the answer): each value rewrote its
  whole file, and the validation read every key with its own `awk`. The values are now written in one pass per
  file and the validation reads each file once: about 12-15 s on the camera, same result.
- **Tests:** the purged Bulma stylesheet kept up with the UI again (`has-text-weight-semibold`), so the CI is green.

### Documentation
- `CREDITS.md`: the Thingino row says what is left of it (nothing shipped); the prebuilt ARM programs are listed.
- `docs/known-issues.md`: 3.0 section brought to rc23 (exposure after a boot, Wi-Fi in the first minute and the
  missing `regulatory.db`, 10 fps in low light, characters refused in MQTT/Telegram settings, import duration).
- `docs/linux-port/audit-2026-11-03.md`: full project audit.
- `README.md`: "HTTPS with a reverse proxy" (Caddy and nginx examples, what the proxy must do for the live video).

## [3.0.1-rc23] - 2026-11-03

### Added
- **Smooth H.264 fMP4 / MediaSource video across all views**:
  - Live video stream via native MediaSource (`/cgi-bin/live.cgi`) is now the default on the main dashboard (`index.html`), all multiview panels (`multiview.html`), and the Settings live preview (`settings.html`).
- **Default mDNS local domain support** (`config/autostart/mdns`):
  - Starts lightweight `tc100-mdnsd` at boot; camera is reachable at `<hostname>.local` out of the box.
- **Live MQTT Bridge Status & Broker Diagnostics in Settings**:
  - Real-time connection badge and diagnostic description in Settings → Integrations, displaying CONNACK codes (4 bad credentials, 5 not authorized) and publish latency.
- **ISP White Balance (AWB) Tuning**:
  - Accelerated blue gain convergence in `tc100_rtsp` to eliminate warm/yellow color cast in indoor environments.

### Fixed
- **Wi-Fi stability under load**:
  - Reverted aggressive proactive USB re-probing in `scripts/net-guard.sh` that caused network bounce loops.

## [3.0.1-rc22] - 2026-11-03

### Added
- **Proactive Wi-Fi USB Recovery** (`scripts/wifi-recover.sh force`, `scripts/net-guard.sh`):
  - When gateway ping fails for >= 60 seconds (even if `wlan0` is still visible), `net-guard` now attempts proactive USB re-probing / Wi-Fi reload before resorting to an ungraceful watchdog reboot of the camera.
- **RTSP Network Pacing & Traffic Shaping** (`RTSP_PACING_US`, `RTSP_SNDBUF`):
  - Adds optional micro-pacing (`RTSP_PACING_US` in µs) in `tc100_rtsp` UDP transmission path to space out RTP packets during large IDR/I-frame bursts, preventing RTL8188FU USB Wi-Fi queue congestion and ping spikes.
  - Adds optional socket send buffer capping (`RTSP_SNDBUF` in KB) for both UDP and TCP RTSP sockets to limit kernel-side driver queuing.
- **RAM Footprint Optimization**:
  - Reduced default `RTSP_LOGMAX` from 256 KB to 128 KB to conserve tmpfs memory.
- **Multiview Live HTML5 Video**: Live camera stream via native MediaSource (`/cgi-bin/live.cgi`) on `multiview.html` with full EN/FR i18n support.

## [3.0.1-rc21] - 2026-11-03

### Added
- **Safe mode** (`v3/linux66-sd/boot-guard`, `BOOT_GUARD=1`): after 3 runs in a row that end within 5 minutes, the next
  start brings up Wi-Fi, web, ssh and the reset button only; the reboot history is kept in the flash settings; a web
  update checks the kernel (uImage, complete, not larger than what this camera's U-Boot reads) before writing anything.
- **Web pages for what only the config editor could set**: Alerts (Ntfy, webhook, Telegram, events, cooldown), tamper
  detection, babyphone and alarm sound (`scripts/action.d/events.sh`).

### Changed
- **One switch per service** (`scripts/service-switch.sh`): the boot, the Services page and the Settings read the same
  settings key (sound detection, syslog, recording, Memory Guard, rescue access point, MQTT, Telegram bot, motion);
  tamper settings live in `tamper.conf` only; one Telegram alert path (`notify.sh`); the Frigate + Home Assistant profile
  switches its services off once in the wizard, not at every boot. Migrated once per camera (`scripts/migrate-switches.sh`).
- **Menus by use**: Image (with a live picture over the image settings; sliders apply on release), Settings, Tools.
- **One definition per value**: Wi-Fi signal (`scripts/wifi-signal.sh`), RAM (MemAvailable), SD card health
  (`sdinfo-sd.sh` alone writes `/tmp/sd-health`).
- **Rescue access point on by default** (`WIFI_RESCUE=1`, owner's decision; fixed documented password kept); network
  guard waits two rescue cycles before rebooting.

### Changed
- **One configuration export/import format: a `.json` file** (`config_exchange.cgi`). The tar.gz backup
  (`configbackup.cgi`, `upload_backup.cgi`) and the `.conf` export (`conf-export.cgi`, `conf-import.cgi`) are removed.
  The export has an "include secrets" box, off by default: without it no Wi-Fi, password or token is in the file (safe
  to share between cameras); with it the file restores a camera completely (Wi-Fi networks, camera password, MQTT,
  Telegram, Ntfy, rescue access point password). Added to the file: local recording (`REC_*` of boot.conf), day/night
  (daynight.conf), notifications (notify.conf), tamper, sound detection (vox, alarm), image tuning (isp_tune.conf), the
  rescue access point, boot guard, saved logs, Wi-Fi quality. Removed rows that no longer matched a live key (`rec_*` of
  recording.conf, the day/night values of rtspserver.conf, `PRIVACY_SCREEN`).
- **Push to another camera works**: the form asks for the target's user and password, the CSRF token of the target is
  read first, the request body is read by the CGI (it used to be dropped); a push never carries secrets.

### Removed
- **network-monitor** (`controlscripts/network-monitor`, `scripts/network-monitor.sh`, `netmon.conf`): `scripts/net-guard.sh`
  (run by the housekeeper every minute) is the one network watcher. The `network/state` MQTT topic and the `network` object of
  the health payload went with it. Cameras that listed it in `MEM_GUARD_SOFT_SERVICES` lose the name at the next memory-guard start.
  `MEM_GUARD_SOFT_SERVICES` is empty by default.
- **HTTP File Share (WebDAV-compat)** service (`controlscripts/webdav`, port 8080): the Recordings page already serves `/DCIM`.
- **Privacy Shield leftovers**: `cmd=enable_privacy_shield`, the MQTT `privacy_shield` command and the `privacy_mode` health field.
- **`cmd=conf_autodaynight`**: it wrote keys of `rtspserver.conf` that nothing reads (the day/night daemon reads `daynight.conf`).

### Fixed
- White balance memory (`awb.state`) no longer triggers a settings write to the SPI flash by itself: it is saved with the next
  real settings save (boot-guard, deliberate reboots).

---

## [3.0.1] - 2026-10-31

Tested on two TC100 cameras of the same variant: from rc5 on, each release candidate was installed and checked on
IPCAM2, and rc16 also runs on IPCAM1 (installed by the web update). In short: runs from the flash with no SD card, the speaker works,
night picture and low-light settings from the sensor tuning, Wi-Fi that recovers by itself after a reboot, about
21 MB of free memory, the clock, masks and sub-stream done by the image processor. The entries below are the
release candidates' details, newest first.

### Added (3.0.1-rc19)
- **Web UI Multi-View 2×2 Grid Viewer (`www/multiview.html`)**:
  - Live 2×2 camera monitoring matrix polling snapshot feeds (`/cgi-bin/currentpic.cgi`) from local and remote cameras.
  - 100% client-side execution in the browser with `localStorage` configuration persistence (IP / `.local` hostnames and custom camera names).
  - Native integration into the top navigation bar (`Multi-View`).
- **Built-in Sound Library & Alert Triggers (`sounds/`, `action.d/audio.sh`, `scripts/mqtt-bridge.sh`)**:
  - Pre-generated PCM 8 kHz anti-clipping sound clips at -6 dBFS: `chime.pcm` (doorbell 2-tone) and `siren.pcm` (swept alarm).
  - Web action API endpoint `cmd=play_sound&sound=chime|siren|alert` with volume control.
  - Home Assistant MQTT discovery buttons ("Play Chime", "Sound Siren") and MQTT command topic support.
  - Audio Test button on live dashboard linked directly to built-in chime playback.
- **Continuous Siren & Smoke / CO Alarm Detection (`controlscripts/sound-detection`)**:
  - Fires on any loud sound sustained ≥3 s (level only, the pitch is not analysed), which smoke and CO alarms
    produce; music or a vacuum cleaner trigger it too. Needs `ENABLE=1` in `sound_detection.conf`. A help, not a
    safety device.
  - Home Assistant `safety` binary sensor (`mdi:fire-alert`) publishing to `<root>/alarm/state`.
- **Motion Best-Shot Selection & Named Zones (`scripts/detectionOn.sh`, `scripts/action.d/detection.sh`, `www/settings.html`)**:
  - `motion_best_shot=1` takes a rapid 3-shot burst and selects the sharpest JPEG image by detail/byte size for alerts and notifications.
  - Switch exposed in Web UI Settings under Detection tab, persisted in `motion.conf`, and exposed in `state.cgi` / `config_exchange.cgi`.
  - Named motion exclusion zones (`MDZ<n>_NAME`).
- **Enhanced Web Config Editor (`www/configeditor.html`, `www/cgi-bin/configeditor.cgi`)**:
  - Added whitelist support for `sound_detection.conf`, `notify.conf`, and `tamper.conf`.

### Added (3.0.1-rc18)
- **Multi-channel Notifications (`scripts/notify.sh` + `config/notify.conf.dist`)**:
  - Direct alert dispatcher supporting **Ntfy** (`ntfy.sh` or self-hosted) with priority, tags and instant JPEG snapshot attachment.
  - Generic **Webhook HTTP POST** with JSON payload (`hostname`, `event`, `message`, `timestamp`).
  - Unified Telegram dispatch through `bin/telegram`.
  - Configurable anti-storm cooldown (`NOTIFY_COOLDOWN_SECONDS=15`) per event type.
  - Automatically wired into `motion-event.sh`, `sound-detection`, and `tamper-detect.sh`.
- **Prometheus Metrics Exporter (`www/cgi-bin/metrics.cgi`)**:
  - Standard Prometheus exposition format (`version=0.0.4`) exposing system uptime, load averages, memory (total/free/available bytes), Wi-Fi link quality and dBm, network traffic and drops, active RTSP viewers, scene luminance, audio dBFS, and active detection states (motion, tamper, vox). Pure ash, reading `/proc` directly without heavy forks.
- **Home Assistant MQTT Binary Snapshot (`scripts/mqtt-bridge.sh`)**:
  - Direct raw JPEG image bytes published to `<root>/snapshot/image` via `mqtt_publish_file` on snapshot requests.
  - Opt-in camera entity discovery (`MQTT_HA_CAMERA_ENTITY_ENABLE=1` in `mqtt.conf`) compatible with Home Assistant's MQTT camera platform.
- **VOX / Babyphone Mode & Camera Tamper Detection**:
  - `VOX_MODE=1` and `VOX_HOLD_SECONDS=5` in `sound_detection.conf` (with `ENABLE=1`, which turns the sound
    detection on) with Home Assistant `sound` binary sensor.
  - Real-time audio VU level (`sound_db`) in the web UI status line without subshells.
  - Occlusion / tamper detector (`scripts/tamper-detect.sh`) with day/night transition guard and Home Assistant `problem` binary sensor.
- **Remote Diagnostics & Network Reliability**:
  - Freestanding mDNS daemon `tc100-mdnsd` answering `.local` domain name queries.
  - 24-hour Wi-Fi connection quality tracking (`scripts/wifi-quality.sh`) reporting retries, packet loss, and signal metrics.
  - Kernel SD card error logging in `sdinfo-sd.sh`.
  - Closed-loop software AWB fallback in `scripts/nightmode.sh`.
  - Persistent SSH host keys across reboots.

### Added (3.0.1-rc17)
- **Install with no click**: after the stock-firmware hook, the first start from the card checks the copy of the
  original flash again (md5, U-Boot and `mac` areas of this camera), the hardware and a picture from the sensor,
  then installs to the flash by itself and restarts from it with the chime (`v3/install/auto-install.sh`). No Wi-Fi
  needed. `ESSAI.txt` on the card keeps the trial mode; a flash that already holds 3.0 is never written by the card.
- **Way back without a shell**: `RESTAURER.txt` (or `RESTORE.txt`) on a card that starts the camera writes back the
  copy of the original flash (`restore-stock.sh`, which now refuses a copy that is not this camera's) and restarts
  into the previous system.

### Changed (3.0.1-rc17)
- An upgrade no longer keeps the picture tint and saturation of an older version (owner's decision: a 2.x camera
  came with `HUE=-10`, `SATURATION=-13` and a green picture): reset to 0 once, live image tuning switched off.
- README, the card's LISEZ-MOI and README-3.0: the automatic install, `ESSAI.txt`, `RESTAURER.txt`; push-to-talk and
  two-way audio marked "not yet checked on a camera"; recording is off until the wizard or Settings turns it on.

### Fixed
- **Strong blue / violet cast on rc15** (R15-01): fed the live white balance statistics, the ISP's own white
  balance chose gains the software white balance could not correct. 3.0.1-rc16: the algorithm works as up to rc14
  (the software white balance then brings the picture to neutral), the live counts still reach `/tmp/cam_awb` and
  the day / night method; `ak_isp.awb_live=1` keeps the rc15 behaviour for further work.
- Boot console: "Wi-Fi settings from the saved settings" when they come from the flash (it always said "SD
  card"), and the board profile line no longer says "unknown hardware" before the sensor is read.

- **The image processor's white balance worked on fixed, random-looking data** (R12-09, statistics dumps on
  IPCAM2): the kernel read the white balance counts at word 1032 of the statistics area; they are the last 40
  words (from 1160). 3.0.1-rc15 reads them there: the ISP's own white balance gets live statistics (a candidate
  for the colour cast), `/tmp/cam_awb` and the stock day / night method too (thresholds at the scale of these
  counts: the stock library defaults 1200 / 50000).
- **Speaker clips at full scale** (R12-04: audible but weak and crackling): the camera's sounds are at -6 dBFS with
  5 ms fades; `sounds/test-1k-m6|m12|m20.pcm` tell clipping from a playback fault.

### Changed
- **3.0.1-rc15 defaults** (each passed on IPCAM2): the night picture settings (R14-02), 10 fps in low light by day
  (R12-02), the IR-cut pulse 10 ms (R12-06: 20 / 20 heard). Each can be turned off (Day/night page, `IRCUT_PULSE_MS`).
- **Wi-Fi recovery:** one clean restart when the link is slow after a power cycle of the chip (R14-01).

- **Camera off the network after warm reboots** (W-NET, IPCAM2: the Wi-Fi chip answered on USB but "Failed power
  on", no `wlan0`, Frigate and the web page unreachable until a power cut; the net-guard's warm reboot did not
  help). 3.0.1-rc14: `scripts/wifi-recover.sh` probes the chip again, then power-cycles it through GPIO 11 (the
  stock firmware's Wi-Fi power pin) and applies the Wi-Fi settings again; it runs at boot when `wlan0` is missing
  and from the net-guard before any reboot. `meta.txt` of the saved logs counts the failures (`wifi_power_fail`).
- **Night picture settings refused** (R12-01: `AK_ISP_SET_TUNING_STYLE` answered ENODEV): the video driver now
  gives the ISP its parameter-set callback.

- **Smart encoding stopped the video server** (rc11, R11-01: mode 1 needs 3.25 MB more encoder DMA than the 9600K
  pool has, mode 2 ends the encoder after 3 frames). 3.0.1-rc13: not on the web page any more; mode 1 only when the
  pool has the room, mode 2 only with `RTSP_SMART_FORCE=1`, and a server that died after trying it skips it at its
  next start (no crash loop under the watchdog).
- **Day / night "Stock firmware method" with frozen white balance counts** (R11-02: the same numbers for hours):
  counts unchanged for 3 samples are ignored and the light metric decides alone.

- **Speaker silent** (3.0.1-rc12, R12-04): the amplifier enable (GPIO 14) is active low, as the stock kernel and app
  use it; the device tree drove it active high, so it was off while playing and on at rest. `speak-gpios-en = <0>`,
  the amplifier stays off at rest; `ak39_codec.spk_active=0|1` overrides the level.

### Added
- **3.0.1-rc13 diagnostic:** dmesg gives the address of the ISP statistics area and
  `scripts/isp-stat-dump.sh` reads it (R12-09: find the live white balance counts; the kernel's own white balance
  reads the frozen ones, a candidate cause of the colour cast).
- **3.0.1-rc12: the rest of what the stock firmware does** (`docs/linux-port/vendor-re-findings.md`), each
  switchable from the web page:
  - **Night picture settings** (Day/night page): the tuning file's night parameter set (2.5 x exposure, night
    noise filter, 10 fps) when night mode starts, the day set back at day. Off by default.
  - **10 fps in low light by day** (Day/night page), as the stock app: brighter, less noise. Off by default.
  - **Day / night source "Stock firmware method"**: exposure x gain / exposure limit x 40 / picture brightness,
    confirmed by the white balance counts, the stock thresholds, the flap lock. The default source stays luminance.
  - **IR LED protection** (every source, on by default): after 14 h of night, day mode for 10 minutes.
  - **Bit rate mode and smart encoding** on the Streams & audio page (`vbr`, `smart` in rtspserver.conf;
    `RTSP_VBR` / `RTSP_SMART` of rc11). Off by default.
  - `/tmp/cam_ae` gets a 7th field, the current exposure limit.

- **3.0.1-rc11: what the stock binaries taught** (Ghidra on the stock firmware dump and `libmpi_venc_ex.so`,
  `docs/linux-port/vendor-re-findings.md`; no vendor file in the repository):
  - **Encoder smart mode** (`RTSP_SMART=1` long-term reference, `2` variable GOP; off by default, only with
    `RTSP_VBR=1`): `ak_venc_set_smart_config` with the stock values (GOP 300, quality 100, static 550).
  - **White balance counts for day / night** in `/tmp/cam_awb` and the calibration log (`awb=`): the stock
    switch confirms its light metric with them. Measurement only, the logic is unchanged.

### Fixed
- **A setting changed less than a minute before a reboot from the web UI or MQTT was lost** (R10-01): the
  settings are saved to the flash once a change has been stable for 30 s. A deliberate reboot now saves first
  when something changed (`cfg-persist flush`, called by `reboot-tracker.sh intent`).

### Changed
- **3.0.1-rc10:**
  - **Anti-flicker:** the default choice is "Camera default", and the page and `tc100_rtsp.log` say what it is
    (`POWER_HZ_BASE`; 50 Hz on IPCAM2, whose tuning file already uses a 281-line exposure step). It was
    labelled "Off", which it never was.
  - **Day / night:** a manual Day / Night choice (`daynight=3`) that keeps the automatic switching off is now
    said at boot (console, syslog) and by the service health ("manual day/night mode") instead of nothing.
  - **3D noise reduction stays off** (R9-01: 25 to 34 % less noise, but 5.6 MB of RAM and 1.6 MB of CMA left;
    the owner keeps the RAM). `ak39_vi.nr3d=1` remains available; CI no longer builds its card test kernel.

### Added
- **3.0.1-rc9: the parts of the SoC still unused, each off by default until checked on a camera** (test queue
  R9-01 to R9-04 in `docs/linux-port/test-queue.md`):
  - **3D noise reduction** (kernel, `ak39_vi.nr3d=1`): the ISP's 6.2 MB reference frame is reserved once at boot
    instead of being asked for at every video start, where it never found room. A card test kernel built by CI
    (`tc100-linux66-nr3d-test`) carries `nr3d=1` and a 24 MiB CMA area in its own command line.
  - **Anti-flicker** (Settings, Picture: Off / 50 Hz / 60 Hz, `POWER_HZ`): the ISP's auto exposure keeps
    exposures at whole lamp pulses (`exp_step` of `AK_ISP_SET_AE`). Applied whatever live tuning is.
  - **Day / night from the ISP exposure:** thresholds of the `ae` source from the night measured on IPCAM2 (night
    above 15000, day below 3000; were 4000 / 1000), and a calibration line every 5 minutes in
    `/tmp/logs/daynight.log`. The default source stays the picture luminance.
  - **Encoder:** the optional calls of the vendor library are listed once in `tc100_rtsp.log` (looked up, never
    called), for the smart mode.

### Fixed
- **Logs kept across reboots stopped after the 8th boot** (3.0.1-rc8, F-05 on IPCAM2): the boot counter `0008` was
  read as octal by ash (`arithmetic syntax error`), so no `boot-NNNN` folder was made at boots 8, 9, 18, 19 ... The
  leading zeros are stripped before the count.
- **`amixer -c 0` failed on rc7** (speaker volume, microphone level at start and from the UI did nothing): the user
  space ALSA tree lacked `cards/aliases.conf`, which `alsa.conf` includes (the slim base drops `cards/`). Its working
  part, the four includes that define `sysdefault`, `dmix` and `dsnoop`, is written into `ext/share/alsa/cards/`.
- **Front LEDs, IR LED, speaker amplifier and reset button lost to the Ethernet pads** (3.0.1-rc7, LED-01): the ISP
  start ORed the OpenIPC 4.4 sharepin values, which mux the RMII pads 10 11 13 14 15 19 20 23 24 47, into SYSCTRL.
  Only the sensor clock pad and I2C are set now.
- **`tc100_rtsp.log` grew without limit in RAM** (a STAT line every 5 s, about 2.6 MB a day): rotated at 256 KB
  (`RTSP_LOGFILE`, `RTSP_LOGMAX`).

### Changed
- **3.0.1-rc9: the encoder pool is 9600K by default** (`ak39_venc.pool`, kernel patch 0015; R8-02 on IPCAM2: the
  encoders use 8866880 bytes at most in H.265 and H.264, MemAvailable 22 MB instead of 19). `ak39_venc.pool=12M`
  takes the whole area as before. The 3D-NR reference frame is no longer tried at each video start (two failed CMA
  allocations and a warning in dmesg every time).
- **3.0.1-rc8: the rc7 switches that passed on IPCAM2 are the defaults** (no new feature; checks R8-01 in
  `docs/linux-port/test-queue.md`):
  - **Kernel:** 3 capture buffers (`ak39_vi.slots`, P-02: +3.5 MB of RAM, no dropped frames at 15 and 25 fps;
    `ak39_vi.slots=4` = before).
  - **Video server:** the clock drawn by the ISP OSD (HW-07, about 2 % of a core; `RTSP_ISPOSD=0` = CPU) and the
    privacy masks by the ISP (HW-04; `RTSP_ISPMASK=0` = CPU). Both fall back to the CPU by themselves on a refusal.
  - **MQTT:** a broker that refuses the login (CONNACK 4 / 5) shows as "MQTT: login refused" in the web UI instead of
    a plain "fail" (`mqtt_refused` in the status JSON).
  - **HW-02 test 2 ready (R8-02):** CI also builds a card-only test kernel with `ak39_venc.pool=9600K` in its own
    command line (artifact `tc100-linux66-hw02-pool9600k`: no U-Boot prompt, nothing written to the flash). With a
    smaller pool `tc100_rtsp` leaves out the 3.4 MB start-of-pool guard by itself (`RTSP_POOLPAD` still forces one);
    the default 12 MiB pool is unchanged. Kept as the default in rc9 if it passes, dropped otherwise.
  - Kept opt-in after the rc7 measurements: `RTSP_UDPSG` (fine, no gain), `RTSP_UDPMMSG` (stutters in VLC),
    `otg_hs.fifo32` and `rtl8xxxu.dma_aggregation` (no gain), `RTSP_FRAMECOPY=0`.
- **3.0.1-rc7** (camera checks P-01..P-09, S-01, W-01 and the rc7 plan in `docs/linux-port/test-queue.md`):
  - **Kernel:** IP multicast (ONVIF discovery), and `ak39_vi.slots` (opt-in 3 capture buffers, about 3.4 MB of CMA).
  - **User space squashfs:** 128 KiB blocks, half the decompression per page.
  - **Video server:** RTP without payload copies (`RTSP_UDPSG=1`, opt-in), 384 KB client queues with a partial
    burst for late joiners, live MP4 built into the send buffer, `RTSP_VBR`.
  - **Web:** `statusline.cgi` (a fifth of the shell to parse per poll), one stylesheet for the main page.
  - **Tools and CI:** `scripts/perf-baseline.sh`; the Buildroot base cached in CI.
- **Remote shells under Services** (`[svc]`): SSH (`ssh-server`, dropbear) on by default, telnet (`telnet-server`) off
  by default; the always-on telnetd of the base image is gone (`v3/S50telnet-linux66`, only a fallback without
  dropbear). The boot follows the Services "Boot" toggle; an upgraded camera that never chose keeps SSH on. The
  rescue telnet while the web UI is down is unchanged.
- **The housekeeper has a restarter** (`housekeeper.sh supervise`): a small `service-watchdog.sh` process restarts the
  loop if it dies (no reboot, same back-off as the other services).
- **Optimisation pass for the AK3918** (commits `[opt] ...`; camera checks O-01..O-05 in `docs/linux-port/test-queue.md`):
  - Kernel config about 520 KB lighter in RAM and squashfs fragment cache 1 block (about 1 MB less in flash mode);
    initramfs about 0.45 MB smaller; `tc100_rtsp` and `libakuio.so` stripped (both live in /tmp).
  - The video server reads each encoder frame once from uncached memory instead of 4 to 6 times
    (`RTSP_FRAMECOPY=0` restores the old path), with less per-frame work and client queues that shrink after a
    congestion (`RTSP_QTRIM=0`).
  - Shell side: dashinfo cached, fewer requests at page load, fork-free day/night daemon wait, the network check
    every 3 minutes while the gateway answers, crond only with a crontab, a single boot.conf parse.
  - One resident housekeeper loop (`scripts/housekeeper.sh`) instead of six shell processes: web guard, network guard
    and SD panel checks, the RTSP and MQTT service watchdogs, the health snapshot and log persistence run as its jobs
    (own periods, a slow job never holds up the others). `HOUSEKEEPER=0` in boot.conf restores the separate daemons.
  - RAM image (initramfs, never reclaimed) from about 4.45 MB to 2.38 MB: the ALSA tools and data, libasound,
    dropbear and the libraries only they need moved to `ext/` of the user space (flash squashfs or card tree, read
    on demand), links left in their old places; busybox 290 -> 192 applets (`wget`, `nslookup`, `traceroute`,
    `telnet` client gone: use `curl`), alsa-lib PCM + mixer only, hostapd / wpa_supplicant / dropbear trimmed
    (camera checks B-01, B-02, O-06).

### Fixed
- **Web UI pass** (HTML/CSS/JS only, commits `[webui] ...`; camera checks: UI-22 in `docs/linux-port/test-queue.md`):
  Settings orientation could not be saved (field taken for an IP address), negative sound threshold refused,
  "Install & reboot" threw before posting, Home Assistant badge stuck on "Checking...", input bounds aligned on the CGIs,
  Wi-Fi password checked before sending; config editor turned a literal `\n` into a line break and failed on tabs;
  restore / import could send an empty CSRF token right after a page load; recordings with a space in the name did not
  play; live video kept streaming after leaving the Live view; error states, confirmations for destructive actions,
  labels and keyboard use, 390 px layout and missing French strings across the pages.

### Added
- **Live video in the browser** (Video / Snapshots switch on the live view): the camera's H.264 stream (sub-stream by default) as fragmented MP4
  through `live.cgi` and Media Source Extensions, no re-encoding, two viewers at most, snapshots as the fallback. Waiting for a camera run
  (`docs/linux-port/README.md`, tc100_rtsp part).
- **Five improvements, waiting for a camera run** (tests: `tests/test_feat30.py`, `src/tc100rtsp/test_util.c`):
  - Day / night can decide from the ISP exposure instead of the picture luminance (`DAYNIGHT_SOURCE=luma|ae|isp` in
    `config/daynight.conf`, Settings -> Day/night with a live reading, hold times: night after 10 s, day after 60 s).
    Default stays `luma`.
  - Frame rate select on Settings -> Streams & audio: 10, 12, 15 (default), 20 or 25, one rate for both streams
    (`rtspserver.conf` `[0] fps`, passed as `-f` by `rtsp-launch.sh`; anything else means 15).
  - Optional lower frame rate when nothing moves: `IDLE_FPS` (0 = off, default) and `IDLE_AFTER` in `boot.conf`;
    needs motion detection; not applied while recording continuously.
  - Logs kept across reboots: `scripts/log-persist.sh` copies dmesg, the syslog and the service logs to
    `/mnt/sd/logs/boot-NNNN` every 10 minutes and before a deliberate reboot (last 5 boots, about 2 MB each,
    `LOG_PERSIST=0` turns it off); the Logs page lists and downloads them (`cgi-bin/savedlogs.cgi`).
  - Config import (`conf-import.cgi`) takes `IDLE_FPS` (0-24), `IDLE_AFTER` (1-3600 s), `LOG_PERSIST` (0/1) and
    `LOG_PERSIST_MIN` (1-1440); a value out of range rejects the whole file, as for the other keys.
  - Memory Guard defaults: warn 6144 KB and critical 3072 KB (were 8192 / 4096, next to the normal 10.8 MB
    MemAvailable); the warn stage no longer stops `auto-night-detection`. Cameras holding exactly the old values are
    moved when the service starts.

- **More work done by the hardware, waiting for a camera run** ([test queue](docs/linux-port/test-queue.md)):
  sharpness and exposure cap on the Image page again, applied by the ISP; privacy masks (`RTSP_ISPMASK=1`) and the
  clock (`RTSP_ISPOSD=1`, kernel patch 0014: ISP OSD ioctls) by the ISP instead of the CPU; 3.4 MB less of the encoder
  pool with direct capture, and the pool from a CMA area whose size `ak39_venc.pool=` sets (patch 0015, the rest goes
  back to the kernel); Wi-Fi USB FIFO in 32-bit words (`otg_hs.fifo32=1`, patch 0013); the exposure state in
  `/tmp/cam_ae` for a future day / night decision. The applied values show under the Image form again.
- **15 fps for real, about 45 points less CPU** (measured on a TC100: user CPU 53 % -> 8 %, frames 9.5 -> 15 per
  second, same bit rate): the encoder reads the capture buffer itself (no 3 MB copy per frame), the white balance
  is steered in the ISP (no table over the colours), the 640x360 sub picture comes from the ISP's second output,
  and the configured frame rate is kept. Each part falls back to the previous way on its own; switches in
  `config/rtsp.env`: `RTSP_DIRECT=0`, `RTSP_ISPAWB=0`, `RTSP_HWSUB=0`, `RTSP_CACHED=0`.
- No more out-of-memory kills with 10 MB free: the kernel's page blocks are 512 KB instead of 4 MB
  (`CONFIG_ARCH_FORCE_MAX_ORDER=7`). With 4 MB blocks the 47 MB of RAM had only 16 of them, and the reserve for
  high-order atomic allocations (the Wi-Fi's receive buffers) took one or two whole blocks, up to 8 MB: a new
  process (16 KB page table) could not be created although 9.7 MB were free (seen 84 s after a start). Measured: 1 MB reserve, no failure.
- 2 MiB more RAM for the system: the guard zones around the encoder pool are gone (they never caught a stray write;
  the old memory corruption was the 640 MHz clock).
- Direct capture takes each buffer's physical address from the capture driver (`AK39_VI_G_PHYS`); the RAM search
  through `/dev/mem` stays only for older kernels.
- Hue (Image page) and the night black and white are done by the ISP too: hue turns every colour sector of
  `AK_ISP_SET_HUE` (measured +27 degrees for +30 asked), black and white sets the ISP colour gain to 0 instead
  of clearing 1 MB of chroma per frame. No table over the picture is left; `RTSP_ISPTUNE=0` brings them back.
- Live image tuning (Image page: brightness, contrast, saturation) is done by the ISP (`AK_ISP_SET_YUV_EFFECT`,
  on top of the tuning file's values) instead of a table over every byte: a camera with tuning on stayed at
  15 fps instead of dropping below 6 (and 95 % CPU). Hue still uses a table (cached buffers then).
  `RTSP_ISPTUNE=0` keeps the tables.
- Uncached capture buffers with direct capture, and the sensor set to the stream rate (15 fps instead of 25) once
  the video runs: the kernel no longer invalidates 3.4 MB of cache line by line for each of 25 frames a second.
  Measured on a TC100 at 15 fps: CPU idle 35 % -> 68 % (system 50 % -> 19 %). `RTSP_CACHED=1`,
  `RTSP_SENSOR_FPS=0` bring the old behaviour back.
- The kernel programs the ISP sub channel by default (`ak39_vi.sub_channel=0` turns it off): no U-Boot change.
- **Sound in the recordings**: a G.711 A-law track next to the video in each MP4 (`REC_AUDIO`, on by default).
- **Listen live** from the browser again (`audio_stream.cgi`, fed by tc100_rtsp, at most 3 listeners).
- **Two-way audio** through the RTSP stream (ONVIF backchannel, go2rtc / Home Assistant / Frigate microphone button),
  password required, one talker at a time; Settings → Video → Two-way audio (`RTSP_LITE_TALK`).
- tc100_rtsp opens `libmpi_venc_ex.so`, else the camera's own `libmpi_venc.so`, and logs which.
- `make test_rtsp`: tc100_rtsp built for the host, with tests of the audio track, backchannel and listeners.

### Changed
- **`main` holds 3.0 only.** The 2.x firmware moved to the branch `2.x`: its boot script, lighttpd and its
  configurations, the vendor RTSP server and `libtc100fix`, the 2.x flash install and update tools (`src/flash`,
  `src/release`, `flash-*.sh`, `fw-update.sh`...), the CPU scaler, the old PTT players, the OpenIPC 4.4 kit and their
  tests (about 150 files).
- **No proprietary file in the repository**: the RTL8188FU firmware is downloaded by the kernel build from
  linux-firmware (pinned tag and checksum); the encoder API library (`libmpi_venc`) and the sensor tuning file come
  from the camera at install, like the other vendor libraries.
- The 3.0 versions became the only ones: `controlscripts/rtsp-h26x`, `bin/setconf`, `www/cgi-bin/update.cgi` and
  `flashinstall.cgi`; the wizard, push-to-talk and the speaker test have no 2.x path left.
- `config/boot.conf.dist`: about 60 settings nothing reads any more removed (lite RTSP server, low-CPU overrides,
  CPU scaler, motion schedule, storage cleanup, print levels...); `WEB_MODE=http` by default.
- README rewritten for 3.0.

### Fixed
- Install to flash on a camera that already ran 3.0 from its flash kept the card's settings instead of its own:
  the settings in the flash are now kept (a first install still takes the card's; `tc100-3/settings-from-card`
  forces them).
- The local-network filter (`libnetacl.so`, built for uClibc) was preloaded into musl programs too (telnet, rescue
  telnet): now only into programs of the uClibc runtime.
- The setup wizard's French text for the 3.0 steps (password, one-click install).
- Settings → System → "Run the wizard again" now also clears the 3.0 marker.
- The Services page and the RTSP control script agree on the pid file of `tc100_rtsp`.
- The self-test checks the picture of `tc100_rtsp` instead of the removed software streamer.

## [3.0.1-rc1] — 2026-10-26 (not yet run on a camera)

### Added
- **Built from git, installable by anyone**: CI makes `tc100-<version>-sd.zip` and `tc100-<version>-update.tar`
  with free files only. On first start the stock (or 2.x) firmware runs the card's hook: it checks the camera,
  saves the whole flash to the card, copies the camera's own vendor libraries, settings and Wi-Fi, and adds the
  3.0 start commands to U-Boot (stock start kept as fallback). Trial mode from the card, then **one-click install
  to flash** from the setup wizard or Settings; web updates write the flash; `restore-stock.sh` goes back.
  New flash partition `vendor` (1 MiB) for the camera's libraries. Details: `docs/linux-port/install-3.0.md`.
- **Web login** on 3.0 (busybox httpd, root + camera password); the 3.0 wizard sets the password.
- **RTSP sub-stream** 640x360 (`video1_unicast`, `ch1`, `sub`), **recording** inside tc100_rtsp to fragmented MP4
  with a JPEG thumbnail per file (no ffmpeg), sound level, motion zones and on/off.
- Every page on 3.0: speaker and push-to-talk through ALSA, Telegram and update check (curl), Wi-Fi rescue access
  point (hostapd), reset button polling, IR-cut pulse, auto day/night with luminance thresholds, ONVIF over HTTP,
  SD panel, a single RTSP restarter, settings deletions kept by `cfg-persist` and a "Settings not saved" badge.
  What the hardware cannot do is hidden on 3.0 with a note.

### Changed
- Wi-Fi changes from the web page and the wizard are written where the boot reads them and used at once.
- One flash writer (`flashw`, now with `-m MD5` and `-b DIR`); `flash-code.sh` refuses the 6.6 layout.
- LF line endings in every checkout (`.gitattributes`).

### Fixed
- Automatic day / night no longer stays stuck in NIGHT: its own switch used the manual-override path; it now keeps
  the automatic mode (`NIGHT_KEEP_AUTO=1`) and its loop starts no process (2026-10-25).
- Fewer processes in the background services (cached `timeout` probe, watchdogs and `cfg-persist` without forks);
  the MQTT bridge launcher no longer holds the console.

### Documentation
- `docs/linux-port/README.md` brought up to date with the flash install (status, memory map, flash layout,
  10-patch series, encoder progress, open items); README: what 3.0 really serves today (one RTSP stream, no
  sub-stream yet; H.264 / H.265 through the vendor encoder libraries on the free driver).

## [3.0.0] — 2026-10-24

The same firmware on Linux 6.6 instead of the vendor 3.4 kernel, running from the SPI flash with the SD card
optional. The 2.x firmware is unchanged and stays available. Details: [docs/linux-port](docs/linux-port/README.md).

### Added
- **Linux 6.6 port** of the AK3918EV300 as a 10-patch series on `v6.6` (`patches/kernel-6.6/series`), built by CI:
  machine, interrupts, timer, console, L2 buffer engine, SD card, USB host, Wi-Fi RTL8188FU (mainline `rtl8xxxu`),
  GPIO, I2C, watchdog, audio (`ak39_codec`, `ak_pcm`), V4L2 video for the JX-F23 (`ak39_vi` + the ISP core), encoder
  access (`ak39_venc`), SPI controller and NOR partitions (`spi-ak39`).
- **Hardware encoder on the free kernel**: `ak39_venc` + `libakuio` (free replacement of the vendor library) let the
  vendor encoder control libraries make H.264 and H.265; `src/jpegenc` makes JPEG on the hardware core with free code.
- **`tc100_rtsp`** (`src/tc100rtsp`): RTSP server for the main 1080p stream, H.265 (RFC 7798) or H.264 (RFC 6184),
  RTP over TCP or UDP, Digest/Basic login with the camera password, optional G.711 A-law audio, web UI pictures and
  the light level from the hardware JPEG engine, grey-world white balance, black and white, and, burned in before the
  encoder: image tuning (brightness, contrast, saturation, hue; `ISP_TUNE=1`), up to 4 privacy masks and the OSD clock.
- **Runs from flash**: kernel, xz initramfs and a 3.2 MiB xz squashfs user space (`v3/linux66-sd/build-slim-stack.sh`)
  in the SPI flash; settings in two alternating 36 KiB slots (`cfga` / `cfgb`, `cfg-persist`); guarded writer
  `flashw` (allow-list, read-back check). U-Boot, `boot` and `mac` are never written. An SD card with
  `tc100test/c66.img` boots first (development and the way back).
- `v3/`: 6.6 boot script, initramfs builder, autorun, self-test (`selftest66.sh`), glue for the 2.x web UI
  (`rtsp-h26x` and `setconf` shims, `rtsp-launch.sh`, `sdinfo-sd.sh`).
- Web UI on 6.6: flash layout and usage on the dashboard, MQTT with Home Assistant discovery (more entities, LED and
  telemetry from the 6.6 sysfs), day / night with thresholds, motion detection, `ntpd` clock, services ticked in the
  UI started at boot.
- Study tools: H.265 command list generator (`src/h265enc`, 40 recorded frames reproduced offline), `venctrace`,
  `venctest`, `AK39_VI_G_PHYS` ioctl (physical address of a capture buffer).
- OpenIPC SD boot kit (`contrib/openipc_sd_kit/`, Linux 4.4, historical) and a first Thingino board port
  (`thingino_port/`).

### Changed
- Core PLL at 480 MHz (ASIC 120 MHz, the stock 3.4 setting): at 640 MHz long H.265 runs crashed.
- Memory: encoder pool 12 MiB with 1 MiB guard zones, CMA 18 MiB from the command line, 3D-NR off (its reference
  frame does not fit), OOM watermarks lowered so small daemons are not killed with memory still free.

### Fixed
- Audio: the delayed capture start is cancelled on stop / close (NULL pointer oops when a stream ended within 300 ms).
- Flash mode without a card: the ISP tuning file is shipped in the squashfs (no video otherwise).
- MQTT discovery refresh; health payload retained.

### Not available on 3.0 yet
- RTSP sub-stream, sharpness and the other ISP-daemon settings, resolution / frame rate settings (fixed 1080p,
  15 fps), speaker and two-way audio (not tested on 6.6), one-click flash installer.

---

## [2.1.9] — 2026-10-18

A lighter RTSP server, sound both ways, motion zones.

### Added
- **Lite RTSP server** (`src/tc100fix/rtsp.c`, inside the video process). It sends the frames the SoC encoders already produce, without decoding or re-encoding them, and does not change the vendor server.
  - **Settings → Video → RTSP server**:
    - *Original* (live555) or *Lite* on the RTSP port (`RTSP_SERVER=lite`). The addresses (`/video0`, `/video0_unicast`, `/video1`…) and the password stay the same, so recorders see no difference.
    - The vendor server keeps running for the encoders, on `RTSP_VENDOR_PORT` (8555), with no client.
    - If the lite server has not opened the port 30 s after a start, the vendor server takes it back until the next reboot.
  - **What it sends**:
    - H.265/H.264 video and the G.711 sound (trackID=1), with both timestamps on the same clock.
    - RTP over the RTSP TCP connection (UDP is refused, and clients fall back to TCP).
    - RTCP sender reports.
    - HTTP Digest authentication: the main account, plus `RTSP_LITE_USER`/`RTSP_LITE_PASS` as a second account.
  - **Fast start**: the frames since the last keyframe are kept (`RTSP_LITE_FASTSTART=1`). A new client gets a picture in about 1 s instead of waiting for the next keyframe.
  - **Slow clients**: a client that cannot keep up skips to the next keyframe. The others are not slowed down.
  - **Measured on a TC100** with Frigate as the only client:
    - the vendor server's RTSP thread went from 15.4 % to 1.8 % CPU, and the lite server uses 6–7 %;
    - 0 decode errors, 16 fps, 25 audio frames per second.
- **Two-way audio** (`RTSP_LITE_TALK=1`, lite server). A client that asks for the ONVIF backchannel gets a send-only audio track; go2rtc does this, so it works from the microphone button of Home Assistant and go2rtc.
  - The G.711 it sends is played on the speaker through `libplat_ao`, opened only while someone talks.
  - The volume is the push-to-talk volume, one talker at a time.
- **Motion zones** (Settings → Detection): up to 4 areas that the camera's own motion detection ignores (MQTT event, picture on motion).
  - The cells of the SoC detector grid (32×24) inside a zone get sensitivity 1, which the library treats as "never" (`src/tc100fix/md.c`).
  - The zones are applied when the detector starts or restarts. Frigate keeps its own zones.
- **Secondary stream on/off** in the same card (`RTSP_SUBSTREAM`).
- Home Assistant diagnostics:
  - *RTSP Clients* and *RTSP Skipped Frames* of the lite server;
  - *Last Restart Cause* (requested / unexpected);
  - *Unexpected Restarts (history)*;
  - an *Unexpected Restart* problem sensor, which turns on after a restart nobody asked for (hardware watchdog, power loss, crash). An automation can notify on it.
- **Snapshots without a helper program.** The video server already encodes one JPEG a second. libtc100fix now keeps the last one in `/tmp/snapshot.jpg`, and `currentpic.cgi` serves it directly while it is under 3 s old. The web page and Home Assistant get the picture at once, without starting `getimage` for each request. `getimage` remains the fallback.

### Changed
- **Clean microphone without sound detection.**
  - The vendor echo canceller and noise gate are now off whenever the sound is served, not only with sound detection. They cost about 4 % CPU and silenced everything below speech level.
  - `RTSP_AEC=1` keeps them.
- **Health snapshot every 5 minutes** instead of every minute (`HEALTH_SNAPSHOT_INTERVAL_SECONDS=300`). Each run probes about 15 services. The Diagnostics page and `health.cgi` follow the new cadence.
- **Less memory.** The reset button is watched by `tc100-button`, a small C program in the code zone (`src/button`). It is one blocked process instead of a shell loop with a `dd | od` pipeline, which held four processes and about 230 KB. The rules are the same, and `scripts/button-watch.sh` stays as the fallback.
- **Faster web requests.** `action.cgi` keeps its checks and helpers, and its 89 commands moved to `scripts/action.d/<group>.sh` (video, stream, audio, storage, detection, hardware, system, network, integrations, setup, logs). A request reads only its group's file: the shell parsed the whole 115 KB file on each request, about 0.3 s on the camera. The commands themselves are unchanged.
- **The camera's own motion detection is off by default** (`mdenabled=0` in `rtspserver.conf.dist`): Frigate does the detection. It saves the detector's work in the video process. Turn it on in Services when its MQTT events or pictures on motion are used. Cameras already set up keep their setting.
- `NR3D_STRENGTH` (test, `isp_tune.conf`): scales the 3D noise-reduction strengths, mapped on the camera's 112-byte sets. Not in the web page yet.

### Security
- **Local network only by default** (`NET_LAN_ONLY=1`). Connections from outside the private networks (10/8, 172.16/12, 192.168/16, link-local, 100.64/10 for Tailscale) are closed at once by the web server, telnet, FTP and both RTSP servers. A port forwarded by the router by mistake no longer reaches the password prompt.
  - The kernel has no packet filter, so the check is a small library on `accept()` (`src/netacl`): `lib/libnetacl.so` for lighttpd, telnetd and ftpd, and the same code is built into `libtc100fix` for the video process.
  - `NET_ALLOW_EXTRA` adds networks (a VPN).
  - An empty or unreadable list, or a missing library, means no filter. If lighttpd does not come up with the filter, it is started again without it.
- **RTSP**: the original server behind the lite one listens on 127.0.0.1 only (`RTSP_VENDOR_LOCAL=1`). The lite server refuses an address outside the local network for 15 min after 5 wrong passwords. The local network is never refused.
- **Telnet and FTP** started from the web page stop by themselves after 15 min (`REMOTE_SHELL_TIMEOUT_MIN`). FTP is no longer started at boot by default.
- **Emergency telnet (port 9527)**: only when the web interface is not up 2 min after a boot (`EMERGENCY_TELNET=auto`), instead of 60 s at every boot.

### Removed
- Features unused with Frigate, or that need internet, while the camera stays offline:
  - the old recorder (`controlscripts/recording`, `bin/ffmpeg-min-recorder`), replaced by the local backup recording;
  - timelapse;
  - motion mail and motion snapshots (`sendPictureMail.sh`, `motion-mail`, `motion-snapshot`);
  - ONVIF event push (`onvif-notify.sh`). The ONVIF service itself stays;
  - `audio_stream.cgi`, which did not work. The lite RTSP server carries the sound.

  Telegram stays in the code, off and hidden in flash mode.

### Fixed
- **SD card format interrupted by a restart.** A code update rebooted a camera while it was formatting its card: the new partition table was written, but there was no file system, and the card then only showed as "no readable file system".
  - Code updates are now refused while a format runs.
  - A format that did not finish is remembered (`/mnt/config/sd-format.pending`). The card is then shown as *formatting did not finish* and the question is asked again.
- The frame tap of the local recording and of the lite server could take the JPEG snapshot encoder for the main stream. Both encoders have the same size, and one JPEG a second ended up as broken video. Only frames with an H.264/H.265 start code are used now.

---

## [2.1.8] — 2026-10-18

### Added
- **SD card from flash** (`scripts/sd-card.sh`, checked every minute by `web-guard.sh`):
  - a card put in is recognised: firmware/install kit (boot files: never mounted, since the vendor boot would start from it), card with files, empty card, card without a readable file system, or card with errors;
  - a usable card (FAT32/exFAT, no boot files, no card errors in the kernel log) is mounted on `/mnt/sd` automatically (`SD_AUTOMOUNT=1`), ready for the local backup recording; a card taken out is released;
  - the web page asks once per card: **"SD card inserted: what do you want to do?"** — set up recording, format the card, or leave it as it is (the answer is kept per card in the persistent config);
  - **formatting from the camera**, only when it runs from flash (never the card it boots from): recording paused and card released, one FAT32 partition from 4 MB (erase-block aligned), label TC100, then mounted again. Refused for a card that reports errors. Runs in the background; the page follows it.
  - Settings → Recording shows the card and its state, with "Mount the card" and "Format or set up…".

---

## [2.1.7] — 2026-10-18

Flash space.

### Changed
- **Code zone 487 KB → about 405 KB of its 640 KB.** Packages and system images are now built from a shrunk copy of the code (`src/flash/minify.sh`, called by `stage-tc100.sh`): comments and indentation removed from the shell scripts and CGIs by `shfmt -mn` (a real shell parser, so here-documents and strings are untouched), web scripts and stylesheets minified by `esbuild` (checked with `node --check`). The repository stays the readable source; without the tools nothing changes; `MINIFY=0` turns it off.
- Shell scripts are only minified when the camera's own shell is available to check them (`CAMERA_SH`, the vendor busybox 1.24.1 ash run with qemu), and a file it refuses keeps its source. A first build checked with a newer busybox booted a test camera without network: the old ash misparsed the minified `autorun.sh` where its 8 KB read buffer ended inside `;then`. The camera rolled back to its built-in code by itself (no confirmation within 5 min), as designed. A test now parses every script with the vendor ash when `TC100_ROOTFS` points to an extracted rootfs.
- Removed from the camera: the icon font's `.eot`, `.ttf` and `.svg` copies (only the WOFF is used by current browsers) and the host-side Python helper that was copied with the scripts.

---

## [2.1.6] — 2026-10-18

Hardware features that cost no CPU.

### Added
- **Privacy masks** (Settings → Image): drag up to 4 rectangles on the camera picture. The ISP paints them (black, grey or white) before encoding, so they are gone from both streams, the snapshots, the recordings and what Frigate analyses, at no CPU cost (`ak_vpss_mask_set_area`, struct checked against the camera's library). Stored as `MASK1..MASK4=x1,y1,x2,y2` in percent in `isp_tune.conf`, set again if a day/night ISP reload drops them. Saving a mask switches live tuning on. Checked on a camera: the masked area is exactly where it was drawn on the 1080p snapshot. (The SDK's "mosaic" type left the area black, so it is not offered.)
- **Wi-Fi rescue access point from flash.** The flash `/usr` has no vendor `hostapd`, so the rescue access point (`WIFI_RESCUE`) could not start there. The code package now carries `hostapd-rtw`, built from Realtek's hostapd 0.8.x_rtw source for the RTL8188FU's `rtl871xdrv` interface (`src/hostapd`, WPA2-PSK only, no WPS/EAP/RADIUS, 190 KB). Checked on a camera: access point up in Master mode on `wlan1` while the station link kept working, then stopped.

### Fixed
- The rescue access point's DHCP server kept running after the access point stopped (busybox `udhcpd` did not write its pidfile): it now runs in the foreground of a background job whose PID is recorded.
- The image-tuning status of the web page and MQTT is removed when tuning is switched off, instead of showing the last values.

### Notes
- WDR (wide dynamic range) is already on: the sensor's ISP file runs it in gain-linked mode for 8 of its 9 gain levels (read on a camera; the status file now reports `WDR_MODE/WDR_MANUAL/WDR_LINK`). Nothing to switch on.
- Wi-Fi transmit power cannot be lowered at run time with this driver build (`tx_power_offset` and `tx_gain_offset` are accepted but change nothing measurable); a camera too close to its access point is better moved by a couple of metres.

---

## [2.1.5] — 2026-10-18

Reliability.

### Added
- **Network guard** (`scripts/net-guard.sh`, checked every minute by `web-guard.sh`): when the default gateway has not answered for `NET_GUARD_MIN` minutes (15) while the rest of the system runs, the camera reboots. The hardware watchdog does not catch that case (its feeder keeps running): a test camera stayed off the network for over 20 minutes until it was unplugged. If the reboot itself hangs, the watchdog feeder is stopped after 2 min so the hardware resets the camera. After such a reboot the next limit doubles (15 → 30 → 60 → 120 min) until the network has been back for 10 min, so a router switched off for the night costs a few reboots. Never while the Wi-Fi rescue access point is up. `NET_GUARD=0` turns it off.
- **Build identity in code packages**: the header now carries the build date and the git commit (`flash-code.sh info`). Settings → Firmware update shows them for the installed code and for an uploaded package, and warns when a package has the same version as the installed code but another build (an older file with the same name was nearly installed). Older packages and the `/usr` copy of `flash-code.sh` still read the new header.

### Fixed
- **Remote syslog got everything.** BusyBox `syslogd -R` sends every message to the remote host before its own filters (they only apply to the local file), so the remote server also received kernel and daemon info/debug lines, and bursts line by line. A small forwarder (`tc100-logfwd`, 10 KB, `src/logfwd`) now follows the filtered local log instead: notice and above plus logins; the same message (numbers ignored) at most once a minute with a "repeated N times" line after; at most 60 lines a minute. It ships in the code package; without it (older system image) the camera falls back to `syslogd -R`.

---

## [2.1.4] — 2026-10-18

### Fixed
- **Day/night flapping at dawn and dusk.** The infrared lights feed back into the light measure (IR on: bright enough for day; IR off: dark enough for night), so a camera switched 4 times in 50 s at dawn. Each switch drops frames (`ak_vi_get_frame … get frame failed`, kernel `>50, sjf`, `set td ok`), changes the whole picture (seen as motion by Frigate) and sent a burst of error lines to the remote syslog. The automatic switch now waits until the ISP has asked for the new mode for `RTSP_DAYNIGHT_HOLD_S` (10 s) and happens at most every `RTSP_DAYNIGHT_DWELL_S` (120 s); 0 = vendor behaviour. Simulated: 3 minutes of flapping → 3 switches instead of ~12; a 3-second flash at night no longer switches.

### Changed
- A code package can now update the RTSP server fixes (`libtc100fix.so` in the code zone, preferred by `rtsp-h26x` over the copy in `/usr`): no system package needed for them.

---

## [2.1.3] — 2026-10-17

### Changed
- **Vendor libraries log errors only** (`VENDOR_PRINT_LEVEL` now defaults to 1 instead of the vendor's 3). At 3 the encoder library writes every slow frame (`>>> encode frame type=0 … time=…ms`, `group_type=…`) at *emergency* priority: with remote syslog on, a NAS received bursts of "emergency" events and sent an alert for each. Checked on a camera: after a stream start only the vendor's error lines remain. Set 3 in boot.conf to get the vendor behaviour back.

---

## [2.1.2] — 2026-10-16

What the logs of two cameras showed over a day (details: docs/known-issues.md, "Reading the camera logs").

### Fixed
- **Time zone**: `timezone.conf` was read whole, comments included (a camera on the template got that as its `TZ`), and only the RTSP server used it, so kernel and vendor lines in one log were hours apart and cron ran on UTC. The first non-comment line is used, checked, and exported to every program from the start of `autorun.sh`; klogd is restarted with it so kernel lines carry the same clock. The template now shows POSIX strings (`CET-1CEST,M3.5.0,M10.5.0/3` for Paris; `UTC+1` meant one hour *behind* UTC).
- False boot warnings from flash: "/mnt has less than 4 MB free", "Self-heal skipped: missing libcurl", "lighttpd.conf rejected by lighttpd".

### Changed
- **Logs page**: syslog lines are classed by the priority they carry, and the vendor drivers' start-up chatter (sensor register dump at "err", encoder start at "emerg", Wi-Fi driver banner, cloud command server not found…) shows as "Vendor" instead of errors: 31–37 "errors" per boot → 0 on a healthy camera, while SD card timeouts and other real faults stay errors.
- **Reboot history**: each heartbeat records the SD card state; an unexpected restart after card errors says "SD card errors (N kernel errors): likely cause". Heartbeat every 5 minutes from flash (15 on an SD card).
- Settings → Network: the time zone field explains the POSIX format.

---

## [2.1.1] — 2026-10-16

### Changed
- **Lighter web requests.** `state.cgi?cmd=statusline` (polled by every open page) runs without subshells on its usual path: about half the time per request on the camera (0.94 → 0.50 s). `func.cgi`, sourced by every CGI, no longer runs `timeout` at each request (the probe is kept in `/tmp` once per boot) and only url-decodes values that need it.
- **HTTPS from flash prefers ChaCha20-Poly1305** (the AK3918 has no AES instructions): serving a page costs about 55 % less CPU and is about twice as fast. Clients that only offer AES-GCM still get it. The certificate was already ECDSA P-256.
- Diagnostics, Logs, Services, Config editor and Recordings get the same page title as the rest; the log tabs are one segmented control; the recordings player follows the dark theme.
- Settings: the page title shows the open section; the search also finds the Wi-Fi and backup cards (loaded on the first search).
- A web code or system update now records its restart as planned in the reboot history, instead of "UNEXPECTED".

---

## [2.1.0] — 2026-10-16

### Changed
- **New web interface layout, after the OpenIPC web interface.** Top bar with the camera name and firmware version, and Dashboard, Live, Recordings, Camera ▾, Services ▾, System ▾. Dark theme by default (light still one click away), one indigo accent.
- **Settings**: a sidebar grouped by use (Image, Video & audio, Events, Network & integrations, System) with a search box that shows every matching card across sections. On a phone it becomes a row of chips. Each section also opens straight from the menus.
- Dashboard and Live switch instantly: the home page is kept aside while other pages are open, not downloaded again.

### Added
- **Dashboard**: CPU, memory, Wi-Fi signal, network out and uptime tiles with small graphs; network in/out and CPU/memory graphs over the last 5 minutes; snapshot, streams, device and storage cards. The graphs are kept in the browser only, and are fed by `dash.cgi` (raw counters from `/proc`, a separate tiny CGI, shell built-ins only, every 5 s while the dashboard is on screen) and `cmd=dashinfo` (once a minute).

---

## [2.0.1] — 2026-10-16

### Added
- **System update from the web page, without SD card or telnet** (flash mode): Settings → Update & backup accepts `tc100-system-<version>.tar` (made by `src/flash/build-flash-kit.sh` next to the install kit). It is unpacked in RAM (the video is paused), checked (same original `/usr`, image md5, squashfs with the files a boot needs, valid code package), then `scripts/usr-update.sh` runs from RAM with the rootfs shell only: it replaces the watchdog feeder, stops every program running from `/usr` (Wi-Fi included), writes `/usr` and reads it back (up to 5 times), writes the code zone, sets up a one-shot boot from flash when an SD card with the firmware hook is in the slot, and reboots. Nothing is written if a program cannot be stopped.
- **SD card health** (`scripts/sd-health.sh`): kernel card/file-system errors, read-only remount, and a write/read-back test after each boot and daily. Shown under the live view ("failing: replace it", "read-only", "errors"), in Home Assistant ("SD Card Problem" now also covers garbled writes, new "SD Card State"), and logged as an event.
- **Rescue access** (`scripts/web-guard.sh`, SD card and flash): when no web port answers, the web server is restarted once, then a rescue telnet opens on port 23; it is closed again once the web interface has been back for two minutes (a telnet started from Services is left alone). An HTTPS → HTTP fallback is shown as an "HTTP" badge in the top bar.

### Changed
- The update work directory on the card is `tc100-update/` instead of `update/`, a name the vendor `service.sh` reserves for reflashing the camera from the card (`update_check.sh`, when `wifitest/` is absent). An existing `update/` holding only our state files is moved at boot.
- The install to flash records the fingerprint of the original `/usr` in the settings partition, so system packages can be matched to it.

---

## [2.0.0] — 2026-10-16

The firmware runs from the camera's flash memory: the SD card becomes optional.

### Added
- **Install to flash from the SD card** (README "Step 3"), in three steps through a `tc100-flash/` folder on the card: the camera copies its original `/usr` to the card (`scripts/flash-install.sh prepare`, read-only for the flash); a computer turns it into `usr.img` + `code.bin` (`src/flash/build-flash-kit.sh`, Linux / macOS / WSL, prebuilt stripped binaries in `src/flash/prebuilt/` so no cross toolchain is needed); the camera installs both at boot before any video service runs, copies the settings, Wi-Fi and an ECDSA certificate into jffs2, reads everything back and does one test boot from flash with the card still in. Every check (partition table, kernel size, empty code area, fingerprint of the original `/usr`, image md5, no process using `/usr`, room in jffs2) refuses without writing anything and reports in `tc100-flash/STATUS.txt`. Also from Settings → Update & backup → *Install to flash* and from the wizard.
- **Setup wizard** rewritten: language and Wi-Fi (kept network as fallback), profile, web access, Frigate and MQTT with Frigate's address, recording on the card, install to flash; all answers validated before anything is written; `wizard.cgi?info`.
- Settings → System → **Password**: one password for web, RTSP, FTP and telnet; characters the writers cannot carry are refused.
- **ONVIF back in the flash image** (`monvifd`, about 94 KB; 312 KB still free in `/usr`). Off by default, started from Tools → Services; the install to flash keeps it on when it was on the SD card. Its health check tries plain HTTP first (the flash curl has no TLS).
- Local recording on **exFAT** cards from flash (`rec-storage.sh`).
- Release: CI also attaches the SD card zip (`tc100-sd-<version>.zip`). Screenshot tool `src/webui/screenshots/shots.py` (canned answers, test pattern) and `docs/screenshots/`.
- README rewritten for 2.0 (possibilities, step-by-step guides, hardware, OpenIPC references); platform notes and the bring-up bug table moved to `docs/known-issues.md`.

### Changed
- Settings → Network Wi-Fi goes through `wifi-txt.sh` like `wifi.txt`: the new network first, the previous ones kept as fallbacks (a wrong password no longer takes the camera off the network).
- `flash-usr.sh` and `flashmode-once.sh` moved from `src/flash/` to `scripts/` (they run on the camera and ship with it).
- `src/flash/stage-tc100.sh`, `build-usr.sh` and `build-code.sh` work on a user's computer (no git checkout or root needed, macOS `md5`).

### Fixed
- Form drafts kept in the browser (`localStorage`, up to 60 min) included password fields (Wi-Fi, Telegram token). Password fields are no longer stored.
- Example addresses and camera names from the test setup were replaced by neutral ones in the documentation and UI placeholders.

---

## [1.8.4] — 2026-10-12

### Added
- `wifi.txt` at the root of the SD card (`SSID=` / `PASSWORD=`): Wi-Fi settings applied at boot by `scripts/wifi-txt.sh` (flashboot.sh from flash — kept in jffs2 —, autorun.sh from the card), password removed from the card afterwards, previous networks (or the vendor `anyka_cfg.ini` network) kept as lower-priority fallbacks. Settings → Wi-Fi from flash now writes `/etc/jffs2/tc100/wpa_supplicant.conf` (it wrote to RAM and was lost at reboot).
- Rescue access point (`scripts/wifi-rescue.sh`) on hold: the vendor hostapd authenticates phones but no data reaches them on this driver, even with the station stopped.
- Local backup recording (`REC_LOCAL=1`, `REC_SEGMENT_SEC`, `REC_RESERVE_MB`, `REC_STREAM`): `src/tc100fix/rec.c` hooks `ak_venc_open` / `ak_venc_request_stream` / `ak_venc_get_stream_ex` in the vendor RTSP server, queues each encoded frame (never blocking the encoder thread: frames are dropped and recording resumes at the next keyframe when the card is too slow) and a low-priority thread writes fragmented MP4 (H.264 `avc1` / H.265 `hvc1`, one fragment a second, new file at the first keyframe after `REC_SEGMENT_SEC` or when the parameter sets change). Refuses RAM and flash filesystems. `scripts/rec-storage.sh` (dir / eject / resume / status). Verified on camera 2: 1080p H.265 and 640×360 H.264 files decode cleanly with ffmpeg, 0 dropped frames; CPU cost measured per thread (writer, mmcqd, writeback): ~4.5 % main stream, ~0.8 % sub-stream.
- Local recording only while the recorder is away (`REC_WHEN=offline`, default): the writer checks `/proc/net/tcp` every 2 s for an established RTSP connection from the recorder (`REC_CLIENT`, by default the host of the Frigate URL) whose data flows (send queue < 256 KB, no retransmission timeout — a client lost on the network stays "established" for minutes); in standby nothing is processed or written: the frame queue (1 MB, ~5 s) is trimmed by whole GOPs and becomes the pre-roll; recording starts `REC_OFFLINE_SEC` (5) after the stream stops flowing and ends `REC_POSTROLL_SEC` after it is back.
- Flash `/usr` replacement, written from Linux without opening the camera (README "Install to flash"): `src/flash/build-usr.sh` (vendor `/usr` minus the cloud app, SD card keeps priority in `service.sh`, `/usr/tc100` HTTP-only binaries, size check) and `scripts/flash-usr.sh` (partition check, write, read-back through `/dev/mtd6`). HTTP-only builds: `src/curl/build.sh` (HTTP/MQTT/RTSP) and `NO_TLS=1 src/lighttpd/build.sh`. camera 2 runs from it since 2026-10-15.
- `src/release/build-sd.sh` builds the content of a new SD card (`dist/tc100-sd-<version>/`, and a zip), with `SD-CARD.txt` (formatting, bringing the settings over) and checks that no reflash file name or live configuration ends up on it. The boot hook `wifitest/wifi_test.sh` (the vendor `service.sh` sees `/mnt/wifitest`, skips the cloud app and runs it; it starts `autorun.sh`) was only on the cameras' cards and is now in the repository: a card made from git alone did not boot the firmware.

### Fixed
- The camera contacted GitHub (`api.github.com`) at every boot to check for a new release, although it is meant to stay off the internet. The check now only runs with `UPDATE_CHECK=1` in boot.conf (default 0); updates are installed from Settings → Firmware update.
- Settings → Firmware update showed nothing on a camera whose update log held control characters (file names made of random bytes from the 2026-10-13 FAT incident): `update.cgi?cmd=status` returned invalid JSON. They are replaced in the log excerpt.
- **Settings: sound detection showed "off" (interval 5 s) on frigate_ha cameras where it was on.** state.cgi fullconfig did not read sound_detection.conf in that profile, even though detection runs in every profile since 1.8.4.
- **Settings: the Telegram card was squeezed into one row.** The show/hide password button set `display:flex` on the field's parent. The field now gets its own wrapper, and the 👁/🙈 emojis became "Show"/"Hide".
- Sound detection never worked on this camera: it read `/dev/voice` / `/dev/dsp`, which do not exist on the AK3918 (the microphone is `/dev/akpcm_cdev0` behind the vendor `ak_ai` library), treated 16-bit PCM as 8-bit, and without a device fell back to a "shim mode" that reported a level above the threshold — enabling it would have published a fake "sound" event every poll. Replaced by a level meter in `libtc100fix.so` (`TC100FIX_SOUND_LEVEL`): it sees the raw PCM the vendor audio encoder reads (`ak_ai_get_frame`), computes RMS/peak in dBFS once a second and counts the seconds at or above `THRESHOLD_DB` (new key, default -30 dBFS; `THRESHOLD` is legacy), so the daemon polls a tmpfs file every `INTERVAL` s (default 2, the forced 10 s minimum is gone) and misses nothing. rtsp-h26x serves audio while sound detection is enabled (v4l2rtspserver only opens the audio encoder for served audio, so the meter needs it even if `RTSP_AUDIO=0`) and turns off the vendor echo canceller and noise reduction for it (`TC100FIX_AEC_OFF`): measured on hardware, with them on the microphone delivered digital silence (stream flat at the A-law floor, -72 dBFS, on both cameras) because the noise gate removes everything below speech; with them off the ADC carries a DC offset of ~-1450/32768 (-27 dBFS on its own), removed in place before the encoder by a one-pole DC blocker (`TC100FIX_DC_BLOCK`) — stream DC offset -0.045 → -0.003, ambient room level -43 dBFS measured identically by the meter and by ffmpeg on the RTSP audio. The meter also measures around the window mean. Switching sound detection restarts RTSP. The daemon no longer is skipped under `frigate_ha` (it is cheap now) but only starts when enabled. Events carry `level_db` / `threshold_db`.
- Settings → Motion & Sound: the save handler read `motionBlink`, a field the form never sent (the LED switch was ignored), and dropped the sound threshold. It now reads the form's fields (sanitised), and the card has a sound detection switch and a threshold in dBFS.
- FTP / Telnet showed "running" with their port closed and refused to start ("already running"): `status` trusted any live PID from the pidfile, and `ftp-server` wrote every PID matching `ftpd` (session children included). `status` now also requires the right process and a listening port (`port_listening`, from `/proc/net/tcp`) and removes a stale pidfile; `ftp-server` records `$!` (tcpsvd itself). The Services page fast path checks the port too. Verified on hardware: after `kill -9` of tcpsvd the service reads "stopped" and starts again.
- Frigate/go2rtc lost the camera 30–50 times an hour ("dial tcp …:554: i/o timeout", mostly on the sub-stream) while ping and already-open streams kept working. `00_system-config` enabled `tcp_tw_recycle`, which makes the kernel silently drop a SYN whose TCP timestamp is older than the last one seen from the same IP — the normal case for clients behind NAT or with per-connection timestamp offsets (go2rtc in Docker). Measured on hardware: `PAWSPassive` grew by ~22 per minute; after setting `tcp_tw_recycle=0` it stopped growing and go2rtc logged no error for the camera. The boot script now sets `tcp_tw_recycle=0` and `tcp_tw_reuse=1` (quick restarts still work: it only affects outgoing connections); a test forbids turning recycle back on.
- Logs page showed `{"ok":false,"error":"CSRF token missing or invalid…"}` instead of the logs: `logs.html` posted to `action.cgi` without the CSRF header, which every POST requires. It now sends the token.
- Settings → Config Profiles: "Failed to refresh preset list" on every visit and presets that could not be loaded — the page asked `list_presets` / `load_preset` without `format=json` and got plain text. Verified on hardware: save → list → load → delete round trip.
- Network page: "Primary IP" and "Default gateway" were `n/a`. The firmware's `timeout` shim (`busybox timeout`) could not find bare command names ("can't execute 'ifconfig'"), so `ifconfig`/`route` never ran; the shim now resolves the path first (`func.cgi`, `common_functions.sh`). Routes are read with `route -n` (the gateway had shown as "lan.home"), `ip route` "default via" is parsed, and ONVIF/FTP/Telnet ports are "expected" only when the service starts at boot.
- Logout did nothing (`action.cgi` has no `logout` command; HTTP Basic auth cannot be ended server-side). The button now replaces the browser's cached credentials and reloads to the login prompt.
- Device Info: binary versions showed printf placeholders (`curl 8.1.2 (…) %s`, `%s version 2.1.3`); "Release" showed only the vendor flash version — the SD firmware version is now listed first.
- Disk page: the summary showed "Root usage: 100 %" — the read-only squashfs root, full by design. It now shows SD card usage.
- System Usage → Service Health listed the boot hooks `00_system-config`, `01_system-emergency-telnet`, `02_system-webserver` as permanently "absent".
- Services: memory-guard and cpu-scaler (started at boot, off until enabled in `boot.conf`) now report "Disabled" (status exit code 3) instead of needing attention; Settings can still enable them without touching autostart.
- Dark theme: the logs table header was a blank light bar (light text on a light background); other light-only panels got dark counterparts.
- Services → View opened a new browser tab with an unescaped `<pre>` (a script containing `<` rendered as markup). It now opens the source in a dialog (Copy, Esc / click outside to close; Ctrl/⌘-click still opens a tab), served as plain text by `scripts.cgi?cmd=source`; the full-page view escapes the source.
- Services page: every row stayed on "Loading…" with "Service status is unavailable". The page polls `scripts.cgi?cmd=allstates` without a script name, but `allstates` was only handled inside the per-script branch, so the request got the HTML listing and the JSON parse failed. It is now answered first. A status exit code of 1 now means "stopped" instead of "error" (onvif, timelapse, sound-detection return 1 when not running); `web-server` finds lighttpd by process (its config writes no pidfile, so a running server showed as failed); `telegram-bot` and `network-monitor` no longer print their "configure first" message on `status` (read as "running"); `syslog-forward status` returns 1 when stopped. The summary counts only real problems (failures and services set to start at boot that are not running). Dark theme: the services table had a light background behind light text. Verified on hardware: 8 running · 17 stopped · 2 need attention (memory-guard and cpu-scaler start at boot but are disabled in `boot.conf`).
- Settings → Dashboard: the Wi-Fi gauge was never filled — the page read `wifi_qual` but `statusline` did not send it. `statusline` now reports `wifi_qual` (link quality 0–100 from `/proc/net/wireless`, shell only) and `wifi_iface`. The "Gateway" field showed `0.0.0.0` from a config key nothing writes; it now shows the live default route. Verified on hardware: Wi-Fi 85–93 %, gateway 192.168.1.1.
- The web server could not start from a fresh install: `lighttpd.conf.dist` loaded `mod_setenv`, which the bundled lighttpd 1.4.69 (static build) does not include ("mod_setenv plugin not found", lighttpd exits). Its `mod_deflate` is missing as well (keys silently ignored), so the gzip and cache/security-header blocks never worked. They were removed from the templates; the rebuilt binary (see *Changed*) brings them back through a migrated block, and a test pins every module the templates load to `src/lighttpd/plugin-static.h`.
- Restarting the web server (web UI service toggle, `memory-guard`, Let's Encrypt renewal) left the camera without a web UI until the next reboot: `http_server` started lighttpd without `LD_LIBRARY_PATH`, and it exits at once ("can't load library 'libpcre2-8.so.0'"). It now starts it like `02_system-webserver`, and honours `WEB_MODE=http`. Verified on hardware.
- Sensor frame rate no longer drops from 25 to ~10 fps in low light (and back), which made the RTSP frame rate oscillate under Frigate. The vendor `libplat_vi.so` (V1.0.04) arms an automatic switch thread from `ak_vi_set_channel_attr()`; `v4l2rtspserver` never disabled it. `RTSP_FPS_LOCK=1` now disables it at run time (see `libtc100fix.so` below). Night test on hardware (IR on, 2026-10-13): the switch is disabled (`rc=0`, sensor kept at 25), but the main stream (configured 12 fps) delivers 10.1 fps in night mode with the lock on *and* off, and with the AE exposure cap at 50 % and 15 %; frame intervals are 93–106 ms rather than multiples of the 40 ms sensor period, so night mode is limited by something else in the capture/ISP path. The default stays `RTSP_FPS_LOCK=0`.
- Restarting the RTSP service could leave it down: with the previous server's client sockets still closing on port 554, the new server exited at once with a misleading "Address family not supported by protocol" and stayed down until the watchdog's next pass (~1 min). `rtsp-h26x` now waits for the port to drain (max 45 s) and retries up to 3 times if the server dies right after start. Reproduced and verified on hardware.
- With `RTSP_AUDIO=0` the server still opened the microphone and ran the echo canceller and noise reduction (`aec_task` + `ai_capture` ≈ 6.4 % CPU measured over 30 s). `RTSP_MIC_OFF_WHEN_NO_AUDIO=1` skips them; both threads disappear on hardware.
- Starting a service from the web UI no longer hangs: `scripts.cgi` captured the start output through `$(...)`, and services that background a daemon (`ftp-server`'s `tcpsvd`, the service watchdogs) inherited that pipe, so the request never completed although the service had started. Output now goes through a temp file with stdin from `/dev/null`. Verified on hardware (start returns in ~1.6 s).

### Changed
- **Settings regrouped into six tabs**: Image & video (streams, day/night, on-screen text, image tuning), Sound & detection (microphone, motion/sound detection, timelapse), Integrations (MQTT/HA and its status, Frigate live view, RTSP addresses, Telegram, syslog), Network (Wi-Fi, IP/DHCP, DNS, Wi-Fi scan, name, time), System (performance and security, LEDs, maintenance, setup wizard, firmware update) and Backup (restore point, presets, export/import, full backup and JSON exchange, with a short guide to which one to use). The Settings "Dashboard" tab, a duplicate of the main screen, is gone; its warnings stay above the tabs. **Tools** now holds one **Diagnostics** page (system usage, device, storage, network state, each loaded when its tab is opened), Logs and, under Advanced, the config editor; Network & DNS and Backup & Restore moved into Settings. `network.cgi?part=settings|diag` serves either half (the settings half skips the netstat/route probes). The "Retry" button of a page that failed to load called an undefined function; fixed. The Wi-Fi scan is part of the Settings Wi-Fi card (a click on a network fills in its name); the scan output now HTML-escapes SSIDs, which come from any neighbour.
- **Web UI, continued:**
  - Settings tabs are underlined and scroll horizontally on a phone. Checkboxes are switches. Card headers are compact. Sliders and code use the ink colour; info and danger banners are outlined.
  - Card titles are in plain English: the French/English mix is gone, and so are "Elite … Mastery/Studio".
  - System Usage reads like a summary: up time, load, CPU busy since boot, memory in MB with the available share. The process list is collapsed, and "absent" boot entries are no longer listed as services.
- **Web UI, "control monitor" style (css/ui-v2.css, loaded after ui-modern):**
  - the live image is the centrepiece, with its status overlaid in the picture (state, time, camera name, profile, light level);
  - one line of readings sits under the picture: CPU, memory, Wi-Fi, SD card, MQTT;
  - visual hierarchy: one dark primary action; Push-to-talk ("Talk") is no longer an alarm-red button; flat background without halos; underlined active menu item;
  - Services is a list with a state dot, a "Boot" switch and a plain Start/Stop button. On a phone the button used to be off-screen;
  - Device Info and System Usage no longer overflow the screen on a phone (they were 714 px and 1036 px wide on a 390 px screen).
- **Firmware updates extract only the files that differ from the installed ones.** The whole package used to be written to the SD card. Measured on a TC100: 12 files extracted instead of 179, and upload + verification took 68 s instead of 132 s.
- **Day/night thread polls every 500 ms instead of 100 ms** (`RTSP_DAYNIGHT_POLL_MS`, applied by libtc100fix to that single `ak_sleep_ms` call site, identified by its return address in the bundled binary). Measured on a TC100 at night: the thread wakes up 2×/s, v4l2rtspserver goes from 30 % to 28 % CPU.
- **Sound detection:** the default threshold moves to -24 dBFS. At -30, an evening at home gave ~170 events an hour, 70 % of them within 3 dB of the threshold. New `MIN_LOUD_SECONDS` setting: publish only once a burst has lasted that long (default 1).
- **MQTT: publishes reuse the persistent connection.** Each message used to open its own TCP connection, with CONNECT, a 1 s wait and DISCONNECT. That made ~1,100 connections in 4 h on a camera with sound detection. Now the packet is written in one go into the listener's connection, once its handshake is written and the broker has accepted it; otherwise it falls back to the old path. Measured on a TC100:
  - 5 publishes: 0 new connections, all received by a subscriber;
  - bridge startup: 13 s instead of 44 s, because the listener now starts before the ~40 Home Assistant discovery messages;
  - discovery payloads: all valid JSON on the broker.
- **Main-stream audio defaults to G.711 A-law instead of AAC** (new installs; settings page labels the cost). Measured on a TC100 at 1080p: v4l2rtspserver 36 % → 28-29 % CPU, idle 52 % → 55-60 %. Frigate's `preset-record-generic-audio-aac` re-encodes recordings to AAC anyway (checked: copy video + AAC audio from the G.711 stream).
- **SD card wear: routine logs stay in RAM.** Measured on a TC100: a cron heartbeat file rewritten every minute (temp file + rename), a stability sample appended every 5 minutes, one sound-detection log line per event (hundreds an evening) and the RTSP server's output all went to the SD card. Now:
  - the sound-detection and RTSP server logs live in /tmp/log, bounded;
  - stability samples are batched in RAM and appended once an hour;
  - the heartbeat is overwritten in place (64 bytes, no new cluster or directory entry) every 15 minutes;
  - /mnt is remounted noatime.
- **System log:** notice and above plus logins, in at most 256 KB of RAM. It used to keep everything, in up to 800 KB; three quarters of it was a USB host controller info line every ~15 s and crond's per-job lines. Remote forwarding sends the same filtered stream and keeps logging locally; stopping the syslog-forward service used to leave the camera with no syslogd at all.
- **Critical lines survive reboots:** every 5 minutes, new warning-or-worse lines about storage, memory, kernel faults and our own `tc100_log_event` failures (RTSP start failure, GOP stall) are appended to /mnt/log/important.log. Nothing is written when nothing happened.
- **System usage page:** one load-average line. The `uptime` output printed it a second time.
- Hardware watchdog: fed every second with an 8 s timeout (the AK39 driver maximum) instead of every 2 s / 5 s, at nice -15 so a loaded system does not starve it. Suspected cause of an unexplained reboot under load. Verified on hardware (`watchdog -t 1 -T 8`, nice -15).
- `vm.min_free_kbytes` 1024 → 2048 at boot: free RAM hovered at 1.5–2 MB, fragmented, and the RTL8188FU driver drops what it cannot buffer.
- The RTSP password no longer shows in `ps` / `/proc/<pid>/cmdline`: `libtc100fix.so` (`TC100FIX_HIDE_CREDENTIALS`, set by rtsp-h26x whenever credentials are passed) overwrites the `-U` argument once v4l2rtspserver has copied it; the start line in the RTSP log is masked too. Verified on hardware (`-U *********`, clients still authenticate).
- The Services page cache is built in the background 45 s after boot (first visit took ~9 s, now ~0.3 s).
- Main stream default 1920×1080 (sensor resolution; was 1280×720), 1.6 Mbit/s target. Tested on hardware at 12 fps: 1.5 Mbit/s, 3 MB RAM free, CPU ~29 %, Frigate unaffected. Second camera at 16 fps: 15.6 fps, 1.6 Mbit/s, keyframes ~220 KB. The sub-stream codec makes no measurable difference to Frigate (same camera, 640×360, H.265 vs H.264: decoder ~6.8 % CPU both ways); the template keeps H.264 for browser playback. Existing cameras keep their own `rtspserver.conf`.
- Web server: `bin/lighttpd` rebuilt (same 1.4.69, `src/lighttpd/build.sh`, Anyka toolchain). The previous binary had `mod_setenv`, `mod_expire` and `mod_deflate` compiled but not registered, and no zlib. The new one registers them (plus `mod_access`, `mod_accesslog`), links zlib statically and OpenSSL/PCRE2 against the libraries already in `lib/`; 428 KB stripped (old 654 KB with debug info). A new `# @migrate webperf` block in the lighttpd templates enables, for existing cameras too (added only once `lighttpd -tt` accepts it, i.e. with the new binary):
  - gzip of static CSS/JS/HTML, compressed once per file and kept in `/tmp/lighttpd-deflate` (84 KB of tmpfs); CGI output is never compressed. A first page load drops from 281 KB to 51 KB (Bulma 123 → 16 KB, `index.bundle.min.js` 93 → 21 KB).
  - versioned assets (`?v=1.8.4`) cached 30 days by the browser: a reload sends no request for them (checked in Chrome: transfer 0 B). Bulma's link is now versioned too.
  - `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: same-origin` on every response.
  Measured on the camera (lighttpd CPU, 7 assets per load): first load after boot 0.42 s (compression), each later full load 0.14 s instead of 0.28 s with the old binary (fewer bytes to encrypt). Memory footprint unchanged (VSZ 6.2 MB vs 6.3 MB). With the 1.8.3 binary still in place the block is refused and logged, and the web server keeps its current config.
- Services page: `allstates` answers in ~1 s instead of 5–12 s (measured on the camera, CLI 5.3 s → 1.0 s). Services whose status is "PID in the pidfile is alive" are read from the pidfile and `/proc`; the LED / IR / night / motion / auto-night / web-server toggles are computed from the same files their `status()` reads; script capabilities are cached in `/tmp` until a controlscript changes. No script is started per poll any more (each start cost ~0.2 s). States verified identical to the probe-based version on hardware.
- `RTSP_MIC_OFF_WHEN_NO_AUDIO` defaults to 1: with `RTSP_AUDIO=0` the vendor server no longer runs the microphone, echo canceller and noise reduction (~6.5 % CPU). No effect when audio is served; set 0 to restore the vendor behaviour.
- Version 1.8.4: `VERSION`, asset cache keys (`?v=1.8.4`), README; the boot log printed a hard-coded "Version: 1.0.0" and now reads `/mnt/VERSION`.
- Motion detection monitor polls every 10 s (12 s after a detection), the values the camera had been tuned to, instead of 20/20 s.
- Removed dead code: the lazy loader for `bulma-switch`/`bulma-badge`/`bulma-divider` (only triggered by a `status.cgi` page that no longer exists, so they were never applied) and the three stylesheets.
- The web UI loads a purged Bulma: 677 KB → 123 KB uncompressed (16 KB gzipped with the rebuilt lighttpd); measured on the camera 0.9 s → 0.2 s for the stylesheet. Rendering checked identical against the full Bulma on 84 screenshots (every page and Settings tab, light/dark, desktop/mobile, real CGI output from the camera); only the "Updated" clock differs.
- Push-to-talk is confirmed working on hardware: README *Known issues* and `docs/api.md` (`upload_audio.cgi`, `get_ptt_status`) now describe the patched `/mnt/bin/ak_ao_ptt` player, the RTSP pause during playback, CSRF on uploads and the `READ_FAILED` / `AUDIO_DEVICE_BUSY` responses.

### Added
- **Optional wpa_supplicant 2.11** (`WIFI_CLIENT=new` in boot.conf, default `vendor`). The vendor Wi-Fi client is Realtek's patched 0.8.x from 2013, older than the KRACK fixes. `bin/wpa_supplicant` is 2.11 built for the RTL8188FU's wireless extensions with internal crypto, no WPS/EAP (`src/wpa_supplicant/build.sh`, reproducible, sha256-checked source). `scripts/wifi-client.sh` starts it in place of the vendor daemon (the vendor configuration's WPS keys, which 2.11 would reject, are filtered out; the vendor connect script adds the network as usual) and falls back to the vendor client, with an important event, if it has not associated within 60 s. Tested on hardware (.24): associated in 4 s, WPA2-PSK/CCMP, 0.7 MB RSS.
- **French / English interface** (`scripts/i18n.js`, `i18n/fr.js`). A FR/EN switch in the top bar; the choice is kept per browser and defaults to the browser language. Pages stay written in English; in French a dictionary (~600 strings, 12 KB compressed, cached 30 days) is loaded once and visible text, placeholders, tooltips and confirmation messages are translated, including what the scripts load or update later (MutationObserver) and the few messages built with numbers (rules). In English nothing extra runs. `src/webui/i18n-strings.py --missing` lists untranslated strings; a test keeps it empty.
- **Smooth live view through Frigate.** Settings → Automation → Frigate live view: enter Frigate's address (e.g. `http://192.168.1.20:5000`); the camera's name in Frigate is found from Frigate's configuration (input or go2rtc stream with this camera's IP; one request, only when saving). A "Smooth live" button under the picture then opens the camera in Frigate's live page (go2rtc restream, full frame rate and sound) in its own tab: Frigate is plain HTTP and the camera UI HTTPS, so it cannot be embedded (mixed content), and relaying the video through the camera would cost it CPU. Frigate already pulls the stream through go2rtc, so viewing adds no connection to the camera.
- **Remote syslog ready for a NAS.** The Settings card explains the Synology Log Center setup (BSD, UDP 514) and the host is validated (host name or IP only: boot.conf is sourced by the shell, a crafted value could run commands at boot); enabling without an address is refused with a message. Verified on hardware with a UDP listener: notice-level messages, logins and `tc100-event` lines arrive with their priority (~13 lines/min at rest; the remote also receives info-level kernel lines, which busybox syslogd cannot filter per destination).
- **Read-only firmware image** (`firmware.sqfs`, `scripts/rofs.sh`). The code directories (`bin lib scripts controlscripts www`) run from one squashfs file, loop-mounted read-only at boot and bind-mounted over the FAT copies, so a FAT corruption caused by the logs/recordings written all day can no longer damage the code (the 2026-10-13 incident). The FAT copies stay underneath as the fallback, used when the image is missing, its `VERSION` differs from the card's, the mount or a smoke test fails, `FIRMWARE_IMAGE=0` (boot.conf) or `RECOVERY` mode. Its md5 is checked once, niced, 5 min after boot; a corrupt image is renamed `.bad` and logged as an important event. Updates keep both up to date: files go to the FAT copies through an overlay-free view of the card (`/tmp/rofs/fat`), the image is written as `firmware.sqfs.new` and swapped in at the next boot (the previous one stays as `.old`, which a rollback puts back). `src/release/build-image.sh` builds it reproducibly (gzip, 32 KiB blocks, FAT-like 0755 modes); `build-update.sh` ships it. The patched PTT player is built into RAM (`/tmp/bin`) when `/mnt/bin` is read-only. An image file on the existing partition rather than a second partition: the cards have one. Measured on hardware: reading every code file takes 8.8 s from the image vs 6.4 s from exFAT (xz: 14.5 s, lzo unsupported by the kernel); CPU and free memory unchanged in steady state.
- **Home Assistant diagnostics** in `<root>/health` (`diag`) with discovery entities:
  - Wi-Fi signal (dBm), Wi-Fi dropped packets, refused connections (PAWSPassive);
  - available memory, sound level (dBFS), light level, night mode;
  - "SD card problem" binary sensor (card read-only, or FAT/MMC errors in the kernel log).
  - Checked on hardware: 8 entities on the broker, values in the real health message.
- **`TAMPER_DETECTION=1`: ISP sharpness and histogram statistics** sampled every 2 s into /var/run/od by libtc100fix (`ak_vpss_od_get`), as groundwork for a lens-covered alert. On the camera's library, histogram bin 255 holds an aggregate and is ignored.
- **ISP tuning: `NR3D=0` turns the temporal (3D) noise reduction off** live; removing the line restores the ISP file's setting. Measured on a TC100 in low indoor light at 1080p: the frame rate stays at ~10 fps (the 3D NR is not what caps it), and the bitrate rises by 39 %. So the default stays on.
- Settings → System → **Firmware update**: upload a package built by `src/release/build-update.sh` (`dist/tc100-update-<version>.tar`, payload + `MANIFEST` of md5 sums). `update.cgi` streams it to the SD card (lighttpd `server.stream-request-body`, new `# @migrate updatestream` block, so the upload never sits in RAM); `scripts/fw-update.sh` checks every file's md5, shell syntax and paths, then installs only changed files by rename (safe for running binaries and scripts), keeps the replaced ones under `/mnt/backup/update-<date>`, runs config-migrate, checks the web server config with the new lighttpd (rolls back by itself if it fails) and reboots. One click rolls back. Start-at-boot toggles and `wpa_supplicant.conf.dist` are never overwritten. Every write is re-read and retried: on hardware one extraction came out with 8.7 KB of zeros at the 128 KiB boundary of a 428 KB file (memory pressure, not reproducible) and was caught by the check. Validated on the camera end to end: upload 16 MB (~100 s over HTTPS), verify, install + reboot, rollback + reboot, reinstall.
- Reboot tracking (`scripts/reboot-tracker.sh`): every deliberate reboot (web UI, MQTT, network-monitor, service-watchdog, schedule, firmware update) records why; a heartbeat (cron, once a minute) records the last time seen alive; at boot the previous run is classified and Device Info shows "Previous run ended: …" (history in `/mnt/log/reboot-history.log`). A run that ended with no recorded reason was a hardware-watchdog reset, a power loss or a crash.
- `scripts/config-migrate.sh`, run at boot: configs from older releases now receive new settings. `install_config` only copied a `.dist` when the file was missing, so an existing camera never got new keys (measured on a 1.8.3 camera: `boot.conf` lacked 34 keys, `mqtt.conf` 7). Append-only and idempotent: missing keys are added with their default, a key the user commented out counts as present, existing lines are never changed. When a `.dist` default differs from what the code does without the key (e.g. `MEM_WATCHDOG_ENABLE`), the code default is written so behaviour does not change; a test fails if such a divergence is not declared. lighttpd configs receive `# @migrate` blocks from the `.dist`, checked with `lighttpd -tt` first, and a config naming the missing `mod_setenv` is repaired. A checksum stamp makes later boots a single `md5sum`. Verified on hardware with the camera's BusyBox 1.24 (also covered under qemu by the tests), including a reboot.
- `src/webui/purge-bulma.mjs` (PurgeCSS 6.0.0): builds `www/css/bulma.1.0.2.purged.min.css` from the full Bulma kept in `src/webui/`. A test fails if a class the UI uses is missing from the purged file.
- Image tuning controls: a "Live image tuning" card in Settings → Image & text (sliders, anti-flicker, exposure cap, applied-values line) and Home Assistant entities over MQTT (six `number` sliders, an anti-flicker `select`, an `Image Tuning` switch; retained `<root>/isp/state`). Shared validation in `scripts/isp-tune.sh`; endpoints `state.cgi?cmd=isp_tune` and `action.cgi?cmd=isp_tune` (see `docs/api.md`). Verified on hardware: UI save → brightness 30 applied, stream luma 111.9; MQTT commands in Home Assistant's exact format applied (brightness −10, exposure cap 40 %, anti-flicker, reset), invalid values rejected with a command result.
- Live image tuning (`ISP_TUNE=1`, `config/isp_tune.conf`): brightness, contrast, saturation, sharpness, hue (−50..50, relative to the sensor ISP file), mains frequency 50/60 Hz and an auto-exposure time cap (% of the ISP value). A thread in `libtc100fix.so` applies changes within ~2 s without restarting the stream and writes `/var/run/isp_tune.status`. Uses the camera's own `ak_vpss_effect_set` numbering (0–4 effects, 5 style, 6 Hz), which differs from the public EV300 SDK v18 header. The vendor re-applies effects after each day/night ISP reload; the exposure cap is re-applied by the thread. Verified on hardware: brightness +40 → mean luma 89.8→113.1, contrast +40 → black 38→16 / white 145→165, saturation +40 → +63 %, sharpness ±40 → edge energy 7.48/5.22 vs 6.70, exposure cap 40 % → `exp_time_max` 1125→450 and back to 1125; same server PID throughout.
- `lib/libtc100fix.so` (source `src/tc100fix/`, Anyka uClibc toolchain): run-time fixes for the closed vendor `v4l2rtspserver`, preloaded into that process only, each opt-in from `boot.conf`: `RTSP_FPS_LOCK`, `RTSP_MIC_OFF_WHEN_NO_AUDIO` (only acts when `RTSP_AUDIO=0`) and `VENDOR_PRINT_LEVEL` (replaces the level 3 the server forces into `/var/log/ak_print_level`). Inert when no option is set. Tests include an ARM-emulated run against the camera's uClibc (`TC100_SYSROOT`, fixtures in `tests/tc100fix/`).
- `scripts/collect-platform-dump.sh`: read-only platform inventory for reverse engineering (raw MTD images via `dd if=`, `/proc` and `/sys` facts, vendor filesystem, library fingerprints), written to the SD card only. Uncompressed archives: the camera busybox has no `gzip` applet.
- Restore `.gitignore` (live configs with credentials, `wpa_supplicant.conf`, runtime artifacts, Python bytecode). `.github/` is no longer ignored.
- GitHub Actions CI: `busybox ash -n` syntax check of every camera-side shell script, Python host regressions and Node frontend tests.

## [1.8.3-rc20] — 2026-09-11

### Changed
- Final stabilization candidate for 1.8.3: Frigate Light profile, bounded monitoring, restored PTT, transactional configuration updates, flat low-cost UI, and the completed operator workflow.
- Tighten release readiness by documenting the final validation gates required before tagging 1.8.3.

### Validation
- Candidate branch is prepared for the final AK3918 trial and release checks before promoting to the 1.8.3 tag.

## [1.8.3-rc10] — 2026-09-10

### Fixed
- Coordinate PTT with the AK3918 exclusive audio device: pause RTSP only for the clip, keep the upload lock until playback ends, then restart RTSP from a detached cleanup worker.


## [1.8.3-rc9] — 2026-09-10

### Fixed
- Release the PTT upload lock when the CGI exits, preserve PCM until playback finishes, and recover locks orphaned by older versions when no playback PID is alive.


## [1.8.3-rc8] — 2026-09-10

### Fixed
- Rebuild PTT playback from the stock firmware behavior: the TC100 amplifier enable is active-low, while ak_ao_demo drives it with the opposite polarity. A source-MD5-guarded installer creates /mnt/bin/ak_ao_ptt and flips only the two speaker-control instructions; /usr/bin/ak_ao_demo remains untouched.


## [1.8.3-rc3] — 2026-09-10 (device trial pending)

### Changed
- Validate imported ports, video geometry/rates/codecs, schedules, recording,
  sound, MQTT and one-line system values before touching active files.
- Stage JSON, legacy text and tar.gz restores under `/tmp`; commit all candidate
  files together and automatically restore originals after a write or readback failure.
- Bound backup decompression to 2 MiB and keep all import work sequential, with no
  resident process or added idle-memory cost.
- Add `frigate-light-ak3918`: H.265 720p/12 fps main stream and H.265 360p/8 fps substream, matching the AK3918 dual-encoder constraint observed on real hardware
- Preserve valid AK3918 audio codec values when profiles disable RTSP audio; `RTSP_AUDIO=0` now controls publication without breaking RTSP startup
- Retry RTSP DESCRIBE during encoder warm-up so a healthy stream is not rolled back before its listener becomes ready
- Use a raw RTSP DESCRIBE probe for profile validation because the bundled curl sends OPTIONS; accept Digest 401 or a video SDP 200 response
  detection stream, 1.32 Mbit/s combined target and audio disabled.

### Fixed
- Correct JSON import mappings for RTSP sections 0/1, audio sections 2/3, OSD,
  motion sensitivity and recording keys. Preserve raw JSON POST bodies.
- Export the real hostname, timezone, NTP server, flip/log flags, OSD placement and
  recording values so exported JSON can be restored without silent drift.
- Preserve the uploaded archive path while creating a rollback archive.

### Validation
- 38 host regression tests cover valid commits, full-batch rejection, JSON and legacy
  imports, staged archive restore, the new profile values, shell/JavaScript syntax and
  existing resource regressions. Real AK3918 validation remains pending.

## [1.8.3-rc2] — 2026-09-09 (device trial pending)

### Changed
- Keep everyday video/audio controls visible and collapse advanced encoding,
  audio formats and day/night thresholds in native, keyboard-accessible details.
  Opening a section preserves all values and makes no network request.
- Save main and secondary streams independently, including the selected stream
  and all existing advanced parameters. Correct the quality preset label to 720p.
- Settings submissions request JSON and inspect the application result, keep
  drafts on failure, prevent concurrent submissions, and show persistent feedback.
- Video/audio saves perform one configuration readback. A requested restart is
  clearly distinguished from a verified RTSP health check. Quick profiles return
  the result of the existing restart/rollback checks and refresh clean video forms.
- Disable settings submission until configuration is loaded; reveal and focus
  invalid fields inside closed advanced sections. Update asset cache versions.

### Fixed
- Read real INI sections when loading settings; expose CBR/VBR as the bitrate
  mode and read audio codecs from sections 2/3. Audio saves write the volume and
  section 2 codec, preserving the main video codec in section 0.
- Video/audio write failures no longer schedule a restart or return success.
- The local draft is removed only after the asynchronous save is confirmed.
- Improve inactive tab contrast and primary button text in settings.

### Validation
- 27 host regression tests and 14 Chrome interaction checks using simulated CGI
  responses. Mobile (390 px), desktop (1280 px), light and dark views inspected.
- Hardware behavior and CPU/RAM gains remain pending. No new background polling
  or frontend dependency. See the rc2 trial guide (removed from the tree, see git history).

## [1.8.3-rc1] — 2026-09-09 (device trial pending)

### Changed
- Share the main statusline poll with dashboard gauges; respect the configured
  health snapshot interval and adapt cache expiry to it (60 seconds by default).
- Bound MQTT capture size and decode only unread bytes in 16 KiB batches, with
  session-specific offsets and a 4 KiB maximum command frame. Add a retained
  offline Will and clean up the listener's own child processes.
- Skip identical configuration writes and unnecessary config-install hashing.
  Remove the unconditional FTP watchdog and boot-time cache drop. Existing
  live configurations and video settings are preserved.
- Limit backup uploads to 1 MiB compressed / 2 MiB expanded / 512 entries,
  rejecting archive links. Require POST and CSRF on the corrected mutation routes.
  Frontend callers and asset cache versions are updated together.

### Fixed
- Preserve raw POST bodies in the config editor and backup upload; refuse
  truncated writes and invalid shell syntax, keep a bounded editor backup.
- Remove recursive configuration installation in action.cgi; correct backup and
  timelapse date formatting; make package backups include the rollback manifest.
- Subtract shared memory from the fallback available-memory estimate and report
  failed deep RTSP/ONVIF probes instead of treating a live PID as healthy.
- Prevent FTP/Telnet starts in security hardening mode and bound update-check waits.

### Validation
- Host regression tests, syntax checks and existing binary hashes checked.
  ARM/BusyBox compatibility and resource gains still require the camera trial.
- French trial and rollback procedure: docs/essai-1.8.3-rc1.md (removed from the tree, see git history).

## [1.8.2] — 2026-08-13

### Fixed
- **Capability probe reported `fail` on a healthy camera.** `capability-check.sh`
  runs right after `run_autostart_scripts`, which starts the video daemons in the
  background — so the ISP pipeline is frequently not capturing yet and the single
  `getimage` attempt returned 0 bytes. A camera that served a 42 KB frame one
  minute later was flagged `{"status":"fail","failed":["getimage"]}`, and a
  monitoring signal that cries wolf is worse than no signal at all.
  The probe now retries up to 3 times (~24 s worst case; a healthy camera answers
  on the first, so it costs nothing normally) and distinguishes the two cases it
  previously conflated: a genuine `fail` only when `/var/run/v4l2rtspserver.pid`
  shows RTSP is up and `getimage` *still* yields nothing; otherwise
  `getimage_unverified` under `shimmed`, because with the pipeline down the probe
  honestly cannot tell "broken" from "not ready yet".
  Verified across two reboots of `.11`: `fail` before, `degraded` with
  `failed:[]` after, while `currentpic.cgi` served 41 976 bytes.

## [1.8.1] — 2026-08-13

TLS certificate lifecycle. Measured on both live cameras.

### Fixed
- **Expired HTTPS certificate was never renewed.** The certificate was generated
  with `-days 365` and only ever when the file was *absent*, so every camera older
  than a year served an expired cert — `.11` had been expired since 8 May 2026,
  which is what produced the `sslv3 alert certificate unknown` entries in
  `lighttpd-error.log`. `02_system-webserver` now also regenerates when
  `openssl x509 -checkend 0` fails, moving the old file aside as
  `lighttpd.pem.expired` rather than deleting it. Validity raised to 10 years.

### Changed
- **Self-signed certificate is now ECDSA P-256 instead of RSA-1024.** On this
  ARMv5 core (no crypto instructions) the TLS handshake measured **~0.09 s against
  ~0.14 s** — a real but modest gain, because the key being replaced was RSA-1024,
  already cheap to verify; against RSA-2048 the difference would have been far
  larger. The stronger reasons are correctness: RSA-1024 is below any current
  security floor, and EC keygen is instant where RSA took seconds — which matters
  because it runs during boot. Verified end-to-end on `.11`: `lighttpd -t` clean,
  HTTPS back 5 s after restart, certificate valid to 2036.

### Notes
- **`AK_PRINT_LEVEL` is a no-op on this hardware — deliberately left unset.**
  Probed on `CLOUD39EV3_AK3918EV300_MNBD`: none of the three candidate sysfs/proc
  paths exist, and there is no message flood to suppress in the first place (last
  `dmesg` line unchanged over 15 s; `syslogd` and `klogd` together consumed 1.35 s
  of CPU across 6 h of uptime, ~0.006%). The knob is kept for builds that expose
  it, but `boot.conf.dist` now records the measurement so nobody chases the
  phantom win again.
- Contrary to an earlier suspicion, certificate generation on a fresh card is
  **not** broken: `config/openssl.cnf` ships with the payload and
  `02_system-webserver` already exports `OPENSSL_CONF`. The manual failure that
  prompted the concern came from invoking `openssl` without that variable set.

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

## [1.8.0] — 2026-08-13

### Added
- **Boot-time capability probe** (`scripts/capability-check.sh`). This firmware has now shipped two bug classes where a tool *existed* but did not behave as the code assumed, and failed **silently**:
  - `tr` — busybox carries the applet but ships no symlink, and `/mnt/bin` is not on the CGI `PATH`. Exit 127 inside `$(...)` yields `""`, so callers got empty data rather than an error. Five shipped bugs.
  - `timeout` — `/bin/timeout` exists *and is on `PATH`*, but is the pre-2014 busybox variant wanting `-t SECS`. Given the modern form it execs the duration as the command; inside a redirect that is invisible. `currentpic.cgi` served a 0-byte JPEG with HTTP 200 and the correct MIME type, and the dashboard liveview was simply blank.

  A `command -v` check passes in the second case, which is precisely why this probe runs each tool and inspects the **result**: `tr` must actually translate, `timeout SECS CMD` must run CMD, `awk` must `gsub()` and split on `RS`, `getimage` must emit a non-empty JPEG, `od -An -tu1` must yield decimal bytes (the MQTT decoder depends on it), and `nc` must exist (the MQTT transport).

  Results land in `/tmp/capability-check.json` and are surfaced under `capabilities` in `health.cgi`, so a misbehaving tool shows up in monitoring instead of as corrupted data downstream. The report distinguishes **`shimmed`** (expected here — the `tr()`/`timeout()` shims cover it) from **`failed`** (something the project genuinely relies on is broken). Verified on hardware: the probe independently rediscovered both known traps — `{"status":"degraded","failed":[],"shimmed":["tr","timeout"]}`.

  Cost: a handful of execs, once, at the end of boot. No daemon, no polling, and it never blocks boot (always exits 0).

### Fixed
- **Power-draw sensor missing on one camera in Home Assistant.** `POWER_ESTIMATE_ENABLE` was `1` on one unit and `0` (the shipped default) on the other, so `power_estimated_mw` published as `null` and the HA template resolved to `none`. The hardware sensor was fine on both — only the estimate was off. Aligned. Worth remembering that this value is *computed* (base + CPU share + IR-LED bonus), not measured: the camera reads voltage only, never current.

---

## [1.7.3] — 2026-08-13

Two real PTT bugs fixed. **Push-to-talk still produces no audible sound** — the
remaining cause is below the software layer; see *Known issues*.

### Fixed
- **Every PTT control was greyed out even with a healthy backend.** `ptt-audio.js` compared the `get_ptt_status` response strictly against `OK`, but `action.cgi` appends an HTML footer to every non-JSON reply, so the body is `OK\n<hr/>`. The mismatch reported "audio backend missing" and disabled the PTT button, the volume slider and the test button. Only the first line is read now.
- **Every PTT upload answered `EMPTY_INPUT`.** `upload_audio.cgi` streams a raw PCM body, but a hygiene pass had made it source `func.cgi` (for the `tr`/`timeout` shims) — and `func.cgi` slurps stdin at load time to parse form bodies, draining the stream before the PCM reader ran. A `FUNC_CGI_SKIP_BODY=1` guard now skips that slurp for binary-body callers; the shims stay. Upload returns `OK`/200 on both cameras.

### Known issues
- **PTT is silent: `v4l2rtspserver` holds the audio codec, and freeing it is not enough.** Diagnosed on hardware:
  - `ak_ao_demo` (the playback binary the CGI uses) prints `play finished` and exits 0 while producing **zero** DAC events in the kernel — it never reaches the hardware and never reports the failure.
  - The full-duplex path reveals the real error: `open /dev/akpcm_cdev1 failed: Operation not permitted`. `v4l2rtspserver` keeps that device open to capture `audio0`, and on this Anyka codec output requires opening it too.
  - With RTSP stopped, `ak_aec_demo` drives the kernel through the *exact* sequence the stock firmware logs at boot — `IOC_SET_SPEAKER value=1`, `ak39_set_hp_power 1`, `set_channel_source: s_dac=1` — identically for `spk_gpio` 0 and 1 (the driver powers the amp itself; that GPIO is not the gate). **Still no audible output.**

  So the software chain is now provably complete down to the driver powering the amplifier, and the remaining gap is below it. Disabling audio in the RTSP stream would free the device but, on this evidence, would *not* restore sound — it was effectively tested by stopping RTSP entirely.

  Next discriminator (needs the operator): boot a camera **without the SD card** so the stock firmware and its `anyka_ipc` app run, and test two-way audio from the vendor app. Working there points at an initialisation `anyka_ipc` performs that our environment never runs (we kill it in `stop_cloud`); silent there points at hardware.

---

## [1.7.2] — 2026-08-13

Consolidation release: no new features, only truthfulness — of logs, of metrics,
and of documentation — plus the first real reboot validation of the 1.6.x boot
changes.

### Fixed
- **`health.cgi` / `health-snapshot` reported `mem_avail_kb:0`.** This kernel ships no `MemAvailable` line and neither consumer had the fallback `state.cgi` already used. Both now estimate available memory as free + buffers + cached + SReclaimable. (While auditing this, the RAM gauges in `state.cgi` and the MQTT health payload turned out to already be cache-aware — the ~17–19 MB "used" figures are honest, and the inter-camera delta is page-cache noise, not a leak. Verified: process sets on both cameras are identical, no orphaned listeners.)
- **The bridge logged `using legacy one-shot polling` while the persistent listener was active.** The pre-persistent FIFO "stream mode" still ran its detection and printed its verdict; in persistent mode it would even have opened a competing broker connection had the shell supported it. The persistent path now short-circuits that block and logs what is actually happening (`Command path: persistent listener`). This line cost real debugging time twice.

### Documentation
- **Quick Start: still image in HA at zero camera cost** — a *Generic Camera* integration pointing at `currentpic.cgi` (basic auth, SSL verify off). HA pulls the JPEG on demand and the camera's 2 s snapshot cache absorbs the polling. This is the supported replacement for the disabled MQTT camera entity.

### Validated
First controlled reboot since the 1.6.x boot changes, on both cameras:
- `initialize_gpio` applies the configured LED intent (`FRONT_LED=0` → LED off at boot, previously only verified by inspection).
- The blocking NTP step before lighttpd holds: the error log opens with a real 2026 date and contains **zero** `clock jumped` graceful restarts (previously one per boot, killing every open connection ~40 s in).
- The `frigate_ha` autostart trim is back in effect — deploy sessions had left `ftp-server` running on both units; after reboot it is off, as profiled. Start it on demand for deploys (`scripts.cgi?cmd=start&script=ftp-server`).
- `mem_avail_kb` reports ~24.7 MB where it previously reported 0.

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

Validated on one camera (CAMERA1) before propagating; the second unit stays on
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
- The persistent listener trades resident memory for the loss of connect/teardown churn every ~13 s. Measured on both cameras after the rollout: RAM went from ~14.8 MB to **17.3 MB (CAMERA1) / 19.5 MB (CAMERA2)** of 33.4 MB, CPU unchanged at **43 % / 51 %** against a 41–43 % baseline. On a 33 MB device that memory cost is a real trade, not a free win — set `MQTT_PERSISTENT_SUBSCRIBE=0` if memory matters more than command latency on a given unit.
- Beware when measuring: `state.cgi?cmd=sysusage` read 98–100 % CPU immediately after a burst of HTTPS polls, because every CGI request is itself a fork on this core. Let the device idle ~90 s before trusting a CPU figure; `/proc/loadavg` (~1.2 steady, dominated by the RTSP stream) is the more honest signal.
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
  Naming a camera `CAMERA1` vs `CAMERA2` is then the single action that gives
  each its own topic root, `uniq_id` prefix and HA device — no more two
  publishers fighting over `teckin/tc100`. Verified on both cameras: roots
  `camera1` / `camera2`, distinct HA devices.
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
