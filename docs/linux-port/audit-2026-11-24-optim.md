# Audit of the C optimisation code, 2026-11-24

Read-only audit of the C programs that were written to save CPU, RAM, forks or flash on the camera (ARM926 400 MHz,
64 MB, uniprocessor, HZ=100, no vDSO): is each optimisation correct against what it replaced, robust, worth its
complexity, and still used? Three parallel reviews (Opus): video core (`src/tc100rtsp`, `src/h265enc`, `src/libakuio`),
network daemons (`src/httpfront`, `src/onvifd`, `src/mqttd`, `src/mdnsd`, `src/whep`), system programs
(`src/supervisord`, `src/logfwd`, `src/rwconf`, `src/netacl`, `src/jpegenc`, `src/ispflip`, `src/ispfps` (removed 2026-11-25), and the
fork-free scripts `memwatch.sh` / `health-snapshot.sh`). Findings of `audit-2026-11-16.md` are not repeated. Nothing
was run on a camera; costs marked "estimate" are from reading the code. The four bugs of section 1 were re-checked by
the main session in the code.

## 1. Bugs (confirmed in the code)

| # | Program | Bug | Scenario | Fix |
|---|---|---|---|---|
| B1 | `onvifd` | **Password change not seen.** `user.pwd` (and `rtspserver.conf`, `boot.conf`) are read only at start and on SIGHUP (`onvifd.c:376-383`, `:1939`); nothing sends SIGHUP, and `set_all_password` (`scripts/action.d/system.sh:254-276`, also the config import and the wizard) restarts ftp, telnet and rtsp, not onvif. | The owner changes the password to lock someone out: the old one keeps working on ONVIF (profiles, stream URIs) until onvif restarts or the camera reboots; an NVR with the new one gets NotAuthorized. First install: onvifd started before a password exists stays open after the wizard sets one. | Re-read `user.pwd` when its mtime changes (one `stat` per authenticated request, as `tc100_whep` reads it per request), and/or restart onvif from `all_password` and the stream-apply path. **Security: first.** |
| B2 | `tc100-supervisord` | **Sound never starts a recording with `REC_WHEN=motion`.** `sd_rec_motion()` reads `boot.conf` into 16 KB (`supervisord.c:1115`); `boot.conf.dist` is 23 773 bytes and `REC_WHEN=` is at byte 16 461. | `REC_LOCAL=1`, `REC_WHEN=motion`, sound detection on, C supervisor (default): `/tmp/motion_detected` is never touched on a sound event. The shell version works. Tests use a 2-line `boot.conf`. | Line-by-line reader without a size limit (or ≥ 64 KB), and a test on the real `boot.conf.dist`. |
| B3 | `onvifd` | **Same class: `boot.conf` read into 8 KB** (`onvifd.c:318`). `RTSP_LITE_TALK=` (byte 19 177) is never seen; `RTSP_SUBSTREAM` / `RTSP_AUDIO` (7 318 / 7 335) are ~850 bytes under the limit. | Two-way audio turned off in Settings: ONVIF still advertises AudioOutput / AudioDecoder. A few hundred more bytes of comments in `boot.conf.dist` would silently re-enable the sub stream and audio in ONVIF. | Same reader as B2; a CI test that every C reader of `boot.conf` sees its keys in the real `boot.conf.dist`. |
| B4 | `tc100_rtsp` | **The user's HUE is lost after the first day/night switch.** When the ISP takes the hue, `p_hue` (the setting and the "CPU table needed" flag at once) is set to 0 (`tc100_rtsp.c:999`); the next `tune_dirty` (every black-and-white switch, `:4750`, `isp_bases_reset` `:1303`) applies `hue_want = p_hue` = 0. | `ISP_TUNE=1`, `HUE≠0`: from the first dawn the day picture has no hue, `isp_tune.status` shows `HUE=0`, until a config file changes; then up to ~7 frames get the hue twice (CPU table + ISP). | Keep the setting (`hue_cfg`) apart from the CPU-table flag (`hue_hw == 1 ? 0 : hue_cfg`). |
| B5 | `httpfront` | **Native `isp_tune` differs from `state.cgi`** (`poll.h:434`, `:520`): a missing key gives `0` (shell `null`), an out-of-range value `null` (shell prints it), `EXPOSURE_MAX_PCT=0` gives `null` (shell `0`). | The Image sliders show 0 instead of "unset"; the web UI and the MQTT `isp/state` (shell) disagree. | Copy `_isp_num` exactly. See T1: the parity test never runs. |

## 2. Risks

| # | Program | Risk | Fix |
|---|---|---|---|
| R1 | `tc100_rtsp` | **Encoder motion detection (`RTSP_MD_ENC`, default on) can stick "motion on" after a budget step.** R1 (`fe_set_fps`) multiplies the per-picture budget at night (10 fps), in low light and at the idle rate; in CBR the P frames grow to it, and `md_enc_frame` only learns frames under its threshold (`:3503-3516`). CBR + `mdsens ≥ 88` at night: motion all night (recordings, MQTT events); `IDLE_FPS` + a noisy scene: false events every ~10 s. | Reset `md_enc_base` / `md_enc_hits` when `fe->fps_now` changes (hook at `:4717`, as done for the smart floor at `:4734`) and on ABR steps. Camera check: an md_enc trigger right after a `capture rate N fps` line. |
| R2 | `tc100-supervisord` | **Night mode and MQTT work block the reset button.** `run(nightmode.sh)` has no timeout (`:505`, `:680`); each sound-job MQTT publish blocks up to 30 s (`:1016`). A hung `nightmode.sh` stops the button job for good (no reboot, no rescue AP; the housekeeper only checks the pid); a normal switch of a few seconds can turn an 8 s hold into the 3-7 s rescue AP. | `run()` waits with the 50 ms poll of `run_to`, samples the button inside it, and gives `nightmode.sh` a generous timeout (e.g. 120 s, then kill and log). |
| R3 | `mqttd` | **A retained command is executed at every connection** (`mqttd.c:758-773`): a retained `{"cmd":"reboot"}` reboots the camera at each connect (the dedupe state is in `/tmp`, lost at reboot): a reboot loop. | Drop command PUBLISH with the retain flag (HA buttons never retain). |
| R4 | `tc100_rtsp` | UDP pacing (`RTSP_PACING_US`, off) with the sender thread (`RTSP_SENDER_THREAD`, off) sleeps with `cl_mu` held: ~0.7 s capture stall per IDR at HZ=100. The 11-06 audit plans exactly that combination (H5). | Remove the pacing, or never sleep with the lock held. **Done 2026-11-24: the pacing is removed (`[cleanup]`, CLEANUP-1124).** |
| R5 (done 2026-11-24, `[small]`, SMALL-A-1124) | `mqtt-bridge.sh` → `mqttd` | FIFO records of 1-3 KB may take several `write()` calls through BusyBox `printf`; two publishers at once can interleave and mqttd drops the buffer (`mqttd.c:394`). Not verified on the camera's BusyBox. | Write each record from a temp file with `dd bs=4096 count=1` (as `mqtt-bridge.sh:594` does). |
| R6 (done 2026-11-24, `[small]`, SMALL-A-1124) | `tc100-supervisord` | `auto-night-detection restart` does not reset the night job in C: the flag is removed and re-created within ms, the daemon looks once a second, so `night_reset()` usually does not run (a DN-FLAP hold survives). | A nonce in the flag file, or document it. |
| R7 (done 2026-11-24, `[small]`, SMALL-A-1124) | `log-cap.sh` | `daynight.log` (rotated at 400 lines, ~160 B/line ≈ 64 KB) sits on the 64 KB RAM-log cap that trims to 200 lines: the documented "2 x 400 lines" may be cut in half. Unverified. | Exclude `daynight.log` from `log-cap.sh`, or rotate by bytes. |
| R8 (done 2026-11-24, `[small]`, SMALL-A-1124) | `rwconf` | Temp file `FILE.tmp<pid>` does not match the `*.tmp` exclusions of `cfg-persist`: a kill between create and rename saves the stray file into the flash settings slot. | Name it `FILE.<pid>.tmp`. |

## 3. Test gap

- **T1, the `poll.h` parity test runs nowhere** (`tests/test_httpfront_poll.py:246` skips without `arm-linux-gnueabi-gcc` +
  `qemu-arm`; the GitHub "Python regressions" step runs before `qemu-user` is installed; `local-ci.sh tests` installs
  neither, and `cross` runs other httpfront tests but not this one). The native daynight, hw_state, health, isp_tune and
  fullconfig routes (all on by default) never had their "byte for byte" check; B5 shows it would fail. Run it in the
  `cross` stage and in CI after qemu is installed, then fix B5.

## 4. Waste (cost estimated, not measured)

| # | Program | Waste | Fix |
|---|---|---|---|
| W1 | `tc100_rtsp` | **Privacy mode paints the chroma one byte at a time** into uncached capture memory, both pictures, every frame (`fill`, `:1697-1706`): ~1 M byte stores per 1080p frame, estimated 10-40 ms/frame (up to 15-50 % CPU at 15 fps); privacy can stay on for hours (presence profiles). | `memset(r + x1, 128, x2 - x1)` (identical output). Measure `pp_ms` with `/tmp/tc100_privacy` before/after. |
| W2 | `tc100_rtsp` | `post_awb_sample`: a signed library division per sample (16 200 per call, 2 calls/s, ~1 % CPU estimated), outside `pp_ms`. | Keep row/column incrementally (same samples). **Done 2026-11-24 (`[small]`, SMALL-B-1124):** `awb_grid_next` (`util.h`) steps column and luma offset with no division, for any width; `test_util.c` checks every sample against the old `i / W` formula on 9 sizes. |
| W3 | `libakuio` / `freeenc` | 7.4 MB zeroed twice at each main encoder open (`libakuio.c:264-269` and `freeenc.h:170`), i.e. at each viewer after an idle period. | Drop one `memset`. |
| W4 | `health-probe.sh` | `onvif` / `rtsp-h26x` `health` print `HEALTHY`, not `ok:`, so the probe runs `status` too; `ssh-server` has no pid-file entry: ~3 extra controlscript runs (each sourcing `common_functions.sh`) every 5 min. | Accept a 0 exit of `health`; add `/var/run/dropbear.pid`. |
| W5 | `httpfront` | Native `hw_state` appends an audit line on every 2 s poll (as the CGI did): `audit.log` fills in ~1 h with the Hardware page open and its 100-line rotation erases real entries (reboot, password change). | Do not audit the `ACTION_GET_READS` commands, in both paths (owner's decision). **Done 2026-11-24 `[w5-audit]`** (owner: yes). |
| W6 | `mdnsd` | 2 ioctls + hostname + 3 files read for every same-subnet query, including queries for other hosts, before matching. The header says "no version by default" but the shipped config advertises fw, load and rssi. | Build the TXT only when an answer is due; cache hostname/IP a few seconds; fix the comment. **Done 2026-11-24 (`[small]`, SMALL-B-1124):** host name, address and netmask kept 5 s; the TXT strings made only for an answer (`mdns_sd_answer_lazy`, same bytes, `test_mdns.c`); header comment fixed. The host name cannot wait for the match (the questions are matched against it): it is cached instead. |
| W7 | `onvifd` | `/tmp/rec_control` read twice a second with no PullPoint subscription. | Skip without a subscription. **Done 2026-11-24 (`[small]`, SMALL-B-1124):** polled only while a subscription exists, and once at `CreatePullPointSubscription` (its `Initialized` state is current); `tests/test_onvifd.py` (a FIFO as motion file: never opened without a subscriber). |
| W8 | `memwatch.sh` | `memory.csv` flushed twice an hour (hourly sample + `health-snapshot` flush). | Flush only from the stop path. |
| W9 | `tc100_rtsp` | `nal_copy` word path mostly not taken (the encoder output is misaligned by the slice header); musl `memcpy` is likely as fast. `live_scan` calls `mono_ms()` before its early return; three `now_us64()` in a row (`:4441-4447`). | Use `memcpy`; reuse the time values. Small. **Done 2026-11-24 (`[small]`, SMALL-B-1124):** `nal_copy` removed, `memcpy` for the encoder output and the JPEG (the pool is mapped write-combined by patch 0008, normal uncached memory: nothing needs the volatile word reads); one `now_us64()` for `lis_scan` / `live_scan` / `talk_tick` (they are at `:4300-4306`, not `:4441-4447`); `live_scan` uses its `now_ms` (same `CLOCK_MONOTONIC`). Note: the JPEG copy (`jpeg_stable`, `jbuf + 0x800` into `malloc`) was aligned, so it did take the word path. |
| W4 (done 2026-11-24, `[small]`, SMALL-A-1124) | `health-probe.sh` | `onvif` / `rtsp-h26x` `health` print `HEALTHY`, not `ok:`, so the probe runs `status` too; `ssh-server` has no pid-file entry: ~3 extra controlscript runs (each sourcing `common_functions.sh`) every 5 min. | Accept a 0 exit of `health`; add `/var/run/dropbear.pid`. |
| W8 (done 2026-11-24, `[small]`, SMALL-A-1124) | `memwatch.sh` | `memory.csv` flushed twice an hour (hourly sample + `health-snapshot` flush). | Flush only from the stop path. |

## 5. Optimisations to remove (off by default, never paid, or impossible)

| Optimisation | Why remove |
|---|---|
| `RTSP_ZEROCOPY` (USERPTR, `tc100_rtsp.c:4183-4214`) | Impossible as written: the driver needs ≥ 3 slots, the code asks 2. **Removed 2026-11-24** (kernel patch 0011 stays: no kernel change). |
| `RTSP_UDPMMSG` (`sendmmsg`) | P-09: picture artefacts. **Removed 2026-11-24.** |
| `RTSP_PACING_US` | Reverted (HZ=100); see R4. **Removed 2026-11-24.** |
| `RTSP_SNDBUF` | Never measured. **Removed 2026-11-24.** |
| `RTSP_POOLPAD` | Effectively off with the 9600K pool; HW-01b not reproduced. **Removed 2026-11-24.** |
| `/dev/mem` marker search fallback of direct capture (`:3670-3713`) | Patch 0006 provides `AK39_VI_G_PHYS`. **Removed 2026-11-24**: the ioctl is in 0006 since 2026-10-22 (4bf95cc), before 3.0.0, so every kernel this server runs on has it; the vendor 3.4 kernel never runs it (2.x branch). Without the ioctl: copy mode. |
| `RTSP_FRAMECOPY=0` and `RTSP_LIVE_DIRECT=0` paths | O-05: no measurable difference; keep the default path only. **Removed 2026-11-24** (the in-place read stays only as the fallback when the copy finds no memory). |
| Native `fullconfig` (`poll.h` route 7, ~270 lines) | Once per Settings open, already cached 5 s by the CGI; falls back on any value ≥ 24 characters (a Frigate URL already is), small semantic differences (`perf_profile`, Content-Type). |
| Native `health.cgi` (route 5) | Once per diagnostics visit; the CGI's cache path is already fork-free. Small; keep or remove. |
| JPEG luma fallback of the day/night logic (`supervisord.c:698-710`, `auto-night-daemon.sh:427-428`) | Averages JPEG header bytes, not light; `tc100_rtsp` writes `/tmp/cam_luma` on 3.0. **Removed 2026-11-24**: no file = luma 50 in both. |

To **measure** before deciding: the sender thread (`RTSP_SENDER_THREAD`, the only one with a real expected gain at ≥ 2
clients; fix R4 first and avoid its double copy), scatter-gather RTP (`RTSP_UDPSG`, with 2-4 TCP clients), AEC
(`RTSP_AUDIO_AEC`, ~5 % CPU estimated at `-Os`), smart mode, R1 (NIGHT-CEIL), BusyBox NOFORK applets (the fork-free
scripts depend on them).

## 6. Kept (measured gains)

Direct capture (pp 2150 → 3 ms / 5 s, 9.5 → 15 fps), uncached buffers with direct capture (system 50 → 19 %), ISP sub
channel (sub 1100 → 460 ms / 5 s), ISP white balance / tuning / OSD / masks (95 % CPU → 15 fps), ALSA direct + HPF + AGC
(~660 KB PSS less), httpfront native status line and `dash.cgi` (93 → 7 ms under qemu, 0.02 s on the camera), whep
on-demand start (672-876 KB PSS when no viewer), `tc100-supervisord` (PSS 226 KB vs ≥ 354 KB for the shells; no fork gain:
the shells were already fork-free, its comment says otherwise), mqttd FIFO hand-off and C discovery, the login OK cache.

**Stack protector (`[harden]`):** no hot function needs `no_stack_protector`: the per-packet canaries (`send_pkt`,
`rtp_out`, `send_nal`, `sg_pkt`, `send_frame`, `aud_send`) cost ~40 cycles per packet next to a `sendto` of tens of µs.

**Concurrency of the video core:** sound (one `cl_mu`, `sndq` never nested with it, the recording ring single-producer
single-consumer with compiler barriers, enough on this uniprocessor, the signal handler only sets a flag).

## 7. Periodic forks (default config, MQTT and tamper off; estimate)

| Source | Period | Forks/min |
|---|---|---|
| `wifi-quality.sh` (also awk-scans its 1440-line log each minute) (done 2026-11-24, `[wifiq]`, WIFIQ-FORKS: 13 pids a run before, 8 after: timeout + iw, timeout + ping, 2 mv; no awk, the last hour kept in a small window file) | 60 s | ~10-12 -> ~8 |
| `health-snapshot.sh` (+ probes, memwatch) | 300 s | ~3-4 |
| `log-cap.sh` | 600 s | ~2-3 |
| `log-persist.sh` (with a card) | 600 s | ~1-4 |
| `net-guard`, `sdinfo-sd`, web guard | 60-600 s | ~2-3 |
| `cfg-persist`, `wifi-roam.sh`, reboot-tracker, ircut, watchdogs | 30-1800 s | ~2-4 |
| `tc100-supervisord` | — | 0 steady |
| **Total** | | **~20-30** |

At 10-20 ms per fork+exec (unmeasured) that is roughly 1-2 % of the ~23 % busy; the ~13 % system time is mostly the
Wi-Fi USB PIO (~480 interrupts/s) and the video path. Cheap real measure: the `processes` line of `/proc/stat` twice,
600 s apart (forks since boot), once with the housekeeper paused. `wifi-quality.sh` is the only one worth reworking.

## 8. Proposed order

1. **B1** (onvifd password) — security.
2. **B2 + B3** (boot.conf readers) and a CI test on the real `boot.conf.dist` for every C reader.
3. **B4** (hue), **R1** (md_enc reset on a rate change), **W1** (privacy fill), **W3** (double zeroing).
4. **R2** (button blocked by night mode), **R3** (retained MQTT command).
5. **T1 + B5** (run the `poll.h` parity test, then fix `isp_tune`).
6. Removals of section 5, in one cleanup change with the test-queue entries they touch.
7. The rest of sections 2 and 4 (small), and the measurements listed in section 5.

Each fix: one change, its off switch where it changes behaviour, a test-queue entry, local CI, review for the C ones.
