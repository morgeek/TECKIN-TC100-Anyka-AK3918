# Free encoder review (Fable 5.2, read-only, 2026-11-15)
Asked by the owner. Inputs: the field facts of 2026-11-14 (1080p H.265 25 fps GOP 50, ceiling 1600 kbit/s, QP 25-48,
`enc_ms` ~30 ms / frame, CPU 20-30 %, VBR at ~64 kbit per picture, `RTSP_VBR_QP` default 33 since b798b11). Nothing run.
The project crash notes on claude.ai (`h265-crash-akmci`, `h265-repeat-runs`) were not readable from the reviewer's side.

## enc_ms
Wall-clock time around `p_send()` for main + sub (`tc100_rtsp.c:4533-4535`), almost all of it asleep in the
`AKUIO_WAIT_IRQ` ioctl (`freeenc.h:294`, `libakuio.c:661`, patch 0008) while the core encodes; software per picture is a
448-byte list, a < 64-byte header and ~30 register accesses. **30 ms = hardware time, not CPU.** The single-threaded loop
is blocked ~75 % of the 40 ms period: ~10 ms of headroom at 25 fps.

## Rate control
- **R1 (verified): the per-picture budget ignores the real frame rate.** `rc_init` sets `budget = kbps*1000/8/fps` from the
  configured fps (`rc.h:50`), `fe_set_kbps` reuses `e->fps` (`freeenc.h:162`); nothing tells the encoder about the 10 fps
  night set (`cap_fps_now`, `tc100_rtsp.c:1123`) or the idle rate (`:4372`). That is the measured 64 kbit / picture
  (647 kbit/s at 10 fps): at night the ceiling is effectively 40 %. The GOP counts frames (50 = 5 s at 10 fps). Fix:
  `fe_set_fps(e, fps)` (`budget = kbps*125/fps`) called where the capture rate changes; RC_SPREAD / RC_VBR_CREDIT and the
  GOP in time. Gain: up to 1600 kbit/s at night when the scene needs it (~4-5 QP lower). Risk low.
- **R2 (logic verified, trigger inferred): an oversized picture fails forever.** `freeenc.h:328`: length over the buffer
  -> `force_idr`, return -1, no `rc_done`: the next IDR uses the same QP and fails again; the main stream has no
  escalation (`tc100_rtsp.c:4537` handles the sub only). Buffers 518 KB (1080p) and 57 KB (640x360) (`freeenc.h:116,122`);
  whether the core stops at the given size is unknown (else it overwrites the tables / work buffers placed after it).
  Fix: on overflow QP +6 and the limit into the RC; 128 KB sub buffer; IDR QP capped from the last IDR size so an IDR
  stays under ~0.4 s of the ceiling (~80 KB at 1600 kbit/s). Measure: `RTSP_DEBUG` FRAME lines (`:4567`), `fails`.
- **R3 (verified): the smart-mode QP floor does nothing with RTSP_VBR_QP=33** (floor `qmin + 4` = 29, `freeenc.h:203`;
  `rc_base` already >= 33, `rc.h:90-93`). In a still scene the IDR sets the quality of the whole long GOP: code it 4-5 QP
  below the P QP (`RC_IDR_OFFSET`, now 2), under the R2 cap. Measure: still-scene kbit/s and IDR size.
- **R4 (verified, moderate): QP pumping when the ceiling binds:** QP moves on one P size, up to +-3 per picture
  (`rc.h:128-131`), +-30 % dead band from the integer division; after a big IDR the aim drops to `budget/4` (`:127`):
  breathing at the GOP period in CBR. Fix: smooth over 3-4 P sizes, +2 up / -1 down per picture, IDR excess paid back over
  the GOP. Risk: ~1 s over the ceiling on sudden motion.
- **R5: VBR with QP 33 is otherwise sound** (no wind-up: `rc_done` restarts from the coded QP; credit <= 1 s, worst ~2x
  the ceiling for ~1 s). Expected still day scene ~200 kbit/s (IDR 40-60 KB every 2 s + small P).

## Coding tools
On (`paramsets.h:1-9`, `slicehdr.h`): CTB 32, 1 reference, no B, deblocking (offsets -1), default scaling lists, TMVP,
`cu_qp_delta`. Off: SAO, AMP, sign hiding, transform skip; one slice.
- **T1 (inferred, highest potential): the 0x4040 "tables" buffer looks like the Allegro QP-control buffer** (64-byte
  header + 1 byte per block). Head (`freeenc.h:80`): six 16-bit thresholds (2500, 1000, 256, 5000, 7000, 9000), six small
  QP deltas, then bytes 18 / 19 = 25 / 48 for P and 25 / 36 for IDR (`:324-325`): the QP range. If confirmed (Xilinx
  `vcu-ctrl-sw`): the hardware clamp is hard-coded 25-48 (36 for IDR) and ignores `minqp` / `maxqp`; the 16 KB after it is
  a per-block QP delta map (and force-intra / force-skip flags in Allegro): ROI, background QP +N from the motion grid,
  forced skip of static noisy blocks at night, rolling intra refresh without I bursts. Potential 20-40 % on busy / noisy
  scenes. Bench only (`h265live`), behind a switch: `-q 49..51` vs 48 (same size = clamped), `ffmpeg -debug qp` for block
  QP variation, then a nonzero map.
- **T2:** status words 0x40-0x6f unused (only 0x40 / 0x41 read): likely intra / skip counts and a QP sum, a free
  scene-change / motion signal. Dump 50 pictures first.
- **T3:** skip detection: measure a covered-lens 1080p P picture (should be < 1-2 KB; >= 5 KB = noise coded -> T1 or 3D-NR).
- **T4 not worth it:** SAO / AMP (a few %, unknown list bits, more encode time with 10 ms spare), multiple slices, motion
  search range, flat scaling lists.

## Reliability
- **L1 (verified):** a hung core blocks the capture loop 2 s per picture (kernel wait timeout, then `fe_hw_init` + IDR);
  a soft reset does not free a core hung by a stale status (README); no escalation for the main stream. Fix: after 5
  consecutive failures close / reopen the encoder, after M exit so the supervisor restarts the service; log once.
- **L2 (inferred):** after a failure `cur` is not toggled, so the forced IDR goes to the buffer the failed picture used;
  `freeenc.h:104-106` says an IDR into the last-written buffer hung the core on IPCAM2 while the README says the vendor
  does it: contradictory; toggling `cur` on failure is free (an IDR needs no reference).
- **L3:** end status not checked (`fe_run` tests `res < 0` only, `:303`); 0x8018 / 0x801c and list word 0x40 stored but
  unused: log them when abnormal.
- **L4 (verified correct):** write-combined pool (no flush for list / headers), `dm_clean` (`:1497`) over dirty rows only,
  output copied once before the next encode (`:4547-4552`); with `RTSP_FRAMECOPY=0` the data is only valid until the next
  `fe_encode` (the GOP cache must not keep it). **L5:** soft reset pulse 1-2 ms (patch 0008), no issue. **L6:** signals fine.

## CPU / latency
The encoder path costs almost no CPU; the cost is serialisation (main 30 ms + sub ~4 ms + JPEG in one thread). Cheap wins:
serve audio / clients during the wait (split start / collect, or the wait in a small thread); skip sub / JPEG work with no
consumer (partly done). Check whether 30 ms is expected at ASIC 120 MHz (the clock bits written to 0xc004, `freeenc.h:281`,
may include a divider): read-only first, no change without a bench soak.

## Other
SPS VUI says 25 fps while night runs at 10 (check MP4 durations); the H.264 SPS declares a CBR HRD at the configured rate
even in VBR (harmless). POC / frame_num limits handled (`FE_SMART_GOP_MAX`, `freeenc.h:169`).

## Top 5 by value / effort
1. R1 real frame rate into the budget and the GOP in time (a few lines, fixes the night under-use).
2. R2 overflow loop, 128 KB sub buffer, IDR size cap (small, removes a permanent-failure path, bounds Wi-Fi bursts).
3. R3 in the still state a larger IDR offset instead of the dead floor (small, best still-scene quality per bit).
4. T1 bench-check of the tables buffer (QP min / max bytes, then the per-block map): half a day, largest potential.
5. L1 + L2 failure escalation and `cur` toggle (small, a hung core becomes a short interruption).
