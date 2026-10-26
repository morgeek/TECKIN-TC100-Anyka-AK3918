TECKIN TC100 firmware 3.0 (Linux 6.6): SD card package
=========================================================

RELEASE CANDIDATE: this SD install has not yet run on a camera. Read "Is it safe?" in the project
README first. Do not unplug the camera during the first start (about 2 minutes).

Made for the TECKIN TC100 indoor camera (Anyka AK3918EV300, JX-F23 sensor, RTL8188FU Wi-Fi) with the
vendor firmware V1.1.41, or with the 2.x firmware of this project installed into its flash. The camera
checks this before it changes anything. Settings and Wi-Fi of a 2.x camera are carried over.

What it does, step by step
--------------------------
1. Copy everything in this zip to the root of a FAT32 microSD card of 32 GB or less (not into a folder: the
   card must show wifitest, tc100test, tc100-3... directly; see 00-LISEZ-MOI-READ-ME.txt).
   A camera never connected to Wi-Fi needs a file wifi.txt at the root with two lines, SSID=your network and
   PASSWORD=its password. A camera already on Wi-Fi (TECKIN app, or 2.x) keeps its network.
2. Put the card in the camera (powered off) and power it on. The stock firmware runs wifitest/wifi_test.sh,
   which:
   - checks the camera (partition table, the stock /usr of firmware V1.1.41, U-Boot environment);
   - saves the WHOLE flash on the card: tc100-3/backup/flash-stock.bin. Keep this file somewhere safe: it is
     your way back to the stock firmware. It holds vendor files: do not publish it;
   - copies the camera's own libraries (uClibc, video encoder) to lib/ on the card;
   - adds the 3.0 start commands to the U-Boot settings (the stock start stays as the fallback);
   - restarts. Progress and any reason to stop: tc100-3/STATUS.txt.
   This takes about 2 minutes, with the blue LED blinking. If anything looks wrong, nothing is written, the
   red LED stays on and STATUS.txt says why.
3. The camera now starts the 3.0 firmware from the card (trial mode) and plays a short chime when it is
   ready. Open http://tc100/ (or the address your router shows, also written to tc100-3/ADRESSE.txt) and sign in as root with the password of your 2.x camera, or
   "pass" on a camera that had the stock firmware. The setup wizard opens: it asks for a new password,
   and its last step offers to install 3.0 into the camera in one click (or "Not now" to try it first;
   nothing of 3.0 is in the flash yet).
4. To install later: Settings -> Update & backup -> Install to flash. The camera writes the firmware into
   its flash (about 10 minutes, each partition saved to tc100-3/backup first and read back after writing)
   and restarts from its flash. The card is then only used for recordings and can be removed.

Without this card, or with a card without tc100test/c66.img, the camera starts its stock firmware until
step 4 is done.

Updates: Settings -> Update & backup -> Firmware update, with tc100-<version>-update.tar.

Way back
--------
- After step 2 or 3: take the card out (or rename tc100test/c66.img): the camera starts the system it had
  before (stock or 2.x) from its flash, unchanged.
- After step 4: put this card back with tc100test/c66.img (the install renamed it c66.img.installed): the
  camera starts from the card again. From there, v3/install/restore-stock.sh (over ssh or telnet) writes
  back the flash as it was before 3.0 from tc100-3/backup/flash-stock.bin.

Source, documentation and issues: https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918
