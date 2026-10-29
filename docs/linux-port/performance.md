# Performance: how it is measured

Every optimisation is measured on a camera before it is kept, and stays behind a switch until it is proven.

## Tools

- `scripts/cpu-profile.sh [seconds] [threads]`: CPU per process or thread, from `/proc` (pure shell). On the camera:
  `http://<camera>/cgi-bin/cpuprofile.cgi?sec=10&threads=1`.
- The `STAT` line of `tc100_rtsp`, every 5 s in `/tmp/logs/tc100_rtsp.log`: frames captured and encoded, bytes,
  `enc_ms` (hardware encoder calls), `snd_ms` (network), `pp_ms` (main picture: copy, colour tables, overlay, black and
  white), `sub_ms` (640x360 sub picture). Milliseconds spent in each step over the last 5 s: 5000 is one full core.
- `v3/dev/try-rtsp.sh CAMERA BINARY [VAR=value]`: from a computer, runs a test build of `tc100_rtsp` in RAM with
  the arguments of the running one, prints the STAT lines and two CPU profiles (before / with the test build), then
  restarts the normal server. Nothing is written to the flash.

## Order

1. **Baseline**: `try-rtsp.sh <camera> src/tc100rtsp/tc100_rtsp` with the current build. Tells whether `pp_ms` (the
   3 MB copy of each frame from uncached capture memory) is the main cost.
2. **Zero copy**: same with `RTSP_ZEROCOPY=1`. Needs the kernel with patch 0011 (USERPTR capture); with an older
   kernel the log says `capture: copy` and nothing changes. The ISP then writes straight into the encoder pool;
   it uses about 3 MB more of the 12 MiB pool (watch `ak_venc_open failed` with H.265).
3. **Sub picture**: `sub_scale` reads one pixel in three since 2026-10-28 (b0907a0); `sub_ms` shows the gain.
4. **Memory**: 3D-NR reference buffers (CMA), the encoder pool size, `MemAvailable` during a long run.

Results go to `docs/linux-port/` with the date, the camera, the build and the numbers.
