# WHEP / WebRTC gateway (item 35): design and steps

Goal: the web page (and any WHEP client) plays the camera's stream over WebRTC, with less than 150 ms of delay,
without go2rtc or MediaMTX, and without loading the processor (owner, 2026-11-05: "must not load the CPU much";
"measure the SRTP cost first").

## What WebRTC needs, and what the camera already has

| Piece | Work per packet | Source |
|---|---|---|
| RTP packets (H.264 / H.265 FU-A, PCMA) | none: `tc100_rtsp` already makes them for RTSP | `src/tc100rtsp` |
| SDP offer / answer (WHEP: one HTTP POST) | once per viewer | new, small text code |
| ICE-lite: answer the browser's STUN binding requests (HMAC-SHA1 + CRC32 fingerprint) | one every few seconds | new, ~200 lines |
| DTLS 1.2 handshake with the `use_srtp` extension, keys exported (RFC 5764) | once per viewer, ~0.5-2 s of CPU with ECDSA P-256 | mbedTLS 2.28.9, already in the user space (`ext/lib`, used by curl) |
| SRTP: AES-128-CM + HMAC-SHA1-80 on every packet | **the only per-packet cost** | `src/whep/srtp.h` (written, tested with RFC 3711 vectors) |
| Certificate (self-signed ECDSA P-256), its fingerprint in the SDP | made once, kept in `/mnt/config` | mbedTLS |

Only the H.264 stream plays in every browser over WebRTC; H.265 over WebRTC only in Safari and recent Chrome. The
secondary stream (H.264, 640x360) is the safe default for the live view; the main stream can be offered when it is
H.264.

## Steps

1. **Measure the SRTP cost** (done in code: `src/whep/srtp_bench.c`, `srtp-bench` in the CI test pack). The camera
   runs it during a normal stream; the result decides whether the main stream can be sent too, or only the
   secondary stream. Expected on the ARM926 at 480 MHz: about 10 MB/s, i.e. 1-2 % of the CPU for 1.2 Mbit/s.
2. **mbedTLS with DTLS-SRTP**: Buildroot's mbedTLS 2.28 is built without `MBEDTLS_SSL_DTLS_SRTP` (off in its
   default configuration). A patch in `v3/buildroot/board/tc100/patches/mbedtls/` switches it on (curl is not
   affected); the base image is rebuilt by the CI. No extra flash: the libraries are already there.
3. **`tc100-whep`, a daemon of its own** (not inside `tc100_rtsp`: a crash in the TLS code must not stop the video),
   built with the Buildroot musl toolchain in the base-rootfs workflow (so that it links the system's mbedTLS),
   about 40 KB:
   - WHEP endpoint `POST /whep` behind `httpfront` (same login as the web page), answer with the SDP;
   - one UDP port (ICE-lite, host candidates of the LAN only), STUN, DTLS, then SRTP;
   - the RTP comes from `tc100_rtsp` over its existing RTSP server on the loopback (`rtsp://127.0.0.1/...` with
     interleaved TCP): no change in `tc100_rtsp`, and the RTSP client limit protects the camera;
   - at most 2 viewers (`WHEP_MAX`), RTCP receiver reports read for the "viewer gone" timeout, PLI answered by
     nothing (the GOP is short; a keyframe request to `tc100_rtsp` can come later).
4. **The web page**: the live view tries WHEP first (`RTCPeerConnection`, about 60 lines), and falls back to the
   current MP4 live view. WHEP is enabled by default (`WHEP=1`); set `WHEP=0` in Settings or `boot.conf` to disable it.
5. **Tests**: host tests for the SDP, STUN (RFC 5769 vectors) and SRTP (done); a qemu test of the daemon against a
   WebRTC client in Python (`aiortc`) in the CI; then the camera: delay (clock in front of the camera), CPU, memory,
   one hour with two viewers.

## What it will cost

- Flash: the daemon (~40 KB) and the page code (~3 KB); mbedTLS is already there.
- Memory: one DTLS context per viewer (~30 KB) and the daemon (~150 KB PSS).
- CPU: the handshake once per viewer, then SRTP (step 1 measures it) and one copy of each packet.

## Implementation status (updated 2026-11-10)

Steps 2 to 5 are implemented. WHEP has been enabled by default since rc28: new configurations ship with `WHEP=1`,
missing keys default to on in the boot and Services paths, and setting `WHEP=0` explicitly disables it. The early
off-by-default state from the initial implementation is historical.

What exists, and the choices made where the design left them open:

- **Step 2, mbedTLS.** `v3/buildroot/external.mk` switches `MBEDTLS_SSL_DTLS_SRTP` on with a `sed` hook
  (`MBEDTLS_POST_PATCH_HOOKS`) instead of a patch file: it does not depend on the lines around the option, and the build
  stops if the option, DTLS, cookies, ECDSA / P-256, X.509 / PEM writing or key export are not in `config.h` afterwards
  (checked on 2.28.9: all are on in the default configuration except SRTP).
- **Step 3, `src/whep/tc100_whep.c` (+ `whep_proto.h`, `srtp.h`).** A Buildroot package (`v3/buildroot/package/tc100-whep`,
  local site `src/whep`) builds it with the musl toolchain against the system mbedTLS; it lands in `usr/bin` of the base
  image, `v3/build-stack.sh` copies it to `ext/bin` (optional: an older base has none), `initramfs-prune.txt` keeps it out
  of the RAM initrd. The base-image cache key includes `src/whep/**`.
  - HTTP: the daemon listens on **127.0.0.1:8889 only**; `www/cgi-bin/whep.cgi` forwards to it with curl, so the web login
    (httpfront + busybox httpd) protects it. The busybox httpd answers no `DELETE`: the page ends a viewer with
    `POST /cgi-bin/whep.cgi?stop=ID` (a `DELETE` to the same URL also works); the `Location` header is that URL.
    `GET /cgi-bin/whep.cgi` answers the daemon's status JSON, or `503 {"enabled":0}` when it is not running.
  - ICE-lite, one host candidate on `wlan0` (then `eth0`), UDP port 8189. The offer's candidates are ignored. STUN
    integrity and fingerprint are tested with the RFC 5769 vectors (`src/whep/whep_test.c`).
  - DTLS 1.2 server, one cipher suite (`ECDHE-ECDSA-AES128-GCM-SHA256`, so the exporter PRF is SHA-256 and is computed
    in the daemon: no dependence on mbedTLS internals), `use_srtp` SRTP_AES128_CM_HMAC_SHA1_80, the browser's certificate
    is checked against the fingerprint of the offer, no HelloVerifyRequest (the address is already proved by the STUN
    checks). Keys: RFC 5764 export from the master secret. The certificate (ECDSA P-256, self-signed) is made once in
    `/mnt/config/whep-cert.pem` and `whep-key.pem` (mode 0600), never in the source tree.
  - Media: one RTSP session per viewer to `tc100_rtsp` on the loopback (TCP interleaved, Basic authentication with the
    password of `config/user.pwd`), `/video1` (sub, default) or `/video0_unicast` (main, `WHEP_STREAM=main`, only if H.264:
    otherwise `415` and the page falls back). RTP packets are re-sent with the payload type and an SSRC of the answer and
    their own sequence numbers; SPS and PPS of the RTSP `sprop-parameter-sets` are put in front of every IDR. One SRTP
    context per stream (each has its own rollover counter). PCMA audio when the offer has it and `WHEP_AUDIO=1`.
    No RTCP sender reports (no lip-sync, picture first), PLI not answered.
  - At most `WHEP_MAX` (1-2) viewers; a viewer silent for 12 s (no STUN check, no SRTCP) is dropped; `429` beyond the limit.
  - `controlscripts/whep` starts it (service `whep`, switch `WHEP` in `boot.conf`, started by `autorun-linux66.sh` step
    12b like the other services); `WHEP_STREAM`, `WHEP_MAX`, `WHEP_AUDIO` are read at each start.
- **Step 4, page.** `src/webui/index/30-live-view.js`: the live view asks `cgi-bin/whep.cgi` (one small request, no statusline
  change), and when the gateway answers it makes a recvonly `RTCPeerConnection`, posts the offer without waiting for
  candidates and plays the stream in the same `<video>`. The gateway off: the MP4 live view at once, not asked again for
  10 minutes. Any failure (offer refused, no picture within 8 s, state `failed`, a picture frozen for 4 s): MP4 live view,
  WebRTC left alone for 1 minute (10 after a second failure in a row, 30 s after a drop while playing). Video only (the
  live view is muted).
- **Step 5, tests.** `tests/test_whep.py` (host vectors, wiring, `whep.cgi` under a shell with a stub curl),
  `tests/whep-live.test.js` (fallback logic), `tests/whep_interop.py` through `tests/docker/whep-interop.sh` (CI job
  `whep-interop`, `sh tests/docker/local-ci.sh whep`): builds mbedTLS 2.28.9 with SRTP, the daemon, and runs aiortc as the
  browser against a fake RTSP source (H.264 without SPS/PPS in the stream, PCMA, Basic authentication): a decoded 640x360
  frame, an audio frame, the viewer limit, DELETE.
- **Still to do, on the camera:** `srtp-bench` during a stream (decides sub or main), delay, CPU and memory with 1-2
  viewers, one hour; the Buildroot build of the package is only checked by CI (the host build uses the same sources and
  the same mbedTLS version).
