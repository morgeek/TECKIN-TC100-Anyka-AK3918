# Release plan: 3.0.1 (2026-10-31)

**Status:** rc17 on main (`VERSION` 3.0.1-rc17 = the prepared 3.0.1 + the install with no click, the way back with
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
