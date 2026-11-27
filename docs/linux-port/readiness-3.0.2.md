# 3.0.2 final: readiness (2026-11-25)

Read-only review of every open entry of `test-queue.md` against the field readings logged so far (both cameras on
3.0.2-rc2 from 23-24/11, rc4 from 25/11 09:05 / 09:10; rc1 and rc3 were never installed, their content reached the
cameras with rc2 and rc4; rc5 is built, not installed). Evidence is quoted from the dated readings in `test-queue.md`
and `watch-2026-11-25-rc4-day.md`. Nothing is marked passed without a reading that shows it.

**Both cameras have no SD card:** `memory.csv`, `memory-hourly.csv` and `nightceil.csv` live in `/mnt/log` (RAM) and
are lost at every reboot; the rc4 reboots restarted the MEMWATCH clock and the rc5 install will restart it again.

## 1. Status of the open entries

| Entry | Build | Status | Evidence, or what is missing |
|---|---|---|---|
| FAILCOUNT | rc2 | **passed by field** | counters 0 on both over ~28-38 h on rc2/rc4, `starts` +1 across the 24/11 18:22 restart, hourly rows; a literal `kill -TERM` stays for the kill loop |
| DN-FLAP | rc2 | **passed by field** | .11: no round trip on two nights (4-9 a night on 3.0.1); .24: one 3-min round trip then held all night. `held back` lines to quote tonight |
| AWB-NIGHT | rc2 | **mechanism passed** | `rex=256` in all night samples, day gains resumed and saved, no night state. The bit-rate criterion moves to NIGHT-CEIL; evening hand-over line to read tonight |
| VBR-QP-01 | 3.0.1 | **passed by field** | rc2 day 88-380 kbit/s at 24 fps vs ~1580 with QP 27; default 33 |
| KRN-02 | 3.0.1 | **passed by field** | patch 0022 in every build since 14/11, no oops or hang (111 h on 3.0.1, rc2/rc4) |
| WIFI-STALL-01 | 3.0.1 | **obsolete (done)** | TX A-MPDU off by default; 0 TX URB error, 0 RX URB lost |
| AUDIT-1116-KERNEL | rc1 | partly | 4 clean boots, ~1.6 days streaming, no oops. Missing: 50x kill -TERM, audio cycles, stream start/stop, Wi-Fi down/up, 5 reboots, OSD soak |
| AUDIT-1116-USB | rc1 | partly | Wi-Fi up, 0 URB errors. Missing: 20x `wlan0` down/up while streaming, reassociate, unbind/bind, 5 reboots, 12 h soak |
| AUDIT-1116-VENCIRQ | rc1 | partly | `pic_fail`/`enc_reopen`/`cap_stall`/`exit3` 0 over ~28-38 h. Missing: IRQ vs picture count, 50x kill loop with a clean first picture, `irq_unlazy=0` control |
| AUDIT-1116-BOOT | rc1 | partly | clean reboot unchanged. Missing: power pull, 3 early crashes giving safe mode |
| AUDIT-1116-RECOVERY | rc1 | partly | normal boots only; steps 2-5 (`stackbad`, SD user space, switch off, watcher) need the Mac + UART + SD |
| AUDIT-1116-UPDATE | rc1 | partly | 3 normal updates fine. Items 1-6 (reboot refused during a write, double POST, crond absent, simfail, full card, kill apply) not exercised |
| AUDIT-1116-INSTALL | rc1 | partly | settings kept across updates; `cfg-persist status` and SD install steps not logged |
| AUDIT-1116-RTSP | rc1 | partly | no capture stall over switches; client-timing, SIGSTOP, `arecord` kill, SETUP 404 not exercised |
| AUDIT-1116-NET | rc1 | partly | ssh LAN works, web update fine. Missing: 431 curl, 10 wrong logins, ONVIF reconnect, netacl in `/proc/<pid>/maps`, non-private refusal |
| AUDIT-1116-WIFI | rc1 | not exercised | wrong-password save, refused quote, rescue AP 30 min cap, button 3-7 s |
| B1-ONVIF, B2B3-CONF, B4-HUE, R1-MDENC, W1-PRIVFILL, W3-ZERO, R2-BUTTON, R3-MQTT, T1B5-PARITY, W5-AUDIT | rc3 | not exercised | each has a short check (section 2, session 2) |
| CLEANUP-1124, SMALL-B-1124 | rc3 | partly | rc4 day watch only (1 h 40, counters 0); STAT-field comparison, night switch, mDNS TXT, ONVIF motion missing |
| SMALL-A-1124 | rc3 | not exercised | cheap reads over the soak; R5 and R6 need one action each |
| CI-PIN | rc4 | partly | .11 smoke test passed (BusyBox, dropbear, wpa_supplicant, iw, curl/mbedTLS, whep, MQTT); .24 clean boot. Missing: browser live view, the first update with this build's updater (rc4 -> rc5), the GitHub reproducibility runs |
| WIFIQ-FORKS | rc4 | partly | outputs correct on the .11; fork count and `top` missing |
| HARDEN | rc2 | partly | ~1.6 days without restart; missing the `stack smashing` / `illegal instruction` grep and `top` before/after |
| MEMWATCH | rc2 | partly | flat over 9 h and 19 h; the 3-day window never ran uninterrupted (reboots, no card) |
| AWB-05-SAVED | rc1 | partly | old `awb.state` form accepted; the "from saved gains" restart line not quoted yet |
| POLISH-01 | rc1 | partly | item 2 indirectly seen; items 1 and 3 not measured; item 4 obsolete (T1B5-PARITY) |
| ENC-02 | 3.0.1 | partly | night budget and 24 h without failures met; smart still scene, recording across a switch, the 128 KB opt-in not done |
| NATIVE-02 | 3.0.1 | partly | web UI works; no timing / diff run; its audit-line step is obsolete (W5-AUDIT) |
| IDLE-MIC-01, WHEP-ONDEMAND, UPD-01 | 3.0.1 | partly | see `test-queue.md`; UPD-01(b) can be done at the rc5 update |
| SUBSTREAM-LOOP, NIGHT-CEIL-AUTO | rc5 | not exercised | install rc5, one undisturbed night |
| RTSP-UDP-NB, WEB-01 | 3.0.1 | not exercised | 10 min UDP client; WEB-01 with the B1 password change |
| AUDIT-1116-FLASHBOOT, AUDIT-1116-FTP, T1-QP-BENCH, HRTIMER-01, MDNS-01, RTSP-AUTH-01, ENC-01, AEC-01, ONVIF-02, WHEP-02, AWB-01, INST-01, PRES-01 | — | owner | decision, credentials, a flash write or the owner's eye; none blocks the final except FLASHBOOT / FTP decisions |

## 2. Before 3.0.2 final: the camera actions in three sessions

Install rc5 first: the 3-day soak restarts at every reboot while the cameras have no card.

**Session 1: rc5 install, one evening and night.**
1. Install rc5 on both cameras by the web update; meanwhile: UPD-01(b) (`discard` / `upload` answer `busy`),
   AUDIT-1116-UPDATE 1-3 (UI reboot answers `UPDATE_RUNNING`, a second install POST does nothing, `crond` /
   `button-watch` absent during the write), CI-PIN (this build's updater runs). Then the rc4 smoke test again.
2. No video restart before the evening: read the AWB-NIGHT `AWB-05 paused (night)` line and the DN-FLAP `held back`
   lines (or `nightceil.csv`).
3. NIGHT-CEIL check A: `nightceil.csv` `main_kbps` against `gain` for `bw=1` on both; check B: at the ceiling on the
   .24, `controlscripts/rtsp-h26x restart` and compare the `stop` row, the `entered=start` switch row and the samples
   after it (`starts` +1 is expected).
4. Next morning, before any reboot: copy `nightceil.csv`, `memory*.csv` and the logs; SUBSTREAM-LOOP histogram
   (`grep 'rtsp: client .* closed' /tmp/logs/tc100_rtsp.log | sort | uniq -c`) next to the Frigate / go2rtc logs.
5. If A and B say noise: one night on the .24 with `RTSP_NIGHT_VBR_QP_ADD=3` (or `RTSP_NIGHT_KBPS=900`).

**Session 2: hands-on, 1-2 h with the owner at the camera (ssh from the Mac, UART optional).**
Run with the bench (`RECETTE-BENCH` in `test-queue.md`, `tests/camera/README.md`): `recette-host.sh --camera IP` for the
safe and host checks, then `--disruptive --wifi` for the 50x kill loop (KERNEL 3, VENCIRQ 3/6, FAILCOUNT TERM), the stall
exit, the 20 Wi-Fi cycles, the stream stop/start cycles, the day/night hue and the privacy timing; the owner types the
password and the Wi-Fi/OSD values in the web UI. What stays manual (SKIP lines of the bench): R2-BUTTON (button and
lens), AUDIT-1116-WIFI (wrong password, refused quote, rescue AP cap, button), AUDIT-1116-USB unbind/bind (UART), B1 and
B2/B3 settings steps, R1-MDENC (walk-ins), SMALL-B (ONVIF motion in HA, W2 colours), the 200 audio cycles, the
induced encoder timeout, the 3 h / 12 h / 24 h soaks and MEMWATCH's 3 days (session 3).
- R2-BUTTON (slow `nightmode.sh`, 5 s hold = rescue AP, 8-10 s = reboot); AUDIT-1116-WIFI (wrong password, refused
  quote, rescue AP cap, button 3-7 s).
- 50x `kill -TERM` of `tc100_rtsp` restarted with the autorun arguments (closes KERNEL 3, VENCIRQ 3/6, RTSP, the
  FAILCOUNT kill); a real capture stall with `RTSP_CAPTURE_STALL_S=5` (not SIGSTOP: a stopped process is not a stall,
  see test-queue AUDIT-1116-RTSP step 4); 200 audio connect cycles; 20 stream start/stop.
- One owner-typed password change: B1-ONVIF, WEB-01(a), AUDIT-1116-NET step 5; ONVIF reconnect after an unplug.
- R3-MQTT (retained command, owner's broker credentials); SMALL-A R5 (two events at once); B2B3-CONF
  (`RTSP_LITE_TALK` toggle); B4-HUE; W1 (`pp_ms` with `/tmp/tc100_privacy`); R1-MDENC; W5-AUDIT (`hw_state` x5, no
  audit line); T1B5-PARITY (`isp_tune` diff, Settings -> Image).
- Web live view in a browser (CI-PIN, WHEP-02); FTP test or decision.
- Mac + UART, RAM only: AUDIT-1116-RECOVERY 2-5 (`stackbad`), AUDIT-1116-USB 2-5 (`wlan0` x20, unbind/bind).

**Session 3: 3-day soak from the rc5 install (no manual restart except check B).**
MEMWATCH (copy the files daily without a card), FAILCOUNT / HARDEN (grep `smash` / `illegal`, `top` before / after) /
VENCIRQ / CLEANUP (STAT fields vs 3.0.1), DN-FLAP two more evenings, SMALL-A reads, WIFIQ-FORKS (2) and (3), SMALL-B
(mDNS TXT, ONVIF motion in HA), POLISH-01 1 and 3, AWB-05-SAVED (day restart, "from saved gains"), W3, IDLE-MIC
`cpu-profile.sh`.

## 3. Owner decisions

**Taken on 2026-11-27: the path to 3.0.2 final** (answers in chat, main session).
- **Criteria for the final:** the bench run in full and green on both cameras (`--disruptive --wifi` with
  `RECETTE_PASS` and `RECETTE_MQTT_*`), the owner's hands-on session (1-2 h, section 2 session 2), one night of
  NIGHT-KBPS-DEFAULT, then 48 h without an incident on the last rc. MEMWATCH's 3-day window is dropped.
- **Also before the final (owner: "do them before"):** MDNS-01 (iPhone / Safari, Windows PC, Home Assistant); AEC-01 and
  the two-way audio (push-to-talk in Safari on the iPhone and in Chrome / Edge on Windows, the RTSP backchannel from
  go2rtc / Frigate and from Home Assistant); ENC-01 (smart mode, still scene with a covered lens); PRES-01 (presence
  modes from Home Assistant); T1-QP-BENCH (tester, one camera, nothing written to the flash); the `RTSP_FE_SUBBUF=1`
  check of ENC-02 (128 KB sub-stream buffer: passed = default, failed = the option is removed).
- **Closed without a camera test:** SUBSTREAM-LOOP (client side), MEMWATCH (3 days dropped), AUDIT-1116-FLASHBOOT
  (both cameras boot 3.0 from the flash daily), the Mac + UART + SD session (AUDIT-1116-RECOVERY 2-5, AUDIT-1116-BOOT,
  the USB unbind / bind steps), INST-01 (host tests), HRTIMER-01 (passed by field), AWB-01 step 3 (colours accepted).
- **Stays as it is:** `RTSP_SENDER_THREAD` stays opt-in (0).
- **Code before the final:** esbuild 0.21.5 -> 0.25 (Dependabot; the minified web UI compared before / after), the
  pinned GitHub actions moved to their Node 24 versions (still pinned by commit).
- **Release:** the main session prepares the version commit, the notes and the file list; the owner creates the
  GitHub release `v3.0.2` himself.
- **After 3.0.2:** the ISP privacy mask (privacy without the memset, about 40% of a core). Not picked this time: the
  kernel guard removal of 25/11, signed updates, the OpenIPC forum draft; they wait for the owner's word.
- **Major upgrade, to decide (owner, 27/11 evening):** the security audit
  [audit-2026-11-27-security.md](audit-2026-11-27-security.md) lists the gaps (kernel 6.6.0 without 163 stable
  releases, Mbed TLS 2.28 out of maintenance and used by WHEP, Buildroot 2024.02, unsigned updates, no fuzzing, root
  everywhere) and the options A-G; a possible 3.1 = SBOM + kernel 6.6.y + Buildroot/Mbed TLS LTS + signed updates.
  Proposal with phases and gates: [plan-upgrade-3.1.md](plan-upgrade-3.1.md).


Taken on 2026-11-25:
- **NIGHT-CEIL:** cause settled on 26/11 (night noise at high gain, read B and a full dark night); owner: try
  `RTSP_NIGHT_KBPS=900` on IPCAM1 only (test-queue NIGHT-CEIL-AUTO); the default is decided after that night.
  **Decided 27/11:** the night passed (mean ~910 kbit/s, day back to 1600, no false motion, picture accepted); 900 is
  the default since 3.0.2-rc8 (`RTSP_NIGHT_KBPS=0` = off), camera check NIGHT-KBPS-DEFAULT.
- **SUBSTREAM-LOOP:** answered on 25/11: the sub-stream client ends its own sessions (`TEARDOWN received`); Frigate /
  go2rtc side, not the camera.
- **SD card:** none in the cameras. The 3-day soak files (`memory*.csv`, `nightceil.csv`) stay in RAM: copy them off
  every day, and any reboot restarts the soak.
- **FTP:** stays off by default, documented; no test (AUDIT-1116-FTP closed by decision).
- **Rescue mode:** cleartext telnet limited to the LAN stays the rescue door; no rescue access point in the
  initramfs; no loop device in the kernel.
- **MQTT admin commands:** a switch `MQTT_ADMIN_CMDS` in `mqtt.conf`, on by default (today's behaviour).
- **AUDIT-1116-FLASHBOOT:** read-only check of the U-Boot environment on both cameras (command in `a-faire`).

Still pending (from before):

1. ~~NIGHT-CEIL after checks A and B~~: decided 27/11, 900 kbit/s at night by default (see above).
2. An SD card in one camera (MEMWATCH, `nightceil.csv`, log persistence).
3. AUDIT-1116-FLASHBOOT: a hook-installed camera to check; a failure needs a U-Boot environment change (owner).
4. AUDIT-1116-FTP: test a wrong password, or keep FTP off and say so.
5. Rescue mode: cleartext telnet as the rescue door, a rescue AP in the initramfs, a loop device in the kernel.
6. Credentials-only tests: B1-ONVIF, ONVIF-02, RTSP-AUTH-01, R3-MQTT.
7. Not blocking: MDNS-01 (iPhone / Windows / HA), AEC-01, ENC-01, AWB-01 step 3, PRES-01, INST-01, T1-QP-BENCH,
   HRTIMER-01 (post-final), `RTSP_FE_SUBBUF=1` (opt-in, can be dropped).
8. WIFI-POWERON (`a-faire` B3) can be dropped: the .24's rc2 update and both rc4 updates were clean.

## 4. Closures the tester can write now

- **WIFI-STALL-01:** closed 25/11: root cause TX A-MPDU, `WIFI_AMPDU_TX=0` default since 3.0.1; rc2/rc4: A-MPDU TX
  off, 0 TX URB error, 0 RX URB lost.
- **KRN-02:** passed 25/11: patch 0022 in every build since 14/11, no oops or hang through 3.0.1 (111 h) and rc2/rc4.
- **VBR-QP-01:** passed 25/11: rc2 day 88-380 kbit/s at 24 fps, still scene ~450 kbit/s, vs ~1580 with QP 27;
  default 33.
- **FAILCOUNT:** passed 25/11: counters 0 over ~28-38 h on rc2/rc4, `starts` +1 across a restart, hourly rows; the
  literal kill -TERM check stays in the session-2 kill loop.
- **DN-FLAP:** passed 25/11 (rc2, 2 nights); `held back` lines to quote tonight.
- **AWB-NIGHT (mechanism):** passed 25/11; night bit rate moved to NIGHT-CEIL-AUTO; close fully once the evening
  hand-over line is read.
- **Obsolete steps:** POLISH-01 item 4 (T1B5-PARITY), NATIVE-02's audit-line step (W5-AUDIT), HRTIMER-01's
  `RTSP_PACING_US` step (removed).
- **Not closable yet:** MEMWATCH (3 days not met), HARDEN (no grep, no `top`), every audit-1116 / rc3 entry.

Doc hygiene for the tester: the 23-25/11 readings filed under ENC-02 and PRES-01 belong in a dated section; the
MEMWATCH `###` heading is missing and FAILCOUNT's heading has an encoding glitch; the "State on 2026-11-14" and
"Still open" paragraphs at the top of `test-queue.md` are stale.
