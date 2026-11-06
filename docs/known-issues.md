# Known issues and platform notes

Moved out of the README in 2.0.0. History of every fix: [CHANGELOG.md](../CHANGELOG.md).

## 3.0 (Linux 6.6)

State of 3.0.1 (rc31, 6 November 2026, two cameras of the same variant; the rc31 checks on the cameras are pending;
details and results in
[linux-port/test-queue.md](linux-port/test-queue.md)):
- **Colours:** slightly warm; the software white balance of the video server corrects them (on by default). The
  image processor's own white balance on its live statistics gave a blue cast and is not used
  (`ak_isp.awb_live=1` to try it).
- **Wi-Fi after a warm reboot:** the Wi-Fi chip sometimes failed to power on (no `wlan0`). 3.0.1 recovers it by
  itself (`scripts/wifi-recover.sh`: probe again, power cycle through GPIO 11, one clean restart if needed); a power
  cut remains the last resort.
- **Speaker:** works; quiet at a low volume (Settings, the speaker volume). Push-to-talk and two-way audio are not yet
  checked on a camera.
- **Day / night:** the picture luminance decides by default; the exposure index and the stock firmware's method are
  options (Settings, Day/night) whose thresholds still need a night of readings.
- **Memory:** about 21 MB free with the 9600K encoder pool; the encoder's smart mode needs 3.4 MB more and is off.
- **Logs with no SD card:** the web page (Logs) or ssh; the saved logs need a card.
- **Picture right after a boot:** once (rc20) the picture stayed almost white for several minutes after a reboot,
  then the exposure settled by itself. Not seen again since (owner, 2026-11-04): treated as an isolated case.
- **Wi-Fi in the first minute after a boot:** the gateway may not answer yet (100 % loss seen once at 1 min of
  uptime); it settles within a few minutes. After 3.0.1-rc24 the services script no longer restarts the DHCP client at
  boot (it dropped the address meanwhile); to be confirmed on the cameras.
- **Wi-Fi country:** without a country (Settings → Network), the Wi-Fi follows the "world" rules: channels 12-13
  passive and a lower transmit power. Up to 3.0.1-rc24 the firmware has no rules database at all.
- **Frame rate in low light:** by day in low light the camera drops to 10 fps on purpose (brighter picture); Frigate
  and NVRs see 10 fps during that time.
- **MQTT and Telegram settings:** the MQTT user / password and the Telegram token / chat id cannot hold spaces,
  quotes or `$ ` \ ; & | < > ( )` (the files that hold them are read by shell scripts). Use other characters.
- **JSON configuration import:** the camera measured 10-20 s on rc31 (about 120 values); main now skips flash-mode
  global syncs and rollback copies for unchanged files. The new import time and capture rate still need camera measurement.
- **Some pages answer slowly on cache misses** (the first Services scan and Settings configuration read were measured
  at several seconds on the single-core CPU). Main now caches short-lived read responses and refreshes stale Services
  state in the background; cold and warm timings still need camera measurement.
- The feature audit of 2026-10-26 ([linux-port/feature-audit-2026-10-26.md](linux-port/feature-audit-2026-10-26.md))
  is history: most of what it lists was fixed in the 3.0.1 release candidates.

The 2.x-era notes (remote syslog 2.1.5, reading the camera logs 2.1.2, the 2026 bring-up fixes, the `tr(1)` platform constraint of the 2.x busybox) moved to [linux-port/history.md](linux-port/history.md#2x-known-issues-history).
