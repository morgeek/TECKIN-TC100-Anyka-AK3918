# T1 bench: is the encoder's "tables" buffer its QP control buffer? (2026-11-16)

Item T1 of [a-faire-implementeur.md](../a-faire-implementeur.md), hypothesis of the
[encoder review](encoder-2026-11-15-reponse.md). **A bench, not a product change:** `tc100_rtsp` is untouched and
nothing here runs unless the owner starts it. Nothing has run on a camera yet. Test-queue entry: `T1-QP-BENCH`.

## What is known, what is guessed
The free encoder gives the core a 0x4040-byte buffer (list word 0x23, `FE_TABLES_SIZE` in `src/h265enc/freeenc.h`).

**Known** (captures of the vendor encoder, 2026-11-07; the capture tools were removed 2026-11-25):
- only its first 20 bytes are not zero, the same for every picture: six 16-bit values 2500, 1000, 256, 5000, 7000,
  9000; six bytes 1, 3, 10, 1, 2, 3; byte 18 = 25 (31 for an H.264 IDR); byte 19 = 36 for an IDR, 48 for a P picture,
  whatever the QP of the picture. `freeenc.h` writes exactly these bytes (`FE_TABLES_HEAD`, bytes 18 / 19 per picture);
- the vendor leaves the other 16 KB at zero; the core does not need anything else in it to code a legal stream;
- the QP of a picture is in the list (word 3 bits 16-23, word 0x1c) and in the slice header, not in this buffer; the PPS
  has `cu_qp_delta` on.

**Matched against public code, not tried:** Allegro's control software (Xilinx `vcu-ctrl-sw`, MIT,
`include/lib_common_enc/EncBuffers.h` and `QPTable.h`) describes a buffer with the same shape: `QP_CTRL` at 0 (48 bytes,
"only 20 bytes used"), `SEG_CTRL` at 48 (16 bytes), `QP_BY_MB` at 64, one byte per block with bits 0-5 = QP,
bit 6 = forced intra, bit 7 = forced zero motion (skip). 20 used bytes and 64 + 0x4000 = 0x4040 fit the camera's buffer.

**Guessed:** that the 20 bytes are the settings of the core's own per-block QP adaptation (thresholds, QP steps,
lowest / highest block QP) rather than a clamp on the picture's QP; that the core reads the map at all in this
configuration (the control software has flags "this table is present", and the list may need a bit we never set); the
block size (32x32 = 2040 bytes at 1920x1080, or 16x16 = 8160), the order, and whether a map value is a difference or an
absolute QP. The bench answers these one at a time.

## The tool
`src/h265enc/qpbench.c` (+ `qpctl.h`), built by CI into the test pack (`tc100test/qpbench`, artifact
`tc100-linux66-cma16-kernel`) or by hand: `make -C src/h265enc CROSS=arm-linux-gnueabi- qpbench` (static).
It is `freeenc.h` itself (the code `tc100_rtsp` runs) at a fixed QP, with one change of the buffer per run:

```
qpbench [-c hevc|avc] [-q QP] [-n PICTURES_PER_PHASE] [-g GOP] [-s SKIP] [-F] -x EXPERIMENT OUTDIR
```
A run = three phases of `-n` pictures (default 50, GOP 25, QP 32, 1920x1080) on the same scene: `base1` (vendor's
values), `test` (vendor's values + the experiment), `base2` (vendor's values). Before **every** picture the whole buffer
is written again from the vendor's values. At the first failed picture (no interrupt, or an impossible length) the run
stops, the vendor's values are back and up to 3 pictures are tried with them. Exit status: 0 done; 3 failed in the test
phase, the core codes again; 4 failed in a baseline (not the experiment); 5 the core does not answer: **reboot**.

Output in `OUTDIR`: `base1.265`, `test.265`, `base2.265` (each starts with a keyframe; `.264` with `-c avc`), `run.csv`
(picture, phase, type, QP, bytes, ms on the core, then the 48 status words 0x40-0x6f of the list) and `summary.txt`
(mean sizes per phase and `CHANGED` / `no change beyond the scene's own`: the test phase against the two baselines).
`qpbench --dry -x EXPERIMENT` (any computer, `make -C src/h265enc qpbench-host`) prints the bytes an experiment changes.

## Procedure (test camera, owner nearby)
Keep the scene still and evenly lit (a run compares sizes); about 10 s per run, 2-3 MB of output.

1. Copy the program (RAM only): `ssh root@CAM 'cat > /tmp/qpbench && chmod +x /tmp/qpbench' < qpbench`, or with the SD
   test loop `pack66/send.sh qpbench tc100test/qpbench` (then `/mnt/tc100test/qpbench`).
2. Stop the video (it owns the ISP and the encoder; this also stops its restarter):
   `/mnt/controlscripts/rtsp-h26x stop`. No stream, snapshot, motion detection or recording until step 5.
3. One run per experiment, in the order below:
   `mkdir -p /tmp/qp/e1a && timeout 120 /tmp/qpbench -x min=45 /tmp/qp/e1a; echo "exit $?"`
   (or `ucmd.sh "..." 30`). Exit 5, or a run that `timeout` had to kill: stop here and reboot (step 5 does not apply).
4. Fetch and free the RAM: `ssh root@CAM 'tar c -C /tmp qp' | tar x`, then `rm -r /tmp/qp` on the camera.
5. Start the video again with the arguments of `v3/autorun-linux66.sh` (it goes through `rtsp-launch.sh` and puts the
   restarter back): `/mnt/controlscripts/rtsp-h26x start`, then check the stream in VLC.

On the PC:
```
cat e1a/summary.txt
ffprobe -v error -show_entries frame=pict_type,pkt_size -of csv=p=0 e1a/test.265      # sizes, as run.csv
ffmpeg -v error -i e1a/test.265 -f null -                                             # must print nothing (legal stream)
ffmpeg -v error -i e1a/base1.265 -vf "select=eq(n\,30)" -frames:v 1 e1a-base.png      # the same picture number
ffmpeg -v error -i e1a/test.265  -vf "select=eq(n\,30)" -frames:v 1 e1a-test.png      # of both, side by side
```
ffmpeg does not show the QP of each block of an H.265 stream; sizes, the pictures and the status columns of `run.csv`
(a column that follows the experiment is probably a QP sum or a skip / intra count: review item T2) are the evidence.

## Experiments, most information per run first
| # | Command (`-x ...`) | Shows | Confirms | Refutes / next |
|---|---|---|---|---|
| E0 | `ctl`; then `ctl -F -g 1` | the bench itself and how much two phases differ on this scene; `-F` (frozen source, all keyframes): do sizes repeat exactly? | exit 0, `no change`; if `-F` works, add `-F -g 1` to the keyframe comparisons below | a failure here: stop, the bench is wrong, not the hypothesis |
| E1a | `min=45` | is byte 18 a lowest block QP? (QP 32 forced up to 45) | sizes fall to a third or less | no change: not a bound of the picture QP, go on with E2 |
| E1b | `max=28` with `-q 40` | is byte 19 a highest block QP? | sizes rise 3x or more | no change: as E1a |
| E1c | `ctl -q 51`, `ctl -q 48`; `ctl -q 20`, `ctl -q 25` | the review's claim "the core clamps to 25-48 whatever we ask" (no buffer change) | 51 = 48 and 20 = 25 in size | sizes differ: no clamp on the picture QP; the bytes then only bound the core's own adaptation |
| E2 | `dq=0` | is the core adapting the QP per block by itself (the six steps)? | sizes move (either way), sharper or flatter detail in the PNGs | no change: the adaptation is off or these bytes are something else |
| E3 | `map=+10` | is the map read at all? | P and IDR about 3x smaller = read as a difference; several times bigger = read as an absolute QP 10 | no change: the map is not read as things are, E4 then E6 |
| E4 | `map=intra`, then `map=skip` (move a hand in front of the lens) | the two flag bits | `intra`: P pictures as big as keyframes; `skip`: P pictures of a few bytes and a frozen picture between keyframes | no change with E3 also negative: E6 |
| E5 | `map=+15,top`, then `map=skip,left` | **the proof of a per-block map** and its geometry | the top half visibly coarser, the bottom untouched (or the left half frozen) | a boundary elsewhere, or stripes: other block size / order: `map=+15,first=1020`, `first=4080`, `...,top,blk=16`, `unit=2` until the boundary sits at half height |
| E6 | `--multi -x map=+10 -x list@WORD:MASK=VALUE` | only if E3-E4 show nothing: the list bit that says "the map is there" | a `CHANGED` run | the riskiest runs (an unknown bit can hang the core): one bit per run, candidates = one-bit fields that are 0 in `cmdlist.PROFILE_1080P`; better first, at the desk: match the vendor's `sp_xx` fields with `AL_TEncSliceParam` of `vcu-ctrl-sw` |

Read E1-E2 together: "E1 changes, E2 does not" = plain bounds; "E2 changes" = the core already varies the QP per block
with the vendor's thresholds, and the map is the same mechanism under our control. A confirmed E5 opens the product
work (static blocks skipped at night from the motion grid, region of interest, background QP +N), which is another
change with its own switch and test-queue entry, never a default before 24 h on both cameras.

## Risk
- A wrong value can hang the core: the picture then takes 2 s (kernel timeout), the bench stops and restores, and if the
  core stays silent (exit 5) only a reboot brings it back; `tc100_rtsp` started on a hung core fails in a loop until its
  watchdog reboots. Nothing touches the flash, the settings or U-Boot: after a reboot the camera is as before.
- Values that make pictures bigger (`max=`, `map=` read as absolute QP, `intra`) can exceed the 518 KB stream buffer: the
  bench counts that as a failed picture and stops. Stay at or above 25 for `min` / `max` until E1 is understood.
- While the bench runs the camera is blind (no stream, no recording); the output is in RAM (`/tmp`), remove it.
