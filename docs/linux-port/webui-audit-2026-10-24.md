# Web UI audit on Linux 6.6 + tc100_rtsp (2026-10-24)

Stack on the card: vendor 2.1.9 UI (commit 7fe58d5), custom httpfront, tc100_rtsp (H.265 + PCMA audio), kernel 6.6 audiofix, autorun v7.
Trigger: user found no MQTT password field and asked to check every page and feature.

## Fixed (on the card; repo copies in v3/linux66-sd/ and v3/autorun-linux66.sh)
| Item | Cause | Fix |
|---|---|---|
| MQTT password field missing; settings lost on save | old settings.html / action.cgi | password column + keep-existing defaults + `mqtt_discovery` alias patched on the card stack |
| MQTT bridge: 4 duplicate processes, stale pid, "Arrêté" | repeated starts, small `sh` killed by OOM | stopped all, one clean start; pid file right; Services shows "En marche" |
| Services/daemons killed at random (mqtt bridge, auto day/night) | OOM killer fired with ~6 MB free: watermark boost 4 MB + high-atomic reserve 4 MB; the failing allocation is GFP_HIGHUSER (pipes), cannot use the 5 MB of free CMA | `vm.watermark_boost_factor=0`, `min_free_kbytes=1024` (autorun 0a). 45 s CGI burst: 0 kills |
| SD card "aucune", 0 MB (status line, Enregistrements, dashboard, Réglages) | `df -k /mnt` prints mount point `/mnt/sd` (card mounted twice); sd-card.sh only works in flash mode | parsers accept `/mnt/sd`; `sdinfo-sd.sh` feeds `/tmp/sd-card` |
| Flux vidéo "Apply", Services start/stop of rtsp-h26x would run the vendor server | vendor `rtsp-h26x` script | shim `rtsp-h26x` + `rtsp-launch.sh` (codec, bit rate, port from rtspserver.conf); vendor copy kept in tc100test/ (not in controlscripts: Services listed it) |
| Audio page mic level had no effect | conf_audioin only writes rtspserver.conf | launcher sets codec "LineIn Capture Volume" from `volume` |
| Auto day/night daemon not running | killed by OOM | restarted (autorun step 9 already starts it); uses its own luma thresholds 40/100 (not the UI thresholds) |
| tc100_rtsp/codec override at every boot | autorun forced codec from rtsp.codec | only seeds the conf when `config/rtsp.codec` exists |

## Verified OK
IR LED (sysfs `leds/ir`), IR-cut (gpio 592/593 pulse, status toggles), image preview (currentpic.cgi 1920 px), Jour/nuit thresholds displayed (6000/1500, 160000/10000), Audio page, Services list/status, recorder (ffmpeg-min-recorder on rtsp://127.0.0.1/video0_unicast, motion-activated, idle), RTSP restart from shell shim (HEALTHY).

## Not working / not available on this stack
- Black and white, live image tuning, privacy masks, thresholds applied to the ISP: need the vendor ISP daemon (`setconf` returns 0 but nothing reads it; /var/run/vday absent).
- Motion detection (event MQTT, photo on motion), local MP4 backup recording (REC_LOCAL): in the vendor RTSP server. Frigate does detection/recording.
- Flux vidéo resolution / fps / sub-stream fields: tc100_rtsp is fixed (1080p main, 352x200 JPEG pictures; fps nominal 15, ~10 reached).
- Service "Démarrage" toggles (button-actions, ftp-server, health-snapshot ...) show on but the 6.6 autorun does not read them.
- Dashboard: "Firmware –", "Réglages (flash) 0/0", version n/d, Wi-Fi shows -256 dBm (UI reads the noise column; /proc/net/wireless level is -40).
- "Format or set up" button (Système) would format the boot card: hide before release.
- Green/yellow colour cast on the picture (ISP colour tuning).

## Open measurements
- tc100_rtsp: one thread, ~50 % CPU in user mode (10 s sample), ~10 fps encoded for 16 configured; recorder adds ~14 %. Whole SoC at ~100 % busy. Candidates: 3 MB frame memcpy per frame from the V4L2 buffer, JPEG snapshot every 2 s even with nobody watching, STAT/encoder prints on the UART (rtsp.debug present). Needs a profile build.
- Still to review: Enregistrement, Réseau, Intégrations (needs the user's MQTT password), Système, Mise à jour, Diagnostic, Journaux, Éditeur, wizard.
