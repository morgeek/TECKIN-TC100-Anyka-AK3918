# Release plan: 3.0.1 (2026-10-31)

**Status (2026-11-04 evening):** rc25 on main (`VERSION` 3.0.1-rc25 = rc24 + Wi-Fi country / earlier Wi-Fi, the MQTT
bridge in C (off by default), the fixes of the audit of 2026-11-04, the licence; kernel unchanged from rc23, initramfs
changed). rc24 is superseded: test rc25 on both cameras (test-queue.md, "Version 3.0.1-rc25"). The lists below hold
what is left.

**Earlier status:** rc17 on main (`VERSION` 3.0.1-rc17 = the prepared 3.0.1 + the install with no click, the way back with
`RESTAURER.txt` and the old tint reset, asked by the owner on 2026-10-31 evening); the tag `v3.0.1` waits for R17-01
and the owner's go. Before that, it was prepared as 3.0.1 = rc16 + the alert sound + the documentation. rc16 passed R16-01 (colours) on IPCAM2, runs on IPCAM1 (web update); R15-03 (a night) and
R15-04 (the owner's checks) were still open.

The owner's target: at most one or two more release candidates, then the release. This page is the plan; the test
results live in [test-queue.md](test-queue.md).

## Path
1. **rc13** was skipped on the camera; **rc14** = rc13 + the W-NET Wi-Fi recovery + the night parameter set fix.
   The tester runs R14-01, R14-02 and the rest of R12 on rc14.
2. **rc15**, the release candidate: the switches that passed become defaults (table below), the fixes the R12 results
   ask for, the white balance statistics offset if R12-09 finds it, the documentation for the release. The flash-only
   install (R12-08) is then the normal state: installed with `update66.sh apply` as every rc, the card optional.
3. **3.0.1**: rc15 unchanged if it passes its short check (install, speaker, one night, no card, Wi-Fi after warm
   reboots); otherwise one more rc with the fixes only, nothing new. The release is published by CI when the tag `v3.0.1` is pushed (sd.zip, update.tar,
   inventory zip, `MD5SUMS.txt`): **the owner gives the go for the tag** (it publishes the files).

Nothing in this path writes U-Boot, `boot`, `mac` or `env`. Every flash write is the usual `update66.sh` (dump first,
`flashw` with read-back, settings kept) with the owner's agreement.

## Defaults for rc15, from the R12 / R14 results

| Test | If it passes (rc15 default) | Where | If it fails |
|---|---|---|---|
| R12-04 speaker | already the default (bug fix) | patch 0009 | `spk_active=1` / rc11 kernel; push-to-talk listed as not working |
| R12-01 / R14-02 night parameter set | **on (done, R14-02 passed)** | `NIGHT_STYLE` default 1 (rtsp-launch.sh, state.cgi, action.d/video.sh) | off by the switch |
| R12-02 low light 10 fps | **on (done in rc15, passed)** | `LOWLIGHT_FPS` default 1, same three places | off by the switch |
| R12-03 stock day / night method | default source `vendor` (needs R12-02 and live white balance counts, R12-09) | `DAYNIGHT_SOURCE=vendor` in the daemon, state.cgi, action.d/video.sh | luminance stays the default |
| R12-05 IR LED protection | already on | daemon | `IR_LED_MAX_ON=0` default |
| R12-06 IR-cut pulse 10 ms | **10 ms (done in rc15, 20 / 20 heard)** | `bin/setconf` default | `IRCUT_PULSE_MS=150` |
| R12-07 web page | fixes of what the owner saw | page / CGI | |
| R12-08 no SD card | the documented normal use | README | the fault fixed in rc15 |
| R14-01 Wi-Fi recovery | already on (only acts without `wlan0`); GPIO 11 confirmed; one clean restart when the link is slow after a power cycle (prepared) | scripts | `WIFI_POWER_GPIO=0` (re-probe only) |
| R12-09 / R15-01 white balance statistics | found (word 1160); live counts for `/tmp/cam_awb` and day / night; the algorithm kept as rc14 (rc15 went blue: `ak_isp.awb_live=1` to retry) | patch 0006 | the software white balance stays on |
| R11-01 smart mode | not in 3.0.1 (stops the encoder with the 9600K pool) | | |
| P-08 VBR | on, if R12-07 shows no loss with Frigate | `rtspserver.conf.dist` [0] `vbr=1` | CBR stays |

## Release checklist (rc15)
- `VERSION` 3.0.1-rc15, then 3.0.1; `CHANGELOG.md`: one "3.0.1" section gathering rc1-rc14 for users (what changed
  since 2.x / since 3.0.0), the rc details below it.
- `README.md`:
  - "Is it safe?": update from "nothing of the SD install has run on a camera" to what was run (IPCAM2: SD hook
    install 2026-10-24, flash updates rc5-rc13, the no-card test R12-08), and what still was not (a second camera, a
    power cut during the environment write, `restore-stock.sh` on a real camera).
  - "What you can do": speaker / push-to-talk / two-way audio as R12-04 says; anti-flicker (camera default 50 Hz);
    day / night (the default source); bit rate mode; frame rate default; no smart encoding.
  - "What 3.0 does not do": remove what now works, add what does not (from R12).
- `v3/install/RELEASE-NOTES.md`: the GitHub release text (install, update, way back), checked against the README.
- `docs/known-issues.md`: the 3.0 section rewritten from the R12 results (the feature audit of 2026-10-26 is history).
- The OpenIPC forum post #2639: a draft only, without mentioning 6.6 (owner's rule).
- The tester's camera: card test files renamed into one `_archive_rc` folder (no deletion without the owner's OK).
- CI green on the tag commit; `local-ci.sh all` before.

## To fix before the final 3.0.1 (tester findings on rc21-rc23, 2026-11-03)
Details and measurements: `test-queue.md`, entries of 2026-11-03 (rc20-rc23). Tick when fixed and retested on both cameras.
- [x] **JSON import "empty body"**: in fact the import took ~40 s and the tester's client gave up at 30 s. Now ~12-15 s (one pass per file, `tc_apply_edits`; validation reads each file once). Fixed 2026-11-04, retested on the .11 (same result, invalid import still refused as a whole).
- [x] **`syslog/host` differs between the two cameras** (.11 = 192.168.1.23, .24 = 192.168.1.22): not a fault, both addresses are the same Synology (owner, 2026-11-04); nothing to align.
- [x] **.24 frame rate in the evening**: not a bug, the "10 fps in low light by day" mode (README). `ffprobe` showed 10/1 on the .24.
- [x] **CI red** (`has-text-weight-semibold` purged from Bulma): purge re-run, bundle rebuilt (2026-11-04). Green CI is required on the tag commit.
- [x] **AE overshoot after boot** (.11, rc20: picture almost white about 7 minutes after boot, back to normal by itself): not seen again by the owner since (2026-11-04), treated as an isolated case; reopen if it comes back (criterion: luma below 200 within 30 s after boot).
- [x] **mDNS**: on by default since rc23; unicast answer verified on both cameras, `<name>.local` confirmed by the owner (2026-11-04).
- [ ] Still to run on both cameras before the tag: tamper alarm with the owner's hand, a real night (day/night switch, colours back in the morning, IR off behind glass), SD card tests on the .24, notifications, flash write frequency of `awb.state` through cfg-persist.

## Added by the audit of 2026-11-03 (`audit-2026-11-03.md`)
- [x] **Values written unquoted into shell-sourced files**: the settings page, Home Assistant pairing and Telegram now refuse spaces, quotes and `$ ` \ ; & | < > ( )` in the MQTT user/password and Telegram token/chat id (`sourced_value_ok` in action.cgi); the wizard no longer keeps `( )`. Retested on the .11 (`a b` and `$(reboot)` refused). The JSON import already wrote them quoted.
- [x] **Reported frame rate wrong**: `frigateyaml`, `integrationmanifest` and `integrationtest` did not load rtspserver.conf before `read_rtsp_stream_summary` (defaults: 15 fps). Fixed and retested on the .11 (25 fps reported). The README "15 by default" is right (`[0] fps=15` in the .dist).
- [x] `frigateyaml`: camera password in clear by default; use `{FRIGATE_RTSP_PASSWORD}`. Fixed in git 2026-11-04 (README says where to set it); to check in rc24.
- [x] **No LICENSE file**: `LICENSE` = GPL-2.0 (owner, 2026-11-04), consistent with the kernel patches and `libakuio`; README and `CREDITS.md` say so.
- [x] `CREDITS.md`: Thingino row fixed, prebuilt programs listed, origin and licence of the four written down (2026-11-04): `rwconf`, `getflag`, `getimage` = public-domain (Unlicense) sources in anyka-v4l2rtspserver; `monvifd` = binary by the same author, no source, no licence.
- [ ] Optional, after 3.0.1: rebuild `rwconf` / `getflag` / `getimage` from source in CI; replace `monvifd` by an open WS-Discovery responder (ONVIF is off by default, so the binary only runs when the user switches it on).

## Added by the night test of 2026-11-03/04 (test-queue.md, 2026-11-04 08:40)
- [x] Night stability: no reboot, no memory drift, day/night switch and morning colours OK on both cameras.
- [ ] **Wi-Fi drops**: the gateway did not answer 2 pings in 11 % (.11) and 7 % (.24) of the samples, all night long, independently on each camera (power save off, strong signal on the .11). Try `RTSP_PACING_US` / `RTSP_SNDBUF` on one camera for a night, then regulatory domain / driver options. Regulatory database + country setting (`WIFI_COUNTRY`, Settings → Network) and no more `udhcpc` restart at boot: prepared 2026-11-04 (`[wifi-country]`, test-queue), to test.
- [x] `wifi-quality.sh` stops writing its log (.11, since 20:13 UTC) while its processes keep running; its RSSI is still wrong (use `iw dev wlan0 station dump`). Fixed in git 2026-11-04: `iw` and `ping` under `timeout`; the signal is iw's `signal avg`, shared with every reader through `scripts/wifi-signal.sh` while fresh. To check in rc24.
- [x] `health.cgi` shows `memory-guard` stopped on the .11 although it is in autostart. Not a failure: its switch is `MEM_GUARD_ENABLE` (0 by default, one switch per service). `health-probe.sh` now says `disabled` for a service switched off, so it no longer counts as a restart. To check in rc24.
- [x] SD card "not properly unmounted" after a deliberate reboot (.24): the reboot path (`reboot-tracker.sh intent`) pauses the recorder and remounts the card read-only, the web update too (2026-11-04). A plain `reboot` over ssh is not covered. To check in rc24.

## Added by the audit of 2026-11-04 (`audit-2026-11-04.md`)
- [x] H1 RTSP stale buffer after an interleaved frame, W1 reflected / stored XSS, W5 open web interface without a password in safe mode, B2 console and password back before the Wi-Fi, CI hardening (tag must match `VERSION`, local CI must run the Python tests, triggers, busybox in GitHub host tests): fixed in git, to check in the next rc.
- [ ] **B1** web update: no automatic reboot after a failed flash write, retries. **Owner's decision, postponed
  (2026-11-04: "on verra plus tard")**; details in `audit-2026-11-04.md`, section 6.
- [ ] **B3** web update: `flashw -m` given the md5 of `MD5SUMS`, not of the file itself (to do with B1).
- [ ] **W4** setup wizard POST without CSRF token. **Owner's decision, postponed (2026-11-04)**: before the tag (rc26,
  with a full wizard run on a camera) or 3.0.2 as a known limit; details in `audit-2026-11-04.md`, section 6.
- [ ] **D8** documentation pass (api.md, linux-port/README.md, AGENTS.md, RELEASE-NOTES.md).
- 3.0.2: W2/R2 (`httpfront`: LAN filter and connection cap), R1 (RTSP slots), W3 (per-camera password), B4-B6, D1-D7, M1.
