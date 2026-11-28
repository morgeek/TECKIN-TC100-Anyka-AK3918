# Native Low-CPU HTTPS (`tc100-httpsd`) — Branch `upgrade-3.2.1`

`3.2.1-rc1` adds an embedded TLS 1.2+ reverse proxy (`src/httpsd/tc100_httpsd.c`, binary `/mnt/ext/bin/tc100-httpsd` on port `443` forwarding to `httpfront` on `127.0.0.1:80`) tuned specifically for the AK3918EV300 ARM926EJ-S core (480 MHz, no AES/PMULL instructions, ~38–42 MB usable RAM while `tc100_rtsp` runs).

## Why CPU stays low
- **Single-process non-blocking `poll()` loop:** zero per-connection heap allocations (`malloc`/`calloc`/`realloc` never called in connection slots), capped at `HTTPS_MAX_CONNS=4` (`<= 8`) and at most `2` concurrent TLS handshakes (`HTTPSD_MAX_HS=2`), plus `nice(+5)` so video/audio capture (`tc100_rtsp`) is never preempted.
- **ChaCha20-Poly1305 & X25519 first:** Mbed TLS 3.6.7 prefers `TLS-ECDHE-ECDSA-WITH-CHACHA20-POLY1305-SHA256` over AES-128-GCM and X25519 over P-256 — ARX software throughput on ARM9 is ~3–5× faster than software AES-GCM table lookups.
- **One TLS handshake per browser tab:**
  - HTTP/1.1 `Connection: keep-alive` (`timeout=30, max=100`), automatically wrapping HTTP/1.0 CGI responses that omit `Content-Length` into HTTP/1.1 `Transfer-Encoding: chunked` streams (`HTTPSD_BODY_CHUNKED_OUT`) so polling endpoints never force connection teardown + re-handshake.
  - TLS session tickets (RFC 5077, 24 h key) + 32-entry server session cache (1 h) skip ECDHE scalar multiplication on reconnects.
- **Persistent ECDSA P-256 certificate:** generated once in `/mnt/config/https-cert.pem` (`0644`) and `/mnt/config/https-key.pem` (`0600`) with SubjectAltName (`tc100`, `tc100.local`, camera hostname, and LAN IPv4).
- **Privilege separation:** reads `/mnt/config/https-key.pem` and binds port `443` as root, then drops privileges via `privdrop_opt net` (`tc100net`, `1002:1002`), never touching config secrets afterward (`secret-modes.sh` keeps `https-key.pem` `0600 root:root`). Honours `TC100_NET_ALLOW` and `WEB_LOCKOUT`.

## Configuration & Certificate Download
- `/mnt/config/boot.conf`:
  - `HTTPS=1` (default; set `HTTPS=0` to disable)
  - `HTTPS_PORT=443`
  - Optional: `HTTPS_MAX_CONNS=4`, `HTTPS_NICE=5`
- Download the camera's public certificate for your browser or Home Assistant from **Diagnostics → HTTPS Cert (.pem)** (`cgi-bin/httpscert.cgi`, serves `/mnt/config/https-cert.pem` only).

## Camera Verification Plan
1. Boot `3.2.1-rc1` (SD or flash) and verify `/mnt/config/https-cert.pem` (0644) and `https-key.pem` (0600) are created once, and `ps` shows `tc100-httpsd` running as `tc100net` (`1002`).
2. Open `https://<camera-ip>/` and keep Live View + Status polling open for 5 minutes while recording `tc100_rtsp` H.265/H.264 stream.
3. Verify: `top` / `scripts/cpu-profile.sh 60` shows low CPU overhead and 0 RTSP frame drops / 3D-NR overflows.
4. Download `httpscert.cgi` from Diagnostics and verify only `https-cert.pem` is served.
