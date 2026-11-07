# H.265 on the AK3918EV300 encoder core: the command list

Work towards a free H.265 (and H.264) encoder for the TC100. The Allegro DVT core is driven by a
**command list in DMA memory**: 112 words (448 bytes) per picture, whose physical address goes to
register 0x20028080 (offset 0x8080 in the window at 0x20020000); writing 2 to 0x8084 starts it.
The vendor control software (`libakv_encode`) keeps two lists and alternates them (frame n even: A,
odd: B, 0x1c0 bytes apart). Everything here comes from the decompiled packing functions
(`SliceParamToCmdRegsEnc1/2`, `ReadStatusRegsEnc`) checked against hardware traces of the vendor
encoder at 1920x1080 (two traces, 40 + 34 H.265 pictures). **Nothing has run on the camera.**

| Words | Content |
|---|---|
| 0x00 - 0x1f | parameter registers (bit fields, `cmdlist.FIELDS`) |
| 0x20 - 0x3f | DMA addresses and pitches |
| 0x40 - 0x6f | status written by the core (statistics for the rate control) |

## Verified (against the recorded pictures)

- `cmdlist.py` rebuilds **all input words (0x00-0x3f) of every recorded list** from: the picture type,
  the QP chosen by the rate control, the source addresses and the buffer layout (`python3 cmdlist.py cmdlists.json`:
  "40 frames, 0 mismatching words"). The remaining 90 % of the parameters are constants of the profile
  (1920x1080, one slice, no B frames), kept in `PROFILE_1080P`.
- `hwseq.py` replays the register accesses between two pictures against the sequence of the vendor
  software: 34 of 34 (first trace) and 40 of 41 (second trace; the exception is the first picture, which includes the
  initialisation) cycles match exactly.

## What the recordings show

- **Picture type:** `sp_40` = 2 for an IDR, 1 for a P picture (HEVC slice_type); IDR also sets `sp_2d` = 0 and `sp_6c/6e` = 7
  (3 for P). The GOP of the recording is **32 pictures** (IDR at 0 and 32), no B pictures, one reference.
- **QP** is in word 3 bits 16-23 and again in word 0x1c bits 16-22; the rate control moved it 35 (IDR), 37, 38, ..., 20 over 40 pictures.
- **Picture order count** (2 per picture, reset at an IDR): words 0x0c (current), 0x0d and 0x0f (previous), 0x10 (the one before, 0xffffffff when none).
- **Words 0x20/0x21:** source Y and UV (NV12, pitch 0x780 = 1920 in word 0x22); the capture side rotates three buffers.
- **Words 0x24/0x25:** reconstructed picture Y/UV (pitch 0x1e00 in 0x26); **0x28/0x29:** reference Y/UV, 0 for an IDR.
- **Frame buffer:** 0x340000 bytes: Y at +0, UV at +0x1fe000, motion-vector info at +0x2fd000 (words 0x37 rec, 0x38 ref),
  co-located info at +0x300400 (words 0x2e rec, 0x2c ref). Two frame buffers alternate; an IDR reuses the previous one.
- **Word 0x23:** a 0x4040-byte table buffer; **0x27:** a 0x6400-byte work buffer; **0x2f:** 256 bytes.
- **Words 0x30-0x33 and 0x3c-0x3f:** the stream buffer: address, size - 0x200, offset 0x820 (reserved for what the core writes first),
  and size - 2 x 0x820.
- Register sequence per picture: see `hwseq.py` (note that 0xc004 gets `| 0x8e00` for H.265, whereas the JPEG path clears bit 15).

## Not known yet

- The meaning of most parameter bytes (`sp_xx` = offset in the vendor structure): they are constants here, and enough to repeat the recorded stream.
- **Where the size of the encoded picture comes from.** It is not in the status words; the 0x820 bytes at the start of the stream buffer (written by the core)
  are the likely place. A memory dump of the stream buffer after a picture is needed.
- The role of the 0x4040-byte table buffer (scaling lists / entropy tables?) and what must be in it.
- Rate control (the vendor chooses the QP), reference management for more than one reference, B pictures: the closed part of the library.
- The bitstream itself: the headers (VPS/SPS/PPS, slice header) come from software; Xilinx's MIT-licensed vcu-ctrl-sw has writers for them.

## Step 2 (2026-11-07): capture on Linux 6.6, then a first IDR without the vendor libraries

The owner's goal: no proprietary library left. The plan, on a test camera (IPCAM2):

1. **Capture** (`v3/dev/h265-step2.sh capture`): tc100_rtsp restarted by hand for 20 s with `AKUIO_CAPTURE` (libakuio
   writes, after each of the first 12 interrupts, the registers, the command list, the table / work / small buffers, the
   stream buffer and, once, the NV12 source of the first IDR) and `RTSP_SAVE_FRAMES` (the pictures the vendor returned).
2. **Analysis** (`python3 capture.py DIR --out DIR/in`): where the picture length is, whether the core writes the
   parameter sets and the slice header, whether the table buffer is constant, whether the lists of the 3.0 vendor
   library still follow `build_list`; writes the inputs of h265enc.
3. **First run** (`v3/dev/h265-step2.sh run`): `h265enc --run` encodes the same NV12 picture with the vendor's IDR list
   as a template (its own buffers, `patch_list` = the address words of `build_list`, tested), the core alone.
   Success = `o.h265` decodes, ideally byte for byte the vendor's `f.0.h26x`.
4. Then: P pictures (two frame buffers, the reference), our own VPS/SPS/PPS writer instead of the captured ones, our
   own table buffer if it is constant, a QP rate control; then h265enc becomes the encoder of tc100_rtsp and
   `libakv_encode`, `libmpi_venc_ex`, `libplat_*`, `libstdc++` and the uClibc runtime leave the camera.

## H.264, the 640x360 sub stream (2026-11-07)

The same core codes the sub stream in H.264 (Main profile, CABAC), with the same list layout. Found on IPCAM2:
- **Captures** (`v3/dev/h265-step2.sh capture` with `H265_WIDTH=640`: libakuio's `AKUIO_CAPTURE_WIDTH` keeps only the
  lists of a 640-wide picture): `slice_type_c` = 0 selects H.264, macroblock counts replace the CTB counts, the stream
  buffer is in list words 0x3c-0x3f only, `sp_8c` = 10 from QP 28 up (9 below), `sp_d8` changes with every picture
  (0 works). `cmdlist.PROFILE_H264_360P`, `H264_IDR_FIELDS`, `H264_P_FIELDS`; `listgen.h` has both codecs' lists.
- **Side buffers**: the work buffer holds only the 52 x 4 rate-distortion weights (`h264_work_table`, the vendor's
  bytes: tests WorkTable), the tables head is H.265's with byte 18 = 0x1f for an IDR.
- **Headers** (`avc.h`): SPS (VUI with a CBR VCL HRD), PPS, slice headers: the vendor's bytes (tests H264liveDry). The
  software writes them, the core writes the CABAC slice data from stream + 0x820 (length: list word 0x41).
- **Start**: the vendor's lists alone hang the core (state 0x20001 in 0x8300, no interrupt). `venctrace/` (the 3.0 port
  of the 2.x tracer, preloaded into tc100_rtsp by `h265-step2.sh trace`) showed the H.264 sequence: interrupt mask
  0x8014 bit 2 (H.265: bit 0), clock register 0xc004 bit 15 clear, list address + 0x8084 = 2 (load), list address
  again + 0x8084 = 8 (encode), mask cleared after the interrupt.
- **`h264live`** (`h265-step2.sh live264`): from the ISP sub channel (the 640x360 picture after the main one in each
  capture buffer), no vendor library or data: 150 pictures, IDR every 50, 0 decoding errors, 3.7 ms per picture on
  the core; `-b 250` gave 274 kbit/s (the QP alternates by 3 between pictures: the rate control's step is too big
  for 1 KB pictures, to tune).

## Use

```
python3 cmdlist.py cmdlists.json      # needs the recorded lists (vendor-derived data, not in git)
python3 hwseq.py trace.trc
python3 -m unittest tests.test_h265cmdlist
```

`TC100_H265_LISTS=<cmdlists.json>` and `TC100_H265_TRACE=<trace.trc>` make the tests replay recordings.
