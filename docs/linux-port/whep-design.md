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
   current MP4 live view; a switch in Settings (`WHEP=0|1`, off by default until tested).
5. **Tests**: host tests for the SDP, STUN (RFC 5769 vectors) and SRTP (done); a qemu test of the daemon against a
   WebRTC client in Python (`aiortc`) in the CI; then the camera: delay (clock in front of the camera), CPU, memory,
   one hour with two viewers.

## What it will cost

- Flash: the daemon (~40 KB) and the page code (~3 KB); mbedTLS is already there.
- Memory: one DTLS context per viewer (~30 KB) and the daemon (~150 KB PSS).
- CPU: the handshake once per viewer, then SRTP (step 1 measures it) and one copy of each packet.
