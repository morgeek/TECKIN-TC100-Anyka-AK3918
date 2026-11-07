Free firmware for the **TECKIN TC100** camera: Linux 6.6, RTSP H.264 / H.265 for Frigate or any NVR, MQTT / Home
Assistant, local web interface, no cloud. Read **"Is it safe?"** in the
[README](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918#is-it-safe) first.

## What is new in 3.0.1
- Runs from the camera's flash with **no SD card**; the card only holds recordings and saved logs.
- **The speaker works** (its amplifier was driven the wrong way round), and the camera's sounds no longer clip.
- **Night picture** from the sensor tuning's own night settings, **10 fps in low light** by day, anti-flicker
  (50 / 60 Hz, the camera default shown), the IR-cut pulsed as the stock firmware does.
- **Wi-Fi recovers by itself** when the chip fails to start after a reboot; Wi-Fi regulatory domain: pick your country in Settings → Network ("Country (Wi-Fi rules)", `WIFI_COUNTRY` in `boot.conf`), applied at once without reconnecting; settings changed just before a reboot are kept; the video server restarts by itself if it stops.
- **Native mDNS local discovery** (`tc100-mdnsd`) enabled out of the box (`<hostname>.local`).
- **100% free hardware H.265 / H.264 / JPEG video encoder** (`src/h265enc/freeenc.h` in `tc100_rtsp`, built against `musl`): drives the Anyka video ASIC directly without loading or copying any proprietary `.so` library (`1920x1080` and `1280x720` H.265/H.264 main stream + `640x360` H.264 sub-stream).
- **Native MQTT bridge in C** (`tc100-mqttd`) and **C supervisor** (`tc100-supervisord`) enabled by default (`MQTT_BRIDGE_IMPL=c` in `config/mqtt.conf`, `SUPERVISOR_IMPL=c` in `config/boot.conf`).
- **Fluid live video preview** powered by native MediaSource fMP4 across all dashboard and settings views.
- Plain HTTP on port 80 only (external TLS delegated cleanly to a reverse proxy).
- About 21 MB of free memory (was 10 MB in the first 3.0 builds), the clock and privacy masks drawn by the image
  processor, a 640x360 sub-stream from its own scaler.
- Bit rate mode (constant / variable), the stock firmware's day / night method as an option, IR LED protection.
- **Hardware test page** (Tools → Hardware test): the camera drawn from the front and the back, each part (lens, LEDs,
  IR-cut, microphone, speaker, microSD card, reset button) tested in one click.
- **Chime, alert and siren buttons** on the dashboard, next to Listen / Talk.
- **Full backup of the camera** (Backup page): every changed setting, secrets and ssh keys included, in one `.tar.gz`,
  and its restore.
- **Picture on events over MQTT** (`MQTT_SNAPSHOT_ON_EVENT=1` in `mqtt.conf`, off by default): a fresh JPEG goes to the
  broker on motion, sound or tamper (Home Assistant camera entity).
- **Prometheus metrics** at `http://<camera>/metrics` (video server rates, clients, microSD card, version).
- Web pages load their scripts and styles with a content stamp, so a browser takes the new files at once after an update.

## Install (copy to a card, power on)

1. Download `tc100-<version>-sd.zip` below.
2. Take a microSD card of **32 GB or less** and format it **FAT32** (bigger cards come as exFAT, which the camera cannot
   read: format them FAT32 with a tool such as Rufus or `guiformat` on Windows, Disk Utility "MS-DOS (FAT)" on macOS).
3. Unzip **into the root of the card**: the card must show `wifitest`, `tc100test`, `tc100-3`, `www`... directly, not
   inside a folder (Windows "Extract all" proposes a folder: remove the folder name from the path).
4. Camera never connected to Wi-Fi? Add a file `wifi.txt` at the root of the card with two lines:
   `SSID=your network` and `PASSWORD=its password`. A camera already on Wi-Fi (TECKIN app or 2.x) keeps its network.
5. Card in, power on. The **blue LED blinks** about 2 minutes while the camera saves its whole flash to the card,
   then it restarts. **Red LED on** = stopped, nothing written: the reason is in `tc100-3/STATUS.txt` on the card.
6. About a minute later the camera plays its **startup chime**. Open **http://tc100/** (or the address in your
   router, also written to `tc100-3/ADRESSE.txt` on the card), sign in as `root` / `pass` (or the password of your
   2.x camera). The setup wizard asks for a new password, and its last step installs the firmware into the camera
   in one click.
7. No chime and no page after 15 minutes (wrong Wi-Fi)? The camera opens its own rescue Wi-Fi (`TC100-<MAC>`,
   default password: `tc100rescue`). Connect to it and open http://10.42.0.1/ to configure your Wi-Fi.

Updates: Settings → Update & backup → Firmware update with `tc100-<version>-update.tar`.
Way back: [docs/linux-port/install-3.0.md](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/blob/main/docs/linux-port/install-3.0.md).

`MD5SUMS.txt` lists the checksums of the files below.
