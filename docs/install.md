# Installation guide

For camera owners, no programming needed. Français : [install.fr.md](install.fr.md). Back to the [README](../README.md).
Known problems: [known-issues.md](known-issues.md). Technical details of the install:
[linux-port/install-3.0.md](linux-port/install-3.0.md).

Each step says **what to do**, **what you should see**, and **what to do if not**.

Contents: [1. What you need](#1-what-you-need) · [2. Download and prepare the card](#2-download-and-prepare-the-card) ·
[3. First start (trial mode)](#3-first-start-trial-mode-nothing-written-to-the-flash) ·
[4. Setup wizard and password](#4-setup-wizard-and-password) · [5. Check that it works](#5-check-that-it-works) ·
[6. Install into the camera, update later](#6-install-into-the-camera-update-later) ·
[7. The way back](#7-the-way-back-to-the-original-firmware) · [8. Troubleshooting](#8-troubleshooting) ·
[9. Where to ask for help](#9-where-to-ask-for-help)

---

## 1. What you need

- A **TECKIN TC100** (TECKIN Click) camera. Only one hardware variant is known so far
  ([hardware variants](hardware-variants.md)). The card checks the camera first and writes nothing to a camera it does not
  recognise.
- A **microSD card of 32 GB or less**, formatted **FAT32**. Cards larger than 32 GB usually come as exFAT: format them
  FAT32 first (Rufus or `guiformat` on Windows, Disk Utility with "MS-DOS (FAT)" on macOS).
- A **computer** with a card reader, to copy files. Nothing to install on it.
- The camera on its power supply, within reach of your Wi-Fi. Know your Wi-Fi name and password.
- About 20 minutes the first time.
- Optional but wise: a **second microSD card** for recordings later (see step 6).

## 2. Download and prepare the card

1. **Download** `tc100-<version>-sd.zip` from the
   [releases page](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/releases) (`MD5SUMS.txt` lists the checksums). The
   release also holds `tc100-<version>-update.tar` (for later updates from the web page) and
   `tc100-<version>-inventory.zip` (only reads what your camera is made of).
2. **Format the card FAT32** (see step 1).
3. **Unzip the package into the root of the card.** On Windows, "Extract all" proposes a folder name: remove it.
4. **Camera never set up on Wi-Fi?** Create a text file named `wifi.txt` at the root of the card with two lines:
   ```
   SSID=your network name
   PASSWORD=its password
   ```
   A camera that already knows your Wi-Fi (TECKIN app, or an earlier version of this firmware) keeps its network.
5. **Trial mode (recommended for the first time):** create an **empty** file named `ESSAI.txt` (or `TRIAL.txt`) at the
   root of the card.

**What you should see:** the card shows directly the folders `wifitest`, `tc100test`, `tc100-3`, `www`... and the file
`00-LISEZ-MOI-READ-ME.txt` (the same steps in French and English).

**If not:** if you see one folder (for example `tc100-...-sd`) holding them, move its content up to the root of the card.
Not sure the camera is supported? Use `tc100-<version>-inventory.zip` instead (same steps; it only writes
`tc100-inventory.txt` to the card) and send that file with a *Hardware inventory* issue.

## 3. First start (trial mode, nothing written to the flash)

1. With the camera **switched off**, put the card in, then power it on.
2. **Leave it plugged in. Do not unplug it during the first two minutes.**

**What you should see:**
- **Blue LED blinking** for about 2 minutes: the camera saves a copy of its whole memory to the card
  (`tc100-3/backup/flash-stock.bin`: this is your way back), then restarts on the new firmware **from the card**.
- About a minute later, a **short chime**. In trial mode the firmware runs from the card only. The firmware itself is not
  written to the camera's memory: take the card out and restart, and the camera starts its previous firmware.
  (At the very start, one small entry is added once to the camera's boot settings so that it looks at the card first; the
  bootloader itself is never written.)
- Without the `ESSAI.txt` file the camera goes on by itself to install into its flash (step 6): blue LED blinking again for
  about 10 minutes, then a chime. Do not unplug it.

**If not:**
- *Nothing happens, no blue LED:* the files are not at the root of the card, or the card is not FAT32. Redo step 2.
- *Red LED on:* the camera stopped; either nothing was changed, or it runs the new firmware from the card with its flash not written. Read `tc100-3/STATUS.txt` on the card from a computer.
  "Not a TC100 variant the firmware knows" means the camera was left untouched: send `tc100-inventory.txt` in a
  *Hardware inventory* issue.

## 4. Setup wizard and password

1. Open **http://tc100/** in a browser on the same network. If that does not work, use the camera's address from your
   router's device list; it is also written in `tc100-3/ADRESSE.txt` on the card.
2. Sign in as user `root`. The **default password is public and is given in the first file of the zip**
   (`00-LISEZ-MOI-READ-ME.txt`) and in the release notes.
3. The **setup wizard** starts. Its steps:
   - **Language and Wi-Fi**: keep the current Wi-Fi or give another network.
   - **Integration profile**: *Standalone*, or *Frigate + Home Assistant* (recommended if you use them).
   - **Camera password**: **choose your own password** (one password for the web page, RTSP, FTP and telnet; at least 4
     characters, no spaces or quotes). Leaving it empty keeps the public default: do not.
   - **Frigate and Home Assistant** (only with that profile): MQTT broker address, port, optional user and password,
     optional Frigate address.
   - **Recording on the SD card**: when Frigate stops receiving the video (recommended), always, or off.
   - **Run without the SD card** (only when running from the card): *Install into the camera now* or *Not now*.
   - **Summary**, then **Apply and start**.
4. Write your new password in a password manager. Never put it in a public post or an issue.

**What you should see:** "Configuration applied", then the page reloads and asks you to sign in with the new password.

**If not:** a red message under the password means it is too short or contains a forbidden character. If you chose the
Wi-Fi step wrongly and lose the camera, see the Wi-Fi item in [troubleshooting](#8-troubleshooting). You can restart the
wizard later (*Restart setup wizard* in Settings).

> While the default password is active, the dashboard shows a red **"Security: default password"** banner. It goes away
> when you change the password in Settings → System → Password.

## 5. Check that it works

- **Web page:** the Dashboard shows the live picture (in trial mode the first picture may take a moment). The *Live view*
  page and *Multi-View* show it too.
- **RTSP:** open this address in VLC (Media → Open Network Stream), with user `root` and your password:
  - main stream: `rtsp://CAMERA-IP:554/video0_unicast`
  - sub-stream: `rtsp://CAMERA-IP:554/video1_unicast`
- **Frigate:** Live view → More tools → Diagnostics gives a configuration to paste. It never holds the camera password:
  set the `FRIGATE_RTSP_PASSWORD` variable in Frigate's environment. Give every camera its own name (Settings → Network →
  Hostname).
- **Home Assistant:** with the MQTT profile, the camera appears by itself through MQTT discovery.

**If not:** no picture in VLC: check the address, the password, and that the camera and the computer are on the same
network. A slow page for a few seconds is normal on this single-core camera. More in [troubleshooting](#8-troubleshooting).

## 6. Install into the camera, update later

**Why install?** In trial mode the firmware runs from the card, so it stops if the card is removed and **web updates are
not possible**. Installing writes it into the camera's own memory: the camera then runs without the card (the card is
only for recordings) and updates from the web page.

**What is written, and what never is.** Written: the kernel, the free system, a copy of the camera's own libraries
(taken from your camera, never published), and the settings area. **Never written:** the bootloader (U-Boot), the radio
data (`mac`). Each part is saved to the card first and read back after writing.

**How to install:**
- Without `ESSAI.txt`, the card installs by itself after the checks (step 3). Nothing to click.
- In trial mode, choose *Install into the camera now* in the wizard, or later go to **Settings → Update & backup → Install
  to flash (run without the SD card)** and press **Install to flash and restart**. It takes about 6 to 10 minutes. **Do
  not unplug the camera.**

**What you should see:** a chime, then the web page again. The card is no longer needed to start the camera.

**If not:** red LED and `tc100-3/STATUS.txt` giving the reason: nothing was changed in the flash, the camera runs from the
card and the web page can retry. An install that is interrupted (power cut) leaves the flash unable to start: keep the
card, it starts the camera again and *Install to flash* writes everything again.

**Recordings after the install.** A card that still holds the install files (`wifitest`, `uImage`...) is **refused for
recording** (it would make the stock firmware boot from it). Keep the install card as your way back, and use a second
card for recordings (FAT32 or exFAT). Insert it with the camera switched off: a card inserted while it runs is not
detected.

**Updating later (no SD card needed):**
1. Download `tc100-<version>-update.tar` from the [releases page](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/releases).
2. Open **Settings → Update & backup → Firmware update**, press **Choose...**, pick the file, then **Upload & check**.
3. When the check passes, press **Install & reboot**. Wait for the camera to restart (several minutes). Do not unplug it.

Your settings are kept. Take a **Full backup** (same page) before big changes.

**If it refuses:** "Running from the SD card (trial)": install into the flash first. "Not enough free memory": put a FAT32
card in the camera and upload again. An update interrupted midway needs the card, as above.

## 7. The way back to the original firmware

Keep the card and its `tc100-3/backup/flash-stock.bin` (never share it: it is a copy of your camera's memory).

1. Power off, take the card, put it in a computer.
2. Rename `tc100test/c66.img.installed` to `c66.img`.
3. Create an empty file `RESTAURER.txt` (or `RESTORE.txt`) at the root of the card.
4. Card in the camera, power on. The blue LED blinks about 10 minutes while the camera writes its original firmware back,
   then it restarts into it. **Do not unplug it.**
5. Take the card out.

If you only tried the firmware in trial mode, just take the card out and restart. The restore refuses a copy that does not
match your camera, and the bootloader is never touched.

## 8. Troubleshooting

| Problem | What to do |
|---|---|
| **Camera not found on the network** | Wait 15 minutes the first time. Try `http://tc100/`, then the address from your router's device list or `tc100-3/ADRESSE.txt` on the card. Browsers or networks that do not resolve names: use the IP address. |
| **Wi-Fi does not connect** | Check `wifi.txt` (two lines, exact spelling; an invalid file is renamed `wifi-invalid.txt` with the reason). After 10 minutes without Wi-Fi, or with the reset button held 3 to 7 seconds, the camera opens its own **rescue Wi-Fi** `TC100-<MAC>` (its default password is in `00-LISEZ-MOI-READ-ME.txt`). Join it and open `http://10.42.0.1/` to enter your network. Settings → Network also has a country setting for Wi-Fi rules. |
| **Nothing happens at the first start, no blue LED** | Files not at the root of the card, or card not FAT32. |
| **Red LED on** | Read `tc100-3/STATUS.txt` on the card. Details in steps 3 and 6. |
| **Card refused for recording** | The card carries boot files (`wifitest`, `uImage`, `root.sqsh4`...). Use another card for recordings, or a card without them. |
| **Red banner "Security: default password"** | Change the password: Settings → System → Password. |
| **Slow first start or slow pages** | The first start takes 15 minutes in all with the install. In normal use, some pages take a few seconds on this single-core camera. In the first minute after a boot the network may not answer yet. |
| **Safe mode** | After 3 runs in a row that ended within 5 minutes (crash, watchdog), the next start only brings up Wi-Fi, the web page, ssh and the reset button; no video or MQTT. The Information page says "SAFE MODE". Use the web page to update or fix the cause, then restart once the camera has run 5 minutes. Restarts from the web page or the reset button do not count. |
| **Camera does not come back after an update** | Start it with the 3.0 card (without `ESSAI.txt` if you want to reinstall) and use *Install to flash*. |
| **Something else** | See [known-issues.md](known-issues.md), then ask (next section). |

## 9. Where to ask for help

- Read [known-issues.md](known-issues.md) and the [README](../README.md).
- Open an issue at <https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/issues/new/choose>. Say what you did, what
  you saw, the firmware version (Information page) and, if you can, the end of `tc100-3/STATUS.txt`.
- **Never post** your password, your Wi-Fi password, MQTT or RTSP credentials, or `tc100-3/backup/flash-stock.bin`.
