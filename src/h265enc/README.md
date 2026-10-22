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

## Use

```
python3 cmdlist.py cmdlists.json      # needs the recorded lists (vendor-derived data, not in git)
python3 hwseq.py trace.trc
python3 -m unittest tests.test_h265cmdlist
```

`TC100_H265_LISTS=<cmdlists.json>` and `TC100_H265_TRACE=<trace.trc>` make the tests replay recordings.
