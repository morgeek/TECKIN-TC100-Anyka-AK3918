# Hardware acceleration: what the AK3918EV300 does, what 3.0 uses (2026-10-29)

Measured on IPCAM2 (3.0.1-rc1, flash mode): the CPU is busy 84 to 100 %, `tc100_rtsp` alone about 76 %. The
hardware encoders are used; the CPU time goes into per-frame passes over the 3 MB picture that the ISP could do,
on a capture memory that the CPU reads uncached.

## The blocks and their use

| Block | Use in 3.0 | CPU work it could remove |
|---|---|---|
| Video encoder (H.264 / H.265) | yes: vendor libraries on the free `libakuio` | - |
| JPEG engine | yes: snapshots, stream.jpg, thumbnails (`jpeg_hw`) | - |
| ISP: demosaic, AE, AWB, noise filters, gamma, CCM | yes, from the camera's own tuning file (`isp.conf`) | - |
| ISP contrast / saturation / hue / Y gamma (`AK_ISP_SET_CONTRAST`, `_SAT`, `_HUE`, `_Y_GAMMA` on `/dev/isp_char`) | **no**: done by a table on every byte (`post_copy`) when Live image tuning is on | a 3 MB pass per frame |
| ISP white balance | yes, but `tc100_rtsp` adds a **software grey-world white balance** (on by default, `config/awb.off` turns it off) because of a colour cast: a chroma table on 1.5 MB per frame | a 1.5 MB pass per frame; the cast itself comes from the tuning file missing at start (dmesg: `Direct firmware load for anyka/isp.conf failed`) |
| ISP privacy masks (`AK_ISP_SET_MAIN_CHAN_MASK_AREA`, `_SUB_CHAN_MASK_AREA`, `_MASK_COLOR`) | **no**: painted by the CPU | small (only the masked areas) |
| ISP black and white (`AK_ISP_SET_YUV_EFFECT` or saturation 0) | **no**: `memset` of the chroma | 1 MB write per frame in B/W |
| ISP flip / mirror (`AK_ISP_SET_FLIP_MIRROR`) | **now**: `bin/isp_flip` (was missing, Settings orientation did nothing) | - |
| ISP sub channel (hardware scaler, 640x360 second output) | **yes** since 2026-10-29: `ak39_vi.sub_channel=1` on the kernel command line (stable since the 480 MHz clock fix), `tc100_rtsp` copies the ISP picture when the capture buffers hold it (`RTSP_HWSUB=0` falls back to `sub_scale`). IPCAM2: sub picture CPU time 1100 -> 460 ms per 5 s, same framing | was 345 600 scattered reads per frame |
| ISP 3D noise reduction | **no**: its reference buffers (2 x 3 MB) do not fit the CMA area, it is forced off | quality and bit rate, not CPU |
| ISP statistics (Y histogram, AE info) | **no**: the light level is a CPU sample of the picture | small |
| Capture DMA into cached memory (kernel patch 0012, `RTSP_CACHED=1`) | **new, to test** | every CPU read above becomes a cache-line fill instead of a bus access |
| Capture straight into the encoder pool (kernel patch 0011, `RTSP_ZEROCOPY=1`) | **new, to test** | the 3 MB copy itself |

## Order of work (quality kept, each step measured with `v3/dev/try-rtsp.sh`)

1. Load the tuning file before the first video start (no colour cast), then the software white balance can stay
   off (`config/awb.off`) with the same picture: removes the 1.5 MB chroma pass. Until then, `post_copy` now
   reads and writes 4 bytes at a time and skips identity tables (fewer bus accesses for the same result).
2. `RTSP_CACHED=1` (kernel with 0012): the copy and the sub picture read cached memory.
3. `RTSP_ZEROCOPY=1` (kernel with 0011): no copy at all; compare with 2.
4. Live image tuning, masks and black and white through `/dev/isp_char` instead of the CPU.
5. The ISP sub channel (hardware 640x360), once the variant B crash is understood.

## Measured on IPCAM2, 2026-10-29 (new flash layout, kernel with 0011/0012, H.265 1080p + H.264 sub, 1 client)

STAT per 5 s (5000 ms = one full core); cap = frames captured in 5 s (15 fps = 75).

| Mode | cap | pp_ms | sub_ms | enc_ms |
|---|---|---|---|---|
| copy, uncached capture (default) | 35-41 | 2240-2410 | 810-1070 | 1100-1270 |
| `RTSP_CACHED=1` | 36-42 | 1910-2310 | 710-870 | 1130-1340 |
| `RTSP_CACHED=1` + `config/awb.off` (no software white balance) | 40-52 | 1900-2070 | 320-600 | 1320-1650 |
| `RTSP_ZEROCOPY=1` | not possible: the driver keeps 4 capture slots (NUM_SLOTS), 4 x 3 MB of the 12 MiB pool; the fallback used to leave a 3 MB pool block taken and the encoder failed to open (fixed) | | | |

- Cached capture: about 10 % less per frame, same picture. Kept on IPCAM2 (`config/rtsp.env`).
- Without the software white balance, the cost per frame of the copy drops from about 54 to 36 ms (cap goes up
  from about 8 to 10 fps), but the colours then rely on the ISP alone: to be judged on the picture before
  making it the default.
- The camera stays CPU-bound (cap < 75): the next gains are the ISP doing the colour work and the sub picture
  (sections above), and a capture at the encoded frame rate only.

## Measured on IPCAM2, 2026-10-29 afternoon (ISP sub channel on, tuning file loaded at boot)

| Mode | cap / 5 s | pp per frame | sub per frame |
|---|---|---|---|
| ISP sub channel, byte-wise colour pass on the sub picture (in the uncached encoder buffer) | 42-46 | 48 ms | 10.5 ms |
| same + `config/awb.off` | 44-52 | 48 ms | 2 ms, but warm cast (mean B 10 % low) |
| ISP sub channel, colour pass applied while copying out of the capture buffer, 4 bytes per access (`post_sub_copy`) | 43-52 | 49 ms | 2.2 ms, neutral colours |

- The software white balance stays: with the tuning file loaded the ISP still leaves a warm cast (mean R/G/B
  103/98/91 without, 102/101/100 with). On the main picture it costs nothing extra: the chroma table is applied
  during the copy, which is limited by memory bandwidth (about 60 MB/s for 3 MB), not by the table.
- Sensor at 15 fps instead of 25 (`isp_fps 15`, `AK_ISP_SET_SENSOR_FPS`; vi interrupts 25/s -> 15/s): no change in
  CPU, copy time or captured frames. Left at 25.
- The stream gets about 10 fps of the 15 asked for, while the CPU is still 29 % idle: the loop copies a frame
  (49 ms), then waits for the hardware encoder (about 30 ms), one after the other. Overlapping the copy of frame
  N+1 with the encoding of frame N, or removing the copy (zero copy), is what brings the frame rate to 15.
- The Wi-Fi USB host raises about 480 interrupts/s (PIO, no DMA); system time is 16 %.

## No copy, white balance in the ISP (2026-10-29 evening, IPCAM2)

Three changes, now the defaults of `tc100_rtsp` (each can be turned off for comparison):

- **Direct capture** (`RTSP_DIRECT=0` turns it off): the encoder and the JPEG engine read the V4L2 capture buffer
  itself instead of a copy in the encoder pool. The kernel does not give the physical address of an mmap
  buffer (pagemap skips device mappings), so before STREAMON each buffer gets a marker at the start of each page,
  the RAM ranges of `/proc/iomem` are searched through `/dev/mem`, and only a buffer whose every page is found in
  order (physically contiguous) is used; `libakuio` then translates its addresses (`akuio_map_extra`). Anything
  missing: copy mode as before. In-place corrections (masks, clock, B/W, colour tables) are written back with a
  data cache clean of the rows they touched (ARM `cacheflush`), because the encoder reads memory, not the cache.
- **White balance in the ISP** (`RTSP_ISPAWB=0`: software tables): the grey-world measure steers the ISP's own
  extra red and blue gains (`AK_ISP_SET_AWB_EX`, `rgain_ex` / `bgain_ex` on top of the tuning file's values)
  instead of a table over the 1.5 MB of chroma. It converges in about 2 s (IPCAM2: red x 0.90, blue x 1.09, mean
  U/V within 1 of grey) and is frozen in black and white.
- **Frame rate kept**: the sensor gives 25 fps, the extra frames go straight back to the driver. Before, the
  loop never reached the configured rate, so there was no limit.
- Cached capture buffers are the default too (`RTSP_CACHED=0`: uncached).

| IPCAM2, 1080p H.265 1.6 Mbit/s, 1 client | before (morning) | now |
|---|---|---|
| frames per second | about 9.5 of 15 | 15 |
| main picture CPU time (pp_ms per 5 s) | about 2 150 | 3 |
| sub picture (sub_ms per 5 s) | about 1 100 | 1-2 |
| CPU: user / system / idle | 53 / 16 / 30 % | 8 / 39 / 50 % |

The system time that is left is mostly the Wi-Fi: the USB host runs without DMA (about 900 interrupts/s at 15 fps),
the next thing to look at.

## Where the system time went (2026-10-29, IPCAM2, two /proc/stat reads 60 s apart)

The 39-50 % of system time left after direct capture was not the Wi-Fi: per process, `tc100_rtsp` itself had
1 711 kernel ticks in 60 s (28 % of the CPU), the kworkers of the Wi-Fi about 5 %, soft interrupts about 3 %.
With cached (non-coherent) capture buffers the kernel invalidates the 3.4 MB buffer line by line at each queue,
for each of the sensor's 25 frames a second, including the 10 the server drops to keep 15.

| 15 fps, 1 client | cached, sensor 25 fps | uncached, sensor 15 fps (now the default) |
|---|---|---|
| user / system / idle | 12.6 / 49.9 / 34.8 % | 10.1-10.5 / 18.0-20.6 / 66-70 % |
| `tc100_rtsp` kernel ticks in 60 s | 1 711 | 610 |

The CPU reads almost nothing of the picture any more (statistics samples only), so cached buffers no longer pay
for themselves: they stay the default in copy mode only. USB DMA for the Wi-Fi would at best take a part of the
remaining 5-8 %.

## Live image tuning in the ISP (2026-10-29)

`AK_ISP_SET_YUV_EFFECT` / `_GET_` (`y_a`, `y_b`, `uv_a`, `uv_b`): measured on IPCAM2, `Y' = Y * y_a / 64 + y_b`
(y_a 68 -> 34 halved the mean luma 117 -> 57, y_b -2 -> 30 raised it to 149); the tuning file sets y_a 68,
y_b -2, uv_a 64. `tc100_rtsp` applies the Image page values on top of these (contrast around mid grey,
brightness 2 levels per step, saturation 2 % per step), live, and puts the base back when tuning is turned off.
With tuning on and the tables, IPCAM1 ran at 95 % CPU and IPCAM2 dropped to under 6 fps (in-place table over
uncached memory); with the ISP: 15 fps, pp 3 ms per 5 s.

## Hue and black and white in the ISP (2026-10-29 evening)

- `AK_ISP_GET_HUE` / `_SET_HUE`: a manual table and four tables by colour temperature (A, TL84, D50, D65), each
  65 sectors of (a, b) = 127 (cos, sin) and a saturation s (64 = 1). The tuning file switches some of them off
  (`en` 0, D65 on IPCAM2), which is why a first try changed nothing. `tc100_rtsp` turns every (a, b) by the hue
  angle and switches all tables on; HUE=0 puts the tuning file's tables back. Measured per pixel on IPCAM2:
  table +34.7 degrees, ISP +26.6 degrees for HUE=50 (30 asked); the ISP turns the other way, the sign is flipped.
- Black and white (night): `uv_a` = `uv_b` = 0 in `AK_ISP_SET_YUV_EFFECT`; snapshot chroma 0.00 (max 0.0).
- IPCAM1 had HUE=14 and SATURATION=-13: 79 % CPU in `tc100_rtsp` with the hue table, which is now gone.

## Out-of-memory kills with free memory: 4 MB page blocks (2026-10-30)

IPCAM2, 84 s after a start on rc4: `sh invoked oom-killer: order=2` (the 16 KB first-level page table of a new
process on ARM) with `Normal free:9696kB ... reserved_highatomic:8192KB`. `/proc/pagetypeinfo`: "Page block order
10" (4 MB), 16 blocks in all (4 unmovable, 6 movable, 1-2 high-atomic, 5 CMA). The high-atomic reserve (for the
Wi-Fi's order-2/3 atomic receive buffers) is counted in whole page blocks, so it took 4 to 8 MB, and the 115 free
16 KB blocks were in it or in CMA. `CONFIG_ARCH_FORCE_MAX_ORDER=7`: 512 KB blocks (128 of them), the reserve stays
near 1 MB and the migrate types are kept apart 8 times more finely. Nothing needs more than 512 KB from the page
allocator (capture buffers come from CMA, the encoder pool is reserved, large driver buffers are vmalloc).

Measured on IPCAM2 with the cb20c19 kernel booted once from the card: "Page block order: 7", 128 pages per block,
blocks 28 unmovable / 58 movable / 4 reclaimable / 2 high-atomic (1 MB) / 36 CMA; free 16 KB blocks outside the
reserve (buddyinfo `64 40 26 18 4 2 2 4`), MemAvailable 10.1-10.8 MB, no OOM or allocation failure after 4 min
(the old kernel failed at 84 s), video 74-76 frames per 5 s with a client, 69 % idle.

3.0.1-rc5 then installed in the flash of IPCAM2 with `update66.sh apply` (stack, kernel, initrd written and checked,
settings kept), normal flash start (no card kernel): "Page block order: 7", 2 high-atomic blocks, MemAvailable
10.7 MB, no OOM or allocation failure, 75 frames per 5 s with a client, 84 % idle.
