# Hardware variants and board profiles

The 3.0 firmware only writes to the flash of a camera it recognises. Cameras sold as TECKIN TC100 may differ from
the one it was developed on (sensor, Wi-Fi chip, flash chip, U-Boot), so each one is checked against the **board
profiles** in `v3/board/*.conf` before anything is written.

## Known variants

| Profile | Sensor | Wi-Fi (USB id) | Flash | U-Boot | Status |
|---|---|---|---|---|---|
| `tc100-f23-rtl8188fu` | SOI JX-F23, MIPI 2 lanes (id 0xf23) | Realtek RTL8188FU (0bda:f179) | XMC XM25QH64A, 8 MiB | 2013.10.0-AK_V3.0.05 | the author's two cameras, vendor firmware V1.1.41 |

Your camera is not in the table, or you do not know? Send its inventory (below): it changes nothing in the camera.

## The inventory

`v3/install/inventory.sh` reads, without writing anything:

| What | Stock firmware (Linux 3.4) | 3.0 (Linux 6.6) |
|---|---|---|
| Sensor | the sensor module loaded (`sensor_f22+f23+f28+f35+f37_mipi`), the tuning files | the id the kernel matched (`sensor id 0xf23` in its log) |
| Wi-Fi | USB vendor:product, driver | same |
| Flash | size and erase size from the partition table | same, plus JEDEC id and part name (`/sys/bus/spi/devices/spi0.0/spi-nor`) |
| U-Boot | version string, md5 of its 228 KiB, `bootcmd` | version and md5 with `?full=1` only (the 6.6 flash reads slowly) |
| Other | RAM, `mem=`, partition table, md5 of the stock root and `/usr`, LEDs, GPIO chips, I2C devices, U-Boot environment | same |

The report holds no MAC address (the `mac` partition is never read) and no Wi-Fi setting; in the U-Boot environment,
`ethaddr`, IP addresses, serial numbers and keys are replaced by `<hidden>`.

How to get it:
- **Vendor firmware or 2.x**: `tc100-<version>-inventory.zip` from the releases, unzipped to the root of a FAT32
  card. The card's `wifitest/wifi_test.sh` (the same hook as the full package, stopped by the file `INVENTORY-ONLY`)
  writes `tc100-inventory.txt` to the card, then the blue LED stays on. Nothing else happens.
- **3.0**: `http://<camera>/cgi-bin/inventory.cgi` (`?full=1` adds the U-Boot md5, about 15 s).

Then open a GitHub issue with the **Hardware inventory** template.

## The checks

`v3/install/hwcheck.sh INVENTORY` prints `board=<profile>` (exit 0) or `unknown: <what differs>` (exit 1):

- **sensor**: `SENSOR_ID` when the kernel logged an id, else the stock module `STOCK_SENSOR_MODULE`;
- **Wi-Fi**: `WIFI_USB`;
- **flash**: `FLASH_SIZE`, and `FLASH_JEDEC` or `FLASH_NAME` when the kernel reports them. With
  `HWCHECK_FLASH_ID=1` (the flash install) a chip the kernel did not identify is refused too.

Where they run:

| Step | What is written | Checks before writing |
|---|---|---|
| SD card hook on the stock firmware (`v3/install/stock-hook.sh`) | the 4 KiB U-Boot environment, once | board profile (stock sensor module, Wi-Fi, flash size); md5 of U-Boot, stock root and `/usr` (`v3/install/known-stock.txt`, several lines per key allowed) |
| Install to flash (`v3/install/install66.sh`) | kernel, initrd, stack, vendor | board profile with the sensor id of the 6.6 kernel and the flash chip identified |

The U-Boot md5 can be overridden by an expert (`tc100-3/ALLOW-OTHER-STOCK` on the card); the board profile cannot:
supporting a new variant means adding a profile.

## At each start of 3.0

`v3/autorun-linux66.sh` runs `inventory.sh --quick` into `/tmp/inventory.txt`, then `hwcheck.sh`, and links the
matching profile to `/tmp/board.conf` (name in `/tmp/board`). An unknown camera gets the first profile, and the flash
install refuses it. Today the profile gives:

- `ISP_CONF`, `ISP_STOCK_GLOB`: the sensor tuning file (copied from the camera by the hook, loaded at start);
- `IRCUT_DAY_GPIO`, `IRCUT_NIGHT_GPIO`, `IRCUT_PULSE_MS`: the IR-cut coil (`bin/setconf`; `boot.conf` still wins);
- `LED_*`, `WIFI_DRIVER`: recorded for the variants to come.

## Adding a variant

1. An inventory of the camera (issue), ideally with the stock flash dump kept by the owner (never published).
2. A kernel that drives it: a sensor of the F22/F23/F28/F35/F37 family is already in the 6.6 driver; another sensor,
   Wi-Fi chip or flash chip needs a driver first.
3. A new `v3/board/<name>.conf` with its identity and settings, and the md5 of its U-Boot and stock partitions in
   `v3/install/known-stock.txt`.
4. A first run with the serial console connected.
