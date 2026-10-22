# jpegenc: JPEG on the hardware JPEG core of the AK3918EV300

The video encoder (Allegro DVT IP, registers at 0x20020000) has a JPEG engine that is driven
by registers, much simpler than the H.264 / H.265 path (which needs a DMA command list).
`jpegenc` programs it from user space, through the `ak39_venc` kernel driver (`/dev/uio0`),
with no vendor library. It is the first brick of a free encoder.

**Status: not run on hardware.** Everything that can be checked without the camera is:

| What | How it was checked |
|---|---|
| Quantisation tables for any quality | quality 35 reproduces the two DQT of a vendor 1920x1080 JPEG exactly |
| The 4 Huffman tables, in the hardware's 32-bit word format | identical, word for word, to the tables in the vendor library (`jpeg_hw_tables.py --check`) |
| Layout of the 0x800-byte table block | follows the decompiled `JpegTables_InitQuant` / `InitHuffman` / `preprocessEp1`; `check_tables_block.py` |
| The 11 control words (0x200283c0..e8) | first four, and the three size words, equal the recorded vendor frame |
| Register sequence (init, start, wait, read length, acknowledge) | copied from the recorded trace of the vendor encoder (JPEG frames) |
| JFIF header | the DQT, SOF0, DHT and SOS segments are identical to the vendor file (fallback only, see below) |

## How the core is driven

1. `build_tables()`: at the start of the stream buffer, a 0x800-byte block:
   - `0x000` luma quantisation table (zigzag order, bytes), `0x040` chroma;
   - `0x080` luma reciprocals, `0x100` chroma: 16 bit, `(0x10000 + q/2) / q - 1` at index zigzag[i];
   - `0x180` 14 constant words, `0x1b8` 4 constant words;
   - `0x1c8` AC luma (162 words), `0x450` DC luma (12), `0x480` AC chroma, `0x708` DC chroma;
   - `0x738` to `0x790` zeros (the rest of the block stays zero).
   Huffman word = `(len - 1) << 24 | code << 8 | next symbol`, AC index = run + 16 * (size - 1), EOB 161, ZRL 160.
2. Eleven control words at `0x200283c0`:

   | word | register | value |
   |---|---|---|
   | 0 | 0x3c0 | `0x130` (4:2:0) |
   | 1 | 0x3c4 | `(width - 1) << 16 \| (height - 1)` |
   | 2 | 0x3c8 | `0x00100009` (only seen at 1920x1080) |
   | 3 | 0x3cc | source stride in bytes |
   | 4, 5 | 0x3d0, 0x3d4 | physical address of the Y plane, of the interleaved UV plane (NV12) |
   | 6 | 0x3d8 | a 0x6400-byte work buffer |
   | 7 | 0x3dc | the stream buffer (0x7e900 bytes) that starts with the table block |
   | 8 | 0x3e0 | stream buffer size - 0x200 |
   | 9 | 0x3e4 | 0x800 (size of the table block: the stream is written after it) |
   | 10 | 0x3e8 | word 8 - 0x800 |
3. Interrupt mask `|= 0x40000`, clock register 0x2002c004 set to `(v & ~0x8000) | 0xe00`, `0x20028010 = 0x10000000`, control words, `0x20028084 = 0x10`, wait for the interrupt.
4. Read `0x200283f0..f8`: **0x3f4 is the length of the stream**, which in the vendor trace is a complete JPEG file (it starts with `FF D8`, SOS at offset 650): the core writes the header itself from the table block.
5. Acknowledge (`0x20028020 = 0x10001`) and restore the clock register.

## Use

```
make jpegenc.host          # host build, dry run only
./jpegenc.host --dry -q 35 frame.nv12 1920 1080 out.jpg   # writes out.jpg.tables and out.jpg.header, prints the words
python3 check_tables_block.py out.jpg.tables 35
make                       # for the camera (static ARM binary)
./jpegenc --run -q 35 frame.nv12 1920 1080 out.jpg        # on a TEST camera booted from RAM
```

`--run` writes the engine's registers. A mistake can hang the video block (the watchdog of a RAM test boot then
restarts the camera); it cannot touch the flash.

## What the camera has to answer

1. Does the core read the table block from the start of the stream buffer (reg 0x3dc)? The words and sizes say so; the 0x4040-byte buffer allocated at start-up by the vendor library is not referenced by any register.
2. What is the 0x6400 buffer of word 6, and does it need to be zeroed?
3. Is the initialisation sequence (`hw_init`) needed with the 6.6 driver, which resets the block on open?
4. Meaning of word 2 and of the status words 0x3f0 and 0x3f8 at other sizes.
5. Does the output start with `FF D8` and decode? Compare with a vendor JPEG at the same quality.

Tests: `python3 -m unittest tests.test_jpegenc` (tables, generated header, dry run).
