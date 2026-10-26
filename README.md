# TECKIN TC100 — alternative firmware

Local-only firmware for the **TECKIN TC100 / TECKIN Click** indoor camera
(Anyka AK3918EV300). It replaces the cloud application with RTSP streams for
Frigate or any NVR, MQTT and Home Assistant discovery, a French / English web
interface, recording on the SD card when the network fails, and updates from
the browser. Nothing needs the internet, and no vendor file is published.

Since **2.0** it runs **from the camera's own flash memory**, with no SD card
at all: the card becomes optional, for recordings only. The SD card mode of
earlier versions is still there and is the way in. The web interface is laid
out after [OpenIPC's](https://openipc.org/web-interface): a dashboard with live
graphs, settings in a sidebar with a search box, and a dark theme.

**3.0** is the same firmware on a free, recent kernel (Linux 6.6) instead of the vendor's 3.4, with
free drivers for the hardware video encoder (H.264, H.265, JPEG) and a free RTSP server, no vendor daemon
and no cloud. It runs from an SD card (trial) or **entirely from the camera's SPI flash**, installed from the
card without a serial console. **3.0.1-rc1 is a release candidate not yet run on a camera**: see
[What's new in 3.0](#whats-new-in-30) and [Is it safe?](#is-it-safe).

It started from [the original TC100 SD-card hack](#where-it-comes-from) and
grew from there.

![Dashboard](docs/screenshots/dashboard-dark.png)

<sub>Every screenshot shows a test pattern instead of the camera image, and example addresses.</sub>

---

## Contents

- [What you can do](#what-you-can-do)
- [What's new in 3.0](#whats-new-in-30)
  - [Try it from the SD card, then install it](#try-it-from-the-sd-card-then-install-it-no-serial-console)
  - [Is it safe?](#is-it-safe)
- [What's new in 2.0](#whats-new-in-20)
- [Screenshots](#screenshots)
- 2.x: [Step 1: run from the SD card](#step-1-run-from-the-sd-card)
- 2.x: [Step 2: the setup wizard](#step-2-the-setup-wizard)
- 2.x: [Step 3 (optional): install to flash, run without the card](#step-3-optional-install-to-flash-run-without-the-card)
- [Updates](#updates)
- [Home Assistant and Frigate](#home-assistant-and-frigate)
- [Recording on the SD card](#recording-on-the-sd-card)
- [Wi-Fi, passwords, safety](#wi-fi-passwords-safety)
- [The hardware, and OpenIPC](#the-hardware-and-openipc)
- [Where it comes from](#where-it-comes-from)
- [How it works](#how-it-works)
- [Repository structure](#repository-structure)

---

## What you can do

**Video**
- Two RTSP streams: main up to 1080p H.264 / H.265, and a sub-stream for detection (`rtsp://CAMERA-IP:554/video0_unicast` and `video1_unicast`), which can be turned off when no recorder uses it. ONVIF (discovery and profiles, port 8081) in both modes: off by default, Services → Services → onvif.
- A choice of RTSP server (Settings → Video): the original one, or a **lite server** that sends the same streams for about 8 points less CPU, with the sound and two-way audio.
- **Privacy masks**: up to 4 areas painted out by the image processor before encoding, so they are absent from every stream, snapshot and recording.
- Presets for Frigate (light, balanced, quality), live image tuning (brightness, contrast, sharpness, saturation, anti-flicker, exposure cap) with no stream restart, a fixed frame rate, day / night with the IR LEDs and the IR filter, flip and on-screen text.
- Still JPEG at `cgi-bin/currentpic.cgi`: the last picture the camera already encodes (one a second), served as it is, so Home Assistant polling costs nothing.

**Home Assistant, Frigate, NVRs**
- MQTT with Home Assistant discovery: about 30 entities (Wi-Fi signal, memory, light level, sound level, night mode, SD card, RTSP clients, LEDs, profile…), commands from Home Assistant, availability. An *Unexpected Restart* sensor turns on after a restart nobody asked for (watchdog, power loss), ready for a notification.
- A Frigate configuration ready to paste (Live view → More tools → Diagnostics, or `state.cgi?cmd=frigateyaml`), and a button that opens the camera in Frigate's smooth live view.
- Any RTSP NVR works: Blue Iris, Synology Surveillance Station, iSpy, go2rtc…

**Recording**
- MP4 files on the SD card, copied from the video the camera already encodes (no re-encoding, about 4.5 % CPU). By default only **while Frigate does not receive the video**, with a few seconds before and after, so a network or Frigate outage leaves no gap. "Always" is available too. FAT32 and exFAT cards.

**Audio**
- Listen live, talk through the speaker (push-to-talk from the browser), sound detection with a level in dBFS.
- **Two-way audio from Home Assistant, Frigate or go2rtc** (lite server): their microphone button plays your voice on the camera's speaker. Setup: [docs/two-way-audio.md](docs/two-way-audio.md).

**Detection**
- The camera's own motion detection (MQTT event, picture on motion) is **off by default**: Frigate does the detection. When it is on, **motion zones** tell it which areas to ignore.

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

## What's new in 3.0

> **Status: 3.0.1-rc1 is a release candidate that has not yet run on a camera.** The author's camera runs the
> 3.0.0 core (kernel, video, RTSP, web interface) from flash since 2026-10-24; the install from an SD card, the
> sub-stream, the recorder and the 3.0 versions of the web pages were written on 2026-10-26 and checked in Docker
> only. Read [Is it safe?](#is-it-safe) before you try it. The 2.x firmware above stays available.

Linux 6.6 with free drivers, the hardware video encoder and a root filesystem that fits the 8 MB flash, with the
SD card optional. It serves a 1080p H.265 (or H.264) RTSP stream at 15 fps with the microphone and a 640x360
sub-stream, the web interface with a login, MQTT / Home Assistant, ONVIF, motion and sound detection, day / night,
and recordings on the card.

- **Linux 6.6 port** of the AK3918EV300 as a series of patches on the `v6.6` tag
  ([patches/kernel-6.6/series](patches/kernel-6.6/series/README.md)): CPU, interrupts, timer, console,
  SD card, USB host, Wi-Fi (mainline `rtl8xxxu`, access point included), GPIO, I2C, watchdog, audio, **video**
  (V4L2 driver for the JX-F23 sensor and the ISP), the hardware video encoder (`ak39_venc`) and a **SPI NOR
  driver that can write** (4 KiB erase, partitions in the device tree). CI builds the kernel on every push.
- **Hardware video encoder on a free driver** (`ak39_venc`, `src/libakuio`): H.264 and H.265 are made by the
  vendor encoder control libraries running on the free driver; JPEG is fully free code (`src/jpegenc`). The
  H.265 command lists are reproduced offline (`src/h265enc`), not yet used on the camera.
- **`tc100_rtsp`** (`src/tc100rtsp`): main stream and 640x360 sub-stream (`video1_unicast`), RTSP over TCP or UDP,
  G.711 audio, Digest/Basic login, image tuning, privacy masks, OSD clock, black and white, the web pictures from
  the hardware JPEG engine, motion with zones, the microphone level, and **recordings** in fragmented MP4 with a
  thumbnail (`/mnt/DCIM/YYYY-MM-DD_HH-MM-SS.mp4`; a cut file plays up to its last second; no ffmpeg).
- **Runs from flash, SD card optional**: kernel, xz initramfs and a squashfs user space in the SPI flash, settings
  in two alternating flash slots (`cfga` / `cfgb`). A card is only for recordings.
- **Built from git, nothing vendor published**: CI makes the SD package and the web update from free files only;
  the few vendor libraries 3.0 needs (the uClibc runtime and the encoder control libraries) are copied from each
  camera into its own `vendor` partition.
- **Every web page on 3.0**, or hidden with a note where the hardware cannot do it (RTSP server choice, two-way
  audio, sharpness, card formatting...). Feature by feature:
  [feature audit](docs/linux-port/feature-audit-2026-10-26.md).

### Flash layout (8 MiB, 4 KiB sectors)

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

### Try it from the SD card, then install it (no serial console)

For a TECKIN TC100 with the vendor firmware V1.1.41, or with the 2.x firmware of this project installed in its
flash. Download `tc100-<version>-sd.zip` from the [releases](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/releases)
(each tag `v3...` publishes one; between releases, the CI artifact `tc100-3-release`).

1. **The card**: microSD of **32 GB or less, FAT32** (bigger cards come as exFAT, which the camera cannot read:
   format them FAT32 with Rufus or `guiformat` on Windows, Disk Utility "MS-DOS (FAT)" on macOS). Unzip **into the
   root** of the card: it must show `wifitest`, `tc100test`, `tc100-3`, `www`... directly, not inside a folder
   (Windows "Extract all" proposes one). `00-LISEZ-MOI-READ-ME.txt`, first in the zip, says the same in French and
   English.
2. **Wi-Fi**: a camera already on Wi-Fi (TECKIN app or 2.x) keeps its network. One that never was needs a `wifi.txt`
   at the root of the card: `SSID=your network` and `PASSWORD=its password` on two lines.
3. **Power on with the card in.** The running firmware starts the card's `wifitest/wifi_test.sh` once, with the
   **blue LED blinking** (about 2 minutes). It:
   - checks the camera (partition table, the stock or 2.x `/usr`, the U-Boot environment);
   - **saves the whole flash to the card** (`tc100-3/backup/flash-stock.bin`: keep it, never publish it);
   - copies the camera's libraries, settings and Wi-Fi to the card;
   - adds the 3.0 start commands to the U-Boot environment (the stock start stays as the fallback) and restarts.

   Any doubt: nothing is written, the **red LED** stays on and `tc100-3/STATUS.txt` says why.
4. **3.0 runs from the card** (trial mode) and plays a **chime** when it is ready. Open **http://tc100/** (or the
   address your router shows, also written to `tc100-3/ADRESSE.txt` on the card), user `root`, the password of your
   2.x camera or `pass`. The setup wizard asks for a new password, and its last step offers
   **"Install into the camera now"** (one click), or "Not now" to try first. Nothing of 3.0 is in the flash yet:
   without the card the camera starts the system it had before.
   No chime or page after 15 minutes (wrong Wi-Fi)? Power off and read `tc100-3/ADRESSE.txt`: it gives the name and
   password of the camera's rescue Wi-Fi, page at http://10.42.0.1/.
5. **Install to flash** (from the wizard, or Settings → Update & backup → Install to flash): about 10 minutes, every
   partition saved to the card first and read back after writing, then the camera restarts from its flash and the
   card only holds recordings.
6. Later versions: **Firmware update** on the same page, with `tc100-<version>-update.tar`.

Way back: a card with `tc100test/c66.img` always starts first; from there `v3/install/restore-stock.sh` writes back
the flash as it was before 3.0 from `flash-stock.bin`. Details, the U-Boot commands, and the move of cameras installed
by hand before 2026-10-26: [docs/linux-port/install-3.0.md](docs/linux-port/install-3.0.md).

### Is it safe?

Not yet proven: **nothing of the SD install has run on a camera.** Use it only if you can live with opening the
camera to reach its serial console in the worst case below.

What protects you:
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
2. **Cameras that differ from the author's.** Until `v3/install/known-stock.txt` lists the md5 of U-Boot and of the
   stock root filesystem, a TC100 with another U-Boot passes the checks. The 3.0 start commands then fall back to
   the stock start if they fail, but this has not been seen on another U-Boot.
3. **An interrupted web update** leaves the flash system unable to start: keep the 3.0 SD card; it starts the
   camera and "Install to flash" writes everything again.

Other limits: settings are kept in flash, the user space is read-only (updated as a whole); a card inserted while
the camera runs is not detected (power it off and on); the default password `pass` is public until you change it.

Notes, hardware facts, status and how to build: [docs/linux-port](docs/linux-port/README.md).

## What's new in 2.0

- **Runs without an SD card.** The firmware is installed into the camera's flash memory, from the card, in three guided steps (below). The vendor's U-Boot, kernel and root file system are not touched. Only the `/usr` partition is replaced (cloud app removed, firmware added), and the code goes into the free end of the kernel partition.
- **Updates from flash** with a small code package (`tc100-code-<version>.bin`, about 350 KB): written, read back, kept only if the camera comes back on the network, rolled back automatically otherwise.
- **Recording on the SD card** when Frigate stops receiving the video (or always), with pre- and post-roll.
- **New interface**: settings grouped by use (Image, Video, Day/night, Audio, Detection, Recording, Integrations, Network, System, Update & backup), camera controls under the live image.
- **New wizard**: language and Wi-Fi, profile, web access, Frigate and MQTT, recording, install to flash.
- **Wi-Fi from a text file** (`wifi.txt`), and a fallback network kept on every change.
- Password card, exFAT cards for recording, HTTP fallback and a rescue telnet when the web server cannot start from flash.

Full list: [CHANGELOG.md](CHANGELOG.md).

---

## Screenshots

| | |
|---|---|
| ![Dashboard, light](docs/screenshots/dashboard.png) Dashboard, light theme | ![Live view](docs/screenshots/live-view-dark.png) Live view |
| ![Settings, image](docs/screenshots/settings-image.png) Settings → Image: live tuning | ![Recording](docs/screenshots/settings-recording.png) Settings → Recording |
| ![Integrations](docs/screenshots/settings-integrations.png) Settings → Integrations: MQTT and Home Assistant | ![Update](docs/screenshots/settings-update.png) Update & backup, from flash |
| ![Install to flash](docs/screenshots/settings-install-to-flash.png) Install to flash, from the SD card | ![System](docs/screenshots/settings-system.png) Settings → System |
| ![Services](docs/screenshots/tools-services.png) Services → Services | ![Diagnostics](docs/screenshots/tools-diagnostics.png) System → Diagnostics |
| ![Logs](docs/screenshots/tools-logs.png) System → Logs | ![Search](docs/screenshots/settings-search.png) Settings search |
| ![Config editor](docs/screenshots/tools-configeditor.png) System → Config editor | |
| ![Dark, French](docs/screenshots/settings-dark-fr.png) Settings in French | ![Phone](docs/screenshots/dashboard-mobile.png) On a phone |
| ![Live, light](docs/screenshots/live-view.png) Live view, light theme | ![Phone settings](docs/screenshots/settings-mobile.png) Settings on a phone |

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
| the **flash** (FLASH badge) | `tc100-system-<version>.tar` | the programs in `/usr` **and** the code, without SD card (see below). |
| the **SD card** | `tc100-update-<version>.tar` | every file checked against its md5, only changed files replaced, the previous ones kept for "Roll back". |

The programs in `/usr` (RTSP server, web server, curl, ONVIF) change with a **system package**: `src/flash/build-flash-kit.sh` writes `tc100-system-<version>.tar` next to the install kit, from the `usr-stock.img` saved at step 1 (it holds the vendor's programs, so it is never in a release). Upload it in Update & backup: the camera checks it (same original `/usr`, image intact, the files a boot needs), pauses the video, then stops every program that runs from `/usr` (Wi-Fi included), writes `/usr` and the code, reads them back and restarts — about 3 minutes without the camera. With an SD card carrying the firmware in the slot, the camera sets it aside for one boot so that the new system is what starts. If something cannot be stopped, nothing is written.

Build them yourself: `sh src/release/build-code-package.sh` and `sh src/release/build-update.sh` (no cross toolchain needed). CI attaches all three files (`.zip`, `.tar`, `.bin`) to each `v*` release.

---

## Home Assistant and Frigate

1. Wizard (or Settings → Integrations): profile **Frigate + Home Assistant**, MQTT broker address and login.
2. **Give each camera its own name** (Settings → Network → Hostname). It names the Home Assistant device and the MQTT topics (`CAMERA1` → `camera1/…`). Two cameras with the same name merge into one device.
3. Home Assistant finds the camera through MQTT discovery. The device page shows the firmware version.
4. Frigate: Live view → More tools → Diagnostics gives a configuration to paste (go2rtc restream; `state.cgi?cmd=frigateyaml&redact=1` without the password). Streams:
   - main (recording): `rtsp://root:PASSWORD@CAMERA-IP:554/video0_unicast`
   - sub (detection): `rtsp://root:PASSWORD@CAMERA-IP:554/video1_unicast`
   - The same addresses work with either RTSP server. With the lite server, go2rtc also gets the speaker: two-way audio from Home Assistant's, Frigate's or go2rtc's microphone button ([docs/two-way-audio.md](docs/two-way-audio.md)).
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
- **HTTPS** with an ECDSA certificate made by the camera (10 years). From flash, if HTTPS cannot start, the page falls back to HTTP and an **HTTP** badge shows it in the top bar; HTTPS is tried again at the next restart.
- **Rescue access**: when no web port answers, the web server is restarted once; if that does not help, a rescue telnet opens on port 23, and it closes again by itself once the web interface has been back for two minutes.
- **SD card health**: kernel errors, a read-only card, and a write/read-back test after each boot and every day. A card that garbles writes shows "failing: replace it" under the live view and in Home Assistant ("SD Card Problem", "SD Card State").
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

The Linux 6.6 port, the OpenIPC boot kit and the Thingino port are described in [docs/linux-port](docs/linux-port/README.md).

Other projects this builds on: see [Where it comes from](#where-it-comes-from).

---

## Where it comes from

Full list of projects and licences: [CREDITS.md](CREDITS.md).

- **The original hack.** This project began in February 2026 as a copy of
  [TECKIN-TC100-Anyka-AK3918-camera-hacks](https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks)
  by **ThatUsernameAlreadyExist**: an SD card that takes over the camera through
  the vendor's factory test hook (`wifitest/`), without changing the firmware,
  and gives it RTSP, a web interface, FTP and telnet instead of the cloud app.
  Everything here grew from that card: same hook, same RTSP server
  ([anyka-v4l2rtspserver](https://github.com/ThatUsernameAlreadyExist/anyka-v4l2rtspserver)),
  same tools ([anyka-software](https://github.com/ThatUsernameAlreadyExist/anyka-software)).
  Thanks to its author, and to the earlier Anyka camera hacks it built on.
- **OpenIPC.** [OpenIPC](https://openipc.org) is the reference open firmware for
  IP cameras, and the model for where this project went: the flash-mode design
  (a small read-only system, settings in their own partition, nothing that needs
  the cloud) and the layout of the web interface
  ([OpenIPC web interface](https://openipc.org/web-interface)). This camera is not
  supported by OpenIPC; what was learnt about it is shared with them (see
  [The hardware, and OpenIPC](#the-hardware-and-openipc)).
- **From there to here**: Home Assistant and Frigate integration, a fixed frame
  rate and live image tuning inside the RTSP server, push-to-talk, recording when
  Frigate is down, updates from the browser with rollback, then the install to
  flash that removes the need for the SD card (2.0), and the new interface.
  The whole history is in [CHANGELOG.md](CHANGELOG.md).

## How it works

- **From the SD card**: the vendor's `service.sh` runs `/mnt/wifitest/wifi_test.sh` when that folder exists (a factory test hook) instead of the cloud app. It starts `autorun.sh`, which runs the firmware from a read-only, checksummed image on the card (`firmware.sqfs`), with the plain files as a fallback.
- **From flash**: the rebuilt `/usr` has the same `service.sh`, changed only where the cloud app started. With `/mnt/wifitest` on a card, the SD firmware starts as above. Without it, `scripts/flashboot.sh` rebuilds the same layout (`/mnt` in RAM, settings in jffs2, code from the code area or from `/usr/tc100`), then runs `autorun.sh`.
- **Code area**: a 4 KB header (`TC100CODE 1`, size, md5, version) and a squashfs. It is "pending" until the camera comes back with it, and a second boot without that confirmation returns to the code inside `/usr` (`scripts/flash-code.sh`).
- **RTSP server fixes**: `lib/libtc100fix.so` is preloaded into the vendor-API RTSP server. It adds a fixed frame rate, G.711 audio, a microphone off when unused, live ISP tuning and privacy masks, the light-level statistics, motion zones (`md.c`), the MP4 recorder (`rec.c`) and the lite RTSP server (`rtsp.c`).
  - The vendor program still drives the sensor, the encoders, day/night and the on-screen text, so it keeps running.
  - With the lite server it only listens on a spare port (`RTSP_VENDOR_PORT`).
- **MQTT**: forged in shell and sent through `nc`, because the platform's curl cannot publish MQTT. One persistent connection.
- Platform notes (missing `tr`, old busybox `timeout`…) and the bugs fixed during the bring-up: [docs/known-issues.md](docs/known-issues.md). HTTP API: [docs/api.md](docs/api.md).

---

## Repository structure

```
autorun.sh          Boot entry point (SD card and flash)
VERSION             Firmware version
bin/ lib/           ARM binaries and libraries (SD card mode)
www/                Web interface; www/cgi-bin/ are shell CGIs
scripts/            Daemons and tools (flash_budget.py, flash-install.sh, flash-code.sh, flashboot.sh, wifi-txt.sh, rec-storage.sh…)
  action.d/         The web commands of www/cgi-bin/action.cgi, one file per group
controlscripts/     Services, started and stopped from the web page
config/             Templates (*.dist) and boot scripts (config/autostart/)
wifitest/           The SD card boot hook
sounds/             Audio clips
src/flash/          Flash images: build-flash-kit.sh, build-usr.sh, build-code.sh, stage-tc100.sh, prebuilt/
src/release/        Release files: SD card zip, update .tar, code .bin
src/tc100fix/       libtc100fix (vendor server hooks, lite RTSP server, MP4 recorder, ISP tuning, motion zones)
src/netacl/         libnetacl: local-network-only filter on accept() for the web server, telnet, FTP and RTSP
src/curl, src/lighttpd, src/wpa_supplicant   Builds with the Anyka uClibc toolchain
src/webui/          Web UI sources: index/ (main script, built by build-index.sh), i18n check, Bulma purge, screenshots
tests/              python3 -m unittest discover -s tests; node --test tests/*.test.js
docs/               API, known issues, screenshots; docs/linux-port: Linux 6.6 port, flash budget, OpenIPC and Thingino notes
patches/kernel-6.6/ Linux 6.6 patch series (series/), kernel config
src/libakuio/       Free replacement for the vendor encoder-memory library (3.0, experimental)
src/jpegenc/        Hardware JPEG encoder tool and tables (3.0, experimental)
src/h265enc/        H.265 command-list generator and register-sequence model (3.0, experimental)
v3/                 Linux 6.6 user space: autorun, initramfs and flash root builders, self-test
contrib/             Not used by the build: OpenIPC SD boot kit (Linux 4.4, RAM only)
v3/buildroot/       Our base root filesystem (Buildroot, musl)
thingino_port/      Thingino board support for the TC100
```

Live configuration with secrets (`config/mqtt.conf`, `config/user.pwd`, `wpa_supplicant.conf`, certificates) is never in git; only the `*.dist` templates are.

---

*Local only. No cloud. Your camera, your network.*
