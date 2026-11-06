# History of the port

History of the port, kept for reference; not the current state. Current docs: [README.md](README.md), [internals.md](internals.md), [audit-2026-11-06.md](audit-2026-11-06.md), [a-faire-implementeur.md](a-faire-implementeur.md). Statements below such as "not yet run on the camera" are as of their date and are mostly outdated.

## Linux 4.4: what was needed for frames

Found by comparing register dumps taken while the stock 3.4 firmware was streaming against the 4.4 kernel. The patch (`linux-4.4-isp-video.patch`, 4 files against OpenIPC/linux `anyka-tc100-fixes` 5b87a69) has since been removed from the tree; the git history keeps it.

1. **SYSCTRL 0x78 bits 19-24 must be clear.** The device-tree MIPI pin groups are the EV330 ones and set them on EV300; with them set the ISP never gets a frame. `REG32(AK_VA_SYSCTRL + 0x78) &= ~0x01F80000;` after the pinctrl select.
2. **JX-F23 MIPI:** 2 lanes, 768 Mbps, THS-SETTLE = the plain index 9 (D-PHY 0x40/0x60/0x80 = 0x89).
3. **Sensor init:** wait 10 ms after writes to register 0x12 (soft reset), otherwise most of the list is lost.
4. **ISP lifecycle:** `ak_camera` acquires and prepares the ISP core itself, and releases it on close so the next open re-runs the sensor init. The ISP soft reset (SYSCTRL 0x20 bit 19) comes right after the CIS sclk, only when the core is down.
5. **Tuning validator:** the real vendor files are the `4.003` layout (modules 1128 / 38 bytes) with fewer styles stored than the header count; the patch accepts them.

## OpenIPC

[OpenIPC](https://openipc.org) is the reference open firmware for IP cameras; it does not support this camera. What was learnt about it was shared in [OpenIPC/firmware#2639](https://github.com/OpenIPC/firmware/issues/2639) and in [the camera report](https://openipc.org/cameras/report/?id=r-rxh32hs4).

**Findings on the OpenIPC Linux 4.4.302 kernel, in RAM** (`docs/openipc/`, collected over the Pico 2 serial bridge):
`01-system-info.txt` (kernel, command line, cpuinfo, meminfo, mtd, iomem, interrupts), `03-gpio-pinctrl.txt`, `04-i2c-sensor-video.txt`, `05-usb-wifi.txt`, `06-audio.txt`, `07-mmc-storage.txt`, `devicetree.dts` (decompiled device tree of the running kernel). The boot log `02-dmesg-full.log` and `devicetree.tar.gz` were removed on 2026-11-06 (git history keeps them).
- `/dev/video0` appears with the OpenIPC kernel (`ak_camera`, `20000000.isp`, JX-F23 at I2C-0 0x40), with a 24 MiB capture pool at 0x81400000; real frames needed the fixes above.
- The generic `r8188eu` driver binds the RTL8188FU but the radio never locks (0 scan results); the dedicated `8188fu` driver (built out of tree; its module and workflow are not tracked here) works on 4.4. On 6.6 the mainline `rtl8xxxu` does it.
- Audio: ALSA driver `akpcm` registers; speaker amplifier gate on GPIO 14 (the report said 79, see the warning above).

**The SD boot kit** (the `contrib/openipc_sd_kit/` folder is no longer in the tree, see the git history; historical, not used by the build): `tc100test/oipc.img` (Linux 4.4 uImage), `oipcrd.gz` (musl initramfs, loaded at 0x80900000 so that the ISP's 24 MiB pool at 0x81400000 is not overwritten), `uEnv.txt`, and the tools used over the serial bridge. Its README describes a persistent dual boot written into U-Boot's environment; **for tests the RAM-only loop above is enough and writes nothing**. If you do write the environment, keep the stock `boot_normal` fallback and the SD recovery of the stock U-Boot in mind. No Wi-Fi credentials are in the initramfs: they come from `tc100test/wpa_supplicant.conf` on the card.

## Thingino

History (the folder was removed on 2026-10-27, 49a2485; 3.0 serves RTSP with its own `tc100_rtsp`): `thingino_port/` held a first Board Support Package for [Thingino](https://github.com/themactep/thingino-firmware): SoC rules (`soc/anyka/ak3918.mk`), Buildroot fragments and a camera config for the TC100 (`configs/`), two Thingino patches (`patches/`: add the Anyka vendor, disable gpio-keys), a known-good 4.4 kernel config (`kernel/`), and packages (`package/thingino-rtsp-server`, `package/thingino-webui`).

- `thingino-rtsp-server` (static ELF, about 80 KB, about 1 MB of RAM): RTSP/1.0 with CSeq tracking, SDP, RTP over TCP interleaved and UDP, RFC 2435 JPEG streams. It was the RTSP server of the first V3 builds on 6.6. Options: `-p port`, `-u user -P password` or `-c config` with `port=`, `username=`, `password=`.
- The Thingino WebUI previews through multipart MJPEG (`cgi-bin/ch0.mjpg`) and JPEG snapshots (`cgi-bin/ch0.jpg`); RTSP paths are `/ch0` and `/ch1`.
- The camera config (`thingino.json`, defconfig) now carries the verified values: GPIO table above (IR LEDs 19, IR-cut 81/80, LEDs 15/47, button 10, speaker 14, not tested), sensor at I2C 0x40, 28 MiB ISP window, 8 MB flash. The boot offsets (`uboot_env_offset`) are still unverified.
- The same RAM-placement rule applies: a root file system loaded inside the ISP pool is wiped during early boot.
## H.265 command list and self-test (2026-10-22)

- `src/h265enc/cmdlist.py` decodes and encodes the 112-word command list of the H.265 encoder and regenerates it: 0 different words over the 40 recorded frames (`python3 src/h265enc/cmdlist.py`).
- `src/h265enc/hwseq.py` models the register write sequence (H.265 clock `v | 0x8e00`) and compares it with the traces: 34/34 and 40/41 cycles.
- Still unknown: where the picture / stream sizes come from. (The physical addresses of the V4L2 buffers are available through `AK39_VI_G_PHYS`, see below.)
- `v3/selftest66.sh`: self-test run at boot when `tc100test/selftest` exists on the card (Wi-Fi, video, audio, uio0; hardware JPEG when `tc100test/selftest-jpeg` exists). Log: `tc100test/selftest-N.log`.
- CI (`build-kernel-linux66.yml`) produces the `tc100test/` folder ready to copy (oipc.img, oipcrd66.gz, jpegenc, libakuio.so, selftest66.sh, README-TEST.txt, md5sums.txt).

## Encoder access without copies (2026-10-22)

- `ak39_vi` has a private ioctl `AK39_VI_G_PHYS` (`include/uapi/linux/ak39_vi.h`): given a buffer index it returns the physical address of the Y and UV planes and the size, so the encoder can read a captured frame in place. It is in patch 0006 of the series. `tc100_rtsp` does not use it yet: it copies each captured frame into the encoder pool (one 3 MB `memcpy` per frame).
- `tests/check_akuio_symbols.py VENDOR_LIB_DIR` checks that every `akuio_*` symbol imported by the vendor libraries (`libmpi_venc`, `libplat_vi`, `libplat_venc_cb`, `libmpi_osd`) is exported by the free `libakuio`: all of them are. A run under qemu was not done: the vendor libraries need uClibc and the free library is built for glibc.
- The old `linux-6.6-ak3918-step*.patch` files are removed; the series in `patches/kernel-6.6/series/` is the only source.

## First boot of the slim 6.6 kernel with the Buildroot base (2026-10-22)

Booted from RAM (U-Boot `bootm`, nothing written to flash) with `oipc.img` (1.8 MB) and the
test initramfs built from `v3/buildroot`:

| Check | Result |
|---|---|
| Kernel, DT, serial console, SD card (FAT), USB host | ok |
| Wi-Fi RTL8188FU (`rtl8xxxu`), WPA2, DHCP (`udhcpc`) | ok, the gateway answers |
| Sensor F23 over MIPI, `/dev/video0` | registered, streamer starts |
| Audio codec (`akpcm`) | card present |
| Encoder access `/dev/uio0` (`ak39_venc`) | ok after the pool fix below |
| Hardware JPEG (`jpegenc --run`) | the core answers (IRQ, length, EOI) but the stream is **not yet valid**: see below |

**RAM budget.** With the 28 MiB CMA pool and the 12 MiB encoder pool only about 15 MB are left for
Linux (`Memory: 16480K/65536K available`). The unpacked initramfs must stay below ~7 MB (a first
8.5 MB image ended in an out-of-memory panic while unpacking), so `v3/initramfs-prune.txt` strips
curl, jq, mbedtls, ncurses, `iw` and friends from the **RAM test image only**; the flash squashfs
keeps them. Do not prune `usr/share/udhcpc` (no DHCP without it) or `usr/share/alsa/alsa.conf`.

**Encoder pool.** The 12 MiB `no-map` region cannot come from `dma_alloc_wc()` (the allocator rounds
the request up to 16 MiB, bigger than the region). `ak39_venc` now `memremap()`s the reserved region
(write-combined) and maps it to user space the same way.

**JPEG: the hardware core now produces valid pictures.** The table block (quantisation, reciprocals,
Huffman words) belongs in the *table buffer*, control word 6 (register 0x3d8), and not at the start of
the output buffer (word 7, 0x3dc) as first assumed. With the block in the wrong place the core read
nothing and fell back to whatever its internal RAM held: a header with junk DQT/DHT bodies and a
40-bit-per-MCU scan (zeroing the block changed nothing, which is how this was found). With the block
at word 6 the core writes a complete, standard JFIF file by itself: the DQT are the quality-35 tables,
the DHT the standard ones, a grey frame gives the textbook `28 a2 8a 00` scan, and a real 1920x1080
frame decodes to the picture (116 KB at quality 35, no software header needed). Free JPEG
encoding on the hardware core works from user space (`src/jpegenc`, `/dev/uio0`).

## tc100_rtsp: sub-stream, sound level, motion zones, recorder (2026-10-26)

Written and tested on the host only (`python3 tests/test_tc100rtsp.py`); not yet run on the camera.

- **Sub-stream:** a second encoder channel, 640x360, same frame rate, fed from the scaled picture that also makes
  `stream.jpg`. Codec and bit rate from `rtspserver.conf` `[1] codec` (0 H.264, 2 H.265) and `[1] bps`; off with
  `RTSP_SUBSTREAM=0` in `boot.conf` (launcher flag `-s 0`). Paths containing `video1` (`video1`, `video1_unicast`) or
  starting with `/ch1` or `/sub` serve it; every other path the main stream. Encoder fields as the vendor server
  (`AnykaCameraManager::getVideoEncodeParams`): channel 1, group 2 (`RTSP_SUB_CHN`, `RTSP_SUB_GROUP` in
  `config/rtsp.env` override). The log shows the pool use after each open; if the sub-stream does not open, or later
  gives no frames, its paths serve the main stream.
- **Sound level:** with `ENABLE=1` in `config/sound_detection.conf`, `/var/run/sound_level` is rewritten 4 times a
  second in the 2.x format `<epoch> <rms_dbfs> <peak_dbfs> <events> <last_event_epoch> <last_event_dbfs>` (RMS and peak
  of the last 0.25 s around the mean; an event per second whose RMS reaches `<file>.threshold`). `arecord` runs only
  while an audio client plays or the sound detection is on.
- **Motion:** on while `/tmp/tc100_md` exists and `mdenabled` is not 0; sensitivity from `/tmp/tc100_md_sens` or
  `mdsens`; the zones of `config/motion_zones.conf` (`MDZ1..4="x1,y1,x2,y2"`, percent) are left out of the 64x36 luma
  grid (2.x `md.c` rule: a cell is ignored when its centre lies in a zone). `/tmp/rec_control` as before;
  `/var/run/md_zones` holds the 2.x status line. The boot starts it only when `mdenabled=1` or
  `config/autostart/motion-detection` exists.
- **Recorder** (`src/tc100rtsp/rec.c`, no ffmpeg): the encoded frames go into fragmented MP4 files (the 2.x writer of `src/tc100fix/rec.c`, one fragment a second: a cut file plays up to its last second)
  `/mnt/DCIM/YYYY-MM-DD_HH-MM-SS.mp4` (the name the Recordings page lists) with a hardware-JPEG thumbnail
  `YYYY-MM-DD_HH-MM-SS.jpg` of the first keyframe next to each. Settings of `boot.conf`, read while running:
  `REC_LOCAL`, `REC_WHEN=offline|always|motion`, `REC_STREAM=main|sub`, `REC_SEGMENT_SEC`, `REC_RESERVE_MB`,
  `REC_OFFLINE_SEC`, `REC_POSTROLL_SEC`, `REC_CLIENT` (else the host of `FRIGATE_URL`). Only into a vfat/exfat card;
  the oldest recordings are deleted to keep `REC_RESERVE_MB` free; `/var/run/tc100rec.pause` (`rec-storage.sh eject`)
  closes the file and leaves the card alone; state in `/var/run/tc100rec`. Card I/O runs in a writer thread so a slow
  card never stalls the capture loop. `controlscripts/recording start|stop` sets `REC_LOCAL`.

### tc100_rtsp: sound in recordings, Listen, two-way audio, encoder library (host-tested only, not yet run on the camera)

- **Sound in recordings** (`REC_AUDIO=1` in `boot.conf`, default 1): the MP4 gets a second track, G.711 A-law, 8000 Hz mono (sample
  entry `alaw`, what ffmpeg reads), one `traf` per track in every `moof`. The 160-byte A-law chunks the RTSP audio track already
  makes are queued next to the frames (`rec_audio`); the track is a running sample count placed on the video clock at the start
  of the file and after a hole (a hole up to 2 s is filled with silence), so file and RTSP audio are the same bytes.
  `RTSP_REC_AAC=1` (`rtsp.env`, default off) turns that track into AAC-LC (`mp4a` + `esds`, `aacenc.c`: own fixed-point encoder,
  1024-sample frames, about 24 kbit/s, `RTSP_REC_AAC_KBPS` 8-48): the same A-law chunks are expanded to 16 bits and encoded, the
  first access unit is stamped one frame early (the MDCT overlap) so that the sound stays on the video clock; browsers play it.
  The microphone (arecord) runs while the recorder is on and the card usable. ffprobe/ffmpeg decode both tracks and the sound
  stays on the video clock (test: silence markers within 20 ms). In headless Chromium a `<video>` with an `alaw` track plays its
  video normally (checked with VP9 files, Chromium of Playwright has no H.264); the sound itself is not decoded by browsers, VLC plays it.
  `/var/run/tc100rec` gets `audio=alaw|off`, `asamples=`.
- **Listen in the browser:** `audio_stream.cgi` makes `/tmp/tc100_listen/<pid>.fifo` and runs `cat` on it after a WAV header;
  tc100_rtsp (`alisten.c`) opens it read-write and non-blocking and writes the microphone PCM (S16_LE, 8 kHz, mono) from the
  capture loop (drop when full, at most 3 listeners, 60 s, closed when 1.5 s of sound stays unread or the FIFO is removed).
  The microphone runs while a listener exists (10 s grace), also with `-a 0`. 503 when tc100_rtsp is not running and arecord is busy.
- **Two-way audio:** `RTSP_LITE_TALK` (default 1) and the RTSP password required. A client sending `Require: www.onvif.org/ver20/backchannel`
  gets a second `m=audio` (`PCMA/8000`, `a=control:track3`, `a=sendonly`). RTP from it (TCP interleaved on the channel given at SETUP, or UDP to
  port 5004 from the client address) is decoded to S16 and written to `sh scripts/speaker-play.sh -` (aplay `plughw:0,0`, volume
  `pttvolume.conf`, amplifier GPIO), started on the first packet and closed 2 s after the last. One talker at a time (3 s of silence
  before another may take over). `speaker-play.sh` holds `/tmp/speaker-play.lock`: while a push-to-talk clip plays the talk is dropped
  (retry after 2 s), while a client talks `upload_audio.cgi` answers 429 BUSY. A client that sets up only the backchannel gets no video.
- **Encoder library:** `libmpi_venc_ex.so`, else `libmpi_venc.so`, from the library directory; the log says which and prints `ak_venc_get_version()` when exported.
- **Host tests:** `make test_rtsp` builds the whole server without camera or encoder (`-DTC100_HOST_TEST`); `tests/test_tc100rtsp.py` runs it with a fake
  `arecord` and `aplay` (RTSP audio track, backchannel over TCP and UDP, locks, listeners, the CGI).

### tc100_rtsp: live video in the browser (host-tested, ffprobe and Chromium checked, not yet run on the camera)

The live view of the web UI had only JPEG snapshots. It now plays the H.264 stream the camera already encodes, packed as fragmented
MP4 and played with Media Source Extensions: no re-encoding, little CPU.

- **Transport (as Listen):** `www/cgi-bin/live.cgi` makes `/tmp/tc100_live/<pid>.fifo` and runs `cat` on it after a
  `Content-Type: video/mp4`, `Cache-Control: no-store` header; tc100_rtsp (`livemp4.c`) finds it twice a second, opens it
  read-write and non-blocking and writes into it from the capture loop. `live.cgi?info=1` gives the page a small JSON
  (`{"ok":1,"stream":"sub","codec":"avc1.42c01e","width":640,"height":360}`) read from `/tmp/tc100_live/status`, which tc100_rtsp
  rewrites when the live stream or its SPS changes. 415: neither stream is H.264 (the page keeps the JPEG view); 503: tc100_rtsp not
  running, SPS not known yet, or two viewers already.
- **Stream:** the 640x360 sub-stream when its codec is H.264 (`rtspserver.conf` `[1] codec 0`, the default), else the main stream when
  it is H.264, else 415. The encoder of that stream runs while a viewer exists (`live_wants()` next to the RTSP clients and the
  recorder in the `want` test of the capture loop) and stops when the last one leaves.
- **Muxing:** the init segment (ftyp + moov with avcC from the SPS/PPS of the first IDR) then one moof + mdat per frame, from the next IDR
  on. The box writers and the SPS parser moved out of `rec.c` into `mp4box.c` (names prefixed `mp4_`); the recorder's files are byte for
  byte what they were (checked old against new on H.264 and H.265, with and without sound). Sequence numbers from 1, decode times from the
  frame timestamps relative to the viewer's first frame, a frame lasts as long as the one before it. Video only (A-law is not played by
  browsers).
- **Limits:** 2 viewers; dropped when its FIFO is removed, when it has read nothing for 1.5 s (bytes written minus bytes still in the FIFO),
  when no keyframe came for 10 s, when the SPS changes, or after 10 min (`TC100_LIVE_SECONDS`); the page reconnects. What the FIFO does not
  take waits in at most 256 KB per viewer; beyond that frames are skipped until the next keyframe with the time line kept continuous. The
  capture loop never blocks.
- **Page** (`src/webui/index/30-live-view.js`, "Video / Snapshots" switch next to Resume Live, remembered in `localStorage` key
  `tc100.liveMode`): Video when `MediaSource.isTypeSupported('video/mp4; codecs="avc1.PPCCLL"')` for the codec of `info=1`; a `<video muted
  autoplay playsinline>` fed by `fetch()` + `ReadableStream` into a `SourceBuffer`; twice a second it jumps to 0.2 s before the newest frame
  when more than 1 s behind (and plays at 1.1x from 0.5 s), buffer older than 10 s is removed. It stops when the page is hidden or off screen
  or paused, reconnects when the stream ends (10 min) or breaks (3 tries), then falls back to snapshots (2 min; 10 min for 415 or a profile
  the browser cannot play). Without Media Source Extensions the switch is hidden and nothing changes. Fallback order: camera video, then
  snapshots. The "Smooth live" (Frigate) button stays as it was: it opens Frigate in another tab, so it cannot be a source inside the page.
- **Latency:** about the keyframe wait at start (up to one GOP when another client already keeps the encoder running, at once otherwise) plus
  the browser's own buffer, 0.2-1 s afterwards.
- **Tests:** `test_livemp4` (`make test_livemp4`, `tests/test_tc100rtsp.py` `LiveMux`: boxes, IDR first, sequence numbers, a real x264 stream
  through ffprobe/ffmpeg, slow, stuck and refused viewers), `LiveServer` (host tc100_rtsp fed from a file, `live.cgi` end to end),
  `tests/live-video.test.js` (fallbacks of the page code) and `tests/ui-browser/live-check.mjs` (headless Chromium against a fake camera: plays,
  jumps to the live edge, pause/hidden close the connection, reconnect, fallbacks; VP9 because the Chromium of Playwright has no H.264).

## 2.x known issues (history)

Moved from `docs/known-issues.md` on 2026-11-06. These describe the 2.x firmware (vendor kernel 3.4, lighttpd, v4l2rtspserver, getimage), not 3.0.

### Remote syslog (2.1.5)

BusyBox `syslogd -R` forwards every message it receives *before* applying its
own `-l` level and `-f` rules, which only filter the local file
(sysklogd/syslogd.c). With remote syslog on, a NAS therefore received the
kernel and daemon info/debug lines as well, and each burst line by line. From
2.1.5 syslogd only writes the local log (`/var/log/messages`, notice and above
plus logins) and `tc100-logfwd` forwards that file: one copy of a repeated
message per minute (numbers ignored, so `sjf:4619178` and `sjf:4619188` are one
message) followed by "last message repeated N times", and 60 lines a minute at
most.

A NAS rule that sends an e-mail for each received error doubles every camera
error with its own "Failed to send email" entry when its mail settings are
wrong (Synology Log Center: check the notification rule and the SMTP account).

### Reading the camera logs (2.1.2)

Logs of two cameras over a day (2026-10-16) showed that almost every line marked
"error" or "critical" was not a fault:

| What you see | What it is |
|---|---|
| `kern.err kernel: reg0x40, read:0x89`, `f22_set_power_on`, `akisp_init`, `2lane thssettle` | the sensor driver dumping its registers each time the video starts, at error priority |
| `user.emerg … encode frame type=1`, `group_type=1, index=…`, `sensor fps switch 25 to 10` | the vendor encoder library at emergency priority, at stream start and whenever a frame takes more than ~100 ms to encode. Silenced from 2.1.3 (vendor print level 1, errors only); it was flooding a remote syslog server and its email alerts |
| `user.err … ak_cmd_register_module … no server was register` | the vendor library looking for the cloud command server, which is not run |
| `user.emerg … [wait_move_stable:193] not stable` | vendor image library message every ~15 min, no effect seen |
| `RTW: …` (≈130 lines at boot) | Wi-Fi driver banner |
| `rfkill: Cannot get wiphy`, `ioctl[SIOCSIWENCODEEXT]: Invalid argument` | wpa_supplicant with the vendor driver's old interface; the camera connects anyway |
| `MTLS … fatal alert message was received from our peer` | a browser refusing the self-signed certificate until it is accepted |

The Logs page now reads the priority that syslog lines carry instead of guessing
from words, and shows these as "Vendor" instead of errors. Real faults stay
errors: SD card timeouts (`mmcblk0: timed out…`, `get_card_status wait too long`),
out of memory, kernel oops.

Found at the same time and fixed in 2.1.2:

- **Clock**: only the RTSP server had a time zone (and on a camera left on the
  template, the whole commented file as its `TZ`), so kernel and vendor lines
  in the same log were two hours apart and cron ran on UTC. `TZ` is now read
  properly and exported for every program from the start. The template's
  example was also wrong: in POSIX, Paris is `CET-1CEST,M3.5.0,M10.5.0/3`,
  not `UTC+1`.
- **False boot warnings** from flash: "/mnt has less than 4 MB free" (a RAM
  disk by design), "Self-heal skipped: missing libcurl" (not shipped) and
  "lighttpd.conf rejected" (the SD-card web config, not used from flash).
- **Sudden restarts**: on a camera with a failing SD card, the kernel's card
  driver busy-waits (`get_card_status wait too long`) until the hardware
  watchdog resets the camera — about every 1–4 hours that day. The reboot
  history now records the card state with each heartbeat (every 5 minutes from
  flash) and names it as the likely cause; web updates are recorded as
  requested restarts instead of "UNEXPECTED".

### Fixed issues (2026 bring-up)

All the issues found during the August 2026 hardware bring-up have been fixed and
verified on live cameras (PTT since 1.8.3). Kept here for the record; see `CHANGELOG.md` for detail.

| Symptom | Cause | Status |
|---------|-------|--------|
| SD card turned read-only during an update, files full of garbage | writes on the card sometimes come out with a run of zeroed pages under memory pressure; the update extracted the whole 16 MB package to compare checksums. Every written file is now checked against its md5 and rewritten, only changed files are extracted, and the code runs from a checksummed read-only image | Mitigated 1.8.4 |
| Frigate/go2rtc lost the camera 30–50 times an hour (`i/o timeout`) | `tcp_tw_recycle=1` dropped SYNs from clients behind NAT/Docker; now 0 | Fixed 1.8.4 |
| Browser warns on HTTPS; `sslv3 alert certificate unknown` in the lighttpd log | the self-signed cert was issued for 365 days and only regenerated when *missing*, so any camera past its first year served an expired certificate. It is now also regenerated when `openssl x509 -checkend 0` fails, is valid 10 years, and uses ECDSA P-256 (handshake ~0.09 s vs ~0.14 s for the RSA-1024 it replaces) | Fixed 1.8.1 |
| HA "Live" camera entity shows nothing | it points at `snapshot/last_path`, a file PATH, while HA's MQTT camera expects image BYTES. Entity now off by default (`MQTT_HA_CAMERA_ENTITY_ENABLE=1` to re-enable); use the RTSP/go2rtc stream instead | Disabled 1.6.2 |
| Dashboard liveview / snapshot blank | `/bin/timeout` is the pre-2014 busybox variant wanting `-t SECS`; `timeout 5 getimage` exec'd the duration and failed silently, so `currentpic.cgi` served a 0-byte JPEG | Fixed 1.7.1 |
| Push-to-talk is silent | two causes: `v4l2rtspserver` holds the exclusive codec device `/dev/akpcm_cdev1`, and the TC100 amplifier enable is active-low while stock `ak_ao_demo` drives it the other way. PTT now pauses RTSP only for the clip, and plays through `/mnt/bin/ak_ao_ptt`, an MD5-guarded copy of `ak_ao_demo` with the two speaker-control instructions flipped (the stock binary is untouched) — see CHANGELOG 1.8.3-rc8 → rc10 | Fixed 1.8.3 |
| Inbound HA → camera commands time out | the SUBSCRIBE path used `curl`, which can't do MQTT here; it is now forged like the publish path | Fixed 1.6.2 |
| Cameras listened on a shared command topic | 1.6.1 re-derived the topic root but left `MQTT_TOPIC_COMMAND` at its written-out default, so every camera received every camera's commands | Fixed 1.6.2 |
| Two cameras merged into one HA device | shared default `MQTT_CLIENT_ID` / topic root; identity now derives from the hostname | Fixed 1.6.1 |
| Firmware version not shown in HA | discovery device block now carries `sw` from `/mnt/VERSION` | Fixed 1.6.1 |
| Config import silently did nothing | `conf-import.cgi` used bare `tr -d '\r'` with no shim — emptied the upload | Fixed 1.6.1 |
| MQTT never reached the broker | `curl --upload-file` sends `SUBSCRIBE` not `PUBLISH` on curl 8.1.2; the bridge now forges the MQTT packets and pipes them to `nc` | Fixed 1.6.0 |
| WiFi SSID blank / reconfig ignored | read a `wpa_supplicant.conf` that need not exist; write path disagreed with `autorun.sh` | Fixed 1.5.0 |
| Dashboard buttons fail with 403 | `csrf_guard()` filtered tokens through `tr`, absent on the device — both sides collapsed to empty | Fixed 1.4.0 |
| `health.cgi` output rejected by parsers | `/proc/meminfo` values pad with multiple spaces; only one was stripped | Fixed 1.4.0 |
| First-boot wizard stuck on "Réessayer" | Same missing `tr` broke POST body parsing | Fixed 1.4.0 |

A bare `tr` in camera-side shell without the `busybox` shim in scope was the root
cause behind most of the above (2.x firmware).

A boot-time probe (`scripts/capability-check.sh`) tests these tools by **behaviour** rather than presence —
`command -v` passes for `timeout`, which exists but wants the old `-t SECS` syntax. Its verdict appears under
`capabilities` in `health.cgi`, separating `shimmed` (expected here) from `failed` (genuinely broken).

### Platform constraint: `tr(1)` was not available (2.x)

On 3.0 this no longer holds: the Buildroot base's busybox has the `tr` applet (listed in `tests/fixtures/busybox-6.6-applets.txt`) and installs its symlink (to check on a camera with `command -v tr`). The shell shims below are kept for the 2.x scripts that 3.0 still shares.

The camera's busybox includes the `tr` applet but ships no symlink for it, and `/mnt/bin` is not on the CGI `PATH`
(`/sbin:/usr/sbin:/bin:/usr/bin`). Any `tr` invocation fails with `tr: not found` (exit 127) and, in a command
substitution, silently yields an empty string — so the failure surfaces as bad data rather than an error.

`awk`, `sed`, `cut`, `grep`, `head`, `sort` and `od` are all present. Use `awk` for character filtering
(`gsub(/[^…]/, "")` replaces `tr -cd`) and for field splitting (`BEGIN { RS = "&" }` replaces `tr '&' '\n'`).

CGIs that source `func.cgi` (19 of them) and daemons that source `scripts/common_functions.sh` (including
`autorun.sh` and `mqtt-bridge.sh`) get a `tr()` shell function that falls back to `busybox tr`, so existing `tr`
calls there work. Fully standalone scripts — e.g. `wizard.cgi`, which sources neither — must avoid `tr` themselves.
Prefer awk regardless: the shim still pays one `busybox` exec per call, which matters in loops (see
`load_conf_file` in `state.cgi`).

When testing a `health.cgi` change, clear `/tmp/health_snapshot.cache` first: responses are cached for the snapshot interval plus 15 s (75 s by default), and a
stale entry looks exactly like a fix that did not take.

## Cameras installed by hand on 2026-10-24 (summary)

The author's two cameras were the first ones moved to the SPI flash, before the one-click install existed. They had a
single 3.7 MiB `stack` partition with the vendor libraries inside, and the boot commands `flashload` / `flashboot`
added to the U-Boot environment by hand (`flashload` reads 0x1ce000 bytes of the kernel; CI warns when the kernel
grows past that). They were moved to the layout with a `vendor` partition through the normal route: new SD package
(keeping the card's `lib/`), start from the card in trial mode, then Settings, Update & backup, Install to flash
(`vendor.sqfs` made from the card's `lib/`); the hand-made `flashboot` kept working (same `initrd` size, kernel under
0x1ce000). The ISP sub picture (`ak39_vi.sub_channel`) became a compiled-in default from 3.0.1-rc2, so no
command-line change is needed any more; on IPCAM2 the command line had been extended by hand on 2026-10-29 for it.

