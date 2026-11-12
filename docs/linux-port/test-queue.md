# Test queue: changes waiting for a run on a real TC100

Several agents work on this repository. The ones without the camera write code; another one runs it on the camera.
This file is the hand-off between them. **Implementers:** add an entry for every change that needs the camera, with a
switch to turn it off. **Testers:** run the entries, write the result under the entry (date, camera, build, numbers),
set the status, and, when it passes, make the change the default in a follow-up commit (or say why not).

Status values: `to test`, `testing`, `passed`, `failed`, `blocked`.

Finished entries (passed and made the default, superseded or abandoned) are moved to [test-queue-archive.md](test-queue-archive.md); this file keeps what is still open.
Closed entries moved to test-queue-archive.md on 2026-11-06. Status labels in the older dated sections below are
historical snapshots, not a second current backlog; use the owner-confirmed list above for current work.

**Current field summary (2026-11-09):** the latest report is rc36 on IPCAM2 and rc35 on IPCAM1. Both reported 12–15
hours without reboot, oops, or OOM and short RTSP captures without decode errors. The planned seven-day watch was
cancelled on 2026-11-09, so it has no pass result. Older entries below remain as the audit trail; use the newest dated
report for the current camera state. The asynchronous RTSP sender remains opt-in; any default change follows a separate
decision after the four-client throughput and mixed TCP/UDP criteria in R16 pass.

Rules that apply to every entry:
- Test kernels boot from the SD card in RAM (`pack66/boot66b.sh`, `tc100test/c66.img`); nothing is written to the flash.
  Pass test-only kernel arguments with `EXTRA` to `boot66b.sh`; do not edit `bootargs` or enter U-Boot commands. After
  boot, check that `/proc/cmdline` holds the full initrd size and every requested argument. If anything is missing,
  stop and report the result before interpreting the test.
- Changes to `tc100_rtsp` can be tried without a reboot: `v3/dev/try-rtsp.sh CAMERA BINARY [VAR=value]`, or switches in
  `/mnt/config/rtsp.env` followed by a restart of the server (`controlscripts/rtsp-h26x restart`).
- The CI build of a change is the run whose title starts with the commit's prefix (`[hwaccel]` for the entries below):
  artifact `tc100-linux66-cma16-kernel` (`oipc.img`, `tc100test/*`, `tc100_rtsp`).
- Measure with the `STAT` lines of `/tmp/logs/tc100_rtsp.log`, `scripts/cpu-profile.sh 60`, `/proc/meminfo`
  (`MemAvailable`), `/proc/interrupts` (two reads 60 s apart), and look at the picture (snapshot, VLC).
- Memory of a process: **PSS** (`awk '/^Pss:/ {print $2}' /proc/<pid>/smaps_rollup`, KB), not RSS. RSS counts the busybox
  and C library pages shared by every shell once per process (the C MQTT bridge looked 5 MB lighter in RSS, 0.9 MB in PSS).

### ONVIF-02 onvifd: lockout per address, full answers on slow links, connection and discovery limits (`[onvifd-review]`) — `to test` (next RC, owner: NVR + Home Assistant)

- **What (read-only Fable review of `tc100-onvifd`, 2026-11-12: no authentication bypass, no out-of-bounds access):**
  - Wrong logins are counted per address (20 a minute locks that address only; 127/8 never; 32 slots, a locked
    address is never evicted). Before, one global counter let any LAN host lock the NVR and Home Assistant out by
    sending 20 bad tokens a minute. Residual: more than 32 guessing addresses at once are not all counted.
  - `send_all` puts the socket back in blocking mode before sending, with 3 s for the whole answer. Before, the
    accepted sockets were non-blocking and an answer larger than the socket buffer (GetProfiles, Media2: up to
    24 KB) was cut at the first `EAGAIN` on a slow Wi-Fi link: a possible cause of a "flaky" ONVIF in an NVR.
  - At most 4 of the 6 connections from one address (127/8 not limited): six idle connections from one host held
    every slot.
  - WS-Discovery answers only a SOAP envelope and at most 20 answers a second, probes for other types not counted
    (a 7-byte `<Probe>` from a spoofed source got a 1 KB answer); a Resolve with a `wsa:ReplyTo` header is answered (it compared the ReplyTo address).
  - The five XML entities and ASCII character references (`&#39;`) are decoded in the user name and password: a password with `& < > " '` works in
    PasswordText (it failed before). `dur_s` no longer overflows on a huge duration.
  - Not changed (owner's choice): no nonce cache against replay of a captured PasswordDigest within ±300 s (some
    clients reuse nonces; LAN only).
- **Switch:** none; revert the commit.
- **Test:** (a) NVR and Home Assistant: discovery, add the camera, live view, motion events, as usual; restart Home
  Assistant: the ONVIF integration comes back. (b) Optional, from another LAN machine: 25 requests with a wrong
  password (e.g. a script with `curl` and a bad UsernameToken), then the NVR still works while that machine gets
  NotAuthorized even with the right password for the rest of the minute. (c) Optional: an ONVIF client on a slow
  link (phone app over Wi-Fi) lists both profiles completely.
- **Pass:** (a); (b)/(c) if run.

### WHEP-02 WebRTC gateway: LAN filter on its UDP port, consent from authenticated checks only (`[whep-udp]`) — `to test` (next RC, owner, with the WHEP entry of 2026-11-05)

- **What (read-only Fable review of the UDP side of `tc100-whep`, 2026-11-12: no out-of-bounds access, nothing
  reachable without a session):**
  - UDP 8189 was bound to every interface and outside `NET_LAN_ONLY` (libnetacl filters accept / bind only, and the
    gateway was not started through it). `controlscripts/whep` now passes `TC100_NET_ALLOW` (`netacl_allow_list`, the
    same list as httpfront) and the gateway drops datagrams from other networks; log line `udp 8189: datagrams from
    the allowed networks only`. `NET_LAN_ONLY=0` gives an empty list = no filter, as before.
  - Only an ICE consent check with the right MESSAGE-INTEGRITY keeps a viewer alive (RFC 7675). DTLS and SRTCP
    datagrams no longer reset the timer: a datagram sent from a spoofed address kept a dead viewer's slot (one of
    `WHEP_MAX=2`) and its stream forever. The timer is 30 s instead of 12 s (Firefox checks every 4-6 s; two lost
    datagrams on the Wi-Fi must not drop a viewer). The page still sends its stop request when it closes or hides
    the video, so a closed tab frees its slot at once; the 30 s only matters for a viewer that vanished.
  - `profile-level-id=` at the end of a long fmtp line no longer reads past the copy (authenticated offer only).
  - Not changed: spoofed datagrams during the handshake window or a replayed binding request (needs sniffing on the
    LAN); one slow authenticated HTTP request stalls the single thread for a few seconds; a non-browser WHEP client
    whose keepalive is a STUN Binding Indication (libnice) is now dropped after 30 s; the network list is read when
    the gateway starts (after a change of `NET_ALLOW_EXTRA` / `NET_LAN_ONLY`, restart the WebRTC service too).
- **Switch:** `NET_LAN_ONLY=0` disables the filter; revert the commit for the old consent rule.
- **Test:** (a) Live view in Chrome and Firefox on the LAN, 10 minutes each: no "no sign of life (consent)" in
  `/tmp/logs/whep.log` while the tab is open; closing the tab frees the viewer at once (stop request), killing the
  browser without closing frees it within ~30 s. (b) Two viewers at once,
  then a third is refused as before. (c) The log shows the "allowed networks only" line. (d) Optional: from a non-LAN
  address (VPN outside `NET_ALLOW_EXTRA`), the live view falls back (no WebRTC) and the log shows no new viewer.
- **Pass:** (a)-(c); a browser that does not send consent checks would be dropped after 30 s: if one is seen, report
  which one.

### UPD-01 Web update: no upload / discard during an install, stricter package, true failure message (`[update-review]`) — `to test` (next RC, owner)

- **What (read-only Fable review of `update66.sh`, `update.cgi`, `boot-guard`, 2026-11-12: no brick path):**
  - `update.cgi` refuses `upload` and `discard` while `/tmp/update66.running` exists. Before, a second tab or API call
    could delete the package being written, and without a card (services stopped for memory) `discard` restarted the
    camera in the middle of a flash erase.
  - `update66.sh check` refuses a package whose files are links, or whose `MD5SUMS` holds any line other than
    `md5  name` / `md5 *name` for `VERSION`, `stack.sqfs`, `c66.img`, `c66rd.gz` (a `VERSION` link showed any file in
    the page; a `/dev/zero` entry hung it). The real `MD5SUMS` of `build-release.sh` passes (test
    `test_md5sums_names_only_the_package_files`).
  - After a write failure the message no longer promises the web page (it lives in the stack partition, written
    first): it points to the SD card. `update66.sh` leaves `/tmp/update66.failed`, and `update.cgi` then refuses any
    upload, discard or install until a restart (a discard deleted the package and could restart on a half-written
    stack; a new install recopied its tools from the rewritten `/mnt`). No manual ssh retry is offered: `apply-ram`
    skips the package checks, and a retry pruned the only good backup. If the stack write was refused before any
    erase (flashw exit 1-4 or 7: no room for the backup on the card, md5, size), the message says the flash is
    unchanged and a restart starts the old firmware.
  - Known, not changed: two install POSTs a few ms apart can both start (check and marker are not atomic); a kill of
    the install shell (OOM) leaves no failed marker.
  - Not changed (owner's decision if wanted): writing kernel and initrd before the stack would keep the web retry for
    those two; mixed old/new partitions were not tested.
- **Switch:** none; revert the commit.
- **Test (next RC update over the web, owner):** (a) normal web update with and without a card: works as before.
  (b) During the install, from a second tab or `curl` with the CSRF token, POST `cmd=discard` and `cmd=upload`: both
  answer `busy`, the install finishes and the camera restarts normally. (c) Optional: a package with an extra line in
  `MD5SUMS` is refused at upload ("MD5SUMS names other files"). (d) Optional, SD test system only: `touch
  /tmp/update66.failed`, then upload / discard / install from the page answer the "failed half way" message.
- **Pass:** (a) and (b); no change for a normal update.

### HOOK-01 First-install hook: stricter checks and U-Boot built-in environment (`[stock-hook-review]`) — `to test` (next RC, owner)

- **What (read-only Fable review of `stock-hook.sh` + `envtool.c`, 2026-11-12: no brick path in the code):**
  - `tc100-3/known-stock.txt` is now a required file (with its 32-digit `uboot` md5 line): without it the U-Boot / root / `/usr` md5 checks were skipped
    (only a note) and the environment was still written on an unidentified camera.
  - The flash copy on the card is read back after `drop_caches`, so a card that loses writes fails the md5 check
    instead of passing from the page cache.
  - An unexpected `envtool` exit (killed, >= 128) no longer logs "Nothing was written to the flash"; it says the
    environment may be incomplete and points to `env-stock.bin`.
  - **Open, the one brick question:** after a power cut in the middle of the environment write, U-Boot uses its
    built-in environment; nobody has checked that this one boots the stock firmware (`internals.md`, "What is not
    covered yet" 1).
- **Switch:** none (the hook runs once per new camera); revert the commit for the old checks.
- **Test (read-only, no card needed, on a camera running 3.0 from its flash, over ssh):**
  `m=$(grep '"boot"' /proc/mtd | cut -d: -f1); dd if=/dev/${m}ro bs=4096 count=57 2>/dev/null | tr '\0' '\n' | grep -E '^(bootcmd|boot_normal|bootargs|bootdelay)='`
  (U-Boot's built-in environment is plain text inside its binary). Paste the lines to the implementer; they hold no
  secret. Also record the stock `bootcmd` from `tc100-3/env-stock.txt` if a card from a first install is available.
- **Pass:** the built-in `bootcmd` (directly or through `boot_normal`) loads the kernel from the flash (`sf read` ...
  `bootm`): the power-cut case is then covered; update `internals.md` and close this entry. If it does not, power-cut
  recovery needs the serial console: say so in the install guide.

### WEB-01 httpfront login counting and remembered login (`[httpfront-auth]`) — `to test` (SD test system)

- **What (read-only Fable review of httpfront, 2026-11-12; `WEB_LOCKOUT=1` and `HTTPFRONT_NATIVE=1` are the
  `boot.conf` defaults, so this concerns every camera):**
  - A new password now forgets the remembered login: the cache `/tmp/.httpfront-ok` holds the MD5 of the header *and*
    of `/etc/httpd.conf`. Before, the old password kept getting the status line / dashboard JSON until a reboot.
  - Only the headers are searched for `Authorization:`: a form body line no longer counts as a wrong login (a hostile
    page could lock the owner's address out for 5 min, again and again).
  - Header name and `Basic` are read in any case, as httpd does: `AUTHORIZATION:` guesses are now counted.
  - A token cut by the end of the 2 KB peek (long cookies or URL) is neither checked nor counted, instead of counting
    as a wrong login.
  - Still possible, by design (LAN only, defence in depth): guesses placed after 2 KB of headers or sent after the 2 s
    wait are not counted; httpd still refuses them.
- **Switch:** `WEB_LOCKOUT=0` / `HTTPFRONT_NATIVE=0` in `boot.conf` as before; revert the commit for the old code.
- **Test:** SD test system with the CI `httpfront`. (a) Log in, change the password in Settings, then
  `curl -u root:<old> http://<ip>/cgi-bin/statusline.cgi` → 401 (before: JSON). New password → JSON. (b) From another
  LAN machine: 10 × `curl -s -o /dev/null -H 'AUTHORIZATION: Basic eDp5' http://<ip>/` → the 11th connection is closed
  (locked 5 min; 127.0.0.1 is never locked). (c) 12 × `curl -X POST --data-binary $'Authorization: Basic eDp5\r\n' -u
  root:<right> http://<ip>/cgi-bin/statusline.cgi` → never locked. (d) The web pages and the dashboard poll as usual,
  no extra 401 prompt.
- **Pass:** (a)-(d) as above, `/tmp/log/httpfront.log` without new errors.

### KRN-01 `ak_isp.awb_live` writable at run time (`[awb-live-rw]`, patch 0006) — `to test` (SD kernel first)

- **What:** `module_param(awb_live, int, 0644)` instead of `0444` (audit 2026-11-06 D3). The white balance code reads
  it at every frame, so `echo 1 > /sys/module/ak_isp/parameters/awb_live` tries the ISP white balance on the live
  statistics without a reboot, and `echo 0` goes back. Default unchanged (0). `ak39_vi.sub_channel` stays `0444`: the
  driver never undoes it at stream start, so a run-time write would not do what it says.
- **Switch:** none needed (default 0, as before); revert the commit to make it read-only again.
- **Test:** boot the CI kernel from the SD card (`tc100test/c66.img`, RAM only, no flash write). Check
  `ls -l /sys/module/ak_isp/parameters/awb_live` shows `-rw-r--r--` and the value `0`; picture as before. `echo 1`:
  within a few seconds the colours change (blue cast expected, R15-01); `echo 0`: back to the usual tint. No kernel
  message, no capture error, RTSP keeps running during both writes. With `awb_live=1`, also run
  `dmesg | grep -i 'division by zero'`: `_calc_awb_gain()` divides by the pixel count of the current colour bin, guarded
  only by `>= total_cnt_thresh` (patch 0006 ~l. 6582 / 6944); if the sensor configuration sets that threshold to 0, an
  empty live bin logs this warning (ARM32: stack dump, no oops). Not introduced by this change (`ak_isp.awb_live=1` on
  the command line already reached it); if seen, a one-line guard goes in a separate kernel change.
- **Pass:** as above; only then is the kernel a candidate for the next flash update (owner's agreement).

### INST-01 SD install skips the per-partition backup only on a first install (`[fast-install-fix]`) — `to test`

- **What:** `v3/install/install66.sh` skipped the per-partition backup (`flashw -b`) whenever
  `restore-stock.sh --check` passed. That check compares only the `boot` and `mac` areas, so reinstalling from the card
  on a camera that already runs 3.0 from its flash overwrote its 3.0 vendor, stack, kernel and initrd with no copy
  (found by the read-only Fable review of `8077ff1`, 2026-11-12). The skip now also requires no valid settings slot in
  the flash (`cfg-persist saved` fails), i.e. a first install over the stock firmware. Not a brick path: every write is
  still read back by `flashw`.
- **Switch:** `INSTALL66_FORCE_PART_BACKUP=1` keeps forcing the backup in every case. To go back to the old behaviour,
  revert the commit.
- **Test:** (a) first install on a stock camera with a card holding a verified `flash-stock.bin`: the log shows
  "skipping redundant per-partition read-back" and `tc100-3/backup/` gets no new partition files. (b) SD reinstall on a
  camera already running 3.0 from its flash (`cfg-persist saved` prints a slot): no skip message, and
  `tc100-3/backup/` holds the vendor, stack, kernel and initrd copies of the previous flash content. Both installs need
  the owner's agreement per flash write.
- **Pass:** (a) and (b) as above, both installs finish, the camera boots from its flash afterwards.

## Owner-confirmed current work (2026-11-10)

These are the current owner-confirmed work items. The detailed switch-by-switch procedures stay in their existing entries.

1. **RTSP and recording qualification:** run the sender-thread multi-client and mixed TCP/UDP procedure in R16 below;
   also record to the SD card while RTSP is active, play the resulting file, test browser push-to-talk (UI-13), and
   confirm end-to-end talk through go2rtc, Frigate or Home Assistant. Record the camera, current build, transports,
   frame rates, `dropped`, memory, recording playback and both talk results. No flash write is part of this check.
2. **RTSP parameter schema:** the VBR/Smart pilot catalog and its focused consistency check are in the repository;
   run the camera save/reload and preservation check in R12-07. Extending the catalog beyond these two modes remains
   separate work.
3. **WHEP:** run the missing-key default, explicit `WHEP=0`, browser fallback, latency, one/two-viewer and resource
   checks in the WHEP entry below. No flash write is part of this check.
4. **Presence modes (#65):** configure each profile, apply it, check manual edits switch the selected-profile label
   to Custom, and check Home Assistant selection and state. Confirm an unsaved profile is rejected with a clear
   instruction to save it in Settings first. Run PRES-01 below from the SD test system; do not install this change
   in flash as part of the test.

### PRES-01 Presence modes — `to test` (owner, SD test system)

- **What:** user-configured Present, Away and Night presets apply privacy screen, motion detection, local SD recording
  and outbound Webhook/Ntfy/Telegram notification delivery, including alert image uploads. The initial state is Custom
  and does not alter any setting. Profile definitions and the selected mode persist in `presence.conf`; live values
  remain in `boot.conf` and `rtspserver.conf`.
  Home Assistant receives a Presence Mode select entity. MQTT telemetry and event topics continue in every mode.
- **Switch / return to Custom:** select Custom in the web page or Home Assistant. This leaves the current privacy,
  motion and recording settings in place and allows configured notifications again. Restore any desired baseline values
  through their existing Settings controls. Manually changing alert-channel configuration also returns to Custom.
- **Test:** boot the test user space from SD/RAM. Confirm the selected profile is Custom and settings have not changed.
  Save each profile without applying it and confirm this also leaves live settings unchanged. Apply each profile and
  verify the privacy image/audio behavior, motion detector state, `REC_LOCAL`, and notification delivery using a test
  recipient or endpoint. Confirm MQTT health and event topics remain available. Change privacy, motion or recording
  manually; the mode must become Custom without undoing the manual value. Change alert-channel settings and confirm the
  mode becomes Custom. Reapply a saved profile and confirm its values are restored. Reboot the SD test system and
  confirm the selected profile and values persist. In Home Assistant, select every configured profile and Custom;
  confirm an unconfigured profile is rejected with an instruction to save it in Settings, and that the reported state
  follows the applied profile. Do not use `flashw` or install
  a partition during this test.
- **Pass:** no action before an explicit profile selection; saved profiles survive an SD test reboot; applying one
  changes only its four selected actions; manual edits switch the reported mode to Custom and remain in effect; the
  Home Assistant entity and local controls agree; no service or RTSP regression.

## Tester report to the implementers (2026-10-30, IPCAM2 / .11 on the serial console)

Historical hand-off from 2026-10-30. Its camera state and requests below are retained for context; the current test
order and camera state are the 2026-11-10 owner-confirmed items above.

**Update 2026-10-31 (night 2, rc7 `4e5d534`, IPCAM2): what to do first, in this order**
1. **Bug, F-05:** `scripts/log-persist.sh` line 80, a boot counter with an 8 or 9 in it (`0008`) is read as octal by ash:
   no log folder is created any more after the 8th boot on a card. Details and fix in the "night 2" table below.
2. **MQTT:** the broker refuses IPCAM2's login (CONNACK 5). Not a firmware fault, but show the CONNACK code in the web UI
   status and back off on refusal (the owner saw "nothing" in Home Assistant and had no way to know why).
3. **Make default:** `RTSP_ISPOSD=1` (HW-07 passed, saves about 2 % of a core), the privacy masks by the ISP (HW-04 passed
   for black, gray and white), `ak39_vi.slots=3` (+3.5 MB RAM, no cost, 15 and 25 fps checked).
4. **Do not make default / drop:** `RTSP_UDPMMSG=1` (blocks and stutter in VLC), `otg_hs.fifo32=1` and
   `rtl8xxxu.dma_aggregation=1` (no gain), `RTSP_FRAMECOPY` (no difference at one client).
5. **Needs data from the day:** HW-08 / F-04 (at night AE is pegged: exposure 1124, gain 6840 with or without IR), HW-05
   (sharpness gains are 1 in the tuning file: only 0 / 1 / 2 levels).
**Questions waiting for the owner** (the tester cannot do these alone): RTSP / web credentials for the client tests (TCP + UDP at the
same time, sub-stream, H.265 UDPSG, W-01, UI-22, F-01, O-04 checks 2-9, ssh); ONVIF discovery from a real LAN client (ONVIF is
off on IPCAM2); the MQTT password (the owner re-enters it); a go for the HW-02 test 2 boot argument `ak39_venc.pool=9600K`
(RAM only, not saved); daylight readings for HW-08 / F-04 tomorrow; the microphone and the speaker by ear.

**IPCAM2 (.11) state at 2026-10-31 00:45:** rc7 (`4e5d534`, nothing newer on main) in the flash, **25 fps set by the owner's decision**
(`rtspserver.conf [0] fps=25`, saved to the flash settings by cfg-persist, survives a full reboot: `-f 25`, 123-126 frames per 5 s,
`dropped` 2 per 5 s at worst, idle 79.8 %, MemAvailable 16.5 MB, Frigate connected). No U-Boot change, no `saveenv`; `ak39_vi.slots=3`
is NOT in the flash boot arguments (it needs a U-Boot env change: the owner has not agreed yet). The SD card still holds `tc100test/`
(consoleshell, test.img) and `.bootcount` = 0009 (see the F-05 bug).

**Historical HW-02 test note (2026-10-31; superseded):** the earlier one-shot tests supplied parameters at a U-Boot
prompt. That procedure is obsolete. Test-only arguments now go through `pack66/boot66b.sh`'s `EXTRA`; validated
defaults such as `ak39_venc.pool=9600K` belong in the kernel C defaults. The 9600K pool test below is no longer open.

**Builds run today**
- `c409d2b` / `4b066c1` (rc5): 512 KB page blocks (`CONFIG_ARCH_FORCE_MAX_ORDER=7`), high-atomic reserve 1 MB,
  no boot OOM; installed in the flash of IPCAM2 in the morning, and on IPCAM1 (.24) by its owner through the web UI.
- `44558cd` (morning): kernel booted once from the card. HW-02 test 1 passed (MemTotal +12 MiB). The new
  `tc100_rtsp` lost the main stream after 5-10 s (HW-01), and after a reboot from that kernel the RTL8188FU stayed in
  `Failed power on` until a power cut (HW-03). Both were reported as blocking.
- `f9c3d81` (evening, after a power cut): kernel from the card, then **installed in the flash** of IPCAM2 with
  `update66.sh` (settings kept). **Neither problem came back**: HW-01b passed (no guard report, `RTSP_POOLPAD=0` and
  even the 44558cd binary stream normally), 6 warm reboots after the new kernel all kept the Wi-Fi. MemAvailable
  15.3-15.9 MB (10.8 on rc5), 15 fps, 84 % idle, UI-01 and F-05 passed. IPCAM2 now runs f9c3d81 from its flash.

- `89768ee` (**3.0.1-rc6**, 20:00): kernel booted once from the card (Wi-Fi 15.4 s, 15 fps, MemAvailable 15.4 MB),
  then installed in the flash of IPCAM2 (settings kept). From flash: MemAvailable 15.9-16.1 MB, 15 fps (about 1 MB
  per 5 s), about 79 % idle a minute after the start, no OOM; 2 warm reboots, Wi-Fi every time; `curl` over TLS works
  in the serial console shell now (api.github.com 200); one housekeeper running. IPCAM2 runs rc6 from its flash.
- **HW-02 test 2 has not been run yet** (no `ak39_venc.pool=` boot so far). Note for its size: without the HW-01b
  guard the pool used is 8866880 bytes (main H.265 + sub H.264), so the pool must be at least about 9.4 MB
  (`ak39_venc.pool=9600K` or so) with `RTSP_POOLPAD=0`; `8M` would be too small. With the guard (12322880 used) a
  smaller pool cannot work: the guard has to go first (proposal 3).

### Next build: 3.0.1-rc17 — install with no click, way back from the card, old tint reset (2026-10-31)
The owner asked for a simpler install: from the original SD hook, and if the camera is compliant, the flash, with the
safest choice and a way back. The tag `v3.0.1` waits for R17-01 (and R15-03 / R15-04).

### R17-01 Automatic install from the card, then the way back with RESTAURER.txt — `to test` (needs the owner's OK per flash write)
- **What:** `v3/install/auto-install.sh`, started by `autorun-linux66.sh` step 12f in trial mode only. It installs when
  the card went through the stock hook (`tc100-3/stage1.done`), the flash's `initrd` has no xz image (no 3.0 yet) and
  `tc100-3/auto-install.tried` is absent; checks first: `restore-stock.sh --check` (copy 8 MiB, md5, `boot` and `mac`
  areas equal to the flash), `install66.sh check`, frames for 30 s (`/tmp/cam_luma`). No chime in that trial start;
  the chime comes from the flash start. `RESTAURER.txt` runs `restore-stock.sh` once (renamed `RESTAURER.done`).
- **Switch:** `ESSAI.txt` (or `TRIAL.txt`) at the root of the card: trial mode as before (wizard / Install to flash).
- **Test (only a camera on its stock or 2.x firmware enters the hook; both cameras run 3.0 from flash):**
  1. Safe part first, on the current 3.0 cameras, nothing written: boot the rc17 card by hand (`boot66b.sh`): the
     console has no `auto-install:` line (flash holds 3.0) and the chime plays; `sh /mnt/v3/install/auto-install.sh
     pending; echo $?` = 1; `sh /mnt/v3/install/restore-stock.sh --check` on a card with that camera's
     `flash-stock.bin` = `ok ...`, and with the other camera's copy = refused (`not this camera's`).
  2. With the owner's OK (flash writes, dump first): `RESTAURER.txt` on the card of one camera (one whose card still holds
     its own `flash-stock.bin` from the hook; step 1 tells): it writes back, restarts into its old system (2.x or stock), card out.
  3. Then a fresh rc17 card (only `wifi.txt` added): power on, wait 15 min: blue blinking twice, chime, `/proc/cmdline`
     has `flashroot=1`, `tc100-3/STATUS.txt` ends with "all checks passed ... installing", `install66.log` "DONE".
  4. `ESSAI.txt` variant (optional): the camera stays on the card, `STATUS.txt` says "trial mode kept".
- **Pass:** steps 1-3 as above; nothing written to the flash when a check fails (simulate: rename `tc100-3/stack.sqfs.md5`
  on a stock camera's card: red LED, "NOT INSTALLED", the camera runs from the card).
- **Also in rc17:** the picture tint and saturation of an older version reset once (`config/.migrated-3.0.1`): on the
  .24 `HUE=0 SATURATION=0` in `isp_tune.conf` and `ISP_TUNE=0` in `boot.conf` after the first rc17 start.

### Owner's decisions, 2026-10-31 evening (for the implementers)
- **An upgrade from an older version must not keep the old image tint and saturation** (`HUE`, `SATURATION` of `isp_tune.conf`; also
  `ISP_TUNE=1` carried over): reset them to 0 at migration (the .24 had HUE=-10, SATURATION=-13: green picture). Not a note: a reset.
- **Both cameras must have the same settings, except their IPs (and what is hardware: names, passwords, Wi-Fi).** The tester will align
  the two cameras' settings and list what still differs and why (`.11` had leftovers of the tests: sub stream 352x200 at 8 fps with the
  smart mode on; the main stream with `smartmode=1`; `.24` has the old IR-cut GPIO lines, `FRONT_LED=0`, no `recording` switch).
- **The second stream must be of the best quality the SoC can give** on both cameras (640x360 is the ISP sub picture; frame rate and bit
  rate to be measured: CPU, dropped frames, Frigate).

### .24 Wi-Fi is unstable, independent of the bit rate (tester, ssh, 2026-10-31 19:40 local)
- 1000-byte pings every 0.25 s to the gateway, in series of 25-40: **.24 loses 0-80 % in bursts** (48 %, 8 %, 80 %, 45 %, with 3-5 s round-trips
  at the worst) with the sub stream at 250 kb/s as well as at 600 kb/s (tried 600/900 kb/s then restored 250: `rtspserver.conf.before-2026-10-31`
  on the card). `/proc/net/wireless` link level swings -46 .. -72 dBm and drops to -256 (link down) for a few seconds, then recovers; no
  `deauth`/`disassoc` line in `dmesg`, USB at 480 Mbit/s, the Wi-Fi chip not power cycled (up 2 h). The .11 on the same network: -29 dBm,
  0 % loss, 7 ms average, max 42 ms. So it is the link of that unit / its place, not the bit rate: no change of the second stream's bit rate yet.
- For the implementers: is there a Wi-Fi quality metric in the web page (signal over time, retries) and a log line when the link drops to
  -256 (the net-guard acts only after a gateway loss)? It would have shown this without a ping flood.
- The .24 could not be measured with `tc100_rtsp.log` (no `STAT` log on its stdout, unlike the .11: the launch differs?).

### Attack surface of the cameras: audit and requests (tester over ssh, owner's goal: reduce it, 2026-11-01)
Seen on both cameras (rc16, flash boot): listening **tcp 22** (dropbear, root, password; no key file is read), **tcp 80** (`httpfront` + busybox httpd,
plain HTTP with a login), **tcp 554** (RTSP, login), **udp 5004** (RTP). Telnet, FTP and ONVIF are off. One password (`config/user.pwd`) is used for the web
page, RTSP and ssh, and it is **short** (4 and 5 bytes on the two cameras, the default-like one). `wifi-rescue` (hostapd AP when the Wi-Fi is lost) is in autostart.
Suggestions, by value:
1. **Password:** the first start (wizard) must refuse the default and short passwords (min 10 characters, not equal to the user name), and the web page should show a warning
   banner while the default is in use. Separate passwords for ssh and for the web/RTSP login (or ssh by key only).
2. **ssh:** off by default again (it is on by default today, "no lock-out after an upgrade"): on for a fresh install only during the wizard, key-based (read
   `config/authorized_keys` into `/root/.ssh` at boot: nothing reads it now), `-s` (no password) when a key exists, `-w` (no root password) is not possible as root is the only user;
   keep a persistent host key (`config/dropbear_ed25519_host_key`): today a new one at each boot, so users learn to ignore the host key warning.
3. **HTTPS:** TLS in `httpfront` (mbedtls already in `ext/lib`, ECDSA P-256 certificate regenerated before expiry, session resumption, HTTP on 80 only
   redirects the login page). Measured here: one TLS handshake costs about 0.8 s of one core on this SoC (curl/mbedTLS, 3 runs); the cameras have 64-69 % idle and about 20 MB
   available; flash `stack` has about 500 KB left (`/rom` 2304 of 2828 KB). Not for 3.0.1: 3.0.2.
4. **RTSP:** login on (it is: `-u root -w user.pwd`); RTSPS is not available. Make the RTSP user and password separate from the web one (Frigate needs only the RTSP one), and
   offer a read-only RTSP user.
5. **Network exposure:** bind the web page and ssh to the Wi-Fi interface only (nothing listens on a second one now), brute-force throttle on the login
   (a few seconds of delay after 5 failures, and a log line); udp 5004 only while an RTP client is connected; `wifi-rescue` AP only for a limited time with a strong random
   password shown on the page (check what `wifi_rescue.psk` holds).
6. **Update path:** the web update is the only thing that writes the flash; keep it behind the login, check that a package is signed (md5 alone does not protect
   against a changed package: a signature with a public key in the initrd), and refuse a downgrade unless forced.
7. **Housekeeping:** no secrets in `/tmp/*.cache` (world-readable files), the `log-persist` files readable by root only, and the `config` backup (`tc100-3/backup`) with
   mode 600 on the card.
Owner's decision: **reduce the attack surface of these small devices; he takes these suggestions.**

**Owner's rule for all of the above (2026-11-01): never block or lock out an existing installation.** An installed camera keeps working exactly as it does
(same password, same ssh, same ports) after an update. The camera **proposes** the change instead: a dismissible banner on the web page ("the password is short or the
default: change it", "ssh is on: turn it off or use a key"), shown at each login until done or dismissed for 30 days; no forced reset, no refused update, no service
switched off by the update. The **strict rules apply to new installs only** (the wizard of a first start: refuses the default / short password, ssh off unless asked, separate
RTSP password offered). Same for 3.0.2's HTTPS: added next to HTTP on port 80, which stays until the owner turns it off.
Also from the owner on the same day: an upgrade from an older version must reset the old image tint and saturation (not keep them) -- see above; this one is a fix, not a security prompt.

### Historical test-method decision (owner, 2026-11-01), superseded 2026-11-10

The Mac UART + SD/RAM loop documented at the top of this file is current. No test procedure below authorizes flashing
or requires U-Boot prompt commands.

- **What is lost:** the card-boot step before a flash install (kernel booted once from the SD card at the U-Boot prompt, nothing written), the U-Boot prompt for recovery,
  the kernel messages of a boot that fails, and any fix that needs the U-Boot environment (e.g. kernel command line switches such as `ak_isp.awb_live`).
  At the time, the proposed workflow sent every build to flash with `update66.sh` / the web update. This proposal is obsolete: test builds use SD/RAM, and flash writes require separate owner authorization.
- **Requests that follow (please treat as release-relevant):**
  1. **ssh by key that survives a reboot:** read `config/authorized_keys` into `/root/.ssh/authorized_keys` at each start (and a persistent host key). Today the tester's key lives
     in RAM and the owner must re-add it after every reboot; with no serial, a reboot ends the tester's access until then.
  2. **Unattended recovery after Linux starts:** if the running initramfs or user space does not reach "network up + web page + RTSP" within a bounded time, use a boot counter and previous user-space/initrd stored outside U-Boot. A broken flashed kernel cannot reach the initramfs, so its protection must happen before flashing: verify size, checksum and target partition, change one kernel at a time, and keep the owner near the camera.
  3. **The last boot's messages kept:** `dmesg` of the previous boot written to the card (or the settings slot) at boot and at a crash (`/mnt/sd/logs/boot-prev.log`), shown on the web page
     (Logs), so a failed boot can be read after the owner power cycles. Today the log in `/tmp` is lost with the power.
  4. **A runtime switch for settings that can safely change at runtime** (white balance mode, etc.); boot-time DMA allocations retain their compiled C defaults and are not live-reallocated.
  5. **No kernel or U-Boot change in a release that has not run a full day on a camera first** (the tester cannot recover a camera that does not boot).
- **Tester's side:** one camera at a time; the owner is asked to be near the camera and its power supply for the first boot of any update that changes the kernel; the SD card with the
  backup stays in; after each reboot the owner re-adds the key (one command) until request 1 is in.

### R15-03 One night on rc15 (the defaults) — `to test`
- Auto day / night (source luma, the default), night picture settings and low light on: the night switch, the picture
  at night (grain, brightness) against R12, back to day in the morning; IR LED protection lines if any; the
  calibration log (`awb=` now live, `lum=`) copied here: it sets the stock method's thresholds for a later default.

### R15-04 The owner's checks — `to test`
- R12-07 (the web page: Streams & audio bit rate mode, Day/night switches and live value, Picture anti-flicker, in
  French too) and R12-08 (no SD card: power off, card out, power on, one hour: video, page, Wi-Fi, MQTT, settings kept
  after a page reboot). Then the release: [release-3.0.1.md](release-3.0.1.md).

### R14-01 Wi-Fi recovery (`scripts/wifi-recover.sh`) — `to test` (first, with someone near the camera)
- **Safe check on a working camera** (Wi-Fi up, the script does nothing): `sh /mnt/scripts/wifi-recover.sh check; echo $?`
  = 0, and `sh /mnt/scripts/wifi-recover.sh run` returns at once with nothing on the console.
- **The power cycle itself, by hand, from the serial console** (the camera goes off the network for about a minute):
  `echo 523 > /sys/class/gpio/export; echo out > /sys/class/gpio/gpio523/direction; echo 0 > /sys/class/gpio/gpio523/value`
  -> within a few seconds dmesg shows the USB device **disconnecting** (`usb 1-1: USB disconnect`) and `wlan0` goes;
  `echo 1 > /sys/class/gpio/gpio523/value` -> the chip enumerates again, `rtl8xxxu` probes, `wlan0` back; then
  `sh /mnt/v3/linux66-sd/wifi-apply` and a ping from the LAN. **If nothing disconnects, GPIO 11 is not the Wi-Fi
  power on this board: write it here and set `WIFI_POWER_GPIO=0` in boot.conf** (the recovery then only re-probes).
- **The failure case, when it comes back** (warm reboots in a row, check `wlan0` after each): the console lines
  `[wifi-recover] no wlan0: probing the Wi-Fi chip again`, then `power cycle` if needed, `wlan0 back after the ...`,
  the camera pingable again without a power cut. `meta.txt` of the saved boots: `wifi_power_fail=`.
- **Pass:** the manual cycle disconnects and brings the chip back; a real failure recovers without a power cut.

### R14-02 Night parameter set (R12-01 again, rc14 kernel) — `to test`
- As R12-01: dmesg `tuning parameter set 1` at night and `0` at day, the log `ISP: night parameter set of the
  tuning file`, about 10 fps at night, the picture against the day set. Then the rest of R12 on rc14 (R12-02 low
  light at dusk, R12-03 / R12-05 over a night, R12-04 listening, R12-06 listening for the clicks, R12-09 dumps,
  R12-07 and R12-08 with the owner).

- **Results R14 (tester, 2026-10-31 ~12:30-13:00 local, rc14 = 7e45f14, both CIs green); rc14 installed in the .11 flash:**
  - Install: rc14 kernel (md5 7c524207…) booted once from the card (U-Boot prompt, RAM): Wi-Fi up (`wlan0: associated` at 15 s), pool 9600K, MemAvailable 21.6 MB;
    package md5 e9123d64…, `check` ok, `apply update14`, `/mnt/VERSION` 3.0.1-rc14; flash boot, Wi-Fi up again, `meta.txt` `wifi_power_fail=0`, `wlan0=yes`.
  - **R14-01 Wi-Fi recovery:**
    - Safe check on a working camera: `wifi-recover.sh check` rc 0, `run` returns at once, nothing printed: PASS.
    - **Manual power cycle of GPIO 11 (= gpio523): PASS, it IS the Wi-Fi chip's power.** `echo 0 > gpio523/value`: `usb 1-1: USB disconnect, device number 2`,
      `wlan0: deauthenticating ... (Reason: 3=DEAUTH_LEAVING)`; `echo 1`: `RTL8188FU rev B` re-enumerates 8 s later, firmware loaded, `wlan0: associated` ~11 s after the
      power came back. `wifi-apply` then gave 192.168.1.11 again. (`gpio522` and `gpio592/593` are already exported by something else; I unexported 523 afterwards.)
    - **But a side effect: after this manual cycle the link was bad for several minutes**: ping from the LAN 1.1-3.6 s (was 4-6 ms), camera-to-gateway ping 2.3-3.5 s, RX `dropped` 1503,
      the server's `dropped` rising 18 -> 68 per 5 s, while the signal read -30..-36 dBm (MCS 4-5). A warm `reboot` cleared it (6 ms, `dropped` 0-2). So the chip comes back working but
      in a degraded state; the real recovery path (`wifi-recover.sh` calling `wifi-apply`) should be checked for the same thing: maybe it needs a clean unbind / module reload or a
      longer off time than 6 s. I did not reproduce the original `Failed power on` failure (all 3 warm boots of the day on rc14 had Wi-Fi), so **the automatic recovery itself is NOT tested.**
  - **R14-02 night parameter set: PASS.** With `RTSP_NIGHTSTYLE=1` and `nightmode.sh on`: dmesg `ak39-vi 8000000.video-input: tuning parameter set 1`, log `ISP: night parameter set of the
    tuning file`, `cam_ae` `47 2812 502 256 256 0 2812` (exposure limit 2812), **`cap` 50 per 5 s (10 fps)**, 380-440 KB per 5 s, one client connected. `nightmode.sh off`: dmesg
    `tuning parameter set 0`, log `day parameter set`, `cam_ae` 7th field 1125, `cap` 125, 978 KB per 5 s. (The picture itself was not compared: the room is lit by day.) The R12-01 refusal (ENODEV) is gone.
  - Not redone on rc14 (need dusk / night / the owner): R12-02, 03, 05, 06, 07, 08, R12-04 sound, R12-09 dumps.
  - .11 now: rc14 in flash, `rtsp.env` empty, auto day/night running (luma), fps 25, soak restarted (13:0x local), Frigate connected (`clients 1`).

- **Results R12 / R13 / R14 with the owner next to the camera (tester, 2026-10-31 ~13:20-14:10 local, rc14 in flash):**
  - **R12-04 speaker: AUDIBLE but weak / crackling (owner listened).** The 20 s alert (`alert.pcm` x 20 = 10 s of 8 kHz mono, `Headphone` 5 then 3) is heard: the amplifier fix works. The owner: "faible ou grésillant", the **same at volume 3**: so it is not
    clipping from the volume setting. dmesg: `perfect asic pll clk is:480000000, actual sample rate is 8000`, `ak39_set_hp_power 1,soft_de_pipa=1`. To look at: the codec's output gain / digital volume, the amplifier supply, the PCM data format,
    the sample rate path; the playback of the stock firmware may use a different mixer setup (`amixer -c 0 contents` here if wanted).
  - **R12-06 IR-cut pulse 10 ms: PASS, heard 20 / 20** (10 out + 10 in, `IRCUT_PULSE_MS=10`, 1.5 s apart): the owner counted every click. 10 ms can become the default (I put the 150 ms default back).
  - **R12-02 10 fps in low light by day: PASS.** `RTSP_LOWLIGHT_FPS=1`, lens covered by hand: `low light: total gain 26x, sensor 10 fps, exposure up to 2812 lines`, `cam_ae` `48 2810 3540 256 256 0 2812`, `cap` 51 per 5 s,
    405 KB per 5 s; uncovered: `low light: total gain 1x, sensor 25 fps, exposure up to 1125 lines` within 40 s, `cap` 117-125. One switch each way, no flapping seen in the ~3 minutes.
  - **R12-09 ISP statistics dumps (read only): the white balance counts are NOT at word 1032.** `dmesg`: `statistics DMA area at 0x82e61dd4, 4800 bytes (white balance counts read from word 1032)`. Three dumps (lit, lit 86 s later, lens covered; `docs/linux-port/r12-09-isp-words.txt`,
    words 1032-1199, three columns): **words 1032-1071 are identical in all three dumps and look like random data** (`0xA658D3D2 0xC7C1FE74 0x3FFA5F8C ...`: an uninitialised or pseudo-random block, not counts), so the kernel's AWB and the vendor
    source were reading garbage. The words that really move are **1155, 1160-1171 and 1180-1183** (e.g. 1160-1163 `0x0004068F 0x0003A1B5 0x00019473 0x00000515` -> `0x00046795 0x0003B344 0x00020778 0x000004F6`, 1180-1181 up to `0x000B0768`
    when lit and `0x00026499` later), the histograms (words 0-1031, 756 words changed between two lit dumps, i.e. noise plus the scene) move too. The files are also on the camera's card in `/mnt/sd/r12-09/`. The implementer can work out which
    of these are the ten AWB `total_cnt`: **1160-1163, 1164-1167 (?), 1168-1171 (?) and 1180-1183 look like groups of four**.
  - **R11-01 follow-up (rc13 guard) PASS:** `RTSP_VBR=1` + `RTSP_SMART=1`: log `encoder main: smart mode 1 not used: it needs 3670016 bytes of encoder pool, 963520 free (a bigger ak39_venc.pool)`, the server stays up (`cap` 122, a client connected),
    no `/tmp/.rtsp_smart_try` left. **Server watchdog PASS:** `killall tc100_rtsp`: `service-watchdog.log` `rtsp-h26x - unhealthy, perform restart (no reboot mode, check=status, backoff=20s)` ~4 s after the kill, the server back (`clients 1`) within 90 s.
  - Camera restored: `rtsp.env` empty, auto day / night running (luma), `IRCUT_PULSE_MS` line removed, fps 25.

- **Result R12-08 camera with no SD card (tester + owner, 2026-10-31 ~13:35-13:55 local, rc14 in flash): short run PASS, the one-hour and the persistence checks NOT done.**
  - Power cut, card out, power on: U-Boot `MMC: no card present` / `** Bad device mmc 0 **` (twice), then the flash boot: console `[tc100] no SD card`, `[flashmode] no SD card: no video storage`,
    `[tc100-v3] free RTSP server + hardware JPEG pictures active`, `WebUI active on port 80`, `Auto Day/Night detection active`, `MQTT bridge service launched`, `All services initialized successfully`; `wlan0` associated
    (`[tc100] Wi-Fi settings from the SD card` is still printed, the settings come from the flash copy), no error loop in the console after boot. `board profile: unknown hardware, defaults of ...tc100-f23-rtl8188fu.conf` (a harmless
    line, but the board is a TC100: the profile detection may deserve a look).
  - From the LAN, 3 minutes after the boot and for the next ~25 minutes: ping 4-6 ms (jitter up to 54 ms, one sample of 1.8 s average at 12:47:50, back to normal the next minute), HTTP 302, RTSP port 554 open.
    **Owner: Frigate shows the picture and detects, the web page opens and reads the settings, and the page says clearly that there is no card (recording / logs) without an error.**
  - **What I could not do: any command on the camera.** The serial shell needs `tc100test/consoleshell` on the card (login prompt otherwise), so no logs, no `dmesg`, no MemAvailable, no `dropped` in this state.
    The owner postponed the persistence check (change a setting on the page, wait 1 minute, reboot from the page, still there?). **To do: that check, and an hour of Frigate with someone watching it.**
  - Suggestion: a way to read the camera's logs with no card (the web page's log view, or `dmesg` / `tc100_rtsp.log` through an authenticated CGI), since the console shell and the logs on the card both need the card.

### R12-01 Night picture settings (Day/night page: "Night picture settings of the sensor tuning") — `to test`
- **What:** at night (black and white) `tc100_rtsp` loads the tuning file's night parameter set
  (`AK_ISP_SET_TUNING_STYLE 1`: exposure up to 2812 lines, night noise filter and sharpness, AE target 45, 10 fps), and
  the day set at day (sensor back to the stream rate). The bases of live tuning, sharpness, exposure cap, anti-flicker
  and white balance are read again after each switch and the settings applied on top. Off: the switch off (as rc11).
- **Test:** switch on, Save (the server restarts). Night (dark room or the Night button): log `ISP: night parameter set
  of the tuning file`, `cap` about 50 per 5 s (10 fps), `cam_ae` 7th field 2812. Snapshot and 30 s of VLC against the
  same scene with the switch off: brightness, grain, smearing of a moving hand. Privacy masks and the clock still
  shown; live tuning values still applied. Day button: `day parameter set`, colour back, the stream rate back (`cap`).
  Frigate: still records and detects at 10 fps at night.
- **Pass:** a better night picture, masks / clock / tuning kept, day back to normal. Then (rc13) on by default.

### R12-03 Day / night "Stock firmware method" source — `to test` (needs R12-02 on)
- **What:** `DAYNIGHT_SOURCE=vendor` (Day/night page, "Light measurement"): lum = exposure x total gain / exposure
  limit x 40 / picture brightness ("Stock method value" in the live reading), night above 3584 when the white balance
  sees no daylight, day below 1536 when it sees visible light, 3 samples in a row, a switch back within 15 s locks it.
- **Test:** with R12-02 on, the live value in a lit room, a dim room by day (must stay day), at dusk and at night; then
  the source on "Stock firmware method" through one dusk and one dawn: one switch each way, the console lines `vendor
  lum=... awb day=... visible=...`, no flapping when the IR LEDs come on. The calibration log (`lum=` and `awb=`) here.
- **Pass:** clean switches both ways, the dim day room stays day. Then (rc13) the default source.

### R12-05 IR LED protection (every source; Day/night page, hours) — `to test`
- **What:** after `IR_LED_MAX_ON` seconds of night (50400 = 14 h, the stock value) day mode for 600 s, then the normal
  decision again; 0 = off. Console: `IR LEDs on for N s: day mode for 600 s (IR LED protection)`.
- **Test:** `IR_LED_MAX_ON=120` in `/mnt/config/daynight.conf` (the page takes whole hours: edit the file for the test),
  restart the daemon (`auto-night-detection stop; start`), night mode: after 2 minutes the line, day mode, 10 minutes
  later back to night (if dark). Then the page value back to 14.

### R12-07 The web page: every new switch wired — `to test` (owner, needs the login)
- Settings, Streams & audio: "Bit rate mode" (main stream form), Save: the form reports "Saved and checked", the
  selected value returns after a reload, `rtspserver.conf` [0] `vbr` matches it, and the RTSP log reports
  `vbr main 1 sub 1` or `vbr main 0 sub 0`. Switch back to CBR after the check. A normal form save must leave
  `[0] smart` unchanged; Smart mode is not on the page since rc13 (R11-01). Settings, Day/night: the
  stock method thresholds, the IR protection hours, the two switches (night settings, low light), the live "Stock
  method value"; Save and reload the page: every value comes back. Settings, Picture: anti-flicker "Camera default" and
  the 50 Hz line. In French too.

### R12-08 A camera with no SD card (the goal) — `to test` (last, after the others)
- **What:** the flash already holds kernel, initramfs, user space, vendor libraries and the settings; U-Boot tries the
  card first and boots the flash without one (the card stays the way back). Nothing is written for this test.
- **Test:** power off, take the card out, power on: video (RTSP, Frigate), web page, Wi-Fi, MQTT, settings kept
  (change one, reboot from the page, still there: R11-03), day / night and the speaker. What needs a card says so
  cleanly: recordings (page message), saved logs (`log-persist` skips), no error loop in `dmesg` / syslog. One hour.
- **Pass:** everything above. **Then the flash-only release (rc14):** the switches that passed become defaults; one
  `update66.sh apply` with the owner's agreement (dump first, `flashw` with read-back, settings kept, as for every rc);
  U-Boot untouched. The camera then runs with no card at all.

- **Results R12 (tester, 2026-10-31 ~10:10-11:40 UTC, rc12 = a25e86e, both CIs green), rc12 installed in the .11 flash:**
  - **R12-00 PASS.** rc12 kernel (md5 165426b4…) booted once from the card (U-Boot prompt, RAM), package md5 308e2478…, `check` ok, `apply update12`;
    `/mnt/VERSION` 3.0.1-rc12, pool 9600K, both encoders `open` (used 8866880, free 963520), MemAvailable 23.0-23.2 MB, `anti-flicker: camera default 50 Hz`,
    `cam_ae` has 7 numbers (7th 1125), `cam_awb` 11 numbers.
  - **R12-04 speaker: electrical part PASS, sound NOT confirmed.** `devmem 0x2017000c`: **0xC800 at rest** (bit 14 set = high = amplifier off) with the rc12 kernel; **0x8800 during
    playback** (bit 14 clear, `speaker-play.sh` of 20 x `alert.pcm`, volume `Headphone` 5), back to 0xC800 after. The owner was not next to the camera: **no one heard it**.
    To do: someone listening while `sh /mnt/scripts/speaker-play.sh /tmp/long.pcm` plays (the file was made with 20 copies of `/mnt/sounds/alert.pcm`).
  - **R12-01 night parameter set: FAIL on this kernel.** `RTSP_NIGHTSTYLE=1`, camera switched to night (`nightmode.sh on`): log
    **`ISP: the night parameter set was refused (No such device): the day set stays, colour off at night`**. `AK_ISP_SET_TUNING_STYLE` returns ENODEV from the 6.6 ISP driver:
    the ioctl is probably not implemented or the ISP style block is not set up. No 10 fps at night, `cap` stays ~125 per 5 s. Switched back (`nightmode.sh off`, auto restarted).
    The implementer needs to look at the kernel side (video-input driver patch) or drop the feature.
  - **R12-02 10 fps in low light: not exercised.** The room was too bright all morning (gain 957-2157, i.e. 3.7-8.4x; the threshold is 14x = 3584): the log line `low light:` never
    appeared. Needs dusk or a covered lens. With `RTSP_LOWLIGHT_FPS=1` the server started and ran normally.
  - **R12-03 stock method (`DAYNIGHT_SOURCE=vendor`, with RTSP_LOWLIGHT_FPS=1): runs; dim day room stays day.** Calibration log lines: `mode=day src=vendor ... idx=4241 lum=989 awb=108594719 …`;
    `lum` 923-1001 against the stock thresholds (night above 3584, day below 1536): the dim morning room (which the `ae` source called night at index 15000-30000) is **day**: the
    stock metric is the better one. Caveat: `awb=` is still the **frozen** set of R11-02, so the white balance check ("no daylight" for night) can never say night: **a night switch with this
    source cannot happen until the AWB counts are real**. Dusk / dawn: not yet. Source put back to `luma`.
  - **R12-05 IR LED protection: not tested** (needs a real night decision from the daemon; with a manual night the counter does not start). To do at dusk with `IR_LED_MAX_ON=120`.
  - **R12-06 IR-cut pulse 10 ms: inconclusive.** `IRCUT_PULSE_MS=10`, 10 x (out, in) with `setconf -k e` without error, `/var/run/ircut` follows. The two snapshots (filter out / in) are both
    almost grey (saturation 8.5 and 9.4): the picture does not show the filter position in this light, so I cannot say it moved 10 / 10. Someone should listen for the clicks. Line removed from `boot.conf`.
  - **R12-07 web page, R12-08 no SD card: not done** (need the owner's login and the card taken out).
  - Also noticed: `clients 0` in the STAT lines since this morning's reboots: nothing is connected to the camera now (Frigate not pulling?). The camera clock is wrong after a boot (00:xx) until NTP.
  - .11 now: rc12 in flash, `rtsp.env` empty, `daynight=2` auto running source `luma`, fps 25, soak restarted.

- **FINDING W-NET (tester, 2026-10-31 ~11:00-11:55 local): the .11 lost its Wi-Fi after a warm reboot, five boots in a row; only a power cut brought it back. To investigate (owner's request).**
  - Symptom: Frigate not connected (`clients 0` in the STAT lines for hours), web page unreachable, no ping from the LAN; the serial console showed `tc100_rtsp` and the web server running and listening
    on 554 / 80, but **no `wlan0`**. Not noticed during the R11 / R12 tests because they were all done over the serial console.
  - Cause in dmesg (boots 0023-0027, `/mnt/sd/logs/boot-NNNN/dmesg.log`): the USB Wi-Fi chip is found (`RTL8188FU rev B`, firmware 4.0 loaded) and then
    **`usb 1-1: rtl8xxxu_init_device: Failed power on`**, **`rtl8xxxu: probe of 1-1:1.0 failed with error -16`** (EBUSY) at ~4.0 s; no retry, so no `wlan0`.
    Boot 0023 = first rc11 boot (kernel from the card), 0024 = rc11 flash boot (`why=shutdown: net-guard: no network for 903 s, reboot (#1)`: the guard rebooted it, which did not help),
    0025, 0026 rc11, 0027 = rc12 flash boot. The older boot logs are rotated (no `dmesg.log`), so the first bad boot is unknown; the soak log shows Wi-Fi fine (`wifi -30..-41` dBm) until 09:33 UTC on rc10, and
    the failure starts with the first reboot after it. All the reboots in between were warm (`reboot`, `update66.sh` restart, U-Boot-prompt boots).
  - **Fix found: a power cut** (the owner unplugged the camera): `wlan0` associated at 15 s (`associate with 58:d9:d5:ae:1a:23 (try 1/3)`), 192.168.1.11 pings in 4-6 ms, HTTP 302, Frigate connected again
    (`clients 1`). So a warm reboot can leave the chip in a state where the driver cannot power it on, and it stays so across warm reboots.
  - Ideas for the implementer (not tested): power-cycle the Wi-Fi chip or its USB port by GPIO before the probe (and in `wifi-rescue`), re-probe on `-16` (unbind / bind of `1-1:1.0`, or `usb reset`),
    retry the probe a few times at boot, and make `net-guard` do this instead of only rebooting (a warm reboot proved useless here). Whether the chip's rail is under software control on the TC100 is for the
    hardware notes. The kernel did not change in any way that explains it (rc10, rc11, rc12 kernels all carry the same Wi-Fi code), so it may be a rare hardware / timing state: **a counter of how often it
    happens would help** (`log-persist` could keep `Failed power on` per boot in `meta.txt`).
  - Also: after this, any test that reboots should be followed by a `ping` and a look at `wlan0` from the LAN; I will do it from now on.

### R9-00 3.0.1-rc9 on the camera: the 9600K encoder pool is the driver's default — `to test`
- **What:** `ak39_venc.pool` defaults to `9600K` in the driver (patch 0015; R8-02 passed: used 8866880 bytes in H.265
  and in H.264, free 963520). The flash boot gets it with no command line change. **Off:** `ak39_venc.pool=12M` (the
  whole 12 MiB area, as rc8) - only through a card kernel; never needed so far.
- **Also in rc9 (no switch needed, harmless):** the 3D-NR reference frame is no longer tried at every video start (the
  two failed CMA allocations of 4 and 2 MB and the `no memory for the 3D-NR reference frame` line are gone from dmesg);
  `tc100_rtsp.log` lists the optional calls of the encoder library once (`encoder library: optional calls: ...`).
- **Test:**
  1. Card boot of rc9 (`c66.img` + `c66rd.gz` of rc9 on the card, as for rc8): `/proc/cmdline` complete,
     `cat /sys/module/ak39_venc/parameters/pool` = `9600K`, dmesg `pool 9600 KiB at 0x81800000 (CMA)`, **no**
     `alloc failed, req-size: 1013 pages` and no `3D-NR` line at video start.
  2. `tc100_rtsp.log`: `encoder pool: 9830400 bytes (ak39_venc.pool), no guard at its start`, both encoders `open`;
     copy the `encoder library: optional calls:` line here.
  3. `update66.sh check`, `apply` (owner's agreement, as for rc8), flash boot: same checks; MemAvailable at 2-4 min
     (R8-02 measured 21.6-22.0 MB).
  4. Overnight soak as R8-01 step 6 (one Frigate client): no reboot, no Oops / OOM, MemAvailable trend.
- **Pass:** steps 1-4. **Fail:** rename the card files back (rc8) or `update66.sh` the rc8 package; write down why.

- **Result (tester, 2026-10-31, rc9 = 6f4900c, CI green) — R9-00 steps 1-3 PASS, step 4 (overnight) running:**
  - **R8-02 closed: PASS.** 1 h with one client on the 9600K pool kernel (06:11-07:01 UTC): no reboot, no Oops, `rtsp` pid unchanged,
    `MemAvailable` flat 21.1-21.8 MB, `dropped` 0-3 per 5 s, main stream ~950-980 KB per 5 s (no HW-01 collapse), wifi -31..-45 dBm.
    (The `kerr 1` column is the word `oops=panic` in the command line: the soak script's grep counts it; ignore it.)
  - Step 1 (one card boot, RAM only through the U-Boot prompt as on night 2: rc9 `c66.img` md5 60e55dfd… as `test.img`, flash initrd):
    pool `9600K`, dmesg `pool 9600 KiB at 0x81800000 (CMA)`, **no** `alloc failed`, **no** `3D-NR` line, MemAvailable 21.97 MB.
  - Step 2: `encoder pool: 9830400 bytes ... no guard at its start`; main H.265 + sub H.264 used 8866880, free 963520, both `open`.
    `encoder library: /mnt/lib/libmpi_venc_ex.so, version "libmpi_venc V1.0.07"`;
    **`encoder library: optional calls: ak_venc_set_smart_config ak_venc_set_rc ak_venc_set_br ak_venc_set_fps ak_venc_set_gop_len ak_venc_set_iframe ak_venc_set_profile ak_venc_set_roi`**
    (R9-04 step 1: the smart-mode call exists in the library).
  - Step 3: `update66.sh check` ok, `apply /mnt/sd/tc100-3/update9` (package md5 d47f46f0…, owner's agreement): stack, kernel, initrd written,
    backup `stack-20261031-072250.bin`, restart; `/mnt/VERSION` = 3.0.1-rc9, flash boot, `cmdline` unchanged (`cma=18M`, no pool argument), pool 9600K,
    settings kept (fps 25), `MemAvailable` 21.7 MB, `dropped` 2, no 3D-NR lines.
  - Step 4: soak restarted 07:23 UTC (`/mnt/sd/soak-20261031.log`), one Frigate client; result to follow.
  - Card state: `tc100test/c66.img` and `c66rd.gz` are renamed (`c66-pool.img`, `c66rd-rc8.gz`), `test.img` = rc9 kernel, `test.img.rc8`/`.rc7` kept:
    the .11 boots from the flash. R9-01 (nr3d kernel) needs `c66.img` + `c66rd.gz` back; I will do it after the soak.

- **Results R9-01 to R9-04 (tester, 2026-10-31 07:30-08:20 UTC, IPCAM2, rc9 6f4900c):**
  - **R9-01 3D-NR (card kernel `c66-nr3d-test.img` md5 a693c2c8…, rc9 `c66rd.gz` 2012654 bytes): steps 1-3 PASS, step 4 partial, step 5 NOT run.**
    Step 2: cmdline ends `ak39_vi.nr3d=1 cma=24M flashroot=1 ak39_vi.sub_channel=1`; `cma: Reserved 24 MiB at 0x82800000`;
    `3D-NR reference frame: 4050 KiB at 0x82900000, 2025 KiB at 0x82d00000`; pool 9600 KiB; both encoders `open`, free 963520.
    Step 3 (20 min, one client, 25 fps): **MemAvailable 15.7-15.9 MB (normal rc9 kernel: 21.5-22.3 MB, so -5.6 MB), CmaTotal 36864 kB, CmaFree only
    1596-1636 kB** (normal kernel: CmaTotal 30720). Idle CPU 75-76 % (normal 72-78 %), `cap` 122-125, `dropped` 0-2 per 5 s, 942-1036 KB per 5 s
    (normal 850-980): no visible CPU or frame cost. Step 4: snapshots in the same dim morning room, daytime mode (IR-cut on), 4 JPEGs each at ~13 s apart,
    static patches (blanket, wall) normalised by their mean: **temporal noise -25 % (blanket 0.0218 vs 0.0290) and -34 % (wall 0.0314 vs 0.0474);
    spatial high-pass noise -24 % and -30 %**. Light drifted between the two series (exposure gain 4562 vs 3562) and JPEG snapshots are not the video,
    so treat it as indicative; I did not judge a moving hand or the night with the IR LEDs, nor RTSP_VBR with 3D-NR. Step 5 (1 h with Frigate) not run.
    Verdict: **measurable noise gain at no CPU cost, for 5.6 MB of RAM and only 1.6 MB of CMA left free**: worth keeping as an option; the owner decides
    whether 5.6 MB is worth it (default `nr3d=0` stays safe). Before it becomes a default, someone should check the 1.6 MB CMA margin with snapshots + recording.
  - **R9-02 day/night log: auto day/night was NOT running on the .11.** `daynight=3` (manual night, left by an earlier test) made the launcher skip the
    daemon although `config/autostart/auto-night-detection` exists. I ran `controlscripts/auto-night-detection start` (writes `daynight=2`, persisted).
    Calibration lines (source `luma`, ircut=1 = day, dim shuttered room, morning light rising): 07:31 `luma=111 ae=50 1124 6840 idx=30031`;
    07:36 `idx=30031`; 07:45 `idx=20030`; 07:50 `idx=17531`; 08:03 `idx=15029`; 08:08 `luma=92 ... 3475 idx=15257`.
    So in **day mode, in this room, the index sits at 15000-30000, the very value the night gives (30000)**: with the rc9 defaults (night above 15000,
    day below 3000) the `ae` source would call this room night all morning and never come back to day. The thresholds need a bright scene (outdoors or a window
    in full sun) and the dusk / dawn readings, which I cannot get today. Dusk (~17:50 local) and dawn are still to do; the daemon now runs and logs.
  - **R9-03 anti-flicker (log and status only, no judgement of bands by eye):** 50 Hz: `anti-flicker: 50 Hz (exposure step 281 -> 281 lines, exp_time_max 1125)`
    (the tuning file already used 281: 50 Hz changes nothing on the IPCAM2); 60 Hz: `(exposure step 281 -> 234 lines ...)`, `/var/run/isp_tune.status`
    `POWER_HZ=60`, `cam_ae` exp_time 1124 -> 936 with gain 3531 -> 4035 (the cap follows the step). Back to empty (Off): no `anti-flicker: off` line was
    written at the restart (the spec says one is). Steps 2-4 (bright window, night, `EXPOSURE_MAX_PCT=30`) not done; banding to be judged by someone
    watching VLC under LED light.
  - **R9-04 encoder:** step 1 done: `libmpi_venc_ex.so` strings hold `ak_venc_set_smart_config`, `ak_venc_set_rc`, `ak_venc_set_rc_weight`, `ak_venc_set_roi`,
    `ak_venc_get/set_gop_len` and the message `setting smart mode=%d, gop=%d, q=%d, v=%d`: the smart-mode call exists (arguments unknown to me).
    Step 2: `RTSP_VBR=1` (log `vbr main 1 sub 1`), 72 STAT lines (6 min, one Frigate client, a person in view part of the time): **899 KB per 5 s against
    950-980 KB with CBR (about -6 %)**, `enc_ms` 3790, `dropped` 16 in 72 lines (0.2 per 5 s, CBR 0-4 at the soak's sampling): the saving is small on this scene
    and the scene was not still. Reverted to CBR (`rtsp.env` empty). Step 3 `IDLE_FPS`: **not testable**: there is no `IDLE_FPS` line in `boot.conf` here and
    the motion-detection daemon is not enabled on the .11 (the log says it needs it); not changed.
  - Left on the .11: rc9 in the flash, `daynight=2` (auto, daemon running), `POWER_HZ` empty, `rtsp.env` empty, fps 25, soak running (`/mnt/sd/soak-20261031.log`).
    Card: `tc100test/c66-nr3d.img`, `c66-pool.img`, `c66rd-rc8.gz`, `c66rd-rc9.gz`, `test.img` (rc9) / `test.img.rc8` / `.rc7`; no `c66.img`: flash boot.
  - Tester slips, no firmware cause: I sent the old pool kernel again once because `split` does not overwrite its output files (3 min lost);
    a recursive grep froze the console (see R8-02). Hand-off for the implementer: rc10 candidates = fix the launcher so `daynight=3` does not hide the daemon
    silently (or log it), print `anti-flicker: off` at start, and re-think the `ae` thresholds from a bright-day reading.

### R9-02 Day / night from the ISP exposure: calibration log and measured thresholds — `to test`
- **What:** rc7 night 2 (HW-08) measured the exposure index at night: `exp_time 1124` (the maximum) and `a_gain 6840`
  (26.7x), index about **30000** with or without the IR LEDs. The defaults of the `ae` source (F-04) were placeholders
  (4000 / 1000, under the night value even in the day); they are now **night above 15000** (full exposure and about
  13x gain) and **day below 3000** (5 times less, room for the IR-cut filter and the LEDs changing the light at the
  switch). The source stays **`luma` by default**. New: `auto-night-daemon.sh` writes a **calibration line every 5
  minutes** to `/tmp/logs/daynight.log` (`HH:MM mode=day|night src=... luma=N ae=<cam_ae line> idx=N`, last 2 x 400
  lines; `log-persist.sh` copies `/tmp/logs` to the card as `other.log`), whatever the source.
- **Test:** leave the camera running through one dusk and one dawn (auto day / night on, source `luma` as now), then
  copy `/tmp/logs/daynight.log` (or `/mnt/sd/logs/boot-NNNN/other.log`) here, or its lines around the two switches.
  From them: the index in full day (indoor and outdoor if possible), when the `luma` source switched, and the index
  right after each switch. Then set the source to "ISP exposure" with thresholds taken from the log, one more dusk and
  dawn: one switch each way, no flapping when the IR LEDs come on or go off.
- **Pass:** a clean switch each way with the `ae` source. **Then** (rc10): `ae` becomes the default source with the
  measured thresholds. **Note:** the `isp` source (the ISP's dark flag) read 0 all night on HW-08: not usable.

### R9-03 Anti-flicker (`POWER_HZ`, Settings, Picture) — `to test`
- **What:** the field is back (Settings, Picture: Off / 50 Hz / 60 Hz), applied by `tc100_rtsp` whatever live tuning
  is: `AK_ISP_SET_AE` with `exp_step` = the sensor lines of one lamp pulse (28125 lines/s on the JX-F23: 281 lines at
  50 Hz, 234 at 60 Hz). The ISP's auto exposure then keeps every exposure longer than a pulse at whole pulses (its own
  code: `ak39_isp2_3a.c`, `exp_step`). **Default Off** (the tuning file's step, unchanged). `RTSP_LINE_RATE` overrides
  the line rate.
- **Test:**
  1. Indoors under mains lighting (LED bulbs or tubes), daytime mode, live tuning off: Off, look at the picture (VLC):
     dark bands rolling up or down, or a pulsing brightness? Then 50 Hz (Save): `tc100_rtsp.log` `anti-flicker: 50 Hz
     (exposure step N -> 281 lines, exp_time_max 1125)`, `/var/run/isp_tune.status` `POWER_HZ=50`. The bands stop.
  2. Outdoors or a bright window (exposure under 10 ms): the picture is not darker or blown out with 50 Hz.
  3. Night (IR): nothing changes (exposure at the maximum).
  4. With `EXPOSURE_MAX_PCT=30` also set: both lines in the log, the exposure cap still applies.
  5. Off again: `anti-flicker: off (exposure step 281 -> <tuning value> lines ...)`.
- **Pass:** 1-5. **Then** (rc10): 50 Hz by default for a camera set to a European time zone? (owner's choice); the Home
  Assistant select comes back. **Fail:** Off; write what was seen (the step value of the tuning file is in the log).

### R9-04 Encoder: VBR, idle frame rate, and the smart mode's calls — `to test`
- **What:** the encoder side of "use the SoC": `[0] vbr=1` in `rtspserver.conf` (P-08: 6 % less on a noisy night, the day scene not
  measured) and `IDLE_FPS` (F-03, frame rate lowered while nothing moves) were opt-in and not finished. rc9 adds the
  list of optional encoder calls to the log (looked up, never called), so that the vendor smart mode (long GOP on a
  still scene) can be used once its call is known.
- **Test:**
  1. The `encoder library: optional calls:` line of R9-00 step 2, and `strings /mnt/lib/libmpi_venc*.so
     /vendor/lib/libmpi_venc*.so 2>/dev/null | grep -i -E 'smart|gop|_rc|roi'` here.
  2. Day, still scene, 10 minutes each, one Frigate client: main stream bytes per 5 s with `[0] vbr=0`, then `[0] vbr=1`
     in `/mnt/config/rtspserver.conf` (restart `tc100_rtsp` as `v3/autorun-linux66.sh` does). Then a hand moving in front:
     the bytes go back up to the ceiling, no smear or blocks. Frigate keeps recording and detecting.
  3. `IDLE_FPS` as F-03 says (Frigate side: a motion still starts a recording without a missed second).
- **Pass:** VBR saves on a still day scene with no visible loss and Frigate is fine: **then** (rc10) `[0] vbr=1` by
  default. Same for `IDLE_FPS`. Smart mode: implemented only once step 1 shows its call.

### R8-01 / R8-02 results: rc8 (`372a83b`, CI run 41147884892) on IPCAM2, 2026-10-31 01:00 (tester)
Installed: package `tc100-3.0.1-rc8-update.tar` (md5 `b33b0c9d...`, 12 chunks over the serial console, each md5 checked, then `tar -x` and `md5sum -c` OK on the card),
first **one card boot of the rc8 kernel** (as on rc7: kernel from the card, flash user space, U-Boot prompt in RAM only, no `saveenv`; owner agreed to this
for the plain card boot), then **`update66.sh check` = ok, `apply`** (kernel md5 `c3687a47...`, initrd md5 `9e3f1978...`, stack, read-back md5 identical, backups of the
old partitions on the card in `tc100-3/backup/`, settings kept; the whole apply took under 2 minutes, `DONE: 3.0.1-rc8 written, restarting`). IPCAM2 now runs rc8 from its flash.
| R8-01 step | Result |
|---|---|
| 1 `slots` | **PASSED.** Card boot and flash boot: `/sys/module/ak39_vi/parameters/slots` = **3** with no `slots=` on the command line, cmdline complete (`initrd=0x81000000,2012654`, `flashroot=1`), Wi-Fi associated at 15.1 s, no Oops. **MemAvailable 19.1-19.2 MB** (rc7: 15.6). |
| 2 ISP clock and masks by default | **PASSED.** With an **empty `rtsp.env`**: `clock: in the ISP OSD (472x44 at 12,16)` (clock on) and `privacy masks: 1 in the ISP` (one mask set), `pp_ms` 1. With `RTSP_ISPOSD=0` and `RTSP_ISPMASK=0`: neither line, `pp_ms` **183-260** per 5 s at 25 fps (CPU clock). Settings restored (`osdenabled=0`, no mask, `rtsp.env` empty). |
| 3 `amixer -c 0` | **PASSED.** `amixer -c 0 scontrols` lists Headphone, LineIn, Mic, DAC out mode; `amixer -c 0 sget 'Headphone'` -> `Playback 3 [60%]`, limits 0-5; `amixer -c 0 cget name='LineIn Capture Volume'` -> `values=10`, 0-15; `amixer -D sysdefault:0 scontrols` works; **no `cannot stat aliases.conf` line any more**. Note for the doc: the plan's `sget 'Headphone Playback Volume'` does not exist as a *simple* control (use `sget 'Headphone'`, or `cget name='Headphone Playback Volume'`). Not checked: that the Settings microphone level moves `LineIn Capture Volume` (needs the UI). |
| 4 F-05 | **PASSED.** `.bootcount` was `0009`: the first rc8 boot made **boot-0010**, a "ui" reboot (`reboot-tracker.sh intent`) wrote `why=shutdown: ui: F-05 rc8 test` into it, the next boot made **boot-0011** (`0011`, first save at 159 s). |
| 5 MQTT refusal | **Partly.** `/tmp/mqtt_last_pub.status` = `1793407671 fail 5` (the code is there). The top badge "MQTT: login refused" needs the web UI (owner). |
| 6 one hour with Frigate, then the soak | **Soak started 2026-10-31 00:57 UTC** (`/mnt/sd/soak.sh`, a line every 5 min in `/mnt/sd/soak-20261031.log`: avail, CPU split, `cap`/`drop`, Wi-Fi, kernel errors). 25 fps, one Frigate client. To be read in the morning. |
Also: at 25 fps after the install: 124-126 frames per 5 s, `dropped` 0-2, MemAvailable 19.2 MB.

**Soak of rc8 on IPCAM2, 2026-10-31 00:57-05:27 UTC (4 h 33 min, still running, one Frigate TCP client, 25 fps, flash boot, MQTT login refused):** 54 samples, one every 5 min.
No reboot, no Oops / OOM / `OPEN FAILED` (the `kerr 1` in every line is the `oops=panic` word of the kernel command line, constant since the first sample), `tc100_rtsp` kept the same pid (636), 1 client throughout.
**MemAvailable 18.1-19.8 MB (average 18.8)**: 19.2 MB over the first hour, 18.5 MB over the last hour, about 0.7 MB lower after 4.5 h (not a leak yet, to confirm on the 8 h
reading). CPU split usr 6.7 / sys 13.4 / **idle 77.5 %** at 25 fps. Frames `cap` per 5 s: average 123.5 (125 expected), lowest sample 111. `dropped`: **31 in 54 samples of 5 s**
(15 samples had one, at most 4), i.e. about 0.5 frame per 5 s, in line with the 0.55 % of P-09 at 15 fps. Main stream 858-988 KB per 5 s (the 1.0 MB cap), Wi-Fi -35 to -44 dBm.
`tc100_rtsp.log` rotated by itself at the real cap (a `tc100_rtsp.log.1` of 262 KB next to the live log): **O-05 rotation passed at 256 KB**. `/mnt/sd/logs` holds `boot-0007` to `boot-0011` (5 kept,
the oldest removed), so log-persist runs and keeps its limit. The MQTT status still reads `fail 5` (broker refusal, owner action).

**Historical R8-02 record (2026-10-31; superseded, not an open test):** the old procedure tried to override the
9600K pool through a test-kernel command line. Do not use that procedure or artifact path. The validated 9600K pool is
now the compiled kernel default; test-only arguments use `pack66/boot66b.sh`'s `EXTRA`.

**Historical implementer response (2026-10-31):** the card test kernel's built-in command line was then
`ak39_venc.pool=9600K flashroot=1 ak39_vi.sub_channel=1` (`CMDLINE_EXTEND`, after the U-Boot arguments; `S39tc100-linux66`
greps `/proc/cmdline` for `flashroot=1`, which holds the appended part). Same artifact name `tc100-linux66-hw02-pool9600k`,
from the CI run of the commit `[rc8] HW-02 card kernel boots the flash user space`. The other artifacts of that run
are the same rc8 build (only the build stamp differs). Historical notes, not current instructions:
- `flashmode-prep.sh` only mounts (`stack`, `vendor`, settings); nothing in the flash mode start writes the flash.
- **Before the reboot:** the hook's `sdboot` carries a fixed `initrd=0x81000000,<size>`. Read it (U-Boot environment,
  read only) and check it equals the size of the card's `c66rd.gz` (2012654 for rc8). A larger file is cut short, the
  kernel panics, and `panic=10` brings it back to the same card boot every time (way out: the owner takes the card out).
- `/proc/cmdline` must end with `ak39_venc.pool=9600K flashroot=1 ak39_vi.sub_channel=1`; R8-02 step 1 is otherwise
  unchanged. Way back as before: rename `tc100test/c66-rc8.img` back to `c66.img` (and the card's `c66rd.gz` back to
  what it was, if you replaced it).
- Without waiting for CI, the same start can be had with the current pool kernel and an empty file
  `tc100test/flashmode` on the card (`S39` line 25 takes it as `flashroot=1`); rename it away after the test, or every
  later card boot also runs from the flash.

### R8-01 3.0.1-rc8 on the camera — `to test`
- **What:** the rc7 tree plus: `slots=3` default (kernel), ISP clock and ISP masks default (`tc100_rtsp`), the F-05 and
  `amixer` fixes, the MQTT refusal in the web UI. `VERSION` = `3.0.1-rc8`.
- **Test, in this order** (card boot of the kernel first, then the flash install with `update66.sh` as for rc7):
  1. `/proc/cmdline` complete; `cat /sys/module/ak39_vi/parameters/slots` = **3** with no `slots=` on the command line;
     Wi-Fi, 15 fps, `MemAvailable` about 18.5-19.5 MB (rc7: 15.6).
  2. `tc100_rtsp.log` with an empty `rtsp.env`: `clock: in the ISP OSD ...` (when the clock is on) and, with a mask
     set in Settings, Privacy & overlay, `privacy masks: N in the ISP`; snapshot: clock and mask as in HW-07 / HW-04.
     `RTSP_ISPOSD=0` in `rtsp.env` + restart: no `clock: in the ISP` line, clock drawn by the CPU (`pp_ms` back to ~100+).
  3. `amixer -c 0 sget 'Headphone Playback Volume'` works (rc 0, no `aliases.conf` error); the Microphone level of
     Settings (UI-12) is applied (`amixer -c 0 sget 'LineIn Capture Volume'` follows it).
  4. F-05: on the card of IPCAM2 (`.bootcount` = `0009`) one reboot makes `boot-0010`, the next `boot-0011`.
  5. MQTT with the current refused login: the top badge reads **MQTT: login refused** (French: "MQTT : connexion
     refusée"), `/tmp/mqtt_last_pub.status` ends with ` fail 5`. After the owner fixes the password: **MQTT: ok**.
  6. One hour of streaming with Frigate at the camera's frame rate: `dropped` as rc7 (P-09: 0.55 %), no Oops / OOM.
     Then the overnight soak of rc8.
- **Pass:** all six; `MemAvailable` gain present; nothing worse than rc7.
- **Fail / revert:** `ak39_vi.slots=4` on the command line (card boot) or `RTSP_ISPOSD=0` / `RTSP_ISPMASK=0` in
  `rtsp.env`; whole build: reinstall rc7 with `update66.sh`.

## Hardware use and memory (2026-10-30, commits `[hwaccel] ...`)

Context: [hardware-acceleration.md](hardware-acceleration.md). None of this was compiled or run before it was pushed
(no compiler on the author's machine): the first check is that the CI run is green.

### HW-05 Sharpness by the ISP (Image page, `SHARPNESS`) — `to test`
- **What:** the Sharpness slider is back on the Image page. `tc100_rtsp` scales the tuning file's medium and high
  frequency gains (`AK_ISP_SET_SHARP`, manual and 9 gain-linked sets) by 2 % per step. On by default (nothing is written
  while the slider is at 0).
- **Test:** live tuning on, sharpness -50, 0, +50: log `sharpness: N in the ISP (medium a -> b, high c -> d)`; the
  picture gets softer / sharper (compare snapshots of the same scene); bit rate goes down / up a little. The "Applied on
  the camera" line under the form shows the value.
- **Fail:** picture broken or unchanged at ±50: note the logged gains; `RTSP_ISPTUNE` does not cover it, set SHARPNESS=0.

### HW-09 Noise reduction by the ISP (Image page, `DENOISE`, item 37) — `partly passed` (2026-11-12, .11 rc37, daylight)
- **What:** a Noise reduction slider on the Image page. `tc100_rtsp` stretches the weight curves of the tuning file's
  NR1 (raw) and NR2 (luma) sets, manual and 9 gain-linked, along the pixel difference: 2 % per step, -50 = almost none,
  +50 = twice as wide. The driver keeps picking the set of the gain level. Nothing is written while the slider is at 0.
  At each video start the log has `noise reduction: gain levels ...` and the NR1 / NR2 mode and sets (read only).
  Also a "Noise Reduction" slider in Home Assistant (MQTT command `isp_denoise`).
- **Test:** live tuning on, at night (gain at its maximum, the iso16 set), noise reduction -50, 0, +50: log
  `noise reduction: N in the ISP (iso16 NR2 w[4] a -> b)`; the grain on flat dark areas goes up / down (compare
  snapshots of the same scene); the bit rate goes up / down. The "Applied on the camera" line shows the value.
- **Fail:** picture broken, frozen or unchanged at ±50: note the log; set DENOISE=0 (the tuning file's values come
  back at the next video start).
- **Also (review of 2026-11-11, `docs/linux-port/frontier/nr-2026-11-11.md`):** DENOISE=25, restart tc100_rtsp: the
  `a` of `w[4] a -> b` must be the same as before the restart (base not stretched twice); a day / night switch with
  DENOISE != 0 logs `noise reduction: 25 in the ISP` again after `night parameter set`; alternate -50 / +50 every
  second for 10 min while streaming: no kernel message, no corrupted frame.
- **Result 2026-11-12 (.11, 3.0.1-rc37, by day, through `isp_tune_set` as the page does; isp_tune.conf restored after,
  backup `isp_tune.conf.bak-20261112`):**
  - start-up log: gain levels and the NR1 / NR2 sets of the day and of the night parameter set: **passed**;
  - -50 / 0 / +50 / 25: `iso16 NR2 w[4] 451 -> 0 / 451 / 834 / 709`, `/var/run/isp_tune.status` follows: **passed**;
  - DENOISE=25, restart of tc100_rtsp: `451 -> 709` again (base not stretched twice): **passed**;
  - -50 / +50 every second for 10 min while streaming (497 changes, 94 applied: the file is read every few seconds):
    no refusal, 0 dropped frames in 121 STAT lines, client kept, no kernel error (one `tuning parameter set 0` line,
    the day set), base stays 451: **passed**; day picture after it clean;
  - still to do **at night** (gain at its maximum): grain at -50 / 0 / +50 on snapshots, and `noise reduction: N in the
    ISP` again after a day / night switch with DENOISE != 0.

### HW-08 Exposure state for day / night (`/tmp/cam_ae`) — `to test`
- **What:** every 2 s `tc100_rtsp` writes `lumi exp_time a_gain d_gain isp_d_gain dark_flag` from
  `AK_ISP_GET_AE_RUN_INFO`. Nothing uses it yet. The day / night daemon decides from `/tmp/cam_luma`, the mean luma
  of the picture *after* auto exposure, which stays near the AE target whatever the light: exposure time and gains
  measure the scene light.
- **Test:** record `/tmp/cam_ae` and `/tmp/cam_luma` in daylight, at dusk, at night with the IR LEDs on and off.
- **Next:** if the values separate day and night clearly, switch `scripts/auto-night-daemon.sh` to them (with
  hysteresis), so the IR light itself does not flip the mode back.

## Web UI on 3.0: checks that need the camera (audit of 2026-10-30)

A static audit traced every control of the web UI to what acts on it on 3.0. The fixes are in the commits
`[ui30] ...`; these checks remain. Write the result after each line.

- UI-01 `passed` (2026-10-30, f9c3d81: crond, crontab, mkfifo, timeout, usleep all present) — Busybox applets: `busybox --list | grep -E '^(crond|crontab|usleep|mkfifo|timeout)$'`. Without
  `usleep` the IR-cut pulse of `bin/setconf` becomes 1 s; without `crond` the scheduled reboot never runs.
- UI-02 `to test` — Time zone: set `CET-1CEST,M3.5.0,M10.5.0/3`, reboot; `date` over ssh, the OSD clock, a new
  recording's file name and the log times agree.
- UI-03 `to test` — IR-cut: Day / Night from the dashboard; the filter clicks and the picture changes the right way
  (the UI state is `/var/run/ircut`, not read from the coil).
- UI-04 `to test` — Auto day / night at dusk or in a dark room: `watch -n2 'cat /tmp/cam_luma /tmp/cam_ae'` and the
  `[auto-night]` lines; note any flapping when the IR LEDs switch on (see HW-08).
- UI-05 `to test` — Image orientation select: Mirror, Flip, Rotate 180; masks, OSD clock and snapshots follow.
- UI-06 `to test` — Video: GOP, min / max QP from Settings reach `tc100_rtsp` (`-q -Q -g -G` in `ps`, keyframe
  interval in VLC's codec info). A camera still holding the old shipped values (QP 20..51, GOP 64 / 32, never applied
  before) keeps QP 25..48 and GOP 2 s; set e.g. GOP 15 and QP 22..45 and check they apply, then the bit rate and the
  picture under motion. Orientation select (Mirror / Flip / Rotate 180): picture changes within 1 s without a
  stream restart, kept after a reboot; `docs/api.md` says 1 = horizontal flip, the code (`bin/setconf`,
  `src/ispflip`) 1 = flip, 2 = mirror: correct the doc after looking.
- UI-06b `to test` — No stream restart any more when switching live tuning, sound detection, two-way audio or the
  motion zones (all read live); the sub-stream switch still restarts. Saving the Image form keeps values set from MQTT.
  Home Assistant: the anti-flicker and Privacy Shield entities are gone. Wizard: only Standalone and Frigate + HA;
  after the Frigate profile, motion and OSD switched on again in Settings stay on after a reboot. Motion events carry
  a picture (`/tmp/motion_snap_*.jpg`, 5 kept).
- UI-07 `to test` — Motion: red LED blinks on motion with "Blink LED" on; the Recordings page timeline shows a
  picture for each event; "On motion" recording with Detection off records nothing (the UI says so).
- UI-08 `to test` — Network: static IP without DNS, reboot: `/etc/resolv.conf` holds the gateway, `ntpd` resolves.
  Changing the RTSP port restarts the server on the new port.
- UI-09 `to test` — Wi-Fi tile: `cat /proc/net/wireless` and `iw dev wlan0 link` give the signal.
- UI-10 `to test` — Rescue access point, from the serial console (it takes wlan0): `sh /mnt/scripts/wifi-rescue.sh
  start`; a phone sees it, `http://10.42.0.1` answers.
- UI-11 `to test` — Scheduled reboot 2 minutes ahead fires (needs UI-01 `crond`).
- UI-12 `to test` — Microphone level 0..15: `amixer -c 0 cget name='LineIn Capture Volume'` follows the setting.
- UI-13 `to test` — Speaker / push-to-talk: a clip through `scripts/speaker-play.sh` is heard; amplifier polarity
  (`SPEAKER_AMP_ACTIVE`, GPIO 14) and RTSP two-way audio from go2rtc / Home Assistant.
- UI-14 `to test` — Home Assistant: the entities that appear all act (no anti-flicker or privacy entities any more).
- UI-15 `to test` — Telegram: `/mnt/bin/telegram p`, and curl over TLS to `api.telegram.org`.
- UI-16 `to test` — Settings size: 10 presets plus MQTT, then `cat /tmp/cfg-persist.status` (a 36 KB slot).
- UI-17 `to test` — Memory Guard: its default thresholds (warn 8192, critical 4096 KB) against the real MemAvailable
  (about 10 MB, more after HW-02); the critical stage must not stop motion detection in normal use.
- UI-18 `to test` — Listen in the browser with the RTSP audio track on; syslog (`ps | grep syslogd`, `/var/log`).
- UI-19 `to test` — SD card mount / eject / resume with FAT32 and exFAT cards; an update uploaded without a card.
- UI-20 `to test` — Reset button held 20 s: only a reboot on 3.0.
- UI-21 `to test` — Settings regrouped (commits `[ui30] Settings: shorter menu...`, `Privacy masks apply whatever
  live tuning is...`): on a desktop and a phone, every tab opens (Picture, Privacy & overlay, Day/night, Streams &
  audio, Detection, Recording, Network, Integrations, System, Update & backup), an old `#nav_audio` bookmark lands on
  Streams & audio. A mask saved with live tuning **off** is painted (stream, snapshot) and the tuning switch stays off;
  a mask-only save with tuning on keeps it on. Orientation alone changes only the flip (OSD, clock, day/night kept).
  Saving the recording settings does not restart the stream. MQTT save and "Refresh Home Assistant Entities" work in
  the merged card; the rescue Wi-Fi line fills in under the Wi-Fi card.
- UI-22 `to test` — Web UI pass (commits `[webui] ...`, HTML/CSS/JS only, no CGI change). On a desktop and a phone, in
  French and English:
  - Settings: orientation alone saves (was blocked by the "ip" check); a negative sound threshold (-30) saves; Wi-Fi
    refuses a password with `"` or `\` or outside 8..63 characters before sending; "Install & reboot" posts
    `update.cgi?cmd=install` (was a ReferenceError; cancel at the confirm or use a test package); the Home Assistant
    badge follows the MQTT and Discovery switches; drawing a mask on a phone marks the form changed.
  - Shell: reboot from the menu gives a green toast (a dropped connection gives the neutral "probably restarting");
    with the network cut, open Logs, restore it and click Logs again: it reloads; leaving Live for Settings closes the
    `live.cgi` connection (`ps`: the sub-stream encode stops); `camcontrols.cgi?cmd=panel` is not polled while the
    Dashboard is shown; the dashboard snapshot keeps refreshing over slow Wi-Fi.
  - Config editor: switch files with unsaved edits and cancel (the list goes back); a value containing a literal `\n`
    and a file with a tab load and save unchanged. Backup: restore and JSON import right after a page load (no 403).
  - Recordings: play, download and delete a clip, also one whose name has a space. Logs: switch tabs quickly, Clear,
    Download, the saved-logs list.
  Found on the way, needs a CGI change (not done): `wizard.cgi` says an empty Wi-Fi password gives an open network but
  `wifi_set_config` refuses it; `wifi_set_config` strips `"` and `\` instead of refusing them; `configeditor.cgi`
  read does not escape control characters in its JSON (the page works around it); `viewrecords.cgi` remove leaves the
  `.jpg` thumbnail; `config_exchange.cgi` / `upload_backup.cgi` messages are English only.

Not fixed, for later: the action endpoints left from 2.x that no page calls (`set_stream_topology`,
`set_onvif_stream_policy`, `set_rtsp_preset`, `set_rtsp_quality_profile`, `set_client_profile`, `pair_home_assistant`,
`complete_setup_wizard`, `conf_autodaynight`, ...); the performance profiles of `system.sh` write values 3.0 does not
read; anti-flicker (see above).

## New features using the freed CPU (2026-10-30, commits `[feat30] ...`, `[live] ...`)

Checked before pushing with `tests/docker/local-ci.sh` (tests + ARM build); nothing run on a camera.

### F-01 Live video in the browser (`live.cgi`, Media Source Extensions) — `to test`
- **What:** the live view plays the camera's H.264 stream (sub-stream 640x360 when it is H.264, else the main stream)
  as fragmented MP4, no re-encoding; "Video / Snapshots" switch on the live view (remembered by the browser); at most
  2 viewers, a viewer is dropped after 1.5 s without reading, reconnects every 10 min. Snapshots as before otherwise.
- **Test:** Chrome / Safari on a desktop and a phone: video within 1-3 s, `/tmp/tc100_live/status` reads
  `stream=sub codec=avc1...`; CPU with Video vs Snapshots (`cpu-profile.sh 60`); a third tab stays on snapshots;
  after closing the tabs `/tmp/tc100_live` is empty and the sub encoder stops (STAT); hiding the tab closes the
  connection; 15 min of video over Wi-Fi (reconnect near 10 min without a long freeze); sub codec H.265 with main
  H.264 serves the main stream, both H.265 = snapshots.
- **Off:** "Snapshots" on the switch.

### F-03 Lower frame rate when nothing moves (`IDLE_FPS`, opt-in) — `to test`
- **What:** with motion detection on, `IDLE_FPS=5`, `IDLE_AFTER=10` (boot.conf, Streams & audio card): after 10 s
  without motion or sound event the encoders get 5 fps; full rate again at the first motion. Not applied while the
  recorder writes continuously.
- **Test:** stay still: log `idle frame rate: ... 5 fps instead of 15`, STAT `cap` 25 per 5 s; wave: `back to the full
  rate` within about 1 s; Frigate and a motion recording still start correctly. **Off:** `IDLE_FPS=0`.

### F-04 Day / night from the ISP exposure (`DAYNIGHT_SOURCE=ae|isp`, opt-in) — `to test`
- **What:** index `exp_time * a_gain/256 * d_gain/256 * isp_d_gain/256` with `AE_NIGHT_ABOVE` / `AE_DAY_BELOW` (the
  defaults 4000 / 1000 are placeholders), or the ISP's own dark flag; night after 10 s, day after 60 s. Live reading
  on the Day/night tab. Default stays `luma`. Uses the HW-08 data.
- **Test:** note the reading in daylight, dusk, night with IR on and off; set the thresholds (day clearly below the
  IR-lit night index); switch to the `ae` source: no flapping when the IR LEDs come on. Check the gain unit (256 = 1x?).
  **Off:** source "Picture luminance".

### F-06 Memory Guard defaults (warn 6144 / critical 3072 KB) — `to test`
- **What:** the old defaults (8192 / 4096) sat next to the normal MemAvailable; cameras holding exactly them are
  migrated when the service starts; the warn stage no longer stops `auto-night-detection`.
- **Test:** `/tmp/log/memory-guard.log` shows the migration once; no warn / critical stage in a day of normal use.
  **Off:** `MEM_GUARD_ENABLE=0`.

Not done: 3D-NR (its 6.2 MB reference frame does not fit until HW-01b / HW-02 free memory).

## Optimisation for the AK3918 (2026-10-30, commits `[opt] ...`)

Baseline to note before flashing the new build: `grep -E 'MemTotal|MemAvailable|Slab|CmaFree' /proc/meminfo`, `ps`
(count the `sh` processes), `scripts/cpu-profile.sh 30`, `ls -l /tmp/logs`. Same commands after; one line per result.

### O-01 Kernel config: less RAM (`defconfig_cma`) — `to test`
- **What:** about 520 KB less kernel RAM and 107 KB less zImage (printk buffer 64 KB, no io_uring / zram / LZ4 /
  ZSTD / signed regdb / inet_diag, slab merging on, small CRC32 tables), squashfs fragment cache 1 block instead of 3
  (2 x 256 KB less per mounted squashfs: stack and vendor in flash mode), `MAGIC_SYSRQ` on (serial break off) so the
  last-resort reboot of `service-watchdog.sh` (`echo b > /proc/sysrq-trigger`) works.
- **Test:** boots from the SD card (c66.img) then from flash; `MemTotal` and `MemAvailable` up by about 0.5 MB, plus
  about 1 MB in flash mode; a full boot log still fits in `dmesg` (first lines are the `Booting Linux` banner);
  Wi-Fi associates (regulatory domain still set: `iw reg get` from ext/); browsing the Settings pages from flash is not
  slower; `echo b > /proc/sysrq-trigger` reboots. **Off:** the previous kernel.
- **Result 2026-10-30, IPCAM2, f9c3d81 (CI run 41089089376), installed in the flash of IPCAM2 (.11) with update66.sh, settings kept (O-01 + O-02 + B-01 + B-02 together):** MemTotal 59932 kB,
  **MemAvailable 15.3-15.9 MB** two minutes after a flash start (rc5 with 0015: 10.8 MB; rc4: 10 MB), no OOM or
  allocation failure, Wi-Fi associates, 15 fps (75 frames per 5 s, about 1 MB), CPU 84 % idle over 10 s with a
  client. Web server answers (`/` 302, `state.cgi` 401 without a session). `curl` over TLS works for the services
  (`CURL_CA_BUNDLE` from autorun: api.github.com 200); note: the serial console shell does not get that variable
  (curl exits 60 there), harmless for the services. BusyBox no longer has `wget` (no script uses it).

### O-02 Smaller initramfs (`v3/initramfs-prune.txt`) — `to test`
- **What:** hostapd sample config, hostapd_cli, wpa_passphrase, the xz tools and liblzma out of the RAM image (about
  0.45 MB); `mksquashfs` in `ext/` gets its own liblzma.
- **Test:** boot; the rescue access point starts (`sh /mnt/scripts/wifi-rescue.sh` from the serial console, UI-10);
  the 3.0 install path that runs `/mnt/ext/bin/mksquashfs` still starts it (`/mnt/ext/bin/mksquashfs -version`).

### O-03 tc100_rtsp and libakuio.so stripped, `-mtune=arm926ej-s` — `to test`
- **What:** both are copied to /tmp (RAM) at boot; 128 -> 112 KB and 16 -> 13 KB. Unstripped copies (`*.dbg`) are
  in the CI symbols artifact for decoding.
- **Test:** the stream starts (VLC), the STAT line appears; `ls -l /tmp/tc100_rtsp /tmp/libakuio.so`.

### O-04 Shell side: fewer forks, fewer resident processes — `to test`
- **What (commits `[opt] Web CGIs...`, `[opt] Resident daemons and boot...`):** `state.cgi?cmd=dashinfo` cached 300 s
  in `/tmp/state_dashinfo.cache` (dropped when the host name or a config file changes); no `cmd=hostname` and no
  `get_ptt_vol` at page load; `csrf_guard` returns early on GET; Day/night tab polls every 5 s with about 2 forks
  instead of 20; `camcontrols.cgi?cmd=panel` without func.cgi; the day/night daemon no longer sources
  common_functions.sh and waits with `read -t` on a FIFO; web-guard runs net-guard every 3rd minute while the gateway
  answers (every minute after a failure, same reboot limits) and sdinfo only when the card changed or every 10th
  minute; the health prober answers "stopped" for motion without a shell and does the RTSP DESCRIBE every 6th probe;
  crond starts only when its crontab has an entry; boot.conf parsed once at boot; one `ln` for the www and vendor
  links; `rtsp-launch.sh` takes the pid from `$!` (no `sleep 2`) and opens the log with `>>` and `RTSP_LOGFILE`.
- **Test:** the 12 checks of the implementer's report, in short:
  1. `cat /var/run/v4l2rtspserver.pid` = `pidof tc100_rtsp`, its `oom_score_adj` is -900; `/mnt/config/rtsp.debug`
     still sends the log to the console.
  2. `time curl -s 'http://127.0.0.1/cgi-bin/state.cgi?cmd=dashinfo&format=json'` (with `-u root:<password>`) twice: second fast, same JSON;
     `touch /mnt/config/rtspserver.conf` rebuilds it.
  3. Browser network tab at page load: no `cmd=hostname`, no `get_ptt_vol`; the title shows the host name; Talk or
     the volume slider fetches `get_ptt_vol` once.
  4. A POST without the CSRF header gets 403; the UI saves still work.
  5. Day/night tab refreshes every 5 s; `state.cgi?cmd=daynight&format=json` same fields as before.
  6. Day / Night buttons under the picture work (`camcontrols.cgi?cmd=panel`).
  7. Change LUMA_NIGHT: applied at the next cycle; `top`: the day/night daemon near 0% (the FIFO wait really waits).
  8. Router unplugged: `/tmp/net-guard/down_since` within about 3 min, reboot at NET_GUARD_MIN as before. Card out
     and in: the SD panel follows within 1 min. `kill` httpfront: restarted, then the rescue telnet if it fails.
  9. Motion off: `/tmp/health_snapshot.cache` says motion "stopped"; `/tmp/health_rtsp_deep` exists.
  10. Fresh config: no `crond` after boot; saving a scheduled reboot starts it.
  11. `ls /tmp/www` lists every page (if the multi-target `ln` failed the UI would 404), `ls -l /lib | grep mnt`.
  12. Idle camera, `ps` a few times over 3 minutes: no new `sh` / `ping` every minute.

### O-05 Video server: one read of the encoder output, log rotation, less per-frame work — `to test`
- **What (commit `[opt] tc100_rtsp: log rotation, one read of the encoder output, ...`):**
  - **Log rotation (bug):** the STAT line every 5 s made `/tmp/logs/tc100_rtsp.log` grow without limit in RAM
    (about 2.6 MB a day). Above `RTSP_LOGMAX` (256 KB) it is now renamed to `.1` and reopened (first line `log rotated`).
  - **Encoder output read once:** it is uncached memory. Each frame is copied once with word reads, the NALs are found
    once, the encoder buffer is given back at once, and the GOP cache keeps that copy. The RTSP clients, the recorder,
    the live MP4 and the IDR test then read the cached copy; before, they read the uncached buffer 4 to 6 times.
  - **Per-frame calls cut:** no `getenv`, file checks every 0.25 s, OSD clock text once a second, colour-table
    identity flags. JPEG tables are built once per quality, and each JPEG is read once from the engine.
  - **Snapshot cadence:** the 2 s snapshot cadence now applies only if the picture was read in the last 4 s (the
    dashboard kept it at 2 s forever).
  - **Client queues:** they shrink back after a congestion.
- **Switches:** `RTSP_FRAMECOPY=0` (frame and JPEG reads as before), `RTSP_QTRIM=0` (queues never shrunk),
  `RTSP_LOGFILE` unset (no rotation), in `/mnt/config/rtsp.env`.
- **Test** (same scene, bit rate and clients before and after):
  1. After about an hour: `ls -l /tmp/logs` shows `tc100_rtsp.log` under 256 KB and a `.1`; `MemAvailable` stops
     drifting down over a day.
  2. STAT `snd_ms` lower than with `RTSP_FRAMECOPY=0`, `enc_ms` unchanged; `scripts/cpu-profile.sh 30` for both.
  3. Main and sub, H.264 and H.265, in VLC and Frigate: clean picture (no green or grey blocks). A client that joins
     mid-GOP starts at once on the cached keyframe. One TCP and one UDP client together. Recordings open with no gap,
     and the live video in the browser plays. Any artefact: compare with `RTSP_FRAMECOPY=0`.
  4. `/tmp/stream.jpg`, `/tmp/frame_ch0.jpg`, the dashboard picture and a recording thumbnail are valid JPEGs. The
     dashboard picture still refreshes smoothly; if it lags, the 4 s window is the cause.
  5. A slow viewer for 30 s, then `MemAvailable` recovers about a second after it catches up (compare with
     `RTSP_QTRIM=0`).
  6. The black-and-white switch reacts within about a second, and the software clock still ticks every second.

### B-01 Initramfs reduced to the boot essentials: ALSA tools, libasound, dropbear, libz/libgcc_s/libatomic moved to `ext/` — `to test`
- **What (commit `[big] ...`):** the RAM image (ramfs, never reclaimed) goes from 4.18 MB of files (4452 KB du) to
  2.51 MB (2720 KB du), the xz initrd from 1.51 MB to 1.03 MB (partition 2,012,654). Out of it, into `ext/` of the user
  space (`/rom/ext` in flash mode, the card tree in SD mode; page cache, read on demand): `aplay`, `arecord`,
  `amixer`, `libasound.so.2` (`ext/lib`), `/usr/share/alsa` (`ext/share/alsa`, without the alsactl init files), `dropbear`
  (and its links ssh/scp/dbclient/dropbearkey, not shipped any more), `libz`, `libgcc_s`, `libatomic` (`ext/lib` only
  for the tools that need them: curl, mksquashfs); the xz helper scripts are dropped. `stack.sqfs` grows from 1.97 to 2.46 MB
  (partition 2.83 MB). **Kept in the RAM image:** busybox, musl, `wpa_supplicant` + libnl-3/genl (Wi-Fi up without
  the user space; moving them would save 0.78 MB more), init scripts, `udhcpc` script (telnetd at boot: see S-01).
  How callers find the moved files: `/usr/bin/aplay|arecord|amixer` and `/usr/share/alsa` are links into `/mnt/ext`
  (CGIs run with busybox httpd's reset PATH, `tc100_rtsp` does `execlp("arecord")`), `etc/ld-musl-arm.path` is baked into
  the initrd (`/lib /usr/lib /mnt/ext/lib`, same as autorun writes), `etc/profile.d/tc100-ext.sh` adds `/mnt/ext/bin`
  to login shells, `S50dropbear` is `v3/S50dropbear-linux66` (looks in `/mnt/ext/bin`, then `/mnt/sd/ext/bin`: in SD mode
  `/mnt` is the card only after autorun, the card is already at `/mnt/sd`; no dropbear = a console line and the
  telnetd fallback of S-01). `S39tc100` logs a warning if the user space has no `ext/bin/aplay`.
- **Off:** none at run time. The initrd and the user space must be updated together (the updater writes `stack` first,
  `initrd` last; a card tree must be the one of the same build). New initrd + old user space = no audio tools, no ssh
  (the telnetd fallback of S-01 and everything else work); old initrd + new user space works.
- **Test** (flash mode, then SD mode `tc100test/c66.img` + card tree, then flash mode with the card removed):
  1. `/proc/cmdline` shows the full initrd size; `free`: MemAvailable about 1.7 MB higher than before.
  2. `ls -l /usr/bin/aplay /usr/share/alsa` (links to `/mnt/ext`), `aplay -l` and `arecord -l` list the card,
     `amixer -c 0 scontents` works from the serial shell and from an ssh session (`PATH` has `/mnt/ext/bin`).
  3. RTSP with audio plays (VLC: sound), the web UI Listen button and the Talk / sound test (speaker) work,
     `pidof arecord` while an audio client is connected.
  4. `ssh root@<ip>` works (password of config/user.pwd) and `ps | grep dropbear`; boot log has `Starting dropbear sshd: OK`
     and no `dropbear is not in the user space` line. Since rc7 (S-01) port 23 is closed at boot.
  5. Wi-Fi up as before; `curl -sI https://example.org | head -1` and `jq -n 1` (`libz`, `libatomic` from `ext/lib`);
     `iw reg get`.
  6. Fallbacks: card removed in flash mode (everything works, no video storage); `tc100test/flashmode` absent and
     no `flashroot=1` (SD mode) works; a card tree from before this build with this initrd prints
     `user space without ext/bin/aplay` and still brings up Wi-Fi, web UI and video.

### B-02 Slimmer Buildroot base (busybox, alsa-lib, hostapd, wpa_supplicant, dropbear) — `to test`
- **What (commit `[big] Slim Buildroot base ...`, `v3/buildroot/` only):**
  - **busybox:** 98 unused applets off, 290 -> 192; IPv6, CIFS, bzip2 and verbose usage off; 968 -> 681 KB.
  - **alsa-lib:** only PCM and mixer (`hw`, `plug` and the conversion plugins; no seq, rawmidi, ucm, topology);
    903 -> 554 KB. alsactl, alsamixer and ncurses are gone.
  - **Wi-Fi tools:** hostapd nl80211 only, without the extras; wpa_supplicant without TDLS / 802.11r.
  - **Other:** dropbear without the ssh client; libnl-route, libgcc_s and the single CA certificate files removed.
  - **Removed applets you might type:** `wget` (use `curl`, in ext/), `nslookup`, `traceroute`, `telnet` (the client;
    `telnetd` stays), `arp`, `fdisk`.
  - **Combined with B-01, measured:** unpacked initramfs 2384 KB (was about 4450 KB), xz initrd 895,968 B,
    `stack.sqfs` 2,195,456 B (partition 2,830,336).
- **Off:** the previous build.
- **Test:**
  1. `busybox --list | wc -l` = 192, and no `not found` from S01..S50 on the console.
  2. Microphone: `arecord -q -D hw:0,0 -f S16_LE -r 8000 -c 1 -t raw -d 3 /tmp/a.raw` gives about 48000 B. RTSP audio
     and the web Listen button work.
  3. Speaker: `aplay -q -D plughw:0,0 -t raw -f S16_LE -r 8000 -c 1 /tmp/a.raw`, and Talk / the sound test of the UI.
  4. Mixer: `amixer -c 0 cset name='LineIn Capture Volume' 10`.
  5. Wi-Fi client, and the rescue AP (`scripts/wifi-rescue.sh`: hostapd starts and a phone joins).
  6. `ssh` and `scp` into the camera.
  7. Web login and CGIs, `ftpd`, `telnetd`, `crond` (scheduled reboot), `ntpd`, the SD card mount.

### O-06 One housekeeper loop for the slow shell daemons — `to test`
- **What (commit `[big] One housekeeper loop ...`):** `scripts/housekeeper.sh` replaces web-guard, log-persist, the
  rtsp / mqtt / onvif / telegram service watchdogs and health-snapshot (separate `sh` processes) with one resident
  loop. It waits with `read -t` on a FIFO, 30 s at most.
  - **Periods are unchanged:** web 60 s, network check 60 s (run every 3rd minute while the gateway answers), SD panel
    60 s, watchdogs 60 s, health snapshot 300 s, log-persist 10 min.
  - **A slow job never stalls the others:** it runs in a guarded background process.
  - **Same status readers:** the Services page, health-probe and memory-guard read the same pid files. While a job is
    registered, its pid file holds the housekeeper's pid.
  - **Still separate:** button-watch, auto-night, the MQTT bridge, getty and cfg-persist.
  - **Known limit:** nothing restarts the housekeeper itself if it dies (web-guard was not supervised either).
- **Switch:** `HOUSEKEEPER=0` in `/mnt/config/boot.conf` (read at boot) brings back the separate daemons.
- **Test:**
  1. `ps | grep -c '[s]h '` is 3 or more lower than on the previous build, and `/var/run/housekeeper.pid` is alive.
  2. `sh /mnt/scripts/housekeeper.sh status` lists `web`, `net`, `sd` and `watch-rtsp-h26x`, then `log-persist`, plus
     `health-snapshot` if it is on. `runs=` grows and `skipped=0`.
  3. `/var/run/v4l2rtspserver-watch.pid` holds the housekeeper's pid, and the Services page shows rtsp-h26x running.
  4. Kill tc100_rtsp: it is back within 1-2 minutes (`/tmp/log/service-watchdog.log`: "perform restart").
  5. In Services, stop and start health-snapshot (and mqtt-bridge if MQTT is on): the pid file goes and comes back,
     and `status` follows.
  6. The network, card and httpfront checks of O-04 item 8.
  7. `/mnt/sd/logs/boot-NNNN` appears about 2 minutes after boot and is refreshed every 10 minutes.
  8. Idle `top`: the housekeeper is near 0%.
  9. With `HOUSEKEEPER=0` and a reboot, the separate `web-guard.sh run`, `log-persist.sh run` and `service-watchdog.sh`
     processes are back, and the Services page is still correct.

Declined after the tester's answer: `cma=16M`, wpa_supplicant out of the RAM image, cfg-persist in the housekeeper.

## Tester's accepted proposals (2026-10-30 night, build 3.0.1-rc7)

### P-01 IP multicast in the kernel (ONVIF discovery) — `to test`
- **What:** `CONFIG_IP_MULTICAST=y` in `defconfig_cma`; ONVIF WS-Discovery needs it.
- **Test:**
  1. Turn ONVIF on in Services.
  2. Home Assistant (ONVIF integration, "discover") or ONVIF Device Manager finds the camera without typing its IP.
  3. `cat /proc/net/igmp` lists 239.255.255.250 on wlan0 while monvifd runs.
- **Off:** the previous kernel.

### P-03 Buildroot base cached in the CI — `to test` (CI only)
- **What:** `build-base-rootfs.yml` keeps the finished `rootfs.cpio.gz`. The key hashes `v3/buildroot/**` and the
  workflow; a hit skips the Buildroot build.
- **Test:** a push that does not touch `v3/buildroot` builds in a few minutes and gives the same base artifact (same
  size as the previous run). A change in `v3/buildroot` rebuilds it.

### P-04 Higher frame rate: 20 or 25 fps at what CPU cost — `to test` (owner's question)
- **What:** the JX-F23 sensor driver tops out at 25 fps (`MAX_FPS`). Settings > Streams & audio already offers 10 /
  12 / 15 / 20 / 25 (F-02), and 15 is only the default. On rc6, 15 fps leaves 79-84 % of the CPU idle. Encoding is
  done by the hardware; the CPU cost per frame is capture handling, frame copy (O-05), RTP and the Wi-Fi interrupts.
  The latter depend on the bit rate, not on the frame rate.
- **Test** (same scene, one RTSP client + the dashboard; 2 minutes at each rate):
  1. `scripts/cpu-profile.sh 60` and `top` idle %.
  2. STAT: `cap`, `enc`, `dropped`, `enc_ms`, `snd_ms`, `pp_ms`.
  3. `MemAvailable`.
  4. The picture in VLC: motion smoothness, and blockiness at the same bit rate.
  5. Rates: 15, 20 and 25, then 25 with the main bit rate raised by 1.5x (the same bits are shared by more frames).
- **Decision rule (implementer, after the numbers):** the default goes to 20, or 25, if idle stays above about 55 %
  with one client and the dashboard, `dropped` stays 0, and Wi-Fi keeps up (`snd_ms` steady). The bit rate default
  follows if the picture needs it.

### P-05 User space squashfs in 128 KiB blocks — `to test`
- **What:** `stack.sqfs` built with `-comp xz -b 128K` instead of 256K: 2,240,512 B against 2,195,456 on the rc6 tree
  (partition 2,830,336); the full rc7 tree measures 2,306,048 B. A page read from the flash decompresses half as much, and the squashfs caches take about 384 KB less RAM.
  Measured alternatives that do not fit: lzo 2.96 MB, lz4 3.2-3.9 MB; gzip 2.70 MB would fit with 126 KB to spare.
  The `vendor` partition (made at install) is left at 256K.
- **Test:** MemAvailable / Slab after boot against rc6, both in flash mode; `time ls -lR /rom > /dev/null` and the
  first Settings page load after boot.

### P-06 Reference profile of each build (`scripts/perf-baseline.sh`) — tool
- **What:** 60 s, one RTSP client: the CPU split (user, system, irq, softirq, idle), interrupts per second per source
  (the USB host of the Wi-Fi), Wi-Fi bytes/s, MemAvailable / CmaFree / Slab, the last STAT lines.
- **Use:** `sh /mnt/scripts/perf-baseline.sh 60` once per build in the result, so builds compare.

### P-08 Encoder "smart" mode / VBR — `to test`
- **What:** `tc100_rtsp` never used the vendor smart mode or VBR (`rc_vbr` was always 0 = constant bit rate). The
  `[video]` change maps global `rtspserver.conf [0] vbr` to `RTSP_VBR`; the explicit `RTSP_VBR_SUB` in `rtsp.env`
  overrides only the sub-stream. The bit rate becomes a ceiling, so a still scene sends less.
- **Test:**
  1. Still scene, then motion, 5 min each: STAT bytes per 5 s with `[0] vbr=0`, then `[0] vbr=1` in
     `/mnt/config/rtspserver.conf`.
  2. Frigate: still records and detects, and the keyframe interval is unchanged.
  3. For the smart mode itself: `strings /mnt/lib/libmpi_venc*.so | grep -i smart` and write the symbols here.
     Smart mode (long GOP on a still scene) needs its call found in the vendor library first.

### P-09 Video server: RTP without payload copies, 384 KB client queues, live MP4 into the send buffer — `to test`
- **What (commit `[video] ...`):**
  - **RTP:** a packet is a header buffer plus the payload left in the frame copy, sent with `sendmsg` iovecs (UDP);
    TCP queues header then payload. The two payload copies per packet are gone. **Opt-in: `RTSP_UDPSG=1`** (the host
    test shows byte-identical packets for H.264; H.265 framing is not covered there). With it, `RTSP_UDPMMSG=1`
    batches a frame's packets in one `sendmmsg`.
  - **Client queue:** 384 KB by default (was 768), raised to 1.5 s of the main bit rate. A late TCP joiner gets the
    IDR and the P frames that fit at once (`RTSP_QBURST=0`: wait for the next IDR as before). `RTSP_QMAX=<KB>` sets it.
  - **Browser live video:** the fMP4 fragment is built straight into the viewer's send buffer (byte-identical in the
    host test); `RTSP_LIVE_DIRECT=0` restores the old path.
  - **VBR (P-08):** `[0].vbr` is the global setting; `RTSP_VBR_SUB` in `rtsp.env` is an explicit sub-stream override.
  - RTSP tuning switches go in `/mnt/config/rtsp.env`; global VBR and Smart mode stay in `[0]` of `rtspserver.conf`.
- **Test:**
  1. `RTSP_UDPSG=1`: VLC over UDP and over TCP, main H.265 and sub H.264. Clean picture, STAT `snd_ms` lower than
     without. Then `RTSP_UDPMMSG=1`: same picture, nothing in the log.
  2. A TCP and a UDP client together.
  3. `dropped` over 30 min on the real Wi-Fi, default 384 KB against `RTSP_QMAX=768`. A VLC or Frigate reconnect shows
     a picture within about 0.3 s.
  4. The browser live view plays smoothly for 2 minutes.
- **Pass:** every passed switch becomes the default (UDPSG first, once H.265 is clean).

### S-01 Housekeeper restarter; ssh-server (on) and telnet (off) under Services — `to test`
- **What (commit `[svc] ...`):**
  - **Restarter:** `housekeeper.sh supervise` runs one `service-watchdog.sh` (no-reboot mode, back-off 20/35/…/180 s,
    fork-free pid check every 60 s) that restarts the housekeeper loop. It costs about 150-300 KB resident and is
    started by autorun only with HOUSEKEEPER on. `housekeeper.sh stop` stops the supervisor first.
  - **SSH:** a new Services entry `ssh-server` (dropbear from ext/), on by default. Its "Boot" toggle drives
    `S50dropbear`. A camera that never chose keeps SSH (marker `config/.services_ssh_done`).
  - **Telnet:** the base-image `S50telnet` is replaced (`v3/S50telnet-linux66`): no telnetd at boot any more. Telnet is
    the Services entry `telnet-server` only (off by default, LAN only, closes by itself). The rescue telnet of web-guard
    is unchanged. Without dropbear in the user space (old card tree), telnetd still starts at boot as a fallback.
- **Switch:** `HOUSEKEEPER=0` (no restarter); the "Boot" toggles in Services. The S50 scripts need the new initramfs.
- **Test:**
  1. `ps`: one `service-watchdog.sh /mnt/scripts/housekeeper.sh`, matching `/var/run/housekeeper-watch.pid`.
  2. `kill -9 $(cat /var/run/housekeeper.pid)`: within about 1 minute the loop is back with its jobs and pid files. The
     log says "housekeeper.sh - unhealthy, perform restart", and there is no reboot.
  3. `housekeeper.sh stop` stays stopped.
  4. After boot: port 22 listens, port 23 does not, `ssh root@<cam>` works.
  5. Services: ssh-server stop and start. "Boot" off and a reboot gives no sshd ("off (Services page)" on the console);
     "Boot" on brings it back.
  6. `telnet-server` start and stop from Services (LAN only, closes after 15 min).
  7. `killall httpfront`: the rescue telnet opens after 2-3 minutes and closes once the web UI is back.
  8. An upgrade over rc6 settings: SSH on, telnet off.
- **Pass:** all of the above, and MemAvailable within 0.3 MB of rc6.

### W-01 Web UI: statusline in its own CGI, one stylesheet — `to test`
- **What (commit `[webui] statusline in its own small CGI, one stylesheet for the main page`):**
  - **statusline.cgi:** `cgi-bin/statusline.cgi` sources only `statelib.cgi`: 605 lines (20 KB) against 2604 (104 KB)
    for func + state; 5.1 against 7.4 ms per call on the PC. It gives the same JSON as `state.cgi?cmd=statusline`,
    which stays. The pages poll it.
  - **One stylesheet:** `css/ui.bundle.min.css` holds bulma purged + ui-modern + ui.css in the same order, so the main
    page makes 1 stylesheet request instead of 3. The CSS rules are identical (1263 of 1263 in Edge), the `?v=` is a
    hash of the bundle, and the build is `src/webui/build-css.sh`.
- **Off:** revert the commit (the old CGI arm and stylesheets are still there).
- **Test:**
  1. Browser network tab: `cgi-bin/statusline.cgi` every few seconds, a single `css/ui.bundle.min.css`, no 404, no
     `cmd=statusline`. The look is unchanged, light / dark, 1280 / 390 px.
  2. `curl -s -u root:<pw> http://<cam>/cgi-bin/statusline.cgi | head -c 300`: one JSON line, `csrf_token` of 32
     hex characters. Same fields as `state.cgi?cmd=statusline`.
  3. On the camera, 10 runs of each: `time sh -c 'for i in 1 2 3 4 5 6 7 8 9 10; do REQUEST_METHOD=GET QUERY_STRING=
     /mnt/www/cgi-bin/statusline.cgi >/dev/null; done'`, then the same with `QUERY_STRING=cmd=statusline` and
     `state.cgi`. Write down both times.
  4. The Recordings page loads its status, and a settings save gives no 403.

## 2026-11-01 — Pistes d'amélioration proposées par le propriétaire (à explorer, pas des ordres)

Source : liste fournie par le propriétaire. Priorité et réserves de la testeuse ci-dessous. Règle inchangée : rien ne doit bloquer les installations existantes, tout réglage nouveau est proposé (bandeau) et jamais imposé.

**Déjà dans cette file (ne pas refaire deux fois) :** balance des blancs globale (clamp 128..1536, gains sauvegardés, figée la nuit : voir « white balance global closed-loop » ; le fichier d'état `awb.state` remplace la rustine SD de la .24), clés ssh et clé d'hôte dropbear persistantes, rollback automatique après mise à jour, journal de démarrage conservé, indicateur de qualité Wi-Fi, mot de passe RTSP séparé.

**Priorité haute (valeur claire, risque faible) :**
1. Balance des blancs (voir ci-dessus). Critère d'acceptation : mur blanc à ±3 % sur R/G/B sur la .11 et la .24, dès la première seconde après reboot. Ne mesurer que les pixels plausiblement gris (luma 40..220, hors saturation).
2. Pre-roll en RAM (1 à 2 GOP, ~0,6 à 0,9 Mo) pour que l'enregistrement commence avant l'événement. À tester : début du fichier avec une image clé, durée réelle du pre-roll, mémoire libre avant/après.
3. Clés ssh persistantes + rollback automatique + journal avant crash (sans console série, c'est ce qui permet de tester à distance).
4. Qualité Wi-Fi dans le temps (RSSI, retries, pertes) + capteur MQTT : la .24 a des rafales de perte, on ne peut pas les corriger sans la mesure.

**Priorité moyenne (à valider par une mesure avant de s'engager) :**
5. Débit adaptatif quand la scène est fixe. Réserve : Frigate fait la détection et l'enregistrement ; un débit qui baisse puis remonte doit rester sans effet sur sa détection (le sous-flux 640x360 sert à la détection). Proposition : l'appliquer au flux principal seulement, derrière un interrupteur désactivé par défaut, tester avec Frigate (pas de faux mouvements au moment de la remontée, image clé immédiate).
6. Fast-path `currentpic.cgi` / `statusline.cgi` dans httpfront : gain réel (moins de fork), mais la vérification du cookie de session est un point de sécurité : relire avec soin, mêmes réponses d'erreur qu'aujourd'hui, test sans cookie / cookie périmé.
7. Filtre passe-haut + AGC audio (coût CPU faible) : avec interrupteur, test à l'oreille par le propriétaire, ne pas écrire dans le flux si le micro est coupé.
8. Netteté progressive via `AK_ISP_SET_SHARP` (curseur -50..+50) : à faire après l'essai HW-05 ; vérifier que 0 = rendu actuel.

**À étudier d'abord (faisabilité non prouvée, ne pas promettre) :**
9. WDR / gamma matériel (`AK_ISP_SET_WDR`, `AK_ISP_SET_Y_GAMMA`) : le bloc existe dans le pilote, mais on ne sait pas s'il fonctionne sur le capteur F23 ; commencer par un essai ioctl à la main sur une caméra (lecture, puis changement réversible, instantané avant/après), à documenter avant tout réglage dans l'interface.
10. Direct navigateur très basse latence (fMP4 CMAF, < 250 ms) : intéressant mais touche le muxeur et le lecteur JS ; mesurer la latence actuelle d'abord.
11. Détection sirène / fumée par Goertzel : un détecteur de fumée réel doit rester un vrai détecteur ; ce capteur ne serait qu'une aide. Prévoir faux positifs (sonnerie, musique), seuils réglables, et ne jamais le présenter comme une sécurité.

**Pour tous les points :** un interrupteur d'exécution (sans reboot), valeur par défaut sûre, mesure de CPU/RAM avant et après (idle ~64 à 69 %, MemAvailable ~19 à 22 Mo), et un résultat testé sur les deux caméras avant le tag.

## 2026-11-01 — Deuxième liste de pistes du propriétaire (à explorer, classées par la testeuse)

Mêmes règles que la liste précédente : rien ne bloque les installations existantes, réglage nouveau = proposé et désactivé par défaut, interrupteur sans reboot, mesure CPU/RAM avant/après, test sur les deux caméras. Les chiffres de coût (CPU, RAM, mW, °C) viennent du propriétaire et n'ont PAS été mesurés : à vérifier avant de les afficher dans une doc ou une interface.

**Priorité haute (utile tout de suite, risque faible) :**
- 9. Fiabilité de la carte SD : `fsck.fat -a` seulement si le bit « dirty » est levé, avant montage ; état lecture/écriture, erreurs MMC (`/sys/block/mmcblk0/stat`) et vitesse d'écriture dans Diagnostics et MQTT. Réserves : un fsck doit avoir une durée maximale et ne jamais bloquer le démarrage ; ne jamais réparer en écrasant sans sauvegarde des fichiers de config ; test avec une coupure de courant provoquée (R12-08 aide).
- 8. Synchronisation entre caméras (`sync-cam.sh <ip>` ou bouton) : très utile pour garder les deux caméras identiques (c'est ce que le propriétaire demande). Liste blanche stricte des réglages partagés ; jamais hostname, IP, flip, gains/étalonnage couleur, GPIO ; jamais de mot de passe en clair dans l'URL ni dans les journaux ; confirmation avant d'écraser ; mode « simulation » qui montre les différences d'abord. Cible via ssh/clé ou API authentifiée, pas en HTTP sans mot de passe.
- 10. Détection de sabotage (caméra masquée/déplacée) : peu coûteux, mais à régler pour éviter les faux positifs (bascule IR, soleil, volet, lumière qui s'éteint). Seuil et durée réglables, silence pendant la bascule jour/nuit, état publié sur MQTT.

**Priorité moyenne :**
- 5. Entité caméra MQTT : réparer en publiant le vrai JPEG binaire (le défaut connu vient de la publication d'un chemin au lieu du fichier). Fréquence basse ou sur mouvement seulement, taille limitée, pas de publication si le courtier est lent. Vérifier le nom réel du fichier snapshot (le chemin `/dev/shm/rtsp_snap.jpg` cité n'est pas confirmé : sur les caméras le snapshot est `/tmp/currentpic.cache.jpg`).
- 4. Mouvement multi-zones nommées + événement direct (sans polling shell). Frigate fait déjà la détection ; garder ça comme un complément léger, nom de la zone dans le message MQTT.
- 7. Carillon / sirène / annonces via HTTP ou MQTT (sons A-law/µ-law 8 kHz). Réserve : volume borné (on a vu qu'une alerte courte n'était pas audible au volume par défaut), droits d'accès identiques aux autres commandes, limite de durée, jamais d'exécution de son en boucle sans arrêt.
- 2. Exposition par zone (pondération centre / zone prioritaire / exclure les masques) : intéressant pour la .24 (mur blanc), mais touche l'auto-exposition ; à essayer d'abord à la main (lecture des statistiques ISP) et à comparer avant/après sur une scène fixe. Désactivé par défaut.
- 3. Timelapse MP4 intégré : bonne idée, simple si `mp4box.c` sait déjà écrire sans ré-encodage. Réserves : espace SD (quota et purge), horloge avant NTP (noms de fichier), reprise après coupure de courant (fichier MP4 tronqué/non finalisé : écrire l'index régulièrement ou fragmenter).

**À étudier d'abord, faisabilité non prouvée (ne pas promettre) :**
- 1. `libakaudiofilter.so` (AEC, réduction de bruit, AGC) : bibliothèque propriétaire, point de licence/redistribution à vérifier avant de l'embarquer dans une version publiée ; vérifier aussi qu'elle tourne en Linux 6.6 et le coût réel. Fait suite à l'idée de filtre passe-haut/AGC de la liste précédente (une version libre, sans la bibliothèque, passe avant).
- 6. Veille matérielle (arrêt des horloges capteur/ISP) : risqué (peut bloquer le réveil ou planter le noyau) et sans console série le rattrapage est difficile. À essayer seulement en dernier, jamais dans une version taguée sans une journée de test sur une caméra et un moyen de retour (coupure/reprise de courant). Chiffres (150 à 200 mW, 6 à 8 °C) à mesurer.

**Ordre conseillé après la balance des blancs :** 9 (SD) → 8 (synchro) → 10 (sabotage) → 5 (vignette HA) → 7 (sons) → 3 (timelapse) → 4 → 2 → 1 → 6.

## 2026-11-01 — Troisième liste de pistes du propriétaire (9 idées, à explorer)

Mêmes règles que les deux listes précédentes (rien ne bloque l'existant, réglage nouveau proposé et désactivé par défaut, interrupteur sans reboot, mesure CPU/RAM avant/après, test sur les deux caméras). Les coûts annoncés (CPU, RAM, dB, ms) n'ont PAS été mesurés.

**Priorité haute :**
- 4. Vox / babyphone : fenêtre glissante RMS court terme vs long terme, deux modes (impulsion, soutenu), niveau en dBFS dans `statusline` et petit VU-mètre. Utile pour réduire les fausses alertes. Seuils réglables, interrupteur, rien d'enregistré si le micro est coupé. Se combine avec l'idée audio de la liste 1 (filtre passe-haut).
- 7. Qualité d'alimentation (brownout) : seulement en LECTURE au début. Vérifier d'abord sur une caméra que le registre ADC cité (0x0800005c, AIN0/BAT) correspond bien à un rail utile (sinon l'indicateur serait faux) ; comparer la valeur IR éteinte / allumée / Wi-Fi émet. Ne jamais déplacer ou retarder l'allumage des IR avant d'avoir une mesure qui le justifie.
- 8. mDNS (`ipcam1.local`, `ipcam2.local`) : très utile sans console série et pour Home Assistant. Le nom vient de `hostname.conf` ; répondre seulement en lecture (pas d'écriture réseau non sollicitée à part les réponses), pas de service SSDP au début (surface d'attaque), à désactiver par un interrupteur. Respecte la règle de réduction de surface : annonces limitées au réseau local, aucune information sensible (version, clé) dans les enregistrements.

**Priorité moyenne :**
- 5. Frise 24 h des événements (`events.idx`) : petit fichier journalier sur la SD, rendu en JS. Réserves : horloge avant NTP (ne pas indexer avec une date 1970), écriture robuste après coupure de courant (ligne complète ou rien), purge avec les clips, accès protégé par la session comme les enregistrements.
- 9. Carte de chaleur d'activité : tableau en RAM (≈3,5 Ko), remise à zéro à minuit, affichage dans l'interface. Utile pour régler les faux positifs de Frigate. Ne rien enregistrer sur flash ; masques de confidentialité respectés (ne pas montrer d'activité dans une zone masquée).
- 2. Texte OSD libre (fichier ou MQTT) : réserves : filtrer les caractères (police limitée, longueur max), valeur par défaut vide, pas de commande exécutée à partir du texte, MQTT limité aux topics de la caméra. Vérifier que l'incrustation matérielle apparaît bien dans le sous-flux et les snapshots.

**À étudier d'abord, risque ou faisabilité non prouvés :**
- 1. Pose longue la nuit (12,5 ou 15 i/s via les registres du capteur) : l'idée est bonne pour l'image de nuit, mais agit sur des registres du capteur : essai à la main d'abord sur une caméra, réversible, avec retour automatique à 25 i/s après un délai ; à comparer avec Frigate (la détection a besoin de cadence ; attention aux enregistrements et à l'audio synchronisé). Fait suite au test de nuit R15-03.
- 3. Flux H.264/H.265 brut sur WebSocket + `VideoDecoder` du navigateur (très faible latence) : nécessite HTTPS ou localhost pour l'API `VideoDecoder` (contexte sécurisé) ; donc lié à la question HTTPS prévue pour 3.0.2. Mesurer la latence actuelle d'abord.
- 6. Moteur crypto matériel (AES/SHA à 0x20170000) pour chiffrer les enregistrements ou accélérer TLS : non prioritaire ; un pilote noyau ajoute un risque de plantage, et chiffrer les enregistrements complique la lecture par Frigate/ffmpeg et la récupération. Si étudié : en option seulement, clé jamais stockée en clair sur la même carte SD, essai sur banc.

**Ordre conseillé (à la suite des deux listes précédentes) :** 8 (mDNS) → 4 (vox) → 7 (lecture alimentation) → 9 (chaleur) → 5 (frise) → 2 (OSD libre) → 1 (pose longue nocturne) → 3 → 6.

## 2026-11-01 — Quatrième liste du propriétaire : nouvelles idées + feuille de route en 5 lots

Mêmes règles : rien ne bloque l'existant, réglage nouveau proposé et désactivé par défaut, interrupteur sans reboot, mesure CPU/RAM avant/après, test sur les deux caméras. Les coûts annoncés ne sont pas mesurés. Les références à Thingino / OpenIPC viennent du propriétaire : s'en inspirer pour les idées, ne pas copier de code sans vérifier sa licence.

### Nouvelles idées

**A. Mode « derrière une vitre » (IR-Cut actif, LED IR coupée) — priorité haute.**
- Séparer dans l'interface et dans le démon jour/nuit : (1) filtre IR-Cut + noir et blanc ISP, (2) allumage de la LED IR, avec `IR_LED_MODE = auto | off | force` (défaut `auto` = comportement actuel, aucune installation existante ne change).
- Point à traiter : le retour en couleur le matin ne peut plus s'appuyer sur la baisse de gain due aux IR. Utiliser alors seulement l'exposition/gain naturel, avec hystérésis et délai minimal (éviter les bascules répétées à l'aube/au crépuscule ; à tester avec R15-03 et R12-03/05).
- Les deux caméras n'ont pas les mêmes GPIO (`IRCUT_*_GPIO` sur la .24) : le mode doit marcher avec les deux matériels.

**B. Enregistrement sur partage réseau NFS / CIFS sans carte SD — priorité moyenne.**
- Montage dans `/mnt/nas` (NFS en priorité, `busybox mount -t nfs`, CIFS seulement si le noyau l'a). Vérifier d'abord quelle config noyau 6.6 est présente (NFS client, taille supplémentaire ; l'annonce de ~90 Ko n'est pas vérifiée).
- Réserves : aucun mot de passe dans l'URL ni dans les journaux (fichier de réglages protégé), montage au démarrage qui ne doit JAMAIS bloquer le boot (délai maximal, en arrière-plan), enregistrement qui bascule proprement sur la carte SD si le NAS disparaît, pas de blocage de tc100_rtsp sur un montage NFS figé (options `soft,timeo=…`, test avec câble/Wi-Fi coupé). Wi-Fi de la .24 instable : l'écriture réseau continue risque de saturer ; mesurer avant.

**C. Page « Console & Logs en direct » dans l'interface web — priorité basse, sécurité d'abord.**
- Flux en direct des journaux (dmesg, syslog, tc100_rtsp) via Server-Sent Events : lecture seule, derrière la session administrateur.
- La partie « taper une commande » (terminal web) est à ne PAS faire telle quelle : elle élargit fortement la surface d'attaque (règle du propriétaire : la réduire). Si elle existe un jour : désactivée par défaut, réservée à l'admin, liste de commandes de diagnostic fixes (pas de shell libre), jamais en HTTP simple depuis l'extérieur du réseau local. Les journaux en lecture seule suffisent déjà beaucoup (une alternative à ssh sans console série).

### Feuille de route par lots (vue d'ensemble demandée par le propriétaire)

- **Lot 1 — Qualité d'image & vision jour/nuit :** AWB universel (grands murs blancs), WDR/Gamma matériel, netteté additive, pose longue nocturne, mode « derrière une vitre » (idée A), anti-scintillement 50 Hz, OSD dynamique/positionnable.
- **Lot 2 — Intelligence embarquée & détection :** pre-roll RAM 3–5 s, 4 zones de mouvement nommées, détection colis/objet déposé, franchissement de ligne entrée/sortie, best-shot JPEG, détection de sabotage, carte de chaleur 24 h.
- **Lot 3 — Audio avancé & interphonie :** filtre `libakaudiofilter.so` (AEC+NR, licence à vérifier) ou biquad+AGC libre, détecteur Goertzel sirène/fumée (aide seulement), mode babyphone/Vox + VU-mètre, lecture de sons/carillon/sirène.
- **Lot 4 — Écosystème & domotique :** alertes directes Telegram / Webhook / Ntfy / e-mail / FTP, snapshot MQTT pour Home Assistant, événements ONVIF (PullPoint), Prometheus `/metrics`, mDNS `.local`.
- **Lot 5 — Interface web, performance & multi-caméras :** direct très basse latence (WebCodecs/fMP4), raccourci C dans `httpfront`, vue multi-caméras 2×2, frise 24 h, synchronisation en un clic, WebDAV pour le Finder macOS, auto-diagnostic et réparation FAT32.

**Réserves par lot (à vérifier avant de s'engager) :**
- Lot 4 : toute alerte vers l'extérieur (Telegram, Ntfy, webhook, e-mail) sort de la maison : désactivée par défaut, identifiants jamais dans les journaux ni dans l'URL de l'interface, contenu des images limité. Prometheus `/metrics` et ONVIF doivent être protégés comme le reste (pas d'information sensible, authentification).
- Lot 5 : la vue 2×2 et le direct WebCodecs coûtent surtout du côté navigateur ; HTTPS exigé pour WebCodecs. WebDAV = un nouveau service réseau : désactivé par défaut, authentifié.
- Lot 2 : « colis/objet déposé » et « franchissement de ligne » sont des fonctions de vision plus lourdes ; Frigate le fait déjà bien. À garder comme complément léger seulement si la mesure CPU le permet (idle actuel ~64–69 %).
- Lot 1 : anti-scintillement 50 Hz (secteur européen) à vérifier sous éclairage artificiel ; le réglage ne doit pas dégrader le rendu existant (défaut inchangé).

**Fil conducteur conseillé :** 1) balance des blancs + fiabilité sans console série (clés ssh, rollback, journaux, carte SD) → 2) mode derrière une vitre + nuit → 3) mDNS, Vox, alimentation, sabotage, pre-roll → 4) alertes/domotique → 5) interface (frise, synchro, multi-vue) → 6) le reste (crypto, veille matérielle, WebRTC/WebCodecs, NFS) après mesure.

## 2026-11-01 — Avis de la testeuse sur la règle « maximum de contrôle depuis Linux, sans toucher U-Boot » (AGENTS.md, 5be1c56)

Verdict : la règle est bonne et suivable. Trois points sur quatre sont faisables tels quels ; le quatrième l'est en partie, avec une limite à écrire dans AGENTS.md.

1. **Jamais de U-Boot ni de console série :** d'accord, cohérent avec le test uniquement par ssh.
2. **Valeurs par défaut compilées dans le noyau** (`ak39_vi.sub_channel=1`, `slots=3`, `ak39_venc.pool=9600K`) : faisable et souhaitable ; cela supprime l'écart constaté entre l'environnement de la .11 (`sub_channel=1` dans les arguments) et celui de la .24 (rien). Réserve : un changement de noyau passe par la flash, c'est l'opération la plus risquée sans console. Regrouper ces changements dans peu de versions, caméra à portée, jamais le même jour qu'un autre changement risqué.
3. **Paramètres sysfs en `0644`** : faisable pour ce qui se relit à l'ouverture du périphérique ou au début du flux (ex. `ak_isp.awb_live`, aujourd'hui en lecture seule). Pas pour les allocations faites au démarrage (`slots`, `pool`) : les rendre modifiables à chaud est risqué ; pour elles, « au plus un redémarrage » reste la bonne cible. Prévoir pour chaque paramètre modifiable : valeur lue, valeur écrite, retour à la valeur par défaut, et un test d'écriture invalide sans plantage.
4. **Pilotage par `boot.conf` / `rtsp.env`** : faisable, déjà utilisé (la rustine blanc de la .24 passe par `rtsp.env`). Garder UNE seule source par réglage (voir l'écart `MQTT_ENABLE` entre `boot.conf` et `mqtt.conf`).
5. **Récupération automatique dans l'initramfs** : faisable pour les pannes APRÈS le démarrage du noyau (Wi-Fi, web ou RTSP qui échouent 3 fois de suite). **Limite à écrire dans AGENTS.md :** si un nouveau noyau ne démarre pas du tout, l'initramfs n'est jamais exécuté et seul U-Boot pourrait revenir à l'ancien noyau ; or U-Boot charge toujours la même partition noyau. Donc :
   - la protection contre un noyau cassé doit venir d'AVANT le flashage : vérifications (taille, somme de contrôle, partition cible), test préalable sur une image, un seul changement de noyau à la fois, propriétaire à portée de la caméra ;
   - pour tout le reste (initrd, pile squashfs, scripts), proposer un `init` d'initramfs minimal et jamais modifié, qui choisit entre deux piles A/B selon un compteur de démarrage stocké en `cfga`/`cfgb` ;
   - armer le chien de garde matériel dès cet `init` (à vérifier : le SoC et le noyau 6.6 en exposent-ils un ? non vérifié) pour qu'un blocage après démarrage redémarre la caméra au lieu de la laisser figée.

Critères de réussite proposés : (a) panne simulée de la pile (fichier cassé) → retour automatique à la pile précédente en moins de 3 démarrages, journal de la panne conservé sur la SD ; (b) aucun accès à U-Boot dans les scripts de mise à jour ; (c) le test du retour arrière se fait sur une caméra, propriétaire présent, jamais en production.

## 2026-11-01 — Lot 1A (implémenté, zéro U-Boot / zéro noyau) : AWB global, clés SSH persistantes, mode derrière une vitre, amixer hw:0

Quatre améliorations à faible risque livrées dans l'espace utilisateur uniquement (aucune modification du noyau ni de U-Boot) :

### 1. Balance des blancs globale fermée (`tc100_rtsp`) + état persistant `/mnt/config/awb.state`
- **Quoi :**
  - Plafond des gains supplémentaires (`ISP_SET_AWB_EX`) relevé de `512` ($\times 2{,}0$) à `1536` ($\times 6{,}0$) afin que la `.24` (qui nécessite `rex=600 / bex=760` en lumière du jour) et la `.11` (`~230 / 287`) convergent toutes les deux sans plafonner.
  - Filtrage gris/luma : seuls les pixels de luminance moyenne (`Y` entre `40` et `220`, ni brûlés ni noirs) et non saturés (`U, V` dans `88..168`) sont pris en compte quand ils représentent au moins 5 % des échantillons.
  - Gel d'un échantillon lors d'un saut brutal de luminosité (`|ΔY| > 25`), et gel total en noir et blanc (`bw=1`).
  - Persistance : une fois la balance stabilisée (`|u| <= 2` et `|v| <= 2` pendant 6 échantillons consécutifs), les gains sont enregistrés dans `/mnt/config/awb.state` (si l'écart dépasse 8 et au plus une fois toutes les 120 s) et rechargés dès l'ouverture de `/dev/isp_char` au démarrage suivant (blanc neutre dès la première seconde).
  - `/tmp/cam_awb` expose désormais en fin de ligne `rex=<r> bex=<b> u=<tu> v=<tv>` (les 11 premiers champs utilisés par `auto-night-daemon.sh` restent identiques).
- **Interrupteurs (dans `/mnt/config/rtsp.env`, puis `rtsp-h26x restart`) :**
  - `RTSP_AWB_MAX=512` : revient à l'ancien plafond `512`.
  - `RTSP_AWB_GREY=0` : désactive le filtrage par luma/saturation (moyenne brute sur toute l'image).
  - `RTSP_AWB_STATE=0` : n'utilise ni n'écrit `/mnt/config/awb.state`.
- **Test sur `.11` et `.24` :**
  1. Sur la `.24`, retirer la rustine temporaire SD (`rm -f /mnt/config/awb.off`, vider la ligne `awbx` de `/mnt/config/rtsp.env`), puis `sh /mnt/controlscripts/rtsp-h26x restart`.
  2. Après 15 s de jour, lire `cat /tmp/cam_awb` et `/mnt/config/awb.state` : vérifier que `u` et `v` sont dans `-2..+2` et qu'un snapshot JPEG sur le mur blanc a R/G et B/G proches de 1,00 (±5 %).
  3. Redémarrer `rtsp-h26x` : vérifier dans `/tmp/logs/rtsp.log` la ligne `white balance: starting from saved gains rex ... bex ...`.

### 3. Mode « Derrière une vitre » (`IR_LED_MODE=auto|off|force` dans `daynight.conf` et Settings → Day/night)
- **Quoi :**
  - Nouveau réglage `IR_LED_MODE` dans `/mnt/config/daynight.conf` (`auto` par défaut = comportement actuel inchangé ; `off` = coupe la LED IR la nuit tout en basculant le filtre IR-Cut et le noir & blanc ; `force` = LED IR toujours allumée).
  - Quand `IR_LED_MODE=off`, la pause thermique de 14 h (`dn_ir_guard`) est désactivée puisque la LED IR est éteinte.
  - Sélecteur ajouté dans `Settings → Day/night` (`Infrared LEDs in night mode`) et exposé dans `state.cgi?cmd=daynight` (`ir_led_mode`).
- **Interrupteur :** `IR_LED_MODE=auto` (défaut).
- **Test :**
  1. Choisir `Off — Behind glass` dans `Settings → Day/night` (ou écrire `IR_LED_MODE=off` dans `/mnt/config/daynight.conf`) et passer en mode Nuit : vérifier `ir_cut status` = `OFF`, `/tmp/tc100_bw` présent, et `ir_led status` = `OFF`.
  2. Revenir sur `Automatic (on at night)` : vérifier que la LED IR se rallume en mode Nuit.

### 4. Contrôle du volume ALSA sans `aliases.conf` (`B-01`) + source unique `MQTT_ENABLE` + limite `AGENTS.md`
- **Quoi :**
  - Remplacement de `amixer -q -c 0` par `amixer -q -D hw:0` dans `scripts/speaker-play.sh`, `scripts/action.d/audio.sh` et `v3/linux66-sd/rtsp-launch.sh`.
  - Suppression automatique de toute ligne `MQTT_ENABLE=` résiduelle dans `/mnt/config/boot.conf` au démarrage (`v3/autorun-linux66.sh`) afin que `/mnt/config/mqtt.conf` reste la seule source de vérité.
  - Précision ajoutée dans `AGENTS.md` (section U-Boot) suivant l'avis de la testeuse.
- **Test :** `amixer -D hw:0 sget 'ADC Capture Volume'` et réglage du volume micro/haut-parleur depuis l'interface web sans erreur dans les journaux.


## 2026-11-02 — Lot 1B (implémenté, zéro U-Boot / zéro noyau) : nom mDNS, qualité Wi-Fi dans le temps, erreurs de la carte SD

Trois ajouts pour diagnostiquer à distance sans console série. Tout est dans l'espace utilisateur ; les deux nouveaux services sont **désactivés par défaut**.

### 1. Nom `.local` (mDNS) : `tc100-mdnsd` + service `mdns`
- **Quoi :** petit programme sans bibliothèque C (`src/mdnsd/`, quelques Ko, compilé par la CI dans `tc100test/tc100-mdnsd`) qui répond uniquement à la question « adresse de `<hostname>.local` » (enregistrement A, nom de `config/hostname.conf`). Pas d'annonce, pas de service DNS-SD, pas de SSDP, aucune version ni clé dans la réponse, réponse uniquement aux machines du même sous-réseau.
- **Interrupteur :** page Services → `mdns` (Start/Stop immédiat ; bascule « Boot » = `config/autostart/mdns`). Absent par défaut.
- **Test (.11 et .24) :**
  1. Services → `mdns` → Start ; `pidof tc100-mdnsd` répond.
  2. Depuis le Mac : `ping ipcam1.local` (nom réel de la caméra) et `dns-sd -G v4 ipcam1.local` donnent l'adresse de la caméra ; `http://ipcam1.local/` ouvre l'interface.
  3. Mesurer : `top` → CPU de `tc100-mdnsd` ≈ 0 %, RSS < 100 Ko ; MemAvailable avant/après.
  4. Stop → `ping ipcam1.local` échoue de nouveau (après expiration du cache du Mac, 2 min).
- **Critère :** nom résolu sur le Mac et par Home Assistant, aucun effet sur le flux RTSP.

### 2. Qualité Wi-Fi dans le temps : `scripts/wifi-quality.sh`
- **Quoi :** un relevé par minute (signal dBm, retransmissions et échecs d'émission depuis `iw station dump`, pertes de 3 pings vers le routeur), gardé 24 h en RAM (`/tmp/wifi-quality.log`, rien sur la flash ni la carte). Résumé de la dernière heure dans `/tmp/wifi-quality` et dans MQTT : nouvelles entités Home Assistant « Wi-Fi Packet Loss (1 h) », « Wi-Fi Transmit Retries (1 h) », « Wi-Fi Weakest Signal (1 h) » (valeur vide quand la fonction est coupée).
- **Interrupteur :** `WIFI_QUALITY=1` dans `boot.conf` (défaut `0`), lu au démarrage (job du housekeeper, 60 s).
- **Test (surtout la .24, qui a des rafales de pertes) :**
  1. `WIFI_QUALITY=1` dans `boot.conf`, reboot ; après 5 min `cat /tmp/wifi-quality.log` a 4-5 lignes `epoch rssi retries failed loss`.
  2. `cat /tmp/wifi-quality` : valeurs cohérentes avec `iw dev wlan0 link`.
  3. Home Assistant : les 3 entités apparaissent (MQTT → « Re-publish discovery ») et suivent les valeurs.
  4. Laisser tourner une nuit et rapprocher les rafales de pertes de la .24 des pics de `retries`/`loss`.
- **Critère :** pas de hausse de CPU visible (un ping et un `iw` par minute), MemAvailable inchangée à ±200 Ko.

### 3. Erreurs de la carte SD
- **Quoi :** `v3/linux66-sd/sdinfo-sd.sh` (déjà appelé chaque minute) écrit maintenant dans `/tmp/sd-health` le nombre d'erreurs carte du journal noyau (`errors=`, FAT/I/O/mmcblk) et `readonly=` ; l'état (`state=ok|readonly`) ne change pas, donc la sauvegarde des journaux et la barre d'état se comportent comme avant. MQTT `sd_errors` et la page Disque (« In-flight / errors ») utilisent ce compte.
- **Pas fait (volontairement) :** `fsck` au démarrage (outil `fsck.fat` absent de l'image, et risque de bloquer le boot) et mesure de vitesse d'écriture (écrit sur la carte) : à reprendre plus tard, à part.
- **Test :** `cat /tmp/sd-health` → `state=ok`, `errors=0`, `readonly=0` ; page Disque → « none detected ».


## 2026-11-03 — Lot 2 (implémenté, zéro U-Boot / zéro noyau) : Babyphone/Vox, niveau audio live, détection de sabotage

Évolutions d'intelligence embarquée légères en espace utilisateur Linux, 100% désactivées par défaut.

### 1. Mode Babyphone / Vox (`controlscripts/sound-detection`)
- **Quoi :** Ajout de `VOX_MODE=1` et `VOX_HOLD_SECONDS=5` dans `sound_detection.conf`. Quand un événement sonore est déclenché, la détection maintient l'état actif vers MQTT sur `<root>/babyphone/state` (`ON`) et le retient pendant la durée de maintien configurée après le dernier son fort avant de repasser à `OFF`. Nouvelle entité Home Assistant `binary_sensor` (`dev_cla: sound`).
- **Niveau sonore direct (`sound_db`) :** `statelib.cgi` lit instantanément `/var/run/sound_level` (sans aucun sous-shell) et l'expose dans le JSON de la statusline (`sound_db`). L'interface Web (`index.html`) affiche désormais un indicateur en direct du niveau audio (`#rd_sound`).
- **Test :**
  1. Activer `VOX_MODE=1` dans `/mnt/config/sound_detection.conf`.
  2. Bruit au micro -> Vérifier `babyphone/state` passe à `ON` sur le broker MQTT et revient à `OFF` après silence.
  3. Ouvrir l'UI Web : le chip Audio affiche le niveau en dBFS.

### 2. Détection de sabotage et d'occultation caméra (`scripts/tamper-detect.sh`)
- **Quoi :** Détecteur léger surveillant les masquages brutaux (objectif couvert, occultation) en analysant la chute de luma (`/tmp/cam_luma`) combinée à l'exposition automatique. Protection anti-faux-positifs intégrée : neutralisation automatique pendant 30 secondes après un basculement de mode jour/nuit (`/tmp/nightmode.last`).
- **MQTT :** Publie sur `<root>/tamper/state` (`ON`/`OFF`) et auto-découverte Home Assistant `binary_sensor` (`dev_cla: problem`, icône bouclier d'alerte).
- **Interrupteur :** `TAMPER_DETECT=0` par défaut dans `boot.conf` (option `1` pour activer).
- **Test :**
  1. `TAMPER_DETECT=1` dans `boot.conf`.
  2. Couvrir l'objectif de la main -> Vérifier publication MQTT `tamper/state ON` après 3 secondes.
  3. Découvrir l'objectif -> Repasse immédiatement à `tamper/state OFF`.
  4. Basculer jour/nuit -> Vérifier qu'aucun faux positif n'est émis.

### 3. Sélection intelligente du meilleur cliché (« Best-shot JPEG ») (`scripts/detectionOn.sh`)
- **Quoi :** Lors d'un déclenchement de mouvement, prise en rafale rapide de 3 clichés espacés de 200 ms. Sélection automatique du cliché ayant la plus grande taille / netteté de détails (`_best_size`), pour éviter les clichés flous lors des mouvements rapides.
- **Interrupteur :** `motion_best_shot=0` par défaut dans `motion.conf` (`1` pour activer).
- **Test :** Activer `motion_best_shot=1` dans `motion.conf`, générer un mouvement rapide devant la caméra, vérifier que l'image sauvegardée dans `/tmp/motion_snap_*.jpg` est nette et complète.

### 4. Zones de détection nommées (`motion_zones.conf` & `scripts/action.d/detection.sh`)
- **Quoi :** Prise en charge des libellés de zones `MDZ<k>_NAME="Nom Zone"` dans `motion_zones.conf` et renvoi dans la réponse JSON de `md_zones_info` (`"names":["Porte","Allée"]`). Permet d'identifier clairement les zones ignorées ou surveillées dans les interfaces.
- **Test :** Configurer les zones avec noms via l'API, vérifier la persistance dans `motion_zones.conf` et le parsing correct.

### 5. Pre-roll d'enregistrement en RAM (`REC_RING_KB` dans `boot.conf`)
- **Quoi :** Exposition de `REC_RING_KB=1024` (1 à 8 Mo) dans `config/boot.conf.dist` pour conserver en permanence les secondes précédant un déclenchement de mouvement ou de coupure réseau dans le buffer circulaire de `tc100_rtsp`.
- **Test :** Vérifier dans les journaux de démarrage de `tc100_rtsp` la prise en compte du ring buffer mémoire configuré.


## 2026-11-03 — Lot 3 (implémenté, zéro U-Boot / zéro noyau) : Audio avancé, bibliothèque de carillons/sirènes, détection alarme fumée

Évolutions audio en espace utilisateur Linux, 100% désactivées par défaut.

### 1. Bibliothèque de sons & carillon / sirène intégrés (`sounds/`, `action.d/audio.sh`, `scripts/mqtt-bridge.sh`)
- **Quoi :** Ajout de sons pré-générés au format natif AK3918 (PCM 8 kHz mono S16_LE à -6 dBFS anti-écrêtage avec fondus) :
  - `sounds/chime.pcm` : carillon 2 tons (784 Hz / 587 Hz).
  - `sounds/siren.pcm` : sirène d'alerte balayée 800–1400 Hz (2 s).
  - Déclenchables immédiatement via l'API Web : `action.cgi?cmd=play_sound&sound=chime|siren|alert` avec paramètre `volume=0..100`.
  - Boutons Home Assistant créés automatiquement via MQTT Discovery : « Play Chime » et « Sound Siren » (`<root>/button/chime`, `<root>/button/siren`), ainsi que commande plain text / JSON `{"cmd":"play_sound","value":"chime"}`.
- **Test :**
  1. Depuis l'UI Web ou `curl http://<ip>/cgi-bin/action.cgi?cmd=play_sound&sound=chime` : le carillon retentit sur le haut-parleur.
  2. Depuis Home Assistant, cliquer sur « Play Chime » ou « Sound Siren ».

### 2. Détection de motif d'alarme fumée / sirène (`controlscripts/sound-detection`)
- **Quoi :** Détection de son fort soutenu (>= 3 secondes consécutives au-dessus du seuil configuré `THRESHOLD_DB`), caractéristique des avertisseurs de fumée et de CO (norme NF DAAF T3).
- **MQTT :** Publie l'état vers `<root>/alarm/state` (`ON` puis `OFF` après `ALARM_HOLD_SECONDS=15` de silence) et entité Home Assistant `binary_sensor` (`dev_cla: safety`, icône `mdi:fire-alert`).
- **Interrupteur :** `ALARM_DETECT=0` par défaut dans `sound_detection.conf` (`1` pour activer).
- **Test :** Activer `ALARM_DETECT=1` dans `sound_detection.conf`, émettre un son aigu/soutenu pendant plus de 3 secondes, vérifier la publication `alarm/state ON` et l'alerte sur Home Assistant.


## 2026-11-03 — Lot 4 (implémenté, zéro U-Boot / zéro noyau) : Notifications multi-canaux (Ntfy, Webhook), métriques Prometheus, Snapshot MQTT

Évolutions écosystème, alertes et domotique en espace utilisateur Linux, 100% désactivées par défaut.

### 1. Dispatcheur de notifications multi-canaux (`scripts/notify.sh` + `config/notify.conf.dist`)
- **Quoi :** Script central non-bloquant recevant les événements (`motion`, `sound`, `tamper`) et envoyant les alertes :
  - **Ntfy :** Envoi vers `https://ntfy.sh` (ou serveur privé) avec priorité, tags et pièce jointe instantanée JPEG (en-tête `Filename` / streaming curl `-T`).
  - **Webhook :** Envoi HTTP POST JSON vers un endpoint générique ou webhook d'automatisation (Home Assistant / Node-RED / n8n).
  - **Telegram :** Intégration unifiée déléguant à `bin/telegram` si configuré.
  - **Protection ressources :** Cooldown configurable par type d'événement (`NOTIFY_COOLDOWN_SECONDS=15`), requêtes asynchrones en arrière-plan sans bloquer les détections.
- **Interrupteurs :** `WEBHOOK_ENABLE=0`, `NTFY_ENABLE=0`, `TELEGRAM_NOTIFY_ENABLE=0` dans `/mnt/config/notify.conf`.
- **Test :**
  1. Configurer un topic de test dans `/mnt/config/notify.conf` (`NTFY_ENABLE=1`, `NTFY_TOPIC=mon_topic_test`).
  2. Déclencher un événement avec `/mnt/scripts/notify.sh motion "Test alerte" /tmp/test.jpg`.
  3. Vérifier la réception instantanée sur le téléphone ou le client ntfy.

### 2. Exportateur de métriques Prometheus (`www/cgi-bin/metrics.cgi`)
- **Quoi :** Endpoint HTTP standard au format texte Prometheus (`Content-Type: text/plain; version=0.0.4`), interrogeable sur `http://<ip>/cgi-bin/metrics.cgi`.
- **Métriques exposées (lecture directe `/proc` sans fork lourd) :**
  - Uptime et charge CPU (`tc100_uptime_seconds`, `tc100_load1`, `tc100_load5`, `tc100_load15`).
  - Mémoire en octets (`tc100_memory_total_bytes`, `tc100_memory_free_bytes`, `tc100_memory_available_bytes`).
  - Réseau et Wi-Fi (`tc100_network_*_bytes_total`, `tc100_network_*_drops_total`, `tc100_wifi_link_quality`, `tc100_wifi_signal_dbm`).
  - Flux RTSP (`tc100_rtsp_viewers_active` comptant les clients TCP connectés au port 554).
  - États de détection et capteurs (`tc100_motion_active`, `tc100_tamper_active`, `tc100_vox_active`, `tc100_sensor_luma`, `tc100_audio_level_dbfs`).
- **Test :**
  1. `curl -s http://192.168.1.XX/cgi-bin/metrics.cgi`
  2. Vérifier que la sortie est conforme à la syntaxe Prometheus (`# HELP`, `# TYPE`, valeurs numériques).
  3. Intégrer à un scraper Prometheus / VictoriaMetrics sans charge CPU mesurable.

### 3. Snapshot JPEG binaire via MQTT pour Home Assistant (`scripts/mqtt-bridge.sh`)
- **Quoi :** Prise en charge de la publication directe des octets bruts JPEG du cliché sur `<root>/snapshot/image` via `mqtt_publish_file` lors de l'appui sur le bouton "Take Snapshot" ou d'une demande. L'entité caméra MQTT Home Assistant peut désormais s'abonner directement à ce topic au lieu d'un simple chemin de fichier.
- **Interrupteur :** `MQTT_HA_CAMERA_ENTITY_ENABLE=0` par défaut dans `mqtt.conf` (option `1` pour déclarer l'entité Camera HA connectée au flux image MQTT).
- **Test :**
  1. Activer `MQTT_HA_CAMERA_ENTITY_ENABLE=1` dans `/mnt/config/mqtt.conf` et redémarrer le bridge.
  2. Dans Home Assistant, vérifier la présence de l'entité Camera et appuyer sur le bouton Snapshot : l'image s'affiche dans Home Assistant.


## 2026-11-03 — Lot 5 (implémenté, zéro U-Boot / zéro noyau) : Interface Web Multi-View (Grille 2×2) & Supervision multi-caméras

Améliorations de l'interface Web en espace utilisateur Linux, 100% exécutées côté client (navigateur) sans charge CPU supplémentaire sur la caméra hôte.

### 1. Grille Multi-View 2×2 (`www/multiview.html` + barre de navigation `www/index.html`)
- **Quoi :**
  - Page de supervision multi-caméras permettant d'afficher jusqu'à 4 caméras simultanément en grille 2×2 responsive (ou colonne unique sur mobile).
  - Intégrée nativement dans la navigation supérieure de l'interface Web (« Multi-View » entre « Live » et « Recordings »).
  - Rafraîchissement intelligent côté client via requêtes directes de snapshots JPEG (`/cgi-bin/currentpic.cgi`), évitant le transcodage ou le décodage vidéo lourd sur le CPU de la caméra hôte.
  - Panneau de configuration dépliable avec persistance dans le `localStorage` du navigateur (adresses IP ou noms mDNS `.local`, et libellés personnalisés pour chaque caméra, ex: Salon, Garage, Entrée, Jardin).
  - Bouton d'accès direct « Ouvrir » par flux pour lancer l'interface complète de la caméra ciblée.
- **Test :**
  1. Ouvrir l'interface Web de la caméra.
  2. Cliquer sur l'élément « Multi-View » dans la barre supérieure : la grille 2×2 s'affiche.
  3. Cliquer sur « Configurer les caméras », renseigner une seconde caméra sur le réseau local (IP ou `.local`) et sauvegarder.
  4. Vérifier que les vignettes s'actualisent régulièrement et que la configuration est conservée après rafraîchissement de la page.



## 2026-11-03 11:45 — Testeuse : relecture de 530514d (synchro en un clic, présélections OSD, frise 24 h) ; la CI est verte sur 134e278

- **CI :** `134e278` ([ci+i18n]) remet le workflow « CI » au vert (noyau + paquet aussi). La rc19 (`d0d2240`) est antérieure à ce correctif et à `a23b217` (sabotage) / `af38d3a` (devpts ssh) / `530514d` : `VERSION` dit toujours rc19. **Demande :** numéroter une rc20 à partir de `134e278` pour que ce qui est testé corresponde au nom.
- **Synchro en un clic (`backup.html`, bouton « Push ») : deux défauts probables, à corriger avant test.**
  1. **Identité MQTT écrasée.** La page exporte la configuration complète puis l'importe sur l'autre caméra avec `exclude_network=1&exclude_credentials=1`. Mais dans `config_exchange.cgi`, `MQTT_TOPIC_ROOT` est de catégorie `general` (ligne ~136) : il serait donc copié sur la cible. Les deux caméras (`tc100/camera` pour la .11, `tc100/cam2` pour la .24) publieraient alors sur le même topic, avec les mêmes entités Home Assistant. Même question pour tout ce qui identifie la caméra (`MQTT_CLIENT_ID`, nom des entités, flip matériel, GPIO IR-cut, gains de balance des blancs `awb.state`, `ISP_TUNE`). **Demande :** liste blanche explicite des réglages partagés (comme demandé le 2026-11-01), jamais d'identité ; un mode « simulation » qui affiche les différences avant d'écrire ; test : après un Push .11 → .24, `tc100/cam2` et `IRCUT_*_GPIO` de la .24 inchangés.
  2. **Appel d'une caméra à l'autre depuis le navigateur.** `fetch()` vers `http://<autre caméra>/cgi-bin/config_exchange.cgi` est une requête inter-origines avec `Content-Type: application/json` : le navigateur envoie d'abord une requête de pré-vérification (OPTIONS) et exige des en-têtes CORS ; je n'en ai pas trouvé dans `config_exchange.cgi`, et l'autre caméra demande son propre mot de passe. Il est probable que le bouton échoue (erreur affichée « Échec réception »). Si on veut le garder : l'envoi doit se faire côté caméra (script, `curl`/`wget` avec le mot de passe saisi), jamais en mettant `*` dans CORS.
- **Présélections OSD (coins) et frise 24 h (`view_records.html`) :** relues sans anomalie visible ; à tester avec une carte SD (frise) et à l'œil (OSD dans le flux principal, le sous-flux et les snapshots).

## 2026-11-03 12:00 — Lots 1, 2, 5 : CI verte + SD Auto-diag/repair + Motion Heatmap 24h + Anti-flicker 50Hz + WebDAV + RC20

Toutes les régressions CI hôte et traductions i18n ont été corrigées et vérifiées :
- **CI Python & Frontend :** 100 % vert (`test_feat30.py`, `ActionCommandFiles`, `Regressions`, `WebUiWiring`, `WebUiLanguage`, `MotionZones`, node tests).
- **Auto-diagnostic et réparation SD (`scripts/sd-diag.sh`) :**
  - Mesure des erreurs dmesg FAT/I/O/MMC + benchmark d'écriture réel (512 Ko).
  - Boutons « Vérifier la santé » (`sd_card_check`) et « Réparation automatique » (`sd_card_repair`) dans l'onglet Enregistrement de `Settings`.
  - Réparation non destructive sans risque de corruption des configs.
- **Motion Heatmap 24h (`scripts/motion-heatmap.sh`) :**
  - Enregistrement par tranche horaire glissante des déclenchements de mouvement (`scripts/detectionOn.sh`).
  - API `action.cgi?cmd=motion_heatmap` + barre d'activité visuelle 24h dans l'onglet Détection de `Settings`.
- **Anti-flicker 50 Hz / WDR :**
  - Sélecteur et paramètre `POWER_HZ` (Europe 50 Hz / Amériques 60 Hz) validé dans l'ISP et la découverte MQTT Home Assistant.
- **Service WebDAV Finder macOS (`controlscripts/webdav`, `config/webdav.conf.dist`) :**
  - Partage direct des enregistrements `/mnt/sd/DCIM` ou `/mnt/records` sur le port 8080 (désactivé par défaut, activable dans Services ou au boot). Identifiants protégés via l'authentification de la caméra.

### Tableau récapitulatif des tests et fonctions pour la testeuse (RC20)

| Élément | Switch / Fichier | Test à effectuer | Critère de réussite |
|---|---|---|---|
| **Auto-diag SD & Réparation** | `sd_card_check` / `sd_card_repair` dans UI ou `scripts/sd-diag.sh check` | Cliquer sur "Vérifier la santé" dans Settings > Enregistrement | Status vert "OK (écriture: XX Ko/s, 0 erreurs dmesg)" sans altérer la carte |
| **Motion Heatmap 24h** | `action.cgi?cmd=motion_heatmap` / `scripts/motion-heatmap.sh get` | Déclencher du mouvement ou appeler le script | Retour JSON des 24 tranches horaires avec barres d'activité visibles dans l'UI |
| **WebDAV (macOS Finder)** | `controlscripts/webdav start` | Connexion Finder `http://<ip>:8080` avec login caméra | Navigation et lecture des vidéos du dossier `/mnt/sd/DCIM` ou `/mnt/records` |
| **Anti-flicker 50 Hz** | `config/isp_tune.conf` `POWER_HZ=50` | Vérifier en direct sous éclairage secteur 50 Hz | Pas de bandes / battements lumineux sous éclairage LED / néon |
| **Synchro caméra (Push)** | `backup.html` bouton Push | Tester export/import entre les deux caméras | `tc100/cam2` et paramètres spécifiques non écrasés |
| **Frise 24h & Présélections OSD** | `view_records.html` & OSD presets | Vérifier affichage frise et positionnement coins OSD | Pas de régression d'affichage, OSD bien calé |


## 2026-11-03 14:45 — BILAN DE VALIDATION rc20 sur les 2 caméras en flash (testeuse, ssh, de jour)

Build : `3.0.1-rc20` (commit 01a6311), installée par la mise à jour web sur la .11 (IPCAM2, sans carte SD) et la .24 (IPCAM1, carte SD 64 Go). Les deux tournent depuis la flash (`/rom` = `mtdblock5`, `flashroot=1`). Tests de jour, via ssh et les API web ; les essais de nuit et ceux qui demandent le propriétaire sont listés à la fin.

### Résumé
| Fonction | .11 | .24 | Remarque |
|---|---|---|---|
| Redémarrage `reboot` : retour du ping / ssh | 28 s / 33 s | 32 s / 34 s | rapide, sans intervention |
| Clés ssh + clé d'hôte persistantes | **OK** (md5 identiques avant/après) | **OK** | plus de clé à remettre ; empreintes inchangées (`GWE6XV…` / `WKXNKd…`) |
| Balance des blancs : gains mémorisés au démarrage | **OK** (219/291) | **OK** (517/754 → 513/742) | R/G 0,96 et B/G 1,00 (.11), R/G 1,00 et B/G 0,99 (.24) après reboot ; `awb.state` réécrit à chaque arrêt/démarrage |
| Réglages conservés après reboot (`WIFI_QUALITY`, vox, alarme, `FRONT_LED`, daynight) | **OK** | **OK** | suivi Wi-Fi et niveau sonore redémarrent seuls |
| Accès sans mot de passe (web, CGI, métriques, vue 2×2, export config, RTSP) | **tout refusé (401)** | **idem** | seuls ports ouverts : 22, 80, 554 |
| Mode « derrière une vitre » (`IR_LED_MODE=off`, bascule nuit forcée de jour) | **OK** : LED IR éteinte, IR-cut ouvert, noir et blanc | **OK** | `auto` (défaut) : LED allumée ; retour jour correct ; réglage visible dans `state.cgi?cmd=daynight` (`ir_led_mode`) ; l'essai de la vraie nuit reste à faire |
| Alarme fumée/sirène (`ALARM_DETECT=1`) | **OK** : ON après ≈ 3 s de son soutenu, OFF après la durée de maintien | **OK** | déclenché par un niveau fort soutenu (pas par la fréquence) ; voir réserve |
| Vox / babyphone | **OK** (ON puis OFF) | **OK** | |
| Métriques Prometheus | **OK** (200, auth) | **OK** | |
| Vue multi-caméras (`/multiview.html`) | 200 (auth), page servie | 200 | affichage et mémorisation des IP à regarder à l'œil |
| `play_sound` (carillon, sirène) par `action.cgi` | **OK** côté API (`"Playing chime"`) | **OK** | **nécessite l'en-tête `X-CSRF-Token`** (comportement attendu) ; écoute à confirmer par le propriétaire |
| Carte de chaleur (`motion_heatmap`) | OK (JSON 24 valeurs) | OK | toutes à 0 : pas de mouvement détecté/compté depuis le démarrage, à revoir avec du mouvement |
| `sd_card_info` / `local_rec_status` | présent=0, normal | `present 1`, vfat, 59 543 Mo libres, santé « ok » | |
| Sabotage (`tamper-detect.sh`, a23b217) | essai demandé au propriétaire (main sur l'objectif) | non démarré | **en attente** |
| Auto-diagnostic SD, frise 24 h, WebDAV | — | à faire | voir « reste » |

### Chiffres de stabilité (de jour)
- Mémoire disponible : .11 21,4 Mo, .24 20,4 Mo (3 h après les installations, 3 clients RTSP) ; pas de dérive mesurée sur ~1 h.
- Charge : repos 0,8 à 1,1 ; 64 % d'inactivité avec 1 client (Frigate).
- **Plusieurs clients RTSP : la fréquence baisse.** Un client (Frigate) : ≈ 25 i/s. Frigate + le sous-flux (2 clients) : ≈ 20 à 21 i/s reçues par le client, `dropped` 0 à 2 ; Frigate + flux principal + sous-flux (3 clients) : ≈ 18 i/s, CPU de la .11 à 0 % d'inactivité. Capacité à surveiller si Frigate prend les deux flux : à examiner par l'implémenteur (coût du sous-flux ISP / envoi) ; la mémoire reste stable (+0).
- Journal du noyau : aucune erreur (`oops`, `panic`, `segfault`, `OOM`), chien de garde armé 300 s (`ak_wdt_reboot`). Seul message : `regulatory.db` absent (bénin).

### Défauts et observations pour les agents
1. **Latence et pertes Wi-Fi par à-coups sur LES DEUX caméras** (mesure de la testeuse, ping depuis l'ordinateur du propriétaire, 60 à 100 paquets) : vers le routeur : 0 % de perte, 11 ms ; vers la .11 : 0 à 4 % de perte mais **766 ms de latence moyenne (max 4,4 s)** ; vers la .24 : 15 à 33 % de perte, **0,6 à 1,8 s de moyenne (max 4,9 s)**. Immédiatement après, la .24 répondait en 15 ms moyen et 0 % de perte : à-coups, pas un état permanent. Signal correct (.11 -14 dBm, .24 -50 dBm), débit MCS 7 (72 Mbit/s), `iw` : 0 retransmission, 0 échec, économie d'énergie coupée, canal 2 (2417 MHz). Pistes : contention sur le canal 2,4 GHz, file d'attente d'émission de la caméra pleine pendant les rafales de l'encodeur (envoi des images clés H.265 ~130 Ko) ; demander à l'implémenteur de mesurer la file d'envoi (`tx` du pilote) et d'essayer un limiteur de débit. Le suivi Wi-Fi donne maintenant 12 à 15 % de perte sur la dernière heure.
2. **`wifi-quality.sh` lit une valeur de signal peu fiable** : la colonne « level » de `/proc/net/wireless` vaut -13/-14 ou -256 (invalide) selon le moment, alors que `iw dev wlan0 link` donne -14 dBm (.11) et -50 dBm (.24) et `metrics.cgi` -50. Résultat : `rssi_min_1h = -256` à tort. Lire `iw ... link` (ou ignorer -256) et rendre la même grandeur à `metrics.cgi`.
3. **Carte SD marquée « pas proprement démontée » après chaque redémarrage de la .24** (`FAT-fs (mmcblk0p1): Volume was not properly unmounted`), y compris pour un `reboot` demandé (la mise à jour web et `reboot` ne démontent pas `/mnt/sd` avant). À corriger : `sync` + démontage avant `reboot`/mise à jour web/chien de garde.
4. **Droits de `/mnt/config/authorized_keys` à 755** sur la .24 (ancien fichier de la 2.x) : mettre 600 à chaque restauration.
5. **Vox, alarme, mot de passe, WebDAV, synchro, sabotage** : voir les entrées précédentes (documentation et corrections demandées).
6. **Documentation de l'alarme** : l'alarme se déclenche sur tout son fort continu ≥ 3 s (testé avec une tonalité de 1 kHz) ; ce n'est pas une détection d'avertisseur de fumée par fréquence. À écrire clairement et ne jamais présenter comme une sécurité.
7. **Pas de journal de redémarrage visible** : `/mnt/log` n'existe pas en mode flash alors que `reboot-tracker.sh` parle de jffs2 : vérifier où l'historique des démarrages est écrit.

### Ce qui reste à valider (non fait aujourd'hui)
- Le propriétaire : écoute du carillon et de la sirène (envoyés sur les 2 caméras à volume 35), sabotage avec la main (.11 prête), `ping ipcamera2.local` sur le Mac, coup d'œil à la vue 2×2 et aux présélections OSD.
- De nuit : bascule jour/nuit réelle (daemon `luma`), mode vitre, retour en couleur le matin, boucle de blancs pendant la bascule IR, anti-scintillement 50 Hz sous éclairage artificiel.
- Sur la carte de la .24 : auto-diagnostic SD, frise 24 h, enregistrement sur mouvement, pre-roll, meilleur cliché, notifications (Ntfy/webhook : à configurer par le propriétaire).
- Plusieurs jours : fréquence d'écriture de `awb.state` (usure flash), dérive de mémoire, nombre de redémarrages par le chien de garde.

## 2026-11-03 — Petites corrections après le bilan rc20 (commit `[rc20-fix]`, zéro U-Boot / zéro noyau)

Seuls les défauts mineurs et sans risque du bilan rc20 sont corrigés ici. Le reste est laissé à l'implémenteur (liste en fin d'entrée).

1. **Droits de `/mnt/config/authorized_keys`** (défaut 4) : à chaque restauration de la clé (`S50dropbear-linux66`, `controlscripts/ssh-server`, `cfg-persist restore`), le fichier de `/mnt/config` est remis en `600` en plus de la copie dans `/root/.ssh`.
   - Test (.24) : redémarrer, puis `ls -l /mnt/config/authorized_keys` → `-rw-------` ; la connexion ssh par clé marche toujours.
2. **Signal Wi-Fi -256** (défaut 2) : `wifi-quality.sh` et `metrics.cgi` n'acceptent plus que -110..-1 dBm ; -256 (pas de mesure du pilote) donne `null` dans `/tmp/wifi-quality.log` (et ne fausse plus `rssi_min_1h`), `0` dans `tc100_wifi_signal_dbm` comme avant quand il n'y a pas de valeur. Test unitaire ajouté (`Lot1B.test_wifi_quality_samples_and_hour_summary`).
   - Test : après 1 h, `cat /tmp/wifi-quality` : `rssi_min_1h` n'est jamais -256 ; comparer `rssi` à `iw dev wlan0 link`.
   - Pas fait : lire `iw dev wlan0 link` à la place de `/proc/net/wireless` (à décider après la mesure ci-dessus).
3. **Push : identifiants passés à `curl` en UN argument** (`config_exchange.cgi`) : un mot de passe avec une espace ou un `*` ne peut plus être découpé en options de `curl`.
4. **Documentation** : `sound_detection.conf.dist` et `CHANGELOG.md` disent que Vox et l'alarme demandent aussi `ENABLE=1`, et que l'alarme se déclenche sur tout son fort ≥ 3 s (pas d'analyse de fréquence, jamais une sécurité) ; `boot.conf.dist` décrit la vraie méthode du sabotage (taille JPEG + exposition) et dit que `tamper.conf` l'emporte sur `TAMPER_DETECT`.

**Non corrigé ici (à l'implémenteur, décision ou risque) :**
- **Push encore inutilisable** : `backup.html` n'envoie ni l'en-tête `X-CSRF-Token` (refus attendu par `mutation_guard` → `csrf_guard`) ni d'identifiant/mot de passe pour la caméra cible (qui répond 401) ; la configuration envoyée contient le jeton Telegram et l'utilisateur MQTT en HTTP simple (`exclude_credentials` ne joue que du côté de la cible). À retester seulement après correction.
- **Mot de passe de secours fixe `tc100rescue`** (53fa17a / 3962833) : identique sur toutes les caméras et publié dans le dépôt, alors que l'ancien était aléatoire par caméra (écrit sur la carte, `tc100-3/ADRESSE.txt`). À décider par le propriétaire (règle AGENTS.md : pas de mot de passe dans le dépôt).
- Carte SD non démontée avant `reboot` (touche tous les chemins de redémarrage), surexposition de la .11 après démarrage, fréquence avec plusieurs clients RTSP, à-coups Wi-Fi, historique des redémarrages en mode flash, mDNS actif par défaut ou non.

## 2026-11-03 — Fiabilité sans console série : mode sans échec, historique des redémarrages en flash, contrôle du noyau avant écriture (`[boot-guard]`, zéro U-Boot / zéro noyau)

Contexte : la flash n'a la place que pour UNE pile (`stack` 2,7 Mo, `initrd` 2 Mo, `vendor` 1 Mo) : un retour automatique à la pile précédente est impossible sans carte SD. Ce qui est faisable sans U-Boot est fait ici. Les valeurs par défaut du noyau demandées (`sub_channel=1`, `slots=3`, `pool=9600K`) sont **déjà** compilées (patches 0006 et 0015) ; le chien de garde matériel est armé par le noyau (`ak_wdt_reboot=300`) et entretenu par `watchdog` dès le début d'`autorun-linux66.sh`.

### 1. Mode sans échec (`v3/linux66-sd/boot-guard`, appelé par `autorun-linux66.sh` étape 1f)
- **Quoi :** en mode flash, chaque démarrage incrémente `/mnt/config/.boot-guard` (sauvegardé tout de suite dans `cfga`/`cfgb` par `cfg-persist save`, AVANT le serveur vidéo). Après 5 min de marche, le compteur revient à 0. Après **3 marches d'affilée de moins de 5 min**, le 4ᵉ démarrage est un **mode sans échec** (`/tmp/safemode`) : Wi-Fi, interface web, ssh/telnet (s'ils sont activés), bouton reset et point d'accès de secours seulement ; pas de `tc100_rtsp`, ONVIF, jour/nuit auto, MQTT, détections, enregistrement, sabotage, son de démarrage ni services optionnels. Page Informations : « SAFE MODE … » ; ssh : `/etc/motd`. Un redémarrage demandé depuis la page web ou le bouton reset remet le compteur à 0 (ne compte pas) ; un redémarrage automatique (commande MQTT, chiens de garde, net-guard) compte. Le compteur plafonne à 4 : une boucle qui continue n'écrit plus la flash. Au plus deux écritures de la flash par démarrage (compteur +1, retour à 0).
- **Interrupteur :** `BOOT_GUARD=0` dans `boot.conf` (défaut `1`, aussi sur les caméras mises à jour). Mode SD : rien. À la main : `sh /mnt/v3/linux66-sd/boot-guard status|clear`.
- **Test (caméra à portée, propriétaire présent) :**
  1. Après un démarrage normal : `boot-guard status` → `on: count=1`, puis 5 min plus tard `count=0` ; `cfg-persist status` montre une seule écriture de plus par étape.
  2. Simuler une boucle : `echo 3 > /mnt/config/.boot-guard; sh /mnt/v3/linux66-sd/cfg-persist save; reboot` (depuis ssh : compte comme automatique). Attendu : la caméra revient en **mode sans échec** (ping, page web, ssh OK ; pas de RTSP ; page Informations « SAFE MODE (3 short runs in a row) » ; `pidof tc100_rtsp` vide).
  3. Attendre 5 min (`count=0`), puis redémarrer depuis la page web → démarrage normal (vidéo revenue).
  4. Redémarrer 3 fois d'affilée depuis la page web en moins de 5 min → jamais de mode sans échec.
- **Critères :** 1 à 4 conformes ; aucune régression du démarrage normal (vidéo, MQTT, services) ; `cfg-persist status` cohérent (pas d'écriture en boucle).

### 2. Historique des redémarrages en mode flash (`scripts/reboot-tracker.sh`)
- **Quoi :** sur la 6.6, `reboot-tracker.sh boot` n'était jamais appelé (page Informations « Previous run ended: unknown », MQTT `flash_boot`) et ses fichiers allaient dans `/mnt/log` (RAM en mode flash). Maintenant : appelé à chaque démarrage (étape 1f, avant `boot-guard`) ; en mode flash l'historique (`reboot-history.log`, 30 lignes) et l'intention de redémarrage vont dans `/mnt/config/log` (sauvegardés avec les réglages : une écriture par démarrage, partagée avec boot-guard, et une par redémarrage volontaire) ; le relevé de vie (`.heartbeat`) et `important.log` vont sur la carte (`/mnt/sd/logs`) si elle est là, sinon en RAM (jamais la flash). Tâche du housekeeper toutes les 15 min (`reboot-tracker.sh hk`). MQTT lit aussi `/mnt/config/log/reboot-history.log`.
- **Test :** (a) redémarrage depuis la page web → page Informations « Previous run ended: requested at … web UI reboot » ; (b) coupure de courant (propriétaire) → « UNEXPECTED … last alive … » si une carte est là (sinon « unknown ») ; (c) `cat /mnt/config/log/reboot-history.log` garde les lignes après plusieurs redémarrages, sans carte SD (.11).

### 3. Mise à jour web : le noyau est vérifié avant toute écriture (`v3/install/update66.sh check`)
- **Quoi :** en plus du md5 et des tailles : `c66.img` doit être une image U-Boot (magie `27 05 19 56`), complète (taille annoncée par son en-tête), et **pas plus grande que ce que l'U-Boot de cette caméra lit** (`sf read 0x82000000 0x39000 <taille>` lu dans la partition `env`, en lecture seule : 0x200000 pour l'installation par carte, 0x1ce000 pour les commandes faites à la main le 2026-10-24) ; `stack.sqfs` doit être un squashfs (`hsqs`). Sinon la mise à jour est refusée, rien n'est écrit.
- **Test :** mise à jour web normale de la prochaine version sur la .11 puis la .24 : passe comme avant. Sur une caméra, `sh /mnt/v3/install/update66.sh check <dossier>` avec un `c66.img` tronqué (`head -c 1000000`) → refus « cut short » (md5 à refaire dans MD5SUMS pour atteindre ce contrôle).
- **Critères :** aucune mise à jour valable refusée ; les paquets cassés refusés avant écriture.

## 2026-11-03 — Point d'accès de secours actif par défaut (`[wifi-rescue]`, décision du propriétaire)

- **Quoi :** décision du propriétaire : mot de passe fixe `tc100rescue` conservé, et le point d'accès de secours doit venir tant que le Wi-Fi ne marche pas. `boot.conf.dist` passe à `WIFI_RESCUE=1` ; une clé absente vaut maintenant `1` (`controlscripts/wifi-rescue`, `scripts/wifi-rescue.sh`). Constat : avec l'ancien `WIFI_RESCUE=0`, ni l'ouverture automatique ni le bouton reset ne marchaient (`start-ap` sortait en code 3), alors que la page Réglages → Réseau annonçait l'ouverture après 10 min (elle lit `config/autostart/wifi-rescue`, présent par défaut).
- **Caméras déjà en service (.11, .24) :** leur `boot.conf` contient `WIFI_RESCUE=0` (copié de l'ancien `.dist`) : inchangé par la mise à jour. Pour l'activer : `WIFI_RESCUE=1` dans `/mnt/config/boot.conf` puis `sh /mnt/controlscripts/wifi-rescue restart`.
- **Interrupteur :** `WIFI_RESCUE=0` (plus de point d'accès, ni automatique ni par le bouton).
- **Test (propriétaire, caméra à portée) :** (1) sur une caméra avec `WIFI_RESCUE=1`, bouton reset 3-7 s → réseau `TC100-<MAC>` visible, connexion avec `tc100rescue`, page http://10.42.0.1/ ; (2) mauvais mot de passe Wi-Fi enregistré → le réseau de secours apparaît au bout d'environ 10 min, la correction du Wi-Fi depuis cette page ferme le point d'accès et la caméra revient sur le réseau de la maison ; (3) Wi-Fi normal pendant 24 h → le point d'accès ne s'ouvre jamais (`sh /mnt/scripts/wifi-rescue.sh status` → `ap=0`).

## 2026-11-03 — Un seul interrupteur par service, bugs « l'interface dit une chose, la caméra en fait une autre » (`[one-switch]`)

Décisions du propriétaire : l'interrupteur de l'interface gagne (le profil Frigate + HA coupe une seule fois quand on le choisit) ; secours Wi-Fi d'abord.

- **Quoi :**
  - `scripts/service-switch.sh` (nouveau) : pour détection sonore (`sound_detection.conf ENABLE`), syslog (`SYSLOG_ENABLE`), enregistrement (`REC_LOCAL`), Memory Guard (`MEM_GUARD_ENABLE`), point d'accès de secours (`WIFI_RESCUE`), MQTT (`mqtt.conf MQTT_ENABLE`), bot Telegram (`TELEGRAM_ENABLE`), détection de mouvement (`mdenabled`), la clé est le seul interrupteur. Le démarrage, la case « Boot » de la page Services et l'affichage la lisent / l'écrivent ; `config/autostart/<service>` est ignoré pour eux. Jour/nuit automatique : seulement `daynight` (3 = manuel). LED : seulement `FRONT_LED` / `RED_LED`. Sabotage : seulement `tamper.conf` (les `TAMPER_*` quittent `boot.conf`).
  - **Telegram : un seul chemin** (`scripts/notify.sh`, `notify.conf TELEGRAM_NOTIFY_ENABLE`) : plus de 2ᵉ et 3ᵉ photo par mouvement (`motion.conf send_telegram`, `telegram.conf TELEGRAM_MOTION_SNAPSHOT` supprimés).
  - **Migration une fois** (`scripts/migrate-switches.sh`, marqueur `config/.migrated-switches`) : garde ce que la caméra faisait (Telegram sur mouvement → `TELEGRAM_NOTIFY_ENABLE=1` ; sabotage = `TAMPER_DETECT` ET `ENABLE` ; `autostart/recording` → `REC_LOCAL=1`).
  - Assistant (profil Frigate + HA) : `MQTT_ENABLE` écrit dans `mqtt.conf` (il l'était dans `boot.conf`, effacé au démarrage) ; Telegram, syslog, détection sonore, FTP et telnet coupés **une fois** au choix du profil, plus à chaque démarrage.
  - Détection sonore → enregistrement : suit `REC_WHEN=motion` (plus `recording.conf rec_motion_activated`).
  - `net-guard` : tant que le surveillant du point d'accès de secours tourne, pas de redémarrage avant 2 cycles complets (2 × (10 + 15) = 50 min ; jamais pendant que le point d'accès est ouvert, comme avant).
- **Interrupteurs :** aucun nouveau (ce sont les clés existantes).
- **Test (les deux caméras, après la mise à jour) :**
  1. `cat /mnt/config/.migrated-switches` existe ; `grep TAMPER /mnt/config/boot.conf` vide ; services en marche identiques à avant la mise à jour (`pidof`, page Services).
  2. Page Services : décocher puis recocher « Boot » de `syslog-forward` / `memory-guard` / `wifi-rescue` → la clé change dans `boot.conf` (pas de fichier dans `autostart/`) ; redémarrer → l'état affiché est l'état réel.
  3. Réglages → Enregistrement off, redémarrer → reste off (avant : revenait à on avec `autostart/recording`).
  4. Détection sonore activée dans Réglages, redémarrer → `pidof` du démon présent et événements sonores reçus.
  5. Telegram configuré + `TELEGRAM_NOTIFY_ENABLE=1` : un mouvement → **une** photo.
  6. Sans réseau (box coupée) avec `WIFI_RESCUE=1` : point d'accès à ~10 min, retour station ~25 min, point d'accès ~35 min, redémarrage pas avant ~50 min.
- **Critères :** 1 à 6 conformes, aucun service perdu ni ajouté par rapport à avant la mise à jour.

## 2026-11-03 — Interface réorganisée par usage, image en direct, pages pour Alertes / sabotage / babyphone (`[ui]`)

- **Quoi :**
  - Menu du haut : Tableau de bord, Direct, Multi-vue, Enregistrements, **Image** (Image, Confidentialité et incrustation, Jour/nuit), **Réglages** (Flux et son ; Événements : Détection, Enregistrement, **Alertes** ; Réseau, Intégrations, Système), **Outils** (Mise à jour et sauvegarde, Services, Diagnostics, Journaux, Éditeur de config, redémarrer, éteindre). « Tous les réglages » disparaît (l'ancien favori `#status` ouvre Image).
  - Image et Jour/nuit : **image en direct** au-dessus des réglages (une photo toutes les 2 s, seulement pendant que la section est ouverte et la page visible). Les curseurs s'appliquent **au relâchement** ; plus d'interrupteur « Enable live image tuning » (actif dès qu'une valeur ≠ 0) ; bouton « Valeurs d'usine ».
  - Détection : cartes **Babyphone et son d'alarme** (`VOX_MODE`, `VOX_HOLD_SECONDS`, `ALARM_DETECT`, `ALARM_HOLD_SECONDS`, `MIN_LOUD_SECONDS`) et **Détection de sabotage** (`tamper.conf`, active/désactive la tâche du housekeeper tout de suite).
  - Nouvelle section **Alertes** (`notify.conf`) : événements (mouvement, son, sabotage), délai, image jointe, Telegram, Ntfy (jeton jamais renvoyé à la page ; vide = garder, « - » = supprimer), webhook. Toutes les valeurs sont filtrées (fichier chargé par le shell).
  - Intégrations → Telegram : l'interrupteur devient « Bot Telegram : répondre aux commandes » (c'est ce qu'il faisait) ; les alertes Telegram sont dans Alertes.
  - Nouvelles commandes `action.cgi` : `events_info` (lecture), `set_notify_config`, `set_tamper_config`, `set_sound_options` (`scripts/action.d/events.sh`).
- **Interrupteurs :** ceux des cartes (tout désactivé par défaut).
- **Test (navigateur, propriétaire) :**
  1. Menus : chaque entrée ouvre la bonne section ; ordinateur et téléphone.
  2. Image : l'image se rafraîchit ; bouger la luminosité → appliqué au relâchement, visible dans l'image en 2 à 4 s ; « Valeurs d'usine » → retour à l'image d'origine ; quitter la section → plus de requêtes `currentpic.cgi` (onglet Réseau du navigateur).
  3. Alertes : Ntfy avec un sujet de test → un mouvement envoie **une** notification avec l'image ; une adresse avec un espace ou un guillemet est refusée avec un message.
  4. Sabotage activé dans la page → main sur l'objectif ≥ 10 s → état « objectif masqué » et alerte ; désactivé → plus rien.
  5. Babyphone activé (avec la détection sonore) → l'entité son de Home Assistant reste active pendant le bruit puis s'éteint après le délai.
- **Critères :** 1 à 5 conformes ; charge CPU de la caméra inchangée hors section Image.

## 2026-11-03 — Une seule définition par valeur : signal Wi-Fi, RAM, santé de la carte SD (`[one-value]`)

- **Quoi :** signal Wi-Fi calculé une seule fois (`scripts/wifi-signal.sh`, -110..-1 dBm, vide si le pilote ne donne rien : -256 et 0) pour le tableau de bord, la ligne d'état, `metrics.cgi` (échantillon omis au lieu d'un faux 0), MQTT et `wifi-quality.sh` ; chemin 2.x `rx_signal` et fonction morte supprimés. RAM : disponible = `MemAvailable`, utilisée = total − disponible, partout (tableau de bord compris ; la ligne de démarrage dit « MemAvailable »). Carte SD : `sdinfo-sd.sh` est le seul à lire dmesg et à écrire `/tmp/sd-health` (`state=errors` quand le noyau a signalé des erreurs) ; `sd-diag.sh` le lit ; réparation **refusée** en mode SD (carte qui porte le firmware, montée en écriture) ; chemins `/mnt/records` morts supprimés. `stability.csv` sur la carte (`/mnt/sd/logs`) quand elle est là, sinon RAM, jamais la flash.
- **Effet de bord :** quand `/tmp/sd-health` dit `errors`, `log-persist.sh` n'écrit plus de journaux sur la carte (il exigeait déjà `ok`).
- **Interrupteur :** aucun (revert de 31ebfc2).
- **Test :** (1) tableau de bord, `/cgi-bin/metrics.cgi` et diag MQTT : même signal (dBm négatif) ; sans lecture : `null` en JSON, pas d'échantillon `tc100_wifi_signal_dbm`. (2) RAM utilisée identique entre tableau de bord, ligne d'état et MQTT. (3) erreur carte dans dmesg → `/tmp/sd-health` `state=errors`, même état dans le panneau Disque et `sd-diag.sh check` ; mode SD : « Réparer » → refusé, aucun fsck ; mode flash avec carte : la réparation fonctionne. (4) mode flash avec carte : `/mnt/sd/logs/stability.csv` se remplit (~1 h), `/cgi-bin/stability.cgi` le renvoie ; sans carte : RAM seulement.
- **Critères :** valeurs identiques partout, aucune valeur inventée, aucun fsck sur la carte en service, rien d'écrit en flash.

## 2026-11-03 — Doublons supprimés : network-monitor, partage HTTP « WebDAV », restes de Privacy Shield ; `awb.state` n'écrit plus la flash à lui seul (`[dedup]`)

Décisions du propriétaire : un seul chemin fonctionnel par fonction ; WebDAV supprimé.

- **Quoi :** suppression de `network-monitor` (`net-guard` reste le seul garde réseau ; ses autres rôles n'apportaient rien sur la 3.0 : relance MQTT déjà gérée par le pont, rebond de wlan0 jugé inutile par l'enquête W-NET) ; du partage HTTP « WebDAV » (port 8080 ; la page Enregistrements sert déjà les vidéos) ; des restes de Privacy Shield (action web, commande MQTT, champ de santé ; la ligne qui efface l'ancienne entité Home Assistant reste) ; de l'action `conf_autodaynight` (écrivait des clés mortes, aucun appelant). `MEM_GUARD_SOFT_SERVICES` ne cite plus `network-monitor` (migration dans memory-guard). `cfg-persist` ignore `awb.state` pour décider d'écrire la flash ; il part avec la sauvegarde suivante (démarrage, 5 min, redémarrage volontaire).
- **Interrupteur :** aucun (suppressions ; revert de 1cf8d47).
- **Test :** (1) page Services : ni network-monitor ni WebDAV ; les autres services démarrent et s'arrêtent. (2) `MEM_GUARD_SOFT_SERVICES` d'une caméra qui citait `network-monitor` : le nom disparaît au redémarrage de memory-guard. (3) box coupée : seul `net-guard` redémarre la caméra (avec `WIFI_RESCUE=1`, après les 2 cycles de secours). (4) MQTT `health` publié, Home Assistant fonctionne. (5) 30 min de flux avec une lumière qui change : `awb.state` change mais `/tmp/cfg-persist.status` ne montre pas de nouvelle sauvegarde ; après un redémarrage volontaire, le slot contient `awb.state` et les gains sont restaurés.
- **Critères :** aucune page cassée ni erreur CGI ; aucune écriture flash due à `awb.state` seul.

## 2026-11-04 01:00 — Correctifs de l'audit poussés par le testeur (à intégrer dans la prochaine RC)

À la demande du propriétaire, le testeur a corrigé lui-même les points P0 de `audit-2026-11-03.md`. **CI verte** sur `46fe526` (tests hôte + build). Commits :
- `4c21283` CSS : purge Bulma relancée (`has-text-weight-semibold`), la CI était rouge depuis e0e9ea0.
- `f3568c4` MQTT/Telegram : refus des espaces, quotes et `$ ` \ ; & | < > ( )` (fichiers sourcés par le shell root) dans la page Réglages, l'appairage HA et Telegram ; l'assistant ne garde plus `( )`.
- `104c65d` Import JSON : **ce n'était pas un corps vide**, l'import durait ~40 s et mon client coupait à 30 s. Écritures groupées par fichier (`tc_apply_edits`) + cache de validation : **12-15 s** mesurées sur la .11.
- `64fa7a2` `frigateyaml` / `integrationmanifest` / `integrationtest` annonçaient 15 fps (rtspserver.conf non chargé) : 25 fps maintenant.
- `9cd90f8` 7 tests de non-régression (`tests/test_audit_fixes.py`).
- `46fe526` Doc : CHANGELOG [Unreleased], CREDITS, known-issues rc23, checklist release cochée.

Méthode de test sur caméra : fichiers superposés en RAM sur la .11 (`mount --bind` sur /mnt, retirés ensuite ; la .11 est revenue exactement en rc23, md5 vérifiés). **Rien n'est installé en flash** : il faut une RC (rc24) pour les avoir sur les caméras.

Pour l'implémenteur :
1. Publier une rc24 avec ces commits ; je la teste sur les deux caméras.
2. Restent ouverts (checklist `release-3.0.1.md`) : exposition au boot, mot de passe en clair dans `frigateyaml` (proposer `{FRIGATE_RTSP_PASSWORD}`), fichier LICENCE (décision du propriétaire), source/licence de `monvifd`, `rwconf`, `getflag`, `getimage`, `syslog/host` différent entre .11 et .24, mDNS multicast depuis le Mac.
3. Correction d'audit : le README « 15 fps by default » est juste (`[0] fps=15` dans la .dist).

## 2026-11-04 — Correctifs des constats de la nuit rc23 (`[night-fixes]`, à intégrer dans la rc24)

- **Quoi :**
  1. `wifi-quality.sh` : `iw` (5 s) et `ping` (8 s) sous `timeout` (un échantillon bloqué dans le pilote figeait le journal de la .11 depuis 20:13) ; le signal est désormais `signal avg` de `iw station dump` (déjà lu à chaque échantillon), écrit dans `/tmp/wifi-signal.avg` ; `scripts/wifi-signal.sh` (le seul lecteur du signal) l'utilise tant qu'il a moins de 3 min, sinon le niveau de `/proc/net/wireless`.
  2. `health-probe.sh` (`health.cgi` et `health-snapshot.sh`) : un service coupé par son interrupteur (clé de `service-switch.sh`, ou pas d'entrée `autostart` pour les autres ; `daynight=3` pour le jour/nuit auto) est `disabled`, plus `stopped` : Memory Guard (`MEM_GUARD_ENABLE=0` par défaut) ne compte plus comme un redémarrage.
  3. Carte SD : avant un redémarrage volontaire (`reboot-tracker.sh intent` : page web, bouton, MQTT, chiens de garde) l'enregistreur est mis en pause puis la carte remontée en lecture seule (5 s max) ; idem à la fin d'une mise à jour web. Un `reboot` tapé en ssh n'est pas couvert.
  4. `frigateyaml` : plus de mot de passe en clair, `{FRIGATE_RTSP_PASSWORD}` dans les adresses (Frigate le remplace depuis son environnement) ; README à jour.
- **Interrupteur :** aucun (revert du commit).
- **Test (rc24) :** (1) `WIFI_QUALITY=1` une nuit : `/tmp/wifi-quality.log` s'écrit jusqu'au matin, un seul processus `wifi-quality.sh` à la fois ; `rssi` du journal ≈ `signal avg` de `iw dev wlan0 station dump` ; tableau de bord et `metrics.cgi` donnent la même valeur. (2) `health.cgi` : `memory-guard` = `disabled` (avec `MEM_GUARD_ENABLE=0`), compteur de redémarrage à 0. (3) .24 : redémarrage depuis la page web → pas de `FAT-fs ... not properly unmounted` au démarrage suivant (`dmesg | grep FAT`). (4) Diagnostics → YAML Frigate : `{FRIGATE_RTSP_PASSWORD}` au lieu du mot de passe ; avec la variable définie dans Frigate, le flux s'ouvre.
- **Critères :** 1 à 4 conformes.

## 2026-11-04 — Plus de HTTPS sur la caméra : restes de la 2.x supprimés, HTTPS par un proxy (`[no-https]`)

Décision du propriétaire : l'interface reste en HTTP simple sur le port 80 ; le HTTPS se fait par un proxy sur son réseau (README, section « HTTPS with a reverse proxy » : Caddy, nginx).

- **Quoi :** supprimés : clés `WEB_MODE`, `ULTRALITE_HTTP_PORT`, `UI_ULTRALITE_MODE` et tout leur code (`set_web_mode`, `apply_web_mode_async`, assistant, `state.cgi`/`statelib.cgi`, `network.cgi`, `mqtt-bridge.sh`, `web-guard.sh` → port 80 seulement, lignes de l'export JSON), le badge « HTTPS impossible » et le mode « ultra-lite » de l'interface, `config/ssl/` (Let's Encrypt de la 2.x, paquet de certificats) et `config/openssl.cnf`. Les adresses du manifeste Home Assistant sont toujours `http://`. Gardés avec une valeur fixe pour Home Assistant : `web_mode: "http"`, `port_https_open: 0`. Le HTTPS sortant (curl vers Ntfy, webhooks, Telegram, GitHub) ne change pas.
- **Interrupteur :** aucun (revert de 1ea1a8c).
- **Test :** (1) `http://IP/` : l'interface se charge, vidéo fluide comprise, sans badge orange « HTTP ». (2) Page Réseau : plus de ligne « HTTPS web UI », « HTTP web UI » ouverte. (3) Manifeste (`state.cgi?cmd=integrationmanifest`) : adresses en `http://IP/…`, `web_mode` = `http`. (4) Import d'une ancienne sauvegarde JSON qui contient `web_mode` : réussit, `boot.conf` sans `WEB_MODE`. (5) Vérification de mise à jour (`UPDATE_CHECK=1`) et alerte Telegram ou Ntfy de test : fonctionnent (certificats du système). (6) Propriétaire : interface derrière son proxy HTTPS, vidéo fluide comprise (`live.cgi` sans mise en tampon).
- **Critères :** 1 à 6 conformes, entité Home Assistant toujours disponible.

## 2026-11-04 — Signal Wi-Fi : `beacon signal avg` (suite de la relecture testeur de 11:05) (`[wifi-beacon]`)

- **Quoi :** `wifi-quality.sh` relève `beacon signal avg:` de `iw dev wlan0 station dump` (signal moyen des balises du point d'accès) au lieu de `signal avg:` (faux sur la .24 : -13 dBm avec MCS 2). Pas de repli sur `signal avg` (démontré faux avec rtl8xxxu) : sans ligne de balises, c'est le niveau de `/proc/net/wireless`. La valeur reste partagée par `scripts/wifi-signal.sh` (cache de 3 min) avec le tableau de bord, `metrics.cgi` et MQTT.
- **Interrupteur :** aucun (revert du commit).
- **Test (rc24, `WIFI_QUALITY=1`) :** `rssi` de `/tmp/wifi-quality.log` ≈ `beacon signal avg` de `iw` (.24 ≈ -51, .11 ≈ -20) et cohérent avec le débit (`tx bitrate`) ; même valeur sur le tableau de bord et `metrics.cgi`.
- **Critères :** écart ≤ 3 dB avec `beacon signal avg` ; plus de valeur aberrante (-13 avec MCS 2).

- 2026-11-04 11:30 (testeur) : `a3fd7e7` relu et vérifié sur la sortie réelle de `iw` de la .24 (retries 3, failed 1, `beacon signal avg` -51 → `3 1 -51`). OK. Prêt pour une **rc24**.

## 2026-11-04 — Retours du propriétaire : mDNS, `syslog/host`, licence (`[license]`)

- **mDNS :** `<nom>.local` confirmé par le propriétaire depuis son poste. Point fermé dans `release-3.0.1.md`.
- **`syslog/host` (.11 = 192.168.1.23, .24 = 192.168.1.22) :** les deux adresses sont le même Synology ; pas de défaut, rien à aligner. À vérifier au passage avec la rc24 : les journaux des deux caméras arrivent bien sur le Synology.
- **Licence :** fichier `LICENSE` = texte officiel de la GPL-2.0 (cohérent avec les patchs noyau et `libakuio`, déjà `SPDX-License-Identifier: GPL-2.0`) ; README (« Where it comes from ») et `CREDITS.md` le disent, le code tiers garde sa licence. Pas de test caméra.

## 2026-11-04 — Pays Wi-Fi (`regulatory.db`), Wi-Fi plus tôt au démarrage (`[wifi-country]`)

- **Quoi :**
  1. **Base des règles Wi-Fi** : `BR2_PACKAGE_WIRELESS_REGDB=y` (Buildroot) → `/lib/firmware/regulatory.db` dans l'initramfs ; le noyau (inchangé, `CFG80211=y`, signature non exigée) la lit au démarrage. Plus de `cfg80211: failed to load regulatory.db`. La base Buildroot est reconstruite une fois en CI (~40 min, cache ensuite). `build-rootfs66.sh` prévient si le fichier manque.
  2. **Pays** : clé `WIFI_COUNTRY` de `boot.conf` (seule source ; vide = règles « monde » comme avant), lue par `scripts/wifi-country.sh` (et par `S39tc100` avec le même motif, avant la partie utilisateur). `wpa_supplicant` démarre sur une copie de `config/wpa_supplicant.conf` avec `country=XX` en première ligne (S39 et `wifi-apply`) ; `autorun` relit la base si le noyau l'a ratée et règle le pays s'il n'est pas appliqué ; Réglages → Réseau → « Pays (règles Wi-Fi) » l'applique tout de suite (`wpa_cli set country` + `iw reg set`, sans reconnexion) ; le point d'accès de secours reçoit `country_code` + `ieee80211d=1` ; export / import JSON (`boot.wifi_country`, code ISO à 2 lettres majuscules ou vide).
  3. **Wi-Fi plus tôt** : dans `S39tc100` (la console et le mot de passe restent avant le Wi-Fi : quelques ms, et sans réseau ils n'attendent pas les 20-30 s du DHCP, audit du 2026-11-04) ; `udhcpc -T 1 -t 20 -A 5` (une demande par seconde au lieu de 3 s : les premières partent avant l'association) ; le nom DHCP vient de `config/hostname.conf` (`/tmp/dhcp-hostname`), donc `autorun` ne tue plus `udhcpc` sur une caméra qui a son propre nom (le nouveau `udhcpc` effaçait l'adresse jusqu'au bail : coupure à chaque démarrage de la .11 et de la .24). Attente de `wlan0` par pas de 0,2 s.
  4. Page Réglages : « Se connecter à ce réseau » et « Relancer l'assistant » affichaient « Error: Unexpected response » après un enregistrement réussi (`ok:true` attendu comme `status:success`). Corrigé.
- **Interrupteur :** `WIFI_COUNTRY=` vide = comportement d'avant pour le pays. Le reste : revert du commit (initramfs, donc mise à jour web complète).
- **Test (les deux caméras, mise à jour web) :**
  1. Après le démarrage : `dmesg | grep -i regulatory` → pas de « failed to load » ; `iw reg get` → `country 00` sans pays.
  2. Réglages → Réseau → Pays = FR, Enregistrer : « En vigueur : FR » après 2-3 s, **pas de coupure** (ping continu depuis le Mac) ; `iw reg get` → `country FR: DFS-ETSI` ; `head -1 /etc/wpa_supplicant.conf` → `country=FR` ; `grep WIFI_COUNTRY /mnt/config/boot.conf`.
  3. Redémarrer : `iw reg get` → FR sans action ; `logread | grep -i country`.
  4. Temps du Wi-Fi : `dmesg` / `logread` : moins de secondes entre « wlan0: associated » et l'adresse DHCP qu'avant ; ping continu depuis le Mac pendant un redémarrage : premier ping reçu (noter l'heure) ; **plus de perte pendant la première minute** une fois la première réponse reçue. `ps | grep udhcpc` : un seul, lancé par S39 (pas de redémarrage par autorun) ; le nom DHCP est celui de la caméra sur la box.
  5. Réglages → Réseau : « Se connecter à ce réseau » sur le réseau actuel → message de succès (plus d'« Unexpected response »).
  6. Nuit `WIFI_QUALITY=1` en FR : pertes de ping comparées à la nuit rc23 (7-11 %).
  7. Point d'accès de secours (bouton reset 3-7 s) : `cat /tmp/wifi-rescue/hostapd.conf` → `country_code=FR` ; le téléphone le voit et s'y connecte.
- **Critères :** 1-5 et 7 conformes ; 6 : pas pire que la rc23 (mieux attendu si les pertes venaient du domaine monde).

## 2026-11-04 — Pont MQTT en C : `tc100-mqttd` (`[mqtt-c]`)

- **Quoi :** `src/mqttd` = un seul processus C (MQTT 3.1.1, TCP simple, QoS 0) à la place des 4 processus shell de `mqtt-bridge.sh run` (~5,7 Mo cumulés). Il tient la connexion (CONNECT `<id>-sub`, Will retenu `<root>/availability` = `offline`, `online` à chaque connexion, PINGREQ toutes les 30 s, reprise avec le backoff et le disjoncteur de `mqtt.conf`), s'abonne au topic de commande et lance `mqtt-bridge.sh command <payload> mqtt` (argument unique, jamais `system()`, 120 s maximum). **Les payloads restent produits par `mqtt-bridge.sh`** (modes `startup`, `health-cycle`, `command`, `print-config`) : discovery, santé, manifeste, résultats de commande = mêmes topics et mêmes octets que le pont shell (test hôte de parité). Les autres scripts (`mqtt-bridge.sh publish`, mouvement, son, sabotage) passent par le FIFO `/tmp/mqtt-bridge.pub` du démon au lieu d'ouvrir une connexion chacun. Binaire compilé par la CI (`tc100-mqttd` dans `tc100test/`, copié dans le stack).
- **Interrupteur :** `MQTT_BRIDGE_IMPL=shell|c` dans `/mnt/config/mqtt.conf` (seule source), lu par `controlscripts/mqtt-bridge` ; **`shell` par défaut**. Pour essayer : mettre `MQTT_BRIDGE_IMPL=c`, puis `/mnt/controlscripts/mqtt-bridge restart`. Retour : `shell` + restart. Sans binaire installé, retombe seul sur le shell. Aucune modification du noyau, de U-Boot ni du Wi-Fi.
- **Test (une caméra, MQTT activé, broker réel) :**
  1. `MQTT_BRIDGE_IMPL=c`, restart. `ps | grep mqtt` : un seul `tc100-mqttd` (plus de `mqtt-bridge.sh run`) ; `grep -E 'VmRSS|VmHWM' /proc/$(cat /var/run/mqtt-bridge.pid)/status` (attendu < 500 Ko au repos, mesure à noter) ; `/tmp/log/mqtt-bridge.log` : « MQTT connected ».
  2. Home Assistant : les ~30 entités existantes **gardent leurs identifiants** (aucun doublon `_2`), l'appareil et la version (`sw`) sont inchangés ; `<root>/availability` = `online` retenu ; `<root>/health` se met à jour toutes les 300 s ; `<root>/isp/state` et `motion/state` suivent.
  3. Commandes depuis HA ou `mosquitto_pub -t <root>/command` : `{"cmd":"ir_led","value":"on"}`, `snapshot`, `profile:low-cpu`, `play_sound` (bouton Chime), `isp_brightness`, `health`, `discovery`, `restart_mqtt_bridge` (le démon redémarre seul, fichier pid refait), `reboot` en dernier. Chaque commande donne un `command/result` et agit sur la caméra ; une commande inconnue donne `rejected`.
  4. Événements des autres scripts : mouvement ON/OFF (`motion/state`), babyphone, sabotage arrivent sans connexion TCP supplémentaire (`netstat -tn | grep 1883` : une seule).
  5. Interface web : Réglages → Intégrations affiche « connecté » (`/tmp/mqtt_last_pub.status` « <t> ok » rafraîchi) ; mauvais mot de passe MQTT : « login refused » (`fail 4` ou `fail 5`) ; broker coupé 1 min puis rétabli : le démon se reconnecte (journal « recovered after N error(s) ») sans intervention, le Will met `availability` à `offline` pendant la coupure.
  6. Arrêt : `mqtt-bridge stop` publie `offline`, le FIFO et `/var/run/tc100-mqttd.pid` disparaissent ; `kill -9` du démon puis `mqtt-bridge.sh publish event x 0` : repli sur la connexion unique (pas de blocage).
  7. Nuit complète (soak) avec `c` : pas de redémarrage, RAM stable, `mqtt-bridge.log` sans erreur répétée.
- **Critères :** 1 à 7 conformes ; RSS du démon bien en dessous des ~5,7 Mo du pont shell ; aucune entité HA dupliquée ou renommée ; au moins une commande de chaque famille (interrupteur, profil, son, ISP, santé, redémarrage) exécutée. Si tout passe sur les deux caméras : mettre `MQTT_BRIDGE_IMPL=c` par défaut dans `config/mqtt.conf.dist` (le testeur peut le faire) ; ne pas encore supprimer le pont shell (repli).
- **Différences connues avec le pont shell :** pas de recyclage horaire de la connexion ; un PINGREQ sans réponse en 20 s coupe la connexion (le shell ne le détectait pas) ; `mqtt_last_pub.status` est aussi rafraîchi à chaque PINGRESP/envoi (au plus 1 fois par s), pas seulement à chaque publication ; une commande bloquée 120 s est tuée ; les publications faites hors connexion attendent la reconnexion (128 Ko max) au lieu de partir sur une connexion à part ; `MQTT_STREAM_*`, `MQTT_COMMAND_WAIT_SECONDS`, `MQTT_PERSISTENT_SUBSCRIBE`, `MQTT_FORGE_SUBSCRIBE` ne servent qu'au pont shell ; le TLS n'existe dans aucun des deux. Non vérifié sans caméra : l'édition de liens sous uClibc (comme `tc100_rtsp`) et le fonctionnement de `printf '\000'` du busybox de la caméra (le pont shell utilisait déjà `\x00`).

## 2026-11-04 — Correctifs de l'audit du soir (`[audit]`, voir `audit-2026-11-04.md`)

- **Quoi :** (H1) `tc100_rtsp` : tampon re-terminé après une trame entrelacée `$`, longueur incohérente → client fermé ; (W1) plus de valeur de la requête réécrite dans les pages d'erreur de `viewrecords.cgi`, `camcontrols.cgi`, `scripts.cgi` ; journal d'audit limité à `[A-Za-z0-9_.-]` ; `showlog` échappe les journaux ; (W5) `user.pwd` copié depuis `.dist` avant `web-auth` sur tous les chemins ; (B2) dans `S39`, console et mot de passe de nouveau avant le Wi-Fi ; CI durcie.
- **Interrupteur :** aucun (revert du commit).
- **Test (rc suivante, une caméra) :**
  1. RTSP : Frigate / VLC lisent toujours le flux principal, le sous-flux et l'audio, en TCP et en UDP ; la voie de retour (push-to-talk ONVIF) passe toujours en TCP entrelacé.
  2. `http://<cam>/cgi-bin/viewrecords.cgi?cmd=<b>x</b>` affiche « Unsupported command » sans gras ; `action.cgi?cmd=showlog` affiche les journaux en texte (aucune balise interprétée).
  3. Mode sans échec (ou caméra sans `user.pwd`) : l'interface demande toujours un mot de passe.
  4. Console série au démarrage sans Wi-Fi : invite de login tout de suite (plus d'attente du DHCP).
- **Critères :** 1-4 conformes, aucune régression de flux.

## 2026-11-04 nuit — Vérification du projet après la rc26 (implémenteur, `[verify]`)

- **Corrigé :** `src/webui/index/90-startup.js:53` (et le bundle) : la regex de détection du redémarrage contenait un caractère « retour arrière » (0x08) au lieu de `\b` ; elle ne correspondait jamais. Effet depuis le 2026-10-30 (`b8459ef`) : après « Redémarrer » sur le tableau de bord, « Command sent to the camera » au lieu de « Restarting: the camera is back in about a minute », et un message rouge « The camera did not accept the command » quand la connexion tombait pendant le redémarrage. Test ajouté : aucun caractère de contrôle dans `www/`, `src/webui/`, `scripts/`, `controlscripts/`, `v3/`.
- **CHANGELOG rc26 corrigé :** la ligne « ~0,3 Mo gagnés au démarrage » était fausse (voir `a-faire-implementeur.md`, P0 n° 2, note de vérification).
- **Interrupteur :** aucun.
- **Test (rc suivante) :** tableau de bord → Redémarrer → « Restarting: the camera is back in about a minute », puis éventuellement « The camera stopped answering: it is probably restarting » (orange), jamais le message rouge.

## 2026-11-04 nuit — Page « Test du matériel » (`[hwtest]`, feuille de route n° 49)

- **Quoi :** Outils → Test du matériel (`www/hardware.html`) : la caméra dessinée de face et de dos (d'après la photo du propriétaire) ; un clic sur un élément le teste avec les commandes existantes : image + luminance / exposition (objectif), LED bleue (allumer, éteindre, clignoter), LED rouge, LED IR et filtre IR-cut, vumètre du micro, carillon sur le haut-parleur, carte microSD (taille, libre, santé), bouton reset affiché enfoncé. Une seule nouvelle commande, en lecture : `action.cgi?cmd=hw_state` (toutes les 2 s tant que la page est ouverte et visible, arrêt en quittant la page). Thème clair / sombre, mobile.
- **Interrupteur :** aucun (page à part ; revert du commit).
- **Test (une caméra) :**
  1. Chaque élément : LED bleue et rouge allumées / éteintes / clignotement visibles sur la caméra **et** sur le dessin ; LED IR (lueur dans le noir, visible au téléphone) ; filtre IR-cut (clic audible, image qui change) ; carillon entendu ; carte .24 : taille et libre corrects ; objectif : image actuelle + luminance.
  2. Micro : avec la détection sonore activée, le vumètre monte quand on parle ; sans elle, le message « Pas de niveau ».
  3. Bouton : appui bref → dessin jaune puis « Relâché (un appui a été vu) » (si `button-watch` a exporté le GPIO 522 ; sinon « Le bouton ne peut pas être lu », à noter).
  4. Charge : `top` pendant 2 min page ouverte : un `action.cgi` toutes les 2 s, CPU moyen à noter ; page quittée : plus aucune requête `hw_state` (journal httpd).
  5. **Emplacements** : dos redessiné d'après la photo du propriétaire (bouton reset = trou en haut à gauche, haut-parleur = gros trous en haut à droite, disque de fixation, micro-USB, fente SD sur le côté). **À confirmer** : le dos n'a pas de LED, donc la LED rouge est supposée être la deuxième couleur de la LED d'état en façade (point du haut) ; vérifier en cliquant « Rouge allumée ».
- **Critères :** 1-4 conformes, aucune action de la page sans jeton CSRF (les commandes de modification répondent 403 sans lui).

## 2026-11-05 — Feuille de route 20, 22, 26, 27, 29 complétées (`[roadmap]`)

- **Quoi :**
  - **26** Carillon / Alerte / Sirène sur le tableau de bord (volume du curseur du haut-parleur, confirmation pour la sirène).
  - **27** `http://<caméra>/metrics` (redirection `httpfront`) ; nouvelles métriques : `tc100_rtsp_capture_fps`, `tc100_rtsp_main_kbps`, `tc100_rtsp_sub_kbps`, `tc100_rtsp_clients_playing`, `tc100_rtsp_dropped_frames` (fichier `/var/run/tc100_rtsp.stat` écrit par `tc100_rtsp` toutes les 5 s), `tc100_sdcard_present|size_bytes|free_bytes`, `tc100_info{version}`.
  - **29** scripts et feuilles de style chargés en `?v=<md5>` (`src/webui/stamp-assets.sh`, lancé par `build-index.sh`).
  - **20** `MQTT_SNAPSHOT_ON_EVENT=1` (dans `mqtt.conf`, désactivé par défaut) : image JPEG sur `<racine>/snapshot/image` à chaque mouvement, son ou sabotage, 10 s minimum entre deux.
  - **22** page Sauvegarde : « Télécharger la sauvegarde complète (.tar.gz) » et « Restaurer cette sauvegarde » (fichiers de `config/` seulement, validés, transaction).
- **Interrupteur :** 20 : `MQTT_SNAPSHOT_ON_EVENT=0` ; le reste : revert du commit.
- **Test (une caméra) :**
  1. Tableau de bord : Carillon, Alerte entendus ; Sirène demande confirmation puis sonne ; le volume suit le curseur.
  2. `curl -u root:<mdp> -L http://<caméra>/metrics` : les nouvelles lignes, `tc100_rtsp_capture_fps` ≈ la cadence réglée, `tc100_rtsp_main_kbps` ≈ le débit, `tc100_sdcard_free_bytes` sur la .24 ; `cat /var/run/tc100_rtsp.stat` mis à jour toutes les 5 s.
  3. Après la mise à jour, le navigateur charge les nouveaux fichiers sans vider son cache (la page Test du matériel et les nouveaux boutons apparaissent, les nouvelles traductions françaises aussi).
  4. MQTT : `MQTT_SNAPSHOT_ON_EVENT=1`, redémarrer le pont ; un mouvement → image dans l'entité caméra de Home Assistant et message sur `snapshot/event` ; deux mouvements à moins de 10 s → une seule image.
  5. Sauvegarde : télécharger l'archive (taille de quelques Ko, contient `config/...`), changer un réglage, restaurer l'archive → réglage revenu, réponse « fichier(s) » ; un fichier quelconque renommé en `.tar.gz` est refusé sans rien changer. La flash garde la restauration après un redémarrage (`cfg-persist`).
- **Critères :** 1-5 conformes ; aucun effet sur le flux vidéo (le fichier `.stat` coûte une écriture en RAM toutes les 5 s).

## 2026-11-05 — Corrections de l'audit du 2026-11-04 : W2, R1, R2, R3, B4, B5, B6, pont MQTT (`[audit-fix]`)

- **Quoi :**
  - **W2** `NET_LAN_ONLY=1` (défaut) s'applique de nouveau à la page web (`httpfront`) et au RTSP (`tc100_rtsp`) : une connexion hors des réseaux privés / link-local / 100.64/10 / `NET_ALLOW_EXTRA` est fermée sans réponse. La caméra elle-même (127.0.0.1) est toujours admise. ssh n'est pas filtré.
  - **R2** `httpfront` : 16 connexions au plus, 8 par adresse (au-delà : `503`), connexion muette fermée après 2 s.
  - **R1** `tc100_rtsp` : connexion sans requête acceptée fermée après 30 s, client qui ne lit pas fermé après 60 s sans requête ; créneaux pleins → le plus ancien inactif qui ne lit pas cède sa place. **R3** gardes (URL vide, TCP/UDP mêlés → 461, OSD borné).
  - **B4/B6** `update66.sh` arrête aussi le housekeeper, `web-guard`, `rtsp-h26x` ; sauvegarde les réglages (`cfg-persist flush`) et remet le compteur de démarrage à zéro avant d'écrire ; garde les sauvegardes des 2 dernières mises à jour dans `tc100-3/backup`. **B5** verrou sur `cfg-persist save`.
  - Pont MQTT : plus de `sh mqtt-bridge start` resté en mémoire.
- **Interrupteur :** W2 : `NET_LAN_ONLY=0` dans `boot.conf` (puis redémarrage) ; le reste : revert du commit.
- **Test :**
  1. Depuis le LAN : page web, Frigate et VLC fonctionnent comme avant (Frigate main + sub ensemble, VLC avec mot de passe tapé lentement : < 30 s).
  2. Depuis une adresse hors liste (un client VPN dont le réseau n.est pas dans `NET_ALLOW_EXTRA`) : connexions web et RTSP fermées ; avec `NET_LAN_ONLY=0` : page de connexion.
  3. `for i in $(seq 12); do nc <caméra> 80 & done` depuis un PC du LAN : la page web reste accessible depuis un autre PC ; les connexions muettes se ferment après ~2 s (`ps | grep -c httpd` revient à 0).
  4. 4 connexions muettes `nc <caméra> 554` puis VLC : la vidéo démarre (une connexion muette est évincée) ; Frigate lisant en continu n'est jamais coupé.
  5. Pont MQTT (shell et C) : `ps` ne montre plus `sh /mnt/controlscripts/mqtt-bridge start` ; `cat /var/run/mqtt-bridge.pid` = pid du démon ; `stop` puis `start` sans doublon.
  6. Mise à jour web suivante (rc27) : le journal `tc100-3/update66.log` montre les arrêts ; `tc100_rtsp` ne revient pas pendant l'écriture ; après redémarrage les réglages changés juste avant sont là ; `ls tc100-3/backup` : au plus 2 jeux.
- **Critères :** 1-6 conformes, aucun redémarrage ni perte de flux.
- **Mesurer la RAM en PSS** (`/proc/<pid>/smaps_rollup`, P0 #6) : le gain du point 5 se lit en PSS (~200 Ko), pas en RSS.

## 2026-11-05 — Flux principal en 720p (`[720p]`, liste de l'implémenteur #8)

- **Quoi :** Réglages → Flux principal → Résolution : 1920 x 1080 (défaut) ou 1280 x 720. Noyau : patch 0016 (`ak39_vi` recadre toujours la fenêtre 1080p entière, l'ISP met le canal principal à l'échelle demandée ; paramètre en lecture seule `ak39_vi.main_scale`). En 1080p le noyau fait exactement la même chose qu'avant (recadrage 1920x1080). `tc100_rtsp` : `RTSP_WIDTH=1280 RTSP_HEIGHT=720` (passés par `rtsp-launch.sh` quand `[0] mainres=720`), refusés si le noyau n'a pas `main_scale`.
- **Interrupteur :** Résolution 1920 x 1080 (ou `mainres=1080` dans `rtspserver.conf`) ; `RTSP_WIDTH=1920` dans `rtsp.env` force le 1080p.
- **Test (noyau de la CI de ce commit, d'abord en RAM depuis la carte : `pack66/boot66b.sh`) :**
  1. 1080p (défaut) : rien ne change. `dmesg | grep crop` → `crop L,T 1920x1080, main 1920x1080`. Image, couleurs, détection de mouvement, sous-flux et instantané comme avant. **Ce point d'abord : le patch touche le démarrage de la capture.**
  2. `ls /sys/module/ak39_vi/parameters/main_scale` existe ; Réglages : l'option 720p est active (grisée sur un ancien noyau).
  3. Choisir 1280 x 720, enregistrer : `dmesg` → `main 1280x720` ; log `tc100_rtsp` → `rtsp://<ip>:554/  1280x720` ; VLC / Frigate : **la même image entière** (pas un coin), nette ; sous-flux 640x360 inchangé ; instantané 1280x720 ; masques, horloge (OSD) et zones de mouvement à leur place.
  4. Mesures 720p contre 1080p au même débit : `STAT` (images capturées, débit), `MemAvailable`, charge CPU (`scripts/cpu-profile.sh 60`), qualité de l'image.
  5. Ancien noyau (rc26) avec `mainres=720` : le log dit `crops instead of scaling`, le flux reste en 1920x1080.
- **Critères :** 1 et 3 sans défaut d'image ni oops ; une heure de 720p sans erreur noyau ni redémarrage du serveur.

## 2026-11-05 — Noyau de test pour le mode smart de l'encodeur (`[smart-pool]`, liste de l'implémenteur #9)

- **Quoi :** le workflow `build-kernel-linux66.yml` a une entrée manuelle `venc_pool` : lancé à la main avec `12M`, il construit un noyau dont `ak39_venc.pool` vaut 12M par défaut (le réservoir est alloué au démarrage et la ligne de commande vient du bootloader, qu'on ne touche pas). Les artefacts s'appellent alors `tc100-linux66-cma16-kernel-pool12M` et `tc100-3-release-TESTKERNEL-pool12M` : **noyau de test, pas pour une mise à jour normale**. Sans l'entrée, rien ne change.
- **Lancer :** GitHub → Actions → « Build Linux 6.6 LTS Kernel… » → Run workflow → `venc_pool` = `12M` (ou `gh workflow run build-kernel-linux66.yml -f venc_pool=12M`).
- **Interrupteur :** démarrer le noyau normal (le noyau de test ne s'essaie qu'en RAM depuis la carte, `pack66/boot66b.sh`) ; `[0] smart=0`.
- **Test (.11) :** noyau de test en RAM, puis `[0] vbr=1` et `[0] smart=1` dans `/mnt/config/rtspserver.conf`, redémarrer `tc100_rtsp`.
  1. `dmesg | grep -i pool` : réservoir de 12288 Ko ; log `tc100_rtsp` : `smart mode 1 (long-term reference)`, pas de `smart mode 1 not used`, pas de `alloc dma … failed`.
  2. 24 h : serveur vivant, aucune erreur noyau ; `MemAvailable` ~2,4 Mo plus bas qu'avec le noyau normal (attendu).
  3. Débit et qualité comparés à la .24 (scène calme : le débit doit baisser nettement).
- **Critères :** 1-3 conformes → décider si 12M devient le défaut (la RAM perdue contre le débit gagné) ; sinon le mode smart reste désactivé.

## 2026-11-05 — Micro sans arecord et traitement du son (`[audio-native]`, liste de l'implémenteur #11)

- **Quoi :** dans `tc100_rtsp`, tout désactivé par défaut :
  - `RTSP_ALSA_DIRECT=1` : le micro est lu par les ioctl ALSA du noyau (`acap.c`) au lieu d'un processus `arecord` (≈ 660 Ko PSS et un tube en moins). Si `/dev/snd/pcmC0D0c` ne s'ouvre pas : retour à `arecord`, dit dans le log.
  - `RTSP_AUDIO_HPF=1` : passe-haut 150 Hz (-19 dB à 50 Hz, voix intacte).
  - `RTSP_AUDIO_AGC=1` : noise gate (souffle d'une pièce calme -12 dB) + contrôle du niveau (voix lointaine jusqu'à +18 dB) + écrêtage doux.
  - `RTSP_AUDIO_DUCK=1` : micro coupé pendant que le haut-parleur joue (retour audio, appuyer-pour-parler, sons), anti-larsen.
  - Le vumètre de la détection sonore mesure toujours le son brut : ses seuils ne changent pas.
- **Interrupteur :** retirer la ligne de `/mnt/config/rtsp.env` (ou `=0`) et redémarrer `tc100_rtsp`.
- **Test :** mettre les switches dans `/mnt/config/rtsp.env`, `sh /mnt/controlscripts/rtsp-h26x restart`.
  1. `RTSP_ALSA_DIRECT=1` seul : log `audio: microphone read directly (/dev/snd/pcmC0D0c, no arecord)` ; `ps` sans `arecord` ; piste audio RTSP (VLC), bouton Écouter, enregistrement SD avec son, détection sonore : tout marche comme avant, pas de saut ni d'écho métallique ; `dmesg` sans erreur ALSA. Une heure de VLC avec le son : pas de coupure (un dépassement est récupéré tout seul). Mesurer la PSS gagnée (`smaps_rollup` d'`arecord` avant).
  2. `RTSP_AUDIO_HPF=1` : le ronflement grave disparaît, la voix reste naturelle.
  3. `RTSP_AUDIO_AGC=1` : pièce calme → souffle plus bas ; voix à 3-4 m → plus forte ; un claquement ne sature pas.
  4. `RTSP_AUDIO_DUCK=1` : pendant un appuyer-pour-parler ou le retour audio de Home Assistant, l'auditeur n'entend pas sa propre voix revenir ; le son revient ~60 ms après.
  5. CPU (`scripts/cpu-profile.sh 60`) avec les quatre : pas de hausse visible.
- **Critères :** 1-5 conformes → les quatre deviennent le défaut (puis un réglage dans la page Audio).

## 2026-11-05 — Clips d'événement gardés en priorité (`[retention]`, liste de l'implémenteur #15)

- **Quoi :** `tc100_rtsp` pose un marqueur vide `AAAA-MM-JJ_HH-MM-SS.evt` à côté de chaque enregistrement pendant lequel il y a eu un mouvement ou un son (toujours, coût : une entrée de répertoire). Avec `REC_KEEP_EVENTS=1` dans `boot.conf`, quand la carte manque de place, le plus ancien enregistrement **sans** événement part d'abord ; les clips d'événement seulement quand il ne reste qu'eux. La page Enregistrements supprime aussi le `.evt`.
- **Interrupteur :** `REC_KEEP_EVENTS=0` (défaut) : le plus ancien part, comme avant.
- **Test (.24, carte SD) :**
  1. `REC_WHEN=always` : agiter la main devant la caméra → le fichier en cours a son `.evt` (`ls /mnt/DCIM/*.evt`) ; un fichier sans mouvement n'en a pas.
  2. `REC_KEEP_EVENTS=1`, `REC_RESERVE_MB` réglé juste au-dessus de l'espace libre actuel (pour forcer le ménage) : le log dit `deleted (keeping N MB free, no event in it)` et les fichiers `.evt` restent ; remettre `REC_RESERVE_MB` ensuite.
  3. Supprimer un enregistrement depuis la page : son `.jpg` et son `.evt` partent avec.
- **Critères :** 1-3 conformes ; aucun effet sur l'enregistrement lui-même.

## 2026-11-05 — Anti-scintillement automatique (`[flicker]`, liste de l'implémenteur #16)

- **Quoi :** Réglages → Image → Anti-scintillement → « Automatique (selon le pays Wi-Fi) » (`POWER_HZ=auto` dans `isp_tune.conf`) : `tc100_rtsp` prend 60 Hz pour les pays à 60 Hz (presque toute l'Amérique, Corée du Sud, Taïwan, Philippines, Arabie saoudite), 50 Hz ailleurs ; Japon et pays non réglé : valeur de la caméra.
- **Interrupteur :** choisir 50 Hz, 60 Hz ou « Valeur de la caméra ».
- **Test :** pays `FR` + Automatique → log `anti-flicker: 50 Hz (exposure step …)` comme avec 50 Hz ; pays `US` → `60 Hz` ; pays vide → `camera default`. Sous un éclairage LED / fluo, pas de bandes avec Automatique en France.
- **Critères :** les trois lignes de log ; pas de bandes.

## 2026-11-05 — Réparations Wi-Fi douces avant le redémarrage réseau (`[wifi-soft]`, liste de l'implémenteur #17)

- **Quoi :** `NET_GUARD_SOFT=1` dans `boot.conf` : quand la passerelle ne répond plus alors que `wlan0` existe (et que le point d'accès de secours n'est pas levé), `net-guard.sh` tente, une fois chacune par coupure : à 2 min `wpa_cli -i wlan0 reassociate` ; à 5 min `wifi-apply` (wpa_supplicant + DHCP) ; à 8 min `wifi-recover.sh reprobe` (puce USB sondée de nouveau). Le redémarrage à `NET_GUARD_MIN` (15 min) reste le dernier recours.
- **Interrupteur :** `NET_GUARD_SOFT=0` (défaut).
- **Test :** `NET_GUARD_SOFT=1`, éteindre la box (ou le point d'accès) 10 min puis la rallumer : `logread | grep net-guard` montre les trois étapes à 2, 5 et 8 min, la caméra revient seule sur le réseau à la remise en route sans redémarrer (avant 15 min) ; second essai : couper 3 min → seule la réassociation a lieu, puis `network back`.
- **Critères :** reconnexion sans redémarrage quand la box revient avant 15 min ; aucune étape quand le réseau va bien.

## 2026-11-05 — Débit automatique du flux principal (`[abr]`, liste de l'implémenteur #18)

- **Quoi :** `RTSP_ABR=1` dans `/mnt/config/rtsp.env` : toutes les 5 s (ligne `STAT`), si des clients TCP ont sauté 3 images ou plus (file pleine : le Wi-Fi ne suit pas), le débit du flux principal baisse de 30 % (pas sous `RTSP_ABR_MIN`, par défaut un quart du réglage, 200 kbit/s au moins) ; après 30 s sans image sautée il remonte d'un dixième du réglage, jusqu'au réglage. Appel `ak_venc_set_br(handle, kbit/s)` de la bibliothèque d'encodage : **signature supposée** (SDK Anyka), à vérifier ici.
- **Interrupteur :** retirer `RTSP_ABR` de `rtsp.env`, redémarrer `tc100_rtsp`.
- **Test (.11, Frigate ou VLC en TCP) :**
  1. Démarrage : log `ABR: on, main bit rate between 500 and 2000 kbit/s` (selon le réglage).
  2. Provoquer de la congestion (éloigner la caméra de la box, ou limiter le débit côté box / `tc qdisc` sur le PC, ou plusieurs VLC) : log `ABR: N frames skipped in 5 s: main bit rate 2000 -> 1400 kbit/s (ak_venc_set_br: 0)` ; **la colonne `bytes` des lignes `STAT` baisse d'autant** (sinon l'appel n'agit pas : le dire ici) ; l'image reste nette, pas d'artefacts.
  3. Rétablir le réseau : remontée par paliers toutes les 30 s jusqu'au réglage.
  4. Si `ak_venc_set_br` répond autre chose que 0 : `regulation off` dans le log, rien d'autre ne change.
- **Critères :** 2 et 3 conformes, aucun plantage de l'encodeur sur une heure → le défaut peut passer à 1.

## 2026-11-05 — Mouvement d'après la taille des trames de l'encodeur (`[md-enc]`, liste de l'implémenteur #19)

- **Quoi :** `RTSP_MD_ENC=1` dans `rtsp.env` : un second détecteur à côté de la grille de luminance. En VBR, trois trames P de suite plus grosses que leur moyenne glissante (x3,6 à la sensibilité 60, x2 à 100, x6 à 1) = mouvement (même sortie que la grille : `/tmp/rec_control`, MQTT, enregistrement, cadence au repos). Zones de mouvement non prises en compte.
- **Interrupteur :** retirer `RTSP_MD_ENC`.
- **Test (.11, `vbr=1`) :** log `motion from the encoder frame sizes: on` ; passer devant la caméra → `rec_control` à 1 comme avec la grille, en même temps ou plus tôt ; scène calme une nuit : compter les fausses alertes contre la grille seule (`RTSP_DEBUG=1` donne les tailles des trames) ; en CBR le log prévient.
- **Critères :** détecte un passage ; pas plus de fausses alertes que la grille → décider s'il reste en option ou devient le défaut en VBR.

## 2026-11-05 — Jour / nuit : 60 s minimum entre deux bascules (`[daynight-lock]`, liste de l'implémenteur #21)

- **Quoi :** `auto-night-daemon.sh` ne rebascule plus avant `MIN_SWITCH` secondes (60 par défaut, `daynight.conf`), quelle que soit la source (luminance, ae, isp, vendor). Une demande trop tôt est notée sur la console et appliquée dès que le temps est écoulé si elle tient toujours. La page Réglages garde la valeur en réécrivant le fichier.
- **Interrupteur :** `MIN_SWITCH=0` dans `/mnt/config/daynight.conf`.
- **Test :** au crépuscule (source luminance) : plus de va-et-vient du filtre IR-cut (`logread | grep auto-night` : au plus une bascule par minute, et la ligne `waiting 60 s` si la luminance remonte avec les LED IR) ; enregistrer Réglages → Jour/nuit : `MIN_SWITCH=60` reste dans le fichier.
- **Critères :** pas de cliquetis ; jour et nuit atteints normalement.

## 2026-11-05 — Heure par l'en-tête HTTP `Date` si NTP est bloqué (`[time-http]`, liste de l'implémenteur #24)

- **Quoi :** `scripts/time-fallback.sh`, lancé 2 min après le démarrage : tant que l'horloge est avant 2025, toutes les 5 min (12 fois au plus), une requête `HEAD` vers la page du routeur (`TIME_HTTP_URLS=gateway`, défaut) ; l'en-tête `Date:` règle l'horloge. ntpd continue et reste la référence.
- **Interrupteur :** `TIME_HTTP_FALLBACK=0` dans `boot.conf`.
- **Test :** bloquer l'UDP 123 sortant sur la box (ou `ntp_srv.conf` vers une adresse muette), redémarrer : 2 min après, `logread | grep time-fallback` → `clock set from the Date header of http://<routeur>/` et `date` est à l'heure (à quelques secondes près) ; sans blocage, rien ne se passe (ntpd a déjà réglé l'heure). Si le routeur n'a pas de page web, ajouter `http://www.google.com` à `TIME_HTTP_URLS`.
- **Critères :** heure juste sans NTP ; aucune requête quand NTP marche.

## 2026-11-05 — Mode confidentialité (`[privacy]`, liste de l'implémenteur #25)

- **Quoi :** `controlscripts/privacy start|stop` (page Services « Privacy Mode », interrupteur MQTT/Home Assistant « Privacy Mode », champ `privacy_on` du topic de santé) crée ou retire `/tmp/tc100_privacy` et écrit `PRIVACY_SCREEN` dans `boot.conf`. `tc100_rtsp` (lu chaque seconde) : image noire sur le flux principal, le sous-flux, l'instantané, la vue en direct et l'enregistrement ; silence à la place du micro ; détection de mouvement en pause. Au démarrage, le drapeau est recréé avant la première image si `PRIVACY_SCREEN=1`.
- **Interrupteur :** `stop` (ou `PRIVACY_SCREEN=0`).
- **Test :**
  1. Activer depuis la page Services : en moins de 2 s, VLC / Frigate / la vue en direct montrent du noir ; `currentpic.cgi` noir ; la piste audio est silencieuse ; bouger devant la caméra → aucun événement de mouvement ; log `privacy mode on`.
  2. **Mode capture directe** (défaut) : aucune ligne de l'image réelle ne doit transparaître (le nettoyage du cache couvre toute l'image) — regarder plusieurs minutes, sous-flux compris.
  3. Redémarrer la caméra : l'image reste noire dès la première trame.
  4. Interrupteur Home Assistant : bascule et état cohérents.
  5. Désactiver : image, son et détection reviennent.
- **Critères :** 1-5 conformes, aucune fuite d'image.

## 2026-11-05 — Démon ONVIF libre `tc100-onvifd`, remplace `monvifd` (`[onvif]`, liste de l'implémenteur #12 et #53)

- **Quoi :** nouveau `tc100-onvifd` (`/mnt/tc100test/tc100-onvifd`, construit par la CI, artefact `tc100-linux66-cma16-kernel`). WS-Discovery, services Device, Media et Media2 (profil avec sortie et décodeur audio = retour audio), service Events (PullPoint : mouvement `VideoSource/MotionAlarm` et `RuleEngine/CellMotionDetector/Motion`, lu dans `/tmp/rec_control`), authentification WS-Security (même identifiant que le RTSP : `RTSP_USER` ou `root`, mot de passe de `user.pwd`), filtre `TC100_NET_ALLOW`.
- **Interrupteur :** `ONVIF_IMPL=monvifd` (défaut) dans `/mnt/config/onvif.conf` puis `/mnt/controlscripts/onvif restart` revient à l'ancien binaire. Mettre `ONVIF_IMPL=c` pour l'essai.
- **Test :**
  1. `ONVIF_IMPL=c`, redémarrer le service ; `ps` montre `tc100-onvifd`.
  2. Découverte : ONVIF Device Manager (ou l'intégration ONVIF de Home Assistant) voit la caméra.
  3. Frigate ou VLC avec l'URI donnée par `GetStreamUri` (`rtsp://<ip>:554/video0_unicast`).
  4. Home Assistant, intégration ONVIF : ajout avec l'identifiant et le mot de passe de la caméra ; flux principal et sous-flux présents ; le capteur de mouvement apparaît, passe à « détecté » en ~2 s quand on agite la main, revient ~8 s après.
  5. Image fixe : `http://<ip>/cgi-bin/currentpic.cgi`.
  6. Mauvais mot de passe refusé (`NotAuthorized`).
  7. go2rtc ou Home Assistant en audio bidirectionnel (retour audio).
  8. Changer la résolution (1080p / 720p) ou le codec dans Réglages, redémarrer `onvif` : les profils suivent.
  9. PSS du processus avec Home Assistant connecté.
- **Critères :** découverte et profils corrects ; flux lisible ; `NotAuthorized` sur mauvais identifiant ; capteur de mouvement HA correct sans abonnements qui s'accumulent (4 au plus) ; pas de plantage sur 24 h ; PSS < 300 Ko ; pas de régression de `tc100_rtsp`. Si tout passe : `ONVIF_IMPL=c` par défaut, puis retrait de `monvifd`.

## 2026-11-05 — Changements d'un autre agent sans entrée de test (ajoutées par l'implémenteur, 11:00)

### `[mqtt-c-default]` Pont MQTT en C par défaut (`7d7e074`, `28ecd67`)
- **Quoi :** `MQTT_BRIDGE_IMPL=c` dans `config/mqtt.conf.dist` (les caméras déjà installées gardent leur `mqtt.conf`) ; `28ecd67` retire aussi l'ancien abonnement par curl (il ne marchait plus) et ajoute `_get_now_ts`.
- **Interrupteur :** `MQTT_BRIDGE_IMPL=shell` dans `/mnt/config/mqtt.conf`.
- **Test :** une installation neuve (ou `mqtt.conf` recopié de la `.dist`) démarre `tc100-mqttd` ; deuxième nuit stable sur la rc26/27 comme la première (un seul démon, pas de reconnexion) ; entités HA inchangées.
- **Note implémenteur :** `_get_now_ts` est appelée par `$(…)` : un sous-shell par événement / commande, là où le script évitait les forks (sans effet fonctionnel).

### `[pacing]` `RTSP_PACING_US=100` par défaut (`cf4960b`)
- **Quoi :** `rtsp-launch.sh` exporte `RTSP_PACING_US=100` si rien n'est donné (100 µs entre les paquets d'une rafale) ; `rtsp.env` peut le changer.
- **Interrupteur :** `RTSP_PACING_US=0` dans `/mnt/config/rtsp.env`.
- **Test (.11, une nuit, avec l'enregistreur de pertes) :** pertes de ping et images sautées (`dropped` des lignes `STAT`) comparées à la nuit du 2026-11-05 (9,5 %) ; latence du direct et charge CPU inchangées ; pas d'artefacts sur les images clés.
- **Critères :** moins de pertes / d'images sautées, rien de pire ; sinon revenir à 0.

### `[sd-fsck]` `dosfsck -a` avant de remonter la carte (`9623e94`)
- **Constat de l'implémenteur (sans caméra) :** `dosfsck` n'est pas dans l'image (la ligne est sautée par `command -v`), et le montage du démarrage se fait dans `S39tc100-linux66`, pas dans `rec-storage.sh` : **aucun effet attendu** sur le « not properly unmounted » de la .24. À reprendre au #41 de `a-faire-implementeur.md` (bit « sale » lu dans S39, réparation seulement s'il est posé, `fsck.fat` dans l'image).
- **Test :** sur la .24, `command -v dosfsck fsck.fat` (attendu : rien) et `dmesg | grep FAT` au démarrage suivant une mise à jour web.

## 2026-11-05 — Carte SD propre après chaque redémarrage, réparation FAT (`[sd-clean]`, liste de l'implémenteur #41 ; remplace `[sd-fsck]`)

- **Quoi :**
  - Cause trouvée de « not properly unmounted » : à l'arrêt, init lance `/etc/init.d/rcK` (donc `S39tc100 stop`) puis `umount -a -r`. S39 sortait aussitôt (`[ "$1" = start ] || exit 0`) : `tc100_rtsp` enregistrait encore, le remontage en lecture seule échouait. **`S39tc100 stop`** arrête maintenant `tc100_rtsp` (SIGTERM, 5 s : le fichier est fermé proprement), `sync`, `mount -o remount,ro /mnt/sd`. Si la carte reste occupée : une ligne dans `tc100-3/shutdown.log` avec les pid qui la tiennent (`fuser`).
  - `fsck.fat` (dosfstools) dans `ext/bin` du stack (pas dans l'initramfs) : le bouton « Réparer » de la page Carte SD (`sd-diag.sh repair` : pause de l'enregistrement, démontage, `fsck.fat -a`, remontage) fonctionne enfin.
  - `SD_AUTO_REPAIR=1` (`boot.conf`, défaut 0, mode flash) : si le noyau a vu la carte sale au démarrage (coupure de courant), la même réparation une minute après.
  - Le `dosfsck -a` ajouté dans `rec-storage.sh` par `9623e94` est retiré.
- **Interrupteur :** `SD_AUTO_REPAIR=0` ; l'arrêt propre n'a pas d'interrupteur (il ne fait que fermer et remonter en lecture seule).
- **Test (.24, carte SD, enregistrement actif) :**
  1. Redémarrage voulu (page web, puis `reboot` en ssh, puis une mise à jour web) : au démarrage suivant, `dmesg | grep FAT` **sans** « not properly unmounted » ; le dernier enregistrement se lit jusqu'au bout ; pas de `tc100-3/shutdown.log` (ou, s'il existe, noter les pid qu'il cite).
  2. `ls /mnt/ext/bin/fsck.fat` ; page Carte SD → Réparer : réponse `fsck_repaired`, l'enregistrement reprend.
  3. `SD_AUTO_REPAIR=1`, couper le courant pendant un enregistrement : au démarrage `not properly unmounted` dans `dmesg`, puis ~1 min après `sd-diag` répare (`/tmp/sd-health`, log) et l'enregistrement reprend.
- **Critères :** 1 sans avertissement FAT sur 3 redémarrages ; 2 et 3 conformes. La taille de l'initramfs ne change presque pas (quelques lignes de S39).

## 2026-11-05 — Filet pour les journaux en RAM (`[log-cap]`, liste de l'implémenteur #28)

- **Quoi :** tâche `log-cap` du housekeeper (toutes les 10 min) : un fichier de `/tmp/log` ou `/tmp/logs` au-dessus de `LOG_CAP_KB` (64) garde ses 200 dernières lignes, réécrit sur place (même inode). `tc100_rtsp.log` et les copies `.0` / `.1` ne sont pas touchés.
- **Interrupteur :** `LOG_CAP_KB=100000` (ou retirer la tâche : `housekeeper.sh job del log-cap`).
- **Test :** `sh /mnt/scripts/housekeeper.sh job list` montre `log-cap` ; `yes x | head -c 100000 >> /tmp/log/essai.log`, attendre 10 min (ou `sh /mnt/scripts/log-cap.sh`) : 200 lignes restent, ligne `log-cap:` dans `logread` ; une semaine de fonctionnement : `du -sh /tmp/log /tmp/logs` stable.
- **Critères :** taille plafonnée, aucun journal qui s'arrête d'écrire après le passage.

## 2026-11-05 — Limite des essais de mot de passe sur la page web (`[web-lockout]`, liste de l'implémenteur #30, audit W3)

- **Quoi :** `WEB_LOCKOUT=1` dans `boot.conf` (redémarrer `httpfront` : `http_server restart`, ou la caméra) : `httpfront` vérifie lui-même l'identifiant Basic de chaque requête contre `/etc/httpd.conf` (MD5 crypt, une seule fois par identifiant : empreinte gardée dans `/tmp/.httpfront-ok`) ; un mauvais identifiant est noté ; **10 en 5 min depuis une adresse → ses connexions sont fermées 5 min** (127.0.0.1 jamais) ; ligne dans `/tmp/log/httpfront.log`. busybox httpd répond toujours aux requêtes (401 inchangé).
- **Interrupteur :** `WEB_LOCKOUT=0` (défaut).
- **Test :**
  1. Avec le bon mot de passe : navigation normale sur toutes les pages, rien dans `/tmp/log/httpfront.log`, `/tmp/.httpfront-ok` existe.
  2. Depuis un autre PC : `for i in $(seq 10); do curl -s -o /dev/null -u root:faux http://<caméra>/cgi-bin/state.cgi; done` puis `curl -v http://<caméra>/` → connexion fermée sans réponse ; le premier PC (autre adresse) navigue toujours ; 5 min après, le second PC est de nouveau servi.
  3. Changer le mot de passe dans Réglages : l'ancien est refusé par httpd comme avant, le nouveau marche (pas de verrou pour l'utilisateur légitime).
- **Critères :** 1-3 conformes ; jamais de verrou sur l'utilisateur qui tape le bon mot de passe → passer `WEB_LOCKOUT=1` par défaut.

## 2026-11-05 — Cadence éco quand personne ne regarde ou la nuit (`[eco-fps]`, liste de l'implémenteur #31)

- **Quoi :** `IDLE_WHEN` dans `boot.conf` (avec `IDLE_FPS`, par ex. 10) : `still` (défaut, comme avant : quand rien ne bouge, détection de mouvement nécessaire), `unwatched` (aucun client RTSP en lecture, pas de vue en direct dans un navigateur ; la pleine cadence dès qu'un client lit), `night` (en mode nuit). Un mouvement ou un son rend la pleine cadence `IDLE_AFTER` secondes.
- **Interrupteur :** `IDLE_FPS=0` (défaut) ou `IDLE_WHEN=still`.
- **Test :** `IDLE_FPS=10 IDLE_WHEN=unwatched`, Frigate arrêté et pas de VLC : log `idle frame rate: lowered`, `STAT cap` ≈ 10 images/s ; ouvrir VLC → `back to the full rate` en moins d'une seconde, l'image est fluide ; fermer VLC → de nouveau 10 après `IDLE_AFTER`. `IDLE_WHEN=night` : la nuit 10 images/s, le jour pleine cadence. Charge CPU (`scripts/cpu-profile.sh 60`) plus basse pendant la cadence réduite.
- **Critères :** bascules conformes, aucune image figée au retour d'un client, enregistrement continu jamais ralenti.

## 2026-11-05 — Aide au placement Wi-Fi (`[wifi-aim]`, liste de l'implémenteur #32)

- **Quoi :** tableau de bord : la valeur du signal Wi-Fi en vert (≥ -60 dBm), orange (jusqu'à -70) ou rouge. `WIFI_AIM=1` dans `boot.conf` : pendant 5 min après le démarrage, la LED bleue de façade clignote d'autant plus vite que le signal est bon (≈ 4 fois/s à -50 dBm, une fois toutes les 2 s à -85), éteinte sans lien ; éteinte à la fin. Le signal vient de `wifi-signal.sh` (le même que partout).
- **Interrupteur :** `WIFI_AIM=0` (défaut).
- **Test :** `WIFI_AIM=1`, redémarrer ; tourner la caméra / l'éloigner de la box : le rythme suit le signal ; après 5 min la LED s'éteint et `ps` n'a plus `wifi-aim.sh`. Tableau de bord : la couleur suit les dBm affichés.
- **Critères :** rythme cohérent avec les dBm, LED rendue éteinte, pas d'effet sur le reste.

## 2026-11-05 — Images hors de la caméra sur alerte grave (`[notify-burst]`, liste de l'implémenteur #34)

- **Quoi :** `scripts/notify.sh` : une alerte sans image (sabotage) en prend une fraîche (`NOTIFY_ATTACH_SNAPSHOT=1`) ; `NOTIFY_BURST=N` (0-5) envoie N images de plus, une par seconde, pour les événements de `NOTIFY_BURST_EVENTS` (défaut `tamper`) vers Ntfy / Telegram ; `NOTIFY_UPLOAD_URL` envoie aussi chaque image de l'alerte par HTTP PUT (dossier WebDAV du Synology, adresse pré-signée), `NOTIFY_UPLOAD_AUTH="utilisateur:mot de passe"` facultatif. Ntfy sans `eval`.
- **Interrupteur :** `NOTIFY_BURST=0`, `NOTIFY_UPLOAD_URL=""` (défauts).
- **Test :** Ntfy (ou Telegram) actif, `NOTIFY_BURST=3`, `NOTIFY_UPLOAD_URL=http://<synology>/webdav/tc100/` : masquer l'objectif avec la main jusqu'à l'alerte de sabotage → 1 + 3 images reçues sur le téléphone, 4 fichiers `<caméra>_<date>_tamper_0..3.jpg` dans le dossier WebDAV ; un mouvement → une seule image (pas de rafale) ; un message avec une apostrophe passe.
- **Critères :** images reçues et copiées ; aucune rafale hors des événements choisis.

## 2026-11-05 — Services mDNS (DNS-SD) et informations (`[mdns-sd]`, liste de l'implémenteur #38)

- **Quoi :** `MDNS_SERVICES=1` dans `boot.conf` (puis `controlscripts/mdns restart`) : `tc100-mdnsd -s` répond aussi à la recherche de services : `_http._tcp` (port 80, `path=/`) et `_rtsp._tcp` (port 554, `path=/video0_unicast`), avec SRV, TXT et l'adresse dans la même réponse. `MDNS_INFO=1` (`-v`) ajoute `model=TC100`, `fw=<version>`, `load=<charge 1 min>`, `rssi=<dBm>` aux TXT. Toujours seulement sur le même sous-réseau, jamais d'annonce spontanée.
- **Interrupteur :** `MDNS_SERVICES=0`, `MDNS_INFO=0` (défauts).
- **Test :** depuis un PC du réseau : `avahi-browse -rt _http._tcp` (ou `dns-sd -B _http._tcp` sur Mac/Windows) montre la caméra, port 80 ; `avahi-browse -rt _rtsp._tcp` : port 554, `path=/video0_unicast` ; VLC → Réseau local → mDNS liste la caméra ; Home Assistant propose de l'ajouter (zeroconf) ; avec `MDNS_INFO=1` les TXT montrent version, charge, signal. `ping <nom>.local` marche toujours.
- **Critères :** découverte par les trois outils ; rien de plus annoncé sans les interrupteurs.

## 2026-11-05 — Roaming entre bornes d'un même réseau (`[wifi-roam]`, liste de l'implémenteur #40)

- **Quoi :** `WIFI_ROAM=1` dans `boot.conf` : tâche `wifi-roam` du housekeeper chaque minute ; sous -75 dBm à deux contrôles de suite, `wpa_cli scan`, puis `wpa_cli roam <bssid>` vers une borne du même SSID au moins 15 dB plus forte ; 10 min de pause après une bascule. Lignes `wifi-roam:` dans `logread`.
- **Interrupteur :** `WIFI_ROAM=0` (défaut).
- **Test (seulement avec un répéteur ou un mesh) :** caméra associée à la borne éloignée (signal < -75), la proche allumée : en 2-3 min `wifi-roam: ... roaming to <bssid>`, `wpa_cli status` montre le nouveau BSSID, le flux continue (coupure de 1-2 s au plus). Avec une seule borne : rien d'autre qu'une ligne « no access point ... better » quand le signal est faible.
- **Critères :** bascule vers la meilleure borne, pas de va-et-vient (10 min de pause).

## 2026-11-05 — Démarrage discret (`[boot-stealth]`, liste de l'implémenteur #42)

- **Quoi :** `BOOT_STEALTH=1` dans `boot.conf` : pas de carillon de démarrage, pas de clignotement `WIFI_AIM`, LED éteintes dès le script S39 (seules les premières secondes du noyau restent allumées) ; `FRONT_LED` / `RED_LED` s'appliquent à la fin du démarrage comme avant. `BOOT_SOUND=0` reste disponible seul.
- **Interrupteur :** `BOOT_STEALTH=0` (défaut).
- **Test :** `BOOT_STEALTH=1`, redémarrer dans le noir : la LED bleue ne reste allumée que quelques secondes au tout début, aucun son, puis la LED suit le réglage de Réglages.
- **Critères :** aucun son, LED éteintes pendant le démarrage (hors noyau), réglages LED respectés ensuite.

## 2026-11-05 — Test du lien vers l'enregistreur (`[nvr-latency]`, liste de l'implémenteur #43)

- **Quoi :** Diagnostics → onglet « Lien vers l'enregistreur » → « Tester le lien » : 10 pings (0,2 s d'écart quand busybox le permet) vers l'adresse Frigate des Réglages, sinon `REC_CLIENT`, sinon la box (ou l'adresse tapée) ; réponse : pertes %, délai min / moyen / max, gigue (moyenne des écarts entre deux mesures).
- **Interrupteur :** aucun (bouton à la demande).
- **Test :** sans adresse : la cible est Frigate (ou la box) ; avec l'adresse du Synology : résultat en ~3 s ; une adresse inexistante → `pertes 100 %` ; une adresse avec des caractères interdits → refusée. Comparer avec la nuit de pertes Wi-Fi (#9).
- **Critères :** chiffres cohérents avec un ping depuis un PC.

## 2026-11-05 — Secrets retirés des réponses en lecture seule (`[secrets-get]`, audit W6)

- **Quoi :** `wifi_rescue_info` ne renvoie plus le mot de passe du point d'accès de secours (seulement `psk_set`) ; Réglages → « Afficher » le demande avec `reveal=1` et le jeton CSRF. `state.cgi?cmd=fullconfig` ne renvoie plus le jeton Telegram (`token_set`) ; dans Réglages, un champ vide garde le jeton, `-` le retire.
- **Interrupteur :** aucun (revert du commit).
- **Test :** Réglages → Wi-Fi de secours : mot de passe masqué, « Afficher » le montre ; `curl -u root:<mdp> 'http://<caméra>/cgi-bin/action.cgi?cmd=wifi_rescue_info&format=json&reveal=1'` sans jeton → refus CSRF. Telegram : enregistrer le formulaire sans toucher au jeton → le bot marche toujours ; `-` → jeton retiré.
- **Critères :** aucun secret dans `fullconfig` ni dans `wifi_rescue_info` sans `reveal` ; Telegram inchangé après un enregistrement.

## 2026-11-05 — Pont MQTT en C : pas de résolution DNS à chaque reconnexion (`[mqtt-m1]`, audit M1)

- **Quoi :** `tc100-mqttd` : une adresse de broker numérique n'est plus jamais résolue (`inet_aton`) ; un nom est résolu une fois, puis de nouveau seulement après un échec de connexion ; un topic de plus de 65 535 octets est refusé au lieu d'être tronqué.
- **Interrupteur :** aucun (revert).
- **Test :** pont en C avec l'adresse IP du broker : couper le broker 1 min puis le relancer → reconnexion, commandes et `availability` comme avant ; avec un nom (`MQTT_HOST=nas.local`) : idem.
- **Critères :** reconnexion normale dans les deux cas, pas de gel du pont pendant la coupure.

## 2026-11-05 — Image flash plus petite (`[flash-space]`, item 54)

- **Quoi :** `stack.sqfs` ne contient plus `sounds/test-1k-m*.pcm` ni `www/css/bulma.1.0.2.purged.min.css`, `ui-modern.min.css`, `ui.css` (et leurs `.gz`) : seul `css/ui.bundle.min.css` est chargé par les pages. Le wizard (`cgi-bin/wizard.cgi`) ne charge plus Bulma (il n'utilise que ses classes `wz-*`) et porte les quelques règles de remise à zéro dont il dépendait. `mksquashfs` utilise le filtre ARM de xz (`-Xbcj arm`). Mesuré en Docker : -65 Ko pour les exclusions, -4 Ko de BCJ sur nos binaires ; le gain sur `ext/` (curl, dropbear, hostapd, libasound) se lit dans le log du build (`stack.sqfs: N bytes`).
- **Interrupteur :** `SQFS_BCJ=none` au build pour le filtre ; les fichiers exclus restent dans le paquet SD ; revert pour le wizard.
- **Test :** comparer `stack.sqfs: N bytes` du build CI avec celui du build précédent. Sur la caméra : `mount` → `stack` monté sans erreur, `dmesg | grep -i squashfs` sans erreur, interface web complète (styles corrects), son de démarrage joué. Wizard : `http://<caméra>/cgi-bin/wizard.cgi` (ou première installation) → même aspect qu'avant (fond sombre, pas de marge blanche, boutons et champs à la bonne police).
- **Critères :** image plus petite, aucune erreur squashfs/xz au montage ni en lisant les binaires (`tc100_rtsp`, `curl --version`, `dropbear -V`), wizard identique.

## 2026-11-05 — Frise des enregistrements (`[rec-timeline]`, item 36)

- **Quoi :** page Enregistrements : la frise du jour est dessinée par le navigateur (canvas) à partir de `viewrecords.cgi?cmd=day_index` (un `stat`, un `date`, un `awk` pour toute la journée : début, durée d'après la date de dernière écriture, taille, plages d'événements). Chaque fichier à sa vraie longueur, les plages mouvement/son en rouge, la tête de lecture, zoom 24 h → 5 min (liste ou double-clic). Clic ou glisser → le lecteur part de cette seconde (même fichier : simple saut, sans recharger) ; flèches ±10 s (Maj : ±1 min). `tc100_rtsp` écrit maintenant les instants dans le `.evt` (`on S` / `off S`, secondes depuis la première image du fichier, 64 lignes au plus) ; les `.evt` vides des versions précédentes colorent tout le fichier en orange. Clic sur un événement de la liste « Motion Events » : ouvre son jour (le format de date ne correspondait pas) à son heure.
- **Interrupteur :** aucun côté caméra (la commande `day_index` ne sert qu'à la page ; sans elle la frise retombe sur les noms de fichiers) ; revert pour la page.
- **Test :** enregistrement en continu (`REC_MODE=always`) pendant au moins 15 min, bouger devant la caméra 2 ou 3 fois. Puis : `cat /mnt/DCIM/<jour>_<heure>.evt` → lignes `on N` / `off N` cohérentes avec les mouvements ; page Enregistrements : fichiers contigus sur la frise, plages rouges aux bons endroits ; clic au milieu d'une plage rouge → la vidéo démarre à cet instant (comparer l'horloge OSD) ; clic dans le même fichier un peu plus loin → saut sans rechargement ; zoom 1 h et 5 min ; touches flèches. Essayer Chrome, Firefox et Safari (le saut dans un MP4 fragmenté sans index peut attendre le téléchargement jusqu'à ce point).
- **Critères :** saut à ±2 s de l'heure cliquée (OSD), pas d'erreur dans la console, `viewrecords.cgi?cmd=day_index&date=<jour>` en moins de 1 s pour une journée complète (288 fichiers), charge CPU de la caméra inchangée pendant le défilement.

## 2026-11-05 — Sons personnalisés (`[sounds]`, item 48)

- **Quoi :** Réglages → Flux & audio → Sons : liste des sons (d'origine et les vôtres, durée), Lire, Supprimer, choix du son de démarrage (ou Silencieux). Ajout : n'importe quel fichier que le navigateur décode (WAV, MP3, OGG…) est converti dans le navigateur en PCM 8 kHz mono 16 bits (crête à -1 dBFS, 30 s au plus) puis envoyé à `cgi-bin/sounds.cgi`, qui l'écrit sur la carte SD (`/mnt/sd/tc100-3/sounds/NOM.pcm`, 32 sons au plus). Un son nommé `chime`, `alert`, `siren` ou `startup_complete` remplace celui d'origine : boutons du tableau de bord, MQTT / Home Assistant (`sound_path` dans `common_functions.sh`), démarrage (`BOOT_SOUND_NAME` dans `boot.conf`).
- **Interrupteur :** supprimer le son personnalisé (celui d'origine revient) ; `BOOT_SOUND_NAME=startup_complete` ; revert pour la page.
- **Test :** avec une carte SD : envoyer un MP3 de quelques secondes nommé `sonnette` → apparaît « le vôtre », Lire → joué sans saturation ; choisir `sonnette` comme son de démarrage, redémarrer → joué au démarrage ; envoyer un fichier nommé `chime` → le bouton Carillon du tableau de bord et le bouton MQTT jouent le nouveau ; Supprimer `chime` → l'ancien revient. Sans carte SD : la partie « Ajouter » est cachée, Lire marche. Fichier de 2 min : seules les 30 premières secondes sont gardées. Essayer Chrome, Firefox et Safari (iPhone).
- **Critères :** son reconnaissable, volume correct, aucun fichier `.part` qui reste sur la carte, le RTSP continue pendant la lecture.

## 2026-11-05 — Prévision mémoire dans Réglages (`[mem-budget]`, item 45)

- **Quoi :** Réglages → Système → Mémoire : MemAvailable mesurée maintenant, les 8 plus gros programmes (PSS de `smaps_rollup`, regroupée par nom ; un script shell par le nom du script), et une prévision quand on coche/décoche : pont MQTT, ONVIF, mDNS, SSH, `arecord`, pré-enregistrement en mémoire (`REC_RING_KB` si `REC_LOCAL=1`), 1080p au lieu de 720p. Un service qui tourne rend sa PSS actuelle ; un service arrêté coûte une estimation (MQTT C 210 Ko, ONVIF 300 Ko, mDNS 10 Ko, SSH 200 Ko, `arecord` 660 Ko, 1080p 1,7 Mo). Jauge orange sous 10 Mo libres, rouge sous 6 Mo. Commande en lecture seule `action.cgi?cmd=mem_budget&format=json` (un `ps`, un `awk`). Ne change aucun réglage.
- **Interrupteur :** aucun (affichage seul) ; revert.
- **Test :** ouvrir Réglages → Système → Mémoire : « Libre maintenant » proche de `grep MemAvailable /proc/meminfo` ; la liste montre `tc100_rtsp` en tête, PSS proche de `awk '/^Pss:/{print $2}' /proc/$(pidof tc100_rtsp)/smaps_rollup` ; décocher le pont MQTT → la prévision monte de sa PSS ; cocher un service arrêté → elle baisse de l'estimation. Noter les PSS réelles de SSH (dropbear) et ONVIF (`tc100-onvifd`) pour corriger les estimations du tableau `OPTIONS` de `settings.html`.
- **Critères :** valeurs cohérentes avec `/proc`, réponse en moins de 1 s, aucune erreur dans la console du navigateur.

## 2026-11-05 — Audit, points dépôt D1-D9 (`[audit-d]`, item 51)

- **Quoi :** surtout dépôt et CI, mais quatre changements tournent sur la caméra :
  1. `scripts/jsonflat.awk` (import JSON des réglages) double les antislashs sans `gsub` (même sortie avec busybox awk, mawk, gawk) ;
  2. `SERVICE_TRIM` n'est plus écrit dans `boot.conf`, seulement dans `service_trim.conf` (profils de performance, `action.cgi`) ;
  3. la détection du mot de passe par défaut ne lit plus `lighttpd.user` (2.x) : seulement `user.pwd` et le RTSP ;
  4. `isp_flip` est compilé depuis `src/ispflip` par la CI au lieu de la copie de `bin/`.
  Côté build : `regulatory.db` absent → erreur (`ALLOW_NO_REGDB=1` pour passer), publication d'un tag seulement si la CI du commit est verte.
- **Interrupteur :** revert du commit.
- **Test :**
  1. Sauvegarde → Import JSON d'une sauvegarde contenant un texte avec `\` (OSD par exemple) → valeur identique.
  2. Réglages → Profil de performance : `rtsp-only` puis `balanced` → `grep SERVICE_TRIM /mnt/config/service_trim.conf` suit, plus rien dans `boot.conf` ; la page Services affiche le bon profil.
  3. Avec le mot de passe `pass` → l'avertissement « mot de passe par défaut » s'affiche ; avec un autre → non.
  4. Réglages → Image → orientation : retourner puis remettre l'image (`isp_flip` du build).
- **Critères :** les quatre comportements identiques à avant.

## 2026-11-05 — Infobulles des réglages et textes à jour (`[ui-text]`, items 44 et 47)

- **Quoi :** Réglages : un « ? » à côté de 71 réglages sans explication (survol : texte en info-bulle ; clic ou toucher : le texte sous le champ ; en français avec la page). Textes : l'éditeur de configuration ne parle plus de lighttpd ; Infos appareil affiche « Firmware : 3.x (runs from the flash / SD card) » au lieu de « Firmware (SD card) » et d'une ligne « Vendor firmware » toujours vide ; la carte Mémoire décrit la garde mémoire telle qu'elle est (désactivée par défaut, paliers 6 et 3 Mo).
- **Interrupteur :** aucun (affichage) ; revert.
- **Test :** Réglages en français sur ordinateur et sur téléphone : les « ? » sont alignés avec les libellés, un clic sur un interrupteur ne le bascule pas, le texte s'affiche puis se cache ; relire quelques textes (jour/nuit, QP, ntfy, garde mémoire) et signaler ceux qui sont faux. Infos appareil : la ligne Firmware dit bien flash ou carte SD.
- **Critères :** aucun réglage modifié par un clic sur « ? », aucune erreur dans la console, textes justes.

## 2026-11-05 — Page Services en cartes (`[services-ui]`, item 46)

- **Quoi :** Outils → Services : trois cartes thématiques en grille (Cœur : vidéo, web et système — `rtsp-h26x`, `web-server`, `memory-guard`, `health-snapshot`, `button-actions` ; Réseau et accès — `ssh-server`, `telnet-server`, `ftp-server`, `mdns`, `wifi-rescue` ; Intégrations — `mqtt-bridge`, `onvif`, `syslog-forward` ; puis Autres), une petite carte par service : nom, impact CPU/RAM, état, Démarrer/Arrêter, Démarrage (au boot), Voir. Une colonne sur téléphone. Même JavaScript et mêmes commandes qu'avant (`scripts.cgi?cmd=start|stop|enable|disable|allstates`) ; seuls le balisage et les sélecteurs changent. L'URL du script de la page est maintenant tamponnée (`?v=` = md5), comme les autres pages.
- **Interrupteur :** aucun (affichage) ; revert.
- **Test :** ouvrir Services sur ordinateur et téléphone : les états se remplissent (vert = en marche, avec la durée) ; arrêter puis démarrer `mdns` ; basculer « Démarrage » de `syslog-forward` deux fois (vérifier `/mnt/config/autostart`) ; « Problèmes seulement » ne garde que les services en défaut et cache les cartes vides ; « Voir » ouvre la source.
- **Critères :** mêmes actions qu'avant, pas d'erreur dans la console, rien de coupé ni de superposé.

## 2026-11-05 — Références de l'UI avant #50 (`[ui-baseline]`, consigne du propriétaire, pour l'autre agent)

- **Quoi :** avant toute modification du moteur d'interface (#50, Pico / Shoelace chargés à la volée), établir des références précises de l'UI actuelle, pour pouvoir comparer ensuite. Rien n'est modifié dans le firmware.
- **À faire (autre agent) :**
  1. Captures de chaque page (Tableau de bord, Direct, Multi-vues, Enregistrements, chaque onglet de Réglages, Outils → Services / Diagnostics / Journaux / Éditeur / Matériel / Sauvegarde, assistant `cgi-bin/wizard.cgi`) en anglais et en français, clair et sombre, à 1280 px et à 390 px (téléphone), avec `src/webui/screenshots/shots.py` et ses réponses factices (`mock/`), à compléter pour les pages manquantes. Les ranger dans un dossier de références daté, hors de la flash.
  2. Pour chaque page : aucune erreur JavaScript (`pageerror`), aucun défilement horizontal à 390 px, tous les textes traduits en français, temps de chargement et poids transféré (HTML + CSS + JS, avec et sans gzip).
  3. Comportements à vérifier sur la caméra : enregistrer un réglage de chaque onglet, Services (démarrer / arrêter / démarrage), frise des enregistrements, sons, infobulles « ? ».
  4. Écrire le résultat sous cette entrée (pages, mesures, défauts trouvés) ; les défauts deviennent des entrées à part.
- **Critères :** les références existent pour toutes les pages ; #50 ne commence qu'après.

## 2026-11-05 — WebRTC, étape 1 : coût du SRTP sur la caméra (`[whep-srtp]`, item 35)

- **Quoi :** `src/whep/srtp.h` : le chiffrement SRTP de WebRTC (AES-128-CM + HMAC-SHA1-80, dérivation des clés RFC 3711), sans bibliothèque, vérifié avec les vecteurs publiés (FIPS-197, RFC 3174, RFC 2202, RFC 3711 B.2 et B.3) sur PC et en ARM sous qemu. `srtp-bench` (binaire statique, pack de test de la CI : `tc100test/srtp-bench`, pas dans la release) chiffre des paquets RTP de 1200 octets pendant N secondes et donne la part d'un CPU pour 600, 1200 et 2000 kbit/s. Conception de la suite : `docs/linux-port/whep-design.md`.
- **Interrupteur :** aucun (outil de mesure seul, rien ne tourne au démarrage).
- **Test :** copier `srtp-bench` sur la carte, puis sur la caméra, flux en marche (un client RTSP ou la vue en direct ouverts) : `/mnt/sd/tc100test/srtp-bench -t` (doit finir par `self-test: all ok`), puis `/mnt/sd/tc100test/srtp-bench 10` ; noter la sortie et `top` pendant la mesure.
- **Critères :** self-test ok ; résultat noté ici. Décision : moins de 3 % de CPU pour 1200 kbit/s → l'étape 3 peut viser le flux principal ; sinon le flux secondaire seulement.

## 2026-11-05 — Mise à jour web : 3 essais, pas de redémarrage après un échec, somme MD5SUMS (`[b1-update]`)

- **Quoi :** `update66.sh` réessaie chaque écriture `flashw` jusqu'à 3 fois ; après un échec final il n'y a plus de `reboot` automatique : message d'état « FAILED writing <partition> after 3 attempts. Web and ssh stay available… Do not cut the power » (affiché par la page de mise à jour, copié dans `tc100-3/update66.log` avec la carte). B3 : `flashw -m` reçoit la somme de `MD5SUMS` du paquet (et non plus celle du fichier lui-même) ; `check` refuse un paquet dont `MD5SUMS` n'a pas de somme pour stack.sqfs, c66.img ou c66rd.gz.
- **Interrupteur :** `echo initrd > /tmp/update66.simfail` (ou `kernel`, `stack`) fait échouer les 3 essais de cette partition sans rien écrire dedans (md5 faux, refusé par `flashw` avant l'écriture) ; `echo "initrd 1" > /tmp/update66.simfail` ne fait échouer que le 1er essai. `rm /tmp/update66.simfail` pour revenir au normal.
- **Test :** caméra démarrée depuis la flash, carte de secours (`tc100test/c66.img`) à portée. (1) Mise à jour normale par la page web d'un paquet valide : doit aboutir et redémarrer. (2) `echo "initrd 1" > /tmp/update66.simfail` puis mise à jour : un « retrying initrd (attempt 2 of 3) » puis DONE. (3) `echo initrd > /tmp/update66.simfail` puis mise à jour : stack et noyau écrits, initrd refusé 3 fois. (4) Vérifier que la caméra ne redémarre pas, que la page web et ssh répondent, retirer le fichier et relancer la mise à jour : elle doit aboutir. (5) Paquet dont `MD5SUMS` est modifié ou sans ligne pour un fichier : refusé à l'envoi.
- **Critères :** aucun redémarrage après l'échec final ; message avec la partition en cause lisible sur la page ; web et ssh disponibles ; la relance aboutit ; la partition provoquée en échec n'est jamais écrite par l'échec simulé ; mise à jour normale inchangée (durée, redémarrage final).

## 2026-11-05 — Assistant : jeton CSRF obligatoire, fin de `.first_boot` au premier mot de passe (`[w4-wizard]`)

- **Quoi :** `wizard.cgi` refuse tout POST sans l'en-tête `X-CSRF-Token` valide (403, `csrf_invalid`) ; la page de l'assistant lit le jeton dans `statusline.cgi` juste avant d'envoyer. `http_password` (Réglages, mot de passe de l'assistant, restauration) supprime `/tmp/.first_boot` et écrit `config/.password_set` ; le démarrage ne recrée plus `.first_boot` si ce fichier existe ; « Relancer l'assistant » l'efface.
- **Interrupteur :** aucun (revert) ; pour rouvrir l'assistant : Réglages → Système → Relancer l'assistant.
- **Test :** (1) Première installation sur une carte neuve (sans `.wizard3_done`, sans mot de passe) : parcours complet de l'assistant, mot de passe compris ; doit aboutir. (2) `curl -X POST -d 'profile=standalone' http://<cam>/cgi-bin/wizard.cgi` sans jeton pendant que l'assistant est ouvert : réponse 403 `csrf_invalid`, rien de modifié. (3) Même POST avec `-H "X-CSRF-Token: <csrf_token de statusline.cgi>"` : accepté. (4) Caméra jamais passée par l'assistant : changer le mot de passe dans Réglages, vérifier que `/tmp/.first_boot` disparaît, que `/mnt/config/.password_set` existe, et qu'après redémarrage `index.html` n'ouvre plus l'assistant. (5) « Relancer l'assistant » puis parcours complet.
- **Critères :** parcours de première installation inchangé et réussi ; POST sans jeton ou avec jeton faux refusé sans écrire ; après un mot de passe réglé ailleurs, plus de redirection vers l'assistant au redémarrage ; « Relancer l'assistant » rouvre bien l'assistant.

## 2026-11-05 — Console série : extinction auto après 5 min, maintenue en mode sûr (`[opt-56]`)

- **Quoi :** le getty de ttySAK0 reste disponible 5 min après le démarrage (compté depuis autorun, soit environ 20 à 30 s après le noyau). Sans session ouverte à ce moment, `v3/linux66-sd/console-timer` l'arrête et libère sa mémoire. Une session ouverte n'est jamais coupée : il attend sa fin. La console reste allumée en mode sûr (`/tmp/safemode`), avec `/tmp/console-keep`, ou si `SERIAL_CONSOLE=on`. Au moindre doute (pas de /proc, écriture impossible) elle est gardée. Limite : aucune « alerte watchdog » ne crée encore `/tmp/console-keep` (le crochet existe, rien ne l'appelle).
- **Interrupteur :** `boot.conf` `SERIAL_CONSOLE=on` (défaut `auto`). Le fichier `tc100test/consoleshell` garde le shell root permanent comme avant.
- **Test :** 1) Démarrer sans toucher à l'UART, attendre 5 min : le message `[console-timer] ... serial console is off` apparaît sur la console, `/tmp/console-off` existe, `ps | grep getty` ne montre plus de getty sur ttySAK0. 2) Se connecter sur l'UART avant 5 min et rester connecté 10 min : pas de coupure. Se déconnecter : le getty s'arrête dans les 30 s. 3) Mettre `SERIAL_CONSOLE=on`, redémarrer : le getty est encore là après 10 min. 4) Provoquer le mode sûr (3 reboots courts) : le getty est encore là après 10 min.
- **Critères :** getty absent après 5 min sans session ; jamais de coupure pendant une session ; getty présent après 10 min en mode sûr ou avec `on` ; caméra joignable (web, ssh) dans tous les cas.

## 2026-11-05 — Réglages VM : vfs_cache_pressure 150, dirty 5/10 (`[opt-56]`)

- **Quoi :** `autorun-linux66.sh` écrit dans `/proc/sys/vm` : `vfs_cache_pressure=150`, `dirty_background_ratio=5`, `dirty_ratio=10`, par défaut.
- **Interrupteur :** `boot.conf` `VM_TUNE=0` (défaut `1`).
- **Test :** démarrer, puis `cat /proc/sys/vm/vfs_cache_pressure /proc/sys/vm/dirty_background_ratio /proc/sys/vm/dirty_ratio` donne 150, 5 et 10. Enregistrement sur SD et flux RTSP pendant 1 h. Comparer MemAvailable et le journal avec `VM_TUNE=0`.
- **Critères :** valeurs appliquées ; aucune erreur `alloc dma failed` ni OOM ; enregistrements complets ; MemAvailable égal ou meilleur.

## 2026-11-05 — Smart bitrate / GOP : interrupteur existant validé, reste l'essai du noyau item 9 (`[opt-56]`)

- **Quoi :** les clés actives sont `[0].vbr=0|1` et `[0].smart=0|1|2`, lues par `rtsp-launch.sh` et validées dans `config-transaction.sh`. Elles s'appliquent aux deux flux par défaut; `RTSP_VBR_SUB` / `RTSP_SMART_SUB` dans `rtsp.env` sont des remplacements explicites du sous-flux. Les défauts `0` figurent dans `rtspserver.conf.dist`. Les clés `brmode` / `smartmode` sont historiques et ignorées par l'encodeur libre. `rtsp.env` ne peut pas remplacer les réglages globaux.
- **Interrupteur :** `smart=0` (défaut). Pour l'essai du mode 1 : `vbr=1`, `smart=1` dans `[0]`. `RTSP_SMART_FORCE=1` seulement pour le mode 2, qui arrête l'encodeur sur cette caméra.
- **Test :** voir l'entrée `[smart-pool]` : noyau avec `ak39_venc.pool=12M`, puis `vbr=1` et `smart=1`. Sur le pool 9600K, le journal doit dire `smart mode 1 not used`.
- **Critères :** `smart mode 1 (long-term reference)` dans le journal, pas de `alloc dma failed`, serveur vivant 24 h, MemAvailable environ 2,4 Mo plus bas, débit et qualité comparés à la .24.

## 2026-11-05 — Superviseur C unique : jour/nuit + bouton reset (`[supervisord]`, items 52 / 55)

- **Quoi :** nouveau démon `tc100-supervisord` (src/supervisord, 21 Ko) qui remplace les deux boucles shell résidentes `auto-night-daemon.sh` et `button-watch.sh` (mêmes décisions, mêmes fichiers `daynight.conf` / `rtspserver.conf`, mêmes scripts appelés pour le travail : `nightmode.sh`, `wifi-rescue.sh`, `reboot-tracker.sh`, `flash-code.sh`). Un seul processus, deux jobs activés par des fichiers drapeaux `/var/run/tc100-sv.{night,button}`. Retour automatique aux boucles shell si le binaire manque, si le démon ne démarre pas, si le GPIO du bouton est refusé (ce job seulement), ou s'il meurt (relance par la surveillance du housekeeper, marqueur `/var/run/tc100-supervisord.failed` jusqu'au prochain démarrage). Pas portés : housekeeper, sound-detection, cfg-persist (restent en shell). Gain attendu estimé 0,3 à 0,5 Mo PSS (pas 1 à 1,5 Mo : trois boucles restent en shell).
- **Interrupteur :** `SUPERVISOR_IMPL=c` dans `/mnt/config/boot.conf` (défaut `sh`), puis redémarrage ou `controlscripts/auto-night-detection restart` et `controlscripts/button-actions restart`. Retour : `SUPERVISOR_IMPL=sh` et même redémarrage.
- **Test :**
  1. Mesurer le PSS avant/après (`awk '/^Pss:/ {print $2}' /proc/<pid>/smaps_rollup`) : somme des deux `sh` (auto-night-daemon, button-watch, plus leurs parents `controlscripts`) contre `tc100-supervisord`.
  2. Jour/nuit : pour chaque `DAYNIGHT_SOURCE` (luma, ae, isp, vendor), vérifier au crépuscule et à l'aube les commutations et les messages `[auto-night]` sur la console, comparer au journal `/tmp/logs/daynight.log` d'une nuit en mode shell ; `daynight=3` (manuel) doit mettre le job en pause.
  3. Bouton : appui 3 s (point d'accès de secours), 8 s (reboot), 20 s depuis la flash (retour au code intégré puis reboot) ; un appui bloqué à 0 depuis le boot ne doit rien faire.
  4. Secours : `kill -9` du démon, attendre la relance de la surveillance (60 s) ; les boucles shell doivent reprendre (`ps`, présence de `/var/run/tc100-supervisord.failed`), puis le jour/nuit et le bouton restent fonctionnels.
  5. Arrêt/démarrage d'un seul service (Services) : l'autre job continue de tourner.
- **Critères :** PSS total inférieur à celui des deux boucles shell ; mêmes commutations jour/nuit et mêmes actions de bouton qu'en mode shell ; aucun reboot parasite ; la reprise shell après arrêt brutal du démon fonctionne sans intervention ; aucune erreur noyau ni boucle de redémarrage pendant une nuit complète de soak.

## 2026-11-05 — Découverte Home Assistant en C dans tc100-mqttd (`[mqtt-disco]`, item 55)

- **Quoi :** `tc100-mqttd` publie lui-même les topics retained `<préfixe>/<composant>/<id>/<objet>/config` (52 entités avec tout activé, dont les deux suppressions à payload vide), au premier connect, à la place de `scripts/mqtt-bridge.sh` (mêmes topics et payloads, octet pour octet, validé par un test de parité sur 12 configurations). Le job `startup` est lancé avec `nodisc` pour que le script ne republie pas la découverte. Santé, manifeste et commandes restent en shell. Binaire : 17 444 → 33 832 octets (+16 Ko bruts) ; gain réel : environ 120 sous-shells de moins à chaque connexion, pas de gain de flash tant que le code shell reste (≈ 5 Ko compressés le jour où on le retire). Limite connue reproduite à l'identique : un nom contenant à la fois `"` et `\` donne un JSON invalide (bogue du `json_escape` shell, à corriger des deux côtés plus tard).
- **Interrupteur :** `MQTT_DISCOVERY_IMPL=sh|c` dans `/mnt/config/mqtt.conf` (défaut `sh` = chemin shell actuel et repli) ; `c` n'a d'effet qu'avec `MQTT_BRIDGE_IMPL=c` ; redémarrer le service MQTT.
- **Test :** 1) Avec `sh`, relever les topics retained `homeassistant/#` (par exemple `mosquitto_sub -v -R -t 'homeassistant/#'`) et les enregistrer. 2) Passer à `c`, redémarrer le service `mqtt-bridge`, relever à nouveau (ou effacer les retained puis redémarrer) et comparer : mêmes topics, mêmes payloads. 3) Vérifier dans Home Assistant que l'appareil et ses entités (capteurs, interrupteurs, boutons, mise à jour, sélecteur de profil) apparaissent sans doublon, sans entité orpheline, et que les commandes (IR, reboot, snapshot, chime) fonctionnent. 4) Changer `MQTT_HA_DISCOVERY_PREFIX` et le nom d'hôte, redémarrer, vérifier. 5) Contrôler que `/tmp/log/mqtt-bridge.log` ne contient pas d'erreur de job `startup`. 6) Repasser à `sh` et vérifier le retour à l'état initial.
- **Critères :** liste des topics et payloads identique entre `sh` et `c` ; aucune entité en double ni disparue dans HA ; commandes OK ; pas de régression de RAM du démon (PSS mesurée) ; retour à `sh` propre. Si tout passe, `c` peut devenir le défaut dans une RC suivante (le code shell n'est retiré qu'à ce moment-là).

## 2026-11-05 — Vue en direct WebRTC / WHEP, passerelle tc100-whep (`[whep]`, item 35 étapes 2 à 5)

**État actuel (2026-11-10) :** WHEP est activé par défaut depuis rc28. Les nouvelles installations et une clé absente
démarrent le service (`WHEP=1`); seule une valeur explicitement réglée à `WHEP=0` le désactive. Les essais en caméra
des RC suivantes sont consignés plus bas et dans l'archive.

- **Quoi :** nouveau service `tc100-whep` : le lecteur de l'interface web essaie WebRTC d'abord (~150 ms de latence, flux secondaire H.264 640x360 par défaut) et retombe sur la vue MP4 actuelle au moindre échec. Le démon (ICE-lite, DTLS-SRTP avec mbedTLS, SRTP de `src/whep/srtp.h`) lit le RTP de `tc100_rtsp` en RTSP sur la boucle locale ; il est joint par `/cgi-bin/whep.cgi`, derrière le même mot de passe que la page (le démon n'écoute que sur 127.0.0.1:8889 ; média en UDP 8189). Certificat ECDSA créé une fois dans `/mnt/config/whep-cert.pem` et `whep-key.pem` (0600, jamais dans le dépôt). Nécessite l'image de base reconstruite par la CI (mbedTLS avec `MBEDTLS_SSL_DTLS_SRTP`, paquet Buildroot `tc100-whep` copié dans `ext/bin`) : **point à risque, la construction musl n'a été vérifiée que par la CI**. Interop testée en CI contre aiortc (image décodée, audio, limite de spectateurs, arrêt). Limites : pas de bouton dans Réglages (clé `WHEP` ou page Services) ; iPhone (sans MediaSource) reste en images fixes.
- **Interrupteur :** `WHEP=1` est le défaut (y compris si la clé manque); mettre explicitement `WHEP=0` dans `boot.conf` ou désactiver Services > whep pour empêcher le démarrage automatique. Les changements de `WHEP_STREAM=sub|main`, `WHEP_MAX=1..2` et `WHEP_AUDIO=0|1` sont lus au démarrage du service. Retour arrière : `WHEP=0` puis `sh /mnt/controlscripts/whep stop`.
- **Test :** (1) Sur une caméra déjà migrée, retirer temporairement la ligne `WHEP=` de `boot.conf`, redémarrer normalement et confirmer que `tc100-whep` démarre et que la page Services indique le démarrage activé ; remettre ensuite `WHEP=1` via Services. (2) Vérifier `/mnt/ext/bin/tc100-whep`, le journal « ready » et la vue WebRTC dans Chrome/Firefox (Safari si possible). (3) Mesurer le délai avec une horloge devant la caméra. (4) Pendant le flux : `srtp-bench`, `top`, PSS avec 1 puis 2 spectateurs ; un 3e onglet retombe sur MP4. (5) Fermer l'onglet : « gone » dans le log ; couper le Wi-Fi du PC : arrêt après ~12 s. (6) `whep stop` : la page retombe sur MP4 sans erreur. (7) `WHEP_STREAM=main` (H.264 seulement, sinon repli MP4). (8) `WHEP_AUDIO=1` : piste audio dans les stats WebRTC. (9) Une heure avec 2 spectateurs : pas de redémarrage de `tc100_rtsp`, mémoire stable. (10) Régler explicitement `WHEP=0`, redémarrer normalement et confirmer que le service reste arrêté ; réactiver ensuite via Services. (11) Avec `WHEP=0` : RTSP, vue MP4, ONVIF et enregistrement inchangés.
- **Critères :** image en moins de 2 s, latence < 150-300 ms, CPU du démon raisonnable avec 1 spectateur sur le flux secondaire (`srtp-bench` tranche secondaire / principal), 2 spectateurs au plus puis repli MP4, aucun spectateur fantôme, clé en 0600, aucune régression avec `WHEP=0`, taille de `tc100-whep` et marge de la partition `stack` notées (STACK_MAX 2 830 336 octets).

## 2026-11-05 18:55 — Relecture testeur de la journée du 2026-11-05 (56 commits, 7038060..184e1e5)

CI et build **verts** sur `184e1e5` (le build de `43efa80` était rouge, corrigé par `184e1e5` : `<sys/time.h>` avec musl). `VERSION` est toujours **3.0.1-rc26** alors que le contenu n'a plus rien à voir avec la rc26 téléchargée hier (`e0020a5`).

- **Flash : ça tient.** Build `4bf4d69` : `stack.sqfs` 2 424 832 o (partition 2 830 336, ~396 Ko libres, même taille qu'en rc26 grâce au filtre xz ARM) ; noyau 1 783 832 / 2 097 152 ; initrd 2 012 654 / 2 097 152 (**84 Ko libres seulement**). Nouveaux binaires dans l'image : `tc100-onvifd`, `tc100-supervisord` (et `tc100-whep` à partir de `bacf1ac`).
- **Installations existantes : pas de surprise de configuration.** `install_config` ne copie une `.dist` que si le fichier manque ; les nouvelles clés absentes prennent la valeur par défaut du code (ex. `BOOT_SOUND` : 0 dans `autorun` si la clé manque, donc pas de son au démarrage sur nos caméras ; `MQTT_BRIDGE_IMPL=c` seulement pour une nouvelle installation).
- **Changements de comportement pour TOUS, sans mesure sur caméra** (à tester dans la prochaine RC) :
  - `cf4960b` : `RTSP_PACING_US=100` **par défaut** dans `rtsp-launch.sh` (« sans effet sur la latence » n'a pas été mesuré) ;
  - `8d4041d` : console série coupée après 5 min (`SERIAL_CONSOLE=auto`), `VM_TUNE=1` ;
  - `9623e94` / `df4a5a5` : `dosfsck -a` avant le montage, `S39 stop` ferme l'enregistreur et remonte en lecture seule (devrait régler le « not properly unmounted » de la .24) ;
  - `2dcea97` : `NET_LAN_ONLY` réappliqué au web et au RTSP, `httpfront` borné, expiration des clients RTSP inactifs (risque : Frigate en TCP inactif ?).
- « Smart mode validated » (`bce1c91`) = l'interrupteur `vbr`/`smart` est validé par `config-transaction.sh`, **pas** un essai sur caméra : le mode smart reste à tester avec le noyau `venc_pool` 12M (`88cc819`).
- Liste `a-faire-implementeur.md` : 37 points cochés, 21 ouverts.
- **Demande** : publier ce contenu en **rc27** (pas sous « rc26 »). Plan de test proposé, sur la .11 seule : (1) installation + boot-guard + SD propre ; (2) une nuit avec `RTSP_PACING_US=100` (images sautées, pertes de ping, latence du direct) ; (3) Frigate et HA inchangés (NET_LAN_ONLY, expiration RTSP) ; (4) `tc100-onvifd` et `tc100-supervisord` un par un (off par défaut) ; (5) WebRTC/WHEP en dernier.

## 2026-11-05 — Ligne d'état native dans httpfront (`[httpfront-native]`, item 55)

- **Quoi :** `httpfront` répond lui-même à `GET /cgi-bin/statusline.cgi` (même URL, même JSON, mêmes caches `/tmp/state_*`), sans lancer httpd ni sh. Uniquement avec un login Basic correct ; le filtre LAN et le verrouillage restent avant. Tout ce qu'il ne peut pas reproduire exactement (fichier `/tmp/csrf_token` absent, antislash dans une valeur, nombre inattendu) part vers le CGI comme avant. Binaire httpfront : 8,7 Ko → 21 Ko (+6,5 Ko compressé ; nouveau code compilé en Thumb). Sous qemu : 7 ms contre 93 ms pour le CGI. Pas de gain de flash tant que le CGI reste en repli.
- **Interrupteur :** `HTTPFRONT_NATIVE=0` dans `/mnt/config/boot.conf` (défaut 0, lu au démarrage de httpfront : redémarrer le serveur web ou la caméra). Pour revenir en arrière : remettre 0.
- **Test :** mettre `HTTPFRONT_NATIVE=1`, redémarrer, ouvrir l'interface (la première interrogation passe par le CGI qui crée le jeton CSRF). Comparer `curl -u root:… http://cam/cgi-bin/statusline.cgi` avec le CGI (`sh /mnt/www/cgi-bin/statusline.cgi`) : mêmes clés, même ordre, valeurs identiques (hors `sd_used_kb` qui bouge). Vérifier : 401 sans mot de passe, pas de JSON avec un mauvais mot de passe, connexion refusée depuis un réseau non autorisé, `sd_*` corrects avec la carte, `wifi_qual`, `sound_db` ; temps (`curl -w %{time_total}`) natif vs CGI sur 20 requêtes ; les POST (action.cgi) marchent avec le jeton CSRF reçu ; `top` : httpfront seul, pas de httpd/sh à chaque interrogation.
- **Critères :** JSON identique au CGI sur la caméra ; temps par requête divisé par au moins 5 ; aucune régression des pages (barre d'état, jauge Wi-Fi, carte SD, mise à jour disponible) pendant 24 h. Si tout est bon, `HTTPFRONT_NATIVE=1` par défaut.

## 2026-11-05 — Corrections pour la rc28 d'après la rc27 sur la .11 (`[rc28-fixes]`, R2 à R7)

- **Quoi :**
  - **R2** : plus de `RTSP_PACING_US=100` par défaut dans `rtsp-launch.sh` (revert de `cf4960b`) : avec `HZ=100`, `usleep(100)` dort 10 ms dans la boucle principale après chaque paquet UDP.
  - **R3** : `tests/check-libc-data-imports.sh` lit les `imports.txt` des programmes liés à la libc factice (tc100_rtsp, mqttd, onvifd, supervisord) après la compilation ARM, en CI locale et dans le build GitHub : refuse toute variable libc importée (`stderr`, `optarg`, `environ`…). Vérifié : il signale l'ancien `tc100-onvifd` (`stderr`), passe sur les binaires actuels.
  - **R4** : la vue en direct WebRTC exige une vraie image (`videoWidth > 0`) dans les 8 s, et le gel se mesure au nombre d'images décodées (`getVideoPlaybackQuality`) quand le navigateur le donne : avant, la seule piste audio déclenchait « playing » et faisait avancer `currentTime` → direct noir avec le son, sans repli MP4.
  - **R5** : `restart` (arrêt puis démarrage) ajouté aux 15 scripts de service qui l'ignoraient en silence (auto-night-detection, black-white, front-led, ftp-server, ir-cut, ir-led, mdns, motion-detection, night-mode, privacy, red-led, ssh-server, telegram-bot, telnet-server, whep). Effets concrets : un nouveau jeton Telegram est pris tout de suite (`system.sh` appelle `telegram-bot restart`), le service-watchdog et memory-guard relancent vraiment ces services. Test : tout script de service doit accepter `restart`.
  - **R6** : `controlscripts/onvif` annonce la cadence réelle (`[0] fps` si 10/12/15/20/25, sinon 15 ; la même pour les deux flux) au lieu de la plafonner à 15, et 1280x720 quand le flux principal est en 720p (`[0] mainres=720` et `main_scale` du noyau).
  - **R7** : l'import JSON ne lance plus un sous-shell `urldecode` pour les valeurs sans caractère encodé (la plupart : `1`, `auto`, `25`…) ; non mesuré sur caméra.
- **Interrupteur :** aucun (corrections) ; `RTSP_PACING_US=<µs>` dans `rtsp.env` reste possible à la main.
- **Test :** (R2) VLC en **UDP** sur la .11 (`rtsp://…/video0_unicast`, option RTSP over UDP) : flux fluide, pas d'images perdues côté `tc100_rtsp` (`cap` normal dans le log). (R4) `WHEP=1`, direct WebRTC dans Chrome : image en < 2 s ; puis simuler l'absence de vidéo (`WHEP_STREAM=main` avec un principal en H.265 est refusé en 415 → repli MP4) ; le cas « son sans image » n'est reproductible qu'avec l'ancien binaire. (R5) Services : `restart` de mdns et de telegram-bot (`ps` : nouveau PID) ; changer le jeton Telegram dans Réglages : le bot répond sans redémarrage. (R6) Client ONVIF (ONVIF Device Manager ou Frigate) avec `ONVIF_IMPL=c` : profils à 25 img/s quand `[0] fps=25`, 1280x720 en 720p. (R7) Import JSON d'une sauvegarde complète : durée comparée aux 20-25 s de la rc27, `cap` pendant l'import.
- **Critères :** UDP fluide ; jamais de direct noir avec le son ; `restart` relance chaque service ; cadence ONVIF = cadence du flux ; import plus rapide qu'en rc27.

## 2026-11-05 — Audit câblage front/back, corrections et code mort (`[wiring-57]`, item 57)

- **Quoi :** nouveau test statique `tests/test_wiring_e2e.py` (tous les appels des pages vers les CGI : fichier, commande, paramètres lus, CSRF ; table d'export ; CGI sans appelant). Corrections : le bouton « Test haut-parleur » du PTT envoie maintenant le jeton CSRF en POST (avant, `action.cgi` le refusait en silence) ; le bouton mort « Étape 1 : copier le système » de la carte « Installer en flash » est retiré (textes 3.0 traduits) ; l'export de configuration inclut maintenant `WHEP_STREAM`, `SUPERVISOR_IMPL` et `SERIAL_CONSOLE` (perdus avant : type non reconnu comme chaîne), ainsi que sous-flux, audio RTSP, parole bidirectionnelle, fps au repos, politique ONVIF et détection de mouvement ; 15 fonctions shell sans appelant supprimées. Restent listés sans suppression : ~150 clés de `fr.js` qui semblent mortes (2.x), quelques outils de débogage documentés.
- **Interrupteur :** aucun (revert des commits `[wiring-57]`).
- **Test :** (1) Page principale, PTT : « Test » du haut-parleur → le son sort. (2) Réglages → Mise à jour et sauvegarde → « Installer en flash » : texte 3.0 en français, seul « Installer en flash et redémarrer » (ne pas lancer). (3) Export JSON : présence de `boot.whep_stream`, `boot.supervisor_impl`, `boot.serial_console`, `video.substream`, `video.idle_fps`, `audio.rtsp_audio`, `audio.two_way`, `services.motion_detection`. (4) Réimport de ce JSON : « applied » sans erreur. (5) Parcourir Réglages, Matériel, Services, Journaux, Enregistrements : aucune erreur CSRF ni 404.
- **Critères :** son du test haut-parleur ; export complet et réimport sans erreur ; plus de bouton « Étape 1 » ; aucun « CSRF token missing » ni « unknown_command ».

## 2026-11-05 — Tout le codé activé par défaut pour la rc28 (`[rc28-defaults]`, consigne du propriétaire)

- **Quoi :** consigne du propriétaire (« active tous les items codés que nous incluront dans la prochaine RC ») : nouvelles valeurs par défaut dans les `.dist` (nouvelles installations) **et** une migration unique `scripts/migrate-rc28-defaults.sh` (lancée par `autorun` avant la lecture de `boot.conf`, marqueur `config/.migrated-rc28-defaults`) pour les caméras déjà installées : chaque clé absente ou encore à l'ancienne valeur par défaut prend la nouvelle ; une valeur choisie par quelqu'un reste ; un choix fait après la migration n'est plus touché.
  - `boot.conf` : `SUPERVISOR_IMPL=c`, `WHEP=1`, `HTTPFRONT_NATIVE=1`, `NET_GUARD_SOFT=1`, `WEB_LOCKOUT=1`, `MDNS_SERVICES=1`, `MDNS_INFO=1`, `REC_KEEP_EVENTS=1`, `SD_AUTO_REPAIR=1`, `WIFI_QUALITY=1`, `WIFI_ROAM=1` ;
  - `mqtt.conf` : `MQTT_BRIDGE_IMPL=c`, `MQTT_DISCOVERY_IMPL=c` ; `onvif.conf` : `ONVIF_IMPL=c` (le service ONVIF lui-même reste à activer comme avant) ;
  - `tc100_rtsp` (défauts posés par `rtsp-launch.sh`, `rtsp.env` peut dire 0) : `RTSP_ALSA_DIRECT=1`, `RTSP_AUDIO_HPF=1`, `RTSP_AUDIO_AGC=1`, `RTSP_AUDIO_DUCK=1`, `RTSP_ABR=1`, `RTSP_MD_ENC=1`.
  - **Non activés (préférences ou situations, pas des remplacements)** : `PRIVACY_SCREEN` (image noire), `BOOT_STEALTH`, `WIFI_AIM`, `IDLE_FPS`, `ISP_TUNE`, `NOTIFY_BURST` (envoi d'images hors de la maison : choix de l'utilisateur), `TAMPER_DETECT` / `ALARM_DETECT`, `MEM_GUARD_ENABLE` ; le mode smart (`vbr` / `smart`) attend le noyau de #9 (sans lui il ne fait rien).
  - **Risques connus à surveiller en priorité** : `RTSP_ABR=1` appelle `ak_venc_set_br` de la bibliothèque du fabricant, dont la signature n'a jamais été vérifiée (#18) : au moindre signe (flux qui s'arrête, débit figé, plantage de `tc100_rtsp`), `RTSP_ABR=0` dans `rtsp.env`. `RTSP_MD_ENC=1` voit peu en CBR (il s'ajoute à la grille de luminance, ne la remplace pas). Traitement audio (passe-haut, niveau, coupure pendant le haut-parleur) : jamais écouté sur caméra.
- Dans le même lot : `httpfront` ne compilait plus avec le gcc 15 du runner GitHub (Ubuntu 26.04 : boucle de `mulu` reconnue comme une multiplication 64 bits → `__aeabi_lmul` de libgcc, absent) : `udiv`/`mulu` en code ARM avec une barrière ; la CI GitHub compile maintenant les programmes autonomes avec le compilateur du runner.
- **Interrupteur :** chaque clé garde le sien (mettre l'ancienne valeur ; `rtsp.env` : `=0`) ; supprimer `config/.migrated-rc28-defaults` ne fait que relancer la migration (elle ne revient pas en arrière).
- **Test :** après la mise à jour en rc28 sur une caméra déjà installée : `cat /mnt/config/.migrated-rc28-defaults` existe ; `grep -E 'SUPERVISOR_IMPL|WHEP=|HTTPFRONT_NATIVE|WEB_LOCKOUT|MDNS_|REC_KEEP|SD_AUTO|WIFI_QUALITY|WIFI_ROAM|NET_GUARD_SOFT' /mnt/config/boot.conf` ; `ps` : `tc100-supervisord`, `tc100-mqttd`, `tc100-whep`, pas d'`arecord` ; log de `tc100_rtsp` : « microphone read directly », « processing: high-pass on… », ABR et « motion from the encoder frame sizes: on ». Puis une nuit complète (le bilan habituel : redémarrages, images sautées, RAM, jour/nuit, Frigate, HA, enregistrement SD).
- **Critères :** aucune régression par rapport à la rc27 de la .11 ; si une fonction pose problème, la couper par sa clé et le noter ici (elle repassera désactivée par défaut).

## 2026-11-05 — Superviseur C : détection de son en troisième job (`[supervisord-2]`, item 52)

- **Quoi :** `tc100-supervisord` (25,8 Ko) prend en charge la boucle résidente `run_daemon` de `controlscripts/sound-detection` comme troisième job (`/var/run/tc100-sv.sound`). Mêmes entrées et appels que le shell : `sound_detection.conf` (relu à chaque tour), `/var/run/sound_level` (+ `.threshold`), `mqtt-bridge.sh publish event|babyphone/state|alarm/state` et `snapshot-event`, `notify.sh`, états VOX/alarme, `REC_WHEN=motion`, journal RAM. Différence voulue : un appel de script synchrone (publication MQTT) est tué après 30 s, pour qu'un broker bloqué ne gèle pas le jour/nuit et le bouton. Retour automatique au shell comme pour les deux autres jobs. **Pas portés** : l'ordonnanceur du housekeeper (le redémarreur reste un shell de toute façon, ses jobs web/net/sd sont des fonctions shell, et tout mettre dans un seul démon ferait un point de défaillance unique pour les chiens de garde) et `cfg-persist` (écriture flash via `flashw` : laissé tel quel par prudence). Gain estimé 140 à 190 Ko PSS avec la détection de son active, à mesurer.
- **Interrupteur :** `SUPERVISOR_IMPL=sh` dans `boot.conf` (défaut `c` depuis la rc28), puis redémarrer les services `sound-detection`, `auto-night-detection`, `button-actions` ; `kill -9` du démon = retour au shell.
- **Test :** (1) détection de son active : `/var/run/tc100-sv.sound` existe, `/var/run/sound-detection.pid` = pid de `tc100-supervisord`, `/tmp/sound-detection.state` se met à jour. (2) Faire du bruit : événement MQTT `sound`, notification, ligne dans `/tmp/log/sound-detection.log` ; `VOX_MODE=1` : `babyphone/state` ON puis OFF ; `ALARM_DETECT=1` : `alarm/state` après 3 s de bruit continu ; `REC_WHEN=motion` : enregistrement. (3) PSS du démon à 3 jobs contre les trois `sh`. (4) `kill -9` du démon : les trois boucles shell reprennent (`/var/run/tc100-supervisord.failed`). (5) Broker MQTT coupé : jour/nuit et bouton restent réactifs.
- **Critères :** événements son identiques au shell ; pas de retard du bouton ni du jour/nuit pendant une publication bloquée ; PSS inférieure à la somme des shells ; retour au shell vérifié ; aucune écriture flash ajoutée.

## 2026-11-05 — `rwconf` libre, `getflag` / `getimage` supprimés (`[rwconf-53]`, item 53)

- **Quoi :** `bin/rwconf` (binaire uClibc 2.x, 31 Ko) est remplacé par `src/rwconf/rwconf.c` (4,9 Ko), compilé par la CI vers `bin/rwconf` avant `build-stack.sh` ; même comportement (`FICHIER r|w SECTION CLÉ [VALEUR]`, `" "` = niveau supérieur, plusieurs paires/triplets, réécriture triée), vérifié contre le source d'origine (domaine public, gardé dans `tests/rwconf-original/`) sur 15 fichiers x 29 formes d'appel + 400 cas aléatoires. `bin/getflag` et `bin/getimage` (mémoire partagée du serveur 2.x, rien d'équivalent dans `tc100_rtsp`) sont supprimés avec leurs appels morts (detection-monitor, mqtt-bridge, capability-check). Pour un build local, lancer `make -C src/rwconf` avant `v3/build-stack.sh`.
- **Interrupteur :** aucun ; retour arrière = revert (anciens binaires dans l'historique git).
- **Test :** sur la caméra, `/mnt/bin/rwconf /mnt/config/rtspserver.conf r " " PORT 0 codec 0 bps` affiche les valeurs du fichier ; changer débit, orientation et texte OSD dans la page (fichier réécrit trié, valeurs conservées) ; redémarrer : `tc100_rtsp` relancé avec les mêmes arguments, ONVIF lit résolution/codec, détection de mouvement et MQTT suivent `/tmp/rec_control` ; `ls /mnt/bin` sans getflag/getimage, aucune erreur « not found » dans les journaux.
- **Critères :** `rwconf` tourne sous le chargeur uClibc ; réglages écrits et relus à l'identique après redémarrage (RTSP, ONVIF, volume, flip, mdsens) ; MQTT/détection inchangés.

## 2026-11-05 — `dash.cgi` natif dans httpfront (`[httpfront-native-2]`, item 55)

- **Quoi :** deuxième route native : `GET /cgi-bin/dash.cgi` (le tableau de bord le sonde toutes les 5 s) répondu par `httpfront` lui-même (`src/httpfront/dash.h`), JSON identique octet pour octet au CGI (`up`, `load`, `cpu`, `mem`, `iface`, `net`, `wifi`, `rtsp_clients`, `sd_health`), seulement avec un login valide, après le filtre LAN et le blocage ; tout ce qu'il ne peut pas reproduire exactement passe au CGI. Les autres sondages ne valaient pas la place (page Matériel seulement, ou commandes à lancer). httpfront : +3,8 Ko bruts (+1,8 Ko xz), 25 052 octets ; compile aussi avec le gcc 15 du runner.
- **Interrupteur :** le même que la ligne d'état : `HTTPFRONT_NATIVE` (`1` par défaut depuis la rc28 ; `0` = les CGI).
- **Test :** tableau de bord ouvert 5 min : tuiles CPU, RAM, réseau, Wi-Fi, spectateurs RTSP, état SD mises à jour toutes les 5 s ; `curl -u root:… http://<cam>/cgi-bin/dash.cgi` avec `HTTPFRONT_NATIVE=1` puis `0` : mêmes clés, même ordre ; VLC ouvert : `rtsp_clients` passe à 1 puis revient à 0 ; sans login : 401 ; temps de réponse natif contre CGI (20 appels).
- **Critères :** JSON identique au CGI ; tableau de bord sans erreur ; `rtsp_clients` suit les connexions ; 401 sans login ; réponse nettement plus rapide.

## 2026-11-05 — Piste audio AAC-LC dans les enregistrements SD (`[rec-aac]`, item 11 ; activée par défaut pour la rc28)

- **Quoi :** encodeur AAC-LC écrit pour le projet, en virgule fixe (`src/tc100rtsp/aacenc.c`, 8 kHz mono, ~24 kbit/s, sans libm ni flottant ; seules les tables de Huffman de la norme viennent de FFmpeg, LGPL-2.1+), pour la piste son des MP4 de `rec.c` (`mp4a` + `esds`) : les navigateurs jouent le son des enregistrements. Le flux RTSP reste en G.711 (Frigate inchangé) ; la vue directe MP4 n'a pas de son, inchangée. Coûts : `tc100_rtsp` +12,3 Ko ; ~6 M instructions par seconde d'audio (≈ 2 % du CPU, estimé sous qemu, pas mesuré sur caméra) ; ~32 Ko de bss, résidents seulement quand il tourne. Limites : pas de modèle psychoacoustique ni de blocs courts (pré-écho sur les attaques), dernier fragment (< 180 ms) perdu en fin de fichier, jamais écouté sur une vraie voix.
- **Interrupteur :** `RTSP_REC_AAC=0` dans `/mnt/config/rtsp.env` (défaut `1` depuis la rc28, posé par `rtsp-launch.sh`) ; `RTSP_REC_AAC_KBPS=8..48` ; redémarrer `tc100_rtsp`. Le statut du recorder dit `audio=aac` ou `audio=alaw`.
- **Test :** `REC_LOCAL=1`, `REC_AUDIO=1` ; enregistrer 2 minutes avec voix, claquement de mains, musique ; lire dans Chrome, Firefox (page Enregistrements) et VLC ; `ffprobe` : `aac, 8000 Hz, mono`, `ffmpeg -i fichier -f null -` sans erreur ; synchro image/son au claquement (< 100 ms) ; une heure : fichiers suivants sans coupure ; CPU de `tc100_rtsp` avec et sans (`top`) pendant un enregistrement H.265 principal ; RTSP toujours en G.711.
- **Critères :** son audible dans les navigateurs et VLC, sans craquement ni dérive ; synchro < 100 ms ; surcoût CPU < 3 % ; voix jugée acceptable à 24 kbit/s (sinon essayer 32) ; aucune erreur `rec:` dans le journal.

## 2026-11-05 — tc100-logfwd et libnetacl.so compilés par la CI (`[ci-uclibc]`, item 51)

- **Quoi :** `bin/tc100-logfwd` (renvoi syslog) et `lib/libnetacl.so` (filtre réseau local de telnet/FTP/telnet de secours) ne sont plus des binaires précompilés avec la chaîne Anyka : la CI les compile depuis `src/logfwd` et `src/netacl` avec le compilateur glibc et une libc de substitution (`libc.so.0`, `libdl.so.0`) faite à l'édition de liens, comme `tc100-mqttd`. `tc100-logfwd.c` n'utilise plus `getopt`/`stderr` (aucune variable libc). `libnetacl` est liée à libgcc en statique (sinon `htonl` importait `__bswapsi2`, lié à un stub vide : défaut trouvé par le test). Tailles 9 272 et 5 060 octets (avant 9 968 et 6 472). **Testé sous qemu-arm avec une glibc présentée sous les noms uClibc, pas contre la vraie uClibc** : à confirmer sur caméra.
- **Interrupteur :** remettre les anciens binaires (`git show <commit précédent>:bin/tc100-logfwd`, idem `lib/libnetacl.so`) ; pour le filtre seul `NET_LAN_ONLY=0` ; pour le renvoi, vider l'hôte syslog (retour à `syslogd -R`).
- **Test :** `readelf -d /mnt/lib/libnetacl.so` : NEEDED libdl.so.0 et libc.so.0 ; syslog distant réglé : `logger -p user.err test` arrive une fois, 5 messages identiques → une ligne « repeated N times », `tc100-logfwd` vivant après un redémarrage de syslogd ; telnet et FTP depuis le LAN : OK ; depuis une adresse hors liste : refusé, `/var/run/netacl.telnet` compte les refus ; aucune « symbol lookup error » ni « can't resolve symbol » dans les journaux.
- **Critères :** journaux distants filtrés comme avant ; telnet/FTP accessibles depuis le LAN, refusés hors liste, jamais bloqués depuis 127.0.0.1 ; aucune erreur de chargement. Si un symbole manque : remettre les binaires précompilés.

## 2026-11-06 09:00-09:15 — rc29, .11 et .24 en conditions réelles : campagne du testeur seul (sans action du propriétaire)

**Surface réseau** — `passed`, identique sur les deux : TCP 22 (dropbear), 80 (httpfront), 554 (RTSP), 8081 (ONVIF), 8889 (WHEP, `127.0.0.1` seulement) ; UDP 3702 (WS-Discovery), 5004, 5353 (mDNS), 8189 (ICE). Ni telnet ni FTP. 401 sans mot de passe sur le web.
- **Alerte « identifiants par défaut actifs »** (Réglages) **justifiée** sur les deux caméras : le compte web / RTSP est encore `root` / `pass` (`default_password_active=1`). À changer par le propriétaire (page Réglages, puis le mot de passe RTSP dans Frigate). Rien changé par le testeur.
- Fuseau `UTC0` sur les deux (horloge de l'OSD et des journaux en UTC) : à passer en `CET-1CEST,M3.5.0,M10.5.0/3` si le propriétaire veut l'heure de Paris.

**Web** — `passed` : les 9 pages et 17 points d'accès lus par l'interface en 200 sur les deux ; navigation dans toutes les pages de l'interface (Chrome 157, .11) sans erreur JavaScript. Lents : `scripts.cgi?cmd=allstates` 7,3-7,7 s (page Services ; `scripts.cgi` 3,6-11,3 s), `state.cgi?cmd=fullconfig` 3,1-5,6 s, `dashinfo` / `isp_tune` / `md_zones_info` 1,2-1,5 s. `logs.html` ouverte seule (hors de `index.html`) : `showlog` en 403 (pas de jeton CSRF) ; normal dans l'interface. Une réponse 503 de `httpfront` vue sur `scripts.cgi` pendant la visite (le navigateur et la VM du testeur partagent une IP : `PERIP 8` atteint avec le direct MP4 ouvert).
- **T8 refait (R11)** — `passed` : 12 connexions muettes par caméra : 8 fermées par la caméra en moins de 4 s, 4 refusées en 503 (`PERIP`), aucune ne reste ouverte. R11 est réglé en rc29.

**Flux** — `passed` : sous-flux h264 640x360 25 img/s + PCMA ; son du micro présent (moyenne -45,6 / -42,2 dB, crêtes -27 / -32 dB, pièces calmes) ; direct MP4 (`live.cgi`, repli du WebRTC) : 331 images en 15 s sur la .11 (~22 img/s, de jour) et 128 sur la .24 (~8,5 img/s, basse lumière) : **R13 réglé** (le repli suit la cadence de capture ; les 1,8 img/s de la nuit du 05/11 venaient de la nuit).

**MQTT** — `passed` : `health` répond sur les deux (`command/result` published, `health`, `isp/state`), `availability` online retenu, 49 configurations de découverte. Racines : `.11` publie sous `ipcamera2/` (nom d'hôte, `MQTT_TOPIC_ROOT` laissé à la valeur par défaut `tc100/camera`), `.24` sous `tc100/cam2/` (valeur réglée). Le même `uniq_id` `<nœud>_night_mode` sert à un `binary_sensor` et à un `switch` (même chose dans le pont shell ; Home Assistant l'accepte car les domaines diffèrent).
- Incident du testeur : une commande `tail` sur `/tmp/mqtt-bridge.pub` (une FIFO) lancée par erreur est restée bloquée 1 h sur la .11 et pouvait y lire les messages du pont ; tuée à 09:05. Aucun effet visible ensuite (le pont répond).

**ONVIF événements (T13, partie mécanique)** — `passed` sur les deux : `GetEventProperties` (MotionAlarm, CellMotionDetector/Motion), `CreatePullPointSubscription` (adresse `subscription?id=1`, fin à +60 s), `PullMessages` : 2 messages d'état initial (`State=false`, `IsMotion=false`), `Unsubscribe` OK. Le mouvement réel reste à voir avec Home Assistant (P5). Détection de mouvement de la caméra éteinte sur les deux (`mdenabled=0`, avant comme après la rc29 : Frigate détecte).

**Export / import de la configuration (R7)** — `.24` : export 12,9 s (18 sections) ; import de ce même export 14,8 s (`applied 143`, `changed_files 4` : clés manquantes ajoutées et fichiers réordonnés, aucune valeur changée) puis 20,5 s (`changed_files 0`). Toujours lent (R7 ouvert).

**T4 (mise à jour refusée)** — `passed` sur la .24 : 200 Ko de données au hasard → « not a 3.0 update package » en 0,8 s ; rc29 avec un octet inversé dans `stack.sqfs` → « the package is damaged (md5) » en 10,3 s ; sans jeton CSRF → `csrf_invalid`. Après chaque essai : état `idle`, aucun service arrêté, rien en `/tmp/update66*`, MemAvailable 22,8 Mo. Non testé : écriture flash refusée en cours d'installation (risqué).

**`failed`, corrigé — la mise à jour éteint aussi l'enregistrement local et la détection de mouvement** : la .24 avait `REC_LOCAL=1` (copie du 06:56 UTC) et l'a perdu à la mise à jour rc29 : `update66.sh` lance `recording stop`, qui écrit `REC_LOCAL=0` pour de bon (même famille que le jour / nuit, R15) ; `motion-detection stop` écrit de même `mdenabled=0`. `REC_LOCAL=1` remis sur la .24. **Corrigé en `8845166`** : verbe `halt` pour `recording` et `motion-detection`, et les trois services « réglage » arrêtés par `halt` dans `update66.sh`, `install66.sh`, `update.cgi`. Tests.

**T6 (emplacements de configuration)** — lecture seule : `.11` cfga 190 / cfgb 191, `.24` cfga 114 / cfgb 113, sommes MD5 présentes, dernier enregistrement `ok`. Le retour en arrière n'a pas été provoqué (risqué).
- `reboot-history.log` : le redémarrage de la mise à jour web est classé « unknown (no heartbeat recorded yet) » sur les deux (pas d'intention notée par `update66.sh` ? et, sans carte SD, le battement de cœur reste en RAM). La .24 a trois « UNEXPECTED » les 05/11 08:45, 14:27 et 06/11 06:27 UTC (heures où le propriétaire a coupé / flashé la caméra, à confirmer).

**Non testé (demande le propriétaire ou un risque)** : T5 (3 démarrages ratés), T7 (même IP), T10 / T11 / T12 (chaque fonction coupe Frigate pendant le redémarrage du flux et demande une condition réelle : mouvement, coupure NTP, réseau saturé), P1-P10.

## 2026-11-06 — `[rc30]` R19, R14, R18, R20-U1/U3 (implémenteur) : à vérifier en rc30

- **R19, garde mémoire** : `controlscripts/memory-guard` appelle `halt` (et non `stop`) pour `recording`,
  `motion-detection`, `auto-night-detection`. Interrupteur : `MEM_GUARD_ENABLE=0` (défaut). Test (facultatif, ssh) :
  `MEM_GUARD_ENABLE=1`, `MEM_GUARD_CRITICAL_KB` au-dessus de MemAvailable, attendre une minute.
  Critère : `/tmp/log/memory-guard.log` dit « stopped … », `mdenabled` et `REC_LOCAL` inchangés, `daynight=2` gardé.
- **R14, réparation de la carte SD** : `scripts/sd-diag.sh repair` (bouton « Auto-repair », et au démarrage avec
  `SD_AUTO_REPAIR=1` après une coupure). Interrupteur : `SD_AUTO_REPAIR=0` dans `boot.conf`. Tests :
  (1) carte de démarrage (avec `wifitest/`) dans la caméra, « Auto-repair » → `refused`, pas de `fsck.fat` dans `ps`,
  rien écrit sur la carte ; (2) la carte 64 Go formatée de la .24 après une coupure de courant → pas d'OOM dans
  `dmesg` ; soit `fsck_repaired`, soit `dirty-not-checked` (message sur Réglages → Enregistrement) et la carte montée
  quand même ; (3) l'enregistrement sur mouvement reprend.
  Critère : jamais de « Killed process … fsck.fat » ni de `tc100_rtsp` tué ; carte montée après chaque cas sauf (1).
- **R18, cause du redémarrage** : intention notée par `update66.sh` (« web update to <version> »), `install66.sh` et
  `update.cgi`. Pas d'interrupteur (journal seulement). Test : la mise à jour web rc29 → rc30.
  Critère : `/mnt/config/log/reboot-history.log` dit « intended: web update to 3.0.1-rc30 » (et non « unknown »).
- **R20** : plus d'entrée « Éteindre » dans le menu (la commande `shutdown` reste pour ssh) ; `LIGHTWEIGHT_MODE` n'est
  plus écrit par « Save Hardening ». Critère : menu Outils sans « Éteindre » ; « Enregistrer le durcissement » ne
  change pas `LIGHTWEIGHT_MODE` de `boot.conf`.

## 2026-11-06 — rc30 lancée par l'implémenteur (consigne du propriétaire : « lancer une nouvelle RC30 »)

- Contenu : rc29 + `7e3b1c8` / `8845166` (halt à la mise à jour), `bf6d15c` (syslog, image de base reconstruite) +
  `7da484e` (R19, R14, R18, R20-U1/U3) ; CI GitHub verte sur `7da484e` ; aucun réglage par défaut modifié.
- Archive : `tc100-3.0.1-rc30-update.tar` du run « Build Linux 6.6 » de ce commit. L'implémenteur n'a pas pu la
  télécharger (`gh` non authentifié sur son poste) : **le contrôle de l'archive** (paragraphe « Vérifier la rc30 » de
  `a-faire-implementeur.md`) et son md5 sont à faire par le testeur avant l'installation.
- Installation prévue : .11 et .24 par la mise à jour web, sans carte SD (propriétaire).
- À vérifier sur les deux caméras : `daynight=2`, `REC_LOCAL` et `mdenabled` inchangés après la mise à jour ;
  `syslogd` + `tc100-logfwd` en marche et lignes reçues par 192.168.1.23 ; `reboot-history.log` « intended: web update
  to 3.0.1-rc30 » ; WebRTC dans Chrome ; plus d'« Éteindre » dans le menu ; carte SD de la .24 (formatée) enregistrée
  sur mouvement sans OOM (entrée `[rc30]` ci-dessus).

## 2026-11-06 11:20 — rc30 : revue du code et contrôle de l'archive par le testeur — `passed`, prête à installer

- **Revue de `7da484e`** : conforme aux consignes. `memory-guard` appelle `halt` quand le script en a un ; profils
  allégés gardent `stop` (choix de l'utilisateur) avec le texte qui le dit ; `sd-diag.sh repair` : refus d'une carte de
  démarrage avant toute écriture (lecture seule), besoin mémoire de `fsck.fat` lu dans le secteur de démarrage
  (12 octets / cluster), `dirty-not-checked` sinon, `oom_score_adj` 1000, `resume` dans tous les cas, rien sur exFAT ;
  intention de redémarrage dans `update66.sh` (l. 87, avant le `cfg-persist flush` l. 90), `install66.sh`,
  `update.cgi` ; « Éteindre » retiré du menu ; `LIGHTWEIGHT_MODE` plus écrit. Vérifié sous qemu-arm sur la BusyBox de
  la rc30 : `dd | od` et l'arithmétique 64 bits du calcul (5 000 000 000 correct).
- **Archive** : run 42192948628 (`9192813`), `tc100-3.0.1-rc30-update.tar` md5 **`65e1cd7033f13ee9c3bdcda21e70e6d9`**,
  `MD5SUMS` OK (stack, noyau, initrd, VERSION 3.0.1-rc30). Dedans : `tc100-whep` avec le recollage du ClientHello,
  `whep.cgi` 12000, `update66.sh` avec la boucle `halt` et l'intention, `halt()` dans `recording`,
  `motion-detection`, `auto-night-detection`, repli syslog dans `common_functions.sh`, plus de `cmd=shutdown` dans
  `index.html`. **BusyBox de l'initrd (2026-11-06 08:21 UTC) accepte `-D` et `-f`** : `syslogd -n -D -f <conf>` reste
  en marche sous qemu-arm.
- Archive copiée sur le Mac du propriétaire : `~/Downloads/tc100-fix/xfer30/tc100-3.0.1-rc30-update.tar`.
- Après l'installation, le testeur vérifie la liste de l'entrée « rc30 lancée » ci-dessus.

## 2026-11-06 — Sons sans carte SD : « Jouer maintenant », vraie détection de la carte (`[ux-sounds]`, rc31)

- **Quoi :** le propriétaire ne trouvait pas l'envoi de sons : bloc caché sans carte SD (ses deux caméras n'en ont pas),
  carte au fond de Réglages → « Flux et audio ». Maintenant : onglet « Flux, audio et sons », carte « Sons du
  haut-parleur », envoi toujours visible ; nouveau bouton **« Jouer maintenant sans enregistrer »** (`sounds.cgi
  cmd=playnow` : le son converti par le navigateur va dans `/tmp`, est joué puis effacé ; refusé si MemAvailable <
  taille + 6 Mo) ; « Convertir et enregistrer sur la carte SD » seulement avec une carte. `sd_ok` ne prend plus le disque
  RAM de 16 Ko monté sur `/mnt/sd` sans carte pour une carte (l'envoi partait dedans et échouait).
- **Interrupteur :** aucun (revert du commit `[ux-sounds]`).
- **Test (sans carte) :** Réglages → Flux, audio et sons → Sons du haut-parleur : choisir un MP3 de 5-10 s, « Jouer
  maintenant » → le son sort du haut-parleur ; `ls /tmp/sound-now.*` vide après la lecture ; le flux RTSP ne coupe pas.
  **Avec une carte :** « Convertir et enregistrer » → le son apparaît dans la liste et se rejoue ; « Jouer maintenant »
  ne l'enregistre pas.
- **Critères :** lecture audible, rien gardé en RAM ni sur la carte avec « Jouer maintenant », pas de chute de
  MemAvailable durable, message clair sans carte.

## 2026-11-06 — Interface Pico CSS par défaut, Bulma en secours jusqu'à la rc32 (`[ux-pico]`, item 50, rc31)

- **Quoi :** décision du propriétaire après mesure (`src/webui/screenshots/bench.py`, Chromium, CPU ×4, médiane de 7) :
  feuille Pico **−31 %** (gzip 21,5 Ko contre 31,3 Ko), calcul des styles −13 à −30 %, mise en page égale ou plus
  rapide, premier affichage +10-20 ms. `index.html` charge **un seul** bundle selon `localStorage tc100_ui` :
  `css/ui.pico.min.css` (Pico 2.0.6 MIT + `css/pico-shim.css` qui dessine les classes Bulma des pages + `ui.css`) par
  défaut, `css/ui.bundle.min.css` (Bulma) si « Classique » est choisi dans Réglages → Système → Apparence. Aucune page
  modifiée. Flash : +~41 Ko (bundle Pico xz + .gz), les sources Pico sont exclues de l'image comme celles de Bulma.
- **Références `[ui-baseline]` :** `src/webui/screenshots/engines.py` (19 pages × clair/sombre × 1280/390 px × deux
  looks, erreurs JavaScript et défilement horizontal relevés) : Bulma 76/76 sans défaut ; Pico 76/76 sans défaut après
  corrections du shim (barre de navigation, bouton du thème, champ fichier caché, tableau des journaux).
- **Interrupteur :** Réglages → Système → Apparence → « Classique » (par navigateur) ; sans JavaScript : Pico.
- **Test (caméra, PC et téléphone) :** ouvrir l'interface après la mise à jour : aspect Pico, clair et sombre (bouton en
  haut à droite) ; parcourir Tableau de bord, Direct, Multi-vues, Enregistrements, chaque onglet de Réglages, Outils ;
  enregistrer un réglage par onglet ; menus déroulants et burger sur téléphone ; passer en « Classique » puis revenir.
  Noter le temps d'ouverture des pages lentes (Services, `allstates`) dans les deux looks.
- **Critères :** rien de cassé ni d'illisible en Pico ; même comportement qu'en Classique ; aucun défilement horizontal
  sur téléphone. Les défauts vont dans `pico-shim.css`. Si tout passe : la rc32 retire Bulma, `ui-modern.min.css`, le
  bundle Classique et le sélecteur (décision du propriétaire du 2026-11-06).

## 2026-11-06 — Pertes Wi-Fi : mesurer d'abord, sans aucun risque pour la liaison (`[wifi-diag]`, audit W1)

- **Pourquoi :** l'audit du 2026-11-06 (`docs/linux-port/audit-2026-11-06.md`, partie W) écarte l'économie d'énergie
  (mesurée `off`), la mise en veille USB (`CONFIG_PM` absent du noyau), le balayage en arrière-plan (aucun `bgscan`) et
  le pays. Les pings se perdent **avec 0 retransmission et 0 échec radio** : la piste est la réception (`rtl8xxxu` sur le
  pilote hôte USB du portage) ou un blocage de la caméra elle-même. Aucun réglage connu ne corrige cela sans risque :
  il faut savoir lequel des deux avant de toucher quoi que ce soit.
- **Quoi :** `scripts/wifi-diag.sh` (nouveau), **lecture seule** : ne touche ni `wlan0`, ni `wpa_supplicant`, ni le
  pilote, ni un réglage ; écrit seulement `/tmp/wifi-diag.log` (6 h max, ~0,4 Mo de RAM) ; s'arrête seul (24 h au plus).
  Une ligne par seconde : retard de la boucle (> 300 ms = la caméra a calé), paquets reçus / émis de `wlan0`, paquets
  rejetés, interruptions USB, `beacon rx` du point d'accès (toutes les 5 s), un ping au routeur (option `ping`).
- **Interrupteur :** aucun service ; `sh /mnt/scripts/wifi-diag.sh stop` l'arrête.
- **Test (testeur, ssh, une caméra) :**
  1. `sh /mnt/scripts/wifi-diag.sh run 7200 ping </dev/null >/dev/null 2>&1 &` ;
  2. en même temps, depuis le Mac (filaire si possible) : `ping -i 0.5 <ip caméra> | while read l; do echo "$(date +%s) $l"; done > ping-cam.txt`
     et, pour comparer, un ping du routeur depuis le Mac à la même cadence ;
  3. après 2 h : `sh /mnt/scripts/wifi-diag.sh summary` ; copier `/tmp/wifi-diag.log` et `ping-cam.txt`.
- **Lecture :** pings perdus avec « camera stalled » → blocage CPU / ordonnanceur (piste R2 : `tc100_rtsp`, tâches du
  housekeeper) ; avec « receive frozen » et « USB interrupts frozen » → hôte USB (patch 0003) ; avec réception figée mais
  USB vivante → `rtl8xxxu` (réception) ; rien de tout cela et le ping du Mac au routeur perd aussi → routeur / canal
  (le propriétaire choisit 1, 6 ou 11) ; le ping du Mac à la caméra propre mais celui de la caméra perdu → artefact de
  mesure (2 pings à `-W 1`) et l'item Wi-Fi peut se fermer.
- **Critères :** le script tourne 2 h sans incident (MemAvailable stable, aucune coupure de la liaison), le résumé
  classe les pertes ; le résultat va sous cette entrée et décide de la piste suivante (audit W2-W5).

## 2026-11-06 12:35 — revue du testeur : `[ux-sounds]`, `[ux-pico]`, `[wifi-diag]`, audit 2026-11-06

- Revus, CI verte (`8bc9f62`). `sounds.cgi?cmd=playnow` : jeton CSRF et limite de débit comme les autres commandes,
  corps PCM pair ≤ 30 s, refus 507 sous MemAvailable + 6 Mo, refus 429 si le haut-parleur joue, fichier `/tmp`
  effacé : OK. `wifi-diag.sh` : lecture seule, `/tmp`, borné, rien au démarrage : OK. Pico : flash `stack.sqfs`
  2 457 600 → 2 502 656 octets (+44 Ko), partition 2 830 336 : marge 320 Ko, OK.
- **Attention, deux archives portent le nom « 3.0.1-rc30 »** : `VERSION` n'a pas changé après la rc30, donc la build de
  `8bc9f62` sort aussi `tc100-3.0.1-rc30-update.tar` (md5 `b026001b1c84c42ffcd70300747ae584`, avec Pico, sons,
  wifi-diag), différente de la rc30 contrôlée (`9192813`, md5 `65e1cd7033f13ee9c3bdcda21e70e6d9`). **À installer en
  rc30 : celle de md5 `65e1cd70`** (sur le Mac du propriétaire, `xfer30/`). Implémenteur : passer `VERSION` à
  `3.0.1-rc31-dev` (ou rc31) dès qu'un commit de code suit une RC publiée, pour qu'une archive ne soit jamais
  confondue avec une RC testée.

## 2026-11-06 — Place en flash : plus de jq (`[flash-nojq]`, audit S1, décision du propriétaire, rc31)

- **Quoi :** `jq` (+ `libjq`, oniguruma ; ~110-240 Ko estimés de l'image) retiré de la flash et de l'image de base
  (`BR2_PACKAGE_JQ` retiré, l'image de base est reconstruite par la CI). Ses deux seuls utilisateurs lisent le JSON avec
  `scripts/jsonflat.awk` : `telegram-bot-daemon.sh` (`tg_parse`, plus d'`eval` d'un texte venu du réseau) et
  `update-check.sh` (`.tag_name`).
- **Interrupteur :** aucun (revert du commit `[flash-nojq]`) ; le paquet SD n'a plus jq non plus.
- **Test :** (1) bot Telegram configuré (jeton saisi par le propriétaire) : envoyer `/help` puis une commande, la
  réponse arrive ; un chat inconnu reçoit « Unauthorized chat » ; (2) `UPDATE_CHECK=1` : `sh /mnt/scripts/update-check.sh`
  puis `cat /tmp/update_status.json` : `latest_version` = l'étiquette de la dernière release GitHub ; (3) dans le journal
  de la CI : la ligne `stack.sqfs: N bytes` comparée à celle de la rc30 (gain mesuré à noter ici).
- **Critères :** Telegram et la vérification de version répondent comme en rc30 ; `ls /mnt/ext/bin/jq` absent.

## 2026-11-06 — Place en flash : plus de monvifd dans la flash (`[flash-nomonvifd]`, audit S3, décision du propriétaire, rc31)

- **Quoi :** `bin/monvifd` (démon ONVIF fermé de la 2.x, 233 Ko, ~70 Ko de l'image) sort de l'image flash ; il reste
  dans le paquet SD. `controlscripts/onvif` : `ONVIF_IMPL` vaut `c` par défaut ; le démon libre `tc100-onvifd` démarre
  sauf si `monvifd` est demandé **et** présent (mode SD) ; une ancienne config `ONVIF_IMPL=monvifd` sur une caméra en
  flash obtient donc ONVIF par `tc100-onvifd` (rien ne démarre seulement si aucun des deux n'est là : ligne dans le
  journal de l'onvif). Le bloc des versions (`common_functions.sh`) ne liste plus `monvifd` (il aurait affiché
  « missing »).
- **Interrupteur :** aucun en flash (retour : paquet SD, ou revert du commit `[flash-nomonvifd]`).
- **Test (propriétaire : il utilise ONVIF) :** après la mise à jour, Services → ONVIF « en marche » ; `ps | grep onvif`
  montre `tc100-onvifd` ; découverte et flux depuis Frigate / Home Assistant / l'enregistreur ; événements de mouvement
  (T13) ; une caméra dont `onvif.conf` dit encore `ONVIF_IMPL=monvifd` démarre aussi `tc100-onvifd`.
- **Critères :** ONVIF identique à la rc30 (découverte, profils, flux, audio retour, événements) ; `/mnt/bin/monvifd`
  absent de la flash.

## 2026-11-06 — Place en flash : `.gz` seulement pour les gros fichiers web (`[flash-gz]`, audit S1b, décision du propriétaire, rc31)

- **Quoi :** `v3/build-stack.sh` ne fait plus un `.gz` de chaque page, style et script > 1 Ko (~287 Ko de l'image : un
  `.gz` ne se recompresse pas dans le squashfs xz), seulement de `GZ_WWW` : `scripts/index.bundle.min.js`,
  `settings.html`, `css/ui.pico.min.css`, `scripts/view_records.bundle.min.js`, `i18n/fr.js`. Busybox `httpd` envoie le
  `.gz` aux navigateurs qui l'acceptent et le fichier en clair sinon : une page sans `.gz` marche pareil, un peu plus
  lourde sur le réseau. Le style « Classique » (Bulma, retiré en rc32) part en clair.
- **Interrupteur :** aucun (revert du commit `[flash-gz]`).
- **Test :** dans le navigateur (outils de développement, onglet Réseau) : les cinq fichiers arrivent avec
  `Content-Encoding: gzip` ; les autres pages (Journaux, Matériel, Diagnostics, Enregistrements, Multi-vues, assistant)
  s'ouvrent normalement ; `curl -sI -H 'Accept-Encoding: gzip' http://<cam>/scripts/index.bundle.min.js` (avec le mot de
  passe) dit `Content-Encoding: gzip`. Noter la ligne `stack.sqfs: N bytes` de la CI.
- **Critères :** toutes les pages s'affichent comme en rc30 ; pas de 404 ; temps d'ouverture du tableau de bord inchangé.

## 2026-11-06 — Place en flash : sons intégrés en A-law (`[flash-alaw]`, audit S7, décision du propriétaire, rc31)

- **Quoi :** à la construction, `scripts/pcm2alaw.py` (outil de build, hors image) convertit les sons intégrés
  (`alert`, `chime`, `siren`, `startup`, `startup_2`, `startup_complete`) en G.711 A-law (`/mnt/sounds/NAME.alaw`, un
  octet par échantillon : moitié de la taille ; la sirène ne se compressait pas). Codec vérifié identique à la
  référence sur les 65 536 valeurs. Les lecteurs prennent les deux formats : `speaker-play.sh` (`aplay -f A_LAW`,
  greffon `alaw` de l'alsa-lib de la base), `sound_path`, la liste de `sounds.cgi` (durée juste), le son de démarrage,
  le test audio. Les sons personnalisés de la carte restent en 16 bits ; les tonalités de test aussi.
- **Interrupteur :** aucun (revert du commit `[flash-alaw]`).
- **Test (caméra, haut-parleur) :** son de démarrage au boot ; Réglages → Flux, audio et sons : « Jouer » sur chaque son
  intégré (carillon, alerte, sirène, démarrage), durées affichées comme avant (sirène 2,0 s, carillon 1,05 s) ; boutons
  carillon / sirène du tableau de bord et commande MQTT `sound` ; un son personnalisé sur la carte remplace toujours le
  son intégré du même nom.
- **Critères :** chaque son audible, sans grésillement nouveau par rapport à la rc30 ; aucune erreur `aplay` dans le
  journal.

## 2026-11-06 — Place en flash : JavaScript et HTML minifiés à la construction (`[flash-minify]`, audit S5, décision du propriétaire, rc31)

- **Quoi :** `v3/build-stack.sh` passe `src/webui/minify.mjs` (esbuild 0.21.5, épinglé) sur sa copie de `www/`, avant
  les `.gz` : chaque `*.js` et les blocs `<script>` / `<style>` en ligne des pages ; **pas** le balisage (le
  dictionnaire français en dépend), **pas** les CGI ni le shell (lisibles en ssh, décision du propriétaire). Noms
  globaux gardés (attributs `onclick`). Mesure sur PC : 661 Ko → 469 Ko de fichiers web en clair ; Playwright sur l'arbre
  minifié : 19 pages × clair/sombre × 1280/390 px, **0 erreur JavaScript**. git garde les fichiers lisibles (les tests
  et `build-index.sh` les comparent). La CI l'exige (`MINIFY_WWW=1`) ; une construction locale sans esbuild livre les
  fichiers tels quels.
- **Interrupteur :** aucun sur la caméra (revert du commit `[flash-minify]`).
- **Test :** sur les deux caméras, parcourir toutes les pages (tableau de bord, direct, multi-vues, enregistrements,
  chaque onglet de Réglages, Outils, assistant) en anglais et en français ; enregistrer un réglage par onglet ; console
  du navigateur sans erreur ; noter la ligne `stack.sqfs: N bytes` de la CI.
- **Critères :** comportement identique à la rc30 ; aucune erreur dans la console ; traductions françaises complètes.

## 2026-11-06 13:25 — revue du testeur : `[flash-*]`, D1-D7, `VERSION 3.0.1-rc31-dev`

- CI verte sur `6c13483`. `VERSION` = `3.0.1-rc31-dev` : plus de confusion possible avec la rc30 (md5 `65e1cd70`).
- `jq` retiré : plus aucun appel à `jq` dans `scripts/`, `www/cgi-bin/`, `controlscripts/`, `v3/`. `monvifd` hors de la
  flash, `tc100-onvifd` pour toutes les configurations. Sons intégrés en A-law : `sound_path`, `speaker-play.sh`
  (`aplay -f A_LAW`), le son de démarrage (`autorun-linux66.sh` l. 451, repli `.pcm`), `sounds.cgi` et le test du
  haut-parleur (`action.cgi` l. 293) cherchent `.alaw` puis `.pcm` : cohérent. Minification JS / scripts en ligne au
  build seulement, shell intact.
- **À vérifier sur caméra en rc31** (le testeur) : chaque son intégré joue et à la bonne durée (carillon, alerte,
  sirène, démarrage, depuis le Direct et par MQTT) ; toutes les pages sans erreur JavaScript après minification ;
  ONVIF ; Telegram et vérification de mise à jour sans `jq` (si activés).
- **Ne pas fusionner la PR Dependabot « Bump esbuild from 0.21.5 to 0.28.1 »** : sa CI échoue et `minify.mjs` épingle
  esbuild 0.21.5 exprès (le même minifieur que pour `index.bundle.min.js`).
- GitHub signale 1 vulnérabilité « moderate » (Dependabot n° 1, illisible avec les droits du testeur), très probablement
  esbuild ≤ 0.24.2 (GHSA-67mh-4wv8-2f99 : le **serveur de développement** d'esbuild accepte des requêtes d'autres
  sites). Le projet n'utilise esbuild qu'au build (bundle et minification), jamais `serve` : rien sur les caméras.
  Implémenteur : si on veut fermer l'alerte, monter esbuild en 0.25.x (première version corrigée) en vérifiant que la
  sortie minifiée reste identique ou que les tests Playwright (19 pages) restent à 0 erreur — pas 0.28 d'un coup.

## 2026-11-06 — rc31 lancée par l'implémenteur (consigne du propriétaire : « lance une RC31 avec tout ce qu'on a fait »)

- **Contenu :** rc30 (`9192813`, md5 `65e1cd70`) + `[ux-pico]` (interface Pico par défaut, Classique en secours),
  `[ux-sounds]` (« Jouer maintenant » sans carte), `[wifi-diag]`, `[flash-nojq]`, `[flash-nomonvifd]`, `[flash-gz]`,
  `[flash-alaw]`, `[flash-minify]`, README / guides / captures, corrections D1-D10 ; CI verte sur `6c13483` (même
  code) ; revus par le testeur (entrées 12:35 et 13:25). Aucun réglage par défaut modifié sauf l'aspect de l'interface.
- **Archive :** `tc100-3.0.1-rc31-update.tar` du run « Build Linux 6.6 » de ce commit. Le testeur la contrôle (md5,
  `MD5SUMS`, contenu : pas de `ext/bin/jq` ni de `bin/monvifd`, `sounds/*.alaw`, `css/ui.pico.min.css(.gz)`, JS
  minifié) et note **la ligne `stack.sqfs: N bytes`** (rc30 + Pico : 2 502 656 octets) pour mesurer le gain réel.
- **Installation prévue :** .11 et .24 par la mise à jour web, sans carte SD (propriétaire).
- **À vérifier sur les deux caméras :** réglages conservés (`daynight`, `REC_LOCAL`, `mdenabled`, MQTT, ONVIF) ;
  interface Pico en clair et sombre, PC et téléphone, toutes les pages sans erreur dans la console ; « Classique » puis
  retour à Pico ; sons intégrés (carillon, alerte, sirène, démarrage) et « Jouer maintenant » ; ONVIF depuis
  Frigate / HA / l'enregistreur avec `tc100-onvifd` ; Telegram et vérification de version si activés ;
  `reboot-history.log` « intended: web update to 3.0.1-rc31 » ; puis `wifi-diag.sh` 2 h (entrée `[wifi-diag]`).
- **Ne pas fusionner** la PR Dependabot esbuild 0.28.1 (voir l'entrée 13:25).

## 2026-11-06 — Historique git réécrit (décision du propriétaire) : **re-cloner avant de pousser**

- **Quoi :** tout l'historique a été réécrit (`git filter-repo`) pour que le propriétaire n'apparaisse plus que sous
  l'identité `morgeek <morgeek@users.noreply.github.com>` (anciennes identités d'auteur et chemin `/Users/...` d'une autre
  machine remplacés). `main`, la branche Dependabot et les étiquettes `v1.6.1` / `v3.1` ont été poussés en force.
  **Tous les hashes de commit ont changé** ; ceux cités dans les messages de commit et dans les fichiers suivis (docs,
  commentaires) ont été remis à jour d'après la table ancien → nouveau ; les md5 d'archives (`65e1cd70`, `b026001b`…)
  ne changent pas.
- **Testeur et autres agents :** `git fetch && git reset --hard origin/main` (ou un nouveau clone) **avant tout
  commit** : pousser depuis un ancien clone ramènerait l'ancien historique. Les commits à identité « Claude » restent
  tels quels.
- **rc31 :** le contenu ne change pas, mais le commit de la rc31 a un nouveau hash ; l'archive à contrôler est celle
  du run « Build Linux 6.6 » du `main` réécrit (dernier commit `[docs] Commit hashes quoted in the docs follow the
  second history rewrite` ou le suivant), pas celle de l'ancien `3b094b1`.
- **GitHub :** les 17 pull requests gardent des références en lecture seule vers les anciens commits ; seul le
  support GitHub peut les purger.

## 2026-11-06 14:55 — rc31 sur la .11 (IPCAM2), installée par le testeur (mise à jour web) : `passed` avec 2 défauts, dont un corrigé

- **Archive** : run 42225296777 (`main` réécrit, `c947479`), `tc100-3.0.1-rc31-update.tar` md5
  **`5d9e83af4a57913435c6d8647a8ab813`**, `MD5SUMS` OK. Dedans : plus de `ext/bin/jq` ni de `bin/monvifd`,
  `sounds/*.alaw`, `css/ui.pico.min.css(.gz)`, JS minifié, les correctifs de la rc30 (`halt`, intention, syslog, WHEP).
  **`stack.sqfs` 2 146 304 octets** (rc30 + Pico : 2 502 656, soit −356 Ko ; partition 2 830 336). Le chargement de
  Chrome (`file_upload`) a refusé le fichier (dossier non partagé avec la session) : envoi par `update.cgi`
  (`cmd=upload` puis `cmd=install`, mêmes requêtes que la page).
- **Mise à jour depuis la rc29** : la .11 était encore en **rc29** (la rc30 n'y a jamais été installée), dont
  `update66.sh` a encore le défaut `stop` (R15). Le testeur a superposé en RAM le `update66.sh` de la rc31 avant
  l'installation : **`daynight=2` conservé**, `mdenabled`, `REC_LOCAL`, `rtsp.env`, `autostart/*`, `WIFI_COUNTRY`,
  `SYSLOG_HOST` conservés. Installation : 13:38:21 → retour 13:40:24 UTC (~2 min). `reboot-history.log` : **« requested
  at 2026-11-06 13:38:34: web update to 3.0.1-rc31 »** (R18 OK). **Attention .24** : une mise à jour depuis la rc29
  sans cette précaution remettrait `daynight=3` et `REC_LOCAL=0` (à rétablir après, ou même superposition).
- **Base** — `passed` : 3.0.1-rc31, `flashroot=1`, MemAvailable 22,7 Mo, CmaFree 5,8 Mo ; démons présents, plus de
  `monvifd` ; superviseur C 3 jobs ; file 1024 Ko, pacing 0, micro direct ; `dropped 0` ; aucune OOM ; Wi-Fi -15 dBm.
- **RTSP** hevc 1080p25 + PCMA, h264 360p25 + PCMA ; **ONVIF** (`tc100-onvifd`) FW rc31, WS-Discovery, `FrameRateLimit`
  25, événements PullPoint ; **MQTT** `ipcamera2/` online, `health` répond, 49 entités ; **WebRTC** Chrome 157 :
  640x360 à 19,9 img/s de jour ; **sons** : `sounds.cgi` liste les 6 clips intégrés (`.alaw`), `sd:false`
  (vraie détection de carte) — **non joués** (bruit dans la pièce du propriétaire : à faire avec lui).
- **Interface Pico** — `passed` : les 9 pages chargées dans `index.html` sans erreur JavaScript, sans défilement
  horizontal ; Réglages → Système → Apparence : `bulma` puis retour `pico` (le `<link>` change, `localStorage
  tc100_ui`). Page Services : > 14 s avant la liste (R17).
- **`failed` — après la mise à jour, Chrome garde l'ancienne interface** : `index.html` en cache (servi sans
  `Cache-Control`, seulement `Last-Modified` / `ETag` : Chrome le réutilise sans revalider pendant des heures). La page
  restait en Bulma de la rc29 jusqu'à un rechargement forcé. R22.
- **`failed`, corrigé — syslog distant mort depuis la rc28** : `syslogd` démarre bien en rc31 (`-D -f` acceptés), mais
  `tc100-logfwd` (construit en CI avec la libc de remplacement depuis la rc28) **meurt à sa première ligne** :
  « can't resolve symbol '__isoc99_sscanf' » (et `__ctype_b_loc` d'`isdigit`), absents de l'uClibc 0.9.33 de la
  caméra ; `syslog-forward` affiché « Arrêté », rien n'arrive sur 192.168.1.23. (Le relancement « réussi » du testeur
  le matin du 06/11 en rc29 mourait de même à la première ligne : rectification.) `libnetacl.so` importait de même
  `__isoc23_strtol`. **Corrigé en `e5a1c05`** (analyse à la main, `tests/check-libc-data-imports.sh` refuse
  désormais ces noms, test `StandInLibcNoGlibcOnlyCalls`). Binaire reconstruit superposé en RAM sur la .11 :
  vivant après tout le fichier (`-b`, 349 lignes) et les nouvelles lignes ; `syslog-forward` « En marche ».
- `wifi-diag.sh run 7200 ping` lancé à 13:58 UTC sur la .11 (lecture seule, `/tmp`) : bilan à 15:58.
- Superpositions en RAM sur la .11 (perdues au redémarrage) : `/mnt/bin/tc100-logfwd` (correctif `e5a1c05`).

## 2026-11-06 — Revue externe : mise à jour sans carte SD confirmée, `flashw -r` fiable, exception U-Boot écrite (`[review-1106]`, rc32)

- **Quoi (décisions du propriétaire) :** (1) sans carte SD, la mise à jour web ne peut pas sauvegarder la flash avant
  de l'écrire : `update.cgi` refuse (`"error":"nobackup"`) et la page demande « Installer sans sauvegarde ? » ; seulement
  après « OK » elle relance avec `&nobackup=1` (`UPDATE66_NOBACKUP=1`), et `update66.sh` le vérifie **avant** d'arrêter
  quoi que ce soit. Avec une carte, rien ne change (sauvegarde `flashw -b` à chaque écriture, refus d'écrire si elle
  échoue). (2) AGENTS.md : la seule écriture de l'environnement U-Boot est celle du hook de première installation
  (`stock-hook.sh`, sauvegarde vérifiée, restauration en cas d'échec) ; un test vérifie qu'aucun autre code ne l'écrit.
  (3) `flashw -r PARTITION FICHIER` ne dit plus « OK » après un dump raté : code 7 si `dd` échoue, si le fichier n'a pas
  la taille de la partition ou si la sortie n'est pas inscriptible.
- **Interrupteur :** aucun (revert du commit `[review-1106]`).
- **Test (prochaine mise à jour web, sans carte) :** « Installer » → la question « No SD card… Install without a
  backup? » (en français : « Pas de carte SD… ») ; « Annuler » → rien n'est arrêté ni écrit, la page reste utilisable ;
  « OK » → l'installation se fait comme avant. Avec une carte : pas de question, `tc100-3/backup/` reçoit les trois
  partitions. En ssh : `sh /mnt/v3/linux66-sd/flashw -r cfga /tmp/cfga.bin; echo $?` → 0 et un fichier de 36 864 octets.
- **Critères :** pas d'écriture sans sauvegarde ni confirmation ; mise à jour inchangée par ailleurs.

## 2026-11-06 15:15 — rc31 sur la .24 (IPCAM1), installée par le testeur (mise à jour web) : `passed`, 2 défauts carte SD

- Même archive (md5 `5d9e83af…`), même précaution qu'à la .11 (`update66.sh` de la rc31 superposé en RAM sur la rc29).
  14:05:36 → retour 14:07:50 UTC. Conservés : `daynight=2`, `mdenabled=0`, **`REC_LOCAL=1`, `REC_WHEN=motion`**,
  `rtsp.env`, `autostart/*`, `WIFI_COUNTRY=FR`, `SYSLOG_HOST=192.168.1.23`. `reboot-history.log` : « requested at
  2026-11-06 14:05:50: web update to 3.0.1-rc31 ».
- **Base** : rc31, `flashroot=1`, MemAvailable 21,0 Mo, démons présents (plus de `monvifd`), superviseur 3 jobs,
  `dropped 0`. RTSP hevc 1080p25 / h264 360p25 + PCMA, ONVIF FW rc31 25 img/s, MQTT `tc100/cam2` online + `health`.
  **Aucune OOM au démarrage** : `sd-diag.sh repair` a refusé la carte (« Boot or install card (wifitest at its root):
  not repaired » : R14 OK).
- **`failed` — la carte de démarrage est restée montée en écriture** : malgré le refus, `/dev/mmcblk0p1` était monté
  `rw` sur `/mnt/sd` (options de `rec-storage.sh _mount_card` : `shortname=mixed`) et `STAT … rec 1`. Hypothèse : deux
  `_mount_card` en même temps au démarrage (enregistreur, contrôle de la carte chaque minute, `sd-diag repair` à
  +60 s) : l'un monte, l'autre voit `_mounted` vrai et rend 0 (donc carte « acceptée »), le premier trouve `wifitest`
  mais son `umount` échoue (occupé) et la carte reste montée. Aucun fichier écrit (dernier fichier de `DCIM/` :
  06:26 UTC, d'avant). Démontée par `rec-storage.sh eject` à 14:13 ; plus remontée en 2 min ; `rec 0`. R25.
- **`failed` — un vieux paquet rc28 « prêt à installer »** tant que la carte était montée : `update.cgi` met son
  dossier de travail sur la carte quand `/mnt/sd` est en vfat (`/mnt/sd/tc100-3/update`, l. 9), et ce dossier
  contient une rc28 envoyée le 05/11 avec son `ok` : `cmd=status` répondait `"state":"staged","staged":"3.0.1-rc28"`
  (un clic sur Installer aurait remis la rc28). Redevenu `idle` après le démontage. R26.
- Syslog : `tc100-logfwd` corrigé (`e5a1c05`) superposé en RAM, « En marche ».
- Superpositions en RAM sur la .24 (perdues au redémarrage) : `/mnt/bin/tc100-logfwd`.

## 2026-11-06 — Fuseau horaire dans l'assistant (F3/F9) et cadence en basse lumière réglable (F2) (`[tz-lowlight]`, rc32)

- **Quoi :** (1) **Assistant** : nouvelle étape « Fuseau horaire » (après Langue et Wi-Fi) ; le navigateur propose son fuseau
  (`Intl.DateTimeFormat().resolvedOptions().timeZone`), une liste d'une centaine de villes (Europe, Amérique, Asie,
  Australie/Pacifique, Afrique, avec l'heure d'été) permet de le changer ; l'assistant envoie la chaîne POSIX
  (`Europe/Paris` → `CET-1CEST,M3.5.0,M10.5.0/3`), validée côté caméra, et l'écrit dans `config/timezone.conf` (le même
  fichier et la même première ligne que Réglages → Fuseau horaire et horloge ; aucune autre clé). Sans `Intl` ou sans
  la table (`scripts/tzlist.js` absent) : UTC0 est présélectionné avec un avertissement, ou l'étape est omise et rien
  n'est envoyé. Un nouveau passage dans l'assistant présélectionne le fuseau en vigueur. Le service vidéo redémarre
  3 s après (sauf si le changement de mot de passe le fait déjà) pour que l'horloge d'image, les noms de fichiers et les
  journaux changent. **Réglages** : la même liste au-dessus du champ texte (la chaîne TZ reste la seule valeur ;
  une valeur existante hors liste s'affiche « Autre » et est conservée) ; `settz` refuse maintenant une chaîne qui
  n'est pas du POSIX TZ. (2) **Cadence en faible lumière** : `daynight.conf` `LOWLIGHT_FPS_VALUE` = 10 (défaut, comme
  avant), 15 ou 20, dans Réglages → Jour/nuit (« Low-light frame rate » / « Cadence en faible lumière ») ;
  `rtsp-launch.sh` l'exporte en `RTSP_LOWLIGHT_FPS_VALUE`, `tc100_rtsp` l'utilise à la place du 10 codé en dur. La limite
  d'exposition suit la durée d'image : 2812 lignes à 10 img/s (inchangé), 1874 à 15, 1406 à 20 (`2812 × 10 / cadence`).
  Une cadence supérieure à celle du flux est ignorée. Entre dans l'export/import JSON (`daynight.lowlight_fps_value`).
- **Interrupteur :** (1) ne pas toucher à l'étape (le choix reste modifiable dans Réglages) ; revert du commit
  `[tz-lowlight]` sinon. (2) `LOWLIGHT_FPS` (interrupteur existant) coupe tout ; `LOWLIGHT_FPS_VALUE=10` redonne le
  comportement d'avant.
- **Test :** (1) Relancer l'assistant (Réglages → Système) depuis un navigateur en heure de Paris : l'étape propose
  `Europe/Paris` ; terminer ; `cat /mnt/config/timezone.conf` → `CET-1CEST,M3.5.0,M10.5.0/3` ; après le redémarrage de la
  vidéo, l'horloge d'image, `date` et les noms des fichiers `DCIM/` sont à l'heure locale ; pas de redémarrage de la
  caméra. Refaire avec un autre fuseau de la liste (p. ex. `Asia/Kolkata` → `<+0530>-5:30`) et en français (groupes
  « Amérique », « Asie »). Réglages → Fuseau horaire et horloge : la liste montre la ville actuelle ; choisir une ville met
  la chaîne TZ à jour dans le champ ; saisir à la main `<+0330>-3:30` → la liste montre Asia/Tehran ; saisir `FOO` ou
  `Europe/Paris` → « Invalid time zone … not saved », fichier inchangé. (2) Réglages → Jour/nuit : choisir 15 img/s,
  enregistrer (la vidéo redémarre) ; dans une pièce sombre `grep "low light" /tmp/logs/tc100_rtsp.log` →
  « low light: 15 fps, exposure up to 1874 lines when the gain is high » puis « total gain …x, sensor 15 fps, exposure
  up to 1874 lines » ; vérifier la fluidité à 15 img/s dans Frigate. 10 : identique à la rc31 (« exposure up to 2812
  lines »). 20 avec un flux réglé à 15 : aucune bascule (ignoré).
- **Critères :** (1) `timezone.conf` écrit une seule fois, première ligne valide ; assistant et Réglages montrent la même
  ville ; chaîne invalide refusée sans rien écrire. (2) 10 identique à avant ; 15 et 20 appliqués avec la limite
  d'exposition annoncée ; pas d'oops, pas de redémarrage. Si l'image à 15 ou 20 est trop sombre ou trop bruitée dans la
  pièce visée, le noter ici : la limite d'exposition est la valeur à ajuster.

## 2026-11-06 15:45 — revue du testeur : `[cleanup]` (`73d2bea`) et `[review-1106]` (`0aac5ee`)

- CI verte. `update.cgi` refuse maintenant d'installer sans carte SD tant que la page n'a pas demandé
  « installer sans sauvegarde ? » (`&nobackup=1` → `UPDATE66_NOBACKUP=1`, vérifié par `update66.sh` avant tout arrêt) :
  cohérent. Les deux caméras n'ont pas de carte utilisable : pour la rc32, le testeur installera avec cette
  confirmation (consigne du propriétaire : « flash la rc32 sur la .11 »), comme le ferait la page.
- `AGENTS.md` : le seul code autorisé à écrire l'environnement U-Boot est le crochet de première installation
  (`stock-hook.sh`), avec un test qui l'impose ; aucune mise à jour web n'y touche : conforme à la règle du propriétaire.
- `flashw -r` échoue maintenant sur une lecture ratée (avant : 0 toujours) ; le chemin d'écriture n'a pas changé.
- Entrées closes de `test-queue.md` déplacées dans `test-queue-archive.md` (les entrées du testeur du 06/11 sont
  restées ici).

## 2026-11-06 — Fil d'envoi dans `tc100_rtsp` : `RTSP_SENDER_THREAD` (R16 / H1, `[sender-thread]`, rc32)

**État au 2026-11-10 :** le défaut du lanceur firmware reste `RTSP_SENDER_THREAD=0` tant que R16 n'est pas qualifié.
Le rapport rc36/rc35 confirme le flux sur les deux caméras avec un client; les critères quatre clients et mélange
TCP/UDP ci-dessous restent à tester. Le binaire lancé seul utilise aussi le chemin inline si la variable manque.
Attention : le tag `v3.0.0` (08/11) a été construit pendant les deux jours où le défaut valait `1` (`21494b9`, retour à
`0` dans `91c408b` le 10/11) ; une caméra en 3.0.0 sans `RTSP_SENDER_THREAD` dans `rtsp.env` fait donc tourner le fil.

**Relecture du code (Fable, lecture seule, 2026-11-12) :** ni interblocage, ni tampon libéré pendant un envoi, ni
mélange des trames TCP. Points à observer pendant l'essai :
- **UDP :** la socket UDP est bloquante et l'envoi se fait sous `cl_mu` (avec l'attente `RTSP_PACING_US` si elle est
  réglée) ; un client UDP lent freine donc encore la capture, fil actif ou non. Le fil n'apporte un gain qu'aux
  clients TCP. Dans l'heure à deux clients, comparer `snd_wait` et `cap` avec et sans le client UDP : une hausse nette
  de `snd_wait` avec UDP confirme ce point (pas une régression : l'envoi inline fait de même).
- **Arrêt :** à l'arrêt, le fil vide d'abord la file (jusqu'à 48 images) ; un redémarrage du serveur RTSP peut prendre
  un peu plus longtemps avec `=1`. Noter la durée d'un `rtsp-h26x restart`.
- **Corrigé (`[sender-gap]`) :** une copie d'image impossible faute de mémoire marquait tout de suite les clients ; un IDR
  plus ancien encore en file pouvait alors effacer la marque et laisser partir les images P suivantes (image corrompue
  jusqu'à l'IDR suivant). La perte est maintenant portée par la prochaine image de la file, comme un rejet de file
  pleine. Aucun effet avec `=0`. Sans test caméra dédié (il faut un échec de `malloc`) : couvert par le critère
  « image correcte » ci-dessous.
- **Non traité :** le fil lit SPS/PPS sans verrou pendant que la boucle les réécrit à chaque IDR ; sans effet tant que
  les paramètres ne changent pas en marche (à vérifier si le débit adaptatif ou le smart mode les modifient).

- **Quoi :** la boucle de capture ne fait plus l'envoi aux clients (environ 2,4 ms par client et par image, cause de R16 :
  chaque client en plus retirait des images à la capture). Avec `RTSP_SENDER_THREAD=1`, elle copie chaque image encodée
  dans une file bornée (48 images, 768 Ko, jamais bloquante) qu'un fil d'envoi vide (`bcast` vers chaque client). File
  pleine : l'image non-IDR la plus ancienne est jetée, et le fil d'envoi fait attendre le prochain IDR à tous les clients
  du flux (`dropped` augmente, comme pour un client TCP congestionné). Un seul mutex (`cl_mu`) protège la table des
  clients ; seule la boucle principale ouvre ou ferme une connexion. Un client qui arrive reçoit le cache GOP comme
  avant, sans doublon ni désordre (`skip_seq`). Le fil est désactivé par défaut jusqu'au verdict R16. Ligne `STAT` :
  quatre champs en plus à la fin, `snd_q` (file la plus profonde sur 5 s), `snd_qdrop` (images jetées de la file),
  `snd_thr_ms` (temps occupé du fil), `snd_wait` (ms d'attente du mutex par la boucle principale).
- **Interrupteur :** mettre `RTSP_SENDER_THREAD=1` dans `/mnt/config/rtsp.env` pour l'essai; absent ou `0` garde
  l'envoi dans la boucle. Redémarrer le serveur RTSP (`rtsp-launch.sh`); la valeur est lue au
  démarrage ; message `tc100_rtsp: sender thread on (queue 48 frames, 768 KB)` dans `/tmp/logs/tc100_rtsp.log`.
- **Test (de jour, comme le T2 de 08:35) :** `RTSP_SENDER_THREAD=1`, redémarrage du serveur RTSP ; 4 clients en même
  temps, `ffmpeg -rtsp_transport tcp -i rtsp://<ip>:554/ -c copy -f null -` (mêmes clients que le T2) pendant 5 minutes ;
  noter les img/s de chacun et les lignes `STAT` (`cap`, `dropped`, `snd_q`, `snd_qdrop`, `snd_thr_ms`, `snd_wait`).
  Refaire avec 1 puis 2 clients. Ensuite 1 h avec 2 clients dont un en UDP et un que l'on coupe et relance chaque minute ;
  relever `MemAvailable` au début et à la fin.
- **Critères :** 4 clients >= 23 img/s chacun (rc29 : ~18) ; `dropped` inchangé par rapport à l'envoi dans la boucle
  (pas de hausse à débit stable) ; pas de plantage ni de client resté bloqué en 1 h ; `MemAvailable` stable ; `snd_wait`
  faible (quelques ms par 5 s) ; image correcte (pas de macroblocs) chez un client qui arrive en cours de route et après
  un client coupé. Si un critère échoue, garder `RTSP_SENDER_THREAD=0`; si tous passent, proposer `1` comme nouveau défaut dans un changement séparé.

## 2026-11-06 — rc32 : aspect Classique (Bulma) et `monvifd` retirés ; cache du navigateur (R22) (`[rc32-remove]`, `[r22-cache]`)

- **Quoi (décisions du propriétaire du 06/11, rc31 validée sur les deux caméras) :** l'interface n'a plus qu'une
  feuille, `css/ui.pico.min.css` (Pico + shim + `ui.css`) ; le sélecteur Réglages → Système → Apparence, le bundle
  Bulma, `ui-modern.min.css` et l'outillage de purge sont retirés. Le shim dessine en plus les champs « libellé à côté »
  (Réglages → Réseau : DNS, adresse fixe) et les boutons radio (DHCP / fixe), seules classes Bulma encore utilisées qu'il
  ne couvrait pas (test `test_the_shim_draws_every_bulma_class_the_pages_use`). `bin/monvifd` est retiré du dépôt :
  `tc100-onvifd` est le seul démon ONVIF (une valeur `ONVIF_IMPL` autre que `c` est ignorée). **R22** : la BusyBox de
  la base n'envoie plus `Last-Modified` (image de base reconstruite) : le navigateur revalide chaque page par `ETag`
  (réponse 304) au lieu de garder l'ancienne interface après une mise à jour.
- **Interrupteur :** aucun (revert des commits).
- **Test (après la mise à jour rc32, sans rechargement forcé) :** ouvrir l'interface comme d'habitude : nouvelle version
  affichée (numéro en haut) ; `curl -sI -u root:… http://<cam>/index.html` : `ETag` présent, plus de `Last-Modified` ;
  un second chargement donne des 304 (outils de développement) ; Réglages → Réseau : libellés à gauche des champs DNS,
  boutons DHCP / fixe alignés ; plus de carte « Apparence » ; ONVIF découvert et diffusé par `tc100-onvifd`.
- **Critères :** l'interface à jour apparaît sans rechargement forcé ; pages identiques à la rc31 sauf la carte
  Apparence retirée ; ONVIF comme en rc31.

## 2026-11-06 — rc32 : R24, R25, R26, diagnostic MQTT, restes 2.x (`[rc32-fixes]`)

- **R24** — Multi-vues : quand la vidéo fluide (`live.cgi`, un seul lecteur) est déjà ouverte ailleurs, la cellule
  revient aux images fixes sans avertissement dans la console (info-bulle sur le bouton).
- **R25** — carte refusée restée montée en écriture : `rec-storage.sh` monte maintenant la carte **en lecture seule**
  d'abord, ne la passe en écriture qu'après avoir vérifié l'absence de fichiers de démarrage, un seul appel à la fois
  (verrou `/tmp/rec-storage.lock`, repris après 60 s) ; une carte de démarrage déjà montée n'est plus prise pour une
  carte utilisable ; si son démontage échoue, elle est remontée en lecture seule et c'est écrit dans
  `/tmp/sd-diag.status`.
- **R26** — paquet périmé sur la carte : un paquet n'est « prêt » que s'il a été envoyé et vérifié depuis le démarrage
  (repère en RAM `/tmp/update66.staged`) ; installer une version plus ancienne que l'actuelle demande une confirmation
  (« This package is older… »).
- **Diagnostic MQTT** : clients RTSP (TCP **et** UDP) et images sautées lus dans `/var/run/tc100_rtsp.stat` (le fichier
  de l'ancien serveur 2.x n'existe pas : jusqu'ici clients TCP seulement et 0 image sautée).
- **Restes 2.x** : branches `/etc/jffs2` mortes retirées (`wifi-rescue.sh`, `reboot-tracker.sh`, `mqtt-bridge.sh`,
  `action.d/network.sh` ; rien n'écrit `/tmp/tc100-storage` en 3.0) ; `clip_thumb.cgi` (ffmpeg, absent en 3.0) retiré,
  les enregistrements gardent leur vignette JPEG ; captures du README refaites (sans la carte Apparence, liste des
  processus 3.0).
- **Interrupteur :** aucun (revert du commit `[rc32-fixes]`).
- **Test :** (R25) la carte de démarrage SD de la .24 insérée : `grep /mnt/sd /proc/mounts` ne montre jamais `rw`
  (au démarrage et après « Monter la carte »), carte formatée : montée `rw`, enregistrement ; (R26) un vieux paquet
  laissé dans `tc100-3/update/` n'apparaît plus « prêt » après un redémarrage ; envoyer la rc31 sur une rc32 →
  question « older » ; (R24) Multi-vues avec le Direct ouvert dans un autre onglet : pas d'avertissement ; (MQTT)
  `diag` publie `rtsp_clients` = nombre réel (Frigate + VLC en UDP) et `rtsp_dropped`.
- **Critères :** aucune carte de démarrage montée en écriture ; aucun paquet ancien proposé sans question.

## 2026-11-06 — Noyau d'essai « minuteries haute résolution » à la demande (`[hrt-test]`, audit H4, item 13)

- **Quoi :** le workflow « Build Linux 6.6 » a une option manuelle `test_hrtimers` (exécution à la main, « Run
  workflow ») : noyau d'essai avec `CONFIG_HIGH_RES_TIMERS` et `CONFIG_NO_HZ_IDLE` (aujourd'hui tic périodique à 100 Hz :
  `usleep(100)` dort 10 ms, d'où l'abandon du pacing en R2). Les paquets de ce run portent la version
  `…-testkernel` (même chose avec l'option existante `venc_pool`) : jamais confondus avec une release. Le noyau
  normal ne change pas.
- **Interrupteur :** aucun (option du run manuel seulement).
- **Test (testeur, carte SD, rien dans la flash) :** lancer le run avec `test_hrtimers` coché ; copier `c66.img` du run
  dans `tc100test/` d'une carte SD de secours ; démarrer depuis la carte (`pack66/boot66b.sh`) ; `cat /proc/timer_list |
  grep resolution` → `1 nsecs` ; puis la nuit H.265 de `nq/` (2 h au moins) comme pour le 480 MHz ; ensuite seulement,
  avec le propriétaire, la question d'un noyau en flash.
- **Critères :** démarrage normal, résolution 1 ns, 2 h H.265 sans erreur noyau ni redémarrage ; puis R2 / H5
  (lissage du débit) pourront être repris dans le fil d'envoi (`RTSP_SENDER_THREAD`).

## 2026-11-06 — Audit de l'interface, le reste de R20 : doublons D1-D6, inutiles U2 et U4-U9 (`[ui-r20]`, rc32)

- **Quoi (décision du propriétaire : « tout faire », une seule commande par action, jamais une fonction retirée) :**
  - **D1** Réglages → Jour/nuit : les boutons Auto / Jour / Nuit et les interrupteurs Éclairage IR / Filtre IR / Noir et
    blanc ne sont plus répétés ; un lien « Ouvrir les commandes sous l'image en direct » mène au Direct, qui les garde.
    Les seuils restent. **D2** Système : la carte « LED » devient « LED au démarrage » avec une phrase (l'état pris à chaque
    démarrage ; les boutons LED bleue / rouge du Direct ne changent que le moment). **D3** Système → Maintenance : le
    bouton « Hard Reboot » (même `cmd=reboot` que Outils → Redémarrer, et pas plus « forcé ») est remplacé par une phrase ;
    le seul redémarrage est dans le menu Outils. **D4** (4 mécanismes) : aucun retiré (« Exporter l'actuel / Importer un
    fichier » des préréglages n'est **pas** un doublon de l'échange JSON : il lit les champs des formulaires dans le
    navigateur, sans `config_exchange.cgi`) ; le guide « Lequel choisir ? » les range du plus large au plus étroit
    (sauvegarde complète, échange JSON, préréglages, point de restauration), une ligne chacun, et une phrase sous les
    boutons d'export/import des préréglages renvoie à l'échange JSON. **D5** page Services : une phrase dit que, pour les
    services qui ont un réglage (recording, syslog-forward, memory-guard, whep, wifi-rescue, mqtt-bridge, telegram-bot),
    « Arrêter » éteint le réglage pour de bon et que « Démarrage » est le même interrupteur. **D6** Telegram : un lien
    d'Alertes vers le jeton / la conversation (Intégrations) et un lien d'Intégrations vers le choix des événements
    (Alertes) ; chaque lien ouvre l'onglet et met le champ en vue.
  - **U2** « Vider le cache mémoire » retiré de l'interface (la commande `clear_mem` reste côté serveur, pour un script).
  - **U4** Clés de `boot.conf` sans lecteur en 3.0 (`WEB_MODE`, `ULTRALITE_HTTP_PORT`, `UI_ULTRALITE_MODE`,
    `LIGHTWEIGHT_MODE`, `CPU_SCALER_*`, `RTSP_SERVER`, `RTSP_VENDOR_PORT`, `RTSP_LITE_*` **sauf `RTSP_LITE_TALK`** (lu par
    tc100_rtsp, onvifd et Réglages → Audio), `RTSP_PROC_*`, `RTSP_FPS_LOCK`, `FIRMWARE_IMAGE`, `STORAGE_CLEANUP_*`,
    `TAMPER_DETECTION`) : `config/boot.conf.dist` n'en contenait plus que `LIGHTWEIGHT_MODE`, retiré ; la nouvelle
    `scripts/migrate-rc32-unused-keys.sh` (appelée par `v3/autorun-linux66.sh` après `migrate-rc28-defaults.sh`, avant la
    lecture de `boot.conf`, une fois : `config/.migrated-rc32-unused-keys`) **commente** ces lignes dans `boot.conf`
    (`#[rc32: unused on 3.0] CLE=valeur`, valeur gardée) et écrit une ligne par clé dans `config/migrations.log` ; aucune
    suppression. `state.cgi` et `config_exchange.cgi` mentionnent encore `LIGHTWEIGHT_MODE` (affichage / export seulement,
    rien n'agit dessus). L'entrée `autostart/cpu-scaler` des deux caméras n'est **pas** touchée (l'autorun l'ignore ; un
    fichier, pas une clé).
  - **U5** Intégrations → MQTT : « 25+ Discovery Nodes » remplacé par le vrai nombre d'entités : nouvelle commande
    `ha_discovery_info` (lecture seule) qui lance `tc100-mqttd -D` (écrit les enregistrements de découverte sans se
    connecter ni rien publier) et compte ceux qui ont un contenu (un contenu vide ne fait que retirer une vieille
    entité) ; « -- » si on ne peut pas le savoir. **U6** Réseau → Wi-Fi → Scanner : colonne « Signal (dBm) », sans
    décimales (« -54 »). **U7** Services : l'âge de `web-server` est celui de `httpfront` (un processus `httpd` n'est plus
    que le repli). **U8** Jour/nuit : seuls les champs de la méthode de « Mesure de la lumière » choisie sont affichés
    (luminance, indice d'exposition, ou méthode d'origine ; les durées de maintien restent) ; les champs cachés restent
    dans le formulaire, enregistrés avec leurs valeurs. **U9** L'alerte « identifiants par défaut » des Réglages a le
    lien « Changer le mot de passe » (ouvre Système et met le champ « Nouveau mot de passe » en vue).
- **Interrupteur :** aucun (changements d'interface) ; la migration U4 ne se rejoue pas (supprimer
  `config/.migrated-rc32-unused-keys` pour la rejouer) et une clé commentée se remet en retirant le préfixe.
- **Test (caméra, interface en français puis en anglais) :** (1) Jour/nuit : pas de boutons Auto/Jour/Nuit, le lien ouvre
  le Direct ; changer « Mesure de la lumière » n'affiche que les seuils de la méthode ; « Enregistrer les seuils » garde les
  quatre jeux de valeurs (relire l'onglet). (2) Système : « LED au démarrage », pas de « Hard Reboot » ni de « Clear Page
  Cache » ; Outils → Redémarrer fonctionne. (3) Mise à jour et sauvegarde : le guide à quatre lignes ; tous les boutons
  encore là. (4) Services : la phrase sous le tableau ; `web-server` « En marche depuis » l'âge de `httpfront`
  (`ps`, pid de `httpfront`), pas 1 s. (5) Alertes et Intégrations : les deux liens Telegram. (6) Intégrations : le
  nombre d'entités (49 attendu sur la .24 avec la découverte active ; « 0 » découverte coupée) ; la page ne se bloque pas.
  (7) Wi-Fi → Scanner : « Signal (dBm) » sans décimales. (8) Avec le mot de passe par défaut : l'alerte et son lien.
  (9) Migration : après le premier démarrage en rc32, `grep -c '^#\[rc32' /mnt/config/boot.conf` = nombre de clés de la
  liste présentes avant, `cat /mnt/config/migrations.log`, `ls /mnt/config/.migrated-rc32-unused-keys` ; l'éditeur de
  configuration ne les propose plus comme réglages ; `RTSP_LITE_TALK` inchangé ; un second redémarrage ne change rien.
- **Critères :** aucune fonction perdue (chaque bouton retiré a son équivalent indiqué) ; aucune erreur JavaScript ;
  aucun défilement horizontal en 360 px ; aucune clé de `boot.conf` supprimée, toutes les clés lues par 3.0 intactes.

## 2026-11-06 — R17/R7/R10/R12 : caches CGI, import config et délais RTSP (`[perf-r17]`)

- **Quoi :** R7 — l'import de configuration compare les fichiers avant de créer les copies de retour arrière ; les
  fichiers identiques sont ignorés, et `sync` est sauté uniquement en mode flash où `/mnt/config` est un tmpfs
  (la persistance reste à `cfg-persist`). En mode SD, les deux synchronisations de la transaction restent. R17 —
  `scripts.cgi?cmd=allstates` démarre son TTL après le scan complet et sert un cache récent pendant son rafraîchissement
  en arrière-plan ; `state.cgi` met en cache brièvement `fullconfig`, `daynight`, `isp_tune` et `dashinfo` ;
  `action.cgi` met aussi en cache brièvement `md_zones_info`. Les écritures web connues invalident ces caches. R10 —
  chaque fermeture pour délai journalise le délai actif (`CLI_AUTH_S=30` ou
  `CLI_IDLE_S=60`), sans changer les valeurs. R12 — `daynight` utilise aussi le cache court ; la première requête
  lente après le boot reste à mesurer.
- **Interrupteur :** aucun. Le cache est temporaire en RAM ; les durées n'affectent pas les flux ni les réglages.
- **Test (rc suivante, sans écriture flash par l'implémenteur) :**
  1. R7 : exporter sans secrets puis réimporter le même fichier deux fois ; relever `applied`, `changed_files`, durée
     et cadence `STAT cap` pendant l'import. Le second import doit rester sans changement et ne pas provoquer de baisse
     de capture liée à un `sync` global. Vérifier que les valeurs des réglages sont identiques avant/après.
  2. R17 : mesurer deux appels successifs à `scripts.cgi?cmd=allstates`; le second doit répondre depuis le cache.
     Attendre plus que le TTL puis refaire l'appel : il doit servir rapidement l'ancien état et actualiser le cache en
     arrière-plan. Après un basculement de service, l'état doit se mettre à jour au poll suivant. Mesurer deux appels
     à `state.cgi?cmd=fullconfig` ; après un changement enregistré dans Réglages, le readback doit montrer la nouvelle
     valeur immédiatement. Vérifier aussi le premier appel `daynight` puis le suivant, et l'absence d'erreur JSON.
     Appeler `action.cgi?cmd=md_zones_info` deux fois, puis enregistrer une modification des zones et vérifier le nouveau
     contenu au prochain appel.
  3. R10 : un client TCP qui n'envoie que `OPTIONS` doit fermer à environ 30 s avec le motif `CLI_AUTH_S` ; un client
     qui passe l'authentification par `SETUP` puis ne lance pas `PLAY` doit fermer à environ 60 s avec `CLI_IDLE_S`.
     Le flux Frigate en lecture reste connecté et ses images continuent.
  4. R12 : juste après un démarrage, mesurer le premier puis le deuxième `state.cgi?cmd=daynight&format=json` ; noter
     l'uptime, la durée et les champs JSON. Si le premier dépasse 2 s, répéter avec l'onglet Réglages déjà ouvert et
     relever les mêmes mesures avant toute modification du handler.
- **Critères :** aucune valeur de configuration ne change pendant ces vérifications ; caches servis en moins de 0,5 s
  quand disponibles ; état rafraîchi après un changement ; motifs RTSP conformes au type de client ; Frigate stable.

## 2026-11-06 16:30 — revue du testeur : `[rc32-*]`, `[ui-r20]`, `[tz-lowlight]`, `[sender-thread]`, `[hrt-test]`, `3c4d77d` — **CI rouge sur `main`, pas de rc32 tant qu'elle l'est**

- La CI de `52ee51b` (fusion des trois branches de travail) échoue, et en local sur `3c4d77d` 6 tests échouent
  (hors `test_httpfront_*`, propres au bac à sable du testeur) :
  - `test_abr.Abr.test_wiring` : attend `rec_active(), pp_us / 1000, sub_us / 1000);` suivi de `abr_tick(dr);` ; la
    ligne `STAT` a maintenant `sq_max, sq_drop, thr_us…` (`[sender-thread]`) : test à mettre à jour.
  - `test_review_20261106.UpdateWithoutBackup.test_page_asks_and_sends_the_confirmation` : attend
    `d.error === 'nobackup' && !extra` ; `settings.html` l. 1413 a la même logique sous une autre forme (`[ui-r20]`) :
    test à mettre à jour (la confirmation est bien là).
  - `test_audit_fixes.SdRepairGuards.test_same_boot_files_as_the_recorder` : `rec-storage.sh` lit maintenant la liste
    commune `$SD_BOOT_FILES` (R25) : le test doit lire cette variable.
  - `test_regressions…test_fullconfig_reads_actual_ini_video_and_audio`, `test_feat30…test_state_cgi_reading`,
    `test_opt.DashinfoCache` : **le cache de `state.cgi` (`3c4d77d`)** relance `sh ${STATE_CGI_SCRIPT:-/mnt/www/cgi-bin/state.cgi}`
    pour remplir le cache : hors caméra (et pour tout appel où ce chemin n'est pas le script courant) la réponse est
    vide (« Expecting value ») ; `dashinfo` ne passe plus par `dashinfo_cached`. Utiliser `$0` (le script en cours) au
    lieu du chemin fixe, et garder `dashinfo_cached` (ou mettre à jour `test_opt` si le nouveau cache le remplace).
- Revue de `3c4d77d` (commit sans étiquette ni `Co-Authored-By`, identité `morgeek`) : caches courts de `state.cgi`
  (`fullconfig` 5 s, `dashinfo` 5 s, `daynight` / `isp_tune` 1 s) et de `action.cgi?cmd=md_zones_info` (2 s), vidés à
  chaque POST, import et écriture de configuration ; Services : instantané de ≤ 60 s rendu tout de suite pendant qu'un
  rafraîchissement tourne en fond (R17) ; import : plus de `sync` global en mode flash ni de copie de secours pour un
  fichier identique (R7) ; `tc100_rtsp` : journal à l'expiration d'un client (R10 : un client qui n'envoie
  qu'`OPTIONS` n'est pas authentifié, d'où les 30 s mesurées). Idée bonne ; à corriger pour les tests ci-dessus.
- **À vérifier en rc32** (testeur) : page Services < 2 s ; `fullconfig` < 1 s au 2e appel ; une modification de
  réglage visible tout de suite (cache vidé) ; import JSON plus court ; journal `client slot … expired`.

## 2026-11-06 17:00 — rc32 lancée par le testeur (consigne du propriétaire : « corriger les problèmes … rc32 exploitable, go »)

- `b82391c` : CI de nouveau verte (cache de `state.cgi` rempli par `$0`, plus de second `case` ; trois tests périmés mis
  à jour). Puis `VERSION` 3.0.1-rc32 et `CHANGELOG` (contenu : rc31 + R22-R26, Pico seul, un seul démon ONVIF, R20,
  fuseau horaire, basse lumière 10/15/20, caches R17/R7, journal R10, fil d'envoi optionnel).
- Le testeur contrôle l'archive puis l'installe sur la .11 par la mise à jour web (sans carte : confirmation
  « sans sauvegarde », comme la page) ; contrôles : réglages conservés, syslog distant (`tc100-logfwd` vivant sans
  superposition), Pico seul, Services < 2 s, `fullconfig` rapide au 2e appel, fuseau et basse lumière dans Réglages,
  WebRTC, ONVIF, MQTT, `reboot-history.log`.


## 2026-11-06 17:05 — `wifi-diag.sh run 7200 ping` sur la .11 (rc31) : bilan

- 5 600 relevés (13:53 → 15:53 UTC), **541 pings perdus (9,7 %)**, ping moyen 11,6 ms quand il répond : comme les
  nuits du 05/11 et du 06/11. **Réception jamais figée ≥ 3 s, hôte USB jamais figé ≥ 3 s** : les compteurs `rx_pkts` et
  `usb_irq` avancent pendant les pertes. Donc ni le pilote USB ni la réception de `wlan0` ne s'arrêtent : la réponse
  ICMP se perd entre la box et la caméra (radio, point d'accès, ou limitation ICMP de la box). Signal de la .11 :
  -15 dBm (très près du point d'accès « Keegrom6 » ; « Keegrom7 » est vu à -40 dBm de la .24).
- **Défauts de l'outil** : (1) `gap_ms` vaut ~190 ms à chaque seconde (le coût de la boucle elle-même avec un noyau à
  HZ=100) ; le seuil « camera stalled > 300 ms » compte donc 1 293 « blocages », dont la plupart sont le délai d'attente
  de 1 s d'un ping perdu : soustraire le temps du ping, ou mesurer le ping hors de la boucle ; (2) `summary` affiche
  parfois des « stalls » de 868 390 ms / 933 380 ms (valeurs du champ `up_ms` prises pour un écart : lignes coupées ou
  redémarrage du chronomètre ?) ; (3) une ligne toutes les ~1,28 s au lieu de 1 s (5 600 pour 7 200 s).
- Pistes suivantes (implémenteur, sans risque pour la liaison) : mesurer en parallèle un ping de la box vers la caméra
  (côté box) et un ping de la .11 vers la .24 (même réseau, sans la box) pour savoir de quel côté les réponses se perdent.

## 2026-11-06 17:15 — rc32 sur la .11 (IPCAM2), installée par le testeur : `passed`

- **Archive** : run 42248185087 (`e267e73`), `tc100-3.0.1-rc32-update.tar` md5 **`f00b91203b3f62a4ccff72bb9970b80d`**,
  `MD5SUMS` OK, `stack.sqfs` 2 134 016 octets. Dedans : `tc100-logfwd` sans `__isoc99_*`, `libnetacl.so` sans
  `__isoc23_*`, Pico seul (`ui.pico.min.css`), pas de `monvifd` ni de `jq`, `tc100-whep` avec le recollage du
  ClientHello, cache de `state.cgi` par `$0`, `halt` et confirmation `nobackup` dans la mise à jour. Copie sur le Mac :
  `~/Downloads/tc100-fix/xfer32/`.
- **Installation** depuis la rc31 (son `update66.sh` a déjà `halt`) : `cmd=upload` puis `cmd=install&nobackup=1` (la rc31
  ne demande pas encore la confirmation ; la page de la rc32 la demandera). 16:06:06 → 16:08:19 UTC.
  `reboot-history.log` : « requested at 2026-11-06 16:06:20: web update to 3.0.1-rc32 ». Réglages conservés
  (`daynight=2`, `mdenabled=0`, `REC_LOCAL=0`, `rtsp.env`, `autostart/*`, `WIFI_COUNTRY=FR`, `SYSLOG_HOST`).
- **Base** : rc32, MemAvailable 23,3 Mo, CmaFree 5,9 Mo, démons présents, superviseur 3 jobs, `dropped 0`, aucune OOM ;
  plus aucune superposition en RAM.
- **R23 / syslog** — `passed` : `syslogd` et `tc100-logfwd` démarrés au boot, **vivants après une nouvelle ligne**,
  `syslog-forward` « running ». (Réception sur 192.168.1.23 à confirmer par le propriétaire.)
- **R22** — `passed` : `index.html` servi sans `Last-Modified` (ETag seul) ; **Chrome a affiché la rc32 (Pico) sans
  rechargement forcé** alors qu'il avait la rc31 en cache.
- **R17** — `passed` en partie : `fullconfig` 3,35 s puis 0,40 s (cache) ; `allstates` 8,1 s puis 0,24 s ; `md_zones_info`
  1,84 s puis 0,48 s ; la page Services (`scripts.cgi`) reste à 4,7 s au premier affichage.
- **Interface** : Pico seul, version rc32 affichée, toutes les pages sans erreur JavaScript ; Réglages : liste de
  fuseaux (`timezone_preset`, 101 zones) et cadence basse lumière (`dn_lowlight_fps`, 3 choix).
- **Flux** : RTSP hevc 1080p25 / h264 360p25 + PCMA ; ONVIF FW rc32, 25 img/s ; MQTT `health` répond, 49 entités ;
  WebRTC Chrome 640x360 à 19 img/s, plus d'avertissement « Live fetch error 503 » (R24).
- Reste : la .24 en rc32 (au choix du propriétaire), les sons intégrés à jouer avec lui, l'enregistrement de la .24
  après formatage de sa carte.

## 2026-11-06 17:25 — rc32 sur la .24 (IPCAM1) et début de la surveillance de 7 jours (testeur, consigne du propriétaire)

- **.24 en rc32** (même archive md5 `f00b9120…`, `cmd=install&nobackup=1`) : 16:16:10 → 16:18:23 UTC ; « requested at
  2026-11-06 16:16:25: web update to 3.0.1-rc32 ». Conservés : `daynight=2`, `mdenabled=0`, `REC_LOCAL=1`,
  `REC_WHEN=motion`, `WIFI_COUNTRY=FR`, `SYSLOG_HOST=192.168.1.23`. Démons présents, `syslogd` + `tc100-logfwd` vivants
  après une ligne, RTSP 1080p, ONVIF rc32, MQTT `tc100/cam2` online + `health`. Aucune OOM.
- **`failed`, corrigé — R25 n'était pas réglé** : après la mise à jour, l'ancienne carte 3.0 (avec `wifitest/`) était de
  nouveau montée en écriture sur `/mnt/sd` (`rec 1`, `ADRESSE.txt` écrit à 16:19, journaux `logs/boot-0012`). La vraie
  cause : l'initramfs monte la carte pour le mode SD et `flashmode-prep.sh` la remettait sur `/mnt/sd` sans aucun
  contrôle ; le verrou de `rec-storage.sh` (rc32) n'y pouvait rien. **Corrigé en `d2ee15f`** (même liste
  `SD_BOOT_FILES` dans `flashmode-prep.sh` : carte démontée, ou laissée en lecture seule si elle est occupée ; test
  `FlashModeRefusesBootCard`). Sur la .24 : carte démontée à la main (`rec-storage.sh eject` a répondu « ok » sans la
  démonter : à voir), placeholder tmpfs remis, `rec 0`. **Jusqu'à la rc33 (ou le formatage de la carte), chaque
  redémarrage de la .24 la remonte en écriture** : le testeur la démonte à chaque contrôle quotidien.
- **Surveillance** : `/tmp/watch7.sh` sur les deux caméras (une ligne toutes les 5 min dans `/tmp/watch7.log`, 2 100
  lignes au plus : uptime, MemAvailable, CmaFree, charge, 3 pings vers la box, `cap`/`clients`/`dropped`/`rec`, signal,
  mode jour/nuit, démons manquants). Contrôles quotidiens du 07 au 12/11 à 08:30 et bilan final le 13/11 à 17:30.
- **Premier relevé (2026-11-06 18:45 UTC, ~2 h 30 de rc32)** : aucun redémarrage, aucune OOM, aucun démon manquant,
  `dropped 0` partout, Frigate connecté (`cl1`). `.11` : MemAvailable 22,1-23,2 Mo, CmaFree ~5,9 Mo, 10 img/s depuis
  ~16:37 (basse lumière, gain ~15-20x, mode jour, éclairage de la pièce) ; `.24` : 20,9-22,6 Mo, CmaFree 3,9-4,3 Mo,
  25 img/s le soir (pièce éclairée, gain ~5x). Pings (3 par relevé, 29 relevés) : `.11` 3 relevés tout perdus + 3
  partiels, `.24` 4 + 2 (≈ 10 %, comme avant). Carte de la .24 toujours démontée. `/proc/net/wireless` donne parfois
  `-256` (valeur invalide du pilote) : ignorée.
- **VERSION → `3.0.1-rc33-dev`** (testeur, 2026-11-06 20:10 UTC) : `d2ee15f` (carte de démarrage, R25) a changé du code
  après la rc32 ; la build de `d2ee15f` porte encore le nom « rc32 ». **La rc32 installée sur les deux caméras est celle
  de md5 `f00b9120…`** (run 42248185087, `e267e73`).

## 2026-11-06 20:15 — point du testeur sur la liste de l'implémenteur (avant d'ajouter les points de la rc33)

- **Fait** : R1-R6, R8, R9, R11, R13-R15, R18-R20, R22-R26 ; flash S1/S1b/S3/S5/S6/S7 ; F2, F3 + F9 ; D1-D10 ; nettoyage du
  dépôt ; retraits de la rc32 (Bulma, `monvifd`). R4 et R21 clos par le testeur (validés sur caméra).
- **Partiel, en attente de mesure sur caméra** : R7 (import, pas remesuré en rc32 pour ne pas couper Frigate pendant la
  surveillance de 7 jours), R10 (journal ajouté), R12 (non reproduit), R16 (fil d'envoi, défaut 0, à mesurer), R17
  (2e appel rapide, 1er affichage de Services 4,7 s).
- **Ouvert** : R27 (`wifi-diag.sh`) ; P0 n° 3 (W4 assistant sans jeton CSRF, B3 `flashw -m`) ; audit W2-W5 (selon
  `wifi-diag`), F1 (audio bidirectionnel), F4 (formatage / exFAT), F5 (image, à confirmer par le propriétaire), F6
  (bascules à l'aube), H2-H4 (noyau, par la carte SD, propriétaire présent), H11 (temps de démarrage) ; plan de test T1
  (7 jours, en cours), T5, T7, T10-T12, P1-P10 (avec le propriétaire).
- **Pour la rc33, déjà sur `main`** : `d2ee15f` (carte de démarrage refusée dès `flashmode-prep.sh`, la vraie cause de
  R25).

## 2026-11-06 21:30 — travail sans le propriétaire avant la rc33 (testeur)

Pendant la surveillance de 7 jours : rien d'installé, seulement des lectures et des CGI copiés dans `/tmp` puis effacés.

- **R27 `wifi-diag.sh`** corrigé (`e4b1ec9`) : les « stalls » de 868 s venaient de la fraction de `/proc/uptime` lue en
  octal (`0.05` → 40 ms, `0.08` / `0.09` → erreur) ; `gap_ms` ne mesure plus que le dépassement du `sleep`, nouvelle
  colonne `work_ms` (coût de la boucle). `summary` inchangé. Tests `tests/test_wifi_diag.py`.
- **R17 page Services** (`fd1ae6a`) : le scan `allstates` à froid passait l'essentiel de son temps à relire `boot.conf`
  (410 lignes) en boucle shell, ~7 fois. Lu une fois par awk : **.11 5,56 → 1,43 s, .24 6,64 → 1,16 s**, JSON identique
  (hors `uptime_s`), mesuré avec le CGI corrigé copié dans `/tmp`. `fullconfig` à froid (~3,2 s) profilé, laissé tel
  quel (détail dans R17 de `a-faire-implementeur.md`).
- **W4 validé** (rc32, les deux caméras) : POST à `wizard.cgi` sans jeton CSRF ou avec un faux jeton → `403
  {"ok":false,"error":"csrf_invalid"}`. B3 relu et testé hors caméra ; il s'exerce pour de vrai à la mise à jour rc33.
- Déjà sur `main` pour la rc33 : `d2ee15f` (carte de démarrage refusée dès `flashmode-prep.sh`), `dc6966c` (« Éjecter »
  démonte aussi une carte refusée), `e4b1ec9`, `fd1ae6a`.

**Tests qui demandent le propriétaire (à faire ensemble)** :
1. Installer la rc33 quand elle sort (mise à jour web : vérifie B1/B3 en vrai, la carte refusée de la .24, `syslogd`).
   À caler avec la surveillance de 7 jours (fin le 2026-11-13) : soit attendre, soit accepter un redémarrage dans la
   surveillance.
2. Carte SD de la .24 : la vider ou la formater (elle porte encore `wifitest/`), puis « Éjecter » / remettre depuis
   l'interface.
3. Wi-Fi (R27 suite) : `wifi-diag.sh` sur la .11 avec, en même temps, un ping depuis la box ou le Mac vers la .11, pour
   situer les ~10 % de pertes.
4. H2-H4 (noyau par la carte SD) et P1-P10 du plan de test : propriétaire présent.

## 2026-11-06 22:30 — demandes du propriétaire sur l'interface, faites par le testeur (pour la rc33)

Demandes du propriétaire (22:29) et ce qui a été changé ; rien n'est installé sur les caméras (surveillance de 7 jours) :

- **Tableau de bord, colonne « Cadence »** : elle affichait le réglage (`[0] fps`, et `[1] fps` qu'aucun programme ne lit :
  `tc100_rtsp` n'a qu'une cadence, `-f`, pour les deux flux). Mesuré ce soir : **la .24 encodait à 10,0 fps** (basse
  lumière) quand la page disait 25. `dash.cgi` donne maintenant `vfps` (dixièmes de fps, `captured / interval_s` de
  `/var/run/tc100_rtsp.stat`, seulement si `tc100_rtsp` tourne) ; la page affiche cette mesure pour les deux flux, le
  réglage en info-bulle quand il diffère, le réglage seul tant qu'il n'y a pas de mesure. `dashinfo` donne la cadence
  de `[0]` pour le sous-flux.
- **Carte « Appareil »** : retirés Fonctionne depuis, Noyau, SoC, Capteur ; Wi-Fi = le nom du réseau seul.
- **Stockage** : la ligne Carte SD est cachée sans carte montée.
- **Menu** : « Enregistrements » seulement avec une carte montée ; Réglages → « Enregistrement » aussi quand une carte
  est présente sans être montée (c'est là qu'on la monte ou la formate).
- **Live** : barre de mesures (`v2-readings`) et « Plus d'outils » (`home-tools`) retirés ; boutons Carillon et Alerte
  retirés (reste Sirène).
- **Écoute** (« plusieurs secondes de retard ») : l'élément `<audio>` tamponnait le WAV sans fin. Lecture par `fetch()`
  + Web Audio avec ~0,25 s d'avance, les données au-delà de 0,6 s de retard sont jetées ; repli sur `<audio>` pour un
  vieux navigateur (`www/scripts/ptt-audio.bundle.min.js`). **À essayer avec le propriétaire** (latence ressentie).
- **Détection** : « The camera replied, but saving is not confirmed » à chaque enregistrement : `conf_motiondetect`
  répondait en HTML. Répond `json_body_ok` quand la page demande du JSON ; message traduit au cas où.
- **Icônes de titre énormes** (Réseau, Infos, Disque, Journaux, Sauvegarde…) : leur taille venait de la feuille Bulma
  retirée en rc32 (`f38a1ea`) ; règles `.title-icon` / `.title-with-icon` remises dans `ui.css`.
- **Mémoire** (mesure et prévision) : sortie de Réglages → Système, nouvelle entrée Outils → Mémoire (`tab-memory`, sans
  lien dans la barre des réglages) ; la mesure ne se lance plus à chaque ouverture des Réglages, seulement sur cette page.
- **Sons** : son de démarrage = le fichier du propriétaire (`sounds/startup.pcm`, 0,67 s, 8 kHz, crête −6 dBFS ; c'est le
  son « pièce » de Mario : le propriétaire a choisi de le mettre dans le dépôt public en connaissance de cause).
  Supprimés : `chime`, `alert`, `startup_2`, `startup_complete`. `BOOT_SOUND_NAME=startup` ; un ancien
  `startup_complete` / `chime` dans `boot.conf` retombe sur `startup` (autorun) ; `play_sound` chime/alert → startup ;
  bouton HA « Play Chime » retiré (config vide publiée, `mqttd.c` et `mqtt-bridge.sh`) ; Test du matériel joue le son
  de démarrage.

## 2026-11-07 01:30 — nos démons sans le runtime uClibc du vendeur (testeur, pour la rc33)

Demande du propriétaire : réduire le code propriétaire. `tc100-mqttd`, `tc100-onvifd`, `tc100-supervisord`,
`tc100-logfwd` et `rwconf` sont compilés contre **musl 1.2.4**, la libc du système de base 3.0 (la caméra a
`/lib/ld-musl-arm.so.1` → `/lib/libc.so`, « musl libc (arm) Version 1.2.4 »), en dynamique : `NEEDED libc.so`,
interpréteur `/lib/ld-musl-arm.so.1`. Avant : chargeur uClibc du vendeur + libc « bouche-trou » faite au lien (d'où
les pannes `__isoc99_sscanf`, variables de libc, etc.). Le runtime uClibc du vendeur ne sert plus qu'à `tc100_rtsp`.

- `v3/musl/build-musl.sh` : télécharge musl 1.2.4 (SHA-256 vérifié), le construit avec `arm-linux-gnueabi-gcc`
  (ARMv5TE, soft float) dans `build/musl` (~1 min) ; `src/musl.mk` : options communes ; Makefiles des 5 programmes.
- Tailles quasi identiques (mqttd 34 148 o, onvifd 50 564, supervisord 30 184, logfwd 9 576, rwconf 9 396).
- **netacl** : en 3.0, telnetd/ftpd sont ceux de la busybox musl du système : la bibliothèque uClibc n'y était
  jamais préchargée, donc le filtre « réseau local seulement » ne s'appliquait pas. Nouvelle `lib/libnetacl-musl.so` ;
  `netacl_exec` choisit la bibliothèque du chargeur du programme.
- **Essai sur la .11** (rc32, rien installé, binaires dans `/tmp` puis effacés) : `rwconf` musl lit et écrit
  exactement comme l'actuel (`cmp` identique), `tc100-onvifd` musl démarre sur un port à part et répond.
- Tests : `tests/test_musl_programs_qemu.py` (vrais binaires sous qemu avec le vrai chargeur musl : dépendances,
  imports résolus dans la libc musl, tests LogForwarder, rwconf = version hôte, filtre netacl) ; CI : étape dédiée
  dans `ci.yml`, `build-musl.sh` dans la construction de la version.
- **À vérifier à l'installation de la rc33** : les 4 démons tournent (`/proc/<pid>/maps` sans `/vendor/lib`),
  ONVIF/MQTT/journal distant/`rwconf` au démarrage fonctionnent ; telnet (si activé) refuse une adresse hors LAN.

## 2026-11-07 02:00 — encodeur H.265 libre, étape 2 : outils prêts (testeur), essais sur la .11 après la surveillance

Choix du propriétaire : tous les essais sur la .11 une fois l'étape 2 écrite. Rien n'a tourné sur une caméra.
- `libakuio` : `AKUIO_CAPTURE=PREFIX` (lecture seule) — après chacune des N premières interruptions, registres, liste
  de commandes, tampons table/travail/petit, tampon de flux et, une fois, l'image NV12 source de la première IDR.
- `tc100_rtsp` : `RTSP_SAVE_FRAMES=PREFIX` — les images rendues par la bibliothèque du vendeur + leur adresse.
- `src/h265enc/capture.py` : analyse (où est la longueur de l'image, le cœur écrit-il les en-têtes, la table est-elle
  constante, les listes 3.0 suivent-elles `build_list`) et fichiers d'entrée de `h265enc`.
- `src/h265enc/h265enc.c` : une image IDR encodée par le cœur seul (liste IDR du vendeur comme modèle, nos tampons),
  `--dry` testé contre `cmdlist.build_list` ; `--run` à essayer.
- `v3/dev/h265-step2.sh capture | run` : la procédure sur la caméra (vidéo coupée ~1 min, rien en flash).
- Les captures sont des données du vendeur : jamais dans git.

## 2026-11-07 07:30 UTC — surveillance rc32 jour 1/7 (testeur)

| | .11 (IPCAM2) | .24 (IPCAM1) |
|---|---|---|
| Uptime | 15 h 23, aucun redémarrage depuis la rc32 | 15 h 13, aucun |
| Mémoire libre mini / CMA libre mini | 20 856 / 5 336 Ko | 19 880 / 3 880 Ko |
| Images perdues | 0 (une ligne `drop2` isolée) | 0 |
| OOM / segfault (dmesg) | aucun | aucun |
| Pertes ping (moyenne des relevés) | 10,5 % (24 relevés sur 180 avec pertes) | 8,6 % (20 sur 181) |
| syslogd + tc100-logfwd | en marche | en marche |
| Jour/nuit | jour → nuit 00:37 UTC (lumière de la pièce) | nuit 00:21, aube 05:39 jour → 05:55 nuit → 06:15 jour |

- Nuit : 10 fps (cap ≈ 50 / 5 s) comme prévu en basse lumière ; 25 fps de jour.
- .24 : deux bascules à l'aube (05:39 → 05:55 → 06:15 UTC), sans suite : seuils à revoir peut-être, rien de bloquant.
- `watch7.sh` : certaines lignes ont `## max nalu size …` (une ligne du journal de `tc100_rtsp`) à la place des champs
  cap/cl/drop : défaut de l'outil de relevé, pas de la caméra.
- Carte SD : placeholder RAM sur les deux (`/mnt/sd` tmpfs) ; la carte de démarrage de la .24 n'a pas été remontée.

## 2026-11-07 09:20-09:40 — .11 en rc33-dev, puis PREMIÈRE IMAGE H.265 SANS LA BIBLIOTHÈQUE DU VENDEUR (testeur)

Le propriétaire a arrêté la surveillance de 7 jours sur la .11 (la .24 continue en rc32) : « flash la .11 ».

**Installation 3.0.1-rc33-dev** (build `91db751`, md5 `d70353375e5136d9a123fb93daa09d68`) par `update.cgi` (upload,
install `nobackup=1`), redémarrage en ~1 min 30, Wi-Fi revenu.
- Les 4 démons (`tc100-onvifd`, `-mqttd`, `-supervisord`, `-logfwd`) tournent sur **musl** : `/proc/<pid>/maps` sans
  `/vendor/lib`. `rwconf` musl OK au démarrage. ONVIF : profils, WS-Discovery, limites 25 fps / 1600-250 kbit/s ;
  MQTT : en ligne, **48** entités de découverte (49 avant : bouton Carillon retiré). Journal distant en marche.
- `dash.cgi` : `vfps` = 228 (22,8 fps mesurés) ; `dashinfo` sous-flux à la cadence de `[0]`.
- `sounds.cgi` : `siren` et `startup` seulement. **Petit défaut** : `boot.name` affiche encore `startup_complete`
  (valeur de `boot.conf` d'une installation existante ; l'autorun retombe bien sur `startup`) → à normaliser dans
  `sounds.cgi` (afficher `startup` si le son nommé n'existe pas).
- **Bug trouvé et corrigé** : la `libakuio.so` de la CI importait `__isoc23_strtol` (les `atoi()` ; en-têtes glibc 2.38
  du compilateur de la CI), absent de l'uClibc : `tc100_rtsp` s'arrêtait dès qu'une variable `AKUIO_*` (débogage)
  était posée. `env_num()` à la place, plus de `stderr` (écriture par `write(2)`), et `src/libakuio` ajouté à
  `tests/check-libc-data-imports.sh` (CI). Sans effet en usage normal (aucune variable posée).

**Capture de l'encodeur du vendeur** (`v3/dev/h265-step2.sh capture`, 20 s, vidéo revenue) puis analyse :
- La liste IDR de la bibliothèque 3.0 (`libmpi_venc_ex`) est **exactement** celle de `cmdlist.build_list`.
- Deux interruptions par image chez le vendeur, masque `0x8014` = 0x4 puis 0x1.
- **Longueur de l'image = mot d'état 0x41** de la liste ; **le cœur n'écrit que les données de tranche**, à partir de
  flux +0x820 ; le logiciel écrit avant : `00 00 00 01 26 01` + 3 octets d'en-tête de tranche (`ac 29 80`, IDR, QP 36).
- La table de 0x4040 octets est la même pour toutes les images du flux principal (une autre pour le sous-flux).
- L'image source n'est pas dans le pool de l'encodeur (tampons V4L2 de l'ISP) : pas de copie NV12 ; l'entrée du test
  a été l'image du vendeur décodée.

**`h265enc --run`** (cœur seul, liste IDR du vendeur comme modèle avec nos tampons, QP 36, table capturée) :
- 1er essai : le cœur encode (26 925 octets, mot 0x41) mais pas d'interruption (masque `0x8014` laissé à 0) ;
  2e essai avec masque 0x5 : interruption reçue, **flux identique octet pour octet** (encodage déterministe).
- `ffprobe` : HEVC Main 1920x1080, une image I ; `ffmpeg` : **0 erreur de décodage** ; PSNR 41,9 dB contre l'image
  d'entrée (normal pour un réencodage à QP 36) ; image nette à l'œil.
- **Premier jalon atteint** : une image H.265 encodée sur le matériel sans `libakv_encode` ni `libmpi_venc`.

Suite (étape 3) : images P (deux tampons d'image, la référence), nos propres VPS/SPS/PPS et en-tête de tranche
(dépend du QP et du POC), table recalculée ou figée, contrôle de débit, sous-flux H.264 ; puis branchement dans
`tc100_rtsp`.

## 2026-11-07 09:45 — encodeur H.265 libre, étape 3 : FLUX IDR + P EN DIRECT DEPUIS L'ISP (testeur, .11)

`src/h265enc/h265live.c` : capture V4L2 (tampons de l'ISP, adresse physique par `AK39_VI_G_PHYS`, aucune copie),
IDR puis images P qui se réfèrent chacune à la précédente, deux tampons d'image en alternance, QP fixe, en-têtes de
tranche écrits par notre code (`slicehdr.h`), VPS/SPS/PPS du vendeur (capturés).
- Hors caméra : listes IDR et P = `cmdlist.build_list` au mot près ; en-têtes = ceux du vendeur à l'octet près (IDR
  QP 36 `ac 29 80`, P POC 2 QP 42 `d0 04 2a f8 20 c0`, P POC 4 QP 38) — `tests/test_h265cmdlist.py` H265liveDry.
- **Sur la .11** (`h265-step2.sh live`, vidéo coupée ~15 s) : 50 images (1 I + 49 P), **0 échec**, 31,1 ms par image
  sur le cœur, 1 236 071 octets (≈ 4,9 Mbit/s à QP 32 fixe : pas encore de contrôle de débit). `ffmpeg` : **0 erreur
  de décodage**, 50 images ; le contenu suit la scène (références justes). Teinte verte : la balance des blancs
  logicielle de `tc100_rtsp` n'est pas appliquée dans ce test.
- Le serveur vidéo normal est revenu après l'essai.

Reste avant de remplacer la bibliothèque du vendeur : contrôle de débit (QP par image d'après la taille, comme le
vendeur : P à QP 38-42 pour 1,6 Mbit/s), nos VPS/SPS/PPS (aujourd'hui ceux du vendeur), table de 0x4040 octets (figée
ou recalculée), sous-flux H.264 640x360 (même méthode), puis l'intégration dans `tc100_rtsp`.

## 2026-11-07 10:00 — encodeur libre, contrôle de débit (testeur, .11)

`src/h265enc/rc.h` : un QP par image (seau virtuel : budget = débit / 25 par image, la taille divisée par 2 tous les
6 QP, gain 1/2, au plus ±3 QP par image, IDR à QP P − 2, la première IDR règle le QP de départ). `h265live -b KBPS`
(IDR toutes les 50 images). Simulation : `src/h265enc/rctest.c`, test `RateControl`.
- **.11, 150 images, -b 1600** : **1 612 kbit/s** (par seconde : 1837, 1392, 1774, 1500, 1674, 1492), 3 IDR + 147 P,
  0 échec, ffmpeg 0 erreur, 29,9 ms par image sur le cœur. QP stable à 35 après le départ (le vendeur : 38-42 au même
  débit). Départ : QP monte à 44 pendant ~1,5 s (les premières P après l'IDR sont plus grosses), puis redescend.

## 2026-11-07 10:05 — encodeur libre : nos propres VPS/SPS/PPS (testeur, .11)

`src/h265enc/paramsets.h` écrit VPS, SPS et PPS (mêmes valeurs que le vendeur, relevées avec `trace_headers` :
Main, niveau 4.0, CTB 32, listes de quantification par défaut, TMVP, 13 jeux de références à court terme, VUI 25 fps…).
**Identiques à l'octet aux 112 octets du vendeur** pour 1920x1080 à 25 fps (test `ParamSets` ; autres tailles lues
par ffmpeg). `h265live` les utilise par défaut (`H265_VENDOR_PARAMS=1` : la copie capturée).
- **.11, 100 images, -b 1600, sans `params.bin` dans le dossier d'entrée** : 1 675 kbit/s, 2 I + 98 P, 0 échec,
  **0 erreur de décodage**, HEVC Main 1920x1080 25/1. Le flux entier (en-têtes de flux, de tranche, débit) vient de
  notre code ; restent des captures : la table de 0x4040 octets, les tampons work/small et les modèles de liste.

## 2026-11-07 10:30 — encodeur libre : PLUS AUCUNE DONNÉE DU VENDEUR (testeur, .11)

- **Listes de commandes** : `listgen.h`, généré par `gen_listgen.py` depuis `cmdlist.py` (une seule source ; test
  `ListGen` : à jour, et listes identiques à celles faites depuis les modèles capturés).
- **Tampon « work » (0x6400 octets)** : seconde capture (40 interruptions) : le logiciel du vendeur le remplit une fois,
  le même pour toutes les images IDR et P ; à zéro, le cœur ignore le QP (20-23 Ko par image à QP 35 comme à 51).
  Contenu décodé et **calculé** (`worktab.h`) : 52 × 4 poids débit-distorsion par QP (colonnes 1-3 = `ceil(A·2^(QP/6))`,
  colonne 0 : les 52 valeurs du vendeur), les listes de quantification par défaut de la norme (table 7-6, matrices 8x8
  en ordre ligne), les facteurs `2^24 / (m · invLevelScale[QP%6])`. **Identique aux 25 600 octets du vendeur** (test
  `WorkTable` : SHA-256 de la capture, la capture elle-même n'est pas dans le dépôt).
- **Table de 0x4040 octets** : 32 octets d'en-tête, le reste à zéro ; l'octet 19 vaut 0x24 en IDR, 0x30 en P (le même
  pour toutes les P quel que soit le QP) ; le tampon de 256 octets est à zéro.
- Les attentes 3 à 5 de la première capture étaient des instantanés JPEG (masque 0x40000).
- **.11, dossier d'entrée VIDE, 150 images, -b 1600** : 1 686 kbit/s (par seconde 1983, 1624, 1698, 1635, 1542, 1630),
  3 I + 147 P, 0 échec, **0 erreur de décodage**, image correcte. L'encodeur ne dépend plus d'aucune capture.
- Remarque : en P, la taille saute d'environ ×2 entre QP 34 et 35 (≈ 10 Ko / 5,5 Ko), avec la table du vendeur comme
  avec la nôtre : un seuil du cœur, à comprendre ; le contrôle de débit oscille entre les deux.

## 2026-11-07 10:45 — encodeur libre : SOUS-FLUX H.264 640x360 SANS LE VENDEUR (testeur, .11)

- **Captures du sous-flux** (`h265-step2.sh capture`, `H265_WIDTH=640` : libakuio `AKUIO_CAPTURE_WIDTH` ne garde que
  les listes d'une image de 640 de large ; tc100_rtsp `RTSP_SAVE_FRAMES` enregistre aussi les images du sous-flux,
  `f.sub.<n>.h26x`) : le même cœur, la même liste ; `slice_type_c` = 0 pour H.264, comptes de macroblocs, flux dans
  les mots 0x3c-0x3f seulement ; tampon « work » = les 52 × 4 poids seulement (calculé, identique au vendeur) ; table :
  octet 18 = 0x1f en IDR. En-têtes SPS/PPS/tranche (`avc.h`) : les octets du vendeur (test `H264liveDry`).
- **Les listes seules bloquent le cœur** (pas d'interruption). `src/h265enc/venctrace/` (portage 3.0 du traceur 2.x,
  `h265-step2.sh trace`) a montré la séquence H.264 : masque 0x8014 bit 2, horloge 0xc004 bit 15 à zéro, adresse +
  0x8084 = 2 puis adresse + 0x8084 = **8**.
- **`h264live` sur la .11** (`h265-step2.sh live264`, depuis le sous-canal de l'ISP, aucune bibliothèque ni donnée du
  vendeur) : 50 images à QP 32 puis 150 images `-b 250` (IDR toutes les 50) : **0 erreur de décodage**, image correcte,
  3,7 ms par image sur le cœur, 274 kbit/s pour 250 demandés (le QP alterne de 3 d'une image à l'autre : pas du
  contrôle de débit trop grand pour des images de 1 Ko, à régler). Vidéo et Wi-Fi revenus après chaque essai.
- Reste : intégrer les deux encodeurs libres dans tc100_rtsp (corrections couleur, RTSP, enregistrement, Frigate).

## 2026-11-07 11:25 — encodeurs libres DANS tc100_rtsp : `RTSP_FREE_ENC=1` (testeur, .11)

- **Quoi** : `src/h265enc/freeenc.h` (forme bibliothèque de h265live / h264live) derrière les appels de la bibliothèque
  du vendeur dans tc100_rtsp. Avec `RTSP_FREE_ENC=1` et H.265 1920x1080 + sous-flux H.264 (ou sans sous-flux), les
  bibliothèques du vendeur (`libakv_encode`, `libmpi_venc_ex`, `libplat_*`) **ne sont pas chargées** ; libakuio reste
  (pool, attente d'interruption). Autre configuration : la bibliothèque du vendeur, journalisé. **Désactivé par
  défaut** (rien ne change sans la variable).
- **Test .11** (`h265-step2.sh free`, mêmes arguments et réglages que le service, JPEG du web, amorce H.264, sous-flux) :
  flux principal 150 s par RTSP/TCP : 3 463 images, **0 erreur de décodage**, 1,48 Mbit/s pour 1,6 demandés ; 20 s :
  482 images ; sous-flux 15 s : 355 images, 0 erreur, 252 kbit/s pour 250 ; images correctes (couleurs, OSD) ; JPEG
  640x360 et 1920x1080 du web toujours faits ; 0 image en échec ; 12 % de CPU ; mémoire et Wi-Fi normaux.
  (RTSP/UDP non testable depuis la VM du Mac.)
- **Pièges trouvés** (README de src/h265enc) : libakuio ne remet à zéro l'état de fin (0x8018) que s'il a les
  registres mappés (`akuio_map_regs`, appelé par le vendeur) : sinon l'attente suivante revient tout de suite et le
  démarrage suivant bloque le cœur **jusqu'au redémarrage** (même pour le vendeur) — 4 redémarrages de la .11 pendant
  la mise au point ; masque 0x8014 bit 2 à zéro pour H.265.
- **Surveillance de 30 min (11:25 → 12:00)** : le même processus tout du long, **0 image en échec** (un encodeur
  H.265 a tenu 43 446 images d'affilée), un client RTSP branché presque tout le temps (pas le testeur), RSS 1,3 Mo,
  mémoire et Wi-Fi normaux (ping 4 ms) ; capture de contrôle de 60 s : 1 453 images, 0 erreur, 1,56 Mbit/s. Service
  normal (vendeur) remis ensuite : `restore` l'avait relancé trop tôt (l'ancien processus pas encore fini, le service
  trouve la caméra occupée et s'arrête) : relancé à la main ; le script attend maintenant la fin du processus.
- **À tester ensuite** : plusieurs heures (surveillance comme pour les rc), Frigate réel, enregistrement sur carte SD
  (la .11 n'a pas de carte), ABR, nuit / noir et blanc, puis en faire le défaut dans une rc.

### [freeenc-multires] Free encoder H.264 1080p, H.264/H.265 720p & musl build (`tc100_rtsp-musl`) — `passed` (2026-11-07, IPCAM2, see rc34 below)
- **What:** Item #62 (62.1 & 62.2):
  1. `src/h265enc/freeenc.h` (`fe_open_wh`) and `src/h265enc/listgen.h` now support **H.264 1920x1080**, **H.264 1280x720**, and **H.265 1280x720** in addition to H.265 1920x1080 and H.264 640x360, covering 100% of `tc100_rtsp` main/sub stream combinations under `RTSP_FREE_ENC=1`.
  2. `make -C src/tc100rtsp musl` builds `tc100_rtsp-musl` against `musl 1.2.4` (`src/musl.mk`) with `libakuio.c` linked directly in (no uClibc loader, no `stubs.c`, no `dlopen` of vendor `.so` blobs; `free_enc` turns on automatically when `libakuio` is built in).
- **Switch:** `RTSP_FREE_ENC=0` (keeps vendor encoder on the standard `tc100_rtsp` binary).
- **Test:**
  1. With `RTSP_FREE_ENC=1` in `/mnt/config/rtsp.env`, test main stream in **H.264 1080p** (`-c h264`), **H.265 720p** (`RTSP_WIDTH=1280 RTSP_HEIGHT=720 -c h265`), and **H.264 720p** (`RTSP_WIDTH=1280 RTSP_HEIGHT=720 -c h264`), verifying `ffmpeg -v error` decoding (0 errors) and bit rate accuracy.
  2. Run `tc100_rtsp-musl` on the camera: verify `/proc/$(pidof tc100_rtsp-musl)/maps` has zero `/vendor/*.so` or `uClibc` mappings, measure PSS saving (`awk '/^Pss:/ {print $2}' /proc/<pid>/smaps_rollup`), and verify streaming + sub-stream + hardware JPEG snapshots.
- **Pass:** 0 decode errors across all 4 main stream modes (H.265 1080p/720p, H.264 1080p/720p) + H.264 360p sub-stream; `tc100_rtsp-musl` runs purely on `/lib/ld-musl-arm.so.1` with ~1-1.5 MB lower PSS.

## 2026-11-07 14:30 — 3.0.1-rc34 : tc100_rtsp en musl, encodeur libre par défaut, AUCUNE bibliothèque du vendeur (testeur)

- **Demande du propriétaire** : tous les derniers commits, l'encodeur libre activé par défaut, sans les bibliothèques
  propriétaires, CI verte avant déploiement.
- **Quoi** : la release embarque `tc100_rtsp` compilé contre musl (la libc de la caméra) avec libakuio intégré et
  `freeenc.h` actif par défaut ; `libakuio.so` n'est plus livré ; `autorun-linux66.sh` et `rtsp-launch.sh` ne
  demandent plus `/mnt/lib/libmpi_venc*.so` ni le chargeur uClibc ; `flashmode-prep.sh` ne lie plus `/vendor/lib/*` dans
  `/mnt/lib` (la partition vendor n'est lue que pour `isp.conf`). Sous-flux H.265 demandé : codé en H.264 (journalisé).
  La compilation musl de tc100_rtsp (#62.2, retirée de la CI à 9822651 faute des en-têtes du noyau) marche : en-têtes
  V4L2 / ALSA / pilote ajoutés à la sysroot musl (`build-musl.sh`) ; test `Tc100RtspMusl` (qemu, libc.so seule).
- **Testé sur la .11 avant la release** (binaire musl lancé à la place du service, `h265-step2.sh free`) : seul
  `/lib/libc.so` dans `/proc/<pid>/maps` ; 1080p H.265 + sous-flux H.264 + son A-law : 0 erreur ; **720p H.265,
  1080p H.264, 720p H.264** (les listes de l'implémenteur, jamais passées sur caméra avant) : 240 / 232 / 251 images
  en 10 s, 0 erreur de décodage, images correctes ; JPEG du web faits ; 0 image en échec.
- **CI verte** sur eeaa57d (CI + noyau/release) ; paquet de cette construction : `tc100-3.0.1-rc34-update.tar`
  md5 `da12f22ebc2211d8af68d53070effca0` (contrôlé : `tc100_rtsp` musl, `libc.so` seule, pas de `libakuio.so`,
  `/vendor/lib` plus lié), `-sd.zip` md5 `da32431b0fb7ae908a7b3d5366636d53`. Le tag `v3.0.1-rc34` n'a pas pu être poussé
  depuis la session du testeur (le proxy git refuse les tags) : à pousser par le propriétaire (`git tag -a v3.0.1-rc34
  eeaa57d && git push origin v3.0.1-rc34`), la CI publie alors la release.
- **Retour arrière** : la mise à jour rc33 (le vendeur reste dans la partition vendor, intacte).
- **À tester après installation** : démarrage depuis la flash, vidéo et son, Frigate, enregistrement SD, nuit / N&B,
  surveillance de plusieurs heures. L'installation neuve (`install66.sh`) copie encore les bibliothèques du vendeur dans
  la partition vendor (inutilisées) : simplifié dans la `3.0.1-rc35` ci-dessous.

## 2026-11-07 15:30 — 3.0.1-rc35 : installation allégée sans copie des bibliothèques vendeuses (`[novendor-install]`, item 62.3)

- **Décision du propriétaire** : conserver la table de partitions Flash intacte (zéro risque pour `restore-stock.sh`,
  `cfga`/`cfgb` et les mises à jour OTA) et alléger l'installation en retirant la copie des 15 bibliothèques
  propriétaires de `stock-hook.sh` et `install66.sh`.
- **Quoi** :
  - `v3/install/stock-hook.sh` ne copie plus les 15 bibliothèques `.so` du firmware d'origine vers `lib/` sur la carte SD
    (seul le fichier de calibration capteur `isp_f23*mipi*.conf` est copié dans `config/`).
  - `v3/install/install66.sh` construit désormais `vendor.sqfs` uniquement avec `isp.conf` (~12 Ko compressé, 3 secteurs
    Flash au lieu de ~900 Ko / ~230 secteurs), car `isp.conf` fait 69,5 Ko brut et ne rentre pas dans les slots
    `cfga`/`cfgb` de 36 Ko (qui l'excluent volontairement).
  - Pour les caméras déjà en Flash (`.11`, `.24`), la mise à jour web `tc100-3.0.1-rc35-update.tar` met à jour `stack`,
    `kernel` et `initrd` tout en continuant de lire `/vendor/isp.conf` en lecture seule depuis la partition `vendor`.
- **Interrupteur** : revenir au commit précédent de `v3/install/{stock-hook,install66}.sh` si l'on souhaitait restaurer
  les bibliothèques vendeuses lors d'une installation SD.
- **Test** : vérification CI complète (`tests`, `build-kernel-linux66.yml`, génération de `tc100-3.0.1-rc35-update.tar`
  et `tc100-3.0.1-rc35-sd.zip`). Validé en production sur les deux caméras (`.11` IPCAMERA2 et `.24` IPCAMERA1).

## 2026-11-07 19:45 — 3.0.1-rc36 : installation SD accélérée (`[fast-install]`) & documentation 100 % libre
- **Quoi** :
  - `v3/install/install66.sh` : lorsque la copie intégrale vérifiée de 8 Mio (`tc100-3/backup/flash-stock.bin`, contrôlée par `restore-stock.sh --check` : taille, MD5, secteurs `boot` et `mac` de cette caméra) est présente sur la carte SD depuis l'étape 1, l'installation à la Flash ne relit plus une seconde fois les 5,7 Mio des partitions `vendor`, `stack`, `kernel` et `initrd` via `-b $K/backup` avant d'écrire (gain d'environ 1 min 30 s d'accès SPI lent ; la vérification MD5 après écriture de `flashw` reste entière). Si `flash-stock.bin` est absent, la sauvegarde par partition `-b $K/backup` est conservée automatiquement.
  - Mise à jour de `CREDITS.md`, `docs/linux-port/README.md` et `v3/install/RELEASE-NOTES.md` pour refléter l'architecture 100 % libre (`freeenc.h` + `musl`, zéro bibliothèque `.so` propriétaire chargée ni copiée).
- **Interrupteur** : `INSTALL66_FORCE_PART_BACKUP=1` force la sauvegarde par partition `-b $K/backup` même en présence de `flash-stock.bin`.
- **Test** : tests unitaires (`tests/test_hwinventory.py`, `tests/test_feat30.py`, `tests/test_flash_image.py`) et CI complète.

## 2026-11-08 08:25 — bilan du matin, encodeur libre sans vendeur sur les deux caméras (testeur)

- **.11 : 3.0.1-rc36**, en marche depuis 12 h 04 ; **.24 : 3.0.1-rc35**, depuis 15 h 10 (installées par le
  propriétaire ; la surveillance rc32 de la .24 est donc remplacée par celle-ci). Aucun redémarrage, aucun oops ni OOM.
- `tc100_rtsp` musl sur les deux : seul `/lib/libc.so` dans `/proc/<pid>/maps` (aucune bibliothèque du vendeur ni
  uClibc) ; encodeur libre : **0 image en échec** dans les journaux (un encodeur H.265 de la .11 fermé après
  12 061 images, celui de la .24 après 7 218, tous à 0 échec). Mémoire disponible environ 23 Mo sur les deux.
- Capture RTSP de 10 s sur chacune : 102 images (10 i/s, éclairage faible), **0 erreur de décodage**. La .11 en mode
  nuit, la .24 en mode jour. Un client RTSP branché sur chacune.
- Wi-Fi : .24 0 % de perte vers la box ; .11 une rafale à 90 % de perte au premier essai, puis 0 % sur 30 et 10 pings
  (à surveiller ; signal -31 dBm, donc pas un problème de portée).
- Point de 08:30 (prévu pour la surveillance rc32, devenue sans objet) : dans `reboot-history.log`, seulement les
  redémarrages demandés par les mises à jour web (.11 : rc34, rc35, rc36 le 7 ; .24 : rc35 le 7 à 16:12) ; aucun
  segfault ni OOM ; `tc100-logfwd` en marche sur les deux ; `watch7.sh` n'est plus lancé (perdu au redémarrage de
  mise à jour, non relancé : la surveillance de 7 jours de la rc32 est terminée par les mises à jour).
- 2026-11-09 08:45 : surveillance annulée par le propriétaire (« Annule la surveillance ») ; les points quotidiens programmés (jours 4 à 6 et bilan du 13) sont supprimés.

## HW-10 — IR-cut polarity (2026-11-12)

- Found on the .11 (rc37): night picture dark (luma 23-37 at full gain), IR LEDs off / on changed nothing, filter "in"
  gave luma 136-198 at half the gain: the pulses were reversed. The .24 already had `IRCUT_DAY_GPIO=592` /
  `IRCUT_NIGHT_GPIO=593` in boot.conf. Fixed on the .11 the same way (owner's OK, backup `boot.conf.bak-20261112`,
  saved to flash) and made the board default on DEV.
- To check: the .11 next evening (night picture as bright as the .24's, one click at the switch), the morning switch
  back to day (true colours, no pink cast), and after the next DEV install on a camera without the boot.conf lines.
- 2026-11-12: night picture right after the fix (luma 115-136 at half the gain); with `DAYNIGHT_SOURCE=vendor` (owner's
  OK) night held, day at 06:58 UTC without a bounce; day picture in true colours (filter in): **passed for the .11**.
  Still to do: the first full night, and a camera without the boot.conf lines on the next DEV build.

## rc37 post-install checks (.11, 2026-11-12)
- `action.cgi` run on the camera with `REQUEST_METHOD=GET`: `cmd=x` and an unknown command get `405 POST required`,
  `cmd=sd_card_info` answers: **passed** (the reboot itself was not tried by GET).
- Start-up log line of the noise reduction: **passed** (HW-09).
- Day / night page save keeping `AWB_*`, `VENDOR_LOCK`, `IR_LED_REST`: covered by the host tests in busybox; not done on
  the camera (a save rewrites the whole daynight.conf from the form).

## 3.0.1-rc38 install on the .24 (2026-11-12, from 3.0.0, web update, owner)
Build: CI run 43207206200 (commit f51961d), package `tc100-3.0.1-rc38-update.tar` (MD5SUMS checked, rc38 content
checked in stack.sqfs: setconf / board profile IR-cut 592 / 593, the two lighter Wi-Fi scripts).

| check (12:28-12:31 UTC, 3-5 min after the reboot) | result |
|---|---|
| `/mnt/VERSION`, kernel | 3.0.1-rc38, kernel built 2026-11-12 11:16 UTC |
| tc100_rtsp, supervisor, mqttd, onvifd, httpfront, whep, wpa_supplicant | all running |
| stream | 1 client, 121 frames / 5 s, 0 dropped; one thread (sender thread opt-in since rc37) |
| MemAvailable | 23.9 MB |
| settings kept | `daynight.conf` still `DAYNIGHT_SOURCE=vendor`; boot.conf `IRCUT_DAY_GPIO=592` / `IRCUT_NIGHT_GPIO=593` kept (same as the new board default); no new migration line; cfg-persist `saved to cfga` |
| day / night | first log line `mode=day src=vendor` |
| noise reduction start-up log | present (HW-09) |
| `action.cgi` by GET, `cmd=x` | `405 Method Not Allowed` |

**Passed.** Still to do: the first night on rc38 (.24, `vendor`), the first full night of the .11 with its IR-cut fixed,
the night part of HW-09; the .11 itself is still on rc37.

## 3.0.1-rc39 install on the .11 (2026-11-12, from rc37, web update, owner)
Build: run 43251033795 (main, commit 09d31b8), package `tc100-3.0.1-rc39-update.tar` (MD5SUMS checked).

| check (17:11-17:13 UTC, 3-5 min after the reboot) | result |
|---|---|
| `/mnt/VERSION`, kernel | 3.0.1-rc39, kernel built 2026-11-12 15:47 UTC |
| tc100_rtsp, supervisor, mqttd, onvifd, httpfront, whep, wpa_supplicant | all running |
| stream | 1 client, 122 frames / 5 s, 0 dropped |
| MemAvailable | 23.8 MB |
| settings kept | `DAYNIGHT_SOURCE=vendor`; boot.conf `IRCUT_DAY_GPIO=592` / `IRCUT_NIGHT_GPIO=593`; no new migration line; cfg-persist `saved to cfgb` |
| day / night | `mode=day src=vendor` (lamps on: lum 8138, counts 1 062 416), filter in (ircut 1) |
| noise reduction start-up log | present |
| `action.cgi` by GET, `cmd=x` | `405 Method Not Allowed` |

**Passed.** Tonight: the first full night of the .11 with the IR-cut fixed and `vendor` (HW-10), the night part of HW-09.
The .24 stays on rc38 for one more night.
