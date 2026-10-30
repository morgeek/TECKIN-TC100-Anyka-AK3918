# TECKIN TC100 — alternative firmware

Local-only firmware for the **TECKIN TC100 / TECKIN Click** indoor camera
(Anyka AK3918EV300). It replaces the cloud application with RTSP streams for
Frigate or any NVR, MQTT and Home Assistant discovery, a French / English web
interface and recording on the SD card when the network fails. Nothing needs
the internet, and no vendor file is published.

**3.0** runs a free, recent kernel (Linux 6.6) instead of the vendor's 3.4, with
free drivers for the hardware video encoder (H.264, H.265, JPEG) and a free RTSP
server: no vendor daemon, no cloud. It runs from an SD card (trial) or
**entirely from the camera's SPI flash**, installed from the card without a
serial console: [copy the files to an SD card and restart the camera](#try-it-copy-to-an-sd-card-restart-the-camera). **3.0.1-rc1 is a release candidate not yet run on a camera**:
read [Is it safe?](#is-it-safe) first.

> **The 2.x firmware** (vendor kernel 3.4, lighttpd with HTTPS, the vendor RTSP
> server with `libtc100fix`, install to `/usr`) is on the branch
> [`2.x`](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/tree/2.x). `main`
> only holds 3.0. A camera running 2.x can move to 3.0 with the SD card below.

It started from [the original TC100 SD-card hack](#where-it-comes-from) and
grew from there.

![Dashboard](docs/screenshots/dashboard-dark.png)

<sub>Every screenshot shows a test pattern instead of the camera image, and example addresses.</sub>

---

## Contents

- [What you can do](#what-you-can-do)
- [Try it: copy to an SD card, restart the camera](#try-it-copy-to-an-sd-card-restart-the-camera)
- [Is it safe?](#is-it-safe)
- [Updates](#updates)
- [Home Assistant and Frigate](#home-assistant-and-frigate)
- [Recording on the SD card](#recording-on-the-sd-card)
- [Wi-Fi, passwords, safety](#wi-fi-passwords-safety)
- [Screenshots](#screenshots)
- [The hardware, and OpenIPC](#the-hardware-and-openipc)
- [How it works](#how-it-works)
- [Where it comes from](#where-it-comes-from)
- [Repository structure](#repository-structure)

---

## What you can do

**Video**
- Two RTSP streams: main 1080p H.265 or H.264 at 15 fps, and a 640x360 sub-stream for detection
  (`rtsp://CAMERA-IP:554/video0_unicast` and `video1_unicast`), over TCP or UDP, with the microphone as a G.711 track.
  The sub-stream can be turned off when no recorder uses it.
- ONVIF (discovery and profiles, port 8081): off by default, Services → Services → onvif.
- **Privacy masks** painted out before encoding, live image tuning (brightness, contrast, saturation, hue) with no
  stream restart, day / night with the IR LEDs and the IR filter, black and white, on-screen clock.
- Still JPEG at `cgi-bin/currentpic.cgi`, made by the hardware JPEG engine, so Home Assistant polling costs nothing.

**Home Assistant, Frigate, NVRs**
- MQTT with Home Assistant discovery: about 30 entities (Wi-Fi signal, memory, light level, sound level, night mode,
  SD card, RTSP clients, LEDs, profile…), commands from Home Assistant, availability, and an *Unexpected Restart*
  sensor after a restart nobody asked for.
- A Frigate configuration ready to paste (Live view → More tools → Diagnostics, or `state.cgi?cmd=frigateyaml`).
- Any RTSP NVR works: Blue Iris, Synology Surveillance Station, iSpy, go2rtc…

**Recording**
- MP4 files on the SD card with the sound, copied from the video the camera already encodes (no re-encoding), each
  with a thumbnail.
  By default only **while Frigate does not receive the video**, with a few seconds before and after; "always" and
  "on motion" too. A file cut by a power loss plays up to its last second.

**Audio**
- The microphone in the RTSP stream and in the recordings, listening live from the browser, a sound level in dBFS with
  detection, and push-to-talk from the browser through the camera's speaker.
- **Two-way audio from Home Assistant, Frigate or go2rtc**: their microphone button plays your voice on the camera's
  speaker (ONVIF backchannel in the RTSP stream; needs the camera password; Settings → Video → Two-way audio).

**Detection**
- The camera's own motion detection (MQTT event, picture on motion), with **motion zones**. Off by default: Frigate
  does the detection.

**Running it**
- From the **flash memory**, the SD card only for recordings; or from the SD card (trial mode).
- Setup wizard, French / English interface, light / dark theme, phone layout.
- Firmware updates from the web page, written to the flash and read back.
- Wi-Fi from a `wifi.txt` file on the card, from the web page, or from a rescue access point when the Wi-Fi is lost;
  the current network is always kept as a fallback.
- One password for the web interface, RTSP, FTP and telnet (Settings → System).
- Backups and presets of the settings, export to another camera.
- Diagnostics: memory, processes, events, service health, reboot history with the cause.

**Privacy**
- No cloud and no outgoing connection, unless you turn on the GitHub release check (`UPDATE_CHECK=1`). Web login,
  CSRF protection, only the local network may connect by default, and a "Privacy shield" switch that stops every
  outgoing service.

**What 3.0 does not do**: HTTPS (busybox httpd serves plain HTTP with a login), sharpness, anti-flicker and exposure
cap, resolution and frame rate changes, card formatting from the web page. Feature by feature: [feature audit](docs/linux-port/feature-audit-2026-10-26.md).

---

## Try it: copy to an SD card, restart the camera

Nothing to install on your computer, no cable, no need to open the camera. The same steps in French are in
`00-LISEZ-MOI-READ-ME.txt`, the first file of the zip.

**You need** a TECKIN TC100 (vendor firmware, or the 2.x firmware of this project), a **microSD card of 32 GB or
less**, and a computer to copy files to the card.

**Is my camera supported?** Only one hardware variant is known so far (JX-F23 sensor, RTL8188FU Wi-Fi, 8 MiB
XM25QH64A flash: [hardware variants](docs/hardware-variants.md)). The card checks the camera first and **writes
nothing to a camera it does not recognise** (red LED, the reason in `tc100-3/STATUS.txt`). Not sure? Try
`tc100-<version>-inventory.zip` first: same steps, it only writes `tc100-inventory.txt` to the card. Send that file
in a [Hardware inventory issue](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/issues/new/choose).

1. **Download** `tc100-<version>-sd.zip` from the
   [releases](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/releases).
2. **Copy everything in the zip to the root of the card.** The card must show the folders `wifitest`, `tc100test`,
   `tc100-3`, `www`... directly, not inside another folder.
   - The card must be **FAT32**. Cards over 32 GB come as exFAT and do not work as they are: format them FAT32
     first (Rufus or `guiformat` on Windows, Disk Utility → "MS-DOS (FAT)" on macOS).
   - Camera never set up on Wi-Fi? Add a file `wifi.txt` at the root of the card, with two lines:
     `SSID=your network` and `PASSWORD=its password`. A camera already on your Wi-Fi keeps its network.
3. **Camera off, card in, power on.** Leave it plugged in for 3 minutes:
   - **blue LED blinking** (about 2 minutes): the camera saves its own memory to the card, then restarts;
   - **a short chime**: the new firmware is running;
   - **red LED on**: it stopped without changing anything. The reason is in `tc100-3/STATUS.txt` on the card.
4. **Open http://tc100/** in a browser (or the camera address shown by your router, also written to
   `tc100-3/ADRESSE.txt` on the card). User `root`, password `pass`, or the password of your 2.x camera.
   The setup wizard asks for a new password.

That is the trial: the new firmware runs **from the card**. **Take the card out and restart: the camera starts its previous
firmware.** (Only a few start commands were added to the U-Boot environment; the previous start stays the fallback.) Keep the card, and never share `tc100-3/backup/flash-stock.bin` (the copy of your camera's memory).

**Keep it?** The last step of the wizard, or Settings → Update & backup → *Install to flash*, copies the firmware into
the camera (about 10 minutes, do not unplug). The camera then starts without the card, and the card only holds
recordings. Later versions: Settings → Update & backup → *Firmware update*, with `tc100-<version>-update.tar`.

**Something went wrong?**

| What you see | What to do |
|---|---|
| Nothing happens, no blue LED | The files are not at the root of the card, or the card is not FAT32. |
| Red LED on | Read `tc100-3/STATUS.txt` on a computer: nothing was changed. "Not a TC100 variant the firmware knows": send `tc100-inventory.txt` from the card in a Hardware inventory issue. |
| No chime and no page after 15 minutes | Wrong Wi-Fi. Power off, read `tc100-3/ADRESSE.txt` on a computer: it gives the name and password of the camera's rescue Wi-Fi; join it and open http://10.42.0.1/. |
| You want the old firmware back after *Install to flash* | Put the 3.0 card back in: it starts the camera, and `v3/install/restore-stock.sh` writes back the memory saved on the card. |

What the card does step by step, the U-Boot commands and the flash layout:
[docs/linux-port/install-3.0.md](docs/linux-port/install-3.0.md).

## Is it safe?

Not yet proven: **nothing of the SD install has run on a camera.** Use it only if you can live with opening the
camera to reach its serial console in the worst case below.

What protects you:
- The camera is identified before anything is written: a read-only inventory (sensor, Wi-Fi chip, flash, U-Boot)
  must match a known board profile, and U-Boot and the stock partitions must match the md5 of the tested camera.
  The flash install checks again on Linux 6.6, with the sensor id and the flash chip id.
- U-Boot and `mac` are never written; the whole flash is saved to the card, read twice and compared, before
  anything is written.
- Only the 4 KiB U-Boot environment is written before the install. The stock start (`boot_normal`) stays in it as
  the fallback: no card, no `tc100test/c66.img`, or a 3.0 start command that fails, and U-Boot starts the system the
  camera had before.
- The trial mode writes nothing else to the flash: take the card out and the camera is as before.
- The install writes `initrd` last, saves each partition first and reads each one back; until the end, the card
  still starts the camera.
- Any doubt in the checks: the hook stops before writing and says why.

What is not covered yet:
1. **A power cut during the environment write** (a fraction of a second). `envtool` puts the original back when the
   write fails, but if power is lost in the middle, U-Boot falls back to its built-in environment, and it is not yet
   checked that this one starts the stock firmware. Worst case: recovery through the serial console. Do not unplug
   the camera during the first two minutes.
2. **Cameras that differ from the author's** are refused (nothing written), but only one variant is known yet: other
   TC100 batches need their inventory first ([hardware variants](docs/hardware-variants.md)).
3. **An interrupted web update** leaves the flash system unable to start: keep the 3.0 SD card; it starts the
   camera and "Install to flash" writes everything again.

Other limits: settings are kept in flash, the user space is read-only (updated as a whole); a card inserted while
the camera runs is not detected (power it off and on); the default password `pass` is public until you change it.

---

## Updates

Settings → **Update & backup** → *Firmware update*: upload `tc100-<version>-update.tar` from the
[releases](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/releases). The camera checks the package, writes the
kernel, the user space and the initramfs (last) to its flash, reads each one back, then restarts. Settings are kept.
An interrupted update leaves the flash system unable to start: keep the 3.0 SD card, it starts the camera and
"Install to flash" writes everything again.

---

## Home Assistant and Frigate

1. Wizard (or Settings → Integrations): profile **Frigate + Home Assistant**, MQTT broker address and login.
2. **Give each camera its own name** (Settings → Network → Hostname). It names the Home Assistant device and the MQTT
   topics (`CAMERA1` → `camera1/…`). Two cameras with the same name merge into one device.
3. Home Assistant finds the camera through MQTT discovery. The device page shows the firmware version.
4. Frigate: Live view → More tools → Diagnostics gives a configuration to paste (go2rtc restream;
   `state.cgi?cmd=frigateyaml&redact=1` without the password). Streams:
   - main (recording): `rtsp://root:PASSWORD@CAMERA-IP:554/video0_unicast`
   - sub (detection): `rtsp://root:PASSWORD@CAMERA-IP:554/video1_unicast`
   - go2rtc also gets the speaker: two-way audio from the microphone button of Home Assistant, Frigate or go2rtc
     ([docs/two-way-audio.md](docs/two-way-audio.md)).
5. Still image in Home Assistant: a *Generic Camera* with `http://CAMERA-IP/cgi-bin/currentpic.cgi`, basic auth.

Home Assistant can drive the camera (LEDs, day / night, profile, snapshot, motion) by publishing on
`<topic>/command`. Results come back on `<topic>/command/result`. More: [docs/api.md](docs/api.md).

---

## Recording on the SD card

Settings → **Recording**:

- **When**: *only while Frigate does not receive the video* (default), *always*, or *on motion*. Frigate is
  recognised by the address entered in Settings → Integrations → Frigate live view (or `REC_CLIENT` in `boot.conf`).
- **Stream**: main (best quality) or sub. The microphone is recorded too (`REC_AUDIO=0` in `boot.conf` turns it off).
- Files: `DCIM/YYYY-MM-DD_HH-MM-SS.mp4` with a `.jpg` thumbnail, 5 minutes each by default, listed in Recordings.
  The oldest are deleted to keep 256 MB free.
- In "offline" mode: recording starts 5 s after the stream stops reaching Frigate. The file begins with the last
  seconds still held in memory, and recording continues 30 s after Frigate is back.

---

## Wi-Fi, passwords, safety

- **Wi-Fi**: `wifi.txt` on the card (`SSID=`, `PASSWORD=`), the wizard, or Settings → Network. In every case the new
  network comes first and the previous ones stay as fallbacks, so a typo does not take the camera off the network.
  An invalid `wifi.txt` becomes `wifi-invalid.txt` with the reason.
- **Rescue access point**: after 10 minutes without Wi-Fi (or holding the reset button 3-7 s) the camera opens its
  own Wi-Fi network; its name and password are in Settings and on the card (`tc100-3/ADRESSE.txt`), the page is at
  http://10.42.0.1/.
- **Password**: `root` / `pass` on a new installation (or the password of a 2.x camera). The wizard asks for a new
  one; a banner says so until it is changed (Settings → System → Password).
- **Plain HTTP**: the web interface has a login but no HTTPS on 3.0. Use it on your own network only.
- **Remote shell**: SSH (dropbear, same `root` password) is on by default; switch it in Services (`ssh-server`).
  Telnet sends the password in clear: it is **off** by default (Services, `telnet-server`; the "Boot" toggle starts it
  at boot, LAN only, it stops by itself after `REMOTE_SHELL_TIMEOUT_MIN`). An upgraded camera keeps SSH on.
- **Rescue telnet**: when the web interface does not answer, the web server is restarted once; if that does not
  help, a telnet opens on port 23, and closes again once the web interface has been back for two minutes.
- **Offline by design**: the camera makes no outgoing connection except to your MQTT broker, NTP server and syslog
  server, if set. *Privacy Shield* (Settings → System → LEDs and privacy) stops every outgoing service at once.
- **Way back**: a card with `tc100test/c66.img` always starts first, and `v3/install/restore-stock.sh` writes back the
  flash saved before 3.0. The vendor U-Boot is never written.

---

## Screenshots

| | |
|---|---|
| ![Dashboard, light](docs/screenshots/dashboard.png) Dashboard, light theme | ![Live view](docs/screenshots/live-view-dark.png) Live view |
| ![Settings, image](docs/screenshots/settings-image.png) Settings → Image: live tuning | ![Recording](docs/screenshots/settings-recording.png) Settings → Recording |
| ![Integrations](docs/screenshots/settings-integrations.png) Settings → Integrations: MQTT and Home Assistant | ![Update](docs/screenshots/settings-update.png) Update & backup |
| ![Install to flash](docs/screenshots/settings-install-to-flash.png) Install to flash, from the SD card | ![System](docs/screenshots/settings-system.png) Settings → System |
| ![Services](docs/screenshots/tools-services.png) Services → Services | ![Diagnostics](docs/screenshots/tools-diagnostics.png) System → Diagnostics |
| ![Logs](docs/screenshots/tools-logs.png) System → Logs | ![Search](docs/screenshots/settings-search.png) Settings search |
| ![Config editor](docs/screenshots/tools-configeditor.png) System → Config editor | |
| ![Dark, French](docs/screenshots/settings-dark-fr.png) Settings in French | ![Phone](docs/screenshots/dashboard-mobile.png) On a phone |
| ![Live, light](docs/screenshots/live-view.png) Live view, light theme | ![Phone settings](docs/screenshots/settings-mobile.png) Settings on a phone |

<sub>Made before the 2.x / 3.0 split; a few pages differ on 3.0.</sub>
Remake them with `python3 src/webui/screenshots/shots.py docs/screenshots` (Playwright, canned answers, no camera needed).

---

## The hardware, and OpenIPC

| | |
|---|---|
| SoC | Anyka **AK3918EV300** (ARM926EJ-S, 64 MB of RAM, about 45 MB for Linux after the video buffers) |
| Image sensor | Silicon Optronics **JX-F23** (1080p, MIPI) |
| Wi-Fi | Realtek **RTL8188FU** (USB; mainline `rtl8xxxu` on 3.0) |
| Flash | 8 MB SPI NOR, 4 KB erase blocks |
| Board marking | **WVC3310S2_V5.0** |
| Vendor software | U-Boot, Linux 3.4.35, uClibc 0.9.33.2, TECKIN firmware V1.1.41 |

### Flash layout of 3.0 (8 MiB, 4 KiB sectors)

| Partition | Offset | Size | Content |
|---|---|---|---|
| `boot` | 0x0 | 228 KiB | vendor U-Boot, never written |
| `kernel` | 0x39000 | 2 MiB | Linux 6.6 uImage (about 1.9 MiB) |
| `mac` | 0x239000 | 4 KiB | radio data, never written |
| `env` | 0x23a000 | 4 KiB | U-Boot environment: the 3.0 start commands are added once, from the stock firmware; read-only for Linux 6.6 |
| `initrd` | 0x23b000 | 2 MiB | xz initramfs, padded to 2,012,654 bytes |
| `stack` | 0x43b000 | 2.7 MiB | squashfs (xz) of the free user space |
| `vendor` | 0x6ee000 | 1 MiB | squashfs of this camera's own vendor libraries, made at install |
| `cfga`, `cfgb` | 0x7ee000, 0x7f7000 | 36 KiB each | settings slots |

`initrd` + `stack` + `vendor` are exactly the stock partitions A, B and C.

**[OpenIPC](https://openipc.org)** is the reference open firmware for IP cameras. This project is not OpenIPC, but it
uses and contributes to its work:

- The camera was identified with OpenIPC's [ipctool](https://github.com/OpenIPC/ipctool). The board was unknown to
  OpenIPC's database, and the report is public:
  [OpenIPC camera report r-rxh32hs4](https://openipc.org/cameras/report/?id=r-rxh32hs4) (hardware, boot log, flash
  map, boot chain, U-Boot SD recovery, Wi-Fi interfaces, vendor media API).
- The flash design follows OpenIPC's approach: a small read-only system, settings in their own partition, and
  nothing that needs the cloud.
- Anyone porting OpenIPC to the AK3918EV300 can reuse the Linux 6.6 patch series
  ([patches/kernel-6.6/series](patches/kernel-6.6/series/README.md)), the encoder driver and `src/libakuio`.

Notes, hardware facts, status and how to build: [docs/linux-port](docs/linux-port/README.md).

---

## How it works

- **Kernel**: Linux 6.6 as a series of patches on the `v6.6` tag: CPU, interrupts, timer, console, SD card, USB host,
  Wi-Fi (mainline `rtl8xxxu`, access point included), GPIO, I2C, watchdog, audio, **video** (V4L2 driver for the
  JX-F23 sensor and the ISP), the hardware video encoder (`ak39_venc`) and a SPI NOR driver that can write. CI builds
  it on every push.
- **Video**: H.264 and H.265 are made by the vendor encoder control libraries running on the free driver
  (`src/libakuio`); JPEG is fully free code (`src/jpegenc`). The H.265 command lists are reproduced offline
  (`src/h265enc`), not yet used on the camera. **`tc100_rtsp`** (`src/tc100rtsp`) is the one video process: RTSP
  server, web pictures, image tuning, privacy masks, OSD, motion with zones, sound level and the MP4 recorder.
- **User space**: our Buildroot base (musl, busybox) in an xz initramfs, the free user space in a squashfs
  (`v3/build-stack.sh`), the web interface served by busybox httpd behind `httpfront`. The few vendor libraries 3.0
  needs (the uClibc runtime and the encoder control libraries) are copied from each camera into its own `vendor`
  partition at install; none is published.
- **Boot**: U-Boot starts the SD card's `tc100test/c66.img` when there is one, otherwise the flash system
  (`flashboot`), otherwise the stock firmware. `v3/autorun-linux66.sh` starts the services.
- **Settings** live in two alternating flash slots (`cfga` / `cfgb`, `cfg-persist`), so a power cut during a save
  keeps the previous settings.
- **MQTT**: forged in shell and sent through `nc`. One persistent connection.
- Platform notes and bugs fixed during the bring-up: [docs/known-issues.md](docs/known-issues.md). HTTP API:
  [docs/api.md](docs/api.md).

---

## Where it comes from

Full list of projects and licences: [CREDITS.md](CREDITS.md).

- **The original hack.** This project began in February 2026 as a copy of
  [TECKIN-TC100-Anyka-AK3918-camera-hacks](https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks)
  by **ThatUsernameAlreadyExist**: an SD card that takes over the camera through the vendor's factory test hook
  (`wifitest/`), without changing the firmware, and gives it RTSP, a web interface, FTP and telnet instead of the
  cloud app. The 3.0 install still enters through that hook, and a few of its tools (`bin/`) are still used.
  Thanks to its author, and to the earlier Anyka camera hacks it built on.
- **OpenIPC.** [OpenIPC](https://openipc.org) is the model for where this project went: the flash design and the
  layout of the web interface ([OpenIPC web interface](https://openipc.org/web-interface)).
- **From there to here**: 1.x and 2.x on the vendor kernel (Home Assistant and Frigate, live image tuning,
  push-to-talk, recording when Frigate is down, the install to flash, the new interface; branch `2.x`), then 3.0 on
  Linux 6.6. The whole history is in [CHANGELOG.md](CHANGELOG.md).

---

## Repository structure

```
VERSION             Firmware version
patches/kernel-6.6/ Linux 6.6 patch series (series/), kernel config
v3/                 3.0 system: boot script (autorun-linux66.sh), initramfs and user space builders, Buildroot base
  install/          SD card install hook, flash install and update, way back to the stock firmware
  linux66-sd/       Glue between the web interface and the free stack, flash writer (flashw), settings slots
src/tc100rtsp/      tc100_rtsp: RTSP server, recorder, pictures, motion, sound level
src/libakuio/       Free replacement for the vendor encoder-memory library
src/jpegenc/        Hardware JPEG encoder
src/h265enc/        H.265 command-list generator and register-sequence model (experimental)
src/httpfront/      Front for busybox httpd (redirects /, one connection per request)
src/netacl/         libnetacl: local-network-only filter for the uClibc programs
src/webui/          Web UI sources: index/ (main script, built by build-index.sh), i18n check, Bulma purge, screenshots
www/                Web interface; www/cgi-bin/ are shell CGIs
scripts/            Daemons and tools (wifi-txt.sh, wifi-rescue.sh, mqtt-bridge.sh…)
  action.d/         The web commands of www/cgi-bin/action.cgi, one file per group
controlscripts/     Services, started and stopped from the web page
config/             Templates (*.dist) and the services started at boot (config/autostart/)
bin/ lib/           Small free ARM programs of the original hack (busybox, rwconf, monvifd…), libnetacl
sounds/             Audio clips
tests/              python3 -m unittest discover -s tests; node --test tests/*.test.js
docs/               API, known issues, screenshots; docs/linux-port: the Linux 6.6 port, install, status
```

Live configuration with secrets (`config/mqtt.conf`, `config/user.pwd`, `wpa_supplicant.conf`) is never in git; only
the `*.dist` templates are.

---

*Local only. No cloud. Your camera, your network.*
