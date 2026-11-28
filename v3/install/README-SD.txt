TECKIN TC100 firmware 3.0 (Linux 6.6): SD card package
=========================================================

Tested on two TC100 cameras of the same variant (October 2026). Read "Is it safe?" in the project README
first. Do not unplug the camera during the install (about 15 minutes).

Made for the TECKIN TC100 indoor camera (Anyka AK3918EV300, JX-F23 sensor, RTL8188FU Wi-Fi) with the
vendor firmware V1.1.41, or with the 2.x firmware of this project installed into its flash. The camera
checks this before it changes anything. Settings and Wi-Fi of a 2.x camera are carried over.

What it does, step by step
--------------------------
1. Copy everything in this zip to the root of a FAT32 microSD card of 32 GB or less (not into a folder: the
   card must show wifitest, tc100test, tc100-3, wifi.txt... directly; see 00-LISEZ-MOI-READ-ME.txt).
   Edit wifi.txt at the root (SSID=your network and PASSWORD=its password) if needed; left untouched with empty
   values, it is ignored cleanly. A camera already on Wi-Fi (TECKIN app, or 2.x) keeps its network; in SD trial
   mode (ESSAI.txt) on a camera already running 3.0.x, Wi-Fi is read-only imported from the flash slots as a
   fallback when the card has no wpa_supplicant.conf (SD_FLASH_WIFI=1 in config/boot.conf; wifi.txt always wins).
   Always eject the card safely on your computer before removing it.
2. Put the card in the camera (powered off) and power it on. The stock firmware runs wifitest/wifi_test.sh,
   which:
   - checks the camera (partition table, the stock /usr of firmware V1.1.41, U-Boot environment);
   - saves the WHOLE flash on the card: tc100-3/backup/flash-stock.bin. Keep this file somewhere safe: it is
     your way back to the stock firmware. It holds vendor files: do not publish it;
   - copies the camera's sensor tuning file (isp_f23*mipi*.conf) to config/ on the card (no vendor library is
     needed or copied since 3.0.1-rc35);
   - adds the 3.0 start commands to the U-Boot settings (the stock start stays as the fallback);
   - restarts. Progress and any reason to stop: tc100-3/STATUS.txt.
   This takes about 2 minutes, with the blue LED blinking. If anything looks wrong, nothing is written, the
   red LED stays on and STATUS.txt says why.
3. The camera now starts the 3.0 firmware from the card and checks, by itself (v3/install/auto-install.sh):
   - the copy of the flash (tc100-3/backup/flash-stock.bin) read again from the card: its md5, and its
     U-Boot and mac areas equal to this camera's (the way back must exist before anything is installed);
   - the hardware on Linux 6.6 (board profile, sensor id, flash chip id), the package files and their md5;
   - a picture from the sensor through the video server.
   If all pass, it writes the firmware into its flash (about 10 minutes, blue LED blinking, each partition
   saved to tc100-3/backup first and read back after writing, initrd last) and restarts from its flash with
   a short chime. Any doubt: nothing is written to the flash, red LED, the reason in STATUS.txt, and the
   camera keeps running from the card. No Wi-Fi is needed for the install.
   With an empty file ESSAI.txt (or TRIAL.txt; rename ESSAI.txt.example at the root) at the root of the card, it
   stays in trial mode instead (nothing of 3.0 in the flash); Settings -> Update & backup -> Install to flash
   installs it later. Always eject the card cleanly before removing it from your computer.
4. Open http://tc100/ (or the IP address written to tc100-3/ADRESSE.txt, or shown by your router) and sign in
   as root with the password of your 2.x camera, or "pass" on a camera that had the stock firmware (in SD trial
   mode ESSAI.txt on a camera already running 3.0.x, the card also uses its default "pass", not the flash
   password). The setup wizard asks for a new password. The card is now only used for recordings and can be removed.

Without this card, or with a card without tc100test/c66.img, the camera starts its stock firmware until
the install of step 3 is done.

Updates: Settings -> Update & backup -> Firmware update, with tc100-<version>-update.tar.

Way back
--------
- Trial mode (ESSAI.txt), or the install stopped (red LED): take the card out (or rename
  tc100test/c66.img): the camera starts the system it had before (stock or 2.x) from its flash, unchanged.
- After the install: on the card, rename tc100test/c66.img.installed to c66.img and add an empty file
  RESTAURER.txt (or RESTORE.txt) at the root. Power on: the camera starts from the card, writes back the
  flash as it was before 3.0 from tc100-3/backup/flash-stock.bin (about 10 minutes, after checking that the
  copy is this camera's), and restarts into it. Then take the card out (with it, the stock firmware runs
  the card's hook instead of its app). v3/install/restore-stock.sh does the same over ssh.

Source, documentation and issues: https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918
