# TECKIN TC100 — alternative firmware (v2)

Local-only firmware for the **TECKIN TC100 / TECKIN Click** indoor camera
(Anyka AK3918EV300). It replaces the cloud application with RTSP streams for
Frigate or any NVR, MQTT and Home Assistant discovery, a French / English web
interface, recording on the SD card when the network fails, and updates from
the browser. Nothing needs the internet, and no vendor file is published.

**Version 2.0.0** runs **from the camera's own flash memory**, with no SD card
at all. The card becomes optional, for recordings only. The SD card mode of
earlier versions is still there and is the way in.

![Live view](docs/screenshots/live-view.png)

<sub>Every screenshot shows a test pattern instead of the camera image, and example addresses.</sub>

---

## Contents

- [What you can do](#what-you-can-do)
- [What's new in 2.0](#whats-new-in-20)
- [Screenshots](#screenshots)
- [Step 1: run from the SD card](#step-1-run-from-the-sd-card)
- [Step 2: the setup wizard](#step-2-the-setup-wizard)
- [Step 3 (optional): install to flash, run without the card](#step-3-optional-install-to-flash-run-without-the-card)
- [Updates](#updates)
- [Home Assistant and Frigate](#home-assistant-and-frigate)
- [Recording on the SD card](#recording-on-the-sd-card)
- [Wi-Fi, passwords, safety](#wi-fi-passwords-safety)
- [The hardware, and OpenIPC](#the-hardware-and-openipc)
- [How it works](#how-it-works)
- [Repository structure](#repository-structure)

---

## What you can do

**Video**
- Two RTSP streams: main up to 1080p H.264 / H.265, and a sub-stream for detection (`rtsp://CAMERA-IP:554/video0_unicast` and `video1_unicast`). ONVIF is available from the SD card.
- Presets for Frigate (light, balanced, quality), live image tuning (brightness, contrast, sharpness, saturation, anti-flicker, exposure cap) with no stream restart, a fixed frame rate, day / night with the IR LEDs and the IR filter, flip and on-screen text.
- Still JPEG at `cgi-bin/currentpic.cgi`, cached so that Home Assistant polling costs nothing.

**Home Assistant, Frigate, NVRs**
- MQTT with Home Assistant discovery: about 25 entities (Wi-Fi signal, memory, light level, sound level, night mode, SD card, LEDs, profile…), commands from Home Assistant, availability.
- A Frigate configuration ready to paste (Live view → More tools → Diagnostics, or `state.cgi?cmd=frigateyaml`), and a button that opens the camera in Frigate's smooth live view.
- Any RTSP NVR works: Blue Iris, Synology Surveillance Station, iSpy, go2rtc…

**Recording**
- MP4 files on the SD card, copied from the video the camera already encodes (no re-encoding, about 4.5 % CPU). By default only **while Frigate does not receive the video**, with a few seconds before and after, so a network or Frigate outage leaves no gap. "Always" is available too. FAT32 and exFAT cards.

**Audio**
- Listen live, talk through the speaker (push-to-talk from the browser), sound detection with a level in dBFS.

**Running it**
- Runs from the **flash memory** (2.0) or from the **SD card**.
- Setup wizard, French / English interface, light / dark theme, phone layout.
- Updates from the web page, checked file by file, with rollback. Updates that fail are rolled back automatically from flash.
- Wi-Fi set from a `wifi.txt` file on a card, or from the web page, always keeping the current network as a fallback.
- One password for the web interface, RTSP, FTP and telnet (Settings → System).
- Backups and presets of the settings, export to another camera.
- Diagnostics: memory, processes, events, service health, reboot history with the cause.

**Privacy**
- No cloud, no outgoing connection, unless you turn on the GitHub release check (`UPDATE_CHECK=1`). HTTPS with a local certificate, CSRF protection, a "Privacy shield" switch that stops every outgoing service.

---

## What's new in 2.0

- **Runs without an SD card.** The firmware is installed into the camera's flash memory, from the card, in three guided steps (below). The vendor's U-Boot, kernel and root file system are not touched. Only the `/usr` partition is replaced (cloud app removed, firmware added), and the code goes into the free end of the kernel partition.
- **Updates from flash** with a small code package (`tc100-code-<version>.bin`, about 350 KB): written, read back, kept only if the camera comes back on the network, rolled back automatically otherwise.
- **Recording on the SD card** when Frigate stops receiving the video (or always), with pre- and post-roll.
- **New interface**: Live view / Settings / Tools / System. Settings are grouped in tabs (Image, Video, Day/night, Audio, Detection, Recording, Integrations, Network, System, Update & backup). Camera controls sit under the live image.
- **New wizard**: language and Wi-Fi, profile, web access, Frigate and MQTT, recording, install to flash.
- **Wi-Fi from a text file** (`wifi.txt`), and a fallback network kept on every change.
- Password card, exFAT cards for recording, HTTP fallback and a rescue telnet when the web server cannot start from flash.

Full list: [CHANGELOG.md](CHANGELOG.md).

---

## Screenshots

| | |
|---|---|
| ![Settings, image](docs/screenshots/settings-image.png) Settings → Image: live tuning | ![Recording](docs/screenshots/settings-recording.png) Settings → Recording |
| ![Integrations](docs/screenshots/settings-integrations.png) Settings → Integrations: MQTT and Home Assistant | ![Update](docs/screenshots/settings-update.png) Update & backup, from flash |
| ![Install to flash](docs/screenshots/settings-install-to-flash.png) Install to flash, from the SD card | ![System](docs/screenshots/settings-system.png) Settings → System |
| ![Services](docs/screenshots/tools-services.png) Tools → Services | ![Diagnostics](docs/screenshots/tools-diagnostics.png) Tools → Diagnostics |
| ![Dark, French](docs/screenshots/live-view-dark-fr.png) Dark theme, in French | ![Phone](docs/screenshots/live-view-mobile.png) On a phone |

Setup wizard:

| | | |
|---|---|---|
| ![Wi-Fi](docs/screenshots/wizard-1-wifi.png) | ![Frigate](docs/screenshots/wizard-4-frigate.png) | ![Recording](docs/screenshots/wizard-5-recording.png) |
| ![Flash](docs/screenshots/wizard-6-flash.png) | ![Summary](docs/screenshots/wizard-7-summary.png) | |

Remake them with `python3 src/webui/screenshots/shots.py docs/screenshots` (Playwright, canned answers, no camera needed).

---

## Step 1: run from the SD card

You need a TECKIN TC100 that works with the TECKIN app, or did, and a microSD card (8–32 GB FAT32 is simplest; exFAT works).

1. Download **`tc100-sd-2.0.0.zip`** from the [latest release](../../releases/latest). Or build it: `sh src/release/build-sd.sh` gives `dist/tc100-sd-<version>/` (needs `squashfs-tools`).
2. Format the card in **FAT32** (MBR, 32 KB clusters). Commands for macOS and Windows are in `SD-CARD.txt` inside the zip.
3. Copy **everything** in the zip to the root of the card, including the `wifitest/` folder. That folder makes the vendor boot skip the cloud app and start this firmware instead. On macOS, run `dot_clean -m /Volumes/<card>` afterwards.
4. **Wi-Fi**: the camera keeps the network it was set up with in the TECKIN app. For another network, or a camera never set up, create a text file **`wifi.txt`** at the root of the card:
   ```
   SSID=YourNetwork
   PASSWORD=your password
   ```
   It is applied at boot, and the password is then removed from the card (`wifi-applied.txt` remains).
5. Put the card in the camera and power it on. After about a minute, find its address in your router (DHCP) and open **`https://CAMERA-IP`**. The certificate is local and self-signed, so accept the warning. The default login is `root` / `pass`.

To go back to the TECKIN app at any time, take the card out and power the camera on. As long as the flash has not been installed (step 3), the camera is exactly as it was.

> Never put files named `uImage`, `uimage`, `root.sqsh4`, `usr.sqsh4` or `usr.jffs2` at the root of the card: the vendor boot loader would try to reflash the camera with them.

## Step 2: the setup wizard

It opens by itself on the first visit (Settings → System → *Restart setup wizard* runs it again):

1. **Language and Wi-Fi**: English or French, and keep the current network or set another one. A new network is used from the next restart, and the current one stays as a fallback.
2. **Profile**: *Frigate + Home Assistant* (recommended: only what Frigate needs runs), *Standalone* (every feature), or *Third-party NVR* (RTSP only).
3. **Web access**: HTTPS only (recommended), HTTPS + HTTP, or an ultra-light HTTP server.
4. **Frigate and Home Assistant** (Frigate profile): MQTT broker address and login, and Frigate's address.
5. **Recording on the SD card**: when Frigate stops receiving the video, always, or off.
6. **Run without the SD card** (SD card mode): starts step 3 below, or not now.
7. **Summary**, then apply.

Then change the password: Settings → System → Password. It covers the web interface, RTSP, FTP and telnet, so update the stream addresses in Frigate or your NVR afterwards.

## Step 3 (optional): install to flash, run without the card

The firmware is copied into the camera's own memory. Afterwards the camera starts it with no card, and a card is only used for recordings.

**What changes in the flash, and what doesn't.** The camera has 8 MB of flash. Only two areas are written:
- the `/usr` partition (3.7 MB): the vendor's files minus the cloud application, plus this firmware;
- the free end of the kernel partition (640 KB after the kernel), for the code updates.

The boot loader (U-Boot), the kernel and the root file system stay as they are. Your settings go into a folder of the camera's settings partition (jffs2), next to the vendor's. The original `/usr` is saved on your card at step 1, so you can put it back.

It is built for the TECKIN TC100 vendor firmware **V1.1.41**. Before writing anything, the camera checks the partition table, the kernel, that the area after the kernel is empty, and the fingerprint of its original `/usr`. On any doubt it stops, writes nothing, and says why in `tc100-flash/STATUS.txt` on the card.

### 3.1 On the camera: copy the original system to the card

Running from the SD card (step 1), either:
- Settings → **Update & backup** → *Install to flash* → **Step 1: copy the original system to the card**, or choose *Prepare the installation now* in the wizard;
- or create an empty folder **`tc100-flash`** at the root of the card and restart the camera.

After about 30 seconds the card holds `tc100-flash/usr-stock.img` (the camera's original `/usr`), `camera.txt` and `STATUS.txt`. **Keep `usr-stock.img`**: it is your way back. It holds the vendor's programs, so don't publish it.

### 3.2 On a computer: build the image to install

Power the camera off, take the card out and put it in a computer. On **Linux**, on **Windows with WSL**, or on **macOS**:

```sh
# tools: squashfs-tools (with xz) and python3
sudo apt install squashfs-tools python3        # Debian / Ubuntu / WSL
# brew install squashfs                         # macOS

git clone https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918.git
cd TECKIN-TC100-Anyka-AK3918
git checkout v2.0.0                             # or unpack the release's source archive

sh src/flash/build-flash-kit.sh /path/to/the/card
#   Linux: /media/$USER/<card>   macOS: /Volumes/<card>   WSL: /mnt/e (card in E:)
```

The script checks the copy against `camera.txt`, unpacks it, removes the cloud application, adds the firmware, and writes `tc100-flash/usr.img`, `usr.img.md5` and `code.bin` on the card. It takes a few seconds, and nothing is sent anywhere. The binaries it adds are in `src/flash/prebuilt/` (open source builds: curl and lighttpd without TLS, the RTSP server and its libraries).

### 3.3 On the camera: install

Eject the card properly, put it back in the camera and power it on (or click **Step 3: reboot and install** in Update & backup if the camera is already on). At boot, before any video service starts, the camera:

1. checks everything again (same camera, image intact, nothing using `/usr`);
2. copies your settings, Wi-Fi and a new HTTPS certificate into its settings partition;
3. writes `/usr`, reads it back, and rewrites it if it differs, up to 3 times;
4. writes the code area and reads it back;
5. restarts **from the flash**, once, with the card still in. That test boot marks the code as good when the network and the web page come back. Otherwise the next boot falls back to the code inside `/usr`.

Allow about 2 minutes, then open the web page. The **FLASH** badge in the top bar means the camera is running from its memory. **Power it off, take the card out, power it on**: that's it.

Progress and errors are in `tc100-flash/STATUS.txt` on the card. If the write fails, the card keeps the camera working as before. Put the card back and the camera runs from it again.

### Afterwards

- **A card in the slot** is used for recordings. It must not carry the `wifitest/` folder or the reflash files above: the camera refuses such a card for recording, because it would change how the camera boots. Use Settings → Recording → *Stop and eject the card* before taking it out.
- **Wi-Fi**: a `wifi.txt` on any card is still applied at boot.
- **Going back to the original `/usr`**: start from the SD card (a card with the step 1 content), enable telnet, and run `sh /mnt/scripts/flash-usr.sh /mnt/tc100-flash/usr-stock.img $(cat /mnt/tc100-flash/usr-stock.img.md5)`. With the original `/usr`, a camera without a card starts the TECKIN cloud app again.
- **No network at all from flash** (wrong Wi-Fi): put an SD card with a `wifi.txt` in, or the SD firmware (step 1), which always wins over the flash.

---

## Updates

Settings → **Update & backup** → *Firmware update*. The release has one file for each mode:

| The camera runs from | Upload | What happens |
|---|---|---|
| the **flash** (FLASH badge) | `tc100-code-<version>.bin` | written to the code area, read back, reboot; kept only if the camera comes back on the network, rolled back otherwise. "Roll back" returns to the code inside `/usr`. |
| the **SD card** | `tc100-update-<version>.tar` | every file checked against its md5, only changed files replaced, the previous ones kept for "Roll back". |

The binaries in `/usr` (RTSP server, web server, curl) only change with a new `/usr` image, built and installed with the same three steps.

Build them yourself: `sh src/release/build-code-package.sh` and `sh src/release/build-update.sh` (no cross toolchain needed). CI attaches all three files (`.zip`, `.tar`, `.bin`) to each `v*` release.

---

## Home Assistant and Frigate

1. Wizard (or Settings → Integrations): profile **Frigate + Home Assistant**, MQTT broker address and login.
2. **Give each camera its own name** (Settings → Network → Hostname). It names the Home Assistant device and the MQTT topics (`CAMERA1` → `camera1/…`). Two cameras with the same name merge into one device.
3. Home Assistant finds the camera through MQTT discovery. The device page shows the firmware version.
4. Frigate: Live view → More tools → Diagnostics gives a configuration to paste (go2rtc restream; `state.cgi?cmd=frigateyaml&redact=1` without the password). Streams:
   - main (recording): `rtsp://root:PASSWORD@CAMERA-IP:554/video0_unicast`
   - sub (detection): `rtsp://root:PASSWORD@CAMERA-IP:554/video1_unicast`
5. Still image in Home Assistant: a *Generic Camera* with `https://CAMERA-IP/cgi-bin/currentpic.cgi`, basic auth, SSL verification off.

Home Assistant can drive the camera (LEDs, day / night, profile, snapshot, motion) by publishing on `<topic>/command`. Results come back on `<topic>/command/result`. More: [docs/api.md](docs/api.md).

> Upgrading a camera that Home Assistant already knew under another name leaves the old device behind: delete it in Home Assistant.

---

## Recording on the SD card

Settings → **Recording**:

- **When**: *only while Frigate does not receive the video* (default) or *always*. Frigate is recognised by the address entered in Settings → Integrations → Frigate live view (or `REC_CLIENT` in `boot.conf`).
- **Stream**: main (best quality, about 4.5 % CPU while recording) or sub (under 1 %).
- Files: `records/YYYYMMDD/HHMMSS.mp4`, 5 minutes each by default. The oldest are deleted to keep 256 MB free. A file cut by a power loss stays playable up to its last second.
- In "offline" mode: recording starts 5 s after the stream stops reaching Frigate. The file begins with the last seconds still held in memory, and recording continues 30 s after Frigate is back.

From flash, the card is mounted on `/mnt/sd` when needed. *Stop and eject the card* before removing it.

---

## Wi-Fi, passwords, safety

- **Wi-Fi**: `wifi.txt` on a card (`SSID=`, `PASSWORD=`), the wizard, or Settings → Network. In every case the new network comes first and the previous ones stay as fallbacks, so a typo does not take the camera off the network. An invalid `wifi.txt` becomes `wifi-invalid.txt` with the reason.
- **Password**: `root` / `pass` on a new installation. A banner says so until you change it in Settings → System → Password.
- **HTTPS** with an ECDSA certificate made by the camera (10 years). From flash, if HTTPS cannot start, the web page falls back to HTTP, and a rescue telnet opens on port 23 when no web server answers within a minute.
- **Offline by design**: the camera makes no outgoing connection except to your MQTT broker, NTP server and syslog server, if set. *Privacy Shield* (Settings → System → LEDs and privacy) stops every outgoing service at once.
- **Recovery**: the SD card firmware always wins over the flash, and the vendor U-Boot (with its own SD card recovery) is untouched.

---

## The hardware, and OpenIPC

| | |
|---|---|
| SoC | Anyka **AK3918EV300** (ARM926EJ-S, about 33 MB of RAM usable by Linux) |
| Image sensor | Silicon Optronics **JXF23** (1080p) |
| Wi-Fi | Realtek **RTL8188FU** (USB) |
| Flash | 8 MB SPI NOR, 4 KB erase blocks |
| Board marking | **WVC3310S2_V5.0** |
| Vendor software | U-Boot, Linux 3.4.35, uClibc 0.9.33.2, TECKIN firmware V1.1.41 |

Flash layout: U-Boot, `KERNEL` 2 MB (kernel ends before 0x15b000; this firmware's code area is 0x160000–0x200000), `MAC`, `ENV`, `A` rootfs (squashfs), `B` settings (jffs2, 500 KB), `C` `/usr` (squashfs, 3.7 MB).

**[OpenIPC](https://openipc.org)** is the reference open firmware for IP cameras. This project is not OpenIPC, but it uses and contributes to its work:

- The camera was identified with OpenIPC's [ipctool](https://github.com/OpenIPC/ipctool). The board was unknown to OpenIPC's database, and the report is public: [OpenIPC camera report r-rxh32hs4](https://openipc.org/cameras/report/?id=r-rxh32hs4) (hardware, boot log, flash map, free areas, boot chain, U-Boot SD recovery, Wi-Fi interfaces, vendor media API).
- The flash-mode design follows OpenIPC's approach: a small read-only system, settings in a separate jffs2 partition, and nothing that needs the cloud.
- Anyone porting OpenIPC to the AK3918EV300 can reuse what is documented here: `src/tc100fix` (the vendor encoder and ISP API, run-time hooks), `src/flash` (rebuilding `/usr` from the camera's own files) and `scripts/flash-code.sh` (using the free end of the kernel partition).

Other projects this builds on: [anyka-software](https://github.com/ThatUsernameAlreadyExist/anyka-software) and [anyka-v4l2rtspserver](https://github.com/ThatUsernameAlreadyExist/anyka-v4l2rtspserver) (most of `bin/`, and the RTSP server), and the earlier Anyka hacks they come from.

---

## How it works

- **From the SD card**: the vendor's `service.sh` runs `/mnt/wifitest/wifi_test.sh` when that folder exists (a factory test hook) instead of the cloud app. It starts `autorun.sh`, which runs the firmware from a read-only, checksummed image on the card (`firmware.sqfs`), with the plain files as a fallback.
- **From flash**: the rebuilt `/usr` has the same `service.sh`, changed only where the cloud app started. With `/mnt/wifitest` on a card, the SD firmware starts as above. Without it, `scripts/flashboot.sh` rebuilds the same layout (`/mnt` in RAM, settings in jffs2, code from the code area or from `/usr/tc100`), then runs `autorun.sh`.
- **Code area**: a 4 KB header (`TC100CODE 1`, size, md5, version) and a squashfs. It is "pending" until the camera comes back with it, and a second boot without that confirmation returns to the code inside `/usr` (`scripts/flash-code.sh`).
- **RTSP server fixes**: `lib/libtc100fix.so` is preloaded into the vendor-API RTSP server. It adds a fixed frame rate, G.711 audio, a microphone off when unused, live ISP tuning, the light-level statistics, and the MP4 recorder (`src/tc100fix/rec.c`).
- **MQTT**: forged in shell and sent through `nc`, because the platform's curl cannot publish MQTT. One persistent connection.
- Platform notes (missing `tr`, old busybox `timeout`…) and the bugs fixed during the bring-up: [docs/known-issues.md](docs/known-issues.md). HTTP API: [docs/api.md](docs/api.md).

---

## Repository structure

```
autorun.sh          Boot entry point (SD card and flash)
VERSION             Firmware version
bin/ lib/           ARM binaries and libraries (SD card mode)
www/                Web interface; www/cgi-bin/ are shell CGIs
scripts/            Daemons and tools (flash-install.sh, flash-code.sh, flashboot.sh, wifi-txt.sh, rec-storage.sh…)
controlscripts/     Services, started and stopped from the web page
config/             Templates (*.dist) and boot scripts (config/autostart/)
wifitest/           The SD card boot hook
sounds/             Audio clips
src/flash/          Flash images: build-flash-kit.sh, build-usr.sh, build-code.sh, stage-tc100.sh, prebuilt/
src/release/        Release files: SD card zip, update .tar, code .bin
src/tc100fix/       libtc100fix (RTSP server hooks, MP4 recorder)
src/curl, src/lighttpd, src/wpa_supplicant   Builds with the Anyka uClibc toolchain
src/webui/          i18n check, Bulma purge, screenshot tool
tests/              python3 -m unittest discover -s tests; node --test tests/*.test.js
docs/               API, known issues, screenshots
```

Live configuration with secrets (`config/mqtt.conf`, `config/user.pwd`, `wpa_supplicant.conf`, certificates) is never in git; only the `*.dist` templates are.

---

*Local only. No cloud. Your camera, your network.*
