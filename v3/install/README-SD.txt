TECKIN TC100 firmware 3.0 (Linux 6.6): SD card package
=========================================================

Made for the TECKIN TC100 indoor camera (Anyka AK3918EV300, JX-F23 sensor, RTL8188FU Wi-Fi) with the
vendor firmware V1.1.41. The camera checks this before it changes anything.

What it does, step by step
--------------------------
1. Copy everything in this zip to the root of a FAT32 microSD card (8 GB or more).
   Optional: a file wifi.txt at the root with two lines, SSID=your network and PASSWORD=its password.
2. Put the card in the camera (powered off) and power it on. The stock firmware runs wifitest/wifi_test.sh,
   which:
   - checks the camera (partition table, the stock /usr of firmware V1.1.41, U-Boot environment);
   - saves the WHOLE flash on the card: tc100-3/backup/flash-stock.bin. Keep this file somewhere safe: it is
     your way back to the stock firmware. It holds vendor files: do not publish it;
   - copies the camera's own libraries (uClibc, video encoder) to lib/ on the card;
   - adds the 3.0 start commands to the U-Boot settings (the stock start stays as the fallback);
   - restarts. Progress and any reason to stop: tc100-3/STATUS.txt.
   This takes about 2 minutes. If anything looks wrong, nothing is written and STATUS.txt says why.
3. The camera now starts the 3.0 firmware from the card (trial mode). Find its address on your router
   (host name tc100), open http://<address>/ and sign in as root / pass. Change the password at once:
   Settings -> System -> Password. Try everything; nothing of 3.0 is in the flash yet.
4. To keep it: Settings -> Update & backup -> Install to flash. The camera writes the firmware into its
   flash (about 10 minutes, each partition saved to tc100-3/backup first and read back after writing) and
   restarts from its flash. The card is then only used for recordings and can be removed.

Without this card, or with a card without tc100test/c66.img, the camera starts its stock firmware until
step 4 is done.

Updates: Settings -> Update & backup -> Firmware update, with tc100-<version>-update.tar.

Way back
--------
- After step 2 or 3: take the card out (or rename tc100test/c66.img): the stock firmware starts.
- After step 4: put this card back with tc100test/c66.img (the install renamed it c66.img.installed): the
  camera starts from the card again. The stock flash can then be written back from
  tc100-3/backup/flash-stock.bin (see the project README, "Back to the stock firmware").

Source, documentation and issues: https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918
