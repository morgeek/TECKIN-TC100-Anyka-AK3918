# v3/linux66-sd: glue between the 3.0 web UI / scripts and the free stack

Inventory of this folder (updated 2026-11-06, 3.0.1-rc31). All files are shell scripts. In the flash image they sit in
`v3/linux66-sd/` of the user space (`/mnt/v3/linux66-sd/`); in SD trial mode they are copied from the card. Each file
starts with a comment that is the reference for its options. The RTSP control script is `controlscripts/rtsp-h26x`
(not in this folder).

| File | What it does | Who calls it |
|---|---|---|
| `boot-guard` | Safe mode after repeated short runs (flash mode): counts runs shorter than 300 s in `config/.boot-guard` (kept in the flash slots) and, after 3 in a row, raises `/tmp/safemode`; subcommands `start`, `ok`, `clear`, `status` | `v3/autorun-linux66.sh`, `v3/install/update66.sh`, `scripts/reboot-tracker.sh`, `console-timer`; shows in `devinfo.cgi` |
| `cfg-persist` | Keeps the user settings (`config/`) in the SPI flash slots `cfga` / `cfgb` (two slots, one written at a time, md5 checked); subcommands `restore`, `save`, `flush`, `daemon`, `status`, `saved` | `flashmode-prep.sh` (restore at boot), `scripts/housekeeper.sh`, `scripts/reboot-tracker.sh`, `boot-guard`, `v3/install/install66.sh`, `v3/install/update66.sh` |
| `console-timer` | The UART login prompt stays for 300 s after boot, then its getty is stopped if nobody is logged in; stays on with `SERIAL_CONSOLE=on` in `boot.conf` or in safe mode | `v3/autorun-linux66.sh`, `v3/S39tc100-linux66` |
| `flashmode-prep.sh` | Prepares the user space from the flash: `/mnt` as a RAM disk with links to the squashfs at `/rom`, settings restored from `cfga` / `cfgb` | `v3/S39tc100-linux66` (flash mode, `flashroot=1`), `v3/autorun-linux66.sh`, `v3/S50dropbear-linux66`; read by `cfg-persist` and `wizard.cgi` |
| `flashw` | The only flash writer: writes a file into one SPI partition from an allow-list (`cfga cfgb` by default, `FLASHW_ALLOW` adds others), with erase, read-back compare and md5; `boot`, `mac` and `env` are never touched | `v3/install/install66.sh`, `v3/install/update66.sh`, `v3/install/restore-stock.sh` |
| `net-apply` | Applies the IP settings of the Network page to `wlan0` (`config/network.conf`: DHCP or static; `config/dns.conf`: DNS servers) | `scripts/action.d/network.sh`, `v3/autorun-linux66.sh`, `wifi-apply` |
| `rtsp-launch.sh` | (Re)starts `tc100_rtsp` with the settings of `config/rtspserver.conf` (codec, bit rate, port, microphone gain); the RTSP login comes from `config/user.pwd` | `v3/autorun-linux66.sh`, `controlscripts/rtsp-h26x`, `controlscripts/onvif`, `controlscripts/sound-detection`, `scripts/action.d/video.sh` |
| `sdinfo-sd.sh` | Fills `/tmp/sd-card` and `/tmp/sd-health` from the card at `/mnt/sd` (status line, Recording page) | `scripts/action.d/storage.sh`, `scripts/web-guard.sh` (every minute), `scripts/housekeeper.sh`, `scripts/mqtt-bridge.sh`, `scripts/reboot-tracker.sh`, `scripts/sd-diag.sh`, `v3/autorun-linux66.sh` |
| `web-auth` | Writes `/etc/httpd.conf` for busybox httpd: the login (user `root`, password from `config/user.pwd`, stored as an MD5 crypt hash) and the media types; no password set (before the wizard) means no login line | `v3/autorun-linux66.sh`, `scripts/common_functions.sh`, `www/cgi-bin/action.cgi`, `www/cgi-bin/statelib.cgi` |
| `wifi-apply` | Uses `config/wpa_supplicant.conf` now: copies it, reloads or restarts `wpa_supplicant`, gets a new DHCP lease (run detached, with an optional delay) | `scripts/action.d/network.sh`, `scripts/net-guard.sh`, `scripts/wifi-country.sh`, `scripts/wifi-recover.sh`, `scripts/wifi-rescue.sh`, `v3/autorun-linux66.sh`, `www/cgi-bin/config_exchange.cgi`, `www/cgi-bin/wizard.cgi` |

Rules: flash writes go only through `flashw`, after a dump and with the owner's agreement for each partition write (see
`AGENTS.md`). Never run `controlscripts/<x> start | tail`: the daemon keeps the pipe open and a serial shell hangs.
